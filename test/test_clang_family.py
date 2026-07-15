from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.clang import Clang
from configsys.runner import Result, Runner


def clang_unit(comp='clang-18', fields=None):
    return ResolvedComponent(key=f'clang\\{comp}', family='clang', comp=comp,
                             fields=fields or {})


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


def test_registered_system_scoped():
    fam = get_family('clang', Runner(pretend=True))
    assert isinstance(fam, Clang) and is_supported('clang')
    assert fam.privileged and fam.default_scope == 'system' and not fam.honors_scope


def test_defaults_from_bare_component():
    # `clang-18: {}` in routes — version, link, slaves, packages all derived.
    fam = Clang(Runner(pretend=True))
    rc = clang_unit()
    assert fam._link(rc) == 'clang' and fam._ver(rc) == '18'
    assert fam._slaves(rc) == ['clang++']               # family default
    assert fam._packages(rc) == ['clang-18']            # clang++ is NOT a package


def test_install_adds_llvm_repo_installs_and_registers_alternative():
    r = Runner(pretend=True)
    Clang(r).install(clang_unit())
    cmd = r.calls[0]
    assert cmd.startswith('sudo ')                       # whole script under root
    assert 'CODENAME="$(. /etc/os-release; echo "$VERSION_CODENAME")"' in cmd
    assert 'apt.llvm.org/llvm-snapshot.gpg.key' in cmd
    assert 'deb http://apt.llvm.org/$CODENAME/ llvm-toolchain-$CODENAME-18 main' in cmd
    assert 'apt-get install -y clang-18' in cmd          # only clang, not clang++
    assert ('update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 18 '
            '--slave /usr/bin/clang++ clang++ /usr/bin/clang++-18') in cmd


def test_repo_uses_version_specific_list_and_key_paths():
    r = Runner(pretend=True)
    Clang(r).install(clang_unit('clang-19'))
    cmd = r.calls[0]
    assert '/etc/apt/sources.list.d/clang-19.list' in cmd
    assert '/etc/apt/trusted.gpg.d/clang.asc' in cmd
    assert 'llvm-toolchain-$CODENAME-19 main' in cmd


def test_uninstall_removes_alternative_then_package():
    r = Runner(pretend=True)
    Clang(r).uninstall(clang_unit())
    cmd = r.calls[0]
    assert 'update-alternatives --remove clang /usr/bin/clang-18' in cmd
    assert 'apt-get remove -y clang-18' in cmd


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
