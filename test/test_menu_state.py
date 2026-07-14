from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui.menu import COMPONENT, PROFILE, UNIT, MenuState


def cs(key, status, requested_as):
    fam, comp = key.split('\\')
    rc = ResolvedComponent(key=key, family=fam, comp=comp, fields={'name': comp},
                           requested_as=set(requested_as))
    common = dict(component=rc, managed=False, error=None, lock_source=None)
    if status == 'installed':
        return ComponentState(supported=True, present=True, installed_version='1',
                              latest_version='1', locked=False, **common)
    if status == 'missing':
        return ComponentState(supported=True, present=False, installed_version=None,
                              latest_version='2', locked=False, **common)
    if status == 'outdated':
        return ComponentState(supported=True, present=True, installed_version='1',
                              latest_version='2', locked=False, **common)
    raise ValueError(status)


def make():
    states = {
        'apt\\btop': cs('apt\\btop', 'installed', ['btop']),
        'flatpak\\firefox': cs('flatpak\\firefox', 'missing', ['firefox']),
        'apt\\flatpak': cs('apt\\flatpak', 'installed', ['firefox']),
        'appImage\\neovim': cs('appImage\\neovim', 'missing', ['neovim']),
        'apt\\ripgrep': cs('apt\\ripgrep', 'installed', ['neovim']),
        'dotfiles\\neovim': cs('dotfiles\\neovim', 'missing', ['neovim']),
        'apt\\build-essential': cs('apt\\build-essential', 'installed',
                                   ['build-essential', 'vulkan-dev']),
        'apt\\libxcb': cs('apt\\libxcb', 'missing', ['vulkan-dev']),
        'tarball\\vulkan-sdk': cs('tarball\\vulkan-sdk', 'missing', ['vulkan-dev']),
        'apt\\curl': cs('apt\\curl', 'installed', ['vulkan-dev']),
    }
    profile_comps = [
        ('user', ['btop', 'firefox', 'neovim']),
        ('vulkan', ['build-essential', 'vulkan-dev']),
    ]
    return MenuState(states, profile_comps)


def ids():
    return [n.id for n in make().rows]


def test_default_view_profiles_expanded_components_collapsed():
    ms = make()
    assert [n.id for n in ms.rows] == [
        'p:user', 'c:user:btop', 'c:user:firefox', 'c:user:neovim',
        'p:vulkan', 'c:vulkan:build-essential', 'c:vulkan:vulkan-dev',
    ]
    kinds = {n.id: n.kind for n in ms.rows}
    assert kinds['p:user'] == PROFILE
    assert kinds['c:user:btop'] == UNIT          # single-unit component -> leaf
    assert kinds['c:user:firefox'] == COMPONENT  # multi-unit -> expandable


def test_leaf_component_carries_family():
    btop = next(n for n in make().rows if n.id == 'c:user:btop')
    assert btop.family == 'apt' and not btop.expandable


def test_expand_component_reveals_units_with_family():
    ms = make()
    ms.cursor = ms.rows.index(next(n for n in ms.rows if n.id == 'c:user:firefox'))
    ms.toggle_expand()
    ids_now = [n.id for n in ms.rows]
    i = ids_now.index('c:user:firefox')
    # units appear right after their component, indented
    assert ids_now[i + 1:i + 3] == [
        'u:user:firefox:apt\\flatpak', 'u:user:firefox:flatpak\\firefox']
    units = {n.id: n for n in ms.rows if n.kind == UNIT and n.depth == 2}
    assert units['u:user:firefox:apt\\flatpak'].family == 'apt'
    assert units['u:user:firefox:flatpak\\firefox'].family == 'flatpak'
    assert units['u:user:firefox:flatpak\\firefox'].label == 'firefox'


def test_stage_on_profile_marks_all_its_missing_units():
    ms = make()
    ms.cursor = 0  # p:user
    ms.stage('install')
    assert ms.staged == {  # only the missing ones across user's components
        'flatpak\\firefox': 'install',
        'appImage\\neovim': 'install',
        'dotfiles\\neovim': 'install',
    }


def test_stage_on_component_marks_its_missing_units():
    ms = make()
    ms.cursor = ms.rows.index(next(n for n in ms.rows if n.id == 'c:vulkan:vulkan-dev'))
    ms.stage('install')
    assert ms.staged == {'apt\\libxcb': 'install', 'tarball\\vulkan-sdk': 'install'}


def test_select_individual_unit_after_expand():
    ms = make()
    ms.cursor = ms.rows.index(next(n for n in ms.rows if n.id == 'c:user:neovim'))
    ms.toggle_expand()
    # move to a single unit and stage just it
    ms.cursor = ms.rows.index(next(n for n in ms.rows
                                   if n.id == 'u:user:neovim:appImage\\neovim'))
    ms.stage('install')
    assert ms.staged == {'appImage\\neovim': 'install'}


def test_parent_shows_staged_when_child_unit_staged():
    ms = make()
    ms.staged = {'flatpak\\firefox': 'install'}
    firefox = next(n for n in ms.rows if n.id == 'c:user:firefox')
    user = next(n for n in ms.rows if n.id == 'p:user')
    assert ms.node_op(firefox) == 'install'
    assert ms.node_op(user) == 'install'


def test_toggle_expand_all():
    ms = make()
    ms.toggle_expand_all()   # expand every component
    assert any(n.kind == UNIT and n.depth == 2 for n in ms.rows)
    ms.toggle_expand_all()   # collapse them
    assert not any(n.kind == UNIT and n.depth == 2 for n in ms.rows)


def test_profile_status_aggregates():
    ms = make()
    user = next(n for n in ms.rows if n.id == 'p:user')
    assert user.status == 'partial'   # some installed, some missing
    vulkan = next(n for n in ms.rows if n.id == 'c:vulkan:vulkan-dev')
    assert vulkan.status == 'partial'


def test_installed_and_latest_columns():
    ms = make()
    ms.toggle_expand_all()
    by = {n.id: n for n in ms.rows if n.kind == UNIT}
    firefox = by['u:user:firefox:flatpak\\firefox']   # missing
    assert firefox.installed_str() == '—'
    assert firefox.latest_str() == '2'                # what you'd install
    ripgrep = by['u:user:neovim:apt\\ripgrep']        # installed, up to date
    assert ripgrep.installed_str() == '1'
    assert ripgrep.latest_str() == '1'
    # a group shows a count in INSTALLED and blank LATEST
    fxgroup = next(n for n in ms.rows if n.id == 'c:user:firefox')
    assert '/' in fxgroup.installed_str() and fxgroup.latest_str() == ''


def test_collapse_via_expand_false():
    ms = make()
    fi = next(n for n in ms.rows if n.id == 'c:user:firefox')
    ms.cursor = ms.rows.index(fi)
    ms.expand(True)
    assert any(n.depth == 2 for n in ms.rows)
    ms.cursor = ms.rows.index(next(n for n in ms.rows if n.id == 'c:user:firefox'))
    ms.expand(False)
    assert not any(n.id.startswith('u:user:firefox') for n in ms.rows)
