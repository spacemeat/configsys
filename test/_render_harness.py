'''Render harness for the D2 TUI MVVM refactor (see docs/d2-mvvm-plan.md).

Renders each TUI screen from a FIXED synthetic state into a BufferSurface, using a deterministic
RecordingPalette that returns hashable descriptor tokens instead of curses attrs — so a screen's
painted grid can be captured and compared with NO curses and NO pseudo-terminal.

This module holds the shared machinery — `RecordingPalette` (a deterministic fake curses palette),
`build_ctx`, and `capture`/`_render`, which paint any screen from its sample through the REAL
build_vm/draw. `test_render_headless.py` asserts every screen renders headlessly; the per-screen
render-regression assertions live in `test_screen_*.py` against HAND-BUILT data (no golden, no oracle,
nothing reads routes.hu — see docs/d2-mvvm-plan.md). The `Attr` value object below dates from the
retired legacy-vs-new equivalence phase and is kept because the fake palette still returns it.
'''

from configsys.app import Context, build_parser
from configsys.tui.surface import BufferSurface


class Attr:
    '''A stand-in for a curses attr that a painter builds by OR-ing a palette result with flag ints
    (`pal.style(...) | A_REVERSE | A_DIM`). It carries the palette's descriptor `token` and the
    accumulated `flags`, so two cells compare equal iff they'd show the same role AND the same
    structural flags — exactly the equivalence the harness needs, with no bit-collision risk.'''

    __slots__ = ('token', 'flags')

    def __init__(self, token, flags=0):
        self.token = token
        self.flags = flags

    def __or__(self, other):
        if isinstance(other, Attr):
            return Attr((self.token, other.token), self.flags | other.flags)
        return Attr(self.token, self.flags | int(other))

    __ror__ = __or__

    def __eq__(self, o):
        return isinstance(o, Attr) and self.token == o.token and self.flags == o.flags

    def __hash__(self):
        return hash((self.token, self.flags))

    def __repr__(self):
        return f'Attr({self.token!r}, {self.flags})'

# Every screen the router hosts, in migration order (simplest table-shaped first, richest last).
SCREENS = ['plugins', 'glue', 'dotfiles', 'config', 'theme', 'profiles', 'components']

# A couple of terminal geometries: a roomy one and a tight one (exercises clipping / compaction).
SIZES = [(40, 120), (24, 80)]


class RecordingPalette:
    '''Mimics the Palette PUBLIC API used by the painters (style/at/fill/get/rgb_*/band/new_frame/
    use_page + the gradient/have256/sel_bg_rgb/color_mode reads), returning a DETERMINISTIC hashable
    token per call instead of a curses attr. Faithful to the distinctions a painter controls — role,
    selection, an explicit bg, the active page, and (when the gradient is on) the diagonal band index,
    replicated from Palette.band — so a positional or role change in a painter changes the token.

    It need not match real curses color math: equivalence renders old and new painters under the SAME
    instance, so only self-consistency matters (real-curses correctness is guarded by test_tui_smoke).
    Construct with gradient/have256/mono to drive the painter branches that read those flags.'''

    def __init__(self, *, gradient=True, have256=True, mono=False, bands=32):
        self.gradient = gradient
        self.have256 = have256
        self.mono = mono
        self._bands = bands
        self._page = 'components'

    # -- Palette API the painters call ------------------------------------

    def new_frame(self):
        pass

    def use_page(self, page):
        self._page = page

    @property
    def color_mode(self):
        return 'harness'

    @property
    def sel_bg_rgb(self):
        return (40, 40, 60)

    def band(self, y, x, h, w):
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(self._bands - 1, int(t * self._bands))

    @staticmethod
    def _bgk(bg):
        return tuple(bg) if bg is not None else None

    def _band_if(self, cond, y, x, h, w):
        return self.band(y, x, h, w) if (cond and self.gradient) else None

    def style(self, element, y, x, h, w, *, selected=False, row=0, bg=None):
        if self.mono:
            return Attr(('m-style', element, bool(selected)))
        b = self._band_if(bg is None and not selected, y, x, h, w)
        return Attr(('style', self._page, element, bool(selected), self._bgk(bg), b))

    def at(self, name, y, x, h, w, *, selected=False, row=0):
        if self.mono:
            return Attr(('m-at', bool(selected)))
        return Attr(('at', self._page, name, bool(selected), self._band_if(not selected, y, x, h, w)))

    def fill(self, y, x, h, w, *, selected=False, bg=None):
        if self.mono:
            return Attr(('m-fill', bool(selected)))
        b = self._band_if(bg is None and not selected, y, x, h, w)
        return Attr(('fill', self._page, bool(selected), self._bgk(bg), b))

    def get(self, name):
        return Attr(('get', name))

    def rgb_attr(self, rgb):
        return Attr(('rgb', tuple(rgb)))

    def rgb_pair(self, fg, bg):
        return Attr(('rgbp', tuple(fg), tuple(bg)))


def build_ctx(home):
    '''A real Context over a throwaway home (pop OS, --pretend) — real routes.hu/config so the
    profiles/config/theme samples read a genuine catalog. Primes the per-frame ctx fields the
    painters expect (reboot chip) and the module-global keymap the legends read.'''
    from configsys.tui import menu
    from configsys.tui.keyspec import Keymap
    args = build_parser().parse_args(['--home', str(home), '--os', 'pop', '--pretend', 'inspect'])
    ctx = Context(args)
    ctx.ensure_user_config()
    ctx.runner._echo = None            # silence the pretend-runner echo the sample probes trigger
    ctx._reboot_pending = (False, '')
    menu._KEYMAP = Keymap(ctx.config.keys())
    return ctx


def _render(name, ctx, pal, h, w):
    '''Paint one screen from its fixed sample state into a BufferSurface, via its REAL Screen — the
    same build_vm/draw the router uses. Used by test_render_headless (every screen renders from a
    realistic sample without curses).'''
    from configsys.tui import menu
    surf = BufferSurface(h, w)
    size = (h, w)
    if name == 'components':
        from configsys.tui.screens.components import ComponentsScreen
        scr = ComponentsScreen(ctx, menu._sample_components_state())
        scr.note, scr.diags = '', ()
        scr.draw(surf, pal, scr.build_vm(ctx, size))
    elif name == 'profiles':
        from configsys.tui.screens.profiles import ProfilesScreen
        ps = menu._sample_profiles_state(ctx)
        scr = ProfilesScreen(ctx, ps)
        vm = scr.build_vm(ps.ctx, size); vm.note = ''
        scr.draw(surf, pal, vm)
    elif name == 'theme':
        from configsys.tui.screens.theme import ThemeScreen
        scr = ThemeScreen(ctx, menu.ThemeScreen(ctx), sample_ms=menu._sample_components_state())
        vm = scr.build_vm(ctx, size); vm.note = ''
        scr.draw(surf, pal, vm)
    else:
        models = {'plugins': menu._sample_plugins_state, 'glue': menu._sample_glue_state,
                  'dotfiles': menu._sample_dotfiles_state,
                  'config': lambda c: menu.ConfigScreen(c)}
        if name not in models:
            raise ValueError(f'unknown screen {name!r}')
        from configsys.tui.screens import config as _cfg, dotfiles as _df, glue as _gl, plugins as _pg
        cls = {'plugins': _pg.PluginsScreen, 'glue': _gl.GlueScreen,
               'dotfiles': _df.DotfilesScreen, 'config': _cfg.ConfigScreen}[name]
        scr = cls(ctx, models[name](ctx))
        vm = scr.build_vm(ctx, size); vm.note = ''
        scr.draw(surf, pal, vm)
    return surf


def capture(name, ctx, pal, h, w):
    '''The painted grid: a sorted list of (y, x, char, attr-token) — a stable, comparable snapshot.'''
    return _render(name, ctx, pal, h, w).grid()
