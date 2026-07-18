'''Plugin-vs-plugin conflict surfacing (docs/plugins.md §10). Two plugins claiming the same
component / os block / driver name is an order-dependent collision the layer stack + registry
resolve silently (last wins); `plugin list` and `check` now surface it. Detection is from
manifests + data files only (no code run).'''

from configsys import plugins


def _mk(plugins_dir, name, manifest, files):
    d = plugins_dir / name
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(manifest)
    for fn, text in files.items():
        (d / fn).write_text(text)


ROUTES_A = ('{ os: { alpine: { using: linux  native: apk } }'
            '  components: { mytool: { install: [ { via: native } ] }'
            '               only-a: { install: [ { via: native } ] } } }')
ROUTES_B = ('{ os: { alpine: { using: linux  native: apk } }'
            '  components: { mytool: { install: [ { via: native } ] }'
            '               only-b: { install: [ { via: native } ] } } }')


def test_declared_conflicts_across_plugins(tmp_path):
    pd = tmp_path / 'plugins'
    _mk(pd, 'a', '{ name: a  requires-abi: 1  provides: { drivers: [ apk ] }  data: [ routes.hu ] }',
        {'routes.hu': ROUTES_A})
    _mk(pd, 'b', '{ name: b  requires-abi: 1  provides: { drivers: [ apk ] }  data: [ routes.hu ] }',
        {'routes.hu': ROUTES_B})
    conflicts = plugins.declared_conflicts(pd, [{'source': 'github:x/a'}, {'source': 'github:x/b'}])
    by = {(k, n): dirs for k, n, dirs in conflicts}
    assert by[('component', 'mytool')] == ['a', 'b']   # both define it, with attribution
    assert by[('os', 'alpine')] == ['a', 'b']          # both define the os block
    assert by[('driver', 'apk')] == ['a', 'b']         # both provide the driver
    assert ('component', 'only-a') not in by           # single-plugin names are not conflicts
    assert ('component', 'only-b') not in by


def test_single_plugin_is_never_a_conflict(tmp_path):
    pd = tmp_path / 'plugins'
    _mk(pd, 'a', '{ name: a  requires-abi: 1  provides: { drivers: [ apk ] }  data: [ routes.hu ] }',
        {'routes.hu': ROUTES_A})
    assert plugins.declared_conflicts(pd, [{'source': 'github:x/a'}]) == []


def test_incompatible_plugin_is_excluded(tmp_path):
    pd = tmp_path / 'plugins'
    _mk(pd, 'a', '{ name: a  requires-abi: 1  data: [ r.hu ] }',
        {'r.hu': '{ components: { x: { install: [ { via: native } ] } } }'})
    _mk(pd, 'b', '{ name: b  requires-abi: 99  data: [ r.hu ] }',   # future ABI -> not loaded
        {'r.hu': '{ components: { x: { install: [ { via: native } ] } } }'})
    assert plugins.declared_conflicts(pd, [{'source': 'github:x/a'},
                                           {'source': 'github:x/b'}]) == []


def test_conflicts_surface_in_list_and_check(tmp_path, capsys):
    from configsys.app import main
    cfg = tmp_path / '.config' / 'configsys'
    pd = cfg / 'plugins'
    _mk(pd, 'a', '{ name: a  requires-abi: 1  provides: { drivers: [ apk ] }  data: [ routes.hu ] }',
        {'routes.hu': ROUTES_A})
    _mk(pd, 'b', '{ name: b  requires-abi: 1  provides: { drivers: [ apk ] }  data: [ routes.hu ] }',
        {'routes.hu': ROUTES_B})
    (cfg / 'configsys.hu').write_text(
        '{ configs: [ ]  plugins: [ { source: "github:x/a" } { source: "github:x/b" } ] }')
    home = ['--home', str(tmp_path), '--os', 'alpine']

    assert main(home + ['plugin', 'list']) == 0
    out = capsys.readouterr().out
    assert "conflict: component 'mytool' claimed by plugins a, b" in out
    assert "conflict: os 'alpine'" in out
    assert "conflict: driver 'apk'" in out

    main(home + ['check'])
    cout = capsys.readouterr().out
    assert "warn    conflict: component 'mytool' claimed by plugins a, b" in cout
