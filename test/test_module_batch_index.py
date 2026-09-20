'''C2 — batch enumeration for the ecosystem module drivers (cargo already covered in
test_cargo_driver). Each driver's `installed_index()` reads ALL installed units from ONE
enumeration, and `get_version` answers from the batch context when inspection is batched (no
per-unit subprocess). Output fixtures use the real tool formats.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers.gem import Gem
from configsys.drivers.opam import Opam
from configsys.drivers.luarocks import LuaRocks
from configsys.drivers.go_install import GoInstall
from configsys.runner import Result


def rc(driver, name, **fields):
    fields.setdefault('name', name)
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name, fields=fields)


class FakeRunner:
    '''Matches by EXACT command so a bare enumeration ("gem list") never collides with a per-unit
    probe ("gem list -e X").'''
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        if cmd in self.responses:
            code, out = self.responses[cmd]
            return Result(full, code, stdout=out)
        return Result(full, 1, stdout='')


# -- gem ------------------------------------------------------------------

_GEM_LIST = ('rails (7.1.3, 7.0.8)\n'
             'bundler (default: 2.4.10)\n'          # default-only → omitted (reads as absent)
             'rake (13.0.6, default: 12.3.3)\n')    # real install FIRST → 13.0.6


def test_gem_installed_index_omits_default_only():
    idx = Gem(FakeRunner({'gem list': (0, _GEM_LIST)})).installed_index()
    assert idx == {'rails': '7.1.3', 'rake': '13.0.6'}    # bundler (default-only) not present


def test_gem_get_version_uses_batch_no_per_pkg_call():
    d = Gem(FakeRunner())
    d._batch = {'installed': {'rails': '7.1.3'}}
    assert d.get_version(rc('gem', 'rails')) == '7.1.3'
    assert d.get_version(rc('gem', 'bundler')) is None      # absent from batch = not installed
    assert d.runner.calls == []                             # answered entirely from the batch


def test_gem_index_none_when_gem_missing():
    assert Gem(FakeRunner()).installed_index() is None      # `gem list` fails → fall back, not empty


# -- opam -----------------------------------------------------------------

def test_opam_installed_index():
    out = 'dune 3.6.1\nlwt 5.6.1\n'
    idx = Opam(FakeRunner({'opam list --installed --short --columns=name,version --safe': (0, out)})
               ).installed_index()
    assert idx == {'dune': '3.6.1', 'lwt': '5.6.1'}


def test_opam_get_version_uses_batch():
    d = Opam(FakeRunner())
    d._batch = {'installed': {'dune': '3.6.1'}}
    assert d.get_version(rc('opam', 'dune')) == '3.6.1'
    assert d.get_version(rc('opam', 'menhir')) is None
    assert d.runner.calls == []


# -- luarocks -------------------------------------------------------------

def test_luarocks_installed_index_tab_separated():
    out = 'busted\t2.0.0\tinstalled\t/home/u/.luarocks\nluacheck\t1.1.0\tinstalled\t/home/u/.luarocks\n'
    idx = LuaRocks(FakeRunner({'luarocks list --porcelain': (0, out)})).installed_index()
    assert idx == {'busted': '2.0.0', 'luacheck': '1.1.0'}


def test_luarocks_get_version_uses_batch():
    d = LuaRocks(FakeRunner())
    d._batch = {'installed': {'busted': '2.0.0'}}
    assert d.get_version(rc('luarocks', 'busted')) == '2.0.0'
    assert d.get_version(rc('luarocks', 'penlight')) is None
    assert d.runner.calls == []


# -- go-install -----------------------------------------------------------

# `go version -m <dir>` over ~/go/bin — a header line per binary, then tab-indented mod info.
_GO_OUT = (
    '/home/u/go/bin/goimports: go1.22.0\n'
    '\tpath\tgolang.org/x/tools/cmd/goimports\n'
    '\tmod\tgolang.org/x/tools\tv0.18.0\th1:abc=\n'
    '\tdep\tgolang.org/x/mod\tv0.15.0\th1:def=\n'
    '/home/u/go/bin/dlv: go1.22.0\n'
    '\tpath\tgithub.com/go-delve/delve/cmd/dlv\n'
    '\tmod\tgithub.com/go-delve/delve\tv1.22.1\th1:ghi=\n')


def test_go_install_index_keyed_by_install_path():
    idx = GoInstall(FakeRunner({'go version -m ~/go/bin': (0, _GO_OUT)})).installed_index()
    assert idx == {'golang.org/x/tools/cmd/goimports': '0.18.0',   # v stripped, dep line ignored
                   'github.com/go-delve/delve/cmd/dlv': '1.22.1'}


def test_go_install_get_version_uses_batch_via_install_path():
    d = GoInstall(FakeRunner())
    d._batch = {'installed': {'golang.org/x/tools/cmd/goimports': '0.18.0'}}
    # route name may even carry an @version — index_key strips it to match the embedded path
    goimports = ResolvedComponent(key='go-install\\goimports', driver='go-install', comp='goimports',
                                  fields={'name': 'golang.org/x/tools/cmd/goimports@v0.18.0'})
    assert d.get_version(goimports) == '0.18.0'
    dlv = ResolvedComponent(key='go-install\\dlv', driver='go-install', comp='dlv',
                            fields={'name': 'github.com/go-delve/delve/cmd/dlv'})
    assert d.get_version(dlv) is None
    assert d.runner.calls == []


def test_go_install_index_none_when_gobin_absent():
    assert GoInstall(FakeRunner()).installed_index() is None
