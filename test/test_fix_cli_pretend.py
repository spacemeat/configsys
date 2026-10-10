'''Regression tests: --pretend is a TRUE dry run (ledger, failure capture, dotfiles marker, offline
version placeholders, and every config-editing command), plus the dotfiles backup-never-clobbers fix.'''

import os
import subprocess
import types

import pytest

from configsys import actions, app
from configsys.app import main
from configsys.componentObj import ResolvedComponent
from configsys.drivers.dotfiles import DotFiles, backup_cmd
from configsys.paths import Paths
from configsys.runner import Result, Runner


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())


def _cs(tmp_path, *argv):
    return main(['--home', str(tmp_path), '--os', 'pop', *argv])


# -- 1(a) ledger / receipts --------------------------------------------------------------------

def test_pretend_lock_writes_no_ledger(tmp_path, capsys):
    rc = _cs(tmp_path, '--pretend', 'lock', 'ripgrep')
    out = capsys.readouterr().out
    assert rc == 0 and 'apt-mark hold ripgrep' in out
    assert not (tmp_path / '.config' / 'configsys' / 'state.hu').exists()


def test_pretend_run_plan_never_saves_ledger_or_receipts(tmp_path):
    class _Drv:
        name = 'apt'
        privileged = False
        holds_version = True

        def sudo(self, rc):
            return False

        def lock(self, rc):
            return Result('hold', 0)

        def install(self, rc):
            return Result('inst', 0)

        def get_version(self, rc):
            return '1.0'

    saved = []

    class _Ledger:
        def set_lock(self, *a):
            saved.append(('lock', a))

        def set_receipt(self, rc):
            saved.append(('receipt', rc.key))

        def save(self, paths):
            saved.append(('save',))

    ctx = types.SimpleNamespace(runner=Runner(pretend=True), paths=None, config=None)
    rcu = ResolvedComponent(key='apt\\x', driver='apt', comp='x', fields={})
    import configsys.drivers as drivers_mod
    orig = drivers_mod.get_driver
    drivers_mod.get_driver = lambda *a, **k: _Drv()
    try:
        res = actions.run_plan(ctx, [('lock', 'apt\\x', rcu), ('install', 'apt\\x', rcu)],
                               ledger=_Ledger(), on_line=lambda m: None)
    finally:
        drivers_mod.get_driver = orig
    assert res.rc_code == 0
    assert saved == []


# -- 1(b) no false "NOT DETECTED" under pretend --------------------------------------------------

def test_pretend_install_has_no_not_detected_warning(tmp_path, capsys):
    _cs(tmp_path, '--pretend', 'install', 'ripgrep')
    assert 'NOT DETECTED' not in capsys.readouterr().out


# -- 1(d)+(e) offline version placeholder, no failure capture ------------------------------------

def test_pretend_unresolved_download_is_a_placeholder_not_a_failure(tmp_path, capsys):
    rc = _cs(tmp_path, '--pretend', 'install', 'lazygit')
    out = capsys.readouterr().out
    assert rc == 0
    assert 'FAILED' not in out and 'configsys report' not in out
    assert '<latest release>' in out
    state = tmp_path / '.config' / 'configsys'
    assert not (state / 'last-failure.hu').exists()
    assert not (state / 'state.hu').exists()
    # 1(c): the dotfiles companion is announced, not stamped
    assert not list(state.rglob('manifest.hu'))


def test_offer_report_under_pretend_saves_nothing(tmp_path, capsys):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    ctx = types.SimpleNamespace(runner=Runner(pretend=True), paths=paths)
    app._offer_report(ctx, [{'component': 'foo'}], fatal=1)
    assert not paths.failure_file.exists()
    assert '[pretend]' in capsys.readouterr().out


# -- 1(c) dotfiles marker --------------------------------------------------------------------------

def _df_paths(tmp_path):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                      'CONFIGSYS_GLUE_SHELLS': 'bash'})


def _df_unit(comp='neovim'):
    return ResolvedComponent(key=f'dotfiles\\{comp}', driver='dotfiles', comp=comp,
                             fields={'config': {'src': 'neovim', 'dst': '$XDG_CONFIG_HOME/nvim'}})


def test_dotfiles_pretend_install_stamps_no_marker_or_store_copy(tmp_path):
    p = _df_paths(tmp_path)
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)
    (p.dotfiles_dir / 'neovim' / 'init.lua').write_text('tmpl')
    msgs = []
    r = Runner(pretend=True, echo=msgs.append)
    assert DotFiles(r, paths=p).install(_df_unit()).ok
    assert not (p.user_dotfiles_dir / 'neovim.cfs').exists()
    assert not (p.user_dotfiles_dir / 'neovim').exists()            # template not materialized
    assert any('would stamp' in m for m in msgs)


# -- 13: the .pre-configsys backup never overwrites an earlier one ------------------------------

def test_backup_cmd_never_overwrites_existing_backups(tmp_path):
    t = tmp_path / 'f'
    (tmp_path / 'f.pre-configsys').write_text('original')
    (tmp_path / 'f.pre-configsys.1').write_text('second')
    t.write_text('third')
    import shlex
    subprocess.run(['sh', '-c', backup_cmd(shlex.quote(str(t)))], check=True)
    assert (tmp_path / 'f.pre-configsys').read_text() == 'original'
    assert (tmp_path / 'f.pre-configsys.1').read_text() == 'second'
    assert (tmp_path / 'f.pre-configsys.2').read_text() == 'third'
    assert not t.exists()


def test_second_force_install_keeps_the_first_backup(tmp_path):
    p = _df_paths(tmp_path)
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)
    (p.dotfiles_dir / 'neovim' / 'init.lua').write_text('template')
    p.dotfiles_force = True
    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'mine.lua').write_text('ORIGINAL')
    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.install(_df_unit()).ok
    # something replaces the link with a real dir again; a second --force must not clobber backup 1
    target.unlink()
    target.mkdir()
    (target / 'mine.lua').write_text('LATER')
    assert df.install(_df_unit()).ok
    assert (p.home / '.config' / 'nvim.pre-configsys' / 'mine.lua').read_text() == 'ORIGINAL'
    assert (p.home / '.config' / 'nvim.pre-configsys.1' / 'mine.lua').read_text() == 'LATER'


def test_dotfiles_driver_cannot_target_a_version():
    assert DotFiles.targets_version is False


# -- 1(f) config-editing commands write nothing under --pretend ---------------------------------

@pytest.mark.parametrize('argv', [
    ['picks', 'add', 'ripgrep'],
    ['picks', 'rm', 'ripgrep'],
    ['picks', 'to-primary'],
    ['config', 'set', 'effects', 'reduced'],
    ['config', 'unset', 'effects'],
    ['config', 'set', 'locations', 'ripgrep=/opt/rg'],
    ['machine', 'add', 'laptop'],
    ['machine', 'use', 'laptop'],
    ['disp', 'set', 'ripgrep', 'seen'],
    ['theme', 'set', 'colors.accent', '#ffffff'],
    ['theme', 'unset', 'colors.accent'],
    ['theme', 'save', 'mytheme'],
    ['orphans', '--adopt', 'ripgrep'],
    ['orphans', '--ignore', 'foo*'],
])
def test_pretend_config_edits_write_nothing(tmp_path, capsys, argv):
    rc = _cs(tmp_path, '--pretend', *argv)
    out = capsys.readouterr().out
    assert rc == 0
    assert '[pretend] would' in out
    assert _files(tmp_path) == []


def test_pretend_edits_leave_an_existing_config_untouched(tmp_path, capsys):
    _cs(tmp_path, 'config', 'set', 'effects', 'full')            # real write: creates the config
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    before = cfg.read_text()
    for argv in (['config', 'set', 'effects', 'none'], ['config', 'move', 'effects'],
                 ['machine', 'rm', 'this-machine'], ['picks', 'add', 'ripgrep']):
        _cs(tmp_path, '--pretend', *argv)
    assert cfg.read_text() == before


def test_pretend_plugin_add_declares_nothing(tmp_path, capsys):
    src = tmp_path / 'src' / 'myplug'
    src.mkdir(parents=True)
    (src / 'plugin.hu').write_text('{\n    name: myplug\n    requires-abi: 1\n}\n')
    home = tmp_path / 'home'
    rc = main(['--home', str(home), '--os', 'pop', '--pretend', 'plugin', 'add', str(src)])
    out = capsys.readouterr().out
    assert rc == 0 and '[pretend] would declare' in out
    assert not (home / '.config' / 'configsys' / 'configsys.hu').exists()
