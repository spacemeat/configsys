'''User component overrides (#2): ~/configsys.hu's `components:` section overlays routes.hu
per component name — redefine (all-or-nothing), add new, or remove with {}.'''

import os

import pytest

from configsys.errors import ConfigError
from configsys.resolve import ResolveError
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolver(tmp_path, overrides_text, block='pop_os!', ver='22.04'):
    p = tmp_path / 'configsys.hu'
    p.write_text(overrides_text)
    return Resolver(ROUTES, block, ver, 'x86_64', overrides_path=str(p))


def test_no_components_section_is_a_noop(tmp_path):
    # a user file with only `configs:` (the common case) changes nothing
    r = _resolver(tmp_path, '{ configs: [ dev ] }')
    assert 'apt\\steam' in r.resolve_names(['steam'])          # still native on Pop


def test_missing_user_file_is_fine():
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64',
                 overrides_path='/no/such/configsys.hu')
    assert 'apt\\steam' in r.resolve_names(['steam'])


def test_override_reroutes_a_component(tmp_path):
    # steam is native on Pop by default; the user forces flatpak by redefining it
    r = _resolver(tmp_path, '''{
        components: {
            steam: { install: [ { via: flatpak  hub: flathub  app: com.valvesoftware.Steam } ] }
        }
    }''')
    units = r.resolve_names(['steam'])
    assert 'flatpak\\steam' in units and 'apt\\steam' not in units
    assert 'apt\\flatpak' in units                             # the flatpak tool comes along


def test_override_adds_a_new_component(tmp_path):
    r = _resolver(tmp_path, '{ components: { my-cli: { install: [ { via: native } ] } } }')
    assert 'apt\\my-cli' in r.resolve_names(['my-cli'])


def test_empty_override_removes_a_component(tmp_path):
    # firefox: {} -> resolving firefox yields nothing, no error (a directly-named removed
    # component is a no-op, so a profile can keep listing it harmlessly)
    r = _resolver(tmp_path, '{ components: { firefox: {} } }')
    assert r.resolve_names(['firefox']) == {}


def test_removed_component_still_required_errors(tmp_path):
    # remove bash-dotfiles, which xclip-dotfiles requires -> a clear "nothing provides" error
    r = _resolver(tmp_path, '{ components: { bash-dotfiles: {} } }')
    with pytest.raises(ResolveError, match='bash-dotfiles'):
        r.resolve_names(['xclip-dotfiles'])


def test_override_is_per_name_others_untouched(tmp_path):
    r = _resolver(tmp_path, '{ components: { firefox: {} } }')
    assert 'apt\\btop' in r.resolve_names(['btop'])            # unrelated component unchanged


def test_malformed_override_raises_config_error_not_traceback(tmp_path):
    # a stray/unknown key in a user component is a clean ConfigError (caught by the app),
    # attributed to the user file
    r_text = '{ components: { bad: { dotfiles: { src: a  dst: b }  install: [] } } }'
    p = tmp_path / 'configsys.hu'
    p.write_text(r_text)
    with pytest.raises(ConfigError, match='configsys.hu'):
        Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', overrides_path=str(p))


# -- pins (#4): the light reroute tier -----------------------------------

def test_binding_pin_forces_method():
    # steam is native on Pop by default; a binding-pin forces the flatpak binding
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', pins={'steam': 'flatpak'})
    units = r.resolve_names(['steam'])
    assert 'flatpak\\steam' in units and 'apt\\steam' not in units


def test_binding_pin_to_absent_via_errors():
    # pinning to a method the component has no binding for is a clear error
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', pins={'btop': 'flatpak'})
    with pytest.raises(ResolveError, match='pinned'):
        r.resolve_names(['btop'])


def test_provider_pin_disambiguates(tmp_path):
    # two components provide the same capability -> ambiguous; a provider-pin picks one
    p = tmp_path / 'configsys.hu'
    p.write_text('{ components: {'
                 '  cap-a:  { provides: mycap  install: [ { via: native } ] }'
                 '  cap-b:  { provides: mycap  install: [ { via: native } ] }'
                 '  needer: { requires: mycap  install: [ { via: native } ] } } }')
    amb = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', overrides_path=str(p))
    with pytest.raises(ResolveError, match='ambiguous'):
        amb.resolve_names(['needer'])
    pinned = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64',
                      pins={'mycap': 'cap-a'}, overrides_path=str(p))
    units = pinned.resolve_names(['needer'])
    assert 'apt\\cap-a' in units and 'apt\\cap-b' not in units


# -- resilient resolution (inspect/TUI can't be bricked by one bad entry) --

def test_resolve_resilient_reports_unknown_component():
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64')
    units, errors = r.resolve_resilient(['btop', 'ghost-tool', 'gdb'])
    assert 'apt\\btop' in units and 'apt\\gdb' in units        # good ones still resolve
    assert 'apt\\ghost-tool' not in units
    assert 'ghost-tool' in errors and 'unknown component' in errors['ghost-tool']


def test_resolve_resilient_reports_unsatisfiable_requirement(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{ components: { bash-dotfiles: {} } }')      # remove a required component
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', overrides_path=str(p))
    units, errors = r.resolve_resilient(['btop', 'xclip-dotfiles'])
    assert 'apt\\btop' in units                               # unrelated component fine
    assert 'xclip-dotfiles' in errors and 'bash-dotfiles' in errors['xclip-dotfiles']
