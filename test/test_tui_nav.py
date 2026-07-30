'''TUI navigation + lock toggle (menu items 2-4): h/l & arrows expand/collapse (profiles too),
enter opens, and L toggles version-lock intent (undoing a requested lock or a settled one).
Pure MenuState logic — no curses.'''

from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui.menu import MenuState, COMPONENT, PROFILE, UNIT


def _cs(key, present=True, locked=False, roots=None):
    driver, cname = key.split('\\')
    rc = ResolvedComponent(key=key, driver=driver, comp=cname,
                           requested_as=set(roots or [cname]))
    return ComponentState(component=rc, supported=True, present=present,
                          installed_version='1' if present else None, latest_version='1',
                          locked=locked, lock_source='ledger' if locked else None,
                          managed=True, error=None, scope='user')


def _menu():
    # profile p: a (single unit, unlocked), b (single unit, locked), docker (2 units)
    states = {
        'apt\\a': _cs('apt\\a'),
        'apt\\b': _cs('apt\\b', locked=True),
        'apt\\docker-ce': _cs('apt\\docker-ce', roots=['docker']),
        'apt\\containerd': _cs('apt\\containerd', roots=['docker']),
    }
    return MenuState(states, [('p', ['a', 'b', 'docker'])])


def _labels(ms):
    return [n.label for n in ms.rows]


# -- expand / collapse / jump ---------------------------------------------

def test_collapse_collapses_a_profile():
    ms = _menu()                                  # rows: p, a, b, docker (docker collapsed)
    assert ms.cur().kind == PROFILE and 'a' in _labels(ms)
    ms.collapse()                                 # h/← on the profile
    assert ms.cur().kind == PROFILE and _labels(ms) == ['p']   # collapsed to just the profile


def test_expand_or_jump_expands_then_steps_into_children():
    ms = _menu()
    ms.cursor = _labels(ms).index('docker')       # a collapsed COMPONENT
    ms.expand_or_jump()                           # l/→ expands it
    assert ms.cur().label == 'docker' and 'docker-ce' in _labels(ms)
    ms.expand_or_jump()                           # already expanded -> step into first child
    assert ms.cur().kind == UNIT and ms.cur().label == 'containerd'   # units sorted by key


def test_collapse_from_child_steps_to_parent():
    ms = _menu()
    ms.cursor = _labels(ms).index('docker')
    ms.expand_or_jump()
    ms.cursor = _labels(ms).index('docker-ce')    # on a unit child
    ms.collapse()                                 # h/← steps to the parent component
    assert ms.cur().label == 'docker' and ms.cur().kind == COMPONENT


# -- L: toggle version lock -----------------------------------------------

def test_lock_toggle_on_unlocked_unit():
    ms = _menu()
    ms.cursor = _labels(ms).index('a')            # present + unlocked
    ms.toggle_lock()
    assert ms.staged['apt\\a'] == 'lock'
    ms.toggle_lock()                              # toggling again undoes the requested lock
    assert 'apt\\a' not in ms.staged


def test_lock_toggle_on_locked_unit():
    ms = _menu()
    ms.cursor = _labels(ms).index('b')            # already locked
    ms.toggle_lock()
    assert ms.staged['apt\\b'] == 'unlock'        # stage removal of the settled lock
    ms.toggle_lock()
    assert 'apt\\b' not in ms.staged


def test_clear_resets_lock_state():
    ms = _menu()
    ms.cursor = _labels(ms).index('a')
    ms.toggle_lock()                              # stage a lock
    assert 'apt\\a' in ms.staged
    ms.unstage()                                  # `c` -> back to the current on-disk state
    assert 'apt\\a' not in ms.staged


def test_columns_responsive_and_equal_versions():
    from configsys.tui.menu import _columns
    for w in (80, 120, 160):
        c = _columns(w)
        assert c['inst'][1] == c['latest'][1]                  # version columns equal width
        xs = [c[k][0] for k in ('name', 'fam', 'scope', 'status', 'inst', 'latest')]
        assert xs == sorted(xs) and len(set(xs)) == 6          # ordered, non-overlapping
        assert c['latest'][0] + c['latest'][1] <= w            # fits within the terminal
    assert _columns(160)['name'][1] > _columns(80)['name'][1]  # NAME absorbs the extra width


# -- include-as-link (menu item 1) ----------------------------------------

def test_include_renders_as_link_stages_target_and_jumps():
    from configsys.tui.menu import LINK
    states = {
        'apt\\x': _cs('apt\\x', present=False, roots=['x']),
        'apt\\y': _cs('apt\\y', present=False, roots=['y']),
        'apt\\z': _cs('apt\\z', present=False, roots=['z']),
    }
    layouts = [('app',  [('include', 'base'), ('component', 'z')]),
               ('base', [('component', 'x'), ('component', 'y')])]
    transitive = {'app': ['x', 'y', 'z'], 'base': ['x', 'y']}
    ms = MenuState(states, layouts, transitive)
    rows = [(n.kind, n.label) for n in ms.rows]
    assert rows == [(PROFILE, 'app'), (LINK, 'base'), (UNIT, 'z'),
                    (PROFILE, 'base'), (UNIT, 'x'), (UNIT, 'y')]   # +base -> one LINK, base shown once
    link = ms.rows[1]
    assert link.kind == LINK and link.link_target == 'p:base'
    # staging install on the link acts on the TARGET profile's units (x, y) -- not z
    ms.cursor = 1
    ms.stage('install')
    assert set(ms.staged) == {'apt\\x', 'apt\\y'}
    # enter (or l/->) on the link JUMPS to the base profile node
    ms.cursor = 1
    ms.enter()
    assert ms.cur().kind == PROFILE and ms.cur().id == 'p:base'
