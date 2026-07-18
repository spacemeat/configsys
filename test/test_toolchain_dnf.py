'''The dnf (Fedora) path of the shared gcc/clang toolchain driver: versioned compat
packages, no update-alternatives, no third-party repo — but the same binary paths.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers.clang import Clang
from configsys.drivers.gcc import Gcc
from configsys.runner import Result, Runner


@pytest.fixture(autouse=True)
def _force_dnf(monkeypatch):
    monkeypatch.setenv('CONFIGSYS_PM', 'dnf')


def gcc_fedora(comp='gcc-13'):
    # as resolved on Fedora: identity from \gcc + `packages` override from the OS block
    return ResolvedComponent(key=f'gcc\\{comp}', driver='gcc', comp=comp,
                             fields={'link': 'gcc', 'version': 13, 'slaves': ['g++'],
                                     'packages': ['gcc13', 'gcc13-c++'],
                                     'ppa': 'ubuntu-toolchain-r/test'})


def clang_fedora(comp='clang-18'):
    return ResolvedComponent(key=f'clang\\{comp}', driver='clang', comp=comp,
                             fields={'packages': ['clang18']})


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


def test_gcc_install_uses_dnf_no_repo_no_alternatives():
    r = Runner(pretend=True)
    Gcc(r).install(gcc_fedora())
    cmd = r.calls[0]
    assert 'dnf install -y gcc13 gcc13-c++' in cmd          # Fedora compat packages
    assert 'add-apt-repository' not in cmd                   # ppa ignored on dnf
    assert 'update-alternatives' not in cmd                  # /usr/bin/gcc is real on Fedora


def test_clang_install_uses_dnf_no_llvm_apt_repo():
    r = Runner(pretend=True)
    Clang(r).install(clang_fedora())
    cmd = r.calls[0]
    assert 'dnf install -y clang18' in cmd
    assert 'apt.llvm.org' not in cmd                         # default_source skipped on dnf
    assert 'update-alternatives' not in cmd


def test_uninstall_removes_via_dnf_without_alternatives():
    r = Runner(pretend=True)
    Gcc(r).uninstall(gcc_fedora())
    cmd = r.calls[0]
    assert 'dnf remove -y gcc13 gcc13-c++' in cmd
    assert 'update-alternatives --remove' not in cmd


def test_upgrade_uses_dnf():
    r = Runner(pretend=True)
    Gcc(r).upgrade(gcc_fedora())
    assert r.calls[0] == 'sudo dnf upgrade -y gcc13 gcc13-c++'


def test_binary_paths_and_version_match_debian():
    # the whole reason one driver serves both: identical /usr/bin/gcc-13 binary
    fam = Gcc(Runner(pretend=True))
    assert fam._master_bin(gcc_fedora()) == '/usr/bin/gcc-13'
    assert fam.location(gcc_fedora()) == '/usr/bin/gcc-13'
    fr = FakeRunner([('/usr/bin/gcc-13 --version', 0, 'gcc-13 (GCC) 13.3.1\n')])
    assert Gcc(fr).get_version(gcc_fedora()) == '13.3.1'
