# Review: TUI core: menu, router, popups, surface

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/tui/menu.py` (5032 lines), `configsys/tui/screen.py`, `configsys/tui/surface.py`,
`configsys/tui/__init__.py`. Context: `docs/tui-architecture.md`, `configsys/tui/screens/base.py`,
`docs/principles.md`, CLAUDE.md, plus the callers/callees needed to judge them (`screens/*.py`,
`routes.Resolver`, `resolve._select`, `installState.ComponentState`, `actions.run_plan`,
`planning.expand_plan`, `app._pin_set` / `_confirm_plan` / `_file_issue` / `load_pipeline`,
`sysupdates`, `primarygit` snapshot/commit, `config.picks/included`, `config.hu` `keys:`).
Tests read: `test_menu_state.py`, `test_menu_nodes.py`, `test_tui_nav.py`, `test_tui_find.py`,
`test_tui_pin.py`, `test_tui_provider.py`, `test_tui_issue.py`, `test_tui_helpers.py`,
`test_surface.py`, `test_fill_bg.py`, `test_scroll_reveal.py`, `test_render_headless.py`,
`_render_harness.py`, `test_tui_smoke.py`, `test_fix_tui_c.py`, `test_execute.py`,
`test_uninstall_queue.py`, `test_direct_color.py`, `test_screen_theme.py`, `test_review_regressions.py`,
the `menu.*` uses in `test_primary_push.py` / `test_primary_safety.py` / `test_splashes.py` /
`test_attrs.py` / `test_config_overlay.py`.

Measurements: a sandbox home (`$RUN/scratch/tui-core/home`, `--os pop`) with **200 picks** over the
real **832-component** catalog; real-curses frame timings taken in a pty (`scratch/tui-core/pty_perf.py`,
direct 24-bit palette); headless timings with `_render_harness.RecordingPalette` and a null surface.
Scratch scripts: `scratch/tui-core/*.py`.

## Carried over from docs/review-2026-09/tui-menu.md (and its README items in this scope)

| earlier finding | status | evidence |
|---|---|---|
| HIGH perf: `profile_untracked_count` recomputed per visible profile row per frame | open | `_parts` was memoized (`d0cf422`), but the count still re-reads `Config.included()` per row: **19.6 → 10.6 ms/keystroke** when memoized → **tui-core-07** |
| HIGH perf: right-pane row loop 3 resolves + 2 layer merges per row | fixed | `d0cf422` (`_parts_cache`, reverse indexes); `is_new` over the whole catalog now 3.6 ms total (~4 µs/row) |
| HIGH perf: `visible_pnodes()` / `_catalog_rows()` rebuilt many times per frame | open (partly fixed) | `visible_pnodes` memoized on a signature (`d0cf422`, 0.002 ms); `_catalog_rows` still uncached (2.5 ms, on every draw + j/k) → folded into **tui-core-07** |
| HIGH MVVM: no view-model seam | fixed | D2: `b13600f` (Surface), `0d092a6` (Screen protocol), `82c7899`, `5a02b55`, `17149b8`, `5641778`; residual (draw reads ctx; samples patch live models) → tui-screens + **tui-core-09** |
| HIGH: `run()` 1300-line monolith, F1 router never built | fixed | `5a02b55` (`_reg`/`_screen` router); `run()` is now 329 lines; residual overlay ladders → **tui-core-08** |
| MED: `note` clobbered by "(also in: …)" | fixed | `468a6d3` (B5); the code now lives in `screens/profiles.py` |
| MED: Theme preview spawns real background work | open (partly fixed) | Profiles sample now stops its warm sweep / stubs probes; Plugins sample still runs `git ls-remote` per real plugin (reproduced), Glue/Dotfiles samples do real probing → **tui-core-09** |
| MED: `_fill_bg` calls `pal.band()` per cell | fixed | `d0cf422` + `f253bc2` (segment cache); 1.8 ms/frame at 200×50 in real curses |
| MED: Components cursor lines run the resolver 3× per keystroke | obsolete | measured over all 449 rows: `_identity_line` 0.04 ms, `_methods_line` 0.06 ms, `_infoblock` 0.03 ms (resolver / `gated_context` caching) |
| MED: `_draw_theme` re-resolves / `_draw_config` re-parses per frame | obsolete (moved) | now `screens/theme.py:83`, `screens/config.py:104` — tui-screens' scope; measured Theme 9.3 ms, Config 4.5 ms per frame |
| MED: draw functions mutate model state | obsolete (moved) | the painters are `screens/*.py` `draw` methods — tui-screens' scope |
| MED: seven modal frames + six hand-rolled modal key loops | open | unchanged; reproduced that they ignore the keymap and page keys → **tui-core-08** |
| MED: three hscroll table renderers + `_hput`/`_put_hscroll` | obsolete (moved) | renderers are in `screens/{plugins,glue,dotfiles}.py` — tui-screens' scope |
| MED: seven page-chrome copies + dead hard-coded legend fallbacks | open (root here) | chrome moved to screens; the root cause (`_KEYMAP` may be None) is `menu.py:71` → **tui-core-21** |
| MED: dead layer-grouped profiles pane, `KEY_TO_OP`, `KEY_TO_SCREEN`, `_DF_CAPTURE_STATES`, `rrows/rncols`, `relation()` | open | all still present and unreachable (grepped) → **tui-core-11**; `show_diag` param / `ov_orph` went with the deleted `_draw*` painters |
| MED: comment drift (retired models) | open | `_describe`, `ProfileScreen` docstring, `(A/D fan out to ✓)`, `_row_component` `m`/`P`, `rrows` "grid", "key 6", "liquid fill" all still there → **tui-core-12** |
| MED: no renderer executed headlessly | fixed | D2: `test_render_headless.py`, `test_screen_*.py`, `test_surface.py`; residual gaps listed below |
| MED ABI: ad-hoc attributes on ctx / MenuState, `os.environ` signalling | open | unchanged → **tui-core-21** |
| LOW naming: 4-tuple rects, overloaded `ms` | open | `_panel` still returns a 4-tuple (`menu.py:2371`); `ms = ctx.config.machine_names()` at `2665`, `2730`, `3424` → **tui-core-27** |
| LOW reuse: smaller duplicate pairs | open | all still present → **tui-core-22** |
| LOW threading: benign races | open (sharpened) | the lock is half-applied and the overlay thread overwrites shared Resolver state → **tui-core-06**; the probe thread has no generation guard → **tui-core-17** |
| LOW security: nothing alarming | obsolete | nothing new in this file beyond the safety items below |
| NIT: function-level imports in hot paths | obsolete | the hot loops moved to `screens/*.py`; what is left in menu.py is off the per-row path |
| NIT misc: `_req_sig` set twice in `_reload` | fixed | `5a02b55` (set once, `menu.py:1646`) |
| NIT misc: `_HELP` hard-codes rebindable keys | open | → **tui-core-20** |
| NIT misc: `_setting_str` special-cases keys, `SPLASH_THRESHOLD` "liquid fill" | open | → **tui-core-27** / **tui-core-12** |
| README D2 structural MVVM (believed done) | fixed | commits above |
| README C3 TUI per-frame recompute | open (regressed) | `d0cf422` reported 8.6 ms/frame; today it's 20 ms/keystroke at 200×50 with 200 picks and the 832-component catalog → **tui-core-07** |
| README D6 `SelectionPolicy` | open (touches this file) | `_why`, `_edges_text`, `_capability_choices` still thread `(cascade, cx, pins, preference, candidate_only)` positionally into the private `resolve._select` (`menu.py:977`, `999`, `1881`) |
| README F "never_auto rename" | open (touches this file) | `_pick_provider_cap` reads the retired-vocabulary `Component.opt_in` (`menu.py:1941`, `1953`); `candidate_only` threaded as above |
| README C4 `diagnostics()` re-resolves per command | open (affects TUI) | `ctx.diagnostics` → `actions.dotfiles_units` → a full `resolve_resilient` (20.8 ms twice in a row, un-memoized) at startup and after every `_reload`; it is also one of the overwriters in **tui-core-06** |

## Cross-cutting themes

- **The tree's "members" are built for install, then used for every op.** A component row's members
  include every unit that row pulled in (its requires closure), which is right for `i`. But `x`, `L`
  and the bulk keys reuse them unchanged. So the TUI removes and holds shared dependencies, and
  upgrades locked units, where the CLI acts only on what you named (01, 02, 04).
- **State carried across a rebuild by hand.** `_reload` and `_rebuild_menu` each copy the MenuState
  view fields one at a time. Many of those fields are ad-hoc attributes assigned from outside
  `__init__`, so a new field gets forgotten: the filter and scroll position are lost on every rebuild
  (03). `ProfileScreen` caches have the same problem; only `_res` follows the routes identity (17).
  The machine-target rebuild in `screens/profiles.py` drops the attr filter the same way.
- **Shared mutable singletons.** A memoized `Resolver` stores per-resolve outputs (06). Other
  cross-module state lives in the `_KEYMAP` global and in `ctx._…` attributes (21). `os.environ`
  carries the effects level.
- **Hand-rolled modal widgets.** There are seven frames, five nav loops and four overlay scroll
  ladders. They drift from the keymap, page keys and help (08, 20).
- **menu.py is still the TUI's grab-bag.** The D2 rewrite moved the painters out. The models, modals,
  samples, help text and startup worker stayed. Screens import 15–27 private `_names` each from
  `menu.py` (components: 27) (10).

## Findings

### tui-core-01 [HIGH] safety — `x` / `L` on a component row also remove / hold its shared dependencies (curl, git, Homebrew, flatpak)
`configsys/tui/menu.py:444-460` (`MenuState.stage`) and `507-533` (`MenuState.toggle_lock`) apply the
op to every member of the target node. A COMPONENT node's members come from `_build_tree:238-253`:
*every* unit whose `requested_as` names the component, i.e. its whole dependency closure. Shared deps
like `apt\curl`, `apt\git`, `script\homebrew` and `apt\flatpak` are members of many rows. So:

- pressing `x` on `ollama` stages the removal of curl, git **and Homebrew itself** (taking every brew
  formula with it);
- `x` on the flatpak app `tenacity` stages `apt\flatpak`;
- `L` on `ollama` runs `apt-mark hold curl git`, which silently blocks their security updates;
  System Updates then reports them as "held, left as-is".

The CLI `configsys remove ollama` / `lock ollama` touch only `brew\ollama`. The TUI prints the plan
before *Proceed? [y/N]*, but a dependency removal buried in a long list contradicts "no surprises" and
CLI parity. `apt-get remove flatpak` also cascades to the packages that depend on it.
**(reproduced)** `scratch/tui-core/repro_rm_dep2.py` (the real model, every unit marked present) →
`x on 'ollama': stages 4 removals incl. shared deps ['apt\\curl', 'apt\\git', 'script\\homebrew']`,
`x on 'tenacity': … ['apt\\flatpak']`, `L on ollama stages: {'apt\\curl': 'lock', 'apt\\git': 'lock',
'brew\\ollama': 'lock', 'script\\homebrew': 'lock'}`. Compare
`python -m configsys --home … --os pop --pretend remove ollama` → `remove brew\ollama … brew uninstall ollama` only.
**Fix:** for `remove`/`lock`/`unlock`, target only the node's OWN units (`m.component.comp == row
component`; on a PROFILE row, each member component's own units). A dependency is acted on only when
its own row is targeted. Keep the full closure for `install`/`upgrade`, where `expand_plan` folds deps
in anyway. Add a test for each op. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced) — an independent run through the real TUI path,
`scratch/verify-tui-core/repro_01_02.py`. Setup: sandbox `--home scratch/verify-tui-core/home --os pop
--pretend`; picks ollama, tenacity, git, lazygit, …; the real `load_pipeline` → `_components_model` →
`MenuState`, built the way `run()` builds it; keys go through `ComponentsScreen.handle` and the merged
keymap, then `_confirm_and_execute` → `run_plan` on the pretend Runner. Only install state is
seeded as present.
- `x` on the `ollama` row (members `apt\curl apt\git brew\ollama script\homebrew`) runs
  `brew uninstall ollama`, then `NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL
  …/Homebrew/install/HEAD/uninstall.sh)"`, then `sudo … apt-get remove -y git` and
  `sudo … apt-get remove -y curl`.
- It is worse than the finding says: `git` is itself a pick here, and the Homebrew uninstaller also
  takes `brew\lazygit`, another pick.
- `L` on ollama runs `sudo apt-mark hold curl`, `sudo apt-mark hold git` and `brew pin ollama`, and
  adds a ledger lock on `script\homebrew`.
- `x` on tenacity stages `{apt\flatpak, flatpak\tenacity}`.
- The CLI with `--pretend`: `remove ollama` runs `brew uninstall ollama` only, `lock ollama` runs
  `brew pin ollama` only, and `remove tenacity` runs `flatpak uninstall --user -y
  org.tenacityaudio.Tenacity` only. `configsys remove --help` says "their dependencies stay".
- The TUI's own Profiles `x` → `!uninstall` → `_seed_uninstall` path already stages only a
  component's own units: a queue of {ollama} gives `{brew\ollama: remove}`.
- Nothing downstream guards it. `expand_plan` folds deps in only for install-type ops, `run_plan` has
  no shared-dependency check, and `plan_companion_cleanup` protects only glue that is still wanted.
  No test covers remove or lock on a component row.
- Blast radius on this Pop 22.04 box, from a read-only `apt-get -s remove`: `curl` takes 11
  packages (`rust-all rustfmt cargo steam-installer steam:i386 steam-libs … rustc curl`), and `git`
  takes `git-lfs git`. The TUI confirm lists only `remove apt\curl (pkg: curl)`.

Severity stays HIGH: a confirm step exists, so this is not CRITICAL.

Caveat on the fix: `m.component.comp == row component` selects NOTHING for a `via: parts`
aggregator. docker's units are `apt\docker-engine` and `service\docker-service`; neither has comp
`docker`, so `x` on docker would do nothing. Use the resolver roots for the row's name instead
(`resolve_with_roots([name])`, which is what the CLI acts on). `_seed_uninstall` has the same blind
spot: a queued `docker` seeds nothing.

### tui-core-02 [HIGH] correctness — bulk `U` / `I` stage upgrades of version-LOCKED components, and ledger-locked drivers then upgrade them for real
`OPS['upgrade']` (`menu.py:36`) is `s.supported and s.outdated`, with no `locked` test, and
`stage_all` (`462-493`) and `stage` (`444-460`, install → upgrade fallback) use it. For drivers whose
lock is the ledger entry (pip, cargo, tarball, appImage, npm…, `driver.py:535-540`), `run_plan` just
calls `drv.upgrade(rc)` (`actions.py:246-247`), so `U` silently defeats the user's version lock. The
CLI's `upgrade --picks` selects `status == 'outdated'` and says "locked picks are left alone"
(`app.py:1043-1063`). Two more inconsistencies:

- `Node.status` (`102-129`) checks `outdated` before `locked`, while `ComponentState.status`
  (`installState.py:118-131`) checks `locked` first. A locked+outdated row reads `outdated` in the
  tracked view.
- The to-do view filters on `ComponentState.status`, so it hides that row, yet `U` stages it: an
  invisible staged op.

**(reproduced)** `scratch/tui-core/repro_lock.py` → `ComponentState.status = locked | tree Node.status
= outdated`, `U (op-upgrade-all) staged: 1 {'pip\\httpie': 'upgrade'}`, `I (op-install-all) staged: 1
{'pip\\httpie': 'upgrade'}`.
**Fix:** exclude `locked` units from `stage_all` (CLI parity). On an explicit `u` of a locked row,
stage nothing and say "locked — L unlocks". Put `Node.status` in the `ComponentState.status` order.
Defense in depth (actions area): `run_plan` refuses `upgrade` on a ledger-locked unit unless asked
for explicitly. **Effort:** S. **Tier:** B.

**Verified:** CONFIRMED (reproduced) — the same harness as 01, with a REAL ledger lock written to
the sandbox `state.hu` (`cargo\bluetui: locked: true`; the pipeline reads `locked=True
lock_source=ledger`). bluetui is seeded as installed 0.4.0 with latest 0.5.0.
- `ComponentState.status` is `locked`, and the default to-do view shows `rows: []`.
- Yet `U` stages `{cargo\bluetui: upgrade}` ("staged 1 upgrade(s)"), and X runs
  `cargo install --force bluetui`. `I` stages the same upgrade. The tracked view's row reads
  `outdated`.
- The CLI `_picks_selection(ctx, 'upgrade')` over the same states returns `[]` ("locked picks are
  left alone").
- Nothing guards it: not `OPS['upgrade']`, `stage_all`, `_confirm_and_execute` or `run_plan`, and
  not the `upgrade` methods of cargo, pip, pipx, npm, tarball or appImage. No test puts a locked unit
  through `stage_all`.
- Scope: on pop, 67 default bindings lock only through the ledger (tarball 21, script 19, pipx 8,
  cargo 7, appImage 5, gem and go-install 2 each, npm, luarocks and font 1 each).
- For tarball and appImage (`targets_version = False`), set-version cannot restore the old version,
  so the defeated lock can't be undone from configsys.
- Native holds (apt-mark hold, brew pin, …) are enforced by the package manager itself, so for those
  drivers the hold survives (by reading).
- The explicit CLI `configsys --pretend upgrade bluetui` also ignores the ledger lock and runs
  `cargo install --force bluetui`. An explicit `u` therefore matches the CLI. The parity break is
  bulk `U`/`I` against `upgrade --picks`, and the proposed `run_plan` defense covers both.

Severity stays HIGH.

### tui-core-03 [MED] correctness — every Components rebuild drops the `F` filter and the scroll position, including the background System Updates fold
`_reload` (`menu.py:1622-1647`) and `_rebuild_menu` (`2127-2148`) each build a fresh `MenuState` and
copy view state across by hand. Both forget `filter` (and `top`). `_fold_system_updates` (`2113-2124`)
runs on a poll tick when the background scan lands. That is seconds after startup and after every
execute / refresh (`screens/components.py` `_rescan_system_updates`). So a filter you just typed
vanishes on its own: the tree un-filters, the `filter:` chip disappears, and the viewport jumps
(`_scroll_top` restarts from `top=0`). A mode switch (`M`), a pin and a return from another screen do
the same. The sibling in `screens/profiles.py:720-728` (tui-screens' file) rebuilds
`ProfileScreen` after the machine-target modal, even on Esc. It keeps a hand-picked `_keep` tuple and
drops the attr filter, the `O` overlay toggle, the expanded tree, `expanded_parts` and the warm
`_res` / `_scan_caches` (so it re-warms ~832 resolves and re-scans).
**(reproduced)** `scratch/tui-core/repro_filter.py` → `before fold: filter='bat' rows=2`,
`after fold: filter='' rows=263`, `after _reload: filter='' rows=263`, `after mode switch: filter='' rows=268`.
**Fix:** one `MenuState.adopt_view(old)` (selection, still-valid staged ops, errors, expansion,
cursor, `top`, `filter`, `mode`, `_req_sig`, descriptions…) used by `_reload`, `_rebuild_menu` and
`_switch_mode`, with every field declared in `__init__`. Do the same for `ProfileScreen`: refresh in
place instead of reconstructing. Add a test that a filter survives each rebuild path. **Effort:** S.
**Tier:** B.

### tui-core-04 [MED] correctness — the default `to-do` view hides tracked picks that aren't green (`partial`, also `error` / `untrusted`), while `I` stages their hidden units
`_components_model` (`menu.py:2085-2093`) decides "actionable" per UNIT, keyed by the unit's *own*
component name (`st.component.comp`). Take a tracked component that is installed but whose required
dependency is missing (`virt-manager` without `libvirt-service`, the docstring's own example at
`3305-3309`). Its own unit is green and the dependency isn't tracked, so the pick vanishes from the
default view. The tracked view shows it as `partial`. `I` (`stage_all`, `requested_as` ∩ picks) then
stages the hidden dependency, so `staged:1` appears with no visible badge. `_TODO_STATUSES`
(`2042`) also omits `error` and `untrusted` (a pick whose plugin driver needs `plugin trust`), so
those never show by default either. The docstring says to-do is "ONLY components needing action for
full green".
**(reproduced)** `scratch/tui-core/repro_todo.py` → `to-do rows: []`, `I staged: 1 {'apt\\libvirt-service':
'install'}`, `tracked rows: [('(other)', 'partial'), ('virt-manager', 'partial')]`.
**Fix:** compute actionable per tracked NAME over the units that group under it (the same
`_name_units` MenuState builds), using the `Node.status` aggregate. Include `partial`, and decide
`error` / `untrusted` (question 3). **Effort:** S. **Tier:** B.

### tui-core-05 [MED] correctness — under a pin, the methods line says "(default: only method here)", never marks the auto-default `*`, and the TUI cannot unpin
`_why` (`menu.py:967-979`) calls `resolve._select(..., r.pins, ...)`. With a binding-pin the
candidates are filtered to the pinned via, so the reason reads `only method here` for a component
with three valid methods. `routes.candidates()` marks the *pinned* binding as `default`
(`routes.py:684-690`). So `_methods_line` (`944-964`) never flags the auto-default with `*`, though
its docstring and `_method_tags` (`926-941`) promise "`via *` (what unpinning would give you)" when
"the divergence is a pin". Nothing in `configsys/tui/` can remove a pin (grep `unpin|pins.pop` → none;
CLI: `configsys pin unset`). Choosing the default in the `v` picker (`_pick_method_name:1819-1857`)
writes `pins: { name: <current default> }`. That freezes the method against a later route change,
for example an AUR → `[extra]` promotion.
**(reproduced)** `scratch/tui-core/repro_pin_star.py` → pinned `bat` to `cargo`: `methods line:  via:
native   [cargo]   brew      (default: only method here · v to change)`, and `native *` flagged? `False`.
**Fix:** have `candidates()` (or a helper) also return the *unpinned* auto-default and its rule.
Render the reason as `pinned`, flag that default with `*`, and add an "auto — unpin" row to the
picker that drops the pin (a shared `actions.unset_pin`, CLI parity). **Effort:** S. **Tier:** B.

### tui-core-06 [MED] correctness — TUI-side resolves overwrite the shared Resolver's per-resolve state that `where` and `context()` read; `_ROUTES_LOCK` is only half-applied
`Resolver.resolve_resilient` stores per-call outputs on the memoized `ctx.routes`: `tighten_pins`,
`dropped_soft_pins` and `provider_rules` (`routes.py:632-644`). `context()` gates drivers with
`tighten_pins` (`routes.py:601-606`), and `where_report` prints `provider_rules` (`app.py:1730`). The
pipeline's second pass (auto-tighten floor pins + detection soft pins, `app.py:476-484`) sets them.
Several resolves without those pins then overwrite them:

- `ProfileScreen._start_overlay_scan` on a daemon thread (`menu.py:2956-2963`; the overlay is on by
  default);
- `installed_scan` (`3364`);
- `ctx.diagnostics` → `actions.dotfiles_units`, at TUI start (`4791`) and after every `_reload` (`1647`).

After any of these, the TUI `w` overlay and the picker's gating no longer describe what the session
resolved. The overlay thread also bypasses `_ROUTES_LOCK` (`2857-2865`), whose comment says it
serializes UI-thread and warm-thread resolves. In practice only `_resolve` (`3626`) takes it;
`_start_overlay_scan`, `_start_probe` (`3010-3034`), `_parts`, `_methods_line`, `available_oses`,
`installed_scan` and `where_report` all drive the same Resolver unlocked.
**(reproduced)** `scratch/tui-core/repro_resolver_state.py`: the pipeline's state is seeded by hand to
stand in for an auto-tighten/detection pass, then `ProfileScreen.overlay()` runs → `tighten_pins = {}`,
`dropped_soft_pins= {}`, `provider_rules has jdk rule? False`. Same result after `ctx.diagnostics(states)`.
**Fix:** (routing area) stop stashing per-resolve outputs on the shared Resolver. Return them, and
keep the pipeline's on ctx (`ctx.resolution`). Then `context()` takes the tighten pins explicitly and
`where` reads ctx. In the TUI, either take `_ROUTES_LOCK` in every thread that touches `ctx.routes`,
or drop the lock and document that only cache-safe calls run off-thread. **Effort:** M. **Tier:** B.

### tui-core-07 [MED] performance — Profiles: ~20 ms per keystroke, nearly half of it `profile_untracked_count` re-merging the picks per visible row
Real curses at 200×50: Profiles **21.1 ms/keystroke-frame** (15.8 ms at 80×24). For comparison:
Components 7.5, Theme 9.3, Config 4.5, Glue 3.6, Dotfiles 3.1, Plugins 2.6. The left pane calls
`profile_untracked_count` (`menu.py:3239-3247`, "Live … not cached") for every visible profile row
(~43 at h=50). Each call runs `Config.included()` → `picks()`, which re-walks every machine-role layer
(`config.py:368-391`, 0.27 ms at 200 picks), plus `members()` and `install_state()` per member.
`_catalog_rows()` (`3488-3498`, 2.5 ms: the attr filter rebuilds a lowercased tag set per catalog
component) runs once per draw and again on every j/k (`screens/profiles.py:494`). During a background
scan the router redraws every 120 ms (`menu.py:4850`), so ~20 ms of UI-thread work competes for the
GIL with the scan it is waiting for. This regressed from `d0cf422`'s 8.6 ms because the cost scales
with #picks × visible profiles.
**(reproduced)** `scratch/tui-core/perf_prof3.py` → `as shipped: 19.6 ms per j+frame`,
`untracked counts memoized: 10.6 ms per j+frame`. `pty_perf.py` → `"profiles": 21.12` (200×50, real curses).
**Fix:** cache the `⊙N` counts keyed on `(name, ceiling, overlay generation, probe-result count,
id(picks))` and bump the generation where the overlay/probe results fold in. Compute `included()` once
per frame. Memoize `_catalog_rows` on a view generation (filters, `expanded_parts`, attr filter,
`lcur`). Redraw on a poll tick only when a generation moved. **Effort:** S. **Tier:** C.

### tui-core-08 [MED] reuse — seven hand-drawn modal frames and the hand-rolled nav loops ignore the keymap and page keys that `config.hu` promises
The same `┌─┐│└─┘` + title + hint block is drawn in `_help_modal:1344-1349`,
`_popup_choose:1728-1732`, `_attr_filter_modal:2614-2619`, `_component_machines_modal:2681-2685`,
`_machines_modal:2747-2751`, `_input_box:3689-3695` and `_order_list:3754-3759`. Five key loops
hard-code `j`/`k`/arrows/`27`/`q`: `_popup_choose:1747-1763`, `_attr_filter_modal:2633-2653`,
`_component_machines_modal:2699-2713`, `_machines_modal:2821-2845` and `_order_list:3766-3784`.
`_attr_filter_modal` (41 rows), `_component_machines_modal`, `_machines_modal` and `_order_list`
handle no PgUp/PgDn/g/G at all. `_popup_choose` and `_report_review` use raw codes (`_PGDN_KEYS`). So a
`down`/`page-down` rebind never reaches a modal, although `config.hu:212` says page-down works in
"all panes + modals". Only `_help_modal` consults `_KEYMAP`. The same six-branch scroll ladder appears
four more times: the where overlay (`4881-4892`), the `!` overlay (`4904-4915`), `_help_modal`
(`1365-1376`) and `_report_review` (`1445-1456`, hard-coded).
**(reproduced)** `scratch/tui-core/repro_modal_keys.py` → `attr modal after PgDn,PgDn,space,enter ->
include = {'cli'}` (PgDn ignored; the first tag toggled), and `popup with rebound down=n: n, enter -> 0`.
**Fix:** a `_modal_frame(surface, pal, box, title, hint)` and a keymap-aware `ListNav.apply(action,
sel, n, page)` used by every modal and overlay. Hints should come from `Keymap.glyph`. About 150 lines
go away, and modal behavior can be unit-tested. **Effort:** M. **Tier:** D.

### tui-core-09 [MED] performance — Theme previews construct REAL screen models: the Plugins sample runs `git ls-remote` for every real plugin
`_sample_plugins_state` (`menu.py:3985-4034`) starts with `PluginScreen(ctx)`. Its `reload()`
(`4330-4340`) reads the real declared plugins, runs `primarygit.state` and starts `_start_remote`
(`4354-4380`): a thread running `primarygit.fetch` (when a primary is declared) and
`plugins.latest_ref` (`git ls-remote`) for each **real** plugin. Then the sample overwrites `rows`
with synthetic ones. Opening Theme → the Plugins preview page therefore makes network calls and
fetches your primary to draw fake data. `_sample_glue_state` (`4037-4055`, 87 ms) and
`_sample_dotfiles_state` (`4058-4074`, 20 ms) likewise run a full real `reload()` (a
`dotfiles_units` resolve + per-spec filesystem probes) before discarding it. `_sample_profiles_state`
(`3893-3982`, 194 ms) constructs a real `ProfileScreen` whose warm thread starts before `_warm_gen` is
poked to stop it. It then monkeypatches five instance methods with lambdas behind the
`_SampleCfg`/`_SampleCtx` proxies; the `_SampleCfg` docstring's "overridden below" has no overrides
below. `_sample_real_page` (`4218-4272`) swallows every exception, so a broken preview never surfaces
(see Test gaps).
**(reproduced)** `scratch/tui-core/repro_sample_net.py` (`latest_ref` stubbed to record, no network) →
`git ls-remote calls the SAMPLE triggered for REAL plugins: ['github:someone/configsys-real']`. Timings:
`_sample_profiles_state 194.3 ms`, `_sample_glue_state 87.3 ms`, `_sample_dotfiles_state 20.6 ms`.
**Fix:** build the sample models without `reload()` (a `load=False` constructor flag, or the sample
fills the fields on `__new__`). Better still, let samples hand each Screen a literal VM, as the
2026-09 refactor intended. Move all `_sample_*` out of `menu.py` (see 10). **Effort:** S–M. **Tier:** C.

### tui-core-10 [MED] refactor — split menu.py: it is still the router plus every model, modal, sample, help text and the startup worker
At 5032 lines, `menu.py` holds:

| Lines | What |
|---|---|
| ~330 | `run()` |
| ~415 | `Node` / `MenuState` |
| ~270 | the execute flow |
| ~810 | `ProfileScreen` |
| ~235 | `PluginScreen` |
| ~215 | `ThemeScreen` |
| ~170 | `DotfilesScreen` / `GlueScreen` |
| ~1000 | 7 modals + `_help_modal` + 2 overlays + `_report_review` |
| ~215 | `_HELP` text |
| ~255 | the `_sample_*` fixtures (test / preview data) |
| ~200 | splash gating + `_InspectWorker` |

Each screen module imports 15–27 *private* names from it (`screens/components.py`: 34 names, 27
private; `profiles.py` 23; `plugins.py` 19). The "model in menu.py, view in screens/" split leaves the
same class name on both sides, which the doc has to explain (`docs/tui-architecture.md` "the name
collision is deliberate"). The two full-page overlays (`_draw_where`, `_draw_diagnostics`) are the
last pre-MVVM painters: they `erase` / `refresh` themselves and clamp-and-return their scroll, and
their key ladders live inline in `run()`.
**(reproduced)** AST count of `menu.<name>` / `from ..menu import` per screen:
`components.py 34 27 · profiles.py 24 23 · plugins.py 20 19 · glue.py 17 16 · theme.py 18 17 ·
config.py 16 15 · dotfiles.py 16 15`.
**Fix:** proposed target layout:

- `tui/models/<id>.py`: each model next to (or merged into) its screen;
- `tui/modals.py`: frame, nav, popup, input, order, attr, machines;
- `tui/widgets.py`: `_put`/`_fit`/panel/scrollbars/`_fill_bg`/nav bar;
- `tui/overlays.py`: Where / Issues as `Screen`s with VMs and `handle`;
- `tui/startup.py`: effects/splash gating + `_InspectWorker`;
- `tui/samples.py` and `tui/help.py`;
- `menu.py`: just `run()`.

This removes the private-import web, makes the overlays testable through the normal protocol, and
gives the 01/03/08 fixes one home each. Do it after the S fixes land. **Effort:** L. **Tier:** D.

### tui-core-11 [LOW] dead-code — unreachable features and stragglers
- **Layer-grouped Profiles pane.** `ProfileScreen.toggle_grouping` (`3175`) has no caller and no key,
  so `grouped` is always False. That makes the following dead: the grouped branch of `visible_pnodes`
  (`3123-3141`), `_GKEY` / `_GROUP_ORDER` / `_GROUP_LABEL` (`2851-2854`), `_fold_role` (which still
  knows a `machine` layer role that no longer exists), `_profile_group(s)` (`3058-3081`),
  `_SYSTEM_GROUPS`, `group_new_count` (`3249-3267`), `_group_new_cache`, `collapsed_groups`,
  `node_group` / `group_ceiling` / `cur_group` / `cur_ceiling` / `cur_readonly`, the group-header
  branches of `expand_cur` / `collapse_cur` (`3182-3200`), the grouped paths in
  `screens/profiles.py:146-191, 232, 514`, and `Config.role_ceilings` (`config.py:416`; its only
  caller is `group_ceiling`). The `ceiling` parameter threaded through
  `members`/`own_members`/`removed_members`/`_profile_counts` is therefore always None.
- `ProfileScreen.relation` (`3595`), `node_kind` (`3146`), `rrows`/`rncols` (`2877`, never read).
- `KEY_TO_OP` (`43`), `KEY_TO_SCREEN` (`1582`), `_DF_CAPTURE_STATES` (`4539`).
- `IMPLEMENTED` (`1581`, every screen): the dim branch in `_draw_nav` and `run()`'s "screen is not
  built yet" (`4979-4980`) can't happen.
- `Intent.quit` (`screens/base.py`, never read; the doc admits it).
- `CursesSurface` (`surface.py:27-52`, used nowhere: not by `run`, not by any test, not by any plugin).
- Test-only in production terms: `_with_uninstall_node` (`616`, last caller removed in `32ef72f`),
  `_menu_model` (`2032`), `_pick_method` (`1811`), `_pick_provider` (`1912`), `is_installed`,
  `clear_all_staged`.
- `_node_component` (`1676-1684`) behaves identically to `_row_component` (`1662-1673`).
- pyflakes: `Path`, `ConfigsysError` and the `OpOutcome` re-export (`588`, re-imported at `798`)
  are unused.

**(reproduced)** grep over `configsys/`, `test/`, `examples/`, `tools/` and `~/src/configsys-*/`
(table under "Dead code"); `.venv/bin/python -m pyflakes configsys/tui/menu.py` →
`'pathlib.Path' imported but unused` / `'..errors.ConfigsysError' imported but unused` / `'..actions.OpOutcome' imported but unused`.
**Fix:** delete the grouping machinery with `role_ceilings` and the ceiling parameters (or bind `L`,
if the two-spaces view is still wanted; question 5). Delete the stragglers. Retarget the tests of the
test-only wrappers to the functions they wrap (`_group_by_owner`, `_pick_method_name`,
`_pick_provider_cap`). **Effort:** S. **Tier:** D.

### tui-core-12 [LOW] comment-drift — docstrings and one on-screen title from retired models
- `_machines_modal` draws the title **`' target machines (A/D fan out to ✓) '`** (`2748`), which the
  user sees. Its docstring and `target_state` (`3441` "what A/D toggles") say the same, but the keys
  are `T`/`t` (`config.hu:297-298`).
- `ProfileScreen` (`2869-2870`): "space toggles membership, `a` toggles a profile active". `space` now
  multi-selects, `a` selects all, and profiles are read-only browse lenses.
- `_describe` (`1688-1690`) and `test_menu_nodes.py`'s docstring: "`ctx.routes` rebuilds a Resolver …
  on EVERY access". It has been memoized since `app.py:330-352`.
- `_row_component` (`1666`): "`m`/`P` on cuda-toolkit-12". The key is `v` (method).
- `ProfileScreen.reload` (`3542`): "The method picker (`m`) is the only edit …". It is `v`, and the
  claim that `_parts_cache` has the "same lifecycle as `_res`" is false (17).
- `rrows`/`rncols` (`2877`): "grid dims … moves by column". There is no grid.
- `grouped` (`2882`): "`L` -> layer groups". Unbound.
- `machines_list` (`3423`): "the defined `machines:` names". `machines:` is retired (`docs/glossary.hu`).
- `_menu_model` (`2033`): "the default 'tracked' mode". The default is `to-do`.
- `# -- Theme editor (its own screen, key 6)` (`3822`). It is key 7.
- `SPLASH_THRESHOLD` (`2172`): "the liquid fill". The default is `braille-bar`.
- `execute_plan` (`593`): "the TUI gets set-version". Nothing in the TUI can stage one (25).
- Module docstrings: `menu.py:1-13` ("MenuState + curses view + run loop") and `tui/__init__.py`
  ("the curses rendering/loop is a thin view over it") predate the screens package.
- `surface.py:3-13`: "The painters (`_draw_*` …)" and "CursesSurface … kept as the explicit adapter for
  tests"; no test uses it. `test_surface.py:2-3` says CursesSurface is "covered by the live pty smoke
  test", which never constructs it.

**(reproduced)** verified by reading each line against `config.hu` `keys:`, `app.py:330`,
`docs/glossary.hu:375-376` and grep for callers.
**Fix:** reword each. Make the modal title read from the keymap
(`f'… ({glyph("track-all")}/{glyph("track-one")} …'`). **Effort:** S. **Tier:** E.

### tui-core-13 [LOW] safety — the direct-colour terminfo cache is written into the REAL home even under `--home` and `--pretend`
`_cache_terminfo_dir` (`screen.py:94-96`) resolves `$XDG_CACHE_HOME` or `os.path.expanduser('~')`.
`_build_direct_entry` / `_tic_direct_entry` (`99-138`) write `<cache>/configsys/terminfo/…` whenever a
truecolor terminal's system lacks the `-direct` entry; the in-code comment says that's a fresh
Debian/Ubuntu/Pop without `ncurses-term`. `curses_screen()` takes no ctx, so it can't honor the
`--home` sandbox or `--pretend` ("a full dry run … no cache … happens"). `test_tui_smoke.py` passes
`dict(os.environ)` (HOME and COLORTERM included) to the TUI under test. On such a box the suite writes
into the developer's real `~/.cache`. The pretend sweep doesn't run the TUI, so nothing catches it.
**(reproduced)** with `XDG_CACHE_HOME` unset and a `--home <sandbox> --pretend` ctx:
`ctx.paths.home = …/scratch/tui-core/home | pretend = True`,
`terminfo cache target = $REAL_HOME/.cache/configsys/terminfo` (no write performed; this box has
`xterm-direct`).
**Fix:** pass the cache directory from `ctx.paths` (a `terminfo/` under the state or cache dir) into
`curses_screen`. Under `--pretend`, build into a temp dir that is removed after `initscr` (ncurses
reads the entry once). In the smoke test, set `XDG_CACHE_HOME` to `tmp_path`. **Effort:** S. **Tier:** A.

### tui-core-14 [LOW] correctness — the System Updates detail line strips the Debian revision, so a pending update reads "no change"
`Node.installed_str` / `latest_str` (`menu.py:143-156`) keep the full version for System Updates rows:
"the change is usually in the Debian revision … that clean_version strips, which would read as 'no
change'". `_infoblock` (`1045-1046`) re-implements the same formatting and calls `clean_version`
unconditionally. The detail line, whose docstring says the versions "show in full" there, therefore
shows identical installed/latest values for exactly those rows.
**(reproduced)** `scratch/tui-core/repro_su_info.py` → `columns : installed=2.39-0ubuntu8.3
latest=2.39-0ubuntu8.4`, `infoblock:  apt\libc6 · scope: system · installed: 2.39 · latest: 2.39`.
**Fix:** one `_version_text(state, field)` used by both, keeping full versions for System Updates
rows, or on the detail line generally since it exists to show them in full. **Effort:** S. **Tier:** B.

### tui-core-15 [LOW] correctness — PgDn / PgUp on Components skip rows
`_page_rows` (`menu.py:67-69`) returns `h - 5` for every screen, but the Components list shows
`h - 9` rows (`screens/components.py:184`). Each page after the first therefore jumps 4 rows past
what was on screen. The other screens' lists have their own heights again.
**(reproduced)** `scratch/tui-core` inline script (24-row terminal, the draw's `_scroll_top`) →
`page jump 19 vs visible rows 15 -> rows never shown while paging 0.. 76 : [20, 21, 22, 23, 39, 40,
41, 42, 58, 59, 60, 61]`.
**Fix:** page by the screen's own list height, which the VM / draw already computes, instead of a
global heuristic. **Effort:** S. **Tier:** B.

### tui-core-16 [LOW] correctness — after `s` in the issue review, the note claims "body saved at <path>" when nothing was saved
`_report_review` (`menu.py:1433-1438`) detects success by searching for the substring `'filed —'` in
`_file_issue`'s text lines. In every other case it returns "not auto-filed — body saved at
{state_dir}/{save_as} (open the link shown)". Under `--pretend`, `_file_issue` files and saves nothing
(`app.py:1271-1273`). When the state dir write fails it leaves `saved = ''`. In both cases the status
note still points at a file that doesn't exist.
**(reproduced)** `scratch/tui-core/repro_issue.py` (`--pretend` ctx) → `note: not auto-filed — body
saved at …/home/.config/configsys/last-os-request.md (open the link shown)`, `file exists: False`.
**Fix:** have `_file_issue` return a small structured result (`filed_url` / `saved_path` / `pretend`)
that both the CLI and the TUI render. **Effort:** S. **Tier:** B.

### tui-core-17 [LOW] correctness — ProfileScreen caches other than `_res` survive a routes rebuild; the probe thread has no generation guard
`aef1da9` keyed `_res` on `id(ctx.routes)` because a pin from *another* screen left it stale. The same
bug class remains in:

- `_parts_cache` (`3275-3302`): a parts list depends on `when:`, pins and plugin layers;
- `_hard_dep_cache` (`3310-3321`): drives the ◐ partial;
- `_avail_os_cache` (`3644-3651`).

None of them is keyed on the routes; they are cleared only by the Profiles screen's own `v` handler.
A pin from Components, or a plugin sync/trust on Plugins (`ctx.invalidate()`), leaves stale twisties,
◐ partials and "where it installs" coverage. `docs/tui-architecture.md` says every screen-local thread
is "generation-guarded so a reload abandons a stale result". `_start_probe` (`3001-3046`) is not: an
in-flight probe writes `_probe_installed[name] = True` into the fresh dict after `invalidate_overlay()`,
so a just-removed component can keep its "installed" underline. `id()` as a cache key is
allocator-dependent; the comment at `3978-3979` concedes this. 0/15 reuse was observed here.
**(reproduced)** verified by reading (no shipped parts aggregator has a second method on pop to
demonstrate the pin path; `id` reuse measured 0/15).
**Fix:** a `ctx.routes_generation` counter bumped in `Context.invalidate()`, and one small
`_RoutesKeyedCache` used for all four caches; add a `_probe_gen` guard in `_start_probe`. **Effort:** S.
**Tier:** B.

### tui-core-18 [LOW] performance — UI-thread stalls with no feedback
Measured stalls, none behind a `_busy` indicator unless noted:

- **Returning to Components after a Profiles edit** runs `_reload` (`menu.py:4966`): 1.52 s with the
  sandbox's 200 picks and real probes reused. The code's own comment puts the pipeline plus
  diagnostics at "~6s on a full machine".
- **The method picker** (`_pick_method_name:1829-1836`) calls `versionreport.report` →
  `_cached_latest` per method before the popup. On a cache miss that is `get_latest`, which can mean
  network.
- **Profiles infobox**: `available_oses` (`3641-3651`, `reportgen.coverage`: 7 resolves) runs inside
  `draw` on the first landing on each unavailable component, **84–131 ms per row**. About 196 of the
  832 components are unavailable on pop, so holding `j` through `!all` stutters.
- **`C` (claim) `installed_scan`** (`3351-3401`): synchronous **5.5 s** (70 commands) behind a busy
  note, with no progress and no cancel.

**(reproduced)** `scratch/tui-core/perf_reload.py` → `_reload on return to Components (UI thread, no
progress): 1.52s`; inline `available_oses` timing → `[84, 93, 115, 131, 105, 16, 15, 88, 11, 120]` ms;
`perf_claim.py` → `installed_scan (C claim, UI thread): 5.5 s, 70 runner commands`.
**Fix:** `_busy(...)` before `_reload` and the picker's version probe. Compute the coverage hint on the
existing single-worker pattern (`PluginScreen._request_diff`) and paint it when it lands. Give the
claim scan a progress line. **Effort:** S. **Tier:** C.

### tui-core-19 [LOW] data-driven — the attrs vocabulary exists only inside the TUI, so nothing lints authored tags (`GPL` is in use but isn't a tag)
`ATTR_AXES` (`menu.py:2570-2579`) is the only machine-readable copy of `docs/component-attrs.md`'s
vocabulary, and it serves only the Profiles filter. `kew` and `foldingathome` carry `GPL`. The spec
says "There is no per-license tag (`GPL`, `MIT`, …): a GPL project is `copyleft`"
(`docs/component-attrs.md:48`). Those two can't be selected by the `f` filter, and neither `check`
nor a test flags them (`test_fix_tui_c.py:165` covers derived attrs only).
**(reproduced)** inline scan over the real catalog → `distinct attrs: 40`, `not in any filter axis: {'GPL': 2}`.
**Fix:** move the axes into the attrs model (`routes.py` / a data file). Have `check` warn on an
unknown tag, and the filter import it. Send the data fix (`GPL` → `copyleft`) to /update-component.
**Effort:** S. **Tier:** D.

### tui-core-20 [LOW] data-driven — `?` help and overlay footers hard-code rebindable keys
`docs/tui-architecture.md` says "Legends and help read the same Keymap, so hints can't drift from
bindings". The `_HELP` glossary (`menu.py:1104-1306`) spells keys in prose: `T / t`, `M`, `E`, `C`,
`O`, `.`, `v`, `m`, `x`, `P`, `H`, `L`, `b`/`B`, `a`/`A`, `s`/`S`, `i`/`I`, `u`/`U`, `R`, `c`.
The `!` page footer (`1399`) advertises `r`/`f`/`s`, which `run()` handles as raw characters
(`4899-4903`) outside the keymap. `_draw_where`, `_help_modal`, `_popup_choose` and `_report_review`
hints are literals too. After a rebind, the `?` page contradicts the footer.
**(reproduced)** verified by reading `_HELP` against `config.hu:229-336`.
**Fix:** write `{track-all}`-style placeholders in `_HELP` and render them through `Keymap.glyph`.
Bind the `!` page's report/request/suggest-OS as `issues`-scope actions. **Effort:** S. **Tier:** D.

### tui-core-21 [LOW] abi — cross-module state bolted on as private attributes, a module-global keymap, and `os.environ` as a channel
- The TUI creates and reads `ctx._reboot_pending`, `ctx._primary_state`, `ctx._primary_push_mode` and
  `ctx._frame` (`4787-4789`, `4818`, `4998-4999`), and `sysupdates` adds `ctx._sysupd_*`.
- `PluginScreen._set_primary_state` writes `ctx._primary_state` from a worker thread (`4352`, `4368`).
- MenuState's `mode`, `_req_sig`, `_uninstall_q`, `_overlay_caches`, `_extra_keys` and `descriptions`
  are assigned from outside `__init__` in four places (`run`, `_reload`, `_rebuild_menu`,
  `_switch_mode`) and read back through `getattr(…, default)`. That is the mechanism behind 03.
- `_KEYMAP` (`71`) is a module global set in `run()` and read by every draw and modal. Tests must set
  it by hand (`_render_harness.build_ctx`), and it is why each screen still carries an
  `if km is not None … else <literal legend>` fallback that is dead in production.
- `resolve_effects` (`2181-2190`) talks to the Palette and splash by mutating `os.environ`.

**(reproduced)** verified by reading (grep `ctx\._[a-z]` / `getattr(ms,` / `_KEYMAP`).
**Fix:** a TUI `Session` object (keymap, frame tick, reboot advice, primary chip/state, System Updates
scan) owned by `run()` and passed to screens. Declare every MenuState field in `__init__`. Build a
default `Keymap` when none is given, so the fallback legends can go. Pass `effects` to `Palette`
explicitly. **Effort:** M. **Tier:** F.

### tui-core-22 [LOW] reuse — smaller duplicates
- `_start_probe.installed_any` (`3013-3034`) and `installed_scan.leaf_installed` (`3370-3391`) are the
  same 20-line routine.
- `_is_companion_comp` (`1998-2005`) duplicates `ProfileScreen._is_companion` (`3511-3517`).
- The "current machine first" ordering is written three times: `machs()` at `2664-2667` and
  `2729-2732` (each binding `ms` to machine names), and `machines_list` (`3421-3430`).
- The pin write is copied three times: `_apply_method_pin` (`1766-1782`), `_apply_provider_pin`
  (`1893-1909`) and the CLI `app._pin_set` (`app.py:2318-2337`, which also validates). One
  `actions.set_pin(ctx, name, value) -> (ok, note)` would serve all three.
- `_confirm_and_execute` (`756-848`) re-implements the CLI's plan preview and confirm
  (`app._confirm_plan`, `app.py:746-766`) with drift. The TUI accepts only `y` where the CLI takes
  `y`/`yes`, and it asks under `--pretend` where the CLI doesn't. Its summary printing is also
  separate.
- Five text-entry loops: `_filter_edit`, `_find_edit`, `_find_edit_tree`, `_input_box` and the inline
  mode of `_machines_modal`.
- `_TuiAutoPushUI.progress` (`703-705`) calls `_TuiPushUI.progress` unbound with a foreign `self`.

**(reproduced)** verified by reading (diffing the pairs by eye; `_pin_set` vs `_apply_method_pin`).
**Fix:** fold each pair into one helper. The pin writer and plan preview belong in `actions` (shared
CLI/TUI). **Effort:** S. **Tier:** D.

### tui-core-23 [LOW] correctness — `Intent.goto` bypasses the screen-entry hooks
`run()` performs the Components rebuild check (dirty / dotfiles / glue dirty / uninstall-queue /
picks change) and the Dotfiles/Glue `reload()` only on the `screens` key path (`menu.py:4943-4981`).
`intent.goto` just assigns `screen = intent.goto` (`5006-5007`). Today only Config `t` → Theme uses it,
so the bug is latent. A future `goto='components'` would show a stale tree.
**(reproduced)** verified by reading (`grep goto=` → only `screens/config.py:354`).
**Fix:** one `_enter(dest)` function used by both paths. **Effort:** S. **Tier:** B.

### tui-core-24 [LOW] correctness — the provider picker's `default` / `current` tags ignore how the resolver actually picks a provider
`_pick_provider_cap` (`menu.py:1934-1966`) tags *every* non-never-auto provider as `default`
(`1953-1954`). When nothing is pinned, its "current" falls back to the alphabetically first non-opt-in
provider (`1941-1943`). It ignores `standing:` ranks, reuse of an installed provider and version
selection (`resolve._pick_provider`). The shipped catalog has no capability with two auto-eligible
providers today, so this is latent until a plugin adds a ranked provider. It also reads the
retired-vocabulary `Component.opt_in` (`never-auto`).
**(reproduced)** verified by reading; a scan of the catalog found 0 capabilities with ≥2
non-`never-auto` providers on pop.
**Fix:** ask the resolver. Resolve a consumer of `cap`, or expose `Resolver.provider_for(cap)` with its
rule, so the tag matches what `where` reports. **Effort:** S. **Tier:** B.

### tui-core-25 [LOW] parity — no TUI path to `set-version` (and no unpin, see 05)
`execute_plan`'s docstring (`menu.py:592-595`) says the shared loop gives the TUI set-version. But
`OPS` has no `set-version`, `MenuState.plan()` carries no version, and `_confirm_and_execute` always
passes `version=None`. The 2026-09 README called the key "a small follow-on; the plumbing is ready".
**(reproduced)** verified by reading (`grep -rn 'set-version\|set_version' configsys/tui/` → only the docstring).
**Fix:** a `set-version` action on Components that opens `versionreport`'s list (or an input box),
stages `('set-version', key)` with the version, and is refused up front for
`targets_version = False` drivers, as the CLI does. **Effort:** M. **Tier:** G.

### tui-core-26 [LOW] safety — terminal setup and teardown aren't failure-safe, and `run()` has no `finally`
- In `curses_screen` (`screen.py:217-247`), `noecho` / `cbreak` / `keypad` / `distinct_return_mode`
  run before the `try:`. An exception there leaves the terminal initialized with no `endwin`.
- The teardown steps aren't individually guarded: a `curses.error` from `nocbreak` skips `endwin`.
- `signal.siginterrupt(SIGINT, True)` is never restored.
- `run()`'s loop has no `finally`. Leaving by Ctrl-C (a `KeyboardInterrupt` is not caught by the
  handlers' `except Exception`) skips `reporter.resume()`, the deferred `pending_notes` (promote hints,
  commit notes) and the `configsys report` nudge.

**(reproduced)** verified by reading.
**Fix:** move the setup calls inside the `try`. Guard each teardown step and restore `siginterrupt`.
Wrap `run()`'s loop in `try/finally` so the reporter resumes and the notes print. **Effort:** S. **Tier:** A.

### tui-core-27 [NIT] linting / naming — leftovers of the painter removal
- Blank-line clusters where painters were cut: `1600-1603`, `3658-3660`, `3819-3821`, `4288-4290`,
  `4523-4529`, `4699-4703`.
- A stray `# -- Profiles screen --` heading in `run()` (`4983`).
- `_routes_lock(ctx)` (`2863`) ignores its argument.
- `_panel` returns a 4-tuple unpacked under ad-hoc names in every caller; a
  `Rect(top, left, h, w)` would read better.
- `_setting_str` (`3787-3800`) special-cases `scope` / `driver-preference` by key inside a
  kind-formatter.
- The h-scroll thumb `'🬋'` (U+1FB0B, `2418`) is missing from common monospace fonts (DejaVu Sans
  Mono) and shows as tofu.
- `_sample_components_state` wraps `toggle_expand_all()` in a needless `try/except`.

**(reproduced)** verified by reading; pyflakes as in 11.
**Fix:** delete / rename as listed; pick a thumb glyph from Block Elements (`▀`/`━`). **Effort:** S. **Tier:** D.

## Test gaps

- **01 / 02 / 04 / 03 have no tests:**
  - component-row `remove` / `lock` must not touch shared dependency units;
  - bulk `U` / `I` must skip locked units;
  - `Node.status` must order `locked` vs `outdated` like `ComponentState.status`;
  - to-do must include a `partial` pick;
  - a filter, scroll `top`, errors and expansion must survive `_reload`, `_rebuild_menu`,
    `_fold_system_updates` and `_switch_mode`.
- **Modals are untested beyond `_popup_choose` via the method picker.** No tests cover
  `_attr_filter_modal`, `_component_machines_modal`, `_machines_modal` (add / rename / remove / `m`),
  `_order_list` (grab / move), `_input_box` (Tab completion, the toggle line, Ctrl-U), `_help_modal`
  (scroll), or `_draw_where` / `_draw_diagnostics` rendering. Page-key and rebind behavior is
  untested everywhere (08).
- **The Theme preview hides breakage.** `_sample_real_page` swallows every exception, and no test
  renders each of the 7 preview pages and asserts its content. Reproduced: with `_sample_profiles_state`
  raising, the Theme render still yields the same 4800 cells (`scratch/tui-core/repro_preview.py`).
  Parametrize over `ts.page` and assert a page-specific string per slot.
- **The router (`run()`) is exercised only by the pty smoke test.** No headless router test covers the
  overlay key handling, the switch-to-Components rebuild conditions, `Intent` adoption, the
  `_commit_primary_action` bracket per key, or the poll-tick fold. A `run_loop(ctx, surface, keys)`
  seam (from 10) would allow one.
- **`test_tui_smoke.py`** writes the retired `configs: [ mine ]` (`:48`). Its comment ("an active
  profile with an unroutable component → a real diagnostic") describes the retired model. It never
  visits screens 3/6/7 in real curses, where Theme's `derwin` and Plugins' polling run, and it
  inherits the real `HOME` / `XDG_CACHE_HOME` (13).
- **Untested pure helpers:** `_chosen_splash` / `_splash_forced` / `_splash_linger`, `_wordwrap`,
  `_wrap`, `_current_via`, `_is_ssh`, `_plugin_code_elem`.
- **`screen.py`:** `curses_screen` / `suspended` / `distinct_return_mode` are covered only by the pty
  smoke test; the terminfo cache-dir choice is untested.
- **Duplicated test fakes.** Five copies of a scripted-`getch` `BufferSurface` subclass
  (`test_tui_issue`, `test_tui_pin`, `test_tui_provider`, `test_tui_find`, `test_splashes`). One
  `ScriptedSurface` in the harness would serve all.

## Dead code

Each entry was grepped over `configsys/`, `test/`, `examples/`, `tools/`, `~/src/configsys-*/` (no
plugin imports `configsys.tui.menu` / `screen` / `surface`) and checked against the frozen ABI list in
`configsys/driver.py` (none of these is on it):

| item | grep evidence |
|---|---|
| `toggle_grouping` + the whole grouped pane (`grouped`, `collapsed_groups`, `_GKEY`, `_GROUP_ORDER`, `_GROUP_LABEL`, `_fold_role`, `_profile_group(s)`, `_SYSTEM_GROUPS`, `group_new_count`, `group_ceiling`, `cur_ceiling`, `cur_group`, `cur_readonly`, `node_group`, `is_group_header` branches) + `Config.role_ceilings` | `grep -rn 'grouped *=\|toggle_grouping'` → only the definition and `= False`; `role_ceilings` → only `group_ceiling` |
| `ProfileScreen.relation`, `node_kind`, `rrows`/`rncols` | `grep -rnw relation\(` → none; `node_kind` refs=0; `rrows` only assigned |
| `KEY_TO_OP`, `KEY_TO_SCREEN`, `_DF_CAPTURE_STATES` | defined, never referenced |
| `IMPLEMENTED` dim / "not built yet" branches | `IMPLEMENTED` = all 7 `SCREENS` ids |
| `Intent.quit` | `grep 'quit=True\|\.quit *='` → none |
| `CursesSurface` | only `surface.py` and docstrings |
| `_with_uninstall_node`, `_menu_model`, `_pick_method`, `_pick_provider`, `ProfileScreen.is_installed`, `MenuState.clear_all_staged` | referenced only by tests (`test_uninstall_queue`, `test_config_overlay`, `test_tui_pin`, `test_tui_provider`, `test_menu_state`) |
| `_node_component` (≡ `_row_component`) | identical bodies; both used |
| unused imports `Path`, `ConfigsysError`, `OpOutcome` re-export | pyflakes; no `menu.OpOutcome` user in tests |

## ABI / interface candidates

- Nothing in these four files is plugin-facing: no plugin repo imports them, and splashes get the raw
  window through `splashes.py`.
- The internal interfaces worth fixing now are in 21 (Session object, MenuState fields, default
  Keymap) and 06 (`Resolver` should return per-resolve outputs instead of storing them).
- The `Surface` contract (`surface.py`) omits `getch` / `timeout` / `keypad`, which every modal and
  `handle` needs. That is why tests subclass it five times. Define an `InputSurface` protocol, or give
  `BufferSurface` an optional scripted key queue.
- The duplicated pin/confirm logic (22) should become `actions`-level APIs before a second front end
  appears.

## Questions for the user

1. Component-row `remove` / `lock` / `unlock` (01): target only the component's OWN units, as the
   CLI does, with dependencies actionable only from their own rows? (Recommended.) And should a
   PROFILE-row `x` keep meaning "everything under it"?
2. Locks (02): bulk `U` / `I` should skip locked components (CLI parity). Should an explicit `u` on a
   locked row also refuse ("L to unlock"), or proceed because you asked for it?
3. Should the default `to-do` view also show tracked components in `error` or `untrusted` state? They
   need action, though not an install.
4. Should the `v` picker get an "auto — unpin" entry (05), with `pin unset` parity?
5. Delete the unreachable layer-grouped Profiles pane (11), or bind it (`L`)? Also, what is your
   appetite for the menu.py split (10, L effort)?
