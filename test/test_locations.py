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
