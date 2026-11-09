'''review-2026-11-2 D7 / tui-screens-08 — the one table painter Plugins, Glue and Dotfiles share.'''

from types import SimpleNamespace

from _render_harness import RecordingPalette

from configsys.tui.screens import table
from configsys.tui.surface import BufferSurface


def _vm(cells, elems, display=None, headers=('name', 'state')):
    widths, xs, virt_w = table.layout(headers, cells)
    return SimpleNamespace(headers=headers, cells=cells, widths=widths, xs=xs, virt_w=virt_w,
                           elems=elems, display=display)


def _text(surf, y):
    return ''.join(c.char for (yy, _x), c in sorted(surf.cells.items()) if yy == y)


def test_layout_sizes_columns_to_their_longest_cell():
    widths, xs, virt_w = table.layout(('a', 'bb'), [['xyz', 'q'], ['x', 'qqqq']], gutter=1)
    assert widths == [3, 4] and xs == [0, 4] and virt_w == 8


def test_rows_rules_and_selection():
    vm = _vm([['fd-glue', 'active'], ['zoxide-glue', 'changed']], ['installed', 'outdated'],
             display=[('hdr', 'bash  loader: active'), ('row', 0), ('row', 1)])
    surf = BufferSurface(10, 40)
    top, hs, page_h = table.draw_table(surf, RecordingPalette(), (1, 1, 6, 30), vm, 1, 0, 0, 10, 40)
    assert (top, hs, page_h) == (0, 0, 5)                        # 6-row panel - the header row
    assert _text(surf, 1).startswith('name')                     # sticky header
    assert _text(surf, 2).startswith('bash  loader: active ─')   # a section rule, ─-padded
    assert 'zoxide-glue' in _text(surf, 4)


def test_per_cell_roles_and_hbar_on_the_panels_own_border():
    cells = [['p' * 50, 'ok']]
    vm = _vm(cells, [['component', 'installed']])
    surf = BufferSurface(12, 30)
    # panel interior rows 1..6 -> its bottom border is row 7: the h-bar must land THERE (the plugins
    # table used to draw it a row below its panel, where the diff pane then painted over it)
    table.draw_table(surf, RecordingPalette(), (1, 1, 6, 20), vm, 0, 0, 5, 12, 30)
    assert any(y == 7 for (y, _x) in surf.cells) and not any(y == 8 for (y, _x) in surf.cells)


def test_hscroll_is_clamped_to_the_content():
    vm = _vm([['short', 'x']], ['component'])
    surf = BufferSurface(8, 40)
    _top, hs, _ph = table.draw_table(surf, RecordingPalette(), (1, 1, 4, 30), vm, 0, 0, 99, 8, 40)
    assert hs == 0
