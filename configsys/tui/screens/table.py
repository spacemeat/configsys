'''table.py — the one table painter the Plugins, Glue and Dotfiles screens share (review-2026-11-2 D7 /
tui-screens-08; each used to carry its own copy of the geometry and the paint loop).

A table VM is any object with:
  headers   column titles
  cells     [[str, …], …] — one list of cell texts per row
  widths, xs, virt_w        column widths, their virtual x starts and the total virtual width — what
                            `layout()` derives from headers + cells
  elems     per row: one element role (every cell) or a list of roles (one per cell)
  display   None (rows in order) or the scrolled list: ('row', i) entries interleaved with
            ('hdr', text) section rules (painted full-width, padded with ─, never selectable)

`draw_table` paints one into a panel interior and returns the clamped (top, hscroll) for the screen to
keep; the painter itself writes nothing.
'''

from ..paint import _fit, _put, _put_hscroll, _scroll_top, _scrollbar_h, _scrollbar_v


def layout(headers, cells, gutter=2):
    '''(widths, xs, virt_w) — every column as wide as its longest cell (nothing truncated; h/l scrolls
    to what doesn't fit), `gutter` spaces between columns.'''
    widths = [max(len(hd), max((len(row[c]) for row in cells), default=0))
              for c, hd in enumerate(headers)]
    xs, vx = [], 0
    for wd in widths:
        xs.append(vx)
        vx += wd + gutter
    return widths, xs, max(0, vx - gutter)


def draw_table(surface, pal, rect, vm, cur, top, hscroll, h, w):
    '''Paint table `vm` into the panel interior `rect` = (inner top, left, height, width) with row
    `cur` selected: a sticky header that scrolls horizontally with the rows, the display list from
    `top`, the vertical scrollbar on the right border and the horizontal one on the bottom border.
    -> the clamped (top, hscroll).'''
    it, il, ih, iw = rect
    hscroll = max(0, min(hscroll, max(0, vm.virt_w - iw)))
    for hdr, vx0 in zip(vm.headers, vm.xs):
        _put_hscroll(surface, it, il, iw, vx0, hscroll, hdr, pal.style('menu_header', it, il, h, w))
    rows_h = max(1, ih - 1)
    disp = vm.display if vm.display is not None else [('row', i) for i in range(len(vm.cells))]
    cur_disp = next((d for d, e in enumerate(disp) if e == ('row', cur)), 0)
    top = _scroll_top(cur_disp, top, rows_h, len(disp))
    for vis, d in enumerate(range(top, min(len(disp), top + rows_h))):
        y = it + 1 + vis
        kind, val = disp[d]
        if kind == 'hdr':                                # a section rule, drawn inline
            rule = val if val.endswith(' ') else val + ' '
            _put(surface, y, il, _fit(rule + '─' * max(0, iw - len(rule)), iw),
                 pal.style('menu_header', y, il, h, w))
            continue
        sel = val == cur
        if sel:
            _put(surface, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
        roles = vm.elems[val]
        if isinstance(roles, str):
            roles = [roles] * len(vm.cells[val])
        for cell, wd, vx0, role in zip(vm.cells[val], vm.widths, vm.xs, roles):
            _put_hscroll(surface, y, il, iw, vx0, hscroll, cell.ljust(wd),
                         pal.style('label' if sel else role, y, il, h, w, selected=sel))
    _scrollbar_v(surface, pal, it + 1, il + iw, rows_h, top, rows_h, len(disp), h, w)
    _scrollbar_h(surface, pal, it + ih, il, iw, hscroll, iw, vm.virt_w, h, w)
    return top, hscroll
