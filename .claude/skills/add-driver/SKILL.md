---
name: add-driver
description: Playbook for adding (or renaming/removing) a configsys install driver — a new `via:` value backed by a Driver class, in core (configsys/drivers/) or in a trusted code plugin. Covers the frozen Driver contract and its easy-to-miss rules, where the driver sits in routing (requires, gates, driver-preference), the extra wiring a native package manager needs, the hard-coded driver sets scattered through the app, which docs/skills enumerate drivers, and the tests to write and run. Use when the user says "/add-driver <name>", asks for a new install method/package manager/module installer, or changes an existing driver's attributes or hooks. test/test_driver_inventory.py enforces this checklist.
---

# add-driver — a new install mechanism, wired everywhere it must be

A driver is rare work with a wide blast radius: the class itself is small, but the app has a dozen
places that branch on driver names, three docs that enumerate every driver, two skills that teach
authors when to use each one, and a preference order that decides defaults for ~800 components.
This playbook is the checklist; **`test/test_driver_inventory.py` is the alarm** — it fails until a
new built-in driver is classified, ranked (or deliberately unranked), documented in every list and
tested, and it fails when a code symbol named here is renamed. Its failures point at the § below.

Read first: the `driver.py` module docstring (THE contract — the frozen surface), `docs/plugins.md`
§7a (the same contract for plugin authors), `docs/routing-model.md` §8 (specificity) and §8a (the
candidate set — driver gates — and selection by `standing:` / driver-preference),
`docs/principles.md` (no surprises; safety rules).

---

## 0. Is it really a driver?

A driver is a distinct install MECHANISM — its own install/uninstall/version/lock verbs. Not a
driver: a new upstream (that's a `version:` source — `versions.register_source` / `_BUILTIN_KINDS`),
a new download shape (a `tarball`/`appImage`/`native-pkg-file` field), a new OS using an existing
manager (an `os:` block — the `/add-os` skill), one tool's odd installer (`via: script`),
a source build (`via: source`, or a plugin driver like blender's when the build is substantial).

Core or plugin? **Core** for anything general (a package manager, an ecosystem installer).
**Plugin** (`DRIVERS = [...]` in a trusted code plugin, §8) for one project's build or anything
personal. A plugin driver uses only the frozen surface, so core's tables below don't apply to it.

## 1. Classify it

Pick its family — the grouping every doc uses, and `FAMILIES` in the inventory test:
**system** (OS package managers + aur, rpm-ostree) · **distribution** (flatpak, snap, appImage,
tarball, native-pkg-file, source, font, script) · **config** (dotfiles, glue) · **module**
(language-ecosystem installers: cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install,
pyenv, sdkman) · **toolchain** (gcc, gcc-toolset, clang) · **primitive** (service, group). The
family predicts most answers below (a module installer needs a toolchain `requires:`, sits unranked,
has an `installed_index`, maybe a compaudit registry probe).

## 2. The class (configsys/drivers/<module>.py)

Subclass the closest shared base, set `name` (= the `via:` value), and register it in
`configsys/drivers/__init__.py` (`_REGISTRY` — the import + the dict entry; `BUILTIN_DRIVERS`
snapshots it). The bases (underscore modules = core-internal, not plugin ABI — a plugin driver
subclasses `Driver` only, §8):
- **`drivers._native.NativePkgManager`** — an OS package manager (§4): `INSTALL`/`REMOVE`/`UPGRADE`
  templates, `ENV`, `ensure_prereqs`, `packages:` + `installed-name:` handling (`_probe_name`).
- **`drivers._module.ModuleDriver`** — a language-ecosystem installer (cargo, pip, pipx, npm, gem,
  opam, luarocks, cabal, go-install, sdkman all are). State the mechanism as DATA — `TOOL`, `CMDS`
  (`{op: template}` with `{tool}`/`{pkg}`/`{ver}`/`{spec}`/`{scope}`), `VERSION_SPEC`,
  `SCOPE_FLAGS`, `LIST_CMD` + `parse_list(stdout)` (a `LIST_CMD` installs `installed_index` for you),
  `BIN_DIR` — and override only what is bespoke (`tool(rc)`, `placeholders(op, rc)`, `module(rc)`).
  PyPI names normalize through `_module.pep503_name`. Its generic `LIST_CMD` index returns `None` on
  ANY failure, a missing tool included — map exit 127 to `{}` yourself (the rule below).
- **`drivers._alt.AltDriver`** — a versioned toolchain slot (gcc, clang; gcc-toolset reuses its dnf
  path): versioned binaries at fixed paths, apt update-alternatives vs dnf compat packages.
- **`drivers._linked`** (functions, not a base) — a config-type driver that places content by
  symlink (dotfiles, glue): `link`/`unlink` own the rules (re-point only a link we own; anything
  else moves aside to the first free `<dst>.pre-configsys`, `.1`, … and is restored on unlink;
  `--pretend`-aware), and `SpecState` is the row its `spec_states` returns for the status views.
- **`Driver`** directly for anything else (the distribution family: tarball, appImage, flatpak, …).

**Class attributes** — each is documented in the `driver.py` docstring, and two are mirrored in
docs the inventory test compares against the code (as is the `installed_index` hook — Batching,
below):
- `privileged` (mutations need sudo) and `default_scope` (`user`/`system`).
- `honors_scope` — user/system selectable per binding → also listed in docs/config-format.md's
  `scope:` field bullet.
- `targets_version = False` when `set_version` can't reach an arbitrary version (a route-fixed
  artifact, a toolchain slot, no version at all) → the op loop refuses set-version up front
  (`actions.targets_version`); listed in CLAUDE.md's `set-version` sentence.
- `holds_version = False` for a rolling manager whose repo has only the current version and whose
  OS updater runs out of band (pacman, apk) — lock/set-version are declined and not offered.
- `native_backed = True` when installs register in the OS package database (aur, native-pkg-file,
  the gcc/clang alternatives) — so the orphan scan doesn't call them foreign.
- `trusted_registry = True` (+ `command_fields`) only for a driver that installs a package BY NAME
  from a registry the system already trusts (the native managers, flatpak, snap, brew): then an
  UNTRUSTED plugin layer's binding of it is still a candidate unless it sets one of
  `command_fields` (a repo, key, remote, debconf answer, `classic:` — anything that runs a command
  or widens privilege). Default `False`: the driver runs, builds or downloads code, and untrusted
  bindings wait for `plugin trust` (`trustgate.binding_needs_trust`; docs/plugins.md §6). A new
  field that adds a repo/key to a trusted-registry driver MUST join its `command_fields`.

**The nine ops** (`get_version`, `get_latest`, `is_locked`, `install`, `uninstall`, `upgrade`,
`set_version`, `lock`, `unlock`) plus usually `location`. Rules that bit us before:
- **Everything through `self.runner.run`** — that is what makes `--pretend` and the tests work. A
  driver that writes files itself (dotfiles, glue, tarball, appImage) must check
  `self.runner.pretend` before any write; `--pretend` is a full dry run (CLAUDE.md).
- **A write into a content root** (your primary plugin's `dotfiles/`/`glue/` tree) calls
  `self.will_write(path)` BEFORE writing — the primary's write journal commits exactly the announced
  paths (an unannounced write reads as your hand edit; test/test_primary_journal.py `WRITES`).
- **Read a binding's `installed-name:` with `self.installed_name(rc, driver=None)`** — it handles
  both the scalar and the driver-keyed map (`{ apt: …  default: … }`); hand-reading the field
  crashes on the map form.
- **Read ops return data; `None` = unknown, never a guess.** A version that isn't installed is
  `None`. Mutating ops return a `runner.Result`.
- **"Manager not installed" is a TRUE empty, not unknown.** When the tool itself is absent (the
  shell's exit 127), `installed_index()` returns `{}` and per-unit reads answer from that — not
  `None`, which makes the core fall back to a probe PER UNIT and spawn a missing binary hundreds of
  times on worker threads during the splash (brew, 2026-10: 168 failed spawns, a choppy splash).
  A manager that exists but fails stays `None`.
- **No `sudo` inside command strings** — pass `sudo=True` to `runner.run` (one auth, the tty
  handling in docs/principles.md). If the driver's commands sudo internally anyway (makepkg, a
  recipe's `sudo make install`), add it to `actions._INTERNAL_SUDO_DRIVERS` so a batch
  authenticates up front.
- **Shell-quote every interpolated value** (`shlex.quote`); a resolved version is network input
  (`_SAFE_VERSION_RE`).
- Lock semantics: a native hold where the manager has one (apt-mark, versionlock, `brew pin`);
  otherwise lock intent lives in the ledger and lock/unlock return an explanatory no-op Result.

**Optional hooks** (all frozen, all with working defaults — override what the mechanism can answer
cheaply; `installState.InstallState` drives them):
- **Batching** — `installed_index()` (one enumeration → `{key: version}`) + `index_key(rc)`, and
  `latest_index(names)` (every candidate in one query — the default `batch_index` carries it with
  `held_keys()`); or a custom `batch_index(rcs)` whose result the core stores on `self.batch`, read
  back with `batched_version(rc)` / `batched_latest(rc)` / `batched_held(rc)`. Any enumerable manager should batch: a subprocess per unit is what made
  startup slow (`InstallState._build_batch` runs each driver's batch once, concurrently). An `installed_index` override also puts the driver in the orphan
  scan — update the list in docs/orphans.md ("Today that means …").
- **Orphans** — `explicit_keys()` (user-installed vs auto-pulled), `origin_index()`.
- **System Updates** — `upgradable_index()`, `held_keys()`, `classify_index(keys)` (tiers from
  `UPDATE_TIERS`), `update_dedup_key`, `upgrade_all()`; docs/system-updates.md "Coverage".
- **Version signals** — `outdated_signal(rc)` (updates that don't change the version string —
  flatpak commits), `upstream_version(rc)`; plus `version_advisory(rc)`, which has no base default
  — the core looks it up with `getattr` (pipx).
- **Download helpers** for artifact drivers: `resolve_version`, `download_url`, `download_target`,
  `arch_token` (with `cpu-names:` — routing-model §7), `expected_sha256` / `verify_download` (a
  binding's `sha256:`), `download_failure`; install markers `marker_path` / `read_marker`. The full
  list of helpers a subclass may call is the `driver.py` docstring's "Helpers a subclass MAY call".

A NEW hook or class attribute on `Driver` is a plugin-ABI change: add it to the `driver.py` frozen
list, to `FROZEN_HOOKS` / `FROZEN_ATTRS` in test/test_abi_surface.py, and to docs/plugins.md §7a —
and prefer an existing hook. Underscore members are internal.

## 3. Routing (routes.hu `drivers:` + resolve.py)

- **`drivers: { <name>: { requires: … } }`** — what every binding of this via needs (the tool,
  its runtime: `cargo → cargo`, `pyenv → [pyenv, python-build-deps]`). This is also the driver's
  VALIDITY: the derived gate (`resolve.gated_context`) makes the driver a non-candidate wherever its
  requires can't be met, so never hand-write an OS gate that duplicates a requirement.
- **Explicit `when:` gate** only for facts that aren't requirements (`brew: when: "glibc_linux"` —
  Linuxbrew refuses musl even with gcompat; `aur: when: "arch"` — Void has base-devel too). It adds
  no specificity (routing-model §8a).
- **`standing: never-auto`** driver-wide if it must never be an automatic default (snap).
- **Preference** — either a slot in `DEFAULT_DRIVER_PREFERENCE` (then also a short tag in
  `tui.panes._DRIVER_ABBR`, the Config-screen display), or deliberately unranked (add it to
  `UNRANKED` in the inventory test, with the reason). A new rank changes defaults across the
  catalog: regenerate the golden and read the diff per OS before accepting it (§9). A user's or OS
  block's stale `driver-preference:` list still ranks a new driver: `resolve._effective_preference`
  chains the lists and the default, each adding only the drivers the earlier ones don't name.
  Unranked drivers tie with each other (and sit below every ranked one), so authors settle an
  overlap with a per-binding `standing:` rank — never a `when:`, which states validity only.
  Remember specificity is decided BEFORE preference (the aur `when: "arch"` exceptions).
- **Fields** — the binding fields the driver reads. `resolve._package` decides the package /
  display name per via (`name:`, `app:` for flatpak, nothing for config drivers); a new naming
  field goes there. Load-time checks for a via's required fields live in `routecheck.validate`
  (script needs its commands, tarball an `installDir:`).
- **Auto-derived attrs** — if every binding of this via implies a component kind, map it in
  `routes._VIA_ATTR` (dotfiles/glue/service/font/group do) and docs/component-attrs.md.
- **Command-carrying data** — if a binding's fields are shell commands (script, source, glue), the
  driver's ops gate on `command_trusted(rc)` and return `untrusted_command_result(rc)` when it isn't
  (defense in depth behind the resolution-time trust gate, §2 `trusted_registry`).
  `plugins._scan_executable_data` (what makes a data-only plugin trustable) derives from
  `trustgate.binding_needs_trust`, so it needs no per-via edit.

## 4. A native package manager (an `os:` block's `native:`)

Everything in §2–3, plus:
- Subclass `NativePkgManager` (INSTALL/REMOVE/UPGRADE templates, `ENV`, `ensure_prereqs` for vendor
  repos/keys); honor `name:` maps keyed by this driver (`resolve._package` picks the entry),
  `installed-name:` (`Driver.installed_name`, read through `_probe_name`) and `packages:` lists.
  Set `trusted_registry = True` and list every repo/key-adding field in `command_fields` (§2).
- The OS block (`native: <name>`) — the `/add-os` skill; the add-component matrix table; in
  `tools/osaudit.py` a facts snippet in `_FACTS` (keyed by manager) and, for each versioned line, a
  sweep setup in `_SETUPS` (keyed by line).
- **Required hooks** (the inventory test checks them): `installed_index`, `upgradable_index`,
  `upgrade_all`, `explicit_keys`. A gap you accept goes in `KNOWN_GAPS` there, with why.
- **A refresh style — exactly one of:** `cli.refresh._NATIVE_REFRESH`, an index-only refresh that is safe
  before a single-package install (apt-get update, xbps-install -S, …; it is also what the
  `refresh-before-execute` setting runs before an execute batch); or `cli.refresh._FULL_UPGRADE_REFRESH`,
  for a manager where an index-only sync breaks the next install, so the only safe refresh is the
  full system upgrade (pacman: a bare `-Sy` is a partial upgrade; `configsys refresh` asks first,
  nothing runs it automatically). Being rolling doesn't decide it — Void and Tumbleweed sync safely.
  `cli.refresh._INDEX_SRC_DIRS` if it has third-party source files whose failures `refresh` should diagnose
  (apt/dnf/zypper).
- **A reboot entry — exactly one of:** `rebootcheck._REBOOT_CHECKS` (the native reboot-required
  check: a flag file, a `needs-rebooting` exit code, or `_kernel_heuristic`), or
  `rebootcheck._NO_REBOOT_CHECK` with why there is none (brew). `_services` for restart-needed
  services, where the manager has a cheap native query.
- System Updates picks up the OS's native manager automatically (`sysupdates.machine_managers`);
  a CROSS-distro app manager (like flatpak/snap) goes in `sysupdates._APP_MANAGERS`.
- **A name-sweep entry — exactly one of:** `tools/namesweep.py` `MANAGERS` (plus its `_CHECK`
  existence verb and `_VERIFIERS` image + repo setup — `test/run-name-sweep-in-podman.sh` just runs
  it), or `namesweep.UNSWEPT` naming what checks the names instead (brew: compaudit's `probe_brew`).
  A `test/Containerfile.<distro>` + `run-<mgr>-in-podman.sh` / `integration_<mgr>.sh` for a
  real-install lifecycle.
- Stranded/orphans: `stranded._SKIP_VIAS` lists vias that are never an install method; an
  OS-specific heuristic for pre-receipt installs lives in stranded.py (the `pacman -Qm` AUR one).

## 5. Tests

- **`test/test_<module>_driver.py`** — the FakeRunner pattern (see test_sdkman_driver.py,
  test_brew_driver.py): every op's command, version parsing incl. "not installed", the batch path,
  missing-manager = `{}`, failing-manager = `None`, pretend. Watch needles: `tmp_path` contains the
  test's name.
- **test/test_driver_inventory.py** — add the driver to `FAMILIES`; to `UNRANKED` if unranked;
  native → the hooks/refresh/reboot/namesweep checks apply.
- **test/test_driver_injection.py** — runs automatically over every built-in driver: a component
  name carrying shell metacharacters goes through `install` and `uninstall` and must stay inside one
  shell word. If install builds no command from a bare name (it needs a url, content root or
  declared commands first), list the driver in `SHALLOW` with why.
- **test/test_pretend_sweep.py** catches a write that ignores `--pretend`, and
  **test/test_primary_journal.py** a primary write without `will_write` — both through the CLI verbs
  that reach the driver.
- test/test_abi_surface.py — only if you added a hook (§2).
- Routing: regenerate `test/routing_golden.json` (add-component §8) and diff it — a new driver
  with no bindings must change nothing; bindings that use it change only those components.

## 6. Docs and skills that enumerate drivers (the inventory test checks each)

- **README.md** "Concepts" → the hand-written **Driver** bullet: name the driver in its family group
  and bump the **"configsys ships N"** count (the inventory test reads this bullet). The
  docs/glossary.hu `driver` entry (→ README's generated Glossary, `tools/docaudit.py glossary
  --write`) doesn't enumerate drivers — touch it only if the definition itself changes.
- **CLAUDE.md** — the "Drivers are defined in code" paragraph (and the `set-version` sentence if
  `targets_version = False`, the architecture `drivers:` summary if it has a gate/requires worth
  stating).
- **docs/config-format.md** — the driver list under the binding fields (→ `tools/gen_manpages.py`
  regenerates configsys.hu(5)); the `scope:` bullet if `honors_scope`.
- **docs/orphans.md** if it has `installed_index`; **docs/system-updates.md** if System Updates
  hooks; **docs/routing-model.md** if it's ranked, gated or changes selection; **docs/plugins.md**
  only for a new hook.
- **.claude/skills/add-component/SKILL.md** — the "Driver catalog" entry (fields, when to reach for
  it) and, if it's a common fallback, a bullet in step 3; **update-component** — its checklist item
  6 (new/removed methods) if authors should start adding bindings for it.
- **tools/compaudit.py** — if the driver installs from a registry with a public API (crates, PyPI,
  npm, AUR, Homebrew, Flathub do), add a probe in `_probe_targets` + `run_probes` and a test in
  test_compaudit.py, and list its categories in the update-component skill.
- `.venv/bin/python tools/docaudit.py check` — 0 errors.

## 7. The hard-coded driver sets (decide each, explicitly)

| symbol | add the driver when… |
|---|---|
| `actions._INTERNAL_SUDO_DRIVERS` | its commands sudo internally though it isn't `privileged` |
| `actions._NO_POST_CHECK` | "not detected" right after a good install is legitimate (config drivers) |
| `ledger._NO_RECEIPT` | an install of it isn't an install METHOD of the component (no receipt) |
| `stranded._SKIP_VIAS` | same — never a method a component can be stranded on |
| `orphans.USER_FACING` | foreign (no-recipe) installs are deliberate user apps worth listing |
| `sysupdates._APP_MANAGERS` | it's a cross-distro app manager whose updates belong in System Updates |
| `routes._VIA_ATTR` | every binding implies a component kind (§3) |
| `resolve._package` | it names its package with a field other than `name:` (flatpak `app:`), or has none (dotfiles, glue) |
| `shellguard._OWN_DRIVERS` | it is a configsys config driver whose own rc-file writes are not "an installer scribbling" (dotfiles, glue) |
| `plugins._scan_executable_data` | nothing to add: it derives from `trustgate.binding_needs_trust` — set `trusted_registry` / `command_fields` instead (§2) |
| `versions._BUILTIN_KINDS` | it comes with a new `version:` source kind |
| `cli.refresh._NATIVE_REFRESH` / `cli.refresh._FULL_UPGRADE_REFRESH` / `cli.refresh._INDEX_SRC_DIRS` / `rebootcheck._REBOOT_CHECKS` / `_NO_REBOOT_CHECK` / `namesweep.MANAGERS` / `UNSWEPT` | native manager (§4) |
| `tui.panes._DRIVER_ABBR` | ranked in `DEFAULT_DRIVER_PREFERENCE` (§3) |
| `shellguard` (the guard itself) | nothing to add: install / upgrade / set-version / fix-scope of every driver outside `_OWN_DRIVERS` run inside the rc-file guard (`installer-shell-writes`), so an installer that edits rc files (sdkman, rustup) is caught there |
| `parity.py` | only if the driver brings a new CLI verb or TUI action — classify it (`CLI_VERBS` / `TUI_ACTIONS`; test/test_parity.py) |

Grep for any new ones before finishing: a quoted driver name outside configsys/drivers/ —
`grep -rn "'<name>'" configsys --include=*.py | grep -v drivers/`.

## 8. A plugin driver

A code plugin lists `DRIVERS = [MyDriver]`; the trusted loader calls `register_driver` before
resolution. It may use ONLY the frozen surface (`from configsys.plugins import Driver, Result,
register_driver, …`), never underscore members or other configsys modules. Its `drivers:` routing
block, docs and tests live in the plugin repo (examples: configsys-blender's and configsys-kicad's
build drivers). A plugin driver named like a built-in SHADOWS it (`BUILTIN_DRIVERS` — `check` /
`plugin list` surface that). It sits outside `DEFAULT_DRIVER_PREFERENCE` unless the user's
`driver-preference:` names it. Core's tables in §7 don't know it; `actions._may_need_root` assumes a
plugin driver may need root. Changes need `configsys plugin sync` + `plugin trust` to take effect.

## 9. Validate and commit

```
.venv/bin/python -m pytest test/test_driver_inventory.py test/test_<module>_driver.py test/test_abi_surface.py -q
for o in pop fedora arch alpine opensuse rhel fedora_atomic void void_musl kde_linux; do
  .venv/bin/python -m configsys --home <scratch> --os $o check | tail -1; done      # 0 errors, warnings not up
CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py -q        # then diff vs HEAD (add-component §8)
.venv/bin/python tools/docaudit.py glossary --write && .venv/bin/python tools/gen_manpages.py
.venv/bin/python tools/docaudit.py check
.venv/bin/python -m pytest test/ -q
```
A real install in podman when the driver touches the system (§4's scripts). Commit locally — never
push — with the identity and trailer in add-component §10; plugin-repo changes are a separate commit.

**Renaming or removing a driver** is the same list in reverse, plus: users' `pins:`,
`driver-preference:` and `disabled-drivers:` may name it (a retired-name warning, like
`routes.RETIRED_STANDING_KEYS`, beats a silent break), and ledger receipts record the old via.
