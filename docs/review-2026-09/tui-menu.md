# Review: configsys/tui/menu.py (6334 LOC) — read-only findings

All line numbers refer to `/home/schrock/src/configsys/configsys/tui/menu.py` unless another path is given.
Every claim below was verified by reading the cited lines (and, where a cost claim depends on another module,
that module's implementation: `app.py:292-332`, `config.py:132-733`, `routes.py:421-487`, `resolve.py:97-117`,
`layers.py:208-228`, `tui/theme.py:498-663`, `tui/keyspec.py:103-136`, `orphans.py:246-271`, `plugins.py:80-85`).

## Themes

1. **MVVM is aspirational, not structural.** The `_SampleCfg`/`_SampleCtx` proxy that lets the Theme preview render
   the REAL `_draw_profiles` is applied to ONE screen. The Components sample renders with the real `ctx` (so its
   methods/edges/location lines come from real routes, not the synthetic tree); Plugins/Glue/Dotfiles samples "work"
   only because those draw functions happen to never read their `ctx` parameter; Config/Theme samples are the real
   live objects. Draw functions read `ctx.config.*` / `ctx.routes.*` / driver methods directly in row loops and
   per-frame tails, and they also WRITE model state (cursor clamps, scroll tops, `lhmax/rhmax`). There is no
   view-model seam; the "model" is the Screen class plus whatever the draw function pulls live.
2. **Per-frame recomputation is the dominant cost, concentrated in the Profiles screen.** Uncached
   `_parts()` (rebuilds a resolve context + evaluates every `when:` predicate) is called 3x per visible row per frame,
   `profile_untracked_count()` is explicitly "live, not cached" and for the `!all` row walks the whole catalog calling
   `install_state()` -> `_parts()` per component per frame, `visible_pnodes()` is rebuilt ~7x per frame (each time
   calling `profile_layer_defs` for every profile), and `Config.is_new()` does two layer merges per row. Elsewhere:
   `_draw_config` re-parses the user config file every frame, `_draw_theme` re-resolves the theme every frame,
   `_fill_bg` calls `pal.band()` once per screen cell, and the Components cursor line runs the resolver 3x per keystroke.
3. **Heavy copy-paste across screens.** Seven hand-drawn modal frames, six hand-rolled j/k/PgUp/PgDn/esc modal loops
   (only `_help_modal` honors the keymap), five text-entry loops, three near-identical table renderers
   (plugins/glue/dotfiles), seven copies of the page-chrome prologue/epilogue plus a second, effectively-dead
   hardcoded legend string per screen, and cursor-nav `if` ladders repeated for six screens inside a 1300-line `run()`.
   The F1 "screen router" from `docs/tui-screens-plan.md` was never built; `run()` is the router.
4. **Comment/docstring drift from retired models.** Several docstrings still describe the pre-matrix profile editor
   (`space toggles membership`, `A/D fan out`, `m`/`P` keys), `_describe` still justifies itself with a
   "ctx.routes re-parses on every access" claim that `app.py:292` memoization made false, and the install-overlay
   comments describe orphan colouring that the draw no longer performs.
5. **Dead/unreachable code from retired features.** The layer-grouped profiles pane (`grouped`, `collapsed_groups`,
   `_GKEY`, `group_new_count`, `toggle_grouping`, `cur_readonly`, `group_ceiling`) has no key binding and is
   unreachable; `KEY_TO_OP`, `KEY_TO_SCREEN`, `_DF_CAPTURE_STATES`, `rrows/rncols`, `relation()`, the `show_diag`
   parameter of `_draw`, and the unpacked-but-unused `ov_orph, ov_uninst` are stragglers.
6. **Test coverage is thin where the code is thickest.** No test renders any `_draw_*` function (a fake-curses
   `_Scr` already exists in `test/test_tui_pin.py:12` but is only used for popups); the pty smoke test never visits
   screens 3/6/7 (Plugins/Config/Theme); the `_sample_*` tests assert data shape only. One real bug slipped through
   as a result (the `note` clobber, below).

## Structural map

| Lines | Region |
|---|---|
| 1-57 | module doc, imports, `OPS`, `KEY_TO_OP` (dead), `_COMP_OPS`, paging keys, `_KEYMAP` global |
| 60-131 | `Node` — tree node + aggregate status |
| 133-497 | `MenuState` — Components tree model (pure, well tested) |
| 501-669 | execution: `OpOutcome`, `_fail_detail`, `execute_plan`, `!uninstall` folding, `_confirm_and_execute` |
| 673-902 | rendering primitives + Components cursor-line builders (`_columns`, `_scroll_top`, `_fit`, `_put`, `_methods_line`, `_why`, `_edges_text`, `_identity_line`, `_infoblock`, `_wrap`, `_wordwrap`) |
| 905-1119 | `_HELP` text + `_help_modal` |
| 1121-1218 | overlays (`_draw_diagnostics`, `_draw_where`), `_fill_bg`, `SCREENS`/nav bar |
| 1220-1365 | `_draw` — the Components screen renderer |
| 1368-1440 | `_reload`, row->component helpers, `_describe` |
| 1442-1737 | modals + pin pickers (`_popup_choose`, method/provider/choices pickers, `_apply_*_pin`) |
| 1739-1851 | Components model builders (`_group_by_owner`, `_menu_model`, `_components_model`, `_rebuild_menu`) |
| 1853-2048 | splash/effects gating + `_InspectWorker` (startup progress) |
| 2051-2245 | F2 primitives (`_panel`, `_thumb`, scrollbars), fuzzy find/filter loops |
| 2250-2525 | Profiles modals (attr filter, per-component machines, machines manager) |
| 2527-3286 | `ProfileScreen` — the biggest state class (overlay/probe threads, tree, catalog, install_state, caches) |
| 3288-3693 | `_draw_profiles` — the biggest renderer (~400 lines) |
| 3696-3833 | `_input_box`, `_order_list`, `_setting_str` |
| 3836-3974 | `ConfigScreen` + `_draw_config` |
| 3977-4200 | `_sample_*` builders + `_SampleCfg`/`_SampleCtx` proxies |
| 4203-4499 | `ThemeScreen`, `_sample_page`/`_sample_real_page`, `_draw_theme` |
| 4501-4744 | `PluginScreen` + table/diff renderers |
| 4746-5027 | `DotfilesScreen`, `GlueScreen`, their cell/draw functions |
| 5030-6334 | `run()` — 1300-line loop: splash, lazy screen construction, screen switch/invalidations, then one `if screen ==` block per screen with the full key ladder |

---

## Findings

### [HIGH] performance — `_draw_profiles` left pane recomputes the whole catalog's install state every frame
`configsys/tui/menu.py:3389` calls `ps.profile_untracked_count(name, _ceil_r)` for every visible profile row on
every frame. That method (`2895-2903`) is documented as "Live ... not cached": it calls `ctx.config.included()`
(-> `picks()` layer walk, `config.py:359-382`), `self.members(name, ceiling)` (a full `profile_components`
expansion), then `install_state(c, force=True)` for EVERY member. `install_state` (`2974-2995`) calls `_parts(c)`,
which is uncached (`2925-2953`): it rebuilds `r.cascade.context(...)` and runs `candidate_bindings` (evaluating each
binding's `when:` predicate, `resolve.py:97-117`) per call. For the always-present `!all` browse row that is every
component in the catalog (~280) x a resolve-context build + predicate evals, per keystroke, before the right pane
is even drawn. **Why:** this is the single largest per-frame cost in the TUI and grows linearly with the catalog.
**Recommend:** (a) memoize `_parts()` per reload (it depends only on routes + pins, both invalidated via
`ctx.invalidate()` — `_res` at `3254-3265` already models exactly this), (b) cache the untracked count keyed by
`(name, ceiling, overlay_generation, probe_generation)` and bump a generation in `overlay()`/`_start_probe.run`,
(c) compute `included()` once per frame and pass it in.

### [HIGH] performance — `_draw_profiles` right-pane row loop does 3 resolves + 2 layer merges per row per frame
`3589-3658`: per visible row, `ps._parts(name)` is called three times — directly at `3596`, inside
`install_state` at `3602`, and via `is_expandable` at `3619` — each a fresh context build + predicate evaluation
(see above). `ctx.config.is_new(name)` at `3605` performs `dispositions()` (a `merge_scalar_map` layer walk,
`config.py:145-156`) AND `uninstall_queue()` (a `merge_scalar` + set build, `config.py:464-470`) per row.
`ps.origin(name)` at `3631` does `str(Path)` conversions of four paths per row (`3054-3069`). Then ~10
`pal.style()` calls and ~10 `_hput` calls per row. **Recommend:** build a per-frame (or per-reload) row view-model:
`new_set = {c for c in catalog if is_new(c)}` computed ONCE per reload (its inputs are `dispositions()`,
`uninstall_queue()`, and the already-memoized `user_layer_components()`); memoize `_parts` and `origin`; then the
loop is pure string/attr emission. Same shape as the `_res` cache that fixed the earlier ~1.5s lag (`3191-3193`).

### [HIGH] performance/architecture — `visible_pnodes()` and `_catalog_rows()` are rebuilt many times per frame and per keypress
`visible_pnodes()` (`2748-2797`) iterates every profile calling `_profile_groups(p)` -> `ctx.config.profile_layer_defs(p)`
(`2735-2744`) and then `cfg.profile_includes(name)` per root. It is called via `cur_node()` (`2827-2829`) by
`cur_curate`, `cur_group`, `cur_ceiling`, `cur_readonly`, `cur_profile`, and directly. In one `_draw_profiles` frame:
`3299`, `3300`, `3316`, `3417` (-> `_catalog_rows` -> `_base_catalog` -> `scoped_members` -> `cur_curate` + `cur_ceiling` = 2 more),
`3429`, `3431` — about seven full rebuilds. `_catalog_rows()` -> `_base_catalog()` (`3116-3127`) does a full
`profile_components` expansion + attr filter and is also called on every `j`/`k` in the key handler (`5264`, `5269`,
`5274`, `5279`) and again inside the draw. **Recommend:** memoize both on a small `_view_gen` counter bumped by every
state mutation (filters, expand/collapse, focus, reload, `attr_inc/exc`, `expanded_parts`, `lcur` for `scoped_members`).
This is the natural seed of a view-model layer.

### [HIGH] data-driven/MVVM — no view-model seam; draw functions read the data source directly and the sample proxy is applied to one screen only
Evidence of live reads inside renderers: `_draw_profiles` reads `ctx.config.dispositions()` `3304`,
`profile_excludes` per ancestor per row `3377`, `profile_layer_defs` `3426`, `profiles_containing` `3513` (which itself
expands EVERY profile twice, `config.py:472-494`), `picks/uninstall_queue/included` `3530-3532`, `is_new` per row `3605`,
`current_machine` `3666`; `ctx.routes.components` `3447`/`3476`, `ctx.routes.dependents(cur)` `3499` (a full scan of
every component's bindings, `routes.py:461-487`). `_draw` (Components) reads `refreshstate.age_days` `1244`,
`ctx._reboot_pending` `1256`, and its three cursor lines (`1339-1342`) call `_edges_text` -> `_select` (a resolve),
`_methods_line` -> `candidates()` + `_why` -> `_select` again, and `_infoblock` -> `get_driver(...).location(rc)`.
`_draw_config` calls `_pl.declared(ctx.paths.user_config_file)` at `3874`, which READS AND PARSES THE CONFIG FILE
(`plugins.py:80-85` -> `layers.read_setting`) every frame, plus `actions.edit_target(ctx)` `3962`. `_draw_theme` calls
`ts.reload()` `4400` (-> `resolve_theme` + `ctx.config.theme()`) every frame, and `actions.edit_target` `4476`.
The sample proxy (`_SampleCfg`/`_SampleCtx`, `4025-4045`) is used only by `_sample_profiles_state`; the Components
sample is drawn with the REAL ctx (`4358`), so its methods/edges/location lines come from real routes for synthetic
names (`libfoo`/`ondistro` don't exist -> blank lines); Plugins/Glue/Dotfiles previews work only because
`_draw_plugins`/`_draw_glue`/`_draw_dotfiles` never touch their `ctx` argument. **Why:** the user's stated priority is
a clean model/view/source split; today the "source" leaks into every view and the mock pattern is accidental.
**Recommend:** see "Top refactor" at the end — a per-screen `ViewModel` dataclass (rows with final strings + roles,
header/status/legend data) built by `Screen.build_vm(ctx, geometry)` and consumed by a pure `draw(stdscr, pal, vm)`.
Samples then construct VMs directly, no proxies, no threads.

### [HIGH] architecture — `run()` is a 1300-line monolithic router; the planned F1 screen router was never built
`5030-6334`. All seven screens' key ladders live inline, each with its own copy of down/up/page/top/bottom
(`5260-5279`, `5429-5435`, `5539-5554`, `5641-5656`, `5716-5755`, `5836-5847`, `5978-6004`), its own `try/except
Exception -> note` wrapper, and its own lazy construction (`5129-5150`). `docs/tui-screens-plan.md:29-33` locked a
`{screen: (draw_fn, handle_key_fn)}` router with each screen owning its state; only the state-object half happened.
**Recommend:** a `Screen` protocol (`draw(stdscr, pal, note)`, `handle(ch, action) -> note|None`, `reload()`,
`on_enter()`, `dirty`) with a `ListNav` helper (cursor attr + length fn) that collapses the six nav ladders. The
cross-screen invalidation soup (`menu_dirty`/`df_dirty`/`q_changed`/`req_changed`, `5222-5246`) becomes a single
`ctx.write_generation` compared against each screen's `built_at`.

### [MED] correctness — footer note is clobbered by the profile "(also in: …)" line
`3441`: `note = '(also in: ' + ...` reassigns the `note` PARAMETER of `_draw_profiles` inside the left-focused
profile-definition box. `3668-3669` then appends `note` to the status line. Whenever the left pane is on a profile
defined in more than one layer, the action feedback ("2 tracked on laptop", "edit failed: …") is replaced by
"(also in: repo)". **Recommend:** rename the local (`also_note`).

### [MED] side effects — the Theme preview of the Profiles page spawns real background work
`_sample_profiles_state` (`4047-4115`) constructs a real `ProfileScreen(ctx)` (`4057`), whose `reload()` runs
`_warm_cache()` (`3196-3216`): a daemon thread resolving the entire catalog (~17 ms each per its own comment). Then every
preview frame ends `_draw_profiles` with `ps.ensure_probes(_shown)` (`3659-3660`) because the sample sets
`show_install = 1` and an EMPTY overlay (`4058-4059`) — so every visible synthetic row is "not in ov" and gets queued;
`_start_probe` (`2664-2709`) then runs real `drv.get_version(rc)` subprocess probes through the real runner
(`_SampleCtx.__getattr__` delegates `runner`). Opening Theme -> F2 launches package probes for whatever is on screen.
**Recommend:** the sample should neutralise the live machinery (`ps.ensure_probes = lambda names: None` and skip
`_warm_cache` via a `warm=False` ctor flag) — or, with the VM refactor, samples never own live objects at all.

### [MED] performance — `_fill_bg` calls `pal.band()` once per screen cell
`1177-1192` loops `for y in range(h): while x < w: pal.band(y, x, h, w)` and again inside the run-length inner loop;
`band()` (`theme.py:616-620`) is two divisions + int + min. On a 200x50 terminal that is ~10k Python calls per frame
before any content is drawn, on every keystroke, on every screen with a gradient. `band` is monotone non-decreasing
in `x` for fixed `y` and depends only on `(h, w, n_bands)`, so the segment boundaries can be computed arithmetically
(`x_start(b) = ceil(((b/n)*2 - y/(h-1)) * (w-1))`) or the per-row segment list cached per `(page, h, w)` — the
gradient is static until a resize or theme edit. **Recommend:** cache `[(x0, x1, attr)]` per row per `(page, h, w)` in
the Palette; `_fill_bg` becomes `h` `addstr` calls with no per-cell work.

### [MED] performance — Components cursor lines run the resolver three times per keystroke
`1339-1342`: `_identity_line` -> `_edges_text` (`802-831`) calls `_select(...)`; `_methods_line` (`764-784`) calls
`ctx.routes.candidates(name)` (`routes.py:421-459`: `candidate_bindings` + `via_representatives` + `_select`) and then
`_why` (`787-799`) calls `_select` a third time; `_infoblock` (`849-875`) calls `get_driver(...)` + `location(rc)` (cheap
for the drivers checked: tarball/pip/npm/flatpak return strings; `_alt.py:198` does a path lookup). All three depend only
on the cursor's component + routes. **Recommend:** memoize the three strings per `(node.id, routes-generation)` on
`MenuState` (drop on `_reload`); `_why` can reuse the `_select` result already computed in `candidates`.

### [MED] performance — `_draw_theme` re-resolves the theme every frame; `_draw_config` re-parses config every frame
`4400` `ts.reload()` per frame (`4251-4261`: `ctx.config.theme()` + `resolve_theme` + list rebuilds), and the nested
'theme' preview calls `state.reload()` again (`4371`). `3873-3874` `_pl.declared(ctx.paths.user_config_file)` per
frame reads the user config from disk (`plugins.py:84`). **Recommend:** every theme edit already goes through
`actions.set_theme_value` + `pal = Palette(...)` in the handler (`6016-6117`) — set `ts.stale = True` there and reload
lazily; `has_primary` belongs in `ConfigScreen.reload()`.

### [MED] MVVM — draw functions mutate model state (draw -> model back-channel)
Renderers write into the state objects: `ms.top`/`ms.reveal` `1285-1287`; `ps.ltop/lhmax/lhoff/rcur/rtop/rcol_left/rhmax/_probe_dirty`
`3329-3331`, `3410-3411`, `3540-3541`, `3561-3563`, `3587`; `cs.top` `3927-3930`; `ts.map_top/map_ncols/map_rows_per_col/role_cur/role_top`
`4412`, `4415`, `4433`, `4437`; `pl.hscroll/top/dfile/dtop/dhscroll` `4661`, `4666`, `4696`, `4704`, `4706`; `gs.top/hscroll`,
`ds.top/hscroll`. The key handlers then read `lhmax`/`rhmax` "set at draw" (`5295`, `5302`). **Why:** it makes the
first frame after a resize/edit depend on the previous frame's geometry and blocks headless testing of clamping.
**Recommend:** a `layout(h, w)` step on each Screen (or the VM builder) that owns clamping and scroll math; `draw`
becomes read-only.

### [MED] code reuse — seven hand-drawn modal frames and six hand-rolled modal key loops
Frames: `_help_modal 1086-1091`, `_popup_choose 1473-1477`, `_attr_filter_modal 2294-2299`,
`_component_machines_modal 2361-2365`, `_machines_modal 2427-2431`, `_input_box 3723-3729`, `_order_list 3788-3793` —
identical `┌─┐│└─┘` + title + hint code. Key loops hardcode `ord('j')`/`curses.KEY_DOWN`/`27`/`ord('q')`/`_PGDN_KEYS`
in `_popup_choose 1493-1508`, `_attr_filter_modal 2314-2333`, `_component_machines_modal 2380-2393`,
`_machines_modal 2501-2524`, `_order_list 2801-2818`; only `_help_modal` (`1104-1118`) consults `_KEYMAP`, so a user
who rebinds `down` gets the rebind on pages but not in modals (and `_help_modal` ignores the raw PgUp/PgDn codes the
others accept). **Recommend:** `_modal_frame(stdscr, pal, box, title, hint)` + `_modal_nav(ch, sel, n, vis)` returning
the new selection, both keymap-aware; ~150 lines removed.

### [MED] code reuse — three copies of the hscroll table renderer and two copies of the hscroll put primitive
`_draw_plugins_table 4652-4679`, `_draw_glue 4897-4932`, `_draw_dotfiles 4969-5005` each: compute `cells_by_row`,
`widths`, `xs`, `virt_w`, clamp `hscroll`, sticky header via `_put_hscroll`, row loop with selection fill, then
`_scrollbar_v`/`_scrollbar_h`. `_hput` (`3565-3573`, a closure in `_draw_profiles`) and `_put_hscroll` (`4621-4629`)
implement the same clipped-horizontal-put. **Recommend:** `_draw_table(stdscr, pal, rect, headers, cells, row_style,
cur, top, hscroll, display=None)` returning the clamped scroll values; delete `_hput`.

### [MED] code reuse — seven copies of page chrome and a second, dead legend source of truth
Prologue `erase/getmaxyx/use_page/_fill_bg/_draw_nav` at `1223-1231`, `3289-3294`, `3853-3858`, `4394-4399`,
`4717-4722`, `4885-4890`, `4955-4960`; epilogue status+footer with an `if _KEYMAP is not None … else <hardcoded string>`
at `1349-1363`, `3679-3691`, `3965-3972`, `4479-4497`, `4732-4742`, `4943-4950`, `5019-5026`. `_KEYMAP` is set at
`5091` before any draw runs, so the seven hardcoded fallback legends are dead in production yet must be kept in sync
by hand (e.g. `1360` lists `X exec`/`R refresh` as literals). **Recommend:** `_begin_page()`/`_end_page()` helpers and a
data table `LEGEND = {screen: [(action, label), …]}` rendered by one function; delete the string fallbacks (or make
`Keymap` always exist and construct a default in tests).

### [MED] dead code — the layer-grouped profiles pane is unreachable
`toggle_grouping` (`2831-2834`) has no caller; no `profiles` action in `keyspec.py:171-173` maps to it. Consequently
`grouped` is always False, so `visible_pnodes` always takes the flat branch (`2776-2779`), `node_group()` is always
None, `group_ceiling()` always None, `cur_readonly()` always False (the `' · browse-only'` title at `3431` never
shows), the `_GKEY`/`_GROUP_ORDER`/`_GROUP_LABEL` constants (`2530-2533`), `group_new_count` (`2905-2923`),
`_group_new_cache`, `collapsed_groups`, the group-header branches in `expand_cur/collapse_cur` (`2838-2841`,
`2853-2856`), `is_group_header`, the `group_counts` block (`3334-3339`) and the `kind == 'group'` row branch
(`3353-3362`) are dead. The per-layer `ceiling` plumbing (`_ceil`, `_ceil_r`, `members(…, ceiling)`) is likewise always
None in practice. **Recommend:** either bind it (`L` per its own comment at `2832`) or delete ~150 lines and the
ceiling parameters. Also dead: `KEY_TO_OP` `38-40` (dispatch is via keymap + `_COMP_OPS`), `KEY_TO_SCREEN` `1200`
(`keymap.screen_for` is used), `_DF_CAPTURE_STATES` `4754`, `ProfileScreen.rrows/rncols` `2545` (a pre-table grid
remnant), `relation()` `3246-3252` (no caller), `ov_orph, ov_uninst` unpacked at `3305` and never read, the
`show_diag`/`diag_top` parameters of `_draw` (`1220-1222`; every caller passes `False`, `run` handles the overlay
itself at `5126`).

### [MED] comment drift — docstrings describing retired models
- `1433-1435` `_describe`: "`ctx.routes` rebuilds a Resolver (re-parsing routes.hu) on EVERY access" — false since
  `app.py:292-312` memoizes it (the `1390` "never hit ctx.routes per frame" motivation is likewise stale, though the
  caching remains good practice).
- `2537-2538` `ProfileScreen` docstring: "Two-panel profile editor … space toggles membership, `a` toggles a profile
  active" — matrix model: `space` multi-selects (`5506-5512`), `a` selects all (`5456-5470`), profiles are a
  read-only browse lens.
- `2400`/`2428` `_machines_modal`: "(A/D fan out to ✓)" and `3093` `target_state`: "what A/D toggles" — the actions are
  `track-all`/`track-one` = `T`/`t` (`5367`).
- `1410-1411` `_row_component`: "an action on a dep row (e.g. `m`/`P` on cuda-toolkit-12…)" — the keys are now the
  unified `method` action / `_pick_choices` (`6241`); there is no `P`.
- `2581-2586` `overlay()` and `3319-3325` (`toggle-install` note: "orphans coloured, ignored orphans revealed
  dimmed") — `_draw_profiles` never reads the orphan map (`3305` unused), never dims ignored orphans, and
  `docs/theming.md:89-92` still lists `orphan_excluded/forgotten/foreign` roles that `test/test_theme.py:47-53`
  asserts were removed. The `orphan-ignore` action (`5389-5402`) mutates a setting nothing on the page reflects.
- `2545` "grid dims … the key handler moves by column" — no grid; the handler moves by row.
- `docs/theming.md:6` and `:115` say the Theme screen is nav key `6`; `SCREENS` (`1196-1198`) puts Config at 6 and
  Theme at 7 (and the code comment at `3976` also says "key 6").

### [MED] test gaps — no renderer is ever executed headlessly; three screens are never rendered at all
No test calls any `_draw_*`; `test/test_tui_pin.py:12` already has a fake curses `_Scr` used only for `_popup_choose`.
The pty smoke test (`test/test_tui_smoke.py:12`, `:59`, `:105`) presses `j ! ? 4 5` and `2 M A`, `2 l j w` — screens
Components/Profiles/Glue/Dotfiles + the `!`/`?` overlays; keys `3`/`6`/`7` (Plugins/Config/Theme) never appear in any
test, so `_draw_plugins`, `_draw_config`, `_draw_theme`, the theme preview recursion, `_order_list`, `_input_box`
(with `complete`/`toggle`), and the whole Theme key ladder (`5960-6178`) have zero execution coverage. The `_sample_*`
tests (`test/test_theme.py:262-335`) assert row/state shape only. Pure helpers without tests: `_thumb`, `_scroll_reveal`,
`_wordwrap`, `_attr_pass`, `_plugin_tree_prefix`, `_plugin_cells`, `_plugin_remote_elem`, `_current_via`,
`_summary_note`, `_with_uninstall_node`, `_seed_uninstall`, `ProfileScreen.install_state` partial/`◐` logic (only via
`test_tui_pin` indirectly). **Recommend:** a parametrised "render every screen + every sample at 80x24 and 40x12 with
`_Scr`" crash gate (cheap, catches the `note` clobber class of bug), plus unit tests for `_thumb`/`_scroll_reveal`/
`_wordwrap`/`_attr_pass` (each is a 10-line pure function).

### [MED] ABI/interface — ad-hoc attributes bolted onto shared objects
`ctx._reboot_pending` is created by the TUI (`5103`, `6287`) and read by `_draw` (`1256`) — a private attribute of
another module's object used as a cross-module cache. `MenuState` acquires `mode`, `_overlay_caches`, `_req_sig`,
`_uninstall_q`, `descriptions` outside `__init__` (`1377-1379`, `1384`, `1390-1391`, `1837-1839`, `5096-5101`), and
`_reload` sets `_req_sig` twice (`1379`, `1391`). `ProfileScreen` grows `lhmax`, `rhmax`, `_ov_thread`, `_warm_gen`
lazily (`3410`, `3563`, `2627`, `3205`) and is read with `getattr(ps, 'lhmax', 0)` defensively (`5295`).
`resolve_effects` (`1862-1871`) communicates with the Palette/splash by mutating `os.environ`. **Recommend:** declare
all fields in constructors; move `_reboot_pending` to a `ctx.cache` namespace or a TUI-owned `SessionState`; pass
`effects` explicitly to `Palette`.

### [LOW] naming — 4-tuple inner rects and overloaded short names
`_panel` returns `(top, left, h, w)` unpacked as `dit, dil, dih, diw` (`3432`), `rit, ril, rih, riw` (`3537`), `lit, lil,
lih, liw` (`3318`), `m_it…` (`4408`), `r_it…` (`4434`), `tit…` (`4645`), `it, il, ih, iw` (`3859`, `4891`, `4961`). A
`Rect = namedtuple('Rect', 'top left h w')` with `.bottom/.right` would make `dit + dih - 4` (`3482`) read as
`box.bottom - 4`. `ms` means `MenuState` almost everywhere but `Node.status` uses `ms = self.members` (`79`) and both
`machs()` closures use `ms = ctx.config.machine_names()` (`2345`, `2410`). In `_draw_profiles`, `cur` is a NAME at
`3419` and an `is-cursor` bool at `3344`/`3599`; `note` is both the parameter and a local (the bug above). Four names
for one concept (horizontal offset): `rcol_left`, `lhoff`, `hscroll`, `dhscroll`. Underscore-prefixed locals to dodge
shadowing (`_d`, `_uq`, `_ceil`, `_ceil_r`, `_lho`, `_lmax`, `_cur_track`, `_parts` shadowing the method name at `3596`)
signal the function is too long rather than solve anything.

### [LOW] code reuse — smaller duplicate pairs
- `_start_probe.installed_any` (`2676-2697`) and `installed_scan.leaf_installed` (`3021-3042`): the same 20-line
  "any non-enumerable candidate binding has a version" routine.
- `_is_companion_comp` (`1739-1746`) and `ProfileScreen._is_companion` (`3162-3168`): identical.
- `_component_machines_modal.machs` (`2344-2347`), `_machines_modal.machs` (`2409-2412`), `machines_list` (`3072-3081`):
  the same "current first" ordering, three times.
- `_reload` (`1380-1389`) vs `_rebuild_menu` (`1840-1848`): the same carry-over block; `_reload` could call
  `_rebuild_menu`.
- The "reveal a just-expanded subtree" block: `1276-1286` and `3320-3330`.
- `_filter_edit`, `_find_edit`, `_find_edit_tree`, `_input_box`, and the inline text mode of `_machines_modal`
  (`2466-2489`): five backspace/printable/esc loops.
- `Node.status` is evaluated twice per row at `1328`; `_KIND_ELEM` (`1289`) and the `col` closure (`1295`) are
  rebuilt per frame/per row.

### [LOW] threading — benign races worth a comment or a lock
`_start_overlay_scan.run` (`2619-2626`) and `_warm_cache.run` (`3208-3215`) read `self.ctx.routes` on a daemon
thread while the main thread may `ctx.invalidate()` (every edit) — the property has no lock (`app.py:299-312`), so
both threads can build a Resolver concurrently (~150 ms each per the app.py comment); results are consistent but the
work is doubled. `_start_probe.run` (`2699-2707`) pops `_probe_queue` while `ensure_probes` extends it (`2659-2662`);
if the thread exits between the emptiness check and a new append, those names wait for the next draw's
`ensure_probes` to restart it — acceptable but undocumented. `_probe_dirty` is set from the thread and cleared by the
draw (`3587`) without synchronisation (fine under the GIL for a bool).

### [LOW] security — nothing alarming; two observations
No `eval`/`exec`/`subprocess` in this file; all shell work goes through drivers/`ctx.runner`. User-typed strings from
`_input_box` flow to `actions.plugin_add(src)` (`5758-5763`) and `actions.plugin_update(name, ref)` (`5821-5824`) —
quoting is `plugins.py`'s responsibility (not reviewed here); the TUI at least strips and gates on non-empty.
`_confirm_and_execute` (`639-668`) prints the full plan before `input('Proceed? [y/N]')` — the "no surprises" posture
is honoured. `_draw_where` (`1156-1166`) colours lines by substring heuristics (`'<- default here' in ln`), which is
brittle but not a security issue.

### [NIT] function-level imports inside hot paths
`from ..drivers.dotfiles import config_display_state` inside the row loop at `4997` (and again at `5007`, `5565`,
`5586`); `from .. import refreshstate` per frame at `1243`; `from .. import plugins` per frame in
`_draw_plugins_table` `4644` / `_draw_plugins_diff` `4683`; `from .. import actions` per frame at `3959`, `4475`.
Python caches modules so the cost is a dict lookup, but the pattern hides the module's real dependency graph;
hoist where no import cycle exists (`refreshstate`, `plugins`, `drivers.dotfiles` are safe — `app` and `actions` are
the genuine cycles).

### [NIT] miscellany
- `1379` and `1391`: `ms._req_sig` assigned twice in `_reload`.
- `_draw` takes `screen='components'` and `_draw_theme` hardcodes `'theme'` while ignoring its `screen` argument
  (`4396`, `4399`); `_draw` vs `_draw_components` naming is inconsistent with every other renderer.
- `_HELP['profiles']` glossary entry `('attr-filter (f)', …)` at `962` vs the legend `g('attr-filter')`; the help text
  hardcodes keys (`T / t`, `M`, `E`, `C`, `v`, `m`, `x`) that the keymap can rebind — `?` will then contradict the
  footer.
- `_setting_str` `3821` special-cases `'scope'` and `'driver-preference'` by key inside a "kind" formatter.
- `SPLASH_THRESHOLD` docstring at `1853` still says "liquid fill" (the liquid splash moved to a plugin).

---

## Top refactor recommendation

Build the **view-model seam** and let it pull the router in behind it — one PR per screen, Profiles first (it is the
hottest and the one already half-way there via `_SampleCfg`):

1. `@dataclass class ProfilesVM: left_rows: list[LeftRow]; right_rows: list[RightRow]; header: …; status: str;
   legend: list[tuple[str, str]]; scroll: ScrollState` where each row already carries its final strings, role names,
   and flags (`installed`, `is_new`, `picked_by_machine`, `twisty`). `ProfileScreen.build_vm(h, w)` computes it ONCE
   per state change (memoised on a `_view_gen`), doing all `ctx.config`/`ctx.routes` reads, `_parts` (memoised),
   `is_new` (as a precomputed set), `origin`, `install_state`, and the scroll clamps.
2. `_draw_profiles(stdscr, pal, vm)` becomes a pure emitter: loops over `vm.right_rows` calling `_hput`/`pal.style`
   — no `ctx`, no `ps` mutation. The sample becomes `ProfilesVM(...)` built from literals — no `_SampleCfg`, no
   `ProfileScreen` construction, no warm-cache thread, no probes.
3. Repeat for Components (the three cursor lines cached per node), Config (`has_primary` into `reload()`), Theme
   (`reload()` on a dirty flag), Plugins/Glue/Dotfiles (share one `TableVM` + `_draw_table`).
4. With every screen exposing `build_vm / draw / handle / reload`, replace the `if screen ==` ladders in `run()` with
   a `SCREENS_IMPL = {id: ScreenClass}` router and a `ListNav` helper — the F1 router the plan already specified.

This single direction resolves the HIGH perf findings (the recomputation moves into the memoised VM build), the
MVVM finding (draw is pure, samples are data), the draw-mutates-model finding (clamping lives in `build_vm`), most of
the duplication, and makes every screen renderable headlessly in tests via the existing `_Scr` fake.
