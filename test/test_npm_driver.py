from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.npm import Npm
from configsys.runner import Result, Runner


def pkg(name='typescript', scope=None):
    fields = {'name': name}
    if scope:
        fields['scope'] = scope
    return ResolvedComponent(key=f'npm\\{name}', driver='npm', comp=name, fields=fields)


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


def test_registered_and_unprivileged():
    d = get_driver('npm', Runner(pretend=True))
    assert isinstance(d, Npm) and is_supported('npm')
    assert d.privileged is False and d.honors_scope is True


def test_user_scope_is_prefixed_and_sudo_free():
    r = Runner(pretend=True)
    Npm(r).install(pkg())
    Npm(r).uninstall(pkg())
    Npm(r).upgrade(pkg())
    assert all('sudo' not in c for c in r.calls)          # userland: never sudo
    assert all('--prefix' in c for c in r.calls)          # into a per-user prefix
    assert r.calls[0].startswith('npm install -g --prefix ')
    assert r.calls[0].endswith(' typescript')


def test_system_scope_uses_global_prefix_and_sudo():
    r = Runner(pretend=True)
    Npm(r).install(pkg(scope='system'))
    assert r.calls == ['sudo npm install -g typescript']   # node's own prefix, with sudo
    assert '--prefix' not in r.calls[0]


def test_set_version_pins_with_at():
    r = Runner(pretend=True)
    Npm(r).set_version(pkg(), '5.4.2')
    assert r.calls[0].endswith(' typescript@5.4.2') and '--prefix' in r.calls[0]


def test_get_version_parses_ls_json():
    listing = '{"dependencies": {"typescript": {"version": "5.4.2"}, "prettier": {"version": "3.2.5"}}}'
    fr = FakeRunner([('npm ls -g', 1, listing)])           # npm ls often exits 1 with valid JSON
    assert Npm(fr).get_version(pkg('typescript')) == '5.4.2'
    assert Npm(fr).get_version(pkg('prettier')) == '3.2.5'


def test_get_version_not_installed():
    fr = FakeRunner([('npm ls -g', 0, '{"dependencies": {"prettier": {"version": "3.2.5"}}}')])
    assert Npm(fr).get_version(pkg('typescript')) is None


def test_get_version_no_output_is_none():
    fr = FakeRunner([('npm ls -g', 1, '')])                # npm not installed at all
    assert Npm(fr).get_version(pkg()) is None


def test_get_latest_none_without_spec_and_no_native_lock():
    d = Npm(Runner(pretend=True))
    assert d.get_latest(pkg()) is None
    assert d.is_locked(pkg()) is False


def test_location_follows_scope():
    d = Npm(Runner(pretend=True))
    assert d.location(pkg()) == '~/.local/bin'             # user scope
    assert d.location(pkg(scope='system')) is None         # system: no single user path
