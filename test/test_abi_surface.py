'''The frozen plugin ABI surface (docs/plugins.md §7a). A code plugin codes against
exactly what `configsys.plugins` re-exports; these tests are the regression gate that keeps
that contract from drifting without a deliberate ABI_VERSION bump.'''

import types

import configsys.plugins as api
from configsys.drivers import get_driver, is_supported, supported_names
from configsys.runner import Runner


def test_one_line_import_surface():
    # the whole contract a plugin author needs, from one module
    from configsys.plugins import (Driver, register_driver, register_version_source,
                                   register_transport, Result, ABI_VERSION, ABI_SUPPORTED)
    assert ABI_VERSION in ABI_SUPPORTED
    assert isinstance(ABI_VERSION, int)
    assert Result('ok', 0).ok and not Result('no', 1).ok      # the mutating-op return type
    assert callable(register_version_source) and callable(register_transport)
    for name in ('Driver', 'register_driver', 'register_version_source', 'register_transport',
                 'Result', 'ABI_VERSION', 'ABI_SUPPORTED'):
        assert name in api.__all__


def test_driver_public_contract_present():
    D = api.Driver
    # class attributes a driver sets
    for attr in ('name', 'privileged', 'default_scope', 'honors_scope', 'targets_version'):
        assert hasattr(D, attr)
    # ops a driver implements + optional overrides
    for op in ('get_version', 'get_latest', 'is_locked', 'install', 'uninstall', 'upgrade',
               'set_version', 'lock', 'unlock', 'location', 'scope'):
        assert callable(getattr(D, op)), op
    # promoted public helpers (the two clusters)
    for helper in ('resolve_version', 'download_url', 'arch',
                   'scoped_dir', 'sudo', 'display_path'):
        assert callable(getattr(D, helper)), helper


# the optional hooks frozen 2026-10-10 (no ABI bump: a new promise about existing members)
FROZEN_ATTRS = ('targets_version', 'holds_version', 'native_backed', 'batch')
FROZEN_HOOKS = ('get_installed', 'reconcile_scope', 'installed_index', 'index_key', 'batch_index',
                'batch_installed_index', 'batched_version', 'explicit_keys', 'origin_index',
                'upgradable_index', 'update_dedup_key', 'held_keys', 'classify_index', 'upgrade_all',
                'outdated_signal', 'upstream_version', 'download_target', 'arch_token',
                'location_override', 'command_trusted', 'untrusted_command_result')


def test_frozen_optional_hooks_present():
    D = api.Driver
    for attr in FROZEN_ATTRS:
        assert hasattr(D, attr), attr
    for hook in FROZEN_HOOKS:
        assert callable(getattr(D, hook)), hook
    import configsys.driver
    for name in FROZEN_ATTRS + FROZEN_HOOKS:       # the module docstring's frozen list names each one
        assert name in configsys.driver.__doc__, name


def test_frozen_hook_defaults_keep_their_contract():
    # a driver that overrides none of them still works: per-unit probes, out of the bulk lanes
    class Bare(api.Driver):
        name = 'bare-test'
    d = Bare(Runner(pretend=True))
    rc = types.SimpleNamespace(name='pkg', fields={}, comp='pkg')
    assert d.installed_index() is None and d.batch_index([rc]) is None
    assert d.index_key(rc) == 'pkg'
    assert d.batched_version(rc) == (None, False)
    d.batch = {'installed': {'pkg': '1.2'}}               # what the core sets after batch_index
    assert d.batched_version(rc) == ('1.2', True)
    assert d.batch_installed_index(d.batch) == {'pkg': '1.2'}
    assert d.upgradable_index() is None and d.held_keys() is None and d.upgrade_all() is None
    assert d.outdated_signal(rc) is None
    assert d.location_override(rc) is None
    assert d.holds_version is True and d.native_backed is False and d.targets_version is True


def test_internals_stay_underscored():
    # implementation details that are NOT part of the frozen surface
    for internal in ('_scope', '_apply_placeholders', '_disco_spec'):
        assert hasattr(api.Driver, internal)          # still there, just not promoted
        assert internal not in api.__all__


def test_register_and_resolve_a_plugin_driver():
    class Zypper(api.Driver):
        name = 'zypper-test'
        privileged = True

        def install(self, rc):
            return self.runner.run(f'zypper install -y {rc.name}', sudo=self.sudo(rc))

    returned = api.register_driver(Zypper)
    assert returned is Zypper                          # usable as a decorator
    assert is_supported('zypper-test')
    assert 'zypper-test' in supported_names()
    d = get_driver('zypper-test', Runner(pretend=True))
    assert isinstance(d, Zypper)


def test_register_rejects_a_nameless_driver():
    class Anon(api.Driver):
        pass                                           # no `name`

    try:
        api.register_driver(Anon)
        assert False, 'expected ValueError for a nameless driver'
    except ValueError:
        pass
