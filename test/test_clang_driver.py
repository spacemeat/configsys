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
    assert r.calls[0] == 'test -f /etc/apt/sources.list.d/clang-18.list'   # did WE create it? (rollback)
    assert all(c.startswith('sudo ') for c in r.calls[1:])                 # the source + install as root
    cmd = '\n'.join(r.calls)
    assert ('CODENAME="$(. /etc/os-release; echo "${UBUNTU_CODENAME:-${DEBIAN_CODENAME:-$VERSION_CODENAME}}")"'
            in cmd)                                   # derivative-safe (B7; LMDE's own codename too)
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
    cmd = '\n'.join(r.calls)
    assert '/etc/apt/sources.list.d/clang-19.list' in cmd
    assert 'llvm-toolchain-' in cmd and '-19 main' in cmd


def test_vendor_key_is_a_per_source_keyring_named_by_signed_by():
    # drivers-lang-03 (d): the key goes in its OWN keyring, trusted only for the source that names it
    # with signed-by= — never the global trusted.gpg.d, where it would vouch for every repo
    r = Runner(pretend=True)
    Clang(r).install(clang_unit('clang-19'))
    cmd = '\n'.join(r.calls)
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


def test_uninstall_leaves_the_vendor_source_and_keyring_like_apts_own():
    # decisions 2026-11-09 W2.2: exactly like the apt driver's `source-*`/`pubkey-*` — uninstall
    # leaves the list and keyring; `configsys refresh` offers to remove them once the component is
    # neither picked nor installed (cli/refresh._reconcile_managed_sources, via vendor_source)
    r = Runner(pretend=True)
    Clang(r).uninstall(clang_unit('clang-19'))
    cmd = r.calls[0]
    assert 'apt-get remove -y clang-19' in cmd
    assert 'clang-19.list' not in cmd and 'keyrings' not in cmd and 'trusted.gpg.d' not in cmd


def test_vendor_source_names_the_key_keyring_and_list_refresh_manages():
    drv = Clang(Runner(pretend=True))
    assert drv.vendor_source('clang-19', {}) == (
        'https://apt.llvm.org/llvm-snapshot.gpg.key', '/etc/apt/keyrings/clang-19.asc',
        '/etc/apt/sources.list.d/clang-19.list')
    assert drv.vendor_source('clang-19', {'version': 20})[2] == '/etc/apt/sources.list.d/clang-20.list'
    from configsys.drivers.gcc import Gcc
    assert Gcc(Runner(pretend=True)).vendor_source('gcc-13', {'ppa': 'ubuntu-toolchain-r/test'}) is None
    assert Gcc(Runner(pretend=True)).vendor_source('gcc-13', {}) is None     # no source at all
    # after refresh removes a stale list of ours: an older configsys's global key, once no list of
    # ours lacks signed-by (the keyring itself goes through apt.drop_keyring_cmd, like apt's keys)
    assert 'rm -f /etc/apt/trusted.gpg.d/clang.asc' in drv.legacy_key_cleanup()


def test_the_source_it_writes_reads_on_every_apt_release_configsys_knows():
    # A one-line `.list` (apt 3 still reads it — deb822 `.sources` is only the new default), an
    # ARMORED `.asc` keyring named by `signed-by=` (an .asc there needs apt >= 1.4), and
    # /etc/apt/keyrings made with mkdir -p (only Debian 12 / Ubuntu 22.04 ship it). Every apt in the
    # release registry clears that floor — so one shape, no version branching.
    import os
    import re
    from packaging.version import Version
    from configsys import routes
    cascade = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))[0]
    apts = [Version(re.match(r'apt (\d+\.\d+(?:\.\d+)?)', str(rel.get('manager'))).group(1))
            for blk in cascade.blocks.values() if isinstance(blk, dict)
            for rel in (blk.get('releases') or {}).values()
            if isinstance(rel, dict) and str(rel.get('manager', '')).startswith('apt ')]
    assert apts and min(apts) >= Version('1.4')
    cmd = '\n'.join(Clang(Runner(pretend=True))._repo_lines(clang_unit('clang-19')))
    assert 'mkdir -p /etc/apt/keyrings' in cmd
    assert cmd.index('mkdir -p /etc/apt/keyrings') < cmd.index('tee /etc/apt/keyrings/clang-19.asc')
    assert "echo 'deb [signed-by=/etc/apt/keyrings/clang-19.asc] " in cmd
    assert 'tee /etc/apt/sources.list.d/clang-19.list' in cmd


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


def _apt_world(our_source_breaks_update):
    '''A scripted runner for the vendor-source step: `test -f`/`rm -f <list>`/the write script track
    whether OUR list exists; `apt-get update` fails either because of ours (`our_source_breaks_update`)
    or always (an unrelated, pre-existing broken source).'''
    from configsys.runner import Result as R
    LIST = '/etc/apt/sources.list.d/clang-19.list'

    class World:
        pretend = False

        def __init__(self):
            self.calls, self.present = [], False

        def run(self, cmd, *, sudo=False, capture=True, **_kw):
            full = f'sudo {cmd}' if sudo else cmd
            self.calls.append(full)
            if cmd.startswith('test -f'):
                return R(full, 0 if self.present else 1)
            if cmd == f'sudo rm -f {LIST}':
                self.present = False
                return R(full, 0)
            if f'tee {LIST}' in cmd:                       # the write script: list written, then update
                self.present = True
            if 'apt-get update' in cmd:
                bad = self.present if our_source_breaks_update else True
                return R(full, 100 if bad else 0, stderr='E: The list of sources could not be read.')
            return R(full, 0)

        def echo(self, msg):
            pass
    return World()


@pytest.fixture
def _no_backoff(monkeypatch):
    import configsys.drivers.apt as apt_mod
    monkeypatch.setattr(apt_mod, '_UPDATE_BACKOFF', 0)


def test_a_preexisting_broken_source_keeps_our_new_vendor_source(_no_backoff):
    # decisions 2026-11-09 W2.2 follow-up: the culprit check apt's own vendor sources get — apt-get
    # update fails WITHOUT our list too, so ours is put back and the real breakage reported
    r = _apt_world(our_source_breaks_update=False)
    res = Clang(r).install(clang_unit('clang-19'))
    assert not res.ok and 'pre-existing apt source' in res.output and 'rolled back' not in res.output
    assert r.present                                               # our list restored
    assert not any('keyrings/clang-19.asc' in c and 'rm -f' in c for c in r.calls if 'tee' not in c)
    assert not any('apt-get install -y clang-19' in c for c in r.calls)


def test_our_broken_vendor_source_is_rolled_back_with_its_keyring(_no_backoff):
    from configsys.drivers.apt import drop_keyring_cmd
    r = _apt_world(our_source_breaks_update=True)
    res = Clang(r).install(clang_unit('clang-19'))
    assert not res.ok and 'rolled back' in res.output and 'pre-existing' not in res.output
    assert not r.present
    assert any(drop_keyring_cmd('/etc/apt/keyrings/clang-19.asc') in c for c in r.calls)
    assert not any('apt-get install -y clang-19' in c for c in r.calls)


def test_apt_and_gcc_clang_share_one_commit_source(monkeypatch):
    import configsys.drivers.apt as apt_mod
    from configsys.drivers.apt import Apt
    seen = []
    monkeypatch.setattr(apt_mod, 'commit_source', lambda runner, write, path, *a, **k: seen.append(path))
    Clang(Runner(pretend=True)).install(clang_unit('clang-19'))
    Apt(Runner(pretend=True)).ensure_prereqs(ResolvedComponent(
        key='apt\\x', driver='apt', comp='x', fields={'name': 'x', 'source-line': 'deb https://x/ y main',
                                                       'source-path': '/etc/apt/sources.list.d/x.list'}))
    assert seen == ['/etc/apt/sources.list.d/clang-19.list', '/etc/apt/sources.list.d/x.list']


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
    # the write step, then the legacy-key check install runs once that step commits (_alt.install)
    script = '\n'.join(['set -e'] + drv._repo_lines(rc) + [drv._drop_legacy_key()])
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
