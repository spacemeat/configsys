# D2 — TUI MVVM rewrite (build_vm / draw / handle + screen router)

Status: ACTIVE. The last big item from the Sept-2026 review ([[code-review-2026-09]]). The TUI is one
6.3k-line `configsys/tui/menu.py`: state classes (`MenuState`, `ProfileScreen`, `ConfigScreen`,
`ThemeScreen`, `PluginScreen`, `DotfilesScreen`, `GlueScreen`) mixed with module-level
`_draw_*(stdscr, pal, state, ctx, note, screen)` painters and one ~800-line `run()` dispatch loop.

## Goals (user's words)
Testability, readability, demonstrated intent for maintainers, and headless/SDK optionality
("abstracted well enough, cfs could be run headless entirely, exposed as an SDK"). Not going all
the way to a shipped SDK — a CLI already exists — but the flexibility has value.

## Locked decisions
- **Layout:** split into a `configsys/tui/screens/` package. `menu.py` shrinks to the `run()` entry +
  shared draw primitives that don't belong to one screen.
- **Fidelity bar:** STRICT pixel-preservation. Every screen renders identically (same char + resolved
  color/flags per cell) before vs after each step, enforced by a render-equivalence harness. Any
  rendering bug spotted is logged to `docs/d2-mvvm-findings.md` for a SEPARATE follow-up — never fixed
  mid-refactor (keeps the refactor provably behavior-neutral).

## Architecture
- **Surface** (`tui/surface.py`): the ONE drawing sink. `CursesSurface` wraps `stdscr`
  (getmaxyx/erase/put/addstr/move/refresh/derwin); `BufferSurface` records a cell grid
  `{(y,x): (char, attr)}` headlessly. Today rendering already funnels through `_put()` (151 calls) +
  2 stray `addstr`; Palette methods (`style/at/fill/get/rgb_*`) only RETURN attrs, they never draw —
  so threading a Surface through the painters is mechanical and Palette is untouched.
- **ViewModel:** a pure-data description of a frame (rows/cells/segments with role+text+position),
  produced by `build_vm(ctx, size)` with NO curses. `draw(surface, vm)` is a dumb painter.
  `handle(key) -> Intent` mutates the screen's model and returns a navigation/side-effect intent.
- **Screen protocol** (`tui/screens/base.py` — `tui/screen.py` is taken by the curses-lifecycle
  helpers): `build_vm` / `draw` / `handle`, holding its model (the existing state classes move in
  mostly as-is).
- **Router** (`tui/router.py`): `{id: Screen}` + the slim loop: build_vm → draw → getch → handle →
  route. Overlays (where/diagnostics/help) and the global keys stay router-level.

## Render-equivalence harness (Phase 0 — the safety net, built FIRST) — BUILT
- No curses / no PTY. `RecordingPalette` (test/_render_harness.py) mimics the Palette public API
  deterministically, returning an `Attr(token, flags)` value object (painters OR the result with
  curses flag ints — never AND-mask, verified — so `Attr.__or__` accumulates flags losslessly). It
  replicates the gradient `band()` and exposes `gradient`/`have256`/mono so the painter branches that
  read those are all covered. Faithful to real curses is NOT required: equivalence renders old and
  new painters under the SAME fake, so only self-consistency matters (real-curses is guarded by
  test_tui_smoke).
- `BufferSurface` (tui/surface.py) duck-types `stdscr` (getmaxyx/erase/addstr/move/refresh/derwin),
  so the EXISTING painters render into it unchanged; `derwin` offsets into the shared grid (Theme
  renders every sub-page through it). `grid()` is the sorted comparable snapshot.
- Fixtures are the existing `_sample_*` generators (already built for the Theme preview) + real
  ConfigScreen/ThemeScreen over a live pop ctx.
- **Equivalence is legacy-vs-new, in-process, NOT a committed golden** — profiles/config/theme
  samples read live routes.hu/config.hu, so a golden would churn on every component add. Instead each
  migrated screen keeps its legacy painter alongside the new build_vm/draw and a test asserts the two
  paint the identical grid against the same ctx (the project's proven "byte-equivalent before the
  flip" pattern). Phase 0 itself ships test_render_headless.py (every screen renders headlessly,
  deterministically, across palette modes) + test_surface.py.

## STATUS: core rewrite COMPLETE
All seven screens (plugins, glue, dotfiles, config, theme, profiles, components) are migrated to
`build_vm`/`draw`/`handle` and live in `configsys/tui/screens/`. `run()` is now a lazy `{id: Screen}`
router with one uniform draw and one uniform handle + `Intent`-apply — ~640 lines of per-screen draw
+ dispatch removed from it. Every screen renders headlessly (BufferSurface) and is pinned to its
legacy painter cell-for-cell across sizes × palette modes × states (≈230 equivalence tests). Full
suite green.

**Cleanup DONE (this pass):** the Theme live-preview (`_sample_real_page`) now renders every sub-page
through the NEW screens (a `suppress_sample` guard on ThemeScreen handles theme-previewing-theme), so
the app's runtime no longer touches the legacy painters. The 9 legacy `_draw_*` painters moved out of
`menu.py` into `test/_legacy_render.py` — the frozen equivalence ORACLE (`globals().update(vars(menu))`
resolves their helper references; `_KEYMAP`→`menu._KEYMAP` for the live keymap; relative imports made
absolute). `menu.py` dropped from 6328 → ~4300 lines. The model classes + shared helpers + `_sample_*`
generators stay in `menu.py` (the new screens compose/import them; the preview uses the samples).

**Going-forward test strategy (chosen): fake-data, not golden, not the oracle.** The legacy-vs-new
tests were a one-time neutrality proof. The sustainable form (demonstrated in
`test/test_render_fakedata_demo.py`) pins renders WITHOUT the oracle or golden snapshots:
`build_vm` is fed a HAND-BUILT model and its ViewModel asserted; `draw` is fed a HAND-BUILT ViewModel
and a few representative cells asserted. Both take fixed inputs, so nothing drifts with routes.hu. The
plan: give each screen such a file, then delete `test/_legacy_render.py` + the `*_equivalent` tests.
The oracle is kept "for now" as the safety net until those land.

## Sequencing (incremental, one screen at a time, each behind the harness) — DONE
0. Surface + BufferSurface + `Palette.describe` + the equivalence harness with golden grids for ALL
   screens captured from current code. Commit.
1. Router + Screen protocol + ViewModel base; wire `run()` to the router with every screen still
   calling its OLD `_draw_*` (adapter). Prove the smoke test + harness still pass. Commit.
2. Migrate screens in dependency order, simplest first — plugins/glue/dotfiles (table-shaped),
   then config/theme, then profiles, then components (the richest). Per screen: extract `build_vm`
   (pure), convert the painter to `draw(surface, vm)`, extract `handle`. Harness proves grid
   identity; commit per screen.
3. Delete the dead `_draw_*` shims and the old dispatch branches; `menu.py` is now thin. Final
   harness + smoke + full-suite green. Commit.

## Test alignment
Existing non-curses model tests (`test_tui_nav`, `test_menu_state`, `test_menu_nodes`,
`test_config_overlay`, `test_tui_pin`, `test_tui_provider`, `test_tui_find`, `test_tui_helpers`,
`test_theme_edit`, …) keep passing — the model classes keep their public methods. New coverage:
`test_render_equiv.py` (the harness) + a `test_surface.py` for the Surface/BufferSurface.

Relates to [[code-review-2026-09]] (D2 is its last open refactor), [[tui-color-and-effects]]
(the color modes the harness sweeps), [[profiles-matrix-model]] (the picks model the screens show).
