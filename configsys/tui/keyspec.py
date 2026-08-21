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
