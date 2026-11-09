'''paint.py — the paint primitives every screen and modal draws with — _put / _fit, panels,
scrollbars, the gradient background, word-wrap, the row-0 screen chips — and `_keymap()` (the
active keymap the router set, else the one config.hu ships).

Split out of menu.py (review-2026-11-2 D2).
'''

import curses
from . import keyspec


def _page_rows(stdscr):
    '''One screenful of the content area — how far page-up/page-down jump the cursor.'''
    return max(1, stdscr.getmaxyx()[0] - 5)


def _columns(w):
    '''Responsive column geometry -> {col: (x, width)} for the given terminal width. NAME and
    DRIVER absorb the extra horizontal room; the two version columns (INSTALLED / LATEST) always
    get equal width. SCOPE/STATUS stay compact.'''
    start = 3                                     # after the select marker + op badge
    scope_w, status_w = 8, 9
    flex = max(24, (w - 1) - start - scope_w - status_w - 5)   # 5 inter-column gaps
    ver_w = max(9, min(12, flex // 8))            # INSTALLED == LATEST — compact (clean_version'd)
    rest = max(20, flex - 2 * ver_w)              # NAME + DRIVER absorb the freed width
    driver_w = max(7, min(rest // 4, 16))         # DRIVER: compact (driver names are short)
    name_w = max(14, rest - driver_w)                # NAME takes the rest
    nx = start
    fx = nx + name_w + 1
    scx = fx + driver_w + 1
    stx = scx + scope_w + 1
    ix = stx + status_w + 1
    lx = ix + ver_w + 1
    return {'name': (nx, name_w), 'driver': (fx, driver_w), 'scope': (scx, scope_w),
            'status': (stx, status_w), 'inst': (ix, ver_w), 'latest': (lx, ver_w)}


def _scroll_top(cursor, top, list_h, nrows):
    '''The first visible row, given a persistent scroll offset `top`: keep the cursor in view but
    only scroll when it leaves the window — so the cursor moves freely inside the viewport and
    sits on the bottom row only once the list is scrolled to its end (not pinned there the moment
    you page down). Clamped so the last page shows fully.'''
    if cursor < top:
        top = cursor
    elif cursor >= top + list_h:
        top = cursor - list_h + 1
    return max(0, min(top, max(0, nrows - list_h)))


def _scroll_reveal(parent, subtree_end, top, list_h, nrows):
    '''Scroll to reveal a just-expanded subtree spanning rows [parent .. subtree_end] as fully as
    possible, ANCHORED on the parent: a no-op if the subtree already fits in the current window;
    otherwise lift the parent toward the top so as many children as fit show beneath it (instead of
    the parent sitting at the bottom with its children below the fold). Clamped like _scroll_top.'''
    if parent < top or subtree_end >= top + list_h:      # above the view, or runs off the bottom
        top = parent                                     # -> anchor the parent at the top (clamp below)
    return max(0, min(top, max(0, nrows - list_h)))


def _reveal_subtree(keys, depths, reveal, top, list_h):
    '''The scroll offset that reveals the subtree under the row whose key is `reveal` (a node just
    expanded) — rows are given as parallel `keys` / `depths` lists; `top` unchanged when no row has
    that key. The tree screens (Components, Profiles) share it.'''
    pi = next((i for i, k in enumerate(keys) if k == reveal), None)
    if pi is None:
        return top
    end = pi
    for j in range(pi + 1, len(keys)):
        if depths[j] <= depths[pi]:
            break
        end = j
    return _scroll_reveal(pi, end, top, list_h, len(keys))


def _fit(s, width):
    return s if len(s) <= width else s[:max(0, width - 1)] + '…'


def _put(stdscr, y, x, s, attr=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    s = s[:max(0, w - x)]
    try:
        stdscr.addstr(y, x, s, attr)
    except curses.error:
        pass


def _wrap(s, width):
    '''Hard char-wrap (paths rarely have useful word breaks), never empty.'''
    s, width = s or '', max(1, width)
    return [s[i:i + width] for i in range(0, len(s), width)] or ['']


def _wordwrap(s, width):
    '''Word-wrap `s` to `width` columns (break on spaces; hard-split a word longer than the line).
    Never empty — for prose like setting descriptions.'''
    width = max(1, width)
    lines, cur = [], ''
    for wd in (s or '').split():
        while len(wd) > width:                          # a single word longer than the line
            if cur:
                lines.append(cur); cur = ''
            lines.append(wd[:width]); wd = wd[width:]
        if not cur:
            cur = wd
        elif len(cur) + 1 + len(wd) <= width:
            cur += ' ' + wd
        else:
            lines.append(cur); cur = wd
    if cur or not lines:
        lines.append(cur)
    return lines


def _keymap():
    '''The live keymap (your `keys:`, which the router — menu.run — sets), or the one config.hu ships
    outside a run (tests, samples) — so no legend or modal keeps its own copy of the defaults.'''
    from . import menu
    return menu._KEYMAP if menu._KEYMAP is not None else keyspec.shipped_keymap()


# The constant-band SEGMENT GEOMETRY of the diagonal gradient is a pure function of the gradient
# length + (h, w) — identical every frame — so cache it and skip the per-cell band() scan that found
# the boundaries (~a third of a Profiles repaint). NOT the resolved fill attr: the palette recycles
# its 8-bit color pairs every frame (new_frame), so a cached attr's pair number would map to the wrong
# colour a frame later (banding/skew). fill() is recomputed per SEGMENT each frame — cheap, and it
# hits the per-frame pair cache, so it allocates once per distinct band, not once per cell.
_FILL_BG_SEGS = {}           # (grad_len, h, w) -> [(y, x, width)]


def _fill_bg(stdscr, pal, h, w):
    '''Paint the diagonal gradient behind the whole screen, in constant-band segments per row.'''
    glen = len(getattr(pal, '_grad_bg', ()) or (None,))   # segment layout depends on the band count
    key = (glen, h, w)
    segs = _FILL_BG_SEGS.get(key)
    if segs is None:
        segs = []
        for y in range(h):
            x = 0
            while x < w:
                b = pal.band(y, x, h, w)
                x2 = x + 1
                while x2 < w and pal.band(y, x2, h, w) == b:
                    x2 += 1
                width = x2 - x - (1 if (y == h - 1 and x2 == w) else 0)   # skip the corner cell
                if width > 0:
                    segs.append((y, x, width))
                x = x2
        if len(_FILL_BG_SEGS) > 64:                        # bound it (a few band counts × window sizes)
            _FILL_BG_SEGS.clear()
        _FILL_BG_SEGS[key] = segs
    for y, x, width in segs:
        try:
            stdscr.addstr(y, x, ' ' * width, pal.fill(y, x, h, w))   # per-frame attr (correct pair)
        except curses.error:
            pass


# -- screen router / nav bar ----------------------------------------------
SCREENS = [('1', 'components', 'Components'), ('2', 'profiles', 'Profiles'),
           ('3', 'plugins', 'Plugins'), ('4', 'glue', 'Glue'), ('5', 'dotfiles', 'Dotfiles'),
           ('6', 'config', 'Config'), ('7', 'theme', 'Theme')]


IMPLEMENTED = {'components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config', 'theme'}


KEY_TO_SCREEN = {ord(k): sid for k, sid, _name in SCREENS}


def _draw_nav(stdscr, pal, screen, h, w):
    '''Row-0 chip bar: press a number to switch screens. Unbuilt screens are dimmed. The switch key
    and the issues/quit hint come from the keymap, so a rebind shows here too.'''
    x = 0
    km = _keymap()
    for _key, sid, name in SCREENS:
        chip = f' {km.glyph("screens", sid)} {name} '
        elem = 'label' if sid == screen else ('menu_header' if sid in IMPLEMENTED else 'info_dim')
        _put(stdscr, 0, x, chip, pal.style(elem, 0, x, h, w))
        x += len(chip) + 1
    hint = f' {km.glyph("global", "issues")} issues · {km.glyph("global", "quit")} quit '
    _put(stdscr, 0, max(x + 1, w - len(hint) - 1), _fit(hint, w - x), pal.style('footer', 0, x, h, w))


def _busy(stdscr, pal, msg):
    '''Flash a centered "working…" indicator + refresh, before a synchronous freeze (e.g. the claim
    scan). No input; the next full redraw paints over it.'''
    h, w = stdscr.getmaxyx()
    s = f'  {msg}  '
    _put(stdscr, h // 2, max(0, (w - len(s)) // 2), s,
         pal.get('accent') | curses.A_BOLD | curses.A_REVERSE)
    stdscr.refresh()


# -- F2 primitive: a bordered panel ---------------------------------------
def _panel(stdscr, pal, top, left, height, width, title, focused, h, w):
    '''Draw a bordered box; return (inner_top, inner_left, inner_h, inner_w) for its content.'''
    elem = 'menu_header' if focused else 'info_dim'
    bar = '─' * (width - 2)
    _put(stdscr, top, left, '┌' + bar + '┐', pal.style(elem, top, left, h, w))
    for r in range(top + 1, top + height - 1):
        _put(stdscr, r, left, '│', pal.style(elem, r, left, h, w))
        _put(stdscr, r, left + width - 1, '│', pal.style(elem, r, left + width - 1, h, w))
    _put(stdscr, top + height - 1, left, '└' + bar + '┘', pal.style(elem, top + height - 1, left, h, w))
    if title:
        te = 'label' if focused else 'menu_header'
        _put(stdscr, top, left + 2, _fit(f' {title} ', width - 4), pal.style(te, top, left + 2, h, w))
    return top + 1, left + 1, height - 2, width - 2


def _thumb(span, offset, window, total):
    '''(pos, size) of a scrollbar thumb along a track of `span` cells, or None when everything fits.
    `window` items are visible starting at `offset` of `total`.'''
    if total <= window or span < 2:
        return None
    size = max(1, min(span, round(span * window / total)))
    maxoff = total - window
    pos = round((span - size) * offset / maxoff) if maxoff > 0 else 0
    return max(0, min(span - size, pos)), size


def _scrollbar_v(stdscr, pal, top, col, rows, offset, window, total, h, w):
    '''Overlay a vertical scrollbar on a panel's right border column: the track reuses the border,
    an accent thumb shows the visible fraction + position. No-op when it all fits.'''
    t = _thumb(rows, offset, window, total)
    if t is None:
        return
    pos, size = t
    for k in range(rows):
        on = pos <= k < pos + size
        _put(stdscr, top + k, col, '█' if on else '│',
             pal.style('select_marker' if on else 'info_dim', top + k, col, h, w))


def _scrollbar_h(stdscr, pal, row, left, cols, offset, window, total, h, w):
    '''Overlay a horizontal scrollbar on a panel's bottom border row (accent thumb over `─`).'''
    t = _thumb(cols, offset, window, total)
    if t is None:
        return
    pos, size = t
    for k in range(cols):
        on = pos <= k < pos + size
        _put(stdscr, row, left + k, '🬋' if on else '─',     # a vertically-centred bar, like the v-thumb
             pal.style('select_marker' if on else 'info_dim', row, left + k, h, w))


def _hex(rgb):
    return '#%02x%02x%02x' % (rgb[0], rgb[1], rgb[2])


def _eff_flags(st):
    return ((curses.A_BOLD if st.get('bold') else 0)
            | (curses.A_UNDERLINE if st.get('underline') else 0)
            | (curses.A_REVERSE if st.get('reverse') else 0))


def _put_hscroll(stdscr, y, left, win_w, vx, hscroll, text, attr):
    '''Draw `text` starting at virtual column `vx`, clipped to a window `win_w` wide scrolled by
    `hscroll` — the primitive behind the plugins table's horizontal (h/l) scroll.'''
    start = vx - hscroll
    if start >= win_w or start + len(text) <= 0:
        return
    if start < 0:
        text, start = text[-start:], 0
    _put(stdscr, y, left + start, text[:win_w - start], attr)
