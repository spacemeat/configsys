# Review: configsys/app.py, configsys/actions.py, configsys/planning.py

Read-only review. Scope: the argparse CLI + `Context` + command dispatch (app.py, 3658 LOC), the
shared action layer (actions.py, 964 LOC), plan ordering (planning.py, 84 LOC). Coverage gauged
against test/test_app.py, test/test_planning.py, test/test_config_edit.py (plus a sweep of the
other 123 test files for callers). TUI parity judged by reading `configsys/tui/menu.py` (execute
path, pin pickers, `refresh` handler) and `configsys/tui/keyspec.py` (the `KNOWN_ACTIONS` table).

All line numbers are against the working tree at HEAD `7c0c04d`.

## Themes

- **The "thin skin over actions" contract is only half-kept.** actions.py holds config/theme/
  plugin/picks/machine orchestration and both surfaces use it well there. But three big pieces of
  business logic live ONLY in app.py and the TUI re-implements them independently: the **op
  execution loop** (`_dispatch_op` vs `menu.execute_plan`), **pin writes** (`_pin_set`/`_pin_unset`/
  `_pin_promote` vs `menu._apply_method_pin`/`_apply_provider_pin`), and **plugin trust/untrust**
  (`cmd_plugin` re-implements `actions.plugin_trust*`). Each divergence has already produced a
  behavioral gap (see HIGH/MED below). `docs/tui-screens-plan.md:57` planned a `pin_promote`
  extraction that never happened.
- **Two real correctness bugs in the CLI op path**: `_dispatch_op` and `cmd_location` skip
  `apply_locations`, so a per-component `locations:` override is honored by `inspect`/TUI but
  silently ignored by `install`/`remove`/`upgrade`/`lock`/`location`. And the TUI never drops the
  glue location cache after a pin/pick edit, while the CLI does.
- **CLI/TUI parity is good on the "manage" surfaces (config, theme, plugins, picks, machines,
  dispositions, dotfiles capture) and weak on the "operate" surfaces**: `set-version`,
  `fix-scope`, `--no-deps`, `pin unset/promote`, `picks to-primary`, `dotfiles staged/activate/
  discard`, `plugin init/set-source/untrust`, `report`/`request` filing have no TUI affordance.
  Conversely the TUI has things the CLI can't do: machine rename, un-ignore orphan, stage/clear
  the `!uninstall` queue, mark-all-seen, dotfiles manage/unmanage/move-store, theme copy-page/
  promote-to-primary.
- **Comment/help drift from three retired models** (active profiles, `machines:` layers, the v2
  disposition/include model) is pervasive in argparse help strings — which are also the man
  page's source (`tools/gen_manpages.py`), so `man configsys` currently documents retired concepts.
- **app.py should be split.** ~350 lines (882–1230) are a self-contained package-index
  refresh/diagnosis module; `cmd_plugin`+init/set-source (~330), `cmd_check` (~210), the dotfiles
  commands (~220), and the parser (~330) are each natural modules. Tests already reach into
  `app._rekey_candidates` etc., so the split needs a re-export shim or test updates.
- **Test gaps track the parity gaps**: `upgrade`, `unlock`, `set-version`, `machine`, `picks`,
  `versions`, `profile`, `theme`, `refresh`, `keys` have no `main([...])`-level test; the op loop's
  advisory/verify-after-fail/`--no-deps`/auto-tighten branches have no test; `expand_plan` with
  `set-version` and with cycles is untested.

---

## CLI / TUI parity table

Legend — TUI column: **yes** = equivalent affordance; **partial** = related but narrower;
**no** = absent; **n/a** = inherently CLI-only (scripting/shell/manpage). TUI key names are the
`KNOWN_ACTIONS` ids from keyspec.py (`configsys keys` prints the bindings).

| Command | CLI (app.py) | TUI (menu.py / keyspec) | Gap notes |
|---|---|---|---|
| `inspect` | `cmd_inspect` :565 | **yes** — Components screen, `mode` cycles to-do/tracked/installed | Parity. TUI also shows `also_present` (coexisting) rows. |
| `install <names>` | `cmd_install` :856 → `_dispatch_op` | **yes** — `op-install`/`op-install-all` + `execute` | Execution loops diverge (see HIGH #2). |
| `install --force` (dotfiles clobber) | `ctx.paths.dotfiles_force` :857 | **no** (TUI offers `capture` on Dotfiles page instead) | Acceptable: TUI path is the safer one. Note it in help. |
| `install --no-deps` (rebuild only this) | `_dispatch_op(no_deps=)` :646 | **no** — staging a unit always folds deps via `expand_plan` :637 | README highlights `install --no-deps folly` as THE source-rebuild idiom; TUI has no way to rebuild one source unit without its dep tree. Real gap. |
| `remove <names>` | `cmd_remove` :861 | **yes** — `op-remove` | Parity. |
| `upgrade <names>` | `cmd_upgrade` :865 | **yes** — `op-upgrade`/`op-upgrade-all` | Parity (same loop divergence). |
| `lock` / `unlock` | `cmd_lock`/`cmd_unlock` :870 | **yes** — `lock` toggle | Parity. |
| `set-version <name> <ver>` | `cmd_set_version` :878 | **no** — `execute_plan` :557 has no `set-version` branch (returns `res=None` → "no result" failure) | Gap. Even a queued `set-version` from the `m` picker's version column would fail. Suggest: version input box on the Components `m`/`v` key. |
| `fix-scope [names]` | `cmd_fix_scope` :822 | **no** — the `!` page shows the `scope` warning text that says "run: configsys fix-scope" | Gap; the TUI literally tells the user to leave. A `fix-scope` action on the scope-warning diag row, or on the component row, is the obvious affordance. |
| `profile:<name>` arg expansion | `_expand_profile_args` :598 | **yes** — Profiles `track-all`, Components profile-node staging | Parity. |
| `where <name>` | `cmd_where` → `where_report` :1290 | **yes** — `where` (`w`) renders the same lines | Parity — a good example of the shared-text pattern. |
| `where -p <profile>` | `where_profile_report` :1354 | **yes** — Profiles infobox (menu :5503) | Parity. |
| `location <name>` / `--all` | `cmd_location` :1630 | **partial** — infoblock shows `at:` for the current unit | n/a for `--all` (shell glue consumer). But see HIGH #1: CLI `location` ignores `locations:`. |
| `versions <name> [--min] [--refresh]` | `cmd_versions` :1751 | **partial** — `m` picker annotates each method with its version + `lags` (menu :1572) | No `--min` floor check, no `--refresh` in the picker. Memory notes a dedicated Versions screen was removed as redundant; the picker is the intended home. Acceptable. |
| `check` | `cmd_check` :1949 | **partial** — `!` page = `ctx.diagnostics()` (load-time subset) | `check` lints things the `!` page does not: routecheck issues, pin sanity, `~ref` typos, theme schema, keybinding lint, stale version pins, multiple-primary. The user runs TUI daily and `check` rarely; consider running the static lint into the `!` page (it is subprocess-free). |
| `refresh` | `cmd_refresh` :1112 | **yes** — `refresh` (`R`) calls `app.cmd_refresh(ctx, None)` under `suspended()` (menu :6306) | Parity (shares the function, incl. rekey/reconcile prompts). |
| `pin list` | `_pin_list` :1828 | **partial** — `m` picker marks `pinned` per component; no global list | Minor. |
| `pin set <comp> <via\|provider>` | `_pin_set` :1841 | **yes** — `method` (`m`) via `_apply_method_pin`/`_apply_provider_pin` | Divergent implementations: TUI skips `_validate_pin`, `invalidate_location_cache` (MED #3), and the `_swap_headsup` text (TUI has `_offer_method_swap` — better). |
| `pin unset <comp>` | `_pin_unset` :1878 | **no** — picker can only re-pin to another candidate; cannot clear back to "default" | Gap. Add an "(unpin — use default)" row to the picker. |
| `pin promote <comp>` | `_pin_promote` :1894 | **no** — TUI prints "run `configsys pin promote`" as a deferred exit note (menu :1524) | Gap; the TUI itself asks the user to go to the CLI. Config screen already has `move` (local⇄primary) for settings — the same verb belongs on pins. |
| `picks list/add/rm --machine` | `cmd_picks` :1474 | **yes** — Profiles `track-one`/`track-all`/`machine-target`/`comp-machines` | Parity (both via `actions.set_included`). TUI does NOT call `invalidate_location_cache` (MED #3). |
| `picks to-primary` | `actions.move_picks_to_primary` | **no** | Gap; a natural `move` action on Profiles (mirrors Config `move`). |
| `machine list/show/add/rm/use` | `cmd_machine` :3340 | **yes** — `_machines_modal` (add/remove/rename/use) | Parity; TUI additionally has **rename** (`actions.rename_machine`, app:0 callers) — reverse gap: no `machine rename` CLI verb. |
| `disp list/get/set` | `cmd_disp` :1427 | **yes** — `disp-seen`/`disp-interesting`/`-all`, `mark-all-seen` | Parity; `mark_all_seen` has no CLI verb (reverse gap, minor). `disp get` output is stale (LOW #12). |
| `profile list/show` | `cmd_profile` :3393 | **yes** — Profiles screen (browse) | Parity. |
| `config show/get/set/unset/move` | `cmd_config` :3443 | **yes** — Config screen (`set_config_setting`, `move`) | Parity. |
| `theme show/list/set/unset/save/load` | `cmd_theme` :3514 | **yes** — Theme screen | Parity; TUI extra: `copy-page`, promote-to-primary (`save_theme_to_primary`, app:0) — reverse gaps. |
| `plugin list/sync/add/remove/update[--all/--latest/--pin]/bless/unbless/trust[--all]` | `cmd_plugin` :2309 | **yes** — Plugins screen actions | Parity. Note CLI `trust`/`untrust` do NOT use `actions.plugin_trust*` (MED #4). |
| `plugin untrust` | `cmd_plugin` :2448 | **partial** — `actions.plugin_untrust` is called (menu :5811) from the `trust` toggle, but `untrust` is not a listed action | Fine. |
| `plugin init` / `plugin set-source` | `cmd_plugin_init` :2196, `cmd_plugin_set_source` :2290 | **no** | `init` is the documented "fast path" to a personal plugin (README) — a one-shot with prompts; reasonable to keep CLI-only but worth an Plugins-screen action since the TUI is where users discover they have a primary. `set-source` pairs with existing `set-ref`. |
| `report [name] [--yes/--print]` | `cmd_report` :2556 | **no** — `execute_plan` persists only the LAST failure (`save_failure`, menu :577) and prints nothing about `report` | Gap: CLI offers to file interactively after a failed batch (`_offer_report` :785); TUI batch failures are silently dropped except the last. At minimum persist all + print the "run `configsys report`" hint in the summary. |
| `request <name>` | `cmd_request` :2604 | **no** | Acceptable CLI-only (an upstream-filing flow), but a `request` action on an "unroutable/missing here" component row is the natural trigger. |
| `orphans [--adopt/--remove/--ignore/--json…]` | `cmd_orphans` :1518 | **yes** — Profiles install-overlay (`toggle-install`), `claim`, `orphan-ignore`, `stage-uninstall` | Parity; TUI extra: un-ignore (`unignore_orphan`, app:0). `--json` n/a. |
| (no CLI) uninstall queue stage/unstage/clear | — (`actions.stage_uninstall`/`clear_uninstall` have 0 app.py callers) | **yes** — `stage-uninstall`, `!uninstall` node in Components | **Reverse gap**: the persisted `uninstall:` queue is TUI-only; the CLI cannot stage, list, or clear it (only `check` warns about conflicts). A `configsys uninstall list/add/rm/clear` (or `picks`-style verb) is missing. |
| `dotfiles status` | `cmd_dotfiles_status` :3213 | **yes** — Dotfiles + Glue screens | Parity (TUI extras: `manage/unmanage/move-store` — reverse gaps). |
| `dotfiles capture [names] [--force/--dry-run/--yes]` | `cmd_dotfiles_capture` :3289 | **yes** — Dotfiles `capture`/`capture-all` | Parity. |
| `dotfiles staged/activate/discard` (shell-writes guard candidates) | :3154–3197 | **no** — `shellguard.list_staged` has 0 menu.py callers; Glue screen `activate` is the glue DRIVER's shipped snippets, not guard-staged candidates | Gap: the guard's own message (shellguard.py:131) tells the user to use the CLI. Staged candidates should appear on the Glue screen as an "inactive (guard-captured)" group. |
| `manpages install/status` | `cmd_manpages` :2652 | n/a | — |
| `show routes\|config [--path]` | `cmd_show` :2730 | n/a | — |
| `keys` | `cmd_keys` :2711 | **yes** — `?` help modal (`_help_modal` :1051) | Parity. |
| `tui` | `cmd_tui` :1232 | — | — |
| global `--pretend` | `Runner(pretend=)` | **partial** — TUI honors pretend for pins/execute, but `_apply_method_pin` returns `changed=False` under pretend so nothing reloads | Fine. |
| global `--machine NAME` | `Context.machine_override` :143 | **yes** — Profiles `machine-target` | Parity. |

**Headline gaps (TUI lacks):** `set-version`, `fix-scope`, `install --no-deps`, `pin unset`,
`pin promote`, `picks to-primary`, `dotfiles staged/activate/discard`, `report` after a failed
batch, `plugin init/set-source`, and the full `check` lint.
**Headline reverse gaps (CLI lacks):** uninstall-queue stage/clear, `machine rename`, orphan
un-ignore, theme copy-page / promote-to-primary, dotfiles manage/unmanage/move-store.

---

## Findings

### [HIGH] correctness — `_dispatch_op` and `cmd_location` never apply `locations:` overrides
- **Where:** `configsys/app.py:642` (`_dispatch_op` calls only `ctx.apply_scope_default(units)`),
  `configsys/app.py:1644-1666` (`cmd_location`), `configsys/app.py:1697-1708` (`_location_lines`).
  Compare `load_pipeline` :433-434 and `inspect_components` :471-472, which call BOTH
  `apply_scope_default` and `apply_locations`.
- **Issue:** `Context.apply_locations` :349 stamps the per-component `locations:` config override
  onto `rc.fields['location-override']`, which is the ONLY thing `driver.py:162` reads. The CLI op
  path resolves fresh units via `routes.resolve_with_roots(names)` and never stamps it, so
  `configsys install|remove|upgrade|lock <x>` for a component whose install dir the user relocated
  targets the DEFAULT dir. `configsys location <x>` (and the `--all` glue cache) likewise prints
  the default path. The TUI is unaffected because it executes against `load_pipeline` states.
- **Why it matters:** "no surprises" — an `install` from the CLI double-installs at the default
  dir; a `remove` from the CLI reports success against a dir that doesn't hold the install; the
  shell glue cache points PATH at the wrong dir. Silent, and CLI-vs-TUI inconsistent.
- **Verified:** test/test_locations.py has only three unit tests (config merge, helper,
  path-driver) — no test drives `_dispatch_op`/`cmd_location` with a `locations:` entry.
- **Recommendation:** Fold both stamps into one `Context.prepare_units(units)` (scope + locations)
  and call it in every place units are resolved for use (`load_pipeline`, `inspect_components`,
  `_dispatch_op`, `cmd_location`, `_location_lines`, `_swap_headsup`). Add a test:
  `--home` config with `locations: { lazygit: ~/tools/lg }`, then `--pretend install lazygit`
  asserts the tarball command targets `~/tools/lg`, and `location lazygit` prints it.

### [HIGH] code-reuse / parity — the op execution loop exists twice and has drifted
- **Where:** `configsys/app.py:670-745` (`_dispatch_op` loop) vs `configsys/tui/menu.py:525-578`
  (`execute_plan`).
- **Issue:** Both loops do arm/finish shellguard, dispatch by op, Ctrl-C, `end_sudo`, ledger save.
  But the CLI loop additionally has: (a) `res.advisory` handling :710 ("needs your input" — e.g.
  dotfiles refusing to clobber); (b) verify-after-fail downgrade via `_installed_despite_failure`
  :722 (apt exits non-zero on a failed Recommends while the package IS installed); (c) the
  `set-version` op :687; (d) persists EVERY failure record (`save_failures`) and calls
  `_offer_report`; (e) auto-tighten resident-provider upgrades folded into the plan :655 and
  `print_reboot_advisory` :744. The TUI loop has none of (a)-(d): an advisory result shows as a
  bare `exit N: <last line>` failure; a sysdig-style install shows FAILED though it succeeded;
  `set-version` falls to `res = None` :557; only `last_failure` is saved (`save_failure` :577) so a
  3-failure batch leaves 2 unreportable. (The TUI does handle the reboot chip separately at
  :6285 and plan_with_swaps/refresh-before-plan in `_confirm_and_execute`.)
- **Why:** This is exactly the class of drift actions.py's docstring promises to prevent ("the TUI
  is a skin over these, never a parallel implementation"). Every op-loop fix lands once.
- **Recommendation:** Extract `actions.run_plan(ctx, plan, *, ledger, version=None, on_line=print)
  -> [OpOutcome]` carrying (a)-(d) and the shellguard/Ctrl-C/end_sudo/ledger bookkeeping; have
  `_dispatch_op` print from outcomes and `execute_plan` become a one-line call. Move `OpOutcome`
  and `_fail_detail` to actions. Then `set-version` and `--no-deps`/auto-tighten come to the TUI
  for free (plan-building can move too: `actions.build_plan(ctx, names, op, *, no_deps)`).

### [MED] parity bug — TUI never invalidates the glue location cache
- **Where:** `configsys/app.py:1854,1889,1509` call `invalidate_location_cache` after `pin set`,
  `pin unset`, `picks add/rm`. `configsys/tui/menu.py` has zero references to
  `invalidate_location_cache`/`write_location_cache`; `_apply_method_pin` :1511,
  `_apply_provider_pin` :1636 and the Profiles `track-*` path (`actions.set_included`) never drop
  `paths.glue_locations_file`.
- **Issue:** A method pin made in the TUI (e.g. nushell native→tarball) changes WHERE the tool
  installs, but the shell glue keeps reading the stale `glue-locations.tsv` (paths.py:95) — PATH
  points at the old dir until something else invalidates it.
- **Recommendation:** Move `invalidate_location_cache`/`write_location_cache`/`_location_lines`
  into actions (or a `locations.py`) and call invalidation from INSIDE `actions.set_included` and a
  new `actions.set_pin`, so neither skin can forget it. (Also: `add_machine`/`remove_machine` don't
  invalidate either; harmless today since the cache is per-current-machine, but `machine use`
  changes which picks are current and SHOULD invalidate — `set_machine_active` doesn't.)

### [MED] code-reuse — pin write logic lives in app.py and is re-implemented in the TUI
- **Where:** `configsys/app.py:1807-1937` (`_validate_pin`, `_pin_list/_set/_unset/_promote`,
  `_swap_headsup`) vs `configsys/tui/menu.py:1511-1525, 1636-1650`.
- **Issue:** Neither is in actions.py. The TUI copy skips `_validate_pin` (safe today because the
  picker only offers candidates) and the cache invalidation (above). `_pin_promote` duplicates the
  primary-data-file lookup that `actions._primary_data_file` :631 already centralizes — and its
  own docstring says "Mirrors the edit_target / _pin_promote idiom", i.e. the duplication is
  acknowledged. `docs/tui-screens-plan.md:57,118` planned a `pin_promote` extraction.
- **Recommendation:** `actions.set_pin(ctx, name, value, *, validate=True) -> (changed, label,
  note)`, `actions.unset_pin`, `actions.promote_pin` (using `_primary_data_file`); `_pin_*` and
  the TUI helpers become callers. Then add `unpin` + `promote` rows to the TUI picker (parity
  table).

### [MED] code-reuse — `cmd_plugin trust/untrust` re-implements `actions.plugin_trust*`
- **Where:** `configsys/app.py:2404-2457` vs `configsys/actions.py:899-951`
  (`plugin_trust`, `plugin_trust_all`, `plugin_untrust`). The TUI uses the actions versions
  (menu :5811-5817); the CLI does not.
- **Issue:** Two copies of the trust logic; the CLI `--all` path writes trust directly via
  `plugins.set_trust` using the status row's `identity` while `actions.plugin_trust_all` re-hashes
  via `plugin_identity` — a subtle divergence if status caching ever lags the disk. Also
  `app._find_decl` :2170 is a verbatim copy of `plugins.find_decl` :1126 (same signature, same
  body); the comment at :2181 even notes it survives only for the trust branch.
- **Recommendation:** Delete `_find_decl`; make the `trust`/`untrust` branches call
  `actions.plugin_trust(_all)`/`plugin_untrust` and print the returned note (`re-approved` vs
  `trusted` wording can be returned by the action).

### [MED] comment/help drift — argparse help (= the man page source) documents retired models
- **Where (all `configsys/app.py`):**
  - :2824 `inspect` "show install state of the active profiles"; :2765 epilog "for the active
    profiles"; :3055 `orphans` "no active profile accounts for"; :3079 `dotfiles status` "every
    dotfile in the active profiles"; :1136 refresh "no discoverable versions in the active
    profiles"; docstrings :3120, :3214, actions.py:957. **Active profiles were retired** — the
    install set is `picks:` (`_install_scope_label` :591 already says so).
  - :2864 `machine` help: "view or edit `machines:` — named profile-sets that overlay the shared
    profiles (a composing layer per machine)". Machines are now the keys of `picks:`
    (config.py:352 `machine_names` = `picks().keys()`); there is no `machines:` section.
  - :2014-2019 `check` warning text: "not defined in any `machines:` block — this box resolves
    shared + local profiles only". The check itself is still valid (selected machine has no picks
    column) but the message describes the retired model.
  - :2877 `disp` help "(the v2 triage state) … include/exclude live in your profiles" and
    :1428 docstring. Under the matrix model Included = picks; there is no profile include/exclude.
  - :2924 `check` help and :1950 docstring "repo + ~/configsys.hu"; :1421 `where` error "your
    ~/configsys.hu"; :281 `_resolver` comment. `~/configsys.hu` is the LEGACY path that
    `_migrate_user_config` moves away.
  - :2818-2819 `-v` help mentions "per-unit state" (fine) — OK.
- **Why:** `man/configsys.1` is generated from these strings (`tools/gen_manpages.py`, see
  :2665); the shipped man page :75-83 currently says "named profile-sets", "v2 triage state".
- **Recommendation:** One sweep replacing "active profiles" → "this machine's picks / install
  set", fixing the `machine`/`disp`/`check` strings, then regenerate the man page.

### [MED] test gaps — the op loop's branches and half the subcommands are untested at the CLI level
- **Where:** test/test_app.py (556 lines, 50 tests); sweep of test/ for `main([... '<cmd>' ...])`.
- **Issue:** No `main`-level test for `upgrade`, `unlock`, `set-version`, `machine`, `picks`,
  `versions`, `profile`, `theme`, `refresh`, `keys` (their action-layer halves ARE tested in
  test_picks/test_theme_edit/test_versionreport, but the argparse wiring + output formatting are
  not). Inside `_dispatch_op`: the `advisory` branch :710, the verify-after-fail branch :717-734
  (only the pure helper `_installed_despite_failure` is tested), `--no-deps` :646, auto-tighten
  fold-in :655, `_offer_report` non-tty path :803. `expand_plan` (test_planning.py) never
  exercises `set-version` as an installish op, a dependency cycle (`dependency_order` claims
  "cycles are broken"), or a dep that is present in `states` but whose OWN dep is missing.
  test_app.py :116, :223, :279 still author configs with the retired `configs:`/`profiles:` keys —
  they pass only because retired keys degrade to a warning; the fix-scope test asserts nothing
  about picks.
- **Recommendation:** Add pretend-mode `main` tests per missing verb (cheap: same fixture as
  `test_pretend_install_emits_apt_command_without_executing`), a fake-driver test for the advisory
  and installed-with-warning branches, and a `expand_plan` cycle test. Migrate the three tests to
  `picks:`.

### [MED] security — `_offer_rekey` runs `sudo curl -o <path>` with a path taken from plugin data
- **Where:** `configsys/app.py:1018` (`ctx.runner.run(f'sudo curl -fsSL {key_url} -o {key_path}')`)
  fed by `_source_key_fields` :968 reading `pubkey-url`/`pubkey-path` from ANY loaded route
  binding; `_owned_index_sources` :882 likewise trusts `source-path`.
- **Issue:** Data plugins are not trust-gated (only code is). A malicious/compromised data plugin
  can declare `source-path: /etc/apt/sources.list.d/x.list  pubkey-path: /etc/sudoers.d/zz
  pubkey-url: https://evil/…`, and on a signature failure the user is prompted "Re-fetch the
  signing key for `comp` into /etc/sudoers.d/zz and retry? [y/N]". The path IS shown, so a careful
  user can decline — but the prompt frames it as routine. Both args are `shlex.quote`d, so no
  shell injection. (`_reconcile_managed_sources` :1060 is safe: it only `rm`s files enumerated
  from the fixed `_INDEX_SRC_DIRS`.) The apt/dnf drivers write the same fields at install time,
  so this is a wider "data plugins write root-owned files" property, not unique to refresh.
- **Recommendation:** Constrain `pubkey-path` (and `source-path`) to the package manager's
  keyring/source dirs at `routecheck` time (`/etc/apt/keyrings`, `/usr/share/keyrings`,
  `/etc/apt/trusted.gpg.d`, `/etc/pki/rpm-gpg`, `/etc/apt/sources.list.d`, …) and refuse
  otherwise; `check` then flags a plugin that strays. Cheap and closes the whole class.

### [MED] refactor — app.py is five modules wearing one file
- **Where:** `configsys/app.py` (3658 LOC). Natural seams: `Context` :114-561 (context.py);
  package-index refresh + diagnosis + rekey + reconcile :882-1230 (`indexrefresh.py`, already
  unit-tested in isolation by test_index_diagnosis/test_index_rekey/test_source_reconcile);
  `cmd_plugin` + init + set-source :2164-2496; `cmd_check` :1940-2162; dotfiles commands
  :3116-3338; parser + epilog :2760-3113; report/request/manpages/show :2498-2758.
- **Why:** The module already has to lazy-import inside functions to dodge cycles (:1237,
  :1430, :1521, …), the TUI lazy-imports `app` (menu :526, :6311) for the same reason, and the
  `_COMMANDS` table :3563 is the only thing tying handlers to names — a `commands/` package with
  a registration decorator would make each file own its parser slice too.
- **Recommendation:** Split behind a compatibility shim (`app.py` re-exports the names tests and
  tools/versionsweep.py import: `main`, `build_parser`, `Context`, `where_report`,
  `where_profile_report`, `maybe_refresh_before_plan`, `cmd_refresh`, `_dispatch_op`,
  `diagnose_index_failure`, `_rekey_candidates`, `_reconcile_managed_sources`,
  `_orphaned_managed_sources`, `_source_key_fields`, `_offer_rekey`, `_find_source_files`,
  `_send_report`, `_URL_PREFILL_LIMIT`, `_install_scope_label`, `_installed_despite_failure`,
  `cmd_disp`, `cmd_check`). External plugin repos (blender/kicad tests) import only
  `configsys.runner/paths/plugins/componentObj`, so the public plugin ABI is untouched.

### [LOW] perf — `diagnostics()` runs two to three times per command and re-resolves the world
- **Where:** `load_pipeline` :449 computes `self.diagnostics(states)` to stream warnings;
  `cmd_inspect` :582 calls it again; the TUI calls it at menu :5105 and on every `_reload` :1392.
  Each call: `ensure_plugin_code`, `plugins.status()` (walks every plugin dir + hashes),
  `flooradvise.advise` + `resident_advise`, and `_dotfiles_diagnostics` :3126 →
  `actions.dotfiles_units` :960 → a FULL `routes.resolve_resilient(requested)` just to find the
  dotfiles/glue units — which `load_pipeline` had already resolved.
- **Recommendation:** Memoize the last diagnostics on the Context keyed by `id(states)` (cleared by
  `invalidate()`), and have `dotfiles_units` accept an already-resolved `units` dict. The startup
  batch prepasses themselves (apt/flatpak/npm) live in installState and are still correct; this is
  the remaining redundant work on the app side.

### [LOW] code-reuse — `cmd_refresh` re-declares `_NATIVE_REFRESH` inline and double-imports
- **Where:** `configsys/app.py:1173-1175` re-types the exact dict that `_NATIVE_REFRESH` :1068
  holds; `from . import refreshstate` at :1146 and again :1171; `refresh_native_index` :1073
  (retry + native lookup) is NOT used by `cmd_refresh`, which re-implements the same
  `retry_transient(...)` call :1184.
- **Recommendation:** `cmd_refresh` → `pm, cmd = _native_refresh_cmd(ctx)`; use the constant.

### [LOW] code-reuse — `cmd_orphans --ignore` and `--adopt` partially bypass actions
- **Where:** `configsys/app.py:1525-1533` builds the list and calls `set_config_setting` directly
  instead of `actions.ignore_orphan` :189 (which the TUI uses); the difference is multi-pattern
  support. `stage_adopt` :68 IS used (:1540). `unignore_orphan` has no CLI verb.
- **Recommendation:** Let `ignore_orphan` accept a list; add `--unignore`.

### [LOW] design — `ctx.paths.dotfiles_force` is an attribute injected onto `Paths` as a side channel
- **Where:** `configsys/app.py:857,866` set `ctx.paths.dotfiles_force`; the dotfiles driver reads
  it. `Paths` never declares it (paths.py has no `dotfiles_force`), so a driver constructed from a
  bare `Paths()` (tests, plugins) must `getattr(..., False)`.
- **Recommendation:** Pass `force=` through the driver call (`drv.install(rc, force=…)`) or make
  it a declared `Paths` field with a default — and it becomes a natural TUI checkbox.

### [LOW] naming/drift — `_shell_glue_root` + shellguard stage under the DOTFILES root after glue was segregated
- **Where:** `configsys/app.py:628-631` (`_shell_glue_root` = `primary_dotfiles_dir or
  user_dotfiles_dir`), matching `shellguard._capture_root` :93-96. paths.py:102-108 now defines a
  separate `user_glue_dir`/`primary_glue_dir` "so config captures and shell glue never share a
  tree" — yet guard-STAGED glue candidates still land in `<dotfiles-root>/staged-glue/`.
- **Recommendation:** Point both at the glue root (`primary_glue_dir or user_glue_dir`) with a
  one-time migration of any existing `staged-glue/` dir; then the Glue screen can list them (parity
  table).

### [LOW] comment drift — `cmd_disp get` reports the retired include semantics
- **Where:** `configsys/app.py:1456-1457`: `if c in cfg.user_layer_components(): state = 'include
  (in one of your profiles)'`. Under the matrix model being in a user-authored profile is NOT
  inclusion; `cfg.included()` (picks) is. (config.py:158 `user_layer_components` and :175 `is_new`
  carry the same legacy notion — out of scope, but the CLI output is where a user sees it.)
- **Recommendation:** `state = 'tracked (picked on <machine>)' if c in cfg.included() else …`.

### [LOW] dead code — `_STATUS_LABEL` is an identity map; `_unskip` is defined mid-import and duplicated
- **Where:** `configsys/app.py:103-111` — every value equals its key, and the only use is
  `.get(s.status, s.status)` :576 (a no-op). `configsys/app.py:21-23` defines `_unskip` BETWEEN two
  import blocks (E402-style; the imports at :24-32 follow it); `Context.diagnostics` :187 defines an
  identical inner `unskip`.
- **Recommendation:** Delete `_STATUS_LABEL`; move `_unskip` below the imports and use it in
  `diagnostics`.

### [LOW] resource leak — `_send_report` leaves a tempfile behind on every `gh` attempt
- **Where:** `configsys/app.py:2515-2517` `NamedTemporaryFile(delete=False)` is never unlinked
  (success or failure path). Also `cmd_show` :2755 re-imports `os` (already imported at :10).
- **Recommendation:** `try/finally: os.unlink(bodyfile)`.

### [LOW] ABI/interface — app.py reaches into private APIs of resolve and drivers
- **Where:** `where_report` :1293 imports `resolve._select`; `cmd_refresh` :1127 calls
  `drv._disco_spec(rc)`; `cmd_keys` :2719 reads `km._m`. menu.py copies the `_select` reach
  (:1622).
- **Why:** These are the exact seams a future `resolve`/driver refactor would break, and
  `where_report` is a public shared-text function used by the TUI and tests.
- **Recommendation:** Promote `_select` to `select_with_reason` (public), `_disco_spec` to
  `disco_spec` on the Driver ABI, and give `Keymap` an `items()`.

### [LOW] feature gap — no CLI surface for the `uninstall:` queue
- **Where:** `actions.stage_uninstall` :51 and `clear_uninstall` :209 have zero app.py callers;
  `build_parser` has no `uninstall` verb; only `cmd_check` :2027 mentions the queue.
- **Issue:** A removal staged in the TUI persists in the top config; from a shell the user can
  neither see it, unstage it, nor clear it without hand-editing. Conversely `configsys remove`
  acts immediately and never consults the queue.
- **Recommendation:** `configsys uninstall list|add|rm|clear` mirroring `picks`; optionally
  `remove --stage`.

### [NIT] `_offer_primary` prompts inside `load_pipeline`
- **Where:** `configsys/app.py:395` → `ensure_user_config(offer_primary=True)` → interactive
  `input()` :381 on a TTY. Any first-run TTY command that loads the pipeline (`inspect`, `install`,
  `refresh`, …) blocks on a prompt before doing its job; `--pretend` is not consulted.
- **Recommendation:** Only offer from `cmd_tui`/`main` when `command == 'tui'`, or gate on
  `not args.pretend`.

### [NIT] README command block omits 9 of 29 subcommands
- **Where:** `README.md:199-219` lists 20 commands; missing: `machine`, `disp`, `picks`,
  `versions`, `profile`, `config`, `theme`, `orphans`, `keys` — all of which exist in the parser
  (:2864-3111) and the man page. `picks` is THE install-set editor in the matrix model, so its
  absence from the README is the most visible.

### [NIT] `expand_plan` treats a `set-version` batch's deps as plain installs — undocumented
- **Where:** `configsys/planning.py:13,63`: `_INSTALLISH` includes `set-version`, and folded deps
  get `ops[dep] = 'install'`; the module docstring :1-11 mentions only install/upgrade. Also
  `dependency_order` :17 "Cycles are broken" — true (the `active` set), but the order chosen for a
  cycle is whichever node was visited first, i.e. alphabetical; worth a one-line note since a
  swap-remove (:76) sorts by that index.

### [NIT] `cmd_refresh(ctx, None)` from the TUI relies on `args` being unused
- **Where:** menu.py:6312 passes `None`; `cmd_refresh` :1112 never touches `args` — fine today,
  but any future `--flag` on `refresh` will crash the TUI path. Make the signature
  `cmd_refresh(ctx, args=None)`.
