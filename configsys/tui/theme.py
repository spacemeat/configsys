'''theme.py — color for the TUI, 24-bit when the terminal allows it.

The model is two tiers (spec: docs/theming.md):

- a shared **color map** — a name -> #rrggbb dict (`theme.colors`); and
- **pages** — each screen's ROLES carry a style `{ fg, bg, bold, underline, reverse }` where fg/bg
  are a color-map NAME or a literal color; plus that page's background **gradient**.

A role's style defaults to a built-in (uniform across pages); a page overrides just what differs,
so per-page divergence is opt-in. fg/bg resolve against the shared map, so retinting one map color
re-tints every role that references it. Every page gets a distinct default gradient.

Rendering: true 24-bit via `curses.init_color` when the terminal can change colors (or a
direct-color terminal where the color number IS the packed RGB); otherwise the xterm-256 cube, or
the basic 8. The diagonal background GRADIENT is only painted under true 24-bit with `effects: full`
(or unset), and a page whose `gradient:` isn't off. `Palette.color_mode`
names what the terminal actually gave us (shown on the Theme screen).
'''

import curses

# The shared color MAP: a name -> rgb (0-255). `theme.colors.<name>` overrides one or adds a new
# name; roles reference these by name (or use a literal color).
COLOR_MAP = {
    'header': (120, 200, 255), 'title': (235, 235, 235), 'accent': (200, 140, 240),
    'dim': (120, 120, 120), 'ink': (220, 220, 220), 'ink_dim': (154, 154, 154),
    'installed': (90, 200, 120), 'outdated': (230, 190, 70), 'partial': (90, 190, 205),
    'missing': (150, 150, 150), 'locked': (110, 165, 255), 'unsupported': (110, 110, 110),
    'untrusted': (220, 140, 60), 'error': (235, 95, 95),
    # routing statuses (stranded.py): installed via a method routes no longer offer (switch), only a
    # disabled driver could install it (unmet), no method on this OS at all (dangling)
    'switch': (240, 150, 210), 'unmet': (175, 155, 110), 'dangling': (205, 110, 140),
    # the Profiles screen's install overlay: the colour for an installed-but-untracked component (⊙)
    # and a staged-for-uninstall one (⮾)
    'orphan_lurking': (150, 180, 220),
    'op_install': (90, 200, 120), 'op_upgrade': (230, 190, 70), 'op_remove': (235, 95, 95),
    'op_lock': (110, 165, 255), 'op_unlock': (120, 210, 210),
    'sel_bg': (58, 34, 88),
    'row_desc': (108, 112, 128),                         # faded inline component descriptions
    'method_dim': (124, 150, 176),                       # muted slate-blue for the method label
    'dep_dim': (192, 158, 108),                          # muted amber for the "required by" line
    'menu_new': (150, 205, 165),                          # NEW (undispositioned) components (◆, ⁺N)
}

# --- low-color (8/16) hand-tuning ---------------------------------------------------------------
# Quantizing the 24-bit map into 8 ANSI hues loses too much (greys collapse, everything muddies).
# BASIC_MAP pins each built-in color NAME to an explicit ANSI slot for the 8/16-color path — the ONLY
# way to reach the bright set (8..15), which is where the legible low-color look lives. A user's
# `theme.colors-basic` (same name -> slot) overrides/extends this. In 256/truecolor mode it's unused.
ANSI8 = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']

BASIC_MAP = {
    'header': 'bright-blue', 'title': 'bright-white', 'accent': 'bright-magenta',
    'dim': 'bright-black', 'ink': 'white', 'ink_dim': 'bright-black',
    'installed': 'bright-green', 'outdated': 'bright-yellow', 'partial': 'bright-cyan',
    'missing': 'bright-black', 'locked': 'blue', 'unsupported': 'bright-black',
    'untrusted': 'yellow', 'error': 'bright-red',
    'switch': 'bright-magenta', 'unmet': 'yellow', 'dangling': 'magenta',
    'orphan_lurking': 'cyan',
    'op_install': 'bright-green', 'op_upgrade': 'bright-yellow', 'op_remove': 'bright-red',
    'op_lock': 'blue', 'op_unlock': 'cyan',
    'sel_bg': 'magenta',                                 # the selection-bar background in 8/16-color
    'row_desc': 'bright-black', 'method_dim': 'bright-black', 'dep_dim': 'yellow',
    'menu_new': 'green',                                  # non-bright green: NEW, not the installed set
}


def parse_ansi(val):
    '''An ANSI color slot for the low-color path: one of the 8 names (black red green yellow blue
    magenta cyan white), a `bright-<name>` (slots 8..15), `grey`/`gray` (= bright-black), a bare int
    0..15, or `default`/`term` (-1, the terminal's own default). Returns the index, -1, or None.'''
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if -1 <= val <= 15 else None
    s = str(val).strip().lower().replace('_', '-')
    if s in ('default', 'term', 'terminal', '-1'):
        return -1
    if s.lstrip('-').isdigit():
        n = int(s)
        return n if 0 <= n <= 15 else None
    bright = False
    if s.startswith('bright-'):
        bright, s = True, s[7:]
    elif s.endswith('-bright'):
        bright, s = True, s[:-7]
    if s in ('grey', 'gray'):
        return 15 if bright else 8                       # grey == bright-black; bright-grey -> white
    if s in ANSI8:
        return ANSI8.index(s) + (8 if bright else 0)
    return None


def ansi_name(idx):
    '''The canonical name for an ANSI slot (inverse of parse_ansi) — for a readable full_snapshot.'''
    if idx == -1:
        return 'default'
    if 0 <= idx <= 7:
        return ANSI8[idx]
    if 8 <= idx <= 15:
        return 'bright-' + ANSI8[idx - 8]
    return str(idx)


def resolve_basic(theme, colors):
    '''The low-color (8/16) override as {map name: ansi_index}: the built-in BASIC_MAP overlaid by
    `theme.colors-basic` (both name -> ANSI slot). Keyed by color-map NAME, so the Palette gives each
    role that references that name its slot before quantizing — and overriding one name never
    recolors another that happens to share its rgb (`installed` / `op_install`; tui-theme-13). Names
    absent from the map (`colors`) or with an unparseable slot are skipped.'''
    theme = theme if isinstance(theme, dict) else {}
    out = {}

    def apply(items):
        for name, val in items:
            idx = parse_ansi(val)
            if name in colors and idx is not None:
                out[name] = idx

    apply(BASIC_MAP.items())
    ub = theme.get('colors-basic')
    if isinstance(ub, dict):
        apply(ub.items())
    return out


GRAD_MAX_BANDS = 96         # cap on the (range-adaptive) number of diagonal gradient steps


def _role_style(fg, bg=None, bold=False, underline=False, reverse=False):
    '''A built-in role style; fg/bg are color-map NAMES (resolved against COLOR_MAP at use).'''
    st = {'fg': fg}
    if bg:
        st['bg'] = bg
    if bold:
        st['bold'] = True
    if underline:
        st['underline'] = True
    if reverse:
        st['reverse'] = True
    return st


# Built-in role styles — the default look, uniform across pages. Each page overrides only what it
# wants to differ. fg/bg are map names; `selection` is the cursor row (its bg is the selected bar).
ROLE_DEFAULTS = {
    'label': _role_style('title', bg='accent', bold=True),       # the `configsys` chip
    'os': _role_style('header', bold=True),
    'issue_error': _role_style('error', bold=True, reverse=True),
    'issue_warning': _role_style('outdated', bold=True, reverse=True),
    'menu_header': _role_style('dim', bold=True),
    'select_marker': _role_style('accent', bold=True),
    'profile': _role_style('accent', bold=True),
    'link': _role_style('accent', bold=True),
    'component': _role_style('title', bold=True),
    'unit': _role_style('title'),
    'driver': _role_style('dim'),
    'scope': _role_style('dim'),
    'scope_choice': _role_style('accent'),
    'version': _role_style('dim'),
    'row_error': _role_style('error'),
    'methods': _role_style('header'),
    'method_dim': _role_style('method_dim'),          # muted method label (Profiles detail pane)
    'dependents': _role_style('dep_dim'),             # "required by" reverse-deps (Profiles detail)
    'menu_new': _role_style('menu_new', bold=True),   # Profiles: NEW (undispositioned) components + ⁺N badges
    'row_desc': _role_style('row_desc'),              # faded description trailing the row name
    'info': _role_style('accent'),
    'info_dim': _role_style('dim'),
    'status_line': _role_style('accent'),
    'footer': _role_style('dim', reverse=True),
    'selection': _role_style('title', bg='sel_bg', bold=True),
    'installed': _role_style('installed'), 'outdated': _role_style('outdated'),
    'partial': _role_style('partial'), 'missing': _role_style('missing'),
    'locked': _role_style('locked'), 'unsupported': _role_style('unsupported'),
    'untrusted': _role_style('untrusted'), 'error': _role_style('error'),
    'switch': _role_style('switch', bold=True), 'unmet': _role_style('unmet'),
    'dangling': _role_style('dangling'),
    'orphan_lurking': _role_style('orphan_lurking'),
    'op_install': _role_style('op_install', bold=True), 'op_upgrade': _role_style('op_upgrade', bold=True),
    'op_remove': _role_style('op_remove', bold=True), 'op_lock': _role_style('op_lock', bold=True),
    'op_unlock': _role_style('op_unlock', bold=True), 'op_mixed': _role_style('accent', bold=True),
    # Plugins diff pane: added/removed lines and the hunk/meta gutter (git-diff green/red).
    'diff_add': _role_style('installed'), 'diff_del': _role_style('error'),
    'diff_hunk': _role_style('partial', bold=True), 'diff_meta': _role_style('dim'),
    # raw passthrough roles for direct get() references (identity -> the same-named map color)
    'accent': _role_style('accent'), 'dim': _role_style('dim'), 'title': _role_style('title'),
    'header': _role_style('header'),
}

# The TUI's screens in nav order: (id, title, default switch key). The ONE list (tui-theme-21) —
# ALL_PAGES, keyspec's screen ids / fallback switcher / the theme's page-N actions, the nav bar's
# chips and `configsys keys`' order derive from it; config.hu's `screens:` keys and PAGE_ROLES /
# BUILTIN_GRADIENTS below are per-page data, pinned to it by test_theme.
SCREEN_REGISTRY = (('components', 'Components', '1'), ('profiles', 'Profiles', '2'),
                   ('plugins', 'Plugins', '3'), ('glue', 'Glue', '4'), ('dotfiles', 'Dotfiles', '5'),
                   ('config', 'Config', '6'), ('theme', 'Theme', '7'))

# Every page, in nav order; the content screens the Theme editor previews are all but its own.
ALL_PAGES = [sid for sid, _title, _key in SCREEN_REGISTRY]
DEMO_PAGES = [p for p in ALL_PAGES if p != 'theme']

# The roles each SCREEN actually uses — drives both the editor's per-page list (list 2) and its
# sample mock, so they swap as you cycle pages and show only what that page needs.
PAGE_ROLES = {   # recorded from each screen's real paint (review-2026-11-2 tui-theme-08)
    'components': ['label', 'os', 'issue_warning', 'issue_error', 'menu_header', 'profile', 'link',
                   'component', 'unit', 'driver', 'version', 'scope', 'scope_choice', 'installed',
                   'outdated', 'partial', 'missing', 'locked', 'switch', 'unmet', 'dangling', 'error',
                   'unsupported', 'op_install', 'op_upgrade', 'op_remove', 'op_lock', 'op_mixed',
                   'row_error', 'row_desc', 'methods', 'info', 'info_dim', 'status_line', 'footer',
                   'selection', 'select_marker'],
    'profiles':  ['label', 'menu_header', 'profile', 'link', 'component', 'installed', 'menu_new',
                  'info', 'info_dim', 'dependents', 'method_dim', 'orphan_lurking', 'issue_warning',
                  'status_line', 'footer', 'selection', 'select_marker'],
    'plugins':   ['label', 'menu_header', 'component', 'installed', 'locked', 'untrusted', 'error',
                  'accent', 'diff_add', 'diff_del', 'diff_hunk', 'diff_meta', 'info', 'info_dim',
                  'status_line', 'footer', 'select_marker'],
    'glue':      ['label', 'menu_header', 'component', 'installed', 'outdated', 'info_dim',
                  'status_line', 'footer', 'selection', 'select_marker'],
    'dotfiles':  ['label', 'menu_header', 'component', 'installed', 'outdated', 'info_dim',
                  'status_line', 'footer', 'selection'],
    'config':    ['label', 'menu_header', 'component', 'scope', 'scope_choice', 'installed',
                  'outdated', 'header', 'method_dim', 'info_dim', 'status_line', 'footer', 'selection',
                  'select_marker'],
    'theme':     ['label', 'menu_header', 'info_dim', 'component', 'unit', 'status_line', 'footer',
                  'selection', 'select_marker'],
}

# Each page's default background gradient (top-left -> bottom-right) — a distinct dark hue per page,
# for the whims. Kept genuinely dark (brightest corner stays low) so text always reads over it.
BUILTIN_GRADIENTS = {
    'components': ((20, 10, 30), (5, 2, 10)),      # purple
    'profiles':   ((7, 24, 20), (2, 8, 6)),        # teal
    'plugins':    ((8, 18, 34), (2, 5, 12)),       # blue
    'glue':       ((10, 26, 14), (3, 8, 4)),       # green
    'dotfiles':   ((28, 20, 8), (8, 6, 2)),        # amber
    'config':     ((16, 17, 34), (4, 4, 12)),      # indigo/slate
    'theme':      ((32, 11, 24), (9, 3, 7)),       # rose
}


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _truthy(v):
    '''A style boolean. humon materializes `true`/`false` as strings, so treat 'false'/'no'/'0'
    as off (a bare `if v` would count the string 'false' as true).'''
    if isinstance(v, str):
        from ..layers import parse_bool               # the one bool spelling (D1)
        return parse_bool(v, False)
    return bool(v)


def is_off(v):
    '''An explicit OFF switch: False or an off token (false/no/off/0, any case — layers.parse_bool),
    or a dict whose `enabled` is one (`gradient: { enabled: 0 }`). None / anything else is not off.
    The one test every gradient / splash opt-out reads (tui-theme-14).'''
    if isinstance(v, dict):
        return is_off(v.get('enabled'))
    if v is None:
        return False
    from ..layers import parse_bool
    return parse_bool(v, True) is False


def parse_color(v):
    '''An (r,g,b) 0-255 tuple from a hex string ("#rrggbb"/"#rgb"), an [r,g,b] list, or an
    "r,g,b" string; None if unparseable.'''
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in v)
        except (TypeError, ValueError):
            return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) == 6 and all(c in '0123456789abcdefABCDEF' for c in h):   # int('-1', 16) parses
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return None
    if ',' in s:
        try:
            parts = [int(p) for p in s.split(',')]
        except ValueError:
            return None
        return tuple(max(0, min(255, c)) for c in parts) if len(parts) == 3 else None
    return None


_ROLE_ATTRS = ('fg', 'bg', 'bold', 'underline', 'reverse')


# the sections a `theme:` block may hold (anything else is never read)
THEME_SECTIONS = frozenset({'colors', 'colors-basic', 'pages', 'splash'})


def theme_problems(theme, colors=None):
    '''What a `theme:` section says that the TUI would silently ignore — an unknown page or role, a
    color that doesn't parse, a role attribute that isn't fg/bg/bold/underline/reverse — as
    [(dotted key, why)]. For `check` and `theme set` (G6 / tui-theme-15).'''
    out = []
    if not isinstance(theme, dict):
        return out
    for section in theme:                              # `theme set accent …` must not land unread
        if section not in THEME_SECTIONS:
            out.append((str(section), f'no such theme section ({", ".join(sorted(THEME_SECTIONS))}; '
                                      'a color is colors.<name>)'))
    names = set(COLOR_MAP) | set((theme.get('colors') or {}) if isinstance(theme.get('colors'), dict) else ())

    def color_ok(v):
        return v in (None, '', 'none', False, 'false') or v in names or parse_color(v) is not None
    for name, v in (theme.get('colors') or {}).items() if isinstance(theme.get('colors'), dict) else ():
        if parse_color(v) is None and v not in names:
            out.append((f'colors.{name}', f'{v!r} is not a color (#rrggbb, #rgb, "r,g,b" or a map name)'))
    pages = theme.get('pages') if isinstance(theme.get('pages'), dict) else {}
    for page, spec in pages.items():
        if page not in ALL_PAGES:
            out.append((f'pages.{page}', f'no such page (pages: {", ".join(ALL_PAGES)})'))
            continue
        for role, st in (spec.items() if isinstance(spec, dict) else ()):
            key = f'pages.{page}.{role}'
            if role == 'gradient':
                if isinstance(st, dict):
                    for end in ('from', 'to'):
                        if end in st and not color_ok(st[end]):
                            out.append((f'{key}.{end}', f'{st[end]!r} is not a color'))
                continue
            if role not in ROLE_DEFAULTS:
                out.append((key, 'no such role'))
                continue
            for attr, v in (st.items() if isinstance(st, dict) else ()):
                if attr not in _ROLE_ATTRS:
                    out.append((f'{key}.{attr}', f'not a role attribute ({", ".join(_ROLE_ATTRS)})'))
                elif attr in ('fg', 'bg') and not color_ok(v):
                    out.append((f'{key}.{attr}', f'{v!r} is not a color or a color-map name'))
    return out


def _ref_rgb(ref, colors):
    '''Resolve a role fg/bg reference: a color-map NAME -> its rgb, else a literal color value.'''
    if isinstance(ref, str) and ref in colors:
        return colors[ref]
    return parse_color(ref)


def resolve_theme(theme):
    '''Merge a `theme:` override dict (already layer-merged by Config.theme — {colors, pages,
    splash}) onto the built-ins. Pure — no curses. Returns (colors, pages):

    - colors: {name: (r,g,b)} — the resolved shared map;
    - pages:  {page: {'roles': {role: {fg:(r,g,b), bg:(r,g,b)|None, bold, underline, reverse,
                                        fg_name, bg_name}},
               'grad': (from, to, enabled), 'sel_bg': (r,g,b)|None, 'sel_bg_name': str|None}}.
    '''
    theme = theme if isinstance(theme, dict) else {}
    colors = dict(COLOR_MAP)
    for name, val in (theme.get('colors') or {}).items():
        rgb = parse_color(val)
        if rgb:
            colors[name] = rgb

    upages = theme.get('pages') or {}
    pages = {}
    for page in ALL_PAGES:
        spec = upages.get(page) if isinstance(upages.get(page), dict) else {}
        roles = {}
        for role, dfl in ROLE_DEFAULTS.items():
            st = dict(dfl)
            ov = spec.get(role)
            if isinstance(ov, dict):
                st.update(ov)                         # per-page fg/bg/effect override
            fg = _ref_rgb(st.get('fg'), colors) or (235, 235, 235)
            bgref = st.get('bg')
            bg = _ref_rgb(bgref, colors) if bgref not in (None, '', 'none', 'false', False) else None
            if bg == fg:                              # never paint text invisibly on its own color
                bg = None
            fgref = st.get('fg')
            roles[role] = {'fg': fg, 'bg': bg, 'bold': _truthy(st.get('bold')),
                           'underline': _truthy(st.get('underline')), 'reverse': _truthy(st.get('reverse')),
                           # the color-map NAMES behind fg/bg (None for a literal) — the 8/16-color
                           # path picks a name's colors-basic slot by name, not by rgb
                           'fg_name': fgref if isinstance(fgref, str) and fgref in colors else None,
                           'bg_name': (bgref if bg is not None and isinstance(bgref, str)
                                       and bgref in colors else None)}
        ga, gb = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        enabled = True
        g = spec.get('gradient')
        if is_off(g):
            enabled = False
        if isinstance(g, dict):
            ga = _ref_rgb(g.get('from'), colors) or ga   # endpoints may name a map color or literal
            gb = _ref_rgb(g.get('to'), colors) or gb
        pages[page] = {'roles': roles, 'grad': (ga, gb, enabled), 'sel_bg': roles['selection']['bg'],
                       'sel_bg_name': roles['selection']['bg_name']}
    return colors, pages


def full_snapshot(theme):
    '''The COMPLETE current theme as a self-contained two-tier dict — every color-map entry
    (name -> #rrggbb) and, per page (the Theme page too), EVERY role that page uses (fg/bg refs + effects) plus
    the gradient endpoints — resolved from the built-in defaults overlaid by `theme`. Unlike the
    diff overrides (theme_overrides), this pins the whole look so a saved pack reproduces exactly
    even if built-in defaults later change. fg/bg stay as refs (map names or literals) so the map is
    still the single place to retint; the full map is saved alongside, so the refs always resolve.'''
    colors, pages = resolve_theme(theme)
    upages = (theme.get('pages') if isinstance(theme, dict) else None) or {}
    out_pages = {}
    for page in ALL_PAGES:                                # the Theme page too (B8)
        spec = upages.get(page) if isinstance(upages.get(page), dict) else {}
        pg = {}
        # every role the page paints, plus any role you overrode there that the list doesn't name —
        # a pack must reproduce the WHOLE look, and promote then drops the local copy (B8)
        extra = [r for r in spec if r != 'gradient' and r not in PAGE_ROLES.get(page, [])]
        for role in list(PAGE_ROLES.get(page, [])) + extra:
            st = dict(ROLE_DEFAULTS.get(role, {}))
            ov = spec.get(role)
            if isinstance(ov, dict):
                st.update(ov)
            entry = {'fg': st.get('fg', 'title')}
            if st.get('bg') not in (None, '', 'none', 'false', False):
                entry['bg'] = st['bg']
            for fl in ('bold', 'underline', 'reverse'):
                if _truthy(st.get(fl)):
                    entry[fl] = True
            pg[role] = entry
        g = spec.get('gradient') if isinstance(spec.get('gradient'), dict) else {}
        ga, gb = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        grad = {'from': g.get('from') or '#%02x%02x%02x' % ga,
                'to': g.get('to') or '#%02x%02x%02x' % gb}
        if not pages[page]['grad'][2]:
            grad['enabled'] = False
        pg['gradient'] = grad
        out_pages[page] = pg
    basic = dict(BASIC_MAP)                               # the full low-color map, spelled out
    ub = theme.get('colors-basic') if isinstance(theme, dict) else None
    if isinstance(ub, dict):
        for name, val in ub.items():
            idx = parse_ansi(val)
            if idx is not None:
                basic[name] = ansi_name(idx)             # normalize the override to a canonical name
    return {'colors': {name: '#%02x%02x%02x' % rgb for name, rgb in colors.items()},
            'colors-basic': basic, 'pages': out_pages}


_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)      # the xterm-256 cube's real (non-linear) channel levels


def rgb_to_256(r, g, b):
    '''The NEAREST xterm-256 entry (16..255) to an rgb: each channel snapped to the nearest real cube
    level (0, 95, 135, 175, 215, 255 — not a linear 0..5), compared against the nearest grey-ramp
    entry (8 + 10k), whichever is closer (tui-theme-16).'''
    def level(c):
        return min(range(6), key=lambda i: abs(_CUBE_LEVELS[i] - c))
    cube = 16 + 36 * level(r) + 6 * level(g) + level(b)
    grey = 232 + max(0, min(23, round(((r + g + b) / 3 - 8) / 10)))
    rgb = (r, g, b)
    return grey if _dist2(xterm_rgb(grey), rgb) < _dist2(xterm_rgb(cube), rgb) else cube


# xterm's standard rgb for the 16 ANSI slots (what a -direct terminfo needs packed for 8..15)
_ANSI16_RGB = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
               (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
               (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def xterm_rgb(idx):
    '''The rgb an xterm-256 palette index stands for (0..15 ANSI, 16..231 the cube, 232..255 greys).'''
    if idx < 16:
        return _ANSI16_RGB[idx]
    if idx < 232:
        i = idx - 16
        lv = [0, 95, 135, 175, 215, 255]
        return lv[i // 36], lv[(i // 6) % 6], lv[i % 6]
    v = 8 + (idx - 232) * 10
    return v, v, v


def rgb_to_basic8(r, g, b):
    '''Nearest of the 8 ANSI colors. Low-saturation colors are GREY (which the 8-color set lacks), so
    map those to black/white by brightness rather than forcing a hue — the old hue-first version sent
    mid-greys to yellow and leaned red. Saturated colors bucket into the 6 hues: a channel counts as
    "on" at >=60% of the brightest, and R + 2·G + 4·B is exactly the ANSI color order (black=0 … white=7).'''
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 40:                                   # near-grey: no grey in the 8-color set
        return curses.COLOR_BLACK if mx < 100 else curses.COLOR_WHITE
    t = mx * 0.6
    return (1 if r >= t else 0) + 2 * (1 if g >= t else 0) + 4 * (1 if b >= t else 0)


def env_color_cap(env=None):
    '''Resolve a color-depth CAP from the environment — it only clamps the detected mode DOWN, never
    up (you can't fake 24-bit on an 8-color tty). Precedence: an explicit --color / --nocolor
    (`CONFIGSYS_COLOR_FLAG`, which _main sets; `auto` = detect) > `NO_COLOR` (any non-empty value,
    per no-color.org: a default a per-run flag overrides) forcing monochrome > your `CONFIGSYS_COLOR`.
    Returns one of 'none'|'basic8'|'basic16'|'256'|'truecolor', or None for auto-detect. `basic8`
    forces the base 8 (no bright slots); `basic16` allows the bright ANSI colors 8..15.'''
    import os
    env = os.environ if env is None else env
    v = (env.get('CONFIGSYS_COLOR_FLAG') or '').strip().lower()
    if not v:
        if (env.get('NO_COLOR') or '').strip():
            return 'none'
        v = (env.get('CONFIGSYS_COLOR') or '').strip().lower()
    if v in ('none', 'no', 'off', '0', 'mono', 'nocolor'):
        return 'none'
    if v in ('8', '8color'):
        return 'basic8'
    if v in ('16', 'basic', 'ansi', '16color'):
        return 'basic16'
    if v in ('256', '256color', '8bit'):
        return '256'
    if v in ('24bit', '24', 'truecolor', 'direct', 'rgb'):
        return 'truecolor'
    return None                                        # 'auto', '', or unrecognized -> auto-detect


def env_effects(env=None):
    '''The resolved TUI motion level from the environment ('full'|'reduced'|'none'), or None. The TUI
    canonicalizes CONFIGSYS_EFFECTS (from --effects / the `effects:` setting / an SSH auto-default)
    into this before building the Palette, so the gradient + splash read one value.'''
    import os
    env = os.environ if env is None else env
    v = (env.get('CONFIGSYS_EFFECTS') or '').strip().lower()
    return v if v in ('full', 'reduced', 'none') else None


# Color depths, lowest first: what a Palette paints at (`Palette.depth`), after any --color cap.
DEPTHS = ('none', '8', '16', '256', 'truecolor', 'direct')
_CAP_DEPTH = {'none': 'none', 'basic8': '8', 'basic16': '16', '256': '256', 'truecolor': 'direct'}


def palette_depth(pal):
    '''A palette's color depth (one of DEPTHS): its `depth`, else derived from the old flags for a
    duck-typed palette that only carries those (truecolor/direct/have256/have16/mono).'''
    d = getattr(pal, 'depth', None)
    if d in DEPTHS:
        return d
    if getattr(pal, 'mono', False):
        return 'none'
    if getattr(pal, 'direct', False):
        return 'direct'
    if getattr(pal, 'truecolor', False):
        return 'truecolor'
    if getattr(pal, 'have256', False):
        return '256'
    return '16' if getattr(pal, 'have16', False) else '8'


class Palette:
    '''Resolves the theme to curses attrs. Holds every page's resolved role styles + gradient; the
    active page is selected with `use_page` (call sites stay `pal.style('component', ...)`). Color
    slots and pairs are deduped across all pages, so switching pages is free.'''
    def __init__(self, theme=None):
        curses.start_color()
        self.bg = -1
        try:
            curses.use_default_colors()
        except curses.error:
            self.bg = curses.COLOR_BLACK
        direct = curses.COLORS >= (1 << 24)
        # how the TERMINFO numbers colors — fixed at initscr, unlike the depth we paint at (which a
        # --color cap lowers). A -direct entry reads an index as packed rgb, so a capped palette
        # index must be sent as the rgb it stands for (B16 / tui-theme-06).
        self.direct_numbering = direct
        try:
            truecolor = direct or (curses.COLORS >= 256 and curses.can_change_color())
        except curses.error:
            truecolor = direct
        # The depth the terminal gives us, CLAMPED down per --color/--nocolor/NO_COLOR (never up).
        # `none` = monochrome: no color pairs at all, only structural A_REVERSE/A_BOLD survive (see
        # the render methods). The bright ANSI slots (8..15) — where the legible low-color look
        # lives — exist only at COLORS>=16; `--color 8` forces the base 8 to preview the fallback.
        natural = ('direct' if direct else 'truecolor' if truecolor else
                   '256' if curses.COLORS >= 256 else '16' if curses.COLORS >= 16 else '8')
        cap = _CAP_DEPTH.get(env_color_cap(), 'direct')
        self.depth = min(natural, cap, key=DEPTHS.index)
        # motion: reduced/none disable the diagonal gradient (the per-cell repaint that's costly over
        # a thin SSH link); `full` (or unset) keeps it. The splash is gated separately, at the TUI.
        self.grad_ok = env_effects() in (None, 'full')

        colors, pages = resolve_theme(theme)
        self._basic = resolve_basic(theme, colors)   # {map name: ansi_slot} hand-tuning for the 8/16 path
        self._next_color = 16          # private palette-slot allocator (truecolor mode)
        self._next_pair = 1
        self._color_cache = {}         # rgb -> palette index
        self._slot_rgb = {}            # redefined palette slot -> the rgb it holds
        self.reduced = 0               # colours / pairs that had to borrow the nearest one (color_mode)
        self._pair_cache = {}          # (fg_idx, bg_idx) -> attr
        self._map = {name: self._color(rgb, name) for name, rgb in colors.items()}   # for get()

        self._pages = {}
        for page, pg in pages.items():
            roles = {}
            for role, st in pg['roles'].items():
                flags = ((curses.A_BOLD if st['bold'] else 0)
                         | (curses.A_UNDERLINE if st['underline'] else 0)
                         | (curses.A_REVERSE if st['reverse'] else 0))
                bg = self._color(st['bg'], st.get('bg_name')) if st['bg'] is not None else None
                roles[role] = (self._color(st['fg'], st.get('fg_name')), bg, flags)
            ga, gb, enabled = pg['grad']
            on = self.truecolor and enabled and self.grad_ok
            grad_bg = []
            if on:
                span = max(abs(ga[i] - gb[i]) for i in range(3))
                n = max(16, min(GRAD_MAX_BANDS, span + 1))
                grad_bg = [self._color(_lerp(ga, gb, k / (n - 1))) for k in range(n)]
            sel_bg_rgb = pg['sel_bg']
            sel_bg = (self._color(sel_bg_rgb, pg.get('sel_bg_name')) if sel_bg_rgb is not None
                      else self.bg)
            self._pages[page] = {'roles': roles, 'grad_bg': grad_bg, 'sel_bg': sel_bg,
                                 'sel_bg_rgb': tuple(sel_bg_rgb) if sel_bg_rgb is not None else (0, 0, 0),
                                 'on': on}
        self.page_name = None
        self.use_page('components')

    # The depth flags, derived from `depth` (kept for the painters and splash plugins that read them).
    @property
    def mono(self):
        return self.depth == 'none'

    @property
    def direct(self):
        '''Painting at direct 24-bit (the color number IS the packed rgb).'''
        return self.depth == 'direct'

    @property
    def truecolor(self):
        return self.depth in ('truecolor', 'direct')

    @property
    def have256(self):
        return self.depth in ('256', 'truecolor', 'direct')

    @property
    def have16(self):
        return self.depth != '8'

    @property
    def lowcolor(self):
        '''The 8/16-color path (where quantization can collide fg with bg) -> the contrast guard runs.'''
        return self.depth in ('8', '16')

    @property
    def color_mode(self):
        d = self.depth
        if d == 'none':
            return 'none (monochrome)'
        if d == 'direct':
            return 'direct 24-bit' + (' (some colors shared)' if self.reduced else '')
        if d == 'truecolor':
            return '24-bit' + (' (palette full: nearest colors reused)' if self.reduced else '')
        return {'256': '256-color (approx)', '16': '16-color', '8': '8-color'}[d]

    def new_frame(self):
        '''Reset the color-PAIR allocator at the start of each full redraw. `curses.color_pair()`
        encodes the pair number in only 8 bits (A_COLOR == 0xff00), so pair numbers MUST stay < 256
        or they wrap to a different pair's colors. One Palette is shared for the whole session and
        pairs never free, so without this a long session (or the pair-heavy Theme screen) eventually
        exceeds 255 and every over-256 cell renders in the wrong color. Color SLOTS persist (a theme
        past the 240 redefinable slots reuses the nearest allocated colour — `_color`); only pairs —
        the fg×bg combinations, of which there are far more — are recycled each frame, which curses is
        built to handle (a frame past 255 borrows the nearest same-fg pair — `_pair`).'''
        self._next_pair = 1
        self._pair_cache.clear()

    def use_page(self, page):
        pg = self._pages.get(page) or self._pages['components']
        self._roles = pg['roles']
        self._grad_bg = pg['grad_bg']
        self._sel_bg = pg['sel_bg']
        self._sel_bg_rgb = pg['sel_bg_rgb']
        self.gradient = pg['on']
        self.page_name = page

    @property
    def sel_bg_rgb(self):
        '''The active page's selection-bar rgb — so callers can derive dimmer/subtler row tints
        (e.g. a residual selection or a member highlight) that stay in the theme's family.'''
        return self._sel_bg_rgb

    def _entry(self, role):
        r = self._roles.get(role)
        if r is not None:
            return r
        idx = self._map.get(role, self._map.get('dim', 0))   # a color-map name used as a role
        return (idx, None, 0)

    def _color(self, rgb, name=None):
        '''The color index painting `rgb`. `name` (the color-map name it came from, if any) picks its
        hand-tuned colors-basic slot on the 8/16-color path; a literal color is quantized.'''
        key = tuple(rgb)
        slot = self._basic.get(name) if (name is not None and not self.have256) else None
        ckey = key if slot is None else (key, name)       # two names sharing an rgb keep their slots
        if ckey in self._color_cache:
            return self._color_cache[ckey]
        r, g, b = rgb
        idx = None
        if self.direct:                                    # color number IS the packed 24-bit RGB
            idx = (r << 16) | (g << 8) | b
            if idx < 8:                                    # 0..7 are still the ANSI slots under
                idx = 8                                    # -direct terminfo; (0,0,8) ~ true black
        elif self.truecolor and self._next_color < curses.COLORS:
            idx = self._next_color
            try:
                curses.init_color(idx, round(r / 255 * 1000), round(g / 255 * 1000),
                                  round(b / 255 * 1000))
                self._next_color += 1
                self._slot_rgb[idx] = key
            except curses.error:
                idx = None
        elif self.truecolor and self._slot_rgb:
            # every slot is taken: in this mode the xterm-256 indexes ARE the redefined slots, so
            # rgb_to_256 would paint whatever theme colour holds that slot — reuse the NEAREST
            # allocated colour instead (B16 / tui-theme-02)
            idx = min(self._slot_rgb, key=lambda s: _dist2(self._slot_rgb[s], key))
            self.reduced += 1
        if idx is None:
            if self.have256:
                idx = rgb_to_256(*rgb)
            else:                                          # 8/16-color: an explicit hand-tuned slot
                idx = slot                                 # wins over the automatic quantizer
                if idx is None:
                    idx = rgb_to_basic8(*rgb)
                elif idx >= 8 and not self.have16:
                    idx -= 8                                # bright slot unavailable -> the base hue
            if self.direct_numbering and idx >= 8:          # capped depth on a -direct terminfo: send
                qr, qg, qb = xterm_rgb(idx)                 # the QUANTIZED colour as packed rgb (0..7
                idx = max(8, (qr << 16) | (qg << 8) | qb)   # stay the ANSI slots there)
        self._color_cache[ckey] = idx
        return idx

    def _index_rgb(self, idx):
        '''The rgb a colour index paints (for nearest-match borrowing), best effort.'''
        if idx is None or idx < 0:
            return (0, 0, 0)
        if idx in self._slot_rgb:
            return self._slot_rgb[idx]
        if self.direct_numbering and idx >= 8:
            return (idx >> 16) & 255, (idx >> 8) & 255, idx & 255
        return xterm_rgb(idx) if idx < 256 else (0, 0, 0)

    # Rough perceived luminance of each ANSI slot (0..1); -1 (terminal default) is assumed dark.
    _ANSI_LUM = {-1: 0.0, 0: 0.00, 1: 0.30, 2: 0.55, 3: 0.75, 4: 0.20, 5: 0.40, 6: 0.65, 7: 0.78,
                 8: 0.42, 9: 0.48, 10: 0.72, 11: 0.92, 12: 0.42, 13: 0.60, 14: 0.82, 15: 1.00}

    def _contrast(self, fg, bg):
        '''Low-color legibility guard: if `fg` would be (near-)invisible on `bg` — too little
        luminance separation, with the terminal default (-1) treated as dark — nudge it so text never
        vanishes (the classic "grey quantizes to black on a black terminal"). A hue is brightened to
        its bright variant where possible (keeps the meaning); greyscale goes to white/black. The
        theme's own default fg (-1) is left alone — the terminal guarantees it reads on its own bg.'''
        if fg == -1:
            return fg
        lf, lb = self._ANSI_LUM.get(fg, 0.5), self._ANSI_LUM.get(bg, 0.0)
        if abs(lf - lb) >= 0.28:
            return fg
        dark_bg = lb < 0.5
        if fg in (0, 7, 8, 15):                        # greyscale: no hue to preserve
            return (15 if self.have16 else 7) if dark_bg else 0
        if dark_bg:
            return fg + 8 if (self.have16 and fg < 8) else fg   # brighten the hue (8-color: keep it)
        return fg - 8 if fg >= 8 else fg                        # a light bg wants the darker hue

    def _pair(self, fg_idx, bg_idx, *, guard=True):
        if guard and self.lowcolor:                    # 8/16-color: keep text legible on its bg
            fg_idx = self._contrast(fg_idx, bg_idx)
        attr = self._pair_cache.get((fg_idx, bg_idx))
        if attr is None:
            n = self._next_pair
            if n > 255:                      # color_pair() only encodes 8 bits — pair >255 would WRAP
                # to another pair's colors: borrow this frame's pair with the same fg and the nearest
                # bg (a one-band difference behind a glyph is invisible) — never the terminal's
                # default colours punching a hole in the gradient (B16 / tui-theme-07)
                near = [(_dist2(self._index_rgb(b), self._index_rgb(bg_idx)), a)
                        for (f, b), a in self._pair_cache.items() if f == fg_idx and a != curses.A_NORMAL]
                self.reduced += 1
                attr = min(near, key=lambda d: d[0])[1] if near else curses.A_NORMAL
                self._pair_cache[(fg_idx, bg_idx)] = attr
                return attr
            try:
                curses.init_pair(n, fg_idx, bg_idx)
                attr = curses.color_pair(n)
                self._next_pair += 1
            except curses.error:
                attr = curses.A_NORMAL
            self._pair_cache[(fg_idx, bg_idx)] = attr
        return attr

    def get(self, name):
        '''A color-MAP name's attr over the default background (a role name works as a fallback) —
        the shared map, so a page's role override never changes it. For the splash ABI.'''
        if self.mono:
            return curses.A_NORMAL
        idx = self._map.get(name)
        if idx is None:
            idx = self._entry(name)[0]
        return self._pair(idx, self.bg)

    def rgb_attr(self, rgb):
        '''An attr painting `rgb` as fg over the default background — for ad-hoc colors (the splash)
        outside the map. Shares the slot/pair allocator + caches and degrades gracefully.'''
        return curses.A_NORMAL if self.mono else self._pair(self._color(rgb), self.bg, guard=False)

    def rgb_pair(self, fg_rgb, bg_rgb):
        '''Like rgb_attr but over an explicit bg colour (e.g. a splash glyph over a coloured background).'''
        return (curses.A_NORMAL if self.mono
                else self._pair(self._color(fg_rgb), self._color(bg_rgb), guard=False))

    def band(self, y, x, h, w):
        '''The gradient band index for a cell, along the top-left -> bottom-right diagonal.'''
        n = len(self._grad_bg)
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(n - 1, int(t * n))

    def style(self, element, y, x, h, w, *, selected=False, bg=None):
        '''The attr for a role at cell (y, x): its fg + flags, over its own bg if it declares one,
        else the active page's diagonal gradient (or the selected-row bar). `bg` (an rgb) forces the
        background for this cell — for a row tint (residual selection / profile member).'''
        fg, elem_bg, flags = self._entry(element)
        if self.mono:                                  # no color — keep the role's flags + reverse the bar
            return flags | (curses.A_REVERSE if selected else 0)
        g = not (flags & curses.A_REVERSE)             # reverse swaps fg/bg on screen -> skip the guard
        if bg is not None:
            return self._pair(fg, self._color(bg), guard=g) | flags
        if not self.gradient:
            base = self._pair(fg, self._sel_bg if selected else (elem_bg if elem_bg is not None
                                                                 else self.bg), guard=g)
            return base | flags
        b = self._sel_bg if selected else (elem_bg if elem_bg is not None
                                           else self._grad_bg[self.band(y, x, h, w)])
        return self._pair(fg, b, guard=g) | flags

    def fill(self, y, x, h, w, *, selected=False, bg=None):
        '''A blank-cell background attr (fg == bg) for painting the empty canvas behind text. `bg`
        (an rgb) forces a specific fill colour (a row tint), in every colour mode.'''
        if self.mono:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        if bg is not None:
            idx = self._color(bg)
            return self._pair(idx, idx, guard=False)   # a solid block: fg == bg is intentional
        if not self.gradient:                          # no gradient (256/16, or truecolor grad-off):
            return self._pair(self._sel_bg, self._sel_bg, guard=False) if selected else curses.A_NORMAL
        b = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(b, b, guard=False)


# The component statuses that have a same-named role to paint them in.
STATUSES = frozenset({'installed', 'outdated', 'partial', 'missing', 'locked', 'unsupported',
                      'untrusted', 'error', 'switch', 'unmet', 'dangling'})
