'''The Plugins screen's three review aids: the derived `provides` codes, the pre-sync review diff
(fetched into an inert cache, never the plugins dir), and the machine-local plugin lock (no sync,
update, bless or trust).'''

import shutil
import subprocess
import types

import pytest

from configsys import actions, plugins
from configsys.runner import Runner
from configsys.tui import menu

pytestmark = pytest.mark.real_runner  # real git clones/commits in tmp dirs (conftest)

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


def _git(cwd, *a):
    subprocess.run(['git', *a], cwd=cwd, check=True)


def _repo(tmp_path, name='src'):
    '''A plugin repo with tags v1 (routes.hu = one) and v2 (routes.hu = two).'''
    src = tmp_path / name
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: sp  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('one\n')
    _git(src, 'init', '-q'); _git(src, 'config', 'user.email', 't@t'); _git(src, 'config', 'user.name', 't')
    _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'A'); _git(src, 'tag', 'v1')
    (src / 'routes.hu').write_text('two\n')
    _git(src, 'commit', '-qam', 'B'); _git(src, 'tag', 'v2')
    return src


# -- provides: derived from what the plugin ships ----------------------------

def test_provisions_come_from_data_sections_manifest_and_content(tmp_path):
    d = tmp_path / 'p'
    (d / 'glue' / 'shell' / 'bash').mkdir(parents=True)
    (d / 'glue' / 'shell' / 'bash' / 'x.sh').write_text('alias x=y\n')
    (d / 'dotfiles').mkdir()                                  # empty: no dotfiles content
    (d / 'plugin.hu').write_text('{ name: p  requires-abi: 1  provides: { drivers: [ foo ]  widgets: [ w ] }'
                                 '  data: [ a.hu ]  plugins: [ { source: "github:x/y" } ] }')
    (d / 'a.hu').write_text('{ components: { t: { install: [ { via: native } ] } }  profiles: { }'
                            '  pins: { t: native }  include: [ b.hu ] }')
    (d / 'b.hu').write_text('{ version-floors: { t: { go: ">=1.22" } } }')
    got = plugins.provisions(d)
    # profiles: {} is empty -> not listed; pins is a machine setting; b.hu via include
    assert got == ['components', 'drivers', 'version-floors', 'settings', 'glue', 'plugins', 'widgets']
    cell = menu._plugin_provides_cell({'provisions': got, 'provides': {}})
    assert cell == 'cm dr vf ms gl pl widgets'


def test_provides_cell_falls_back_to_the_manifest_when_unsynced():
    assert menu._plugin_provides_cell({'provisions': [], 'provides': {'splash': ['nova']}}) == 'sp'
    assert menu._plugin_provides_cell({'provisions': [], 'provides': {}}) == '—'


def test_every_code_is_on_the_help_page():
    gloss = dict(menu._HELP['plugins']['glossary'])
    for _k, code, label in plugins.PROVISIONS:
        assert gloss[f'  {code}'] == label
    assert len({c for _k, c, _l in plugins.PROVISIONS}) == len(plugins.PROVISIONS)   # codes unique


# -- the review diff -----------------------------------------------------------

def test_review_plan_cases():
    plan = actions.plugin_review_plan
    assert plan({'synced': True, 'ref': 'v1'}, 'v2')[:3] == ('synced', 'HEAD', 'v2')
    assert plan({'synced': True, 'ref': 'v1'}, None)[0] is None
    assert plan({'synced': False, 'ref': 'v1'}, 'v2')[:3] == ('review', 'v1', 'v2')
    assert plan({'synced': False, 'ref': 'v2'}, 'v2')[:3] == ('review', None, 'v2')    # whole content
    assert plan({'synced': False, 'ref': None}, 'main')[:3] == ('review', None, 'main')
    assert plan({'synced': False, 'ref': 'v1'}, None)[:3] == ('review', None, 'v1')
    assert plan({'synced': False, 'ref': None}, None)[0] is None


@needs_git
def test_review_diff_reads_an_unsynced_plugin_without_syncing_it(tmp_path):
    src = _repo(tmp_path)
    pdir, cache = tmp_path / 'plugins', tmp_path / 'review'
    decl = {'source': str(src), 'ref': 'v1'}
    files, err = plugins.review_diff(Runner(pretend=False), cache, decl, 'v1', 'v2')
    assert err is None and [f['path'] for f in files] == ['routes.hu']
    assert ('del', '-one') in files[0]['lines'] and ('add', '+two') in files[0]['lines']
    # base None = everything a sync would download
    files, err = plugins.review_diff(Runner(pretend=False), cache, decl, None, 'v1')
    assert err is None and sorted(f['path'] for f in files) == ['plugin.hu', 'routes.hu']
    assert not pdir.exists()                                  # nothing synced
    repo = cache / 'src.git'
    assert (repo / 'HEAD').exists() and not (repo / 'hooks').exists()   # bare, no hook templates
    files, err = plugins.review_diff(Runner(pretend=False), cache, decl, 'v1', 'v9')
    assert files == [] and 'could not fetch v9' in err


def test_review_diff_refuses_a_non_git_transport(tmp_path, monkeypatch):
    monkeypatch.setitem(plugins._TRANSPORTS, 'oci', lambda *a: 'cloned')
    files, err = plugins.review_diff(Runner(pretend=False), tmp_path, {'source': 'oci:x/y'}, None, 'v1')
    assert files == [] and 'not a git source' in err


# -- the lock ----------------------------------------------------------------

def test_lock_store_round_trip(tmp_path):
    lf = tmp_path / 'plugin-locks.hu'
    assert plugins.read_locks(lf) == {} and plugins.read_locks(None) == {}
    plugins.set_lock(lf, 'a', '2026-10-21')
    assert plugins.read_locks(lf) == {'a': '2026-10-21'}
    assert plugins.remove_lock(lf, 'a') is True and plugins.remove_lock(lf, 'a') is False


@needs_git
def test_sync_leaves_a_locked_plugin_alone(tmp_path):
    src = _repo(tmp_path)
    pdir = tmp_path / 'plugins'
    decl = {'source': str(src), 'ref': 'v1'}
    assert plugins.sync(Runner(pretend=False), pdir, [decl], locked={'src'}) == [('src', 'locked')]
    assert not (pdir / 'src').exists()
    plugins.sync(Runner(pretend=False), pdir, [decl])
    assert (pdir / 'src' / 'routes.hu').read_text() == 'one\n'
    # a moved ref is not taken while locked
    decl['ref'] = 'v2'
    plugins.sync(Runner(pretend=False), pdir, [decl], locked={'src'})
    assert (pdir / 'src' / 'routes.hu').read_text() == 'one\n'


def _ctx(tmp_path):
    pdir = tmp_path / 'plugins'
    (pdir / 'codeplug').mkdir(parents=True)
    (pdir / 'codeplug' / 'plugin.hu').write_text(
        f'{{ name: codeplug  requires-abi: {plugins.ABI_VERSION}  code: driver.py }}\n')
    (pdir / 'codeplug' / 'driver.py').write_text('# a driver\n')
    user = tmp_path / 'user.hu'
    user.write_text('{ plugins: [ { source: codeplug  ref: v1 } ] }\n')
    ctx = types.SimpleNamespace(
        runner=Runner(pretend=False),
        paths=types.SimpleNamespace(user_config_file=str(user), plugins_dir=pdir,
                                    plugin_trust_file=str(tmp_path / 'trust.hu'),
                                    plugin_lock_file=tmp_path / 'locks.hu'))
    ctx.invalidate = lambda: None
    ctx.ensure_plugin_code = lambda: None
    return ctx


def test_a_locked_plugin_refuses_update_bless_and_trust(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    ok, note = actions.plugin_lock(ctx, 'codeplug')
    assert ok and 'locked codeplug' in note and 'still loads' in note
    assert actions.plugin_lock(ctx, 'codeplug') == (False, 'codeplug is already locked')

    ok, note = actions.plugin_trust(ctx, 'codeplug')
    assert not ok and 'locked' in note and 'no trust' in note
    n, note = actions.plugin_trust_all(ctx)
    assert n == 0 and '1 locked left untrusted' in note
    monkeypatch.setattr(plugins, 'latest_ref', lambda *a: pytest.fail('update must not reach the remote'))
    ok, note, _r = actions.plugin_update(ctx, 'codeplug', latest=True)
    assert not ok and 'no update' in note
    rows = actions.plugin_update_all(ctx)
    assert rows == [('codeplug', True, 'codeplug: locked — skipped')]
    ok, note, _r = actions.plugin_add(types.SimpleNamespace(**vars(ctx), ensure_user_config=lambda: None),
                                      'codeplug')
    assert not ok and 'unlock it first' in note

    row = plugins.status(ctx.paths.plugins_dir, [{'source': 'codeplug'}],
                         lock_file=ctx.paths.plugin_lock_file)[0]
    assert row['locked']
    assert menu._plugin_cells(row, {'depth': 0, 'last': [True]}, 'v2')[0] == '⊘codeplug'
    assert menu._plugin_remote_elem(row, 'v2') == 'info_dim'          # no amber nag for a held update

    assert actions.plugin_unlock(ctx, 'codeplug') == (True, 'unlocked codeplug')
    assert actions.plugin_trust(ctx, 'codeplug')[0]


def test_lock_honors_pretend(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.runner = Runner(pretend=True)
    assert actions.plugin_lock(ctx, 'codeplug') == (False, actions.PRETEND_NOT_SAVED)
    assert not ctx.paths.plugin_lock_file.exists()


@needs_git
def test_cli_lock_list_and_diff(tmp_path, capsys):
    from configsys.app import main
    src = _repo(tmp_path)
    home = ['--home', str(tmp_path), '--os', 'pop']
    assert main(home + ['plugin', 'add', str(src), '--ref', 'v1']) == 0
    capsys.readouterr()
    assert main(home + ['plugin', 'diff', 'sp', '--to', 'v2']) == 0
    out = capsys.readouterr().out
    assert 'v1 -> v2' in out and '+two' in out
    assert main(home + ['plugin', 'lock', 'sp']) == 0
    assert main(home + ['plugin', 'list']) == 0
    out = capsys.readouterr().out
    assert 'locked since' in out
    assert main(home + ['plugin', 'update', 'sp', '--ref', 'v2']) == 1
    assert 'locked' in capsys.readouterr().out
    assert main(home + ['plugin', 'unlock', 'sp']) == 0
