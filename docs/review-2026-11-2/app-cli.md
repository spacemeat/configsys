# Review: CLI: app.py (parser, handlers, Context)

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/app.py` (4940 lines, read line by line), `configsys/__main__.py`, `configsys/__init__.py`.
Context: `configsys/actions.py` (run_plan, edit targets, pickers' writers), `test/test_pretend_sweep.py`,
`docs/principles.md`, CLAUDE.md, plus the code app.py leans on where a claim needed it
(`installState.superseded_installs/plan_with_swaps`, `planning.expand_plan`, `detection.py`,
`routes.Resolver` entry points, `versions.discover`, `sysupdates.apply_bulk`, `tui/menu.py` execute + pin
writers, `drivers/{apt,brew,tarball}.py`, `primarygit.fetch/primary_root`, `plugins.ensure_branch`).
Tests read: the 54 test files that import `configsys.app` (test_app, test_fix_cli_misc,
test_fix_cli_pretend, test_execute, test_locations, test_dispositions, test_pin, test_picks,
test_plugin_pretend, test_pretend_sweep, test_system_updates, …). A recording pytest plugin wrapped
`app.main` across all 54 files (820 passed) to list which verbs are ever driven through `main([...])`.

Sandboxes: `$RUN/scratch/app-cli/home*` (`--home`, `--os pop_os!:22.04` unless noted); `home5` is a
realistic config — the user's own plugin repos cloned in as local plugins (blender, kicad, opencv,
source, splash-ocean, neovim, bigdata) and `configsys-user` blessed as primary, machine `desktop`
(478 picks → 481 units, 878 components). No install ran; op repros capture the plan by stubbing
`actions.run_plan` with sudo refused in the runner.

## Carried over from docs/review-2026-09/app-cli-actions.md (+ README open items in this scope)

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] `_dispatch_op`/`cmd_location` skip `locations:` | fixed | `468a6d3` — `Context.prepare_units` (app.py:405) used by every op path |
| [HIGH] op execution loop exists twice (D3/B10) | fixed | `cc7bbe9` — `actions.run_plan`; `_dispatch_op` calls it (app.py:876) |
| [MED] TUI never invalidates the glue location cache (B4) | fixed | `468a6d3` — `actions.invalidate_location_cache` inside `set_included`; TUI pin writers call it (menu.py:1779, 1906) |
| [MED] pin write logic in app.py + re-implemented in the TUI | **open** | still 5 hand copies, no `actions.set_pin` → **app-cli-12** |
| [MED] `cmd_plugin trust/untrust` re-implements actions | fixed (core) | `f066814` — trust/untrust branches call `actions.plugin_trust*`; the verbatim `_find_decl` copy survives → **app-cli-24** |
| [MED] argparse help documents retired models | fixed | `acfdecc` (help + man regenerated); residual docstring/comment drift → **app-cli-17** |
| [MED] test gaps (verbs without `main` tests) | **open** (narrowed) | → **app-cli-15** |
| [MED] security `_offer_rekey` writes a plugin-chosen root path (A10) | **open** | → **app-cli-16** (also security-04) |
| [MED] refactor: app.py is five modules (D9) | **open** (worse: 3658 → 4940 lines) | → **app-cli-14** |
| [LOW] `diagnostics()` 2–3× per command (C4) | **open** | measured → **app-cli-11** |
| [LOW] `cmd_refresh` re-declares `_NATIVE_REFRESH`, double import | partly fixed (`ac709eb` uses the constant) / **open** | the copy of `refresh_native_index` has now drifted into a bug → **app-cli-06** |
| [LOW] `orphans --ignore` bypasses `actions.ignore_orphan`; no unignore verb | **open** | → **app-cli-22** |
| [LOW] `ctx.paths.dotfiles_force` side channel | **open** | app.py:1069,1100; dotfiles.py:582 → **app-cli-29** |
| [LOW] `_shell_glue_root` stages glue under the dotfiles root | obsolete | removed in `2a577c0`; staging is `<state>/staged-glue/` (shellguard) |
| [LOW] `disp get` reports retired include semantics | **open** | app.py:1900 (and test_dispositions.py:90 pins it) → **app-cli-17** |
| [LOW] `_STATUS_LABEL` identity map; `_unskip` mid-import + duplicate | **open** | app.py:22-24, 98-106, 191-192 → **app-cli-27** |
| [LOW] report tempfile leak; `cmd_show` re-imports os | **open** | now `_file_issue` app.py:3277; app.py:3557 → **app-cli-28**, **app-cli-27** |
| [LOW] private-API reaches (`resolve._select`, `_disco_spec`, `km._m`) | **open** | still there, and more of them → **app-cli-24** |
| [LOW] no CLI surface for the `uninstall:` queue | **open** | → **app-cli-22** |
| [NIT] `_offer_primary` prompts inside `load_pipeline` | **open** | app.py:459 → **app-cli-32** |
| [NIT] README command block omits 9 subcommands | fixed | `acfdecc` (README:245-349 lists picks/machine/…) |
| [NIT] TUI calls `cmd_refresh(ctx, None)` | **open** | tui/screens/components.py:440; signature unchanged → **app-cli-32** |
| [NIT] `expand_plan` set-version undocumented | n/a here | planning.py belongs to the actions area — but see **app-cli-04** for the CLI's `expand_plan` call |
| README: D9, C4, A10, Tier F reaches, `never_auto` rename | open | app-cli-14, -11, -16, -24 (app.py still reads `routes.candidate_only`, app.py:602,1745,2434) |

## Cross-cutting themes

- **The Context resolves in two different ways, and only one of them is right.** `load_pipeline`
  runs a second resolve pass with the auto-tighten and **detection** (adopt-installed) pins
  (app.py:473-487); every other resolve in app.py — `_dispatch_op`, `cmd_location`,
  `_location_lines`, `inspect_components`, the orphans listing, `_swap_headsup`, `check` — calls
  `ctx.routes.resolve_*` with config pins only. So `inspect` and the TUI show one method, and the CLI
  then acts on another (app-cli-01, -04). The fix is one `Context.resolve()` that everything uses.
- **The CLI and the TUI still execute "the same op" differently**, even after D3: the CLI's
  `expand_plan` gets no live states (it re-runs every present dependency), the CLI `upgrade --system`
  hand-copies `sysupdates.apply_bulk` and records no failure, `remove` doesn't drain the uninstall
  queue, and `fix-scope` bypasses `run_plan` entirely (app-cli-04, -05, -22, -26).
- **Hand copies drift, and in this area they already have.** `cmd_refresh` re-implements
  `refresh_native_index` — and today's brew-off-PATH fix (3d5bb6b) landed in only one of them
  (app-cli-06). The same shape: 5 pin writers, 12 hand-rolled y/N prompts (one crashes on a non-tty),
  11 hand-rolled `--pretend` previews reaching into 7 private `actions._…` helpers to re-derive "where
  it would land" (their labels already disagree with the real write), and string-sniffed return
  status (`'nothing to trust' in note`, `' from ' in msg`, `'pinned to' in err`).
- **Validation is weakest exactly where the CLI is the only door**: `picks add`/`disp set` accept any
  name, and `check` — whose resolve filter still assumes requested names come from profiles — calls a
  config with a typo'd pick clean while `inspect` shows it as an error (app-cli-08).
- **app.py is a library as well as the CLI.** The TUI imports 8 names from it (`where_report`,
  `where_profile_report`, `maybe_refresh_before_plan`, `published_pending`, `_file_issue`,
  `_edit_conflict`, `_primary_dir_name`, `cmd_refresh`) and `sysupdates` lazily imports
  `refresh_native_index` to dodge a cycle. It grew 35% since the D9 proposal (55 commits).
- **Per-command fixed cost is dominated by work nobody asked for**: every invocation builds a fully
  route-checked Resolver (0.61 s, 61% of it `routecheck.check_component` ×878), `check` does that and
  then loads + validates the catalog again, `inspect` runs `diagnostics()` twice (each re-resolving all
  picks and re-hashing every plugin), and every pick toggle drops the whole Resolver.

## Findings

### app-cli-01 [HIGH] correctness — CLI ops resolve without the detection tier: `install`/`upgrade` remove an adopted install, `remove` misses it, `location` points elsewhere
`configsys/app.py:780-882` (`_dispatch_op`, resolve at :816), `:2106-2157` (`cmd_location`),
`:2160-2193` (`_location_lines`, the shell-glue cache), `:537-555` (`inspect_components`, the TUI
`!uninstall` queue), `:2039` (`cmd_orphans` listing), `:2340-2352` (`_swap_headsup`). Compare
`load_pipeline` :473-487, the only place the detected soft pins and auto-tighten pins are applied.

When a component is installed through a valid non-default method (a tarball, a flatpak, cargo…),
`inspect` and the TUI adopt it (principles: "Detection-first … pin > detected > standing default").
The CLI op path never computes those pins, so it resolves the *default* method, and
`plan_with_swaps → superseded_installs` (installState.py:339-387) then finds the adopted install
"via another method" and schedules its **removal**. Named ops are not previewed or confirmed, so
`configsys upgrade syncthing` — run because `inspect` said `tarball\syncthing outdated` — silently
uninstalls the tarball and installs the apt package instead. `remove` goes the other way: it targets
the default unit (not installed) and leaves the real install in place. `location` and the
`location --all` glue cache report the default method's (empty) location, so PATH glue misses the
adopted tarball. The `--picks` runs pick names from the detected states, then plan from the
undetected resolve (the swap shows in their confirmed plan, at least).
**(reproduced)** sandbox `home2` (syncthing picked; only the tarball marker
`~/apps/syncthing/.configsys-syncthing.version` written; apt syncthing not installed on the host):
`repro_detect.py … syncthing upgrade` →
`inspect/TUI view: {'apt\\curl': ('installed', …), 'tarball\\syncthing': ('outdated', '1.0.0')}` /
`CLI 'configsys upgrade syncthing' plan: [('remove', 'tarball\\syncthing'), ('upgrade', 'apt\\syncthing')]`;
same for `install` (`[('remove', 'tarball\\syncthing'), ('install', 'apt\\syncthing')]`) and `remove`
(`[('remove', 'apt\\syncthing')]`); `configsys --home home2 location syncthing` →
`syncthing (apt) has no managed install location`.
**Fix:** compute the two machine-derived pin sets once per Context (`Context.resolution_pins()` →
`(tighten, detected)`, memoized, dropped by `invalidate()`), give the Resolver's `resolve_names` /
`resolve_with_roots` the same `extra_pins=`/`soft_pins=` parameters `resolve_resilient` has, and add
`Context.resolve(names, roots=False)` that every app.py resolve goes through. `where` should then
say "adopted: installed via tarball". Regression test: a tarball marker in a sandbox, `upgrade`
plan contains no `remove`. **Effort:** M. **Tier:** B.

**Verified:** CONFIRMED (reproduced) — and the `upgrade` case is worse than stated. Own sandbox
`scratch/verify-app-cli/home` (picks `[syncthing]`, `disabled-drivers: [brew]` to keep brew out, the
tarball marker `~/apps/syncthing/.configsys-syncthing.version` = `1.0.0` written through the tarball
driver, the version cache seeded so nothing needed the network; host Pop 22.04, apt syncthing not
installed, brew Cellar empty). `configsys --home H -v inspect` → `adopting installed: syncthing -> tarball` /
`tarball\syncthing  outdated  1.0.0  2.1.7`. `configsys --home H --pretend upgrade syncthing` → no plan,
no prompt, then `remove tarball\syncthing … [pretend] if [ -f …/.configsys-syncthing.version ]; then rm -rf
…/apps/syncthing; fi` / `upgrade apt\syncthing … [pretend] sudo … apt-get install --only-upgrade -y syncthing`;
`--pretend install syncthing` → the same remove, then `apt-get install -y syncthing`; `--pretend remove
syncthing` → only `apt-get remove -y syncthing` (the tarball stays); `location syncthing` →
`syncthing (apt) has no managed install location (installed on the system PATH)`, and `location --all`
wrote an empty `glue-locations.tsv`. One `upgrade --picks </dev/null` run prints `adopting installed:
syncthing -> tarball` and then `plan (2 ops): remove tarball\syncthing / upgrade apt\syncthing` (it stopped
at the confirm: non-tty, no `--yes`). By reading: `_dispatch_op` (app.py:816) →
`Resolver.resolve_with_roots` → `_resolve` passes only `self.pins` (routes.py:608-650; the soft/extra pins
exist only on `resolve_resilient`), while the TUI plans from `ms.states`' units (menu.py:765-771), so it
upgrades the tarball. `plan_with_swaps` has no "is this the adopted method" check (installState.py:339-407).
No test runs a CLI op over an adopted install (test_coexistence / test_detection cover the pieces). Worse
than "installs the apt package instead": `apt-get -s install --only-upgrade -y syncthing` →
`Skipping syncthing, it is not installed and only upgrades are requested.` / `0 upgraded, 0 newly
installed`, rc 0. So `configsys upgrade syncthing` deletes the install and installs nothing, and
`run_plan` then blames "a detection bug" (actions.py:306-313, by reading). The same holds for an
app installed from the store via flatpak, which is adopted and then `flatpak uninstall`ed (without
`--delete-data`, so its app data survives). Severity stays HIGH: the install can be reinstalled, and
no user data is lost.

### app-cli-02 [MED] safety — `--pretend refresh` hits the network and writes the version cache
`configsys/app.py:1527` and `:1552` (`cmd_refresh`): both `discover(spec, ctx.paths, refresh=True)`
calls omit `offline=ctx.runner.pretend`, so a dry run does live version discovery and
`versions._persist` writes `<state>/versions.hu` — CLAUDE.md: "`--pretend` is a full dry run … no
… cache". Drivers use `Driver._offline()`; only this direct call misses it. `test_pretend_sweep`
can't see it because its sandbox's picks (btop/fzf/bash/jq) have no github/url version source.
**(reproduced)** `home6` (`picks add syncthing; pin set syncthing tarball`), `_discover_live`
stubbed so no network: `repro_refresh.py` → `versions.hu before: False` /
`rc 0 | live discovery calls under --pretend: 1 | versions.hu after: True`. The same run without
the stub would fetch from GitHub. `versions --refresh`, `location --all`, `inspect`, `where`,
`install` under `--pretend` made 0 live calls (checked).
**Fix:** pass `offline=ctx.runner.pretend` to both calls (or print "[pretend] would re-query N
version sources" and skip the loop); add a github-sourced pick (`pin syncthing tarball`) to the
sweep's sandbox so this class stays covered. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). By reading: app.py:1527 `discover(spec, ctx.paths, refresh=True)`
and :1552 `_discover_latest(lc, ctx.paths, refresh=True)` pass no `offline=`. With `refresh=True`,
`versions._resolve` skips the cache and, since `offline` is False, calls `_discover_live` and then
`_persist` (versions.py:444-476). The same function guards `record_stale_pins` with
`if not ctx.runner.pretend` (:1560) but not these two calls. Sandbox `scratch/verify-app-cli/home` with
`pins: { syncthing: tarball }`, in-process `app.main([... '--pretend', 'refresh'])`: (a) with
`_discover_live` stubbed → `live _discover_live calls under --pretend:
['github:syncthing/syncthing:asset=syncthing-linux-amd64-*.tar.gz']`, and `versions.hu` changed hash and
mtime (its record went 2.1.7 → 9.9.9 with a new `fetched`); (b) unstubbed, with `urllib.request.urlopen`
recording and refusing (nothing sent) → it tried `https://github.com/syncthing/syncthing/releases.atom`,
`…/tags.atom` and `https://api.github.com/repos/syncthing/syncthing/releases/latest`. The pretend sweep's
picks resolve to `apt\btop apt\fzf apt\jq` + dotfiles/glue units, none with a `version:` spec or a
`latest-check:` (checked; its `bash` pick is not a known component), so its `['refresh']` never reaches
`discover`. The only other direct `discover()` without `offline=`, floorderive.py:61, has no runtime
caller in `configsys/`. Severity stays MED.

### app-cli-03 [MED] safety — `refresh` offers to delete the vendor source of an installed component that just isn't picked
`configsys/app.py:1365-1400` (`_orphaned_managed_sources`, `_reconcile_managed_sources`), called at
`:1595-1596` with `wanted = {comp of the resolved picks}`. A source is called "stale" when its
owning component isn't in this machine's picks — but `configsys install X` never adds a pick (by
design; the install help says so), and anything installed before the matrix model isn't picked
either. The prompt asserts "configsys wrote it for `X`, which you no longer use? [y/N]" and a `y`
runs `sudo rm -f` on a source an installed package needs for updates. With `--home` (the sandbox
flag) the check still reads the real `/etc/apt/sources.list.d` against the sandbox's picks. It also
prompts under `--pretend`, where nothing can happen.
**(reproduced)** `home6` (picks: syncthing only), answering `n`:
`yes n | configsys --home home6 --pretend refresh` →
`── stale managed package sources (owning component no longer in your config) ──` /
`remove /etc/apt/sources.list.d/charm.list — configsys wrote it for 'gum', which you no longer use? [y/N]` /
`remove /etc/apt/sources.list.d/slack.list — configsys wrote it for 'slack' …`, while
`dpkg-query -W gum slack-desktop` → `gum install ok installed`, `slack-desktop install ok installed`.
Function-level: `_reconcile_managed_sources(ctx, 'apt', wanted, ask=…, lister=lambda: brave_files)`
prompts for brave although nothing says brave is gone.
**Fix:** `wanted` = picks ∪ components with a ledger install receipt ∪ (cheap) owners whose package
the native manager reports installed; word it "not in this machine's picks"; never prompt under
`--pretend` (print what would be offered); with `--home`, say the system dirs are the real ones.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). By reading: `wanted = {units[k].comp for k in units}` (app.py:1595)
is the resolved picks only; `_orphaned_managed_sources` (:1365-1371) flags every route-owned source file on
disk whose owner isn't in it, with no receipt check and no installed check. test_source_reconcile.py injects
`wanted` and never tests how `refresh` computes it. Host: `/etc/apt/sources.list.d/charm.list` (route owner
`gum`, routes.hu:843) and `slack.list` (`slack`, :2344) exist; `dpkg-query -W gum slack-desktop` →
`gum install ok installed 2.0.2` / `slack-desktop install ok installed 4.53.276`. Sandbox
`scratch/verify-app-cli/home`, picks `[syncthing]`: `yes n | configsys --home H --pretend refresh` →
`── stale managed package sources (owning component no longer in your config) ──` /
``remove /etc/apt/sources.list.d/charm.list — configsys wrote it for `gum`, which you no longer use? [y/N]``,
and the same for `slack.list`. So it prompts under `--pretend`, against the real system dir, from a
`--home` sandbox. `yes y | … --pretend refresh` → `[pretend] sudo rm -f /etc/apt/sources.list.d/charm.list`
(echoed only; both files intact). `install X` never picks X (install help, app.py:3677; README:415
"installs the components without picking them"). Note: README:432 does document the criterion ("offers
to remove sources it added for components you no longer pick"). But the function's own docstring states
the intent ("I removed the component but its broken source keeps breaking apt"), and the prompt asserts
"which you no longer use"; a never-picked, still-installed package fits neither. Severity stays MED: it
needs an explicit `y`, and reinstalling re-adds the source.

### app-cli-04 [MED] correctness — the CLI re-runs every already-installed dependency; the TUI skips them
`configsys/app.py:860` calls `expand_plan(base_plan, units)` with no `states`, so `present(dep)`
(planning.py:46-47) is always false and every transitive dependency is folded in as an `install`.
The TUI passes them (`expand_plan(raw, units, ms.states)`, menu.py:771) and skips present deps — so
one op means two things. Consequences on the CLI: `sudo apt-get install -y <dep>` on every present
apt dep (an implicit upgrade of that dep, not in any plan; an apt-held dep with a newer candidate
can make apt refuse the whole install — by apt's held-package rule, not reproduced here); a ledger-locked non-native dep is reinstalled at the routed
version — `run_plan` never consults ledger locks, although driver.py:462-464 says "the ledger carries
the intent, honored by the op loop"; a source dep rebuilds. README:402-410 documents the
whole-tree rebuild as how CLI `install` behaves (hence `--no-deps`), so this may be intended for
`via: source` — but it is not the TUI's semantics, and planning.py's docstring says present deps
are skipped.
**(reproduced)** `home6` (syncthing pinned to tarball; host has curl): `repro_deps.py … install` →
`live state: {'apt\\curl': 'installed', 'tarball\\syncthing': 'missing'}` /
`CLI 'install syncthing' plan: [('install', 'apt\\curl'), ('install', 'tarball\\syncthing')]`.
**Fix:** decide the semantics (question 1). If deps should be skipped when present, inspect the
plan's units (the `Context.resolve` of app-cli-01 can return states cheaply via the probe cache) and
pass `states`; keep "the named component always re-runs" and `--no-deps`. Either way make
`run_plan` refuse install/upgrade of a ledger-locked unit unless the op is the explicit target.
**Effort:** M. **Tier:** B.

### app-cli-05 [MED] correctness — `upgrade --system` failures vanish: not recorded, no reason printed, apply loop hand-copied
`configsys/app.py:1192-1205` (`cmd_upgrade_system`) loops `drv.upgrade_all()` itself. The TUI goes
through `sysupdates.apply_bulk` (sysupdates.py:196-212: probe-cache invalidation + rescan) and records
each bulk failure as `system-updates\<mgr>` (menu.py:800-808) — which `_failure_open` (app.py:907)
already expects. The CLI records nothing, so the `!` page and `configsys report` never hear of a
failed CLI bulk upgrade, and it prints only `FAILED (exit N)` without `actions.fail_detail`.
**(reproduced)** `repro_sysupd.py` (gather stubbed to one apt row, a fake apt whose `upgrade_all`
exits 100): `-> apt upgrade FAILED (exit 100)` / `rc 100 | saved failures for 'configsys report' / ! page: []`.
**Fix:** call `sysupdates.apply_bulk(ctx, sorted(groups), refresh=False)`, record with
`reportgen.record_run(..., [f'system-updates\\{m}' …])`, print the failure excerpt, and
`_offer_report` like `_dispatch_op`. **Effort:** S. **Tier:** B.

### app-cli-06 [MED] reuse — `cmd_refresh` hand-copies `refresh_native_index`, and today's brew fix missed the copy
`configsys/app.py:1567-1601` vs `:1416-1430`. 3d5bb6b (brew off PATH) added `env=brew_env()` to
`refresh_native_index` only, so on fedora_atomic (brew is the native manager) `configsys refresh`
still runs bare `brew update` → "command not found" when Homebrew's prefix isn't on the process
PATH — the exact chain that commit describes. The post-cleanup re-run (:1598) also skips the
transient retry. Carried from 2026-09 LOW (the constant was fixed; the copy remains), plus the
double imports at :1540/:1566 and :1507/:1541.
**(reproduced)** `repro_brewenv.py` (`--os fedora_atomic`, `brew_env` stubbed to a marked env):
`native pm: brew` / `refresh_native_index ran: ('brew update', 'brew_env')` /
`cmd_refresh ran:         ('brew update', None)`.
**Fix:** `cmd_refresh` calls `refresh_native_index` (return the `Result` too, for the diagnosis
path) and re-uses it for the post-cleanup re-run. **Effort:** S. **Tier:** B.

### app-cli-07 [MED] correctness — `plugin init --dry-run` moves a tag-pinned primary onto its branch
`configsys/app.py:2837` (`_plugin_init_merge`): `plugins.ensure_branch(ctx.runner, plug)` runs
before the `args.dry_run or ctx.runner.pretend` return (:2853) and before "nothing to merge"
(:2856). On a detached (tag-pinned) primary it `git checkout`s the default branch, so a dry run
("show the plan and exit; write nothing") changes which content of the primary loads on this machine.
(`--pretend` is safe: the runner only echoes.)
**(reproduced)** `pinit` sandbox, a local primary added `--ref v1` then blessed:
`git status` → `HEAD detached at v1`; `configsys plugin init --dry-run` → `(dry run — nothing written)`;
`git status` → `On branch main`.
**Fix:** call `ensure_branch` only after the dry-run/pretend/nothing-to-merge returns, immediately
before the first write. **Effort:** S. **Tier:** B.

### app-cli-08 [MED] correctness — a typo'd pick passes `check`; `picks add` / `disp set` accept any name
`configsys/app.py:2603-2611` (`cmd_check`): resolve errors are kept only if the message contains
`'pinned to'` or `'ambiguous providers'`, and unknown components are skipped because "Unknown-
component members are already reported by prof_issues" — a leftover of the active-profiles model:
picks are not profile members, so an unknown pick is reported nowhere by `check`, while `inspect` /
the `!` page show it as an error. `cmd_picks add` (:1970) and `cmd_disp set` (:1909) never check the
name either (the TUI only offers catalog names). Classifying errors by substring is brittle (a
method tie, "equally valid AND equally preferred", is also dropped — the spec makes that a `check`
warning via routecheck, so it is covered there today).
**(reproduced)** `home1`: `configsys picks add nosuchtool` → `nosuchtool picked on this-machine (in top config)`, rc 0;
`configsys check` → `0 error(s), 1 warning(s) across 832 components`, rc 0;
`configsys --pretend inspect` → `✗ unroutable   nosuchtool: unknown component: nosuchtool`;
`configsys disp set nosuchcomp seen` → `nosuchcomp → seen (in top config)`, rc 0.
**Fix:** `check` lints every machine column of `picks:` (and `dispositions:`, `uninstall:`) against
the merged component set — an error for this machine's column, a warning for other columns
(another box may load a plugin that defines it); `picks add`/`disp set` print a warning for an
unknown name (question 3); give `ResolveError` a `kind` so `check` filters on data, not wording.
**Effort:** S. **Tier:** B.

### app-cli-09 [MED] correctness — `theme set`/`theme load` report success while the top config shadows the edit
`configsys/app.py:4752-4775` (`cmd_theme`) → `actions.set_theme_value` / `load_theme`
(actions.py:960-982, 1059-1070) write through `edit_target` (actions.py:333-343), which is
primary-first and not shadow-aware (its own docstring warns of exactly this). `config set`,
`picks add` and `disp set` use the shadow-aware `_nature_target`; the theme writers don't. With a
`theme:` key in the top config and a blessed primary, `theme set` lands in the primary and changes
nothing visible. (Code is in actions.py; reported here because the CLI verb prints the success.)
**(reproduced)** `pinit` (primary `myprim`): `theme set colors.accent "#00ff00" --local` then
`theme set colors.accent "#ff0000"` → `set colors.accent = #ff0000 (in myprim)`; `theme show` →
`colors: accent: #00ff00`.
**Fix:** pick the theme target with `_nature_target(ctx, 'theme', lives_in=<dotted key present in that file>)`.
**Effort:** S. **Tier:** B.

### app-cli-10 [MED] performance — `Context.invalidate()` throws away the Resolver on every config edit
`configsys/app.py:367-379`. Every writer in actions.py calls `ctx.invalidate()`, which drops the
config, the cached Resolver, the plugin data-file list, the plugin-code registration and the OS
refinement. Picks, dispositions, the uninstall queue, theme and keys can't change routes, but the
next `ctx.routes` access re-parses every layer and re-runs routecheck. The docstring says the
opposite ("Config edits (a pin, a profile toggle) need only the config reread").
**(reproduced/measured)** `home5` (878 components, 9 plugins): `actions.set_included(ctx, 'jq',
['desktop'], False)` → `write 17 ms, then next ctx.routes/config rebuild 521 ms` (a no-op toggle:
`1 ms`); `plugin code reloads: 1`. In the TUI that is ~0.5 s per changing `t` on Profiles
(`set_included` + `mark_all_seen` both invalidate; `ps.reload()` rebuilds).
**Fix:** `invalidate(*, routes=False)` — config only by default; the writers that change routing
inputs (pins, driver-preference, disabled-drivers, facets, components/os/drivers, plugin
add/sync/trust) pass `routes=True`. **Effort:** S. **Tier:** C.

### app-cli-11 [MED] performance — `diagnostics()` runs twice per `inspect`, each re-resolving the picks and re-hashing the plugins
`configsys/app.py:530-533` (`load_pipeline`) and `:673` (`cmd_inspect`) both call
`ctx.diagnostics(states)`; each call runs `plugins.status` (hashes every plugin tree, :234) and
`_dotfiles_diagnostics → actions.dotfiles_units` (a full `resolve_resilient` of the picks,
actions.py:1631-1638) that `load_pipeline` already did. Carried from 2026-09 C4.
**(measured)** `count.py home5 --pretend inspect` → total 1.95 s; `diagnostics x2 441 ms`;
`resolve_resilient x3 409 ms` (1 needed); `status x2 338 ms`.
**Fix:** memoize the last result on the Context keyed by `id(states)` (dropped by `invalidate()`),
and let `dotfiles_units(ctx, units=None)` take the units `load_pipeline` already resolved.
**Effort:** S. **Tier:** C.

### app-cli-12 [MED] reuse — pin writes are still five hand copies (and the TUI can't unpin or promote)
`configsys/app.py:2318-2404` (`_pin_set`, `_pin_unset`, `_pin_promote`) and
`configsys/tui/menu.py:1766-1782` (`_apply_method_pin`), `:1893-1909` (`_apply_provider_pin`) each do
read_pins → mutate → set_pins → invalidate cache. Only the CLI validates (`_validate_pin`) and gives
the swap heads-up; the TUI tells the user to go run `configsys pin promote` (menu.py:1781, 1908)
and has no unpin. Carried from 2026-09 MED (`docs/done/tui-screens-plan.md` planned the extraction).
**(verified by reading)**.
**Fix:** `actions.set_pin(ctx, name, value, *, validate=True)`, `unset_pin`, `promote_pin`
(returning `(changed, label, note)`), used by both surfaces; add "unpin" and "promote" rows to the
TUI method picker. **Effort:** M. **Tier:** D.

### app-cli-13 [MED] data-driven — `--pretend` previews are hand-rolled per verb over private `actions` helpers
`configsys/app.py:1910-1915` (disp), `:1942-1955` (picks), `:1991-1994`, `:2010-2014` (orphans),
`:2523-2539` (machine), `:2641-2650`, `:2675-2680` (config), `:4729-4748` (theme), plus
`_pin_set/_unset/_promote`, glue add/override, dotfiles activate/discard: 11 branches that re-derive
"where would this land" through `actions._setting_target`, `_picks_target`, `_nature_target`,
`_primary_target_label`, `_setting_home`, `_parse_map_tokens`, `edit_target` — while the real writers
already return `(False, PRETEND_NOT_SAVED)` under pretend. Two derivations of one answer already
disagree: `config set --local` prints the absolute path when real and `top config` under pretend.
**(reproduced)** `pinit`: `config set splash braille-bar --local` →
`set splash = braille-bar (in /tmp/…/pinit/home/.config/configsys/configsys.hu)`; the `--pretend`
branch says `(in top config)`.
**Fix:** writers return an `Edit(changed, target_label, pretend)` — under pretend they compute the
target and return without writing; the CLI prints `[pretend] would …` once, generically. Deletes the
per-verb branches and the private reach-ins. **Effort:** M. **Tier:** D.

### app-cli-14 [MED] refactor — split app.py (D9): it is the CLI and a shared library, and 35% bigger than when the split was proposed
`configsys/app.py` — 4940 lines (3658 at 7a395c5), 130 top-level defs, 55 commits since. Largest:
`Context` 533 lines, `build_parser` 491, `cmd_check` 238, `cmd_plugin` 184, `cmd_orphans` 124,
`cmd_refresh` 118. The TUI imports 8 names from it and `sysupdates` lazily imports
`refresh_native_index` "because app imports this module" (sysupdates.py:203).
Proposed modules: `context.py` (Context: load/resolve/diagnostics, :109-641 — the natural home of
app-cli-01's `Context.resolve`); `indexrefresh.py` (:1220-1623 — refresh, diagnosis, rekey,
reconcile, `maybe_refresh_before_plan`, `published_pending`; unit-tested in isolation already);
`whereview.py` (`where_report`, `where_profile_report` — shared text); `issues.py` (`_file_issue`,
report/request/request-os); `cli/` per command group (plugin, check, dotfiles+glue, config+theme+keys,
picks+machine+disp+profile, ops), each owning its argparse slice so `build_parser` stops being a
491-line function; `app.py` keeps `main` + a re-export shim for tests/tools. Removes the lazy
cycle-dodging imports and the TUI's dependency on the CLI module. **(measured by `ast`)**.
**Effort:** L. **Tier:** D.

### app-cli-15 [MED] test-gap — verbs no test drives through `main`, and the missing case that hid app-cli-01
From the recording run (424 `main` calls across the 54 files): never driven at all — `updates`,
`profile list|show`, `machine list|show`, `theme show|list|load`; only via a direct `cmd_disp` call
that pins the retired semantics with a `configs:` fixture (test_dispositions.py:60-96) — `disp
list|get`; only under `--pretend` by the no-writes sweep (no assertion on output or rc) — `remove`
(incl. the stranded-removal branch, app.py:794-814), `unlock`, `versions`, `refresh`,
`upgrade --system` (the real confirm/abort/failure-rc path), `request-os` beyond `--print`.
No CLI op test has an install present through a non-default method (the case behind app-cli-01, -04).
`test_pretend_sweep.VERBS` lacks `orphans --adopt`, `orphans --remove`, `theme load`, `plugin
unlock`, `dotfiles staged` (it migrates a legacy layout — a write path) — I ran all five under
`--pretend` against the sweep's sandbox: no writes today, but nothing guards them — and its
sandbox has no github-sourced pick (app-cli-02). Carried from 2026-09 MED (narrowed).
**Fix:** add the verbs to `VERBS` and a tarball pick to the sandbox; `main`-level tests for each
listed verb; a detection-adoption op test (tarball marker → no swap); an `upgrade --system` test with
a fake failing manager. **Effort:** M. **Tier:** B.

### app-cli-16 [LOW] security — `_offer_rekey` writes a plugin-chosen path as root (A10, still open)
`configsys/app.py:1306-1362`, fed by `_owned_index_sources` (:1220-1238), which takes `source-path`
/ `repo-id` from any layer's bindings. On a signature failure for a source a plugin claims, the
prompt offers `sudo curl -fsSL <pubkey-url> -o <pubkey-path>` with both values from route data
(quoted, so no injection; the path is shown). Who: any plugin author, trusted or not. When:
`configsys refresh` hits a SIGNATURE-class failure. Privilege: root file write. Consent: a y/N whose
wording ("rotated?") frames it as routine. Already possible without this bug: the apt driver writes
the same `pubkey-url` → `pubkey-path` at **install** time with no prompt and no trust check — I
reproduced an untrusted plugin's `pubkey-url`, `source-line` and `debconf` all running under
`--pretend install evtool` (`[pretend] [ -f /etc/apt/keyrings/ev.gpg ] || sudo curl … -o …`,
`… | sudo tee /etc/apt/sources.list.d/ev.list`, `sudo echo '…' | debconf-set-selections …`) while
`plugin list` said `ships recipes — untrusted`. That root issue is **plugins-01 / security-04**;
the app.py part adds little on top, hence LOW.
**Fix:** with the routecheck path constraint security-04 proposes, `_offer_rekey` should also
refuse a key path outside the manager's keyring dirs and a source not owned by a trusted layer.
**Effort:** S. **Tier:** A.

### app-cli-17 [LOW] comment-drift — retired vocabulary and stale promises in docstrings, comments and printed text
`configsys/app.py`: :1-7 module docstring "resolve the **active profiles**" (glossary-retired);
:315 "`~/configsys.hu`" (the legacy path); :368-374 `invalidate` "need only the config reread"
(app-cli-10); :393-397 `apply_locations` "as the reserved `location` field … a route field named
`location`" (it sets `location-override`); :470-471 "from an **auto-activated project profile**"
(discovery was removed); :538,544 "the active set", "bash-dotfiles" (retired → `shell-glue`);
:1367,1376,1395 "active set/config" (user-visible header); :1831-1841 prints
"**configsys: active set changed:**" and "an included profile that grew upstream"; :1872-1873
`cmd_disp` "(v2 triage) … include/exclude are profile membership"; :1900-1901 `disp get` prints
"include (in one of your profiles)" (carried 2026-09 LOW; test_dispositions.py:90 asserts it);
:2161-2164 `_location_lines` "subprocess-free" (42 `brew --prefix` spawns on home5, app-cli-20);
:2212 "+ tests" (no test uses it); :2403 `pin promote` prints "**commit & push** {prim}" though the
journal already committed it; :2430 `check` "your ~/configsys.hu"; :2595 "the active set";
:2685-2686 "`_find_decl` … still used by the `trust` branch" (it isn't; `plugin diff` is);
:3122 "`plugin push` shares the removal" (under `primary-push: auto` it already did); :4480
capture prompt "committed if you push the plugin" (capture commits now); :4613-4614 `cmd_config`
"(scope / driver-preference / auto-tighten) … the TUI Config screen will call"; :4711-4712
`cmd_theme` "(Config screen) will call". The `-h` epilog (the man page source, :3584-3606) omits
`CONFIGSYS_FACET_<name>` (routes.py:523) and `CONFIGSYS_LAUNCHER` (glue preludes).
**(reproduced, pin promote)** `pinit`: `pin promote fzf` → `moved pin fzf -> native into primary plugin myprim` /
`commit & push myprim so it travels to your other machines` / `saved to myprim — 1 change not pushed yet`;
`git log` → `52d6a9e pin promote fzf`.
**Fix:** one sweep (then `/update-docs` regenerates the man page); rename `active_snapshot` →
`picks_snapshot`; `disp get` reports `picked on <machine>` from `cfg.included()` and the test moves
to `picks:`. **Effort:** S. **Tier:** E.

### app-cli-18 [LOW] reuse — twelve hand-written y/N prompts with three different non-tty policies (one crashes)
`configsys/app.py:439, 760, 975, 1186, 1350, 1390, 1611, 2026, 3001, 3041, 3364, 3400, 3432, 4481`.
`_confirm_plan`, `upgrade --system`, `report`/`request`/`request-os` refuse without `--yes` on a
non-tty; `plugin undo` proceeds without asking (:3036); `dotfiles capture` has no isatty check and
no `EOFError` handler; `refresh`'s prompts run under `--pretend`. The three report/request/
request-os commands also repeat the same print-body/confirm/send block verbatim (:3350-3370,
3388-3407, 3420-3439).
**(reproduced)** `home8` (btop picked, `~/.config/btop/btop.conf` present):
`configsys dotfiles capture < /dev/null` → `File "…/app.py", line 4481, in cmd_dotfiles_capture` /
`EOFError: EOF when reading a line`.
**Fix:** one `_ask(prompt, *, yes=False, default=False, refuse_noninteractive=True)` helper (pretend
→ say what would be asked and answer no), and one `_review_and_file(ctx, title, body, *, yes,
print_only, label, save_as)` for the three filing verbs. **Effort:** S. **Tier:** D.

### app-cli-19 [LOW] performance — `check` loads and route-checks the whole catalog twice
`configsys/app.py:2434-2446`: `routes.load(…, validate=False)` + `routecheck.validate` duplicate the
work the Context's Resolver already did (it is built anyway — glue drift and resolve errors at
:2584, :2607 use `ctx.routes`, and `ensure_plugin_code` at :2432).
**(measured)** `home3`: `Resolver build 0.53s; second routes.load(validate=False) 0.16s;
routecheck.validate 0.39s`; under cProfile `check_component` ran 1664 times for 832 components;
`check` total 1.31 s.
**Fix:** take `cascade/components/drivers` from `ctx.routes` and keep the issues its load-time
routecheck produced (a `Resolver.route_issues` attribute) instead of re-validating. A structural
error that stops the Resolver still falls back to the tolerant path. **Effort:** S. **Tier:** C.

### app-cli-20 [LOW] performance — `location --all` (the shell glue's cold-cache call) takes ~2 s
`configsys/app.py:2160-2193`: `resolve_names` raises on any unroutable pick and then
`resolve_resilient` resolves everything again (:2173-2176); `brew.location` spawns `brew --prefix
<formula>` per brew unit (drivers/brew.py:194-198) though the docstring promises "subprocess-free";
and with `--os`/`CONFIGSYS_OS` set, `main`'s `check_os` (:4914-4916) builds the full validated
Resolver even for `show`/`keys`.
**(measured)** `home5`: `location --all` 1.96/1.98/1.97 s; per driver `brew x42 640 ms`,
`resolve_names` raised (blender-5.2 method tie) → second resolve; `subprocesses spawned by
location(): 42`. `show routes --path`: 0.18 s without `--os`, 0.82 s with it; Resolver build 0.61 s
of which `check_component x878 = 0.37s`.
**Fix:** call `resolve_resilient` once; compute brew locations as `<brew prefix>/opt/<formula>` from
one prefix lookup (drivers area); check a forced block against the cascade only. Also pass
`probecache.of(ctx)` to `stranded.foreign_index` in `_dispatch_op`'s remove loop (:805 spawns
`pacman -Qm` per unroutable name on Arch). **Effort:** S. **Tier:** C.

### app-cli-21 [LOW] performance — `refresh` queries version sources one at a time
`configsys/app.py:1513-1528` and `:1544-1555` loop `discover(...)` serially. Since B9 the cache
writes are lock-safe (`versions._persist` under `_CACHE_LOCK`), so the per-source network waits can
run in parallel like the inspect probes (`installState._parallel_map`).
**(measured: count only — no network in this review)** `count_refresh.py home5` → `units 481 |
unique live version sources refresh queries serially: 28` (`github 19, crates 4, pypi 3, url 2`);
at a few hundred ms per fetch that is several seconds of waiting.
**Fix:** collect the unique specs, `_parallel_map(discover, …)`, print in sorted order.
**Effort:** S. **Tier:** C.

### app-cli-22 [LOW] parity — the CLI can't see or clear the uninstall queue, and `remove` never drains it
`build_parser` has no `uninstall` verb; `actions.stage_uninstall` / `clear_uninstall` have no app.py
callers. The TUI drains the queue after a successful remove (menu.py:811-818); `_dispatch_op`
(through `run_plan`, which doesn't) leaves a CLI-removed component queued. Also CLI-missing: `machine
rename` (`actions.rename_machine`), `orphans --unignore` (`actions.unignore_orphan`), and `orphans
--ignore` still writes `orphans-ignore` by hand (:1988-2003; its `else` branch at :2001 is
unreachable). Carried from 2026-09 LOW. **(verified by reading)**.
**Fix:** `configsys uninstall list|add|rm|clear` (or `remove --stage`), drain the queue in
`_dispatch_op` on a successful remove, `machine rename`, `orphans --unignore`, `--ignore` →
`actions.ignore_orphan` (taking a list). **Effort:** S. **Tier:** G.

### app-cli-23 [LOW] correctness — exit codes and messages that claim more than happened
`config unset K` (:4688-4689) clears only the shadowing top-config value and prints "cleared K"
while a primary value stays effective; `refresh` always returns 0 (:1623), even when the index
refresh failed and nothing was stamped (so `configsys refresh && configsys upgrade --picks --yes`
proceeds); `plugin untrust <unknown>` (:3171-3174) and `plugin unbless` with no primary
(:3097-3100) return 0 on failure; `plugin trust` / `plugin diff` / `plugin remove` decide their rc
or follow-up text by substring-matching the action's message (:3169, :2954, :3120-3121 — `plug` there
is assigned and never used). **(reproduced)** `pinit`: `config set splash plain` (→ myprim),
`config set splash braille-bar --local`, `config unset splash` → `cleared splash (in top config)`;
`config get splash` → `plain`. `home1`: `plugin untrust nosuch` → `nosuch was not trusted`, rc=0;
`plugin unbless` → `no primary plugin set`, rc=0.
**Fix:** `unset` says "still set in <primary> (= plain)" (or offers to clear both); `refresh`
returns 1 when the index refresh failed; actions return a status enum instead of prose to sniff.
**Effort:** S. **Tier:** B.

### app-cli-24 [LOW] abi — app.py reaches into a dozen modules' private names
`resolve._select` (:1712, 1744 — carried), `drv._disco_spec` (:1521 — carried), `km._m` (:3521-3522 —
carried), `menu._is_ssh` (:4819), `config._selected_machine(cfg._layers)` (:1028-1030),
`plugins._transport_for/_git_transport/_set_push_remote` (:2911, 2923), `primarygit._count/_them`
(:3021, 4891-4892), the glue driver's `_dest_glue_root/_specs/_installed_shells/_user_glue_roots/
_load_overrides` and `drivers.glue._GLUE_SHELLS` (:2760, 2581-2582, 4144, 4183, 4235, 4241),
`df._capture_root` (:4447), and the seven `actions._…` helpers of app-cli-13. `_find_decl`
(:2675-2682) is a verbatim copy of `plugins.find_decl` (plugins.py:1443-1449). The retired
`candidate-only` term lives on as `routes.candidate_only` / `_candidate_only` (:602, 1745, 2434 —
Tier F `never_auto` rename). **(verified by reading)**.
**Fix:** promote the ones a surface needs (`select_with_reason`, `Driver.version_spec`,
`Keymap.items()`, `Config.own_machine()`, `primarygit.count_phrase`, a glue `user_glue_root(local)`),
delete `_find_decl`, rename `candidate_only` → `never_auto` with the Tier F batch. **Effort:** M.
**Tier:** F.

### app-cli-25 [LOW] data-driven — `cmd_check` is seventeen hand-kept lists; the OS advisories are prose keyed by block name
`configsys/app.py:2429-2666`: each lint builds its own list, and the lists are enumerated three
times (the "all clear" condition :2616-2620, the printing :2624-2657, the counts :2658-2663) — a new
lint must be added in three places. `Context.diagnostics` (:194-221) hard-codes three OS advisories
in Python, matched by `_blk == 'kde_linux'` / `'chimera'` (a derivative block that `using:`s them
gets none) — data that belongs on the `os:` block.
**Fix:** `checks = [(level, tag, messages)]` built by small functions and printed/counted by one
loop (which also lets the `!` page reuse the static lints); an `advisory:` text field on `os:`
blocks, inherited through `using`. **Effort:** M. **Tier:** D.

### app-cli-26 [LOW] safety — `fix-scope` moves installs with no preview and outside the op loop
`configsys/app.py:988-1019`: with no names it acts on every mismatched unit immediately (each is an
uninstall at one scope + install at the other), with no plan shown or confirmation (unlike
`--picks`, `upgrade --system`), and it calls `drv.reconcile_scope` directly — no failure record for
`report`/`!`, no ledger save/receipt update, no Ctrl-C handling, no up-front sudo. The TUI has no
fix-scope at all; its `!` line tells the user to run it. **(verified by reading)**.
**Fix:** build `[('fix-scope', key, rc)]` steps, show + confirm like `_confirm_plan`, and run them
through `run_plan` (a `fix-scope` op). **Effort:** S. **Tier:** B.

### app-cli-27 [LOW] dead-code — stragglers
`_expand_profile_args` (:689-695) has no caller anywhere (only its `_detail` sibling is used);
`_installed_despite_failure` (:941-944) is a test-only re-export shim (test_app.py:555 can import
`actions.installed_despite_failure`); `_STATUS_LABEL` (:98-106) is an identity map; `_unskip` is
defined between the import blocks (:22-24) and duplicated as `diagnostics.unskip` (:191-192);
pass-through wrappers `invalidate_location_cache` (:2211-2214), `_dotfiles_root_label`
(:4338-4340), `_active_dotfiles` (:4106-4110); unreachable `else` in `orphans --ignore` (:2001-2002);
unused `plug` (:3121); repeated imports (`refreshstate` :1540/:1566, `discover` :1507/:1541, `os`
:3557, `Path` :3447, `sys` :433, `actions` :3161, `primarygit` :3068).
Grepped: `grep -rn` of each name over `configsys/ tools/ test/ examples/ ~/src/configsys-*/`
(`*.py`, `*.sh`, `*.md`); none is in the frozen ABI list (driver.py docstring). **Effort:** S. **Tier:** D.

### app-cli-28 [LOW] correctness — the `gh` report body tempfile is never removed
`configsys/app.py:3276-3283` (`_file_issue`): `NamedTemporaryFile(delete=False)` per filing, never
unlinked on success or failure (the body can hold scrubbed-but-personal output). Carried from 2026-09
LOW. **(verified by reading)**. **Fix:** `try/finally: os.unlink(bodyfile)`. **Effort:** S. **Tier:** B.

### app-cli-29 [LOW] abi — `--force` reaches the dotfiles driver through an undeclared `Paths` attribute
`configsys/app.py:1069, 1100` set `ctx.paths.dotfiles_force`; drivers/dotfiles.py:582 reads it with
`getattr(…, False)`. `Paths` doesn't declare it, so a plugin or test building a `Paths` gets a
silent default, and the TUI can't offer it. Carried from 2026-09 LOW. **(verified by reading)**.
**Fix:** declare it on `Paths` (default False) or pass `force=` through the op. **Effort:** S. **Tier:** F.

### app-cli-30 [NIT] correctness — piping any command to `head` ends in a BrokenPipeError
Only `cmd_show` handles it (:3554-3558). **(reproduced)** `home5`:
`configsys profile list | head -1` → `Exception ignored in: <_io.TextIOWrapper name='<stdout>' …>` /
`BrokenPipeError: [Errno 32] Broken pipe`. **Fix:** catch it once in `main` with the same `dup2`
devnull trick. **Effort:** S. **Tier:** B.

### app-cli-31 [NIT] naming — parser locals that shadow each other or read as other commands
`build_parser`: `mp` is both the `machine` (:3746) and `manpages` (:4072) parser, `pr` both
`profile` (:3836) and `plugin remove` (:3920), `pun` both `plugin untrust` (:3940) and `plugin undo`
(:3965), and `pin` (:3968) is the `plugin init` subparser. **Fix:** name them by command
(`p_machine`, `p_plugin_init`, …) — or let each command module own its slice (app-cli-14).
**Effort:** S. **Tier:** D.

### app-cli-32 [NIT] correctness — two leftovers from 2026-09
`load_pipeline` (:459) still offers the first-run primary prompt from any pipeline command (`inspect`,
`refresh`, `install --picks`…), not just the TUI; the TUI still calls `app.cmd_refresh(ctx, None)`
(tui/screens/components.py:440) against `def cmd_refresh(ctx, args)` (:1506). Carried NITs.
**Fix:** offer only from `cmd_tui`/an interactive bare run; `cmd_refresh(ctx, args=None)`.
**Effort:** S. **Tier:** B.

### app-cli-33 [NIT] feature — no `--version`
`configsys/__init__.py:1` defines `__version__` (only hatch reads it); `configsys --version` →
`configsys: error: unrecognized arguments: --version` **(reproduced)**. Collaborators filing
issues by hand will be asked for it. **Fix:** `p.add_argument('--version', action='version',
version=f'configsys {__version__} (<git short HEAD>)')`. **Effort:** S. **Tier:** G.

### app-cli-34 [NIT] correctness — `--pretend plugin list --fetch` says the fetch failed
`configsys/app.py:3234-3235`: under `--pretend`, `primarygit.primary_root` returns None so `fetch`
returns False and the row reads "could not fetch its remote — counts are as of the last fetch", and
no counts follow. **(reproduced)** `pinit`: `--pretend plugin list --fetch` →
`ok  [could not fetch its remote — counts are as of the last fetch]`. **Fix:** say
"[pretend] not fetched". **Effort:** S. **Tier:** B.

## Test gaps

- A CLI op (`install`/`upgrade`/`remove`/`location`) over a component installed through a
  non-default method — would have caught app-cli-01.
- A CLI `install` whose dependency is already present (and one that is ledger-locked) — app-cli-04.
- `--pretend refresh` with a github-sourced pick; `VERBS` += `orphans --adopt`, `orphans --remove`,
  `theme load`, `plugin unlock`, `dotfiles staged` — app-cli-02, -15.
- `refresh`'s stale-source reconcile with an installed-but-unpicked owner (should not be offered) —
  app-cli-03.
- `upgrade --system` with a failing manager: rc, printed reason, recorded failure — app-cli-05.
- `cmd_refresh` on a brew-native OS passes `brew_env` — app-cli-06.
- `plugin init --dry-run` on a detached primary leaves HEAD alone — app-cli-07.
- `check` errors on an unknown pick — app-cli-08.
- `theme set` with a shadowing top-config `theme:` — app-cli-09.
- `main`-level tests for `updates`, `profile list|show`, `machine list|show`, `theme show|list|load`,
  `disp list|get` (on a `picks:` fixture), `remove` (stranded branch), `unlock`, `versions`,
  `refresh`, `upgrade --system` — app-cli-15.
- `dotfiles capture` without `--yes` on a non-tty — app-cli-18.

## Dead code

- `app._expand_profile_args` — `grep -rn "_expand_profile_args" configsys/ test/ tools/ ~/src/configsys-*/ --include=*.py` → only its definition and its sibling's docstring.
- `app._installed_despite_failure` — used only by test_app.py:555 (same grep).
- `app._STATUS_LABEL` — an identity map used once as `.get(s, s)` (app.py:657).
- Also the stragglers in app-cli-27 (each grepped over `configsys/ tools/ test/ examples/ ~/src/configsys-*/`; none in the frozen ABI list of configsys/driver.py).

## ABI / interface candidates

- `Resolver.resolve_names` / `resolve_with_roots` should accept `extra_pins=` / `soft_pins=` like
  `resolve_resilient`, and the Context should own the machine-derived pins (app-cli-01).
- Writers in actions.py should return a typed `Edit(changed, target_label, pretend)` (and a status
  enum rather than prose) so neither surface re-derives targets or sniffs messages (app-cli-13, -23).
- `ResolveError.kind` (unknown / no-binding / pin-conflict / method-tie / provider-ambiguity) so
  `check`, the `!` page and `where` classify without substring matching (app-cli-08).
- `actions.set_pin` / `unset_pin` / `promote_pin` (app-cli-12).
- `Paths.dotfiles_force` declared, or a `force=` op argument (app-cli-29).
- The private names app.py reaches into (app-cli-24), and the `candidate_only` → `never_auto` rename.

## Questions for the user

1. **Dependency semantics of CLI `install`/`upgrade`.** README says `install X` rebuilds X's whole
   dependency tree (hence `--no-deps`); the TUI skips present dependencies. Which should both
   surfaces do? Re-running present deps upgrades apt deps implicitly, fails on an apt-held dep with a
   candidate, and reinstalls a ledger-locked non-native dep (app-cli-04).
2. **Detection in the CLI.** I assume CLI ops should honor adopted installs exactly as `inspect`/the
   TUI do (app-cli-01). Confirm — or should a named CLI op deliberately mean "the default method"?
   If so it must at least preview + confirm the swap-remove.
3. **Unknown names in `picks add` / `disp set`.** Picks are uniform (they travel), and another
   machine may load a plugin that defines the name — warn only, or refuse unless `--force`?
4. **`config unset` when the setting lives in both layers**: clear only the shadowing one (today,
   but say so), or clear every writable layer (app-cli-23)?
5. **D9 shape**: per-command modules that own their argparse slice (a registration table) — or the
   lighter split (context / indexrefresh / whereview / issues / cli-plugin / cli-check) behind a shim?
