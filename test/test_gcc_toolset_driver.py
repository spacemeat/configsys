import humon

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.gcc_toolset import GccToolset
from configsys.routes import Resolver
from configsys.runner import Result, Runner


def unit(comp='gcc-13'):
    return ResolvedComponent(key=f'gcc-toolset\\{comp}', driver='gcc-toolset',
                             comp=comp, fields={})


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
    fam = get_driver('gcc-toolset', Runner(pretend=True))
    assert isinstance(fam, GccToolset) and is_supported('gcc-toolset')
    assert fam.privileged and fam.default_scope == 'system'


def test_paths_and_package_derived_from_component():
    fam = GccToolset(Runner(pretend=True))
    rc = unit('gcc-13')
    assert fam._pkg(rc) == 'gcc-toolset-13'
    assert fam._gcc_bin(rc) == '/opt/rh/gcc-toolset-13/root/usr/bin/gcc'
    assert fam.location(rc) == '/opt/rh/gcc-toolset-13'


def test_install_uninstall_use_dnf_meta_package():
    r = Runner(pretend=True)
    GccToolset(r).install(unit())
    GccToolset(r).uninstall(unit())
    assert r.calls == ['sudo dnf install -y gcc-toolset-13',
                       'sudo dnf remove -y gcc-toolset-13']


def test_get_version_reads_the_toolset_gcc_binary():
    # not the meta rpm version (13.0) — the real gcc version from the binary
    out = 'gcc (GCC) 13.3.1 20240611 (Red Hat 13.3.1-2)\nCopyright (C) 2023\n'
    fr = FakeRunner([('/opt/rh/gcc-toolset-13/root/usr/bin/gcc --version', 0, out)])
    assert GccToolset(fr).get_version(unit()) == '13.3.1'


def test_get_version_none_when_not_installed():
    fr = FakeRunner([('gcc --version', 127, '')])
    assert GccToolset(fr).get_version(unit()) is None


def test_activation_is_not_configsys_and_no_latest():
    fam = GccToolset(Runner(pretend=True))
    assert fam.lock(unit()).ok and fam.unlock(unit()).ok    # ledger no-ops
    assert fam.is_locked(unit()) is False
    assert fam.get_latest(unit()) is None


def test_rhel_routes_gcc_to_toolset(tmp_path):
    import os
    routes = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
    r = Resolver(routes, 'rhel', '9.8')
    assert r.cascade_names == ['rhel', 'redhat', 'linux']
    units, _ = r.resolve_with_roots(['gcc-15'])
    assert 'gcc-toolset\\gcc-15' in units
    # native packages still route through dnf (inherited from the fedora block)
    units, _ = r.resolve_with_roots(['btop'])
    assert 'dnf\\btop' in units
