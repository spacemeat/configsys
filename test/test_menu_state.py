from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui.menu import MenuState


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
    if status == 'unsupported':
        return ComponentState(supported=False, present=False, installed_version=None,
                              latest_version=None, locked=False, **common)
    raise ValueError(status)


def make():
    # firefox -> flatpak\firefox (+ apt\flatpak dep); vulkan-dev composite; btop singleton
    states = {
        'apt\\btop': cs('apt\\btop', 'installed', ['btop']),
        'apt\\flatpak': cs('apt\\flatpak', 'installed', ['firefox']),
        'flatpak\\firefox': cs('flatpak\\firefox', 'missing', ['firefox']),
        'apt\\build-essential': cs('apt\\build-essential', 'installed', ['vulkan-dev']),
        'apt\\libxcb': cs('apt\\libxcb', 'missing', ['vulkan-dev']),
        'tarball\\vulkan-sdk': cs('tarball\\vulkan-sdk', 'missing', ['vulkan-dev']),
    }
    requested = {'btop': ['u'], 'firefox': ['u'], 'vulkan-dev': ['v']}
    return MenuState(states, requested)


def test_top_view_has_one_row_per_profile_name():
    ms = make()
    assert ms.mode == 'top'
    assert [r.id for r in ms.rows] == ['btop', 'firefox', 'vulkan-dev']  # not the units
    assert all(r.is_group for r in ms.rows)


def test_full_view_has_one_row_per_unit():
    ms = make()
    ms.toggle_mode()
    assert ms.mode == 'full'
    assert [r.id for r in ms.rows] == [
        'apt\\btop', 'apt\\build-essential', 'apt\\flatpak',
        'apt\\libxcb', 'flatpak\\firefox', 'tarball\\vulkan-sdk',
    ]


def test_group_status_aggregation():
    ms = make()
    by = {r.id: r.status for r in ms.rows}
    assert by['btop'] == 'installed'          # its one unit installed
    assert by['firefox'] == 'partial'         # flatpak dep installed, firefox missing
    assert by['vulkan-dev'] == 'partial'      # build-essential installed, rest missing


def test_staging_a_group_marks_only_applicable_member_units():
    ms = make()
    ms.cursor = 2  # vulkan-dev
    assert ms.stage('install') is True
    # install applies to the missing members only (build-essential is installed)
    assert ms.staged == {'apt\\libxcb': 'install', 'tarball\\vulkan-sdk': 'install'}


def test_staged_ops_persist_across_mode_toggle():
    ms = make()
    ms.cursor = 2
    ms.stage('install')          # stages vulkan-dev's missing parts
    ms.toggle_mode()             # to full
    # the parts show as staged units
    libxcb = next(r for r in ms.rows if r.id == 'apt\\libxcb')
    be = next(r for r in ms.rows if r.id == 'apt\\build-essential')
    assert ms.row_op(libxcb) == 'install'
    assert ms.row_op(be) is None  # not staged (was already installed)


def test_group_remove_targets_present_members():
    ms = make()
    ms.cursor = 2  # vulkan-dev
    ms.stage('remove')
    assert ms.staged == {'apt\\build-essential': 'remove'}  # only the installed one


def test_plan_is_unit_level():
    ms = make()
    ms.cursor = 1  # firefox
    ms.stage('install')  # firefox missing -> flatpak\firefox
    plan = ms.plan()
    assert [(op, k) for op, k, _rc in plan] == [('install', 'flatpak\\firefox')]


def test_select_all_and_toggle():
    ms = make()
    ms.select_all()
    assert ms.selected == {'btop', 'firefox', 'vulkan-dev'}
    ms.toggle_mode()             # selection resets on mode change
    assert ms.selected == set()


def test_errors_shown_on_group_row():
    ms = make()
    ms.errors = {'flatpak\\firefox': 'install failed: exit 1'}
    firefox = next(r for r in ms.rows if r.id == 'firefox')
    assert ms.row_error(firefox) == 'install failed: exit 1'
