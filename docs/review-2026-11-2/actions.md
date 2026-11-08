# Review: Shared actions: plans, execution, ledger, system updates

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/actions.py`, `configsys/failures.py`, `configsys/ledger.py`, `configsys/sysupdates.py`.
Context: `configsys/app.py` (`_dispatch_op`, `cmd_upgrade_system`, `cmd_fix_scope`, `cmd_picks`,
`load_pipeline`, `diagnostics`, `ensure_user_config`, `cmd_plugin remove`), `configsys/tui/menu.py`
(`OPS`, `MenuState.stage/stage_all`, `execute_plan`, `_confirm_and_execute`, `_reload`, the pin
helpers), `docs/system-updates.md`, `docs/principles.md`; also read to judge claims:
`configsys/driver.py`, `configsys/runner.py` (sudo keep-alive, pretend echo), `configsys/stranded.py`,
`configsys/installState.py`, `configsys/plugins.py` (sync outcomes, `find_decl`, `command_source_trusted`),
`configsys/routes.py` (`resolve_resilient`), `configsys/tui/screens/{components,plugins}.py`,
`configsys/drivers/{service,dotfiles,flatpak,script}.py`, `config.hu` (`keys:`), glue preludes.
Tests read: `test_run_plan.py`, `test_execute.py`, `test_ledger.py`, `test_stranded.py`,
`test_system_updates.py`, `test_failures.py`, `test_failure_issues.py`, `test_fix_cli_pretend.py`,
`test_fix_cli_followups.py`, `test_pretend_sweep.py`, `test_uninstall_queue.py`, `test_menu_state.py`,
`test_fix_drivers_d2.py`, `test_plugins.py` (replace/retarget), `test_primary_verify.py`.

Reproductions ran against sandbox homes under `$S` =
`$RUN/scratch/actions/` (`$RUN` = this review's scratchpad run dir), scripts in `$S/scripts/`. Nothing
ran as root; no real install. Commands are quoted as run (`cs` = `.venv/bin/python -m configsys`).

## Carried over from docs/review-2026-09/app-cli-actions.md (+ README open items in scope)

Only items whose code is in this area (actions.py / ledger.py / sysupdates.py / failures.py, or whose
fix lands there) are settled here; app.py-only items (argparse help, `_STATUS_LABEL`, `_send_report`,
`app.py` split D9, …) belong to the app-cli area. A5/A7/A10, C2, C5, D6–D9 and Tier F have no code here.

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] the op-execution loop exists twice (`_dispatch_op` vs `menu.execute_plan`) — D3 | fixed | `cc7bbe9` (actions.run_plan; `menu.execute_plan` is a one-line call, actions.py:198) |
| B10 TUI batch persists only the last failure; no set-version branch | fixed | `cc7bbe9` + `40b5eaf` (`reportgen.record_run` from run_plan; `!` page lists failures) |
| [MED] TUI never invalidates the glue location cache (B4) | fixed for pins/picks/sync; **open** for `machine use` | `468a6d3` (`invalidate_location_cache` inside `set_included`, `plugin_sync`); `set_machine_active` and most settings still don't → actions-10 |
| [MED] `cmd_plugin trust/untrust` re-implements `actions.plugin_trust*` | fixed | `f066814` — app.py:3163-3172 now call `actions.plugin_trust_all/plugin_trust/plugin_untrust` (the stray `app._find_decl` is app-cli's) |
| [MED] pin write logic lives in app.py and is re-implemented in the TUI | open | no `actions.set_pin`; app.py:2284-2400 vs menu.py:1766 → actions-27 |
| [LOW] C4 `diagnostics()` re-resolves the world 2–3× per command | obsolete (as perf) | measured: `actions.dotfiles_units` resolve = 9–18 ms on 156 picks; `_reload` diagnostics is one call. The same code has a different bug → actions-13 |
| [LOW] `cmd_orphans --ignore` bypasses `actions.ignore_orphan`; no `--unignore` | open | app.py:1989-2000 still calls `set_config_setting` directly → actions-28 |
| [LOW] no CLI surface for the `uninstall:` queue | open | `stage_uninstall` 0 CLI callers; `clear_uninstall` 0 callers anywhere → actions-29 |
| [MED help drift] actions.py docstring "active profiles" | open | now `dotfiles_units` actions.py:1632 → actions-32 |
| D3 `build_plan` half ("--no-deps / auto-tighten to the TUI for free") | open | app.py:848-853, 863-872 have no TUI counterpart → actions-16 |
| D4 `LedgerLockMixin` | fixed | `3fe0f4a` (lock/unlock defaults hoisted to `Driver`, run_plan records the ledger). The `ModuleDriver` half is drivers-lang's |
| D5 settings registry | open | still 6 tables across actions/layers + config getters → actions-17 (same as config-layers-20) |
| [MED] test gaps in the op loop | partly fixed | test_run_plan.py now covers advisory / verify-after-fail / every-failure / set-version / sudo-once; ^C, a raising op, lock ledger paths, skips still untested → Test gaps |
| parity: set-version has no TUI trigger | open | "plumbing is ready" (README progress) — still no key → folded into actions-16 |

## Cross-cutting themes

- **The action layer's conventions are per-writer etiquette, not structure.** Every writer re-decides
  pretend, shadow-guarding, cache invalidation, validation and "did the sync work": theme writes skip the
  shadow guard (actions-12), 5 layout-changing settings skip the cache invalidation (actions-10), bool
  settings skip validation (actions-11), `plugin_update` skips sync-first (actions-08), `plugin_bless` uses
  a substring test that misses `unsigned` (actions-08), and the pretend result has three shapes
  (actions-35). A `Setting` registry + one writer helper (`_write(ctx, key, fn)`: pretend → shadow-guard →
  validate → write → invalidate) would make each of these a table column instead of a habit.
- **Destructive file operations in actions don't read the git state they destroy.** `plugin remove`,
  `plugin add --replace`, and the TUI Plugins `x` rmtree a clone without checking for unpushed commits or
  local edits (actions-01), while `primarygit` next door counts exactly those (`state().ahead/dirty`).
- **run_plan is the one per-unit loop, but the batch policy around it is still split.** Lock enforcement
  (actions-02), plan building / auto-tighten / no-deps / set-version (actions-16), System Updates bulk apply
  (actions-14), fix-scope (actions-15), the uninstall-queue drain, and the exit status of skipped steps
  (actions-18) live in app.py or menu.py, each with its own gaps.
- **Shared mutable state, last-writer-wins.** The ledger is loaded once and saved whole (actions-03/04),
  the Resolver keeps "the last resolve's" record that any later resolve overwrites (actions-13), and the
  System Updates thread reads the unsynchronized lazy `Context` (actions-24).

## Findings

### actions-01 [CRITICAL] safety — `plugin remove`, `plugin add --replace` and TUI Plugins `x` delete a clone's unpushed commits and local edits (your primary's picks, settings, captured dotfiles) without a word
`configsys/actions.py:1247-1269` (`plugin_add` retarget), `:1323-1345` (`plugin_remove`),
`configsys/tui/screens/plugins.py:318-321` (`remove` → `actions.plugin_remove`, no confirmation; bound to
`x` in `config.hu:277`). A retarget renames the old clone to `<name>.configsys-retarget-bak`, clones the
new source, then `shutil.rmtree(backup)` on success (`:1268-1269`; an older backup is rmtree'd unread at
`:1256-1257`). `plugin_remove` rmtrees the synced dir. Neither looks at `git status` / commits not on any
remote — which for the PRIMARY are configsys's own journal commits of your edits (`primary-push: ask` is
the default, so "N changes not pushed yet" is the normal state) and its `dotfiles/` store — capture's
default home (drivers/dotfiles.py:131-140); once a captured config is installed, `~/.config/<app>` is a link
into that store (the pre-capture original survives only as a `.pre-configsys` backup), so the links dangle
and every edit made since is gone.
configsys itself prompts the destructive path: a same-name add is refused with "re-run with --replace to
swap it". `--replace` also drops `primary: true` (the old decl is removed, the new one is added as a plain
plugin), so the primary's machine settings — your picks — silently stop applying. On the Plugins screen
the same key that only *stages* a removal on Components (`x`) deletes immediately.
**(reproduced)** `cs --home $S/homeT plugin bless $S/srcplug; cs … theme set colors.accent '#00ff00'`
(→ "2 changes not pushed yet") then `cs … plugin add $S/alt/srcplug --replace` → `cloned srcplug / added
…/alt/srcplug`, exit 0; afterwards `git log` of the clone = only `82ceafd A`, no backup dir, decl has no
`primary: true`, `plugin list` shows no `[primary]`. And `cs --home $S/homeV picks add btop` (→ commit
`eb5c4cf picks add btop`, "1 change not pushed yet") then `cs … plugin remove srcplug </dev/null` →
`removed …/srcplug`, exit 0, plugins dir empty. A dirty third-party clone (`$S/homeU`, ` M plugin.hu`) was
removed the same way.
**Fix:** before any rmtree of a clone, ask git (`status --porcelain`, `log --branches --not --remotes`,
`stash list`; `primarygit.state` already computes ahead/dirty for the primary) and refuse with a list of
what would be lost unless `--force` (TUI: a confirm popup naming it, always for the primary). On
`--replace`, keep a clone that holds local work as `<name>.replaced-<date>` instead of deleting it, and carry
`primary`/`ref` from the replaced decl to the new one. Add a confirm to TUI Plugins `remove`. **Effort:** M.
**Tier:** A.
**Verified:** CONFIRMED (reproduced). The sandboxes are new, under `$V` = `$RUN/scratch/verify-actions` (`cs` =
`.venv/bin/python -m configsys --os pop`). **remove:** `cs --home $V/home-rm plugin bless $V/src/myprim; cs … picks add btop` →
"1 change not pushed yet"; the clone's log is `19fd536 picks add btop` / `84fd05c init myprim` (`## main...origin/main [ahead 1]`).
Then `cs … plugin remove myprim </dev/null` → `removed …/src/myprim`, exit 0, `plugins/` empty, and the source repo
still holds only `84fd05c`. **`--replace`** (`$V/home-replace`): a plain `plugin add $V/src/alt/myprim` → "…re-run with
--replace to swap it…". With `--replace` → `cloned myprim` / `added …/alt/myprim`, exit 0. Afterwards the clone's log
is only `392ecf0 init alt/myprim` (the unpushed `c828d46 picks add btop` is gone), there is no `.configsys-retarget-bak`,
the decl is `{ source: …/alt/myprim }` with no `primary: true`, and `picks list` → `picks for this-machine (0)`.
**TUI** (`$V/home-tui`): keys `3` `x` `Q` under `script` → note `removed …/myprim`; the plugins dir and the decl are
gone and commit `f8f5a1f` is lost. `screens/plugins.py:318-321` has no confirm; only the history undo opens a
`_popup_choose`. **Worse than reported:** a primary made by `plugin init` is authored in place. Its `source:` is
`plugins/<name>` itself, it has no remote, and init MOVES the local dotfiles store into it. In `$V/home-init`:
`plugin init mine` (moved `dotfiles/foo.cfs/foorc`), `picks add btop`, `plugin remove mine` → exit 0, and
`find $V/home-init -name foorc` finds nothing. The only copy of the user's captured config and picks is gone. There
is no guard anywhere, and no test: test_plugins.py:518 removes only a non-primary. Severity stays CRITICAL.

### actions-02 [HIGH] correctness — a version lock kept in the ledger is not honored: `u` / `U` / `i` and `configsys upgrade <name>` upgrade a locked unit
`configsys/actions.py:198-330` (`run_plan` never consults `ledger.is_locked` / `drv.is_locked`),
`configsys/tui/menu.py:36` (`'upgrade': … s.supported and s.outdated` — `outdated` ignores `locked`), used
by `stage` (:444-460, incl. `i`'s make-current fallback) and `stage_all` (:462-492). The driver contract
says the opposite: "most drivers have no NATIVE hold (the ledger carries the intent, honored by the op
loop)" (driver.py:461-465, :536-540), and README calls the ledger the lock store for every driver without a
native hold — tarball, cargo, pip/pipx, npm, gem, go-install, source, script, appImage, … Only
`upgrade --picks` respects it, by accident of `status == 'outdated'` (app.py:1043-1044). For native holds
the manager itself refuses (`apt-get install --only-upgrade -y <held>` errors), so the user sees a
confusing FAILED instead of "locked".
**(reproduced)** `$S/scripts/locked_upgrade.py` → `status: locked | outdated: True` / `U (stage_all upgrade)
staged: 1 {'tarball\\lazygit': 'upgrade'}` / `run_plan executed: ['upgrade lazygit'] | outcome ok: True |
still locked in ledger: True`. CLI: `cs --home $S/homeL pin set lazygit tarball; cs … lock lazygit` (ledger
`locked: true`) then `cs … --pretend upgrade lazygit` → `upgrade tarball\lazygit (pkg: lazygit) … -> ok
(pretend)`.
**Fix:** in run_plan, an `upgrade` of a unit locked in the ledger (or natively) becomes a non-fatal
`locked` outcome ("held at X — `configsys unlock <comp>` first"), never a driver call; in menu.py
`'upgrade': … s.outdated and not s.locked`. Decide set-version on a locked unit (Questions). **Effort:** S.
**Tier:** B.
**Verified:** CONFIRMED (reproduced), end to end with the real script driver and ledger. The sandbox is `$V/home-lock`
with a PATH that has no sudo. Its top config defines `lockme` via `script`: version-cmd `cat $V/lockme.ver`, latest-cmd
`echo 2.0`, upgrade-cmd writes `2.0`. `cs … install lockme; cs … lock lockme` → state.hu `locked: true`, and `inspect`
→ `script\lockme  locked  1.0  2.0 [locked]`. `cs … upgrade --picks --yes` → "nothing to do — every pick of this box
is up to date (locked picks are left alone)", so holding is the stated intent. But `cs … upgrade lockme` →
`upgrade script\lockme (pkg: lockme) ... -> ok`, exit 0: the version file now reads `2.0` and the ledger still says
`locked: true`. **TUI:** with the file reset to 1.0, keys `U` `X` `y` → "About to execute: upgrade script\lockme
(pkg: lockme)" / `Proceed? [y/N] y`, and the file reads `2.0`. The code readings hold: the `menu.py:36` predicate
ignores `locked`, `stage`'s `i`→upgrade fallback uses that predicate, and neither run_plan nor `_dispatch_op` checks
`ledger.is_locked`. No test covers a locked, outdated unit. HIGH stays.

### actions-03 [MED] correctness — the ledger is last-writer-wins across processes: a TUI that is open drops locks and receipts written meanwhile by a CLI run
`configsys/ledger.py:66-75` (`save` writes the whole in-memory record set), `configsys/actions.py:326-327`;
the TUI holds the ledger from `load_pipeline` (menu.py:1627, :4757) until its next `X`, and the CLI loads it
before resolving/confirming/refreshing (app.py:783). Whatever the other process saved in between is
overwritten: a lost lock means the unit is later upgraded (actions-02's harm again); a lost receipt makes
a stranded install unfindable (the receipt's whole purpose, docs/stranded-installs.md).
**(reproduced)** `$S/scripts/ledger_race.py` (two `Ledger.load`s, a CLI `lock` through run_plan, then a TUI
`install` through run_plan) → `after CLI lock   : locked` / `after TUI install: NOT locked | btop receipt:
True`.
**Fix:** run_plan records the keys it changed (lock set/cleared, receipt set/cleared) and saves through
`Ledger.update(paths, changes)`: take an `fcntl.flock` on `state.hu.lock`, re-read, apply only those keys,
write atomically (actions-04). **Effort:** S. **Tier:** B.

### actions-04 [MED] correctness — `state.hu` is written in place and loaded intolerantly: a truncated ledger bricks every command
`configsys/ledger.py:66-75` (`paths.ledger_file.write_text(...)` — no temp + `os.replace`), `:36-42`
(`troveio.load` raises `ConfigError`; only the receipt pass is guarded). A crash, ^C or ENOSPC mid-write
leaves a partial file; from then on `load_pipeline` (inspect, install, the TUI) dies at startup until the
user hand-edits `~/.config/configsys/state.hu`.
**(reproduced)** wrote `{ "apt\\btop": { locked: true  managed: fal` to `$S/home/.config/configsys/state.hu`;
`cs --home $S/home --os pop inspect` and `cs … --pretend install btop` both print `…/state.hu: Trove has
syntax errors: [line 4, column 21: UNEXPECTEDEOF]` and stop.
**Fix:** write `state.hu.tmp`, fsync, `os.replace`; on a parse error move the file aside
(`state.hu.corrupt-<ts>`), warn once on the `!` page, and continue with an empty ledger (or refuse only
writes). **Effort:** S. **Tier:** B.

### actions-05 [MED] correctness — run_plan is not exception-safe: one raising op loses the batch's receipts and locks, its failure record, and leaves the sudo keep-alive running
`configsys/actions.py:240-268` catches only `KeyboardInterrupt`; `end_sudo` (:325), `ledger.save`
(:326-327) and `reportgen.record_run` (:328-329) are not in a `finally`. Route data can trigger it today:
`service._runit` raises `ValueError` for a unit/`runit:` name failing `_SAFE` (drivers/service.py:47-58,
reached from install/uninstall), and any trusted code-plugin driver bug (or a `lock()` returning `None`,
:251-252) does the same. The TUI's `execute` handler doesn't catch it (screens/components.py:388), so the
TUI dies with earlier successful installs unrecorded.
**(reproduced)** `$S/scripts/raise_midplan.py` → `install tarball\good … -> ok` / `raised: ValueError service
bad: unsafe runit name(s)` / `end_sudo called: False | ledger file exists: False | receipt for good (already
installed): False`.
**Fix:** wrap the dispatch in `except Exception as e: res = Result.fail(f'{type(e).__name__}: {e}')` (a
normal failure row, batch continues), and move end_sudo / save / record_run into `try … finally`.
**Effort:** S. **Tier:** B.

### actions-06 [MED] correctness — verify-after-fail reads a failed REINSTALL or forced REBUILD as "installed with a warning" and exits 0
`configsys/actions.py:110-129` (`installed_despite_failure`: for `install`, any present version counts),
`:289-302` (that branch sets neither `n_fatal` nor `rc_code`). README's source-rebuild idiom `configsys install
--no-deps folly` runs `install` on an installed unit; when the build fails the OLD build is still there, so
the run says "the package itself is present", exits 0, and `_failure_diagnostics` hides
installed-with-warning records from the `!` page (app.py:928-930). Same for `configsys install X` on an
installed X whose re-download fails.
**(reproduced)** `$S/scripts/rebuild_fail.py` → `-> installed WITH A WARNING (exit 2) — a recommended package or
post-install step failed; the package itself is present.` / `outcome ok: True | with warning: True |
n_fatal: 0 | exit code: 0`.
**Fix:** probe the unit's version before an `install` op (only when the step may be a reinstall: the plan
builder knows from `states`, or one `get_version` per install step) and treat "present now" as success only
if it was absent before or the version changed; otherwise a real failure. **Effort:** S. **Tier:** B.

### actions-07 [MED] security — receipts drop the binding's source, so a removed or untrusted plugin's `via: script` commands still run as trusted
`configsys/ledger.py:102-108` (`set_receipt` stores via/name/fields — the fields carry `install-cmd`,
`version-cmd`, `uninstall-cmd` — but not `rc.source`), `configsys/stranded.py:69-74`
(`_rc_from_receipt` builds an rc with `source=''`), driver.py:180-188 (`command_trusted` →
`plugins.command_source_trusted(paths, '')` → "core / user — trusted"). `stranded.augment` runs on every
inspect and TUI start (a safety check, always on) and probes each receipt (stranded.py:131-140) — running
the receipt's `version-cmd`; installing the component then swaps out the stranded unit with the receipt's
`uninstall-cmd`. Who: the author of a plugin whose script binding you trusted and installed. When: after you
`plugin untrust` / `plugin remove` it (exactly what you do on learning it is malicious) or it changes
content (trust lapses to `changed`). Already possible without this bug: everything while it was trusted
(its install-cmd ran) — so the delta is that revoking trust doesn't stop its declared commands.
**(reproduced)** `$S/scripts/receipt_trust.py` writes a receipt the way run_plan does for
`script\btop` (`source` set on the rc to `plugins/evilplug/r.hu`; `receipt keeps the binding source? False`),
then `cs --home $S/homeR --os pop -q inspect` → `⚠ switch btop: installed via script (btop 1.0) — routes no
longer offer that method…` and `$S/PWNED` exists (the receipt's `version-cmd` ran).
**Fix:** record `source` in the receipt and restore it in `_rc_from_receipt`, so `command_trusted` gates on
the plugin's current trust (a removed plugin → untrusted → probe skipped, the row reads "installed via an
untrusted/removed plugin's script — remove by hand or re-trust"). **Effort:** S. **Tier:** A.
**Verified:** CONFIRMED (reproduced), but the trigger is narrower than stated. Run end to end with real CLI commands
in `$V/home-receipt2`, with a PATH that has no sudo. The top config defines `zzcfsfake` (`via: native`; no such
package on this system). Plugin `$V/src/evilplug2` adds a `via: script` binding whose version-cmd appends a line to
`$V/evil-runs.log`. `plugin add --local`, `plugin trust evilplug2`, `pin set zzcfsfake script`, `install zzcfsfake`
→ ok. The state.hu receipt has `version-cmd` but no `source`; the log has 1 line, from the legitimate post-install
probe. **`plugin untrust evilplug2` alone does NOT trigger it:** after `inspect`, pinned and then unpinned, the log
still has 1 line. The binding is still a candidate, so `stranded.find`'s `is_current` skips the receipt, and the live
probe is gated on trust. **`plugin remove evilplug2`** then `inspect` → `⚠ switch zzcfsfake: installed via script
(zzcfsfake 1.0) — routes no longer offer that method…`, and every inspect adds a line (2, then 3).
`$V/scripts/receipt_swap_plan.py` builds the `install zzcfsfake` plan and executes nothing. It prints `remove
script\zzcfsfake source='' command_trusted=True uninstall-cmd=True` alongside `evilplug2 synced dir exists: False`
and `trust store: {}`; building the plan ran version-cmd again (4 lines). So the bug fires once the binding stops
being a candidate while the component is still known:
- the plugin is removed while another layer still defines the component (core, or another plugin, as with
  configsys-source's additive `via: source` bindings);
- a content update drops or renames the binding;
- or a gate removes it.

It does not fire on `untrust`, or on `changed` with the binding intact. A receipt can only hold commands from content
that was trusted at install time: an untrusted install fails before `set_receipt`. So the delta is exactly that
revocation doesn't stop them, and MED stays. The proposed fix works: `plugin_of_source` maps a path by prefix, and a
removed dir has no identity, so it reads as untrusted.

### actions-08 [MED] correctness — `plugin update --ref` re-pins before syncing and reports success when the sync fails; `plugin bless` proceeds on an unsigned primary
`configsys/actions.py:1378-1395` (`plugin_update` writes `target['ref']` + `set_declared` before
`plugin_sync`, never checks the result, returns ok), `:1434-1451` and `:1262` (`plugin_bless` /
`plugin_add` test `'failed' in results[0][1]`, which misses `unsigned`; the docstring promises "only on a good
sync does it declare + mark primary"). plugin_add is sync-first; plugin_update is declare-first — every later
`plugin sync` fails until the user notices.
**(reproduced)** `cs --home $S/home2 plugin add $S/srcplug --ref v1 --local; cs … plugin update srcplug --ref
nosuchref` → `failed srcplug` / `configsys: re-pinned …/srcplug @nosuchref`, exit 0; the decl now reads
`ref: nosuchref` and `cs … plugin sync` → `failed srcplug`. And `cs --home $S/home3 config set primary-verify
signed; cs … plugin bless $S/srcplug` → `unsigned srcplug` / "not synced — its newest commit has no good
signature…" / `configsys: blessed srcplug as primary (its machine settings now apply)`, exit 0; the decl has
`primary: true` and nothing is on disk.
**Fix:** one `plugins.sync_succeeded(action)` predicate over the outcome set (`ok/cloned/updated/local/ahead/
kept` vs `failed…/unsigned/locked/diverged`), used by add/bless/update; plugin_update syncs
`{**target, 'ref': ref}` first and writes the decl only on success, returning `ok=False` otherwise.
**Effort:** S. **Tier:** B.

### actions-09 [MED] correctness — `plugin remove` / `plugin update` of a transitive plugin edits a THIRD-PARTY plugin's checked-out manifest
`configsys/actions.py:1185-1200` (`_locate_decl` searches every synced plugin's `plugins:`, not just the top
config and the primary), used by `plugin_remove` (:1328-1334) and `plugin_update` (:1353, :1378-1380). The
edit dirties a clone configsys doesn't own: its content hash changes (code trust → `changed`, a `sha256:`
pin → quarantined), later syncs report `kept`, and the CLI then says "`configsys plugin push` shares the
removal with your other machines" (app.py:3120-3122) though only the primary is pushable.
**(reproduced)** `$S/plugA` declares `plugins: [ srcplug ]`; `cs --home $S/homeU plugin add $S/plugA --local`
(→ `cloned plugA` / `cloned srcplug`), `cs … plugin remove srcplug` → `removed …/srcplug from plugA` / "`configsys
plugin push` shares the removal…", and `git -C …/plugins/plugA status --short` → ` M plugin.hu` (diff:
`plugins: [ … ]` → `plugins: []`).
**Fix:** `_locate_decl` returns only the top config or the primary's manifest; a decl owned by another plugin
is refused with "srcplug is declared by plugA — remove or lock plugA, or override in your config". **Effort:**
S. **Tier:** B.

### actions-10 [MED] correctness — settings that move installs keep the shell's 1-hour glue-locations cache: `dirs.*`, `scope`, `machine use`, `disabled-drivers`, `driver-preference`
`configsys/actions.py:885-922` (`set_config_setting` invalidates only for `locations`, :904-905),
`:619-622` (`set_machine_active`), `:925-950` (`move_config_setting`). The preludes trust the cache for 60
minutes (`find "$_cs_cache" -mmin -60`, glue/shell/zsh/00-configsys.zsh:32-37), so after `config set dirs.app
…` + reinstall, new shells point PATH at the old dir for up to an hour. The docstring at :26-29 says the
writers call it "so neither the CLI nor the TUI can forget it" — most do forget. (2026-09 noted the
`machine use` half.)
**(reproduced)** with a `glue-locations.tsv` planted before each command in `$S/homeM`: `KEPT stale cache
after: config set dirs.app myapps` / `… config set scope system` / `… machine use this-machine` / `… config
set disabled-drivers tarball` / `… config set driver-preference tarball`; `invalidated after: config set
locations btop=/opt/x`.
**Fix:** invalidate on every successful `set_config_setting` / `move_config_setting` (the next shell rebuilds
it once — cheap), or give each setting an `affects_layout` flag in the registry (actions-17). **Effort:** S.
**Tier:** B.

### actions-11 [MED] correctness — `set_config_setting` writes invalid values silently: `reboot-advice ture` turns the reboot advisory OFF
`configsys/actions.py:881-882, 913-915` (bool kind: anything not truthy is written as `false`),
`:916-920` (choices only for keys in `layers.SETTING_CHOICES`, which lacks `scope` and
`installer-shell-writes`), `:892-901` (`dir` kind: no absolute/`~` check). The command echoes the typo as
if it were stored. A typo'd `scope` silently means user scope (driver.py:143 compares `== 'system'`); a
relative `dirs.user` makes `scope_base` CWD-relative (paths.py:201-204) — the base tarball later `rm -rf`s
under. `check` says nothing about any of them. (Same root as config-layers-06 from the reading side; this is
the writer.)
**(reproduced)** `cs --home $S/home3 config set reboot-advice ture` → `set reboot-advice = ture`, then
`config get reboot-advice` → `false`; `config set scope sytem` / `config set installer-shell-writes alow` /
`config set dirs.user relative/dir` all exit 0 and `check` is silent.
**Fix:** bool kind accepts exactly true/false/yes/no/on/off/1/0 (else `ValueError`, like choices); add
`scope: (user, system)` and `installer-shell-writes: (block, allow)` to the choices; `dir` values must be
absolute or start with `~`; echo the stored value. **Effort:** S. **Tier:** B.

### actions-12 [MED] correctness — theme edits land in the primary even where your top config overrides that key: "set … (in <primary>)", nothing changes
`configsys/actions.py:960-982` (`set_theme_value` → `edit_target`), `:1059-1070` (`load_theme`),
`:1073-1087` (`copy_page_theme` reads only the edit target's pages). `edit_target`'s own docstring
(:333-339) warns that "an edit here is only effective when a higher layer doesn't shadow it" — settings,
picks and dispositions use `_nature_target`'s shadow guard; theme writes don't. The TUI Theme screen uses the
same default target (tui/screens/theme.py:259-366), so every edit of a shadowed color is a silent no-op
(`unset` likewise leaves the top-config value in force).
**(reproduced)** `$S/homeT` with a blessed primary: `cs … theme set colors.accent '#ff0000' --local; cs … theme
set colors.accent '#00ff00'` → `set colors.accent = #00ff00 (in srcplug)`; effective `ctx.config.theme()['colors']`
→ `{'accent': '#ff0000'}`.
**Fix:** resolve the target per dotted key with the same rule as `_nature_target` (the writable layer that
already sets the key wins; else the primary); `copy_page_theme` reads the merged theme. **Effort:** S. **Tier:** B.

### actions-13 [MED] correctness — `dotfiles_units` re-resolves the picks without the pipeline's pins and overwrites the Resolver's record of the real resolve
`configsys/actions.py:1631-1639` calls `ctx.routes.resolve_resilient(requested)` with no soft (detected) or
floor (auto-tighten) pins; `Resolver.resolve_resilient` stores `tighten_pins`, `dropped_soft_pins` and
`provider_rules` on the shared Resolver (routes.py:632, 643-644). It runs from `diagnostics(states)` at the end
of every `load_pipeline` and TUI `_reload` (app.py:272-274), so afterwards `where`'s "providers … by
standing" line (app.py:1728-1734) and `Resolver.context()`'s floor-pin gating (routes.py:600-605, which
CLAUDE.md requires to agree with resolution) describe a resolve that never ran. The Dotfiles/Glue screens and
the dotfiles diagnostics can also see a different unit set than Components (a detected provider pulls
different `-glue`/`-dotfiles` companions). (`plan_companion_cleanup`, installState.py:438, has the same
side effect.) The 2026-09 perf concern (C4) is gone: this resolve costs 9–18 ms.
**(reproduced)** `$S/scripts/resolver_clobber.py` → `pipeline resolve: dropped_soft_pins = {'wget': …} |
tighten_pins = {'curl': 'tarball'}` / `after dotfiles_units: dropped_soft_pins = {} | tighten_pins = {}` /
`provider_rules changed: True`.
**Fix:** keep the pipeline's `units` on the Context and have `dotfiles_units` filter them (resolve only when
no pipeline ran, e.g. `dotfiles status`); longer term `resolve_resilient` returns its record instead of
mutating the Resolver. **Effort:** S. **Tier:** B.

### actions-14 [MED] reuse — the System Updates apply step exists twice and the CLI copy records no failures
`configsys/app.py:1192-1205` (`cmd_upgrade_system` loops `upgrade_all` itself) vs
`configsys/sysupdates.py:196-211` (`apply_bulk`) + `configsys/tui/menu.py:796-809` (the TUI turns its
results into OpOutcomes and `reportgen` records inline). Drift: the CLI never calls `reportgen.record_run`, so a
failed `apt upgrade` from `upgrade --system` never reaches the `!` page or `configsys report`
(`_failure_open` special-cases `system-updates\` records precisely for this, app.py:907); a `None` result is
"skipped" in the CLI but "FAILED: bulk upgrade failed" in the TUI; neither handles ^C (in the TUI it kills the
session before the component ops). And `apply_bulk` ends with `start_scan` (:210) although its only caller
invalidates and rescans after the component ops — a full gather (apt list, 2× flatpak remote-ls, snap)
runs concurrently with the installs and is thrown away.
**(reproduced)** `$S/scripts/sysup_cli_record.py` (gather/driver stubbed, `upgrade_all` → exit 100) → `-> apt
upgrade FAILED (exit 100)` / `CLI exit: 100 | failure records saved: []`.
**Fix:** `sysupdates.apply_bulk(ctx, managers, *, refresh, on_line) -> [OpOutcome]` that records failures
(not under pretend), handles ^C like run_plan, and leaves rescanning to the caller; both surfaces render
its outcomes. **Effort:** S. **Tier:** D.

### actions-15 [MED] reuse — `fix-scope` (and the Dotfiles/Glue screens) still execute outside run_plan
`configsys/app.py:988-1020` calls `drv.reconcile_scope` (install-at-target + uninstall-old) directly: no
shell-writes guard around a real install, no up-front sudo for a batch that may need it, no failure record for
`report`/`!`, no ^C handling, and the unit's install receipt keeps the OLD `scope` field
(`set_receipt` copies `rc.fields`, ledger.py:107), which a later stranded removal acts on. The Dotfiles/Glue
screens (`tui/screens/dotfiles.py:183-218`, `glue.py:204-219`) and `glue override` (app.py:4221) call
`drv.install/uninstall` directly too — acceptable for config drivers (no receipts, own pretend), but their
failures never reach `report`.
Verified by reading `app.py:988-1020` and `ledger.py:102-108`.
**Fix:** a `fix-scope` op in run_plan (dispatching to `reconcile_scope(rc, detected, target)`, refreshing the
receipt), with `cmd_fix_scope` building the plan; optionally route the config-driver screen ops through it
for the failure record. **Effort:** M. **Tier:** D.

### actions-16 [MED] parity — plan BUILDING is still two implementations (the unfinished half of D3)
`configsys/app.py:780-879` (`_dispatch_op`: stranded removes, auto-tighten resident upgrades :848-853, the
floor heads-up :863-872, `--no-deps` `_targeted_plan`) vs `configsys/tui/menu.py:756-771`
(`_confirm_and_execute`: `plan_with_swaps` + `expand_plan` only). With `auto-tighten: true`, CLI `install
goimports` upgrades a resident go first; TUI `i goimports` + `X` doesn't, and fails deep in the run — the
floor advisory is on the `!` page, but not on the confirm screen (verified by reading; menu.py has no
`resident_upgrades_probed` / `flooradvise.advise` call). The TUI has no set-version, fix-scope or `--no-deps` trigger although run_plan supports them.
Conversely only the TUI drains the `uninstall:` queue after a successful remove (menu.py:813-822), so
`configsys remove foo` leaves `foo` queued.
**Fix:** `actions.build_plan(ctx, base_plan, units, *, no_deps=False) -> (plan, units, advisories)` (swaps,
auto-tighten, expand/targeted ordering, floor advisories) and a shared post-run step (queue drain) used by
both; then a TUI `set-version` entry in the `v` picker and a `fix-scope` action on the scope-warning row.
**Effort:** M. **Tier:** G.

### actions-17 [MED] refactor — settings knowledge is still split across six tables (D5, open)
`configsys/actions.py:629-758` (`CONFIG_SETTINGS` kind/desc/man, `SETTING_NATURE`, `_SETTING_GETTERS`) +
`configsys/layers.py:34-56` (`MACHINE_SETTING_SECTIONS`, `SETTING_CHOICES`, `TOP_CONFIG_ONLY`) + the
config.py getters, with seven boolean parsers using different truthy sets (actions.py:881, ledger.py:20,
config.py:257/264, routes.py:175, tui/theme.py:237, drivers/snap.py:32). `layers.machine_setting_sections()`
lazily imports actions under a bare `except` that hides an import failure. actions-10 and actions-11 are this
drift. Same finding as config-layers-20 — fix once.
Verified by reading the tables and grepping the bool parsers.
**Fix:** one `SETTINGS = {key: Setting(kind, nature, choices, default, getter, top_only, affects_layout,
desc)}` in a leaf module that layers, config and actions read. **Effort:** M. **Tier:** D.

### actions-18 [LOW] correctness — a skipped step (no driver, an untrusted plugin's driver, a dangling row) exits 0 and says "not yet supported"
`configsys/actions.py:219-226` set neither `rc_code` nor `n_fatal`. `configsys install blender-5.2` with the
plugin's code untrusted prints `skip …: driver "blender-build" not yet supported` and exits 0, while
inspect already knows the real reason (installState.py:228-233: "comes from a plugin you haven't trusted yet —
`configsys plugin trust <name>`").
**(reproduced)** `$S/scripts/skip_exit.py` → `skip blender-build\blender-5.2: driver "blender-build" not yet
supported` / `rc_code: 0 | n_fatal: 0 | failures recorded: 0`.
**Fix:** `rc_code = rc_code or 1` for skips; reuse the untrusted wording via `ctx.plugin_pending_vias`.
**Effort:** S. **Tier:** B.

### actions-19 [LOW] correctness — the failure classifier calls a 404 "network" (retried 3×, "check connectivity"), misses 403, and matches "line 404"
`configsys/failures.py:37-54`: rules are tried in list order, so the generic `Failed to fetch|Cannot
download` NETWORK rule (:43-45) wins over the 404 rule (:52-54) for apt's `E: Failed to fetch … 404 Not
Found` (a stale index) and dnf's `Cannot download repomd.xml: Status code: 404` (a vendor repo with no tree
for a new Fedora yet — the `/update-os` moment). NETWORK isn't `DEFINITIVE`, so `retry_transient` retries 3×
before the refresh diagnosis says "check connectivity/proxy". `returned error: 403` is unclassified (git) or
NETWORK (curl); `\b404\b` matches any token "404". The module docstring says classification "never changes
control flow", but `retry_transient` (:90-102) decides retries with it.
**(reproduced)** `classify()` on those strings → `network-unreachable` (apt 404), `network-unreachable` (403
Forbidden), `network-unreachable` (dnf Status code: 404), `None` (git 403), `not-found/moved` ("failed to build
at line 404").
**Fix:** a status-code rule (`\b(?:Status code:|returned error:|^\s*)\s*40[34]\b|\s40[34]\s+(?:Not
Found|Forbidden)`) before the generic NETWORK rule, mapping 404 → NOT_FOUND, 403 → AUTH; anchor the bare
`404`; fix the docstring. **Effort:** S. **Tier:** B.

### actions-20 [LOW] correctness — `machine rm` deletes the machine this box is set to; the install set silently becomes empty
`configsys/actions.py:577-581` (`remove_machine` → `set_included_clear_machine`, label `'picks'`). No guard
for `name == current_machine()`, so `machine:` is left naming a machine with no column and the CLI prints
`configsys: picks`.
**(reproduced)** `cs --home $S/homeM machine add laptop; … machine use laptop; … picks add btop; … machine rm
laptop` → `configsys: picks`, exit 0; `machine list` → "no machines defined … `machine: laptop` is selected but
undefined"; `check` → "this box's install set is empty".
**Fix:** refuse (or require `--force` and clear `machine:`) when removing the current machine; return a real
label ("removed machine laptop (its N picks)"). **Effort:** S. **Tier:** B.

### actions-21 [LOW] correctness — `set_included` accepts any string: `picks add profile:<name>` stores the literal token
`configsys/actions.py:432-464`; caller `app.py:1971`. CLAUDE.md promises `profile:<name>` expansion on CLI
ops; here the token is written as a pick, and a typo'd name is accepted too. Both surface only later as an
`unroutable` error row.
**(reproduced)** `cs --home $S/homeQ picks add profile:compression-tools` → `profile:compression-tools picked on
this-machine`; `inspect` → `✗ unroutable profile:compression-tools: unknown component: profile:compression-tools`.
**Fix:** expand `profile:` in `cmd_picks` (reuse `_expand_profile_args_detail`), and have `set_included(on=True)`
refuse a name that is neither a known component nor a valid profile token. **Effort:** S. **Tier:** B.

### actions-22 [LOW] correctness — re-running `plugin add <source>` without `--ref` silently drops its version pin
`configsys/actions.py:1302` (`plugins.upsert_decl(cur, source, ref)` sets `ref = None` on an existing decl),
`:1314` (message "re-pinned X" with no ref). The sync also moves the clone to the default branch.
**(reproduced)** `cs --home $S/homeW plugin add $S/srcplug --ref v1 --local` then `… plugin add $S/srcplug
--local` → `re-pinned …/srcplug`; the decl is now `{ source: …/srcplug }`.
**Fix:** keep the existing ref when none is given (say "already declared @v1"); unpinning should be explicit
(`plugin update --ref <branch>`). **Effort:** S. **Tier:** B.

### actions-23 [LOW] safety — `theme save <name>` doesn't validate the name: `../..` writes outside the plugins dir
`configsys/actions.py:1039-1056`: `pdir = plugins_dir / name`; with `--force` it overwrites `plugin.hu` /
`theme.hu` in any existing directory the path reaches. Input is your own CLI arg / TUI prompt, so this is a
foot-gun, not an exposure. It also creates an empty `dotfiles/` dir nobody uses.
**(reproduced)** `cs --home $S/homeT theme save ../../escaped-theme` → `saved current theme ->
…/plugins/../../escaped-theme`; `ls $S/homeT/.config/escaped-theme` → `dotfiles plugin.hu theme.hu`.
**Fix:** require a single safe segment (reuse plugins' dir-name validation) and drop the `dotfiles/` mkdir.
**Effort:** S. **Tier:** A.

### actions-24 [LOW] correctness — System Updates scan: prints over the curses screen under `--pretend`, and a failed scan reads as "no updates"
`configsys/sysupdates.py:124-153`. (a) Under `--pretend` the scan thread's six runner calls echo through
`print` (runner.py:467, `echo=lambda m: print(m)` app.py:127) while curses owns the terminal; the result is
`{}` anyway. (b) An exception in `gather` is cached as `{}` with no note (:140-143), so the header chip simply
disappears — the "absent warning reads as nothing to report" case docs/principles.md warns about. (c) The
native manager answering `None` (query failed — it is certainly installed) is dropped like an absent flatpak
(:98-99); system-updates.md makes that policy, see Questions. (d) The thread reads the lazily rebuilt
`ctx.routes` / `ctx.config` without synchronization while the main thread may `invalidate()`; the property
assigns its Resolver at the end (app.py:351), so a thread that started a rebuild before an edit could
re-cache a stale Resolver (not reproduced; the window is small).
**(reproduced, a)** `printf 'Qyq' | script -qfc "cs --home $S/homeP --os pop --pretend --effects none tui"
$S/tui_pretend.log` → after the first full frame (byte 15819, inside smcup 8696 … rmcup 16108): `[pretend]
apt list --upgradable\n[pretend] flatpak list …\n[pretend] flatpak remote-ls --user …\n[pretend] snap refresh
--list\n[pretend] snap list`.
**Fix:** `start_scan` is a no-op under pretend; on an exception store a note (`system-updates: scan failed:
<e>`) for the `!` page; treat `None` from the OS's own manager as "couldn't list" with a note. **Effort:** S.
**Tier:** B.

### actions-25 [LOW] performance — `Ledger.load` parses the file twice and is reloaded once per plan target
`configsys/ledger.py:36-64` parses with `troveio.load` (locks) and again with `materialize_string`
(receipts); `installState.superseded_installs` calls `Ledger.load` inside the per-target loop of
`plan_with_swaps` (installState.py:381, :397-400). Receipts store every field of the unit, so the file grows
~570 B per install.
**(reproduced)** `$S/scripts/ledger_load_time.py` (200 receipts, 114 KB) → `Ledger.load: 23.6–30.2 ms each` =
`trove load only: 8.3 ms` + `materialize only: 18.8 ms`; a `U` over 40 outdated units pays ~1 s of ledger
parsing in plan building.
**Fix:** one materialize pass; pass the already-loaded ledger into `plan_with_swaps`/`superseded_installs` (or
cache by mtime). **Effort:** S. **Tier:** C.

### actions-26 [LOW] performance — `config_settings` re-reads the plugin declarations twice per setting
`configsys/actions.py:848-878`: `_setting_home` + `_setting_target` per key each call `_primary_data_file`
(→ `plugins.declared` + `plugins.layer_files`) and re-parse the top config and primary file.
**(reproduced)** `$S/scripts/time_config_settings.py` ($S/homeT, a primary) → `config_settings: 43.1 ms for 23
settings; calls: {'declared': 45, 'layer_files': 45, 'read_scalar_section': 50, 'read_list_section': 16}`; the
TUI Config screen pays it on every edit (`cs.reload()`, tui/screens/config.py:239-338).
**Fix:** resolve the primary file once per call and read each file's sections once. **Effort:** S. **Tier:** C.

### actions-27 [LOW] reuse — pin writes still have no shared action (carried, 2026-09 MED)
`configsys/app.py:2284-2400` (`_validate_pin`, `_pin_set/_unset/_promote`) vs `configsys/tui/menu.py:1766-1782`
(`_apply_method_pin`) and the provider-pin twin. The TUI skips `_validate_pin`, writes the top config directly,
calls the cache invalidation by hand, and has no unpin / promote (it prints "run `configsys pin promote`").
Verified by reading; `grep -n "def set_pin" configsys/actions.py` → nothing.
**Fix:** `actions.set_pin / unset_pin / promote_pin` (validate + invalidate inside), both skins call them; add
"(use default)" and "promote" rows to the TUI method picker. **Effort:** M. **Tier:** D.

### actions-28 [LOW] reuse — `orphans --ignore` bypasses `ignore_orphan`; there is no `--unignore` (carried)
`configsys/app.py:1989-2000` re-implements the append (multi-pattern) via `set_config_setting`;
`actions.unignore_orphan` (:536-544) is TUI-only.
Verified by reading `app.py:1989-2000`.
**Fix:** `ignore_orphan(ctx, patterns)` takes a list; add `orphans --unignore`. **Effort:** S. **Tier:** D.

### actions-29 [LOW] feature — the `uninstall:` queue has no CLI, and `clear_uninstall` has never had a caller (carried)
`configsys/actions.py:375-391` (`stage_uninstall`, TUI-only), `:547-555` (`clear_uninstall`: 0 callers in
configsys/, the plugin repos, examples/ or tools/ since it was added in `5c95155`; `stage_uninstall`'s docstring
still names it as the cancel path).
Verified: `grep -rn clear_uninstall configsys ~/src/configsys-*/ examples tools` → the definition only; `git log -G clear_uninstall` → added in `5c95155`, never called.
**Fix:** `configsys uninstall list|add|rm|clear` (or `remove --stage`), which gives `clear_uninstall` its caller —
or delete it. **Effort:** S. **Tier:** G.

### actions-30 [LOW] correctness — `set_theme_value` accepts any dotted key: `theme set accent X` stores a no-op
`configsys/actions.py:960-982` writes whatever path it's given; `theme set accent '#ff0000'` writes `theme: {
accent: … }`, which nothing reads, reports "set accent = #ff0000", and `check` doesn't flag (the pretend sweep's
own VERBS use this form).
**(reproduced)** `cs --home $S/homeT theme set accent '#00ff00'` → `set accent = #00ff00 (in srcplug)`; effective
`theme()['colors']` → `{}`; `check | grep -i accent` → nothing.
**Fix:** validate against the theme schema (`colors.<name>`, `pages.<page>.<role>.<attr>`,
`pages.<page>.gradient.<k>`, `splash`) and refuse otherwise; fix the sweep's VERBS entry. **Effort:** S.
**Tier:** B.

### actions-31 [LOW] dead-code — the ledger's `managed` and `pinned_version` fields have never been written
`configsys/ledger.py:24-25, 53-58, 70-71, 85-98` (`is_managed/set_managed/pinned_version/set_pinned`) and
`installState.ComponentState.managed`: production never calls `set_managed`/`set_pinned` (not since the ledger
was created in `9ff301f`), `pinned_version` is never read, and `managed` is only copied into a field nothing
reads — yet every record serializes `managed: false  pinned_version: ""`. The module docstring (:4-6) and README
("the files it manages") still describe them. Records are also never pruned (an unlocked, receipt-cleared unit
keeps a blank record).
Verified: `grep -rn "set_managed\|set_pinned\|pinned_version\|is_managed"` over configsys/, `~/src/configsys-*/`, examples/ → tests and `installState.py:226` only; `git log -S "set_managed("` → only `9ff301f`.
**Fix:** drop the two fields and their accessors (tolerate them on load), prune blank records on save, and fix
the docstring. **Effort:** S. **Tier:** D.

### actions-32 [NIT] comment-drift — stale docstrings and comments
`actions.py:1632` "the via:dotfiles units in the active profiles" (retired; carried from 2026-09) and `:1637-1638`
"(Phase 2 splits these into separate glue/dotfiles pages.)" (done — two screens exist); `:26-29` "called from
inside the shared writers, so neither … can forget it" (actions-10, actions-27); `:378` "or `clear_uninstall`
cancels" (no caller); `:205-207` docstring lines lost their indentation; `ledger.py:4-6` `managed` (actions-31);
`failures.py:5` "never changes control flow" (actions-19); `sysupdates.py:19-20` "P0 proves … P3 extends … to the
rest" reads as a plan, P3 shipped. Verified by reading each cited line.
**Fix:** update them. **Effort:** S. **Tier:** D.

### actions-33 [NIT] dead-code — small duplicates and identity indirections
`actions.py:1546-1547` redefines `_pretend` (identical to :21-23); `actions.py:372` `UNINSTALL_PROFILE` is unused
(`Config.UNINSTALL_PROFILE` is the one read, config.py:470); `actions.py:780` re-imports `layers`;
`sysupdates.py:25` `_TIER_TOKEN` maps every tier to itself; `CONFIG_SETTINGS`' third column is `'configsys.hu(5)'`
for all 23 rows; in run_plan `rc` (unit), `rc_code` (exit status) and `rc_snap` (rc-file snapshot) overload one
abbreviation. Grepped configsys/, test/, `~/src/configsys-*/`, examples/, tools/.
**Fix:** delete / rename (`exit_code`, `shell_rc_snapshot`). **Effort:** S. **Tier:** D.

### actions-34 [NIT] correctness — every flatpak System Updates row reads scope `user`
`configsys/sysupdates.py:221`: `scope = 'user' if row.manager == 'flatpak' else 'system'`, though `gather` lists
both installations (flatpak.py:301-310 — Pop's Flathub runtimes are system-wide).
Verified by reading `sysupdates.py:221` and `flatpak.py:301-310`.
**Fix:** carry the installation from `upgradable_index` (the `--user`/`--system` pass) into `UpdateRow`. **Effort:**
S. **Tier:** B.

### actions-35 [NIT] abi — three return conventions for "--pretend, nothing written"
Config writers return `(False, PRETEND_NOT_SAVED)` / `0`; plugin verbs return `(True, '[pretend] would …')`
(`plugin_add/remove/update/bless/unbless`) or `(False, '[pretend] would …')` (`plugin_trust/untrust`); labels are
`'top config'` in most writers but the file basename in `stage_uninstall` (:391). menu.py's `_pretend_note` papers
over it. **Fix:** one `WriteResult(changed, where, note, pretend)` for every actions writer before collaborators
build on the tuple shapes. **Effort:** M. **Tier:** F.

## Test gaps
- run_plan: Ctrl-C (rc 130, `interrupted`, ledger still saved, `end_sudo` called); an op that raises (actions-05);
  lock/unlock ledger writes incl. `holds_version=False`; the dangling-placeholder and no-driver skips' exit code
  (actions-18); `set-version` refusal for `targets_version = False` inside run_plan; the unknown-op branch; a
  locked unit staged for upgrade (actions-02, after the fix).
- ledger: a truncated / non-humon `state.hu` (actions-04); two writers (actions-03); the receipt keeps `source`
  (actions-07). test_ledger.py still exercises only the dead `managed`/`pinned_version` fields.
- plugins via actions: `plugin update --ref <bad>` (actions-08); `plugin remove` / `--replace` of a clone with
  unpushed commits or edits (actions-01); `--replace` of the primary keeps `primary: true`; remove of a transitive
  decl (actions-09); `test_an_unsigned_primary_is_never_cloned` asserts no clone but not that bless refused (it
  didn't); `stage_adopt` has no test at all.
- settings: bool / scope / dir validation (actions-11); every layout-changing setting invalidates the cache
  (actions-10); theme edit against a shadowing top config (actions-12).
- sysupdates: `start_scan`'s exception path; CLI `upgrade --system` failure recording (actions-14); no scan under
  pretend.
- failures: apt/dnf 404 and 403 strings (actions-19).
- pretend: a parametrized test that calls EVERY public writer in actions with a pretend ctx over a populated home
  (introspect `actions` for writers) — `clear_uninstall`, `unignore_orphan`, `copy_page_theme`, `load_theme`,
  `save_theme_to_primary`, `plugin_unlock` are covered only by reading today.

## Dead code
- `actions.clear_uninstall` — 0 callers in configsys/, test-only; grepped `~/src/configsys-*/`, examples/, tools/;
  not in the driver.py frozen list (actions-29).
- `actions._pretend` second definition (:1546) and `actions.UNINSTALL_PROFILE` (:372) — same greps (actions-33).
- `Ledger.set_managed/is_managed/set_pinned/pinned_version`, `ComponentState.managed` — production writes none,
  reads none meaningfully; plugin repos and examples don't use them (actions-31).
- `sysupdates._TIER_TOKEN` identity map; the `dotfiles/` mkdir in `save_theme_plugin` (actions-23/33).

## ABI / interface candidates
- `RunResult` / `OpOutcome` → dataclasses with an outcome `kind` (`ok | warned | advisory | failed | skipped |
  locked | interrupted`) instead of four booleans; `rc_code` → `exit_code`.
- One `WriteResult` for the actions writers (actions-35).
- `plugins.sync` outcomes as a closed set with `sync_succeeded()` (actions-08).
- `Resolver.resolve_resilient` returns its record (dropped soft pins, provider rules, floor pins) instead of storing
  "the last resolve" on the shared object (actions-13).
- Ledger: receipts carry `source`; `Ledger.update(paths, changes)` (locked, atomic read-modify-write); drop
  `managed` / `pinned_version` (actions-03/04/07/31).

## Questions for the user
1. Locks (actions-02): should an explicit `configsys upgrade <locked>` be refused until `unlock` (my reading of
   driver.py's "honored by the op loop"), or proceed because you named it? Should `set-version` on a locked unit be
   allowed (retarget-then-hold is README's documented flow)? Should `remove` clear the lock record, and should a lock
   follow the component across a method swap (today it stays on the old `driver\comp` key forever)?
2. System Updates (actions-24c): docs/system-updates.md says a failed manager query "drops that manager silently";
   docs/principles.md says an advisory that silently goes dark is worse than none. Surface a `!` note when the OS's
   own manager (always installed) can't list, keeping the silent drop for absent flatpak/snap?
3. Plugin removal (actions-01): confirm always on TUI Plugins `x`, or only when the clone holds local work? Should
   `--replace` of the primary be allowed at all, or require `plugin unbless` first?
4. Receipts (actions-07): gate receipt probes by the recorded plugin's current trust (my proposal), or never run
   command-carrying drivers' probes from a receipt?
5. Appetite for the settings registry (actions-17 = config-layers-20) now, since actions-10/11 are its symptoms.

## Refuted on verification

None. All three findings checked held up: actions-01 and actions-02 (every CRITICAL and HIGH) and actions-07 (the
only other security/safety finding at MED or above; actions-23 is LOW). One sub-claim of actions-07 did not hold:
that `plugin untrust` (or trust lapsing to `changed`) triggers it on its own. Its Verified line has the details.
