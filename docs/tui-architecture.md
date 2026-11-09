# TUI architecture

> **Status: REFERENCE** — how the TUI is built; maintained.

The TUI (`configsys tui`, or no command at all: `cli.ops.cmd_tui` → `configsys/tui/menu.py` `run`;
`inspect` output instead when stdin/stdout isn't a terminal) is a curses app built as a small router
over seven screens. Each screen follows one protocol (build a view model, paint it, handle a key),
paints through a `Surface` so it can render without a terminal, and dispatches on keymap **actions**,
not raw key codes. User-facing look and keys are covered in [theming.md](theming.md) and
[config-format.md](config-format.md#theme-and-keys); splash code plugins in
[plugins.md](plugins.md#7b-other-hooks). The cross-cutting rules (no surprises, sudo/TTY handling)
are in [principles.md](principles.md).

## Module map

| Module | Holds |
|---|---|
| `tui/menu.py` | the router: `run` (the session loop), `_route_key`, the active keymap `_KEYMAP`, and a PEP 562 `__getattr__` facade (`_MOVED`: name → defining module) so every name that moved to a sibling still resolves as `menu.<name>` |
| `tui/paint.py` | paint primitives: `_put`, `_fit`, `_wrap`/`_wordwrap`, `_panel`, scrollbars (`_scrollbar_v`/`_scrollbar_h`, `_put_hscroll`), `_scroll_top`/`_reveal_subtree`, `_fill_bg` (the gradient), `SCREENS` + `_draw_nav` (row-0 chips), `_busy`, and `_keymap()` (the router's keymap, else the one `config.hu` ships) |
| `tui/modals.py` | every modal and overlay: `_modal_frame` (the one box), `ListNav` + `_NAV_ACTIONS` (keymap-aware movement), `_keep_visible`, `_popup_choose`, `_input_box`, `_order_list`, `_filter_edit`, `_find_edit*`, the attr filter and machine modals, the overlays `_help_modal` (`?`), `_draw_diagnostics` (`!`), `_draw_where`, and `_issue_flow` |
| `tui/help.py` | `_HELP` (each screen's `?` description + glossary) and `help_page`, which renders `{scope:action}` placeholders through the live keymap |
| `tui/models.py` | the Components model: `MenuState`, `Node`, `OPS`, `COMPONENT_MODES`, `_TODO_STATUSES`, `_components_model`, `_fold_system_updates`, `_rebuild_menu`, `_switch_mode`, and the row helpers it paints from (`_identity_line`, `_methods_line`, `_infoblock`) |
| `tui/panes.py` | the other screens' models: `ProfileScreen`, `PluginScreen`, `GlueScreen`, `DotfilesScreen`, `ConfigScreen`, their cell helpers, and `_ROUTES_LOCK` |
| `tui/preview.py` | the Theme editor's model (`ThemeScreen`), `_sample_page` / `_sample_real_page`, and the hand-built `_sample_*_state` fixtures the previews and render tests paint |
| `tui/flows.py` | multi-step actions: `_confirm_and_execute` / `execute_plan`, `_reload`, `_seed_uninstall`, the method/provider pickers and pins, `_pretend_note`, the primary write-journal commit (`_commit_primary_action`) and push (`_TuiPushUI`, `_quit_push`) |
| `tui/startup.py` | `_InspectWorker`, `SPLASH_THRESHOLD`, `_chosen_splash`, `resolve_effects`, `is_ssh` |
| `tui/screens/base.py` | the protocol: `Screen` (`build_vm`/`draw`/`handle`, `render`/`commit`, `begin_page`/`end_page`), `ViewModel` (`settle`), `Intent`, and the bulk-note helpers `results_note`/`result_ok` |
| `tui/screens/<id>.py` | one `<Id>Screen` + `<Id>VM` per screen: `components`, `profiles`, `plugins`, `glue`, `dotfiles`, `config`, `theme` |
| `tui/screens/table.py` | `layout` + `draw_table`, the one table painter Plugins, Glue and Dotfiles share |
| `tui/surface.py` | `BufferSurface`, `Cell` |
| `tui/keyspec.py` | key-name parsing, `Keymap`, `merge_layer_keys`, `ROUTER_ACTIONS`, `KNOWN_ACTIONS`, `ACTION_LABELS`, `lint_keys` / `lint_merged` |
| `tui/theme.py` | `COLOR_MAP`, `BASIC_MAP`, `ROLE_DEFAULTS`, `PAGE_ROLES`, `BUILTIN_GRADIENTS`, `THEME_SECTIONS`, `theme_problems`, `resolve_theme`, `full_snapshot`, `Palette`, `STATUSES`, `SCREEN_REGISTRY`, `env_color_cap`/`env_effects` |
| `tui/screen.py` | curses lifecycle: `curses_screen`, `suspended`, Return/Ctrl-J separation, direct-color terminfo selection |
| `tui/terminfo.py` | pure-Python compiled-terminfo reader/writer (builds a `-direct` entry without `tic`) |
| `tui/splash.py` | the splash host loop `run_splash` + the built-in `braille-bar` (`BrailleBarSplash`) |
| `splashes.py` | the curses-free splash ABI: `Splash`, `SplashFrame`, `register_splash`, `get_splash` |

`menu.py` was split into those siblings in the 2026-11 review (D2; plan
[docs/done/split-app-menu-plan.md](done/split-app-menu-plan.md)). In-package code imports the
defining module; the facade exists for plugins, scripts and tests that still say `menu.<name>`.
The screen modules compose their model classes as `self.model` (`screens/profiles.py` imports
`panes.ProfileScreen as _ProfilesModel`, etc.); the like-named `screens.*` classes and model classes
are distinct objects. Screen modules import `menu` (for `_keymap`, `ListNav`, …) freely; `menu`
imports the screen modules lazily inside `run`, and `preview` inside `_sample_real_page`, to stay
acyclic.

## The screen protocol

`Screen` (base.py) has a class attribute `id` — both the router key and the keymap scope — and three
seams:

- **`build_vm(ctx, size) -> ViewModel`** — settles the whole frame from the model, `ctx` and `size`
  (the `(h, w)` from `getmaxyx()`): text, positioned cells, element roles, scroll offsets. No curses.
  The work a frame needs beyond the model happens here, never in `draw`: Profiles folds a finished
  background overlay scan (and may start one) and reads the cached coverage hint; Components reads the
  refresh age. (Theme's re-read of a changed `ctx.config` is not here: its `sync_config` runs after
  each key and on entering the screen.)
- **`draw(surface, pal, vm)`** — paints the VM and nothing else: palette concerns only (the selection
  fill, reverse video on a low-colour terminal). **A draw writes nothing on the model and starts no
  work.** What the frame's geometry settles (a scroll offset clamped to the panel height, a
  horizontal-scroll limit, the page size PgDn moves by) it records with `vm.settle(**attrs)`.
- **`handle(ch, ctx, stdscr, pal) -> Intent`** — one key. Components' signature adds `cfg, ledger`
  (it re-runs the load pipeline). `handle` mutates the model and may run modal loops inline
  (`_popup_choose`, `_input_box`, the `suspended` confirm/execute prompt); a modal that live-filters
  gets a redraw callback that re-renders the screen.

`Screen.render(surface, pal, ctx, note=None)` is one frame: `build_vm` → stamp `vm.note` (the
transient status note the router owns) → `draw` → `commit(vm)`. `commit` applies `vm.settle(...)` to
the model, and is where a screen starts post-paint work (Profiles probes the rows it just showed and
requests the coverage hint for an unavailable cursor component — both off the UI thread). The router
calls `render`; a preview (the Theme samples) calls `build_vm` + `draw` only. Components receives its
note and diagnostics as `ComponentsScreen.note`/`.diags` (the router sets them before `render`), so
its `build_vm` carries them on `ComponentsVM`.

`begin_page(surface, pal)` paints what every page opens with — erase, `pal.use_page(self.id)`, the
gradient background, the row-0 chips — and returns `(h, w)`; `end_page(surface, pal, status,
legends, h, w)` paints the status row above the bottom legend rows and refreshes. Every screen's
list movement is one `ListNav.apply` call (page size asked lazily).

Since the D7 refactor every screen's VM is complete: Components (`ComponentsVM`: title-row chips,
column header, the visible tree rows as positioned cells, the three cursor lines, status, legends)
and Profiles (`ProfilesVM`: panel geometry, the profile tree's rows, the detail box, the catalog
matrix as positioned cells) paint from it alone — a hand-built literal VM renders with no ctx or
model (`test_draw_paints_a_hand_built_vm` in `test_screen_components.py` / `test_screen_profiles.py`).
The table screens build a table VM (`headers`, `cells`, `widths`/`xs`/`virt_w` from `table.layout`,
`elems`, `display`) and paint it with `table.draw_table`, which returns the clamped `(top,
hscroll)` and page height for the screen to `settle`. Theme's draw still reads its model's cursor and
focus (read-only) and renders the live sample through `_sample_page`.

The invariant the tests lean on: **draw is a deterministic function of (vm, palette) and writes
nothing** (`test_tui_modals.py::test_draw_leaves_the_model_untouched`, all seven screens). Nothing in
a paint path reads the clock or probes the system — the Components header's System Updates spinner
indexes `ctx._frame`, a tick the loop advances; the reboot chip reads `ctx._reboot_pending`, probed
once at start and after an execute; the primary chip reads `ctx._primary_state`; descriptions come
from `ms.descriptions`, cached by `_describe`. VM memoization was measured unnecessary: frames
repaint only on a key or while a background job polls, at about 23 ms (Profiles) and 13 ms
(Components) per frame.

**Config-editing keys under `--pretend`.** Every actions-level config writer refuses under `--pretend`
(returns `actions.PRETEND_NOT_SAVED` instead of writing), so a screen that edits config routes its
status note through `flows._pretend_note(ctx, note, wrote)`: under a dry run it reads
"[pretend] not saved (--pretend) — would: …" rather than claiming the edit happened. A bulk action's
note is built from its results, never its intent (`base.results_note`: "activated 5 of 6 — fd-glue
failed: …", or "[pretend] nothing changed — would have: …"). `test_tui_pretend_sweep.py` drives every
screen-scope action key of all seven screens under `--pretend` and fails on any file change.

**Glue screen user glue.** `GlueScreen._user_rows` adds your own user.d snippets
(`Glue.user_glue_entries`) to each installed shell's group, after its component glue, as 7-tuples
flagged `True` (`panes._is_user_glue`); a snippet whose conf.d link is missing reads `inactive`
(state `unlinked`). They aren't units: `a` relinks that shell's user.d namespace
(`Glue.deploy_user_glue`), `A` also relinks it with the group, and `x` only explains that configsys
never edits user glue. `n`, `o` and `S` are the TUI side of `glue add`, `glue override` and the
staged shell-writes review. See [shell-glue.md](shell-glue.md).

**`Intent`** is how a key asks for effects the router owns, so the shared loop state has one owner:
`note`, `goto` (switch screen), `dirty` (rebuild the Components tree on the next visit), `new_pal`
(Theme edits rebuild the `Palette`), `open_where` (`(lines, subject)` for the full-page `where`
overlay), `pending_notes` (printed after the TUI exits), and the Components-only `reloaded` (`(ms,
cfg, ledger, states, diags)` from `_reload`), `remodeled` (`(ms, states, layouts, transitive)` from
a view-mode switch), `pending_report` (a failed op's component, for the post-quit `configsys report`
nudge) and `invalidate_ps_overlay`. There is no "handled" flag and no quit field: the router resolves
its own keys *before* the screen sees the key (below), so every key that reaches `handle` is the
screen's to consume, and leaving goes through the `quit` / `quit-force` router actions.

## Router and event loop (`menu.run`)

Startup, in order: `ctx.ensure_user_config(offer_primary=True)` on the main thread (it prompts on
stdin, so it must precede curses and the worker) → `resolve_effects` → `_chosen_splash`
(`ctx.ensure_plugin_code()` up front *only* when a non-default splash is selected) →
`_InspectWorker(ctx).start()` runs `load_pipeline` on a thread → the splash is shown if inspection
outlasts `SPLASH_THRESHOLD` (0.25 s) or `CONFIGSYS_SPLASH=always`/`linger` (`--splash-linger`) →
enter `curses_screen(terminfo_cache_dir(ctx.paths), pretend)` → `ctx.reporter.pause()` → build the
`Palette` → run the splash, then rebuild the `Palette` (the splash's colour allocations are
discarded) → `worker.join()` (re-raises load errors) → re-assert noecho/cbreak/keypad → build the
`Keymap` from `ctx.config.keys()`, the Components model and the first `MenuState`; seed the
uninstall queue; cache descriptions, the primary state and push mode, and the reboot check → compute
diagnostics and `ctx.start_check_lints()` → `sysupdates.start_scan`.

**Screens.** `paint.SCREENS` (from `theme.SCREEN_REGISTRY`) lists `(key, id, title)` for the row-0
chip bar (`_draw_nav`; chip glyphs come from the keymap's `screens` scope, so a rebind shows). Screens
are built **lazily** by `_screen(sid)` into `_reg = {id: Screen}` on first visit and then live for
the session (model state — cursor, filters, caches, threads — persists across switches). Components
is built over the live `MenuState`; the router re-assigns `scr.model = ms` each frame, because `ms` is
rebound by reloads. Theme additionally gets `sample_ms = ms` for its sample slot.

**Each iteration:** bump `ctx._frame`; `pal.new_frame()` (curses `color_pair()` encodes 8 bits, so
pairs are recycled per frame — colour slots persist); draw the where overlay, the `!` diagnostics
overlay, or the current screen (`scr.render`). A `curses.error` mid-paint (a resize) is ignored; any
other paint exception shows a one-line error instead of ending the session. Then read one key. The
`getch` blocks, except it polls at 120 ms while background work must paint on its own: on
Components while the System Updates scan runs or its result is unconsumed; on Plugins while
remote-refs or a review diff are still fetching (`PluginScreen.busy`); on Profiles while
`overlay_busy()` / `probe_busy()` / `os_busy()`; and on any screen while the background `check`
lints run (`ctx.check_busy()`). A timeout (`-1`) lets Plugins show a landed diff (`load_diff`),
recomputes the diagnostics when the `check` lints landed (`ctx._check_dirty`), folds a landed System
Updates scan (plus its advisories into the `!` page), and redraws.

**Key resolution order** (`menu._route_key` after the overlays): overlay keys first (where /
diagnostics, scrolled via the `components` scope's nav actions; Esc, `quit`, or the key that opened
the overlay closes it, even when the screen rebinds `where`/`issues`; on the `!` page the `issues`
scope's `report` / `request` / `suggest-os` run `_issue_flow` and `help` opens its help) → the
current screen's **own** scope (`Keymap.own_action`, no fall-back to `global`): a key the screen
binds goes to its `handle` even when `global` or `screens` also claims it, and a screen-scope binding
of a router action is acted on by the router on that screen → `global` scope, router actions only
(`keyspec.ROUTER_ACTIONS`: `quit-force`, `quit` with a confirm popup, `issues`, `help`) → `screens`
scope (`Keymap.screen_for`) → the current screen's `handle`. With the shipped `config.hu` no screen
binds a router or screen-switch key, so this reads as global-then-screens. Both quit actions go
through `flows._quit_push` first, which applies the `primary-push` policy (`primarygit.PUSH_POLICY`)
to unpushed primary commits.

**Each handled key** runs inside a primary write-journal bracket: `primarygit.snapshot(ctx)` before
`handle`, `flows._commit_primary_action` after it (commit message `<screen>: <action label> — <note>`;
see [plugins.md](plugins.md)). When the action wrote into the primary, the router refreshes
`ctx._primary_state` / `ctx._primary_push_mode` (and the Plugins row). An exception in `handle`
becomes an `error:` note; staged work is kept.

On entering Components (`_enter`) the router reloads (`_reload`, behind a "rebuilding…" note) if any
of: an Intent set `dirty`, the Dotfiles/Glue models report mutated units (`model.dirty`), the
uninstall queue differs from `ms._uninstall_q`, or `config.requested()` differs from `ms._req_sig`
(picks or the current machine changed). Entering Dotfiles/Glue calls their `reload()` (link state
may have changed elsewhere), entering Theme its `sync_config` (the theme re-read when `ctx.config`
changed). After the loop exits (also on Ctrl-C or an escaping error):
`reporter.resume()`, the session summary (on a normal quit), each `pending_notes` line once, and a
`configsys report` nudge if an op failed.

## Components: `MenuState`

`MenuState(states, layouts, transitive)` — `states` = `{unit_key: ComponentState}`; `layouts` =
`[(profile, [items])]`, an item a component name or `('include', name)` (rendered as a LINK node to
`p:<name>`); `transitive` = `{profile: [all transitive names]}`. `_build_tree` makes PROFILE → COMPONENT
→ UNIT nodes (a single-unit component is a leaf UNIT row). Glue/dotfiles companions are dropped in
`_invert` — they belong to the Glue/Dotfiles screens. Ids are stable strings (`p:`, `c:`, `u:`, `l:`).
Every rebuild (`_reload`, a mode switch, the System Updates fold) carries the old view across with
`MenuState.adopt_view(old)`: selection, still-valid staged ops (and staged versions), errors,
expansion, the `F` filter, cursor and scroll offset.

**Model building** (`_components_model(ctx, cfg, states, mode, caches)`): the view mode
(`COMPONENT_MODES`: `to-do` default, `tracked`, `installed+tracked`) picks the scope — this machine's
picks that aren't green, plus present uninstall-queue entries / all picks / picks plus
installed-but-untracked (`orphans.install_overlay`, its enumeration `caches` reused across switches).
The to-do test is `models._TODO_STATUSES` — `missing`, `outdated`, the routing statuses
`switch`/`unmet`/`dangling` (they rank ahead of missing/outdated in `ComponentState.status`, so a
stranded `switch` would otherwise never surface), `error` and `untrusted` — judged per picked name
over every unit grouped under it, so a pick whose own unit is green but whose dependency is missing
still shows. A view-mode switch goes through `models._switch_mode`: installed+tracked's extra units
are remembered on the MenuState (`ms._extra_keys`, from `_added_extras`) and dropped from `states`
when switching away, unless they carry a staged op — so they can't linger invisibly for a later bulk
op to sweep up. Names not yet in `states` are inspected (`ctx.inspect_components`). Then
`_group_by_owner` groups by owning profile and the synthetic System Updates group is injected from
`ctx._sysupd_groups` (`sysupdates.tree_injection`).

**Staging is keyed by unit** (`ms.staged = {unit_key: op}`), so a mark is consistent wherever the unit
appears. `OPS` maps op → `(badge, palette role, predicate on ComponentState)`; `stage(op)` applies it
to the selection or cursor node. `install` means *make current*: on an absent unit it installs; on a
present one it falls back to `upgrade` if outdated; a `switch` row (installed via a method routes no
longer offer) passes the install predicate, and the swap is folded in at execute. `dangling`/`unmet`
never stage install. A locked unit is never upgraded (`stage` sets `skip_note` saying so). `lock`
requires `holds_version` (not on rolling managers). `remove`/`lock`/`unlock` act on a row's **own**
units only (`_own_members`), never the shared dependencies its closure pulled in. `set-version` is
staged only from the `v` picker (`stage_unit`, with `staged_versions`). `toggle_lock` flips both a
pending request and a settled lock. `stage_all` covers every unit except companions and System Updates
rows, and skips a unit that already carries a staged op (a `remove` seeded from the uninstall queue by
`flows._seed_uninstall` is never flipped by `I`/`U`) and any unit not tracked on this machine (its
`requested_as` must meet `ms._req_sig`). System Updates rows are a **bulk mark**:
`stage_system_updates` stages all or none, and the screen intercepts per-row actions inside that
subtree (`_SU_BULK_ACTS`, `_SU_NA_ACTS`). `unstage` is all-or-nothing for them too: touching any
System Updates row unstages every one (`unstage_system_updates`), because execute upgrades a whole
manager whenever any of its rows is staged. With `--machine <other>` the Components screen is
read-only (it stages nothing and says why).

**Execute** (`flows._confirm_and_execute`): pull System Updates out of `ms.plan()`, then
`actions.build_plan` — the one plan builder the CLI uses too (auto-tighten, the method-switch swap
`plan_with_swaps`, only the missing dependencies, and the version-floor heads-ups). Under `suspended`
and one `ctx.runner.sudo_session()`: with System Updates staged, refresh the index *before* the
confirm (so the count you confirm is current); print the heads-ups and the plan; confirm (the CLI's
`cli.common.ask`); run System Updates first (`sysupdates.apply_bulk` → each manager's `upgrade_all`),
then `execute_plan` → `actions.run_plan` (the same loop the CLI uses; every failure saved for
`configsys report`); `actions.after_run` drains removed components from the uninstall queue; print
the summary. Back in `handle`, the touched keys (plus every unit of a bulk-upgraded manager) are
re-probed via `_reload`, `ms.errors` gets the failures, the reboot check reruns, and
`invalidate_ps_overlay` tells Profiles to re-enumerate. Every executed run also drops the System
Updates scan before the `_reload` (`sysupdates.invalidate`, so the rebuilt tree doesn't re-inject
stale rows) and starts a fresh background scan after it (`_rescan_system_updates`).

## Background work and reloads

- **Startup inspection** runs in `_InspectWorker`; the splash polls its `frac`/`counts`/`phase_label`.
  Phase bands are sized from learned timings (`startuptiming`).
- **System Updates** — `sysupdates.start_scan` runs `gather` on a daemon thread into
  `ctx._sysupd_groups` and sets `ctx._sysupd_dirty`. On a poll timeout, `take_dirty` triggers
  `_fold_system_updates`, which drops the old synthetic rows and rebuilds only the *tree* via
  `_rebuild_menu` from the states already held (~10–15 ms). It deliberately does **not** call
  `_reload`, which reruns the load pipeline and diagnostics (seconds) on the UI thread — that froze
  the UI right after the splash.
- **`check` lints on the `!` page** — `Context.start_check_lints` runs `cli.check.check_report` on a
  daemon thread (at start and after every `_reload`); when it lands it sets `ctx._check_dirty` and the
  loop recomputes `ctx.diagnostics(states)`, so `check`'s warnings join the `!` page without blocking
  startup.
- **`_reload(ctx, old, dirty)`** — `ctx.load_pipeline(reuse=old.states, dirty=dirty)` re-probes only
  `dirty` + newly-appearing units and reuses the cached probes for the rest; rebuilds the model fresh
  (overlay caches dropped: disk changed); `adopt_view` carries the view over (errors are re-derived);
  re-seeds the uninstall queue (`_seed_uninstall`); restarts the `check` lints. Used after a pin
  (`v`), execute, refresh (`R`, which re-probes everything — and, like execute, invalidates the System
  Updates scan before the reload and rescans after it; staged System Updates marks go with the old
  rows and the note says so), unstaging from the uninstall queue, and screen-return rebuilds.
  `_rebuild_menu` is the cheap counterpart for a view-mode switch (same states, new tree).
- **Screen-local threads**, each generation-guarded (or newest-request-only) so a reload abandons a
  stale result: `ProfileScreen._start_overlay_scan` (the full install overlay + orphan
  classification), `ProfileScreen._start_probe` (installed checks for drivers with no batch
  `installed_index` — tarball, script, appImage, …), `ProfileScreen._warm_cache` (pre-resolves the
  catalog), `ProfileScreen.request_available_oses` (the 7-resolve coverage hint for a component with
  no method here), `PluginScreen._start_remote` (each plugin's remote-ref by `git ls-remote`, the
  primary fetched first for its ↓N) and `PluginScreen._request_diff` (the review diff). Results are
  written into model attributes and painted on a later frame; the router's 120 ms poll (above) is what
  makes them appear without a keypress.
- **`_warm_cache` thread-safety.** The warm thread calls `ProfileScreen._resolve` concurrently with
  the UI thread, so `_resolve` uses two locks. `self._res_lock` (per screen) guards the result cache
  `_res`/`_res_routes`: the routes-identity check, the clear on a routes swap, the lookup and the
  insert. The slow `ctx.routes.candidates(...)` call runs outside it, under `panes._ROUTES_LOCK` (a
  process-wide `RLock`, via `_routes_lock(ctx)`), so no two threads drive one Resolver's internal
  caches at once — also across two ProfileScreens over one ctx (the Profiles sample). The insert is a
  `setdefault` (a value already there wins, so a late warm result can't overwrite a primed row) and is
  skipped if `ctx.routes` was swapped mid-resolve.

## Surfaces and headless rendering

A painter touches only `getmaxyx`, `erase`, `addstr`, `move`, `refresh`, `derwin`. That is the
`Surface` contract. `BufferSurface(h, w)` records `{(y, x): Cell(char, attr)}`, clips out-of-bounds
writes silently (as `_put` swallows `curses.error`), and its `derwin` writes into the parent grid at
absolute coordinates (the Theme sample slot renders whole sub-screens into a `derwin`). `grid()`
gives a sortable snapshot; `text_rows()` gives plain text. The `Palette` only *computes* attrs, so the
attr a painter passes is opaque to the surface. In production, `run` hands each screen's `render` the
raw `stdscr`, which satisfies the same duck-typed contract.

**Test harness** (`test/_render_harness.py`): `RecordingPalette` mimics the Palette's public API,
returning deterministic hashable `Attr` tokens (role, page, selection, explicit bg, gradient band)
instead of curses attrs. `build_ctx(home)` makes a real `Context` over a throwaway `--home`
(`--os pop --pretend`) and installs the module-global keymap. `capture(name, ctx, pal, h, w)` paints a
screen from its `preview._sample_*_state` through the real `build_vm`/`draw`. Suites:

- `test_render_headless.py` — every screen renders non-empty and in bounds at roomy/tight sizes,
  deterministically, across gradient/flat/low-color/mono palettes.
- `test_screen_<id>.py` — per-screen render regression against **hand-built** data (no golden file,
  no routes.hu reads in the assertions) plus `handle` → `Intent` behavior; Components and Profiles
  also paint a literal VM with no ctx or model.
- `test_tui_table.py` (the shared table painter), `test_tui_modals.py` (`ListNav`, the modal frame,
  `begin_page`/`end_page`, draw-writes-nothing), `test_tui_pretend_sweep.py` (every screen key under
  `--pretend`), `test_surface.py`, `test_keyspec.py`, `test_menu_state.py`, `test_menu_nodes.py`,
  `test_tui_*.py` (nav/find/pin/provider/helpers/issue); `test_tui_smoke.py` drives the real curses
  TUI under a PTY — the only real-curses check.

History: the D2 MVVM port proved each new screen against its legacy painter (render equivalence);
D7 proved the complete Profiles and Components VMs cell-for-cell identical to the paint they replaced
(24 and 32 frames). Both were one-off proofs; the legacy painters are gone, and the `Attr` type is the
last trace.

## Keymap pipeline

The defaults live in the repo's `config.hu` `keys:` section. There is no Python default map, only
`keyspec._FALLBACK` (quit / quit-force / issues + screen switch) so a broken section can't brick the
TUI. `Config.keys()` delegates to `keyspec.merge_layer_keys` over `Config.key_layers()` — every
layer's `keys:` (repo < plugins < primary < top config), except a plugin's (or the primary's) until
it is trusted (`plugins.command_source_trusted`; `check` names the ignored ones). The merge runs in
passes over the final bindings, **rebind-wins**: (1) each (scope, action) takes the highest layer's
spec; (2) within a scope, a key two final actions hold stays with the higher layer's action and is
stripped from the lower one (an action left with no key is dropped); (3) across scopes, in the
router's precedence, a higher layer's `global` router-action or `screens` binding takes its key from
a lower layer's page bindings, and a `screens` key takes it from a lower `global` nav action. Each
steal is a `check` warning; `configsys keys` prints the effective map with the layer each binding
came from (`owners_out`).

`Keymap(merged)` parses each spec (`parse_key`: a literal char, case-sensitive; named keys such as
`enter`/`pgdn`/`shift-tab`; `ctrl-x`; `f1`–`f12`) into `{scope: {action: [codes]}}`. Scopes:
`screens`, `global`, `issues` (the `!` page), and one per screen id. `action_for(scope, code)` tries
the page scope first, then `global`, so a page key overrides a global key on that page (`tab` =
`expand-all` on Components, `switch-pane` elsewhere); within one scope, a key bound to two actions
goes to the first listed. `own_action` is the page scope alone (the router's first check). Return
(CR) and Ctrl-J (LF) are distinct because `screen.distinct_return_mode` turns off CR→NL folding
(vim-style); that's why `confirm` and `page-down` can coexist.

**Legends and help read the same Keymap**, so hints can't drift from bindings: `Keymap.glyph` feeds
the footers, modal hints and chip bar, through `paint._keymap()` (the module global `menu._KEYMAP`
set in `run`, else `keyspec.shipped_keymap()`). `glyph` uses `effective_codes`, so a legend never
shows a key the page shadows. The `?` overlay (`_help_modal`) combines `help.help_page(screen,
keymap)` (the description + glossary, with `{scope:action}` placeholders rendered as your keys) with
`Keymap.help_rows(scope)`: the global actions in a fixed order, then the page's own actions,
labelled by `Keymap.label(scope, action)` — a scope-specific `ACTION_LABELS` entry `<scope>.<action>`
first (one action id can mean different things per page, e.g. `profiles.where`), else the shared
label (`page-1..7` collapse to one row). Labels name the action only, never a hard-coded key.
`KNOWN_ACTIONS` is the per-scope dispatch contract. `lint_keys` (run by `configsys check`) flags
unknown scopes and actions, unparseable keys, keys the TUI can never receive, same-layer
self-conflicts, cross-layer steals, and — via `lint_merged` — a page that shadows every
`quit`/`quit-force` key (no way out from it). To add an action, add it to `config.hu`,
`KNOWN_ACTIONS`, `ACTION_LABELS`, the screen's `handle`, and `parity.TUI_ACTIONS` (its CLI
counterpart or why it has none; `test_parity.py` fails until it is classified).

## Theming hooks

`Config.theme()` deep-merges `theme:` from every layer (`colors`, `colors-basic`, `pages`, and the
legacy `splash`). `resolve_theme` turns it into the colour map plus per-page role styles and
gradient; `theme_problems` lists what the TUI would silently ignore (an unknown section, page, role
or role attribute; a colour that doesn't parse) — `check` warns, `theme set` refuses. `Palette` (one
per session, rebuilt by Theme edits via `Intent.new_pal`, and once after the splash to discard its
colour allocations) exposes `style/fill` (roles, over the active page's gradient or the selection
bar), `get` (a colour-map name over the default background), `rgb_attr/rgb_pair` (ad-hoc colours for
swatches and splashes), `use_page(id)` (`begin_page` calls it), `gradient` (whether this page paints
one), `depth` (the colour depth it paints at, one of `theme.DEPTHS`, after any `--color` cap; the
`mono`/`have256`/`truecolor`/`direct`/`lowcolor` flags derive from it) and `color_mode` (the Theme
status line's words). `STATUSES` names each status and routing status that has a same-named role.

- **Colour depth:** detected from `curses.COLORS`/`can_change_color` as `direct` (a `-direct`
  terminfo: ≥ 2²⁴ colours) → `truecolor` (`init_color` slots) → `256` → `16` → `8`. It can be clamped
  *down* only, by `env_color_cap` (`NO_COLOR`, `CONFIGSYS_COLOR` from `--color`/`--nocolor`), to
  `none` (mono: flags only) at the bottom. On the 8/16 path each colour-map name takes its `BASIC_MAP`
  / `colors-basic` ANSI slot, and `_contrast` keeps fg off bg. When the 240 redefinable slots or the
  per-frame pairs run out, the nearest existing one is reused (`reduced`, which `color_mode` reports).
  A capped depth on a `-direct` terminfo still sends packed RGB (`direct_numbering`).
- **Direct colour:** `curses_screen` initializes under `direct_color_env`. When the environment signals
  truecolor (`_truecolor_signal`) or `--color 24bit` asks, it swaps `TERM` to `<base>-direct`. That
  entry comes from the system, or is built into `terminfo_cache_dir(paths)` (the sandbox home's
  `.cache` under `--home`; a throwaway temp dir under `--pretend`) by `terminfo.build_direct` or,
  failing that, `tic`; a cached entry older than the terminal's own is rebuilt. `TERM` is restored
  after `initscr` so children see the real one. The reason: terminals that ignore OSC 4 (COSMIC) show
  wrong colours under `init_color`. Under direct colour a colour number *is* the packed RGB.
- **Effects:** `resolve_effects` canonicalizes `--effects` > the `effects:` setting > reduced-over-SSH
  (`is_ssh`) > full into `CONFIGSYS_EFFECTS`. `env_effects` gates the gradient (`Palette.grad_ok`;
  the gradient also needs truecolor) and the splash: `reduced` caps it at 15 fps, and `none` (or mono)
  forces the plain built-in splash.

## Splash interface

The host (`tui/splash.py` `run_splash`) owns the frame loop, clock, skip key, `linger`, and a
plain-text progress fallback. A key drops the animation to the text line (with `linger`, ends it); a
resize is not a key; typeahead is discarded on the way out, so keys mashed to skip never reach the
first screen. A misbehaving constructor or `render` drops to the text line and never breaks startup;
a class's `fps` (clamped to 1–120) and `min_duration` are sanitized. A splash subclasses
`splashes.Splash` with a class `name` and is constructed once as `(scr, pal, (h, w), seed)`. Each
frame it gets `render(SplashFrame(progress, counts, label, dt, elapsed, done))`, draws without
refreshing, and returns truthy when at rest. A `raw = True` splash returns an ANSI string written
straight to the tty (it sets `at_rest` itself), which bypasses curses' 256-pair limit;
`_sgr_downconvert` keeps it within the colour cap. `register_splash` keys by name; a trusted code
plugin exports `SPLASHES = [cls, …]` and `plugins.load_code` registers them (a name clash is reported
as a conflict). The `splash:` setting selects one: a provider name, the name of a plugin that ships
exactly one splash (`plugins.resolve_splash_value`), `random` (any registered splash but the default),
or `off`. An unknown or untrusted name falls back to `braille-bar` with a note (an ambiguous plugin
name lists the choices — `splash_value_hint`). `splashes.py` is curses-free because it sits on the
frozen plugin ABI (`test_abi_surface.py` pins `SplashFrame`, the `Splash` attributes and
constructor, and `register_splash`).
