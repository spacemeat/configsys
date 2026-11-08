# Review: Config, settings + the layer stack

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/config.py`, `configsys/hutext.py`, `configsys/layers.py`, `configsys/troveio.py` (all read line by line).
Context: `config.hu`, `docs/config-format.md` (layers, settings, picks, includes), `configsys/actions.py` (settings
registry + edit routing, 320-470 / 600-960 / 1100-1120), plus the call sites the findings run through:
`plugins.py` (section writers 785-1110, `plugin_of_source` / `command_source_trusted` 431-456, `_data_files` /
`_data_sections`), `routes.py` `load` 312-380, `humerge.py` `_key` 307-318, `app.py` (`Context`, `diagnostics`,
`cmd_check`, `cmd_config`), `driver.py` `location_override`, `drivers/tarball.py`, `paths.py`.
Tests read: `test_config_overlay.py`, `test_includes.py`, `test_hutext.py`, `test_troveio.py`,
`test_fix_routing_layers.py`, `test_fix_routing_layers2.py`, `test_config_edit.py`, plus the test lists of
`test_config_move.py`, `test_picks.py`, `test_uninstall_queue.py`, `test_dispositions.py`,
`test_review_regressions.py`, `test_fix_final.py`.

Every **(reproduced)** item was run with `.venv/bin/python` against a sandbox under
`$RUN/scratch/config-layers/` (`--home …/homeN`); `$S` below is that scratch dir.

**Verification** (2026-11-08, adversarial checker, opus). Re-run independently: config-layers-01, -02, -03, -04
and -07, which is every CRITICAL and HIGH finding plus the MED security and safety ones. Each has a **Verified:**
block. `$V` = `$RUN/scratch/verify-config-layers/`. Every run used `--home $V/home/<case>` with the process
`HOME=$V/fakehome`. Nothing was installed, and nothing ran except a `touch` into `$V`. Result: all five confirmed,
no severity changed.

## Carried over from docs/review-2026-09/config-plugins.md (+ README items A5, B7, D5, D8)

Only the findings whose code is in config.py / layers.py / troveio.py / hutext.py; the plugins.py ones
(`remove_sections`, the `rfind('}')` insert, the readers, trust identity, transitive `plugins:`) belong to the
plugins area and are re-reported there (plugins-02/03/05/10/11).

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] include dedup by realpath demotes the user's top config (README A5) | open | re-reported as config-layers-03; `_visit` still keys `done` on realpath alone (`layers.py:166-171`); reproduced end to end below |
| [MED] `_KNOWN_TOP_KEYS` misses `locations` / `reboot-advice` (README B7) | fixed | 7f43966 (B7), then 2a577c0 made `_KNOWN_TOP_KEYS` ⊇ `MACHINE_SETTING_SECTIONS` and `unknown_section_warnings` unions `machine_setting_sections()`; `test_every_registered_config_setting_is_forbidden_from_a_plugin` |
| [MED] machine-setting knowledge in four places (README D5) | open | 2a577c0 completed `MACHINE_SETTING_SECTIONS` and forbids all of it from include/plugin layers (fixed half); the parsing/validation half is still per-getter → config-layers-06 (bugs) + config-layers-20 (the registry) |
| [MED] `humon.from_file` rejects a `{}` file (BADENCODING) | open | config-layers-05; still `humon.from_file` at `layers.py:119,175`; any file under 10 bytes fails |
| [MED] section scanner desyncs on `\` / backtick strings | fixed | 0c62c22 (review-2026-11 D3: `hutext.skip_trivia` has no escapes, three quote styles; `test_hutext.py`). The scanner has a different, worse defect → config-layers-01 |
| [MED] `profiles_containing` O(profiles × expansion) per call | fixed | d0cf422 (`_pc_index`, `config.py:490-510`) |
| [MED] config-format.md teaches retired constructs | fixed | acfdecc; the doc now describes picks / machine / the uniform layer rule (read 1-350) |
| [MED] stale module docstrings (layers / config / dispositions) | open | layers.py module docstring fixed in 2a577c0; config.py's (`configs`, "repo/user"), `read_setting` (`discover:`), `dispositions()` remain → config-layers-22 |
| [LOW] `keys:` merges from every layer incl. untrusted plugins | obsolete | decided by design: config-format.md "`theme:` and `keys:` are cosmetic: every layer may contribute them", and `check` reports cross-layer key steals (`keyspec.lint_keys`, fb5208d) |
| [LOW] dead `Config._profiles` / `merge_named` | open | config-layers-23 |
| [LOW] phantom `'machine'` layer role | open | removed from `_MACHINE_ROLES` in 2a577c0 (`test_machine_roles_has_no_phantom_role`), but still in `user_layer_components` (`config.py:163`) and `role_ceilings` (`:420`) → config-layers-23 |
| [LOW] `splash()` `is False` / `is True` unreachable | open | config-layers-23 |
| [LOW] inline `_selected_machine` | open | now worse: app.py:1028 and primarygit.py:384 import the private function and reach into `cfg._layers` → config-layers-24 |
| [LOW] `_PROFILE_AUTHORING_ROLES` vs user-profile weight | fixed | 2a577c0 removed it (user `profiles:` un-retired as browse categories; `test_user_profiles_are_no_longer_retired`) |
| [LOW] `_flat` ≈ `config._leaves`; `merge_name_overrides` ≈ `merge_version_floors` | open | config-layers-21 |
| [LOW] `Config.load(paths, plugin_files=…)` takes bare paths or tuples | open | `config.py:73-74` → config-layers-24 |
| [LOW] `Config.PICKS_PROFILE` has no reader | open | config-layers-23 |
| [LOW] `Layer.role` docstring vs the `'machine'` role | fixed | 2a577c0 (the role is gone; `layers.py:134` lists the five real roles) |
| [NIT] `troveio._scalar(None)` → `""`; `emit_hu` unused by the section writers | open | folded into config-layers-21 |
| [NIT] `materialize` drops empty keys | open | folded into config-layers-13 (with the duplicate-key case) |
| README D8 — consolidate the hand-rolled humon text I/O | open | 0c62c22 moved the scanner + quoting into hutext (half done); the scalar-end fix stayed in humerge and `troveio._emit` still duplicates `hutext.emit` → config-layers-01 / -21; the plugins.py readers are plugins-10 |

## Cross-cutting themes

- **Text surgery that never checks its own result.** configsys edits your config as text through a scanner
  whose idea of "the value" differs from humon's: a scalar runs to end of line (or, if quoted, past the
  string to the end of the *next* line), `//` inside a bare word is a comment to humon but not to the
  quoting rule, a key after `,` or in quotes is invisible. No writer re-parses before writing — except humerge,
  which already found and patched the scalar-end bug locally (`humerge.py:316`, "a scalar ends at its token,
  not the line's end") without pushing the fix down into `hutext`. Result: config-layers-01, -02, -13.
- **The layer stack identifies a layer by its file path, not by the root that brought it in.** Dedup
  (`done` by realpath), command trust (`plugin_of_source` by realpath) and include reach (unconfined) all ask
  "where is this file?" instead of "which root owns this layer?", so a plugin can demote your own config
  (-03) or launder an out-of-tree file into user trust (-04). `plugins._data_sections` already assumes
  includes stay inside the plugin tree; the loader doesn't enforce it.
- **Setting values are validated nowhere central.** Each getter parses its own tokens (three bool dialects),
  `config set` validates 4 of ~20 settings, `check` warns on the same 4, and path values (`locations:`) reach
  `rm -rf` in the tarball driver raw (-02, -06, -07, -17).
- **Warnings computed but not delivered evenly.** `check` throws away `expand_tolerant`'s skip warnings (a
  malformed primary reads "0 errors"); the TUI `!` page throws away `setting_value_warnings` (-08, -18).

## Findings

### config-layers-01 [CRITICAL] safety — editing a scalar setting deletes the lines after it (or corrupts the file)
`configsys/hutext.py:64-93` (`value_end`), reached through `section_span` (`:96-128`) from
`plugins.set_section` (`plugins.py:810-834`) — the write path of `config set` / `unset`-then-set, `machine use`,
the TUI Config screen, `set_machine_active`, every scalar setting in the primary.

`value_end` opens with a `skip_trivia` loop (`:68-73`) that skips **quoted strings** as well as blanks, then
treats whatever token follows as the value and runs it to end of line (`:92-93`). So:
- an existing **quoted** scalar (`scope: "user"`) is skipped as "trivia", the scanner lands on the *next* key,
  and the span runs to the end of *that* line — replacing it deletes the next line's section (silently, if it
  was one line) or cuts a multi-line block open (the file stops parsing);
- an existing **bare** scalar with anything after it on the line (`{ scope: user  machine: laptop … }`, or
  `scope: user }`) loses everything to end of line, including the root's closing brace.

The top config is not under version control, so the lost lines are gone; in the primary the damage is
committed by the write journal (and pushed under `primary-push: auto`). humerge hit the same thing and fixed
it locally (`humerge.py:316-317` uses `scalar_end`); `section_span`'s other callers didn't get the fix.

**(reproduced)** silent loss of the whole install matrix line, valid file afterwards:
`p9_quoted.py` on `{ machine: "laptop" / picks: { laptop: [ btop  ripgrep ] } / pins: {…} }` →
`span of machine: 'machine: "laptop"\n    picks: { laptop: [ btop  ripgrep ] }'` →
`after: '{\n    machine: desk\n    pins: { btop: native }\n}\n'` (picks gone, file parses).
**(reproduced)** CLI, multi-line picks: `printf '{\n    scope: "user"\n    picks: {\n        laptop: [ btop  ripgrep  neovim ]\n …' > …/home10/…/configsys.hu; configsys --home $S/home10 config set scope system`
→ `configsys: set scope = system  (in top config)`, file now `{\n    scope: system\n        laptop: [ btop … ]\n …`,
next command: `could not read (Trove has syntax errors: … TOOMANYROOTS …)`.
**(reproduced)** CLI, one-line config: `{ scope: user  machine: laptop  picks: {…}  pins: {…} }` →
`config set scope system` → file `{ scope: system\n` → `could not read (… UNEXPECTEDEOF)`.
Also: `scope: user  // keep me` loses the comment (`p2_variants.py`, `trailing_comment`).
No file in `~/src/configsys-*` or `config.hu` has a quoted top-level scalar configsys rewrites today, so this
hasn't fired on the user's own data yet; it fires on any hand-written `key: "value"` (a JSON/YAML habit, and
legal humon) and on any value configsys itself had to quote (`scalar()` quotes a value with a space or `:`).

**Fix:** (1) `value_end`: skip only blanks/comments (`skip_blank`), then brace-match a `{`/`[` value, else
`return scalar_end(text, i)` — i.e. move humerge's `_key` correction into hutext and delete it there.
(2) validate-then-commit in `set_section`: re-parse the edited text and require that every top-level key
other than the edited one materializes unchanged (humerge's `_load(text) != merged` guard); refuse the write
with a clear error otherwise. (3) tests: replace an existing quoted scalar followed by a one-line and a
multi-line sibling, a bare scalar mid-line, a scalar on the closing-brace line; tighten
`test_hutext.py:18` (it asserts only `startswith`, which hides the overrun). **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). CRITICAL kept. Nothing guards this: `set_section` writes whatever the splice
produces. The only scalar-edit tests (`test_config_edit.py:13`, `test_review_regressions.py:22-38`) insert into a
file that lacks the key, or replace a bare scalar that is alone on its line.
- **Silent loss through `machine use`.** `$V/home/h01b` = `{ machine: "laptop" / picks: { laptop: [ btop  ripgrep ]
  desk: [ zsh ] } / pins: { btop: native } }`. Running `configsys --home $V/home/h01b machine use desk` prints
  `this box is now machine "desk"  (in top config)`. The file is now `{\n    machine: desk\n    pins: { btop: native
  }\n}`. Then `picks list` gives `picks for desk (0)` and `machine list` gives `no machines defined`. Both machines'
  picks are gone, the file is valid, and nothing warns.
- **Brick through `config set`.** `h01a`: `scope: "user"` followed by a multi-line `picks:`. `config set scope system`
  prints `set scope = system  (in top config)`, and the next command fails with `could not read (… TOOMANYROOTS …)`.
  `h01c`: a one-line `{ scope: user  machine: laptop  picks: {…}  pins: {…} }` becomes `{ scope: system\n`
  (`od -c`), and the next command fails with `UNEXPECTEDEOF`, rc=1.
- **configsys can brick the file on its own.** `h01d`: `config set splash "my splash"` writes `splash: "my splash"`.
  It is quoted because of the space, and it is the last key, since inserts go before the root brace. The next
  `config set splash plain` eats the closing `}`, and the next command fails with `UNEXPECTEDEOF`. So no hand edit
  is needed, only a value `config set` accepts unvalidated (see -06).
- **Direct `plugins.set_scalar_section` (scratch).** `scope: "user"` followed by `disabled-drivers: [ snap ]`
  silently deletes the `disabled-drivers` line, which turns snap back on. `scope: user }` on the closing-brace line
  loses the brace (`UNEXPECTEDEOF`). `scope: user  // keep me` loses the comment.
- **Why CRITICAL stands.** This is data loss from everyday commands (`config set`, `machine use`, the TUI Config
  screen). The loss is silent whenever the next section fits on one line, and the top config has no history.
  Calibration note: `test_hutext.py:18`'s `startswith` is loose, but nothing follows `last: x` on that line, so it
  isn't hiding a live overrun.

### config-layers-02 [HIGH] safety — the shared quoting rule misses `//` and `/*`, and several writers bypass it: a `locations:` path can come back as `~/apps` and be `rm -rf`'d
`configsys/hutext.py:11` (`UNSAFE`) and `:14-31` (`scalar`); downstream `driver.py:311`,
`drivers/tarball.py:41-55,125-126`. Writers that skip the rule: `plugins.set_list_section` (`plugins.py:1011`,
raw `str(i)`), `_emit_picks` / `_emit_pins` / `_emit_map_packed` (raw keys, `:855,928-930`).

humon treats `//` and `/*` as comment starts **inside a bare word** (`{ a: x//y\n b: 1 }` reads `a: x`), but
`UNSAFE` has no `/`, so `scalar()` emits such values bare. A `//` value is truncated on re-read; a `/*` value
opens an unterminated block comment and bricks the file. `locations:` values are paths, and `//` arises
naturally from an empty shell variable (`$HOME/apps/$X/lazygit`). The truncated path is the parent dir — for a
category-dir path that is `~/apps`, which the tarball guard does not refuse (it refuses `$HOME`, the scope
bases and `/`, `/opt`, … only), and tarball `install` runs `rm -rf <dir> && mv <stage> <dir>` unconditionally.
Separately, `set_list_section` doesn't quote at all (`config set orphans-ignore 'my app'` stores two entries),
and `_emit_picks` writes the machine name raw as a key.

**(reproduced)** `config set locations "ripgrep=$H/apps//ripgrep"` → `config get locations` →
`ripgrep=…/home3/apps`; with `pins: { ripgrep: tarball }`, `p3_guard.py` → `_safe_install_dir: (PosixPath('…/home3/apps'), None)`
(not refused), so the next `install ripgrep` would run `rm -rf …/home3/apps` — every other app in `~/apps`.
**(reproduced)** `config set locations 'x=/opt/x/*'` → next command: `could not read (… UNFINISHEDCSTYLECOMMENT …)`.
**(reproduced)** `configsys machine add "my box"` → `machine "my box" created`, file `picks: { … my box: [] }`,
every later command: `could not read (Trove has syntax errors: [line 4, column 12: SYNTAXERROR])`.
**(reproduced)** round-trips: `hutext.scalar('x//y')` → `x//y` → re-read ERR; `'a/*b'` → ERR; a value holding
all three quote characters loses its backticks (`'"\'`all'` → `` `"'all` ``).

**Fix:** in `scalar()`/`key()` quote when `'//' in s or '/*' in s` (bare-word comment starts), and make every
emitter go through `hutext.scalar`/`hutext.key` (list items, picks/pins/dispositions keys) — a test that
round-trips each writer over a hostile-value table (`a b`, `x//y`, `a/*b`, `:`, `[`, `"`, `'`, backtick) gates
it. Defence in depth: the tarball/appImage/source guards should also refuse the category dirs
(`dirs.app/sdk/src` under either scope base) and the location map should be validated at write (see -07);
config-layers-01's verify-before-write catches the bricking cases. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept.
- **humon truncates at `//`.** In `$V/scripts/p02_humon.py`, `{ a: x//y\n b: 1 }` reads as `{'a': 'x', 'b': '1'}`.
  `hutext.scalar('x//y')` and `hutext.scalar('/opt/x/*')` both come back bare. Re-reading the second gives
  `UNFINISHEDCSTYLECOMMENT`.
- **End to end to the `rm -rf`.** `$V/home/h02a` has `pins: { ripgrep: tarball }`. `config set locations
  "ripgrep=$H/apps//ripgrep"` writes the path bare. `config get locations` then gives `ripgrep=$H/apps`, and so does
  `--pretend location ripgrep`. `v02_tarball.py` drives the real Context and tarball driver with a recording runner
  and a stubbed URL. It shows `_safe_install_dir: ($H/apps, None)` and `WOULD RUN: rm -rf $H/apps && mv
  $H/apps.configsys-stage $H/apps`: every other app in the category dir would be replaced by ripgrep's tree.
  `--pretend install` can't show this, because offline there is no cached asset and so no URL. Nothing was executed.
- **The bricks and the split.** `config set locations 'x=/opt/x/*'`: the next command fails with `UNFINISHEDCSTYLECOMMENT`.
  `machine add "my box"` prints `machine "my box" created`, writes `my box: []`, and the next command fails with
  `SYNTAXERROR`. `config set orphans-ignore 'my app'` writes `[ my app ]`, which `read_list_section` reads as
  `['my', 'app']`. `scalar('"\'`all')` gives `` `"'all` ``, dropping the backtick.
- **Nothing downstream catches it.** `_parse_map_tokens` stores the raw token. `pathlib` can't restore a `//` that
  humon already cut off. The tarball guard refuses only `/`, the shared system dirs, the home and the two scope
  bases.
- **Why HIGH, not CRITICAL.** The `rm -rf` needs a typed `//` (an empty shell variable, say) and then a tarball
  install. The bricking cases are likelier to hit (`machine add "work laptop"`).

### config-layers-03 [HIGH] security — a plugin that includes your top config (or your primary's file) demotes it, erasing your machine settings
`configsys/layers.py:166-171` (`_visit`: `if rp in done: return` regardless of the role it was visited as),
`:198-218` (`expand_tolerant`). Carried from 2026-09 A5 (also security-03).

Roots expand lowest-first (repo, plugins, primary, user). A plugin data file with
`include: [ ../../configsys.hu ]` (its dir is `<state>/plugins/<name>/`, so the relative path is fixed) visits
your top config first, as role `include`; when the `user` root comes up it is already `done` and skipped. Every
machine setting in it is then ignored (Config reads them only from repo/primary/user roles) and its definitions
(`components:` overrides, `{}` tombstones, `os:`/`drivers:` tweaks) sit *below* the plugin's. The same works
against the primary (plugins sort before it). The only signal is a set of `check` warnings that blame your own
file as "an include layer". What an untrusted data plugin could already do: add bindings that win by
specificity. What it gains: switching off your `disabled-drivers:`, `pins:`, `installer-shell-writes:` and your
component overrides, and emptying `picks:` — without trust, with no prompt.

**(reproduced)** `$S/home5`: top config with `scope: system`, `machine: laptop`, `pins`, `disabled-drivers:
[ snap ]`, `picks`; plugin `plug/plug.hu` = `{ include: [ ../../configsys.hu ] … }` →
`config get scope` → `(unset)`, `config get machine` → `(unset)`, `config get disabled-drivers` →
`(unset — built-in default)`, `pin list` → `no pins set`, `picks list` → `picks for this-machine (0)`;
without the include: `system`, `laptop`, `ripgrep -> tarball [local]`. `check` →
`warn …/configsys.hu: \`pins:\` is ignored here (not permitted from a include layer …)` ×5.

**Fix:** in `expand_tolerant` precompute the realpaths of all roots and, in `_visit`, refuse an include that
resolves to any root (warn "`include:` of a root layer ignored"); and confine a `plugin`/`primary` root's
includes to its own plugin tree (realpath containment — the rule `plugins._data_sections` already assumes; no
plugin in `~/src/configsys-*` uses `include:` at all). Regression tests in `test_includes.py` for both.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept. It also wipes one setting the reviewer didn't list:
`primary-verify: signed`.
- **The top config.** `$V/home/h03a`'s top config sets `scope: system`, `primary-verify: signed`, `machine:
  laptop`, `disabled-drivers: [ snap ]`, `installer-shell-writes: allow`, `pins` and `picks`, and declares plugin
  `plug` (never trusted; there is no trust file). `plug/plug.hu` = `{ include: [ ../../configsys.hu ]  components:
  {…} }`. Control `h03b` is the same without the include. What `config get` gives, control vs with the include:

  | setting | control | with the include |
  |---|---|---|
  | `scope` | `system` | `(unset)` |
  | `machine` | `laptop` | `(unset)` |
  | `disabled-drivers` | `snap` | `(unset — built-in default)` |
  | `installer-shell-writes` | `allow` | `block` |
  | `primary-verify` | `signed` | `off` |

  `pin list` gives `no pins set` and `picks list` gives `picks for this-machine (0)`. `check` exits 0 with
  `0 error(s), 9 warning(s)`, and the warnings blame your own `configsys.hu` as "a include layer".
- **Why `primary-verify` matters.** It is read only from the `user` role (`config.py:334`), and sync and push take
  it from `ctx.config.primary_verify()` (`actions.py:1205`, `primarygit.py:534`). So an untrusted, non-primary data
  plugin turns off the signed-only gate on the primary, the safeguard that setting exists for.
- **The primary.** `h03c` blesses `mine` (`splash: plain`, `disabled-drivers: [ snap ]`, `picks`), and `plug.hu` is
  `{ include: [ ../mine/mine.hu ] }`. It gives splash `(unset)`, disabled-drivers `(unset)` and `picks … (0)`.
  Control `h03d` gives `plain`, `snap` and `(2)`.
- **Coverage.** No test covers an include of a root: `test_includes.py` tests only cycles, diamonds, not-found and
  ignored settings. A grep finds no `include:` in any `~/src/configsys-*` plugin, so confining includes breaks
  nothing known.

### config-layers-04 [MED] security — an untrusted plugin's include (or symlinked data file) of an out-of-tree file is trusted as the user
`configsys/layers.py:166-187` (a `Layer` records only its own path), `plugins.py:431-456`
(`plugin_of_source` realpaths the file; outside `plugins_dir` → "core / user / include — trusted as the user"),
`routes.py:340-348` (`_facet_ok`, whose comment says an include "carries its includer's trust" — it doesn't).

Trust for command-carrying data is decided by the realpath of the *defining file*. An untrusted plugin can make
a file outside its tree define things — by `include:` (absolute, `~/…`, or `../..`), or by shipping a data file
that is a symlink out — and that file's `facets: detect:` probe (runs at every startup) and `via: script`
bindings are then judged trusted. The attacker needs attacker-controlled `.hu` text at a known path outside
`plugins_dir`; the plugin's own tarball/font component (ungated download+extract) can put it there once you
install that one component, and a second data file of the plugin includes it on the next run. Baseline: a
plugin whose download you install already runs its binary when you launch it; this adds configsys-run shell at
every startup and `sudo bash -c` script bindings without the trust prompt.

**(reproduced)** `p4_trust.py` (`$S/home6`, plugin `plug` untrusted, `plug.hu` = `{ include: [ $S/outside/payload.hu ] }`):
`pwn facet merged from an UNTRUSTED plugin include: True`, `evil binding source: …/outside/payload.hu`,
`command_source_trusted -> True`, `plugin trusted? False`. Symlink variant (`plug2/link.hu -> outside/payload.hu`):
`command_source_trusted -> True`.

**Fix:** give `Layer` an `owner` (the root path + role it hangs under) set by `_visit`, and decide command trust
from the owner, not the file (`command_source_trusted(paths, layer.owner)`); with -03's include confinement the
include route closes; for the symlink route resolve data files and refuse ones outside the tree (plugins-05).
**Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). MED kept.
- **The probe really runs.** Each `$V/outside/payload-*.hu` carries `facets: { pwn: { detect: "touch
  $V/outside/PROBE-RAN-…; echo x" … } }` and a `via: script` component. Plugin `plug` is declared and never
  trusted. Three cases:
  - `h04a`: `plug.hu` = `{ include: [ $V/outside/payload-inc.hu ] }`.
  - `h04c`: the plugin ships `link.hu -> $V/outside/payload-sym.hu`.
  - `h04b` (control): the same text sits in `plug.hu` itself.

  `configsys --home … --os ubuntu:24.04 --pretend where …` on each creates `PROBE-RAN-inc` and `PROBE-RAN-sym`, and
  no `PROBE-RAN-ctl`. It runs even under `--pretend`, because `detect_facets` calls `subprocess.run(shell=True)`
  directly (`routes.py:514`), not through the runner.
- **Trust, per route.** `v04_trust.py` (a real Context):
  - include: the binding's source is `$V/outside/payload-inc.hu`, `command_source_trusted -> True` while
    `plugin plug trusted? -> False`, and facet `pwninc` is merged with no warning.
  - symlink: the source shows as the in-tree `…/plugins/plug/link.hu`, yet `command_source_trusted -> True`,
    because `plugin_of_source` follows the link out. The facet is merged.
  - control: `False`, nothing merged, and the warning `facets: from an untrusted plugin is ignored`.
- **Doc vs code.** `docs/facets.md` and the `_facet_ok` comment both say an include carries its includer's trust.
  The code judges the file's location instead.
- **Why MED is right.** The attacker needs its own `.hu` text at a known path outside `plugins/`. In practice, one of
  its own tarball or font components that you installed drops it there. And an untrusted data plugin can already
  reach root through a `native-pkg-file` binding you install, since download drivers aren't trust-gated. What this
  adds: a component that never executes (a font) becomes shell at every startup, with no trust prompt.

### config-layers-05 [MED] correctness — any config file under 10 bytes fails to load (`{}` bricks configsys; an emptied primary shows a red error every run)
`configsys/layers.py:119` (`read_setting`) and `:175` (`_visit`) call `humon.from_file`, which sniffs the byte
encoding and rejects short inputs with `BADENCODING`; `troveio.load` (`troveio.py:22-39`) exists precisely to
avoid this (reads UTF-8-sig text, `from_string`). configsys itself writes such files: `config move <key>` of a
primary's last setting leaves `{\n}\n`, and `_writable_primary_file` creates `{\n}\n` (`actions.py:1117`).
Carried from 2026-09.

**(reproduced)** threshold: `{ a: b }\n` (9 bytes) ERR, 10+ bytes ok; `{}` ERR.
`printf '{}\n' > …/home7/…/configsys.hu; configsys config get scope` → `could not read (Unable to make trove: BADENCODING)`, rc=1.
`$S/home8` primary `mine.hu` = `{ splash: maze }` → `config move splash` → `od` shows `{ \n } \n` (4 bytes) →
`p7_warn.py`: `config load_warnings: ['…/mine.hu: could not read (Unable to make trove: BADENCODING)']` and the same
in `routes load_warnings` — two `error skipped` rows on the `!` page for an empty, valid file.

**Fix:** `_visit` and `read_setting` parse via `troveio.load` (one parse chokepoint, BOM-tolerant, one error
wording); treat a whitespace-only file as `{}` there. Test: `{}`, `{ }`, `{\n}\n` as user / primary / include.
**Effort:** S. **Tier:** B.

### config-layers-06 [MED] correctness — setting values are parsed three ways and mostly unvalidated: a typo silences reboot advice, and `config set adopt-installed ture` writes `false`
`configsys/config.py:250-318` (bool getters), `actions.py:881-882` (`_to_bool`), `:913-921` (bool/scalar branches
of `set_config_setting`), `layers.py:46-51` (`SETTING_CHOICES`), `:59-74` (`setting_value_warnings`).

- Three bool dialects: `auto_tighten`/`reboot_advice` are true only for `true/yes/on/1`; `adopt_installed`,
  `detect_coexisting`, `install_overlay_default` are true unless `false/no/off/0`;
  `block_installer_shell_writes` unless `allow/false/no/off/0`. So `reboot-advice: ture` turns a default-ON
  safety advisory **off** while `adopt-installed: ture` stays on.
- `config set <bool> <token>` maps any non-truthy token to `false` and echoes the token: a typo flips a
  default-ON setting off while saying the opposite.
- `scope` (documented "`user` or `system`", config-format.md:115) and `installer-shell-writes` ("`block` or
  `allow`", :175) are not in `SETTING_CHOICES`, so `config set` accepts anything and `check` is silent;
  `scope: sytem` installs at user scope (`driver.py:139-143`).
- Bools have no `check` warning at all.

**(reproduced)** `config set adopt-installed ture` → `configsys: set adopt-installed = ture  (in top config)`;
file `adopt-installed: false`; `config get adopt-installed` → `false`. `config set installer-shell-writes alow`
→ accepted, `get` → `block`. `config set scope sytem` → accepted, `get` → `sytem`. Getter table:
`ture reboot_advice False adopt True detect True tighten False`; `enabled reboot_advice False adopt True …`.
`check | grep -i 'scope\|shell-writes\|adopt'` → nothing.

**Fix:** one `_bool(v, default)` (unknown token → default + a `check`/`!` warning) used by every bool getter;
`config set` refuses a non-bool token for a bool and a non-choice for `scope`/`installer-shell-writes` (add them
to `SETTING_CHOICES`); the structural home for all of it is config-layers-20. **Effort:** S. **Tier:** B.

### config-layers-07 [MED] safety — `locations:` paths are never validated: a relative path is CWD-relative and `~` is the REAL home even under `--home`
`configsys/config.py:182-188` (`locations()` returns raw strings), `actions.py:767-775` (`_parse_map_tokens`
accepts any `k=v`), `driver.py:311` (`Path(str(loc)).expanduser()`).

config-format.md:183 promises "An absolute path, regardless of scope", and its own example is
`blender: ~/dev/blender-git`. Nothing enforces "absolute": `ripgrep=relative/rg` becomes a CWD-relative target,
and `expanduser()` expands `~` against the process `$HOME`, not `Paths.home` — so in a `--home`/`CONFIGSYS_HOME`
sandbox a location points into the real home (docs/principles.md: never act on `$HOME` from a sandbox), and
tarball `install` `rm -rf`s that dir.

**(reproduced)** `$S/home3`: `config set locations 'ripgrep=~/apps/ripgrep-REVIEW-PROBE'` → `p3_guard.py` →
`_safe_install_dir: (PosixPath('$REAL_HOME/apps/ripgrep-REVIEW-PROBE'), None)`; `config set locations
'ripgrep=relative/rg'` → `_safe_install_dir: (PosixPath('relative/rg'), None)`.

**Fix:** validate in `_parse_map_tokens` (and warn in `check` for file values): absolute or `~`-prefixed,
`os.path.normpath`'d (which also removes the `//` of -02); expand `~` against `paths.home` when stamping
`location-override` (`Context.apply_locations`), not in the driver. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). MED kept.
- **Where `~` goes.** `Context.__init__` sets `CONFIGSYS_HOME` only in a copy of the environment (`app.py:110-112`).
  So `location_override`'s `Path(loc).expanduser()` (`driver.py:311`) expands `~` against the process `$HOME`, while
  `dirs:` paths go through `Paths.expand` and land under `--home`.
- **Reproduction.** Process `HOME=$V/fakehome` stood in for the real home.
  - `--home $V/home/h07a config set locations 'ripgrep=~/apps/ripgrep-PROBE'`, then `v02_tarball.py`:
    `_safe_install_dir: ($V/fakehome/apps/ripgrep-PROBE, None)` and `WOULD RUN: rm -rf $V/fakehome/apps/ripgrep-PROBE
    && mv …`. That is outside the `--home` sandbox.
  - `config set locations 'ripgrep=relative/rg'` is accepted. It gives `_safe_install_dir: (relative/rg, None)` and
    `rm -rf relative/rg && mv relative/rg.configsys-stage relative/rg`, relative to wherever configsys runs.
- **The doc.** config-format.md:182-187 promises "An absolute path", which nothing enforces, and its own example
  (`:90`) is `blender: ~/dev/blender-git`.
- **Why MED.** The `~` half bites only `--home` / `CONFIGSYS_HOME` runs, because otherwise `~` is the configsys home.
  The relative half bites normal use, but needs a mistyped path.

### config-layers-08 [MED] correctness — `configsys check` reports "0 error(s)" while your primary's data file is unreadable and skipped
`configsys/app.py:2434-2440` (`cmd_check`: `routes.load(...)` without `warnings_out`, and
`layer_list, _w = layers.expand_tolerant(...)` — `_w` is discarded). `expand_tolerant`'s contract
(`layers.py:198-202`) is "returns (layers, warnings)"; the TUI's `Context.diagnostics` (`app.py:223-226`)
reports the same warnings as `error skipped`, so the two surfaces disagree.

**(reproduced)** `$S/home8` primary `mine.hu` = `{\n    picks: { this-machine: [ btop ripgrep ] \n}\n`
(unterminated) → `configsys check` → rc=0, `grep -ci "mine.hu\|skipped\|could not read"` → `0`, last line
`configsys: 0 error(s), 1 warning(s) across 832 components` — every portable pick is gone and the linter is clean.

**Fix:** `cmd_check` counts `_w` and the routes `warnings_out` as errors (same `unskip` wording as
diagnostics). Better: one `layers.load_stack(paths, plugin_files)` that both Config/routes/check use, so the
root list (written three times: `config.py:72-75`, `routes.py:325-328`, `app.py:2437-2439`) and its warnings
can't diverge. **Effort:** S. **Tier:** B.

### config-layers-09 [MED] performance — Config re-merges its machine-setting views on every call; `is_new` over the catalog costs 77 ms instead of 0.9 ms
`configsys/config.py:145-156,175-180,368-391,472-478`. A `Config` is immutable (rebuilt by `ctx.invalidate`),
yet `dispositions()`, `uninstall_queue()`, `picks()`, `pins()`, `included()` re-walk every layer per call, and
`is_new(c)` calls two of them per component. The TUI computes NEW/interesting counts per profile
(`menu.py:3224,3264`, `screens/profiles.py:391,632`) and `app.py:1880` over the whole universe.

**(reproduced)** real catalog (832 components, 94 profiles), 300 dispositions: `is_new over 832 comps: 77.1 ms`;
with `dispositions`/`uninstall_queue` memoized: `0.93 ms` (83×); cold all-profile NEW/interesting counts
(1143 member visits): `216.1 ms`; `included() x100: 4.4 ms`.

**Fix:** compute the merged maps once per Config (`functools.cached_property`, or eagerly in `__init__`):
`dispositions`, `uninstall_queue`, `picks`, `pins`, `locations`, `install_dirs`; `included()` reads the cached
picks. **Effort:** S. **Tier:** C.

### config-layers-10 [LOW] correctness — a "skipped" plugin still contributes the includes it reached before failing
`configsys/layers.py:203-217` (`expand_tolerant`): on a tolerant failure it clears `stack` but not the layers
the failed root already appended to `order` (nor their `done` entries). A plugin whose second include is
missing is reported "skipped" yet its first include's definitions are live — and at the plugin's precedence.

**(reproduced)** `p5_partial.py`: `p.hu` = `{ include: [ ./a.hu ./missing.hu ] … }` (plugin), `q.hu` includes
`./a.hu` → `layers: [('a.hu', 'include'), ('q.hu', 'plugin')]` with a warning that `p.hu` was skipped.

**Fix:** snapshot `len(order)` and the `done` set per root; on a tolerant failure truncate `order` and restore
`done`. Test in `test_includes.py`. **Effort:** S. **Tier:** B.

### config-layers-11 [LOW] correctness — `plugins:` written anywhere but the top config is ignored without a word
`configsys/layers.py:377-383` (`plugins` is a KNOWN key, not in any forbidden set), `plugins.py:87-92`
(`declared` reads only the top config). config-format.md:343 says an include may not set "machine settings or
`plugins:`", and :32 promises `check` warns about an ignored machine setting — but `plugins:` in an include, in
a plugin's data file, or in your primary's `<name>.hu` (a natural place to try — the primary's transitive
plugins go in its `plugin.hu` manifest) produces no warning anywhere.

**(reproduced)** `ignored_section_warnings` / `unknown_section_warnings` / `setting_value_warnings` on
include / primary / plugin layers that each set `plugins:` → `[]`, `[]`, `[]`.

**Fix:** a top-config-only warning for `plugins:` in `ignored_section_warnings` ("read only from your top config
and plugin manifests — for your primary, put it in plugin.hu"). **Effort:** S. **Tier:** B.

### config-layers-12 [LOW] correctness — an ordinary plugin's os-block `driver-preference:` overrides your `driver-preference:` setting
`layers.merge_dict_section(…, ALL_ROLES)` (called from routes for `os:`) + `resolve._effective_preference` (OS-block
lists rank ahead of the machine setting). The uniform layer rule keeps `driver-preference:` (a machine setting)
out of plugins, but a plugin can ship `os: { <your-os>: { driver-preference: [...] } }` and it outranks yours;
`drivers: { x: { when: … } }` / `standing:` from a plugin likewise act like `disabled-drivers`.

**(reproduced)** `$S/p10`: user `driver-preference: [ native flatpak ]`, component with native + flatpak bindings →
`no plugin -> ['apt\\t']`; add plugin `{ os: { debian: { driver-preference: [ flatpak ] } } }` →
`plugin layer -> ['flatpak\\t']`.

**Fix:** honor os-block `driver-preference:` only from repo/primary/user layers (or rank your setting ahead of a
plugin's os-block list) and say so in config-format.md; see Questions. **Effort:** S. **Tier:** B.

### config-layers-13 [LOW] correctness — the key scanner misses keys after `,` / `]` / `}` and quoted keys, and edits the shadowed copy of a duplicated key
`configsys/hutext.py:119-121` (left boundary is only whitespace or `{`; a `"key":` is skipped as a string),
`:96-128` returns the FIRST match, while humon's lookup and `layers.materialize` (`layers.py:90-104`) keep the
LAST; `materialize` also drops an empty key silently.

**(reproduced)** `p2_variants.py`: `{ machine: m,scope: user }` → set scope → `'{ machine: m,scope: user     scope:
system\n}\n'` (a second `scope:` appended); `"scope": user` → duplicate appended likewise. `dup.hu` =
`{ scope: user / scope: system }` → `set_scalar_section(…, 'scope', 'user')` → reads back `system` (the edit hit
the dead copy); `unknown_section_warnings` on it → `[]`.

**Fix:** boundary set `' \t\r\n{,]}'`; match a quoted key spelling; locate the last occurrence (or refuse when a
key is duplicated); `check` warns on a duplicated top-level key. **Effort:** S. **Tier:** B.

### config-layers-14 [LOW] correctness — the profile helpers that walk the chain ignore a wholesale redefinition (and `profile_includes` iterates raw values)
`configsys/config.py:512-555` (`profile_removed`, `profile_excludes`, `profile_removal_terms`), `:729-737`
(`profile_includes`). They scan every layer's definition, but a redefinition without `+self` replaces the lower
ones (`profile_components`/`_layout` honor that). `profile_includes` also loops `for t in terms` on the raw value:
a nested map yields its keys and a scalar its characters, so a nested profile's `+base` is missed
(`reachable_subprofiles` → check's orphan-`~` warning; the editor's `~` / exclude markers).

**(reproduced)** repo `p: [ a b ~b +base ]`, user `p: [ c ]` → `components ['c'] | removed {'b'} | includes {'base'}
| reachable {'base'} | layout [('component', 'c')]`. `dev: { g: [ +base b ] }` → `profile_includes` → `set()`
while `profile_components('dev')` → `['a', 'b']`.

**Fix:** one `_effective_chain(profile, ceiling)` (the top def, then lower defs only while each carries `+self`)
used by all four, iterating `_leaves(val)`. **Effort:** S. **Tier:** B.

### config-layers-15 [LOW] correctness — a machine whose picks value is a single name vanishes
`configsys/config.py:378-381` (`picks()` keeps only list values), `plugins.read_picks`. Every list setting accepts
a scalar through `_leaves` (`disabled-drivers: snap` works), but `picks: { laptop: btop }` drops the machine
entirely — no column, nothing installed, no warning.

**(reproduced)** `picks: { laptop: btop }`, `machine: laptop` → `picks {} included set() machines []`, while
`disabled-drivers: snap` → `['snap']`.

**Fix:** treat a scalar as a one-item list (or warn in `check`). **Effort:** S. **Tier:** B.

### config-layers-16 [LOW] correctness — `requested()` says "Ordered" but its order changes from run to run
`configsys/config.py:389-391,739-748`: `included()` returns a `set`, so `requested()`'s dict order follows string
hashing (randomized per process). The resolved set is the same; unit/plan/display order isn't.

**(reproduced)** `PYTHONHASHSEED=1/2/3` on `picks: [ zsh btop ripgrep fd neovim ]` →
`['btop', 'zsh', 'fd', 'ripgrep', 'neovim']`, `['ripgrep', 'fd', 'btop', 'neovim', 'zsh']`, `['fd', 'btop', …]`;
`p8_order.py` over 10 picks: unit-set hash `df8a503b6e` all four seeds, unit-order hash differs every time.

**Fix:** build `requested()` from the picks list (file order); keep `included()` a set for membership.
**Effort:** S. **Tier:** B.

### config-layers-17 [LOW] correctness — `config show` says a top-config-only setting lives in your primary while ignoring it there
`configsys/config.py:97-106` (`machine_setting_source`) and `actions._setting_home` (`:827-837`) don't consult
`layers.TOP_CONFIG_ONLY`.

**(reproduced)** `$S/home8` primary with `primary-verify: signed` → `config show` →
`primary-verify               off  (primary: mine)`.

**Fix:** for a `TOP_CONFIG_ONLY` key, only the `user` role counts as its home/source; show "(ignored in mine —
top config only)". **Effort:** S. **Tier:** B.

### config-layers-18 [LOW] parity — the TUI `!` page never shows bad setting values
`app.py:223-230` (`Context.diagnostics` adds `ignored_section_warnings` and `unknown_section_warnings` but not
`layers.setting_value_warnings`), vs `cmd_check` (`app.py:2447-2449`). `primary-push: sometimes` or a
`primary-verify:` in the primary is visible to `check` only.

**Fix:** add `setting_value_warnings` (as `warn`, kind `setting`) to diagnostics. **Effort:** S. **Tier:** G.

### config-layers-19 [LOW] performance — the repo layers are re-parsed on every Resolver rebuild, twice by `check`
`configsys/layers.py:175-176` parses and materializes each file on every expansion. routes.hu costs
`humon parse routes.hu: 35.2 ms; materialize: 36.8 ms` (of a `Resolver(): 440.9 ms`); `ctx.invalidate` drops the
Resolver after every TUI edit, and `cmd_check` expands routes.hu twice (`routes.load` + its own
`expand_tolerant`).

**Fix:** cache materialized layer data per `(realpath, st_mtime_ns, st_size)` in `_visit` (treat it as read-only
— every consumer already copies before merging), invalidated naturally by a write. **Effort:** S. **Tier:** C.

### config-layers-20 [MED] refactor — one settings registry instead of nine tables and twenty getters
Carried from 2026-09 D5. Setting knowledge today: `layers.MACHINE_SETTING_SECTIONS`, `SETTING_CHOICES`,
`TOP_CONFIG_ONLY`, `_KNOWN_TOP_KEYS`, `_RETIRED_TOP_KEYS`; `actions.CONFIG_SETTINGS`, `SETTING_NATURE`,
`_SETTING_GETTERS`; ~20 hand-written `Config` getters each re-implementing token parsing; and `layers` imports
`actions` lazily (`layers.py:77-87`) to complete its own list — a low-level module reaching up into the action
layer. **Proposal:** `configsys/settings.py` with `Setting(key, kind, nature, default, choices, roles|top_only,
parse, desc)`; `Config.setting(key)` + thin typed wrappers; `MACHINE_SETTING_SECTIONS`/`SETTING_CHOICES`/
`TOP_CONFIG_ONLY`/`CONFIG_SETTINGS`/`SETTING_NATURE`/`_SETTING_GETTERS`/docaudit's extraction all derived.
Collapses -06, -07 (a `path` kind), -11, -17, and the inverted import; a new setting becomes one table row.
**Effort:** M. **Tier:** D.

### config-layers-21 [LOW] reuse — duplicate emitters, flatteners and overlays
- `troveio._emit` (`troveio.py:51-77`) duplicates `hutext.emit` (`hutext.py:160-174`) with a different list
  layout and its own key quoting that misses the empty-key case (`'': v` emits `: v`, unparseable); the
  `_scalar`/`_UNSAFE` aliases (`troveio.py:17`) survive for one caller (`actions.py:792`).
- `config._leaves` (`config.py:23-29`) ≈ `plugins._flat`; `_as_list` is copied in layers, routes, resolve,
  routecheck, apt, dnf, docaudit and reviewaudit.
- `merge_name_overrides` / `merge_version_floors` (`layers.py:252-287`) are one two-level overlay with a
  different section name.
- `scalar(None)` → `""` is indistinguishable from `''` on reload.
**Fix:** `emit_hu = hutext.emit(obj, 0) + '\n'` (pick one list layout), a `hutext.quote`, one `_leaves`, and
`merge_two_level(layers, section)`. **Effort:** S. **Tier:** D.

### config-layers-22 [LOW] comment-drift — docstrings still describe retired models
- `config.py:1-8`: "`configs` (which profiles apply) and `scope` are machine SETTINGS — from the repo/user files";
  `pins` "(repo/user)" — `configs` is retired; machine settings come from repo/primary/user.
- `config.py:82-90`: `ignored_section_warnings` cites "`configs:` from a non-primary plugin" (configs is
  deliberately excluded there); `unknown_section_warnings` cites "a user-level `profiles:`" as retired
  (un-retired 2026-10-10).
- `config.py:145-150`: `dispositions()` "repo < primary < machine < user"; "include/exclude live in the profiles
  themselves" (the matrix model's picks). `:158-161`: "user/primary/machine layer".
- `config.py:472-478`: `uninstall_queue` "needs no `!` reservation" — `UNINSTALL_PROFILE = '!uninstall'` is one.
- `config.py:740`: `requested` "Ordered" (see -16). `layers.py:114-115`: `read_setting` "(e.g. `discover:`)" —
  discovery was removed (ded2826); its callers read `plugins:` and `facets:`.
- `hutext.py:97-100`: `section_span` "matches `section` only as a real key" — not a quoted key or one after `,`
  (-13). `routes.py:342-345`: includes "carry their includer's trust" (they don't, -04).
**Effort:** S. **Tier:** E.

### config-layers-23 [LOW] dead-code — leftovers in config/layers
`Config._profiles` (`config.py:53`, assigned, never read — and the only user of `layers.merge_named`,
`layers.py:221-233`); `Config.PICKS_PROFILE` (`:366`, no reader); `layers._DEFINITION_SECTIONS` /
`_REPO_SECTIONS` (`layers.py:24-25`, no reader); the phantom `'machine'` role in `user_layer_components`
(`:163`) and `role_ceilings` (`:420`); `splash()`'s `if v is False / if v is True` (`:343-346` — humon yields
strings); the `troveio._UNSAFE` alias. See "Dead code" for the greps. **Effort:** S. **Tier:** D.

### config-layers-24 [NIT] abi — callers reach into `Config._layers` and the private `_selected_machine`
`app.py:1028-1030` and `primarygit.py:384-385` import `config._selected_machine` and pass `cfg._layers` to get
"this box's configured machine, ignoring `--machine`"; `tui/keyspec.py:138` reads `config._layers`. `Config.load`
also accepts bare paths or `(path, role)` tuples (`config.py:73-74`) where `routes._pf` does the same normalizing.
**Fix:** public `Config.configured_machine()` and a read-only `Config.layers`; one root shape. **Effort:** S.
**Tier:** F.

### config-layers-25 [NIT] correctness — the removed `discover:` / `ignore-profiles:` settings read as typos
`layers.py:385-389` (`_RETIRED_TOP_KEYS`): ded2826 removed both machine settings, but a config still carrying one
gets "unrecognized top-level key … (typo, or retired?)" rather than the retired explanation the other three get.
**Fix:** add both with "retired — project discovery was replaced by `plugin add --local`". **Effort:** S. **Tier:** B.

### config-layers-26 [NIT] refactor — the include home is process-global state set by a constructor
`layers.py:141-154`: `Paths.__init__` calls `set_include_home`, and the global then beats `$CONFIGSYS_HOME`. Every
test that builds a `Paths(env=…)` leaves it pointing at its tmp dir for later tests (only
`test_tilde_include_expands_against_the_configsys_home` resets it). **Fix:** pass `home=` into
`expand`/`expand_tolerant` from `Config.load` / `routes.load` (both already know the paths). **Effort:** S.
**Tier:** D.

## Test gaps

- **Replacing an existing scalar** with siblings after it (quoted value; bare value mid-line; value on the
  closing-brace line) — `test_config_edit.py::test_scalar_section_roundtrip_and_clear` only inserts then clears;
  `test_hutext.py:18` asserts `startswith`, hiding the overrun (-01).
- A hostile-value round-trip table through every writer (`x//y`, `a/*b`, spaces, `:`, brackets, each quote) and
  a machine name with a space (-02).
- Includes: of the top config / the primary from a plugin; out-of-tree include + symlinked data file vs
  `command_source_trusted`; a tolerant root failing after a successful include (-03, -04, -10).
- `{}`, `{ }`, `{\n}\n` as user / primary / include layers (-05).
- Invalid tokens for each bool setting and for `scope` / `installer-shell-writes`, through both the getters and
  `config set` (-06). No direct test of `reboot_advice`, `adopt_installed`, `install_overlay_default`,
  `block_installer_shell_writes`, `effects()`.
- `locations` values: relative, `~` under `--home`, `//` (-07); `check` exit status with a malformed primary (-08).
- `expand_tolerant`, `machine_setting_source`, `dict_section_sources`, `merge_scalar_map`, `hutext.key`,
  `scalar_end`, `skip_blank` have no direct tests.
- Profile helpers after a wholesale redefinition and on nested profiles (-14); `picks:` scalar value (-15);
  duplicate top-level keys (-13).
- Many `test_config_overlay.py` fixtures still carry the retired `configs:` key — harmless, but they now test
  nothing about it; prune when touching them.

## Dead code   (each entry: what you grepped to be sure)

- `Config._profiles` / `layers.merge_named`: `grep -rn "\._profiles\b\|merge_named" --include=*.py configsys/ tools/
  test/ ~/src/configsys-*/ examples/` → only `config.py:53` (the assignment), its own def, and docstring mentions.
- `Config.PICKS_PROFILE`: same tree grep → only the definition.
- `layers._DEFINITION_SECTIONS`, `layers._REPO_SECTIONS`: same tree grep → only `layers.py:24-25`.
- `'machine'` role in `user_layer_components` / `role_ceilings`: no code assigns `role='machine'` (`Config.load`,
  `routes.load`, `cmd_check`, `layer_files` produce repo/plugin/primary/include/user only;
  `test_machine_roles_has_no_phantom_role`).
- `splash()` `is False` / `is True`: `layers.materialize` returns `node.value` (strings) — `'{ a: false }'` →
  `'false'`; no caller builds a `Layer` with a Python bool outside tests (`grep -rn "Layer(" configsys/`).
- `troveio._UNSAFE` / `troveio._scalar` aliases: only `actions.py:792` (`_scalar`); `_UNSAFE` only in troveio itself.
- Not in the frozen ABI list (`driver.py` docstring) and not used by any `~/src/configsys-*` plugin or `examples/`.

## ABI / interface candidates

- `Layer` gains an `owner` (root path + role) — the identity the uniform layer rule, dedup and command trust should
  key on (-03, -04). Internal, but `layers_out` exposes `Layer` to `-v` reporting.
- `Config.configured_machine()` and a read-only `Config.layers` replace three `_layers` reach-throughs (-24).
- Move `set_section` (+ verify-before-write) into `hutext` so no writer can splice humon text without the shared
  scanner and the re-parse check (-01, -02); the plugins.py emitters become callers.
- `configsys/settings.py` (-20): the registry plugins would see if they ever register a setting.

## Questions for the user

1. Should `machine:` (and the `uninstall:` queue) be top-config-only, like `primary-verify`? Today
   `config move machine` puts `machine: laptop` into the primary (reproduced: `configsys: machine → mine`), so
   every box syncing it without its own `machine:` becomes the laptop column and `install --picks` installs the
   laptop's picks; an `uninstall:` that reached the primary (hand edit / merge) would stage removals on every box.
2. Should an ordinary plugin's os-block `driver-preference:` (and `drivers:` `when:`/`standing:`) be able to
   outrank your machine-level choices (-12), or should those per-OS preference knobs be honored only from
   repo / primary / top config?
3. OK to confine a plugin's (and the primary's) `include:` to its own tree (-03/-04)? No plugin in
   `~/src/configsys-*` uses `include:`, so nothing known breaks.
