# TUI architecture

> **Status: REFERENCE** — how the TUI is built; maintained.

The TUI (`configsys tui`, entered via `app.cmd_tui` → `configsys/tui/menu.py` `run`) is a curses
app built as a small router over seven screens. Each screen follows one protocol (build a view model,
paint it, handle a key), paints through a `Surface` so it can render without a terminal, and dispatches
on keymap **actions**, not raw key codes. User-facing look and keys are covered in
[theming.md](theming.md) and [config-format.md](config-format.md#theme-and-keys); splash code plugins
in [plugins.md](plugins.md#7b-other-hooks). The cross-cutting rules (no surprises, sudo/TTY handling)
are in [principles.md](principles.md).

## Module map

| Module | Holds |
|---|---|
| `tui/menu.py` | `run` (the router + event loop), `MenuState` (the Components tree), the screen MODEL classes (`ProfileScreen`, `PluginScreen`, `ConfigScreen`, `ThemeScreen`, `DotfilesScreen`, `GlueScreen`), shared modals/painting helpers (`_put`, `_fit`, `_popup_choose`, `_input_box`, `_filter_edit`, `_find_edit*`, `_panel`, scrollbars, `_draw_nav`, `_fill_bg`), `_HELP`, the overlays (`_draw_where`, `_draw_diagnostics`), and the `_sample_*_state` fixtures |
| `tui/screens/base.py` | the protocol: `Screen`, `ViewModel`, `Intent`, `Size` |
| `tui/screens/<id>.py` | one `<Id>Screen` + `<Id>VM` per screen: `components`, `profiles`, `plugins`, `glue`, `dotfiles`, `config`, `theme` |
| `tui/surface.py` | `CursesSurface`, `BufferSurface`, `Cell` |
| `tui/keyspec.py` | key-name parsing, `Keymap`, `KNOWN_ACTIONS`, `ACTION_LABELS`, `lint_keys` |
| `tui/theme.py` | `COLOR_MAP`, `BASIC_MAP`, `ROLE_DEFAULTS`, `PAGE_ROLES`, `BUILTIN_GRADIENTS`, `resolve_theme`, `Palette`, `STATUS_COLOR`, `env_color_cap`/`env_effects` |
| `tui/screen.py` | curses lifecycle: `curses_screen`, `suspended`, Return/Ctrl-J separation, direct-color terminfo selection |
| `tui/terminfo.py` | pure-Python compiled-terminfo reader/writer (builds a `-direct` entry without `tic`) |
| `tui/splash.py` | the splash host loop `run_splash` + the built-in `braille-bar` (`BrailleBarSplash`) |
| `splashes.py` | the curses-free splash ABI: `Splash`, `SplashFrame`, `register_splash`, `get_splash` |

The screen MODEL classes stayed in `menu.py` and are composed into the screen modules as `self.model`
(`screens/profiles.py` imports `menu.ProfileScreen as _ProfilesModel`, etc.). The name collision is
deliberate: inside `run` the `screens.*` classes shadow the like-named models. Screen modules import
from `menu` freely; `menu` imports the screen modules lazily (inside `run` / `_sample_real_page`) to
stay acyclic.

## The screen protocol

`Screen` (base.py) has a class attribute `id` — both the router key and the keymap scope — and three
seams:

- **`build_vm(ctx, size) -> ViewModel`** — pure: read the model and `ctx`, return plain data. No curses,
  no drawing. `size` is the `(h, w)` tuple from `getmaxyx()` (the `Size` dataclass exists but the
  router passes a tuple). The router stamps `vm.note` (the transient status note it owns) on every VM
  except Components', which carries the note and diagnostics as `ComponentsScreen.note`/`.diags` and
  copies them into `ComponentsVM`.
- **`draw(surface, pal, vm)`** — a dumb painter: positions and colours, decides nothing the VM and model
  didn't settle. Every draw must append `vm.note` to its status line.
- **`handle(ch, ctx, stdscr, pal) -> Intent`** — one key. Components' signature adds `cfg, ledger`
  (it re-runs the load pipeline). `handle` mutates the model and may run modal loops inline
  (`_popup_choose`, `_input_box`, the `suspended` confirm/execute prompt); a modal that live-filters
  gets a redraw callback (`lambda: self.draw(stdscr, pal, self.build_vm(...))`).

How "pure" each VM is varies. Components, Profiles and Theme keep the VM light (chrome strings,
frame inputs) and let `draw` read the heavy per-row content from the model; the table screens
(Plugins/Glue/Dotfiles/Config) carry more in the VM. The invariant that matters is the one the tests
lean on: **draw is a deterministic function of (model, ctx, vm, palette)**. Nothing in a draw path
reads the clock or probes the system — the Components header's System Updates spinner indexes
`ctx._frame`, a tick the loop advances; the reboot chip reads `ctx._reboot_pending`, probed once at
start and after an execute, never per frame; descriptions come from `ms.descriptions`, cached by
`_describe`.

**`Intent`** is how a key asks for effects the router owns, so the shared loop state has one owner:
`note`, `goto` (switch screen), `dirty` (rebuild the Components tree on the next visit), `quit`,
`new_pal` (Theme edits rebuild the `Palette`), `open_where` (`(lines, subject)` for the full-page
`where` overlay), `pending_notes` (printed after the TUI exits), and the Components-only `reloaded`
(`(ms, cfg, ledger, states, diags)` from `_reload`), `remodeled` (`(ms, states, layouts, transitive)`
from a view-mode switch), `pending_report`, `invalidate_ps_overlay`. `handled` defaults to `True` and the
router never reads it: global keys are resolved *before* the screen sees the key (below), so there's
no fall-through path to fall back to.

## Router and event loop (`menu.run`)

Startup, in order: `ctx.ensure_user_config(offer_primary=True)` on the main thread (it prompts on
stdin, so it must precede curses and the worker) → `resolve_effects` → `_chosen_splash` (registers
trusted plugin code up front *only* when a plugin splash is selected) → `_InspectWorker(ctx).start()`
runs `load_pipeline` on a thread → enter `curses_screen` → splash if inspection outlasts
`SPLASH_THRESHOLD` (0.25s) or `CONFIGSYS_SPLASH=always` → `worker.join()` (re-raises load errors) →
build the `Keymap`, the Components model, the first `MenuState` → `sysupdates.start_scan`.

**Screens.** `SCREENS` lists `(key, id, name)` for the row-0 chip bar (`_draw_nav`; chip glyphs come
from the keymap's `screens` scope, so a rebind shows); `IMPLEMENTED` gates switching. Screens are
built **lazily** by `_screen(sid)` into `_reg = {id: Screen}` on first visit and then live for the
session (model state — cursor, filters, caches, threads — persists across switches). Components is
built over the live `MenuState`; the router re-assigns `scr.model = ms` each frame, because `ms` is
rebound by reloads. Theme additionally gets `sample_ms = ms` for its sample slot.

**Each iteration:** bump `ctx._frame`; `pal.new_frame()` (curses `color_pair()` encodes 8 bits, so
pairs are recycled per frame — slots persist); draw the where overlay, the `!` diagnostics overlay, or
the current screen; then read one key. The `getch` is blocking, except it polls at 120ms while
background work must paint on its own: on Components while the System Updates scan runs or its result
is unconsumed; on Profiles while `overlay_busy()` / `probe_busy()`. A timeout (`-1`) folds a landed
System Updates scan and redraws.

**Key resolution order:** overlay keys (where / diagnostics, scrolled via the `components` scope's
nav actions) → `global` scope (`quit-force`, `quit` with a confirm popup, `issues`, `help`) →
`screens` scope (`Keymap.screen_for`) → the current screen's `handle`. On switching *to* Components
the router reloads (`_reload`) if any of: an Intent set `dirty`, the Dotfiles/Glue models report
mutated units (`model.dirty`), the uninstall queue differs from `ms._uninstall_q`, or
`config.requested()` differs from `ms._req_sig` (picks or the current machine changed). Switching to
Dotfiles/Glue calls their `reload()` (link state may have changed elsewhere). After the loop exits:
`reporter.resume()`, the session summary, `pending_notes`, and a `configsys report` nudge if an op
failed.

## Components: `MenuState`

`MenuState(states, layouts, transitive)` — `states` = `{unit_key: ComponentState}`; `layouts` =
`[(profile, [items])]`, an item a component name or `('include', name)` (rendered as a LINK node to
`p:<name>`); `transitive` = `{profile: [all transitive names]}`. `_build_tree` makes PROFILE → COMPONENT
→ UNIT nodes (a single-unit component is a leaf UNIT row). Glue/dotfiles companions are dropped in
`_invert` — they belong to the Glue/Dotfiles screens. Ids are stable strings (`p:`, `c:`, `u:`, `l:`),
which is what lets rebuilds keep cursor/selection/expansion.

**Model building** (`_components_model(ctx, cfg, states, mode, caches)`): the view mode
(`COMPONENT_MODES`: `to-do` default, `tracked`, `installed+tracked`) picks the scope — tracked picks
not green, plus present uninstall-queue entries / all picks / picks plus installed-but-untracked
(`orphans.install_overlay`, its enumeration `caches` reused across switches). Names not yet in
`states` are inspected (`ctx.inspect_components`). Then `_group_by_owner` groups by owning profile and
the synthetic System Updates group is injected from `ctx._sysupd_groups` (`sysupdates.tree_injection`).

**Staging is keyed by unit** (`ms.staged = {unit_key: op}`), so a mark is consistent wherever the unit
appears. `OPS` maps op → `(badge, palette role, predicate on ComponentState)`; `stage(op)` applies it
to the selection or cursor node's members. `install` means *make current*: on an absent unit it
installs; on a present one it falls back to `upgrade` if outdated; a `switch` row (routing status:
installed via a method routes no longer offer) passes the install predicate, and the swap is folded
in at execute. `dangling`/`unmet` never stage install. `lock` requires `holds_version` (not on rolling
managers). `toggle_lock` flips both a pending request and a settled lock. `stage_all` covers every
unit except companions and System Updates rows. System Updates rows are a **bulk mark**:
`stage_system_updates` stages all or none, and the screen intercepts per-row actions inside that
subtree (`_SU_BULK_ACTS`, `_SU_NA_ACTS`).

**Execute** (`_confirm_and_execute`): pull System Updates out of `ms.plan()`, apply
`installState.plan_with_swaps` (a method switch removes the old install before reinstalling), then
`planning.expand_plan`; print the plan under `suspended`, confirm, run System Updates first
(`sysupdates.apply_bulk` → each driver's `upgrade_all`), then `execute_plan` → `actions.run_plan` (the
same loop the CLI uses; all failures saved for `configsys report`); drain successfully removed
components from the uninstall queue. Back in `handle`, the touched keys (plus every unit of a
bulk-upgraded manager) are re-probed via `_reload`, `ms.errors` gets the failures, the reboot check
reruns, and `invalidate_ps_overlay` tells Profiles to re-enumerate.

## Background work and reloads

- **Startup inspection** runs in `_InspectWorker`; the splash polls its `frac`/`counts`/`phase_label`.
  Phase bands are sized from learned timings (`startuptiming`).
- **System Updates** — `sysupdates.start_scan` runs `gather` on a daemon thread into
  `ctx._sysupd_groups` and sets `ctx._sysupd_dirty`. On a poll timeout, `take_dirty` triggers
  `_fold_system_updates`, which drops the old synthetic rows and rebuilds only the *tree* via
  `_rebuild_menu` from the states already held (~10–15ms). It deliberately does **not** call
  `_reload`, which reruns the load pipeline and diagnostics (seconds) on the UI thread. That froze
  the UI right after the splash.
- **`_reload(ctx, old, dirty)`** — `ctx.load_pipeline(reuse=old.states, dirty=dirty)` re-probes only
  `dirty` + newly-appearing units and reuses the cached probes for the rest; rebuilds the model fresh
  (overlay caches dropped: disk changed); carries over selection, still-valid staged ops, expansion and
  cursor; re-seeds the uninstall queue (`_seed_uninstall`). Used after a pin (`v`), execute, refresh
  (`R`, which re-probes everything), unstaging from the uninstall queue, and screen-return rebuilds.
  `_rebuild_menu` is the cheap counterpart for a view-mode switch (same states, new tree).
- **Screen-local threads**, each generation-guarded so a reload abandons a stale result:
  `ProfileScreen._start_overlay_scan` (orphan classification), `ProfileScreen._start_probe`
  (installed checks for non-enumerable drivers), `ProfileScreen._warm_cache` (pre-resolves the
  catalog), `PluginScreen._start_remote` (`git ls-remote`). They rely on the idle loop blocking in
  `getch` (GIL released). Results are written into model attributes and painted on a later frame.
- **Open — `_warm_cache` thread-safety.** The warm thread calls `ProfileScreen._resolve` →
  `ctx.routes.candidates(...)` concurrently with the UI thread. That shares `ctx.routes`' internal
  caches and `self._res` (including its `_res.clear()` on a routes-id change) with no lock. It is
  safe enough with one ProfileScreen per session, which is production. It is **not** safe for two
  views over one ctx (seen in tests and worked around in the sample fixture). Fix it before adding a
  second profile view: make the cache instance-local or lock it.

## Surfaces and headless rendering

A painter touches only `getmaxyx`, `erase`, `addstr`, `move`, `refresh`, `derwin`. That is the
`Surface` contract. `CursesSurface` delegates verbatim (exists but is unused by `run`; see below). `BufferSurface(h, w)` records
`{(y, x): Cell(char, attr)}`, clips out-of-bounds writes silently (as `_put` swallows `curses.error`),
and its `derwin` writes into the parent grid at absolute coordinates (the Theme sample slot renders
whole sub-screens into a `derwin`). `grid()` gives a sortable snapshot; `text_rows()` gives plain
text. The `Palette` only *computes* attrs, so the attr a painter passes is opaque to the surface. In
production, `run` hands each screen's `draw` the raw `stdscr`, which satisfies the same duck-typed
contract.

**Test harness** (`test/_render_harness.py`): `RecordingPalette` mimics the Palette's public API,
returning deterministic hashable `Attr` tokens (role, page, selection, explicit bg, gradient band)
instead of curses attrs. `build_ctx(home)` makes a real `Context` over a throwaway `--home`
(`--os pop --pretend`) and installs the module-global keymap. `capture(name, ctx, pal, h, w)` paints a
screen from its `menu._sample_*_state` through the real `build_vm`/`draw`. Suites:

- `test_render_headless.py` — every screen renders non-empty and in bounds at roomy/tight sizes,
  deterministically, across gradient/flat/low-color/mono palettes.
- `test_screen_<id>.py` — per-screen render regression against **hand-built** sample data (no golden
  file, no routes.hu reads in the assertions) plus `handle` → `Intent` behavior.
- `test_surface.py`, `test_keyspec.py`, `test_menu_state.py`, `test_menu_nodes.py`, `test_tui_*.py`
  (nav/find/pin/provider/helpers); `test_tui_smoke.py` drives the real curses TUI under a PTY. It's
  the only real-curses check.

The legacy-vs-new render-equivalence phase is over; the `Attr` type and some docstrings still mention it.

## Keymap pipeline

The defaults live in the repo's `config.hu` `keys:` section. There is no Python default map, only
`keyspec._FALLBACK` (quit + screen switch) so a broken section can't brick the TUI. `Config.keys()`
merges `keys:` from **every** layer (repo < plugins < primary < top config), replacing per action.
`Keymap(merged)` parses each spec (`parse_key`: a literal char, case-sensitive; named keys such as
`enter`/`pgdn`/`shift-tab`; `ctrl-x`; `f1`–`f12`) into `{scope: {action: [codes]}}`. Scopes:
`screens`, `global`, and one per screen id. `action_for(scope, code)` tries the page scope first, then
`global`, so a page key overrides a global key on that page (`tab` = `expand-all` on Components,
`switch-pane` elsewhere). Return (CR) and Ctrl-J (LF) are distinct because `screen.distinct_return_mode`
turns off CR→NL folding (vim-style); that's why `confirm` and `page-down` can coexist.

**Legends and help read the same Keymap**, so hints can't drift from bindings: `Keymap.glyph` feeds
the footers and chip bar, through the module global `menu._KEYMAP` set in `run`. The `?` overlay
(`_help_modal`) combines `_HELP[screen]` (description + glossary) with `Keymap.help_rows(scope)`: the
global actions in a fixed order, then the page's own actions, labelled by `ACTION_LABELS`
(`page-1..7` collapse to one row). `KNOWN_ACTIONS` is the per-scope dispatch contract.
`lint_keys` (run by `configsys check`) flags unknown scopes and actions, unparseable keys, and
same-layer self-conflicts. To add an action, add it to `config.hu`, `KNOWN_ACTIONS`, `ACTION_LABELS`,
and the screen's `handle`.

## Theming hooks

`Config.theme()` deep-merges `theme:` from every layer. `resolve_theme` turns it into the colour map
plus per-page role styles and gradient. `Palette` (one per session, rebuilt by Theme edits via
`Intent.new_pal`, and once after the splash to discard its colour allocations) exposes
`style/at/fill/get` (roles, over the active page's gradient or the selection bar),
`rgb_attr/rgb_pair` (ad-hoc colours for splashes), `use_page(id)` (each draw calls it), and
`gradient`. `STATUS_COLOR` maps each status and routing status to its role.

- **Colour depth:** detected from `curses.COLORS`/`can_change_color`. It can be clamped *down* only, by
  `env_color_cap` (`NO_COLOR`, `CONFIGSYS_COLOR` from `--color`/`--nocolor`): `direct` → `truecolor`
  (`init_color` slots) → `256` → `basic16`/`basic8` (`BASIC_MAP` hand-tuned slots plus the
  `_contrast` guard) → `none` (mono: flags only). `Palette.color_mode` names the result.
- **Direct colour:** `curses_screen` initializes under `direct_color_env`. When the environment signals
  truecolor (`_truecolor_signal`), it swaps `TERM` to `<base>-direct`. That entry comes from the system,
  or is built into a cache with `tic` or, failing that, with `terminfo.build_direct`. `TERM` is
  restored after `initscr` so children see the real one. The reason: terminals that ignore OSC 4
  (COSMIC) show wrong colours under `init_color`. Under direct colour a colour number *is* the packed
  RGB.
- **Effects:** `resolve_effects` canonicalizes `--effects` > the `effects:` setting > reduced-over-SSH
  > full into `CONFIGSYS_EFFECTS`. `env_effects` gates the gradient (`Palette.grad_ok`, which is
  truecolor only) and the splash frame-rate cap. `none`, or mono, forces the plain built-in splash.

## Splash interface

The host (`tui/splash.py` `run_splash`) owns the frame loop, clock, skip key, deadline, `linger`, and
a plain-text progress fallback. A misbehaving `render` drops to the text line and never breaks
startup. A splash subclasses `splashes.Splash` with a class `name` and is constructed once as
`(scr, pal, (h, w), seed)`. Each frame it gets `render(SplashFrame(progress, counts, label, dt,
elapsed, done))`, draws without refreshing, and returns truthy when at rest. Class knobs are `fps` and
`min_duration`. A `raw = True` splash returns an ANSI string written straight to the tty, which
bypasses curses' 256-pair limit. `_sgr_downconvert` keeps it within the colour cap. `register_splash`
keys by name; a trusted code plugin exports `SPLASHES = [cls, …]` and `plugins.load_code`
registers them (a name clash is reported as a conflict). The `splash:` setting selects one (`random`,
`off`, or a plugin name as an alias). An unknown or untrusted name falls back to `braille-bar` with a
note. `splashes.py` is curses-free because it sits on the frozen plugin ABI.
