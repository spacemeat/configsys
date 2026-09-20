'''Phase 0 of the D2 MVVM refactor (docs/d2-mvvm-plan.md): prove every TUI screen renders HEADLESSLY
— into an off-screen BufferSurface via a deterministic RecordingPalette, with no curses and no PTY.

This is the safety-net infrastructure the per-screen migration builds on: if a screen can be painted
into a buffer and captured as a stable grid, its legacy painter and its future build_vm/draw
replacement can be diffed cell-for-cell. It also IS the headless-render milestone toward the
SDK/headless optionality the rewrite is for.'''

import pytest

from _render_harness import SCREENS, SIZES, RecordingPalette, build_ctx, capture


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('render'))


@pytest.mark.parametrize('name', SCREENS)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight'])
def test_screen_renders_headless_nonempty(ctx, name, h, w):
    grid = capture(name, ctx, RecordingPalette(), h, w)
    assert grid, f'{name} painted nothing at {h}x{w}'
    # every cell is in bounds and carries a single glyph
    for y, x, char, _attr in grid:
        assert 0 <= y < h and 0 <= x < w, f'{name}: cell ({y},{x}) out of {h}x{w}'
        assert len(char) == 1


@pytest.mark.parametrize('name', SCREENS)
def test_render_is_deterministic(ctx, name):
    '''Same state + same palette -> byte-identical grid on repeat. Non-determinism here would make
    legacy-vs-new equivalence meaningless, so it's asserted up front.'''
    h, w = SIZES[0]
    a = capture(name, ctx, RecordingPalette(), h, w)
    b = capture(name, ctx, RecordingPalette(), h, w)
    assert a == b


@pytest.mark.parametrize('name', SCREENS)
@pytest.mark.parametrize('mode', ['grad', 'flat', 'lowcolor', 'mono'], )
def test_render_across_palette_modes(ctx, name, mode):
    '''The painters branch on pal.gradient / pal.have256 (and mono); render in each so a change on any
    of those branches is coverable by the equivalence tests, not just the default truecolor path.'''
    pal = {
        'grad': RecordingPalette(gradient=True, have256=True),
        'flat': RecordingPalette(gradient=False, have256=True),
        'lowcolor': RecordingPalette(gradient=False, have256=False),
        'mono': RecordingPalette(gradient=False, have256=False, mono=True),
    }[mode]
    grid = capture(name, ctx, pal, *SIZES[0])
    assert grid
