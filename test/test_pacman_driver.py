import os

import humon

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.pacman import Pacman
from configsys.routes import Resolver
from configsys.runner import Result, Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def pkg(name='btop'):
    return ResolvedComponent(key=f'pacman\\{name}', driver='pacman', comp=name,
                             fields={'name': name})


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
    fam = get_driver('pacman', Runner(pretend=True))
    assert isinstance(fam, Pacman) and is_supported('pacman')
    assert fam.privileged and fam.default_scope == 'system'


def test_install_upgrade_commands():
    r = Runner(pretend=True)
    Pacman(r).install(pkg())
    Pacman(r).upgrade(pkg())
    assert r.calls == ['sudo pacman -S --noconfirm btop', 'sudo pacman -S --noconfirm btop']


def test_uninstall_handles_package_or_group():
    r = Runner(pretend=True)
    Pacman(r).uninstall(pkg('xfce4'))
    c = r.calls[0]
    assert c.startswith('sudo ')
    assert 'pacman -Qq xfce4' in c and 'pacman -R --noconfirm xfce4' in c   # direct remove if a pkg
    assert 'pacman -Qgq xfce4' in c                                          # else expand the group


def test_get_version_detects_installed_group():
    # xfce4 is a group: `pacman -Q` fails, but `pacman -Qg` lists its installed members
    fr = FakeRunner([('pacman -Q xfce4', 1, "error: package 'xfce4' was not found\n"),
                     ('pacman -Qg xfce4', 0, 'xfce4 xfce4-panel\nxfce4 thunar\n')])
    assert Pacman(fr).get_version(pkg('xfce4')) == '(group)'


def test_get_latest_group_marker_matches_installed():
    # a group has no version; get_latest reports the same marker so it isn't flagged "outdated"
    fr = FakeRunner([('pacman -Si xfce4', 1, ''), ('pacman -Sg xfce4', 0, 'xfce4 xfce4-panel\n')])
    assert Pacman(fr).get_latest(pkg('xfce4')) == '(group)'


def test_get_version_parses_pacman_q():
    fr = FakeRunner([('pacman -Q btop', 0, 'btop 1.4.7-1\n')])
    assert Pacman(fr).get_version(pkg()) == '1.4.7-1'


def test_get_version_not_installed():
    fr = FakeRunner([('pacman -Q btop', 1, "error: package 'btop' was not found\n")])
    assert Pacman(fr).get_version(pkg()) is None


def test_get_latest_parses_si_version():
    si = 'Repository      : extra\nName            : btop\nVersion         : 1.4.7-1\n'
    fr = FakeRunner([('pacman -Si btop', 0, si)])
    assert Pacman(fr).get_latest(pkg()) == '1.4.7-1'


def test_rolling_lock_is_ledger_only():
    fam = Pacman(Runner(pretend=True))
    assert fam.is_locked(pkg()) is False
    assert fam.lock(pkg()).ok and fam.unlock(pkg()).ok    # ledger no-ops


def test_arch_routes_and_name_translations():
    r = Resolver(ROUTES, 'arch', '20260712')
    assert r.cascade_names == ['arch', 'glibc_linux', 'linux']
    # renamed packages resolve to the Arch names
    assert r.resolve_names(['pipx'])['pacman\\pipx'].name == 'python-pipx'
    assert r.resolve_names(['rust'])['pacman\\rust'].name == 'rust'
    assert r.resolve_names(['libfuse2'])['pacman\\libfuse2'].name == 'fuse2'
