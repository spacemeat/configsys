from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.brew import Brew
from configsys.runner import Result, Runner


def formula(name='btop'):
    return ResolvedComponent(key=f'brew\\{name}', driver='brew', comp=name,
                             fields={'name': name})


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
    d = get_driver('brew', Runner(pretend=True))
    assert isinstance(d, Brew) and is_supported('brew')
    assert d.privileged is False
    assert d.default_scope == 'user'


def test_install_uninstall_upgrade_never_sudo():
    r = Runner(pretend=True)
    Brew(r).install(formula())
    Brew(r).uninstall(formula())
    Brew(r).upgrade(formula())
    assert r.calls == [
        'brew install btop',
        'brew uninstall btop',
        'brew upgrade btop',
    ]
    assert all('sudo' not in c for c in r.calls)   # user-space, always


def test_lock_unlock_use_pin():
    r = Runner(pretend=True)
    Brew(r).lock(formula())
    Brew(r).unlock(formula())
    assert r.calls == ['brew pin btop', 'brew unpin btop']


def test_set_version_targets_versioned_formula():
    r = Runner(pretend=True)
    Brew(r).set_version(formula('python'), '3.11')
    assert r.calls == ['brew install python@3.11']


def test_get_version_parses_list_versions():
    fr = FakeRunner([('brew list --versions btop', 0, 'btop 1.4.0\n')])
    assert Brew(fr).get_version(formula('btop')) == '1.4.0'


def test_get_version_multiple_kegs_takes_newest():
    fr = FakeRunner([('brew list --versions foo', 0, 'foo 1.2.0 1.3.0\n')])
    assert Brew(fr).get_version(formula('foo')) == '1.3.0'


def test_get_version_not_installed():
    fr = FakeRunner([('brew list --versions btop', 1, '')])   # brew exits nonzero
    assert Brew(fr).get_version(formula('btop')) is None


def test_get_latest_parses_info_json():
    payload = '{"formulae":[{"versions":{"stable":"1.4.0","head":null}}]}'
    fr = FakeRunner([('brew info --json=v2 --formula btop', 0, payload)])
    assert Brew(fr).get_latest(formula('btop')) == '1.4.0'


def test_get_latest_handles_missing_or_bad_json():
    assert Brew(FakeRunner([('brew info', 1, '')])).get_latest(formula()) is None
    assert Brew(FakeRunner([('brew info', 0, 'not json')])).get_latest(formula()) is None


def test_is_locked_reads_pinned():
    pinned = FakeRunner([('brew list --pinned', 0, 'btop\nripgrep\n')])
    assert Brew(pinned).is_locked(formula('btop')) is True
    assert Brew(pinned).is_locked(formula('nmap')) is False
    # brew absent -> not locked, no crash
    assert Brew(FakeRunner([('brew list --pinned', 1, '')])).is_locked(formula()) is False


def test_location_uses_prefix_else_generic():
    fr = FakeRunner([('brew --prefix btop', 0, '/home/linuxbrew/.linuxbrew/opt/btop\n')])
    assert Brew(fr).location(formula('btop')) == '/home/linuxbrew/.linuxbrew/opt/btop'
    # not installed / brew missing -> generic marker
    assert Brew(FakeRunner([('brew --prefix', 1, '')])).location(formula()) == '(homebrew)'


def test_no_homebrew_is_a_true_empty_and_reads_spawn_nothing():
    # command-not-found (127): nothing is installed via brew — {} (not None = "couldn't tell"), and
    # the batched per-unit reads answer from it instead of spawning a missing `brew` 3x per unit
    fr = FakeRunner([('brew list --versions', 127, '')])
    d = Brew(fr)
    assert d.installed_index() == {}
    d.batch = d.batch_index([])
    assert d.batch == {'installed': {}, 'missing': True}
    fr.calls.clear()
    rc = formula('btop')
    assert d.get_version(rc) is None and d.get_latest(rc) is None and d.is_locked(rc) is False
    assert fr.calls == []


def test_a_failing_brew_is_still_unknown_not_empty():
    fr = FakeRunner([('brew list --versions', 1, '')])
    d = Brew(fr)
    assert d.installed_index() is None and d.batch_index([]) is None
