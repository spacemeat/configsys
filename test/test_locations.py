'''Per-component install-location override: the `locations:` section (component -> absolute path),
merged into Config like pins(), injected as the reserved `location-override` field, and honored by
path-based drivers over their computed target — "find/manage this component's install HERE".'''

import types

from configsys import layers
from configsys.componentObj import ResolvedComponent
from configsys.config import Config
from configsys.driver import Driver
from configsys.drivers import get_driver
from configsys.runner import Runner


def test_config_locations_merge_per_key():
    c = Config([
        layers.Layer('repo.hu', 'repo', layers.materialize_string('{ locations: { blender: /opt/b } }')),
        layers.Layer('user.hu', 'user',
                     layers.materialize_string('{ locations: { blender: "~/dev/b"  kicad: /opt/k } }')),
    ])
    assert c.locations() == {'blender': '~/dev/b', 'kicad': '/opt/k'}   # user wins per key


def test_location_override_helper_expands_and_defaults_none():
    d = Driver.__new__(Driver)                       # pure helper: no runner/paths needed
    assert d.location_override(types.SimpleNamespace(fields={})) is None
    got = d.location_override(types.SimpleNamespace(fields={'location-override': '~/dev/blender-git'}))
    assert got is not None and str(got).endswith('/dev/blender-git') and '~' not in str(got)


def test_path_driver_prefers_location_override():
    d = get_driver('source', Runner(pretend=True))
    over = ResolvedComponent(key='source\\rg', driver='source', comp='rg',
                             fields={'installDir': 'ignored', 'location-override': '/opt/rg-src'})
    assert str(d._src_dir(over)) == '/opt/rg-src'                       # override wins over installDir
    plain = ResolvedComponent(key='source\\rg', driver='source', comp='rg',
                              fields={'installDir': '/tmp/rg'})
    assert str(d._src_dir(plain)) == '/tmp/rg'                          # no override -> computed dir


def test_prepare_units_stamps_locations_override_for_op_and_location_paths(tmp_path):
    # regression: install/remove/upgrade/lock and `configsys location` resolve their own units and
    # historically applied ONLY the scope default, ignoring `locations:` — so a relocated component
    # installed/reported at the wrong dir. Context.prepare_units (now on every such path) stamps both.
    from configsys.app import Context, build_parser
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{ locations: { bazelisk: /opt/bztest } }')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    units = ctx.routes.resolve_names(['bazelisk'])
    ctx.prepare_units(units)
    rc = next(u for u in units.values() if u.comp == 'bazelisk')
    assert rc.fields.get('location-override') == '/opt/bztest'


def test_set_included_invalidates_the_glue_location_cache(tmp_path):
    # B4: a pick changes the install set (hence glue PATH targets), so set_included must drop the
    # glue-locations cache — from INSIDE the shared action, so neither the CLI nor the TUI forgets.
    from configsys.app import Context, build_parser
    from configsys import actions
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    ctx.ensure_user_config()                          # the real flow always has a config on disk
    cache = ctx.paths.glue_locations_file
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text('bazelisk\t/x\n')
    assert cache.exists()
    n, _ = actions.set_included(ctx, 'bazelisk', [ctx.config.current_machine()], True)
    assert n == 1 and not cache.exists()
