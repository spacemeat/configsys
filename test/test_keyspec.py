'''keyspec: parsing key names <-> codes, and the Keymap resolved from a merged `keys:` dict. Pure —
no curses runtime (only the KEY_* int constants).'''

import curses

from configsys import layers
from configsys.config import Config
from configsys.tui.keyspec import Keymap, key_name, parse_key


def test_parse_key_forms():
    assert parse_key('g') == ord('g') and parse_key('G') == ord('G')      # case-SENSITIVE
    assert parse_key('1') == ord('1')                                     # a digit is its char
    assert parse_key('enter') == ord('\n') and parse_key('tab') == ord('\t')
    assert parse_key('up') == curses.KEY_UP and parse_key('PgDn') == curses.KEY_NPAGE
    assert parse_key('shift-tab') == curses.KEY_BTAB
    assert parse_key('ctrl-c') == 3 and parse_key('^c') == 3 and parse_key('c-a') == 1
    assert parse_key('f5') == curses.KEY_F0 + 5
    assert parse_key('nope') is None and parse_key('') is None and parse_key(None) is None


def test_key_name_glyphs():
    assert key_name(curses.KEY_DOWN) == '↓' and key_name(ord('q')) == 'q'
    assert key_name(ord('\t')) == 'tab' and key_name(3) == '^c'
    assert key_name(curses.KEY_F0 + 3) == 'F3'


def test_keymap_resolution_override_and_fallback():
    km = Keymap({'global': {'quit': 'q', 'down': ['j', 'down']},
                 'screens': {'components': '1', 'theme': 't'},
                 'components': {'expand-all': 'tab', 'op-install': 'i'}})
    assert km.action_for('global', ord('q')) == 'quit'
    assert km.action_for('global', ord('j')) == 'down'
    assert km.action_for('global', curses.KEY_DOWN) == 'down'            # a list alternate
    assert km.screen_for(ord('1')) == 'components' and km.screen_for(ord('t')) == 'theme'
    # a page scope resolves its own action, and falls back to global for keys it doesn't bind
    assert km.action_for('components', ord('i')) == 'op-install'
    assert km.action_for('components', ord('q')) == 'quit'
    assert km.glyph('global', 'quit') == 'q' and km.glyph('screens', 'theme') == 't'


def test_keymap_fallback_when_section_missing():
    km = Keymap({})                                                      # empty -> the safety net
    assert km.action_for('global', ord('q')) == 'quit'
    assert km.screen_for(ord('1')) == 'components'


def _cfg(*texts):
    roles = ['repo'] + ['user'] * (len(texts) - 1)
    return Config([layers.Layer(f'l{i}.hu', roles[i], layers.materialize_string(t))
                   for i, t in enumerate(texts)])


def test_config_keys_merge_across_layers_feeds_keymap():
    c = _cfg(
        '{ keys: { global: { quit: q  down: [ j down ] }  screens: { components: "1" } } }',
        '{ keys: { global: { quit: [ q  "ctrl-c" ] }  components: { op-install: i } } }',
    )
    k = c.keys()
    assert k['global']['quit'] == ['q', 'ctrl-c']       # a higher layer overrides that action
    assert k['global']['down'] == ['j', 'down']         # a repo action it didn't touch survives
    assert k['screens']['components'] == '1'
    assert k['components']['op-install'] == 'i'          # a new scope from the higher layer
    km = Keymap(k)
    assert km.action_for('global', 3) == 'quit'         # ctrl-c now quits
    assert km.action_for('global', ord('q')) == 'quit'  # the original alternate still works


def test_repo_config_hu_defines_a_full_global_keymap():
    # the base bindings live in the repo config.hu (humon), not a Python dict — assert they load.
    import os
    repo_cfg = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.hu')
    c = _cfg(open(repo_cfg, encoding='utf-8').read())
    km = Keymap(c.keys())
    for a in ('quit', 'issues', 'down', 'up', 'find'):
        assert km.keys_for('global', a), f'{a} unbound in the repo base keymap'
    assert km.screen_for(ord('6')) == 'theme'
