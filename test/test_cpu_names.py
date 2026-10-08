'''`cpu-names:` — a binding's per-cpu spelling of `$ARCH` (amd64/arm64/x64…), whose keys are also the
cpus upstream ships: on any other cpu the binding is not valid. Unlike a `when: "cpu: …"` gate it
doesn't make the binding more specific, so it never shifts which method is the default.'''

import os
import platform

import pytest

from configsys import routecheck
from configsys.errors import ConfigError
from configsys.resolve import ResolveError, arch_ok, arch_token, resolve_asset
from configsys.routes import Binding, Component, Resolver

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')

PLUGIN = '''{ components: {
    archy: { description: "x"  install: [
        { via: flatpak  hub: flathub  app: org.archy.App }
        { via: tarball  installDir: "$CONFIGSYS_APP_DIR/archy"  cpu-names: { x86_64: amd64  aarch64: arm64 }
          version: { github: a/archy  asset: "archy_*_linux_$ARCH.tar.gz" } } ] }
    x86only: { description: "x"  install: [
        { via: tarball  installDir: "$CONFIGSYS_APP_DIR/x86only"  cpu-names: { x86_64: x64 }
          url: "https://example.com/x86only-linux-$ARCH.tar.gz" } ] }
} }'''


@pytest.fixture
def plugin(tmp_path):
    p = tmp_path / 'archy.hu'
    p.write_text(PLUGIN)
    return str(p)


def test_helpers():
    d = {'cpu-names': {'x86_64': 'amd64', 'aarch64': 'arm64'}}
    assert arch_token(d, 'aarch64') == 'arm64' and arch_token(d, 'x86_64') == 'amd64'
    assert arch_token({}, 'aarch64') == 'aarch64'                 # no map: the raw cpu
    assert arch_ok({'cpu-names': {'x86_64': 'x64'}}, 'aarch64') is False
    assert arch_ok({'cpu-names': {'x86_64': 'x64'}}, None) is True   # undetected cpu never declines
    assert arch_ok({}, 'riscv64') is True
    # an explicit per-cpu asset map declares the supported cpus too (flat, or format-then-cpu)
    assert arch_ok({'asset': {'x86_64': 'a.deb'}}, 'aarch64') is False
    assert arch_ok({'asset': {'deb': {'x86_64': 'a.deb'}, 'rpm': {'x86_64': 'a.rpm'}}}, 'aarch64') is False
    assert arch_ok({'asset': {'deb': {'x86_64': 'a.deb', 'aarch64': 'b.deb'}}}, 'aarch64') is True


def test_resolve_asset_maps_arch_token():
    b = Binding({'via': 'tarball', 'cpu-names': {'x86_64': 'amd64', 'aarch64': 'arm64'},
                 'version': {'github': 'a/b', 'asset': 'b_*_linux_$ARCH.tar.gz'}})
    assert resolve_asset(b, 'aarch64') == 'b_*_linux_arm64.tar.gz'
    assert resolve_asset(b, 'x86_64') == 'b_*_linux_amd64.tar.gz'


def test_arch_names_keys_gate_validity_without_changing_the_default(plugin):
    x86 = Resolver(ROUTES, 'arch', '20260101', 'x86_64', plugin_files=[plugin])
    arm = Resolver(ROUTES, 'arch', '20260101', 'aarch64', plugin_files=[plugin])
    # the arch-declared tarball does NOT out-specific the ungated flatpak: flatpak stays default
    assert 'flatpak\\archy' in x86.resolve_names(['archy'])
    assert 'flatpak\\archy' in arm.resolve_names(['archy'])
    # an x86-only binding declines on aarch64, cleanly at resolve time
    assert 'tarball\\x86only' in x86.resolve_names(['x86only'])
    with pytest.raises(ResolveError):
        arm.resolve_names(['x86only'])


def test_driver_expands_arch_through_the_map(monkeypatch):
    from configsys.drivers import get_driver
    from configsys.runner import Runner
    from configsys.componentObj import ResolvedComponent
    monkeypatch.setattr(platform, 'machine', lambda: 'aarch64')
    drv = get_driver('tarball', Runner(pretend=True))
    rc = ResolvedComponent(key='tarball\\b', driver='tarball', comp='b',
                           fields={'cpu-names': {'x86_64': 'amd64', 'aarch64': 'arm64'},
                                   'version': {'github': 'a/b', 'asset': 'b-$ARCH.tgz'},
                                   'url': 'https://e.com/$VERSION/b-$ARCH.tgz'})
    assert drv.arch_token(rc) == 'arm64'
    assert drv._disco_spec(rc)['asset'] == 'b-arm64.tgz'
    assert drv._apply_placeholders(rc.fields['url'], '1.0', rc) == 'https://e.com/1.0/b-arm64.tgz'


def test_routecheck_validates_and_treats_disjoint_arch_sets_as_disjoint():
    from configsys import routes
    cascade = routes.load(ROUTES)[0]
    bad = Component('bad', {'install': [{'via': 'tarball', 'cpu-names': ['amd64']}]})
    with pytest.raises(ConfigError):
        routecheck.check_component('bad', bad, cascade)
    # two same-via bindings, overlapping when: (both ungated) but disjoint cpu sets -> not ambiguous
    split = Component('split', {'install': [
        {'via': 'tarball', 'cpu-names': {'x86_64': 'x64'}, 'url': 'https://e.com/a-$ARCH'},
        {'via': 'tarball', 'cpu-names': {'aarch64': 'arm64'}, 'url': 'https://e.com/b-$ARCH'}]})
    routecheck.check_component('split', split, cascade)
