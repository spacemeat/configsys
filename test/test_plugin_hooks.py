'''P2c — extension hooks beyond drivers: register_version_source (new `version: { <name>: }`
backends) and register_transport (new `source:` sync schemes). Both are registered only from
trusted plugin code (via plugins.load_code), so they inherit the same trust + ABI gate.'''

import pytest

from configsys import plugins, versions
from configsys.runner import Runner


@pytest.fixture(autouse=True)
def _restore_hooks():
    '''The hook registries are process-global; snapshot + restore so nothing leaks.'''
    vs, tr = dict(versions._SOURCES), dict(plugins._TRANSPORTS)
    yield
    versions._SOURCES.clear(); versions._SOURCES.update(vs)
    plugins._TRANSPORTS.clear(); plugins._TRANSPORTS.update(tr)


# -- version-source hook --------------------------------------------------

def test_register_version_source_dispatch():
    calls = []

    def src(spec, fetch):
        calls.append(spec)
        return spec['demo'] + '-resolved', None

    plugins.register_version_source('demo', src)              # the frozen-surface name
    assert versions.discover({'demo': '1.2'}) == '1.2-resolved'
    assert versions.source_key({'demo': '1.2'}) == 'demo:1.2'  # cached under a proper key
    assert calls == [{'demo': '1.2'}]


def test_builtin_sources_win_over_a_registered_name():
    plugins.register_version_source('static', lambda spec, fetch: ('HIJACKED', None))
    assert versions.discover({'static': '3.3'}) == '3.3'       # builtin static still wins


def test_register_source_validates():
    with pytest.raises(ValueError):
        versions.register_source('', lambda s, f: (None, None))
    with pytest.raises(ValueError):
        versions.register_source('x', None)


# -- transport hook -------------------------------------------------------

def test_register_transport_claims_a_scheme(tmp_path):
    seen = {}

    def copy_transport(runner, dest, source, ref):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'plugin.hu').write_text('{ name: t }')
        seen['args'] = (str(dest), source, ref)
        return 'copied'

    plugins.register_transport('demo', copy_transport)
    results = plugins.sync(Runner(pretend=True), tmp_path,
                           [{'source': 'demo:whatever', 'ref': 'v1'}])
    assert results == [('whatever', 'copied')]
    assert (tmp_path / 'whatever' / 'plugin.hu').exists()
    assert seen['args'][1] == 'demo:whatever' and seen['args'][2] == 'v1'


def test_unregistered_scheme_falls_back_to_git(tmp_path):
    r = Runner(pretend=True)
    plugins.sync(r, tmp_path, [{'source': 'github:a/b', 'ref': 'v1'}])
    assert any('git clone' in c for c in r.calls)             # default transport is git


def test_transport_failure_is_isolated(tmp_path):
    plugins.register_transport('boom', lambda *a: (_ for _ in ()).throw(RuntimeError('nope')))
    results = plugins.sync(Runner(pretend=True), tmp_path, [{'source': 'boom:x'}])
    assert results[0][0] == 'x' and 'failed' in results[0][1]  # isolated, not raised


def test_register_transport_validates():
    with pytest.raises(ValueError):
        plugins.register_transport('', lambda *a: None)
    with pytest.raises(ValueError):
        plugins.register_transport('x', None)


# -- the real path: a trusted plugin registers a source via its own code ---

def test_trusted_plugin_registers_a_version_source(tmp_path):
    pdir = tmp_path / 'plugins' / 'srcplug'
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text('{ name: srcplug  requires-abi: 1  code: code.py }')
    (pdir / 'code.py').write_text(
        'from configsys.plugins import register_version_source\n'
        'register_version_source("demo", lambda spec, fetch: (spec["demo"] + "!", None))\n'
        'DRIVERS = []\n')
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'github:x/srcplug'}]

    # untrusted -> code not imported -> the source is never registered
    plugins.load_code(tmp_path / 'plugins', tf, decls, lambda c: None)
    assert versions.discover({'demo': '5'}) is None

    # trust the content -> the module imports -> its register_version_source() ran
    plugins.set_trust(tf, 'srcplug', plugins.plugin_identity(pdir))
    plugins.load_code(tmp_path / 'plugins', tf, decls, lambda c: None)
    assert versions.discover({'demo': '5'}) == '5!'


# -- code-level registration collisions (version-source / transport) ------

def _code_plugin(root, name, code):
    d = root / name
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(f'{{ name: {name}  requires-abi: 1  code: c.py }}')
    (d / 'c.py').write_text(code)
    return d


def _load_trusted(root, tf, names):
    '''Trust + load each named plugin; return the collected code conflicts.'''
    for n in names:
        plugins.set_trust(tf, n, plugins.plugin_identity(root / n))
    conflicts = []
    plugins.load_code(root, tf, [{'source': f'github:x/{n}'} for n in names],
                      lambda c: None, conflicts=conflicts)
    return conflicts


_SRC = ('from configsys.plugins import register_version_source\n'
        'register_version_source({name!r}, lambda s, f: ("1", None))\nDRIVERS = []\n')
_TR = ('from configsys.plugins import register_transport\n'
       'register_transport({name!r}, lambda *a: "ok")\nDRIVERS = []\n')


def test_version_source_collision_between_plugins(tmp_path):
    root = tmp_path / 'plugins'
    _code_plugin(root, 'p1', _SRC.format(name='dup'))
    _code_plugin(root, 'p2', _SRC.format(name='dup'))
    conflicts = _load_trusted(root, tmp_path / 'trust.hu', ['p1', 'p2'])
    assert any("version-source 'dup'" in c and 'p1' in c and 'p2' in c and 'last loaded wins' in c
               for c in conflicts)


def test_transport_collision_between_plugins(tmp_path):
    root = tmp_path / 'plugins'
    _code_plugin(root, 'p1', _TR.format(name='dup'))
    _code_plugin(root, 'p2', _TR.format(name='dup'))
    conflicts = _load_trusted(root, tmp_path / 'trust.hu', ['p1', 'p2'])
    assert any("transport 'dup'" in c and 'last loaded wins' in c for c in conflicts)


def test_registration_shadowing_a_builtin_is_flagged(tmp_path):
    root = tmp_path / 'plugins'
    _code_plugin(root, 'psrc', _SRC.format(name='github'))     # shadows built-in source
    _code_plugin(root, 'ptr', _TR.format(name='github'))       # overrides git's scheme
    conflicts = _load_trusted(root, tmp_path / 'trust.hu', ['psrc', 'ptr'])
    assert any("version-source 'github'" in c and 'shadows a built-in' in c for c in conflicts)
    assert any("transport 'github'" in c and 'overrides the built-in git' in c for c in conflicts)


def test_distinct_registrations_are_not_conflicts(tmp_path):
    root = tmp_path / 'plugins'
    _code_plugin(root, 'p1', _SRC.format(name='aaa'))
    _code_plugin(root, 'p2', _SRC.format(name='bbb'))
    assert _load_trusted(root, tmp_path / 'trust.hu', ['p1', 'p2']) == []


def test_code_conflict_surfaces_in_check(tmp_path, capsys):
    from configsys.app import main
    cfg = tmp_path / '.config' / 'configsys'
    root = cfg / 'plugins'
    _code_plugin(root, 'p1', _SRC.format(name='dup'))
    _code_plugin(root, 'p2', _SRC.format(name='dup'))
    (cfg / 'configsys.hu').write_text(
        '{ configs: [ ]  plugins: [ { source: "github:x/p1" } { source: "github:x/p2" } ] }')
    home = ['--home', str(tmp_path)]
    main(home + ['plugin', 'trust', 'p1'])
    main(home + ['plugin', 'trust', 'p2'])
    capsys.readouterr()
    main(home + ['check'])
    out = capsys.readouterr().out
    assert "conflict: version-source 'dup'" in out and 'p1' in out and 'p2' in out
