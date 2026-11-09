import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.clang import Clang
from configsys.runner import Runner

from fakes import FakeRunner


@pytest.fixture(autouse=True)
def _force_apt(monkeypatch):
    # these tests assert the apt path; pin the PM so they're host-independent
    monkeypatch.setenv('CONFIGSYS_PM', 'apt')


def clang_unit(comp='clang-18', fields=None):
    return ResolvedComponent(key=f'clang\\{comp}', driver='clang', comp=comp,
                             fields=fields or {})


def test_registered_system_scoped():
    fam = get_driver('clang', Runner(pretend=True))
    assert isinstance(fam, Clang) and is_supported('clang')
    assert fam.privileged and fam.default_scope == 'system' and not fam.honors_scope


def test_defaults_from_bare_component():
    # `clang-18: {}` in routes — version, link, slaves, packages all derived.
    fam = Clang(Runner(pretend=True))
    rc = clang_unit()
    assert fam._link(rc) == 'clang' and fam._ver(rc) == '18'
    assert fam._slaves(rc) == ['clang++']               # driver default
    assert fam._packages(rc) == ['clang-18']            # clang++ is NOT a package


def test_install_adds_llvm_repo_installs_and_registers_alternative():
    r = Runner(pretend=True)
    Clang(r).install(clang_unit())
    cmd = r.calls[0]
    assert cmd.startswith('sudo ')                       # whole script under root
    assert ('CODENAME="$(. /etc/os-release; echo "${UBUNTU_CODENAME:-${DEBIAN_CODENAME:-$VERSION_CODENAME}}")"'
            in cmd)                                   # derivative-safe (B7; LMDE's own codename too)
    assert "if ! apt-get update; then rm -f" in cmd                         # a broken source is rolled back
    assert 'apt.llvm.org/llvm-snapshot.gpg.key' in cmd
    # the deb line is quoted with only "$CODENAME" left to expand in-shell (injection-safe)
    assert 'apt.llvm.org/' in cmd and 'llvm-toolchain-' in cmd and '-18 main' in cmd
    assert '"$CODENAME"' in cmd
    assert 'apt-get install -y clang-18' in cmd          # only clang, not clang++
    assert ('update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 18 '
            '--slave /usr/bin/clang++ clang++ /usr/bin/clang++-18') in cmd


def test_repo_uses_version_specific_list_and_key_paths():
    r = Runner(pretend=True)
    Clang(r).install(clang_unit('clang-19'))
    cmd = r.calls[0]
    assert '/etc/apt/sources.list.d/clang-19.list' in cmd
    assert 'llvm-toolchain-' in cmd and '-19 main' in cmd


def test_vendor_key_is_a_per_source_keyring_named_by_signed_by():
    # drivers-lang-03 (d): the key goes in its OWN keyring, trusted only for the source that names it
    # with signed-by= — never the global trusted.gpg.d, where it would vouch for every repo
    r = Runner(pretend=True)
    Clang(r).install(clang_unit('clang-19'))
    cmd = r.calls[0]
    assert "tee /etc/apt/keyrings/clang-19.asc" in cmd
    assert "'deb [signed-by=/etc/apt/keyrings/clang-19.asc] http://apt.llvm.org/'" in cmd
    assert 'tee /etc/apt/trusted.gpg.d/' not in cmd
    assert 'mkdir -p /etc/apt/keyrings' in cmd                  # absent before Debian 12 / Ubuntu 22.04
    # an older configsys's global key goes once no list of ours still relies on it (no signed-by)
    assert 'rm -f /etc/apt/trusted.gpg.d/clang.asc' in cmd
    # a route's own [options] keep their place, signed-by joins them; one it already set is kept
    rc = clang_unit('clang-19', {'apt-source': {'key': 'https://k', 'deb': '[arch=amd64] http://x/ y main'}})
    assert "'deb [arch=amd64 signed-by=/etc/apt/keyrings/clang-19.asc] http://x/ y main'" in \
        '\n'.join(Clang(Runner(pretend=True))._repo_lines(rc))
    rc = clang_unit('clang-19', {'apt-source': {'key': 'https://k', 'deb': '[signed-by=/usr/share/keyrings/x.gpg] http://x/ y main'}})
    assert "'deb [signed-by=/usr/share/keyrings/x.gpg] http://x/ y main'" in \
        '\n'.join(Clang(Runner(pretend=True))._repo_lines(rc))


def test_uninstall_removes_alternative_then_package():
    r = Runner(pretend=True)
    Clang(r).uninstall(clang_unit())
    cmd = r.calls[0]
    assert 'update-alternatives --remove clang /usr/bin/clang-18' in cmd
    assert 'apt-get remove -y clang-18' in cmd


def test_uninstall_takes_back_the_vendor_source_and_its_keyring():
    r = Runner(pretend=True)
    Clang(r).uninstall(clang_unit('clang-19'))
    cmd = r.calls[0]
    assert cmd.index('apt-get remove -y clang-19') < cmd.index('rm -f /etc/apt/sources.list.d/clang-19.list')
    # the keyring only when no other source still names it
    assert ('grep -rqsF /etc/apt/keyrings/clang-19.asc /etc/apt/sources.list.d/ || '
            'rm -f /etc/apt/keyrings/clang-19.asc') in cmd


def test_get_version_parses_compiler_output():
    fr = FakeRunner([('/usr/bin/clang-18 --version', 0,
                      'Ubuntu clang version 18.1.8 (++20240731...)\nTarget: x86_64\n')])
    assert Clang(fr).get_version(clang_unit()) == '18.1.8'


def test_switching_is_not_configsys_and_no_latest():
    fam = Clang(Runner(pretend=True))
    assert fam.lock(clang_unit()).ok and fam.unlock(clang_unit()).ok   # no-ops
    assert fam.is_locked(clang_unit()) is False
    assert fam.get_latest(clang_unit()) is None
    assert fam.location(clang_unit()) == '/usr/bin/clang-18'


def _run_repo_lines(tmp_path, madison_out, list_exists, setup=None):
    '''Execute the driver's generated repo logic in bash with stub apt-cache/apt-get/curl, against a
    list file (and the apt list/legacy key dirs) in tmp. Returns (list file exists after, log of stub
    calls).'''
    import subprocess
    stub = tmp_path / 'bin'
    stub.mkdir()
    log = tmp_path / 'log'
    (tmp_path / 'madison').write_text(madison_out)
    (stub / 'apt-cache').write_text(f'#!/bin/sh\ncat {tmp_path / "madison"}\n')
    for name in ('apt-get', 'curl'):
        (stub / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\n')
    for f in stub.iterdir():
        f.chmod(0o755)
    lst = tmp_path / 'clang-20.list'
    if list_exists:
        lst.write_text('deb http://apt.llvm.org/noble/ llvm-toolchain-noble-20 main\n')
    rc = clang_unit('clang-20', {'apt-source': {
        'key': 'https://apt.llvm.org/llvm-snapshot.gpg.key', 'key-path': str(tmp_path / 'k.asc'),
        'deb': 'http://apt.llvm.org/$CODENAME/ llvm-toolchain-$CODENAME-20 main', 'list': str(lst)}})
    drv = Clang(Runner(pretend=True))
    drv.apt_lists_dir, drv.legacy_key_dir = str(tmp_path), str(tmp_path / 'trusted.gpg.d')
    if setup:
        setup(tmp_path)
    script = '\n'.join(['set -e'] + drv._repo_lines(rc))
    subprocess.run(['bash', '-c', script], check=True, env={'PATH': f'{stub}:/usr/bin:/bin'})
    return lst.exists(), (log.read_text() if log.exists() else '')


def test_distro_carrying_the_package_skips_and_drops_the_vendor_repo(tmp_path):
    # Ubuntu 24.04 ships clang-20; adding apt.llvm.org then mixes its clang-20 with the distro's
    # libllvm20 -> "held broken packages" on Pop!_OS. Use the distro's; remove a leftover OUR list.
    madison = (' clang-20 | 1:20.1.8~++2025 | http://apt.llvm.org/noble llvm-toolchain-noble-20/main amd64 Packages\n'
               ' clang-20 | 1:20.1.2-0ubuntu1~24.04.3 | http://archive.ubuntu.com/ubuntu noble-updates/universe amd64 Packages\n')
    exists, log = _run_repo_lines(tmp_path, madison, list_exists=True)
    assert not exists and 'apt-get update' in log and 'curl' not in log


def test_distro_without_the_package_adds_the_vendor_repo(tmp_path):
    exists, log = _run_repo_lines(tmp_path, '', list_exists=False)
    assert exists and 'curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key' in log


def test_legacy_global_key_goes_once_no_list_of_ours_needs_it(tmp_path):
    def legacy(d, unsigned):
        (d / 'trusted.gpg.d').mkdir()
        (d / 'trusted.gpg.d' / 'clang.asc').write_text('KEY')
        if unsigned:   # an older configsys's clang-18 list, still relying on the global key
            (d / 'clang-18.list').write_text('deb http://apt.llvm.org/noble/ llvm-toolchain-noble-18 main\n')
    _run_repo_lines(tmp_path, '', list_exists=False, setup=lambda d: legacy(d, False))
    assert not (tmp_path / 'trusted.gpg.d' / 'clang.asc').exists()
    assert 'signed-by=' in (tmp_path / 'clang-20.list').read_text()
    other = tmp_path / 'other'
    other.mkdir()
    _run_repo_lines(other, '', list_exists=False, setup=lambda d: legacy(d, True))
    assert (other / 'trusted.gpg.d' / 'clang.asc').exists()                # still needed: kept


def test_a_ppa_is_only_added_on_ubuntu_and_only_when_the_distro_lacks_the_package():
    # review-2026-11-2 B7: a Launchpad PPA on Debian 404s and poisons apt
    from configsys.componentObj import ResolvedComponent
    from configsys.drivers.gcc import Gcc
    r = Runner(pretend=True)
    Gcc(r).install(ResolvedComponent(key='gcc\\gcc-13', driver='gcc', comp='gcc-13',
                                     fields={'packages': ['gcc-13', 'g++-13'], 'ppa': 'ubuntu-toolchain-r/test'}))
    cmd = r.calls[0]
    assert 'grep -q "^UBUNTU_CODENAME=" /etc/os-release' in cmd and 'Ubuntu-only' in cmd
    assert cmd.index('apt-cache madison') < cmd.index('add-apt-repository')


@pytest.mark.parametrize('os_release,want', [
    ('VERSION_CODENAME=faye\nDEBIAN_CODENAME=bookworm\n', 'bookworm'),   # LMDE: its own codename
    ('VERSION_CODENAME=wilma\nUBUNTU_CODENAME=noble\n', 'noble'),        # Mint
    ('VERSION_CODENAME=trixie\n', 'trixie'),                               # Debian itself
])
def test_the_vendor_suite_is_the_base_distros_codename(tmp_path, os_release, want):
    import subprocess
    line = next(ln for ln in Clang(Runner(pretend=True))._repo_lines(clang_unit('clang-19'))
                if ln.startswith('CODENAME='))
    f = tmp_path / 'os-release'
    f.write_text(os_release)
    out = subprocess.run(['bash', '-c', line.replace('/etc/os-release', str(f)) + '; echo "$CODENAME"'],
                         capture_output=True, text=True).stdout.strip()
    assert out == want
