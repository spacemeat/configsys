# Review: Subsystems: state, versions, runner, OS detection, reports

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: configsys/{flooradvise, floorderive, installState, orphans, osdetect, osversion, paths,
probecache, rebootcheck, refreshstate, report, reportgen, runner, splashes, startuptiming,
versionreport, versions, versionsweep}.py.
Context read: docs/versioned-requires.md, docs/orphans.md, docs/principles.md, resolve.py,
app.py (Context/load_pipeline/diagnostics/run callers), actions.run_plan, tui/menu.py execute path,
sysupdates.py, detection.py, drivers/{apt,dnf,brew,tarball}.py, driver.py ABI docstring.
Tests read: test/test_{runner,reportgen,rebootcheck,probecache,osdetect,detect_marker,osversion,
paths,report,refreshstate,versionsweep,versionreport,flooradvise,floorderive,orphans,coexistence,
installstate,versions,splashes}.py.

**Verification (2026-11-08, checker):** 6 findings checked (every HIGH, plus every MED+ security/safety finding: 01, 05, 08, 02, 03, 04). All 6 were CONFIRMED by reproduction. subsystems-04 was raised MED → HIGH: the version-`url` fetch also carries the user's GitHub token. subsystems-08 was lowered HIGH → MED: measured, it is a cache costing ≤0.3 s with no in-process data loss. Each finding's `**Verified:**` line has the evidence. Scripts are under the review scratchpad's `scratch/verify-subsystems/v2/`, and every mutating run used `--pretend` or a never-executing runner.

## Carried over from docs/review-2026-09/subsystems.md (+ README open items)

| earlier finding | status | evidence |
| --- | --- | --- |
| HIGH `versions.py` cache per-call load + lost updates under the thread pool (B9) | **open** (partial) | B9's `_CACHE_LOCK`/`_persist` (4553619) stopped lost *writes*, but the per-call `VersionCache.load` is UNLOCKED and `save()` uses non-atomic `write_text`, so a concurrent reader still sees a torn file → spurious miss. Re-reported as **subsystems-08**. |
| MED `detect_coexisting` re-enumerates with a thundering herd | **fixed** | now routes through the shared `probecache.of(ctx)` (13d5d22); the detection tier pre-warms every driver's `installed_index` before `detect_coexisting` runs, so it hits a warm cache. |
| MED `diagnostics()` re-runs `versionreport.report` live subprocesses per TUI rebuild | **fixed** | `report()` now reads installed versions from `probecache` and latest from `_LatestCache`; measured 2 spawns on the first `diagnostics(states)` and 0 reused work after (see subsystems-09 for the residual per-call file IO). |
| MED TUI batch persists only the LAST failure | **fixed** | CLI + TUI share `actions.run_plan` → `reportgen.record_run` persists every failure (cc7bbe9, D3/B10). |
| MED `failures.py` rule order misclassifies "target not found" as a dead URL | **fixed** | the `command not found` / DEPENDENCY rule now precedes the 404 rule and `Not Found` is matched case-sensitively `(?-i:Not Found)` (3d5bb6b). |
| MED `superseded_installs`/`plan_with_swaps` probe per binding, serially | **open** | still `drv.get_version(rc)` per candidate with no `installed_index`/`also_present` reuse; re-reported as **subsystems-11** (now with a measured brew cost). |
| MED three version-comparison idioms + duplicated memo closures | **open** | `versionreport._ge/_lt/_max_version`, `versionsweep.meets`, `flooradvise` regex; `_unmet.rep()` == `sweep_ctx.rep()`. Re-reported as **subsystems-12**. |
| ABI drift — batch/enumeration hooks absent from the Driver ABI docstring | **fixed** | driver.py now lists `batch_index`/`installed_index`/`explicit_keys`/`origin_index`/… and the `batch` attribute under "Optional hooks" (da0a7ac). |
| LOW `paths.py` header names a default/file that no longer exist | **fixed** | header now says `<state dir>/configsys.hu`; no `dotfiles/bash.d` reference. |
| LOW apt `is_locked` keys on `rc.name` not `_probe_name` | **fixed** | `is_locked` now uses `self._pkg_list(rc)` (apt.py:420-425). |
| LOW `paths.install_dir` does not normalise `..` | **open** | still true, and shown to defeat the tarball rm guard — re-reported concretely as **subsystems-02**. |
| LOW `osversion.py` docstring documents the retired `@`-qualifier model | **open** | subsystems-14. |
| LOW `installState.py` "not yet implemented in M1" | **open** | subsystems-15. |
| LOW dead code: `save_failure`/`load_failure`, `resident_upgrades`(states), `osversion.split_qualifier/satisfies/specificity`, `versionsweep` `drivers=` param, `reportgen._MARKER` | **open** | all re-confirmed dead; subsystems-16. |
| LOW `inspect()` progress can't reach `total` when `reuse` is non-empty | **open** (minor) | `total=len(units)`, `i` counts `to_do` only; subsystems-17. |
| NIT `refreshstate` JSON vs sibling `.hu`; `splashes.register_splash` silently overwrites | **open** | subsystems-17. |

## Cross-cutting themes

- **The version/floor subsystem assumes every constraint and version parses.** `versionsweep.meets`
  calls `osversion._CMP[op](pv, target)` without checking `target is not None`, so one unparseable
  constraint literal anywhere in the merged config raises `TypeError` out of resolution
  (subsystems-05). The same "parse-or-abstain" discipline that `_ge/_lt` already use is missing in
  the one function the resolver depends on.
- **Two bespoke TTL cache files, each parsed per call, under a thread pool they weren't written
  for.** `versions.VersionCache` and `versionreport._LatestCache` are near-identical classes that
  `load()` + `save()` the whole file every call. Concurrency (versions.hu) and per-call parse cost
  (both) follow (subsystems-08, -09). The 2026-09 recommendation — one process-lifetime cache,
  loaded once — still stands and would fix all three.
- **The runner's streamed-op fallback re-executes the command.** Any exception from
  `_run_captured_tty` (a non-UTF-8 byte in the child's output is enough) is swallowed as "degrade to
  plain streaming" and the whole command runs a second time (subsystems-01). This is the single most
  serious finding in the area.
- **A filed issue trusts a narrow secret-shape list.** The scrubber masks `ghp_`/AWS/Slack token
  shapes and labelled `token=`/`password:` pairs, but not URL-embedded credentials or GitLab/other
  PAT prefixes that routinely appear verbatim in git/curl command output (subsystems-03).
- **(added on verification) A plugin-controlled URL is handed the user's credential.** `http_fetch`
  attaches `CONFIGSYS_GITHUB_TOKEN`/`GITHUB_TOKEN` to any url that merely *contains*
  `api.github.com`, and a data-only plugin's `version: { url: }` is fetched at every inspect. So an
  untrusted plugin receives the token with no install and no prompt (subsystems-04, raised to HIGH).

## Findings

### subsystems-01 [HIGH] safety — a streamed sudo/warm-batch op runs TWICE when the child emits a non-UTF-8 byte
`configsys/runner.py:482-514` (`Runner.run`), `:310-336` (`_run_captured_tty`). For a top-level
`sudo=True` streamed op, or any streamed op in a batch holding a warm sudo credential, `run` calls
`_run_captured_tty`, which does `subprocess.Popen(argv, …, text=True, bufsize=1)` and iterates
`for line in proc.stdout`. `text=True` decodes as UTF-8; a single non-UTF-8 byte (latin-1 progress
output, a filename in a non-UTF-8 locale, binary noise) raises `UnicodeDecodeError` mid-stream. That
propagates out of `_run_captured_tty` into the `except Exception: pass` "degrade to plain streaming"
guard at `runner.py:493`/`:505`, so control falls through to the final `subprocess.run(argv, …)`
(`:521`) — which **re-runs the entire command**. For `apt-get install` that is wasteful; for a
`via: script`/`via: source` build, a `curl … | sudo bash` installer, or `makepkg`, it double-applies
a non-idempotent op (the common case, since `run_plan` keeps every op of a root batch on this path).
**(reproduced)** scratch `runner_rerun.py` with `_can_tee=True`, `_sudo_warm=True`, a command that
appends a line to a counter file then prints a `\xff` byte →
`returncode 0 | times the command ran: 2`.
**Fix:** read the pipe as bytes and decode with `errors='replace'` (like `_run_teed` already does at
runner.py:304), or capture `stdout` as bytes; and never let the `except` fall through to a re-run
once the child has started — only fall back to plain streaming on a *pre-exec* failure.
**Effort:** S. **Tier:** A.
**Verified:** CONFIRMED (reproduced). HIGH stands, and the bug is worse than reported. `scratch/verify-subsystems/v2/rerun01.py` drives the real `Runner.run(capture=False)` with `runner._can_tee` patched True (what a terminal gives) and `_sudo_warm=True` set directly (no `begin_sudo`, no real sudo; the `sudo=True` variant runs a PATH stub, asserted with `shutil.which` first). The command appends `start` to a counter, prints, then appends `done`. UTF-8 control → `STARTED: 1 | FINISHED: 1`. `\xff` at the end → `returncode 0 | STARTED: 2 | FINISHED: 2`. `\xff` early in a 1 s op → `STARTED: 2 | FINISHED: 1 | run() took 1.01s`: the decode error closes the pipe but never kills or reaps the child, so the fallback `subprocess.run` runs alongside the still-running first instance. That first instance then dies of SIGPIPE on its next write, half-applied (for apt, an interrupted dpkg while a second apt-get waits for the lock). The `sudo=True` path behaves the same. The returned rc is the re-run's, so the user sees `ok`. On a real terminal, every streamed op of a batch with root work takes this path (`actions.run_plan:214` → `begin_sudo`; there are 118 `capture=False` call sites in drivers/). `test_runner.py` has no decode-error test.

### subsystems-05 [HIGH] correctness — a malformed version constraint anywhere in the merged config crashes inspect / check / where (not a clean load error)
`configsys/versionsweep.py:20-27` (`meets`), `configsys/osversion.py:24-30` (`_CMP`). `meets` builds
`parse_constraint(constraint)` then evaluates `osversion._CMP[op](pv, target)`. `parse_constraint`
returns clauses with `target=None` for any operand `parse_version` can't read (e.g. `">=v3.11"` — a
leading `v`, which `parse_version` does not strip — or `"~1.21"`, or a typo). `_CMP['>=']` is a bare
`a >= b`, so `tuple >= None` raises `TypeError`. `meets` is called from `resolve._satisfy_constrained`
(every versioned `requires:`) and from `flooradvise`, so one bad literal in *any* layer (even a
component this machine doesn't pick, as long as the component defines a versioned `requires:`) takes
down resolution. `check` is supposed to lint the config, not abort on it.
**(reproduced)** a sandbox config with `foo: { requires: [ { python3: ">=v3.11" } ] … }` →
`configsys --os ubuntu:24.04 --pretend check` exits non-zero with
`TypeError: '>=' not supported between instances of 'tuple' and 'NoneType'` (full traceback, not a
`check` warning). `inspect` tracebacks the same way when `foo` is picked.
**Fix:** `meets` should treat a `None` target like any other unparseable input — return `False`
(abstain) — i.e. `if pv is None or not clauses or any(t is None for _op, t in clauses): return
False`; and `parse_loose`/`parse_version` should strip a leading `v`/`V` in constraint operands so
`">=v3.11"` parses. Add a `routecheck` lint that reports a malformed constraint as an
`unsatisfiable-constraint`-style warning.
**Effort:** S. **Tier:** B.
**Verified:** CONFIRMED (reproduced). HIGH stands. Sandbox `home-05-unpicked` (`zz-floor` requires `python3: ">=v3.11"`, not picked): `configsys --home … --pretend --os ubuntu:24.04 check` → exit 1 via `cmd_check:2445 → routecheck.validate:341 → _unsatisfiable:178 → versionsweep.meets:27 → TypeError: '>=' not supported between instances of 'tuple' and 'NoneType'`. `where zz-floor` fails the same way. With `zz-floor` picked (`home-05-picked`), `inspect` exits 1 via `load_pipeline:472 → resolve_resilient → _satisfy_constrained:919 → meets`. The TUI's loader catches the exception and re-raises it on the main thread (`tui/menu.py:2297-2302`), so the TUI is bricked too. Nothing validates the literal at load (`resolve.cap_constraints` just `str()`s it). One correction: only an ORDERING operator with an unparseable operand raises (`>=v3.11`, `>=1.0,<v2`). `~1.21`, `^1.2`, `!=1.0` and `latest` fall back to `=` (`tuple == None`) and quietly return False.

### subsystems-04 [HIGH] security — a `version: { url: … }` / `file://` spec from an untrusted data plugin fetches at inspect time (and is sent the user's GitHub token)
`configsys/versions.py:379-388` (`_discover_live` url branch), `:62-90` (`http_fetch`). A plugin's
`version: { url: "…" regex: … }` is **data**, so a data-only plugin syncs and loads with no trust
prompt, yet its url is fetched by `urllib.request.urlopen` during `get_latest` on the "read-only"
inspect sweep — an outbound request to a plugin-controlled host (a beacon / deanonymizer that fires at
every refresh with zero user action), and `urlopen` also honors `file://`, so `version: { url:
"file:///home/<user>/.ssh/id_rsa" regex: "..." }` reads a local file into the version string.
This is the same "command-carrying data" class the 2026-09 A1 gated for `script`/`source`/apt
`source-line`/glue/`facets: detect:` (docs/principles.md "data not script is not a security
boundary"), but the version-`url` fetch was not included in that gate.
**(reproduced)** `versions.discover({'url': 'file:///etc/os-release', 'regex':
'VERSION_ID="?([0-9.]+)'}, None)` → `'22.04'` — a local file read, no trust gate. (What an attacker
could already do: a trusted code plugin can run anything; a data plugin that also ships
`script`/glue is already trust-gated. The gap is specifically the untrusted data-only plugin whose
only "executable" surface is a version-`url`.)
**Fix:** restrict the url backend to `http(s)://` (reject `file://`/other schemes), and either gate a
plugin that ships a `version: { url: }` (an arbitrary host, unlike github/pypi/crates) under
`command_source_trusted`, or surface it in `plugin list`/`check`. **Effort:** M. **Tier:** A.
**Verified:** CONFIRMED (reproduced). Severity raised from MED to HIGH. (a) `versions.discover({'url': 'file:///etc/os-release', 'regex': 'VERSION_ID="?([0-9.]+)'}, None)` → `'22.04'`. (b) `e2e04.py`, sandbox `home-04`: a data-only plugin placed on disk (`plugin list` → `ok`, no trust) defines `zz-beacon` with `version: { url: "http://127.0.0.1:<port>/api.github.com/zz-beacon" }`. It also adds a `when: "ubuntu"` tarball binding to the CORE `btop`, with url `http://127.0.0.1:<port>/beacon?host=api.github.com&who=btop`. The run was a plain non-pretend `configsys inspect`, with `Runner.run` replaced by a recorder that never executes, `urlopen` limited to localhost/`file://`, and a dummy `GITHUB_TOKEN`. It shows `tarball\btop … 7.7.7` (the core pick moved onto the plugin's binding). The local server logged `GET /api.github.com/zz-beacon Authorization='Bearer dummy-review-token-0000'` and `GET /beacon?host=api.github.com&who=btop Authorization='Bearer dummy-review-token-0000'`. The finding missed the cause: `http_fetch` attaches `CONFIGSYS_GITHUB_TOKEN`/`GITHUB_TOKEN` whenever `'api.github.com' in url` (versions.py:71). That is a substring test over a plugin-controlled url, so a path, a query string, an `api.github.com.<evil>` host or plain http all match. README:479 and docs/config-format.md:707/1170 tell users to set that token. So an untrusted data-only plugin gets a GitHub credential at every inspect or TUI start, with no install and no prompt. That token is often repo-scoped, which means push access to the user's primary plugin. Fix this first: send the token only when `urlparse(url)` is `https` with hostname `api.github.com`. Then restrict `url:` specs to http(s) and settle the beacon/trust question above.

### subsystems-02 [MED] safety — a tarball `installDir: ../…` escapes the scope-base rm guard
`configsys/drivers/tarball.py:38-54` (`_safe_install_dir`), `configsys/paths.py:206-214`
(`install_dir`). The guard refuses an install dir that `== dp.parent`, is in `_SHARED_SYSTEM_DIRS`, or
equals a scope base — but it compares the raw joined path without `os.path.normpath`, so a
bare-relative `installDir:` containing `..` is neither normalized nor contained. `paths.install_dir`
joins `scope_base / "../home4"` and the guard passes it, so install/uninstall `rm -rf`s a path OUTSIDE
the scope base.
**(reproduced)** a sandbox tarball component with `installDir: "../home4"` under
`--home …/home4` → `--pretend install` prints
`… && rm -rf <SB>/home4/../home4 && mv <SB>/home4/../home4.configsys-stage <SB>/home4/../home4` — the
guard did not fire (no "refusing to (un)install" line). With a deeper `../../..` an attacker-authored
or careless route reaches arbitrary dirs; it is route data, which a data-only plugin ships untrusted.
**Fix:** `os.path.normpath` the resolved dir in `paths.install_dir` (and/or in the guard) and reject
any bare-relative input whose normalized form escapes the scope base; keep the existing
shared-dir/parent checks on the normalized path.
**Effort:** S. **Tier:** A.
**Verified:** CONFIRMED (reproduced). MED stands. Sandbox `scratch/verify-subsystems/home` (the user scope base is the home itself, paths.py:43): `configsys --home <S>/home --pretend --os ubuntu:24.04 install --no-deps …`. A binding with no `installDir` is refused (`refusing to (un)install into <S>/home`). `installDir: "../home"` prints `rm -rf <S>/home/../home && mv <S>/home/../home.configsys-stage <S>/home/../home` (= `rm -rf $HOME`) with no refusal. `scope: system` + `installDir: "../usr"` prints `sudo … rm -rf /opt/../usr && mv /opt/../usr.configsys-stage /opt/../usr` (= `sudo rm -rf /usr`). The sandbox's file list was unchanged. `check` lints only the missing-`installDir` case (routecheck.py:324). pathlib keeps `..` (`Path('/opt/../usr') == Path('/usr')` → False). Nuance: GNU rm refuses a path that ENDS in `..` (exit 1, so the `&&` chain stops), which means `../../..` doesn't reach `/`; a `..` followed by a name does. Severity is unchanged: it reaches exactly the dirs the guard exists for, but it needs route data containing `..` (a hostile plugin, or an unlikely slip). For a hostile plugin, security-02 (2) already shows unlisted dirs such as `/usr/bin` and `~/.local/bin` are accepted outright. One containment check should fix both.

### subsystems-03 [MED] security — the report scrubber misses URL-embedded credentials and non-GitHub token prefixes
`configsys/reportgen.py:25-34, 125-135` (`_SECRET_PATTERNS`, `_LABELED`, `scrub`). A filed
`report`/`request` body carries each failure's `command` and driver `output`. The scrubber masks
`ghp_`/`github_pat_`/Slack/AWS shapes and `token=`/`password:` *labelled* pairs, but not:
`https://user:password@host` basic-auth userinfo (common in `git clone`/`curl`/pip `--index-url`
output), GitLab `glpat-…` / `glpat` deploy tokens, generic `sk-…`/`glpat-…` PATs, or a raw bearer
JWT that appears without an `Authorization` label. The FOCUS for this area is exactly "what a filed
issue can leak (tokens)".
**(reproduced)** `reportgen.scrub(...)` on representative lines:
`git clone https://oauth2:glpat-AbCdEf0123456789xyz@gitlab.com/me/p.git` → **unchanged**;
`pip install --index-url https://alice:s3cr3tpw@pypi.corp.example/simple foo` → **unchanged**;
`export NPM_TOKEN=npm_AbCdEf…` → **unchanged**. (The `ghp_` and `Authorization: Bearer` cases are
masked.)
**Fix:** add a URL-userinfo rule (`://[^/\s:@]+:[^/\s@]+@` → `://***:***@`) and the common PAT
prefixes (`glpat-`, `github_pat_` already present, `sk-`, `npm_`, `xox…` present) to
`_SECRET_PATTERNS`; the user still reviews, but the obvious cases shouldn't ride through.
**Effort:** S. **Tier:** A.
**Verified:** CONFIRMED (reproduced). MED stands, with one correction and two mitigations. `scrub03.py` runs `reportgen.scrub(text, '/home/u', secrets)`. With no secret env vars, these come back UNCHANGED: the `oauth2:glpat-…@gitlab.com` clone, the `alice:s3cr3tpw@` index url, `https://deploy:hunter2hunter2@files…`, `export NPM_TOKEN=npm_…`, `DB_PASSWORD=hunter2`, `AWS_SECRET_ACCESS_KEY=…`, `--password hunter2`, `curl -u alice:s3cr3t`, a bare JWT. Correction: `Authorization: Bearer eyJ…` is NOT masked. `_LABELED` masks only the next token, the word `Bearer`, giving `Authorization: *** eyJhbGciOiJIUzI1NiJ9…` with the JWT intact. First mitigation: every caller passes `secret_values(ctx.env)` (app.py:3346/3384/3416, tui/menu.py:1464), so a token that is also an exported secret-named env var is masked. With `NPM_TOKEN`/`GITLAB_TOKEN` exported, the glpat and NPM_TOKEN lines come out masked, so the real gap is credentials kept in URLs, config files and recipes. Second mitigation: the body is shown and y/N-confirmed before `gh issue create` posts it to the public `spacemeat/configsys-issues` (unless `--yes`).

### subsystems-06 [MED] correctness — the multi-kernel reboot heuristic false-positives on a non-booted newer kernel series
`configsys/rebootcheck.py:107-142` (`_kernel_heuristic`). On pacman/apk/xbps the check compares the
running `uname -r` against the MAX installed kernel version across ALL kernel packages
(`linux`/`linux-lts`/`linux-zen`/…). A box booted on `linux-lts` with a newer non-default `linux`
also installed (or an Alpine box on `linux-lts` with `linux-edge` present) reads "a newer kernel is
installed" **permanently** — a reboot won't clear it, because the user boots the LTS series on
purpose. docs/principles.md warns that a safety advisory people calibrate on must not cry wolf.
**(reproduced)** scratch `reboot_fp.py` with `uname -r = 6.6.30-1-lts` and `pacman -Q` reporting
`linux 6.12.1.arch1-1` + `linux-lts 6.6.30-1` → `(True, 'a newer kernel is installed (6.12.1.arch1-1)
than the running one (6.6.30)')`. (The same-series upgrade case correctly returns `(False, '')`.)
**Fix:** compare the running kernel only against the package of the series it was booted from
(derive the flavor suffix from `uname -r`, e.g. `-lts`/`-zen`, and pick the matching package), or at
least require the newer kernel to share the running flavor.
**Effort:** M. **Tier:** B.

### subsystems-07 [MED] correctness — two bindings of the same `via:` with different package names share one version-cache slot, so `versions` shows one method twice
`configsys/versionreport.py:99-107, 162-186` (`_LatestCache` keyed by `rc.key`),
`configsys/versions.py:118-135` (`source_key`). `_LatestCache` and the per-method report key on
`rc.key` = `driver\comp`, which is identical for two `via: native` bindings of one component that
resolve to the SAME driver with DIFFERENT package `name:` (p7zip's `p7zip-full` vs `7zip`; several
cpp-toolchain/libstdc++ bindings — 7 components on Ubuntu, 4 on Fedora/Debian). The report then lists
the method twice with one method's `latest`/`installed` under both.
**(reproduced)** `configsys versions p7zip` on this box prints two `native (apt)` rows both reading
`16.02+dfsg-8`, though `apt-cache policy` shows `p7zip-full` candidate `16.02+dfsg-8` and `7zip`
candidate `21.07+dfsg-4`. Dup scan `dup_via.py`: `ubuntu:24.04 → 7 components with >1 candidate
binding of one via`. Likewise `versions.source_key` collapses `{github: x}` and `{github: x,
strip-v: true}` to one `versions.hu` slot (7 repos ship a split-v and a non-split spec over one
repo — yazi/fzf/btop/neovim/…); the two differ only by a leading `v`, so it's cosmetic there, but
it is the same class of under-keyed cache.
**Fix:** key `_LatestCache` (and the report's method identity) by `(rc.key, rc.name)` or the binding
identity, not `rc.key`; the display-dedup should fold identical (via, package) pairs.
**Effort:** M. **Tier:** B.

### subsystems-11 [MED] performance — `plan_with_swaps`/`superseded_installs` probe every candidate serially (one `brew` spawn per formula) and reload the ledger per op
`configsys/installState.py:339-387` (`superseded_installs`), `:390-407` (`plan_with_swaps`, via
`stranded.find` which `Ledger.load`s). For each install/upgrade target, every non-target candidate
binding is probed with `drv.get_version(rc)` — no `installed_index`/`also_present`/`probecache`
reuse — and `superseded_installs` also calls `stranded.find` which `Ledger.load(ctx.paths)` (a full
state.hu parse) per target. On a brew machine each probe is a `brew list --versions <formula>`
(~0.7 s measured), serial.
**(reproduced)** scratch `swap_cost.py`, 17 install ops on this box →
`plan_with_swaps: 26 ms, 23 probe commands, Ledger.load x17` with `brew 15` of the 23 — i.e. 15
`brew list --versions <formula>` at ~0.7 s each ≈ 10 s of serial spawns before the first install
would run on a brew-default machine. `app.py:1868` loops it again for the pin heads-up.
**Fix:** pass `inspector.enum`/`states[*].also_present` into `superseded_installs` so an already-paid
enumeration answers; load the ledger once and pass it down; or `_parallel_map` the per-candidate
probes like `detect_coexisting` does.
**Effort:** M. **Tier:** C.

### subsystems-08 [MED] performance/correctness — versions.hu is parsed per unit and read torn under the inspect thread pool
`configsys/versions.py:444-476` (`_resolve`), `:479-511` (`_resolve_asset`), `:423-431`
(`VersionCache.save`). Every `discover()` (reached from `inspect_one` → `get_latest` for every
tarball/appImage/source/script/pipx unit, on an 8-thread pool — `installState.py:187`) does a full
`VersionCache.load(paths)` (a humon parse of the whole file). B9 (4553619) serialized the *write*
merge under `_CACHE_LOCK`, but the per-call `load` is **not** under that lock and `save` uses a
non-atomic `write_text`, so a reader thread can observe a truncated file mid-write; `load` swallows
the resulting `ConfigError` and returns an EMPTY cache → a spurious miss → a redundant network fetch
for that unit ("warm == cold" for a non-deterministic subset). `configsys refresh` does load+save per
spec over a file that grows with the catalog, so it is O(n²) file IO.
**(reproduced)** scratch `race_versions.py`: a 300-record cache, 1 writer + 4 reader threads for 3 s →
`loads=703 torn_reads(records<300)=189` (27% of reads saw a short/truncated parse). Warm-hit cost
`time_versions.py`: `100 records 2.25 ms/call · 300 records 7.11 ms · 600 records 15.51 ms` — the
per-unit parse scales with file size (routes.hu already has ~200 `version:` specs).
**Fix:** hold ONE `VersionCache` per `Paths`/process behind the existing lock: load lazily once,
mutate in memory, mark dirty, `save` once at the end of `inspect()`/`refresh`; and make `save` atomic
(write a temp + `os.replace`). Add a test that two `discover` calls for different keys concurrently
both survive AND that a reader never sees an empty cache while a write is in flight.
**Effort:** M. **Tier:** C.
**Verified:** CONFIRMED (reproduced). Severity lowered from HIGH to MED. By reading: the `load` in `_resolve`/`_resolve_asset` runs outside `_CACHE_LOCK`, `save` truncates in place, and a parse error maps to an empty cache. `torn08.py` runs the real `versions.discover` on an 8-thread pool, with `_discover_live` stubbed at 30 ms and a cache of mixed staleness. N=60 with 50% stale → 7 spurious refetches of FRESH keys in 5 trials (4.7% of fresh lookups). 10% stale → 5.6%. N=200 → 17.7%. No records were lost in-process. `xproc08.py`: two processes persisting 150 distinct keys each leave 5–9 of 300 records on disk (a cross-process torn read empties the cache, which then overwrites the file). Cost (`measure08.py`): a pretend inspect with all 129 discoverable-version components picked (224 units, ubuntu:24.04) does 60 loads. An uncontended load costs 0.99 ms at 60 records, 4.29 ms at 260 and 13.9 ms at 600, so 0.06–0.26 s of CPU per inspect at that upper-bound pick set. Memoizing `load` changed inspect wall time by about 0.2–0.3 s in noisy 2.2–2.6 s runs. It rates MED, not HIGH, for four reasons: it is a cache (no user data, and in-process writes are never lost), the redundant fetches hit the anonymous atom feeds, the overhead is ≤0.3 s, and the wipe needs two configsys processes writing at once. The proposed fix (load once, save atomically via temp + `os.replace`) is still right.

### subsystems-09 [MED] performance/reuse — `method-versions.hu` is loaded+saved per `report()` call, and is a second copy of the versions cache class
`configsys/versionreport.py:54-92` (`_LatestCache`), `:162, 187-188` (load at entry, save per call).
`report()` loads the whole `method-versions.hu` at `:162` and (unless pretend) `save()`s it at `:188`
on every call; `flooradvise._unmet` and `versionsweep.sweep_ctx` call `report()` per provider, so a
machine with several floored providers re-parses+rewrites the file once per provider. `_LatestCache`
is a near-verbatim copy of `versions.VersionCache` (load/save/get/set with `repr(float)` parsing).
**(reproduced)** `diag_cost.py` sandbox: `diagnostics()` calls `report()` 4× and each writes
`method-versions.hu` (`exists=True` after the first `diagnostics`); the reuse is only within one
`_unmet` run, not across the 4 providers. (Cheap in the sandbox — it matters on a box whose picks
floor several toolchains.)
**Fix:** one shared TTL-record cache class (a `cachefile.py` keyed explicitly), held once on `ctx`
per load generation and saved once; `flooradvise`/`sweep`/the TUI reuse one `Reports(ctx)` memo. This
is the same consolidation subsystems-08 wants for versions.hu.
**Effort:** M. **Tier:** C.

### subsystems-12 [MED] reuse — three version-compare idioms + duplicated memo closures across the floor subsystem
`configsys/versionreport.py:122-141` (`_pv/_ge/_lt/_max_version`), `configsys/versionsweep.py:20-27`
(`meets` over `osversion._CMP`), `configsys/flooradvise.py:96-110` (`_provides_meets` re-extracts the
literal out of `>=9.4` with `re.search(r'[0-9][0-9.]*', …)`, ignoring the operator). The two memo
closures `flooradvise._unmet.rep()` (`:64-70`) and `versionsweep.sweep_ctx.rep()` (`:96-102`) are
identical, and `sweep_ctx.best_version` re-implements `_max_version`. `versionreport._max_version`
is private but is the only "max across methods" helper.
Verified by reading the three sites. **Fix:** one constraint-aware `osversion.compare/meets` (via
`parse_constraint`), a public `versionreport.max_version`, and a shared `Reports(ctx)` memo object.
**Effort:** M. **Tier:** D.

### subsystems-13 [LOW] safety — the sudo keepalive thread leaks when a sudo op runs outside `run_plan`
`configsys/runner.py:406-448` (`_ensure_sudo`/`end_sudo`), `configsys/sysupdates.py:196-211`
(`apply_bulk`), `configsys/app.py:1506-1623` (`cmd_refresh`). The warm-sudo contract is "pre-auth
once, release at batch end" — but the only `end_sudo` in the normal flow is inside
`actions.run_plan`. The TUI System-Updates-ONLY apply path (`menu._confirm_and_execute` →
`sysupdates.apply_bulk` → `apt.upgrade_all` with `sudo=True`, when `plan` is empty so `run_plan` is
never reached) and `cmd_refresh`'s pacman full-upgrade both warm the credential (starting
`_SudoKeepalive`) and never call `end_sudo`, so the daemon keeps `sudo -n -v` alive every 50 s for the
rest of the TUI session.
**(reproduced)** scratch `keepalive_leak.py`: after a single `run('apt-get upgrade …', sudo=True,
capture=False)` → `warm = True | keepalive thread alive = True`,
`live threads: ['MainThread', 'Thread-1 (_loop)']`.
**Fix:** wrap these paths in `runner.sudo_session()` (which is otherwise dead — see subsystems-16),
or call `end_sudo()` after `apply_bulk`/the refresh upgrade. **Effort:** S. **Tier:** A.

### subsystems-10 [LOW] performance — `build_reverse_index` is rebuilt up to 3× per orphan pass and instantiates a driver per binding
`configsys/orphans.py:50-76` (`build_reverse_index`), called at `:203` (`scan_orphans`), `:253`
(`installed_overlay`) and `:272` (`install_overlay`) — the `install_overlay` path builds it once then
calls `scan_orphans` which builds it again. Each build walks every component × valid binding and
calls `get_driver` (a fresh instance per binding, `drivers/__init__.py:98-101`).
**(reproduced)** `time_revindex.py` on the real catalog (832 components):
`build_reverse_index: 42 ms, 1291 keys, get_driver calls=1222` — and it runs twice per `O` press /
membership re-classify (orphans.py:272 then 203). `sysupdates.py:79` builds it a further time.
**Fix:** build once per routes generation and pass it (or memoize on `ctx` keyed by `id(ctx.routes)`);
memoize `get_driver` per name inside the walk (as `scan_orphans._drv` already does).
**Effort:** S. **Tier:** C.

### subsystems-14 [LOW] comment-drift — `osversion.py` module docstring documents the retired `@`-qualifier block-key model
`configsys/osversion.py:1-18`. The docstring teaches `"ubuntu@22.04"`/`"ubuntu@<23.04"` block keys as
the live model; the current model is versioned `when:` atoms, and `split_qualifier`/`satisfies`/
`specificity` (the functions that implemented it) are dead (subsystems-16). Only
`parse_version/parse_loose/clean_version/parse_constraint/_CMP` are live. Verified: no
`@`-qualified keys in routes.hu, zero source/plugin callers of the three functions.
**Fix:** rewrite the docstring around `parse_loose`/`parse_constraint` (cross-scheme version compare)
and drop the `@`-qualifier narrative. **Effort:** S. **Tier:** E.

### subsystems-15 [LOW] comment-drift — `installState.py` header "not yet implemented in M1"
`configsys/installState.py:5-6`: "Unsupported drivers (not yet implemented in M1) degrade to an
'unsupported' state" — a stale milestone reference; an unsupported driver today means an
unknown/untrusted `via`, not an unimplemented one. **Fix:** reword to "a `via` with no registered
driver (unknown, or an untrusted code plugin) degrades to 'unsupported'/'untrusted'".
**Effort:** S. **Tier:** E.

### subsystems-17 [NIT] misc
- `configsys/runner.py:395, 464` `Runner.calls` grows unbounded for the process lifetime (every probe
  command string, thousands in a long TUI session). Cap it (a `deque(maxlen=…)`) or make recording
  opt-in for tests.
- `configsys/installState.py:167, 177` `total = len(units)` but progress counts over `to_do`, so a
  partial requery (pin change / post-execute) ends at `(len(to_do), len(units))` — the bar stalls
  below 100%. Count `len(reuse) + i`.
- `configsys/splashes.py:74-84` `register_splash` silently overwrites an existing name (last wins);
  `plugins.py` only flags conflicts between *different* plugins, not a plugin shadowing a built-in at
  registration. A one-line warning here would catch dynamic registrations.
- `configsys/versions.py:104, 111` the `register_source` docstring claims the built-in kinds are
  "github/crates/pypi/aur/url/static", but `_BUILTIN_KINDS` omits github/pypi (special-cased above the
  loop) and adds hackage/goproxy — the comment and the tuple have drifted apart.
- `configsys/refreshstate.py` + `startuptiming.py` store state as JSON while the sibling caches
  (`versions.hu`, `method-versions.hu`, `state.hu`) are `.hu`; harmless, but worth a one-line note in
  paths.py that machine-only numeric state is deliberately JSON.

## Test gaps

- **subsystems-01 (double-run):** no test that a streamed op whose child emits a non-UTF-8 byte runs
  exactly once. Add one against a recording runner with a `\xff`-emitting command. (`test_runner.py`
  has 27 tests but none exercises a decode error on the captured-tty path.)
- **subsystems-05 (malformed constraint):** `test_versionsweep.py::test_meets_abstains_false_on_
  unparseable` covers an unparseable *version*, not an unparseable *constraint operand* (`>=v3.11`,
  `~1.21`) — the case that raises. Add it; add a `check`/`inspect` end-to-end test that a bad
  constraint is a warning, not a traceback.
- **subsystems-06 (reboot FP):** `test_rebootcheck.py` has the same-series-no-false-positive test but
  not the multi-flavor case (booted LTS, newer non-default kernel installed). Add it.
- **subsystems-07 (cache slot collision):** no test that two same-`via` bindings with different
  `name:` get distinct `versions`/`_LatestCache` entries.
- **subsystems-03 (scrub):** `test_reportgen.py::test_scrub_masks_tokens_labels_and_home` doesn't
  cover URL userinfo or GitLab/npm token prefixes. Add adversarial inputs.
- `versions.hu` concurrency: `test_versions.py::test_concurrent_discovery_of_distinct_keys_persists_
  every_record` covers writers vs writers but not a reader observing a torn file (subsystems-08).
- `osdetect.refine`: `test_detect_marker.py` has the positive case; no test for the base-mismatch
  skip (`osdetect.py:169`) or two detectable derivatives matching (dict-order winner).

## Dead code (grepped configsys/, ~/src/configsys-*/, examples/, tests, driver.py ABI)

- `configsys/reportgen.py:63-65` `save_failure`, `:91-94` `load_failure` — zero production callers
  (only the module's own docstring mention + `test_reportgen.py`). The TUI/CLI use
  `save_failures`/`record_run`/`load_failures`. Remove, or keep only if a plugin ABI needs them (none
  does).
- `configsys/flooradvise.py:228-235` `resident_upgrades` (the `states` variant) — zero callers
  anywhere; production uses `resident_upgrades_probed` (`app.py:852`). Only `test_flooradvise.py`
  calls it.
- `configsys/osversion.py:90-124` `split_qualifier`, `satisfies`, `specificity` — zero source and
  zero plugin callers (confirmed over `~/src/configsys-*`); the `@`-qualifier model they served is
  retired. (`test_osversion.py` still tests them.)
- `configsys/versionsweep.py:30` `collect_requirement_floors(components, drivers=None)` — `drivers`
  is accepted and never used (the docstring admits it).
- `configsys/reportgen.py:22` `_MARKER` "reserved for later auto-labeling" — emitted in the body,
  never consumed.
- `configsys/runner.py:450-457` `sudo_session` — zero callers (the one context manager that would fix
  subsystems-13); `:460-461` `presudo` parameter — accepted and explicitly ignored, no caller passes
  it (grep: only the test stubs mirror the signature). Decide at the next ABI bump: wire
  `sudo_session` into the bulk-upgrade/refresh paths (subsystems-13) and drop `presudo`.

## ABI / interface candidates

- **`Runner.run(presudo=…)`** is dead compat — drop it at the next ABI bump (it's in every test
  runner stub's signature, so it's a visible surface).
- **`runner.sudo_session()`** should either become a used, documented part of the Runner contract
  (the exception-safe batch scope) or be removed; today it's an unused public method.
- The version-cache classes (`versions.VersionCache`, `versionreport._LatestCache`) are effectively a
  private interface duplicated twice; folding them into one `cachefile` class (subsystems-08/-09)
  would also give plugins one place to key a TTL cache.

## Questions for the user

1. subsystems-04: do you want the version-`url` backend restricted to `http(s)://` and/or gated under
   `command_source_trusted`, or is an untrusted data plugin's arbitrary-host/`file://` version fetch
   acceptable (it rides the same "data isn't a boundary" posture that A1 explicitly rejected for other
   command-carrying data)?
2. subsystems-01: confirm the decode-error re-run is a real hazard on your fleet (any non-UTF-8 build
   output) — the fix is small and I'd rank it Tier A regardless.
3. subsystems-13: fold the bulk-upgrade/refresh sudo paths through `sudo_session`, or just add
   `end_sudo()`?

## Refuted on verification

None. All six checked findings reproduced.
