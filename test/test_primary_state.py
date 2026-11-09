'''Primary-push plan, phase 2 (docs/done/primary-push-plan.md): where your primary stands against its
remote — ↑N to push, ↓N to sync, ● uncommitted — on its Plugins row, in a Components header chip, and
in words in `plugin list`.'''

import shutil

import pytest

from configsys import primarygit
from configsys.app import Context, build_parser, main
from configsys.tui import menu

from fakes import git as _git, primary_remote

pytestmark = pytest.mark.real_runner  # real git clones/commits in tmp dirs (conftest)

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


@pytest.fixture
def primary(tmp_path):
    base, clone, _bare, other = primary_remote(tmp_path, {'p.hu': '{ picks: { this-machine: [ btop ] } }\n'},
                                               seed='other')
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    return base, ctx, clone, other


def _st(ahead=0, behind=0, dirty=False):
    return primarygit.PrimaryState('prim', 'main', ahead, behind, dirty)


@needs_git
def test_state_counts_ahead_behind_and_dirty(primary):
    base, ctx, clone, other = primary
    assert primarygit.state(ctx) == _st()
    assert main(base + ['picks', 'add', 'fzf']) == 0                    # configsys commits it: ↑1
    assert primarygit.state(ctx) == _st(ahead=1)
    (other / 'p.hu').write_text('{ picks: { laptop: [ htop ] } }\n')
    _git(other, 'commit', '-qam', 'B'); _git(other, 'push', '-q', 'origin', 'main')
    assert primarygit.state(ctx).behind == 0                          # not fetched yet
    assert primarygit.fetch(ctx)
    assert primarygit.state(ctx) == _st(ahead=1, behind=1)
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  x: 1 }\n')
    assert primarygit.state(ctx).dirty is True


def test_the_words_and_marks():
    assert primarygit.glyphs(_st()) == '' and primarygit.chip(_st()) == ''
    assert primarygit.glyphs(_st(2, 3, True)) == '↑2 ↓3 ●'
    assert primarygit.chip(_st(2)) == 'prim: ↑2 to push'
    assert primarygit.chip(_st(0, 1)) == 'prim: ↓1 to sync'
    assert primarygit.chip(_st(0, 0, True)) == ''                        # uncommitted alone: row only
    words = primarygit.describe(_st(1, 2, True))
    assert '1 change not pushed yet' in words and '2 changes from your other machines' in words
    assert 'edits not committed' in words and 'combines them' in words
    assert primarygit.describe(_st()) == ''


def test_the_primary_row_carries_the_marks():
    row = {'primary': True, 'name': 'prim', 'source': 'github:me/prim', 'ref': 'main', 'abi_ok': True,
           'requires_abi': 1, 'code_state': 'none', 'has_code': False, 'provides': {}, 'synced': True}
    node = {'depth': 0, 'last': [True]}
    assert menu._plugin_cells(row, node, 'main', _st(2, 1))[3] == 'main ↑2 ↓1'
    assert menu._plugin_remote_elem(row, 'main', _st(2, 1)) == 'outdated'
    assert menu._plugin_cells(row, node, 'main', _st())[3] == 'main'
    assert menu._plugin_remote_elem(row, 'main', _st()) == 'installed'
    other = dict(row, primary=False)
    assert menu._plugin_cells(other, node, 'main', _st(2, 1))[3] == 'main'   # only the primary


def test_the_components_header_chip(tmp_path):
    from _render_harness import RecordingPalette, build_ctx
    from configsys.tui.screens.components import ComponentsScreen
    from configsys.tui.surface import BufferSurface
    ctx = build_ctx(tmp_path)
    ctx._primary_state = _st(ahead=3)
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.note, scr.diags = '', ()
    surf = BufferSurface(40, 160)
    scr.draw(surf, RecordingPalette(), scr.build_vm(ctx, (40, 160)))
    assert 'prim: ↑3 to push' in surf.text_rows()[1]


@needs_git
def test_plugin_list_says_where_the_primary_stands(primary, capsys):
    base, _ctx, _clone, _other = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    capsys.readouterr()
    assert main(base + ['plugin', 'list']) == 0
    assert '1 change not pushed yet' in capsys.readouterr().out



@needs_git
def test_plugin_list_fetch_counts_what_your_other_machines_pushed(primary, capsys):
    # G3 / primary-31: the CLI never fetched, so a CLI-only machine never learned it was behind
    base, _ctx, _clone, other = primary
    (other / 'p.hu').write_text('{ picks: { laptop: [ htop ] } }\n')
    _git(other, 'commit', '-qam', 'B'); _git(other, 'push', '-q', 'origin', 'main')
    capsys.readouterr()
    assert main(base + ['plugin', 'list']) == 0
    assert 'from your other machines' not in capsys.readouterr().out          # as of the last fetch
    assert main(base + ['plugin', 'list', '--fetch']) == 0
    assert '1 change from your other machines' in capsys.readouterr().out

@needs_git
def test_the_plugins_screen_fetches_and_shows_behind(primary):
    import time
    base, ctx, _clone, other = primary
    (other / 'p.hu').write_text('{ picks: { laptop: [ htop ] } }\n')
    _git(other, 'commit', '-qam', 'B'); _git(other, 'push', '-q', 'origin', 'main')
    pl = menu.PluginScreen(ctx)
    for _ in range(300):                                                 # the background fetch lands
        if pl.primary_state and pl.primary_state.behind:
            break
        time.sleep(0.02)
    assert pl.primary_state.behind == 1 and ctx._primary_state.behind == 1
