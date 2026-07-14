from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.cargo import Cargo
from configsys.runner import Result, Runner


def crate(name='tree-sitter-cli'):
    return ResolvedComponent(key=f'cargo\\{name}', family='cargo', comp=name,
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
    fam = get_family('cargo', Runner(pretend=True))
    assert isinstance(fam, Cargo) and is_supported('cargo')
    assert fam.privileged is False


def test_install_uninstall_upgrade_commands():
    r = Runner(pretend=True)
    Cargo(r).install(crate())
    Cargo(r).uninstall(crate())
    Cargo(r).upgrade(crate())
    assert r.calls == [
        'cargo install tree-sitter-cli',
        'cargo uninstall tree-sitter-cli',
        'cargo install --force tree-sitter-cli',
    ]
    assert all('sudo' not in c for c in r.calls)   # user-space


def test_set_version_pins():
    r = Runner(pretend=True)
    Cargo(r).set_version(crate(), '0.20.8')
    assert r.calls == ['cargo install --force --version 0.20.8 tree-sitter-cli']


def test_get_version_parses_list():
    listing = ('ripgrep v14.1.0:\n    rg\n'
               'tree-sitter-cli v0.20.8:\n    tree-sitter\n')
    fr = FakeRunner([('cargo install --list', 0, listing)])
    assert Cargo(fr).get_version(crate('tree-sitter-cli')) == '0.20.8'
    assert Cargo(fr).get_version(crate('ripgrep')) == '14.1.0'


def test_get_version_not_installed():
    fr = FakeRunner([('cargo install --list', 0, 'ripgrep v14.1.0:\n    rg\n')])
    assert Cargo(fr).get_version(crate('tree-sitter-cli')) is None


def test_list_command_fails_gracefully():
    fr = FakeRunner([('cargo install --list', 1, '')])   # cargo not installed
    assert Cargo(fr).get_version(crate()) is None


def test_get_latest_deferred_and_no_native_lock():
    fam = Cargo(Runner(pretend=True))
    assert fam.get_latest(crate()) is None
    assert fam.is_locked(crate()) is False


def test_location_is_cargo_bin():
    assert Cargo(Runner(pretend=True)).location(crate()) == '~/.cargo/bin'
