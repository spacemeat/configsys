import pytest
from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.brew import Brew
from configsys.runner import Runner

from fakes import FakeRunner


def formula(name='btop'):
    return ResolvedComponent(key=f'brew\\{name}', driver='brew', comp=name,
                             fields={'name': name})


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


def test_location_is_prefix_opt_formula_without_running_brew(monkeypatch, tmp_path):
    # app-cli-20: what `brew --prefix <formula>` answers, computed — no brew spawn per unit
    import configsys.drivers.brew as B
    monkeypatch.setenv('HOMEBREW_PREFIX', '/home/linuxbrew/.linuxbrew')
    fr = FakeRunner()
    assert Brew(fr).location(formula('btop')) == '/home/linuxbrew/.linuxbrew/opt/btop'
    assert Brew(fr).location(formula('user/tap/thing')) == '/home/linuxbrew/.linuxbrew/opt/thing'
    assert fr.calls == []
    # no $HOMEBREW_PREFIX: the dir above the `brew` on PATH
    monkeypatch.delenv('HOMEBREW_PREFIX')
    monkeypatch.setattr(B.shutil, 'which', lambda n: '/opt/hb/bin/brew' if n == 'brew' else None)
    assert Brew(fr).location(formula('btop')) == '/opt/hb/opt/btop'
    # brew nowhere -> the generic marker
    monkeypatch.setattr(B.shutil, 'which', lambda n: None)
    monkeypatch.setattr(B, '_PREFIXES', (str(tmp_path / 'none'),))
    assert Brew(fr).location(formula()) == '(homebrew)'
    assert fr.calls == []


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


@pytest.mark.real_runner
def test_brew_off_path_is_found_in_its_prefix(tmp_path, monkeypatch):
    # Homebrew installed earlier in the same batch isn't on this process's PATH: the driver still
    # runs `brew …`, with the prefix's bin APPENDED (nothing brew ships shadows a system tool)
    from configsys.drivers import brew
    prefix = tmp_path / 'linuxbrew'
    (prefix / 'bin').mkdir(parents=True)
    exe = prefix / 'bin' / 'brew'
    exe.write_text('#!/bin/sh\necho "brew $*"\n'); exe.chmod(0o755)
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    monkeypatch.setattr(brew, '_PREFIXES', (str(tmp_path / 'absent'), str(prefix)))
    assert brew.brew_env()['PATH'] == f'/usr/bin:/bin:{prefix}/bin'
    assert Runner().run('brew list --versions', env=brew.brew_env()).stdout.strip() == 'brew list --versions'
    monkeypatch.setattr(brew, '_PREFIXES', (str(tmp_path / 'absent'),))
    assert brew.brew_env() is None                                # not installed anywhere: inherit


def test_per_user_prefix_is_under_configsys_home(tmp_path, monkeypatch):
    # `~/.linuxbrew` is configsys's home (--home / CONFIGSYS_HOME), never the real $HOME — a sandboxed
    # run finds (and only finds) the sandbox's Homebrew
    from configsys.drivers import brew as B
    from configsys.paths import Paths
    from configsys.runner import Result
    home = tmp_path / 'home'
    (home / '.linuxbrew' / 'bin').mkdir(parents=True)
    exe = home / '.linuxbrew' / 'bin' / 'brew'
    exe.write_text('#!/bin/sh\n'); exe.chmod(0o755)
    monkeypatch.delenv('HOMEBREW_PREFIX', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path / 'real-home'))         # the real $HOME has no brew
    monkeypatch.setattr(B.shutil, 'which', lambda n: None)
    monkeypatch.setattr(B, '_PREFIXES', (str(tmp_path / 'no-shared'), '~/.linuxbrew'))
    paths = Paths(env={'CONFIGSYS_HOME': str(home)})
    assert Brew(FakeRunner(), paths).location(formula('btop')) == str(home / '.linuxbrew' / 'opt' / 'btop')
    assert B.brew_env(home)['PATH'].endswith(str(home / '.linuxbrew' / 'bin'))
    assert B.brew_env() is None                                       # the real $HOME: nothing there

    class R(FakeRunner):
        envs = []

        def run(self, cmd, env=None, **kw):
            self.envs.append(env)
            return Result(cmd, 0)
    r = R()
    Brew(r, paths).installed_index()
    assert r.envs[-1]['PATH'].endswith(str(home / '.linuxbrew' / 'bin'))
