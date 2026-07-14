from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui.menu import MenuState


def state(key, status):
    rc = ResolvedComponent(key=key, family=key.split('\\')[0], comp=key.split('\\')[-1],
                           fields={'name': key.split('\\')[-1]})
    common = dict(component=rc, managed=False, error=None, lock_source=None)
    if status == 'installed':
        return ComponentState(supported=True, present=True, installed_version='1',
                              latest_version='1', locked=False, **common)
    if status == 'outdated':
        return ComponentState(supported=True, present=True, installed_version='1',
                              latest_version='2', locked=False, **common)
    if status == 'missing':
        return ComponentState(supported=True, present=False, installed_version=None,
                              latest_version='2', locked=False, **common)
    if status == 'locked':
        return ComponentState(supported=True, present=True, installed_version='1',
                              latest_version='1', locked=True,
                              component=rc, managed=False, error=None, lock_source='native')
    if status == 'unsupported':
        return ComponentState(supported=False, present=False, installed_version=None,
                              latest_version=None, locked=False, **common)
    raise ValueError(status)


def make():
    # sorted keys => deterministic row order 0..4
    states = {
        'apt\\a_missing': state('apt\\a_missing', 'missing'),
        'apt\\b_installed': state('apt\\b_installed', 'installed'),
        'apt\\c_outdated': state('apt\\c_outdated', 'outdated'),
        'apt\\d_locked': state('apt\\d_locked', 'locked'),
        'flatpak\\e_unsup': state('flatpak\\e_unsup', 'unsupported'),
    }
    return MenuState(states)


def test_navigation_clamps():
    ms = make()
    assert ms.cursor == 0
    ms.move(-1)
    assert ms.cursor == 0
    ms.move(100)
    assert ms.cursor == 4
    ms.top()
    assert ms.cursor == 0
    ms.bottom()
    assert ms.cursor == 4


def test_selection_toggle_and_all():
    ms = make()
    ms.toggle_select()
    assert ms.selected == {0}
    ms.toggle_select()
    assert ms.selected == set()
    ms.select_all()
    assert ms.selected == {0, 1, 2, 3, 4}
    ms.clear_selection()
    assert ms.selected == set()


def test_stage_respects_applicability_on_cursor():
    ms = make()
    # row 0 is missing -> install applicable, remove not
    assert ms.stage('install') is True
    assert ms.staged == {0: 'install'}
    ms.clear_all_staged()
    assert ms.stage('remove') is False
    assert ms.staged == {}


def test_stage_over_selection_filters_inapplicable():
    ms = make()
    ms.select_all()
    # install applies only to the missing row (index 0)
    ms.stage('install')
    assert ms.staged == {0: 'install'}


def test_remove_applies_to_present_rows():
    ms = make()
    ms.select_all()
    ms.stage('remove')
    # present rows: installed(1), outdated(2), locked(3)
    assert set(ms.staged) == {1, 2, 3}
    assert all(op == 'remove' for op in ms.staged.values())


def test_lock_unlock_applicability():
    ms = make()
    ms.select_all()
    ms.stage('lock')            # present & not locked: 1,2 (3 already locked)
    assert set(ms.staged) == {1, 2}
    ms.clear_all_staged()
    ms.stage('unlock')          # only the locked row 3
    assert set(ms.staged) == {3}


def test_unsupported_never_stages():
    ms = make()
    ms.cursor = 4  # unsupported row
    for op in ('install', 'upgrade', 'remove', 'lock', 'unlock'):
        assert ms.stage(op) is False
    assert ms.staged == {}


def test_plan_is_ordered_with_components():
    ms = make()
    ms.select_all()
    ms.stage('remove')  # 1,2,3
    plan = ms.plan()
    assert [op for op, _k, _rc in plan] == ['remove', 'remove', 'remove']
    keys = [k for _op, k, _rc in plan]
    assert keys == ['apt\\b_installed', 'apt\\c_outdated', 'apt\\d_locked']
    assert all(hasattr(rc, 'name') for _op, _k, rc in plan)


def test_errors_default_empty_and_stage_clears_current_row_error():
    ms = make()
    assert ms.errors == {}
    ms.errors = {'apt\\a_missing': 'install failed: exit 1'}
    ms.cursor = 0  # the missing row
    ms.stage('install')  # re-attempting clears its error mark
    assert 'apt\\a_missing' not in ms.errors


def test_targets_prefers_selection_over_cursor():
    ms = make()
    ms.cursor = 0
    ms.selected = {1, 2}
    ms.stage('remove')
    assert set(ms.staged) == {1, 2}  # not the cursor row
