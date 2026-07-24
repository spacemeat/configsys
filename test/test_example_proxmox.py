'''The examples/configsys-proxmox reference plugin — a pure-DATA plugin that adds a *detectable*
derivative OS. Proves the `detect:` marker mechanism + that one os block makes the whole
debian-family catalog install on a PVE host, with no code and no trust step.'''

import os
from pathlib import Path

from configsys import osdetect
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'configsys-proxmox'


def _resolver(block):
    return Resolver(ROUTES, block, None, 'x86_64',
                    plugin_files=[(str(EXAMPLE / 'routes.hu'), 'plugin')])


def test_os_block_and_detect_marker_load():
    r = _resolver('proxmox')
    assert 'proxmox' in r.cascade.blocks
    det = r.cascade.blocks['proxmox']['detect']
    assert det['id'] == 'debian' and det['marker'] == '/etc/pve'


def test_detect_refines_debian_with_marker_to_proxmox():
    r = _resolver('debian')
    # an ID=debian host WITH /etc/pve is really proxmox; without it, plain debian
    assert osdetect.refine('debian', r.cascade, env={}, exists=lambda p: p == '/etc/pve') == 'proxmox'
    assert osdetect.refine('debian', r.cascade, env={}, exists=lambda p: False) == 'debian'


def test_native_catalog_installs_via_apt_on_proxmox():
    r = _resolver('proxmox')
    # a plain repo `via: native` component routes through apt (debian family) — zero per-component work
    assert 'apt\\btop' in r.resolve_names(['btop'])


def test_pve_specific_component_resolves_only_on_proxmox():
    r = _resolver('proxmox')
    units = r.resolve_names(['proxmox-headers'])
    assert units['apt\\proxmox-headers'].name == 'proxmox-default-headers'
