# Review: Test suite + maintenance tools

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: test/ — conftest.py, _render_harness.py, flatpak_family_drive.py, the 199 `test_*.py` files
(sampled for a close read, swept by script for assertion-free tests, skips, sleeps, duplicated
fixtures, pyflakes, and instrumented for subprocess, network and timing), the 22 `integration_*.sh` +
13 `run-*-in-podman.sh` harnesses, 7 Containerfiles, namesweep-allowlist.hu, routing_golden.json;
tools/ — compaudit, docaudit, gen_manpages, namesweep, osaudit, regsweep, repos.sh, reviewaudit,
versionsweep (each read line by line); pyproject.toml; .claude/hooks/block-no-touchy.sh.
Context: .claude/skills/update-docs/SKILL.md, .claude/skills/update-component/SKILL.md, CLAUDE.md,
configsys/paths.py, configsys/app.py (Context, `_dispatch_op`, `maybe_refresh_before_plan`),
configsys/routes.py (`load`), configsys/runner.py, configsys/plugins.py (`load_code`).
Tests read: test_compaudit, test_osaudit, test_docs, test_manpages, test_reviewaudit,
test_versionsweep, test_driver_inventory, test_golden, test_pretend_sweep, test_render_headless,
test_tui_smoke, test_tui_pin, test_execute, test_pin, test_profile_edit, test_primary_* fixtures,
test_config_overlay, test_uninstall_queue, test_fix_* headers, plus the scripted sweeps below.

How it was measured. The baseline run (`--durations=40`: 2314 passed, 500 s) was not repeated.
Instead a scratch pytest plugin (`-p spy3`) **blocked** outbound DNS/connect and logged every
subprocess spawn plus the time spent in `routes.load`, over three targeted batches: the slow
files (268 tests), an unbiased every-4th-file sample (420 tests), and every remaining file that
can reach a Runner, a Context or `main` (1215 tests). That last batch ran with `HOME` pointed at a
scratch dir, git identity in the env, and a logging fake `sudo` on PATH, so nothing reached the
host. Mutating paths ran only under `--pretend` or with the fake `sudo`. One disclosure: the
unbiased-sample batch ran before tests-tools-01 was known, without the fake `sudo`. Its
`test_execute` case therefore invoked the real `sudo -n -v` / `sudo -v` / `sudo bash -c
apt-get update` from this non-tty session. These almost certainly failed to authenticate (no tty, no
askpass). Per the no-sudo rule, sudo's state was not checked. The orchestrator's Phase-0 full run
executed the same test.

## Carried over from docs/review-2026-09/README.md

No earlier area file covered this area (INHERITED: none). The 2026-09 README §3 "Test gaps worth
filling" applies to the whole suite, so each of its items is settled here. The 2026-11 review
inherits only to `primary`.

| earlier finding | status | evidence |
|---|---|---|
| §3 tarball/appImage empty-`installDir` guard | fixed | `fcafb84` (test_tarball.py:245, `check` lint `tarball-no-installdir`) |
| §3 `dir_name('..')` / `-`-prefixed source reaching git | fixed | `7f43966`, test_plugins.py:745-753 (`--upload-pack=…` rejected) |
| §3 headless render of each `_draw_*` | fixed | `b13600f` + D2: test_render_headless.py renders all 7 screens × 2 sizes × 4 palettes |
| §3 `{}` config file | fixed | test_config_edit.py:25/40, test_config_move.py:20/114 write into an empty `{ }` user file |
| §3 `apk` has no test at all | open (narrowed) | `2a577c0` added `installed_index`/`explicit_keys` (test_fix_drivers_d.py:120-168) and System Updates covers `upgradable_index`. `Apk.install/uninstall/lock/get_version/get_latest` are still never exercised. Carried in tests-tools-16 |
| §3 cross-driver injection regression gate | open | there are per-driver checks only (test_source.py:192, test_clang_driver.py:56, test_go_install_driver, test_plugins.py:753). No test passes one metacharacter-laden name through every driver's command builder. Carried in tests-tools-16 |
| §3 section-scanner corruption cases | open | test_hutext.py has 3 tests and test_plugins.py:439 has one; config-layers-01 (CRITICAL: a scalar edit deletes lines) shows the gap is still live. Owned by config-layers |
| §3 include-of-a-root-layer | open | no test; the bug it would guard (2026-09 A5) is open as config-layers-03 |
| §3 per-CLI-verb `main([...])` tests | open | carried by app-cli ("Verbs no test drives through main") |

## Cross-cutting themes

- **The suite is not hermetic, and nothing in the shared infrastructure tries to make it so.**
  `conftest.py` (21 lines) only fixes `sys.path`. The "sandbox" each test builds is `--home tmp_path`,
  but `--home` does not beat an ambient `CONFIGSYS_STATE_DIR` / `CONFIGSYS_CONFIG` /
  `CONFIGSYS_REPO`. Global git config, the user's real flatpak/brew/cargo state, and the network
  all leak in, and one test reaches real `sudo` (tests-tools-01, -02, -04). The right pattern
  already exists, written locally in `test_pretend_sweep.sandbox` and `test_primary_journal.primary`
  (scrub `CONFIGSYS_*`/`XDG_*`, set `HOME`, set git identity). It was never promoted to an autouse
  fixture, and the tui-core (tui-core-13) and drivers-lang findings show the same leak from the
  product side.
- **Maintenance tools report "OK" when their infrastructure fails.** namesweep and osaudit ignore
  the verifier's exit status, compaudit stores its network error in the *body* slot that callers
  parse as content, and `osaudit fixtures` lists Containerfile bases without judging them. A failed
  image pull, a 429 or a flathub outage therefore reads as green, as "arrived", or as "broken"
  (tests-tools-06, -07). The tools' own tests use fakes that never return the failure shapes
  (tests-tools-16).
- **Fixtures and harnesses froze at the model they were written for.** 11 podman scripts still
  seed the retired `{ configs: user }` into the legacy `~/configsys.hu`. `integration_apod.sh`
  asserts the pre-glue `~/.bash.d` link. About 20 unit-test fixtures and comments still talk about
  "active"/"selected" profiles. `docaudit`'s retired-term check never looks outside `*.md`, so none
  of this is flagged (tests-tools-08, -12, -17).
- **Time goes to re-deriving the same thing.** About 55 % of wall time is `routes.load` re-parsing and
  re-validating the same routes.hu per test (0.4 s a call). Most of the rest of the top-40 is host
  probing a fake runner would make free, or fixed waits (tests-tools-05, -13, -14).

## Findings

### tests-tools-01 [HIGH] safety — a unit test runs real `sudo -v` and `sudo apt-get update` on the developer's host
`test/test_execute.py:76-95` (`test_dispatch_op_prints_the_failure_reason_to_the_console`): the test
stubs `get_driver`, but builds its Context **without `--pretend`** (line 91) and calls
`app._dispatch_op(ctx, ['git'], 'install')`. Before the stub is reached, `maybe_refresh_before_plan`
(`configsys/app.py:1444`, `refresh-before-execute: auto`) runs the native index refresh, and
`actions.run_plan` authenticates up front (`actions.py:214`, `begin_sudo`). Both go through the real
`Runner`. On a developer terminal this happens mid-suite: either `sudo -v` prompts for a password on
/dev/tty (the suite hangs on a hidden prompt), or, with cached credentials, root runs
`apt-get update` on the host. The test passes either way, so nothing ever flags it. `conftest.py` has
no guard against a non-pretend Runner, so the next stub that misses a code path would run a real
`sudo apt-get install`. This is exactly the class the orchestrator's safety addendum warns about.
Across the ~1900 instrumented tests (every file that can reach a Runner, a Context or `main`), this is the only one that reached `sudo`.
**(reproduced)** `PATH=$S/fakesudo:$PATH pytest test/test_execute.py::test_dispatch_op_prints_the_failure_reason_to_the_console`
→ `1 passed`; the fake sudo logged `bash -c apt-get update` ×3, `-n -v`, `-v`, `-n -v`.
**Fix:** add `--pretend` to that Context, or inject a FakeRunner. Then add an autouse conftest
fixture that monkeypatches `Runner.run` (and `Runner.begin_sudo`) to raise unless `self.pretend`, or
unless the test carries an explicit `@pytest.mark.real_runner` (the runner tests, the `file://` curl
tests, the shell-glue tests). **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept. `$V` = `$RUN/scratch/verify-tests-tools`. Two guards made sure
the real sudo could not run: a logging fake `sudo` first on PATH, and a `-p sudoguard` plugin that
rewrites any `sudo` argv to that fake. `HOME=$V/home01 PATH=$V/fakesudo:$PATH pytest -p sudoguard
test/test_execute.py::test_dispatch_op_prints_the_failure_reason_to_the_console` → `1 passed in 3.53s`.
The fake logged `bash -c apt-get update` ×3, then `-n -v`, `-v`, `-n -v`: 6 of the test's 7 spawns.
**Why, by reading:** `refresh_native_index` (app.py:1416-1430) calls
`ctx.runner.run('apt-get update', sudo=True)` directly, so the `get_driver` stub never covers it.
`StubDrv` has no `.privileged`, so `_may_need_root` catches the `AttributeError` and returns True
(actions.py:144-148), and `begin_sudo` runs.
**No guard:** conftest.py holds only the sys.path fix and an unused fixture. No pytest config adds
`--pretend`. Product code has no test-mode check (`grep -rn PYTEST configsys/` → nothing).
**Two wording corrections:**
- The first prompt comes from the refresh's `sudo bash -c 'apt-get update'`, before `begin_sudo`'s
  `sudo -v`.
- The prompt is not hidden. sudo prompts on /dev/tty, which pytest does not capture, so an
  unexplained password prompt appears mid-run and the suite blocks on it.

A real sudo's "a password is required" is classed AUTH, which is DEFINITIVE (failures.py:55, :87), so
it is not retried. The ×3 retry only happens for the fake's generic failure. The reviewer's spy logs
back "the only one": 1870 distinct tests, and `sudo` exec records only for this test. The whole
suite was not re-run (targeted runs only).

### tests-tools-02 [HIGH] safety — tests read and write the developer's real config; `--home` loses to ambient env, and global git config breaks 105 tests
`test/conftest.py:1-21`, `configsys/paths.py:76-90`, `configsys/app.py:110-113`: `--home` only sets
`CONFIGSYS_HOME`, while `Paths` gives an existing `CONFIGSYS_STATE_DIR` (and `CONFIGSYS_CONFIG`,
`CONFIGSYS_REPO`) precedence over it. No test fixture except two file-local ones scrubs them. A
developer whose shell exports `CONFIGSYS_STATE_DIR`, for instance to test a second state dir, runs a
suite that edits their real configsys.hu. The project memory already notes this user's shell exports
other `CONFIGSYS_*_DIR` vars. Separately, nothing isolates git from the user's global config. The
primary fixtures claim otherwise (`test_primary_autocommit.py:21-22`: "commits never depend on the
developer's ~/.gitconfig"), yet a global `commit.gpgsign = true` fails their setup commits. Signing
is the very workflow `primary-verify: signed` encourages, so a signing collaborator cannot run the
primary/plugin tests at all.
**(reproduced)** a scratch state dir with `// my real config` + `picks:`, then
`CONFIGSYS_STATE_DIR=$S/leak6/state pytest test/test_pin.py::test_pin_set_reroutes_resolution` → `1 passed`, and
`diff before.hu state/configsys.hu` → `> pins: { steam: flatpak }` (the test wrote the "real" config).
`GIT_CONFIG_GLOBAL=$S/signing.gitconfig pytest test_primary_*.py test_humerge.py test_plugins.py` →
`15 failed, 91 passed, 90 errors` (`git commit -qm A` exit 128).
**Fix:** one autouse fixture in conftest, promoted from `test_pretend_sweep.sandbox:41-48`. It
deletes every `CONFIGSYS_*`/`XDG_*`, sets `HOME` to a tmp dir, and sets `GIT_CONFIG_GLOBAL=/dev/null`,
`GIT_CONFIG_NOSYSTEM=1` and the four `GIT_AUTHOR_*`/`GIT_COMMITTER_*`. Separately (product,
app-cli/config-layers): decide whether `--home` should clear an inherited `CONFIGSYS_STATE_DIR`
(see Questions). **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept. The git count is corrected: 89 broken tests, not 105,
when the signing config lives in `~/.gitconfig`.

**By reading.** `Context` sets only `env['CONFIGSYS_HOME']` (app.py:111-112). `Paths` takes
`CONFIGSYS_STATE_DIR` first (paths.py:79-81), `CONFIGSYS_CONFIG` over `<state>/configsys.hu`
(:88-89), and `CONFIGSYS_REPO` first (:145-147). Only test_pretend_sweep.py:44-46 and
test_primary_journal.py:26-28 scrub `CONFIGSYS_*`.

**Env leak, reproduced.** Fake sudo and sudoguard were on, with `HOME` set to a scratch dir. The
"real" config was a hand-written `{ picks: { this-machine: [ btop ] } }`.
- `CONFIGSYS_STATE_DIR=$V/leak/state pytest test/test_pin.py::test_pin_set_reroutes_resolution` →
  `1 passed`, and the diff shows `pins: { steam: flatpak }` added.
- `CONFIGSYS_CONFIG=$V/leakcfg/real.hu pytest test/test_pin.py` → `4 failed, 4 passed`, and the
  same pin was written into real.hu.
- Worse: `CONFIGSYS_STATE_DIR=$V/leak2/state pytest test/test_plugins.py test/test_picks.py
  test/test_config_edit.py` → `19 failed, 48 passed`. The "real" config lost its `picks:` entirely.
  It gained 4 `plugins:` declarations, one of them `primary: true` from a pytest tmp dir, and 7 test
  clones appeared in its `plugins/`.

**Git, reproduced.** Nine files, 196 tests (the seven test_primary_* files, test_humerge,
test_plugins). The config went in a scratch home's `.gitconfig`, with fake gpg programs; real gpg
never ran.
- Identity only → `196 passed`.
- `commit.gpgsign = true` with no key for the fixtures' `t <t@t>` → `15 failed, 107 passed, 74 errors`.
  Every one is `git commit -qm A` exiting 128.
- The same config via `GIT_CONFIG_GLOBAL`, as the reviewer ran it, → `15 failed, 91 passed,
  90 errors`. That matches their numbers, but it also breaks test_primary_journal's 16 tests, whose
  fixture moves `HOME`; a real `~/.gitconfig` would not reach them.
- A working signer (`user.signingkey` set) → `196 passed`, but the fake signer logged 220
  `-bsau` calls. The suite signs its throwaway commits with the developer's real key.

So "cannot run them at all" holds only for a signer whose key isn't found for the test identity.

**Trigger.** Nothing configsys ships exports these variables (the glue preludes only read
`CONFIGSYS_STATE_DIR`), and none is set in this session. HIGH stays because the variable is a
documented override, and once it is set the suite deletes the developer's real picks.

### tests-tools-03 [MED] security — a fixed, world-writable `/tmp/nohome` is used as a trusted configsys home
`tools/regsweep.py:120` (`load_catalog`), `test/test_theme.py:281,295,320`,
`.claude/skills/add-component/SKILL.md:283`: each builds
`Context(['--home', '/tmp/nohome', …]).routes`. `Context.routes` → `_resolver` →
`ensure_plugin_code()` → `plugins.load_code(<home>/.config/configsys/plugins, <home>/…/plugin-trust.hu, …)`
imports every trusted code plugin of that home (app.py:282-318). `/tmp` is shared. Any local user
who creates `/tmp/nohome` first controls its configsys.hu, plugins dir and trust file. Trust is a
content hash they can compute, so `pytest`, `regsweep` or the skill snippet then runs their
Python as the maintainer. It also lets a previous run's leftovers pollute the next. Without this
bug, that local user would have no way to run code as the maintainer.
**(reproduced, in scratch)** `scratch/tests-tools/r3/squat_demo.py` plants a manifest with
`code: evil.py`, a `plugins:` declaration and a `plugin-trust.hu` entry in a scratch home standing
in for `/tmp/nohome`, then runs `Context(['--home', <it>, '--os','pop','inspect']).routes`
→ `marker written by planted plugin: True imported`. `/tmp/nohome` itself was not created.
**Fix:** `tempfile.mkdtemp()` (removed after), or `tmp_path` in the tests; update the skill snippet.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). MED kept.

**The path is free to claim.** `/tmp` is `drwxrwxrwt`, and `/tmp/nohome` does not exist on this host,
even though Phase 0 ran the full suite today (booted 2026-10-26). The call sites never create it:
all three test_theme tests pass against an absent scratch home and leave it absent. Any local
account can therefore claim the name at any time.

**Nothing gates on ownership.** `load_code`, `is_trusted`, `read_trust` and `_import_module`
(plugins.py:1176-1212, :425, :373, :1134-1152) check no uid or file mode. `plugin_identity` is a
public sha256 over files the squatter wrote.

**Reproduced.** `$V/squat_verify.py` plants a squatter home in scratch: a top-config `plugins:`
declaration, `plugins/sq/plugin.hu` with `code: evil.py`, and `plugin-trust.hu` holding the computed
hash. It then execs the real call-site source with only the literal `'/tmp/nohome'` swapped.
- test_theme.py: all 3 `passed`, and the planted module ran (stack `ensure_plugin_code → load_code →
  _import_module`, uid 1000).
- `regsweep.load_catalog()`: `748 catalog rows`, and it ran.
- The SKILL.md `reschk` snippet: its normal 9-OS table, and the module ran once per OS.
- 12 runs in total.
- With the planted tree `chmod -R a-w`, as when another uid owns it, the tests still pass and the
  code still runs (`12 -> 14`). Nothing in the path needs to write there.

**Precision.** Only 2 of the 3 test_theme sites reach `.routes` (:281 and :320; :295's plugins sample
does not). The call sites never write to the home, so the "leftovers pollute the next run" half
applies only to leftovers someone else creates.

**Severity.** MED matches drivers-os-06 (`/tmp/configsys-aur`, MED). This is silent cross-user code
execution as the maintainer, on every full-suite run and every /add-component resolve check. It is
reachable only where a second local account exists.

### tests-tools-04 [MED] correctness — tests depend on the host's packages and the network: real dpkg/flatpak/brew probes, and api.github.com
`test/test_tui_pin.py:34-36` (`_ctx` has no `--pretend`), :260-276
(`test_row_error_not_smeared_onto_profiles`). Also `test_tui_provider`, `test_pin._run` and
`test_app.test_inspect_generates_user_config_and_exits_zero`. These tests assert on the menu
*model* but build it through a full real `load_pipeline()` inspect. That spawns `dpkg-query`,
`apt-cache policy`, `apt-mark showhold`, `flatpak remote-info/remote-ls --user flathub` (network,
and it initializes `~/.local/share/flatpak/repo` in the user's home), `brew info --json` (refreshes
`~/.cache/Homebrew/api`), `cargo install --list` and `lspci`. For lazygit/nushell it also calls the
GitHub version discovery, including **unauthenticated api.github.com**, which is capped at 60
requests per hour. Each suite run therefore spends the developer's rate limit and depends on what
they have installed. It costs 12.7 s even offline (retry backoff), and ~2 s per test elsewhere in
the file.
**(reproduced)** spy run with DNS/connect blocked: `dns-blocked test_tui_pin.py::test_row_error_not_smeared_onto_profiles`
×18 (`github.com` ×12, `api.github.com` ×6); `12.66s call …test_row_error_not_smeared_onto_profiles`,
`2.4-2.7s` for the other test_tui_pin/test_tui_provider tests with one 0.35 s routes.load each. With
`HOME` redirected, the run left `.local/share/flatpak/repo`, `.cache/flatpak/system-cache/summaries/flathub.idx`,
`.cache/Homebrew/api/formula_names.txt` and `.cargo/.crates2.json` in the scratch home.
**Fix:** build these contexts with `--pretend`, or inject a FakeRunner plus a stub `versions` fetch
(the model tests need states, not real probes). Make the autouse fixture from -02 block sockets
except for an opt-in `network` marker. **Effort:** S. **Tier:** B.

### tests-tools-05 [MED] performance — about 55 % of suite time re-parses and re-validates routes.hu (0.4 s per load)
`configsys/routes.py:312` (`load`), called through every `Resolver(...)` and `Context.routes`.
Each call parses the full layer stack and runs `routecheck` over 868 components. That is about
0.4 s (0.115 s with `validate=False`, so the check is three quarters of it), and it is repeated
from scratch in nearly every test that touches routing. A CLI round-trip test pays it per `main()`
call (`test_config_show_reports_values_that_were_set`: 10 loads = 3.8 s of 4.4 s;
`test_fedora_atomic_audit_fixes`: 9 loads = 3.75 s of 3.94 s). The baseline top-40 tests account for
186 s of the 500 s. The remaining ~314 s is the long tail of ~2270 tests at ~0.14 s each, and that
tail is mostly this one cost.
**(reproduced, measured)** `routes.load #1/2/3: 0.390s 0.517s 0.492s; validate=False: 0.115s`.
Spy totals: slow files `268 tests, wall 159.9s, routes.load 245 calls = 98.7s (62%)`; unbiased
sample `420 tests, wall 34.9s, 105 calls = 18.0s (52%)`; remaining files `1215 tests, wall 206.0s,
328 calls = 120.5s (58%)`.
**Fix:** memoize the parsed repo layer and the routecheck result, keyed on each layer's
(path, mtime, size) or content hash, in production code. A Context invalidate after a write already
changes the user layer's key, and the TUI rebuilds after every edit, so the TUI benefits too. As a
cheaper test-only alternative, add a session-scoped cache of the validated repo `load()` that
per-test Resolvers reuse. Expect the suite to drop from ~8 min to ~4. **Effort:** M. **Tier:** C.

### tests-tools-06 [MED] correctness — namesweep and osaudit report "OK" when the container never ran
`tools/namesweep.py:152-157` (`_run_verifier` returns `rc`), :184 and :231 (`sweep`/`sweep_plugin`
discard it), `tools/osaudit.py:494-514`, :877-879: the "missing" set is whatever the container
printed on stdout. A failed image pull (manifest unknown, no network, podman error, exit 125)
prints nothing, so every name "exists". namesweep then prints `name sweep: OK` (exit 0) and
advises **removing allowlist entries** ("now exists"). `osaudit sweep` reports `0 missing` and
lists **every** arrival candidate as a package that has "arrived", also with exit 0. A verifier
timeout is recorded as a per-release `error` but still exits 0. `namesweep --sweep --only <name>`
with a block name instead of a manager (`--only fedora`) sweeps nothing and prints OK. /update-os
and /add-component treat these sweeps as the gate.
**(reproduced)** with `scratch/tests-tools/fakebin/podman` (prints the real "manifest unknown"
error, exit 125): `namesweep.py --sweep --only apk` → `note apk: allowlist entry "rocm-hip" now
exists — remove it` / `name sweep: OK` / `exit=0`. `namesweep.py --sweep --only fedora` → `OK`,
`exit=0`. `osaudit.py sweep fedora 44` → `394 checked … 0 missing`, 150 `arrival … name-only`
lines, `exit=0`.
**Fix:** have `_run_verifier` raise or return an error when `rc != 0` and stdout carries no names.
Better, end the snippet with a sentinel line (`echo __CFS_DONE__`) and treat its absence as a
failed run. Make any per-release error exit nonzero, and reject `--only` values not in
`_VERIFIERS`. Add tests with a fake `_run_verifier` (tests-tools-16). **Effort:** S. **Tier:** B.

### tests-tools-07 [MED] correctness — compaudit turns outages into "broken" findings, and a flathub outage crashes the scan
`tools/compaudit.py:354-367` (`Fetcher._fetch` returns `(None, url, 'network error: …')`, the
error string in the **body** slot). At :410-439, `probe_github` regexes that "body" for release tags,
finds none, and emits `broken asset-glob-miss … (no releases)` for every asset. A 429 or 403 from
github.com takes the same path. At :596-599, `run_probes` does `json.loads(b1) if b1 else {}` on the
flathub `/eol/*` "body", so an unreachable flathub raises `JSONDecodeError` and aborts the whole
scan. At :337-339, a cache file torn by Ctrl-C mid-`write_text` (or two threads writing the same
key, :351) raises on every later `get` within the TTL, and always under `--offline`. The skill does
re-verify every *broken* finding (SKILL.md:208), but a 12-thread scan that trips GitHub's throttle
floods the report with false "broken" entries. The skill itself calls that "the most expensive kind".
**(reproduced)** `scratch/tests-tools/compaudit_neterr.py`:
`NetDown -> [('broken', 'asset-glob-miss', "lazygit … matches no asset … (no releases)")]`,
`RateLimited -> [same]`, `run_probes(NetDown) raised JSONDecodeError`, `torn cache -> JSONDecodeError`.
**Fix:** return `(None, url, None)` plus a separate `error` field from `_fetch`. In `probe_github`,
emit a `note probe-failed` (never `broken`) when any github fetch had `st is None or st >= 429`.
Guard `run_probes`' `json.loads` on `st == 200`. Write cache files atomically (tmp + `os.replace`)
and treat an undecodable one as a miss. **Effort:** S. **Tier:** B.

### tests-tools-08 [MED] correctness — the podman harnesses no longer match the code
- `test/integration_apod.sh:32-33` asserts `[ -e "$HOME/.bash.d/apod.sh" ]`. Since `221e52d`
  (2026-09-17) apod-glue links `~/.config/bash/conf.d/50-apod.sh` (`drivers/glue.py:51-74`), so
  `run-apod-in-podman.sh` fails on a correct install. The script was last touched 2026-07-17.
- 11 scripts (`integration_{arch_graphics,el_rpmfusion,langs,rhel_epel,zip,aur,lang_modules,
  fastfetch_deb,pacman,script,zypper}.sh`, e.g. zypper.sh:15-17) seed
  `printf '{ configs: user }' > "$HOME/configsys.hu"` to "select the base profile". Today that file
  is migrated to `~/.config/configsys/` and `configs:` is retired, so the setup selects nothing and
  each run starts with a `check` warning. **(reproduced)**
  `configsys --home H --os opensuse check` → `moved …/configsys.hu -> …/.config/configsys/configsys.hu`,
  `` warn … `configs:` retired — the matrix model installs from picks: ``.
- `Containerfile.fedora:5` and `run-dnf-in-podman.sh:13` default to `FEDORA=41`, which the registry
  marks `eol 2025-12-15`. `run-fedora-toolchain-in-podman.sh:3` still says "fedora:41" while it
  loops over 43/44/45. `osaudit fixtures` lists these bases only as `info`, although its docstring
  says it checks them against the registry.
- `Containerfile.el9:10-12` installs `python3.12 python3.12-pip python3.12-devel`, which EL10 does not
  have, so the "release-selectable" `EL_IMAGE=almalinux:10` (rhel 10 is `released`) cannot build.
  Both EL runners also tag the image `configsys-test:el9` whatever the base is. **(reproduced)**
  `podman run --rm almalinux:10 dnf -q list --available python3.12 python3.12-pip python3.12-devel python3 python3-pip`
  → only `python3-pip.noarch … appstream`.
- `integration_lang_modules.sh`, `integration_script.sh` and `integration_zip.sh` have no runner;
  only docs/done/expansion-plan.md mentions them. Step counters are off in
  `run-in-podman.sh:26-35` (1/3, 2/3, 3/4, 4/4) and `run-pacman-in-podman.sh:19-25` (1/2, 2/3, 3/3).

**Fix:** assert `~/.config/bash/conf.d/50-apod.sh`. Replace the seeds with
`mkdir -p ~/.config/configsys && printf '{ picks: { this-machine: [ ] } }'`, or drop them. Default
FEDORA to the newest released entry, and have `osaudit fixtures` flag an EOL or non-newest
Containerfile `ARG` as stale. Give Containerfile.el9 an EL10 branch (`python3`) and tag by base.
Give the three orphans runners or fold them into `run-langs-in-podman.sh`. **Effort:** M. **Tier:** B.

### tests-tools-09 [MED] test-gap — the routing golden doesn't cover two whole package managers or the newest releases
`test/test_golden.py:26-29` (`CONTEXTS`): 15 contexts, none of them alpine (apk), opensuse /
opensuse_leap (zypper), the native-less blocks (chimera, kde_linux, where the `via: native` skip
rule applies), amzn/oracle, or the newest live releases (ubuntu 26.04 LTS and 26.10, debian 13,
rhel 10, fedora 43/44). Meanwhile it spends contexts on EOL fedora 41/42 and debian 11. CLAUDE.md
calls `routing_golden.json` "the regression gate". Yet a resolver or data change that reroutes every
Alpine or openSUSE component passes the suite: `test_routecheck` only checks ambiguity, and
`test_os_blocks` checks lineage.
**(reproduced)** `osaudit.py fixtures` → `stale test/test_golden.py CONTEXTS: debian: newest released 13 has no golden context`,
same for `elementary 8.1`, `rhel 10` and `ubuntu 26.10`, plus `namesweep.py MANAGERS: apt sweeps ubuntu 24.04; newest released is 26.10`.
The golden's keys are 15 contexts, all apt/dnf/pacman/xbps/brew.
**Fix:** add `('alpine','3.24')`, `('opensuse_tumbleweed', None)`, `('opensuse_leap','15.6')`,
`('chimera', None)`, `('kde_linux', None)`, `('ubuntu','26.04')`, `('debian','13')` and `('rhel','10')`.
Drop the EOL contexts the registry freezes, if the size matters (the file is 6 MB). Make osaudit's
"no golden context for newest release" check fail a test. **Effort:** S. **Tier:** B.

### tests-tools-10 [LOW] correctness — `osaudit … --routes F` is half-honored by `sweep`
`tools/osaudit.py:780-782` rebinds the module global `ROUTES`. But `release_names` (:544) calls
`namesweep._native_names(line, version, manager)` without `routes_path`, and that default was bound to
namesweep's own `ROUTES` at definition time (`namesweep.py:59`). A sweep of a snapshot therefore checks
the **repo's** native names while computing arrivals and `_NATIVE_BACKED` names from the snapshot.
**(reproduced)** `scratch/tests-tools/r3/routes_flag_probe.py`, with a routes copy that renames
`btop` → `btopRENAMEDX`: `release_names (namesweep half) has btop: True` and
`_resolve_all has btopRENAMEDX: True  btop: False`.
**Fix:** pass `routes_path=ROUTES` through, or make both modules read one shared setting. **Effort:** S. **Tier:** B.

### tests-tools-11 [LOW] correctness — pyproject's wheel can't build, would ship no glue, and the sdist isn't self-checking
`pyproject.toml:44-49`: `force-include` maps `"dotfiles"`, but the repo has no `dotfiles/` (content
moved to the user store and plugins; `git log --diff-filter=D -- 'dotfiles/*'` → `221e52d`).
hatchling raises `FileNotFoundError: Forced include not found` for a missing source. `glue/` is not
listed, although `Paths.glue_dir = repo/'glue'` (paths.py:74) holds the 00-configsys preludes and
every component's shipped glue, so a wheel install would have none. The sdist (:51-62) omits
`tools/`, `examples/` and `glue/`, which test_compaudit, test_osaudit, test_docs, test_example_plugin
and the glue tests need, so "the sdist is self-checking" (:49) is false. The header comment (:10)
still says "make sure dotfiles/ holds only shippable templates".
Verified by reading; hatchling is not installed here and there is no network to fetch it.
**Fix:** replace `dotfiles` with `glue` in force-include, and add `glue`, `tools` and `examples` to the
sdist. Add a test that loads pyproject (tomli is in the venv) and asserts every force-include source
exists and covers each repo root `Paths` reads (`routes.hu`, `config.hu`, `glue`, `man`).
**Effort:** S. **Tier:** B.

### tests-tools-12 [LOW] correctness — docaudit's checks have blind spots and one false error
`tools/docaudit.py`:
- `_check_cli_coverage` (:476-498) takes the first non-flag word as the subcommand. In
  `configsys --os fedora where steam` that is the *value* of `--os`, which becomes an error-level
  `cli-unknown` (the run exits 1). Documenting the headline `--os`/`--home`/`--machine` flags in an
  example is therefore penalized.
- `_check_retired` (:343-369) skips any line whose ±1-line window contains generic words such as
  `was `, `were `, `old `, `avoid`, `gone`, `removed` or `instead of`. That blinds 10 % of live doc
  lines. It found 0 drift today, but a real regression sitting next to a "was" is invisible.
- `_check_examples` (:387-391) treats every `SystemExit` as a parse failure, so a fenced
  `configsys plugin --help` is an error, and argparse prints the help to **stdout**, corrupting
  `check --json`.
- `markdown_files` (:53-60) is the only input, so the retired terms in test/ and the integration
  scripts (`configs:` in 11 scripts and ~20 fixtures; tests-tools-08/-17) are never seen.

**(reproduced)** `scratch/tests-tools/r3/cov_probe.py`: `'configsys --os fedora where steam' -> sub
detected as 'fedora'`. `` ["Add your install list to `configs:`…", "That was the easy part."] `` →
`retired findings: []` (one line alone → one warning). The `--help` example → `bad-example` error,
with help text printed to stdout. `window_blind.py` → `837/8801 non-blank live-doc lines (10%) sit in a window that suppresses retired-term detection`.
**Fix:** skip global value options using `app._GLOBAL_VALUE_OPTS` (app.py:4854) before picking the
subcommand. Match narration phrases ("was renamed", "replaced the old", "formerly") instead of bare
`was`/`old`. Accept `SystemExit(0)`, and redirect stdout during `parse_args`. Add an opt-in pass
over `test/*.sh` and `test/*.py` string literals for retired config keys. **Effort:** S. **Tier:** B.

### tests-tools-13 [LOW] performance — `docaudit inventory` spawns two git processes per markdown file
`tools/docaudit.py:185-191` (`_git_dates`), :214-235: `git log --follow --diff-filter=A` plus
`git log -1` for each of the 100 `.md` files, 200 subprocesses in all. It runs on every
`docaudit check` (through `_check_status_headers`) and in `test_docs.py::test_inventory_classifies_docs`
(4.9 s in the baseline top-40).
**(reproduced, measured)** `inventory(): 5.89s` vs one
`git log --format=@%as --name-status -- '*.md'` pass: `0.14s for 139 paths`, with
`modified-date mismatches vs one-pass: 0`. `docaudit check(): 7.35s`.
**Fix:** one `git log --name-status -M` walk, building first-added (following `R` entries) and
last-modified maps. **Effort:** S. **Tier:** C.

### tests-tools-14 [LOW] performance — `test_install_probe_underlines_nonenumerable` always waits its full 5 s
`test/test_profile_edit.py:106-130`: the loop `for _ in range(50): if not ps.probe_busy(): break;
time.sleep(0.1)` can never exit early. `ProfileScreen.probe_busy()` (`tui/menu.py:3048-3054`)
returns True while `_probe_dirty` is set, and only the menu loop's repaint clears that flag. The
result lands after ~0.1 s, the test burns 5 s, then asserts. It is the third-slowest call in the
suite (6.53 s).
**(reproduced)** `scratch/tests-tools/r3/probe_busy.py` → `result visible after 0.116s; probe_busy() went False after 8.03s (iterations 79)` (it never went False).
**Fix:** `ps._probe_thread.join(timeout=5)`, or poll `ps._probe_installed`. **Effort:** S. **Tier:** C.

### tests-tools-15 [LOW] reuse — 30 hand-copied FakeRunners and 4 near-identical primary-remote fixtures
`test/*.py`: `class FakeRunner` is defined in 30 files: two shapes repeated 6× each, plus 18
one-offs. Each hard-codes `Runner.run(cmd, *, sudo, capture, tui_active, cwd, env)`. None accepts
`presudo`, which the real runner still accepts (runner.py:459-462), and most lack `.pretend`. That is
why production code reads `getattr(ctx.runner, 'pretend', False)` (actions.py:213, 1229;
versionreport.py:187; rebootcheck.py:47/54). The bare-remote-plus-bless `primary` fixture exists
4 times (`test_primary_{autocommit,journal,push,state}.py`), `_git` 8 times, the
`build_ctx`-wrapping `ctx` fixture 10 times, and `_ctx` helpers 19 times.
`test_humerge.py:14` and `test_primary_safety.py:14` import `primary` *from another test module*,
which produces 26 pyflakes "redefinition of unused 'primary'" warnings.
Verified by `scratch/tests-tools/scan.py` (AST sweep) and `pyflakes test/`.
**Fix:** add a `test/fakes.py` FakeRunner (substring responses, `calls`, `pretend=False`,
`**kwargs`-tolerant, `inspect.signature`-checked against `Runner.run` in one test). Move
`primary_remote(files)`, `git(cwd, *a)` and the render `ctx` into conftest. **Effort:** M. **Tier:** D.

### tests-tools-16 [LOW] test-gap — the tools' failure paths are untested, and "every driver has a test" counts an import
- namesweep: no test drives `sweep`, `sweep_plugin`, `_load_allowlist` or the `_CHECK` snippets.
  The false green in tests-tools-06 would have been caught by a fake `_run_verifier` returning `('', 125)`.
- regsweep: no test at all.
- compaudit: `FakeFetcher` (test_compaudit.py:18-24) only ever returns 404 for unknown URLs, never
  the real `(None, url, 'network error…')` or 429 shapes, so tests-tools-07 is invisible.
- osaudit: `sweep` is tested only for refusing lines ("the podman sweep … exercised by running the
  skill").
- gen_manpages: only `--check`; nothing tests `_inline`'s handling of a leading `.`/`'`, backslashes
  or `-`.
- `test_driver_inventory.py:233-245` (`test_every_driver_has_a_test`) passes when any test file
  imports the driver module. `apk` qualifies through the orphan-scan import alone, so its
  install/uninstall/lock/get_version/get_latest are never exercised. The 2026-09 cross-driver
  injection gate (one metacharacter name through every driver's command builder) is still missing.

**Fix:** add the fakes above. Strengthen the inventory check to require that each driver's `install`
and `uninstall` be called under a FakeRunner, or keep an explicit allowlist of known-shallow
drivers. **Effort:** M. **Tier:** B.

### tests-tools-17 [LOW] naming — test files named after audit batches, and test names from the retired profile model
11 files (~183 tests) are named for the review batch that produced them, not the code they cover:
`test_fix_drivers_d.py`, `_d2`, `test_fix_tui_c.py`, `test_fix_routing_layers.py`, `…layers2.py`,
`test_fix_routing_resolve.py`, `test_fix_routes_e.py`, `test_fix_cli_misc.py`, `…followups.py`,
`…pretend.py`, `test_fix_final.py`, plus `test_review_regressions.py`. Their docstrings cite
ephemeral numbering ("batch B #13", "3a"), so a newcomer looking for glue tests must also know about
`test_fix_drivers_d{,2}.py`. Fixture and test text also still describe the retired model:
`test_tui_smoke.py:47-50` seeds `{ configs: [ mine ] profiles: { mine: [ ghost-tool ] } }` "so the
`!` page has content … a resilient error row". The `!` page now shows the retired-key warning
instead, so the error-row path the comment names is no longer exercised. There is also
`test_config_overlay.py:58` `test_selected_but_undefined_profile_errors` (no profile is "selected"
any more) and `test_picks.py:60` "no active profiles". About 20 files use `configs:` as setup.
**Fix:** fold each batch file's tests into the subject test files over time. Swap the smoke seed to a
picked unroutable component (`picks: { this-machine: [ ghost-tool ] }`, which yields a real error
row). Rename the profile-era tests. **Effort:** M. **Tier:** D.

### tests-tools-18 [LOW] comment-drift — configsys(1)'s FILES section is hand-written and stale
`tools/gen_manpages.py:96-102`: six hard-coded entries. `configsys.hu` is described as "per-machine
config (profiles, pins, plugins)", but the install set is `picks:` and profiles are browse lenses.
The list omits `glue/` (the glue store), `staged-glue/`, `plugin-locks.hu`, `last-failure.hu`,
`method-versions.hu` and `launcher`. Nothing ties it to `Paths`, so `--check` keeps it "current"
forever.
Verified by reading paths.py:76-117 against the list.
**Fix:** generate FILES from a small table in paths.py (attribute, relative path, one-line purpose)
that the man page, `configsys location` and docs can share. **Effort:** S. **Tier:** E.

### tests-tools-19 [LOW] safety — `repos.sh push|tag` pushes the whole fleet with no confirmation, and tags dirty trees
`tools/repos.sh:18`, :112-150: the header says "Every mode prints the status report first, so you see
the state before anything is pushed/tagged". There is no pause, though: `push` and `tag` proceed at
once across all 16 repos. `do_tag` tags a repo whose worktree has uncommitted changes (the report
shows them; nothing gates on them). A bare `vX.Y.Z` tag such as `1.2.3` is silently restyled to
`v1.2.4`.
Verified by reading.
**Fix:** after the report, `read -r -p 'push N repos? [y/N]'` unless `--yes`; skip (or warn about)
dirty repos in `tag`; keep the tag's `v` style. **Effort:** S. **Tier:** A.

### tests-tools-20 [NIT] dead-code — a hook from another project, an unused fixture, and pyflakes noise
`.claude/hooks/block-no-touchy.sh` (tracked since `fa3892a`, registered for
`Write|Edit|NotebookEdit` in `.claude/settings.json`) guards a `no-touchy/` folder that configsys
does not have. Its fallback project dir is `/home/schrock/src/stonks` (:10). It reads only
`.tool_input.file_path` (:7), so NotebookEdit's `notebook_path` would bypass it anyway, and it
spawns bash plus jq on every edit for nothing. `test/conftest.py:17-21` `fixtures_dir` points at
`test/fixtures`, which doesn't exist, and nothing uses it. `pyflakes tools/ test/`: 59 warnings
(unused imports in osaudit:44, regsweep:20 and reviewaudit:25; unused locals; the cross-module
`primary` import).
Grepped: `grep -rn fixtures_dir test/` (definition only); `ls no-touchy` (absent).
**Fix:** delete the hook and its settings entry (or point it at a real folder); delete
`fixtures_dir`; clean the pyflakes list. **Effort:** S. **Tier:** D.

### tests-tools-21 [NIT] reuse — regsweep reimplements an uncached HTTP layer and sends the maintainer's email in its User-Agent
`tools/regsweep.py:22-44`: a private `_get` with an in-memory dict cache and a fixed 0.25 s sleep.
compaudit already has a disk-cached, per-host-throttled `Fetcher`. The UA string is
`configsys-regsweep (https://github.com/; spacemeat@gmail.com)`, so a collaborator running the tool
sends the maintainer's address to crates.io, PyPI, npm and flathub. Also `import sys` is unused, and
`urllib.parse` is imported at :115 after its first use at :90 (this works only because it is
module-level).
**Fix:** import `compaudit.Fetcher`, and use compaudit's project-URL UA. **Effort:** S. **Tier:** D.

### tests-tools-22 [NIT] performance — `namesweep --sweep --only apk` resolves all six managers first
`tools/namesweep.py:172`: `extract()` resolves the whole catalog for every entry in `MANAGERS` before
filtering to `targets`, which took 8.3 s for a one-manager sweep.
**(reproduced)** `time namesweep.py --sweep --only apk` (fake podman) → `real 0m8.293s`.
**Fix:** `extract(only=targets)`. **Effort:** S. **Tier:** C.

## Test gaps

Already listed as findings: -09 (golden contexts), -16 (tool failure paths, apk lifecycle, injection
gate), -11 (pyproject packaging test). Smaller ones:

- No test asserts that the suite itself is hermetic. Once -01/-02 land, add a meta-test that the
  autouse fixture refuses a non-pretend `Runner.run` and that `CONFIGSYS_STATE_DIR` is unset.
- `test_pretend_sweep` snapshots only the sandbox home. It would not notice a `--pretend` write to
  `$XDG_CACHE_HOME` (tui-core-13) or to `/tmp` (e.g. `aur._BUILD_ROOT`).
- `test_golden` writes `routing_golden.json` whenever `CONFIGSYS_REGEN_GOLDEN` is set in the
  environment, and only `skip`s. An exported variable silently re-blesses the golden on every run;
  regenerate only from a dedicated command.
- What the scripted sweeps found clean: no assertion-free tests (the 5 the AST scan flagged are
  deliberate "must not raise" tests), no tautologies, and every skip/skipif is an
  environment gate (git, curl, tic, zsh, PTY). The two data-dependent skips are
  `test_screen_components.py:84,102`: if the sample state loses its lockable row, those tests
  silently skip forever. They should assert instead.

## Dead code

- `.claude/hooks/block-no-touchy.sh` and its `.claude/settings.json` registration (tests-tools-20).
  Grepped: there is no `no-touchy/` dir, and the default project is "stonks".
- `test/conftest.py` `fixtures_dir`. `grep -rn fixtures_dir test/ examples/ ~/src/configsys-*/` →
  the definition only; `test/fixtures/` does not exist.
- `test/integration_lang_modules.sh`, `integration_script.sh` and `integration_zip.sh` have no runner
  (only docs/done/expansion-plan.md names them). Either give them runners or drop them (tests-tools-08).
- `_render_harness.Attr`: kept on purpose (its docstring explains why); it is still the fake
  palette's return type. Not dead.
- No dead functions found in tools/. Every public function in namesweep and osaudit is reached from
  its `main` or from the other tool (osaudit imports namesweep's `_CHECK`, `_run_verifier`,
  `_build_snippet`, `_native_names`, `_load_allowlist`, `_NON_REPO_FIELDS`, `UNSWEPT`). Grepped tools/,
  test/, .claude/skills/ and the plugin repos.

## ABI / interface candidates

- **A public test kit for plugin authors.** The code-plugin tests (`configsys-blender/test_blender_build.py`,
  `configsys-kicad/test_kicad_build.py`) have no fake runner to import, so they drive the real
  `Runner(pretend=True)`, and `test_blender_build.py:114` drives `Runner(pretend=False)`. If
  tests-tools-15's `test/fakes.py` were shipped as `configsys.testing` (`FakeRunner`,
  `sandbox_home()`), code-plugin authors would test against the same frozen `Runner.run` surface the
  ABI promises. It is cheap to add before collaborators write a 31st fake of their own.
- The tools' finding dicts (`compaudit._fd`, `osaudit` findings, the `docaudit` findings) are
  consumed by skills and subagents as JSON. A `"probe-failed"` / `"error"` severity is worth adding
  now (tests-tools-06/-07) so skill text can rely on it.

## Questions for the user

1. Should a hermetic, no-real-runner conftest be the default, so that every test that needs real
   `git`, `curl file://`, shells or PTYs opts in with a marker? That is a one-time sweep over about
   30 tests, and it makes tests-tools-01/-02/-04 impossible to reintroduce.
2. Should `--home` also discard an inherited `CONFIGSYS_STATE_DIR` / `CONFIGSYS_CONFIG`, so that it
   really is a sandbox (CLAUDE.md, paths.py docstring)? Or is an explicit env var meant to win? The
   test fix in -02 works either way; the product behavior is the question.
3. For the golden (-09): should EOL contexts (fedora 41/42, debian 11) stay frozen in it, or be
   replaced by the newest releases to keep the 6 MB file from growing?
4. Should the three runner-less integration scripts get runners or be retired?

## Refuted on verification

None. The checker verified the three findings in scope (every CRITICAL/HIGH, plus every
security/safety finding at MED or above): tests-tools-01, -02 and -03. All three were confirmed by
reproduction, and no severity changed. The real sudo could not run during any of these checks: a
fake `sudo` was first on PATH, a pytest plugin rewrote every `sudo` argv to it, and `HOME` was a
scratch dir.

Three sub-claims were narrowed:
- **-01:** the password prompt is visible on /dev/tty, not hidden, and the first one comes from the
  refresh's `sudo bash -c 'apt-get update'`.
- **-02:** git signing breaks 89 of 196 tests when the config lives in `~/.gitconfig`. The 105 figure
  only appears via `GIT_CONFIG_GLOBAL`. A signer with `user.signingkey` passes, but 220 test commits
  get signed with their real key.
- **-03:** 2 of the 3 test_theme call sites reach the plugin import.

tests-tools-19 (LOW safety) was outside the scope and was not re-checked.

Incidental, more evidence for -04: test_plugins.py:641 runs `plugin bless
github:nobody/does-not-exist-xyz`. That makes a real `git clone https://github.com/…` attempt, so
the targeted runs above made 7 failing github.com clones (none to api.github.com).
