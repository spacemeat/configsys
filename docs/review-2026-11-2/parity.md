# Review: CLI / TUI parity + missing features (cross-cutting)

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: no owned files — every CLI capability in `app.build_parser` (configsys/app.py:3610-4100, plus
the `cmd_*` handlers it dispatches to) compared with the TUI (configsys/tui/menu.py `run()` router,
modals, `_confirm_and_execute`; configsys/tui/screens/{components,profiles,plugins,glue,dotfiles,config,theme}.py
`handle`; configsys/tui/keyspec.py `KNOWN_ACTIONS`; config.hu `keys:`), with README.md's CLI and TUI
sections as the stated contract. Context: CLAUDE.md, docs/principles.md, actions.py (`run_plan`,
`plugin_*`, `set_included`, `_picks_target`, `move_picks_to_primary`), flooradvise.py, planning.py,
sysupdates.py, shellguard.py, plugins.py (`declared_conflicts`, `shadowed_builtins`), config.py
(`selected_machine`, `requested`), installState.py (`ComponentState`), driver.py docstrings; the other
2026-11-2 area files (to cross-reference, not to re-review). Tests read: test_tui_pin.py,
test_tui_provider.py, test_tui_issue.py, test_execute.py, test_menu_state.py, test_uninstall_queue.py,
test_pretend_sweep.py, test_flooradvise.py (resident sections), test_screen_components.py,
test_screen_plugins.py, test_screen_profiles.py.

Scratch reproductions live in `$RUN/scratch/parity/` (`pin_default.py`, `locked_upgrade.py`,
`tui_remove_primary.py`, `tui_other_machine.py`, `tui_add_local.py`, `tui_trust_all.py`,
`rebuild.py`); every one drives the real screen `handle` / `MenuState` / `actions` call the TUI makes,
in a `--home` sandbox under `$RUN/scratch/parity/`. No package-mutating verb, TUI execute or driver op
ran without `--pretend`: the scripts only *stage* (`MenuState.stage*`) or call config/plugin actions
whose writes stay inside the sandbox home (`plugin init`, `plugin_add` of a local git path,
`plugin_remove`, `plugin_trust_all`); `load_pipeline` probes are read-only queries; no sudo.

## The parity table

Verdicts: **present** (an equivalent TUI affordance; behavior notes where they differ) ·
**missing → add** (should be in the TUI) · **CLI-only by design** · **reverse** (TUI-only; CLI lacks it).

| CLI | TUI (screen · key) | verdict |
|---|---|---|
| `inspect` | Components (1); `M` view mode; `!` issues | present — same `load_pipeline` + `diagnostics()` |
| `install <names>` | Components `i` (cursor/selection) → `X` | present — but the plans differ: CLI re-runs present deps (app-cli-04/routing-15), CLI skips the detection tier (app-cli-01/routing-01), TUI skips auto-tighten + floor heads-up (**parity-09**) |
| `install --picks [--yes]` | Components `I` → `X` | present — `I` is "make current" = `install --picks` + `upgrade --picks` |
| `install`/`upgrade --no-deps`; re-running `install` to **rebuild** a present component | — (`i`/`u` stage nothing on a present, current unit) | **missing → add** (**parity-05**) |
| `install`/`upgrade --force` (dotfiles clobber) | Dotfiles `m` captures first, so there's nothing to clobber | CLI-only by design |
| `remove <names>` | Components `x` → `X` | present (TUI drains `!uninstall`; CLI doesn't — app-cli-22) |
| `upgrade <names>` | Components `u` → `X` | present |
| `upgrade --picks` | Components `U` → `X` | present but **differs**: `U` includes LOCKED components (**parity-02**) |
| `upgrade --system [--yes]` / `updates` | System Updates group: `i`/`u` stage all → `X` | present — preview timing differs (**parity-16**); CLI records no failures (app-cli-05/actions-14) |
| `lock` / `unlock` | Components `L` → `X` | present |
| `set-version <name> <ver>` | — (`run_plan`/`execute_plan(version=)` plumbing unused) | **missing → add** (**parity-05**) |
| `fix-scope [names]` | — (the `!` row says "run: configsys fix-scope") | **missing → add** (**parity-05**) |
| `machine list` / `show` | Profiles matrix columns; `M` modal | present |
| `machine add` / `rm` / `use <name>` | Profiles `M` modal `a` / `x` / `m` | present; `use` with no name (clear) has no TUI path (**parity-14**) |
| `disp list [--new]` / `get` / `set` | Profiles `s`/`i` (cursor), `S`/`I` (set/profile), `E` all-seen, NEW marks | present |
| `picks list` / `add` / `rm` `[--machine]` | Profiles `t`/`T`/Enter on target machines (`M`), `m` per component | present |
| `picks to-primary` | — | **missing → add** (**parity-10**) |
| `where <name>` / `where -p <profile>` | `w` on Components / Profiles right pane; Profiles left pane for `-p` | present — shared `where_report` / `where_profile_report` |
| `location <name>` / `--all` | infoblock `at:` | CLI-only by design (shell-glue consumer) |
| `versions <name> [--min] [--refresh]` | `v` picker shows each method's version + `lags` | present (partial; `--min` / `--refresh` CLI-only — acceptable) |
| `check` | `!` page = `diagnostics()` only | **missing → add** the lint (**parity-06**) |
| `pin list` | — (the picker marks `pinned` per component only) | **missing → add** (**parity-04**) |
| `pin set` | `v` (Components: method + provider; Profiles: method only) | present but "keep the default" writes a pin (**parity-04**, **parity-17**) |
| `pin unset` / `pin promote` | — (the TUI prints "run `configsys pin promote`") | **missing → add** (**parity-04**) |
| `profile list` / `show` | Profiles left pane; `w` | present |
| `config show` / `get` / `set` / `unset` / `move` | Config (6): Enter edits, `m` moves | present; a bool can't be unset (**parity-17**); `--local` only via `m` afterwards |
| `theme show/list/set/unset/save/load [--local]` | Theme (7) | present; no `--local` (actions-12 covers where edits land) |
| `plugin list [--fetch]` | Plugins (3) (remote fetched on a thread) | present; conflicts / shadowed built-ins not shown (**parity-06**) |
| `plugin sync` | Plugins `s` / `S` | present; no "how the active set changed" delta (**parity-17**) |
| `plugin add [--ref --pin --local --replace]` | Plugins `a` (replace toggle only) | partial — **add `--local`/ref** (**parity-08**) |
| `plugin remove` | Plugins `x` — immediate, no confirm | present but unsafe (**parity-01**) |
| `plugin update [--all --latest --ref --pin]` | Plugins `u`/`U` (always `--latest`), `v` set-ref | present (no plain re-sync at the pinned ref except `s`; no `--pin`) |
| `plugin bless` / `unbless` | Plugins `b` / `B` — no confirm | present (**parity-07**) |
| `plugin trust [--all]` / `untrust` | Plugins `t` (toggle) / `T` — no confirm | present but consent-free (**parity-07**) |
| `plugin lock` / `unlock` | Plugins `L` | present |
| `plugin diff [--to REF]` | Plugins diff pane (`tab`) | present (no `--to`) |
| `plugin push [--include-edits -y]` | Plugins `P`; quit prompt | present (popup lists no files — primary-15) |
| `plugin log` / `undo` | Plugins `H` | present |
| `plugin init` / `set-source` | — | **missing → add** (**parity-13**) |
| `report` / `request` / `request-os` | `!` then `r` / `f` / `s` (full-text review) | present — keys hard-coded, not in `?` (**parity-15**) |
| `orphans` (known orphans) / `--adopt` / `--remove` / `--ignore` | Profiles `O` overlay, `t`/`T`/`C`, `x`→`!uninstall`→`X`, `.` | present (globs, `--foreign`/`--include-auto`/`--system`/`--all` CLI-only — acceptable) |
| `orphans --json` | — | CLI-only by design |
| `dotfiles status` | Dotfiles (5) + Glue (4) | present |
| `dotfiles capture [--force --dry-run]` | Dotfiles `m` / `M` (capture + link) | present (`--force`/`--dry-run` CLI-only) |
| `dotfiles staged` / `activate` / `discard` | — | **missing → add** (**parity-12**, = dotfiles-glue-33) |
| `glue add` / `glue override` | — | **missing → add** (**parity-12**) |
| `refresh` | Components `R` (calls `cmd_refresh`) | present |
| `keys` | `?` | present |
| `manpages`, `show`, `tui`, `--probe` | — | CLI-only by design |
| `--pretend` | `[PRETEND]` header; writers refuse | present (post-batch text still offers `configsys report` — **parity-15**) |
| `--os` / `--home` / `--config` / `-v` / `-q` | apply to the TUI launch | present |
| `--machine NAME` | Components shows NAME's picks; `I`+`X` installs them here | present but **differs**: CLI refuses (**parity-03**) |
| `--color` / `--nocolor` / `--effects` / `--splash-linger` | launch flags; Config `effects` / `splash` | present |
| (TUI) machine rename · claim `C` · mark-all-seen `E` · `!uninstall` stage/unstage · orphan un-ignore `.` · glue per-shell `a`/`A`/`x` · dotfiles move-store `s`/`S` · theme copy-page / promote | — | **reverse** (**parity-14**) |

## Carried over from docs/review-2026-09/ (app-cli-actions.md parity table, dotfiles-glue.md, README progress + open items)

| earlier finding | status | evidence |
|---|---|---|
| set-version has no TUI trigger (README D3 follow-on; app-cli-actions table) | open | no key; `menu.execute_plan(version=)` never passed a version → **parity-05** |
| fix-scope has no TUI affordance | open | `app.py:256-260` still tells the TUI user to run it → **parity-05** |
| `install --no-deps` has no TUI path | open | → **parity-05** (and no rebuild at all) |
| `pin unset` / `pin promote` / `pin list` missing in TUI | open | `menu.py:1780-1781,1907-1908` still defer "run `configsys pin promote`" → **parity-04** (dup app-cli-12) |
| TUI pin writes diverge (skip cache invalidation / validation / swap note) | fixed | `468a6d3` (TUI calls `actions.invalidate_location_cache`); `b68a645` swap offer; the duplication itself remains → app-cli-12 |
| `picks to-primary` missing in TUI | open | → **parity-10** |
| `dotfiles staged/activate/discard` CLI-only; glue per-shell CLI-missing (dotfiles-glue LOW) | open | `shellguard.py:208-210` still points at the CLI → **parity-12** (= dotfiles-glue-33) |
| `report` after a failed TUI batch | fixed | `de332c0` (`!` → `r`/`f`/`s` in-TUI filing), `cc7bbe9` (every failure persisted) |
| B10 TUI batch persisted only the last failure | fixed | `cc7bbe9` (`run_plan` shared) |
| B4 TUI never invalidated the glue location cache | fixed | `468a6d3` |
| B3 CLI ignored `locations:` | fixed | `468a6d3` (`Context.prepare_units`, `app.py:822`) |
| `plugin init` / `set-source` CLI-only | open | → **parity-13** |
| `check` lint not on the `!` page | open | → **parity-06** |
| reverse gaps: uninstall queue, machine rename, orphan un-ignore, theme copy/promote, dotfiles move-store, mark-all-seen | open | → **parity-14** (uninstall queue = app-cli-22 / actions-29) |
| A5 include-dedup demotes the top config | open | security-03 / config-layers-03 |
| A7 asset `sha256:` | open | security-02 / drivers-lang-19 |
| A10 key/source paths | open | security-04 / app-cli-16 |
| D2 structural MVVM + `{id: Screen}` router | fixed | `5a02b55`, `17149b8`, `5641778` (screens/ + `_screen()` router in `menu.run`) |
| `_alt` / native-pkg-file delegating to the native driver (D1 follow-on) | open | drivers-lang-03 / drivers-os-10 |
| D4 `LedgerLockMixin` | fixed | `3fe0f4a` (per actions area) |
| D4 `ModuleDriver` base | open | drivers-lang-17 |
| C2 ecosystem installers probe per component | fixed | `4c38d08`, `eae03ac`, `5b64e2b` (per drivers-lang) |
| C4 `diagnostics()` re-resolves per command | open | app-cli-11 (measured twice per `inspect`) |
| C5 plugin trees re-hashed per startup | open | plugins-06 |
| D5 settings registry | open | actions-17 / config-layers-20 |
| D6 `SelectionPolicy` | open | routing-18 |
| D7 `LinkedContentDriver` | open | dotfiles-glue-23 |
| D8 hand-rolled Humon I/O | open (half: `0c62c22` hutext) | config-layers-01 / plugins-10 |
| D9 split app.py | open | app-cli-14 (4940 lines) |
| Tier F `never_auto` rename | open | routing-20 |
| Tier F driver-contract omissions | fixed | `da0a7ac` (`test_abi_surface.FROZEN_HOOKS`) |
| Tier F `routes.load` / `Resolver.candidates` return types | open | routing-34 |
| Tier F trust-identity length prefix | open | plugins-08 |
| Tier F trim `plugins.__all__` | open | `plugins.py:60-66` unchanged (plugins.md themes) |
| Tier F delete dead public names (`errors.ResolveError`, `predicate.Cpu`, …) | open | routing-30 |
| Tier F `presudo` / `privileged` | partly fixed | `privileged` read by `actions._may_need_root` (`de4d79f`); `presudo` still accepted and ignored (`runner.py:459-462`, drivers-lang carry table) |

## Cross-cutting themes

- **The TUI's *operate* surface is still a subset of the CLI's.** The manage surfaces (picks, machines,
  dispositions, config, theme, plugins, dotfiles) reached near-parity, but four of README's documented
  operations — rebuild, `set-version`, `fix-scope`, and the pin lifecycle (`unset` / `promote` / `list`)
  — exist only on the CLI, and the TUI's own text sends the user there (parity-04/-05/-15).
- **Same action, two policies.** Where both surfaces do something, the *batch policy* around the shared
  `run_plan` is still per surface: which units a bulk op selects (locked: parity-02; another machine's
  picks: parity-03), what the plan adds (auto-tighten: parity-09; present deps: app-cli-04), what a
  "keep the default" choice writes (parity-04), and what the preview shows before a refresh
  (parity-16). Each was decided once in app.py and never in the TUI.
- **Consent is calibrated by surface, not by consequence.** A typed CLI command names its target, so it
  gets away without a prompt; the TUI reuses the same no-prompt action behind a single letter. That is
  fine for reversible stagings (Components/Profiles `x` only stage) and wrong for the Plugins screen,
  where `x` rmtrees, `t`/`T` grant code-execution trust, and `b` grants machine-setting authority, all
  on one keystroke (parity-01/-07).
- **Advisories exist on one surface only.** `check` holds a dozen lints the `!` page never shows —
  including `shadowed_builtins`, whose docstring promises "never silent" (parity-06) — while the TUI's
  floor advisory promises an `auto-tighten` behavior only the CLI implements (parity-09).
- **Parity is unenforced.** Nothing ties `build_parser()`'s verbs to `keyspec.KNOWN_ACTIONS`; every gap
  above arrived silently, while the project already gates drivers (`test_driver_inventory`), pretend
  (`test_pretend_sweep`) and journal writers (`test_primary_journal`) with inventory tests (parity-11).

## Findings

### parity-01 [CRITICAL] safety — Plugins `x` deletes a plugin on one unconfirmed keystroke; on a `plugin init` primary that is the only copy of your captured dotfiles
`configsys/tui/screens/plugins.py:318-321` (`remove` → `actions.plugin_remove`, no popup) →
`configsys/actions.py:1323-1345` (`plugin_remove`: undeclare, then `shutil.rmtree(pdir)`).
`configsys/app.py:2802` (`plugin init` *moves* the local dotfiles store into the plugin) and `:2815-2816`
(declares `{'source': str(plug), 'primary': True}` — the source **is** the synced dir). So after the
README's "fast path" (`plugin init`, before `set-source`/`push`), the primary under
`~/.config/configsys/plugins/<name>/` holds the only copy of the user's captured configs (their
`~/.config/<app>` files are now links into it), their glue and their component definitions — and the
Plugins screen deletes it on `x`, the key that on Components, Profiles and Glue only stages or
deactivates. The CLI needs a typed `plugin remove <name>`; the TUI needs a slip of the cursor. Same
root as **actions-01** (no git-state check before any rmtree); this adds the own-source case, where
even a fully pushed-and-clean check can't apply because there is no remote.
**(reproduced)** `configsys --home $RUN/scratch/parity/home-init --os pop:24.04 plugin init mine` (one
captured `htop-dotfiles.cfs/htoprc`) → `created + blessed "mine"`; then
`.venv/bin/python $RUN/scratch/parity/tui_remove_primary.py …/home-init` (builds `PluginsScreen`,
`handle(ord('x'))`) → `rows: [('mine', True)]` / `captured dotfile exists before: True` / `note: removed
…/plugins/mine` / `captured dotfile exists after : False | plugin dir exists: False`.
**Fix:** (1) TUI: `remove` opens a confirm popup naming what is deleted (synced dir, unpushed count,
dirty files from `primarygit.state`), default "keep", and refuses outright for the primary; (2) actions:
never rmtree a dir that is its own declared source (`abs_local_source(src) == pdir`) — undeclare only —
and adopt actions-01's ahead/dirty refusal for every clone. **Effort:** S (TUI + own-source guard).
**Tier:** A.
**Verified:** CONFIRMED (reproduced) — CRITICAL kept; the same defect as actions-01 and tui-screens-01 (fold them).
Fresh sandbox `$RUN/scratch/verify-parity/home/p01`. Every command went through a recording runner
(`scratch/verify-parity/scripts/fakerun.py`): only `git` confined to the sandbox ran, everything else was recorded,
and no sudo was attempted. `scripts/p01_init_remove.py` follows README's "natural flow" (capture, then `plugin init`).
It writes a real `~/.config/htop/htoprc` (`ORIGINAL-BEFORE-CAPTURE`) and runs `dotfiles capture htop-dotfiles --yes`.
The driver's own link script was recorded, then applied by hand (`mv` → `htop.pre-configsys`, `ln -s` → the store).
The script then edits the config through the link (`EDITED-AFTER-CAPTURE`), adds a `components:` and a `profiles:`
section to configsys.hu, and adds a user.d glue snippet. `plugin init mine` → "(profiles, components moved into the
plugin and removed from configsys.hu.)", with the decl `{ source: …/plugins/mine  ref: main  primary: true }`,
`git remote -v` empty and the local store `[]`. `PluginsScreen.handle(ord('x'))` on the ★ row (`x` → `remove`,
`_popup_choose` instrumented) → `note: removed …/plugins/mine | popups shown: 0`, `primary dir exists: False`. A grep
of the whole sandbox then found `EDITED-AFTER-CAPTURE`, `MY-OWN-COMPONENT-DEF`, `my-favs` and `MY-USER-GLUE`
nowhere (`[]`), and `ORIGINAL-BEFORE-CAPTURE` only in `.config/htop.pre-configsys/htoprc`. So "the only copy" holds
for everything since the capture: every edit, the manifest, the moved `components:`/`profiles:`, the user glue and
the git history. One correction: the pre-capture original survives as `<dst>.pre-configsys` once the config has
been linked, and a capture that was never linked keeps its on-system file. `primarygit.state` is `None` for this
primary (no remote, `primarygit.py:440-443`). A confirm or refusal built only on its ahead/dirty counts would
therefore protect nothing here, so fix (2)'s own-source check is needed. Nothing guards the delete: `plugin_remove`
checks only that the dir is inside the plugins dir, neither `screens/plugins.py:318-321` nor the router confirms,
and `test_plugins.py` removes only non-primary plugins. On the other screens `x` only stages or deactivates
(config.hu: components `op-remove`, profiles `stage-uninstall`, glue `deactivate`).
**A new, separate defect seen on the way (not filed):** "their `~/.config/<app>` files are now links into it" is not
yet true after `plugin init`. `_plugin_init_create` (`app.py:2801-2802`) and `_plugin_init_merge` (`:2862-2868`)
`shutil.move` the store but re-point only glue (`_redeploy_user_glue`). They never re-point the dotfiles links, which
`DotFiles.relocate` does (`drivers/dotfiles.py:505-508`). In `home/p01b` (init with no `x`) the link stays
`→ …/.config/configsys/dotfiles/htop-dotfiles.cfs/htop | resolves: False`, and `dotfiles status` →
`! unmanaged ~/.config/htop htop-dotfiles <plugin>/htop-dotfiles.cfs/htop`, while every user-glue link reads
`linked` into the primary. So on the documented capture-then-init path, every linked config is broken until it is
re-linked.

### parity-02 [HIGH] correctness — TUI `U` / `I` / `u` / `i` stage upgrades of LOCKED components; CLI `upgrade --picks` leaves them alone
`configsys/tui/menu.py:36` (`'upgrade': … lambda s: s.supported and s.outdated` — `outdated`
(`installState.py:83`) ignores `locked`), used by `stage` (`:444-460`, including `i`'s make-current
fallback) and `stage_all` (`:462-492`). The CLI's `--picks` selection filters on `status == 'outdated'`
(`app.py:1043-1044`), and `status` puts `locked` ahead of `outdated` (`installState.py:127-130`), so
`upgrade --picks` honors the hold ("locked picks are left alone", `app.py:1063`). `run_plan` never checks
a lock (`actions.py:198-330`), so for a ledger-held method (tarball, AppImage, cargo, …) the TUI's "upgrade
every outdated component" replaces the version the user locked; for an apt hold the batch fails. The row
reads `locked` while `U` stages it. Same bug class as **actions-02** (which also covers explicit
`configsys upgrade <name>`); the parity angle is that the two bulk upgrades disagree.
**(reproduced)** `.venv/bin/python $RUN/scratch/parity/locked_upgrade.py` (a `tarball\lazygit`
`ComponentState`, `locked=True`, 0.40.0 → 0.44.1) → `status: locked  outdated: True` / `U (op-upgrade-all)
staged: 1 {'tarball\\lazygit': 'upgrade'}` / `I (op-install-all) staged: 1 {…'upgrade'}` / `CLI upgrade
--picks would select it: False`.
**Fix:** `OPS['upgrade']` predicate `s.supported and s.outdated and not (s.locked and staged != 'unlock')`
— one place, so `u`/`U`/`i`/`I` all follow; `stage_all` notes "N locked left alone"; and (actions-02)
`run_plan` refuses an upgrade of a locked unit unless the same plan unlocks it. Test both bulk ops.
**Effort:** S. **Tier:** B.
**Verified:** CONFIRMED (reproduced) — HIGH kept; the same root as actions-02, whose checker reproduced TUI `U X y`
end to end. `scratch/verify-parity/scripts/p02_locked_upgrade.py` uses the fresh sandbox `home/p02` and a recording
runner that only answers canned probes (`version-cmd` → 1.0, `latest-cmd` → 2.0) and executes nothing. A top-config
`lockme` (`via: script`) is picked on this-machine. `configsys lock lockme` → `state.hu`
`"script\lockme": { locked: true … }`. `configsys upgrade --picks --yes` → "nothing to do — every pick of this box is
up to date (locked picks are left alone)", and the install-cmd is never dispatched. The real `ctx.load_pipeline()` →
`status=locked locked=True lock_source=ledger installed=1.0 latest=2.0 outdated=True` (`inspect_one` calls
`get_latest` whatever the lock). Through the TUI's own `_components_model` + `MenuState` (`_req_sig` = requested),
the `[tracked]` rows are `['(other)', 'lockme']`. There `U` → `1 {'script\\lockme': 'upgrade'}` and `I` gives the
same. With the cursor on the row, `u` → `True {…: 'upgrade'}` and `i` gives the same. **Worse than written:** in the
DEFAULT `to-do` view the locked row is not shown at all (`locked` ∉ `_TODO_STATUSES`, `menu.py:2042`;
`[to-do] visible rows: []`). Even so, `U`/`I` stage `{'script\\lockme': 'upgrade'}` there, because `stage_all`
walks `self.states`, not the visible tree. The only sign is the `X` confirm's `upgrade script\lockme (pkg: lockme)`,
which doesn't say "locked". That plan then went through the real `run_plan` (`menu.execute_plan`, fake runner):
`upgrade script\lockme … -> ok`, outcome `('upgrade', 'script\\lockme', True)`, `echo INSTALL-LOCKME` dispatched,
ledger still `locked: True`. Nothing between staging and the driver checks a lock (read by hand: `stage`/`stage_all`,
`_confirm_and_execute`, `expand_plan`, `run_plan`). No test stages an upgrade of a locked unit: the only locked state,
in `test_tui_nav.py`, has latest == installed. The apt-hold half ("the batch fails") was checked by reading only,
not run: apt's `UPGRADE` is `apt-get install --only-upgrade -y {pkgs}` (`drivers/apt.py:66`), which apt refuses for
a held package without `--allow-change-held-packages`.

### parity-03 [MED] correctness — under `--machine <other>` the TUI installs the other machine's picks on this box; the CLI refuses
`configsys/config.py:356-391` (`selected_machine` → `current_machine` → `included` → `requested()`
all follow the `--machine` override), so `load_pipeline` builds the Components tree from the other
machine's picks and `stage_all` sweeps exactly them (`menu.py:478-485`, `_req_sig`). `X` then installs
them here. The CLI guards this invariant explicitly — `_picks_selection` (`app.py:1022-1035`):
"installs only ever happen on this box, so curating machine X's set from here must not install X's picks
here" — and the flag's help says `--machine` is "to view or curate another machine from here". The
Components header (`screens/components.py:123-127`) shows the OS block, `[PRETEND]` and the view mode,
not which machine's picks are listed, and the `X` confirm lists unit keys only.
**(reproduced)** `$RUN/scratch/parity/home-mach` with `picks: { this-machine: [btop] laptop: [fzf] }`:
`tui_other_machine.py` (`--machine laptop`, `_components_model` + `stage_all('install')`) → `TUI --machine
laptop: I stages 1 [('apt\\fzf', 'install')]`; `configsys --home … --pretend --machine laptop install
--picks` → `--picks acts on THIS box ("this-machine"), but --machine names "laptop" — installs never
happen for another machine here.`
**Fix:** when `machine_override` names another machine, show `machine: laptop (curating — installs
off)` in the Components header and make `stage`/`stage_all` refuse with that note (or build Components
from this box's picks and let `--machine` retarget only Profiles). Test it. **Effort:** S. **Tier:** B.

### parity-04 [MED] correctness — the TUI method picker can't leave a component unpinned: "keep the default" writes a hard pin, the popup hides the method in use, and there is no unpin / promote / pins list
`configsys/tui/menu.py:1819-1857` (`_pick_method_name`): the popup tags only `default` / `pinned` / `lags`
(`:1843`) and opens on the routes-only default (`:1852`, `candidates()` can't see detection — see
`_current_via`'s docstring `:911-916`), while the methods line two rows below brackets the method
actually in use. Enter on the pre-selected row calls `_apply_method_pin` (`:1766-1782`), which writes
`pins: { name: <default via> }`. Consequences: (a) a pin outranks the detected install (pin > detected
> default, routing-model §10), so "keeping" the default on a component installed another way flips it —
and the follow-up `_offer_method_swap` popup (`:1785-1808`) starts on "queue removal + reinstall", so
Enter-Enter stages the removal of the adopted install; (b) once pinned, no TUI path returns to
"unpinned" (choosing the default again just re-pins it), so later route improvements never reach this
component and the `via *` "you've diverged" marker can't appear (current == pinned == default); (c)
`pin promote` and `pin list` exist only on the CLI — the TUI's deferred note says "run `configsys pin
promote`" (`:1780-1781`, `:1907-1908`). The CLI has `pin unset`/`promote`/`list`
(`app.py:2305-2404`). Carried (2026-09 parity table); the duplication half is **app-cli-12**.
**(reproduced)** `.venv/bin/python $RUN/scratch/parity/pin_default.py …/home-pin` (steam: native default
+ flatpak; Enter on the pre-selected row) → `candidates: [('native', True, False), ('flatpak', False,
False)]` / `picker result: (True, 'pinned steam → native', …run \`configsys pin promote steam\`…)` /
`pins after choosing the DEFAULT: {'steam': 'native'}`.
**Fix:** give the picker the node (`_current_via`) and tag the current method; Enter on the current
method = no change; add rows "use the default (unpin)" when a top-config pin exists and "promote this pin
to <primary>" when it is local — through shared `actions.set_pin`/`unset_pin`/`promote_pin` (app-cli-12).
Add a Pins section to the Config screen (name → value, `[local]`/`[primary]`; Enter = unset, `m` =
promote) for `pin list`. **Effort:** M. **Tier:** G.

### parity-05 [MED] parity — no rebuild/reinstall, `set-version` or `fix-scope` in the TUI
Three operations README documents as core: **rebuild** ("Rebuilding a component": `install <name>`
re-runs, `--no-deps` rebuilds only it — README:402-410), **`set-version`** (README:399-401), and
**`fix-scope`** (README:358). In the TUI, `OPS['install']` requires `not s.present` (or `switch`) and
`OPS['upgrade']` requires `outdated` (`menu.py:33-37`), so nothing stages for an installed, current
component — no way to rebuild a source component after a recipe change, re-run a half-broken install, or
pick up a `[R]` recipe-pin. `set-version` has no key although `execute_plan(version=)`
(`menu.py:591-602`) and `run_plan` support it (note `run_plan`'s single `version=` per plan can't carry
per-unit versions, which a staged TUI batch needs). `fix-scope` runs outside the op loop
(`app.py:988-1019`, actions-15 / app-cli-26) and the `!` row it produces says "run: configsys fix-scope"
(`app.py:256-260`). Carried (2026-09: set-version, fix-scope, `--no-deps`); the plan-building half is
**actions-16**.
**(reproduced)** `.venv/bin/python $RUN/scratch/parity/rebuild.py` (an installed, current
`source\ripgrep`) → `stage('install') … -> False {}` / `stage('upgrade') … -> False {}` (the screen
answers "install not applicable here").
**Fix:** a Components `r` "reinstall / rebuild" op (stages `install` on a present unit; the `X` confirm
gets a "dependencies too? (y = like `install`, n = `--no-deps`)" line); `V` "set version…" (an input
box seeded from `versionreport`, refused up front when `actions.targets_version` is False), staged as
`('set-version', key)` with the version carried per step (`plan` tuples → `(op, key, rc, arg)` or a
`versions` map passed to `run_plan`); a `scope` badge on mismatched rows with `fix-scope` stageable and
executed through `run_plan`. **Effort:** M. **Tier:** G.

### parity-06 [MED] parity — `check`'s lints never reach the TUI: the `!` page hides plugin conflicts, built-in driver shadowing, key lockouts and the rest
`Context.diagnostics` (`app.py:175-280`) is the `!` page; `cmd_check` (`app.py:2429-2668`) adds, and
only prints: routecheck warnings, profile/`~ref` errors, pin issues, pin-vs-constraint conflicts,
`declared_conflicts` + `shadowed_builtins` (plugins.py:723-781 — whose docstring says a shadowing driver
is "legitimate … but never silent"), sha256 quarantine wording, theme-schema leftovers, `lint_keys`
(including "every quit key is bound to another action on this page — there is no way to quit from
it"), stale version pins, glue-override drift, uninstall-vs-picks conflicts, and setting values
(config-layers-18). The TUI Plugins screen doesn't show conflicts/shadows either (no caller in
configsys/tui/). A TUI-only user never learns that two plugins define the same component (last declared
wins) or that a plugin replaced core's `apt` driver. Carried (2026-09 "full check lint").
**(reproduced)** `$RUN/scratch/parity/home-shadow` (two plugins both defining `btop`, one declaring
`provides: { drivers: [apt] }`): `configsys … plugin list` → `conflict: component 'btop' claimed by
plugins aptplug, otherplug (last declared wins)` / `shadow: plugin aptplug replaces the built-in 'apt'
driver …`; `ctx.diagnostics(states)` after `load_pipeline` → `n = 0`.
Cost measured on the real catalog: `cmd_check` over an already-loaded Context = 0.65 s first call,
0.51 s second (`load 0.550s  check#1 0.654s  check#2 0.511s`).
**Fix:** split `cmd_check` into `lint(ctx) -> [Issue{level, tag, text}]` (data — app-cli-25) that the
CLI prints and the TUI merges into `!` lazily (on first `!` open, or on a background thread like the
System Updates scan), deduped against `diagnostics()`. **Effort:** M. **Tier:** G.

### parity-07 [MED] security — Plugins `t` / `T` / `b` grant trust and authority on one unconfirmed keystroke; `T` re-approves changed plugins without showing what changed
`configsys/tui/screens/plugins.py:362-372` (`trust` toggles via `actions.plugin_trust`/`untrust`;
`trust-all` calls `actions.plugin_trust_all`, `actions.py:1501-1527`, which trusts every `untrusted`
**and `changed`** plugin), `:338-343` (`bless`). No popup, and the review diff covers only the cursor
row. On return to Components the tree reloads and the newly trusted code/recipes are live in the same
session. CLI: `plugin trust` with no name also trusts everything (`app.py:3162-3165`; documented in the
help, but a bare `plugin trust` reads like "show me"). *Who controls the input:* a plugin's author — or
whoever pushed to its upstream, since `u` (update to latest) is what turns a trusted plugin `changed`.
*When it runs:* at the next load after the keystroke, with the user's privileges plus the batch's sudo on
the next install. *Consent:* one letter (`T` is shift-`t`). *What the attacker could already do without
this:* nothing — the content-hash trust gate is the boundary (docs/principles.md), so its consent UX
*is* the security property. `b` similarly hands a plugin machine-setting authority (`picks:`,
`disabled-drivers:`, `installer-shell-writes:`) without a prompt.
**(reproduced)** `$RUN/scratch/parity/home-trust` (two plugins shipping a `via: script` recipe):
`tui_trust_all.py` → `before: [('recplug', 'untrusted'), ('recplug2', 'untrusted')]` / `note: trusted 2
plugin(s)` / `after : [('recplug', 'trusted'), ('recplug2', 'trusted')]`.
**Fix:** `t`/`T` open a confirm listing each plugin, what it ships (code / recipes / glue / facets), its
short identity, and for `changed` "N files changed since you trusted it — tab shows the diff", default
No; `b` confirms with "its picks and settings will apply here". CLI: `plugin trust` without a name lists
what needs trust and asks on a tty (requires `--all` otherwise). **Effort:** S. **Tier:** A.
**Verified:** CONFIRMED (reproduced) — MED kept. `scratch/verify-parity/scripts/p07_trust_bless.py` uses the fresh
sandbox `home/p07b`. `plugin sync` brought in three local git plugins (sandbox git only, everything else recorded, no
sudo attempted). `recplug` has a `via: script` recipe for the picked `evil`, and `codeplug` has a `code:` module
whose top-level code appends to a marker file. `candidate` is data only (`disabled-drivers: [ flatpak ]
installer-shell-writes: allow`), and its settings are ignored with a warning while it isn't primary. `codeplug` was
trusted at v1, and then a v2 commit landed in its source repo (upstream). `u` on its row →
`re-pinned … @main (latest branch)`, and the row reads `changed`. The CLI's bare `plugin trust` (`--pretend`) →
"[pretend] would trust 2 plugin(s) — not saved / recplug / codeplug": no name means all, the changed one included
(documented in the help and docs/plugins.md §6). One `T` (with `_popup_choose` and `_input_box` instrumented) →
`trusted 2 plugin(s) | trusted recplug | re-approved codeplug | dirty: True | popups: []`. Nothing runs during the
keystroke itself. The router's next step is the return to Components (`_reload` → `load_pipeline`, called directly
here). That imported the changed module in-process (`codeplug v2 (NEW UPSTREAM) top-level code ran`). It also
dispatched recplug's `version-cmd` (`echo EVIL-PROBE-RAN`), which was only recorded here and would run on a real
runner. One `b` on `candidate` → `blessed candidate as primary (its machine settings now apply) | popups: []`. After
it, `disabled_drivers()` = `['flatpak']` and `block_installer_shell_writes()` = `False`, so the installer rc-file
guard is off. "Without showing what changed" holds, and not only in the TUI. After `u`, `plugin diff codeplug` → "up
to date — nothing to pull in" (the review diff is HEAD → remote-ref), and `plugin-trust.hu` keeps only a content
hash (`codeplug: "sha256:52ca…"`). So no surface can show what changed since the last approval. The fix's "N files
changed since you trusted it — tab shows the diff" therefore needs something new recorded at trust time (the trusted
commit, or a per-file hash map). A confirm that lists what each plugin ships can be built today. docs/plugins.md §6
says trust is "an explicit command, never an inline prompt, so the CLI stays scriptable"; that reasoning covers the
CLI, not a single TUI letter. `t` takes `T`'s path for one row (`screens/plugins.py:362-368`, by reading). MED stays:
the key is labelled and deliberate, but this gate is the only boundary for plugin code, and re-approving upstream
changes in bulk takes one reflex keystroke.

### parity-08 [MED] parity — TUI `plugin add` has no `--local` (nor ref / pin): with a primary blessed, a project checkout's path is published to every machine
`configsys/tui/screens/plugins.py:308-317` calls `actions.plugin_add(ctx, src, replace=replace)` —
`local` defaults to False (`actions.py:1221`), so with a primary the declaration lands in the primary's
manifest `plugins:` (portable). CLAUDE.md's machine-level-plugin model is precisely `plugin add
<source> --local` for "a source repo or app install … without traveling to the user's other machines".
From the TUI an absolute local path travels; on every other machine it can't sync and shows an
`unsynced` warning on `!` indefinitely. No ref and no `--pin` either.
**(reproduced)** `$RUN/scratch/parity/home-add` (primary from `plugin init mine`), local git repo
`$RUN/scratch/parity/projplug`: `tui_add_local.py` (the exact TUI call) → primary manifest `plugins: [ {
source: …/scratch/parity/projplug } ]`; top config holds only the primary.
**Fix:** the add box gets a second toggle "this machine only (`--local`)", defaulting ON when the source
is a local path, and an optional ref field. **Effort:** S. **Tier:** G.

### parity-09 [MED] correctness — the TUI execute path skips `auto-tighten`'s provider upgrade and the floor heads-up, while the TUI's own advisory promises it
`app.py:847-853` (`_dispatch_op`: under `auto-tighten`, append an `upgrade` for each resident provider
below a consumer's floor, `flooradvise.resident_upgrades_probed`) and `:862-871` (print each
`flooradvise.advise` heads-up before running) have no counterpart in `_confirm_and_execute`
(`menu.py:756-851`, which goes straight from `plan_with_swaps` to `expand_plan`). Yet the `!` page row
from `resident_advise` reads "… run `configsys upgrade <prov>` (or set `auto-tighten` to upgrade it
automatically before installing <comp>)" (`flooradvise.py:213-225`): a TUI user who sets it on the Config
screen and presses `i` gets the consumer built against the too-old toolchain. `flooradvise.resident_upgrades`
(`:228-235`, the states-based variant suited to the TUI, which has full states) has no production caller.
Part of **actions-16** (plan building is two implementations). **(verified by reading)** the three sites
above and `grep -rn resident_upgrades configsys/ ~/src/configsys-*/` (only the CLI's `_probed` call and
`test/test_flooradvise.py:223`).
**Fix:** one `actions.build_plan(ctx, raw, units, states=None, *, no_deps=False) -> (plan, advisories)`
doing swaps → auto-tighten (`resident_upgrades` when states are known, else `_probed`) → `expand_plan`,
returning the heads-up texts for each surface to print (the TUI on its confirm screen). **Effort:** M.
**Tier:** B.

### parity-10 [MED] parity — `picks to-primary` has no TUI path, and the TUI never shows that a machine's picks are a local shadow
`actions._picks_target` (`actions.py:426-429`) keeps writing a machine's picks to the top config once a
local list for it exists (the shadow guard — a higher layer replaces a machine's whole list), so after
any pre-bless or `--local` edit every TUI `t`/`T`/Enter/`C` lands locally and never travels. The fix
is `configsys picks to-primary` (`app.py:1959-1960` → `actions.move_picks_to_primary`), which the TUI
lacks, and nothing in the Profiles matrix or the `M` modal marks a column as local vs primary (no
provenance in screens/profiles.py), so the user can't see why their picks don't reach the laptop.
Carried (2026-09). **(verified by reading)** `actions.py:426-461`, `screens/profiles.py`.
**Fix:** tag each machine in the `M` modal / matrix header `(local)` / `(primary)`; a `p` "move this
box's local picks into <primary>" in that modal (or a Config-screen row), calling
`move_picks_to_primary`. **Effort:** S. **Tier:** G.

### parity-11 [MED] refactor — parity is maintained by hand; nothing fails when a CLI verb ships without a TUI decision
`build_parser()` (`app.py:3610-4100`) and `keyspec.KNOWN_ACTIONS` (`keyspec.py:244-262`) are two
independent vocabularies; the same operation is implemented separately per surface (pins in app.py and
menu.py; System Updates apply in app.py and menu.py; plan building in app.py and menu.py), and each gap in
this file appeared silently. The project already enforces three such inventories
(`test_driver_inventory.py`, `test_pretend_sweep.py` `VERBS`, `test_primary_journal.py` `WRITES`).
**Fix:** a `PARITY` table (`{cli verb[/flag]: ('<screen>', '<action>') | 'cli-only: <reason>' |
'tui-gap: <finding id>'}` plus the reverse for TUI-only actions) and a test that walks
`build_parser()._subparsers` and every `KNOWN_ACTIONS` id and fails on an unclassified one. Longer term,
an `ops` registry (id, action function, confirm policy, pretend preview, plan builder) that both
`cmd_*` and `Screen.handle` dispatch through would delete the per-surface copies behind parity-02/-04/
-09/-16. **Effort:** S (table + test), L (registry). **Tier:** D.

### parity-12 [LOW] parity — staged glue and `glue add` / `override` are CLI-only (same as dotfiles-glue-33)
During a TUI execute the shell-writes guard prints "review with `configsys dotfiles staged`, enable with
`configsys dotfiles activate X`" (`shellguard.py:208-210`); `shellguard.list_staged` has no TUI caller,
and the Glue screen lists activated user glue (`menu.py:4631-4658`) but not staged candidates, nor offers
add/override. Carried (2026-09 dotfiles-glue LOW). **(verified by reading)**.
**Fix:** as dotfiles-glue-33 — a "staged" group on the Glue screen with activate/discard, and `n` (new
snippet → `$EDITOR` under `suspended`) / `o` (override) keys. **Effort:** M. **Tier:** G.

### parity-13 [LOW] parity — `plugin init` and `plugin set-source` are CLI-only
`app.py:2766-2896`. The TUI is where a user meets the primary concept (header chip, Plugins `b`, quit-push
prompt), but creating one from local content and pointing it at a new remote both need the CLI;
`set-source` pairs naturally with the existing `v` set-ref. Carried (2026-09).
**Fix:** Plugins `n` "new primary from local content" (render `_plugin_init_create`'s plan — already
printed as text — in a confirm popup, then run it) when none is blessed; extend `v` to a "ref / source"
chooser. **Effort:** M. **Tier:** G.

### parity-14 [LOW] parity — the CLI lacks the TUI-only verbs (reverse gaps)
TUI-only: machine **rename** (`_machines_modal` `r` → `actions.rename_machine`; `machine` has no
`rename`), **claim** (Profiles `C`, track everything installed; the CLI adopts one orphan at a time with
`orphans --adopt`), the **`!uninstall` queue** (stage/unstage/list — app-cli-22 / actions-29),
**orphan un-ignore** (`.`; app-cli-22), **dotfiles move-store** (`s`/`S`), **glue per-shell
activate/deactivate** (dotfiles-glue-33), **theme copy-page / promote**, **mark-all-seen** (`E`).
Conversely the TUI can't clear `machine:` (`machine use` with no name). Scripted bootstrap of a new box
("adopt everything already installed") is the one that matters most. Carried (2026-09 reverse gaps).
**Fix:** `machine rename A B`, `picks claim [--machine M] [--yes]`, `uninstall list|add|rm|clear`
(app-cli-22), `orphans --unignore`, `dotfiles move <names> --to primary|local`, `disp set --all-new seen`;
`theme copy`/`promote` only if asked. **Effort:** M. **Tier:** G.

### parity-15 [LOW] data-driven — TUI text and keys that bypass the keymap or point at the CLI
- `!` page issue keys are hard-coded (`menu.py:4899` `ord('r'), ord('f'), ord('s')`; footer `:1399`) —
  not in `keyspec.KNOWN_ACTIONS`, so `?` never lists them (`_help_modal` reads `help_rows`) and a rebind
  of `down`/`up` leaves the footer's "j/k scroll" wrong.
- The post-batch summary says "`configsys report` files the details of the above (they stay on the !
  page until fixed)" (`menu.py:838-840`) — inside the TUI the path is `!` → `r`; and under `--pretend`
  nothing was recorded (the CLI says so, `app.py:954-958`).
- The machines modal title reads "target machines (A/D fan out to ✓)" (`menu.py:2748`) — retired keys;
  the fan-out keys are `T`/`t`. Its keys (`j/k/space/m/a/r/x/q`, `:2820-2847`) and
  `_component_machines_modal`'s (`:2702-2713`) are hard-coded too, as are `_popup_choose`'s.
- `!` rows are CLI-worded even where the TUI has the action (`fix-scope`, `plugin sync`, `plugin trust`,
  `upgrade <prov>`), because diagnostics are bare strings.
**Fix:** an `issues` keymap scope (`report`, `request`, `suggest-os`) with labels; footers/modal legends
from `keymap.glyph`; diagnostics carry an optional structured `fix` (`{'cli': '…', 'tui': (screen,
action)}`) so the `!` page renders the TUI hint and can offer Enter = do it. **Effort:** M. **Tier:** G.

### parity-16 [LOW] correctness — the TUI System Updates confirm previews the startup scan, then refreshes and bulk-upgrades whatever is newer
`_confirm_and_execute` prints "System Updates — bulk upgrade via apt (N package(s))" from the rows staged
off the startup scan (`menu.py:776-783`), asks (`:784`), and only then refreshes the index
(`:795`, `maybe_refresh_before_plan(…, system=True)`) and runs each manager's `upgrade_all` (`:800`) —
which upgrades everything upgradable *after* the refresh. `published_pending` can't report the extras
because the bulk run consumed them. The CLI refreshes first and previews the post-refresh list
(`app.py:1159-1191`). No-surprises: the count you confirmed can be lower than what ran. **(verified by
reading)**.
**Fix:** when System Updates are staged, refresh (once) before the confirm and re-gather the rows, or
after the refresh print "+K published since the scan will also be upgraded — continue? [y/N]".
**Effort:** S. **Tier:** B.

### parity-17 [LOW] parity — smaller same-action differences
- Config screen: a bool setting can only be flipped (`screens/config.py:247-252`), never unset — a local
  value shadowing the primary's can't be removed from the TUI (CLI `config unset`).
- Profiles `v` opens only the install-method picker (`screens/profiles.py:699-711` →
  `_pick_method_name`); Components `v` opens `_pick_choices` (method **and** provider axes), so
  provider-pins (`cuda-toolkit`, `jdk`) can't be set from Profiles, though README calls both "pin".
- Plugins `s`/`S` report only "synced X" (`screens/plugins.py:322-337`); the CLI prints how the active
  set changed (`print_sync_delta`, `app.py:3080-3081`).
**Fix:** bool → popup `true / false / unset`; Profiles `v` → `_pick_choices`; the sync note appends the
delta's one-line summary. **Effort:** S. **Tier:** G.

### parity-18 [LOW] feature — the CLI has no catalog search or listing
The TUI browses the whole catalog (`!all`, `/` find, `F` filter, `f` attr filter, descriptions); the CLI
has only `profile list` (190 lines of profiles, no descriptions or attrs) and `where <exact name>`. A
user asking "which component is a terminal emulator / what provides `rg`" must grep routes.hu.
**(reproduced)** `configsys … profile show '!all'` → `configsys: profile '!all' is not defined`;
`configsys … where terminal` → `unknown component "terminal"`.
**Fix:** `configsys search <text> [--attr A] [--installed] [--json]` over names, descriptions and attrs
(lift the ProfileScreen catalog/attr filtering into a pure function both use). **Effort:** S. **Tier:** G.

### parity-19 [LOW] feature — expected and missing on both surfaces
- **Removing your own glue.** `glue add` / `override` create files; neither surface removes a user snippet
  or reverts an override to the shipped one — the Glue screen's `x` on user glue says "delete or move
  <file> to stop it loading" (`screens/glue.py:197-199`).
- **An operations history.** The ledger keeps install receipts, but there is no "what did configsys do on
  this box, and when" view (`plugin log` exists only for the primary's config commits).
- **Machine-readable `inspect`.** `orphans --json` exists; `inspect --json` (status / versions / locked per
  unit) doesn't, so scripts screen-scrape the table.
**Fix:** `glue rm <name>` / `glue override --revert <comp>` (+ Glue-screen keys); a ledger op log
(`state.hu` `history:` capped at N, shown by `configsys history` and a `!`-page section); `inspect
--json`. **Effort:** M. **Tier:** G.

## Test gaps

- No test that bulk `U`/`I` (and `u`/`i`) skip locked units (parity-02) — test_menu_state.py builds only
  `locked=False` states.
- No test that `--machine <other>` blocks TUI staging (parity-03); the CLI refusal is untested at
  `main()` level too.
- No test of the picker's "Enter on the pre-selected row" (parity-04) — test_tui_pin.py's
  `test_pick_method_popup_selects_and_writes` only moves off the default.
- Screen-handle tests (test_screen_plugins.py, test_screen_components.py, test_screen_profiles.py) cover
  navigation only; none drive the destructive / consent handlers (Plugins `x`/`t`/`T`/`b`, Components
  `X`) — parity-01/-07.
- No test that `diagnostics()` (the `!` page) surfaces plugin conflicts / shadowed built-ins / key
  lockouts (parity-06).
- No TUI test of `auto-tighten` (test_flooradvise.py exercises `resident_upgrades` directly, nothing
  calls it from a plan) — parity-09.
- No parity inventory test (parity-11).

## Dead code

- `menu._pick_method` (`menu.py:1811-1816`) and `menu._pick_provider` (`:1912-1931`): superseded by
  `_pick_choices` (`:1969`), no production caller — only test_tui_pin.py / test_tui_provider.py. Grepped
  `configsys/`, `test/`, `examples/`, `~/src/configsys-*/` for `_pick_method(` / `_pick_provider(` (the
  `resolve.py` hits are `Resolver._pick_provider`, a different method). Not ABI. Repoint the tests at
  `_pick_choices` / `_pick_method_name`, then delete.
- `menu.execute_plan(…, version=None)` (`menu.py:591`): no caller passes `version` — keep, it is the
  plumbing parity-05 needs.
- `flooradvise.resident_upgrades` (`flooradvise.py:228`): only `test/test_flooradvise.py:223`; grepped
  the same trees. Wire it (parity-09) rather than delete.

## ABI / interface candidates

- `actions.run_plan(…, version=)` carries one version per plan; a TUI that stages several `set-version`s
  needs it per step (parity-05). Decide the plan tuple shape (`(op, key, rc)` → `(op, key, rc, arg)` or a
  `PlanStep` dataclass) before plugin code ever builds plans.
- Diagnostics are bare `{level, tag, text}`; adding an optional structured `fix` (parity-15) is cheap now,
  breaking later if plugins start emitting diagnostics.

## Questions for the user

1. `--machine <other>` in the TUI: should Components refuse to stage installs (keep showing that
   machine's picks, read-only), or always show this box's picks and let `--machine` retarget only the
   Profiles editing (parity-03)?
2. Locks: should a single explicit `u` on a locked row (and CLI `upgrade <locked-name>`) ask "unlock and
   upgrade?", refuse, or proceed — given the bulk ops should skip locked rows (parity-02 / actions-02)?
3. Plugins-screen consent: confirm every `x` / `t` / `T` / `b`, or only the primary and `changed`
   content (parity-01 / -07)? And should a bare `configsys plugin trust` keep meaning "trust all"?
4. Where should `set-version` and rebuild live in the TUI — new `V` / `r` keys on Components, or rows in
   the `v` picker (parity-05)?
5. Is ~0.5 s of `check` lint on first `!` open (or on a background thread) acceptable for parity-06, or
   would you rather a separate "lint" view?
6. Should a TUI `plugin add` of a local path default to "this machine only" (parity-08)?

## Refuted on verification

None. The checker verified the three findings in scope (every CRITICAL/HIGH, plus every security/safety finding
at MED or above): parity-01, parity-02 and parity-07. All three were confirmed by reproduction in
`$RUN/scratch/verify-parity/` through a recording runner (sandbox-confined git only; no package-manager command,
driver op or sudo was executed), and no severity changed. Two sub-claims were corrected in the Verified lines.
For parity-01, a linked capture's pre-capture original survives as `.pre-configsys`, and right after `plugin init`
the live links dangle instead of pointing into the primary, which is a separate new defect. For parity-02, the
default `to-do` view hides the locked row that `U`/`I` stage. parity-03…19 (MED and below, not security/safety)
were outside the scope and were not re-checked.
