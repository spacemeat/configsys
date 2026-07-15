from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.gcc import Gcc
from configsys.runner import Result, Runner


def gcc_unit(comp='gcc-13', link='gcc', version=13, slaves=('g++',),
             ppa='ubuntu-toolchain-r/test'):
    fields = {'link': link, 'version': version, 'slaves': list(slaves)}
    if ppa:
        fields['ppa'] = ppa
    return ResolvedComponent(key=f'gcc\\{comp}', family='gcc', comp=comp, fields=fields)


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
    fam = get_family('gcc', Runner(pretend=True))
    assert isinstance(fam, Gcc) and is_supported('gcc')
    assert fam.privileged and fam.default_scope == 'system' and not fam.honors_scope


def test_packages_derivation():
    assert Gcc._packages(Gcc(Runner(pretend=True)), gcc_unit()) == ['gcc-13', 'g++-13']


def test_install_adds_ppa_installs_and_registers_alternative():
    r = Runner(pretend=True)
    Gcc(r).install(gcc_unit())
    cmd = r.calls[0]
    assert cmd.startswith('sudo ')                       # whole script under root
    assert 'add-apt-repository -y ppa:ubuntu-toolchain-r/test' in cmd
    assert 'apt-get install -y gcc-13 g++-13' in cmd
    assert ('update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-13 13 '
            '--slave /usr/bin/g++ g++ /usr/bin/g++-13') in cmd


def test_install_without_ppa_skips_repo_add():
    r = Runner(pretend=True)
    Gcc(r).install(gcc_unit(ppa=None))
    assert 'add-apt-repository' not in r.calls[0]
    assert 'apt-get install -y gcc-13 g++-13' in r.calls[0]


def test_uninstall_removes_alternative_then_packages():
    r = Runner(pretend=True)
    Gcc(r).uninstall(gcc_unit())
    cmd = r.calls[0]
    assert 'update-alternatives --remove gcc /usr/bin/gcc-13' in cmd
    assert 'apt-get remove -y gcc-13 g++-13' in cmd


def test_get_version_parses_compiler_output():
    fr = FakeRunner([('/usr/bin/gcc-13 --version', 0,
                      'gcc-13 (Ubuntu 13.2.0-4ubuntu3) 13.2.0\nCopyright (C) 2023\n')])
    assert Gcc(fr).get_version(gcc_unit()) == '13.2.0'


def test_get_version_not_installed():
    fr = FakeRunner([('gcc-13 --version', 127, '')])
    assert Gcc(fr).get_version(gcc_unit()) is None


def test_switching_is_not_configsys_and_no_latest():
    fam = Gcc(Runner(pretend=True))
    assert fam.lock(gcc_unit()).ok and fam.unlock(gcc_unit()).ok   # no-ops
    assert fam.is_locked(gcc_unit()) is False
    assert fam.get_latest(gcc_unit()) is None
    assert fam.location(gcc_unit()) == '/usr/bin/gcc-13'
