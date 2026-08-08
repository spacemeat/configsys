'''Driver-level `candidate-only` (drivers: { snap: { candidate-only: true } }): a via that is a
VALID, LISTED install method but never wins the auto-default while any ordinary method is valid
here. This lets snap — which must be gated `when: ubuntu` for validity, making it MORE specific
than a broad native binding and so the specificity winner — be offered without hijacking the
Ubuntu default. A binding-pin still forces it; if it is the only valid method it wins.'''

from configsys import routes
from configsys.resolve import candidate_bindings, _select
from configsys.routes import Resolver

OS = ('os: { linux: {}'
      '  debian: { using: linux  native: apt }'
      '  ubuntu: { using: debian  native: apt } }')

# browser: broad native (valid everywhere) + a snap gated to ubuntu (more specific there).
BROWSER = ('browser: { install: [ { via: native }'
           '                       { via: snap  when: "ubuntu"  name: chromium } ] }')
# a component whose ONLY method here is the candidate-only snap.
SNAPONLY = 'thing: { install: [ { via: snap  when: "ubuntu"  name: thing } ] }'


def _write(tmp_path, drivers, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  drivers: { ' + drivers + ' }  components: { ' + comps + ' } }')
    return p


def _resolver(tmp_path, drivers, comps, block='ubuntu', pins=None):
    return Resolver(str(_write(tmp_path, drivers, comps)), block, '24.04', pins=pins)


def test_snap_is_listed_but_not_the_ubuntu_default(tmp_path):
    r = _resolver(tmp_path, 'snap: { candidate-only: true }', BROWSER)
    # native wins on Ubuntu even though snap's `when: ubuntu` is the more-specific validity.
    assert set(r.resolve_names(['browser'])) == {'apt\\browser'}
    cx = r.cascade.context('ubuntu', '24.04', None)
    winner, cands, _reason = _select(r.components['browser'], r.cascade, cx, r.pins,
                                     r.preference, r.candidate_only)
    assert winner.via == 'native'
    # ...but snap is still a LISTED candidate (the picker/`where` show it).
    assert {b.via for b in candidate_bindings(r.components['browser'], r.cascade, cx)} == \
        {'native', 'snap'}


def test_without_the_flag_snap_would_win_by_specificity(tmp_path):
    # control: same routes, snap NOT candidate-only -> specificity makes snap the Ubuntu default.
    r = _resolver(tmp_path, 'snap: {}', BROWSER)
    assert set(r.resolve_names(['browser'])) == {'snap\\browser'}


def test_binding_pin_still_forces_snap(tmp_path):
    r = _resolver(tmp_path, 'snap: { candidate-only: true }', BROWSER, pins={'browser': 'snap'})
    assert set(r.resolve_names(['browser'])) == {'snap\\browser'}


def test_candidate_only_wins_when_it_is_the_only_method(tmp_path):
    r = _resolver(tmp_path, 'snap: { candidate-only: true }', SNAPONLY)
    assert set(r.resolve_names(['thing'])) == {'snap\\thing'}


def test_flag_is_parsed_off_the_drivers_section(tmp_path):
    r = _resolver(tmp_path, 'snap: { candidate-only: true }', BROWSER)
    assert 'snap' in r.candidate_only
    r2 = _resolver(tmp_path, 'snap: {}', BROWSER)
    assert 'snap' not in r2.candidate_only
