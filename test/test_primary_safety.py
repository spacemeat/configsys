'''The primary's git layer is safe off the happy path (docs/done/primary-safety-plan.md; findings in
docs/review-2026-11/primary.md): the ambient git environment never redirects it, file names that aren't
UTF-8 and very long path lists don't crash the snapshot/commit bracket, paths are never globs, and the
non-interactive network env keeps your own ssh command.'''

import os
import shutil
import subprocess

import pytest

from configsys import primarygit

from test_primary_push import BASE_P, _ctx, _git, primary  # noqa: F401

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


def _log(repo):
    return _git(repo, 'log', '--format=%s')


@needs_git
def test_an_ambient_git_dir_never_redirects_the_primary(primary, tmp_path, monkeypatch):
    # inside `yadm enter` / `vcsh enter`, GIT_DIR + GIT_WORK_TREE point at your dotfiles repo; the
    # primary's snapshot / commit / state must still act on the primary (review primary-06)
    base, clone, bare, other = primary
    dot = tmp_path / 'dotfiles'
    subprocess.run(['git', 'init', '-q', str(dot)], check=True)
    (dot / 'secret.txt').write_text('token')
    monkeypatch.setenv('GIT_DIR', str(dot / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(dot))
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    assert snap is not None and snap.before == set()
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))
    assert primarygit.commit(ctx, snap, 'picks add fzf') == []
    st = primarygit.state(ctx)
    monkeypatch.delenv('GIT_DIR')
    monkeypatch.delenv('GIT_WORK_TREE')
    assert _log(clone).splitlines()[0] == 'picks add fzf'
    assert subprocess.run(['git', 'log'], cwd=dot, capture_output=True).returncode != 0   # nothing there
    assert st['branch'] == 'main' and st['ahead'] == 1


@needs_git
def test_a_file_name_that_is_not_utf8_does_not_break_the_bracket(primary):
    # an app writing into a config dir that's linked into the primary can create one (primary-05)
    base, clone, bare, other = primary
    odd = os.fsencode(str(clone / 'dotfiles')) + b'/caf\xe9.conf'
    os.makedirs(clone / 'dotfiles')
    with open(odd, 'wb') as fh:
        fh.write(b'x')
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    assert snap is not None and len(snap.before) == 1              # the odd name, already dirty
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))
    assert primarygit.commit(ctx, snap, 'picks add fzf') == []
    assert _log(clone).splitlines()[0] == 'picks add fzf'
    assert os.path.exists(odd)                                     # left alone, still uncommitted
    assert primarygit.state(ctx)['dirty'] is True


@needs_git
def test_a_long_path_list_commits_without_overflowing_the_command_line(primary):
    # a `dotfiles capture` of a big config dir: thousands of paths at once (primary-05)
    base, clone, bare, other = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'dotfiles' / 'big-dotfiles.cfs')
    cfs = clone / 'dotfiles' / 'big-dotfiles.cfs' / 'a-rather-long-directory-name-for-the-config'
    cfs.mkdir(parents=True)
    for i in range(2000):
        (cfs / f'theme-file-number-{i:05d}.conf').write_text(str(i))
    assert primarygit.commit(ctx, snap, 'dotfiles capture big-dotfiles') == []
    assert _git(clone, 'status', '--porcelain') == ''
    assert _git(clone, 'show', '--stat', '--format=%s', 'HEAD').splitlines()[0] == \
        'dotfiles capture big-dotfiles'


@needs_git
def test_paths_are_literal_never_globs(primary):
    # a captured `a[bc].conf` must not stage your hand-edited `ab.conf` (primary-18)
    base, clone, bare, other = primary
    (clone / 'ab.conf').write_text('mine\n')
    _git(clone, 'add', 'ab.conf')
    _git(clone, 'commit', '-qm', 'ab')
    (clone / 'ab.conf').write_text('mine, edited by hand\n')
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'a[bc].conf')
    (clone / 'a[bc].conf').write_text('captured\n')
    primarygit.commit(ctx, snap, 'capture')
    assert _git(clone, 'status', '--porcelain', 'ab.conf') == 'M ab.conf'   # still unstaged (" M")


@needs_git
def test_the_non_interactive_network_env_keeps_your_ssh_command(primary, monkeypatch):
    # push and the background fetch never prompt — and never replace your core.sshCommand (primary-10)
    base, clone, bare, other = primary
    repo = primarygit.PrimaryRepo(clone)
    monkeypatch.delenv('GIT_SSH_COMMAND', raising=False)
    assert repo.network_env(interactive=False)['GIT_SSH_COMMAND'] == 'ssh -o BatchMode=yes'
    _git(clone, 'config', 'core.sshCommand', 'ssh -i ~/.ssh/primary_key')
    env = repo.network_env(interactive=False)
    assert env['GIT_SSH_COMMAND'] == 'ssh -i ~/.ssh/primary_key -o BatchMode=yes'
    assert env['GIT_TERMINAL_PROMPT'] == '0'
    monkeypatch.setenv('GIT_SSH_COMMAND', 'ssh -F /tmp/cfg')
    assert repo.network_env(interactive=False)['GIT_SSH_COMMAND'] == 'ssh -F /tmp/cfg -o BatchMode=yes'
    assert 'GIT_TERMINAL_PROMPT' not in repo.network_env(interactive=True)


@needs_git
def test_the_bracket_never_raises(primary, monkeypatch):
    # snapshot / commit / state are best-effort: a git that can't run is "nothing to do", not a crash
    base, clone, bare, other = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))

    def boom(*a, **k):
        raise OSError('git vanished')
    monkeypatch.setattr(primarygit.PrimaryRepo, 'git', boom)
    assert primarygit.state(ctx) is None
    notes = primarygit.commit(ctx, snap, 'x')
    assert notes and 'could not' in notes[0]
    again = primarygit.snapshot(ctx)                                # opening one runs no git at all
    primarygit.will_write(clone / 'p.hu')                           # git fails: recorded as unknown
    assert again.unknown and primarygit.commit(ctx, again, 'y') == []


# -- the undoable combine (phase 2: review A2, A3) ----------------------------------------------

from test_primary_push import Scripted, _both_change_line_one, _clean, _other_pushes, _remote_file  # noqa: E402


def _state(clone):
    return {'head': _git(clone, 'rev-parse', 'HEAD'), 'status': _git(clone, 'status', '--porcelain'),
            'stash': _git(clone, 'stash', 'list'),
            'merging': (clone / '.git' / 'MERGE_HEAD').exists() or (clone / '.git' / 'rebase-merge').exists()}


@needs_git
def test_ctrl_c_at_a_conflict_question_puts_everything_back(primary):
    # an interrupt mid-merge used to leave MERGE_HEAD, conflict markers and your edits in the stash
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    (clone / 'scratch.txt').write_text('my own, uncommitted\n')
    before = _state(clone)
    with pytest.raises(KeyboardInterrupt):
        primarygit.push(_ctx(base), Scripted(raise_on=KeyboardInterrupt()))
    after = _state(clone)
    assert after == before and not after['merging']
    assert (clone / 'scratch.txt').read_text() == 'my own, uncommitted\n'
    assert '<<<<<<<' not in (clone / 'notes.txt').read_text()


@needs_git
def test_any_error_mid_combine_puts_everything_back(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    before = _state(clone)
    with pytest.raises(OSError):
        primarygit.push(_ctx(base), Scripted(raise_on=OSError('the terminal went away')))
    assert _state(clone) == before


@needs_git
def test_a_binary_file_both_changed_is_asked_about_not_decoded(primary):
    base, clone, bare, other = primary
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\nOTHER')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'other logo'); _git(other, 'push', '-q', 'origin', 'main')
    (clone / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\nMINE')
    _git(clone, 'add', '-A'); _git(clone, 'commit', '-qm', 'my logo')
    ui = Scripted('mine')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    assert [a[0] for a in ui.asked] == ['resolve']
    assert subprocess.run(['git', 'show', 'main:logo.png'], cwd=bare, capture_output=True).stdout == \
        b'\x89PNG\r\n\x1a\nMINE'
    _clean(clone)


@needs_git
def test_a_malformed_plugins_entry_falls_back_to_the_file_question(primary):
    # a remote `plugins:` entry whose source is a map used to raise TypeError mid-merge (primary-02)
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('} }', '}  splash: plain  plugins: [ { source: { x: y } } ] }'))
    (clone / 'p.hu').write_text(BASE_P.replace('} }', '}  splash: ocean }'))
    _git(clone, 'commit', '-qam', 'mine')
    ui = Scripted('stop')
    before = _state(clone)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert not ok
    assert any(a[1] == 'p.hu' for a in ui.asked)                       # asked, didn't crash
    assert _state(clone) == before


@needs_git
def test_hand_edits_overlapping_what_came_in_are_asked_about_first(primary):
    # decision 3: refuse and ask — never leave conflict markers while reporting success (primary-03)
    base, clone, bare, other = primary
    _other_pushes(other, 'notes.txt', BASE_P.replace('[ btop ]', '[ btop  zsh ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'mine')
    (clone / 'notes.txt').write_text(BASE_P.replace('[ btop ]', '[ btop  fish ]'))   # by hand, overlapping
    before = _state(clone)
    ui = Scripted(overlap='stop')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert not ok and ('overlap', ('notes.txt',)) in ui.asked
    assert _state(clone) == before                                     # nothing touched
    assert 'fish' in (clone / 'notes.txt').read_text()
    assert 'yq' not in _remote_file(bare)                              # nothing pushed
    assert any('overlap' in ln for ln in lines)


@needs_git
def test_overlapping_hand_edits_included_go_through_the_normal_questions(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'notes.txt', BASE_P.replace('[ btop ]', '[ btop  zsh ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'mine')
    (clone / 'notes.txt').write_text(BASE_P.replace('[ btop ]', '[ btop  fish ]'))
    ui = Scripted('mine', overlap='include')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    assert 'fish' in _git(bare, 'show', 'main:notes.txt') and 'yq' in _remote_file(bare)
    _clean(clone)


@needs_git
def test_hand_edits_that_dont_overlap_come_back_after_the_combine(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'notes.txt', BASE_P.replace('[ btop ]', '[ btop  zsh ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'mine')
    (clone / 'mine-only.txt').write_text('untracked, mine\n')
    ok, lines = primarygit.push(_ctx(base), Scripted())
    assert ok, lines
    assert (clone / 'mine-only.txt').read_text() == 'untracked, mine\n'
    assert _git(clone, 'stash', 'list') == ''
    assert '<<<<<<<' not in (clone / 'notes.txt').read_text()


@needs_git
def test_a_primary_left_mid_merge_is_never_pushed_or_committed_into(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    _git(clone, 'fetch', '-q', 'origin')
    subprocess.run(['git', 'merge', '--no-commit', 'origin/main'], cwd=clone, capture_output=True)
    assert (clone / '.git' / 'MERGE_HEAD').exists()
    ctx = _ctx(base)
    ok, lines = primarygit.push(ctx, Scripted('mine'))
    assert not ok and 'merge' in lines[-1] and '--abort' in lines[-1]
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    notes = primarygit.commit(ctx, snap, 'picks add yq')
    assert notes and 'middle of a merge' in notes[0]
    assert _git(clone, 'diff', '--cached', '--name-only', '--', 'p.hu') == ''      # not staged


def test_the_cli_and_tui_ask_about_overlapping_edits(monkeypatch, capsys):
    from configsys.app import _CliPushUI
    from configsys.tui import menu
    cli = _CliPushUI()
    cli.interactive = False                                       # no terminal: the cautious answer
    assert cli.overlapping('prim', ['notes.txt']) == 'stop'
    assert 'overlap' in capsys.readouterr().out
    cli.interactive = True
    monkeypatch.setattr('builtins.input', lambda prompt: 'i')
    assert cli.overlapping('prim', ['notes.txt']) == 'include'
    seen = []
    monkeypatch.setattr(menu, '_popup_choose', lambda *a, **k: seen.append(a[2]) or 0)
    assert menu._TuiPushUI(None, None).overlapping('prim', ['a', 'b']) == 'stop'   # the default
    assert seen == ['prim: your edits to 2 files overlap what your other machine pushed']


# -- the small fixes (plan phase 4) -------------------------------------------------------------

@needs_git
def test_quitting_under_auto_pushes_without_asking_anything(primary, monkeypatch):
    # B7 / primary-11: "nothing is asked" — not even "push your hand edits too?"
    from configsys.tui import menu
    base, clone, bare, other = primary
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'mine')
    (clone / 'notes.txt').write_text('a hand edit\n')
    asked = []
    monkeypatch.setattr(menu, '_popup_choose', lambda *a, **k: asked.append(a[2]) or 0)
    monkeypatch.setattr(primarygit, 'push_mode', lambda ctx: 'auto-on-quit')
    leave, notes = menu._quit_push(None, None, _ctx(base), force=True)
    assert leave and asked == []
    assert notes and notes[-1].startswith('pushed 1 change')
    assert (clone / 'notes.txt').read_text() == 'a hand edit\n'          # left out, still here


@needs_git
def test_a_primary_never_pushed_shows_its_commits_as_not_pushed(primary):
    # B8 / primary-15: after `plugin init` + `set-source` to an empty repo there's no origin/main yet
    base, clone, bare, other = primary
    _git(clone, 'update-ref', '-d', 'refs/remotes/origin/main')
    st = primarygit.state(_ctx(base))
    assert st is not None and st['ahead'] == int(_git(clone, 'rev-list', '--count', 'HEAD')) >= 1


def test_a_markdown_underline_is_not_a_conflict_marker(tmp_path):
    # B16 / primary-25
    readme = tmp_path / 'README.md'
    readme.write_text('Title\n=======\n\nbody\n')
    assert not primarygit._has_markers(readme)
    readme.write_text('<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n')
    assert primarygit._has_markers(readme)


@needs_git
def test_the_combine_leaves_no_copies_of_your_files_behind(primary):
    # B18 / primary-34: the driver's scratch dir (notes + base/mine/theirs copies) goes away
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    ok, lines = primarygit.push(_ctx(base), Scripted('mine'))
    assert ok, lines
    assert not (clone / '.git' / 'configsys-merge').exists()


def test_text_from_a_remote_is_made_safe_to_show():
    # A5 / primary-17: a value carrying a terminal escape (OSC 52 writes your clipboard, \x1b[2K
    # rewrites the prompt) must reach a question as visible text
    shown = primarygit._printable('ocean\x1b]52;c;ZXZpbA==\x07\x1b[2K\rkeep it\nnext')
    assert '\x1b' not in shown and '\x07' not in shown and '\r' not in shown
    assert shown == 'ocean\\x1b]52;c;ZXZpbA==\\x07\\x1b[2K\\x0dkeep it ⏎ next'
    assert primarygit._printable('a\tb') == 'a\tb'
    said = primarygit.explain_git_failure('remote: \x1b[31mspoofed\x1b[0m\nfatal: weird', name='prim',
                                          root='/r', source='github:me/prim')
    assert '\x1b' not in said


@needs_git
def test_settings_in_one_file_are_numbered_by_setting(primary):
    # B12 / primary-21: two keys conflict in one file — the questions say 1 of 2 and 2 of 2
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('} }', '}  splash: plain  effects: none }'))
    (clone / 'p.hu').write_text(BASE_P.replace('} }', '}  splash: ocean  effects: full }'))
    _git(clone, 'commit', '-qam', 'mine')
    seen = []

    class UI(Scripted):
        def resolve_value(self, name, path, words, i, n):
            seen.append((i, n))
            return 'mine'
    ok, lines = primarygit.push(_ctx(base), UI())
    assert ok, lines
    assert seen == [(0, 2), (1, 2)]


def test_git_failures_name_the_right_cause_and_host():
    # B13 / primary-22
    def why(text, source='github:me/prim'):
        return primarygit.explain_git_failure(text, name='prim', root='/r', source=source)
    denied = why('remote: Permission to me/prim.git denied to bot.\nfatal: unable to access '
                 "'https://github.com/me/prim.git/': The requested URL returned error: 403")
    assert 'refused the push' in denied and 'offline' not in denied
    assert 'branch rule' in why(' ! [remote rejected] main -> main (protected branch hook declined)')
    assert 'another machine pushed' in why(' ! [rejected] main -> main (fetch first)')
    assert 'ssh -T git@gitlab.com' in why('Host key verification failed.', source='gitlab:me/prim')
    assert 'git@git.example.org' in why('Host key verification failed.',
                                        source='git@git.example.org:me/prim.git')
    assert "GitLab's SSH Keys page" in why('git@gitlab.com: Permission denied (publickey).',
                                           source='gitlab:me/prim')
    assert 'offline?' in why('fatal: unable to access ... Could not resolve host: github.com')


@needs_git
def test_a_refused_switch_to_the_branch_leaves_the_pin_as_it_was(primary):
    # B14 / primary-23: `ref:` is written only once the checkout worked
    from configsys import plugins
    base, clone, bare, other = primary
    _git(clone, 'tag', 'v1'); _git(clone, 'push', '-q', 'origin', 'v1')
    ctx = _ctx(base)
    decls = plugins.declared(ctx.paths.user_config_file)
    decls[0]['ref'] = 'v1'
    plugins.set_declared(ctx.paths.user_config_file, decls)
    _other_pushes(other, 'p.hu', BASE_P.replace('[ jq ]', '[ jq  yq ]'))    # main moves past v1
    _git(clone, 'fetch', '-q', 'origin')
    _git(clone, 'checkout', '-q', '--detach', 'v1')
    pinned = _git(clone, 'rev-parse', 'HEAD')
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  gh ]'))     # an edit that blocks it
    ok, lines = primarygit.push(_ctx(base), Scripted(switch=True, include=False))
    assert not ok
    assert plugins.declared(ctx.paths.user_config_file)[0]['ref'] == 'v1'
    assert _git(clone, 'rev-parse', 'HEAD') == pinned
    assert subprocess.run(['git', 'symbolic-ref', '-q', 'HEAD'], cwd=clone).returncode != 0   # detached
    assert 'gh' in (clone / 'p.hu').read_text()
    assert any('still pinned' in ln for ln in lines)


# -- G1: what leaves the machine is shown first (decision 6) -------------------------------------

@needs_git
def test_push_shows_what_leaves_and_a_no_pushes_nothing(primary):
    base, clone, bare, other = primary
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'picks add yq')
    ui = Scripted(confirm=False)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert not ok and 'not pushed' in lines[-1]
    commits, files = ui.confirms[0]
    assert any('picks add yq' in c for c in commits) and files == ('p.hu',)
    assert 'yq' not in _remote_file(bare)
    ok, lines = primarygit.push(_ctx(base), Scripted(confirm=True))
    assert ok and 'yq' in _remote_file(bare)


@needs_git
def test_pretend_push_lists_what_would_leave(primary, capsys):
    from configsys.app import main
    base, clone, bare, other = primary
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'picks add yq')
    head = _git(clone, 'rev-parse', 'HEAD')
    capsys.readouterr()
    assert main(base + ['--pretend', 'plugin', 'push']) == 0
    out = capsys.readouterr().out
    assert '[pretend] would push 1 change' in out and 'picks add yq' in out and 'p.hu' in out
    assert _git(clone, 'rev-parse', 'HEAD') == head and 'yq' not in _remote_file(bare)


def test_the_cli_confirms_on_a_terminal_unless_yes(monkeypatch, capsys):
    from configsys.app import _CliPushUI
    ui = _CliPushUI()
    ui.interactive = True
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    assert ui.confirm_push('prim', 'github:me/prim', ['abc1234 picks add yq'], ['p.hu']) is False
    out = capsys.readouterr().out
    assert 'abc1234 picks add yq' in out and 'p.hu' in out and 'github:me/prim' in out
    assert _CliPushUI(yes=True).confirm_push('prim', 's', ['x'], ['f']) is True
    quiet = _CliPushUI()
    quiet.interactive = False                                       # a script: the command is consent
    assert quiet.confirm_push('prim', 's', ['x'], ['f']) is True
