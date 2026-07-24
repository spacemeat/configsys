from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.go_install import GoInstall
from configsys.runner import Result, Runner


def tool(name='goimports', path='golang.org/x/tools/cmd/goimports'):
    return ResolvedComponent(key=f'go-install\\{name}', driver='go-install', comp=name,
                             fields={'name': path})


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
    d = get_driver('go-install', Runner(pretend=True))
    assert isinstance(d, GoInstall) and is_supported('go-install')
    assert d.privileged is False


def test_install_uses_latest_and_no_sudo():
    r = Runner(pretend=True)
    GoInstall(r).install(tool())
    GoInstall(r).upgrade(tool())
    assert r.calls == [
        'go install golang.org/x/tools/cmd/goimports@latest',
        'go install golang.org/x/tools/cmd/goimports@latest',
    ]
    assert all('sudo' not in c for c in r.calls)


def test_uninstall_removes_binary_by_last_segment():
    r = Runner(pretend=True)
    GoInstall(r).uninstall(tool())
    assert r.calls == ['rm -f ~/go/bin/goimports']


def test_set_version_pins():
    r = Runner(pretend=True)
    GoInstall(r).set_version(tool(), 'v0.28.0')
    assert r.calls == ['go install golang.org/x/tools/cmd/goimports@v0.28.0']


def test_get_version_reads_embedded_module_version():
    out = ('/home/x/go/bin/goimports: go1.22.3\n'
           '\tpath\tgolang.org/x/tools/cmd/goimports\n'
           '\tmod\tgolang.org/x/tools\tv0.28.0\th1:abc=\n')
    fr = FakeRunner([('go version -m', 0, out)])
    assert GoInstall(fr).get_version(tool()) == '0.28.0'


def test_get_version_missing_binary_is_none():
    fr = FakeRunner([('go version -m', 1, '')])
    assert GoInstall(fr).get_version(tool()) is None


def test_get_latest_none_without_spec_and_no_lock():
    d = GoInstall(Runner(pretend=True))
    assert d.get_latest(tool()) is None
    assert d.is_locked(tool()) is False


def test_location_is_gobin():
    assert GoInstall(Runner(pretend=True)).location(tool()) == '~/go/bin'
