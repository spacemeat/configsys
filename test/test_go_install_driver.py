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


_P = 'PATH="${CONFIGSYS_SDK_DIR:-$HOME/sdks}/go/bin:$PATH" '


def test_install_uses_latest_and_no_sudo():
    r = Runner(pretend=True)
    GoInstall(r).install(tool())
    GoInstall(r).upgrade(tool())
    # a configsys-managed go (the `go` tarball) is put ahead of the system go on PATH, so a modern
    # module's go.mod isn't rejected by an old /usr/bin/go
    assert r.calls == [
        _P + 'go install golang.org/x/tools/cmd/goimports@latest',
        _P + 'go install golang.org/x/tools/cmd/goimports@latest',
    ]
    assert all('sudo' not in c for c in r.calls)


def test_uninstall_removes_binary_by_last_segment():
    r = Runner(pretend=True)
    GoInstall(r).uninstall(tool())
    assert r.calls == ['rm -f ~/go/bin/goimports']


def test_set_version_pins():
    r = Runner(pretend=True)
    GoInstall(r).set_version(tool(), 'v0.28.0')
    assert r.calls == [_P + 'go install golang.org/x/tools/cmd/goimports@v0.28.0']


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


def test_version_reads_use_the_managed_go(tmp_path, monkeypatch):
    # with go ONLY from the tarball (~/sdks/go/bin — what a go>=X floor advises), a bare
    # `go version -m` isn't found: every go-installed tool read "not installed" though it was there
    sdk = tmp_path / 'sdks/go/bin'
    sdk.mkdir(parents=True)
    fake_go = sdk / 'go'
    fake_go.write_text('#!/bin/sh\n'
                       'printf "%s: go1.26.1\\n\\tpath\\tgolang.org/x/tools/cmd/goimports\\n'
                       '\\tmod\\tgolang.org/x/tools\\tv0.50.0\\th1:x\\n" "$3"\n')
    fake_go.chmod(0o755)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('CONFIGSYS_SDK_DIR', raising=False)
    monkeypatch.setenv('PATH', '/usr/bin:/bin')            # no system go anywhere on it
    assert GoInstall(Runner()).get_version(tool()) == '0.50.0'


def test_latest_comes_from_the_module_proxy(monkeypatch):
    # go-install had no 'latest' at all (no version: spec on its routes) — now the proxy's @latest,
    # the same thing `go install …@latest` resolves
    from configsys import versions
    monkeypatch.setattr(versions, 'discover', lambda spec, paths, **kw: '0.50.0' if spec == {'goproxy': 'golang.org/x/tools/cmd/goimports'} else None)
    assert GoInstall(Runner(pretend=True)).get_latest(tool()) == '0.50.0'


def test_pseudo_versions_compare_by_commit_time():
    # discordo is untagged: 0.0.0-<timestamp>-<commit>. The numeric base is always 0.0.0, so without
    # this every snapshot read current forever.
    from configsys.installState import ComponentState
    from configsys.componentObj import ResolvedComponent
    rc = ResolvedComponent(key='go-install\\discordo', driver='go-install', comp='discordo', fields={})

    def st(inst, latest):
        return ComponentState(component=rc, supported=True, present=True,
                              installed_version=inst, latest_version=latest, locked=False,
                              lock_source=None, managed=True, error=None)
    assert st('0.0.0-20260819035418-d1f67621141c', '0.0.0-20260926000522-08b41176c060').outdated
    assert not st('0.0.0-20260926000522-08b41176c060', '0.0.0-20260926000522-08b41176c060').outdated
