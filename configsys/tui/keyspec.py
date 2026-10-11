'''keyspec.py — parse key NAMES <-> curses codes, and a Keymap resolved from the merged `keys:`
config section. The TUI dispatches on ACTIONS (not raw key codes), and its legends read the SAME
Keymap, so bindings and their on-screen hints can never drift. No curses call at import (only the
module's KEY_* int constants, which are available without initscr).

The base bindings live as humon in the repo's config.hu `keys:` section and merge up the layer stack
(repo < plugins < primary < user) via Config.keys() — so a `keys:` block in any plugin's data file, or
the top user config, overlays them per action. There is deliberately no Python default map; the humon file IS
the default. A tiny FALLBACK here only guards against a missing/broken repo section bricking the TUI.'''

import curses

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
    10: 'ctrl-j', 11: 'ctrl-k',
    curses.KEY_UP: '↑', curses.KEY_DOWN: '↓', curses.KEY_LEFT: '←', curses.KEY_RIGHT: '→',
    curses.KEY_PPAGE: 'pgup', curses.KEY_NPAGE: 'pgdn', curses.KEY_HOME: 'home', curses.KEY_END: 'end',
    curses.KEY_BACKSPACE: '⌫', curses.KEY_DC: 'del', curses.KEY_IC: 'ins', curses.KEY_BTAB: 'shift-tab',
}


def parse_key(name):
    '''A key NAME -> its curses code, or None if unrecognized. Accepts a single literal character
    (case-SENSITIVE, so `g` != `G`), a named key (`enter`/`tab`/`up`/`pgdn`/…, case-insensitive), or
    `ctrl-<x>` (a control char). Numbers-as-strings ("1") are just their single character.'''
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
    'screens': {'components': '1', 'profiles': '2', 'plugins': '3', 'glue': '4',
                'dotfiles': '5', 'config': '6', 'theme': '7'},
}


# The global actions the ROUTER (menu.run) owns rather than a screen's handle: it acts on them before
# the screen sees the key. A screen may still bind these in its own scope (they then work there), and
# a screen-scope binding of their keys to something else wins on that screen (see Keymap.own_action).
ROUTER_ACTIONS = ('quit', 'quit-force', 'issues', 'help')


def merge_layer_keys(layers, warnings=None):
    '''Merge every layer's `keys:` section (low -> high precedence) into `{scope: {action: spec}}` —
    Config.keys()'s per-action override, plus REBIND-WINS: when a higher layer binds a key that a
    LOWER layer gave to another action in the same scope, that key is removed from the lower action
    (an action left with no key is dropped), so the user's rebind wins deterministically instead of
    whichever action happens to come first in the map. Each such steal appends a warning to
    `warnings` (if given). `layers` are objects with `.data` (dict) and `.path`.'''
    import os
    out, owner = {}, {}                              # owner: scope -> action -> (layer idx, basename)
    for idx, lyr in enumerate(layers):
        keys = (getattr(lyr, 'data', None) or {}).get('keys')
        if not isinstance(keys, dict):
            continue
        where = os.path.basename(getattr(lyr, 'path', '') or '?')
        for scope, actions in keys.items():
            if not isinstance(actions, dict):
                continue
            dst, own = out.setdefault(scope, {}), owner.setdefault(scope, {})
            for action, spec in actions.items():
                specs = spec if isinstance(spec, list) else [spec]
                codes = {c for c in (parse_key(k) for k in specs) if c is not None}
                for other in list(dst):
                    if other == action or own.get(other, (idx,))[0] >= idx:
                        continue                     # same action, or not from a LOWER layer
                    ospecs = dst[other] if isinstance(dst[other], list) else [dst[other]]
                    keep = [k for k in ospecs if parse_key(k) not in codes]
                    if len(keep) == len(ospecs):
                        continue
                    lost = [k for k in ospecs if parse_key(k) in codes]
                    if warnings is not None:
                        gone = (f" — '{other}' is now unbound in keys.{scope}" if not keep else '')
                        warnings.append(
                            f"{where}: keys.{scope}.{action}: "
                            f"{', '.join(repr(str(k)) for k in lost)} takes the key from "
                            f"'{other}' ({own[other][1]}){gone}")
                    if keep:
                        dst[other] = keep
                    else:
                        del dst[other]
                dst[action] = spec                   # per-action override (whole value replaced)
                own[action] = (idx, where)
    return out


def config_keys(config):
    '''The merged `keys:` for a Config with rebind-wins (merge_layer_keys) applied over its layer
    stack; falls back to `config.keys()` for an object without layers.'''
    layers = getattr(config, '_layers', None)
    if layers is None:
        return config.keys()
    return merge_layer_keys(layers)


class Keymap:
    '''Resolved bindings: `{scope: {action: [codes]}}`. Built from the merged `keys:` dict (already
    layer-merged — config_keys / Config.keys()). Page scopes override the `global` scope for the
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

    def glyph(self, scope, action):
        '''The primary key for `action` as a legend glyph (scope, then global). '?' if unbound.'''
        codes = self.keys_for(scope, action) or self.keys_for('global', action)
        return key_name(codes[0]) if codes else '?'

    def help_rows(self, scope):
        '''[(keys, label)] for the `?` overlay: the shared global keys first, then this page's own
        actions. page-1..page-7 collapse to one row; up to two alternate keys are shown per action.'''
        order = ['down', 'up', 'left', 'right', 'top', 'bottom', 'page-down', 'page-up', 'select',
                 'confirm', 'switch-pane', 'switch-pane-back', 'find', 'filter', 'issues', 'help', 'quit', 'quit-force']
        rows, seen_page = [], False

        def keyglyph(sc, action):
            codes = self.keys_for(sc, action)
            return '/'.join(key_name(c) for c in codes[:2]) if codes else ''

        for a in order:                                    # global (shared) keys, in a readable order
            if a in self._m.get('global', {}):
                rows.append((keyglyph('global', a), self.label('global', a)))
        for a in sorted(self._m.get(scope, {})):           # then the page's own actions
            if a.startswith('page-'):
                if not seen_page:
                    seen_page = True
                    lo, hi = self.keys_for(scope, 'page-1'), self.keys_for(scope, 'page-7')
                    g = f'{key_name(lo[0])}-{key_name(hi[0])}' if lo and hi else 'F1-F7'
                    rows.append((g, 'preview sample page'))
                continue
            rows.append((keyglyph(scope, a), self.label(scope, a)))
        return rows


# The canonical actions each scope's dispatch understands — the contract `configsys check` lints a
# user's `keys:` against. A page scope may ALSO bind any `global` action (to rebind nav on that page),
# so a page's valid set is its own actions ∪ global's. `screens` binds screen ids, not actions.
_GLOBAL_ACTIONS = {'down', 'up', 'left', 'right', 'top', 'bottom', 'page-down', 'page-up', 'select',
                   'confirm', 'switch-pane', 'switch-pane-back', 'find', 'filter', 'issues', 'help',
                   'quit', 'quit-force'}
SCREEN_IDS = {'components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config', 'theme'}
KNOWN_ACTIONS = {
    'global': _GLOBAL_ACTIONS,
    'components': {'where', 'lock', 'expand-all', 'select-all', 'clear', 'method', 'op-install',
                   'op-upgrade', 'op-install-all', 'op-upgrade-all', 'op-remove', 'execute',
                   'refresh', 'mode'},
    'config': {'theme', 'move'},
    'dotfiles': {'manage', 'manage-all', 'unmanage', 'unmanage-all', 'move-store', 'move-store-all'},
    'glue': {'activate', 'activate-group', 'deactivate'},
    'plugins': {'add', 'remove', 'sync', 'sync-all', 'bless', 'unbless', 'update', 'update-all',
                'trust', 'trust-all', 'set-ref'},
    'profiles': {'track-all', 'track-one', 'select-all', 'method', 'comp-machines', 'machine-target',
                 'attr-filter', 'toggle-install', 'stage-uninstall', 'disp-interesting', 'disp-seen',
                 'disp-interesting-all', 'disp-seen-all', 'mark-all-seen', 'claim', 'orphan-ignore',
                 'where'},
    'theme': {'new', 'reset', 'edit-bg', 'effect-bold', 'effect-underline', 'effect-reverse',
              'gradient-toggle', 'copy-page', 'save', 'load',
              'page-1', 'page-2', 'page-3', 'page-4', 'page-5', 'page-6', 'page-7'},
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
    'op-install': 'make current: install if missing, else upgrade',
    'op-install-all': 'make every tracked component current',
    'op-upgrade': 'stage upgrade (outdated only)', 'op-upgrade-all': 'upgrade every outdated component',
    'op-remove': 'stage remove',
    'execute': 'run staged ops', 'refresh': 'refresh versions + package index',
    'mode': 'cycle view: to-do / tracked / installed+tracked',
    'theme': 'open the theme editor', 'move': 'move setting: local ⇄ primary',
    'manage': 'manage: capture + link', 'manage-all': 'manage every unmanaged config',
    'unmanage': 'unmanage (unlink; confirms)', 'unmanage-all': 'unmanage every managed config',
    'move-store': 'move store: local ⇄ primary', 'move-store-all': 'move all configs to a store',
    'activate': 'activate for this shell', 'activate-group': "(re)activate this shell's group",
    'deactivate': 'deactivate for this shell',
    'add': 'add a plugin', 'remove': 'remove plugin', 'sync': 'sync plugin', 'sync-all': 'sync all',
    'bless': 'bless: make it your primary plugin', 'unbless': 'clear the primary plugin',
    'update': 'update plugin to its latest ref', 'update-all': 'update all to latest',
    'trust': 'trust / untrust plugin', 'trust-all': 'trust every untrusted plugin',
    'set-ref': 'set git ref + re-sync',
    'attr-filter': 'filter by attrs',
    'track-all': 'toggle tracking: set / whole profile', 'track-one': 'toggle tracking: highlighted',
    'select-all': 'select all in view', 'machine-target': 'choose target machines',
    'comp-machines': 'machines for this component',
    'disp-interesting': 'toggle interesting', 'disp-seen': 'toggle new / seen',
    'disp-interesting-all': 'mark set / profile interesting', 'disp-seen-all': 'mark set / profile seen',
    'mark-all-seen': 'mark all NEW seen', 'claim': 'track all installed',
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
        where = os.path.basename(getattr(lyr, 'path', '') or '?')
        for scope, actions in keys.items():
            if not isinstance(actions, dict):
                out.append(f"{where}: keys.{scope} is not a map — ignored")
                continue
            if scope not in KNOWN_ACTIONS and scope != 'screens':
                out.append(f"{where}: unknown key scope '{scope}' "
                           f"(scopes: screens, {', '.join(sorted(KNOWN_ACTIONS))})")
                continue
            valid = _valid_actions(scope)
            seen = {}                                  # code -> action, for self-conflict within a scope
            for action, spec in actions.items():
                if action not in valid:
                    out.append(f"{where}: unknown action 'keys.{scope}.{action}' "
                               f"(not a {scope} action)")
                specs = spec if isinstance(spec, list) else [spec]
                for k in specs:
                    code = parse_key(k)
                    if code is None:
                        out.append(f"{where}: keys.{scope}.{action}: unparseable key '{k}'")
                        continue
                    if code in seen and seen[code] != action:
                        out.append(f"{where}: keys.{scope}: '{k}' bound to both "
                                   f"'{seen[code]}' and '{action}'")
                    else:
                        seen[code] = action
    # ACROSS layers: a higher layer rebinding a key a lower layer gave another action in the same
    # scope. The TUI resolves it rebind-wins (merge_layer_keys) — report what got taken.
    merged = merge_layer_keys(layers, warnings=out)
    out.extend(lint_merged(merged, only_lockout=True))
    return out


def lint_merged(keys, only_lockout=False):
    '''Lint a MERGED `keys:` map (`{scope: {action: spec}}`, e.g. Config.keys() / config_keys()):
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
                    out.append(f"keys.{scope}: '{k}' bound to both '{seen[c]}' and '{action}' "
                               f"(the TUI uses '{seen[c]}')")
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
            out.append(f"keys.{scope}: every quit / quit-force key is bound to another action "
                       f"on this page — there is no way to quit from it")
    return out
