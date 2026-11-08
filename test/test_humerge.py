'''Primary-push plan, phase 4 (docs/done/primary-push-plan.md): a `.hu`-aware three-way merge. Two
machines editing their own picks column, bumping the same plugin, or changing different settings is
no conflict; a real disagreement is asked about per key, in plain words — checked on the merge itself,
as git's merge driver, and end to end through `plugin push` between two sandbox clones.'''

import shutil
import subprocess
import sys

import pytest

from configsys import humerge, layers, primarygit

from test_primary_push import BASE_P, Scripted, _clean, _ctx, _git, _other_pushes, _remote_file, primary  # noqa: F401

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')

BASE = '''// my primary
{
    // what each machine picks
    picks: {
        desk: [ btop fzf ]
        laptop: [ htop ]
    }
    splash: ocean           // the startup animation
    pins: { python3: native }
    plugins: [
        { source: "github:me/blender"  ref: v0.1.0 }
    ]
}
'''


def _data(text):
    return layers.materialize_string(text)


def test_each_machine_edits_its_own_column():
    mine = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop fzf ripgrep ]')
    theirs = BASE.replace('laptop: [ htop ]', 'laptop: [ htop bat ]')
    r = humerge.merge(BASE, mine, theirs)
    assert r.conflicts == [] and r.notes == []
    assert _data(r.text)['picks'] == {'desk': ['btop', 'fzf', 'ripgrep'], 'laptop': ['htop', 'bat']}
    assert '// what each machine picks' in r.text and '// the startup animation' in r.text


def test_both_change_one_column_adds_and_removes_combine():
    mine = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop fzf ripgrep ]')
    theirs = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop jq ]')          # dropped fzf, added jq
    r = humerge.merge(BASE, mine, theirs)
    assert r.conflicts == []
    assert _data(r.text)['picks']['desk'] == ['btop', 'ripgrep', 'jq']


def test_a_new_column_and_a_new_setting_from_theirs_keep_their_text():
    theirs = BASE.replace('laptop: [ htop ]', 'laptop: [ htop ]\n        tv: [ mpv ]  // the den').replace(
        '    pins:', '    effects: reduced\n    pins:')
    mine = BASE.replace('splash: ocean', 'splash: plain')
    r = humerge.merge(BASE, mine, theirs)
    assert r.conflicts == []
    d = _data(r.text)
    assert d['picks']['tv'] == ['mpv'] and d['effects'] == 'reduced' and d['splash'] == 'plain'
    assert '// the den' in r.text


def test_a_real_scalar_conflict_is_asked_in_plain_words():
    mine, theirs = BASE.replace('ocean', 'plain'), BASE.replace('ocean', 'blocks')
    r = humerge.merge(BASE, mine, theirs)
    assert r.text is None and len(r.conflicts) == 1
    c = r.conflicts[0]
    assert c.path == ('splash',)
    assert c.words() == ('This machine set `splash: plain`; your other machine set `splash: blocks`.')
    assert _data(humerge.merge(BASE, mine, theirs, {('splash',): 'theirs'}).text)['splash'] == 'blocks'
    assert _data(humerge.merge(BASE, mine, theirs, {('splash',): 'mine'}).text)['splash'] == 'plain'


def test_removed_on_one_side_changed_on_the_other_is_a_conflict():
    mine = BASE.replace('    splash: ocean           // the startup animation\n', '')
    theirs = BASE.replace('ocean', 'blocks')
    c = humerge.merge(BASE, mine, theirs).conflicts[0]
    assert c.words() == 'This machine removed `splash`; your other machine set `splash: blocks`.'
    r = humerge.merge(BASE, mine, theirs, {('splash',): 'mine'})
    assert 'splash' not in _data(r.text)


def test_both_removing_or_making_the_same_change_is_no_conflict():
    mine = theirs = BASE.replace('ocean', 'plain')
    assert humerge.merge(BASE, mine, theirs).text == mine


def test_both_bump_the_same_plugin_keeps_the_newer():
    mine = BASE.replace('v0.1.0', 'v0.2.0')
    theirs = BASE.replace('v0.1.0', 'v0.10.0').replace('desk: [ btop fzf ]', 'desk: [ btop ]')
    r = humerge.merge(BASE, mine, theirs)
    assert r.conflicts == []
    assert _data(r.text)['plugins'] == [{'source': 'github:me/blender', 'ref': 'v0.10.0'}]
    assert r.notes == ['both machines moved plugin github:me/blender — kept the newer, v0.10.0.']
    # a branch name isn't a version: that's a real choice
    r = humerge.merge(BASE, BASE.replace('v0.1.0', 'main'), BASE.replace('v0.1.0', 'dev'))
    assert [c.path for c in r.conflicts] == [('plugins', 'github:me/blender', 'ref')]


def test_plugins_added_on_each_side_are_both_kept():
    mine = BASE.replace('ref: v0.1.0 }', 'ref: v0.1.0 }\n        { source: "github:me/kicad" }')
    theirs = BASE.replace('ref: v0.1.0 }', 'ref: v0.1.0 }\n        { source: "github:me/splash" }')
    r = humerge.merge(BASE, mine, theirs)
    assert [d['source'] for d in _data(r.text)['plugins']] == [
        'github:me/blender', 'github:me/kicad', 'github:me/splash']


def test_components_and_pins_merge_per_name():
    base = '{ components: { a: { description: "A" } }  pins: { x: native } }\n'
    mine = '{ components: { a: { description: "A" }  b: { description: "B" } }  pins: { x: flatpak } }\n'
    theirs = ('{ components: { a: { description: "A2" } }  pins: { x: native  y: brew } }\n')
    r = humerge.merge(base, mine, theirs)
    assert r.conflicts == []
    assert _data(r.text) == {'components': {'a': {'description': 'A2'}, 'b': {'description': 'B'}},
                             'pins': {'x': 'flatpak', 'y': 'brew'}}


def test_one_line_maps_and_quoted_values_are_rewritten_in_place():
    base = ('{ components: {\n    a: { attrs: [ CLI ] description: "A tool." install: [ { via: native } ] }'
            '   // keep me\n    b: { description: "B." }\n} }\n')
    mine = base.replace('"A tool."', '"A better tool."')
    theirs = base.replace('[ CLI ]', '[ CLI FOSS ]').replace('"B."', '"B!"')
    r = humerge.merge(base, mine, theirs)
    assert _data(r.text)['components'] == {
        'a': {'attrs': ['CLI', 'FOSS'], 'description': 'A better tool.', 'install': [{'via': 'native'}]},
        'b': {'description': 'B!'}}
    assert '// keep me' in r.text and r.text.count('\n') == base.count('\n')


def test_an_order_list_is_not_a_set():
    base = '{ driver-preference: [ native flatpak ] }\n'
    r = humerge.merge(base, '{ driver-preference: [ flatpak native ] }\n',
                      '{ driver-preference: [ native flatpak snap ] }\n')
    assert [c.path for c in r.conflicts] == [('driver-preference',)]


def test_both_created_the_file():
    r = humerge.merge('', '{ splash: plain }\n', '{ effects: reduced }\n')
    assert _data(r.text) == {'splash': 'plain', 'effects': 'reduced'}


def test_not_a_map_is_unmergeable():
    with pytest.raises(humerge.Unmergeable):
        humerge.merge('[ a ]\n', '[ a b ]\n', '[ a c ]\n')
    with pytest.raises(humerge.Unmergeable):
        humerge.merge(BASE, BASE + '{{{', BASE)


# -- as git's merge driver --

def _driver(tmp_path, base, mine, theirs):
    for n, t in (('O', base), ('A', mine), ('B', theirs)):
        (tmp_path / n).write_text(t)
    r = subprocess.run([sys.executable, '-m', 'configsys.humerge', '-', str(tmp_path / 'O'), str(tmp_path / 'A'),
                        str(tmp_path / 'B'), 'p.hu'], capture_output=True, text=True)
    return r.returncode, (tmp_path / 'A').read_text()


@needs_git
def test_the_driver_settles_what_git_cannot(tmp_path):
    mine = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop fzf ripgrep ]')
    theirs = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop jq ]')
    rc, out = _driver(tmp_path, BASE, mine, theirs)
    assert rc == 0 and _data(out)['picks']['desk'] == ['btop', 'ripgrep', 'jq']


@needs_git
def test_the_driver_leaves_a_real_conflict_as_git_would(tmp_path):
    rc, out = _driver(tmp_path, BASE, BASE.replace('ocean', 'plain'), BASE.replace('ocean', 'blocks'))
    assert rc == 1 and '<<<<<<<' in out and 'plain' in out and 'blocks' in out


@needs_git
def test_the_driver_keeps_gits_text_when_lines_merge_cleanly(tmp_path):
    mine = BASE.replace('ocean', 'plain')
    theirs = BASE.replace('laptop: [ htop ]', 'laptop: [ htop bat ]')
    rc, out = _driver(tmp_path, BASE, mine, theirs)
    assert rc == 0 and out == mine.replace('laptop: [ htop ]', 'laptop: [ htop bat ]')


# -- end to end through `plugin push` --

@needs_git
def test_push_two_machines_adding_picks_needs_no_question(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('[ btop ]', '[ btop  zsh ]').replace('[ jq ]', '[ jq  yq ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fish ]'))
    _git(clone, 'commit', '-qam', 'mine')
    ui = Scripted('stop')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    assert ui.asked == []
    picks = _data(_remote_file(bare))['picks']
    assert sorted(picks['this-machine']) == ['btop', 'fish', 'zsh'] and picks['desk'] == ['jq', 'yq']
    assert _git(clone, 'rev-list', '--merges', '--count', 'HEAD') == '0'      # still a linear replay
    assert any('combined key by key' in ln for ln in lines)
    _clean(clone)
    assert not (clone / '.gitattributes').exists()                              # nothing left configured
    assert subprocess.run(['git', 'config', '--get-regexp', r'^merge\.'], cwd=clone, capture_output=True,
                          text=True).stdout == ''


@needs_git
def test_push_a_real_conflict_asks_per_key(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('{ picks', '{ splash: ocean  picks').replace('[ jq ]', '[ jq  yq ]'))
    (clone / 'p.hu').write_text(BASE_P.replace('{ picks', '{ splash: plain  picks'))
    _git(clone, 'commit', '-qam', 'mine')
    ui = Scripted('theirs')
    ok, lines = primarygit.push(_ctx(base), ui)
    assert ok, lines
    assert ui.asked == [('value', 'p.hu',
                         'This machine set `splash: plain`; your other machine set `splash: ocean`.')]
    d = _data(_remote_file(bare))
    assert d['splash'] == 'ocean' and d['picks']['desk'] == ['jq', 'yq']
    _clean(clone)


@needs_git
def test_push_a_real_conflict_stopped_pushes_nothing(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('{ picks', '{ splash: ocean  picks'))
    (clone / 'p.hu').write_text(BASE_P.replace('{ picks', '{ splash: plain  picks'))
    _git(clone, 'commit', '-qam', 'mine')
    head, remote_head = _git(clone, 'rev-parse', 'HEAD'), _git(bare, 'rev-parse', 'main')
    ok, lines = primarygit.push(_ctx(base), Scripted('stop'))
    assert not ok and 'nothing was pushed' in lines[-1]
    assert _git(clone, 'rev-parse', 'HEAD') == head and _git(bare, 'rev-parse', 'main') == remote_head
    _clean(clone)


@needs_git
def test_push_a_real_conflict_shown_in_the_editor(primary):
    base, clone, bare, other = primary
    _other_pushes(other, 'p.hu', BASE_P.replace('{ picks', '{ splash: ocean  picks'))
    (clone / 'p.hu').write_text(BASE_P.replace('{ picks', '{ splash: plain  picks'))
    _git(clone, 'commit', '-qam', 'mine')
    settled = BASE_P.replace('{ picks', '{ splash: blocks  picks')
    ok, lines = primarygit.push(_ctx(base), Scripted('edit', edit_to=settled))
    assert ok, lines
    assert _data(_remote_file(bare))['splash'] == 'blocks'


def test_the_cli_and_tui_ask_per_key(monkeypatch):
    from configsys.app import _CliPushUI
    from configsys.tui import menu
    cli = _CliPushUI()
    cli.interactive = False
    q = primarygit.question('value', name='prim', path='p.hu', detail='This machine set `a: 1`; …')
    assert cli.ask(q) == 'stop'
    seen = []
    monkeypatch.setattr(menu, '_popup_choose', lambda *a, **k: seen.append((a[2], a[3])) or 1)
    q = primarygit.question('value', name='prim', path='p.hu', detail='words', index=1, count=2)
    assert menu._TuiPushUI(None, None).ask(q) == 'theirs'
    title, options = seen[0]
    assert title == 'prim: p.hu, setting 2 of 2 — words'
    assert options[2] == ('Show me the file in my editor (sets aside the answers above)', 'e')


@needs_git
def test_the_merge_driver_never_imports_code_from_the_primary(primary, tmp_path):
    # Git runs the driver from the top of the primary's work tree. A `subprocess.py` or a
    # `configsys/` package committed there by whoever can push to the remote must NOT shadow the
    # real modules — that would be unreviewed, untrusted code running as you (review-2026-11
    # primary-01).
    base, clone, bare, other = primary
    marker = tmp_path / 'planted-code-ran'
    planted = f'open({str(marker)!r}, "w").write("ran")\n'
    _git(other, 'pull', '-q', '--rebase', 'origin', 'main')
    (other / 'subprocess.py').write_text(planted)
    (other / 'configsys').mkdir()
    (other / 'configsys' / '__init__.py').write_text(planted)
    (other / 'p.hu').write_text(BASE_P.replace('[ jq ]', '[ jq  yq ]'))
    _git(other, 'add', '-A')
    _git(other, 'commit', '-qm', 'other: a pick, plus code')
    _git(other, 'push', '-q', 'origin', 'main')
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fish ]'))
    _git(clone, 'commit', '-qam', 'mine')

    ok, lines = primarygit.push(_ctx(base), Scripted('stop'))
    assert not marker.exists(), 'code from the primary ran inside the merge driver'
    assert ok, lines
    picks = _data(_remote_file(bare))['picks']
    assert 'fish' in picks['this-machine'] and picks['desk'] == ['jq', 'yq']   # the driver still merged


# -- the driver is git's own result when it falls back (review-2026-11 B9 / primary-16) --

def _driver_bytes(tmp_path, base, mine, theirs, *extra):
    for n, t in (('O', base), ('A', mine), ('B', theirs)):
        (tmp_path / n).write_bytes(t)
    r = subprocess.run([sys.executable, '-m', 'configsys.humerge', '-', str(tmp_path / 'O'),
                        str(tmp_path / 'A'), str(tmp_path / 'B'), 'p.hu', *extra],
                       capture_output=True)
    return r.returncode, (tmp_path / 'A').read_bytes(), r.stderr


@needs_git
def test_the_drivers_markers_say_which_machine(tmp_path):
    rc, out, _e = _driver_bytes(tmp_path, BASE.encode(), BASE.replace('ocean', 'plain').encode(),
                                BASE.replace('ocean', 'blocks').encode())
    assert rc == 1 and b'<<<<<<< this machine' in out and b'>>>>>>> your other machine' in out


@needs_git
def test_the_driver_keeps_crlf_line_endings(tmp_path):
    crlf = lambda t: t.replace('\n', '\r\n').encode()      # noqa: E731
    mine = BASE.replace('desk: [ btop fzf ]', 'desk: [ btop fzf ripgrep ]')
    theirs = BASE.replace('laptop: [ htop ]', 'laptop: [ htop bat ]')
    rc, out, _e = _driver_bytes(tmp_path, crlf(BASE), crlf(mine), crlf(theirs))
    assert rc == 0 and out.count(b'\r\n') == BASE.count('\n') and b'\n' not in out.replace(b'\r\n', b'')


@needs_git
def test_a_binary_or_undecodable_file_is_left_to_git(tmp_path):
    # a NUL byte: git calls it binary and merge-file errors — %A must stay mine, rc 1 (a conflict)
    mine = BASE.encode() + b'\0mine'
    rc, out, err = _driver_bytes(tmp_path, BASE.encode() + b'\0', mine, BASE.encode() + b'\0theirs')
    assert rc == 1 and out == mine and b'Traceback' not in err
    # invalid UTF-8: no crash; git's line merge result (here, with its conflict markers) is what's left
    bad = BASE.replace('ocean', 'oc\udcffean'.encode('utf-8', 'surrogateescape').decode('latin-1'))
    rc, out, err = _driver_bytes(tmp_path, BASE.encode('latin-1'), bad.encode('latin-1'),
                                 BASE.replace('ocean', 'blocks').encode('latin-1'))
    assert b'Traceback' not in err and rc == 1 and b'<<<<<<<' in out


def test_backtick_strings_and_backslashes_dont_confuse_the_text_scanner(tmp_path):
    # B10 / primary-19: humon has three quote styles (backtick included) and NO escapes — a scanner
    # that skips `\` as an escape, or doesn't know backticks, loses every key after such a string
    from configsys import plugins
    text = ('{\n    components: { tool: { install: [ { via: script  install-cmd: `echo \'{ hi }\'` } ] } }\n'
            '    dir: "C:\\\\"\n'
            '    splash: ocean\n'
            '    effects: full\n}\n')
    mine = text.replace('ocean', 'plain')
    theirs = text.replace('effects: full', 'effects: none')
    res = humerge.merge(text, mine, theirs)
    assert res.text is not None and _data(res.text)['splash'] == 'plain' and _data(res.text)['effects'] == 'none'
    path = tmp_path / 'p.hu'
    path.write_text(text)
    plugins.set_section(str(path), 'effects', lambda indent: 'effects: reduced')
    assert _data(path.read_text())['effects'] == 'reduced' and _data(path.read_text())['dir'] == 'C:\\\\'


def _plugins_text(*entries):
    body = '  '.join('{ source: "github:me/%s"  ref: %s }' % e for e in entries)
    return '{\n    plugins: [ %s ]\n}\n' % body


def test_plugins_order_is_layer_precedence_and_is_merged_not_lost():
    # B11 / primary-20: theirs reordering [a b] -> [b a] while mine bumps a keeps theirs' order
    base = _plugins_text(('a', 'v1'), ('b', 'v1'))
    mine = _plugins_text(('a', 'v2'), ('b', 'v1'))
    theirs = _plugins_text(('b', 'v1'), ('a', 'v1'))
    res = humerge.merge(base, mine, theirs)
    got = [(p['source'], p['ref']) for p in _data(res.text)['plugins']]
    assert got == [('github:me/b', 'v1'), ('github:me/a', 'v2')]
    # both sides reordered three plugins differently: asked, never silently picked
    base3 = _plugins_text(('a', 'v1'), ('b', 'v1'), ('c', 'v1'))
    res = humerge.merge(base3, _plugins_text(('b', 'v1'), ('a', 'v1'), ('c', 'v1')),
                        _plugins_text(('c', 'v1'), ('a', 'v1'), ('b', 'v1')))
    assert res.text is None and [c.path for c in res.conflicts] == [('plugins',)]


def test_a_plugin_declared_twice_is_not_collapsed():
    dup = _plugins_text(('a', 'v1'), ('a', 'v2'))
    with pytest.raises(humerge.Unmergeable):
        humerge.merge(_plugins_text(('a', 'v1')), dup, _plugins_text(('a', 'v1'), ('b', 'v1')))


# -- order-preserving profile terms (B4, decision 5) and comments kept (B5) --

PROFILES = '''{
    profiles: {
        mine: [ btop  ~vim ]
    }
}
'''


def test_profile_terms_merge_in_order():
    # theirs inserts `+editors` BEFORE `~vim` ("editors, but still no vim"); mine appends htop —
    # a set merge put +editors last, bringing vim back (primary-08)
    mine = PROFILES.replace('[ btop  ~vim ]', '[ btop  ~vim  htop ]')
    theirs = PROFILES.replace('[ btop  ~vim ]', '[ btop  +editors  ~vim ]')
    res = humerge.merge(PROFILES, mine, theirs)
    assert _data(res.text)['profiles']['mine'] == ['btop', '+editors', '~vim', 'htop']


def test_profile_terms_both_adding_at_the_end_combine():
    mine = PROFILES.replace('[ btop  ~vim ]', '[ btop  ~vim  htop ]')
    theirs = PROFILES.replace('[ btop  ~vim ]', '[ btop  ~vim  fzf ]')
    assert _data(humerge.merge(PROFILES, mine, theirs).text)['profiles']['mine'] == \
        ['btop', '~vim', 'htop', 'fzf']


def test_profile_terms_both_reordering_differently_is_asked():
    base = PROFILES.replace('[ btop  ~vim ]', '[ a  b  c ]')
    res = humerge.merge(base, base.replace('[ a  b  c ]', '[ b  a  c ]'),
                        base.replace('[ a  b  c ]', '[ a  c  b ]'))
    assert res.text is None and [c.path for c in res.conflicts] == [('profiles', 'mine')]


@needs_git
def test_the_driver_keeps_gits_clean_order_correct_profile_merge(tmp_path):
    # primary-08: git's line merge was clean and right; the driver used to replace it
    base = PROFILES.replace('[ btop  ~vim ]', '[\n            btop\n            ~vim\n        ]')
    mine = base.replace('~vim\n', '~vim\n            htop\n')
    theirs = base.replace('btop\n', 'btop\n            +editors\n')
    rc, out = _driver(tmp_path, base, mine, theirs)
    assert rc == 0 and _data(out)['profiles']['mine'] == ['btop', '+editors', '~vim', 'htop']


def test_a_combined_list_keeps_its_comments():
    # primary-09: group comments inside a picks column survive both sides adding to it
    base = '''{
    picks: {
        desk: [ zsh     // shells
                neovim  // editors
              ]
    }
}
'''
    mine = base.replace('neovim  // editors', 'neovim  helix  // editors')
    theirs = base.replace('zsh     // shells', 'zsh  fish     // shells')
    res = humerge.merge(base, mine, theirs)
    assert '// shells' in res.text and '// editors' in res.text
    assert sorted(_data(res.text)['picks']['desk']) == ['fish', 'helix', 'neovim', 'zsh']


def test_a_comment_only_edit_of_mine_is_not_lost():
    # primary-09: mine added only a comment; theirs changed the value — theirs' value, mine's comment
    base = '{\n    splash: ocean\n    effects: full\n}\n'
    mine = '{\n    splash: ocean   // the one I like\n    effects: full\n}\n'
    theirs = base.replace('effects: full', 'effects: none')
    res = humerge.merge(base, mine, theirs)
    assert '// the one I like' in res.text and _data(res.text)['effects'] == 'none'


def test_main_is_the_driver_entry_point(tmp_path, capsys):
    # F3: the isolated `python -I -c` boot and `python -m configsys.humerge` both go through main()
    for n, text in (('O', '{ a: 1 }\n'), ('A', '{ a: 1  b: 2 }\n'), ('B', '{ a: 1  c: 3 }\n')):
        (tmp_path / n).write_text(text)
    paths = [str(tmp_path / n) for n in 'OAB']
    assert humerge.main(['-', *paths, 'p.hu']) == 0
    assert layers.materialize_string((tmp_path / 'A').read_text()) == {'a': '1', 'b': '2', 'c': '3'}
    assert humerge.main(['-']) == 2 and 'usage' in capsys.readouterr().err
