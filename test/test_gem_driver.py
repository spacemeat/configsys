from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.gem import Gem
from configsys.runner import Result, Runner


def gem(name='bundler', scope=None):
    fields = {'name': name}
    if scope:
        fields['scope'] = scope
    return ResolvedComponent(key=f'gem\\{name}', driver='gem', comp=name, fields=fields)


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


def test_registered_and_scope_honoring():
    d = get_driver('gem', Runner(pretend=True))
    assert isinstance(d, Gem) and is_supported('gem')
    assert d.privileged is False and d.honors_scope is True


def test_user_scope_uses_user_install_no_sudo():
    r = Runner(pretend=True)
    Gem(r).install(gem())
    assert r.calls == ['gem install --user-install bundler']


def test_system_scope_uses_sudo_no_user_install():
    r = Runner(pretend=True)
    Gem(r).install(gem(scope='system'))
    assert r.calls == ['sudo gem install bundler']


def test_set_version_pins_with_user_flag():
    r = Runner(pretend=True)
    Gem(r).set_version(gem(), '2.5.9')
    assert r.calls == ['gem install --user-install -v 2.5.9 bundler']


def test_uninstall_and_upgrade():
    r = Runner(pretend=True)
    Gem(r).uninstall(gem())
    Gem(r).upgrade(gem())
    assert r.calls == ['gem uninstall -x bundler', 'gem update bundler']


def test_get_version_parses_list():
    fr = FakeRunner([('gem list -e', 0, 'bundler (2.5.9, 2.4.1)\n')])
    assert Gem(fr).get_version(gem()) == '2.5.9'


def test_get_version_not_installed():
    fr = FakeRunner([('gem list -e', 0, '\n')])
    assert Gem(fr).get_version(gem()) is None


def test_get_latest_none_without_spec_and_no_lock():
    d = Gem(Runner(pretend=True))
    assert d.get_latest(gem()) is None
    assert d.is_locked(gem()) is False


def test_location_follows_scope():
    d = Gem(Runner(pretend=True))
    assert d.location(gem()) == '~/.gem'
    assert d.location(gem(scope='system')) is None
