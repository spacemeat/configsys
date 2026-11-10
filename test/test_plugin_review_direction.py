'''The Plugins review shows which DIRECTION a change goes — never one two-way difference (review.py,
actions.plugin_review). The bug behind it: `git diff HEAD..FETCH_HEAD` showed whatever this machine
had and the remote lacked REVERSED — after `update` re-pinned a plugin in your primary (and configsys
committed that there, ↑1), the primary's review read as if an update would take the ref back down.

Fixture: a primary (`prim`, bare remote + a seed clone standing in for your other machine) whose
manifest declares `configsys-source`, a local plugin repo with tags v0.1.12 and v0.1.13. No network.'''

import shutil
import subprocess

import pytest

from configsys import actions, plugins, review
from configsys.app import Context, build_parser, main
from configsys.runner import Runner

from fakes import git as _git, primary_remote

pytestmark = [pytest.mark.real_runner,
              pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


def _source_repo(tmp_path):
    '''`configsys-source`: a plugin repo tagged v0.1.12, then v0.1.13 (its s.hu changed).'''
    src = tmp_path / 'configsys-source'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: configsys-source  requires-abi: 1  data: [ s.hu ] }\n')
    (src / 's.hu').write_text('{ components: { htop: { install: [ { via: native } ] } } }\n')
    for cmd in (['init', '-q', '-b', 'main'], ['add', '-A'], ['commit', '-qm', 'one'], ['tag', 'v0.1.12']):
        subprocess.run(['git', *cmd], cwd=src, check=True, capture_output=True)
    (src / 's.hu').write_text('{ components: { htop: { install: [ { via: native } { via: flatpak } ] } } }\n')
    for cmd in (['commit', '-qam', 'two'], ['tag', 'v0.1.13']):
        subprocess.run(['git', *cmd], cwd=src, check=True, capture_output=True)
    return src


@pytest.fixture
def world(tmp_path):
    src = _source_repo(tmp_path)
    manifest = ('{ name: prim  requires-abi: 1  data: [ p.hu ]\n'
                f'  plugins: [ {{ source: "{src}"  ref: v0.1.12 }} ]\n}}\n')
    base, clone, bare, other = primary_remote(
        tmp_path, {'plugin.hu': manifest, 'p.hu': '{ picks: { this-machine: [ btop ] } }\n'}, seed='other')
    return base, clone, bare, other, src


def _ctx(base):
    return Context(build_parser().parse_args(base + ['inspect']))


def _review(base, name='prim', remote=None, fetch=True):
    ctx = _ctx(base)
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    decl = plugins.find_decl(eff, ctx.paths.plugins_dir, name)
    row = plugins.status(ctx.paths.plugins_dir, [decl], lock_file=ctx.paths.plugin_lock_file)[0]
    return actions.plugin_review(ctx, decl, row, remote, fetch=fetch)


def _heads(rv):
    return [s.heading(None) for s in rv.sections]


def _one(rv, direction):
    got = [s for s in rv.sections if s.direction == direction]
    assert len(got) <= 1
    return got[0] if got else None


def _diff_lines(section, kind):
    return [t for f in section.files for k, t in f.lines if k == kind]


def _other_pushes(other, rel, text):
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / rel).write_text(text)
    _git(other, 'commit', '-qam', f'edit {rel} elsewhere')
    _git(other, 'push', '-q', 'origin', 'main')


def _update_source(base):
    '''What the user did: `u` on configsys-source — re-pinned in the PRIMARY, committed there (↑1).'''
    assert main(base + ['plugin', 'update', 'configsys-source', '--latest']) == 0


# -- the user's scenario ---------------------------------------------------------------------------

def test_an_unpushed_ref_bump_goes_out_and_nothing_comes_back_down(world):
    base, clone, _bare, _other, _src = world
    _update_source(base)
    assert 'v0.1.13' in (clone / 'plugin.hu').read_text()
    rv = _review(base)
    assert not rv.error
    down, up = _one(rv, review.IN), _one(rv, review.OUT)
    assert down.heading(None) == '↓ nothing new from your other machines' and not down.files
    assert up.heading(None) == '↑ push would share: 1 change'
    assert [f.path for f in up.files] == ['plugin.hu']
    assert any('v0.1.13' in t for t in _diff_lines(up, 'add'))          # forward: v0.1.12 -> v0.1.13
    assert any('v0.1.12' in t for t in _diff_lines(up, 'del'))
    for s in rv.sections:                                                # and NOTHING takes it back
        assert not any('v0.1.12' in t for t in _diff_lines(s, 'add')), s.heading(None)
    assert up.commits and 'plugin update configsys-source --latest' in up.commits[0]
    assert up.files[0].summary == [('change', 'configsys-source: ref v0.1.12 → v0.1.13')]   # in words
    for s in rv.sections:
        assert not any('v0.1.13 → v0.1.12' in t for f in s.files for _k, t in (f.summary or []))
    # the old review's two-way `HEAD..<remote>` diff read this same state backwards (the bug)
    two_way = _git(clone, 'diff', 'HEAD..origin/main')
    assert '+' in two_way and any(ln.startswith('+') and 'v0.1.12' in ln for ln in two_way.splitlines())


def test_behind_only_is_what_your_other_machines_pushed(world):
    base, _clone, _bare, other, _src = world
    _other_pushes(other, 'p.hu', '{ picks: { this-machine: [ btop ]  laptop: [ htop ] } }\n')
    rv = _review(base)
    assert _heads(rv) == ['↓ sync would bring in from your other machines: 1 change']
    assert [f.path for f in rv.sections[0].files] == ['p.hu']
    assert any('laptop' in t for t in _diff_lines(rv.sections[0], 'add'))


def test_diverged_shows_both_sides_and_push_combines(world):
    base, _clone, _bare, other, _src = world
    _update_source(base)
    _other_pushes(other, 'p.hu', '{ picks: { this-machine: [ btop ]  laptop: [ htop ] } }\n')
    rv = _review(base)
    down, up = _one(rv, review.IN), _one(rv, review.OUT)
    assert 'from your other machines: 1 change — push combines them with yours' in down.heading(None)
    assert [f.path for f in down.files] == ['p.hu']                     # theirs, from the merge base
    assert up.heading(None) == '↑ push would share: 1 change'
    assert [f.path for f in up.files] == ['plugin.hu']                  # mine, from the merge base


def test_uncommitted_edits_go_out_as_edits(world):
    base, clone, _bare, _other, _src = world
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  jq ] } }\n')
    (clone / 'notes.txt').write_text('hello\n')
    rv = _review(base)
    up = _one(rv, review.OUT)
    assert up.heading(None) == '↑ edits not committed yet: 2 files — push asks whether to include them'
    assert sorted(f.path for f in up.files) == ['notes.txt', 'p.hu']
    assert rv.sections[0].heading(None) == '↓ nothing new from your other machines'


def test_a_primary_without_a_remote_branch_yet(world):
    base, clone, bare, _other, _src = world
    _git(clone, 'checkout', '-q', '-b', 'work')                          # a branch the remote lacks
    rv = _review(base, fetch=False)
    assert rv.sections[0].heading(None) == '↓ nothing to compare with yet — its remote has no work branch'
    assert _one(rv, review.OUT).heading(None).startswith('↑ push would share: 1 change (its remote has none')


# -- an ordinary synced plugin ----------------------------------------------------------------------

def test_an_ordinary_plugin_with_a_newer_tag(world):
    base, _clone, _bare, _other, _src = world
    rv = _review(base, 'configsys-source', 'v0.1.13')
    assert _heads(rv) == ['↓ update would bring in: v0.1.12 → v0.1.13']
    assert [f.path for f in rv.sections[0].files] == ['s.hu']
    assert any('flatpak' in t for t in _diff_lines(rv.sections[0], 'add'))
    assert _heads(_review(base, 'configsys-source', 'v0.1.12')) == ['↓ up to date — nothing to pull in']


def test_local_work_in_an_ordinary_plugin_is_kept_never_reverted(world):
    base, _clone, _bare, _other, _src = world
    ctx = _ctx(base)
    pdir = ctx.paths.plugins_dir / 'configsys-source'
    (pdir / 'local.hu').write_text('{ }\n')
    rv = _review(base, 'configsys-source', 'v0.1.13')
    assert rv.sections[0].heading(None) == '↓ update would bring in: v0.1.12 → v0.1.13'
    assert _one(rv, review.OUT).heading(None) == ('↑ edited here, not committed: 1 file — a sync or update '
                                                  'keeps your edits (it stops rather than overwrite one)')
    _git(pdir, 'add', 'local.hu')
    _git(pdir, 'commit', '-qm', 'mine')
    head = _git(pdir, 'rev-parse', 'HEAD')
    rv = _review(base, 'configsys-source', 'v0.1.13')
    down, up = _one(rv, review.IN), _one(rv, review.OUT)
    assert [f.path for f in down.files] == ['s.hu']                    # not "local.hu removed"
    assert up.heading(None).startswith('↑ committed here, not on its remote: 1 commit — a sync or update '
                                       'leaves them in place')
    assert [f.path for f in up.files] == ['local.hu'] and 'mine' in up.commits[0]
    # …and it's true: a sync of the tag-pinned plugin stops rather than strand the commit
    decl = {'source': str(_src), 'ref': 'v0.1.13'}
    assert plugins.sync(Runner(pretend=False), ctx.paths.plugins_dir, [decl]) == [('configsys-source', 'kept')]
    assert _git(pdir, 'rev-parse', 'HEAD') == head


# -- not synced: the review cache ------------------------------------------------------------------

def test_an_unsynced_plugin_is_read_from_the_review_cache(world, tmp_path):
    base, _clone, _bare, _other, src = world
    ctx = _ctx(base)
    decl = {'source': str(src)}
    rv = actions.plugin_review(ctx, decl, {'synced': False, 'ref': 'v0.1.12', 'name': 'x'}, 'v0.1.13')
    assert _heads(rv) == ['↓ not synced — update would download v0.1.13; what it changes from your '
                          'declared v0.1.12:']
    assert [f.path for f in rv.sections[0].files] == ['s.hu'] and rv.span == 'v0.1.12 → v0.1.13'
    rv = actions.plugin_review(ctx, decl, {'synced': False, 'ref': 'v0.1.13', 'name': 'x'}, 'v0.1.13')
    assert _heads(rv) == ['↓ not synced — sync would download all of v0.1.13: 2 files']
    rv = actions.plugin_review(ctx, decl, {'synced': False, 'ref': 'v0.1.12', 'name': 'x'}, 'v9')
    assert 'could not fetch v9' in rv.error and not rv.sections


def test_render_names_each_action_its_own_way():
    s = review.Section(review.OUT, '{push} would share: 1 change', commits=['abc123 picks add yq'])
    tui = lambda p: f'{review.ACTIONS[p][1]} ({ {"push": "P"}.get(p, "?") })'   # noqa: E731
    lines = review.render([s], tui)
    assert lines[0] == ('head-out', '↑ push (P) would share: 1 change')
    assert lines[1] == ('commit', '    abc123 picks add yq')
    assert review.render([s], lambda p: '`configsys plugin push`')[0][1] == \
        '↑ `configsys plugin push` would share: 1 change'


# -- the two surfaces print the same sections ------------------------------------------------------

def _pane(base, rv, size=(30, 110), raw=False):
    '''The Plugins screen's review pane for the primary row, as text (BufferSurface).'''
    from _render_harness import RecordingPalette
    from configsys.tui.panes import PluginScreen
    from configsys.tui.screens.plugins import PluginsScreen
    from configsys.tui.surface import BufferSurface
    ctx = _ctx(base)
    pl = PluginScreen(ctx, load=False)
    pl.tree = plugins.declared_tree(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    pl.rows = plugins.status(ctx.paths.plugins_dir, [t['decl'] for t in pl.tree])
    pl.remote = {plugins.dir_name(r['source']): r['ref'] for r in pl.rows}
    pl.cur, pl.focus = 0, 'diff'
    pl.diff_review, pl.diff_span, pl.raw = rv, rv.span, raw
    scr = PluginsScreen(ctx, pl)
    surf = BufferSurface(*size)
    scr.draw(surf, RecordingPalette(), scr.build_vm(ctx, size))
    return surf.text_rows()


def test_the_tui_pane_shows_the_sections_with_their_keys(world):
    base, _clone, _bare, _other, _src = world
    _update_source(base)
    rows = _pane(base, _review(base))
    text = '\n'.join(rows)
    assert 'review · prim · this copy ⇄ main on its remote' in text
    assert '↓ nothing new from your other machines' in text
    assert '↑ push (P) would share: 1 change' in text                  # the key, from the keymap
    assert '  plugin.hu' in text and 'configsys-source: ref v0.1.12 → v0.1.13' in text
    assert 'v0.1.13 → v0.1.12' not in text and 'd: raw diff' in text
    raw = '\n'.join(_pane(base, _review(base), (30, 220), raw=True))      # `d`: the raw diff
    assert '[1/1] ↑ plugin.hu   +3 -1' in raw and 'd: summary' in raw
    assert any(ln.startswith('│+') and 'v0.1.13' in ln for ln in raw.splitlines())


def test_the_cli_prints_the_same_sections(world, capsys):
    base, _clone, _bare, _other, _src = world
    _update_source(base)
    capsys.readouterr()
    assert main(base + ['plugin', 'diff', 'prim']) == 0
    out = capsys.readouterr().out
    assert out.startswith('configsys: prim: this copy ⇄ main on its remote\n')
    assert '\n↓ nothing new from your other machines\n' in out
    assert '\n↑ `configsys plugin push` would share: 1 change\n' in out
    assert '  plugin.hu\n    configsys-source: ref v0.1.12 → v0.1.13\n' in out


def test_pretend_reads_the_primary_as_it_is_and_writes_nothing(world, capsys):
    base, clone, _bare, other, _src = world
    _update_source(base)
    _other_pushes(other, 'p.hu', '{ picks: { this-machine: [ btop ]  laptop: [ htop ] } }\n')
    before = {p: p.stat().st_mtime_ns for p in (clone / '.git').rglob('*') if p.is_file()}
    capsys.readouterr()
    assert main(base + ['--pretend', 'plugin', 'diff', 'prim']) == 0
    out = capsys.readouterr().out
    assert '--pretend fetches nothing' in out
    assert '↓ nothing new from your other machines' in out              # not fetched: not seen yet
    assert '↑ `configsys plugin push` would share: 1 change' in out
    after = {p: p.stat().st_mtime_ns for p in (clone / '.git').rglob('*') if p.is_file()}
    assert after == before


def test_summaries_come_with_each_side(world):
    base, clone, _bare, other, _src = world
    _other_pushes(other, 'p.hu', '{ picks: { this-machine: [ btop ]  laptop: [ htop ] } }\n')
    rv = _review(base)
    assert rv.sections[0].files[0].summary == [('add', 'picks: laptop + htop')]
    rv = _review(base, 'configsys-source', 'v0.1.13')
    assert rv.sections[0].files[0].summary == [('add', 'components.htop.install: added via flatpak')]
    (clone / 'notes.txt').write_text('hi\n')                            # not .hu: one plain line
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop ] }  splash: plain }\n')
    up = _one(_review(base, fetch=False), review.OUT)
    by = {f.path: f for f in up.files}
    assert by['p.hu'].summary == [('add', 'added splash: plain')] and by['notes.txt'].summary is None
    lines = review.render([up], None)
    assert ('add', '    added splash: plain') in lines and ('file', '  notes.txt: new file (1 line)') in lines
    assert ('add', '    +hi') not in lines                                  # its diff: only in the raw view
    raw = review.render([up], None, raw=True)
    assert ('meta', 'diff --git a/p.hu b/p.hu') in raw and ('add', '+hi') in raw


def _plain_repo(tmp_path):
    '''A plugin repo whose v1 -> v2 touches only files with no words: a new script, a changed config,
    a removed file, a changed binary (and one .hu change, in words).'''
    src = tmp_path / 'plain'
    (src / 'dotfiles' / 'x.cfs').mkdir(parents=True)
    (src / 'bin').mkdir()
    (src / 'plugin.hu').write_text('{ name: plain  requires-abi: 1  data: [ p.hu ] }\n')
    (src / 'p.hu').write_text('{ splash: plain }\n')
    (src / 'old.sh').write_text('echo old\n')
    (src / 'dotfiles' / 'x.cfs' / 'config').write_text('a\nb\nc\n')
    (src / 'bin' / 'tool').write_bytes(b'\x00\x01\x02 v1')
    for cmd in (['init', '-q', '-b', 'main'], ['add', '-A'], ['commit', '-qm', 'one'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True, capture_output=True)
    (src / 'p.hu').write_text('{ splash: braille-bar }\n')
    (src / 'old.sh').unlink()
    (src / 'glue' / 'shell' / 'bash').mkdir(parents=True)
    (src / 'glue' / 'shell' / 'bash' / 'foo.sh').write_text(''.join(f'alias f{i}=foo\n' for i in range(12)))
    (src / 'dotfiles' / 'x.cfs' / 'config').write_text('a\nB\nc\nd\ne\n')
    (src / 'bin' / 'tool').write_bytes(b'\x00\x01\x02 v2')
    for cmd in (['add', '-A'], ['commit', '-qm', 'two'], ['tag', 'v2']):
        subprocess.run(['git', *cmd], cwd=src, check=True, capture_output=True)
    return src


def test_a_file_with_no_words_is_one_plain_line_never_a_diff(tmp_path):
    from configsys.runner import Runner
    src = _plain_repo(tmp_path)
    repo, b, t, err = plugins.review_fetch(Runner(pretend=False), tmp_path / 'cache', {'source': str(src)}, 'v1', 'v2')
    rv = review.unsynced(repo, b, t, base_ref='v1', to='v2')
    texts = [t for _k, t in review.render(rv.sections, None)]
    assert texts == ['↓ not synced — update would download v2; what it changes from your declared v1:',
                     '  bin/tool: binary file changed',
                     '  dotfiles/x.cfs/config: changed (+3 −1 lines)',
                     '  glue/shell/bash/foo.sh: new file (12 lines)',
                     '  old.sh: removed',
                     '  p.hu',
                     '    splash: plain → braille-bar']
    raw = review.render(rv.sections, None, raw=True)                   # `d` / --raw: the full diffs
    assert ('add', '+alias f0=foo') in raw and ('del', '-echo old') in raw and ('add', '+B') in raw
    assert review.in_a_line(review.File('x', [('meta', 'old mode 100644'), ('meta', 'new mode 100755')])) == \
        'x: file mode changed'


# -- where an action landed --------------------------------------------------------------------------

def test_update_says_it_landed_in_your_primary_not_pushed_yet(world, capsys):
    base, _clone, _bare, _other, _src = world
    capsys.readouterr()
    _update_source(base)
    out = capsys.readouterr().out
    assert 'configsys: configsys-source updated to v0.1.13 (latest tag)\n' in out
    assert ('configsys: recorded in your primary (prim) — 1 change not pushed yet; `configsys plugin push` '
            'shares it.') in out


@pytest.mark.parametrize('mode, cli, tui', [
    ('ask', 'recorded in your primary (prim) — 2 changes not pushed yet; `configsys plugin push` shares them.',
     'recorded in your primary (prim), not pushed yet (P)'),
    ('auto', 'recorded in your primary (prim) — pushing it now (primary-push: auto)',
     'recorded in your primary (prim) — pushed when you quit'),
    ('auto-on-quit', 'recorded in your primary (prim) — 2 changes not pushed yet; `configsys plugin push` '
                     'shares them, or quitting the TUI does.',
     'recorded in your primary (prim) — pushed when you quit'),
    ('manual', 'recorded in your primary (prim).', 'recorded in your primary (prim)'),
])
def test_one_wording_for_where_it_landed_by_push_mode(monkeypatch, mode, cli, tui):
    from configsys import primarygit
    monkeypatch.setattr(primarygit, 'push_mode', lambda ctx: mode)
    monkeypatch.setattr(primarygit, 'state', lambda ctx: primarygit.PrimaryState('prim', 'main', ahead=2))
    assert primarygit.landed(object(), 'prim', tui=False) == cli
    assert primarygit.landed(object(), 'prim', tui=True, push_key='P') == tui


def test_the_tui_note_after_u_says_where_it_landed(world, monkeypatch):
    from contextlib import nullcontext
    from configsys import primarygit
    from configsys.tui import flows, menu
    from configsys.tui.panes import PluginScreen
    from configsys.tui.screens import plugins as pmod
    base, _clone, _bare, _other, _src = world
    ctx = _ctx(base)
    monkeypatch.setattr(pmod, 'suspended', lambda _s: nullcontext())
    monkeypatch.setattr(PluginScreen, '_start_remote', lambda self: None)   # no ls-remote thread
    scr = pmod.PluginsScreen(ctx)
    scr.model.cur = next(i for i, r in enumerate(scr.model.rows) if r['name'] == 'configsys-source')
    u = next(k for k in range(32, 127) if menu._keymap().action_for('plugins', k) == 'update')
    snap = primarygit.snapshot(ctx)                     # the router's per-key write journal
    intent = scr.handle(u, ctx, None, None)
    cnotes = flows._commit_primary_action(ctx, snap, 'plugins', 'update', intent.note)
    note = flows._after_primary_action(ctx, snap, intent.note, cnotes)
    assert note == ('configsys-source updated to v0.1.13 (latest tag) — recorded in your primary (prim), '
                    'not pushed yet (P)')


# -- CLI parity: --raw, and the push preview shows the same ↑ ------------------------------------

def test_plugin_diff_raw_prints_the_unified_diffs(world, capsys):
    base, _clone, _bare, _other, _src = world
    _update_source(base)
    capsys.readouterr()
    assert main(base + ['plugin', 'diff', 'prim', '--raw']) == 0
    out = capsys.readouterr().out
    assert '\n↑ `configsys plugin push` would share: 1 change\n' in out
    assert '\ndiff --git a/plugin.hu b/plugin.hu\n' in out and '\n+  plugins: [\n' in out
    assert 'configsys-source: ref v0.1.12 → v0.1.13' not in out


def test_the_push_preview_and_its_question_show_what_goes_out_in_words(world, capsys):
    from configsys import primarygit
    base, _clone, bare, _other, _src = world
    _update_source(base)
    capsys.readouterr()
    assert main(base + ['--pretend', 'plugin', 'push']) == 0
    out = capsys.readouterr().out
    assert '[pretend] would push 1 change to' in out
    assert '[pretend]     ' in out and 'plugin update configsys-source --latest' in out
    assert '[pretend]   plugin.hu\n' in out and '[pretend]     configsys-source: ref v0.1.12 → v0.1.13\n' in out

    asked = []

    class UI(primarygit.PushUI):
        def ask(self, q):
            asked.append(q)
            return False if q.kind == 'confirm-push' else q.unattended
    ok, _lines = primarygit.push(_ctx(base), UI())
    q = next(q for q in asked if q.kind == 'confirm-push')
    listing = q.listing()
    assert any('plugin update configsys-source --latest' in ln for ln in listing)
    assert '  plugin.hu' in listing and '    configsys-source: ref v0.1.12 → v0.1.13' in listing
    assert not ok and 'v0.1.13' not in _git(bare, 'show', 'main:plugin.hu')     # "don't push": nothing sent


def test_a_brace_in_a_ref_is_just_text_in_a_title():
    s = review.Section(review.IN, '{update} would bring in: v1 → feat{x}')   # git allows `{` in a ref
    assert s.heading(None) == '↓ update would bring in: v1 → feat{x}'


def test_a_tag_pinned_primary_is_reviewed_like_any_synced_plugin(world, capsys):
    base, clone, _bare, _other, _src = world
    _git(clone, 'checkout', '-q', '--detach', 'HEAD')                       # pinned: not on its branch
    capsys.readouterr()
    assert main(base + ['plugin', 'diff', 'prim']) == 0
    assert '↓ up to date — nothing to pull in' in capsys.readouterr().out
