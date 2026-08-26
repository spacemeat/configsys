'''keyspec.py — parse key NAMES <-> curses codes, and a Keymap resolved from the merged `keys:`
config section. The TUI dispatches on ACTIONS (not raw key codes), and its legends read the SAME
Keymap, so bindings and their on-screen hints can never drift. No curses call at import (only the
module's KEY_* int constants, which are available without initscr).

The base bindings live as humon in the repo's config.hu `keys:` section and merge up the layer stack
(repo < plugins < primary < user) via Config.keys() — so a primary plugin's configsys.hu, or the top
user config, overlays them per action. There is deliberately no Python default map; the humon file IS
the default. A tiny FALLBACK here only guards against a missing/broken repo section bricking the TUI.'''

import curses

# name -> code, for keys that aren't a single literal character. Case-insensitive.
_NAMED = {
    'enter': ord('\n'), 'return': ord('\n'), 'ret': ord('\n'), 'cr': ord('\n'),
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
    ord('\n'): '⏎', ord('\t'): 'tab', 27: 'esc', ord(' '): 'space',
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
    'global': {'quit': 'q', 'issues': '!'},
    'screens': {'components': '1', 'profiles': '2', 'plugins': '3', 'dotfiles': '4',
                'config': '5', 'theme': '6'},
}


class Keymap:
    '''Resolved bindings: `{scope: {action: [codes]}}`. Built from the merged `keys:` dict (already
    layer-merged by Config.keys()). Page scopes override the `global` scope for the same key.'''

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

    def keys_for(self, scope, action):
        '''Every code bound to `action` in `scope` (empty if none).'''
        return self._m.get(scope, {}).get(action, [])

    def screen_for(self, code):
        '''The screen id `code` switches to (the `screens` scope), or None.'''
        for sid, codes in self._m.get('screens', {}).items():
            if code in codes:
                return sid
        return None

    def glyph(self, scope, action):
        '''The primary key for `action` as a legend glyph (scope, then global). '?' if unbound.'''
        codes = self.keys_for(scope, action) or self.keys_for('global', action)
        return key_name(codes[0]) if codes else '?'

    def help_rows(self, scope):
        '''[(keys, label)] for the `?` overlay: the shared global keys first, then this page's own
        actions. page-1..page-6 collapse to one row; up to two alternate keys are shown per action.'''
        order = ['down', 'up', 'left', 'right', 'top', 'bottom', 'select', 'confirm', 'switch-pane',
                 'switch-pane-back', 'find', 'filter', 'issues', 'help', 'quit']
        rows, seen_page = [], False

        def keyglyph(sc, action):
            codes = self.keys_for(sc, action)
            return '/'.join(key_name(c) for c in codes[:2]) if codes else ''

        for a in order:                                    # global (shared) keys, in a readable order
            if a in self._m.get('global', {}):
                rows.append((keyglyph('global', a), ACTION_LABELS.get(a, a)))
        for a in sorted(self._m.get(scope, {})):           # then the page's own actions
            if a.startswith('page-'):
                if not seen_page:
                    seen_page = True
                    lo, hi = self.keys_for(scope, 'page-1'), self.keys_for(scope, 'page-6')
                    g = f'{key_name(lo[0])}-{key_name(hi[0])}' if lo and hi else 'F1-F6'
                    rows.append((g, 'preview sample page'))
                continue
            rows.append((keyglyph(scope, a), ACTION_LABELS.get(a, a)))
        return rows


# The canonical actions each scope's dispatch understands — the contract `configsys check` lints a
# user's `keys:` against. A page scope may ALSO bind any `global` action (to rebind nav on that page),
# so a page's valid set is its own actions ∪ global's. `screens` binds screen ids, not actions.
_GLOBAL_ACTIONS = {'down', 'up', 'left', 'right', 'top', 'bottom', 'select', 'confirm', 'switch-pane',
                   'switch-pane-back', 'find', 'filter', 'issues', 'help', 'quit'}
SCREEN_IDS = {'components', 'profiles', 'plugins', 'dotfiles', 'config', 'theme'}
KNOWN_ACTIONS = {
    'global': _GLOBAL_ACTIONS,
    'components': {'where', 'lock', 'expand-all', 'select-all', 'clear', 'method', 'op-install',
                   'op-upgrade', 'op-remove', 'execute', 'refresh'},
    'config': {'theme', 'move'},
    'dotfiles': {'unlink', 'capture', 'migrate', 'capture-all', 'link-all', 'migrate-all'},
    'plugins': {'add', 'remove', 'sync', 'sync-all', 'bless', 'unbless', 'update', 'update-all',
                'trust', 'trust-all', 'set-ref'},
    'profiles': {'star', 'toggle-member', 'toggle-active', 'new', 'delete', 'include', 'method',
                 'attr-filter', 'toggle-install', 'stage', 'stage-uninstall', 'orphan-ignore'},
    'theme': {'new', 'reset', 'edit-bg', 'effect-bold', 'effect-underline', 'effect-reverse',
              'gradient-toggle', 'copy-page', 'save', 'load',
              'page-1', 'page-2', 'page-3', 'page-4', 'page-5', 'page-6'},
}


# Human labels for each action — used by the per-page `?` help overlay (and available to anything that
# wants to describe a binding). An action absent here falls back to its id.
ACTION_LABELS = {
    'down': 'move down', 'up': 'move up', 'left': 'left / collapse', 'right': 'right / expand',
    'top': 'jump to top', 'bottom': 'jump to bottom', 'select': 'select / mark', 'confirm': 'activate / open',
    'switch-pane': 'switch pane', 'switch-pane-back': 'switch pane (back)', 'find': 'find (jump cursor)',
    'filter': 'filter (narrow the list)', 'issues': 'show issues (!)', 'help': 'this help', 'quit': 'quit',
    'where': 'explain component (where)', 'lock': 'lock / unlock version', 'expand-all': 'expand / collapse all',
    'select-all': 'select all', 'clear': 'clear selection + staged', 'method': 'pick install method / provider',
    'op-install': 'stage install', 'op-upgrade': 'stage upgrade', 'op-remove': 'stage remove',
    'execute': 'run staged ops', 'refresh': 'refresh versions + package index',
    'theme': 'open the theme editor', 'move': 'move setting: local ⇄ primary',
    'unlink': 'unlink', 'capture': 'capture on-system config', 'migrate': 'migrate (this component)',
    'capture-all': 'capture all', 'link-all': 'link all captured', 'migrate-all': 'migrate all',
    'add': 'add a plugin', 'remove': 'remove plugin', 'sync': 'sync plugin', 'sync-all': 'sync all',
    'bless': 'bless (trust content)', 'unbless': 'unbless', 'update': 'update plugin', 'update-all': 'update all',
    'trust': 'trust code plugin', 'trust-all': 'trust all code', 'set-ref': 'set git ref',
    'star': 'star (cycle: filter · +removed · off)', 'toggle-member': 'include / exclude subprofile', 'toggle-active': 'activate / deactivate',
    'new': 'new', 'delete': 'delete', 'include': 'include another profile (+)', 'attr-filter': 'filter by attrs',
    'toggle-install': 'overlay install (cycle: on · +ignored · off)',
    'stage': 'stage orphan for triage', 'stage-uninstall': 'stage uninstall (→ !uninstall)',
    'orphan-ignore': 'ignore / un-ignore this orphan',
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
    for its scope (typo), an unparseable key name, and — per layer, per scope — the same key bound to
    two different actions (a self-conflict; a page key that shadows a `global` one is NOT flagged, that
    override is intentional and page-wins). `layers` is an iterable of objects with `.data` (dict) and
    `.path`.'''
    import os
    out = []
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
    return out
