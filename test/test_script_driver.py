import pytest
from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.script import Script
from configsys.runner import Result, Runner

LOCAL_BIN = 'PATH="$HOME/.local/bin:$PATH"; '   # every script command runs with ~/.local/bin on PATH


def sc(name='sdkman', **fields):
    fields.setdefault('name', name)
    return ResolvedComponent(key=f'script\\{name}', driver='script', comp=name, fields=fields)


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        self.calls.append(cmd)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(cmd, code, stdout=out)
        return Result(cmd, 0, stdout='')


def test_registered_unprivileged():
    d = get_driver('script', Runner(pretend=True))
    assert isinstance(d, Script) and is_supported('script') and d.privileged is False


def test_install_runs_declared_command():
    r = Runner(pretend=True)
    Script(r).install(sc(**{'install-cmd': 'curl -s x | bash'}))
    assert r.calls == [LOCAL_BIN + 'curl -s x | bash']


def test_install_missing_command_fails():
    assert Script(Runner(pretend=True)).install(sc()).returncode == 1


def test_get_version_with_regex():
    fr = FakeRunner([('sdk version', 0, 'SDKMAN!\nscript: 5.18.2\nnative: 0.4.6\n')])
    rc = sc(**{'version-cmd': 'sdk version', 'version-re': r'([0-9]+\.[0-9]+\.[0-9]+)'})
    assert Script(fr).get_version(rc) == '5.18.2'


def test_get_version_first_line_without_regex():
    fr = FakeRunner([('vc', 0, '1.2.3\n')])
    assert Script(fr).get_version(sc(**{'version-cmd': 'vc'})) == '1.2.3'


def test_get_version_none_when_no_cmd_or_fails():
    assert Script(FakeRunner()).get_version(sc()) is None                        # no version-cmd
    fr = FakeRunner([('vc', 1, '')])
    assert Script(fr).get_version(sc(**{'version-cmd': 'vc'})) is None            # tool absent


def test_get_latest_from_latest_cmd():
    # a package-install script reports its candidate via latest-cmd (same version-re)
    fr = FakeRunner([('apt-cache policy', 0, '  Candidate: 8.9.7.29-1+cuda12.2\n')])
    rc = sc(**{'latest-cmd': 'apt-cache policy libcudnn8-dev | grep Candidate',
               'version-re': r'([0-9][0-9.+-]*)'})
    assert Script(fr).get_latest(rc) == '8.9.7.29-1+'
    # no latest-cmd and no version: spec -> None (unchanged)
    assert Script(FakeRunner()).get_latest(sc(**{'version-cmd': 'vc'})) is None


def test_uninstall_runs_command_when_present():
    r = Runner(pretend=True)
    Script(r).uninstall(sc(**{'uninstall-cmd': 'rm -rf ~/.sdkman'}))
    assert r.calls == [LOCAL_BIN + 'rm -rf ~/.sdkman']


def test_uninstall_without_command_warns_but_succeeds():
    # warn, don't gatekeep: no uninstall-cmd -> a warning result, not a failure
    res = Script(Runner(pretend=True)).uninstall(sc('rustup'))
    assert res.ok and 'no uninstall-cmd' in res.cmd and 'rustup' in res.cmd


def test_set_version_unsupported_without_cmd():
    assert Script(Runner(pretend=True)).set_version(sc(), '1.0').returncode == 1


def test_location_from_field():
    assert Script(Runner(pretend=True)).location(sc(location='~/.sdkman')) == '~/.sdkman'



@pytest.mark.real_runner
def test_version_probe_finds_a_tool_in_local_bin(tmp_path, monkeypatch):
    # claude-code: the official installer puts `claude` in ~/.local/bin, which a fresh login only has
    # on PATH if the dir existed at login — the bare `claude --version` probe failed and a
    # just-installed tool read "not installed"
    (tmp_path / '.local/bin').mkdir(parents=True)
    tool = tmp_path / '.local/bin/claude'
    tool.write_text('#!/bin/sh\necho "2.1.9 (Claude Code)"\n')
    tool.chmod(0o755)
    monkeypatch.setenv('HOME', str(tmp_path))
    v = Script(Runner()).get_version(sc(**{'version-cmd': 'claude --version 2>/dev/null',
                                           'version-re': '([0-9][0-9.]*)'}))
    assert v == '2.1.9'


def test_version_re_without_a_group_is_the_whole_match():
    # drivers-lang-24: m.group(1) raised IndexError for a group-less pattern
    fr = FakeRunner([('tool --version', 0, 'tool 1.2.3 (build 9)\n')])
    d = Script(fr)
    assert d.get_version(sc('tool', **{'version-cmd': 'tool --version', 'version-re': r'[0-9]+\.[0-9.]+'})) == '1.2.3'


def test_an_invalid_version_re_reads_unknown_and_fails_the_route_check():
    fr = FakeRunner([('tool --version', 0, 'tool 1.2.3\n')])
    assert Script(fr).get_version(sc('tool', **{'version-cmd': 'tool --version', 'version-re': '([0-9.]+'})) is None
    import os
    from configsys import routes
    from configsys.errors import ConfigError
    from configsys.routecheck import check_component
    cascade = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))[0]
    comp = routes.Component('tool', {'install': [{'via': 'script', 'install-cmd': 'x',
                                                  'version-re': '([0-9.]+'}]})
    with pytest.raises(ConfigError, match=r"'tool'.*version-re"):
        check_component('tool', comp, cascade)


def test_missing_commands_fail_with_a_reason_in_stderr():
    # drivers-lang-20: the reason rode in Result.cmd, so the TUI summary showed only "exit 1"
    from configsys import actions
    d = Script(FakeRunner())
    res = d.install(sc('tool'))
    assert not res.ok and 'install-cmd' in actions.fail_detail(res)
    res = d.upgrade(sc('tool'))
    assert not res.ok and 'install-cmd' in actions.fail_detail(res)
    res = d.set_version(sc('tool'), '1.0')
    assert not res.ok and 'set-version-cmd' in actions.fail_detail(res)
