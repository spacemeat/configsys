'''D1 (routing-overhaul phase 0): a provider-pin is TOP precedence and must not be silently shadowed
by the capability-reuse cache. Previously `_satisfy` returned an inventory hit BEFORE consulting the
pin, so a pin on an env-provided or already-wanted capability was ignored.'''

from configsys.routes import Resolver


def _resolve(tmp_path, os_block, comps, names, pins=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + os_block + '  components: { ' + comps + ' } }')
    return set(Resolver(str(p), 'debian', '12', pins=pins).resolve_names(names))


ENV_OS = 'os: { linux: {}  debian: { using: linux  native: apt  provides: cap } }'
OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def test_pin_honored_over_env_provided_capability(tmp_path):
    '''cap is provided by the OS environment (inventory seeds it as satisfied-by-env, no unit). A
    provider-pin must still install the pinned provider — before the fix, reuse returned the empty
    env set and the pin was silently dropped.'''
    comps = '''
        prov-b:   { provides: cap  install: [ { via: native } ] }
        consumer: { requires: cap  install: [ { via: native } ] }
    '''
    assert _resolve(tmp_path, ENV_OS, comps, ['consumer']) == {'apt\\consumer'}   # env satisfies, no unit
    assert _resolve(tmp_path, ENV_OS, comps, ['consumer'], pins={'cap': 'prov-b'}) == {
        'apt\\consumer', 'apt\\prov-b'}                                            # pin now wins


def test_pin_honored_over_an_earlier_wanted_provider(tmp_path):
    '''prov-a is explicitly wanted (phase-1 seeds cap -> {prov-a}); a provider-pin cap->prov-b must
    still route the generic consumer to prov-b, not silently reuse prov-a.'''
    comps = '''
        prov-a:   { provides: cap  install: [ { via: native } ] }
        prov-b:   { provides: cap  install: [ { via: native } ] }
        consumer: { requires: cap  install: [ { via: native } ] }
    '''
    got = _resolve(tmp_path, OS, comps, ['prov-a', 'consumer'], pins={'cap': 'prov-b'})
    assert 'apt\\prov-b' in got            # the pinned provider is pulled...
    assert 'apt\\prov-a' in got            # ...alongside the explicitly-wanted prov-a
    assert 'apt\\consumer' in got


def test_no_pin_still_reuses(tmp_path):
    '''Without a pin, the fast reuse path is unchanged (env-satisfied cap pulls no unit).'''
    comps = '''
        prov-b:   { provides: cap  install: [ { via: native } ] }
        consumer: { requires: cap  install: [ { via: native } ] }
    '''
    assert _resolve(tmp_path, ENV_OS, comps, ['consumer']) == {'apt\\consumer'}
