'''Per-unit scope is DETECTED from where a thing is actually installed (not the configured
target), so a scope mismatch never reads as "missing" and the menu shows reality.'''

from types import SimpleNamespace as NS

from configsys.driver import Driver
from configsys.drivers.flatpak import Flatpak
from configsys.runner import Result


def rc(**fields):
    return NS(name='app', driver='x', comp='app', fields=dict(fields), vars={})


class _Stub(Driver):
    '''A scope-honoring, path-style driver whose "install" exists only at `present_at`.'''
    name = 'stub'
    honors_scope = True
    default_scope = 'user'

    def __init__(self, present_at):
        super().__init__(runner=None)
        self.present_at = present_at

    def get_version(self, rc):
        return '1.0' if rc.fields.get('scope') == self.present_at else None

    def get_installed(self, rc):                # like tarball/appImage/debian-font
        return self._installed_across_scopes(rc)


def test_probe_finds_the_installed_scope_even_when_target_differs():
    r = rc(scope='user')                       # config targets user...
    assert _Stub('system').get_installed(r) == ('1.0', 'system')   # ...but it's at system
    assert r.fields['scope'] == 'user'         # rc restored (no lasting mutation)


def test_probe_returns_none_when_nowhere():
    assert _Stub('neither')._installed_across_scopes(rc()) == (None, None)


def test_probe_restores_absent_scope_field():
    r = rc()                                   # no scope field at all
    _Stub('user').get_installed(r)
    assert 'scope' not in r.fields             # helper cleaned up after itself


def test_fixed_driver_default_reports_its_scope_when_present():
    class Fixed(Driver):
        name = 'fixed'
        default_scope = 'system'

        def get_version(self, rc):
            return '2.0'
    assert Fixed(runner=None).get_installed(rc()) == ('2.0', 'system')

    class Absent(Fixed):
        def get_version(self, rc):
            return None
    assert Absent(runner=None).get_installed(rc()) == (None, None)


def test_flatpak_reports_which_installation_has_it():
    class FakeRunner:
        pretend = False

        def __init__(self, ok_flag):
            self.ok_flag = ok_flag

        def run(self, cmd, **kw):
            ok = self.ok_flag in cmd
            return Result(cmd, 0 if ok else 1, stdout='Version: 3.1\n' if ok else '')

    fp = Flatpak(FakeRunner('--system'), paths=None)
    assert fp.get_installed(rc(scope='user')) == ('3.1', 'system')   # detected system, not target
    fp2 = Flatpak(FakeRunner('nope'), paths=None)
    assert fp2.get_installed(rc()) == (None, None)
