'''The data-driven `detect:` marker mechanism: an os block that declares
`detect: { id: <base>  marker: <path> }` reroutes a base OS to itself when the marker exists on
disk (how the configsys-proxmox plugin makes an ID=debian host route to `proxmox` via /etc/pve).
Uses a synthetic plugin layer so core coverage doesn't depend on any external plugin repo.'''

import os

from configsys import osdetect
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')

_PLUGIN = '''{
    os: {
        acme: { using: debian  detect: { id: debian  marker: /etc/acme }  provides: qemu }
    }
    components: {
        acme-tool: { install: [ { via: native  when: "acme"  name: acme-cli } ] }
    }
}'''


def _resolver(tmp_path, block):
    p = tmp_path / 'plug.hu'
    p.write_text(_PLUGIN)
    return Resolver(ROUTES, block, None, 'x86_64', plugin_files=[(str(p), 'plugin')])


def test_detect_block_and_marker_load(tmp_path):
    det = _resolver(tmp_path, 'acme').cascade.blocks['acme']['detect']
    assert det['id'] == 'debian' and det['marker'] == '/etc/acme'


def test_marker_reroutes_base_to_derivative(tmp_path):
    r = _resolver(tmp_path, 'debian')
    assert osdetect.refine('debian', r.cascade, env={}, exists=lambda p: p == '/etc/acme') == 'acme'
    assert osdetect.refine('debian', r.cascade, env={}, exists=lambda p: False) == 'debian'
    # a forced OS is never second-guessed
    assert osdetect.refine('debian', r.cascade, env={'CONFIGSYS_OS': 'debian'},
                           exists=lambda p: True) == 'debian'


def test_base_catalog_installs_via_native_on_derivative(tmp_path):
    # one os block (using: debian) makes the whole debian-family catalog install via apt
    assert 'apt\\btop' in _resolver(tmp_path, 'acme').resolve_names(['btop'])


def test_derivative_specific_component_resolves(tmp_path):
    units = _resolver(tmp_path, 'acme').resolve_names(['acme-tool'])
    assert units['apt\\acme-tool'].name == 'acme-cli'
