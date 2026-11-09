'''review-2026-11-2 B14 — the driver correctness batch (lang side): gem scope + set-version + update,
luarocks per-tree scope, cabal's XDG bin, the `strip:` guard.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.runner import Result, Runner


class FR:
    pretend = False

    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(cmd, code, stdout=out)
        return Result(cmd, 0, stdout='')


def _rc(driver, name, **fields):
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name,
                             fields={'name': name, **fields})


def test_gem_reports_where_a_gem_actually_lives():
    from configsys.drivers.gem import Gem
    fr = FR([('gem list -e', 0, 'rubocop (1.60.0)\n'), ('ruby -e', 0, 'rubocop\tuser\n')])
    assert Gem(fr).get_installed(_rc('gem', 'rubocop', scope='system')) == ('1.60.0', 'user')
    fr = FR([('gem list -e', 0, 'rubocop (1.60.0)\n'), ('ruby -e', 1, '')])   # unknown: no false mismatch
    assert Gem(fr).get_installed(_rc('gem', 'rubocop', scope='system')) == ('1.60.0', 'system')


def test_gem_set_version_removes_the_other_versions_and_uninstall_takes_all():
    from configsys.drivers.gem import Gem
    r = Runner(pretend=True)
    g = Gem(r)
    g.set_version(_rc('gem', 'rubocop'), '1.50.0')
    assert r.calls[-1].startswith('gem install --user-install -v 1.50.0 rubocop && for o in')
    assert 'gem uninstall -x -v "$o" rubocop' in r.calls[-1]
    g.uninstall(_rc('gem', 'rubocop'))
    assert r.calls[-1] == 'gem uninstall -x -a rubocop'
    g.upgrade(_rc('gem', 'rubocop'))
    assert r.calls[-1] == 'gem update --user-install rubocop'
    assert not g.set_version(_rc('gem', "x'; rm -rf ~; '"), '1').ok      # never spliced into sed


def test_luarocks_scope_comes_from_the_rock_tree(tmp_path):
    from configsys.drivers.luarocks import LuaRocks
    from configsys.paths import Paths
    out = 'luafilesystem\t1.8.0-1\tinstalled\t/usr/local/lib/luarocks/rocks-5.4\n'
    d = LuaRocks(FR([('luarocks list --porcelain', 0, out)]), paths=Paths(env={'HOME': str(tmp_path)}))
    assert d.get_installed(_rc('luarocks', 'luafilesystem')) == ('1.8.0-1', 'system')
    home_out = f'luafilesystem\t1.8.0-1\tinstalled\t{tmp_path}/.luarocks/lib/luarocks/rocks-5.4\n'
    d = LuaRocks(FR([('luarocks list --porcelain', 0, home_out)]), paths=Paths(env={'HOME': str(tmp_path)}))
    assert d.get_installed(_rc('luarocks', 'luafilesystem', scope='system')) == ('1.8.0-1', 'user')
    d.batch = d.batch_index([_rc('luarocks', 'luafilesystem')])           # batched: no extra probe
    n = len(d.runner.calls)
    assert d.get_installed(_rc('luarocks', 'luafilesystem')) == ('1.8.0-1', 'user')
    assert len(d.runner.calls) == n


def test_cabal_finds_and_removes_only_store_links_in_xdg_bin():
    from configsys.drivers.cabal import Cabal
    fr = FR([('readlink -e', 0, '/home/u/.local/state/cabal/store/ghc-9.6/hlint-3.8-abc/bin/hlint\n')])
    assert Cabal(fr).get_version(_rc('cabal', 'hlint')) == '3.8'
    assert '~/.local/bin/hlint' in fr.calls[-1] and '*/cabal/store/*' in fr.calls[-1]
    r = Runner(pretend=True)
    Cabal(r).uninstall(_rc('cabal', 'hlint'))
    assert 'rm -f ~/.cabal/bin/hlint' in r.calls[-1]
    assert 'if [ -L "$f" ]; then case "$(readlink "$f")" in */cabal/store/*' in r.calls[-1]


@pytest.mark.parametrize('v, n', [(1, 1), ('2', 2), (0, 0), ('one', None), (-1, None), (True, None)])
def test_strip_count(v, n):
    from configsys.driver import strip_count
    assert strip_count(v) == n


def test_a_bad_strip_is_a_load_error_not_a_traceback():
    import os
    from configsys import routecheck, routes
    from configsys.errors import ConfigError
    cascade = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))[0]
    bad = routes.Component('bad', {'install': [{'via': 'tarball', 'url': 'https://x/a.tgz', 'strip': 'one'}]})
    with pytest.raises(ConfigError, match='strip'):
        routecheck.check_component('bad', bad, cascade)


def test_every_downloading_driver_requires_curl():
    # B14 / drivers-lang-10 / routing-13: a driver whose ops run curl declares it, so the plan pulls
    # curl in (and the derived gate declines the driver where curl has no route). `source` downloads
    # only for an archive binding (its default acquisition is git) — that binding requires curl itself.
    import os
    import re
    from configsys import routes
    here = os.path.dirname(__file__)
    _c, _comps, drivers, _co = routes.load(os.path.join(here, '..', 'routes.hu'))
    drv_dir = os.path.join(here, '..', 'configsys', 'drivers')
    module_driver = {'appImage.py': 'appImage', 'font.py': 'font', 'tarball.py': 'tarball',
                     'native_pkg_file.py': 'native-pkg-file'}
    for fname in sorted(os.listdir(drv_dir)):
        if not fname.endswith('.py') or fname == 'source.py':
            continue
        text = open(os.path.join(drv_dir, fname), encoding='utf-8').read()
        if re.search(r'_CURL_DOWNLOAD|_fetch_and_extract', text):
            name = module_driver.get(fname)
            assert name, f'{fname} downloads with curl — map it to its driver here'
            assert 'curl' in (drivers.get(name) or []), f'drivers: {name} must `requires: curl`'
