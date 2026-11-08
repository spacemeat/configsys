# Review: TUI screens (build_vm / draw / handle)

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/tui/screens/__init__.py`, `base.py`, `components.py`, `config.py`, `dotfiles.py`,
`glue.py`, `plugins.py`, `profiles.py`, `theme.py` (read line by line). Context: `configsys/tui/menu.py`
(the screen MODEL classes, router `run`, `_sample_*` states, paint primitives), `configsys/tui/surface.py`,
`docs/tui-architecture.md`, `docs/principles.md`, `config.hu` `keys:`, and the `actions.*` / `app.py` /
`plugins.py` / `primarygit.py` functions the handlers call. Tests read: `test/_render_harness.py`,
`test_render_headless.py`, `test_screen_{components,config,dotfiles,glue,plugins,profiles,theme}.py`,
the screen-touching parts of `test_fix_tui_c.py`, `test_primary_push.py`, `test_primary_state.py`,
`test_system_updates.py`. Targeted run: the 8 screen/render files — 99 passed.

All runs used throwaway homes under `$RUN/scratch/tui-screens/` (scripts in `scratch/tui-screens/scripts/`).
No non-pretend run invoked install/remove/upgrade/set-version/lock/unlock/fix-scope/refresh/execute; the
non-pretend runs only exercised config writers, `plugin bless/init/remove` on local bare repos, and
read-only probes. Frame timings use a no-op surface + palette (`scripts/nullsurf.py`), so they measure the
screen's own Python, not curses.

## Carried over from docs/review-2026-09/tui-menu.md (baseline 7a395c5^) and the 2026-09 README

Only the items whose code now lives in `tui/screens/` are settled here; the menu.py-only items (modal
frames/loops, `_fill_bg`, `run()` remainder, threading, the `_HELP` text, popups) belong to tui-core.

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] perf — left pane recomputes every member's install state per frame (`profile_untracked_count`) | open → tui-screens-12 | still "live, not cached", once per visible left row per frame: 3.7 ms of a ~7.5 ms Profiles frame (measured, 832-component catalog) |
| [HIGH] perf — right-pane row loop: 3 resolves + 2 layer merges per row | fixed | `d0cf422` memoized `_parts`/`_res`; measured `is_new`+`origin` for 44 rows = 0.155 ms |
| [HIGH] perf — `visible_pnodes()` rebuilt ~7×/frame | fixed | `d0cf422` (signature memo, `menu.py:3092`) |
| [HIGH] no view-model seam; draw reads the data source | fixed structurally; residual open → tui-screens-07 | Screen protocol + all 7 screens migrated: `0d092a6`, `82c7899`, `5a02b55`, `17149b8`, `5641778`. Profiles/Components VMs still carry only chrome |
| [HIGH] `run()` 1300-line router, per-screen ladders inline | fixed (screen half) | `5a02b55` moved each ladder into its screen's `handle`; `run()` remainder is tui-core's |
| [MED] `_draw_profiles` note clobbered by "(also in: …)" | fixed | `468a6d3` (B5); now `_layer_note`, `profiles.py:241` |
| [MED] Theme preview of Profiles spawns real background work | fixed | `5a02b55`: `_sample_profiles_state` stubs `ensure_probes`, aborts the warm sweep (`menu.py:3901-3909`) |
| [MED] Components cursor lines run the resolver 3× per keystroke | obsolete | measured `candidates`+`_why`+`_edges_text` = 0.04–0.43 ms/frame (ripgrep/neovim/docker/python3.12) — not worth a cache |
| [MED] Theme re-resolves per frame; Config re-parses config per frame | open (Theme half) → tui-screens-12 | Config: `plugins.declared` now 5 µs/call (fixed). Theme: `build_vm` still `ts.reload()`s every frame, 0.78 ms |
| [MED] draw mutates model state (scroll/clamps/`lhmax`/`rhmax`) | open → tui-screens-06 | every screen's `draw` still writes the model; Profiles' draw also starts probe threads |
| [MED] three copies of the hscroll table renderer | open → tui-screens-08 | now `plugins._draw_table`, `glue.draw`, `dotfiles.draw` + three copies of the width/xs geometry in `build_vm` |
| [MED] seven copies of page chrome + dead hardcoded legends | open → tui-screens-09 | 7 prologues/epilogues, 7 `_nav_str` with `_KEYMAP is None` fallbacks, 6 nav ladders |
| [MED] dead code — layer-grouped Profiles pane | open → tui-screens-10 | `toggle_grouping` still has no caller (grep: 1 hit, its def); the group branches live on in `profiles.py` |
| [MED] comment drift from retired models | open (partly) → tui-screens-19 | toggle-install note is now true (dimming implemented, `test_ignored_orphan_is_dimmed`); `profiles.py:493` "column-major grid" remains; new legacy-painter drift |
| [MED] test gaps — no renderer executed headlessly | fixed | `b13600f` harness + `test_screen_*.py`; new gap is handle coverage → tui-screens-11 |
| [MED] ABI — ad-hoc attributes on shared objects | open → tui-screens-23 | more since: `ctx._primary_state`, `_primary_push_mode`, `_sysupd_groups`, `_frame`, read via `getattr` |
| [LOW] naming — 4-tuple rects, overloaded short names | open → tui-screens-22 | `it, il, ih, iw` etc. in every screen; `_parts` has two meanings in `profiles.draw` |
| [LOW] reuse — "reveal a just-expanded subtree" block twice | open → tui-screens-09 | `components.py:185-195` ≡ `profiles.py:131-141` |
| [NIT] function-level imports in hot paths | open → tui-screens-26 | `components.draw` imports `refreshstate`/`sysupdates` per frame; `build_vm`s import `actions`/`plugins`/`primarygit` per frame |
| [NIT] `_draw` vs `_draw_*` naming; `_draw_theme` ignores `screen` | obsolete | the legacy painters were deleted in `5641778` |
| README D2 structural (OPEN_ITEMS) | fixed | commits above; `docs/done/d2-mvvm-plan.md` |

## Cross-cutting themes

- **Single-key destructive actions without a confirm.** Dotfiles' unmanage asks first; Plugins `x`
  (deletes a plugin's clone — including the primary's, the only copy of a `plugin init` user's dotfiles),
  Plugins `T` (trusts every changed plugin's code) and Theme `L` (replaces your whole theme) don't. The
  posture ("confirm hard-to-reverse actions", principles.md) is applied per screen, by hand.
- **Notes that report the intent, not the outcome.** Glue/Dotfiles/Plugins notes are built before or
  regardless of the driver's result and ignore `--pretend` ("activated 6 snippets" when nothing ran),
  while Config/Profiles/Theme route through `menu._pretend_note`. No shared "outcome → note" helper.
- **Error handling is per-branch.** Plugins/Glue/Dotfiles/Theme wrap their whole `handle`; Config most of
  it; Profiles only `ConfigsysError` in some branches; Components almost nothing; the router nothing.
  One unexpected exception (a humon parse error from a hand-edited config) ends the session.
- **Model-state lifetime is decided by object identity, and the identities lie.** Profiles keys its resolve
  cache on `id(ctx.routes)`, but every config write drops `ctx.routes`, so the "kept across edits" cache
  is dropped on every triage key (the ~1.5 s lag the 2026-08 fix removed is back); `_parts_cache` /
  `_hard_dep_cache` aren't keyed at all; `machine-target` rebuilds the model from scratch.
- **MVVM is a seam, not yet a contract.** Every draw writes scroll/clamp state back into the model, two
  build_vms mutate, Profiles' draw starts probe threads and runs ~100 ms resolves, and the
  Profiles/Components VMs carry only chrome. The tests lean on determinism, which holds — but "draw is a
  dumb painter" and "nothing in a draw path probes the system" (tui-architecture.md) are not true yet.
- **Presentation hand-built per screen.** Seven nav-string functions (each with a dead fallback), three
  table painters, six cursor-nav ladders (one shared off-by-one bug), and key glyphs hardcoded into
  notes/status lines so a rebind silently contradicts the screen.

## Findings

### tui-screens-01 [CRITICAL] safety — Plugins `x` deletes the primary plugin's clone (your dotfiles, user glue, unpushed commits) on one keypress
`configsys/tui/screens/plugins.py:318-321` (`PluginsScreen.handle`, `remove`) → `configsys/actions.py:1323-1346`
(`plugin_remove`): `x` on the cursor row calls `plugin_remove(ctx, row['name'])` with no confirmation;
it undeclares the plugin and `shutil.rmtree`s its synced dir — with no check that the row is the ★primary,
that the clone has unpushed commits or uncommitted edits, or that the clone is the ONLY copy. After the
documented onboarding `configsys plugin init` (`app.py:2775-2826`), the primary is created *inside*
`plugins/<name>`, declared with `source: <that same dir>`, and your dotfiles store and user glue are
**moved** into it (and `profiles:`/`components:` stripped from `configsys.hu`) — there is no remote until
you `set-source` + `push`. One `x` then destroys every captured config (every managed `~/.config/…`
symlink now dangles) plus its git history. For a remote-backed primary it still discards every
configsys-made commit not yet pushed (`primary-push: ask` is the default, so unpushed commits are the
normal state). Dotfiles' far milder `unmanage` confirms first; this does not.
**(reproduced)** `scripts/rm_init_primary.py` (sandbox home; `plugin init configsys-me` with one captured
`nvim.cfs/init.lua`, then `PluginsScreen.handle(<x>)` on the ★ row) →
`after init: store has [] | primary dotfiles: ['nvim.cfs']` · `x on -> removed …/plugins/configsys-me` ·
`primary dir exists: False | nvim init.lua anywhere? False`. And `scripts/rm_primary.py` (remote-backed
primary + `picks add jq`) → `unpushed: 1` … `clone exists: False` · `bare has jq commit? False`.
**Fix:** (TUI, this area) confirm every `remove` with a popup that names what is deleted ("undeclare X
and delete its synced copy at …"); for the primary, default to "unbless + keep the directory" and
refuse deletion while `primarygit.state` reports ahead/dirty or the source path *is* the plugins-dir copy
(no remote). (actions/plugins areas) make `plugin_remove` itself refuse an rmtree of a primary or a
local-only/ahead/dirty clone unless forced, so the CLI `plugin remove` is covered too.
**Effort:** S (TUI confirm) + M (action guard). **Tier:** A.
**Verified:** CONFIRMED (reproduced) — fresh sandboxes under `$RUN/scratch/verify-tui-screens/`, every command
through a guard runner (non-git commands refused, a fake `sudo` first on PATH; nothing was blocked, no sudo was
attempted). (a) `scripts/v01_init_linked.py`: `picks add btop` → `dotfiles capture btop --yes` → `plugin init
configsys-me` ("(profiles, components moved into the plugin and removed from configsys.hu.)"; the clone has no
remote) → `~/.config/btop` linked into `plugins/configsys-me/dotfiles/btop-dotfiles.cfs/btop` (the driver's
backup + `ln -sfn`, done by hand) and edited → `PluginsScreen.handle(ord('x'))` on the ★ row →
`note: removed …/plugins/configsys-me | confirm popups: []`, `primary dir exists: False`, `~/.config/btop …
resolves: False`, `copies of the v2 edit anywhere: []`, `.pre-configsys holds: color_theme = "v1"`,
`profile my-kit now: GONE | my-tool component: GONE`. (b) `scripts/v01_remote_primary.py` (local bare remote,
`plugin bless`, `picks add jq` → "1 change not pushed yet", `## main...origin/main [ahead 1]`,
`primarygit.state: ahead 1`) → one `x` → `clone exists: False`, `remote log: ['20c1553 seed']`, `picks now: {}`.
No guard anywhere: no confirm in `screens/plugins.py:318-321` or the router (`menu.py:4985-4993`),
`plugin_remove`'s only check is plugins-dir containment, and no test removes a primary (`test_plugins.py:518`
removes a non-primary addon). One correction: capture is read-only on the system side, so an UNLINKED captured
config keeps its on-system original (`scripts/v01_init_primary.py`, never linked: after `x`, `btop.conf copies now:
[…/home/.config/btop/btop.conf]`). What is lost is
everything that only the store holds: edits made through the links since linking, the moved `profiles:` /
`components:` / user glue, the primary's history and its unpushed commits. Same root cause as actions-01, which
was confirmed there too. CRITICAL kept: one key in normal use loses data with no undo, and `x` only stages on
Components.

### tui-screens-02 [HIGH] performance — every Profiles triage key drops the "kept across edits" resolve cache: ~1–3 s per keystroke
`configsys/tui/screens/profiles.py:563,585,605,608,652,760` (the writers `stage_uninstall`,
`set_disposition`, `set_included`, `mark_all_seen`) → `actions.py:401,428,463,524` each call
`ctx.invalidate()` → `app.py:375-376` drops `_config` **and `_routes`** → `menu.py:3603-3636`
(`ProfileScreen._resolve`) sees a new `id(ctx.routes)` and clears all of `_res`. The design (commit
`8d721f9`, "toggles ~1.5s → ~27ms"; `aef1da9`; `docs/done/d2-mvvm-findings.md`) rests on "a
membership/profile edit does NOT invalidate, so its id is unchanged and the cache survives" — false since
`set_included` gained `ctx.invalidate()` (`468a6d3`, same day as `aef1da9`). Worse, `ps.reload()`'s
`_warm_cache` (`menu.py:3548-3552`) runs *before* the lazy clear, sees a full `_res`, and does not
re-warm — so after the first edit the catalog stays cold and every newly scrolled row resolves on demand.
Each keystroke also rebuilds the Resolver (~0.5 s; `routecheck.check_component` dominates). The Profiles
triage loop (`s`/`i`/`t`/`x`/Enter, pressed hundreds of times when adopting a box) is the screen's core use.
**(reproduced)** `scripts/triage_lag.py` (sandbox home, 150 picks, warm cache, then one key each) →
`disp-seen handle 785 ms + next frame 617 ms (_res 34 of 832)` · `disp-interesting handle 1745 ms + next
frame 1097 ms` · `stage-uninstall handle 1367 ms + next frame 778 ms` · `track-one handle 581 ms + next
frame 512 ms (_res 34 of 832)`; with `ctx.invalidate` replaced by a config-only drop
(`scripts/track_lag.py`): `handle(t) 15.6 ms … _res size now 832`.
**Fix:** give `Context` an `invalidate_config()` that drops `_config` but keeps `_routes`, and use it from
the writers whose sections the Resolver never reads (`picks`, `dispositions`, `uninstall`,
`orphans-ignore`); keep the full `invalidate()` for pins/driver/route/plugin edits. Independently, key
`_res` on a routes *generation* the Resolver bumps only when routing inputs change, and make `_warm_cache`
check the same key (re-warm after a swap). Add a test that a disposition edit keeps `_res` warm.
**Effort:** M. **Tier:** C.
**Verified:** CONFIRMED (reproduced) — `scripts/v02_triage.py` (sandbox `home-perf`, 150 picks, `--os pop`, guard
runner). From a fully warm cache, every triage key rebuilds `ctx.routes` and empties `_res`. With the install
overlay off: `disp-seen handle 430 ms + next frame 62 ms | routes rebuilt: True | warm thread restarted: False |
_res 832 -> 34/832`; `disp-interesting` 423 + 61 ms; `stage-uninstall` 427 + 63 ms; `track-one` 683 + 78 ms;
`3 s after the last key: _res 34/832 (no re-warm)`. A six-row `s`/`j` triage run took 505–1239 ms per `s`. With
the default overlay on (probe threads running, host load 7.5): `disp-interesting handle 1549 ms + next frame
341 ms`, and the run averaged 2.7 s per `s` (0.75–4.5 s). With a config-only invalidate: `handle 14–17 ms + next
frame 36 ms … _res 832/832`. `ctx.invalidate(); ctx.routes` alone takes 427–491 ms on an idle host; under cProfile
`routecheck.check_component` is 1.10 of 1.39 s. Most of the cost is now the per-key Resolver rebuild. A resolve
costs about 1 ms here, so dropping `_res` adds only about 50–80 ms to the next frame, but it leaves the catalog cold.
A correction to the history: `set_included` and `set_disposition` already called `ctx.invalidate()` at `aef1da9`
(`git show aef1da9:configsys/actions.py`), so keying on `id(ctx.routes)` was wrong from the commit that introduced
it. `468a6d3` only inserted `invalidate_location_cache` before the existing call. The current `invalidate` lines
are `actions.py:390,422,463,523`. HIGH kept. Keying on `id()` has a second weakness: CPython may reuse a freed
Resolver's address, and a generation counter would fix both.

### tui-screens-03 [MED] correctness — an exception in a screen's `handle` ends the TUI (traceback, staged work lost)
`configsys/tui/menu.py:4985-4995` calls `scr.handle(...)` with no guard; `app.py:4927-4935` (`main`)
catches only `ConfigsysError` and `KeyboardInterrupt`. Plugins/Glue/Dotfiles/Theme wrap their whole
handle in `except Exception`; Config wraps the edit branch; Profiles catches only `ConfigsysError` in
track/disp/stage/orphan and nothing in `claim`, `mark-all-seen`, `method`, `comp-machines`,
`machine-target`, `where`, `filter`/`find` (`profiles.py:631-742`); Components guards only its
`_reload` calls (`where` at `components.py:309-314`, `_pick_choices` at 361, `stage*`, `_switch_mode`
partially). A realistic trigger: editing `configsys.hu` in another terminal while the TUI is open — a
half-typed quote makes `plugins.read_picks` raise `humon.DeserializeError` (not a `ConfigsysError`) on the
next `t`. The curses screen is restored, but every staged op and selection is gone.
**(reproduced)** `scripts/typo_crash.py` (sandbox home; append `{ splash: "oops` to the config, press `t`
on Profiles) → `ESCAPED handle -> humon.DeserializeError Trove has syntax errors:`; `scripts/handle_raise.py`
→ `profiles t: ESCAPED handle -> PermissionError …` · `components w: ESCAPED handle -> KeyError 'ripgrep'`.
**Fix:** one guard in the router around `build_vm`/`draw`/`handle` (`except Exception as e: note =
f'error: {e}'`, plus `reporter` debug output), and delete the per-screen copies (or keep them only where a
branch needs a specific message). **Effort:** S. **Tier:** B.

### tui-screens-04 [MED] correctness — Profiles `M` (machine targets) rebuilds the model: the cursor silently moves to a different component
`configsys/tui/screens/profiles.py:719-729` (`machine-target`): after `_machines_modal` closes — even with
no change — the handler constructs a fresh `ProfileScreen(ctx)` and copies back only `lcur, ltop, rcur,
rtop, focus, pfilter, cfilter, selected_comps`. Dropped: `expanded` (the include tree collapses, so
`lcur` now indexes a different profile), `attr_inc`/`attr_exc` (the catalog changes, so `rcur` indexes a
different component), `show_install`, `expanded_parts`, `lhoff`, `rcol_left`, plus the `_res` cache and
`_scan_caches` (a full re-warm and orphan re-scan start while the old model's threads keep running). The
very next `t`/Enter tracks a component the user never chose. `ps.reload()` already re-reads profiles,
catalog and clamps; `machines_list()` reads the machine registry live.
**(reproduced)** `scripts/mtarget.py` → `before (left node, right row, attr_inc, show_install, #expanded):
('cloud-tools', 'grpcurl', ['cli'], 0, 1)` · `after …: ('benchmark-tools', 'glmark2', [], 1, 0)`.
**Fix:** replace the rebuild with `ps.target_machines = cur; ps.reload()`; set `dirty` only if the modal
reported a change (see tui-screens-25). Test: expanded tree + attr filter survive `M`. **Effort:** S.
**Tier:** B.

### tui-screens-05 [MED] correctness — Glue/Dotfiles/Plugins notes claim success they don't check (and under `--pretend`)
`configsys/tui/screens/glue.py:202-227` (`deactivate`, `activate-group`), `dotfiles.py:188-221`
(`manage-all`, `unmanage`, `unmanage-all`), `dotfiles.py:236-254` (`move-store-all`),
`plugins.py:332-337` (`sync-all`): the driver/action result is discarded and the note is the intent
("deactivated X", "(re)activated 6 snippet(s) … (6 newly active)", "managing N config(s)", "unmanaged
X", "synced all"). Single `activate`/`manage` do read `res.ok`; the bulk forms don't. Under `--pretend`
nothing is written (good — verified below) but the notes still say it happened, unlike
Config/Profiles/Theme which use `menu._pretend_note`. "No surprises": a partial failure or a dry run
reads as done; the next reload quietly shows the old state.
**(reproduced)** `scripts/tui_pretend_sweep.py` (every mutating key of every screen under `--pretend`
against a populated sandbox with a blessed primary) → every row `ok` (no file changed) but:
`glue activate … note: 'activated btop-glue (bash)'` · `glue deactivate … 'deactivated btop-glue (bash)'` ·
`glue activate-group … '(re)activated 6 snippet(s) in the bash group (6 newly active)'` ·
`dotfiles manage … 'managing btop-dotfiles'` · `dotfiles unmanage … 'unmanaged btop-dotfiles'` ·
`plugins sync-all … 'synced all'`. The failure half is verified by reading (results unassigned).
**Fix:** collect per-unit results (`Result.ok`, `relocate`'s bool) and build the note from them
("activated 5 of 6 — fd-glue failed: …"); route every screen's note through `_pretend_note` (make it
the router's job for any Intent whose screen attempted a write). **Effort:** S. **Tier:** B.

### tui-screens-06 [MED] data-driven — draw writes the model on every screen; Profiles' draw starts probe threads and runs resolves
Draw-time model writes: `components.py:185-196` (`ms.reveal`, `ms.top`); `config.py:161-165` (`cs.top`);
`dotfiles.py:120,126`; `glue.py:129,134`; `plugins.py:200,205,226-227`; `theme.py:127,130,146,150`
(`map_ncols`, `map_rows_per_col` — read back by `handle` at `theme.py:214-217`); `profiles.py:131-142,
215-216, 329-330, 347-349, 373` (`ltop`, `reveal`, `lhmax`, `lhoff`, **`rcur`**, `rtop`, `rcol_left`,
`rhmax` — read back by `handle` at 525/532 — `_probe_dirty`). `build_vm` mutates on Plugins
(`plugins.py:164` clamps `pl.dfile`) and Theme (`theme.py:83` reloads the model). Side effects in draw:
`profiles.py:444-445` `ps.ensure_probes()` spawns the per-component `get_version` probe thread;
`profiles.py:253-257` `ps.available_oses()` runs `reportgen.coverage` (7 resolves) synchronously on first
view of an unavailable component; `components.py:129-141` reads `refreshstate.age_days` (a file read +
`time.time()`) every frame. `docs/tui-architecture.md` states "Nothing in a draw path reads the clock or
probes the system", so the code breaks its spec. Practical cost today is small (determinism tests pass),
but it is why `handle` depends on the previous frame's geometry and why samples need stubs.
**(reproduced, cost)** `scripts/avail_os.py` → `available_oses first call ms: [113.0, 94.1, 81.8, 92.2,
95.0, 12.8, …]` (pop has 45 unavailable components — ~100 ms per `j` across a run of them).
**Fix:** a `layout(size)` step (or `build_vm`) that owns scroll clamping and returns offsets in the VM;
the router stores them back after draw; move `ensure_probes` + `available_oses` into `build_vm` (or the
warm thread), and compute the refresh age into the VM (or cache it on `ctx` like `_reboot_pending`).
A test asserting `draw` leaves `vars(model)` unchanged would pin it. **Effort:** M. **Tier:** D.

### tui-screens-07 [MED] refactor — Profiles and Components still paint from the live model/ctx; no VM is memoized
`profiles.py:100-462` reads, per frame: `ctx.config.dispositions/picks/uninstall_queue/included/
orphans_ignore/profile_excludes/profile_layer_defs/profiles_containing/is_new`,
`ctx.routes.components/dependents`, `ps._parts/_resolve/install_state/origin/available*`, and lays the
catalog table out as ad-hoc locals (`x_name`, `x_via`, `x_org`, `st_x`, `m_base`). `components.py:110-276`
reads `ms` + `ctx.routes` (`_identity_line`, `_methods_line`, `_infoblock` → `drv.location`),
`refreshstate`, `sysupdates`. `ProfilesVM`/`ComponentsVM` hold only titles/status/legends (their own
docstrings call the deep extraction "a later pass"). None of the seven VMs is memoized on any generation
— each is rebuilt per frame, including 120 ms poll ticks. Consequences: the Theme sample still needs a
`_SampleCfg`/`_SampleCtx` proxy (`menu.py:3871-3891`) and a frozen `_resolve`; the render tests can only
assert routes-independent chrome for Profiles (`test_screen_profiles.py` docstring).
**Fix:** finish the D2 plan for these two: a `ProfilesVM` with `left_rows`/`catalog_rows` (final text +
roles + flags) and a column spec list; a `ComponentsVM` with `rows`/`header_chips`/`cursor_lines`;
memoize on `(id(ctx.config), id(ctx.routes), model.view_gen, size)`. Samples then become literal VMs.
**Effort:** L. **Tier:** D.

### tui-screens-08 [MED] reuse — three hand-copied table screens (geometry + painter)
`plugins.py:128-135` / `glue.py:81-88` / `dotfiles.py:78-85` compute `widths`/`xs`/`virt_w` identically
(gutter 1 vs 2); `plugins.py:193-214` / `glue.py:126-152` / `dotfiles.py:117-144` repeat the clamp
`hscroll`, sticky header via `_put_hscroll`, `_scroll_top` over a display list, selection fill, per-cell
`_put_hscroll`, `_scrollbar_v`/`_scrollbar_h`. Glue and Dotfiles even share the `('hdr', …)/('row', i)`
display format and `_DF_STATE_ELEM`.
**Fix:** `TableVM(headers, cells, elems, display, gutter)` + `menu._draw_table(surface, pal, rect, vm,
cur, scroll) -> scroll`; the three screens shrink to their build_vm content and handle. ~120 lines.
**Effort:** M. **Tier:** D.

### tui-screens-09 [MED] reuse — page chrome, legends and cursor nav hand-built seven times
Every `draw` opens with `erase/getmaxyx/use_page/_fill_bg/_draw_nav` and closes with status+note and
nav footer(s); every module has a `_nav_str` (`components.py:259-272`, `config.py:47-53`,
`dotfiles.py:48-54`, `glue.py:51-57`, `plugins.py:52-62`, `profiles.py:50-63`, `theme.py:46-62`) whose
`_KEYMAP is None` fallback is unreachable in production (`run` sets `_KEYMAP` before the first draw) and
already disagrees with the real legend (Dotfiles' fallback lists `h/l scroll`, the real one doesn't;
Theme's lists `x/r remove`). Six `handle`s re-implement down/up/page/top/bottom (`config.py:219-230`,
`dotfiles.py:163-178`, `glue.py:171-186`, `plugins.py:268-307`, `profiles.py:490-509`,
`theme.py:222-248`) — the duplication carries a shared bug (tui-screens-13). The "reveal a just-expanded
subtree" block is duplicated at `components.py:185-195` and `profiles.py:131-141`.
**Fix:** `Screen.begin_page()`/`end_page(status, nav_rows)` helpers; a `LEGEND = {scope: [(action,
label), …]}` table rendered by one function (no fallbacks — build a default `Keymap` in tests instead);
a `ListNav(cur_attr, len_fn)` that clamps to `[0, n-1]`; one `_reveal_subtree(rows, key, top, h)`.
**Effort:** M. **Tier:** D.

### tui-screens-10 [MED] dead-code — the layer-grouped Profiles pane and discarded per-frame expansions
`profiles.py:145-150` (`group_counts`), 153 (`node_group`), 164-173 (the `kind == 'group'` row), 180-181,
191 (`group_ceiling` → always `None`), 230-232 (`_grp`/`cur_readonly` → always `''`), 514-515
(`is_group_header` in `confirm`): `ps.grouped` is never True — `toggle_grouping` (`menu.py:3175`) has no
caller, no `profiles` action maps to it (`keyspec.py` `KNOWN_ACTIONS`), and no plugin/example/test calls
it. `profiles.py:115-120` call `ps.members()`, `ps.own_members()`, `ps.removed_members()` every frame and
discard the results ("kept as calls so the model's per-frame caches warm identically" — a leftover of the
deleted render-equivalence oracle; `Config.profile_components` has no cache to warm). `own_members` /
`removed_members` have no other caller anywhere.
**(measured)** the three discarded calls cost 0.59 ms/frame on `!all` (`scripts/prof_frame.py`).
Grepped: `toggle_grouping|own_members|removed_members|\.grouped` over `configsys/ test/ examples/
~/src/configsys-*/` → only their definitions and these call sites.
**Fix:** delete the group branches here and (tui-core) the model's grouping/ceiling plumbing
(`_GKEY`, `_GROUP_*`, `group_new_count`, `collapsed_groups`, `cur_readonly`, …), or bind it — user's
call (Questions). Delete the three discarded calls and the two dead methods. **Effort:** S. **Tier:** D.

### tui-screens-11 [MED] test-gap — the mutating key paths are untested on every screen; no TUI `--pretend` sweep
The `test_screen_*.py` handle tests cover navigation (and Profiles `select`, Dotfiles/Glue one branch
each). Untested: Profiles `track-all`, `disp-*`, `stage-uninstall`, `claim`, `mark-all-seen`,
`orphan-ignore`, `comp-machines`, `machine-target`, `attr-filter`, `toggle-install`, `method`; Plugins
`remove`, `sync*`, `bless`, `update*`, `trust*`, `lock`, `set-ref`, `history`; Dotfiles `manage*`,
`unmanage*`, `move-store`; Glue `deactivate`; Theme `new`/`reset`/`edit-bg`/effects/`copy-page`/`save`/
`load`; Config `move`/scope/splash/effects/choices/scalar/driver-preference/dir/list; Components `mode`,
`method`, `op-*-all` notes. Each of tui-screens-01/02/04/05/13 would have been caught by one test.
`test_pretend_sweep.py` covers CLI verbs only, though CLAUDE.md's rule ("any new write path must honor
`ctx.runner.pretend`") applies to TUI writers too. No test asserts draw/build_vm purity.
**(reproduced, feasibility)** `scripts/tui_pretend_sweep.py` already drives 60 mutating keys with
`_popup_choose`/`_input_box`/`suspended` monkeypatched and asserts nothing changed on disk — today every
row passes.
**Fix:** add `test/test_tui_pretend_sweep.py` from that script (fail on any file change; check each note
says pretend/would); per-branch handle tests with fake popups; a purity test (`vars(model)` unchanged
across `build_vm`+`draw` once scroll is a VM output). **Effort:** M. **Tier:** B.

### tui-screens-12 [LOW] performance — the Profiles ⊙N badge and the Theme reload are the remaining per-frame costs
`profiles.py:194` calls `ps.profile_untracked_count` (`menu.py:3239-3247`, "Live … not cached") per
visible left row per frame: a full `profile_components` expansion + `install_state` per member, while
the sibling ⁺N/☆N counts are memoized. `theme.py:83` reloads the theme (merge + `resolve_theme`) every
frame; the Theme sample of Profiles costs 6 ms/frame.
**(reproduced)** `scripts/untracked.py` → `untracked badges per frame (44 rows) 3.71 ms` vs `new/int badges
per frame (memoized) 0.294 ms`; `scripts/frame_cost.py` → `profiles (right, !all): 7.95 ms/frame`,
`ThemeScreen.reload per call 0.779 ms`, `theme (sample=profiles): 5.97 ms/frame`.
**Fix:** memoize the untracked count in `_profile_counts`' cache keyed by the overlay/probe generation +
`id(ctx.config)`; reload the Theme model only when `id(ctx.config)` changes (a `_theme_sig`).
**Effort:** S. **Tier:** C.

### tui-screens-13 [LOW] correctness — `j` on an empty list sets the cursor to −1, and reloads keep it there
`plugins.py:272`, `glue.py:172,176`, `dotfiles.py:164,168`, `config.py:220,224` compute
`min(len(rows) - 1, cur + 1)` = −1 on an empty list; the models' reload clamp `min(cur, max(0, n - 1))`
(`menu.py:4339`, 4576, 4628, 3816) keeps −1, so after rows appear `cur_row()` is `None` and every row
action silently does nothing until the user presses `k`/`g`. The common path: a fresh user opens Plugins
(empty), presses `j`, then `a` adds a plugin — `s`/`t`/`b`/`x` are now no-ops with no row highlighted.
**(reproduced)** `scripts/neg_cursor.py` → `after j on an empty Plugins page: cur = -1` ·
`after a plugin appears (reload clamp): cur = -1 -> cur_row(): None` · `glue empty + j -> cur -1`.
**Fix:** clamp with `max(0, …)` in the handlers and reloads — via the `ListNav` of tui-screens-09.
**Effort:** S. **Tier:** B.

### tui-screens-14 [LOW] correctness — Profiles' parts / hard-dep caches survive a routes rebuild
`menu.py:3269-3302` (`_parts`), `3304-3321` (`_hard_deps`, docstring "Cached per reload"), `3528-3546`
(`reload` clears neither): only `_res` checks `id(ctx.routes)`. After a plugin sync/update, a
Components-side pin (`v`), or a Config `disabled-drivers`/`driver-preference` edit, the Profiles screen keeps
the old parts list (▸ twisty, parts rows, ◐ partial) and the old requires closure (◐ "required component
missing") for the session. Profiles' own `v` pops one entry (`profiles.py:708-709`); nothing else does.
(Model code is tui-core's; the wrong glyphs are this screen's.)
**(reproduced)** `scripts/stale_parts.py` (swap routes, change `cuda.parts` and `ant.requires`, `reload()`)
→ `routes swapped: True` · `cuda: _parts after swap+reload = ['cuda-toolkit-12']… (new routes: … ['__changed__'])`
· `ant: _hard_deps after swap+reload = ['jdk'] (new routes: requires [])`.
**Fix:** key `_parts_cache`, `_hard_dep_cache`, `_avail_os_cache` on the same routes generation as
`_res` (one `_routes_caches()` helper). **Effort:** S. **Tier:** B.

### tui-screens-15 [LOW] correctness — Config flags most settings "relocated" while the primary is declared but not synced
`config.py:104` derives `has_primary` from the declaration (`plugins.primary_name(plugins.declared(…))`),
but edit routing (`actions.edit_target` / `_nature_target`) needs a blessed **and synced** primary. Between
`bless` and a successful sync (a new machine, an offline clone, a failed sync), every untouched uniform
setting is painted in the "relocated" `header` role although its edit lands exactly where its nature says.
**(reproduced)** `scripts/config_unsynced.py` (declare `{ source: "github:nobody/configsys-me" primary:
true }`, unsynced) → `has_primary: True | edit target: top config` · `highlighted as relocated: 14 of 23
[('driver-preference', '(machine-local)'), ('auto-tighten', '(machine-local)'), …]`.
**Fix:** compute `has_primary` with the edit-routing predicate (`actions.edit_target(ctx)[1] != 'top
config'`, or `_primary_data_file(ctx)[0] is not None`) and show "(primary not synced)" in the status.
**Effort:** S. **Tier:** B.

### tui-screens-16 [LOW] correctness — Config never paints the cursor's setting when its block is taller than the panel
`config.py:161-176` (`draw`): the keep-in-view loop stops at `top == cur`, and the paint loop `break`s
when a block doesn't fit — so a cursor block taller than the panel draws nothing. On a 12-row terminal the
cursor on `disabled-drivers` or `primary-push` shows an empty list; Enter edits a setting you can't see.
**(reproduced)** `scripts/config_small.py` → `23 settings; cursor setting NOT painted at: [(12, 60,
'disabled-drivers', 5), (12, 60, 'primary-push', 6)]`.
**Fix:** always paint the cursor block's header row, truncating its description to the rows left (an
ellipsis line). **Effort:** S. **Tier:** B.

### tui-screens-17 [LOW] safety — Theme `L` replaces your theme overrides with no confirm; the export name isn't validated
`theme.py:408-417` (`load`): picking a pack (the popup defaults to the first, so `L` Enter) calls
`actions.load_theme`, which **replaces** the whole `theme:` section in the edit target; the note says only
"loaded X". In the machine-local top config there is no history, so a hand-tuned look (including custom
color names) is gone. `theme.py:393-407` (`save` → export): the typed name goes straight to
`plugins_dir / name` (`actions.py:1039-1056`): an existing plugin's name — the primary's included — gets
its `plugin.hu` manifest rewritten as a theme-only plugin after one "overwrite?" confirm (its `data:` and
`plugins:` stop loading); `..` or `/` leave the plugins dir. User-typed, so not a trust boundary.
**(reproduced, load)** `scripts/theme_load.py` → `before L: {'accent': '#ff00aa', 'dim': '#335577', 'ok':
'#11dd44'}` · `note: loaded stock-pack` · `after L : {'header': '#78c8ff', …}` (custom `ok` gone).
**Fix:** confirm load ("replace your N color / M role overrides with X?", offer "export current look
first"); validate the export name (`plugins.dir_name`-safe, no existing primary/code plugin; refuse
`/`/`..`). **Effort:** S. **Tier:** A.

### tui-screens-18 [LOW] security — Plugins `T` trusts every untrusted/changed plugin's code on one keystroke, without listing them
`plugins.py:369-372` → `actions.plugin_trust_all`: no confirmation and no list of what is approved; the
note shows only the summary line. `T` sits next to `t` (trust the cursor plugin). Trust is the gate that
lets a plugin's code, recipes and glue run (with your privileges, and under sudo during installs); after
`u`/`U` pulls new versions, every one of them is "changed", and `T` re-approves all of them unseen. An
attacker who pushed to a plugin repo can't run anything until trust; this lowers the consent to one
misplaced shift. The CLI `plugin trust` with no name behaves the same (parity area).
Verified by reading `actions.py:1501-1530`.
**Fix:** a confirm popup listing each plugin with `untrusted`/`changed` and its content hash ("review its
diff: Tab"), defaulting to Cancel. **Effort:** S. **Tier:** A.

### tui-screens-19 [LOW] comment-drift — the screens still describe the deleted legacy painters; other stale notes
Every module docstring says the draw "reproduces menu._draw_X cell for cell, which test_screen_X pins
against the legacy painter" (`components.py:10`, `config.py:12-13`, `dotfiles.py:11-12`, `glue.py:12`,
`plugins.py:11-12`, `profiles.py:13-15`, `theme.py:15-17`) and handles say "Ported verbatim" — the painters
and oracle were deleted in `5641778`; tests now use hand-built data. `theme.py:17,170` say the self-preview
"keeps using the legacy painter" — it renders `ThemeScreen` with `suppress_sample` (`menu.py:4262-4268`).
`profiles.py:102,116`, `theme.py:83`, `dotfiles.py:241` cite legacy behaviour. `base.py:35-37`: VMs are
"INSPECTABLE and comparable" — they are plain classes with no `__eq__`/`__repr__`.
`profiles.py:493` "column-major grid: down = next item, wraps col" (no grid). Context-file drift describing
these screens: `menu.py:1294-1296` (`_HELP['theme']`: "Left: map, then roles. Right: sample" — the draw
puts map top-left, roles top-right, sample full-width below), `menu.py:4078-4081` ("a-e cycles the
page" — it's F1-F7), `menu.py:3822` ("key 6" — Theme is 7), `menu.py:2869-2870` ("space toggles
membership, `a` toggles a profile active").
**(reproduced, VM claim)** `ConfigVM() == ConfigVM(): False | repr: <…ConfigVM object at 0x…>`.
**Fix:** one docstring sweep; make the VMs `@dataclass` (then they ARE comparable/inspectable, and
memoization can compare inputs). **Effort:** S. **Tier:** E.

### tui-screens-20 [LOW] correctness — Dotfiles tells you to press `c` to capture; no key does that
`dotfiles.py:98`: the at-risk clause reads "! N unmanaged file(s) at risk — capture (c) before linking".
The Dotfiles scope has no `capture` action (`keyspec.py:246`; `config.hu` dotfiles block) — since
`bdc9ef9` capture and link are one step under `manage` (`m`/Enter), as the `?` page says. `c` falls through
to `handle` and does nothing. (The CLI's `app.py:4435` has the same stale text — app-cli area.)
Verified by reading.
**Fix:** "… — manage (m) adopts it", with the glyph from the keymap. **Effort:** S. **Tier:** B.

### tui-screens-21 [LOW] data-driven — key glyphs hardcoded in notes, badges and titles
`components.py:174` ("press ! to view"), 291 ("press X to apply"), 295 ("i/u stages them all, then X
applies"); `glue.py:103` ("A to re-activate"); `plugins.py:124` ("a to add"), 161/169 ("Tab"), 329
("L unlocks"); `theme.py:52,54,148` ("F1-7"), 417 ("s to save one"); `config.py:324` ("space grab, j/k
move"). `docs/tui-architecture.md` promises "Legends and help read the same Keymap, so hints can't drift
from bindings"; a `keys:` rebind (rebind-wins) makes these lie.
**Fix:** a `menu._k(scope, action)` helper (`Keymap.glyph`) used in every user-facing string; a test that
rebinds `execute` and greps the SU note. **Effort:** S. **Tier:** D.

### tui-screens-22 [LOW] naming — retired term in a user string; positional tuples everywhere
`dotfiles.py:74` "(no dotfiles in the active profiles)" — `active profiles` is `retired:` in
`docs/glossary.hu` ("profiles are browse-only; picks are the install set"); `test_screen_dotfiles.py:75,115`
pin the string. Rows are positional tuples read by index in handlers and painters — dotfiles `row[0..5]`,
glue `row[0..6]` (`_is_user_glue` keys on `len(row) > 6`), profile nodes `nd[2]`/`nd[3]`/`nd[4]`,
panel rects `it, il, ih, iw` / `dit, dil, dih, diw`. In `profiles.draw`, `_parts` means an ancestor path at
179 and a parts list at 382; `ProfilesScreen.draw(self, stdscr, …)` breaks the protocol's `surface` name.
**Fix:** "(nothing in this machine's picks ships a dotfiles config)"; `NamedTuple`s (`DotfileRow`,
`GlueRow`, `PNode`, `Rect`). **Effort:** S (string) / M (tuples). **Tier:** D.

### tui-screens-23 [LOW] abi — the Screen protocol isn't uniform; screens talk through ad-hoc ctx attributes
`base.py:20-21,71-72`: `ComponentsScreen.handle` takes `cfg, ledger` extra, so the router special-cases
it (`menu.py:4989-4993`), plus `scr.note/scr.diags` instead of `vm.note` and `scr.sample_ms` for Theme.
`reload()` and `model.dirty` exist on six screens but not in the protocol, so the router hard-codes which
to reload on entry. `Intent.quit` (`base.py:48`) is never set or read (grep over configsys/, test/,
plugins). Cross-screen state rides private ctx attributes read with `getattr` defaults:
`ctx._primary_state`, `_primary_push_mode`, `_reboot_pending`, `_frame`, `_sysupd_groups/_dirty/_notes`
(`components.py:104-105,142,156-158`), and model attributes created outside `__init__` (`ms.mode`,
`ms.descriptions`, `pl.primary_state`, `ps.lhmax/rhmax`).
**Fix:** a `Session` object (cfg, ledger, note, diags, sample_ms, primary/reboot/sysupd state, frame)
passed to every `build_vm`/`handle`; add `on_enter()`/`dirty` to `Screen`; drop `Intent.quit`.
No plugin imports `configsys.tui.screens` (grep), so this is free to change now. **Effort:** M.
**Tier:** F.

### tui-screens-24 [LOW] parity — the Plugins screen can't add a machine-local plugin, pin, or retarget
`plugins.py:308-317`: `a` calls `plugin_add(ctx, src, replace=…)` — never `local=True` (the documented
replacement for project discovery: `plugin add <dir> --local`), `ref=`, or `pin=`. There is no TUI
counterpart to `plugin set-source` (needed to publish a `plugin init` primary) or `plugin init`. (The
parity reviewer owns the full table.) Verified by reading `actions.py:1221`.
**Fix:** two more toggles in the add box (local / pin) and a ref field; a `set-source` action on the ★ row.
**Effort:** S. **Tier:** G.

### tui-screens-25 [LOW] performance — closing the machines modals marks Components dirty even when nothing changed
`profiles.py:717` (`comp-machines`) and 728 (`machine-target`) set `dirty = True` unconditionally, so the
next visit to Components runs `_reload` (the load pipeline + diagnostics — "~6s on a full machine" per the
router's own comment, `menu.py:4865-4867`). Real picks/machine changes are already caught by the router's
`req_changed` check. Verified by reading (not timed: a non-pretend `_reload` runs real probes).
**Fix:** have the modals return whether they wrote; set `dirty` from that. **Effort:** S. **Tier:** C.

### tui-screens-26 [NIT] correctness — small nav and clarity nits
`theme.py:212-219`: `right` from the right-hand roles pane jumps to the left-hand map (and `left` from the
map's first column jumps the cursor to row 0). `profiles.py:599-614`: with no target machines, `T`/`t`
say "no change" instead of "no target machines — M to pick". `components.py:446`:
`self.diags = ms.states and self.diags` (sets `{}` when states is empty — obscure). Per-frame function
imports (`components.py:103,129,152`; `config.py:98-99`; `theme.py:81`; `plugins.py:118,148`) hide real
dependencies (`refreshstate`, `sysupdates`, `plugins` are safe to hoist). `_build_diff_vm`'s
`getattr(pl, 'diff_span', None)` for a declared attribute.
**(reproduced, theme)** `scripts/neg_cursor.py` → `theme: right from roles pane -> focus map`.
**Fix:** spatial focus moves; the clearer note; hoist the safe imports. **Effort:** S. **Tier:** D.

## Test gaps
- Every mutating `handle` branch (list in tui-screens-11); the two that would have caught real bugs here:
  Plugins `remove` on the primary (01) and Profiles `M` state preservation (04).
- A Profiles test that a disposition/track edit keeps `_res` warm (02) — the existing
  `test_res_cache_drops_when_ctx_routes_rebuilt` only covers the pin half.
- A TUI `--pretend` sweep (script ready: `scratch/tui-screens/scripts/tui_pretend_sweep.py`).
- An exception-in-handle test through the router (03).
- Empty-list navigation then reload (13); Config tall-block-at-small-height (16); unsynced-primary store
  roles (15); stale `_parts`/`_hard_deps` after a routes swap (14).
- Theme `load` confirmation and export-name validation (17); hardcoded-glyph drift under a rebind (21).
- `test_screen_profiles.py` asserts only chrome — no catalog row content, because the VM has none (07).

## Dead code
- `ProfilesScreen.draw`'s grouped-pane branches and `handle`'s `is_group_header` branch — grepped
  `toggle_grouping|\.grouped|group_new_count|cur_readonly` over `configsys/ test/ examples/
  ~/src/configsys-*/`: definitions + these call sites only (01 hit for `toggle_grouping`).
- `ps.own_members(...)`, `ps.removed_members(...)` (`profiles.py:119-120`, results discarded; methods have
  no other caller — same grep), and the discarded `ps.members(prof, _ceil)` at 118.
- `Intent.quit` — grepped `intent.quit|quit=True|\.quit\b`: no hits outside the field itself.
- The seven `_nav_str` `_KEYMAP is None` fallbacks — reachable only when a test runs without
  `build_ctx` (e.g. a single `test_screen_config` function); `run` always sets `_KEYMAP`.
- `ov_inst`, `ov_uninst` unpacked and unused at `profiles.py:122`.
- Not dead (checked): `_sample_*` states (used by the Theme preview and tests), `ComponentsVM.diags`.

## ABI / interface candidates
- Unify the Screen protocol before anyone else writes a screen (tui-screens-23): one `Session`, uniform
  `handle(ch, session, surface, pal)`, `on_enter()`/`dirty`, VMs as dataclasses, no `Intent.quit`.
- `Context.invalidate_config()` (or a routes generation) as the documented way to say "config changed,
  routing didn't" (tui-screens-02) — today every writer must choose between correctness and a 0.5 s rebuild.
- `actions.plugin_remove` should grow a guard for the primary / local-only / ahead clone (tui-screens-01).

## Questions for the user
1. Plugins `x` on the ★primary: confirm-and-delete, unbless-and-keep-the-dir, or refuse until pushed?
   And should `plugin remove` ever `rmtree` a `plugin init` primary whose source is that directory?
2. Picks, dispositions, the uninstall queue and orphans-ignore never feed the Resolver — OK to make those
   writers invalidate only the config (tui-screens-02)?
3. Scroll offsets written back by `draw`: accept and document it, or move clamping into a layout step and
   make "draw never writes the model" a tested rule (tui-screens-06)?
4. The layer-grouped Profiles pane: bind it (it was meant for `L`) or delete it with its ceiling plumbing?
5. Theme `load`: should it keep replacing your overrides (with a confirm), or overlay the pack on them?

## Refuted on verification
None. The checker verified the two findings in scope (every CRITICAL/HIGH plus every security/safety finding at
MED or above): tui-screens-01 and tui-screens-02. Both were confirmed by reproduction and neither severity
changed. The LOW safety/security findings tui-screens-17 and tui-screens-18 were outside the scope and were not
re-checked.
