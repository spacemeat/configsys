import os

import humon

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.aur import Aur
from configsys.routes import Resolver
from configsys.runner import Result, Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def aur_unit(comp='yay', name='yay-bin', version_spec=None):
    fields = {'name': name}
    if version_spec is not None:
        fields['version'] = version_spec
    return ResolvedComponent(key=f'aur\\{comp}', family='aur', comp=comp, fields=fields)


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


def test_registered_and_unprivileged():
    fam = get_family('aur', Runner(pretend=True))
    assert isinstance(fam, Aur) and is_supported('aur')
    assert fam.privileged is False        # makepkg refuses root; it sudo's internally


def test_install_clones_and_makepkgs_without_sudo():
    r = Runner(pretend=True)
    Aur(r).install(aur_unit())
    cmd = r.calls[0]
    assert not cmd.startswith('sudo ')
    assert 'git clone --depth 1 https://aur.archlinux.org/yay-bin.git' in cmd
    assert 'makepkg -si --noconfirm' in cmd


def test_uninstall_uses_pacman_remove_as_root():
    r = Runner(pretend=True)
    Aur(r).uninstall(aur_unit())
    assert r.calls == ['sudo pacman -R --noconfirm yay-bin']


def test_get_version_parses_pacman_q_on_pkgname():
    fr = FakeRunner([('pacman -Q yay-bin', 0, 'yay-bin 13.0.1-1\n')])
    assert Aur(fr).get_version(aur_unit()) == '13.0.1-1'


def test_get_latest_from_aur_spec(tmp_path):
    from configsys.paths import Paths
    from configsys.versions import VersionCache
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path),
                       'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    VersionCache({'aur:yay-bin': {'version': '13.0.1-1', 'url': None,
                                  'fetched': 1e12}}).save(paths)
    rc = aur_unit(version_spec={'aur': 'yay-bin'})
    assert Aur(Runner(pretend=True), paths=paths).get_latest(rc) == '13.0.1-1'


def test_aur_routes_pull_build_deps():
    r = Resolver(ROUTES, 'arch', '20260712')
    units, _ = r.resolve_with_roots(['yay'])
    assert units['aur\\yay'].name == 'yay-bin'
    assert {'pacman\\base-devel', 'pacman\\git'} <= set(units)
