'''Primary-push plan, phase 3 (docs/done/primary-push-plan.md): `configsys plugin push` commits, combines
with what your other machines pushed (asking per file when both changed the same lines), and pushes to
the primary's branch — never leaving a half-done rebase, never sweeping in your hand edits unasked —
plus the `primary-push: ask | auto | auto-on-quit | manual` setting and the TUI's quit prompt and `P` key.'''

import dataclasses
import shutil
import subprocess

import pytest

from configsys import plugins, primarygit
from configsys.app import Context, build_parser, main
from configsys.tui import menu
from configsys.tui import flows as flows_mod

from fakes import BASE_P, git as _git           # the `primary` fixture is conftest's

pytestmark = pytest.mark.real_runner  # real git clones/commits in tmp dirs (conftest)

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')

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
                 raise_on=None, confirm=True):
        self.choice, self.include, self.switch, self.edit_to = choice, include, switch, edit_to
        self.overlap, self.raise_on = overlap, raise_on      # raise_on: an exception for a resolve
        self.confirm = confirm
        self.asked, self.confirms = [], []                 # confirms: the "push these?" questions

    def ask(self, q):
        if q.kind == 'confirm-push':
            self.confirms.append((q.items, q.files))
            return self.confirm
        if q.kind == 'overlap':
            self.asked.append(('overlap', q.items))
            return self.overlap
        if q.kind == 'include-own':
            self.asked.append(('include', q.items))
            return self.include
        if q.kind == 'switch-branch':
            self.asked.append(('switch', q.ref, q.branch))
            return self.switch
        self.asked.append(('value' if q.kind == 'value' else 'resolve', q.path, q.detail))
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
    assert primarygit.state(_ctx(base)).ahead == 0
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
    st = primarygit.PrimaryState('prim', 'main', ahead=2, behind=1)
    assert primarygit.chip(st, hide_ahead=True) == 'prim: ↓1 to sync'
    assert primarygit.chip(dataclasses.replace(st, behind=0), hide_ahead=True) == ''


def test_the_setting_reads_and_defaults(tmp_path):
    from configsys import actions
    assert actions.SETTING_NATURE['primary-push'] == 'uniform'
    assert 'primary-push' in actions.CONFIG_SETTINGS
    from configsys.layers import machine_setting_sections
    assert 'primary-push' in machine_setting_sections()



def test_a_push_mode_it_doesnt_take_is_refused_and_flagged(tmp_path, capsys):
    # D2 / primary-27: `config set primary-push autoo` used to save it and silently mean `ask`
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    assert main(base + ['config', 'set', 'primary-push', 'autoo']) == 1
    assert 'takes one of ask, auto, auto-on-quit, manual' in capsys.readouterr().err
    assert main(base + ['config', 'set', 'primary-push', 'Auto']) == 0      # case doesn't matter
    assert 'primary-push: auto' in (home / '.config' / 'configsys' / 'configsys.hu').read_text()
    cfg = home / '.config' / 'configsys' / 'configsys.hu'
    cfg.write_text(cfg.read_text().replace('primary-push: auto', 'primary-push: sometimes'))
    capsys.readouterr()
    main(base + ['check'])
    assert '`primary-push: sometimes` is not one of ask, auto, auto-on-quit, manual' in capsys.readouterr().out


def test_every_push_mode_has_a_policy():
    assert set(primarygit.PUSH_POLICY) == set(primarygit.PUSH_MODES)
    for rules in primarygit.PUSH_POLICY.values():
        assert set(rules) == {'after_cli', 'quit', 'quit_force', 'hide_ahead'}


class _FakeCtx:
    pass


def _quit(monkeypatch, *, ahead, mode, choice=None, push_ok=True):
    st = primarygit.PrimaryState('prim', 'main', ahead=ahead)
    monkeypatch.setattr(primarygit, 'state', lambda ctx: st)
    monkeypatch.setattr(primarygit, 'push_mode', lambda ctx: mode)
    calls = []
    monkeypatch.setattr(flows_mod, '_popup_choose', lambda *a, **k: calls.append(a[2]) or choice)
    push = lambda s, p, c: calls.append('push') or (push_ok, ['pushed 2 changes to x'])  # noqa: E731
    monkeypatch.setattr(flows_mod, '_push_primary', push)
    monkeypatch.setattr(flows_mod, '_auto_push_primary', push)
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
    from configsys.tui.keyspec import Keymap
    from configsys.tui.screens.plugins import PluginsScreen
    from _render_harness import build_ctx
    ctx = build_ctx(tmp_path)
    monkeypatch.setattr(menu, '_KEYMAP', Keymap(ctx.config.keys()))
    monkeypatch.setattr(flows_mod, '_push_primary', lambda s, p, c: (True, ['left out x', 'pushed 1 change']))
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    scr.model.load_diff = lambda: None
    intent = scr.handle(ord('P'), ctx, None, None)
    assert intent.note == 'pushed 1 change' and intent.pending_notes == ['left out x']


@pytest.mark.parametrize('kind', sorted(primarygit.QUESTIONS))
def test_every_question_renders_the_same_choices_on_both_uis(kind, monkeypatch, capsys):
    # F1: one Question, one choice table — the CLI and the TUI can't drift apart in wording or keys,
    # and Enter / Esc / no terminal always give the question's own cautious answers
    from configsys.app import _CliPushUI
    from configsys.tui import menu
    q = primarygit.question(kind, name='prim', items=['a\x1b[2Jb'], files=['f'], path='p.hu',
                            detail='what', ref='v1', branch='main', source='github:me/prim')
    keys = [c.key for c in q.choices]
    assert len(set(keys)) == len(keys) and q.enter in [c.answer for c in q.choices]
    assert '\x1b' not in q.title + ''.join(q.listing())                 # A5: made safe once, here
    assert primarygit.PushUI().ask(q) == q.unattended
    cli = _CliPushUI()
    cli.interactive = True
    shown = []
    monkeypatch.setattr('builtins.input', lambda prompt: shown.append(prompt) or '')
    assert cli.ask(q) == q.enter
    for c in q.choices:
        assert f'[{c.key}] {c.label}' in shown[0]
        monkeypatch.setattr('builtins.input', lambda prompt, k=c.key: k)
        assert cli.ask(q) == c.answer
    capsys.readouterr()
    popups = []
    monkeypatch.setattr(flows_mod, '_popup_choose', lambda *a, **k: popups.append((a[3], k)) or None)
    assert menu._TuiPushUI(None, None).ask(q) == q.enter                # Esc
    options, kw = popups[0]
    assert options == [(c.label, c.key) for c in q.choices]
    assert q.choices[kw['start']].answer == q.enter


def _other_makes_a_link(other, path, target):
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / path).unlink()
    (other / path).symlink_to(target)
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', f'other: {path} -> link')
    _git(other, 'push', '-q', 'origin', 'main')


@needs_git
@pytest.mark.parametrize('choice', ['mine', 'theirs'])
def test_a_type_change_is_described_and_settled_as_one_file(primary, choice):
    # B17 / primary-26: the remote turned notes.txt into a symlink while this machine edited it. It
    # was asked as "this machine deleted it" plus a second question about `notes.txt~HEAD`, and
    # "keep mine" pushed a tree holding `notes.txt~HEAD`
    base, clone, bare, other = primary
    _other_makes_a_link(other, 'notes.txt', 'p.hu')
    (clone / 'notes.txt').write_text(BASE_P + '// mine\n')
    _git(clone, 'commit', '-qam', 'mine: notes')
    ui = Scripted(choice)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    asked = [a for a in ui.asked if a[0] == 'resolve']
    assert len(asked) == 1 and asked[0][1] == 'notes.txt', ui.asked
    assert 'link' in asked[0][2] and 'deleted' not in asked[0][2]
    tree = _git(bare, 'ls-tree', '--name-only', 'main').split()
    assert sorted(tree) == ['notes.txt', 'p.hu', 'plugin.hu'], tree       # no `notes.txt~HEAD`
    mode = _git(bare, 'ls-tree', 'main', 'notes.txt').split()[0]
    assert mode == ('100644' if choice == 'mine' else '120000')
    if choice == 'mine':
        assert _remote_file(bare, 'notes.txt').endswith('// mine')
    _clean(clone)


@needs_git
@pytest.mark.parametrize('choice', ['mine', 'theirs'])
def test_a_file_that_became_a_folder_is_one_question(primary, choice):
    # B17's other shape: the remote replaced notes.txt with a folder while this machine edited it
    base, clone, bare, other = primary
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / 'notes.txt').unlink()
    (other / 'notes.txt').mkdir()
    (other / 'notes.txt' / 'a').write_text('in a folder\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'other: folder'); _git(other, 'push', '-q', 'origin', 'main')
    (clone / 'notes.txt').write_text(BASE_P + '// mine\n')
    _git(clone, 'commit', '-qam', 'mine: notes')
    ui = Scripted(choice)
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    asked = [a for a in ui.asked if a[0] == 'resolve']
    assert len(asked) == 1 and asked[0][1] == 'notes.txt' and 'folder' in asked[0][2], ui.asked
    tree = _git(bare, 'ls-tree', '-r', '--name-only', 'main').split()
    assert not any('~' in t for t in tree), tree
    assert ('notes.txt' in tree) == (choice == 'mine') and ('notes.txt/a' in tree) == (choice == 'theirs')
    _clean(clone)


# -- G2: seeing and undoing configsys's own commits -------------------------------------------

@needs_git
def test_plugin_log_marks_unpushed_and_configsys_made(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    capsys.readouterr()
    assert main(base + ['plugin', 'log']) == 0
    out = capsys.readouterr().out
    assert '↑* ' in out and 'picks add fzf' in out and '[p.hu]' in out
    assert '`configsys plugin undo` takes back' in out
    first = next(ln for ln in out.splitlines() if ' A' in ln and 'picks' not in ln)
    assert first.lstrip().startswith(tuple('0123456789abcdef'))         # pushed, not configsys's: no marks


@needs_git
def test_undo_drops_an_unpushed_change(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    head = _git(clone, 'rev-parse', 'HEAD~1')
    assert main(base + ['plugin', 'undo', '--yes']) == 0
    assert 'never pushed, so it is simply gone' in capsys.readouterr().out
    assert _git(clone, 'rev-parse', 'HEAD') == head and 'fzf' not in (clone / 'p.hu').read_text()
    _clean(clone)


@needs_git
def test_undo_reverts_a_pushed_change_and_undo_again_redoes_it(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert main(base + ['plugin', 'push', '--yes']) == 0
    assert main(base + ['plugin', 'undo', '--yes']) == 0
    assert _git(clone, 'log', '-1', '--format=%s') == 'Undo: picks add fzf'
    assert 'fzf' not in (clone / 'p.hu').read_text()
    assert main(base + ['plugin', 'undo', '--yes']) == 0                # the undo is itself undoable
    assert 'fzf' in (clone / 'p.hu').read_text()
    _clean(clone)


@needs_git
def test_undo_never_takes_back_your_own_commits_or_edits(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    (clone / 'notes.txt').write_text('mine\n')
    _git(clone, 'commit', '-qam', 'my own commit')
    (clone / 'p.hu').write_text((clone / 'p.hu').read_text() + '// typing\n')
    capsys.readouterr()
    assert main(base + ['plugin', 'undo', '--yes']) == 1                # your edit to its file: refused
    assert 'uncommitted edits (p.hu)' in capsys.readouterr().out
    _git(clone, 'checkout', '-q', '--', 'p.hu')
    assert main(base + ['plugin', 'undo', '--yes']) == 0                # reverts the configsys one …
    assert (clone / 'notes.txt').read_text() == 'mine\n'                # … never yours
    assert _git(clone, 'log', '-1', '--format=%s') == 'Undo: picks add fzf'


@needs_git
def test_undo_under_pretend_changes_nothing(primary, capsys):
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    head = _git(clone, 'rev-parse', 'HEAD')
    capsys.readouterr()
    assert main(base + ['--pretend', 'plugin', 'undo', '--yes']) == 0
    assert '[pretend] would drop' in capsys.readouterr().out
    assert _git(clone, 'rev-parse', 'HEAD') == head


@needs_git
def test_the_plugins_screen_history_key_undoes(primary, monkeypatch):
    from configsys.tui.screens import plugins as plugscreen
    base, clone, bare, other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    ctx = _ctx(base)
    shown = []
    monkeypatch.setattr(menu, '_popup_choose', lambda *a, **k: shown.append((a[2], a[3])) or 0)
    note, undone = plugscreen._history(None, None, ctx, menu.PluginScreen(ctx))
    assert shown[0][1][0] == ('Undo "picks add fzf"', 'z')
    assert 'undid "picks add fzf"' in note and 'fzf' not in (clone / 'p.hu').read_text()
    assert undone                                      # primary-16: the screens rebuild after an undo


@needs_git
def test_an_editor_backup_beside_its_file_is_an_ordinary_conflict(primary):
    # B17 / primary-09: a real `notes.txt~` (an editor backup a capture swept in) conflicting next to
    # `notes.txt` was read as git's type-change rename — one nonsense question, `notes.txt~` deleted
    base, clone, bare, other = primary
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / 'notes.txt~').write_text('backup v0\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'other: backup'); _git(other, 'push', '-q', 'origin', 'main')
    _git(clone, 'pull', '-q', '--rebase', 'origin', 'main')
    _other_pushes(other, 'notes.txt', 'theirs notes\n')
    (other / 'notes.txt~').write_text('backup theirs\n')
    _git(other, 'commit', '-qam', 'other: backup again'); _git(other, 'push', '-q', 'origin', 'main')
    (clone / 'notes.txt').write_text('mine notes\n')
    (clone / 'notes.txt~').write_text('backup mine\n')
    _git(clone, 'commit', '-qam', 'mine: both')
    ui = Scripted('mine')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    asked = [a for a in ui.asked if a[0] == 'resolve']
    assert sorted(a[1] for a in asked) == ['notes.txt', 'notes.txt~'], ui.asked
    tree = _git(bare, 'ls-tree', '--name-only', 'main').split()
    assert 'notes.txt~' in tree and 'notes.txt' in tree
    _clean(clone)


@needs_git
def test_a_locked_primary_is_never_combined_with_what_its_remote_holds(primary):
    # review-2026-11-2 A12: the lock held back the other machine's commits on sync, but `push`
    # rebased onto them anyway (and `primary-push: auto` did it on any edit)
    from configsys import plugins
    base, clone, bare, other = primary
    ctx = _ctx(base)
    plugins.set_lock(ctx.paths.plugin_lock_file, 'prim', '2026-11-08')
    _other_pushes(other, 'notes.txt', BASE_P + '// ALARMING\n')
    (clone / 'p.hu').write_text(BASE_P.replace('desk: [ jq ]', 'desk: [ jq fzf ]'))
    _git(clone, 'commit', '-qam', 'mine')
    ok, lines = primarygit.push(_ctx(base), Scripted('mine'))
    assert not ok and any('is locked' in ln for ln in lines), lines
    assert 'ALARMING' not in (clone / 'notes.txt').read_text()


@needs_git
def test_a_dirty_tree_git_cannot_stash_never_pops_your_older_stash(primary, monkeypatch):
    # A13 / primary-06: a submodule with untracked content reads dirty (` M sub`) but `stash push`
    # saves nothing — `_combine` then popped stash@{0}: YOUR parked work, applied and dropped
    base, clone, bare, other = primary
    (clone / 'notes.txt').write_text(BASE_P + '// my parked WIP\n')
    _git(clone, 'stash', 'push', '-q', '-m', 'my parked WIP')
    _other_pushes(other, 'p.hu', BASE_P.replace('laptop: [ htop ]', 'laptop: [ htop bat ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('desk: [ jq ]', 'desk: [ jq fzf ]'))
    _git(clone, 'commit', '-qam', 'mine')
    monkeypatch.setattr(primarygit.PrimaryRepo, 'dirty', lambda self: {'vendor/thing'})
    ok, lines = primarygit.push(_ctx(base), Scripted('mine'))
    assert ok, lines
    assert 'my parked WIP' in _git(clone, 'stash', 'list')
    assert 'parked WIP' not in (clone / 'notes.txt').read_text()


@needs_git
@pytest.mark.parametrize('choice', ['stop', 'mine'])
def test_an_ignored_file_the_remote_now_tracks_is_never_lost(primary, choice):
    # A13 / primary-03: a secret kept out of git by a .gitignore here; the other machine drops the
    # ignore and commits its own copy. "Stop" deleted ours ("not in HEAD"), continuing replaced it.
    base, clone, bare, other = primary
    (clone / '.gitignore').write_text('secret.env\n')
    _git(clone, 'add', '.gitignore'); _git(clone, 'commit', '-qm', 'ignore secret')
    _git(clone, 'push', '-q', 'origin', 'main')
    (clone / 'secret.env').write_text('MY SECRET\n')
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / '.gitignore').write_text('')
    (other / 'secret.env').write_text('OTHER MACHINE\n')
    (other / 'notes.txt').write_text('theirs\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'other'); _git(other, 'push', '-q', 'origin', 'main')
    (clone / 'notes.txt').write_text('mine\n')
    _git(clone, 'commit', '-qam', 'mine')
    ok, lines = primarygit.push(_ctx(base), Scripted(choice))
    if choice == 'stop':
        assert not ok and (clone / 'secret.env').read_text() == 'MY SECRET\n'
    else:
        assert ok, lines
        assert (clone / 'secret.env.pre-configsys').read_text() == 'MY SECRET\n'
        assert any('kept as secret.env.pre-configsys' in ln for ln in lines)


@needs_git
def test_undo_of_a_commit_that_added_files_saves_them_first(primary, capsys):
    # A13 / primary-08: undoing `plugin init` (files MOVED in) deleted the only copy
    from configsys import primarygit as pg
    base, clone, bare, other = primary
    ctx = _ctx(base)
    snap = pg.snapshot(ctx)
    pg.will_write(clone / 'dotfiles' / 'foo.cfs' / 'foo.conf')
    (clone / 'dotfiles' / 'foo.cfs').mkdir(parents=True)
    (clone / 'dotfiles' / 'foo.cfs' / 'foo.conf').write_text('only copy\n')
    pg.commit(ctx, snap, 'plugin init')
    ok, lines = pg.undo(_ctx(base))
    assert ok, lines
    saved = ctx.paths.state_dir / 'undo'
    hits = list(saved.rglob('foo.conf'))
    assert hits and hits[0].read_text() == 'only copy\n'
    assert any('saved in' in ln for ln in lines)


@needs_git
def test_signed_only_push_warns_that_its_own_commits_are_unsigned(primary):
    # G5 / primary-21: other verifying machines would refuse them
    base, clone, bare, other = primary
    ctx = _ctx(base)
    top = ctx.paths.user_config_file
    top.write_text(top.read_text().rstrip().rstrip('}') + '  primary-verify: signed }\n')
    (clone / 'p.hu').write_text(BASE_P.replace('desk: [ jq ]', 'desk: [ jq fzf ]'))
    _git(clone, 'commit', '-qam', 'mine')
    seen = []

    class UI(primarygit.PushUI):
        def ask(self, q):
            if q.kind == 'confirm-push':
                seen.append(q.title)
                return False
            return q.unattended
    primarygit.push(_ctx(base), UI())
    assert seen and 'not signed' in seen[0], seen


@needs_git
def test_history_names_the_machine_a_change_was_made_on(primary):
    # G5 / primary-20: undo's confirm can say "made on desk, not this machine"
    base, clone, bare, other = primary
    ctx = _ctx(base)
    top = ctx.paths.user_config_file
    top.write_text(top.read_text().rstrip().rstrip('}') + '  machine: desk }\n')
    assert main(base + ['picks', 'add', 'fzf']) == 0
    _name, changes = primarygit.history(_ctx(base), 5)
    newest = next(c for c in changes if c.by_configsys)
    assert newest.machine == 'desk'


# -- review-2026-11-2 primary-11 / -12 / -13 / -16 -----------------------------------------------

def test_driver_notes_from_the_remote_are_made_safe(tmp_path):
    # primary-11: notes carry remote file names and plugin refs — an OSC / colour escape goes out as text
    notes = tmp_path / 'notes'
    notes.write_text('both machines moved plugin github:x/y — kept the newer, v1\x1b]0;T\x07.\n'
                     'a\x1b[31m.hu: both machines changed it — combined key by key.\n')
    got = primarygit._driver_notes(notes)
    assert len(got) == 2 and not any('\x1b' in ln or '\x07' in ln for ln in got)
    assert '\\x1b]0;T\\x07' in got[0]


@needs_git
def test_a_conflicted_file_name_from_the_remote_is_made_safe(primary):
    # primary-11: "combined — <files> settled as you chose" names files the remote chose
    base, clone, bare, other = primary
    odd = 'esc\x1b[31mred.txt'
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / odd).write_text('theirs\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'other: odd'); _git(other, 'push', '-q', 'origin', 'main')
    (clone / odd).write_text('mine\n')
    _git(clone, 'add', '-A'); _git(clone, 'commit', '-qm', 'mine: odd')
    ok, lines = primarygit.push(_ctx(base), Scripted('mine'))
    assert ok, lines
    assert any('settled as you chose' in ln for ln in lines)
    assert not any('\x1b' in ln for ln in lines)


@needs_git
def test_a_combine_that_absorbs_every_change_pushes_nothing_and_asks_nothing(primary):
    # primary-12: both machines made the same change — the rebase drops mine; no "push 0 changes?"
    base, clone, bare, other = primary
    same = BASE_P.replace('[ jq ]', '[ jq  yq ]')
    _other_pushes(other, 'p.hu', same)
    (clone / 'p.hu').write_text(same)
    _git(clone, 'commit', '-qam', 'mine: the same')
    ui = Scripted()
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok and 'nothing left to push' in lines[-1]
    assert ui.confirms == []
    assert _git(clone, 'rev-parse', 'HEAD') == _git(bare, 'rev-parse', 'main')
    _clean(clone)


def test_auto_push_after_a_cli_command_shows_every_line(monkeypatch, capsys):
    # primary-12: under auto, "kept the newer" / "left out" notes were dropped — only the last line showed
    from configsys.cli import plugin as cli_plugin
    monkeypatch.setattr(primarygit, 'push_mode', lambda ctx: 'auto')
    monkeypatch.setattr(primarygit, 'push', lambda ctx: (True, [
        'prim: both machines moved plugin github:me/blender — kept the newer, v0.3.0.', 'pushed 1 change to x']))
    cli_plugin._after_primary_commit(_FakeCtx())
    out = capsys.readouterr().out
    assert 'kept the newer, v0.3.0' in out and 'pushed 1 change' in out
    monkeypatch.setattr(primarygit, 'push', lambda ctx: (False, ['prim: 1 file left out', 'offline?']))
    cli_plugin._after_primary_commit(_FakeCtx())
    out = capsys.readouterr().out.splitlines()
    assert out == ['configsys: prim: 1 file left out', 'configsys: not pushed automatically — offline?']


def test_quit_under_auto_keeps_the_drivers_notes(monkeypatch):
    _quit(monkeypatch, ahead=1, mode='auto')
    monkeypatch.setattr(flows_mod, '_auto_push_primary', lambda s, p, c: (True, ['kept the newer, v2', 'pushed']))
    assert menu._quit_push(None, None, _FakeCtx()) == (True, ['kept the newer, v2', 'pushed'])


@needs_git
def test_dont_push_after_a_combine_puts_head_back(primary):
    # primary-13 (decided: "don't push" after a combine puts HEAD back) — declining must not leave the
    # other machine's commits checked out here, unannounced
    base, clone, bare, other = primary
    _other_pushes(other, 'notes.txt', BASE_P.replace('[ btop ]', '[ btop  zsh ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(clone, 'commit', '-qam', 'mine')
    (clone / 'mine-only.txt').write_text('untracked, mine\n')
    head = _git(clone, 'rev-parse', 'HEAD')
    ok, lines = primarygit.push(_ctx(base), Scripted(confirm=False))
    assert not ok and 'not combined in' in lines[-1]
    assert _git(clone, 'rev-parse', 'HEAD') == head
    assert 'zsh' not in (clone / 'notes.txt').read_text() and 'yq' in (clone / 'p.hu').read_text()
    assert (clone / 'mine-only.txt').read_text() == 'untracked, mine\n'
    assert 'yq' not in _remote_file(bare)
    ok, lines = primarygit.push(_ctx(base), Scripted())                # and it combines again next time
    assert ok and 'yq' in _remote_file(bare) and 'zsh' in _remote_file(bare, 'notes.txt')


def test_the_plugins_screen_P_rebuilds_after_a_combine(monkeypatch, tmp_path):
    # primary-16: a push that combined the other machine's picks left Components / Profiles stale
    from configsys.tui.keyspec import Keymap
    from configsys.tui.screens.plugins import PluginsScreen
    from _render_harness import build_ctx
    ctx = build_ctx(tmp_path)
    monkeypatch.setattr(menu, '_KEYMAP', Keymap(ctx.config.keys()))
    heads = iter(['aaa', 'bbb'])
    monkeypatch.setattr(primarygit, 'head', lambda c: next(heads))
    invalidated = []
    monkeypatch.setattr(ctx, 'invalidate', lambda: invalidated.append(1), raising=False)
    monkeypatch.setattr(flows_mod, '_push_primary', lambda s, p, c: (True, ['pushed 1 change']))
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    scr.model.load_diff = lambda: None
    intent = scr.handle(ord('P'), ctx, None, None)
    assert intent.dirty and invalidated
    monkeypatch.setattr(primarygit, 'head', lambda c: 'same')        # nothing moved: nothing rebuilt
    invalidated.clear()
    intent = scr.handle(ord('P'), ctx, None, None)
    assert not intent.dirty and not invalidated
