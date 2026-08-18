'''Unit tests for the opam / luarocks / cabal module drivers. Output-parsing fixtures use the
REAL formats captured from opam 2.1.5, luarocks 3.8.0, cabal-install 3.8.1 in a container.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.opam import Opam
from configsys.drivers.luarocks import LuaRocks
from configsys.drivers.cabal import Cabal
from configsys.runner import Result, Runner


def rc(driver, name, **fields):
    fields.setdefault('name', name)
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name, fields=fields)


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


# -- opam (fixed-user) ----------------------------------------------------

def test_opam_registered_unprivileged():
    d = get_driver('opam', Runner(pretend=True))
    assert isinstance(d, Opam) and is_supported('opam') and d.privileged is False


def test_opam_lifecycle_commands():
    r = Runner(pretend=True)
    Opam(r).install(rc('opam', 'dune'))
    Opam(r).uninstall(rc('opam', 'dune'))
    Opam(r).upgrade(rc('opam', 'dune'))
    Opam(r).set_version(rc('opam', 'dune'), '3.15.0')
    assert r.calls == ['opam init --no-setup --yes && opam install -y dune',
                       'opam remove -y dune', 'opam upgrade -y dune',
                       'opam install -y dune.3.15.0']
    assert all('sudo' not in c for c in r.calls)


def test_opam_get_version_uses_safe_flag():
    # --safe keeps get_version from erroring on an uninitialized opam
    r = Runner(pretend=True)
    Opam(r).get_version(rc('opam', 'dune'))
    assert '--safe' in r.calls[0]


def test_opam_get_version_reads_columns_output():
    fr = FakeRunner([('opam list --installed --short --columns=version', 0, '3.15.0\n')])
    assert Opam(fr).get_version(rc('opam', 'dune')) == '3.15.0'
    fr2 = FakeRunner([('opam list', 0, '')])                 # not installed
    assert Opam(fr2).get_version(rc('opam', 'dune')) is None


def test_opam_location():
    assert Opam(Runner(pretend=True)).location(rc('opam', 'dune')) == '~/.opam'


# -- luarocks (scope-honoring) --------------------------------------------

def test_luarocks_scope_honoring():
    d = get_driver('luarocks', Runner(pretend=True))
    assert isinstance(d, LuaRocks) and d.honors_scope is True


def test_luarocks_user_vs_system():
    r = Runner(pretend=True)
    LuaRocks(r).install(rc('luarocks', 'luacheck'))
    LuaRocks(r).install(rc('luarocks', 'luacheck', scope='system'))
    assert r.calls == ['luarocks install --local luacheck', 'sudo luarocks install luacheck']


def test_luarocks_get_version_parses_porcelain():
    # porcelain: name\tversion\tstatus\tpath
    out = 'luacheck\t1.1.0-1\tinstalled\t/home/t/.luarocks/lib/luarocks/rocks-5.1\n'
    fr = FakeRunner([('luarocks list --porcelain', 0, out)])
    assert LuaRocks(fr).get_version(rc('luarocks', 'luacheck')) == '1.1.0-1'


def test_luarocks_location_follows_scope():
    d = LuaRocks(Runner(pretend=True))
    assert d.location(rc('luarocks', 'x')) == '~/.luarocks'
    assert d.location(rc('luarocks', 'x', scope='system')) is None


# -- cabal (fixed-user) ---------------------------------------------------

# the cabal driver prepends a ghcup toolchain (if installed) to PATH for its cabal invocations
_GHCUP = 'PATH="$HOME/.ghcup/bin:$PATH" '


def test_cabal_install_uses_overwrite_policy():
    r = Runner(pretend=True)   # pretend index-probe returns empty -> update runs before each install
    Cabal(r).install(rc('cabal', 'hlint'))
    Cabal(r).set_version(rc('cabal', 'hlint'), '3.5')
    installs = [c for c in r.calls if 'cabal install' in c]
    assert installs == [_GHCUP + 'cabal install hlint --overwrite-policy=always',
                        _GHCUP + 'cabal install hlint-3.5 --overwrite-policy=always']


def test_cabal_updates_index_when_missing():
    # a fresh cabal (no package index) gets `cabal update` before install, else the solver has
    # nothing to resolve against ("goals I've had most trouble fulfilling").
    r = FakeRunner(responses=[('ls ~/.cabal', 0, '')])        # index probe finds nothing
    Cabal(r).install(rc('cabal', 'hlint'))
    assert any('cabal update' in c for c in r.calls)
    assert r.calls[-1] == _GHCUP + 'cabal install hlint --overwrite-policy=always'


def test_cabal_skips_update_when_index_present():
    r = FakeRunner(responses=[('ls ~/.cabal', 0, '/home/x/.cabal/packages/hackage/01-index.tar')])
    Cabal(r).install(rc('cabal', 'hlint'))
    assert not any('cabal update' in c for c in r.calls)      # index already there -> no re-fetch


def test_cabal_uninstall_removes_binary():
    r = Runner(pretend=True)
    Cabal(r).uninstall(rc('cabal', 'hlint'))
    assert r.calls == ['rm -f ~/.cabal/bin/hlint']
    # an explicit exe: field overrides the derived binary name
    r2 = Runner(pretend=True)
    Cabal(r2).uninstall(rc('cabal', 'ormolu-pkg', exe='ormolu'))
    assert r2.calls == ['rm -f ~/.cabal/bin/ormolu']


def test_cabal_get_version_parses_simple_output():
    fr = FakeRunner([('cabal list --installed --simple-output', 0, 'hlint 3.5\n')])
    assert Cabal(fr).get_version(rc('cabal', 'hlint')) == '3.5'
    fr2 = FakeRunner([('cabal list', 0, 'other 1.0\n')])
    assert Cabal(fr2).get_version(rc('cabal', 'hlint')) is None
