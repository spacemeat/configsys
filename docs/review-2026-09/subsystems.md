# Subsystems review — install-state, versions/floors, orphans, reporting, runner, OS detect, paths, misc

Scope: configsys/{installState,versions,versionreport,versionsweep,floorderive,flooradvise,orphans,reportgen,report,rebootcheck,refreshstate,failures,startuptiming,runner,osdetect,osversion,paths,splashes}.py plus their tests. Read-only; every claim below was verified by reading the cited lines. Absolute paths: /home/schrock/src/configsys/...

## Themes

- **The two on-disk version caches are per-call load/modify/save and are now hit from a thread pool.** `versions.VersionCache` and `versionreport._LatestCache` each re-parse their .hu file on every lookup and rewrite it on every miss. Since Phase C made `inspect_one` run on 8 threads, the tarball/appImage/source `get_latest` path races on `versions.hu` (lost updates) and re-parses it once per unit. `configsys refresh` is O(n) full-file reads+writes.
- **Already-paid enumerations are paid again.** `inspect()` batches `installed_index()` per driver and exposes it (`inspector.enum` / `ctx.startup_enum`), but `detect_coexisting` re-enumerates every package manager (and, because its lock is released during the subprocess, up to 8 workers can spawn the same `dpkg-query` simultaneously); `superseded_installs`/`plan_with_swaps` probe per binding per target; `build_reverse_index` is rebuilt three times per `O` press; `diagnostics()` re-runs `versionreport.report` (live `get_version` subprocess per method) on every TUI rebuild.
- **The version/floor subsystem has three comparison idioms and two copies of the same memo closure.** `versionreport._ge/_lt/_max_version`, `versionsweep.meets`+`osversion._CMP`, and `flooradvise._provides_meets` (a regex that re-extracts the literal from a constraint instead of `osversion.parse_constraint`). `sweep_ctx.rep()` and `flooradvise._unmet.rep()` are the same 7 lines.
- **Doc/comment drift is concentrated in three places**: `osversion.py`'s module docstring (and half its API) describes the retired `ubuntu@22.04` block-qualifier model; `paths.py`'s header names a default and a file that no longer exist; `docs/startup-perf-plan.md` still says "fixes NOT built" while all three phases are in `installState.py`. Plus the orphans doc still specifies an `excluded` kind the code doesn't have.
- **Runner security posture is sound where checked, but rests on convention.** `Runner.run` takes a shell string executed as `sudo bash -c`; apt quotes every route field with `shlex.quote`, but nothing in the runner enforces it, and `env=` is silently discarded by sudo's env_reset for privileged ops. `sudo_session` (the only exception-safe way to drop the keepalive) has zero callers.
- **Small correctness bugs**: the TUI batch persists only the LAST failure (CLI persists all); `failures.py` rule order classifies pacman's "target not found" as a dead-URL; `inspect()` progress can never reach 100% when `reuse` is non-empty.

---

### [HIGH] performance/correctness — `versions.py` cache is loaded and saved per call, now from a thread pool (lost updates)

- `configsys/versions.py:331-365` (`_resolve`) and `:368-399` (`_resolve_asset`): every call does `VersionCache.load(paths)` (a full humon parse of `state_dir/versions.hu`) and, on a miss, `cache.save(paths)` (rewrites the whole file from THIS call's in-memory copy).
- Reached from `configsys/driver.py:104-113` (`resolve_version` → `discover`) which is the `get_latest` of tarball (`drivers/tarball.py:46-47`), appImage, source, script, pipx (`drivers/pipx.py:125`) — i.e. every non-package-manager unit.
- `configsys/installState.py:142-149` runs `inspect_one` on a `ThreadPoolExecutor(max_workers=8)`. Two threads that both miss the TTL for different keys each load the file, set their own key, and save → last writer wins, the other's discovery is silently dropped (it will re-fetch next start — a "warm == cold" regression for a subset of units). On a warm cache it is still one file parse per unit (N units → N parses of a file that grows with N).
- `configsys/app.py:1123-1133` (`cmd_refresh`): the serial refresh loop does load+save per spec → O(n²) bytes of file IO over a run.
- No test covers concurrent access or the per-call load (test/test_versions.py has cache hit/TTL/refresh tests only, all single-threaded).

Recommendation: hold ONE `VersionCache` per process (or per `Paths`) behind a lock: load lazily once, mutate in memory, mark dirty, save once at the end of `inspect()`/`refresh` (or via an `atexit`/explicit `flush`). Same shape as `versionreport._LatestCache` should get (below). Add a test that runs two `discover` calls for different keys concurrently and asserts both records survive.

### [MED] performance — `detect_coexisting` re-enumerates what `inspect()` just enumerated, with a thundering-herd window

- `configsys/installState.py:236-247`: `index_of()` checks `enum` under the lock, RELEASES the lock, runs `drv.installed_index()` (a `dpkg-query -W` / `flatpak list` / `npm ls -g`), then `setdefault`. With `_parallel_map(_one, …)` at `:283` (8 workers) the first wave of states all miss on `apt` simultaneously → up to 8 concurrent identical enumerations; only the first result is kept.
- `configsys/installState.py:115-121` already computed `self.enum = {driver: installed_index}` for the batched drivers, and `configsys/app.py:442` stores it as `ctx.startup_enum` — but `detect_coexisting(self, states)` at `app.py:446` is called without it and starts from an empty `enum`.

Recommendation: accept a `seed` (pass `inspector.enum`) and use a per-driver `Future`/`Event` so a concurrent miss waits for the in-flight enumeration instead of spawning its own. Add a test with a counting fake `installed_index` under >1 states.

### [MED] performance — `diagnostics()` re-runs `versionreport.report` (live subprocesses) on every TUI rebuild

- `configsys/app.py:235-241`: `flooradvise.advise` + `resident_advise` run inside `Context.diagnostics(states)`, which is called at `app.py:449`, `app.py:582`, `tui/menu.py:1392` and `tui/menu.py:5105` (every TUI tree rebuild).
- `configsys/flooradvise.py:49-55` memoizes `versionreport.report` only within ONE `_unmet` call; `versionreport.report` (`configsys/versionreport.py:159-175`) loads + saves `method-versions.hu` per call and runs a LIVE `drv.get_version(rc)` subprocess per candidate method (`:172`) — the installed versions are already in `states`.
- The comment at `app.py:233-234` ("adds no cost until the version-floors data exists") is now stale: floors ship in `routes.hu:948,1036,1046` (`provides: { cargo: ">=1.80" }`, `go: ">=1.21"`, goimports `requires: [ { go: ">=1.21" } ]`), so any machine that picks a go-install tool pays per-provider subprocesses on each rebuild.

Recommendation: memoize reports on `ctx` per load generation (invalidate on execute/refresh), and let `report()` take an optional installed-map so `flooradvise` can feed `states` instead of re-probing.

### [MED] bug — TUI batch persists only the LAST failure; CLI persists all

- `configsys/tui/menu.py:571-577`: `last_failure = reportgen.failure_from_result(...)` overwrites per failed op, then `reportgen.save_failure(ctx.paths, last_failure)` (the single-record compat wrapper, `reportgen.py:49-51`).
- `configsys/app.py:792` uses `save_failures(ctx.paths, failures)` (all of them), and `reportgen.py:39-45` docstring says the file exists "so every failed unit is kept, not just the last".
- Result: after a TUI run with three failures, `configsys report` sees one.

Recommendation: collect a list in the TUI loop and call `save_failures`; delete `save_failure`/`load_failure` (see dead code).

### [MED] bug — `failures.py` rule order misclassifies "target not found" / "command not found" as a dead URL

- `configsys/failures.py:43-45`: the NOT_FOUND rule `\b404\b|Not Found|…` is `re.I` and precedes the DEPENDENCY rule at `:49-52`, which contains `target not found` (pacman's exact wording). So `error: target not found: foo` → NOT_FOUND ("an upstream URL is gone…") instead of DEPENDENCY ("per-distro name drift"). `bash: xyz: command not found` likewise reads as a moved URL.
- `\b404\b` also matches inside version strings (`1.404`) since `.` is a word boundary. Because NOT_FOUND is in `DEFINITIVE` (`:78`), a false NOT_FOUND also suppresses `retry_transient` (`:89`).

Recommendation: move the DEPENDENCY rule above NOT_FOUND, anchor `Not Found` to an HTTP context (`HTTP.*404|404 Not Found`), and add the pacman/bash cases to test/test_failures.py.

### [MED] performance — `superseded_installs`/`plan_with_swaps` probe per binding per target, serially

- `configsys/installState.py:307-325`: for each non-target candidate binding, `drv.get_version(rc)` (a subprocess) — no `installed_index` reuse (unlike `detect_coexisting`), no parallelism.
- `configsys/installState.py:336-344` calls it for every install/upgrade/set-version op in the plan; `configsys/app.py:1868-1871` loops it again for the pin heads-up. A 30-component install with 3-4 methods each is ~100 extra serial spawns before the first `apt-get`.
- `states[*].also_present` (computed at startup by `detect_coexisting`) already holds exactly this information when `detect-coexisting` is on.

Recommendation: accept an optional `index cache`/`states` and use `also_present` when present; fall back to the shared `index_of` shape otherwise.

### [MED] performance — `build_reverse_index` rebuilt 3× per overlay pass; a driver instance per binding

- `configsys/orphans.py:271` (`install_overlay`) builds it, then calls `scan_orphans` which builds it again at `:202`, and the TUI's instant path `installed_overlay` (`:252`) builds it a third time (`tui/menu.py:2602`). Each build walks every component × valid binding and calls `get_driver` (`:69`), which instantiates a new driver object per binding (`drivers/__init__.py:94-97`).
- Pure CPU, but it runs on the `O` keypress and on every membership edit that re-classifies.

Recommendation: build once per routes generation and pass it (or cache on `ctx`, keyed by `id(ctx.routes)`); memoize `get_driver` per name inside the walk like `scan_orphans._drv` does.

### [MED] reuse — three version-comparison idioms + duplicated memo closures across the floor subsystem

- `configsys/versionreport.py:120-139` (`_pv/_ge/_lt/_max_version`), `configsys/versionsweep.py:20-27` (`meets` over `osversion._CMP`), `configsys/flooradvise.py:94-95` (`re.search(r'[0-9][0-9.]*', …)` to pull the literal out of `>=9.4` — ignores the operator, so a `provides: { x: "<12" }` is read as "provides 12").
- `versionsweep.sweep_ctx.rep()` (`:96-102`) and `flooradvise._unmet.rep()` (`:49-55`) are identical; `sweep_ctx.best_version` (`:104-111`) re-implements `versionreport._max_version`.
- `versionsweep.collect_requirement_floors(components, drivers=None)` (`:30-41`) accepts `drivers` and never uses it (docstring admits).

Recommendation: one `osversion.compare/meets` (constraint-aware, via `parse_constraint`), `versionreport.max_version` public, and a `versionreport.Reports(ctx)` memo object shared by sweep/advise/TUI.

### [MED] security/robustness — the runner's shell-string contract has no enforcement, and `env=` is dropped under sudo

- `configsys/runner.py:432`: `argv = ['sudo', 'bash', '-c', cmd]` — every driver builds `cmd` by f-string. In the in-scope reads, apt quotes all route-supplied fields (`drivers/apt.py:88,101,108,148-161,292,303,325`), and `driver._fetch_and_extract` quotes URL/dest (`driver.py:150-153`). 3 drivers import no `shlex` at all (`drivers/clang.py`, `gcc.py`, `script.py` — script is by design). Route data comes from synced plugin layers (`plugins.py:250`, data files load per content trust), so one missed quote in any driver = arbitrary root shell from a data file.
- `runner.py:471-472`: `env=env` is handed to `subprocess.run` — but for `sudo=True` the child is `sudo`, whose default `env_reset` strips it, so a driver's build env silently doesn't reach a privileged command. No caller guard, no comment.
- `Runner.calls` (`:374,423`) appends every command string for the life of the process — unbounded in a long TUI session (thousands of probe commands).

Recommendation: add `Runner.run_argv(list, …)` and migrate mutating ops toward argv (keeping `run(str)` for compound shell); document/handle `env` under sudo (`sudo env K=V …` or `-E` opt-in); cap `calls` (deque) or make recording opt-in for tests.

### [MED] ABI drift — batch/enumeration hooks are load-bearing but absent from the documented Driver ABI

- `configsys/driver.py:15-26` lists the frozen surface (get_version/get_latest/is_locked/…); the hooks the core now depends on — `_batch` (set externally at `installState.py:195`), `batch_index`, `batch_installed_index`, `explicit_keys`, `origin_index`, `native_backed`, `version_advisory` (read via `getattr` in `versionreport.py:168`) — are defined at `driver.py:46-51,213-255` but not in that list. A plugin driver that overrides `get_version` has no documented reason to consult `_batch`, and `installState.inspect` will happily set it.

Recommendation: promote the optional hooks into the ABI docstring (with "optional; default None"), and turn `_batch` into a documented `batch` attribute or pass it as an argument (`get_version(rc, batch=None)`) at the next ABI bump.

### [LOW] bug — `inspect()` progress cannot reach `total` when `reuse` is non-empty

- `configsys/installState.py:122` sets `total = len(units)`; `:134-138` and `:145-149` count `i` over `to_do` only. With a partial requery (pin change / post-execute), the last callback is `(len(to_do), len(units))` — a bar that stalls below 100%. `to_probe` (`:112`) and `to_do` (`:132`) are also the same computation done twice.

### [LOW] dead code / unused parameters

- `configsys/runner.py:408-415` `Runner.sudo_session` — zero callers (it is the only exception-safe way to guarantee `end_sudo`; `app.py:737` and `tui/menu.py:574` call `end_sudo` after the loop, so an exception mid-batch leaves the `_SudoKeepalive` daemon refreshing sudo until exit).
- `configsys/runner.py:418-421,458-459` `presudo` parameter — no caller passes `presudo=True` (grep: only the docstring mentions it; memory notes presudo was retired).
- `configsys/reportgen.py:77-80` `load_failure` — zero callers; `save_failure` (`:49-51`) has one (the TUI bug above).
- `configsys/flooradvise.py:194-201` `resident_upgrades` (states variant) — only test/test_flooradvise.py calls it; production uses `resident_upgrades_probed` (`app.py:657`).
- `configsys/osversion.py:90-124` `split_qualifier`, `satisfies`, `specificity` — zero source callers (only test/test_osversion.py); `routes.hu` has no `@`-qualified block keys.
- `configsys/versionsweep.py:30` `drivers` parameter unused.
- `configsys/installState.py:57-59` `ComponentState.key` — no `state.key`/`st.key` reader found in configsys/ (verify with a broader grep before removing).
- `configsys/reportgen.py:22` `_MARKER` "reserved for later auto-labeling" — emitted, never consumed.

### [LOW] comment/doc drift

- `docs/startup-perf-plan.md:3` "fixes NOT built (awaiting go-ahead)" — Phases A/B/C are all present (`installState.py:108-149` batch prepass + thread pool; flatpak batch `drivers/flatpak.py:125-172`).
- `configsys/paths.py:10` "CONFIGSYS_CONFIG … (default: <home>/configsys.hu)" vs code `:85` `state_dir / 'configsys.hu'` (legacy path is `:86`); `paths.py:15` cites `dotfiles/bash.d/00-configsys.sh` — `dotfiles/` contains only `gdbinit`; shell glue moved to `glue/shell`.
- `configsys/osversion.py:1-18` module docstring documents `"ubuntu@<23.04"` block-key qualifiers — the current model is versioned `when:` atoms; only `parse_version/parse_loose/clean_version/parse_constraint/_CMP` are live.
- `configsys/installState.py:5-6` "Unsupported drivers (not yet implemented in M1)" — stale milestone reference.
- `configsys/app.py:233-234` "adds no cost until the version-floors data exists" — floors exist in routes.hu (see MED above).
- `configsys/versionreport.py:154` and `reportgen.py:162,366` pass `r.candidate_only` (`routes.py:266`) — the retired `candidate-only` name survives as an attribute while CLAUDE.md says `standing` replaced it; rename for consistency.
- `docs/managed-orphans-plan.md:14-50,273-277` still specifies an `excluded` kind and `Config.profile_removed_closure`; `configsys/orphans.py:32` `KINDS = ('lurking','forgotten','foreign')` — with `~`-profiles retired by the matrix model the kind is gone; the doc's ladder and Caveats are stale. `docs:293` "Still TODO: a `check` stale-ignore warning" — status unverified in this scope, leave flagged.
- `configsys/floorderive.py:10` "Pure given an injected fetch" — `built_ref` (`:50-64`, the default `ref_of`) calls `versions.discover(spec, paths)` with the real `http_fetch`; pure only when `ref_of` is injected.

### [LOW] naming — apt `is_locked` keys on `rc.name`, the other read ops on `_probe_name`

- `configsys/drivers/apt.py:336-340` vs `:301-303,323-325`. Consistent with "hold applies to the install name", but `rc.name` may be a whitespace-separated set (`_pkgs` docstring `:346-349`), in which case `rc.name in held` is never true. Not in scope files but reached through `installState.inspect_one`.

### [LOW] security hygiene — `paths.install_dir` does not normalise `..`; `expand` mis-handles `~user`

- `configsys/paths.py:184-192`: a route `installDir: apps/../../x` resolves to `<scope base>/apps/../../x` — escapes the scope base (the tarball/source drivers extract there with `rm -f`/`mkdir -p`). `expand` (`:141-154`) treats `~user/x` as bare-relative → `<home>/~user/x`.
- `_DIR_VARS` (`:30-34`) duplicates the app/sdk/src rows of `CONFIG_DIR_KEYS` (`:40-46`) — two tables to keep in sync.

Recommendation: `Path(...).resolve()`-free normalisation (`os.path.normpath`) + reject results outside the scope base for bare-relative inputs; derive `_DIR_VARS` from `CONFIG_DIR_KEYS`.

### [LOW] performance — `versionreport._LatestCache` and `versions.VersionCache` are the same class twice, with the same per-call IO

- `configsys/versionreport.py:52-90` is a near-copy of `versions.py:282-329` (load/save/get/set with `fetched` float parsing). `report()` loads at `:159` and saves at `:175` on every call; `sweep_ctx` and `flooradvise` call `report()` per provider. Cache key is `rc.key` (`driver\comp`, `:99,104`), so two same-`via` bindings of one component (versioned `when:` alternatives, different `name:`) share one slot.

Recommendation: one generic TTL-record cache class in `troveio`/a new `cachefile.py`, keyed explicitly, loaded once per process (fixes the HIGH too).

### [LOW] test gaps

- No concurrency test for `versions.discover` / `_LatestCache` (HIGH above).
- `installState.inspect(reuse=, dirty=)` has no direct unit test in test/test_installstate.py (only test/test_tui_pin.py:297 exercises it); progress `(i, total)` semantics untested.
- `detect_coexisting` duplicate-enumeration / `superseded_installs` probe count untested (test/test_coexistence.py has 5 behavioural tests, no call-count assertions).
- `rebootcheck`: apk heuristic (`:113-119`) and the `needrestart -b` path (`:141-145`) untested; `_service_tokens` untested.
- `osdetect.refine`: one positive test; no test for base-mismatch skip (`:118-119`), multi-marker all-must-exist, or forced-OS bypass (`:109-110`).
- `paths.install_dir` traversal / `~user`; `Paths._locate_data_root` wheel fallback is tested.
- `reportgen.coverage` (`:375-405`) only via `render_request` fixtures; `_route` error branches untested.
- `failures.classify` ordering bug above has no failing test (test/test_failures.py, 90 lines).
- `report.Reporter.status/flush_transient` tty vs non-tty (test_report.py is 48 lines).

### [LOW] `osdetect.refine` returns the first matching `detect:` block in dict order

- `configsys/osdetect.py:111-122`: with two detectable derivatives of the same base (e.g. two Debian rebrands each with markers present) the winner is insertion order, not specificity/descendant depth. Deterministic but undocumented; consider preferring the deepest `is_descendant` chain or erroring on multiple matches.

### [NIT] misc

- `configsys/installState.py:15-35` `_parallel_map` is defined ABOVE the module imports (`:37-39`) — move under imports; it is also imported by `orphans.py:270` from `installState`, an odd home (a `concurrency.py` helper).
- `configsys/runner.py:263` `os.write(sys.stdout.fileno(), data)` — partial writes unchecked; `:300` tail deque sized `limit // 80` LINES approximates bytes (a `\r`-progress child can retain far more than `tee_limit`).
- `configsys/reportgen.py:140-147` `_os_pretty` hand-parses `/etc/os-release` — reuse `osdetect._parse_os_release`; `collect()` `:185-199` vs `:201-220` duplicate the os/platform/configsys/machine/pins block.
- `configsys/refreshstate.py:21-37` stores stale-pins as JSON while sibling state files are `.hu` (`versions.hu`, `method-versions.hu`) and `startup-timing.json` — pick one (`startuptiming` also JSON; fine to standardise on JSON for machine-only state, but say so in paths.py).
- `configsys/splashes.py:74-84` `register_splash` silently overwrites an existing name (last wins); `plugins.py:1032` detects conflicts separately from manifests — a runtime warning here would catch dynamic registrations.
- `configsys/rebootcheck.py:108` `pacman -Q linux linux-lts linux-zen linux-hardened` exits non-zero when any is absent; the code correctly reads `stdout` regardless — add a comment so nobody "fixes" it to check `.ok`.
- `configsys/versions.py:58-83` `source_key` special-cases `github`/`pypi` then loops `_BUILTIN_KINDS` (which also contains neither `github` nor `pypi`) — fine, but `github` is missing from the `_BUILTIN_KINDS` tuple the docstring at `:64` claims lists "github/crates/…".

## Feature status notes (lens 11)

- **Managed orphans**: BUILT (scan, tiers, explicit filter, adopt/remove/ignore, TUI overlay `installed_overlay`/`install_overlay` at `orphans.py:246-317`, `tui/menu.py:2602`). Divergence from the plan: the `excluded` kind and `profile_removed_closure` are absent (obsolete under the picks/matrix model); the synthetic `foreign` node is intentionally not built; `check` stale-ignore warning is listed TODO in the doc.
- **Versioned requires**: fully shipped as the doc says; the "no cost until floors exist" assumption no longer holds (floors are in routes.hu), which is what turns the `diagnostics()` re-probe into a real cost.
- **Startup perf**: all phases built; the plan doc's status line is stale.
- **Method-versions cache in `inspect`** (Phase B of the perf plan): `inspect_one` still calls `drv.get_latest(rc)` directly (`installState.py:198`) and never consults `method-versions.hu`; flatpak's `remote-ls` batch made it moot for flatpak, but tarball/appImage/source `get_latest` goes through `versions.hu` (the HIGH above) rather than the per-method cache — two caches for one concept.

## Counts

HIGH 1 · MED 9 · LOW 8 · NIT 1 (grouped, 7 items)
