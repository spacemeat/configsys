'''The write journal (docs/done/primary-journal-plan.md; review-2026-11 B1, B3, C1): every configsys
writer into the primary says what it writes (`primarygit.will_write`), and the bracket commits exactly
that — so a writer nobody wired in is a visible note and a failure here, an edit you make while a
command runs is never swept in, and an action that writes nothing costs no git call.'''

from pathlib import Path

import os
import shutil
import subprocess

import pytest

from configsys import primarygit
from configsys.app import Context, _command_words, build_parser, main

pytestmark = [pytest.mark.real_runner, pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def primary(tmp_path, monkeypatch):
    '''A populated sandbox home with a blessed, synced primary `prim` that has dotfiles/ and glue/
    roots — so capture, glue add/override and activate all land in it.'''
    for k in list(os.environ):
        if k.startswith(('CONFIGSYS_', 'XDG_')):
            monkeypatch.delenv(k)
    for k, v in (('GIT_AUTHOR_NAME', 't'), ('GIT_AUTHOR_EMAIL', 't@t'), ('GIT_COMMITTER_NAME', 't'),
                 ('GIT_COMMITTER_EMAIL', 't@t')):
        monkeypatch.setenv(k, v)
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr('builtins.input', lambda *a: 'y')
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    seed = tmp_path / 'seed'
    subprocess.run(['git', 'clone', '-q', str(bare), str(seed)], check=True, capture_output=True)
    (seed / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ] }\n')
    (seed / 'p.hu').write_text('{ picks: { this-machine: [ btop  fzf  bash ] }  effects: reduced }\n')
    for d in ('dotfiles', 'glue'):
        (seed / d).mkdir()
        (seed / d / 'README').write_text(f'{d} that travel\n')
    _git(seed, 'add', '-A'); _git(seed, 'commit', '-qm', 'A'); _git(seed, 'push', '-q', 'origin', 'main')
    (home / '.bashrc').write_text('# bashrc\n')
    (home / '.config' / 'btop').mkdir(parents=True)
    (home / '.config' / 'btop' / 'btop.conf').write_text('color_theme = "x"\n')
    base = ['--home', str(home), '--os', 'pop_os!:22.04', '-q']
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    state = home / '.config' / 'configsys'
    (state / 'staged-glue' / 'bash').mkdir(parents=True)
    (state / 'staged-glue' / 'bash' / 'rustup.sh').write_text('export PATH="$HOME/.cargo/bin:$PATH"\n')
    return base, state / 'plugins' / 'prim', home


def _log(clone):
    return _git(clone, 'log', '--format=%s', '-n', '5').splitlines()


# Every CLI verb that writes into the primary, with the writer it reaches. A new writer that doesn't
# call `will_write` leaves its file uncommitted (and noted) — this fails until it is wired in.
WRITES = [
    (['picks', 'add', 'jq'], 'plugins.set_section'),
    (['config', 'set', 'splash', 'plain'], 'plugins.set_section (a uniform setting)'),
    (['config', 'unset', 'effects'], 'plugins.remove_sections (a uniform setting)'),
    (['theme', 'set', 'colors.accent', '#ff0000'], 'plugins.set_theme'),
    (['dotfiles', 'capture', 'btop', '--yes'], 'Dotfiles.capture + _write_manifest_at'),
    (['glue', 'add', 'mine', '--shell', 'bash'], 'Glue.new_user_snippet + the 99-user scaffold'),
    (['glue', 'override', 'fzf', '--shell', 'bash'], 'Glue.override + _record_override'),
    (['dotfiles', 'activate', 'rustup'], 'Glue.add_user_glue'),
]


@pytest.mark.parametrize('argv,writer', WRITES, ids=[' '.join(a) for a, _ in WRITES])
def test_every_writer_is_journaled(primary, capsys, argv, writer):
    base, clone, _home = primary
    head = _git(clone, 'rev-parse', 'HEAD')
    capsys.readouterr()
    assert main(base + argv) == 0
    out = capsys.readouterr().out
    assert _git(clone, 'rev-parse', 'HEAD') != head, f'{writer} wrote nothing into the primary'
    assert _log(clone)[0] == _command_words(argv, argv[0])
    assert _git(clone, 'status', '--porcelain', '--untracked-files=all') == '', \
        f'{writer} wrote into the primary without primarygit.will_write'
    assert 'not by configsys' not in out


def test_plugin_init_merge_commits_the_moved_dotfiles_and_glue(primary, capsys):
    # `_plugin_init_merge` + `_sweep_glue_to_primary`: local bits moved into an existing primary
    base, clone, home = primary
    state = home / '.config' / 'configsys'
    (state / 'dotfiles' / 'foo-dotfiles.cfs').mkdir(parents=True)
    (state / 'dotfiles' / 'foo-dotfiles.cfs' / 'foo.conf').write_text('x = 1\n')
    (state / 'glue' / 'shell' / 'bash' / 'user.d').mkdir(parents=True)
    (state / 'glue' / 'shell' / 'bash' / 'user.d' / 'a.sh').write_text('alias a=b\n')
    assert main(base + ['plugin', 'init']) == 0
    assert _log(clone)[0] == 'plugin init'
    files = _git(clone, 'show', '--name-only', '--format=', 'HEAD').splitlines()
    assert 'dotfiles/foo-dotfiles.cfs/foo.conf' in files and 'glue/shell/bash/user.d/a.sh' in files
    assert _git(clone, 'status', '--porcelain', '--untracked-files=all') == ''


def test_a_primary_with_no_data_file_gets_one_committed(tmp_path, primary):
    # `actions._writable_primary_file`: the empty `<name>.hu` created on a primary's first write
    base, clone, _home = primary
    _git(clone, 'rm', '-q', 'p.hu')
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1 }\n')
    _git(clone, 'commit', '-qam', 'no data')
    assert main(base + ['picks', 'add', 'jq']) == 0
    assert 'prim.hu' in _git(clone, 'show', '--name-only', '--format=', 'HEAD').splitlines()
    assert _git(clone, 'status', '--porcelain', '--untracked-files=all') == ''


def _ctx(base):
    return Context(build_parser().parse_args(base + ['inspect']))


def test_tui_relocate_to_local_copies_and_leaves_the_primary(primary):
    # TUI Dotfiles move-store primary -> local: a COPY (§7.15) — the primary keeps it for your other
    # machines, so nothing is written (or committed) there
    from configsys import actions
    from configsys.drivers import get_driver
    base, clone, home = primary
    assert main(base + ['dotfiles', 'capture', 'btop', '--yes']) == 0
    assert any(p.startswith('dotfiles/btop-dotfiles.cfs/') for p in _git(clone, 'ls-files').splitlines())
    ctx = _ctx(base)
    ctx.ensure_plugin_code()
    _drv, units = actions.dotfiles_units(ctx)
    btop = next(u for u in units if u.comp == 'btop-dotfiles')
    snap = primarygit.snapshot(ctx)
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    assert df.relocate(btop, ctx.paths.user_dotfiles_dir)
    assert primarygit.commit(ctx, snap, 'dotfiles: move to local store') == []
    assert any(p.startswith('dotfiles/btop-dotfiles.cfs/') for p in _git(clone, 'ls-files').splitlines())
    assert (Path(ctx.paths.user_dotfiles_dir) / 'btop-dotfiles.cfs').is_dir()      # the local copy
    assert _git(clone, 'status', '--porcelain', '--untracked-files=all') == ''


def test_an_edit_you_make_while_a_command_runs_is_left_and_named(primary):
    base, clone, _home = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  fzf  bash  jq ] }  effects: reduced }\n')
    (clone / 'notes.txt').write_text('typed in another window meanwhile\n')
    notes = primarygit.commit(ctx, snap, 'picks add jq')
    assert _log(clone)[0] == 'picks add jq'
    assert _git(clone, 'show', '--name-only', '--format=', 'HEAD') == 'p.hu'
    assert _git(clone, 'status', '--porcelain') == '?? notes.txt'
    assert len(notes) == 1 and 'notes.txt' in notes[0] and 'not by configsys' in notes[0]


def test_an_edit_you_made_before_stays_yours_without_a_note(primary):
    base, clone, _home = primary
    (clone / 'notes.txt').write_text('mine, from before\n')
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  fzf  bash  jq ] }  effects: reduced }\n')
    assert primarygit.commit(ctx, snap, 'picks add jq') == []
    assert _git(clone, 'status', '--porcelain') == '?? notes.txt'


def test_a_write_outside_the_primary_is_not_recorded(primary):
    base, clone, home = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(home / '.config' / 'configsys' / 'configsys.hu')
    primarygit.will_write(clone.parent / 'prim-other')            # a sibling dir sharing a prefix
    assert snap.recorded == set() and snap.before is None
    primarygit.will_write(clone)                                   # the checkout itself: everything
    assert snap.recorded == {''}


def test_will_write_with_no_bracket_open_does_nothing(primary):
    base, clone, _home = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.commit(ctx, snap, 'nothing')                        # closes it
    primarygit.will_write(clone / 'p.hu')
    assert snap.recorded == set()


def test_an_action_that_writes_nothing_runs_no_git(primary, monkeypatch):
    # C1: the bracket used to spend ~6 git spawns per non-navigation TUI keypress to learn nothing
    # was written; now opening and closing an empty journal runs none
    base, clone, _home = primary
    ctx = _ctx(base)
    calls = []
    real = primarygit.PrimaryRepo.git
    monkeypatch.setattr(primarygit.PrimaryRepo, 'git', lambda self, *a, **k: calls.append(a) or real(self, *a, **k))
    for _ in range(20):
        snap = primarygit.snapshot(ctx)
        assert snap is not None
        assert primarygit.commit(ctx, snap, 'components: down') == []
    assert calls == []


def test_the_tui_brackets_every_action_and_skips_the_chip_when_nothing_was_written():
    # the allowlist of "actions that don't write" is gone: the journal knows (phase 3)
    from configsys.tui import menu
    assert not hasattr(menu, '_NO_WRITE_ACTIONS')
