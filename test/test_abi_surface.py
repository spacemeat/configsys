'''The frozen plugin ABI surface (docs/plugins.md §7a). A code plugin codes against
exactly what `configsys.plugins` re-exports; these tests are the regression gate that keeps
that contract from drifting without a deliberate ABI_VERSION bump.'''

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
    for attr in ('name', 'privileged', 'default_scope', 'honors_scope'):
        assert hasattr(D, attr)
    # ops a driver implements + optional overrides
    for op in ('get_version', 'get_latest', 'is_locked', 'install', 'uninstall', 'upgrade',
               'set_version', 'lock', 'unlock', 'location', 'scope'):
        assert callable(getattr(D, op)), op
    # promoted public helpers (the two clusters)
    for helper in ('resolve_version', 'download_url', 'arch',
                   'scoped_dir', 'sudo', 'display_path'):
        assert callable(getattr(D, helper)), helper


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
