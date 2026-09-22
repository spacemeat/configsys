# configsys code review — 2026-09-20

A full-tree review of configsys (~26k LOC: engine, 35 drivers, TUI, docs). Conducted by 11
focused agents (Fable 5.1), one per area, each applying the same lens set: code reuse,
data-driven/MVVM structure, comment-vs-code drift, naming, performance, tests, dead code,
security, refactors, CLI/TUI parity, and ABI-break candidates. This README is the synthesis;
the per-area detail (with file:line for every finding) is in the sibling files:

`routing-engine.md` · `config-plugins.md` · `drivers-os.md` · `drivers-lang-build.md` ·
`dotfiles-glue.md` · `app-cli-actions.md` · `subsystems.md` · `tui-menu.md` · `tui-theme.md` ·
`security.md` · `docs-sync.md`

Line numbers are a snapshot against HEAD ~`7c0c04d`/`fcafb84` and will drift as fixes land.

Roughly 260 findings: ~37 HIGH, ~108 MED, ~82 LOW, ~35 NIT (with cross-report overlap on the
security items). The suite is green (1331) and `check` is 0-error across all base OSes, so every
finding is against a working baseline — this is polish and hardening, not triage of a broken tree.

---
For posterity, this is the given prompt for this work:
Let's do a thorough and complete code review. Use Fable 5.1, and as many spawned agents as you need. *Take your time.* I think you know in general what good quality code looks like, but focus on:
- Code reuse, where it makes sense.
- Data-driven presentations. Think MVVM-style stacks, which could use real or mock data.
- Good linting. Many of the comments are for your own future edification, so don't feel the need to erase them, but ensure any comments are up-to-date with the code.
- Good, human-readable variable names.
- Don't be bashful about looking for performance enhancements. Examine how often a computation is performed in inner loops, and whether caching or memoizing makes sense. Remember too that this is python, and it is in general slow and mostly single-threaded.
- Don't be bashful about adding tests. *Do* be bashful about removing tests, unless there is no codepath they cover. Adding tests is great.
- Look for dead code. We've made lots of changes over the development. There may be straggling bits. Do bear in mind that this is a plugin architecture, so some parts may be called from the outside, especially in plugins.
- Be judicious about security. We're evaluating script in some places, and doing other things that make the security question vague--the trust model for plugins is great, but what else might slip in? Besides the usual supply chain attacks any user of, say, flatpak might encounter anyway.
- Feel free to make suggestions about broader refactors. If an overhaul is worthy, I'd like to consider it. We've been iterating a long time.
- If there's any features missing in your mind, call them out. If there's any imparity between CLI and TUI, call them out. *Most* things CLI can do *should* be elevated to TUI as well, but not necessarily all.
- I remain the only user (but not for long). If an ABI or major interface ought to change, so be it. Let's tackle that now, before we break anybody.
- Synchronize all public docs (README.md and anything it links to), man pages, etc. to current functionality. Look for outdated terms or language, and aim to reduce new terms and to be consistent with terms like component, driver and via, dotfiles vs. glue.

---

## Progress (updated as work lands)

- **DONE — critical:** tarball `rm -rf $HOME` (`fcafb84`).
- **DONE — Tier A security (the #1 theme):** A1 gate command-carrying data as code (`f066814`);
  A2 facets repo/primary-only (`4e45a8b`); A3 dir_name traversal, A4 git option injection, A6
  `$VERSION` validation, A8 native-pkg-file mktemp, A9 `_alt` quoting, B7 `_KNOWN_TOP_KEYS`
  (`7f43966`).
- **DONE — Tier B correctness:** B1 pin-namespace collision + B2 disabled-context (`468a6d3`…
  `b12`), B3 CLI `locations:` + B4 glue-cache invalidation + B5 note-clobber (`468a6d3`), B8
  driver bugs — apt multi-package lock / flatpak empty hub / dnf keyless repo (`f684a71`), B6 glue
  safety — literal rc regen / `--pretend` / communal-conf.d backup (`328d25e`), B9 version-cache
  race (`4553619`). (B10 folds into D3.)
- **DONE — Tier E docs:** README/config-format/routing-model/theming/plugins/CLAUDE.md synced to
  the picks model; 24 plan docs stamped; argparse help + man pages regenerated (`acfdecc`).
- **TODO — Tier A remainder:** A5 (transitive `plugins:` scope), A7 (asset `sha256:` checksums),
  A10 (constrain `pubkey-path`/`source-path` to keyring dirs).
- **DONE — plugin correctness:** facet-trust fix (a plugin's `facets:` merge when the plugin is
  content-trusted, not blanket-refused — restored configsys-opencv's `cuda` facet); recipe-vs-code
  trust labels.
- **DONE — C1 (D1's highest-value slice):** shared `batch_index` on the Driver base so
  dnf/zypper/pacman/brew/snap batch their startup probes (the non-Debian startup-perf fix) —
  `eae03ac`.
- **DONE — D3 unified `run_plan`** (`…`): the CLI and TUI share one op-execution loop
  (`actions.run_plan`); the TUI gained set-version, advisory handling, verify-after-fail, and
  all-failures persistence (closes B10). (A TUI key to *trigger* set-version is a small follow-on;
  the plumbing is ready.)
- **DONE — D1 `NativePkgManager` dedup:** the five native drivers (apt/dnf/zypper/pacman/apk) now
  share one install/uninstall/upgrade skeleton via command templates; byte-identical commands, unit
  suite green, and the real install→lock→unlock→remove lifecycle PASSES in podman on Fedora (dnf)
  and Arch (pacman).
- **DONE — pacman/Arch correctness:** rolling native managers (pacman/apk) no longer fake
  version-locks/pins (`holds_version=False`) — they decline honestly, record nothing, and the UI
  doesn't offer them (`d5b29d0`).
- **DONE — D2 perf (C3):** memoized the Profiles per-frame hot paths (gradient background, `_parts`,
  `visible_pnodes`, and the `dependents`/`profiles_containing` reverse indexes) → **27.9 → 8.6
  ms/frame, 3.2×** on the real catalog; the gradient cache speeds every screen (`d0cf422`).
- **TODO — D2 structural (optional):** the full MVVM rewrite (draw fns as pure VM emitters +
  `{id: Screen}` router). The *perf* payoff is delivered; this is architectural cleanliness for
  testability — an incremental, screen-by-screen follow-on, not required for the C3 win.
- **TODO — the rest:** `_alt.py`/native-pkg-file delegating to the native driver (D1 follow-on),
  D4 `ModuleDriver`/C2 (podman-validatable), C4/C5 caching, A5/A7/A10 hardening, Tier F ABI cleanups.

## 0. Already fixed this session

- **`rm -rf $HOME` in the tarball driver (CRITICAL).** A tarball binding is wiped on every
  (re)install (`rm -rf <dir> && mv <stage> <dir>`); with no `installDir:` the dir resolves to the
  bare scope base — `$HOME` at user scope. Core `android-studio` had no `installDir:`, so
  `configsys install android-studio` would have run `rm -rf $HOME` (verified with a pretend run).
  Fixed in `fcafb84`: route gets a dedicated `installDir`, the driver refuses any shared-base
  target, `check` gains a `tarball-no-installdir` lint, + regression tests. **This one finding
  justified the review.**

---

## 1. The cross-cutting themes (what recurs across areas)

1. **The plugin trust model gates the wrong axis.** Trust is per-content-hash on Python `code:`
   modules — well built, fails closed. But a plugin's *data* is already a program: `via: script`
   (`install-cmd`), `via: source` (`build:`), `via: glue` (`#!cs-eval`), apt `source-line:`, and
   especially `facets: { detect: … }` all carry shell strings configsys runs through `bash -c` /
   `shell=True`. Data-only plugins sync and load with **no trust prompt** (docs promise "just data
   can't do much harm" — false), and are reachable *transitively*. `facets: detect:` runs at every
   startup/`inspect` with zero user action; `script`/`source` version probes run during the
   "read-only" inspect sweep. This is the single most important theme, raised independently by the
   security, config-plugins, drivers-lang-build, and routing-engine agents.

2. **Driver code is 5 native + 10 ecosystem installers hand-copied.** apt/dnf/pacman/zypper/apk are
   the same 9-op skeleton; cargo/pip/pipx/npm/gem/opam/luarocks/cabal/go-install/sdkman are the same
   5-command table. ~600 + ~400 lines of near-duplicate. Consequences beyond bloat: `batch_index`
   (the startup-perf win) exists only for apt/flatpak/npm/pip, so **inspect on Fedora/Arch/openSUSE/
   Alpine is back to per-unit subprocess spawns**; and quoting/scope bugs must be fixed N times.

3. **The TUI has no view-model seam.** `_draw_*` functions read `ctx.config`/`routes`/drivers in
   row loops *and* write model state (scroll clamps). The `_SampleCfg`/`_SampleCtx` proxy (the
   theme-sample work) is applied to one screen. Per-frame recomputation dominates
   (`_parts()` 3×/row/frame, `profile_untracked_count` over the whole catalog per keystroke,
   `visible_pnodes()` ~7×/frame, config re-parsed from disk every frame). `menu.py` is 6.3k LOC with
   a 1300-line `run()` and heavy modal/table/chrome copy-paste.

4. **Machine-setting knowledge is scattered across four registries and has drifted.** `config.py`
   getters, `layers._KNOWN_TOP_KEYS`, `layers._SETTING_SECTIONS`, `actions` nature table — already
   out of sync: `locations:` and `reboot-advice:` are live settings that `check` reports as
   "unrecognized" (a real, demonstrated bug), and non-primary plugins setting `picks:`/`dirs:` are
   ignored with no warning.

5. **The profiles→picks retirement never reached the public docs (or CLI help).** README,
   config-format.md, plugins.md, routing-model.md, CLAUDE.md, and dozens of argparse help strings
   (→ the man pages) still teach `configs:`/user `profiles:`/`prefer:`/`opt-in:` as current.
   Terminology (`component`/`driver`/`via`/`pick`/`dotfiles` vs `glue`) is inconsistent, and glue is
   nearly invisible in the docs.

6. **Comment/code drift and dead-code stragglers from the long iteration** are everywhere but
   individually small — retired-model docstrings, an unreachable layer-grouped profiles pane, a
   dead `errors.ResolveError`, `presudo`, `privileged`, `_STATUS_LABEL`, etc. The profile-authoring
   writers named in the old consolidation plan are already gone (verified) — that plan is done.

---

## 2. Act-on-these, ranked

### Tier A — security hardening (do as one workstream)

The findings below are mostly "requires a malicious/careless plugin", not accidental — but the
user is about to gain collaborators, so the plugin boundary is about to matter for real.

- **A1 [HIGH] Extend trust to command-carrying data.** Treat a plugin layer that contributes a
  `via: script`/`source`/`glue`(`#!cs-eval`) binding, an apt `source-line:`/`ppa:`, or a `facets:
  detect:` as a *code* plugin: require the same per-content trust before those bindings can run,
  and/or surface them in `plugin list`/`check`/the install plan. Fix docs/plugins.md §6.
  (security H1–H3, config-plugins H1, drivers-lang-build MED.)
- **A2 [HIGH] `facets: detect:` at startup.** Merge `facets:` only from `repo`/`primary` (not plain
  `plugin`), or gate behind A1; prefer an argv list over `shell=True`. (routing-engine H2,
  security H2.)
- **A3 [HIGH] `dir_name()` path traversal → `rmtree`.** `dir_name('github:a/..') == '..'`; feeds
  `sync` clone, layer loads, and `shutil.rmtree` in `plugin remove`. Reachable via transitive
  decls. Validate to a single safe segment; assert containment before any clone/read/rmtree.
  (config-plugins H2, security MED.)
- **A4 [HIGH] git option injection.** `source:`/`ref:` starting with `-` become git options
  (`--upload-pack=…`). Put `--` before positionals in every git command; reject `-`-leading
  sources/refs. (config-plugins H3.)
- **A5 [HIGH] include-dedup demotes the user's top config.** A lower layer that `include:`s the
  user's own config re-tags it `include`-role and silently drops their `scope`/`pins`/`picks`.
  Skip/upgrade root paths in `_visit`. (config-plugins H4.)
- **A6 [MED] `$VERSION` injection.** An upstream tag name is spliced unquoted into `source`/`script`
  build commands. Validate discovered versions to a strict charset, or pass as env not text.
  (drivers-lang-build H2, security MED.)
- **A7 [MED] No asset checksums.** Every download `curl`s a plugin-controlled URL (http allowed) and
  installs/executes it unverified — `native-pkg-file` as root. Add optional `sha256:`, verify before
  extract/install, warn on system-scope downloads without it. (drivers-lang-build H3, security MED.)
- **A8 [MED] `native-pkg-file` predictable `/tmp` as root.** `curl -o /tmp/configsys-<comp>.deb`
  under sudo → symlink attack → arbitrary root write. Use `mktemp`. (drivers-os MED, security MED.)
- **A9 [HIGH] `_alt.py` interpolates route fields (ppa/deb/link/slaves) unquoted into a root
  shell.** `shlex.quote` every field. (drivers-os H1.)
- **A10 [MED] key/source-path from data plugins written to arbitrary root paths** (`_offer_rekey`,
  apt/dnf source writers). Constrain `pubkey-path`/`source-path` to keyring/source dirs at
  routecheck. (app-cli-actions MED, drivers-os LOW.)

### Tier B — correctness bugs (small, high-value)

- **B1 [HIGH] Pin-namespace collision.** `pins: { python3.13: pyenv }` (or any via-named component)
  is classified as a provider-pin in `resolve` but a binding-pin in `app`, breaking every component
  that `requires: python3.13`. One shared classifier. (routing-engine H1.)
- **B2 [MED] `disabled` dropped from 15 hand-built contexts** (detection.py can soft-pin a disabled
  via → phantom error rows). Add `Resolver.context()` and use it everywhere. (routing-engine MED.)
- **B3 [HIGH] CLI ignores `locations:` on install/remove/upgrade/lock/location** (only inspect/TUI
  honor it). Fold scope+locations into one `prepare_units`. (app-cli-actions H1.)
- **B4 [MED] TUI never invalidates the glue location cache after a pin/pick** → PATH points at the
  stale dir. Move invalidation inside `actions.set_included`/`set_pin`. (app-cli-actions MED.)
- **B5 [MED] `_draw_profiles` clobbers its `note` param** with "(also in: repo)", dropping
  action-feedback status. (tui-menu MED.)
- **B6 [MED] Glue/dotfiles safety:** `conf.d` clobber with no backup/refusal; `--pretend` honored
  only for the bash `ln` step (rc rewrites, `.cfs` stamping, `~/.bash_aliases` rename all run for
  real); the inline-shell block is spliced with `re.sub(pattern, block)` using snippet content as
  the *replacement* string — verified to mangle `\t` today and to raise on any `\1`. (dotfiles-glue
  H1–H3.)
- **B7 [MED] `_KNOWN_TOP_KEYS` missing `locations`/`reboot-advice`** → `check` false positives.
  (config-plugins MED, docs-sync.)
- **B8 [MED] flatpak `install` emits a literal `''`** when a binding has no `hub`; **dnf writes
  `gpgkey=None`** when no `pubkey-url`; **apt lock/set-version disagree with `_pkgs`** on
  multi-package bindings. (drivers-os MED/LOW.)
- **B9 [MED] Version caches race under the inspect thread pool** (per-call load/modify/save of
  `versions.hu`, last-writer-wins). (subsystems.)
- **B10 [MED] TUI batch persists only the last failure** and has no `set-version` branch (returns
  "no result"); advisory/verify-after-fail handling is CLI-only. Resolved by B-refactor below.
  (app-cli-actions H2.)

### Tier C — performance (Python is slow; these are the hot paths)

- **C1 Non-Debian startup regression:** give the native base a default `batch_index` (dnf/zypper/
  pacman/apk/brew/snap currently spawn per unit). Biggest real-world win. (drivers-os H2.)
- **C2 Ecosystem installers probe per component** (cargo/gem/luarocks/opam/pyenv/sdkman/go-install);
  add `batch_index`. sdkman shells `sdkman-init.sh` per unit — read the `current` symlink instead.
  (drivers-lang-build MED.)
- **C3 TUI per-frame recompute** (theme C-tier of tui-menu): memoize `_parts`, precompute `is_new`
  as a set, cache `visible_pnodes`/untracked counts, stop re-parsing config/theme every frame. The
  view-model refactor (D-tier) subsumes this. (tui-menu H1–H3, subsystems.)
- **C4 `diagnostics()` re-resolves the world 2–3× per command** (`dotfiles_units` does a full
  resolve that `load_pipeline` already did). Memoize on the Context. (app-cli-actions LOW,
  subsystems.)
- **C5 Plugin trees re-hashed and manifests re-parsed many times per startup.** Memoize on
  `(path, mtime, size)`. (config-plugins MED.)

### Tier D — worthy refactors (need your appetite; each is a focused change)

Ranked by value-per-line. Each collapses duplication *and* fixes a bug class in one place.

- **D1 `NativePkgManager` base** (apt/dnf/pacman/zypper/apk + native-pkg-file/`_alt` delegate to it).
  Deletes ~400 lines, gives every native driver `batch_index` (C1), and fixes the `_APT_ENV`/
  config-files/quoting drift once. *Highest value.* (drivers-os.)
- **D2 TUI view-model seam** — `Screen.build_vm(h,w) -> VM dataclass` (memoized on a `_view_gen`),
  `draw(stdscr, pal, vm)` a pure emitter. Resolves every HIGH TUI perf finding, the MVVM finding,
  the draw-mutates-model finding, most duplication, and makes samples literals (no proxies/threads/
  probes) and every screen headlessly testable. Then the `if screen ==` ladders collapse into the
  `{id: ScreenClass}` router the plan already specified. *Biggest structural win; do Profiles
  first.* (tui-menu.)
- **D3 `actions.run_plan()`/`build_plan()`** — one op-execution loop for CLI + TUI. Brings
  `set-version`, `--no-deps`, advisory handling, verify-after-fail, and full failure-reporting to
  the TUI for free (B10). (app-cli-actions.)
- **D4 `ModuleDriver` base + `LedgerLockMixin`** for the 10 ecosystem installers. ~400 lines,
  batch enumeration (C2) for free. (drivers-lang-build.)
- **D5 Settings registry** — one `SETTINGS = {key: Setting(kind, nature, roles, default, desc)}`
  table feeds `_KNOWN_TOP_KEYS`, `_SETTING_SECTIONS`, the `Config` getters, and the `actions` view.
  Kills theme 4's drift class (B7) and the 3-way bool-parsing. (config-plugins.)
- **D6 `SelectionPolicy` + `Resolver.context()/select()`** — folds `(pins, preference, never_auto,
  disabled)` into one object; erases B2's whole class and the private-`_select` reach-throughs.
  (routing-engine.)
- **D7 `LinkedContentDriver` base** for glue+dotfiles — Python-side link/backup ops fix `--pretend`
  and backup policy (B6) in one place; a `ShellSpec` table replaces 7 parallel per-shell dicts.
  (dotfiles-glue.)
- **D8 Consolidate the plugins.py hand-rolled Humon I/O** (`_read_top`/`_write_top`) and fix the
  section scanner (backslash/backtick/empty-file/trailing-`}` corruption — all demonstrated).
  (config-plugins.)
- **D9 Split app.py** (3658 LOC) into Context / indexrefresh / plugin / check / dotfiles / parser
  behind a re-export shim. (app-cli-actions.)

### Tier E — docs & terminology sync (you asked for this explicitly)

- **E1** Rewrite the config model in README + config-format.md around `picks:`/`machine:` (Profile =
  read-only browse lens; add **pick** to Concepts). Generate a settings table from the registry
  (D5).
- **E2** Regenerate README's command block (missing 9 of 29 subcommands), global flags, and env list
  from `configsys -h`; extend the argparse `environment:` epilog so `-h`/man are complete.
- **E3** Fix argparse help drift (active-profiles, `machines:`, v2 triage, `~/configsys.hu`) — these
  are the man-page source — then re-run `tools/gen_manpages.py`.
- **E4** `prefer:`/`opt-in:` → `standing:`; correct the precedence list (never-auto → specificity →
  `standing` → `driver-preference`) in config-format.md and routing-model.md.
- **E5** Add a "dotfiles vs glue" section; document the Glue screen (Theme key 6→7); add the 5
  missing drivers (snap/native-pkg-file/pyenv/sdkman/glue) to both driver lists.
- **E6** Stamp the ~22 superseded plan docs `Status: HISTORICAL — superseded by …` (or move to
  `docs/history/`); fix false "NOT built" lines.
- **E7** CLAUDE.md itself needs the same pass (still says `configs:` selects profiles; omits glue).

### Tier F — ABI / interface changes (decide now, before collaborators)

The user is OK breaking these. Candidates, grouped:

- **Rename** `candidate_only`/`opt_in`/`optin`/`_binding_candidate_only` → `never_auto`. (Retired
  vocabulary is the live identifier set.)
- **Driver contract:** the documented ABI omits methods plugins already use — `location_override`,
  `scoped_dir`, `reconcile_scope`, `ensure_prereqs`, and the batch/enumeration hooks
  (`batch_index`, `installed_index`, `explicit_keys`, `origin_index`, …). Declare them on the base +
  in `test_abi_surface`. Decide `_batch` (de-facto ABI). Drop `presudo` (dead) and either make
  `privileged` meaningful or drop it.
- **Return types:** `routes.load` → named tuple; `Resolver.candidates` → a small dataclass.
- **Trust identity:** length-prefix the content hash (a demonstrated collision exists); bumps the
  trust-store format once.
- **Trim `plugins.__all__`** to the real ABI; document the rest as internal.
- **Delete dead public names:** `errors.ResolveError` (0 importers), `predicate.Cpu`/`most_specific`
  (test-only), `routecheck.check_all` (test-only), `_pf` bare-path form.

---

## 3. Test gaps worth filling (adding tests encouraged)

Every area flagged the same shape: happy paths are covered, **adversarial/edge inputs are not.**
Highest-value additions: an injection regression gate (a name with shell metacharacters must be
quoted) across drivers; `apk` has no test at all; the tarball/appImage empty-`installDir` guard
(added); `dir_name('..')`/`-`-prefixed source reaching git; include-of-a-root-layer; `{}` config
file; the section-scanner corruption cases; per-CLI-verb `main([...])` tests for the ~10 untested
subcommands; and a headless render of each `_draw_*` (trivial once D2 lands).

---

## 4. Suggested sequencing

1. **Security workstream (Tier A)** — coherent, mostly independent, matters most with collaborators
   incoming. A1/A2/A3 first.
2. **Correctness quick-wins (Tier B)** — small, each a real user-visible bug.
3. **Docs/terminology (Tier E)** — you asked for it; do it alongside B (it re-teaches the model the
   code now uses).
4. **Refactors (Tier D)** — pick appetite. D1 (native base, unblocks C1) and D2 (TUI view-model)
   are the two with the best return; D3 (run_plan) closes the biggest parity gap.
5. **ABI (Tier F)** — bundle into whatever refactor touches each surface, so it's one break.

Decisions I need from you before starting the big items: **(a)** trust-model direction for Tier A1
(gate command-carrying data as code, vs surface-and-warn only); **(b)** appetite for D1/D2/D3 now vs
later; **(c)** go-ahead on the Tier F renames/ABI breaks. Everything in Tiers A–C and E I can start
without further input.
