'''review-2026-11-2 D9: every CLI verb and every TUI screen action carries a parity decision
(configsys/parity.py) — a new one can't ship unclassified, and every reference points at something real.'''

import argparse

from configsys import parity
from configsys.app import build_parser
from configsys.tui import keyspec


def _subs(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices
    return {}


def _cli_verbs():
    out = set()
    for name, sp in _subs(build_parser()).items():
        inner = _subs(sp)
        out |= {f'{name} {n}' for n in inner} if inner else {name}
    return out


def _tui_actions():
    return {(s, a) for s, acts in keyspec.KNOWN_ACTIONS.items() if s != 'global' for a in acts}


def test_every_cli_verb_has_a_parity_decision():
    missing = sorted(_cli_verbs() - set(parity.CLI_VERBS))
    assert not missing, f'classify these CLI verbs in configsys/parity.py CLI_VERBS: {missing}'
    stale = sorted(set(parity.CLI_VERBS) - _cli_verbs())
    assert not stale, f'CLI_VERBS names verbs that no longer exist: {stale}'


def test_every_tui_action_has_a_parity_decision():
    missing = sorted(_tui_actions() - set(parity.TUI_ACTIONS))
    assert not missing, f'classify these TUI actions in configsys/parity.py TUI_ACTIONS: {missing}'
    stale = sorted(set(parity.TUI_ACTIONS) - _tui_actions())
    assert not stale, f'TUI_ACTIONS names actions that no longer exist: {stale}'


def test_every_counterpart_named_is_real():
    actions = {(s, a) for s, acts in keyspec.KNOWN_ACTIONS.items() for a in acts}
    for verb, v in parity.CLI_VERBS.items():
        if isinstance(v, tuple) and not v[1].startswith('('):
            assert v in actions, f'{verb}: {v} is not a TUI action'
    verbs = _cli_verbs()
    for act, v in parity.TUI_ACTIONS.items():
        if ':' not in v:
            assert v in verbs, f'{act}: {v!r} is not a CLI verb'
