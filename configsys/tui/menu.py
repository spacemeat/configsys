'''menu.py — the TUI router: `run` (the session loop — screens, overlays, the router keys, the
startup inspection hand-off) and `_route_key`, plus the active keymap the router sets (`_KEYMAP`).

Everything the screens draw with and act through lives in sibling modules (review-2026-11-2 D2):
paint (primitives), modals (modals + overlays), help (the `?` pages), models (the Components
MenuState tree), panes (the other screens' models), preview (the Theme editor + samples), flows
(execute / pick / push), startup (inspection worker, splash, effects). Every name listed in `_MOVED`
still resolves as `menu.<name>` (PEP 562 `__getattr__`).

The Components tree is three levels: a profile (expanded by default) → a component (collapsed) → its
install units; staging is keyed by unit, so a mark is consistent everywhere the unit appears.
'''

import curses

from .. import primarygit
from .screen import curses_screen
from .theme import Palette

# Split into sibling modules (review-2026-11-2 D2). What this module itself uses is imported;
# every other moved name still resolves here (plugins, scripts, tests) via __getattr__ below.
from .paint import _page_rows
from .paint import _busy
from .modals import (
    ListNav, _NAV_ACTIONS, _draw_diagnostics, _draw_where, _help_modal, _issue_flow, _popup_choose,
)
from .models import MenuState, _components_model, _describe, _fold_system_updates
from .startup import (
    SPLASH_THRESHOLD, _InspectWorker, _chosen_splash, _splash_forced, _splash_linger,
    resolve_effects,
)
from .flows import _commit_primary_action, _quit_push, _reload, _seed_uninstall

_KEYMAP = None       # the active tui.keyspec.Keymap (set in run(); paint._keymap() reads it)
# the `!` page's `issues` keymap actions -> the _issue_flow kind each files
_ISSUE_KINDS = {'report': 'report', 'request': 'request', 'suggest-os': 'os'}

_MOVED = {  # name -> the module that defines it
    '_columns': 'paint', '_scroll_top': 'paint', '_scroll_reveal': 'paint',
    '_reveal_subtree': 'paint', '_fit': 'paint', '_put': 'paint', '_wrap': 'paint',
    '_wordwrap': 'paint', '_FILL_BG_SEGS': 'paint', '_fill_bg': 'paint', 'SCREENS': 'paint',
    '_draw_nav': 'paint', '_panel': 'paint', '_thumb': 'paint',
    '_scrollbar_v': 'paint', '_scrollbar_h': 'paint', '_put_hscroll': 'paint', '_busy': 'paint',
    '_hex': 'paint', '_eff_flags': 'paint', '_keymap': 'paint', '_provides_legend': 'help',
    '_PROVIDES_LEGEND': 'help', '_HELP': 'help', '_nav_glyphs': 'modals', '_modal_frame': 'modals',
    '_keep_visible': 'modals', '_report_review': 'modals', '_fuzzy_score': 'modals',
    '_filter_edit': 'modals', '_find_next': 'modals', '_find_edit': 'modals',
    '_find_edit_tree': 'modals', 'ATTR_AXES': 'modals', '_ATTR_AXIS_OF': 'modals',
    '_attr_pass': 'modals', '_attr_filter_modal': 'modals', '_component_machines_modal': 'modals',
    '_machines_modal': 'modals', '_input_box': 'modals', '_order_list': 'modals', 'OPS': 'models',
    '_COMP_OPS': 'models', 'PROFILE': 'models',
    '_REFRESH_WARN_DAYS': 'models', '_is_system_update': 'models', 'Node': 'models',
    '_scope_is_choice': 'models', '_row_component': 'models',
    '_current_via': 'models', '_method_tags': 'models', '_methods_line': 'models',
    '_why': 'models', '_edges_text': 'models', '_identity_line': 'models', '_infoblock': 'models',
    '_is_companion_comp': 'models', '_group_by_owner': 'models',
    'COMPONENT_MODES': 'models', '_TODO_STATUSES': 'models', '_rebuild_menu': 'models',
    '_added_extras': 'models', '_switch_mode': 'models', '_ROUTES_LOCK': 'panes',
    '_routes_lock': 'panes', 'ProfileScreen': 'panes', '_DRIVER_ABBR': 'panes',
    '_setting_str': 'panes', 'ConfigScreen': 'panes', '_PLUGIN_HEADERS': 'panes',
    '_DIFF_ELEM': 'panes', 'PluginScreen': 'panes', '_plugin_tree_prefix': 'panes',
    '_plugin_provides_cell': 'panes', '_plugin_cells': 'panes', '_plugin_remote_elem': 'panes',
    '_plugin_code_elem': 'panes', '_DF_STATE_ELEM': 'panes',
    '_ContentRootLabelMixin': 'panes', 'DotfilesScreen': 'panes', 'GlueScreen': 'panes',
    '_DF_HEADERS': 'panes', '_df_cells': 'panes', '_is_user_glue': 'panes', '_glue_cells': 'panes',
    '_sample_components_state': 'preview', '_SampleCfg': 'preview', '_SampleCtx': 'preview',
    '_sample_profiles_state': 'preview', '_sample_plugins_state': 'preview',
    '_sample_glue_state': 'preview', '_sample_dotfiles_state': 'preview', 'ThemeScreen': 'preview',
    '_sample_page': 'preview', '_sample_real_page': 'preview', '_ref_str': 'preview',
    '_valid_ref': 'preview', '_pretend_note': 'flows', 'execute_plan': 'flows',
    '_summary_note': 'flows', '_TuiPushUI': 'flows',
    '_TuiAutoPushUI': 'flows', '_push_primary': 'flows', '_auto_push_primary': 'flows',
    '_confirm_and_execute': 'flows', '_apply_method_pin': 'flows', '_offer_method_swap': 'flows',
    '_pick_method_name': 'flows', '_providers_of': 'flows',
    '_capability_choices': 'flows', '_apply_provider_pin': 'flows',
    '_pick_provider_cap': 'flows', '_pick_choices': 'flows', '_stage_set_version': 'flows',
    '_fix_scope_row': 'flows', '_is_ssh': 'startup', 'is_ssh': 'startup', '_PACE_CAP': 'startup',
    'COMPONENT': 'models', 'UNIT': 'models', 'LINK': 'models',
}


def __getattr__(name):
    '''A name that moved out of this module (PEP 562) keeps resolving here.'''
    mod = _MOVED.get(name)
    if mod is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    import importlib
    return getattr(importlib.import_module(f'.{mod}', __package__), name)


def _route_key(keymap, screen, ch):
    '''How the router resolves one key on `screen` -> (router_action, dest_screen); (None, None) means
    "hand it to the screen's handle". The screen's OWN scope is consulted first (Keymap.own_action):
    a key the screen binds goes to the screen even when `global`'s quit/quit-force/issues/help or the
    `screens` switcher also claims it, and a screen-scope binding of one of those four actions is
    the router's to act on, on that screen. Otherwise: `global` (router actions only), then
    `screens`. With the shipped config.hu no screen binds those keys, so this is the old
    global-then-screens order.'''
    from .keyspec import ROUTER_ACTIONS
    own = keymap.own_action(screen, ch)
    if own is not None:
        return (own, None) if own in ROUTER_ACTIONS else (None, None)
    gact = keymap.action_for('global', ch)
    if gact in ROUTER_ACTIONS:
        return gact, None
    return None, keymap.screen_for(ch)



_GLUE_HEADERS = ['component', 'state', 'conf.d', 'source']




def run(ctx):
    '''Entry point used by cli.ops.cmd_tui. Returns an exit code.'''
    # First-run config generation + the interactive primary-plugin offer must happen on the MAIN
    # thread, in the normal terminal, BEFORE the worker/curses — it prompts on stdin, which would
    # collide with the background load and curses init. load_pipeline's own call then no-ops.
    ctx.ensure_user_config(offer_primary=True)
    effects = resolve_effects(ctx)                # 'full'|'reduced'|'none' -> stamps CONFIGSYS_EFFECTS
    splash_on, splash_name = _chosen_splash(ctx)  # (which the Palette gradient + this splash choice read)
    # A PLUGIN splash must be registered before we can construct it, and the splash is chosen before
    # the worker joins — so register trusted plugin code up front, on the main thread, ONLY when a
    # plugin splash is actually selected (the built-in default needs nothing). Doing it
    # unconditionally serialized plugin loading ahead of inspection for everyone. Idempotent, so the
    # worker's own later call no-ops; skipping it here lets the worker load it lazily instead.
    from .splash import DEFAULT_SPLASH
    if splash_on and splash_name and splash_name != DEFAULT_SPLASH:
        ctx.ensure_plugin_code()
    # Inspect on a worker thread; only paint the splash if it's still going after a short beat
    # ("only when there's work" — a warm/fast run skips straight to the menu), unless forced.
    worker = _InspectWorker(ctx).start()
    if not splash_on:
        show_splash = False
    elif _splash_forced(ctx):
        show_splash = True                       # skip the timing gate entirely
    else:
        show_splash = worker.wait_settled(SPLASH_THRESHOLD)

    splash_note = None
    pending_report = None                     # a component whose op failed this session
    pending_notes = []                        # messages saved for after the TUI exits
    finished = False                          # the loop ended normally (q / Q), not by an exception
    from .screen import terminfo_cache_dir
    try:
        with curses_screen(terminfo_cache_dir(ctx.paths), ctx.runner.pretend) as stdscr:
            ctx.reporter.pause()          # curses owns the screen now; don't stream to stderr
            pal = Palette(ctx.config.theme())
            if show_splash:
                import random
                from .splash import DEFAULT_SPLASH, run_splash   # importing registers the built-in default
                from ..splashes import get_splash, random_splash
                if splash_name == 'random':              # surprise me: any registered splash but the default
                    splash_name = random_splash(exclude=DEFAULT_SPLASH) or DEFAULT_SPLASH
                provider = get_splash(splash_name) if splash_name else get_splash(DEFAULT_SPLASH)
                if provider is None:
                    if splash_name:                  # named but not registered/trusted -> default + note
                        from .. import plugins as _pl
                        _decls = _pl.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
                        hint = _pl.splash_value_hint(splash_name, ctx.paths.plugins_dir, _decls)
                        splash_note = hint or f"splash '{splash_name}' unavailable — using '{DEFAULT_SPLASH}'"
                    provider = get_splash(DEFAULT_SPLASH)   # the trust-free in-core default
                run_splash(stdscr, pal, provider, label=worker.phase_label,   # tracks the live phase
                           is_done=worker.done, frac=worker.frac, counts=worker.counts,
                           seed=random.randrange(1 << 30), linger=_splash_linger(ctx),
                           fps_cap=(15 if effects in ('reduced', 'none') else None))   # calmer bar
                # The splash allocated a run-varying number of RANDOM color slots + pairs into `pal`
                # (its water/fish palette). Rebuild the Palette so the menu starts from a clean,
                # deterministic allocator — otherwise those random colors leak into the UI and, on a
                # small-COLOR_PAIRS terminal, shift which theme colors survive every run.
                pal = Palette(ctx.config.theme())
            cfg, _requested, _units, ledger, states = worker.join()   # re-raises load errors, if any
            # Re-assert curses input modes before the interactive loop: a startup probe that briefly
            # inherited the tty (or a splash quirk) must never leave us in cooked/echo mode.
            curses.noecho()
            curses.cbreak()
            stdscr.keypad(True)
            from .keyspec import Keymap
            # the screens (lazy import: avoids an import cycle). Several share a name with their MODEL
            # class in panes/preview (GlueScreen, DotfilesScreen, ConfigScreen, ThemeScreen); within
            # run() these names are the Screens — the models are composed inside them.
            from .screens.plugins import PluginsScreen
            from .screens.glue import GlueScreen
            from .screens.dotfiles import DotfilesScreen
            from .screens.config import ConfigScreen
            from .screens.profiles import ProfilesScreen
            from .screens.theme import ThemeScreen
            from .screens.components import ComponentsScreen
            global _KEYMAP
            # merged bindings (rebind-wins across layers); legends read the same map
            _KEYMAP = keymap = Keymap(ctx.config.keys())
            comp_mode = 'to-do'                       # Components view MODE: to-do | tracked | installed+tracked
            _mode_caches = {}                         # overlay-enumeration bundle, reused across mode switches
            states, layouts, transitive = _components_model(ctx, cfg, states, comp_mode, caches=_mode_caches)
            ms = MenuState(states, layouts, transitive)
            ms.mode = comp_mode
            ms._overlay_caches = _mode_caches
            ms._req_sig = frozenset(_requested)       # the install set this tree was built for (matrix picks)
            _seed_uninstall(ms, ctx)                  # surface the persisted !uninstall queue as staged removes
            ms._uninstall_q = set(ctx.config.uninstall_queue())
            ms.descriptions = _describe(ctx)          # {name -> desc}, cached; not touched per frame
            from .. import rebootcheck                 # (reboot, reason) cached ONCE — the header chip reads
            ctx._primary_state = primarygit.state(ctx)  # the header's ↑/↓ chip (local; Plugins fetches)
            ctx._primary_push_mode = primarygit.push_mode(ctx)
            ctx._reboot_pending = (rebootcheck.reboot_pending(ctx)   # it per frame; never re-probe in a draw
                                   if ctx.config.reboot_advice() else (False, ''))
            diags = ctx.diagnostics(states)
            if hasattr(ctx, 'start_check_lints'):
                ctx.start_check_lints()                      # `check`'s lints join `!` when they land (G2)
            note = splash_note or ''
            show_diag = False
            diag_top = 0
            show_where = False                        # `w` full-page: the complete where-report for a row
            where_lines, where_top, where_subject = [], 0, ''
            screen = 'components'
            # The screen router: one Screen per id, built lazily on first visit (components is the default
            # and holds the live MenuState). The router feeds each screen the frame state it needs
            # (ms/note/diags/sample_ms) right before build_vm/draw.
            _reg = {}

            def _screen(sid):
                s = _reg.get(sid)
                if s is None:
                    s = _reg[sid] = (ComponentsScreen(ctx, ms) if sid == 'components' else
                                     {'profiles': ProfilesScreen, 'plugins': PluginsScreen,
                                      'glue': GlueScreen, 'dotfiles': DotfilesScreen,
                                      'config': ConfigScreen, 'theme': ThemeScreen}[sid](ctx))
                return s
            menu_dirty = False                        # a profile/config edit -> rebuild the Components tree

            def _enter(dest):
                '''Switch to screen `dest` — from a screen key OR a handle's Intent(goto=…): rebuild
                the Components tree when what it was built for changed (an edit, the !uninstall
                queue, the picks), and re-read Dotfiles / Glue link state on entry. -> `dest`.'''
                nonlocal ms, cfg, ledger, states, diags, menu_dirty, note
                # dotfiles/glue mutated on their pages (link/activate) -> re-probe those units so
                # Components doesn't show stale 'managed'/'adopted' after they're now linked.
                _dscr, _gscr = _reg.get('dotfiles'), _reg.get('glue')
                df_dirty = ((_dscr.model.dirty if _dscr is not None else set())
                            | (_gscr.model.dirty if _gscr is not None else set()))
                # the !uninstall queue can change from OTHER screens (Profiles `x`) or drain, so
                # rebuild whenever it differs from what this view last folded — not just on edits.
                q_changed = (set(ctx.config.uninstall_queue())
                             != getattr(ms, '_uninstall_q', frozenset()))
                # the matrix's picks (and the current-machine switch) change the install set; rebuild
                # Components whenever the requested set no longer matches what its tree was built for.
                try:
                    req_changed = frozenset(ctx.config.requested()) != (getattr(ms, '_req_sig', None) or frozenset())
                except Exception:                     # noqa: BLE001 — a bad config shouldn't block a switch
                    req_changed = True
                if dest == 'components' and (menu_dirty or df_dirty or q_changed or req_changed):
                    _busy(stdscr, pal, 'rebuilding…')   # a synchronous re-probe: say so first
                    try:
                        # re-resolve + re-probe newly-appearing/changed units (a membership,
                        # driver-preference or scope edit can add units or change how they
                        # resolve) plus the dotfiles units just mutated; reuses the rest and
                        # preserves selection/staging/expansion.
                        ms, cfg, ledger, states, diags = _reload(ctx, ms, set(df_dirty))
                    except Exception as e:  # noqa: BLE001 — surface, don't crash
                        note = f'reload failed: {e}'
                    menu_dirty = False
                    if _dscr is not None:
                        _dscr.model.dirty = set()
                    if _gscr is not None:
                        _gscr.model.dirty = set()
                if dest == 'dotfiles' and _dscr is not None:  # re-read link state on entry — an
                    _dscr.reload()                            # install/capture elsewhere may have changed it
                if dest == 'glue' and _gscr is not None:      # re-read glue state on entry likewise
                    _gscr.reload()
                if dest == 'theme' and _reg.get('theme') is not None:   # a Config edit elsewhere ->
                    _reg['theme'].sync_config(ctx)                     # re-read the theme on entry
                return dest

            from .. import sysupdates
            sysupdates.start_scan(ctx)                # gather the whole-machine update set in the background;
                                                      # the System Updates group folds in when it lands
            while True:
                ctx._frame = getattr(ctx, '_frame', 0) + 1   # a monotonic frame tick for animation
                # (e.g. the System Updates spinner) — advanced by the loop, NOT read from the clock in
                # draw, so draw stays a pure function of state (the render-determinism contract).
                pal.new_frame()          # recycle color pairs each frame (color_pair() is 8-bit; a
                # long session or the pair-heavy Theme screen would otherwise exceed 255 pairs and wrap
                if show_where:
                    where_top = _draw_where(stdscr, pal, where_lines, where_top, where_subject)
                elif show_diag:
                    diag_top = _draw_diagnostics(stdscr, pal, diags, diag_top)
                else:
                    scr = _screen(screen)
                    try:
                        if screen == 'components':
                            scr.model, scr.note, scr.diags = ms, note, diags   # the live tree + frame inputs
                            scr.render(stdscr, pal, ctx)
                        else:
                            if screen == 'theme':
                                scr.sample_ms = ms     # the live Components state for its bottom sample slot
                            scr.render(stdscr, pal, ctx, note)   # + the transient note the router owns
                    except curses.error:
                        pass                           # a resize mid-paint: the next frame repaints
                    except Exception as e:             # noqa: BLE001 — a paint bug shows, never crashes (B16)
                        try:
                            stdscr.erase()
                            stdscr.addnstr(0, 0, f'configsys: the {screen} screen failed to draw — '
                                                 f'{type(e).__name__}: {e}  (1-7 switch screens, q quits)',
                                           max(1, stdscr.getmaxyx()[1] - 1))
                        except curses.error:
                            pass
                note = ''
                # While the Profiles install-overlay's background orphan scan is running, poll (timed
                # getch) so its result paints on its own; otherwise block. Restore blocking immediately
                # after so the modal getch loops are unaffected.
                _pscr = _reg.get('profiles')
                # Poll while the System Updates scan is running OR its result is pending consumption —
                # so the fold fires on its own even if the scan finishes between two poll ticks (else it
                # would wait for the next keypress).
                _su_busy = screen == 'components' and (sysupdates.scan_busy(ctx)
                                                       or getattr(ctx, '_sysupd_dirty', False))
                _plscr = _reg.get('plugins')                 # remote-refs / a review diff still fetching
                _pl_busy = screen == 'plugins' and _plscr is not None and _plscr.model.busy()
                _ck_busy = getattr(ctx, 'check_busy', lambda: False)()
                stdscr.timeout(120 if (_su_busy or _pl_busy or _ck_busy or (screen == 'profiles' and _pscr is not None
                                       and (_pscr.model.overlay_busy() or _pscr.model.probe_busy()
                                            or _pscr.model.os_busy()))) else -1)
                ch = stdscr.getch()
                stdscr.timeout(-1)
                if ch == -1:                                 # timed out with no key -> just redraw
                    if _pl_busy:                             # a remote-ref landed -> fetch/show its diff
                        try:
                            _plscr.model.load_diff()
                        except Exception as e:               # noqa: BLE001
                            note = f'error: {e}'
                    # the background System Updates scan just landed -> fold its group into the tree.
                    # Only the TREE changes (install state didn't), so rebuild it from the states we have
                    # (_rebuild_menu, ~10ms) — NOT _reload, which re-runs the load pipeline + diagnostics
                    # (~6s on a full machine) on this, the UI thread: the freeze right after the splash.
                    if getattr(ctx, '_check_dirty', False):   # the background `check` pass landed
                        ctx._check_dirty = False
                        try:
                            diags = ctx.diagnostics(states)
                        except Exception as e:               # noqa: BLE001
                            note = f'check lints failed: {e}'
                    if sysupdates.take_dirty(ctx):
                        try:
                            ms, states = _fold_system_updates(ctx, cfg, ms)   # drawn next frame
                        except Exception as e:               # noqa: BLE001 — never crash on the fold-in
                            note = f'system-updates fold failed: {e}'
                        # its advisories (a manager's list may be incomplete) join the `!` page here,
                        # since diagnostics aren't recomputed for a fold
                        diags = [d for d in diags if d.get('tag') != 'system-updates'] + [
                            {'level': 'warn', 'tag': 'system-updates', 'text': n}
                            for n in getattr(ctx, '_sysupd_notes', None) or ()]
                    continue

                oact = keymap.action_for('components', ch)   # overlays scroll via the same nav actions
                if show_where:                              # where overlay: scroll or exit
                    if (oact in ('where', 'quit') or ch == 27
                            or keymap.action_for(screen, ch) in ('where', 'quit')):   # the opening key
                        show_where = False
                    elif oact in _NAV_ACTIONS:               # the limit is clamped by _draw_where
                        where_top = ListNav.apply(oact, where_top, 10 ** 6, _page_rows(stdscr))
                    continue

                if show_diag:                               # diagnostics overlay: scroll, file an issue, or exit
                    if (oact in ('issues', 'quit') or ch == 27
                            or keymap.action_for(screen, ch) in ('issues', 'quit')):
                        show_diag = False
                    elif keymap.action_for('issues', ch) in _ISSUE_KINDS:   # file an issue, in-TUI
                        _n = _issue_flow(stdscr, pal, ctx, _ISSUE_KINDS[keymap.action_for('issues', ch)],
                                         pending_report)
                        if _n is not None:                  # sent / reviewed (None = cancelled at the prompt)
                            note, show_diag = _n, False
                    elif keymap.action_for('issues', ch) == 'help':
                        _help_modal(stdscr, pal, 'issues')
                    elif oact in _NAV_ACTIONS:               # the limit is clamped by _draw_diagnostics
                        diag_top = ListNav.apply(oact, diag_top, 10 ** 6, _page_rows(stdscr))
                    continue

                # -- router keys, resolved through the keymap. The screen's OWN scope is consulted first:
                # a key the screen binds itself goes to the screen (even one `global`'s quit/issues/help
                # or the `screens` switcher would claim), and a screen-scope binding of quit/quit-force/
                # issues/help works on that screen. With the shipped config no screen binds those keys,
                # so this reads exactly as global-then-screens did.
                gact, dest = _route_key(keymap, screen, ch)
                if gact == 'quit-force':                     # leave immediately, no confirm (harder to hit)
                    pending_notes.extend(_quit_push(stdscr, pal, ctx, force=True)[1])
                    finished = True
                    break
                if gact == 'quit':                          # confirm before leaving; esc no longer quits
                    _leave, _qnotes = _quit_push(stdscr, pal, ctx)   # primary-push: ask / auto / auto-on-quit
                    if _leave is None:
                        _leave = _popup_choose(stdscr, pal, 'Really quit?',
                                               [('Yes, quit', ''), ('No, keep working', '')], start=1,
                                               shortcuts={'y': 0, 'n': 1}) == 0
                    if _leave:
                        pending_notes.extend(_qnotes)
                        finished = True
                        break
                    continue
                if gact == 'issues':                        # the `!` page: diagnostics + file an issue
                    show_diag, diag_top = True, 0            # open even with no diags — it's also the
                    continue                                # report / request / suggest-OS hub
                if gact == 'help':
                    _help_modal(stdscr, pal, screen)
                    continue
                if dest is not None:
                    screen = _enter(dest)
                    continue

                # -- per-screen input: every screen's handle() returns an Intent the router applies to
                # the shared loop state; the components handle also gets cfg/ledger and re-probes/rebinds.
                scr = _screen(screen)
                _act = keymap.action_for(screen, ch)
                _snap = primarygit.snapshot(ctx)      # every key's write journal (free until something writes)
                try:
                    if screen == 'components':
                        scr.model = ms
                        intent = scr.handle(ch, ctx, stdscr, pal, cfg, ledger)
                    else:
                        intent = scr.handle(ch, ctx, stdscr, pal)
                except Exception as e:                # noqa: BLE001 — one bad key never ends the session (B16):
                    # a half-typed config edited in another terminal, a plugin bug — say so, keep staged work
                    from .screens.base import Intent
                    intent = Intent(note=f'error: {type(e).__name__}: {e}')
                if intent.note is not None:
                    note = intent.note
                _cnotes = _commit_primary_action(ctx, _snap, screen, _act, intent.note) if _snap else []
                if _snap is not None and _snap.recorded:   # the action wrote into the primary
                    ctx._primary_state = primarygit.state(ctx)          # the chip / Plugins row follow it
                    ctx._primary_push_mode = primarygit.push_mode(ctx)  # (a Config edit may change it)
                    if _reg.get('plugins') is not None:
                        _reg['plugins'].model.primary_state = ctx._primary_state
                    if _cnotes:
                        note = (f'{note}  ·  ' if note else '') + _cnotes[0]
                        pending_notes.extend(_cnotes)
                menu_dirty = menu_dirty or intent.dirty
                if intent.goto is not None:
                    screen = _enter(intent.goto)          # the same entry work as a screen key
                if intent.new_pal is not None:
                    pal = intent.new_pal          # Theme live-preview edit rebuilt the palette
                if intent.open_where is not None:
                    where_lines, where_subject = intent.open_where
                    where_top, show_where = 0, True
                if intent.pending_notes:
                    pending_notes.extend(intent.pending_notes)
                if intent.pending_report is not None:
                    pending_report = intent.pending_report
                if intent.reloaded is not None:
                    ms, cfg, ledger, states, diags = intent.reloaded
                if intent.remodeled is not None:
                    ms, states, layouts, transitive = intent.remodeled
                if intent.invalidate_ps_overlay:
                    _psx = _reg.get('profiles')
                    if _psx is not None:
                        _psx.model.invalidate_overlay()
    finally:
        # also on Ctrl-C / an escaping error: the console comes back and the held notes still print
        ctx.reporter.resume()         # back on the console (endwin has restored the terminal)
        if finished:
            ctx.report_session_summary(cfg, states, diags)   # -v+: leave a recap in the scrollback
        for msg in dict.fromkeys(pending_notes):   # held back so they don't interrupt the TUI; once each
            print(f'configsys: {msg}')
        if pending_report:            # an op failed; its output is captured and persisted
            print(f'configsys: an op failed — run `configsys report {pending_report}` to file it '
                  f'(OS + route + captured output; you approve the full text first).')
    return 0
