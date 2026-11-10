import shlex
from types import SimpleNamespace

import pytest

from configsys import app
from configsys.cli import refresh
from configsys.drivers.apt import drop_keyring_cmd
from configsys.runner import Result

JLIST = '/etc/apt/sources.list.d/jenkins.list'
CODELIST = '/etc/apt/sources.list.d/code.list'


def _ctx(owned, runner=None):
    '''owned: {component: source-path}. Builds routes.components so _owned_index_sources maps
    each source-path back to its component.'''
    comps = {}
    for comp, path in owned.items():
        comps[comp] = SimpleNamespace(bindings=[SimpleNamespace(details={'source-path': path})])
    return SimpleNamespace(routes=SimpleNamespace(components=comps), runner=runner)


def test_orphan_detection_component_not_wanted():
    ctx = _ctx({'jenkins': JLIST, 'vscode': CODELIST})
    disk = [JLIST, CODELIST]
    # vscode is wanted, jenkins is not -> only jenkins's source is an orphan
    orphans = app._orphaned_managed_sources(ctx, wanted={'vscode'}, disk_files=disk)
    assert orphans == [(JLIST, 'jenkins')]


def test_foreign_file_never_an_orphan():
    ctx = _ctx({'jenkins': JLIST})
    disk = [JLIST, '/etc/apt/sources.list.d/some-random.list']   # the random one isn't in any route
    orphans = app._orphaned_managed_sources(ctx, wanted=set(), disk_files=disk)
    assert orphans == [(JLIST, 'jenkins')]                        # foreign file excluded


def test_all_wanted_no_orphans():
    ctx = _ctx({'jenkins': JLIST})
    assert app._orphaned_managed_sources(ctx, wanted={'jenkins'}, disk_files=[JLIST]) == []


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True):
        self.calls.append(cmd)
        return Result(cmd, 0)


def test_reconcile_prompts_and_removes(monkeypatch):
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted=set(),
                                       ask=lambda p: True, lister=lambda: [JLIST])
    assert n == 1
    assert any(c == f'sudo rm -f {JLIST}' for c in r.calls)


def test_reconcile_declined_removes_nothing():
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted=set(),
                                       ask=lambda p: False, lister=lambda: [JLIST])
    assert n == 0 and not r.calls


def test_reconcile_noop_when_component_wanted():
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted={'jenkins'},
                                       ask=lambda p: True, lister=lambda: [JLIST])
    assert n == 0 and not r.calls


def test_reconcile_under_pretend_asks_nothing(capsys):
    # A14 / app-cli-03: a dry run can't remove anything, so it never prompts
    import types
    from configsys import app
    ctx = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=True),
                                paths=types.SimpleNamespace(home=__import__('pathlib').Path.home()))
    orig = refresh._orphaned_managed_sources
    refresh._orphaned_managed_sources = lambda c, w, files: [('/etc/apt/sources.list.d/x.list', 'x')]
    try:
        n = app._reconcile_managed_sources(ctx, 'apt', set(), ask=lambda p: (_ for _ in ()).throw(AssertionError(p)),
                                           lister=lambda: ['/etc/apt/sources.list.d/x.list'])
    finally:
        refresh._orphaned_managed_sources = orig
    assert n == 0 and 'would offer to remove' in capsys.readouterr().out


CLANG_LIST = '/etc/apt/sources.list.d/clang-19.list'
CLANG_KEY = '/etc/apt/keyrings/clang-19.asc'


def _clang_ctx(runner=None):
    '''A route with a `via: clang` binding: no source-path field — the driver's own apt.llvm.org
    source (decisions 2026-11-09 W2.2: managed by refresh exactly like apt's vendor sources).'''
    comps = {'clang-19': SimpleNamespace(bindings=[
        SimpleNamespace(via='clang', details={'packages': ['clang-19']}),
        SimpleNamespace(via='clang', details={'packages': ['clang19']})])}   # (a dnf binding: same)
    return SimpleNamespace(routes=SimpleNamespace(components=comps), runner=runner)


def test_a_gcc_clang_vendor_list_is_a_managed_source():
    assert refresh._owned_index_sources(_clang_ctx()) == {CLANG_LIST: 'clang-19'}
    assert app._orphaned_managed_sources(_clang_ctx(), wanted=set(), disk_files=[CLANG_LIST]) == \
        [(CLANG_LIST, 'clang-19')]
    assert app._orphaned_managed_sources(_clang_ctx(), wanted={'clang-19'}, disk_files=[CLANG_LIST]) == []
    # a rotated apt.llvm.org key is re-fetchable into its own keyring, like a route's pubkey-*
    assert refresh._source_key_fields(_clang_ctx(), 'clang-19', CLANG_LIST) == (
        'https://apt.llvm.org/llvm-snapshot.gpg.key', CLANG_KEY)


def test_removing_a_stale_clang_source_takes_its_keyring_too():
    r = _Runner()
    n = app._reconcile_managed_sources(_clang_ctx(r), 'apt', wanted=set(),
                                       ask=lambda p: True, lister=lambda: [CLANG_LIST])
    assert n == 1
    assert r.calls[0] == f'sudo rm -f {CLANG_LIST}'
    rest = '\n'.join(r.calls[1:])
    assert drop_keyring_cmd(CLANG_KEY) in rest
    assert 'trusted.gpg.d/clang.asc' in rest and rest.startswith('sudo ')


JKEY = '/usr/share/keyrings/jenkins-keyring.asc'


def _keyed_ctx(key, runner=None):
    comps = {'jenkins': SimpleNamespace(bindings=[SimpleNamespace(
        via='native', details={'source-path': JLIST, 'pubkey-url': 'https://pkg.jenkins.io/k', 'pubkey-path': key})])}
    return SimpleNamespace(routes=SimpleNamespace(components=comps), runner=runner)


def test_removing_a_stale_apt_source_takes_the_key_it_named_too():
    # decisions 2026-11-09 W2.2 follow-up: one rule for apt's pubkey-path and gcc/clang's keyring
    r = _Runner()
    assert app._reconcile_managed_sources(_keyed_ctx(JKEY, r), 'apt', wanted=set(),
                                          ask=lambda p: True, lister=lambda: [JLIST]) == 1
    assert r.calls[0] == f'sudo rm -f {JLIST}'
    assert r.calls[1] == f'sudo sh -c {shlex.quote(drop_keyring_cmd(JKEY))}'


@pytest.mark.parametrize('key', ['/etc/apt/trusted.gpg.d/jenkins.asc',   # global: vouches for every source
                                 '/opt/jenkins.asc', None])
def test_a_key_outside_the_signed_by_keyring_dirs_is_never_touched(key):
    r = _Runner()
    app._reconcile_managed_sources(_keyed_ctx(key, r), 'apt', wanted=set(),
                                   ask=lambda p: True, lister=lambda: [JLIST])
    assert r.calls == [f'sudo rm -f {JLIST}']
    assert drop_keyring_cmd(key) is None


def test_drop_keyring_keeps_a_key_another_source_names_or_a_package_owns(tmp_path):
    import subprocess
    keys, lists, stub = tmp_path / 'keyrings', tmp_path / 'sources.list.d', tmp_path / 'bin'
    for d in (keys, lists, stub):
        d.mkdir()
    (stub / 'dpkg').write_text(f'#!/bin/sh\n[ "$2" = "{keys}/owned.asc" ]\n')   # dpkg -S: owned?
    (stub / 'dpkg').chmod(0o755)
    for k in ('named', 'owned', 'free'):
        (keys / f'{k}.asc').write_text('KEY')
    (lists / 'other.list').write_text(f'deb [signed-by={keys}/named.asc] https://x/ y main\n')
    for k in ('named', 'owned', 'free'):
        cmd = drop_keyring_cmd(str(keys / f'{k}.asc'), sources=(f'{lists}/',), dirs=(f'{keys}/',))
        subprocess.run(['sh', '-c', cmd], check=True, env={'PATH': f'{stub}:/usr/bin:/bin'})
    assert (keys / 'named.asc').exists() and (keys / 'owned.asc').exists()
    assert not (keys / 'free.asc').exists()


def test_an_installed_or_receipted_owner_is_never_stale(tmp_path, monkeypatch):
    import types
    from configsys import app
    from configsys.componentObj import ResolvedComponent
    from configsys.ledger import Ledger
    from configsys.paths import Paths
    paths = Paths(env={'HOME': str(tmp_path)})
    led = Ledger()
    led.set_receipt(ResolvedComponent(key='apt\\gum', driver='apt', comp='gum', fields={'name': 'gum'}))
    led.save(paths)
    monkeypatch.setattr(refresh, '_owned_index_sources', lambda c: {'/etc/apt/x.list': 'gum', '/etc/apt/y.list': 'slack'})
    slack = ResolvedComponent(key='apt\\slack', driver='apt', comp='slack', fields={'name': 'slack-desktop'})
    ctx = types.SimpleNamespace(paths=paths, runner=None,
                                routes=types.SimpleNamespace(resolve_resilient=lambda n, **k: ({'apt\\slack': slack}, {})))
    monkeypatch.setattr(refresh, 'get_driver', lambda *a, **k: types.SimpleNamespace(get_version=lambda rc: '4.0'))
    assert app._installed_owners(ctx) == {'gum', 'slack'}
