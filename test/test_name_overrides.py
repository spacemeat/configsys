'''component-names — per-driver package-name patches for existing components. A higher layer
(a plugin OS, or the user config) overrides the package a component maps to under a given driver,
or drops it where that driver has no package — WITHOUT redefining the component wholesale. This
is the substrate the Void plugin uses to supply xbps names for core components (docker->docker,
r->R, nmap absent). Driver-keyed, so it does NOT touch same-driver splits (Ubuntu-vs-Debian perf).'''

import os

from configsys.resolve import ResolveError
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolver(tmp_path, text, block='ubuntu', ver='24.04', as_plugin=False):
    p = tmp_path / 'patch.hu'
    p.write_text(text)
    if as_plugin:
        return Resolver(ROUTES, block, ver, 'x86_64', plugin_files=[(str(p), 'plugin')])
    return Resolver(ROUTES, block, ver, 'x86_64', overrides_path=str(p))


def _pkg(units, key):
    return units[key].name


def test_no_section_is_a_noop(tmp_path):
    r = _resolver(tmp_path, '{ configs: [ dev ] }')
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'btop'


def test_override_replaces_the_package_name(tmp_path):
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: btop-custom } } }')
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'btop-custom'


def test_override_is_driver_scoped(tmp_path):
    # patching the apt name must not leak to dnf (Fedora resolves btop unchanged)
    text = '{ component-names: { apt: { btop: btop-custom } } }'
    on_fedora = _resolver(tmp_path, text, block='fedora', ver='42')
    assert _pkg(on_fedora.resolve_names(['btop']), 'dnf\\btop') == 'btop'


def test_empty_map_drops_the_component(tmp_path):
    # `{}` means the driver has no package for it here -> a silent no-op, like a removed component
    r = _resolver(tmp_path, '{ component-names: { apt: { nmap: {} } } }')
    units = r.resolve_names(['ripgrep', 'nmap'])
    assert 'apt\\ripgrep' in units
    assert 'apt\\nmap' not in units


def test_drop_is_silent_not_an_error_row(tmp_path):
    # resilient resolution treats a drop as not-offered, NOT an error (unlike an unroutable name)
    r = _resolver(tmp_path, '{ component-names: { apt: { nmap: {} } } }')
    units, errors = r.resolve_resilient(['nmap'])
    assert 'nmap' not in errors and not units


def test_override_via_a_plugin_layer(tmp_path):
    # the real use case: a plugin (not the user) supplies the name patch
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: plugin-btop } } }', as_plugin=True)
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'plugin-btop'


def test_override_lands_in_install_fields(tmp_path):
    # the driver reads the package off rc.fields['name'] — the override must reach it, not just .name
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: btop-custom } } }')
    rc = r.resolve_names(['btop'])['apt\\btop']
    assert rc.fields.get('name') == 'btop-custom'
