'''keyspec.py — parse key NAMES <-> curses codes, and a Keymap resolved from the merged `keys:`
config section. The TUI dispatches on ACTIONS (not raw key codes), and its legends read the SAME
Keymap, so bindings and their on-screen hints can never drift. No curses call at import (only the
module's KEY_* int constants, which are available without initscr).

The base bindings live as humon in the repo's config.hu `keys:` section and merge up the layer stack
(repo < plugins < primary < user) via Config.keys() — so a `keys:` block in any plugin's data file, or
the top user config, overlays them per action (a plugin's, the primary's included, only once that plugin
is trusted — Config.key_layers). There is deliberately no Python default map; the humon file IS
the default. A tiny FALLBACK here only guards against a missing/broken repo section bricking the TUI.'''

import curses
import re

from .theme import ALL_PAGES, SCREEN_REGISTRY

# name -> code, for keys that aren't a single literal character. Case-insensitive.
_NAMED = {
    # Return is CR (13), NOT LF (10) — we run with CR->NL folding OFF (see screen.py), so the Return
    # key and Ctrl-J (LF, 10) are distinct. `kpenter` is the keypad Enter (KEY_ENTER).
    'enter': ord('\r'), 'return': ord('\r'), 'ret': ord('\r'), 'cr': ord('\r'),
    'kpenter': curses.KEY_ENTER, 'kp-enter': curses.KEY_ENTER,
    'tab': ord('\t'), 'esc': 27, 'escape': 27, 'space': ord(' '), 'spc': ord(' '),
    'up': curses.KEY_UP, 'down': curses.KEY_DOWN, 'left': curses.KEY_LEFT, 'right': curses.KEY_RIGHT,
    'pgup': curses.KEY_PPAGE, 'pageup': curses.KEY_PPAGE, 'pgdn': curses.KEY_NPAGE,
    'pagedown': curses.KEY_NPAGE, 'home': curses.KEY_HOME, 'end': curses.KEY_END,
    'backspace': curses.KEY_BACKSPACE, 'bs': curses.KEY_BACKSPACE, 'del': curses.KEY_DC,
    'delete': curses.KEY_DC, 'ins': curses.KEY_IC, 'insert': curses.KEY_IC,
    'shift-tab': curses.KEY_BTAB, 'btab': curses.KEY_BTAB,
}

# code -> a compact glyph for legends (prefer a symbol where it reads well).
_GLYPH = {
    ord('\r'): '⏎', curses.KEY_ENTER: '⏎', ord('\t'): 'tab', 27: 'esc', ord(' '): 'space',
    curses.KEY_UP: '↑', curses.KEY_DOWN: '↓', curses.KEY_LEFT: '←', curses.KEY_RIGHT: '→',
    curses.KEY_PPAGE: 'pgup', curses.KEY_NPAGE: 'pgdn', curses.KEY_HOME: 'home', curses.KEY_END: 'end',
    curses.KEY_BACKSPACE: '⌫', curses.KEY_DC: 'del', curses.KEY_IC: 'ins', curses.KEY_BTAB: 'shift-tab',
}


def parse_key(name):
    '''A key NAME -> its curses code, or None if unrecognized. Accepts a single literal character
    (case-SENSITIVE, so `g` != `G`), a named key (`enter`/`tab`/`up`/`pgdn`/…, case-insensitive), or
    `ctrl-<x>` (a control char). Numbers-as-strings ("1") are just their single character. An int is
    taken as a code already (a bool is not a key).'''
    if isinstance(name, bool):
        return None
    if isinstance(name, int):
        return name
    if not isinstance(name, str) or not name:
        return None
    if len(name) == 1:
        return ord(name)                               # a literal char, case-sensitive
    s = name.strip().lower()
    if s in _NAMED:
        return _NAMED[s]
    if s.startswith(('ctrl-', 'c-', '^')):
        tail = s.split('-', 1)[-1] if '-' in s else s[1:]
        if len(tail) == 1 and tail.isalpha():
            return ord(tail) & 0x1f
        return None
    if s.startswith('f') and s[1:].isdigit():          # function keys f1..f12
        n = int(s[1:])
        if 1 <= n <= 12:
            return curses.KEY_F0 + n
    return None


# Codes a parsed name can yield that the TUI never receives: under cbreak the terminal keeps ISIG
# and IXON, so these become signals / flow control before getch() sees them (tui-theme-12).
_UNRECEIVABLE = {3: 'SIGINT', 17: 'XON flow control', 19: 'XOFF flow control', 26: 'SIGTSTP',
                 28: 'SIGQUIT'}


def unreceivable(code):
    '''Why a bound `code` can never reach the TUI (a short phrase), or None when it can. A single
    character beyond ASCII arrives from getch() as its UTF-8 bytes, never as one code.'''
    if code in _UNRECEIVABLE:
        return f'the terminal uses it for {_UNRECEIVABLE[code]}'
    if 128 <= code < curses.KEY_MIN:
        return 'a non-ASCII character arrives as several bytes'
    return None


def _shown(s):
    '''A layer-supplied string made safe to print in a `check` warning: every control character
    (C0, DEL, C1, …) is written as its escape, so a plugin's `keys:` can't drive the terminal.'''
    return ''.join(c if c.isprintable() else repr(c)[1:-1] for c in str(s))


def key_name(code):
    '''A curses code -> a short display glyph for legends (inverse-ish of parse_key).'''
    if code in _GLYPH:
        return _GLYPH[code]
    if 1 <= code <= 26:                                # a control char
        return f'^{chr(code + 96)}'
    if curses.KEY_F0 + 1 <= code <= curses.KEY_F0 + 12:
        return f'F{code - curses.KEY_F0}'
    if 32 <= code < 127:
        return chr(code)
    return '?'


# A minimal safety net if config.hu's `keys:` section is missing/broken — NOT the real defaults (those
# are the humon file). Just enough that quit and screen-switch always work.
_FALLBACK = {
    'global': {'quit': 'q', 'quit-force': 'Q', 'issues': '!'},
    'screens': {sid: key for sid, _title, key in SCREEN_REGISTRY},
}


# The global actions the ROUTER (menu.run) owns rather than a screen's handle: it acts on them before
# the screen sees the key. A screen may still bind these in its own scope (they then work there), and
# a screen-scope binding of their keys to something else wins on that screen (see Keymap.own_action).
ROUTER_ACTIONS = ('quit', 'quit-force', 'issues', 'help')


def merge_layer_keys(layers, warnings=None, owners_out=None):
    """Merge every layer's `keys:` section (low -> high precedence) into `{scope: {action: spec}}`,
    REBIND-WINS (review-2026-11-2 B16 / tui-theme-04/05), in passes over the FINAL bindings:

    1. a plain per-action overlay: each (scope, action) takes the highest layer's spec;
    2. within a scope, a key two final actions hold stays with the one from the HIGHER layer and is
       stripped from the other (an action left keyless is dropped). Computed against the final
       bindings, so a middle layer's steal undone by a higher layer leaves nothing dead;
    3. across scopes, following the router's precedence (page > global router actions > screens >
       global nav): a HIGHER layer's `global` / `screens` binding of a key takes it from a LOWER
       layer's page bindings — your `screens: { theme: t }` switches screens on Plugins too instead
       of silently staying `trust` there — and a `screens` key takes it from a lower `global` nav
       action. Within one layer the page keeps its key.

    Each steal appends one warning to `warnings` (if given). `layers` are objects with `.data` (dict)
    and `.path`."""
    import os
    out, owner = {}, {}                              # owner: scope -> action -> (layer idx, basename)
    for idx, lyr in enumerate(layers):               # pass 1: per-action overlay
        keys = (getattr(lyr, 'data', None) or {}).get('keys')
        if not isinstance(keys, dict):
            continue
        where = os.path.basename(getattr(lyr, 'path', '') or '?')
        for scope, actions in keys.items():
            if not isinstance(actions, dict):
                continue
            for action, spec in actions.items():
                out.setdefault(scope, {})[action] = spec
                owner.setdefault(scope, {})[action] = (idx, where)

    def specs_of(scope, action):
        s = out[scope][action]
        return s if isinstance(s, list) else [s]

    def strip(scope, action, codes, by, by_where, label):
        """Remove `codes` from (scope, action); warn naming who took them."""
        ospecs = specs_of(scope, action)
        keep = [k for k in ospecs if parse_key(k) not in codes]
        if len(keep) == len(ospecs):
            return
        lost = [k for k in ospecs if parse_key(k) in codes]
        if warnings is not None:
            act, sc = _shown(action), _shown(scope)
            gone = f" — '{act}' is now unbound in keys.{sc}" if not keep else ''
            warnings.append(f"{_shown(by_where)}: keys.{_shown(label)}: "
                            f"{', '.join(_shown(repr(str(k))) for k in lost)} "
                            f"takes the key from '{act}' in keys.{sc} "
                            f"({_shown(owner[scope][action][1])}){gone}")
        if keep:
            out[scope][action] = keep
        else:
            del out[scope][action]

    def codes_of(scope, action):
        return {c for c in (parse_key(k) for k in specs_of(scope, action)) if c is not None}

    for scope in list(out):                          # pass 2: within a scope, the higher layer keeps it
        ranked = sorted(out[scope], key=lambda a: -owner[scope][a][0])
        for hi in ranked:
            if hi not in out[scope]:
                continue
            for lo in ranked:
                if lo == hi or lo not in out[scope] or owner[scope][lo][0] >= owner[scope][hi][0]:
                    continue
                strip(scope, lo, codes_of(scope, hi), None, owner[scope][hi][1], f'{scope}.{hi}')

    pages = [s for s in out if s not in ('global', 'screens')]
    takers = [('global', a) for a in out.get('global', {}) if a in ROUTER_ACTIONS]
    takers += [('screens', a) for a in out.get('screens', {})]
    for tscope, taction in takers:                   # pass 3: across scopes, by layer
        if taction not in out.get(tscope, {}):
            continue
        tidx, twhere = owner[tscope][taction]
        tcodes = codes_of(tscope, taction)
        victims = [(s, a) for s in pages for a in list(out.get(s, {}))]
        if tscope == 'screens':
            victims += [('global', a) for a in list(out.get('global', {})) if a not in ROUTER_ACTIONS]
        for vscope, vaction in victims:
            if vaction in out.get(vscope, {}) and owner[vscope][vaction][0] < tidx:
                strip(vscope, vaction, tcodes, None, twhere, f'{tscope}.{taction}')
    if owners_out is not None:                       # {scope: {action: the layer file it came from}}
        for scope, acts in out.items():
            owners_out[scope] = {a: owner[scope][a][1] for a in acts}
    return out


class Keymap:
    '''Resolved bindings: `{scope: {action: [codes]}}`. Built from the merged `keys:` dict (already
    layer-merged — Config.keys()). Page scopes override the `global` scope for the
    same key; within one scope, if a key is (mis)bound to two actions the first listed wins
    (lint_merged / `configsys check` reports that).'''

    def __init__(self, merged):
        src = merged if (isinstance(merged, dict) and merged.get('global')) else _FALLBACK
        self._m = {}
        for scope, actions in src.items():
            if not isinstance(actions, dict):
                continue
            am = {}
            for action, spec in actions.items():
                specs = spec if isinstance(spec, list) else [spec]
                codes = [c for c in (parse_key(k) for k in specs) if c is not None]
                if codes:
                    am[action] = codes
            self._m[scope] = am

    def bindings(self):
        '''[(scope, action, [codes])] — every resolved binding (the public view of the map).'''
        return [(s, a, list(codes)) for s, acts in self._m.items() for a, codes in acts.items()]

    def action_for(self, scope, code):
        '''The action `code` triggers in `scope` — page scope first, then falling back to `global`.'''
        for action, codes in self._m.get(scope, {}).items():
            if code in codes:
                return action
        if scope != 'global':
            return self.action_for('global', code)
        return None

    def own_action(self, scope, code):
        '''The action `code` triggers in `scope`'s OWN bindings — no fall-back to `global`. The router
        consults this first: a key a screen binds itself goes to that screen (even one `global` /
        `screens` would otherwise claim), and a screen-scope binding of a ROUTER_ACTIONS action
        (quit/quit-force/issues/help) is acted on by the router on that screen.'''
        if scope in ('global', 'screens'):
            return None
        for action, codes in self._m.get(scope, {}).items():
            if code in codes:
                return action
        return None

    def keys_for(self, scope, action):
        '''Every code bound to `action` in `scope` (empty if none).'''
        return self._m.get(scope, {}).get(action, [])

    def screen_for(self, code):
        '''The screen id `code` switches to (the `screens` scope), or None.'''
        for sid, codes in self._m.get('screens', {}).items():
            if code in codes:
                return sid
        return None

    @staticmethod
    def label(scope, action):
        '''The `?` help label for `action` on `scope` — a scope-specific `<scope>.<action>` entry in
        ACTION_LABELS first (one action id can mean different things per page), else the shared one.'''
        return ACTION_LABELS.get(f'{scope}.{action}') or ACTION_LABELS.get(action, action)

    def effective_codes(self, scope, action):
        '''The codes that really trigger `action` on `scope`, in the router's precedence: the page's
        own binding of it, else the `global` codes minus every code the page binds to another action
        (and, for a nav action the screen handles, minus the `screens` switch keys, which the router
        consults first). So a legend never shows a key the page shadows (tui-theme-11).'''
        own = self.keys_for(scope, action)
        if own or scope in ('global', 'screens'):
            return list(own)
        taken = {c for a, cs in self._m.get(scope, {}).items() if a != action for c in cs}
        if action not in ROUTER_ACTIONS:
            taken |= {c for cs in self._m.get('screens', {}).values() for c in cs}
        return [c for c in self.keys_for('global', action) if c not in taken]

    def glyph(self, scope, action):
        '''The primary key for `action` as a legend glyph (effective_codes: the page's own binding,
        else an unshadowed global one). '?' if unbound.'''
        codes = self.effective_codes(scope, action)
        return key_name(codes[0]) if codes else '?'

    def help_rows(self, scope):
        '''[(keys, label)] for the `?` overlay: the shared global keys first (each by the keys that
        really reach it on this page — effective_codes; a global action the page shadows entirely is
        left out), then this page's own actions. The theme screen's page-1..page-N collapse to one
        row; up to two distinct alternate glyphs are shown per action.'''
        order = ['down', 'up', 'left', 'right', 'top', 'bottom', 'page-down', 'page-up', 'select',
                 'confirm', 'switch-pane', 'switch-pane-back', 'find', 'filter', 'issues', 'help', 'quit', 'quit-force']
        rows, seen_page, shown = [], False, set()

        def keyglyph(codes):
            glyphs = list(dict.fromkeys(key_name(c) for c in codes))   # ⏎ (enter) = ⏎ (kpenter)
            return '/'.join(glyphs[:2])

        for a in order:                                    # global (shared) keys, in a readable order
            if a in OPTIONAL_GLOBALS and a not in SCREEN_GLOBALS.get(scope, ()) \
                    and a not in self._m.get(scope, {}):
                continue                                   # a global this page doesn't act on
            if a in self._m.get('global', {}) or a in self._m.get(scope, {}):
                codes = self.effective_codes(scope, a)
                if codes:
                    rows.append((keyglyph(codes), self.label('global', a)))
                shown.add(a)
        for a in sorted(self._m.get(scope, {})):           # then the page's own actions
            if a in shown:
                continue
            if _PAGE_N.match(a):
                if not seen_page:
                    seen_page = True
                    n = len(ALL_PAGES)
                    lo, hi = self.keys_for(scope, 'page-1'), self.keys_for(scope, f'page-{n}')
                    g = f'{key_name(lo[0])}-{key_name(hi[0])}' if lo and hi else f'F1-F{n}'
                    rows.append((g, 'preview sample page'))
                continue
            rows.append((keyglyph(self.keys_for(scope, a)), self.label(scope, a)))
        return rows


# Global actions only SOME screens act on: a `?` page lists one only where its screen handles it
# (SCREEN_GLOBALS — keep it in step with each screen's handle()). Every other global (navigation,
# confirm/select, issues, help, quit) is honored on every page.
OPTIONAL_GLOBALS = frozenset({'find', 'filter', 'switch-pane', 'switch-pane-back'})
SCREEN_GLOBALS = {
    'components': frozenset({'find', 'filter'}),
    'profiles': OPTIONAL_GLOBALS,
    'plugins': frozenset({'switch-pane', 'switch-pane-back'}),
    'theme': frozenset({'switch-pane', 'switch-pane-back'}),
}

_PAGE_N = re.compile(r'page-\d+$')        # the theme screen's sample-page actions (not page-down/-up)



_SHIPPED = None


def shipped_keymap():
    '''The Keymap config.hu ships (its `keys:` section) — what the modals, overlays and legends read
    outside a TUI run (tests, theme samples), so none of them keeps its own copy of the defaults.
    Read once; the minimal _FALLBACK if config.hu can't be read.'''
    global _SHIPPED
    if _SHIPPED is None:
        try:
            from ..layers import read_tree
            from ..paths import Paths
            _trove, data = read_tree(Paths({}).config_file)
            _SHIPPED = Keymap(data.get('keys') or {})
        except Exception:                            # noqa: BLE001 — never break a legend over this
            _SHIPPED = Keymap({})
    return _SHIPPED

# The canonical actions each scope's dispatch understands — the contract `configsys check` lints a
# user's `keys:` against. A page scope may ALSO bind any `global` action (to rebind nav on that page),
# so a page's valid set is its own actions ∪ global's. `screens` binds screen ids, not actions.
_GLOBAL_ACTIONS = {'down', 'up', 'left', 'right', 'top', 'bottom', 'page-down', 'page-up', 'select',
                   'confirm', 'switch-pane', 'switch-pane-back', 'find', 'filter', 'issues', 'help',
                   'quit', 'quit-force'}
SCREEN_IDS = set(ALL_PAGES)
KNOWN_ACTIONS = {
    'global': _GLOBAL_ACTIONS,
    'components': {'where', 'lock', 'expand-all', 'select-all', 'clear', 'method', 'op-install',
                   'op-upgrade', 'op-install-all', 'op-upgrade-all', 'op-remove', 'execute',
                   'refresh', 'mode'},
    'config': {'theme', 'move'},
    'issues': {'report', 'request', 'suggest-os'},         # the `!` page (an overlay, not a screen)
    'dotfiles': {'manage', 'manage-all', 'unmanage', 'unmanage-all', 'move-store', 'move-store-all'},
    'glue': {'activate', 'activate-group', 'deactivate', 'new-snippet', 'override', 'staged'},
    'plugins': {'add', 'remove', 'sync', 'sync-all', 'bless', 'unbless', 'update', 'update-all',
                'trust', 'trust-all', 'set-ref', 'lock', 'push', 'history', 'init-primary',
                'set-source', 'picks-to-primary'},
    'profiles': {'track-all', 'track-one', 'select-all', 'method', 'comp-machines', 'machine-target',
                 'attr-filter', 'toggle-install', 'stage-uninstall', 'disp-interesting', 'disp-seen',
                 'disp-interesting-all', 'disp-seen-all', 'mark-all-seen', 'claim', 'orphan-ignore',
                 'where'},
    'theme': {'new', 'reset', 'edit-bg', 'effect-bold', 'effect-underline', 'effect-reverse',
              'gradient-toggle', 'copy-page', 'save', 'load',
              *(f'page-{i}' for i in range(1, len(ALL_PAGES) + 1))},   # F1.. select a sample page
}


# Human labels for each action — used by the per-page `?` help overlay (and available to anything that
# wants to describe a binding). An action absent here falls back to its id.
ACTION_LABELS = {
    'down': 'move down', 'up': 'move up', 'left': 'left / collapse', 'right': 'right / expand',
    'top': 'jump to top', 'bottom': 'jump to bottom', 'page-down': 'page down', 'page-up': 'page up',
    'select': 'select / mark', 'confirm': 'activate / open',
    'switch-pane': 'switch pane', 'switch-pane-back': 'switch pane (back)', 'find': 'find (jump cursor)',
    'filter': 'filter (narrow the list)', 'issues': 'show issues', 'help': 'this help',
    'quit': 'quit (asks to confirm)', 'quit-force': 'quit now (no prompt)',
    'where': 'explain component (where)',
    'profiles.where': 'explain (where): cursor component, or the profile (left pane)',
    'lock': 'lock / unlock version', 'expand-all': 'expand / collapse all',
    'clear': 'unstage cursor/selection, clear selection', 'method': 'pick install method / provider',
    'components.method': 'change: method / provider; rebuild, version, scope',
    'op-install': 'make current: install if missing, else upgrade',
    'op-install-all': 'make every tracked component current',
    'op-upgrade': 'stage upgrade (outdated only)', 'op-upgrade-all': 'upgrade every outdated component',
    'op-remove': 'stage remove',
    'execute': 'run staged ops (confirms)', 'refresh': 'refresh versions + package index',
    'mode': 'cycle view: to-do / tracked / installed+tracked',
    'theme': 'open the theme editor', 'move': 'move setting: local ⇄ primary',
    'report': 'file a report (a component, or the last failures)', 'request': 'request a component',
    'suggest-os': 'suggest this OS (or report an update that changed it)',
    'manage': 'manage: capture + link', 'manage-all': 'manage every unmanaged config',
    'unmanage': 'unmanage (unlink; confirms)', 'unmanage-all': 'unmanage every managed config',
    'move-store': 'move store: local ⇄ primary', 'move-store-all': 'move all configs to a store',
    'activate': 'activate for this shell', 'activate-group': "(re)activate this shell's group",
    'deactivate': 'deactivate for this shell',
    'new-snippet': 'new snippet of your own ($EDITOR)', 'override': "override this component's glue",
    'staged': 'review staged installer writes',
    'add': 'add a plugin', 'remove': 'remove plugin', 'sync': 'sync plugin', 'sync-all': 'sync all',
    'bless': 'bless: make it your primary plugin', 'unbless': 'clear the primary plugin',
    'update': 'update plugin to its latest ref', 'update-all': 'update all to latest',
    'trust': 'trust / untrust plugin', 'trust-all': 'trust every untrusted or changed plugin (confirms)',
    'set-ref': 'set git ref + re-sync',
    'init-primary': 'new primary from local config', 'set-source': 'set plugin source / remote',
    'picks-to-primary': "move this box's picks into the primary",
    'plugins.lock': 'lock / unlock plugin (no sync, update, bless or trust)',
    'plugins.push': 'push your primary plugin (commit, combine, push)',
    'plugins.history': "your primary's recent changes; undo configsys's latest",
    'attr-filter': 'filter by attrs',
    'track-all': 'toggle tracking: the set, else highlighted', 'track-one': 'toggle tracking: highlighted',
    'select-all': 'select all in view', 'machine-target': 'choose target machines',
    'comp-machines': 'machines for this component',
    'disp-interesting': 'toggle interesting', 'disp-seen': 'toggle new / seen',
    'disp-interesting-all': 'mark the set (else highlighted) interesting',
    'disp-seen-all': 'mark the set (else highlighted) seen',
    'mark-all-seen': 'mark all NEW seen (confirms)', 'claim': 'track all installed (confirms)',
    'toggle-install': 'install overlay on/off',
    'stage-uninstall': 'stage uninstall (→ !uninstall)',
    'orphan-ignore': 'ignore / un-ignore this orphan',
    'new': 'add a color to the map',
    'reset': 'reset to default', 'edit-bg': 'edit background', 'effect-bold': 'toggle bold',
    'effect-underline': 'toggle underline', 'effect-reverse': 'toggle reverse', 'gradient-toggle': 'toggle gradient',
    'copy-page': 'copy this page onto another', 'save': 'save / export', 'load': 'load a theme pack',
}


def _valid_actions(scope):
    if scope == 'screens':
        return SCREEN_IDS
    if scope == 'global':
        return _GLOBAL_ACTIONS
    return KNOWN_ACTIONS.get(scope, frozenset()) | _GLOBAL_ACTIONS


def lint_keys(layers):
    '''Lint every layer's `keys:` section for a `configsys check`. Returns a list of warning strings
    (with the offending file's basename as provenance). Catches: an unknown scope, an unknown action
    for its scope (typo), an unparseable key name, per layer per scope the same key bound to two
    different actions (a self-conflict), ACROSS layers a higher layer's binding taking a key a lower
    layer gave another action in the same scope (resolved rebind-wins, see merge_layer_keys), and a
    page that shadows every quit key. A page key that shadows a `global` one is NOT flagged — that
    override is intentional and page-wins. `layers` is an iterable of objects with `.data` (dict) and
    `.path`.'''
    import os
    out = []
    layers = list(layers)
    for lyr in layers:
        keys = getattr(lyr, 'data', {}).get('keys')
        if not isinstance(keys, dict):
            continue
        where = _shown(os.path.basename(getattr(lyr, 'path', '') or '?'))
        for scope, actions in keys.items():
            sc = _shown(scope)
            if not isinstance(actions, dict):
                out.append(f"{where}: keys.{sc} is not a map — ignored")
                continue
            if scope not in KNOWN_ACTIONS and scope != 'screens':
                out.append(f"{where}: unknown key scope '{sc}' "
                           f"(scopes: screens, {', '.join(sorted(KNOWN_ACTIONS))})")
                continue
            valid = _valid_actions(scope)
            seen = {}                                  # code -> action, for self-conflict within a scope
            for action, spec in actions.items():
                act = _shown(action)
                if action not in valid:
                    out.append(f"{where}: unknown action 'keys.{sc}.{act}' "
                               f"(not a {sc} action)")
                specs = spec if isinstance(spec, list) else [spec]
                for k in specs:
                    code = parse_key(k)
                    if code is None:
                        out.append(f"{where}: keys.{sc}.{act}: unparseable key '{_shown(k)}'")
                        continue
                    why = unreceivable(code)
                    if why:
                        out.append(f"{where}: keys.{sc}.{act}: '{_shown(k)}' never reaches the "
                                   f"TUI: {why}")
                    if code in seen and seen[code] != action:
                        out.append(f"{where}: keys.{sc}: '{_shown(k)}' bound to both "
                                   f"'{_shown(seen[code])}' and '{act}'")
                    else:
                        seen[code] = action
    # ACROSS layers: a higher layer rebinding a key a lower layer gave another action in the same
    # scope. The TUI resolves it rebind-wins (merge_layer_keys) — report what got taken.
    merged = merge_layer_keys(layers, warnings=out)
    out.extend(lint_merged(merged, only_lockout=True))
    return out


def lint_merged(keys, only_lockout=False):
    '''Lint a MERGED `keys:` map (`{scope: {action: spec}}`, e.g. Config.keys()):
    a key bound to two actions within one scope (at runtime the first listed silently wins), and a
    page scope that shadows EVERY quit and quit-force key (no way out of the TUI from that page).
    Returns warning strings. `only_lockout` skips the duplicate check (lint_keys already reports
    duplicates per layer and across layers).'''
    out = []
    if not isinstance(keys, dict):
        return out
    parsed = {}
    for scope, actions in keys.items():
        if not isinstance(actions, dict):
            continue
        am = parsed.setdefault(scope, {})
        seen = {}
        for action, spec in actions.items():
            specs = spec if isinstance(spec, list) else [spec]
            codes = [c for c in (parse_key(k) for k in specs) if c is not None]
            am[action] = codes
            for k, c in zip([k for k in specs if parse_key(k) is not None], codes):
                if not only_lockout and c in seen and seen[c] != action:
                    first = _shown(seen[c])
                    out.append(f"keys.{_shown(scope)}: '{_shown(k)}' bound to both '{first}' and "
                               f"'{_shown(action)}' (the TUI uses '{first}')")
                else:
                    seen.setdefault(c, action)
    gl = parsed.get('global', {})
    exits = set(gl.get('quit', [])) | set(gl.get('quit-force', []))
    for scope, am in parsed.items():
        if scope in ('global', 'screens'):
            continue
        own_exit = set(am.get('quit', [])) | set(am.get('quit-force', []))
        taken = {c for a, cs in am.items() if a not in ('quit', 'quit-force') for c in cs}
        if exits and not own_exit and exits <= taken:
            out.append(f"keys.{_shown(scope)}: every quit / quit-force key is bound to another action "
                       f"on this page — there is no way to quit from it")
    return out
