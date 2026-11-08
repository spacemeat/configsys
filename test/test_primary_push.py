'''Primary-push plan, phase 3 (docs/done/primary-push-plan.md): `configsys plugin push` commits, combines
with what your other machines pushed (asking per file when both changed the same lines), and pushes to
the primary's branch — never leaving a half-done rebase, never sweeping in your hand edits unasked —
plus the `primary-push: ask | auto | auto-on-quit | manual` setting and the TUI's quit prompt and `P` key.'''

import shutil
import subprocess

import pytest

from configsys import plugins, primarygit
from configsys.app import Context, build_parser, main
from configsys.tui import menu

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')

BASE_P = '{ picks: {\n    this-machine: [ btop ]\n    laptop: [ htop ]\n    desk: [ jq ]\n} }\n'


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def primary(tmp_path, monkeypatch):
    '''A sandbox home with a blessed primary `prim` cloned from bare remote `bare`, plus `other`: a
    second clone standing in for your other machine.'''
    for k, v in (('GIT_AUTHOR_NAME', 't'), ('GIT_AUTHOR_EMAIL', 't@t'), ('GIT_COMMITTER_NAME', 't'),
                 ('GIT_COMMITTER_EMAIL', 't@t')):
        monkeypatch.setenv(k, v)
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    other = tmp_path / 'other'
    subprocess.run(['git', 'clone', '-q', str(bare), str(other)], check=True, capture_output=True)
    (other / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ] }\n')
    (other / 'p.hu').write_text(BASE_P)
    (other / 'notes.txt').write_text(BASE_P)                  # a plain file: git's line merge only
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'A'); _git(other, 'push', '-q', 'origin', 'main')
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    clone = home / '.config' / 'configsys' / 'plugins' / 'prim'
    return base, clone, bare, other


def _ctx(base):
    return Context(build_parser().parse_args(base + ['inspect']))


def _remote_file(bare, path='p.hu'):
    return _git(bare, 'show', f'main:{path}')


def _other_pushes(other, path, text):
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / path).write_text(text)
    _git(other, 'commit', '-qam', f'other: {path}'); _git(other, 'push', '-q', 'origin', 'main')


class Scripted(primarygit.PushUI):
    def __init__(self, choice='stop', include=False, switch=False, edit_to=None, overlap='stop',
                 raise_on=None):
        self.choice, self.include, self.switch, self.edit_to = choice, include, switch, edit_to
        self.overlap, self.raise_on = overlap, raise_on      # raise_on: an exception for a resolve
        self.asked = []

    def overlapping(self, name, paths):
        self.asked.append(('overlap', tuple(paths)))
        return self.overlap

    def include_own(self, name, paths):
        self.asked.append(('include', tuple(paths)))
        return self.include

    def switch_to_branch(self, name, ref, branch):
        self.asked.append(('switch', ref, branch))
        return self.switch

    def resolve(self, name, path, what, i, n):
        self.asked.append(('resolve', path, what))
        if self.raise_on is not None:
            raise self.raise_on
        return self.choice

    def resolve_value(self, name, path, words, i, n):
        self.asked.append(('value', path, words))
        if self.raise_on is not None:
            raise self.raise_on
        return self.choice

    def edit(self, path):
        if self.edit_to is not None:
            path.write_text(self.edit_to)


def _clean(clone):
    assert _git(clone, 'status', '--porcelain') == ''
    assert not (clone / '.git' / 'rebase-merge').exists() and not (clone / '.git' / 'MERGE_HEAD').exists()


@needs_git
def test_push_publishes_configsys_commits(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    out = capsys.readouterr().out
    assert 'not pushed yet; `configsys plugin push` shares it' in out          # ask: a hint, no prompt
    assert 'fzf' not in _remote_file(bare)
    assert main(base + ['plugin', 'push']) == 0
    out = capsys.readouterr().out
    assert 'pushed 1 change to' in out and 'next `configsys plugin sync`' in out
    assert 'fzf' in _remote_file(bare)
    assert primarygit.state(_ctx(base))['ahead'] == 0
    assert main(base + ['plugin', 'push']) == 0
    assert 'nothing to push' in capsys.readouterr().out


@needs_git
def test_push_replays_onto_the_other_machines_changes(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'plugin.hu', '{ name: prim  requires-abi: 1  data: [ p.hu ]  x: 1 }\n')
    assert main(base + ['picks', 'add', 'fzf']) == 0
    ok, lines = primarygit.push(_ctx(base), Scripted())
    assert ok, lines
    assert 'x: 1' in _remote_file(bare, 'plugin.hu') and 'fzf' in _remote_file(bare)
    assert _git(clone, 'rev-list', '--merges', '--count', 'HEAD') == '0'      # a clean replay: linear
    _clean(clone)


def _both_change_line_one(base, clone, other):
    '''This machine and the other both change line two of a plain (non-.hu) file; the other also
    changes line four. (A .hu file would be merged key by key instead — test_humerge.py.)'''
    _other_pushes(other, 'notes.txt', BASE_P.replace('[ btop ]', '[ btop  zsh ]').replace('[ jq ]', '[ jq  yq ]'))
    (clone / 'notes.txt').write_text(BASE_P.replace('[ btop ]', '[ btop  fish ]'))
    _git(clone, 'commit', '-qam', 'mine')


@needs_git
def test_a_conflict_kept_mine_keeps_the_rest_of_theirs(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    ui = Scripted('mine')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    assert ('resolve', 'notes.txt', 'both machines changed the same lines') in ui.asked
    text = _remote_file(bare, 'notes.txt')
    assert 'fish' in text and 'zsh' not in text and 'yq' in text            # overlap: mine; the rest: both
    assert any('settled as you chose' in ln for ln in lines)
    _clean(clone)


@needs_git
def test_a_conflict_kept_theirs(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    ok, _lines = primarygit.push(_ctx(base), Scripted('theirs'))
    assert ok
    text = _remote_file(bare, 'notes.txt')
    assert 'zsh' in text and 'fish' not in text and 'yq' in text


@needs_git
def test_a_conflict_edited_by_hand(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    merged = BASE_P.replace('[ btop ]', '[ btop  fish  zsh ]').replace('[ jq ]', '[ jq  yq ]')
    ok, _lines = primarygit.push(_ctx(base), Scripted('edit', edit_to=merged))
    assert ok and _remote_file(bare, 'notes.txt') == merged.rstrip('\n')


@needs_git
def test_an_unsettled_conflict_pushes_nothing_and_leaves_work_intact(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    head, remote_head = _git(clone, 'rev-parse', 'HEAD'), _git(bare, 'rev-parse', 'main')
    for ui in (Scripted('stop'), Scripted('edit', edit_to=None)):          # an edit that left the markers
        ok, lines = primarygit.push(_ctx(base), ui)
        assert not ok and 'nothing was pushed' in lines[-1]
        assert _git(clone, 'rev-parse', 'HEAD') == head
        assert _git(bare, 'rev-parse', 'main') == remote_head
        _clean(clone)


@needs_git
def test_hand_edits_are_asked_about(primary):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  mine: 1 }\n')
    ui = Scripted(include=False)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok and ('include', ('plugin.hu',)) in ui.asked
    assert any('left out of the push' in ln for ln in lines)
    assert 'mine' not in _remote_file(bare, 'plugin.hu')
    assert _git(clone, 'status', '--porcelain') == 'M plugin.hu'
    ok, _lines = primarygit.push(_ctx(base), Scripted(include=True))
    assert ok and 'mine: 1' in _remote_file(bare, 'plugin.hu')


@needs_git
def test_hand_edits_survive_a_conflicted_combine(primary):
    base, clone, bare, other = primary
    _both_change_line_one(base, clone, other)
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  mine: 1 }\n')
    ok, _lines = primarygit.push(_ctx(base), Scripted('mine'))
    assert ok and 'mine: 1' in (clone / 'plugin.hu').read_text()
    assert 'mine' not in _remote_file(bare, 'plugin.hu')


@needs_git
def test_no_remote_explains_set_source(primary):
    base, clone, _bare, _other = primary
    _git(clone, 'remote', 'remove', 'origin')
    ok, lines = primarygit.push(_ctx(base), Scripted())
    assert not ok and 'no remote' in lines[0] and 'plugin set-source prim' in lines[0]


@needs_git
def test_first_push_to_an_empty_remote(primary, tmp_path):
    base, clone, _bare, _other = primary
    empty = tmp_path / 'empty'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(empty)], check=True)
    _git(clone, 'remote', 'set-url', 'origin', str(empty))
    ok, lines = primarygit.push(_ctx(base), Scripted())
    assert ok, lines
    assert _git(empty, 'rev-parse', 'main') == _git(clone, 'rev-parse', 'HEAD')


@needs_git
def test_a_tag_pinned_primary_is_explained_and_offered_the_branch(primary):
    base, clone, bare, _other = primary
    _git(clone, 'tag', 'v1'); _git(clone, 'push', '-q', 'origin', 'v1')
    ctx = _ctx(base)
    decls = plugins.declared(ctx.paths.user_config_file)
    decls[0]['ref'] = 'v1'
    plugins.set_declared(ctx.paths.user_config_file, decls)
    _git(clone, 'checkout', '-q', '--detach', 'v1')
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))
    ui = Scripted(switch=False, include=True)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert not ok and 'pinned to v1' in lines[0] and ('switch', 'v1', 'main') in ui.asked
    assert plugins.declared(ctx.paths.user_config_file)[0]['ref'] == 'v1'
    ok, lines = primarygit.push(_ctx(base), Scripted(switch=True, include=True))
    assert ok, lines
    assert plugins.declared(ctx.paths.user_config_file)[0]['ref'] == 'main'
    assert _git(clone, 'symbolic-ref', '--short', 'HEAD') == 'main'
    assert 'fzf' in _remote_file(bare)


@needs_git
def test_pretend_pushes_nothing(primary, capsys):
    base, _clone, bare, _other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    capsys.readouterr()
    assert main(base + ['--pretend', 'plugin', 'push']) == 0
    assert '[pretend] would' in capsys.readouterr().out
    assert 'fzf' not in _remote_file(bare)


@needs_git
def test_auto_pushes_after_each_command(primary, capsys):
    base, _clone, bare, _other = primary
    assert main(base + ['config', 'set', 'primary-push', 'auto']) == 0     # lands in the primary
    assert 'primary-push: auto' in _remote_file(bare)                      # ...and is itself pushed
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert 'fzf' in _remote_file(bare)
    assert 'pushed 1 change' in capsys.readouterr().out


@needs_git
def test_manual_stays_quiet(primary, capsys):
    base, _clone, bare, _other = primary
    assert main(base + ['config', 'set', 'primary-push', 'manual']) == 0
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert 'plugin push' not in capsys.readouterr().out
    assert 'fzf' not in _remote_file(bare)


@needs_git
def test_auto_on_quit_leaves_cli_commands_unpushed(primary, capsys):
    base, _clone, bare, _other = primary
    assert main(base + ['config', 'set', 'primary-push', 'auto-on-quit']) == 0
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert 'not pushed yet' in capsys.readouterr().out                    # the TUI quit pushes it
    assert 'fzf' not in _remote_file(bare)


def test_failures_are_explained_in_plain_words():
    say = lambda t: primarygit.explain_git_failure(t, name='prim', root='/r', source='github:me/prim')
    assert 'SSH key' in say('git@github.com: Permission denied (publickey).\nfatal: Could not read')
    assert 'never connected' in say('Host key verification failed.')
    assert 'signed in' in say("fatal: could not read Username for 'https://github.com': terminal prompts disabled")
    assert "doesn't exist yet" in say('ERROR: Repository not found.')
    assert 'offline' in say('ssh: Could not resolve hostname github.com')
    assert 'again' in say(' ! [rejected]        main -> main (fetch first)')
    assert 'git said "weird"' in say('weird')


def test_the_chip_hides_ahead_under_auto():
    st = {'name': 'prim', 'branch': 'main', 'ahead': 2, 'behind': 1, 'dirty': False}
    assert primarygit.chip(st, hide_ahead=True) == 'prim: ↓1 to sync'
    assert primarygit.chip(dict(st, behind=0), hide_ahead=True) == ''


def test_the_setting_reads_and_defaults(tmp_path):
    from configsys import actions
    assert actions.SETTING_NATURE['primary-push'] == 'uniform'
    assert 'primary-push' in actions.CONFIG_SETTINGS
    from configsys.layers import machine_setting_sections
    assert 'primary-push' in machine_setting_sections()


class _FakeCtx:
    pass


def _quit(monkeypatch, *, ahead, mode, choice=None, push_ok=True):
    st = {'name': 'prim', 'branch': 'main', 'ahead': ahead, 'behind': 0, 'dirty': False}
    monkeypatch.setattr(primarygit, 'state', lambda ctx: st)
    monkeypatch.setattr(primarygit, 'push_mode', lambda ctx: mode)
    calls = []
    monkeypatch.setattr(menu, '_popup_choose', lambda *a, **k: calls.append(a[2]) or choice)
    monkeypatch.setattr(menu, '_push_primary',
                        lambda s, p, c: calls.append('push') or (push_ok, ['pushed 2 changes to x']))
    return calls


def test_quit_asks_to_push(monkeypatch):
    calls = _quit(monkeypatch, ahead=2, mode='ask', choice=0)
    assert menu._quit_push(None, None, _FakeCtx()) == (True, ['pushed 2 changes to x'])
    assert 'not pushed yet' in calls[0] and calls[1] == 'push'
    _quit(monkeypatch, ahead=2, mode='ask', choice=1)
    leave, notes = menu._quit_push(None, None, _FakeCtx())
    assert leave and 'plugin push' in notes[0]
    _quit(monkeypatch, ahead=2, mode='ask', choice=None)                  # esc: keep working
    assert menu._quit_push(None, None, _FakeCtx()) == (False, [])


def test_quit_without_anything_to_push_falls_through_to_the_plain_confirm(monkeypatch):
    _quit(monkeypatch, ahead=0, mode='ask')
    assert menu._quit_push(None, None, _FakeCtx()) == (None, [])
    _quit(monkeypatch, ahead=3, mode='manual')
    assert menu._quit_push(None, None, _FakeCtx()) == (None, [])


def test_quit_under_auto_pushes_and_force_never_stops(monkeypatch):
    calls = _quit(monkeypatch, ahead=1, mode='auto')
    assert menu._quit_push(None, None, _FakeCtx()) == (True, ['pushed 2 changes to x'])
    assert calls == ['push']
    calls = _quit(monkeypatch, ahead=1, mode='auto', push_ok=False)
    assert menu._quit_push(None, None, _FakeCtx())[1][0].startswith('not pushed automatically')
    calls = _quit(monkeypatch, ahead=1, mode='ask')
    leave, notes = menu._quit_push(None, None, _FakeCtx(), force=True)
    assert leave and calls == [] and 'plugin push' in notes[0]


def test_quit_under_auto_on_quit_pushes_even_on_quit_force(monkeypatch):
    for force in (False, True):
        calls = _quit(monkeypatch, ahead=1, mode='auto-on-quit')
        assert menu._quit_push(None, None, _FakeCtx(), force=force) == (True, ['pushed 2 changes to x'])
        assert calls == ['push']
    calls = _quit(monkeypatch, ahead=1, mode='auto')                     # plain auto: Q still just notes
    leave, notes = menu._quit_push(None, None, _FakeCtx(), force=True)
    assert leave and calls == [] and 'plugin push' in notes[0]
    calls = _quit(monkeypatch, ahead=1, mode='auto-on-quit', push_ok=False)
    assert menu._quit_push(None, None, _FakeCtx(), force=True)[1][0].startswith('not pushed automatically')


def test_the_plugins_screen_P_pushes(monkeypatch, tmp_path):
    from configsys.tui.keyspec import Keymap, config_keys
    from configsys.tui.screens.plugins import PluginsScreen
    from _render_harness import build_ctx
    ctx = build_ctx(tmp_path)
    monkeypatch.setattr(menu, '_KEYMAP', Keymap(config_keys(ctx.config)))
    monkeypatch.setattr(menu, '_push_primary', lambda s, p, c: (True, ['left out x', 'pushed 1 change']))
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    scr.model.load_diff = lambda: None
    intent = scr.handle(ord('P'), ctx, None, None)
    assert intent.note == 'pushed 1 change' and intent.pending_notes == ['left out x']
