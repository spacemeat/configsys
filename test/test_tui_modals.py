'''review-2026-11-2 D7 / tui-core-08 — every modal and overlay moves through the keymap: page/top/
bottom work everywhere, a rebound `down` reaches a modal, and the frame + hints come from one place.'''

import curses

import pytest
from _render_harness import RecordingPalette

from configsys.tui import keyspec, menu
from configsys.tui.surface import BufferSurface


class Keys(BufferSurface):
    '''A BufferSurface that answers getch from a scripted key list.'''

    def __init__(self, keys, h=40, w=100):
        super().__init__(h, w)
        self._keys = list(keys)

    def getch(self):
        return self._keys.pop(0)


@pytest.fixture
def keymap(monkeypatch):
    def use(merged=None):
        km = keyspec.Keymap(merged) if merged else keyspec.shipped_keymap()
        monkeypatch.setattr(menu, '_KEYMAP', km)
        return km
    return use


def test_listnav_clamps_and_pages():
    nav = menu.ListNav
    assert nav.apply('down', 4, 4, 10) == 4                      # clamped at the limit
    assert nav.apply('page-down', 0, 50, 10) == 10
    assert nav.apply('page-up', 3, 50, 10) == 0
    assert nav.apply('bottom', 0, 7, 3) == 7 and nav.apply('top', 7, 7, 3) == 0
    assert nav.key(ord('x'), 2, 5, 3) is None                    # not a nav key


def test_listnav_outside_a_run_reads_the_shipped_keys(monkeypatch):
    monkeypatch.setattr(menu, '_KEYMAP', None)
    assert menu.ListNav.action(ord('j')) == 'down'
    assert menu.ListNav.action(curses.KEY_NPAGE) == 'page-down'
    assert menu.ListNav.action(ord('G')) == 'bottom'


def test_attr_modal_pages_over_tag_rows(keymap):
    keymap()
    # PgDn twice, then space toggles the tag the cursor landed on — not the first tag (the bug)
    scr = Keys([curses.KEY_NPAGE, curses.KEY_NPAGE, ord(' '), ord('\r')], h=14)
    inc, _exc = menu._attr_filter_modal(scr, RecordingPalette(), set(), set())
    first_tag = next(t for _axis, tags in menu.ATTR_AXES for t in tags)
    assert inc and first_tag.lower() not in inc


def test_popup_follows_a_rebound_down(keymap):
    keymap({'global': {'down': 'n', 'up': 'p', 'quit': 'q'}})
    scr = Keys([ord('n'), ord('\r')])
    assert menu._popup_choose(scr, RecordingPalette(), 'pick', [('a', ''), ('b', ''), ('c', '')]) == 1


def test_popup_hint_names_the_bound_keys(keymap):
    keymap({'global': {'down': 'n', 'up': 'p', 'quit': 'q'}})
    scr = Keys([27])
    menu._popup_choose(scr, RecordingPalette(), 'pick', [('a', ''), ('b', '')])
    painted = ''.join(c.char for (_y, _x), c in sorted(scr.cells.items()))
    assert 'n/p' in painted


def test_order_list_scrolls_and_carries_a_grabbed_item(keymap):
    keymap()
    items = [f'm{i}' for i in range(30)]
    # bottom, grab, top (carries the last item to the front), drop, enter
    scr = Keys([ord('G'), ord(' '), ord('g'), ord(' '), ord('\r')], h=12)
    out = menu._order_list(scr, RecordingPalette(), 'reorder', items)
    assert out[0] == 'm29' and out[1:] == items[:29]


def test_every_modal_frame_comes_from_one_painter():
    import inspect
    src = inspect.getsource(menu)
    assert src.count("'┌' + '─' * (box_w - 2) + '┐'") == 1      # only _modal_frame draws a box top


def test_reveal_subtree_lifts_a_just_opened_parent():
    keys, depths = list('abcdefgh'), [0, 1, 1, 0, 1, 1, 1, 1]
    # 'd' at row 3 opens rows 4-7; a 4-row window at top 0 can't show them -> the parent goes to the top
    assert menu._reveal_subtree(keys, depths, 'd', 0, 4) == 3
    assert menu._reveal_subtree(keys, depths, 'a', 0, 4) == 0       # already fits: unchanged
    assert menu._reveal_subtree(keys, depths, 'zz', 2, 4) == 2      # no such row: unchanged


def test_page_chrome_paints_status_above_the_legends():
    from configsys.tui.screens.base import Screen

    class S(Screen):
        id = 'config'
    surf = BufferSurface(10, 60)
    s = S()
    h, w = s.begin_page(surf, RecordingPalette())
    s.end_page(surf, RecordingPalette(), 'STATUS', ['NAV1', 'NAV2'], h, w)
    row = lambda y: ''.join(c.char for (yy, _x), c in sorted(surf.cells.items()) if yy == y)
    assert (h, w) == (10, 60)
    assert row(7).startswith('STATUS') and row(8).startswith('NAV1') and row(9).startswith('NAV2')
    assert 'Components' in row(0)                                   # the screen chips
