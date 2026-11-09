'''review-2026-11-2 B16 — the real Palette under a fake curses: a theme past the 240 redefinable slots
reuses the NEAREST allocated colour (not whatever slot rgb_to_256 lands on); a frame past 255 pairs
borrows the nearest same-fg pair (never a default-colour hole); a --color cap on a -direct terminfo
sends the quantized colour as packed rgb.'''

import curses

import pytest

from configsys.tui import theme as th


@pytest.fixture
def fake_curses(monkeypatch):
    state = {'colors': {}, 'pairs': {}}

    def setup(colors, can_change):
        monkeypatch.setattr(curses, 'COLORS', colors, raising=False)
        monkeypatch.setattr(curses, 'start_color', lambda: None)
        monkeypatch.setattr(curses, 'use_default_colors', lambda: None)
        monkeypatch.setattr(curses, 'can_change_color', lambda: can_change)
        monkeypatch.setattr(curses, 'init_color', lambda i, r, g, b: state['colors'].__setitem__(i, (r, g, b)))
        monkeypatch.setattr(curses, 'init_pair', lambda n, f, b: state['pairs'].__setitem__(n, (f, b)))
        monkeypatch.setattr(curses, 'color_pair', lambda n: n << 8)
        return state
    return setup


def _wide_theme(span=96):
    hues = ['#{0:02x}00{0:02x}', '#00{0:02x}{0:02x}', '#{0:02x}{0:02x}00', '#{0:02x}0000',
            '#00{0:02x}00', '#0000{0:02x}', '#{0:02x}{0:02x}{0:02x}']
    return {'pages': {p: {'gradient': {'enabled': True, 'from': hues[i % len(hues)].format(span),
                                       'to': '#000000'}} for i, p in enumerate(th.ALL_PAGES)}}


def test_slot_exhaustion_reuses_the_nearest_colour(fake_curses, monkeypatch):
    monkeypatch.delenv('CONFIGSYS_COLOR', raising=False)
    monkeypatch.delenv('NO_COLOR', raising=False)
    fake_curses(256, True)
    pal = th.Palette(_wide_theme())
    assert pal._next_color == 256                       # every slot used
    for page in th.ALL_PAGES:
        pal.use_page(page)
        for want, idx in zip(range(len(pal._grad_bg)), pal._grad_bg):
            got = pal._slot_rgb.get(idx)
            assert got is not None                      # always a slot WE defined, never a stray cube index
    # an overflowed near-black asks for near-black, never the bright map colour slot 16 holds
    near_black = pal._color((3, 0, 4))
    assert th._dist2(pal._slot_rgb[near_black], (3, 0, 4)) < 40 ** 2
    assert 'reused' in pal.color_mode


def test_pair_overflow_borrows_the_nearest_same_fg_pair(fake_curses, monkeypatch):
    monkeypatch.delenv('CONFIGSYS_COLOR', raising=False)
    monkeypatch.delenv('NO_COLOR', raising=False)
    fake_curses(1 << 24, False)                         # direct: no slot limit, only the pair budget
    pal = th.Palette()
    pal.new_frame()
    fg = pal._color((200, 200, 200))
    for b in range(300):
        pal._pair(fg, pal._color((b % 256, 0, 0)))
    attr = pal._pair(fg, pal._color((255, 0, 1)))
    assert attr != curses.A_NORMAL


@pytest.mark.parametrize('cap', ['256', '16'])
def test_a_capped_depth_on_a_direct_terminfo_sends_packed_rgb(fake_curses, monkeypatch, cap):
    monkeypatch.setenv('CONFIGSYS_COLOR', cap)
    monkeypatch.delenv('NO_COLOR', raising=False)
    fake_curses(1 << 24, False)
    pal = th.Palette()
    idx = pal._color((235, 95, 95), 'error')            # the `error` red (its bright-red slot)
    r, g, b = (idx >> 16) & 255, (idx >> 8) & 255, idx & 255
    assert r > 150 and g < 150 and b < 150              # still red — not (0, 0, 210) near-black blue


# -- review-2026-11-2 tui-theme-13 / 20 ------------------------------------------------------------

def test_colors_basic_overrides_one_name_not_its_rgb_twins(fake_curses, monkeypatch):
    monkeypatch.delenv('CONFIGSYS_COLOR', raising=False)
    monkeypatch.delenv('NO_COLOR', raising=False)
    fake_curses(16, False)
    pal = th.Palette({})
    fg = lambda role: pal._roles[role][0]
    assert fg('installed') == fg('op_install') == fg('diff_add') == 10    # bright-green
    pal = th.Palette({'colors-basic': {'op_install': 'cyan'}})
    assert fg('op_install') == 6                                            # the one you named
    assert fg('installed') == 10 and fg('diff_add') == 10                   # its rgb twins keep theirs


_EXPECT_DEPTH = {   # (cap, COLORS, can_change) -> depth
    (None, 8, False): '8', (None, 16, False): '16', (None, 256, False): '256',
    (None, 256, True): 'truecolor', (None, 1 << 24, False): 'direct',
    ('none', 256, True): 'none', ('8', 256, True): '8', ('8', 16, False): '8',
    ('16', 1 << 24, False): '16', ('16', 8, False): '8', ('256', 1 << 24, False): '256',
    ('256', 256, True): '256', ('256', 16, False): '16', ('24bit', 256, False): '256',
    ('24bit', 1 << 24, False): 'direct',
}


@pytest.mark.parametrize('cap,colors,can_change', list(_EXPECT_DEPTH))
def test_palette_depth_is_the_one_derivation(fake_curses, monkeypatch, cap, colors, can_change):
    if cap is None:
        monkeypatch.delenv('CONFIGSYS_COLOR', raising=False)
    else:
        monkeypatch.setenv('CONFIGSYS_COLOR', cap)
    monkeypatch.delenv('NO_COLOR', raising=False)
    fake_curses(colors, can_change)
    pal = th.Palette()
    d = _EXPECT_DEPTH[(cap, colors, can_change)]
    assert pal.depth == d and th.palette_depth(pal) == d
    assert pal.mono == (d == 'none') and pal.direct == (d == 'direct')
    assert pal.truecolor == (d in ('truecolor', 'direct'))
    assert pal.have256 == (d in ('256', 'truecolor', 'direct'))
    assert pal.lowcolor == (d in ('8', '16'))
    assert pal.direct_numbering == (colors >= 1 << 24)
    mode = {'none': 'none', '8': '8-color', '16': '16-color', '256': '256-color',
            'truecolor': '24-bit', 'direct': 'direct 24-bit'}[d]
    assert pal.color_mode.startswith(mode)
