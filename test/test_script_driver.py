from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.script import Script
from configsys.runner import Result, Runner


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
    assert r.calls == ['curl -s x | bash']


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
    assert r.calls == ['rm -rf ~/.sdkman']


def test_uninstall_without_command_warns_but_succeeds():
    # warn, don't gatekeep: no uninstall-cmd -> a warning result, not a failure
    res = Script(Runner(pretend=True)).uninstall(sc('rustup'))
    assert res.ok and 'no uninstall-cmd' in res.cmd and 'rustup' in res.cmd


def test_set_version_unsupported_without_cmd():
    assert Script(Runner(pretend=True)).set_version(sc(), '1.0').returncode == 1


def test_location_from_field():
    assert Script(Runner(pretend=True)).location(sc(location='~/.sdkman')) == '~/.sdkman'
