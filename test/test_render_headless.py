'''Every TUI screen renders HEADLESSLY — into an off-screen BufferSurface via a deterministic
RecordingPalette, through its real build_vm/draw, with no curses and no PTY (docs/tui-architecture.md
"Surfaces and headless rendering").

These are the cross-screen smoke checks: each screen paints something, in bounds, deterministically,
at a roomy and a tight size and across the palette branches (gradient / flat / low-colour / mono).
Per-screen render regression lives in test_screen_<id>.py against hand-built data.'''

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
    '''Same state + same palette -> byte-identical grid on repeat: draw is a deterministic function
    of (model, ctx, vm, palette) — the contract every render assertion leans on.'''
    h, w = SIZES[0]
    a = capture(name, ctx, RecordingPalette(), h, w)
    b = capture(name, ctx, RecordingPalette(), h, w)
    assert a == b


@pytest.mark.parametrize('name', SCREENS)
@pytest.mark.parametrize('mode', ['grad', 'flat', 'lowcolor', 'mono'], )
def test_render_across_palette_modes(ctx, name, mode):
    '''The painters branch on pal.gradient / pal.have256 (and mono); render in each so every one of
    those branches is exercised, not just the default truecolor path.'''
    pal = {
        'grad': RecordingPalette(gradient=True, have256=True),
        'flat': RecordingPalette(gradient=False, have256=True),
        'lowcolor': RecordingPalette(gradient=False, have256=False),
        'mono': RecordingPalette(gradient=False, have256=False, mono=True),
    }[mode]
    grid = capture(name, ctx, pal, *SIZES[0])
    assert grid
