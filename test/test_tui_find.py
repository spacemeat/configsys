'''`/` fuzzy-FIND (jump the cursor to a match) vs `F` FILTER (narrow the list). This covers the
scorer ranking + the _find_edit input loop's cursor side-effects (live jump, Enter commits, Esc /
empty-backspace restores). Curses drawing is stubbed.'''

from configsys.tui.menu import _find_edit, _fuzzy_score


class _Scr:
    def __init__(self, keys):
        self._keys = list(keys)

    def getmaxyx(self):
        return (24, 80)

    def addstr(self, *a):
        pass

    def refresh(self):
        pass

    def getch(self):
        return self._keys.pop(0)


def _keys(s):
    return [ord(c) for c in s]


LABELS = ['ripgrep', 'git', 'gnuradio', 'gnome', 'neovim', 'gimp']
ENTER, ESC, BKSP = 13, 27, 127


def _run(keys, restore=0):
    '''Drive _find_edit over LABELS with a key script; return the committed cursor index.'''
    box = {'cur': restore}
    _find_edit(_Scr(keys), LABELS, restore,
               lambda i: box.__setitem__('cur', i), lambda: None)
    return box['cur']


# -- scorer ranking -------------------------------------------------------

def test_substring_beats_subsequence_and_boundary_wins():
    assert _fuzzy_score('git', 'git') > _fuzzy_score('git', 'digit')      # boundary start ranks higher
    assert _fuzzy_score('gno', 'gnome') > _fuzzy_score('gno', 'gnuradio')  # substring beats subseq
    assert _fuzzy_score('rg', 'ripgrep') is not None                      # subsequence matches
    assert _fuzzy_score('xyz', 'ripgrep') is None                         # no match
    assert _fuzzy_score('', 'ripgrep') is None                           # empty = no target


# -- the find loop moves the cursor --------------------------------------

def test_find_jumps_cursor_to_best_match_on_enter():
    assert _run(_keys('gno') + [ENTER]) == LABELS.index('gnome')          # substring hit
    assert _run(_keys('rip') + [ENTER]) == LABELS.index('ripgrep')
    assert _run(_keys('vim') + [ENTER]) == LABELS.index('neovim')         # subsequence within


def test_find_is_live_and_refines_as_you_type():
    # 'g' could hit several; 'gnu' narrows to gnuradio. Commit lands there.
    assert _run(_keys('gnu') + [ENTER]) == LABELS.index('gnuradio')


def test_esc_restores_the_original_cursor():
    assert _run(_keys('gnome') + [ESC], restore=4) == 4                   # jumped then cancelled


def test_backspace_on_empty_query_cancels():
    assert _run([BKSP], restore=3) == 3


def test_no_match_holds_at_restore():
    assert _run(_keys('zzz') + [ENTER], restore=2) == 2                   # nothing matches -> stays


# -- tree-aware find reaches components collapsed inside subtrees ----------

def _ms_with_nested_dep():
    from configsys.componentObj import ResolvedComponent
    from configsys.installState import ComponentState
    from configsys.tui.menu import MenuState

    def cs(key, reqas):
        fam, comp = key.split('\\')
        rc = ResolvedComponent(key=key, driver=fam, comp=comp, fields={'name': comp},
                               requested_as=set(reqas))
        return ComponentState(component=rc, supported=True, present=True, installed_version='1',
                              latest_version='1', locked=False, managed=False, error=None,
                              lock_source=None)
    states = {'apt\\neovim': cs('apt\\neovim', ['neovim']),
              'apt\\ripgrep': cs('apt\\ripgrep', ['neovim'])}   # ripgrep = a dep unit UNDER neovim
    return MenuState(states, [('user', ['neovim'])])


def test_find_reveals_a_component_collapsed_in_a_tree():
    from configsys.tui.menu import _find_edit_tree
    ms = _ms_with_nested_dep()
    for n in ms._all_nodes():                            # collapse everything (user + neovim)
        if n.expandable:
            n.expanded = False
    ms._refresh()
    assert not any('ripgrep' in (n.label or '') for n in ms.rows)         # hidden two levels deep

    _find_edit_tree(_Scr(_keys('ripgrep') + [ENTER]), ms, lambda: None)
    assert ms.rows[ms.cursor].label == 'ripgrep'                          # cursor jumped to it
    assert any('ripgrep' in (n.label or '') for n in ms.rows)             # its tree was opened


def test_find_tree_esc_restores_collapsed_state():
    from configsys.tui.menu import _find_edit_tree
    ms = _ms_with_nested_dep()
    for n in ms._all_nodes():
        if n.expandable:
            n.expanded = False
    ms._refresh()
    before = [n.id for n in ms.rows]
    _find_edit_tree(_Scr(_keys('ripgrep') + [ESC]), ms, lambda: None)     # find then cancel
    assert [n.id for n in ms.rows] == before                             # expansion restored (still collapsed)
