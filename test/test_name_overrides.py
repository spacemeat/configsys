'''component-names — per-driver package-name patches for existing components. A higher layer
(a plugin OS, or the user config) overrides the package a component maps to under a given driver,
or says that driver has no package for it (`{}` — that method is then not a candidate, so another
is tried or the pick is an error row) — WITHOUT redefining the component wholesale. This
is the substrate the Void plugin uses to supply xbps names for core components (docker->docker,
r->R, nmap absent). Driver-keyed, so it does NOT touch same-driver splits (Ubuntu-vs-Debian perf).'''

import os

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
    r = _resolver(tmp_path, '{ picks: { this-machine: [ btop ] } }')   # a layer with no component-names
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'btop'


def test_override_replaces_the_package_name(tmp_path):
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: btop-custom } } }')
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'btop-custom'


def test_override_is_driver_scoped(tmp_path):
    # patching the apt name must not leak to dnf (Fedora resolves btop unchanged)
    text = '{ component-names: { apt: { btop: btop-custom } } }'
    on_fedora = _resolver(tmp_path, text, block='fedora', ver='42')
    assert _pkg(on_fedora.resolve_names(['btop']), 'dnf\\btop') == 'btop'


def test_a_drop_takes_that_method_out_of_the_candidates(tmp_path):
    # `{}` says the driver has no package for the component here: that METHOD isn't a candidate
    # (validity, like a false `when:`), so another method is tried — nmap falls through to brew
    r = _resolver(tmp_path, '{ component-names: { apt: { nmap: {} } } }')
    units = r.resolve_names(['ripgrep', 'nmap'])
    assert 'apt\\ripgrep' in units
    assert 'apt\\nmap' not in units and 'brew\\nmap' in units
    assert [c['via'] for c in r.candidates('nmap')] == ['brew']   # the picker sees the same set


def test_a_drop_of_the_only_method_is_an_error_row_not_a_vanish(tmp_path):
    # no candidate left -> the ordinary "no install method here" error row, naming the entry —
    # never a silent no-op (review-2026-11-2 B5's rule: a pick never vanishes without a row)
    r = _resolver(tmp_path, '{ component-names: { apt: { debhelper: {} } } }')
    units, errors = r.resolve_resilient(['debhelper', 'ripgrep'])
    assert 'apt\\ripgrep' in units and not any(k.endswith('\\debhelper') for k in units)
    assert 'debhelper' in errors
    assert 'component-names: { apt: { debhelper: {} } }' in errors['debhelper']


def test_override_via_a_plugin_layer(tmp_path):
    # the real use case: a plugin (not the user) supplies the name patch
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: plugin-btop } } }', as_plugin=True)
    assert _pkg(r.resolve_names(['btop']), 'apt\\btop') == 'plugin-btop'


def test_override_lands_in_install_fields(tmp_path):
    # the driver reads the package off rc.fields['name'] — the override must reach it, not just .name
    r = _resolver(tmp_path, '{ component-names: { apt: { btop: btop-custom } } }')
    rc = r.resolve_names(['btop'])['apt\\btop']
    assert rc.fields.get('name') == 'btop-custom'


def test_where_names_the_drop_that_ruled_a_method_out(tmp_path):
    # `where` says why the apt method isn't a candidate: the `component-names` entry + its layer
    from configsys.app import Context, build_parser, where_report
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text('{ component-names: { apt: { nmap: {} } } }')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'ubuntu:24.04', 'inspect']))
    lines = where_report(ctx, 'nmap')
    apt_line = next(ln for ln in lines if 'via native   when: not (opensuse_leap >= 16)' in ln)
    assert 'not a candidate: `component-names: { apt: { nmap: {} } }`' in apt_line
    assert 'in ~/.config/configsys/configsys.hu' in apt_line and 'apt packages nothing' in apt_line
    assert any('brew\\nmap' in ln for ln in lines)
