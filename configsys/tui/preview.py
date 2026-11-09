'''preview.py — the Theme editor's model (ThemeScreen) and the hand-built sample states its live
previews (and the render tests) paint.

Split out of menu.py (review-2026-11-2 D2).
'''

import curses
from .models import MenuState
from .paint import _hex
from .panes import ConfigScreen, DotfilesScreen, GlueScreen, PluginScreen, ProfileScreen


# -- Theme editor (its own screen, key 6) ---------------------------------
def _sample_components_state():
    '''A STABLE, synthetic Components tree for the Theme editor's F1 sample — always populated and
    exercising every themeable element (a two-profile tree, components + a nested unit, each driver /
    scope / version, and every status: installed / outdated / partial / missing / locked / error /
    unsupported, plus the op badges), so role colors are visible regardless of the user's real install
    state (which may be empty when there's nothing to do, or never hit certain statuses).'''
    from ..componentObj import ResolvedComponent
    from ..installState import ComponentState

    def st(key, req, *, present, iv, lv, scope='user', locked=False, supported=True, error=None):
        fam, comp = key.split('\\')
        rc = ResolvedComponent(key=key, driver=fam, comp=comp, fields={'name': comp}, requested_as=set(req))
        return ComponentState(component=rc, supported=supported, present=present, installed_version=iv,
                              latest_version=lv, locked=locked, lock_source=('native' if locked else None),
                              managed=False, error=error, scope=scope)
    states = {
        'apt\\ripgrep':     st('apt\\ripgrep', ['ripgrep'], present=True, iv='14.1.0', lv='14.1.0'),   # installed
        'cargo\\bottom':    st('cargo\\bottom', ['bottom'], present=True, iv='0.9.6', lv='0.10.2'),     # outdated
        'appImage\\neovim': st('appImage\\neovim', ['neovim'], present=False, iv=None, lv='0.10.2'),    # missing
        'tarball\\zig':     st('tarball\\zig', ['zig'], present=True, iv='0.13.0', lv='0.13.0',
                               scope='system', locked=True),                                            # locked (system scope)
        'flatpak\\firefox': st('flatpak\\firefox', ['firefox'], present=False, iv=None, lv='130.0'),    # firefox: 1 of 2
        'apt\\flatpak':     st('apt\\flatpak', ['firefox'], present=True, iv='1.14.10', lv='1.14.10'),  # units present -> partial
        'apt\\libfoo':      st('apt\\libfoo', ['libfoo'], present=True, iv='2.1', lv='2.1',
                               error='a post-install step failed'),                                     # error
        'snap\\ondistro':   st('snap\\ondistro', ['ondistro'], present=False, iv=None, lv=None,
                               supported=False),                                                        # unsupported here
    }
    layouts = [('dev-tools', ['ripgrep', 'bottom', 'neovim', 'zig', 'libfoo']),
               ('web-browsers', ['firefox', 'ondistro'])]
    pm = MenuState(states, layouts)
    pm.descriptions = {
        'ripgrep': 'ripgrep — recursive regex search (`rg`)', 'bottom': 'System monitor (`btm`)',
        'neovim': 'Hyperextensible Vim-based editor', 'zig': 'The Zig toolchain',
        'firefox': 'Mozilla Firefox web browser', 'libfoo': 'An example shared library',
        'ondistro': 'Not packaged on this OS'}
    try:
        pm.toggle_expand_all()             # reveal nested units + leaf rows (op badges, driver/version/scope cols)
    except Exception:                      # noqa: BLE001
        pass
    pm.cursor = pm.top = 0
    for key, op in (('appImage\\neovim', 'install'), ('cargo\\bottom', 'upgrade'),
                    ('apt\\ripgrep', 'remove'), ('apt\\flatpak', 'lock')):   # one of each op badge
        if key in states:
            pm.staged[key] = op
    return pm


class _SampleCfg:
    '''A thin overlay over the real Config for the Profiles sample: a handful of reads
    (is_new/dispositions/included/picks/uninstall_queue + the machine registry) return deterministic
    synthetic values so every catalog glyph shows; everything else delegates to the real config.'''
    def __init__(self, real):
        self._real = real

    def __getattr__(self, k):                        # everything not overridden below -> real config
        return getattr(self._real, k)


class _SampleCtx:
    '''A ctx whose `.config` is the sample overlay; routes/os_info/paths/runner delegate to the real
    ctx. Passed to both the ProfileScreen (ps.ctx) and _draw_profiles so their config reads agree.'''
    def __init__(self, real, config):
        self._real = real
        self.config = config

    def __getattr__(self, k):
        return getattr(self._real, k)


def _sample_profiles_state(ctx):
    '''The Profiles sample: the real ProfileScreen (its profile tree + `+include` links + component
    catalog come from the actual config, which is never empty) fed a synthetic ctx overlay so the
    catalog glyphs + infobox all show deterministically. A REPEATING per-row pattern is stamped across
    the WHOLE visible catalog (dominated by not-installed ○, like a real machine early in setup) so
    every glyph recurs — tracked+pinned (●, [via]), tracked (●), installed-untracked (⊙), NEW (◆/○),
    interesting (☆/⊙), seen+partial (·/◐), staged-for-uninstall (⮾), unavailable (⊘) — not just a few
    rows at the top. The cursor parks on a component with requires + dependents, forced unavailable, so
    the infobox shows the ⊘ warn banner alongside the requires/required-by lines. A synthetic empty
    overlay is injected so overlay() never spawns the real (threaded) scan.'''
    ps = ProfileScreen(ctx)
    ps._warm_gen = 10 ** 9                           # stop __init__'s whole-catalog warm sweep: a
    # sample only paints the visible rows (resolved on demand), so warming ~all components would just
    # burn CPU (this sample also backs the Theme editor's Profiles preview). Not a race guard: _resolve
    # is lock-guarded and inserts with setdefault, so a late warm result can't overwrite the priming.
    ps.show_install = 1
    ps._overlay = (frozenset(), {}, frozenset())     # present -> overlay() returns it, no orphan scan
    ps._async_overlay = None
    ps.ensure_probes = lambda *a, **k: None          # sample: no background installed-probe — its
    # results would fold underlines in at a nondeterministic moment; the sample's install state is the
    # stubbed install_state below, so the render is complete AND deterministic.
    ps.focus = 'right'                               # the catalog cursor drives the infobox + selection

    vis = [nm for nm, _d in ps._catalog_rows()]      # the stable visible catalog (config-independent)

    # cursor: a real component with BOTH requires and dependents, forced unavailable so the infobox
    # exercises the ⊘ banner + the requires/required-by lines together.
    def _has_req(n):
        return bool(getattr(ctx.routes.components.get(n), 'requires', None))

    def _has_dep(n):
        try:
            return bool(ctx.routes.dependents(n))
        except Exception:                            # noqa: BLE001
            return False
    curc = (next((n for n in vis if _has_req(n) and _has_dep(n)), None)
            or next((n for n in vis if _has_req(n)), None) or (vis[0] if vis else None))
    if curc in vis:
        ps.rcur = vis.index(curc)

    # one 'tag' per visible row (cycled); most rows are not-installed, a realistic early-setup spread.
    PATTERN = ['tracked_pin', 'none', 'new', 'untracked', 'interesting', 'none',
               'seen_partial', 'tracked', 'none', 'uninstall', 'unavail', 'none']
    tag = {n: PATTERN[i % len(PATTERN)] for i, n in enumerate(vis)}
    if curc:
        tag[curc] = 'unavail'                        # cursor row must be the banner+requires exemplar
    _ISTATE = {'tracked_pin': 'all', 'tracked': 'all', 'untracked': 'all', 'interesting': 'all',
               'seen_partial': 'some', 'uninstall': 'all', 'new': 'none', 'none': 'none',
               'unavail': 'none'}
    _track = {n for n, t in tag.items() if t in ('tracked_pin', 'tracked')}
    _new = {n for n, t in tag.items() if t == 'new'}
    _disp = {n: ('interesting' if t == 'interesting' else 'seen')
             for n, t in tag.items() if t in ('interesting', 'seen_partial')}
    _uq = {n for n, t in tag.items() if t == 'uninstall'}
    _unavail = {n for n, t in tag.items() if t == 'unavail'}
    ps.install_state = lambda name, *a, **k: _ISTATE.get(tag.get(name), 'none')

    # prime the _resolve cache: pinned method ([via]) on the pinned-tracked rows, ⊘ on the unavailable.
    for n, t in tag.items():
        if t == 'tracked_pin':
            _av, _via, _pin = ps._resolve(n)
            ps._res[n] = (True, _via or 'apt', True)
    for n in _unavail:
        ps._res[n] = (False, None, False)

    _laptop = {n for n in _track if tag.get(n) == 'tracked'}   # laptop picks a subset -> columns differ
    cfg = _SampleCfg(ctx.config)
    cfg.is_new = lambda name: name in _new
    cfg.dispositions = lambda: dict(_disp)
    cfg.included = lambda: set(_track)
    cfg.picks = lambda: {'thisbox': set(_track), 'laptop': set(_laptop)}
    cfg.uninstall_queue = lambda: set(_uq)
    cfg.machine_names = lambda: ['thisbox', 'laptop']
    cfg.current_machine = lambda: 'thisbox'
    ps.ctx = _SampleCtx(ctx, cfg)                    # ps + _draw_profiles now read the overlay
    # Hermetic sample: abort the __init__ warm-cache thread and resolve every visible row NOW, so the
    # draw only READS _res (no on-demand resolve during paint). Otherwise the background warm thread
    # (which resolves into shared ctx.routes caches) races the draw under a loaded test run, and a
    # component's shown via/pin can differ between two renders — a flaky equivalence check.
    for _n in vis:
        try:
            ps._resolve(_n)                          # fills _res[_n] once (no-op if already primed above)
        except Exception:                            # noqa: BLE001 — a preview never bricks
            pass
    # FREEZE the sample's answers: the draw reads this snapshot, so neither a straggling warm-thread
    # write nor a ctx.routes rebuild (which clears _res by the Resolver's id — allocator-dependent
    # under a loaded run) can change a row's via/pin between two renders.
    _frozen, _live = dict(ps._res), ps._resolve
    ps._resolve = lambda name: _frozen[name] if name in _frozen else _live(name)
    return ps


def _sample_plugins_state(ctx):
    '''A stable synthetic Plugins sample: a small declared tree covering every table state — a primary
    ★ plugin up-to-date + trusted, a plugin with an update available (amber remote-ref), its transitive
    child (tree prefix), an ABI-mismatch row (error), an untrusted/changed-code row, and an unsynced
    row — plus a mocked diff so the diff roles show. Built by hand so the roles are colourable
    regardless of the machine's real (usually empty) plugin set. No network: the draw reads rows/
    remote/diff directly and never resolves remote-refs itself.'''
    from .. import plugins
    pl = PluginScreen(ctx, load=False)   # no real plugin read, primary fetch or ls-remote (C6)

    def _row(primary, name, source, ref, abi_ok, requires_abi, code_state, has_code, provides,
             synced, checksum='ok'):
        return {'primary': primary, 'name': name, 'source': source, 'ref': ref, 'abi_ok': abi_ok,
                'requires_abi': requires_abi, 'code_state': code_state, 'has_code': has_code,
                'provides': provides, 'synced': synced, 'checksum': checksum}

    pl.rows = [
        _row(True,  'mytools',      'github:me/configsys-mytools',        'v1.2.0', True, 2,
             'trusted',  True,  {'driver': ['footool']},  True),
        _row(False, 'science',      'github:org/configsys-science',       'v0.4.1', True, 2,
             'trusted',  True,  {'splash': ['nova']},     True),
        _row(False, 'science-data', 'github:org/configsys-science-data',  'v0.4.1', True, 2,
             'none',     False, {},                       True),
        _row(False, 'legacy-pack',  'github:old/configsys-legacy',        'v3.0.0', False, 1,
             'unsynced', True,  {},                       True),
        _row(False, 'labkit',       'github:lab/configsys-labkit',        'v2.1.0', True, 2,
             'changed',  True,  {'driver': ['labdrv']},   True),
        _row(False, 'fresh',        'github:new/configsys-fresh',         None,     True, 2,
             'unsynced', False, {},                       False),
    ]
    for r, prov in zip(pl.rows, (['components', 'drivers', 'glue', 'plugins'], ['components', 'splashes'],
                                 ['profiles', 'version-floors'], [], ['drivers'], [])):
        r['provisions'] = prov
    pl.rows[3]['locked'] = '2026-10-21'                   # `legacy-pack` held (⊘)
    # tree: `science-data` is a transitive child of `science`; the rest are roots.
    pl.tree = [{'depth': 0, 'last': [True], 'decl': {}} for _ in pl.rows]
    pl.tree[2] = {'depth': 1, 'last': [False, True], 'decl': {}}
    # remote-refs: up-to-date (green) except `science`, which has an update (amber), and `fresh` (—).
    _rem = {'v1.2.0', 'v0.4.1', 'v3.0.0', 'v2.1.0'}                       # match each row's ref
    pl.remote = {plugins.dir_name(r['source']): r['ref'] for r in pl.rows if r['ref'] in _rem}
    pl.remote[plugins.dir_name('github:org/configsys-science')] = 'v0.5.0'   # newer -> outdated amber
    pl.remote[plugins.dir_name('github:new/configsys-fresh')] = None         # unreachable / unsynced

    pl.diff_files = [{'path': 'science.hu', 'lines': [
        ('hunk', '@@ components @@'), ('meta', ' astropy:'),
        ('add', '+   pipx: { name: astropy }'), ('del', '-   pip: { name: astropy }'),
        ('ctx', '    suggests: astropy-dotfiles')]}]
    pl.dfile, pl.diff_note = 0, None
    pl.cur = 1                                            # park on `science` (the update-available row)
    return pl


def _sample_glue_state(ctx):
    '''A stable synthetic Glue sample: snippets across two shells covering active / changed / available
    + loader on/off, so every glue role is colourable regardless of the user's real glue. The draw
    reads only the row tuple's comp/state/target/source/shell, so a placeholder rc (None) is fine. One
    USER glue row (7-tuple flagged True) shows the user.d namespace next to component glue.'''
    gs = GlueScreen(ctx, load=False)
    gs.rows = [   # component glue links as conf.d/50-<name>.<ext>; user glue (user.d) as 90-<name>
        (None, 'fd-glue',     '~/.config/bash/conf.d/50-fd.sh',     'linked',   '<repo>/shell/bash/fd.sh',     'bash'),
        (None, 'zoxide-glue', '~/.config/bash/conf.d/50-zoxide.sh', 'drifted',  '<repo>/shell/bash/zoxide.sh', 'bash'),
        (None, 'yazi-glue',   '~/.config/bash/conf.d/50-yazi.sh',   'template', '<repo>/shell/bash/yazi.sh',   'bash'),
        (None, '(user) aliases', '~/.config/bash/conf.d/90-aliases.sh', 'linked',
         '<plugin>/shell/bash/user.d/aliases.sh', 'bash', True),
        (None, 'bat-glue',    '~/.config/fish/conf.d/50-bat.fish',  'linked',   '<repo>/shell/fish/bat.fish',  'fish'),
    ]
    gs.loader = {'bash': 'loader-on', 'fish': 'loader-off'}       # one wired, one not
    gs.display = [('hdr', 'bash', 'loader-on'), ('row', 0), ('row', 1), ('row', 2), ('row', 3),
                  ('hdr', 'fish', 'loader-off'), ('row', 4)]
    gs.cur = gs.top = gs.hscroll = 0
    return gs


def _sample_dotfiles_state(ctx):
    '''A stable synthetic Dotfiles sample covering managed / unmanaged(!) / no-config, so every role is
    colourable regardless of the user's real captures.'''
    import types
    ds = DotfilesScreen(ctx, load=False)
    # The cursor row is painted with the SELECTION colour (it overlays that row's status colour), so
    # every status needs at least one row OFF the cursor. Managed appears twice — one at the cursor
    # (shows the selection colour) and one below (shows its own green).
    ds.rows = [                                                   # (rc(.comp), name, target, raw-state, source, capturable)
        (types.SimpleNamespace(comp='neovim-dotfiles'), 'neovim', '~/.config/nvim',       'linked',    '<plugin>/neovim.cfs', False),
        (types.SimpleNamespace(comp='git-dotfiles'),    'git',    '~/.gitconfig',         'unmanaged', 'gitconfig',           True),
        (types.SimpleNamespace(comp='bat-dotfiles'),    'bat',    '~/.config/bat/config', 'empty',     'bat.cfs',             False),
        (types.SimpleNamespace(comp='helix-dotfiles'),  'helix',  '~/.config/helix',      'linked',    '<plugin>/helix.cfs',  False),
    ]
    ds.display = [('row', 0), ('row', 1), ('row', 2), ('row', 3)]
    ds.cur = ds.top = ds.hscroll = 0                             # cursor on row 0 (managed) -> its green shows on row 3
    return ds


class ThemeScreen:
    '''Two lists over one sample page: the shared color MAP (name -> #rrggbb) and the focused page's
    ROLE styles (fg/bg/effects, fg/bg referencing a map name or a literal). Tab toggles focus; a-e
    cycles the page. Edits write via actions.set_theme_value; the caller re-instantiates the Palette
    so the sample repaints instantly.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = 0                              # focused page (index into ALL_PAGES, incl. 'theme')
        self.focus = 'map'                         # 'map' | 'roles'
        self.map_cur = self.map_top = 0
        self.role_cur = self.role_top = 0
        self.map_ncols = 1                         # set during draw; the h/l column stride
        self.map_rows_per_col = 10 ** 6
        self._preview = {}                         # page -> a preview-only state obj (built+augmented once)
        self.preview_diags = [{'level': 'warn', 'tag': 'sample', 'text': 'example issue'}] * 2
        self.reload()

    def preview_state(self, ctx, page, ms):
        '''A real state object for `page`'s live sample, built + lightly augmented ONCE (so every
        themeable role shows) and cached. `ms` is the session's live components state (for the
        components sample). Returns None if it can't be built (then the sample is simply skipped).'''
        if page not in self._preview:
            self._preview[page] = self._build_preview(ctx, page, ms)
        return self._preview[page]

    def _build_preview(self, ctx, page, ms):
        try:
            if page == 'components':
                return _sample_components_state()           # a STABLE synthetic tree, not the user's
                                                            # real (possibly empty/partial) install set
            if page == 'profiles':
                return _sample_profiles_state(ctx)
            if page == 'plugins':
                return _sample_plugins_state(ctx)
            if page == 'glue':
                return _sample_glue_state(ctx)
            if page == 'dotfiles':
                return _sample_dotfiles_state(ctx)
            if page == 'config':
                return ConfigScreen(ctx)
            if page == 'theme':                                  # the editor previewing itself
                pts = ThemeScreen(ctx)
                pts.focus, pts.map_cur = 'map', 0                # show the map panel's selection
                return pts
        except Exception:                                        # noqa: BLE001 — never break the editor
            return None
        return None

    def reload(self):
        from .theme import COLOR_MAP, resolve_theme
        self.theme = self.ctx.config.theme()
        names = list(COLOR_MAP)
        for n in (self.theme.get('colors') or {}):
            if n not in names:
                names.append(n)                     # user-added map colors after the built-ins
        self.map_names = names
        self.colors, self.pages = resolve_theme(self.theme)      # resolved rgb
        self.map_cur = max(0, min(self.map_cur, len(names) - 1))
        self.role_cur = max(0, min(self.role_cur, len(self.role_list()) - 1))

    def page_name(self):
        from .theme import ALL_PAGES                    # DEMO_PAGES + 'theme' (the editor's own page)
        return ALL_PAGES[self.page]

    def role_list(self):
        from .theme import PAGE_ROLES
        # the roles THIS page uses, plus the two gradient endpoints as single-color pseudo-roles
        return PAGE_ROLES.get(self.page_name(), []) + ['@grad_from', '@grad_to']

    def grad_override(self, which):
        g = ((self.theme.get('pages') or {}).get(self.page_name()) or {}).get('gradient')
        return g.get(which) if isinstance(g, dict) else None

    def grad_ref(self, which):
        '''The authored ref (map name or literal) for a gradient endpoint, else the built-in
        default as a hex — what the user edits.'''
        from .theme import BUILTIN_GRADIENTS
        ov = self.grad_override(which)
        if ov not in (None, ''):
            return ov
        page = self.page_name()
        dflt = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        return _hex(dflt[0 if which == 'from' else 1])

    def grad_rgb(self, which):
        '''The resolved rgb of a gradient endpoint on the focused page (for the swatch).'''
        return self.pages[self.page_name()]['grad'][0 if which == 'from' else 1]

    def cur_color(self):
        return self.map_names[self.map_cur] if self.map_names else None

    def cur_role(self):
        rl = self.role_list()
        return rl[self.role_cur] if rl else None

    def color_override(self, name):
        return (self.theme.get('colors') or {}).get(name)

    def role_override(self, role):
        return ((self.theme.get('pages') or {}).get(self.page_name()) or {}).get(role)

    def role_ref(self, role):
        '''Effective fg/bg refs (map name or literal) for a role = built-in default overlaid by the
        page's override — what the user is editing (before resolution to rgb).'''
        from .theme import ROLE_DEFAULTS
        st = dict(ROLE_DEFAULTS.get(role, {}))
        ov = self.role_override(role)
        if isinstance(ov, dict):
            st.update(ov)
        return st

    def role_style(self, role):
        '''Resolved rgb style {fg, bg, bold, ...} for a role on the focused page (for the swatch).'''
        return self.pages[self.page_name()]['roles'].get(role, {'fg': (235, 235, 235), 'bg': None})

    def page_gradient_enabled(self, page):
        from .theme import is_off
        return not is_off(((self.theme.get('pages') or {}).get(page) or {}).get('gradient'))


def _sample_page(stdscr, pal, ctx, ts, page, y0, x0, hh, ww, ms):
    '''Paint the sample slot as a live, COMPRESSED instance of the REAL page, so a theme edit previews
    exactly as it will look — every element, role, and scroll thumb, and future-robust (it IS the real
    renderer). The Theme editor's OWN page renders the real editor too (with its inner sample slot
    suppressed to avoid recursing).'''
    if hh < 6 or ww < 24:
        return
    _sample_real_page(stdscr, pal, ctx, ts, page, y0, x0, hh, ww, ms)
    pal.use_page('theme')                    # the real draw fn switched the active page; restore it


def _sample_real_page(stdscr, pal, ctx, ts, page, y0, x0, hh, ww, ms):
    '''Render `page` through its REAL Screen (screens/<page>.py build_vm + draw, as the router does)
    into a sub-window over the sample slot, fed a preview-only state object (a real instance, lightly
    augmented so every themeable role shows). The sub-window gives the draw its own 0-based coordinate
    space, so it lays out (and scroll-thumbs) naturally at
    the compressed size. Never raises — a broken preview must not break the Theme editor.'''
    try:
        sub = stdscr.derwin(hh, ww, y0, x0)
    except curses.error:
        return
    try:
        state = ts.preview_state(ctx, page, ms)
        if state is None:
            return
        # Render the sub-page through its REAL Screen (the same build_vm/draw the router uses), fed the
        # preview-only model. A tiny helper paints any vm-driven screen; components/theme take extra
        # frame state. (Lazy imports keep menu<->screens acyclic.)
        from .screens.components import ComponentsScreen
        from .screens.config import ConfigScreen
        from .screens.dotfiles import DotfilesScreen
        from .screens.glue import GlueScreen
        from .screens.plugins import PluginsScreen
        from .screens.profiles import ProfilesScreen
        from .screens.theme import ThemeScreen as _ThemeUI
        size = (hh, ww)

        def _paint(scr):
            vm = scr.build_vm(scr.ctx, size)
            vm.note = ''
            scr.draw(sub, pal, vm)

        if page == 'components':
            scr = ComponentsScreen(ctx, state)
            scr.note, scr.diags = '', ts.preview_diags
            scr.draw(sub, pal, scr.build_vm(ctx, size))
        elif page == 'profiles':
            _paint(ProfilesScreen(getattr(state, 'ctx', ctx), state))
        elif page == 'plugins':
            _paint(PluginsScreen(ctx, state))
        elif page == 'glue':
            _paint(GlueScreen(ctx, state))
        elif page == 'dotfiles':
            _paint(DotfilesScreen(ctx, state))
        elif page == 'config':
            _paint(ConfigScreen(ctx, state))
        elif page == 'theme':                # the editor itself — suppress its own inner sample slot
            try:
                state.reload()               # keep the mini editor's swatches/hexes current after edits
            except Exception:                # noqa: BLE001
                pass
            _tscr = _ThemeUI(ctx, state, sample_ms=ms)
            _tscr.suppress_sample = True
            _paint(_tscr)
    except Exception:                        # noqa: BLE001 — a preview never bricks the editor
        pass


def _ref_str(ref):
    '''Show a role's fg/bg reference as-authored: a map name, a literal, or — for the gradient.'''
    if ref in (None, '', 'none', 'false', False):
        return '—'
    return str(ref)


def _valid_ref(val, map_names):
    '''A role fg/bg / gradient endpoint is valid if it names a map color or parses as a literal.'''
    from .theme import parse_color
    v = (val or '').strip()
    return v in map_names or parse_color(v) is not None
