'''Multi-method selection (Phase 1): a component may offer several install methods valid in the
SAME context (native + flatpak, etc.). `when:` decides VALIDITY only; a separate, total
preference channel picks the default — most-specific when: (same-method specialization), then a
driver-preference order (global or per-OS), then a per-binding `prefer:`. A genuine tie errors
toward the preference channel, never toward narrowing `when:`. A binding-pin picks any candidate.'''

import pytest

from configsys import routes
from configsys.resolve import ResolveError, candidate_bindings, select_binding, _select
from configsys.routes import Resolver

OS = ('os: { linux: {}'
      '  debian: { using: linux  native: apt }'
      '  atomic: { using: linux  native: rpm-ostree  driver-preference: [ flatpak native ] } }')


def _write(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return p


def _resolve(tmp_path, comps, names, block='debian', pins=None, preference=None):
    r = Resolver(str(_write(tmp_path, comps)), block, '12', pins=pins, preference=preference)
    return set(r.resolve_names(names))


def _load(tmp_path, comps):
    return routes.load(str(_write(tmp_path, comps)))     # (cascade, components, drivers)


# a component with two equally-valid methods (no when: on either) -----------
TWO = 'browser: { install: [ { via: native } { via: flatpak  app: org.x.B } ] }'


def test_candidates_are_all_valid_methods(tmp_path):
    cascade, comps, _ = _load(tmp_path, TWO)
    cx = cascade.context('debian', '12', None)
    assert {b.via for b in candidate_bindings(comps['browser'], cascade, cx)} == {'native', 'flatpak'}


def test_default_follows_driver_preference(tmp_path):
    # native beats flatpak by the built-in default order -> apt wins
    assert _resolve(tmp_path, TWO, ['browser']) == {'apt\\browser'}
    cascade, comps, _ = _load(tmp_path, TWO)
    winner, cands, reason = _select(comps['browser'], cascade, cascade.context('debian', '12', None))
    assert winner.via == 'native' and reason == 'driver-preference' and len(cands) == 2


def test_prefer_overrides_the_global_order(tmp_path):
    comps = 'browser: { install: [ { via: native } { via: flatpak  app: X  prefer: 10 } ] }'
    assert _resolve(tmp_path, comps, ['browser']) == {'flatpak\\browser'}
    # prefer: is resolver-only — it must NOT leak into the driver's install fields
    cascade, cs, _ = _load(tmp_path, comps)
    winner = select_binding(cs['browser'], cascade, cascade.context('debian', '12', None))
    from configsys.resolve import _install_fields
    assert 'prefer' not in _install_fields(winner.details, 'X')


def test_per_os_block_preference_override(tmp_path):
    # the `atomic` OS block declares driver-preference: [flatpak native] -> flatpak wins there,
    # while the same component still resolves native on debian (context-dependent default, and
    # NOT smuggled into when:)
    assert _resolve(tmp_path, TWO, ['browser'], block='atomic') == {'flatpak\\browser'}
    assert _resolve(tmp_path, TWO, ['browser'], block='debian') == {'apt\\browser'}


def test_config_global_preference(tmp_path):
    # a machine's driver-preference (passed to the Resolver) flips the default
    assert _resolve(tmp_path, TWO, ['browser'], preference=['flatpak', 'native']) == {'flatpak\\browser'}


def test_binding_pin_picks_a_non_default_candidate(tmp_path):
    assert _resolve(tmp_path, TWO, ['browser'], pins={'browser': 'flatpak'}) == {'flatpak\\browser'}


def test_true_tie_errors_toward_preference_not_when(tmp_path):
    # two methods neither ranked by the default order nor separated by prefer: -> undecidable
    comps = 'tool: { install: [ { via: cargo } { via: gem } ] }'
    with pytest.raises(ResolveError) as e:
        _resolve(tmp_path, comps, ['tool'])
    msg = str(e.value)
    assert 'driver-preference' in msg and 'prefer' in msg
    assert 'do not narrow' in msg.lower()                 # points AWAY from when:


def test_most_specific_same_method_still_wins(tmp_path):
    # two native bindings, comparable when: (debian ⊂ always) -> the specialized one wins as the
    # default (legit specialization, not method-choice); reason is most-specific, not preference
    comps = 'pkg: { install: [ { via: native } { via: native  when: debian  repo-component: extra } ] }'
    cascade, cs, _ = _load(tmp_path, comps)
    winner, _c, reason = _select(cs['pkg'], cascade, cascade.context('debian', '12', None))
    assert reason == 'most-specific when:' and winner.details.get('repo-component') == 'extra'


def test_candidates_collapse_same_via_to_one_row(tmp_path):
    # The picker/pin choose a VIA, not an individual binding — so two comparable native bindings
    # (fastfetch's real bug: a `when: debian` .deb subsumed by a bare `via: native`) must collapse
    # to ONE native row (the one that resolves), alongside genuinely-distinct vias. Guards the
    # picker from showing two indistinguishable "via native" rows.
    comps = ('pkg: { install: [ { via: native } { via: native  when: debian  repo-component: extra }'
             '                   { via: flatpak  app: org.x.P } ] }')
    cands = Resolver(str(_write(tmp_path, comps)), 'debian', '12').candidates('pkg')
    vias = [c['via'] for c in cands]
    assert vias.count('native') == 1 and 'flatpak' in vias        # one native row, plus the distinct via
    native = next(c for c in cands if c['via'] == 'native')
    assert native['when'] == 'debian' and native['default'] is True   # the specialized binding, and it wins
