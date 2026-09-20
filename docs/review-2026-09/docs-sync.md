# configsys — documentation sync audit (read-only)

Ground truth used: CLAUDE.md + the live code/CLI (`configsys/app.py` argparse, `configsys/layers.py`
`_KNOWN_TOP_KEYS`/`_RETIRED_TOP_KEYS`, `configsys/actions.py` `CONFIG_SETTINGS`, `configsys/tui/menu.py`
`SCREENS`/`COMPONENT_MODES`, `config.hu` `keys:`, `configsys/drivers/*`, `configsys/paths.py`). Every
claim below was checked against the code or a live `configsys ... --help` / `check` run, not assumed.
`tools/gen_manpages.py --check` passes (exit 0), so both man pages are byte-current with their sources —
which means they faithfully inherit every drift listed below.

## Themes

1. **The profiles→picks retirement never reached the public docs.** README, docs/config-format.md (and
   thus `configsys.hu(5)`), docs/plugins.md and several argparse help strings (and thus `configsys(1)`)
   still teach `configs: [ dev ]` and a user-authored `profiles:` block as THE way to say what a machine
   installs. Both keys now produce `check` warnings ("`configs:` retired…", "`profiles:` is retired in a
   user config…" — verified live). `picks:` / `machine:` / `configsys picks|machine` — the actual install
   set — appear in NO public doc.
2. **README's command/flag inventory is ~40% short of the real CLI.** Missing subcommands: `machine`,
   `picks`, `versions`, `profile`, `config`, `theme`, `orphans`, `keys`, `tui`, `disp`; missing `dotfiles
   staged|activate|discard`; wrong `manpages check` (real: `status`); missing global flags `--machine`,
   `--color/--nocolor`, `--effects`, `--probe`, `--splash-linger`; env list omits ~15 real vars.
3. **Glue is invisible.** The glue/dotfiles split (own `via: glue` driver, own `glue/` roots, a TUI Glue
   screen at key `4`, `dotfiles staged/activate/discard`, `CONFIGSYS_GLUE_SHELLS`) is shipped but not in
   README, config-format.md, or the driver lists; theming.md omits the `glue` page; the `.cfs` config
   marker/manifest model is undocumented.
4. **Stale preference vocabulary.** `prefer:` (config-format.md §Choosing among methods — and the man
   page), `opt-in:` (routing-model.md §3/§4 schema + examples) are gone; the ONE knob is `standing:`.
   config-format.md also has the precedence ORDER wrong (driver-preference before prefer; real order is
   specificity → `standing` → `driver-preference`).
5. **Retired constructs still cited as live in code-facing text**: "discovered" layer role (theming.md,
   routing-model.md §10a), `machines:` (argparse help for `machine`, contradicting layers.py where
   `machines` is a RETIRED key), "v2 triage state / include-exclude live in your profiles" (`disp` help),
   "active profiles" (inspect/orphans/dotfiles-status help, README).
6. **Plan-doc sprawl**: 31 files in docs/, of which only 6 are current reference; ~20 are dated
   implementation plans (many with stale "NOT built" status lines that memory/commits show are built),
   and 3 profile-model docs describe two SUPERSEDED models (^derive, dispositions) with no top-of-file
   supersession banner on one of them.

Bonus: two **code** bugs surfaced by the docs (the docs are right, the checker is wrong): `locations:`
and `reboot-advice:` are real settings (config.py:188, actions.py CONFIG_SETTINGS) but are missing from
`layers._KNOWN_TOP_KEYS`, so `configsys check` warns "unrecognized top-level key" for both (verified live).

---

## (a) docs/*.md classification

| doc | class | notes |
| --- | --- | --- |
| config-format.md | CURRENT reference (**drifted**, HIGH) | source of `configsys.hu(5)`; see edits below |
| routing-model.md | CURRENT reference (drifted, MED) | §1/§12/§14 explicitly history; §3/§4 still show `opt-in:`; §10a "discovered" |
| plugins.md | CURRENT reference (drifted, MED) | `configs:` refs, `[@ref]` syntax, "prune" claim |
| theming.md | CURRENT reference (drifted, MED) | key 6→7, missing `glue` page, "discovered" |
| name-sweep-test.md | CURRENT reference | accurate; roadmap item 4 (CI) still open |
| component-attrs.md | CURRENT reference (spec) | fine; "Profiles-view behaviour (built)" |
| facets.md | CURRENT reference, **unlabeled** | facets ARE live (predicate.py, `facets:` known key, `CONFIGSYS_FACET_*`) but doc has no Status line and no other public doc mentions facets |
| versioned-requires.md | HISTORICAL plan (SHIPPED) | header says "design / exploration"; memory says fully shipped → mark SHIPPED |
| routing-overhaul-plan.md | HISTORICAL plan | header "Planning only — no code yet"; most of it (standing, version-scoped providers, detection tier) is built → status line stale |
| startup-perf-plan.md | HISTORICAL plan | header "fixes NOT built"; ALL phases built (memory) → stale status |
| dotfiles-redesign.md | HISTORICAL plan | header "DESIGN AGREED, not built" but body lists phases 1a/1b/2/3 DONE → stale header |
| dotfiles-glue-split-plan.md | HISTORICAL plan (Phases 1–2 DONE, 3 pending) | most recent; the only doc describing glue at all |
| dotfiles-capture-plan.md | HISTORICAL plan (SHIPPED) | correctly labeled |
| shell-writes-switch.md | HISTORICAL plan (BUILT) | correctly labeled |
| plugin-init-plan.md | HISTORICAL plan (SHIPPED) | correctly labeled |
| install-methods-plan.md | HISTORICAL plan (SHIPPED) | status para still says "`driver-preference` + per-binding `prefer:`" — retired term |
| many-installs-including-src.md | HISTORICAL (SUPERSEDED) | correctly labeled |
| method-broadening-plan.md | HISTORICAL plan (Phase 1 done) | fine |
| source-plugin-plan.md | HISTORICAL plan | "in progress (pilot batch)"; pilot DONE, batches remain — acceptable |
| driver-resilience-plan.md | HISTORICAL plan (BUILT) | correctly labeled |
| expansion-plan.md | HISTORICAL plan (SHIPPED) | says "`script` driver generalizes sdkman" but a dedicated `sdkman` driver exists (drivers/sdkman.py) |
| immutable-distros.md | HISTORICAL design (SHIPPED) | correctly labeled |
| python-versions-plan.md | HISTORICAL plan (BUILT) | correctly labeled |
| keybindings-plan.md | HISTORICAL plan (FEATURE COMPLETE) | fine; only doc describing `keys:` — content should migrate to config-format.md |
| managed-orphans-plan.md | HISTORICAL plan (complete) | uses "active profiles" framing; theming.md links to it for orphan kinds |
| tui-screens-plan.md | HISTORICAL plan | "Decisions locked 2026-08-03", pre-dates Glue/Theme screens; largely built |
| theme-redesign.md | HISTORICAL plan | superseded by theming.md; says "nav key 6" (now 7) |
| profiles-plan.md | HISTORICAL (APPLIED) | v1 profile pass; fine as history |
| profiles-derive-plan.md | HISTORICAL — **SUPERSEDED** | header still "DESIGN, not built" though it was built then ripped out; needs a SUPERSEDED-by-matrix banner |
| profiles-disposition-plan.md | HISTORICAL — **SUPERSEDED** (v2) | NO status banner at all; reads as current ("system profiles… user profiles are your own curated sets") |
| profiles-matrix-plan.md | CURRENT plan (v3, ACTIVE) | the only doc describing picks/matrix; Phase C (TUI) marked next but is built |

Also: `docs/history/` (IMPLEMENTATION.md, PLAN.md, README.md, wire-in.md) already exists as an archive
location — the HISTORICAL rows above are candidates to move there or to get a uniform
`Status: HISTORICAL — superseded by X` first line.

---

## Findings

### [HIGH] doc-vs-code — README/config-format teach the retired `configs:` + user `profiles:` model
- README.md:33-34 ("Edit that file to pick your **profiles**"), :45-46 (Profile = "flat list… Your
  machine's config picks which profiles apply here"), :129 (`configs: [ dev ]`), :139 (`profiles: {…}`
  "define or shadow a profile"), :147 (include "pull profiles"), :173/:182 (plugin init copies "your
  `profiles:`"), :233-235 (`profile:<name>` — still valid, fine).
- docs/config-format.md:22 (`configs:` as a machine setting), :33, :45, :59 ("`configs:` is the set of
  profiles active on this machine"), :120-144 (whole Profiles section as user-authored term algebra; :142
  "add it to `configs:`"). → inherited verbatim by man/configsys.hu.5.
- docs/plugins.md:93-95 ("`plugins:` is a machine SETTING (like `configs:`/`pins:`)… primary may set
  `configs:`").
- Code: layers.py:276-278 `_RETIRED_TOP_KEYS['configs']`; layers.py:295-297 warns on `profiles:` in a
  user/primary layer; config.py:726 "configs:/active profiles are retired". Verified: `check` on a
  sandbox config emits both warnings.
- Fix: replace with the picks model — `picks: { <machine>: [ … ] }` + `machine: <name>` in the top
  config; `configsys picks add|rm|list|to-primary`, `configsys machine list|show|add|rm|use`, `--machine`.
  Profiles become "read-only browse lenses (repo/plugin-defined; `configsys profile list|show`, TUI
  Profiles screen); `profile:<name>` still expands in install/remove/…". The `+include/~remove/+self`
  term algebra stays valid for REPO/PLUGIN profile authors only — say so.

### [HIGH] README completeness — commands block (README.md:199-219) vs app.py argparse
Missing entirely: `machine`, `picks`, `versions`, `profile`, `config`, `theme`, `orphans`, `keys`,
`tui`, `disp`. Wrong: `manpages <install|check>` → real is `install|status` (help-sub.txt). Incomplete:
`dotfiles <status|capture>` → also `staged|activate|discard`; `where` has `-p/--profile`; `location`
has `--all`; `plugin trust [--all]`, `plugin add --pin/--local/--replace`; `report/request --yes/--print`.
Fix: regenerate the block from `configsys -h` (or, better, point at `configsys(1)` and keep README to
the 10 most-used).

### [HIGH] README completeness — global flags + environment (README.md:237-244)
Missing flags: `--machine NAME`, `--color {auto,24bit,256,16,8,none}`, `--nocolor/--no-color`,
`--effects {full,reduced,none}`, `--probe`, `--splash-linger`. Missing env vars actually read
(grep over configsys/): `CONFIGSYS_COLOR`, `CONFIGSYS_EFFECTS`, `CONFIGSYS_SPLASH`, `CONFIGSYS_NO_SPLASH`,
`CONFIGSYS_STATE_DIR`, `CONFIGSYS_REPO`, `CONFIGSYS_USERSCOPE_DIR`, `CONFIGSYS_SYSTEMSCOPE_DIR`,
`CONFIGSYS_APP_DIR/_SDK_DIR/_SRC_DIR`, `CONFIGSYS_GIT_TOKEN`, `CONFIGSYS_GLUE_SHELLS`, `CONFIGSYS_PM`,
`CONFIGSYS_FACET_*`, `CONFIGSYS_USER`, `NO_COLOR`, `GITHUB_TOKEN`. README says "Full list in
`configsys -h`" — but the `-h` epilog (app.py epilog / man ENVIRONMENT) lists only 4 lines, so the
promise is false in both places. Fix: extend the argparse epilog `environment:` block (single source →
flows to `configsys(1)`), and have README defer to it.

### [HIGH] doc-vs-code — `prefer:` / wrong precedence order in "Choosing among methods"
docs/config-format.md:203-211 (→ configsys.hu.5): "1. most specific; 2. `driver-preference`; 3. a
per-binding `prefer:` rank". Code (resolve.py:123-146 `_standing`) and routing-model.md §8a / CLAUDE.md:
0. `never-auto` filter; 1. most specific; 2. **`standing:` integer** (outranks driver-preference);
3. `driver-preference`. `prefer:` no longer exists. Fix: rewrite the list; document `standing:`
(`never-auto` | integer) at binding/driver/component level in the Components-and-bindings section.

### [HIGH] doc-vs-code — glue absent from every public doc
`via: glue` driver (drivers/glue.py), roots `repo/glue/` + `<state>/glue/<shell>/conf.d/` (paths.py:68,
107), TUI **Glue** screen (menu.py SCREENS key `4`; keys `a/A/x`), `dotfiles staged|activate|discard`
(shell-writes guard → staged glue), `disabled-drivers` ("dotfiles / glue to manage your own shell
config"). Not in README (Concepts, Dotfiles, driver list), config-format.md (Drivers, dotfiles
section), theming.md (pages list). Only docs/dotfiles-glue-split-plan.md describes it. Fix: add a
short "Dotfiles vs glue" subsection to README + config-format.md: dotfiles = an app's own config
(`.cfs` marker dir + manifest, linked from your store); glue = per-shell conf.d enablement snippets
configsys ships, activated per installed shell; add `glue`, `snap`, `native-pkg-file`, `pyenv`,
`sdkman` to both driver lists (all registered: drivers/*.py `name =`).

### [HIGH] man-page sync — argparse help strings carry retired concepts into configsys(1)
Because man1 is generated from `build_parser()`, these app.py strings ARE the man page:
- app.py:2864 `machine` help: "view or edit `machines:` — named profile-sets that overlay the shared
  profiles" — but layers.py:278 lists `machines` as RETIRED and cmd_machine (app.py:3340) documents
  "the columns of the matrix, i.e. the keys of `picks:`". Contradiction inside one binary.
- app.py:2877 `disp` help: "(the v2 triage state)… include/exclude live in your profiles" — v2 is
  superseded; include/exclude are picks now.
- app.py:2824 `inspect` "active profiles"; :3055 `orphans` "no active profile accounts for";
  dotfiles `status` "every dotfile in the active profiles"; epilog :2765.
- app.py:2924 `check`: "(repo + ~/configsys.hu)" — the file moved to `~/.config/configsys/configsys.hu`
  (legacy path only migrated; app.py:157).
- man FILES (gen_manpages.py:96-102): "configsys.hu — per-machine config (profiles, pins, plugins)" →
  should read picks/machine/pins/plugins; missing `glue/`, `method-versions.hu`, `last-refresh`,
  `glue-locations.tsv`, `stale-pins.json`, `last-failure.hu` (paths.py:87-108). "plugin-trust.hu:
  approved content hashes" ok.
Fix: edit the strings in app.py, then `python3 tools/gen_manpages.py` (test_manpages.py enforces).

### [MED] code bug exposed by docs — `locations:` and `reboot-advice:` flagged unrecognized by `check`
config-format.md:53,69-72 documents `locations:` (read at config.py:188); `reboot-advice` is in
`CONFIG_SETTINGS` (actions.py). Neither is in `layers._KNOWN_TOP_KEYS` (layers.py:266-274), so a user
who follows the docs gets `warn … unrecognized top-level key `locations:` (typo, or retired?)`
(verified live with a sandbox config). Fix (code): add both to `_KNOWN_TOP_KEYS`.

### [MED] doc-vs-code — config-format.md machine-settings list is half the registry
Documented: scope, include, plugins, pins, driver-preference, splash, dirs, locations, detect-coexisting,
theme, component-names. Real settings (actions.py CONFIG_SETTINGS + layers known keys) also include:
`picks`, `machine`, `dispositions`, `uninstall`, `adopt-installed`, `auto-tighten`, `disabled-drivers`,
`refresh-before-execute`, `install-overlay`, `reboot-advice`, `effects`, `orphans-ignore`, `keys`,
`installer-shell-writes`, `installer-shell-writes-allow`, `version-floors`, `facets`. The "Where a
machine-setting edit lands" section (:95-118) lists only 5 uniform + 3 machine settings; SETTING_NATURE
has 17. Fix: one table generated from / mirroring CONFIG_SETTINGS (kind, nature, default, one-liner).

### [MED] doc-vs-code — splash default named `plain`; `random` undocumented
config-format.md:83-87 "unset for the built-in default (`plain` — a static progress line)". Code:
`DEFAULT_SPLASH = 'braille-bar'` (tui/splash.py:75); `splash: random` is accepted (CONFIG_SETTINGS).
plugins.md §8 P2d correctly says braille-bar. Fix the line; mention `random`.

### [MED] retired-feature — "discovered" layer role still in precedence chains
theming.md:41 "repo < plugins < primary < discovered < your top config"; routing-model.md:414 "(repo <
plugin < discovered < user)". Discovery was removed (memory: ded2826; CLAUDE.md "Machine-level plugins
(was: project discovery)"). Fix: drop "discovered" from both.

### [MED] terminology — routing-model.md §3/§4 still show `opt-in:`
routing-model.md:69-72 (schema block), :145-148 (`opt-in: true` examples), :152-164 ("opt-in", "non-opt-in").
§8a of the same doc says the name is gone. routes.hu has 0 live `opt-in:` keys (4 grep hits are all
comments) and 41 `standing:`. Fix: replace with `standing: never-auto` in the schema + examples; add
`standing:` and `attrs:`/`description:`/`installed-name:`/`locations` to the §3 shape.

### [MED] README TUI section (README.md:254-271) describes a superseded screen
- "A **profile → component → unit** tree. Profiles are expanded by default…" — the Components screen
  is now a component tree over this machine's picks with a tri-state view MODE (`to-do` / `tracked` /
  `installed+tracked`, `M` cycles; menu.py:1779); profiles live on a separate Profiles screen (key 2,
  matrix of components × machines).
- Key list drift vs config.hu `keys:`: `m` "pick install method" → real is **`v`** (`m` is machines on
  Profiles, move on Config/Dotfiles); missing `w` where, `M` mode, `R` refresh, `I/U` all, `/` find,
  `F` filter, `?` help, `Q` force-quit, `pgup/pgdn`, and the `1`-`7` screen switcher (Components,
  Profiles, Plugins, Glue, Dotfiles, Config, Theme). No mention that keys are rebindable (`keys:` /
  `configsys keys`).
- Fix: rewrite as "seven screens" + per-screen one-liners, cite `?` in-TUI help and `configsys keys`
  as the authoritative legend rather than listing keys.

### [MED] README/WALKTHROUGH — `where` output samples don't match the real format
README.md:246-252 and WALKTHROUGH.md:185 show `<- selected here`. Real output (run live): `<- default
here`, plus `(shadowed — …)` / `(alternative here — pin to use)` annotations and a `default: via native
(by most-specific when:)` line, "defined in routes.hu" header. Fix: paste a fresh capture.

### [MED] plugins.md CLI claims not matching app.py
- :103 "`plugin add github:x/y[@ref]`" — no `@ref` parsing exists (only `--ref`; plugins.py:186 is
  token auth). Fix → `--ref`.
- :104-105 "`sync` … **prune undeclared ones**" — no prune code in app.py/plugins.py (grep). Verify or
  drop.
- :63 precedence "repo < plugins (declaration order) < user config" omits primary (correct at :11).
- :93-95 `configs:` (see HIGH #1). :36 `profiles.hu` is fine (plugins may define profiles).
- `plugin trust` accepts `--all` / no-name; `plugin add --pin/--local/--replace` — `--local` only
  documented in config-format.md.

### [MED] theming.md drift
- :6 and :115 "Theme screen (nav key **6**)" → key `7` (SCREENS; `6` is Config). theme-redesign.md:5 same.
- :71 pages list `components, profiles, plugins, dotfiles, config` → add `glue` (and `theme` itself is
  in ALL_PAGES). :124 "`a`–`e` cycle pages" vs config.hu keys `page-1..page-7` = F1–F7 — verify which
  the screen actually binds (config.hu is the merged default → F-keys).
- :41 "discovered" (above).

### [MED] terminology — "unit" is a fourth noun the canonical set lacks
README.md:41-44, :256-264 use **unit** (`driver\comp`, "unit-keyed staging") heavily; CLAUDE.md also
uses "unit key". The canonical list is component / driver / via / binding / pin / pick / profile. Either
add "unit (= a resolved component+driver pair, the dedup identity)" to README Concepts as a defined
term, or say "resolved component" consistently. Also README:47 "Driver — … behind a uniform op set
(install / … / inspect)" — the op set is get_version/get_latest/is_locked/install/uninstall/upgrade/
set_version/lock/unlock/location (CLAUDE.md, plugins.md §7a); "inspect" isn't a driver op.

### [MED] terminology — "machine-level plugin" vs "local plugin" vs "non-primary"
README:149-151 "Machine-level plugins", config-format.md:301-315 "Machine-level plugins", CLI flag is
`--local`, layers role is `plugin`. Three names for one idea. Pick one ("a local plugin, `plugin add
--local`") and use it everywhere.

### [MED] dead/superseded plan docs lacking a supersession banner
- docs/profiles-disposition-plan.md — no Status line; body reads as the current model.
- docs/profiles-derive-plan.md:3 "DESIGN, not built" — it was built then ripped out (memory).
- docs/dotfiles-redesign.md:3 "DESIGN AGREED, not built" vs body ":197-228 DONE".
- docs/startup-perf-plan.md:3 "fixes NOT built" — all built.
- docs/routing-overhaul-plan.md:3 "Planning only — no code yet" — standing/detection tier built.
- docs/versioned-requires.md:3 "design / exploration" — fully shipped.
Fix: uniform first line `Status: HISTORICAL — <built|superseded by docs/X.md>` (or move to docs/history/).

### [LOW] facets are live but undocumented publicly
docs/facets.md has no Status line; `facets:` is a known top key, predicate.py evaluates categorical +
versioned facets, `CONFIGSYS_FACET_*` env exists. config-format.md §The `when:` expression (:187-201)
lists only OS + cpu atoms; README:95-96 same. Fix: one bullet ("a declared **facet** atom — see
docs/facets.md") + a Status line in facets.md.

### [LOW] config-format.md Layers paragraph (:20-24) — includes ignore "`configs:`, `scope:`, `pins:`"
Retired key in the ignore list; the machine-settings set is now much larger (`picks`, `machine`, …).
Also ":23 The one exception is `theme:`" — `keys:` is merged from every layer the same way
(keybindings-plan.md decision 1; layers.py known key). Fix: "cosmetic/UI sections `theme:` and `keys:`".

### [LOW] README Dotfiles section (README.md:276-308)
":292 every dotfile in your active profiles" → picks. No mention of `.cfs` marker / manifest /
managed-even-when-empty / `manage`/`unmanage` TUI verbs (Dotfiles screen keys m/M/u/U/s/S) / exclude
globs. config-format.md dotfiles section (:248-273) same gap ("`absorb-into`" documented; `.cfs`
not). Fix: brief paragraph + pointer.

### [LOW] README Concepts "State" (:55-58) and man FILES omit real state files
`method-versions.hu`, `last-refresh`, `stale-pins.json`, `last-failure.hu`, `glue-locations.tsv`,
`startup-timing.json`, `glue/` store (paths.py:87-108). At minimum say "ledger + caches in
`~/.config/configsys/`" rather than enumerating one file.

### [LOW] README ":36 `--pretend` … no network calls" vs config-format ":245 `--pretend` never touches
the network (cache-only)" — consistent, fine. But README:213 "refresh — re-query latest versions" omits
that refresh also refreshes the native package index (sudo apt-get update etc.; memory refresh-and-index)
and stamps `last-refresh`; `refresh-before-execute` setting undocumented.

### [LOW] expansion-plan.md:67 "`script` driver generalizes sdkman — rather than a bespoke sdkman
driver" — a dedicated `sdkman` driver now exists (drivers/sdkman.py). Historical doc; add a note.

### [LOW] CLAUDE.md itself (out of scope for edits, but it is the stated ground truth)
CLAUDE.md:16 "If it contains a top-level node called 'configs'… those values are the profiles" and :68
"`configs:`/`scope:` (machine settings)" contradict CLAUDE.md's own memory entries and layers.py
(`configs` retired). CLAUDE.md driver list (:100-108) omits `glue`, `snap`, `pyenv`, `sdkman`. Flag
for the owner: the "ground truth" doc needs the same picks/glue pass.

### [NIT] README:212 `check` "(repo + your file + includes + plugins)" fine; README:105/config-format:184
"`configsys where`" fine. README:170 "`./configsys.sh plugin sync` … transitive plugins" fine.
### [NIT] README:6 lists Void/Proxmox as plugins, table :347-352 omits `configsys-source`,
`configsys-splash-*`, `configsys-bigdata`, `configsys-opencv` (memory says published/local) — the "Known
plugins" table is incomplete relative to memory; verify which are pushed before listing.
### [NIT] config-format.md:294 tarball "(also bare-binary and `.zip` archives)" — fine; :296 driver list
missing `snap`, `glue`, `native-pkg-file`, `pyenv`, `sdkman` (same as HIGH glue finding).
### [NIT] name-sweep-test.md:37 counts "apt 138 / dnf 140…" are a snapshot; label as "at time of writing".
### [NIT] WALKTHROUGH.md:172-173 `plugin list` sample output format — verify against current `plugin
list` rendering (not re-run here; format has gained conflict footers/checksum states).

---

## (b) Concrete edits per public doc

### README.md
1. :33-34, :45-46, :129, :139: replace `configs:`/`profiles:` authoring with `picks:` + `machine:`;
   redefine **Profile** as a read-only browse lens (repo/plugin-authored; `+include/~remove/+self`
   are for those authors); add **Pick** to Concepts.
2. :41-44 define **unit** explicitly or drop the term; :47-48 fix the driver op set; :49-54 add glue,
   snap, native-pkg-file, pyenv, sdkman.
3. :101-103 scope-honoring list → match config-format (font/npm/gem/luarocks also honor scope).
4. :147-151 unify "machine-level plugin"/`--local` naming.
5. :172-183 `plugin init` copies "profiles/components" → "picks/components/dotfiles/glue".
6. :199-219 regenerate the command block from `configsys -h` (add machine, picks, versions, profile,
   config, theme, orphans, keys, tui; fix `manpages install|status`; dotfiles staged|activate|discard).
7. :237-244 add the 6 missing global flags and the full env list (or defer to `configsys -h` once the
   epilog is complete).
8. :246-252 re-capture `where steam`.
9. :254-274 rewrite TUI as 7 screens (1-7), Components MODE cycle, `?`/`configsys keys` for bindings;
   fix `m`→`v`.
10. :276-308 add "dotfiles vs glue" + `.cfs` marker + Glue screen; :292 "active profiles" → picks.
11. :357-365 Design notes: "Selecting a profile never changes your system" → "Browsing a profile /
    picking a component never changes your system".

### docs/config-format.md (→ regenerates man/configsys.hu.5)
1. :20-24 layers: drop `configs:`; list machine settings as "picks/machine/pins/scope/… (see table)";
   `theme:` AND `keys:` merge from every layer.
2. :31-57 sample config: remove `configs:` and `profiles:`; add `machine:`, `picks:`, `keys:`,
   `disabled-drivers`, `adopt-installed`, `auto-tighten`, `reboot-advice`, `effects`, etc.
3. :59-93 bullets → a full settings table (kind / nature / default / description) mirroring
   `actions.CONFIG_SETTINGS`; fix splash default `braille-bar` + `random`.
4. :95-118 edit-target nature: list all 17 settings' natures; mention `picks` uniform / `dispositions`
   machine.
5. :120-144 Profiles: reframe as repo/plugin-authored browse lenses; keep term algebra for authors;
   `all` synthetic profile: replace "add it to `configs:`" with the Components MODE / `profile:all`.
   Add a **Picks** section (`picks: { <machine>: [...] }`, `machine:`, `uninstall:`, `dispositions:`,
   CLI `picks`/`machine`/`--machine`).
6. :173-175 mention `standing:` per binding; :203-215 rewrite precedence (never-auto filter →
   specificity → `standing` → `driver-preference`; pin > detected-installed > default via
   `adopt-installed`); delete `prefer:`.
7. :187-201 `when:` atoms: add facets.
8. :248-273 dotfiles: add `.cfs` marker/manifest/managed-when-empty + a **glue** section (via: glue,
   conf.d per shell, `dotfiles staged|activate|discard`, `CONFIGSYS_GLUE_SHELLS`, `disabled-drivers`).
9. :290-299 Drivers: add glue, snap, native-pkg-file, pyenv, sdkman.
10. :301-315 "Machine-level plugins" → unify naming with README.

### man/configsys.1 (via configsys/app.py strings + tools/gen_manpages.py)
1. app.py:2864 machine help → "view or edit machines — the columns of the picks matrix".
2. app.py:2877 disp help → drop "v2 triage"/"include/exclude live in your profiles".
3. app.py:2824/:3055/dotfiles-status/:2765 "active profiles" → "this machine's picks".
4. app.py:2924 check → "~/.config/configsys/configsys.hu".
5. app.py epilog `environment:` → the full env list.
6. gen_manpages.py:96-102 FILES → picks wording + glue/ + the other state files.
7. Re-run `tools/gen_manpages.py`; test_manpages.py gates it.

### docs/routing-model.md
1. :69-72 schema: `opt-in:` → `standing:`; add `attrs:`, `description:`, `installed-name:` fields.
2. :145-164 examples/prose: `opt-in: true` → `standing: never-auto`; "non-opt-in"/"opt-in" wording.
3. :414 drop "discovered".
4. :463-464 "consolidation now under way … routing-overhaul-plan.md" → "shipped; see §8a".

### docs/plugins.md
1. :93-95 `configs:` → picks/machine/pins.
2. :103 `[@ref]` → `--ref R` (+ `--pin`, `--local`, `--replace`).
3. :104-105 verify/drop "prune undeclared ones".
4. :63 precedence add primary.
5. :116 `trust [name|--all]`.

### docs/theming.md
1. :6, :115 key 6 → 7. 2. :41 drop "discovered". 3. :71 add `glue` page. 4. :124 confirm page-cycle
keys (F1–F7 per config.hu `keys:` vs `a`–`e`).

### docs/name-sweep-test.md
Current; optionally note roadmap 4 still open and the counts are a snapshot.

### examples/examplos/WALKTHROUGH.md
1. :185 `<- selected here` → `<- default here` (re-capture). 2. :172-173 re-capture `plugin list`.

### docs/*.md plan hygiene
Add/repair `Status:` first lines per the table (profiles-disposition-plan, profiles-derive-plan,
dotfiles-redesign, startup-perf-plan, routing-overhaul-plan, versioned-requires, facets); consider
moving HISTORICAL rows into `docs/history/`.

### Code (surfaced by the audit, not doc edits)
- layers.py `_KNOWN_TOP_KEYS`: add `locations`, `reboot-advice`.

---

## Counts
HIGH 6 · MED 12 · LOW 6 · NIT 5 (plus 1 code bug, MED).
