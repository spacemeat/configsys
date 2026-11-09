'''modals.py — every modal and overlay — the shared frame + keymap-aware ListNav, popups, the input
box, the reorder list, the attr filter, the machine modals, find/filter edits, the `?` / `!` /
where overlays and the issue review-and-send.

Split out of menu.py (review-2026-11-2 D2).
'''

import curses
from ..attrs import ATTR_AXES, ATTR_AXIS_OF as _ATTR_AXIS_OF
from .help import help_page
from .models import COMPONENT, UNIT
from .paint import _busy, _fit, _keymap, _put, _scrollbar_v, _wordwrap, _wrap


# -- modal + overlay plumbing (review-2026-11-2 D7 / tui-core-08) -----------------------------------
# Every modal and overlay moves through the SAME keymap the panes do: the `global` scope's nav actions,
# whatever keys you bound them to (config.hu says page-down works "in all panes + modals").
_NAV_ACTIONS = ('down', 'up', 'top', 'bottom', 'page-down', 'page-up')


class ListNav:
    '''Keymap-aware movement over a list — the one implementation the modals and overlays share (they
    used to hard-code j/k/arrows and mostly ignored page/top/bottom). A position is clamped to
    [0, limit]: a cursor's limit is n-1, a scroll offset's is n - visible rows.'''

    @staticmethod
    def action(ch, scope='global'):
        '''The nav action key `ch` means, or None.'''
        act = _keymap().action_for(scope, ch)
        return act if act in _NAV_ACTIONS else None

    @staticmethod
    def apply(act, pos, limit, page):
        '''`pos` moved by nav action `act`, clamped to [0, limit]. `page` is the rows a page moves —
        or a callable giving it, asked only for a page move (a pane's page size needs the screen).'''
        if act == 'top':
            pos = 0
        elif act == 'bottom':
            pos = limit
        elif act in ('page-down', 'page-up'):
            rows = max(1, page() if callable(page) else page)
            pos += rows if act == 'page-down' else -rows
        else:
            pos += {'down': 1, 'up': -1}.get(act, 0)
        return max(0, min(pos, max(0, limit)))

    @classmethod
    def key(cls, ch, pos, limit, page, scope='global'):
        '''The new position for key `ch`, or None when `ch` isn't a nav key.'''
        act = cls.action(ch, scope)
        return None if act is None else cls.apply(act, pos, limit, page)


def _nav_glyphs():
    '''"j/k" — the down/up keys as you bound them, for a modal's hint line.'''
    km = _keymap()
    return f'{km.glyph("global", "down")}/{km.glyph("global", "up")}'


def _modal_frame(stdscr, pal, y0, x0, box_h, box_w, title, hint=None):
    '''Draw a modal's box — border, blanked interior, title on the top edge, `hint` on the bottom
    edge — and return the border attribute (the modals reuse it for their scroll arrows).'''
    border = pal.get('accent') | curses.A_BOLD
    _put(stdscr, y0, x0, '┌' + '─' * (box_w - 2) + '┐', border)
    _put(stdscr, y0, x0 + 2, f' {_fit(title, box_w - 6)} ', border)
    for r in range(1, box_h - 1):
        _put(stdscr, y0 + r, x0, '│' + ' ' * (box_w - 2) + '│', border)
    _put(stdscr, y0 + box_h - 1, x0, '└' + '─' * (box_w - 2) + '┘', border)
    if hint:
        _put(stdscr, y0 + box_h - 1, x0 + 2, _fit(f' {hint} ', box_w - 4), border)
    return border


def _keep_visible(sel, top, vis):
    '''The scroll offset that keeps row `sel` inside a `vis`-row window starting at `top`.'''
    if sel < top:
        return sel
    if sel >= top + vis:
        return sel - vis + 1
    return top


def _help_modal(stdscr, pal, screen):
    '''The per-page `?` overlay: a brief description, the live keybindings for this page, and a small
    glossary of its terms/markers. Scrollable; esc / quit / help closes. Drawn OVER the current screen.'''
    km = _keymap()
    info = help_page(screen, km)                           # its prose keys rendered through YOUR keymap
    h, w = stdscr.getmaxyx()
    box_w = min(78, max(40, w - 4))
    iw = box_w - 4
    rows = []                                              # each row is a list of (text, role, bold) segs

    def line(text, role='info', bold=False):
        rows.append([(text, role, bold)])

    for dl in _wordwrap(info.get('desc', ''), iw):
        line(dl, 'info')
    line('', 'info')
    line('keys', 'menu_header', True)
    for keys, label in km.help_rows(screen):
        rows.append([(f'{keys:>10}  ', 'scope_choice', False), (label, 'ink', False)])
    if info.get('glossary'):
        line('', 'info')
        line('glossary', 'menu_header', True)
        for term, meaning in info['glossary']:
            tw = len(term) + 2
            wrapped = _wordwrap(meaning, max(8, iw - tw))
            rows.append([(f'{term}  ', 'scope_choice', False), (wrapped[0], 'info_dim', False)])
            for cont in wrapped[1:]:
                rows.append([(' ' * tw + cont, 'info_dim', False)])

    box_h = min(len(rows) + 4, max(8, h - 2))
    vis = box_h - 4
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    top, limit = 0, max(0, len(rows) - vis)
    while True:
        _modal_frame(stdscr, pal, y0, x0, box_h, box_w, f'{screen} · help',
                     f'{_nav_glyphs()} scroll · esc/{km.glyph("global", "help")} close')
        for i in range(vis):
            idx = top + i
            if idx >= len(rows):
                break
            x = x0 + 2
            for text, role, bold in rows[idx]:
                _put(stdscr, y0 + 1 + i, x, _fit(text, x0 + box_w - 2 - x),
                     pal.get(role) | (curses.A_BOLD if bold else 0))
                x += len(text)
        _scrollbar_v(stdscr, pal, y0 + 1, x0 + box_w - 1, vis, top, vis, len(rows), h, w)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27 or km.action_for(screen, ch) in ('quit', 'help'):
            return
        moved = ListNav.key(ch, top, limit, vis, scope=screen)
        if moved is not None:
            top = moved


_DIAG_RANK = {'error': 0, 'warn': 1, 'warning': 1}   # anything softer (a note) sorts after both


def _diag_order(diags):
    '''The `!` page's order — errors, then warnings, then notes; stable within a level (as `inspect`
    and `check` list them).'''
    return sorted(diags, key=lambda d: _DIAG_RANK.get(d['level'], 2))


def _draw_diagnostics(stdscr, pal, diags, top):
    '''The `!` page: every non-fatal skip/warning, errors first, scrollable. Returns the clamped
    scroll top.'''
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    _put(stdscr, 0, 0, _fit(f' configsys — diagnostics ({len(diags)}) ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    lines = []                                       # [(text, attr)]
    for d in _diag_order(diags):
        rank = _DIAG_RANK.get(d['level'], 2)
        col = pal.get(('error', 'outdated', 'info')[rank])
        mark = ('✗', '⚠', '·')[rank]
        lines.append((f'{mark} {d["tag"]}', col | curses.A_BOLD))
        for seg in _wrap(d['text'], w - 4):
            lines.append(('    ' + seg, pal.get('dim')))
        lines.append(('', curses.A_NORMAL))
    if not diags:
        lines = [('  no issues — everything loaded cleanly.', pal.get('installed'))]
    body_h = max(1, h - 3)
    top = max(0, min(top, max(0, len(lines) - body_h)))
    for i, (text, attr) in enumerate(lines[top:top + body_h]):
        _put(stdscr, 2 + i, 0, _fit(text, w), attr)
    km = _keymap()                                   # the legend follows your `keys:` (parity-15)
    g = lambda a: km.glyph('issues', a)              # noqa: E731
    foot = (f' {g("down")}/{g("up")} scroll · {g("report")} report a component · {g("request")} request '
            f'a component · {g("suggest-os")} suggest this OS · {g("help")} help · {g("issues")} or '
            f'{g("quit")} back ')
    _put(stdscr, h - 1, 0, _fit(foot.ljust(w), w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()
    return top


def _issue_note(result):
    '''The status note after filing (a cli.issues.IssueResult), from what actually happened — never a
    saved-at path that wasn't written (a --pretend run saves nothing; a failed write leaves none).'''
    if result.filed_url:
        return f'issue filed: {result.filed_url}'
    if result.pretend:
        return '[pretend] issue not sent — nothing filed or saved'
    if result.saved_path:
        return f'not auto-filed — body saved at {result.saved_path} (open the link shown)'
    return 'not sent — could not save the body (open the link shown)'


def _report_review(stdscr, pal, ctx, title, body, label, save_as):
    '''Full-text review-and-send overlay for an issue (report / request / os-request). Shows the
    EXACTLY-what-sends scrubbed body, scrollable, so the user verifies no private info before `send`
    (`s`) files it to configsys-issues (the overlay IS the consent — no hidden send); esc / quit
    cancels. Returns a status note.'''
    from .. import reportgen
    from ..cli.issues import _file_issue
    lines = body.split('\n')
    top, result = 0, None
    km = _keymap()
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _put(stdscr, 0, 0, _fit(f' review issue — {title} '.ljust(w), w),
             pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
        _put(stdscr, 1, 0, _fit('  this is EXACTLY what will be sent — verify no private info', w),
             pal.get('dim'))
        bt, bh = 3, max(1, h - 5)
        shown = result.lines if result is not None else lines
        top = max(0, min(top, max(0, len(shown) - bh)))
        for i in range(top, min(len(shown), top + bh)):
            _put(stdscr, bt + (i - top), 0, _fit(shown[i], w), pal.get('info'))
        _scrollbar_v(stdscr, pal, bt, w - 1, bh, top, bh, len(shown), h, w)
        if result is None:
            foot = (f' {_nav_glyphs()} scroll · {km.glyph("global", "top")}/{km.glyph("global", "bottom")} '
                    f'top/bottom · {km.glyph("issue-review", "send")} SEND to {reportgen.REPORTS_REPO} · '
                    f'Esc cancel ')
        else:
            foot = f' {"filed" if result.filed_url else "not filed"} — any key to return '
        _put(stdscr, h - 1, 0, _fit(foot.ljust(w), w), pal.get('dim') | curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if result is not None:                             # showing the send result -> any key returns
            return _issue_note(result)
        act = km.action_for('issue-review', ch)
        if ch == 27 or act == 'quit':                      # Esc / quit
            return 'issue not sent'
        elif act == 'send':
            _busy(stdscr, pal, f'filing to {reportgen.REPORTS_REPO}…')
            result = _file_issue(ctx, title, body, label, save_as)
            top = 0
        else:
            moved = ListNav.key(ch, top, max(0, len(shown) - bh), bh)
            if moved is not None:
                top = moved


def _issue_flow(stdscr, pal, ctx, kind, pending_report=None):
    '''Assemble a report / request / os-request, then review-and-send it in-TUI. `kind`:
    'report' (a broken component), 'request' (full support for a component), 'os' (suggest THIS OS /
    report that an update broke it). Returns a status note, or None if cancelled at the name prompt.'''
    from .. import reportgen
    secrets = reportgen.secret_values(ctx.env)
    home = ctx.paths.home
    if kind == 'os':
        payload = reportgen.os_request_payload(ctx)
        body = reportgen.render_os_request(payload, home=home, secrets=secrets)
        return _report_review(stdscr, pal, ctx, reportgen.os_request_title(payload), body,
                              reportgen.OS_REQUEST_LABEL, 'last-os-request.md')
    if kind == 'request':
        name = _input_box(stdscr, pal, 'request full support for which component?', '')
        if not name or not name.strip():
            return None
        name = name.strip()                                # an unknown name is OK — a request to ADD it
        payload = reportgen.request_payload(ctx, name)
        body = reportgen.render_request(payload, home=home, secrets=secrets)
        return _report_review(stdscr, pal, ctx, reportgen.request_title(payload), body,
                              reportgen.REQUEST_LABEL, 'last-request.md')
    # kind == 'report' — name what a BLANK entry will file so it's an informed default
    saved = reportgen.load_failures(ctx.paths)
    captured = [f.get('component') for f in saved if f.get('component')]
    if not captured:
        blank = 'blank: nothing captured — name one'
    elif len(captured) == 1:
        blank = f'blank = {captured[0]}'
    else:
        shown = ', '.join(captured[:3]) + (f' +{len(captured) - 3} more' if len(captured) > 3 else '')
        blank = f'blank = all {len(captured)}: {shown}'
    name = _input_box(stdscr, pal, f'report which component?  ({blank})', pending_report or '')
    if name is None:
        return None
    name = name.strip()
    multi = failure = None
    if name:
        failure = next((f for f in saved if f.get('component') == name), None)
    elif len(saved) > 1:
        multi = saved
    elif len(saved) == 1:
        name, failure = saved[0].get('component'), saved[0]
    else:
        return 'nothing to report — name a component, or report after a failed install'
    payload = (reportgen.collect(ctx, failures=multi) if multi
               else reportgen.collect(ctx, component=name, failure=failure))
    body = reportgen.render(payload, home=home, secrets=secrets)
    return _report_review(stdscr, pal, ctx, reportgen.title(payload), body,
                          'install-report', 'last-report.md')


def _draw_where(stdscr, pal, lines, top, subject):
    '''The `w` full-page: the complete `configsys where` report for one component — every binding
    (valid / reachable / shadowed, the winner marked), the deciding rule, and the resolved dep tree.
    Scrollable, for the deep dive the ambient panel can't hold. Returns the clamped scroll top.'''
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    _put(stdscr, 0, 0, _fit(f' where — {subject} ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    body = []
    for ln in lines or ['(unknown component)']:
        low = ln.strip()
        if '<- default here' in ln or low.startswith('on '):
            attr = pal.get('installed') | curses.A_BOLD          # the winner / where it resolves
        elif low.startswith(('provides', 'requires', 'defined in', 'pinned')):
            attr = pal.get('accent')
        elif ln and not ln.startswith(' '):
            attr = pal.get('label') | curses.A_BOLD              # the component name header
        else:
            attr = pal.get('dim')
        body.append((ln, attr))
    body_h = max(1, h - 3)
    top = max(0, min(top, max(0, len(body) - body_h)))
    for i, (text, attr) in enumerate(body[top:top + body_h]):
        _put(stdscr, 2 + i, 0, _fit(text, w), attr)
    km = _keymap()
    foot = (f' {_nav_glyphs()} scroll · {km.glyph("global", "top")}/{km.glyph("global", "bottom")} '
            f'top/bottom · {km.glyph("components", "where")} or {km.glyph("global", "quit")} back ')
    _put(stdscr, h - 1, 0, _fit(foot.ljust(w), w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()
    return top


def _popup_choose(stdscr, pal, title, options, start=0, shortcuts=None, body=()):
    '''A modal chooser drawn OVER the current screen (no drop to the terminal). `options` is a
    list of (label, tag-string). j/k or arrows move, enter selects, esc/q cancels. Returns the
    chosen index or None. `shortcuts` is an optional {char: index} map (e.g. {'y': 0, 'n': 1}) so a
    letter jumps straight to (and picks) an option. `body`: lines shown (dim, unselectable) above the
    options — what a question is about (the commits + files a push would send). The background stays
    put; the loop redraws.'''
    h, w = stdscr.getmaxyx()
    body = list(body)[:max(0, h - len(options) - 8)]      # the choices always fit
    n = len(options)
    inner = max([len(title)] + [len(lbl) + len(tag) + 2 for lbl, tag in options]
                + [min(len(b), w - 8) for b in body] + [24])
    box_w = min(inner + 4, max(20, w - 2))
    box_h = min(n + 4 + (len(body) + 1 if body else 0), max(5, h - 2))
    nb = (len(body) + 1) if body else 0                  # body rows + a spacer
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    vis = max(1, box_h - 4 - nb)             # option rows that fit inside the box (below title + body)
    sel = start
    ptop = 0
    keys = (f'{"/".join(shortcuts)} · ' if shortcuts else '') + f'{_nav_glyphs()} · enter · esc'
    while True:
        ptop = _keep_visible(sel, ptop, vis)
        border = _modal_frame(stdscr, pal, y0, x0, box_h, box_w, title, keys)
        for r, line in enumerate(body):
            _put(stdscr, y0 + 2 + r, x0 + 2, _fit(line, box_w - 4), pal.get('dim'))
        for r, i in enumerate(range(ptop, min(n, ptop + vis))):
            label, tag = options[i]
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            _put(stdscr, y0 + 2 + nb + r, x0 + 2, _fit(label.ljust(box_w - 4), box_w - 4), attr)
            if tag:
                _put(stdscr, y0 + 2 + nb + r, x0 + box_w - 2 - len(tag), tag,
                     attr | pal.get('dim'))
        if ptop > 0:                         # more above / below than the window shows
            _put(stdscr, y0 + 1, x0 + box_w - 3, '↑', border)
        if ptop + vis < n:
            _put(stdscr, y0 + box_h - 2, x0 + box_w - 3, '↓', border)
        stdscr.refresh()
        ch = stdscr.getch()
        if shortcuts and 0 <= ch < 256:
            hit = shortcuts.get(chr(ch).lower())
            if hit is not None:
                return hit
        if ch == 27 or _keymap().action_for('global', ch) == 'quit':
            return None
        moved = ListNav.key(ch, sel, n - 1, vis)
        if moved is not None:
            sel = moved
        elif ch in (ord('\r'), curses.KEY_ENTER, curses.KEY_RIGHT):
            return sel


def _fuzzy_score(query, text):
    '''Score how well `text` fuzzy-matches `query` (case-insensitive); higher is better, None means
    no match. A contiguous substring beats a scattered subsequence; an earlier hit and a word-
    boundary start rank higher. Powers `/` find (jump the cursor to the best match).'''
    q = (query or '').lower()
    if not q:
        return None
    t = (text or '').lower()
    idx = t.find(q)
    if idx != -1:                                      # substring: the strongest kind of match
        boundary = idx == 0 or not t[idx - 1].isalnum()
        return 10000 - idx * 5 + (50 if boundary else 0)
    score, ti = 0, 0                                   # subsequence: every query char, in order
    for qc in q:
        nxt = t.find(qc, ti)
        if nxt == -1:
            return None
        score -= (nxt - ti)                            # penalize the gap skipped over
        ti = nxt + 1
    return score - ti                                  # a later finish is marginally worse


def _filter_edit(stdscr, initial, apply_fn, redraw):
    '''Live substring-FILTER entry (`F`): narrows the view to matching rows. Starts empty;
    `apply_fn(text)` sets the filter (called every keystroke so the view filters live) and
    `redraw()` repaints. Enter commits the typed text (empty text clears the filter); Esc — or
    backspace on an empty query — reverts to `initial`. A `filter:` prompt shows on the bottom line.
    Workflow: `Fgnuplot⏎` filters, `Fgod⎋` cancels, `F⌫` cancels, `F⏎` clears.'''
    buf = ''
    while True:
        apply_fn(buf)
        redraw()                                       # repaint with the live filter applied
        h, w = stdscr.getmaxyx()
        _put(stdscr, h - 1, 0, _fit(f' filter:{buf}▏', w).ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (13, curses.KEY_ENTER):
            return buf                                 # commit (empty -> cleared)
        if ch == 27:                                   # Esc -> revert to the pre-filter state
            apply_fn(initial)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not buf:                                # backspace on an empty query -> cancel too
                apply_fn(initial)
                return None
            buf = buf[:-1]
        elif 32 <= ch <= 126:
            buf += chr(ch)


def _find_next(labels, query, after):
    '''Index of the best fuzzy match for `query`, scanning from JUST AFTER `after` (wrapping). So
    among equally-good matches the next one after the cursor wins — repeated `/` with the same query
    steps sequentially through siblings (gcc-10..15, cudnn-8/9, python3.11/12/…). None = no match.'''
    best_i, best_s, n = None, None, len(labels)
    for off in range(n):
        i = (after + 1 + off) % n
        s = _fuzzy_score(query, labels[i])
        if s is not None and (best_s is None or s > best_s):
            best_i, best_s = i, s
    return best_i


def _find_edit(stdscr, labels, restore, set_cursor, redraw):
    '''Live fuzzy-FIND (`/`): as you type, jump the cursor to the best fuzzy match among `labels`
    (the visible items, index-aligned with the cursor). Find does NOT filter (that is `F`) —
    the list stays whole and only the cursor moves; type more to disambiguate. Enter keeps the
    cursor at the match; Esc — or backspace on an empty query — restores the `restore` index. A
    vim-style `/query` prompt shows on the bottom line.'''
    buf = ''

    def jump(b):
        i = _find_next(labels, b, restore)
        set_cursor(i if i is not None else restore)

    while True:
        jump(buf)                                      # empty query -> best_i None -> restore
        redraw()
        h, w = stdscr.getmaxyx()
        _put(stdscr, h - 1, 0, _fit(f' /{buf}▏', w).ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (13, curses.KEY_ENTER):
            return                                     # commit — leave the cursor at the match
        if ch == 27:                                   # Esc -> restore the pre-find cursor
            set_cursor(restore)
            return
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not buf:
                set_cursor(restore)
                return
            buf = buf[:-1]
        elif 32 <= ch <= 126:
            buf += chr(ch)


def _find_edit_tree(stdscr, ms, redraw):
    '''Live fuzzy-FIND (`/`) for the Components tree that reaches components collapsed INSIDE trees:
    it searches EVERY component/unit node (not just the visible rows), and expands the containing tree
    to reveal the best match as you type. Enter keeps it revealed; Esc — or backspace on an empty
    query — restores the pre-find expansion + cursor. Repeated `/` steps to the next match (the anchor
    is the current row), like the flat find.'''
    saved_exp = {n.id: n.expanded for n in ms._all_nodes()}
    nodes = [n for n in ms._all_nodes() if n.kind in (COMPONENT, UNIT)]
    labels = [n.label or '' for n in nodes]
    cur = ms.rows[ms.cursor].id if (ms.rows and ms.cursor < len(ms.rows)) else None
    anchor = next((i for i, n in enumerate(nodes) if n.id == cur), -1)
    buf = ''

    def reset_expansion():
        for n in ms._all_nodes():                          # collapse back to the pre-find state so only
            if n.id in saved_exp:                          # the CURRENT match's tree ends up open
                n.expanded = saved_exp[n.id]

    def jump(b):
        reset_expansion()
        i = _find_next(labels, b, anchor) if b else None
        if i is None:
            ms._refresh(keep_id=cur)                       # empty / no match -> restore the cursor
        else:
            ms.reveal_node(nodes[i])                       # expand its tree + move the cursor to it

    while True:
        jump(buf)
        redraw()
        h, w = stdscr.getmaxyx()
        _put(stdscr, h - 1, 0, _fit(f' /{buf}▏', w).ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (13, curses.KEY_ENTER):
            return                                         # commit — leave the match revealed
        if ch == 27:                                       # Esc -> restore expansion + cursor
            reset_expansion()
            ms._refresh(keep_id=cur)
            return
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not buf:
                reset_expansion()
                ms._refresh(keep_id=cur)
                return
            buf = buf[:-1]
        elif 32 <= ch <= 126:
            buf += chr(ch)


# -- Profiles screen ------------------------------------------------------
# ---- attrs filter (Profiles catalog) — faceted include/exclude over component attribute tags ----
# The axes + vocabulary (ATTR_AXES / _ATTR_AXIS_OF) live in configsys/attrs.py, outside the TUI, so
# `check`'s unknown-attr lint reads the same table. Used by the attr-filter modal + the catalog filter.


def _attr_pass(tags, inc, exc):
    '''`tags` (a set of lowercased attrs) passes the faceted filter when it has NONE of the excluded
    tags AND, for every axis the user included a tag from, at least one of that axis's included tags
    (per-axis OR, cross-axis AND). Empty inc/exc -> everything passes.'''
    if exc & tags:
        return False
    if inc:
        for axis in {_ATTR_AXIS_OF.get(t) for t in inc}:
            if not ({t for t in inc if _ATTR_AXIS_OF.get(t) == axis} & tags):
                return False
    return True


def _attr_filter_modal(stdscr, pal, inc, exc):
    '''Tri-state faceted filter over the attr axes, drawn over the screen. space cycles a tag
    neutral(·) -> include(✓) -> exclude(✗) -> neutral; `clear` (`c`) clears all; enter applies; esc /
    quit cancels. Its keys are the `attr-filter` scope (falling back to `global`).
    Returns (new_inc, new_exc) as lowercased sets, or None on cancel.'''
    rows = []                                       # ('head', axis) | ('tag', tag)
    for axis, tags in ATTR_AXES:
        rows.append(('head', axis))
        rows.extend(('tag', t) for t in tags)
    inc, exc = {x.lower() for x in inc}, {x.lower() for x in exc}
    tags = [i for i, r in enumerate(rows) if r[0] == 'tag']     # the selectable rows (not axis heads)
    sel = tags[0] if tags else 0
    top = 0
    km = _keymap()
    g = lambda a: km.glyph('attr-filter', a)          # noqa: E731
    while True:
        h, w = stdscr.getmaxyx()
        box_w = min(48, max(30, w - 4))
        vis = max(3, min(len(rows), h - 6))
        box_h = vis + 4
        y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
        top = _keep_visible(sel, top, vis)
        _modal_frame(stdscr, pal, y0, x0, box_h, box_w, 'filter catalog by attributes',
                     f'{g("select")}:·/✓/✗ · {g("clear")}:clear · enter · esc')
        for k in range(vis):
            idx = top + k
            if idx >= len(rows):
                break
            kind, val = rows[idx]
            yy = y0 + 1 + k
            if kind == 'head':
                _put(stdscr, yy, x0 + 2, _fit(val, box_w - 4), pal.get('dim') | curses.A_BOLD)
            else:
                mark = '✓' if val.lower() in inc else ('✗' if val.lower() in exc else '·')
                attr = curses.A_REVERSE if idx == sel else curses.A_NORMAL
                _put(stdscr, yy, x0 + 2, _fit(f'  [{mark}] {val}'.ljust(box_w - 4), box_w - 4), attr)
        stdscr.refresh()
        ch = stdscr.getch()
        act = km.action_for('attr-filter', ch)
        if ch == 27 or act == 'quit':
            return None
        if ch in (ord('\r'), curses.KEY_ENTER):
            return inc, exc
        moved = ListNav.key(ch, tags.index(sel) if sel in tags else 0, len(tags) - 1, vis,
                           scope='attr-filter') \
            if tags else None
        if moved is not None:                               # move over the tag rows (skip axis heads)
            sel = tags[moved]
        elif act == 'clear':
            inc.clear()
            exc.clear()
        elif act == 'select' and rows[sel][0] == 'tag':
            t = rows[sel][1].lower()
            if t in inc:                            # ✓ -> ✗
                inc.discard(t)
                exc.add(t)
            elif t in exc:                          # ✗ -> ·
                exc.discard(t)
            else:                                   # · -> ✓
                inc.add(t)


def _component_machines_modal(stdscr, pal, ctx, comp):
    '''Toggle which machines TRACK a single component (space), styled like the machines modal. Returns
    a status note. Mutates picks via actions; tracking a component also marks it seen.'''
    from .. import actions
    sel, top = 0, 0
    dim = pal.get('dim')

    def machs():
        return ctx.config.machines_current_first()

    note = ''
    km = _keymap()
    while True:
        rows = machs()
        this = ctx.config.current_machine()
        picks = ctx.config.picks()
        sel = max(0, min(sel, len(rows) - 1))
        h, w = stdscr.getmaxyx()
        box_w = min(52, max(36, w - 4))
        vis = max(3, min(len(rows), h - 7))
        box_h = vis + 5
        y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
        top = _keep_visible(sel, top, vis)
        _modal_frame(stdscr, pal, y0, x0, box_h, box_w, f'track "{comp}" on…')
        for k in range(vis):
            idx = top + k
            if idx >= len(rows):
                break
            m = rows[idx]
            on = comp in picks.get(m, ())
            tag = '  (this box)' if m == this else ''
            _put(stdscr, y0 + 1 + k, x0 + 2,
                 _fit(f'  [{"✓" if on else "·"}] {m}{tag}'.ljust(box_w - 4), box_w - 4),
                 curses.A_REVERSE if idx == sel else curses.A_NORMAL)
        _put(stdscr, y0 + box_h - 3, x0 + 2,
             _fit(f'{km.glyph("global", "select")}: toggle tracking on this machine', box_w - 4), dim)
        _put(stdscr, y0 + box_h - 2, x0 + 2, _fit('enter / esc: close', box_w - 4), dim)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27, ord('\r'), curses.KEY_ENTER) or km.action_for('global', ch) == 'quit':
            return note
        moved = ListNav.key(ch, sel, len(rows) - 1, vis)
        if moved is not None:
            sel = moved
        elif km.action_for('global', ch) == 'select':
            m = rows[sel]
            on = comp in picks.get(m, ())
            actions.set_included(ctx, comp, [m], not on)
            if not on:
                actions.mark_all_seen(ctx, [comp])       # tracking implies seen
            ctx.invalidate()
            note = f'{comp}: {"untracked from" if on else "tracked on"} {m}'


def _machines_modal(stdscr, pal, ctx, targets):
    '''Manage machines AND pick the edit-TARGET set — styled like the attr-filter modal, drawn OVER
    the screen. All editing is IN-PLACE (no sub-dialogs to linger): select (space) toggles a target;
    the `machines` key scope's use (m) sets the current box, add (a) adds (types a new row inline),
    rename (r) renames the selected row inline, remove (x) removes it (inline y/n; refuses the current
    machine). enter / esc / quit closes. Returns (target_set, note).'''
    from .. import actions
    tg = set(targets)
    note = ''
    sel, top, held_h = 0, 0, 0
    mode, buf = None, ''                              # mode: None | 'rename' | 'add' | 'confirm'
    dim = pal.get('dim')
    km = _keymap()
    g = lambda a: km.glyph('machines', a)             # noqa: E731

    def machs():
        return ctx.config.machines_current_first()

    while True:
        rows = machs()
        this = ctx.config.current_machine()
        sel = max(0, min(sel, len(rows) - 1))
        nshow = len(rows) + (1 if mode == 'add' else 0)
        h, w = stdscr.getmaxyx()
        box_w = min(52, max(36, w - 4))
        vis = max(3, min(nshow, h - 7))
        held_h = max(held_h, vis + 5)                # never shrink mid-session -> no leftover rows
        box_h = min(held_h, h - 2)
        y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
        cursor_at = nshow - 1 if mode == 'add' else sel
        top = _keep_visible(cursor_at, top, vis)
        _modal_frame(stdscr, pal, y0, x0, box_h, box_w,
                     f'target machines ({_keymap().glyph("profiles", "track-all")}/'
                     f'{_keymap().glyph("profiles", "track-one")} fan out to ✓)')
        for k in range(vis):
            idx = top + k
            if idx > nshow - 1:
                break
            yy = y0 + 1 + k
            if mode == 'add' and idx == len(rows):   # the inline new-machine row
                _put(stdscr, yy, x0 + 2, _fit(f'  [ ] {buf}▏'.ljust(box_w - 4), box_w - 4),
                     curses.A_REVERSE)
                continue
            m = rows[idx]
            is_sel = idx == sel
            if mode == 'rename' and is_sel:          # inline rename edit on the selected row
                _put(stdscr, yy, x0 + 2, _fit(f'  [{"✓" if m in tg else "·"}] {buf}▏'.ljust(box_w - 4),
                                              box_w - 4), curses.A_REVERSE)
            elif mode == 'confirm' and is_sel:       # inline remove confirmation
                _put(stdscr, yy, x0 + 2, _fit(f'  remove "{m}"?  y / n'.ljust(box_w - 4), box_w - 4),
                     pal.get('error') | curses.A_BOLD)
            else:
                mark = '✓' if m in tg else '·'
                tag = '  (this box)' if m == this else ''
                _put(stdscr, yy, x0 + 2, _fit(f'  [{mark}] {m}{tag}'.ljust(box_w - 4), box_w - 4),
                     curses.A_REVERSE if is_sel else curses.A_NORMAL)
        # legend (two lines), context-sensitive
        if mode in ('rename', 'add'):
            l1, l2 = 'type a name', 'enter:save · esc:cancel'
        elif mode == 'confirm':
            l1, l2 = 'y: remove (drops its picks)', 'n / esc: cancel'
        else:
            l1 = f'{g("select")}:target · {g("use")}:current · {g("add")}:add'
            l2 = f'{g("rename")}:rename · {g("remove")}:remove · enter/esc:close'
        _put(stdscr, y0 + box_h - 3, x0 + 2, _fit(l1, box_w - 4), dim)
        _put(stdscr, y0 + box_h - 2, x0 + 2, _fit(l2, box_w - 4), dim)
        stdscr.refresh()
        ch = stdscr.getch()

        if mode in ('rename', 'add'):                # inline text entry
            if ch == 27:
                mode, buf = None, ''
            elif ch in (ord('\r'), curses.KEY_ENTER):
                nm = buf.strip()
                if mode == 'rename':
                    old = rows[sel]
                    ok, why = actions.rename_machine(ctx, old, nm)
                    ctx.invalidate()
                    if ok and old in tg:
                        tg.discard(old); tg.add(nm)
                    note = f'renamed "{old}" → "{nm}"' if ok else why
                elif nm:
                    ok, why = actions.add_machine(ctx, nm)
                    ctx.invalidate()
                    note = f'added "{nm}"' if ok else why
                    if ok:
                        tg.add(nm)
                mode, buf = None, ''
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif 32 <= ch < 127:
                buf += chr(ch)
            continue
        if mode == 'confirm':
            if ch in (ord('y'), ord('Y')):
                rm = rows[sel]
                ok, why = actions.remove_machine(ctx, rm)   # (False, '[pretend] not saved') on --pretend
                if ok:                                # (remove_machine already cleared its picks)
                    tg.discard(rm)
                ctx.invalidate()
                note = f'removed "{rm}"' if ok else why
            mode = None
            continue

        act = km.action_for('machines', ch)
        if ch in (27, ord('\r'), curses.KEY_ENTER) or act == 'quit':
            return tg, note
        moved = ListNav.key(ch, sel, len(rows) - 1, vis, scope='machines')
        if moved is not None:
            sel = moved
        elif act == 'select':
            tg ^= {rows[sel]}                         # toggle freely — the current machine included; an
                                                     # empty set is allowed (T/t then simply no-op)
        elif act == 'use':                           # make the selected machine THIS box's current
            if rows[sel] != this:
                ok, why = actions.set_machine_active(ctx, rows[sel])
                ctx.invalidate()
                note = f'current → "{rows[sel]}"' if ok else why
                if ok:
                    sel = 0                          # current sorts first
        elif act == 'add':
            mode, buf = 'add', ''
        elif act == 'rename':
            mode, buf = 'rename', rows[sel]
        elif act == 'remove':
            if rows[sel] == this:
                note = f'can’t remove the current machine (switch with {g("use")} first)'
            else:
                mode = 'confirm'


# -- primitive: a single-line text-input modal -------------------------
def _input_box(stdscr, pal, title, initial='', complete=None, toggle=None):
    '''Modal single-line text entry over the current screen. Returns the string on Enter, or None
    on Esc. Handles printable ASCII + backspace. `complete` is an optional list of candidate strings:
    the first that extends the current text shows as a dim ghost, and Tab accepts it. `toggle` is an
    optional (label, initial_bool): it adds a checkbox line that Tab flips (when there's no
    completion to accept), and the box then returns (text, checked) — (None, checked) on Esc.'''
    h, w = stdscr.getmaxyx()
    box_w = min(max(len(title) + 4, 60), max(24, w - 2))
    box_h = 5 + (1 if toggle else 0)
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    ghost_attr = pal.get('dim')
    buf = list(initial)
    checked = bool(toggle[1]) if toggle else False

    def _match(s):
        return next((c for c in (complete or []) if c.startswith(s) and c != s), None) if s else None

    def _ret(text):
        return (text, checked) if toggle else text

    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        while True:
            border = _modal_frame(stdscr, pal, y0, x0, box_h, box_w, title,
                                  'enter · esc' + (' · tab' if (complete or toggle) else ''))
            s = ''.join(buf)
            _put(stdscr, y0 + 2, x0 + 2, _fit(s, box_w - 4).ljust(box_w - 4), curses.A_UNDERLINE)
            m = _match(s)
            if m and len(s) < box_w - 4:                 # dim autocomplete ghost after the text
                _put(stdscr, y0 + 2, x0 + 2 + len(s), _fit(m[len(s):], box_w - 4 - len(s)), ghost_attr)
            if toggle:                                   # a checkbox line (tab toggles it)
                mark = '☑' if checked else '☐'
                _put(stdscr, y0 + 3, x0 + 2, _fit(f'{mark} {toggle[0]}', box_w - 4),
                     border if checked else ghost_attr)
            try:
                stdscr.move(y0 + 2, x0 + 2 + min(len(s), box_w - 5))
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == 27:
                return _ret(None)
            if ch in (ord('\r'), curses.KEY_ENTER):
                return _ret(''.join(buf))
            if ch == ord('\t'):
                if m:
                    buf = list(m)
                elif toggle:
                    checked = not checked
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf.pop()
            elif ch == 21:                       # Ctrl-U: clear the line (replace a prefilled value)
                buf = []
            elif 32 <= ch < 127:
                buf.append(chr(ch))
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def _order_list(stdscr, pal, title, items, label=None):
    '''Reorder modal: j/k move the cursor; `space` grabs/drops the current item; while grabbed, j/k
    move THE ITEM up/down. Enter commits (returns the new order), Esc cancels (None). `label(item)`
    formats an item for DISPLAY only — the returned order is always the original items.'''
    items = list(items)
    fmt = label or str
    disp = [fmt(it) for it in items]
    h, w = stdscr.getmaxyx()
    box_w = min(max(len(title) + 4, max((len(d) for d in disp), default=0) + 10, 46), max(24, w - 2))
    box_h = min(len(items) + 5, max(7, h - 2))
    vis = max(1, box_h - 4)
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    sel, top, grabbed = 0, 0, False
    while True:
        top = _keep_visible(sel, top, vis)
        _modal_frame(stdscr, pal, y0, x0, box_h, box_w, title,
                     f'space grab · {_nav_glyphs()} move · enter · esc')
        for r, i in enumerate(range(top, min(len(items), top + vis))):
            mark = '↕' if (grabbed and i == sel) else ('▸' if i == sel else ' ')
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            _put(stdscr, y0 + 2 + r, x0 + 2,
                 _fit(f'{i + 1:>2}. {mark} {fmt(items[i])}'.ljust(box_w - 4), box_w - 4), attr)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (ord('\r'), curses.KEY_ENTER):
            return items
        if ch == ord(' '):
            grabbed = not grabbed
            continue
        act = ListNav.action(ch)
        if act is None:
            continue
        to = ListNav.apply(act, sel, len(items) - 1, vis)
        if grabbed and to != sel:                    # carry the grabbed item to its new slot
            items.insert(to, items.pop(sel))
        sel = to
