# configsys

Configsys is a single tool for setting up a new operating system installation and account from a config and TUI application. The notion is that not only are dotfiles able to be synchronized across systems (via a remote git repository) but that, whether the system is linux, unix, or macos, we are able to, from a TUI tool and bash, choose per machine which components to install and quickly sync os-native packages, appImages, flatpaks, SDKs, distributed binaries, or other means of software distribution. We want total control over updating, version locking, and removal of any such component, and to be able to easily modify the config and routes files to further refine the (relatively) uniform setup. (As built, only Linux is modeled: every `os:` block descends from `linux`.)

## Architecture

Every system we care about either comes with a version of python3, or that must be the first requirement of the system. Additionally, there is a python library in PyPI called humon, which we can use as well (see skill). From there, we are able to read and use routes.hu and config.hu to:
- determine, depending on the OS, the install/update driver for a component
- determine the installation state (whether installed, what version, is it latest, is it version-locked) of a component
- install a component to latest version
- change a component to a particular version or upgrade to its latest
- lock / unlock a component version

The application should be python3, and so python3 and humon must be the first to synchronize; this can be done via bash, since we need these components for the rest of the app. The app should be an interactive TUI, and slick looking on a 24-bit RGB terminal. It should be menu-driven, with single-key actions and menu navigation via VIM-like controls.

On start, the user config (`~/.config/configsys/configsys.hu`, i.e. `$XDG_CONFIG_HOME/configsys/` —
the state dir that also holds the ledger `state.hu` and the synced `plugins/`; `CONFIGSYS_CONFIG` /
`CONFIGSYS_STATE_DIR` / `CONFIGSYS_HOME` override) must exist: `Context._migrate_user_config` moves a
legacy `~/configsys.hu` there, else `Context.ensure_user_config` writes one from
`app.USER_CONFIG_TEMPLATE` (an interactive first run also offers to bless a primary plugin). What a
machine installs is its **picks**: `picks:` is a component × machine matrix (`{ <machine>: [
components ] }`, merged repo < primary < user, a higher layer replacing a machine's whole list) and
`machine:` names this box's column (default `this-machine`; top config only —
`layers.TOP_CONFIG_ONLY`). The install set (`Config.requested()`) is exactly this machine's picks;
**profiles are read-only browse lenses**, never an install set (definable in any layer, the top
config included; `+include` / `~remove` / `+self` term algebra; `profile:<name>` on CLI ops skips
members with no route here with a notice, while a named component still errors). The retired
`configs:`, `machines:` and `orphans-adopt-target:` each raise a `check` warning
(`layers._RETIRED_TOP_KEYS`). `picks` is uniform-nature (edits land in the primary plugin when one is
blessed, else the top config); `dispositions:` (seen/interesting triage) and `uninstall:` (staged
removals, top config only) are machine-local side-stores (docs/config-format.md "Picks: what a
machine installs"). For each
picked component the app finds what is installed and evaluates versions. From that known state, an
interactive menu lets the user:

- view the install state of each component
- interactively mark installed components for an operation (upgrade, remove, etc)
- quickly mark all components for an operation (select all)

**TUI (configsys/tui/; docs/tui-architecture.md).** Seven screens on keys 1–7: Components (this
machine's picks as a tree with state/versions, plus the System Updates group), Profiles (the
component × machine matrix), Plugins, Glue, Dotfiles, Config (settings; `m` moves one local ⇄
primary), Theme. vim navigation, `/` find, `F` filter, `!` issues (`check`'s lints join it on a
background thread), `?` help; on Components ops are staged (`i`/`u`/`x`/`L`, `v` pick method, `w`
where) and `X` runs everything staged after a confirmation (`I`/`U` skip locked units; a row's
`x`/`L` act on its own units, never on dependencies it shares; under `--machine <other>` Components
is read-only). Every key: the `?` pages (`tui/help.py`) / README "The TUI". `tui/menu.py` is only
the router (`run`, `_route_key`); paint, modals, help, models (the Components `MenuState`), panes,
preview, flows and startup are siblings, and `menu.<name>` still resolves each moved name (PEP 562
`__getattr__` over `menu._MOVED`; in-package code imports the defining module). Each screen is a `Screen` (configsys/tui/screens/,
contract in `screens/base.py`): `build_vm(ctx, size)` (pure) → `draw(surface, pal, vm)` (paints
only; what the geometry settles goes through `vm.settle(...)`) → `commit(vm)`, the three run by
`Screen.render`; `handle` returns an `Intent` for the router; everything paints through a `Surface`
(`BufferSurface` = headless render tests). Keys are rebindable via `keys:` (tui/keyspec.py): a
screen's own scope is consulted FIRST, even over the router actions (`keyspec.ROUTER_ACTIONS`);
cross-layer steals and a page left with no quit key are `check` lints (docs/config-format.md "theme
and keys"). Color depth (`--color`, `NO_COLOR`) and motion (`effects:`, auto-reduced over SSH)
degrade gracefully; the startup splash is a pluggable provider (`splash:`).

**CLI (configsys/cli/; the argparse tree is `cli.parser.build_parser`).** `app.py` keeps the
`Context` (the pipeline every command and the TUI share: detect the OS → load layers + routes →
resolve this machine's picks → inspect) and `main` (dispatch through `app._COMMANDS`); each verb
family is a cli/ module — ops (inspect, install/remove/upgrade/lock/unlock/set-version/fix-scope,
updates, uninstall, tui), matrix (picks/machine/profile/disp/pin/orphans), where
(where/location/versions/search), check, plugin, refresh, settings (config/theme/keys/show/
manpages), dotfiles (dotfiles/glue), issues (report/request/request-os), common, parser — and
`app.<name>` still resolves every moved name (PEP 562 `__getattr__` over `app._MOVED`). No command
(or `tui`) = the TUI (`inspect` output when not on a terminal); the command catalogue is README
"Commands" / `configsys --help`. The CLI and the TUI share one plan path: `actions.resolve_targets`
(through auto-tighten + the detection tier, so an op acts on the install you have),
`actions.build_plan` (folds in only MISSING dependencies — `--with-deps` / `--no-deps` — plus the
method-switch swap), `actions.run_plan` (an explicit op on a locked unit is refused, a bulk one
skips it, remove clears the lock). Global `--pretend`, `--os BLOCK[:VERSION]` (`osdetect.settle`;
an unknown block errors), `--home` (a full sandbox: children run with `HOME=<sandbox>` and no
`XDG_*_HOME` — `runner.sandboxed_env` — and an inherited `CONFIGSYS_STATE_DIR`/`CONFIGSYS_CONFIG` is
dropped), `--machine` (curate another machine's column; installs act only on this box), `--config`.
`set-version` refuses up front on a driver whose class attribute `targets_version = False` (tarball,
appImage, font, native-pkg-file, aur, rpm-ostree, gcc/clang alternatives, gcc-toolset, glue,
dotfiles, service, group — `actions.targets_version`). **`--pretend` is a full dry run**: the runner
echoes instead of executing and nothing is written (every side effect it suppresses:
docs/principles.md "Safety"). Any new write path must honor `ctx.runner.pretend` —
`test/test_pretend_sweep.py` runs every mutating verb under --pretend against a populated sandbox
home and fails on any file change (add a new verb to its `VERBS`), and
`test/test_tui_pretend_sweep.py` drives every screen action key through `Screen.handle` the same way.

In the repo, routes.hu is a **capability/component model** (the full spec: `docs/routing-model.md`).
Its sections:
- `os:` — the OS layer (routing-model §6): `using` inheritance (pop_os! -> ubuntu -> debian ->
  glibc_linux -> linux; fedora/rhel -> redhat -> glibc_linux; arch, opensuse, void, fedora_atomic,
  kde_linux -> glibc_linux; the musl blocks alpine, chimera, void_musl -> linux directly — so a
  Void-wide gate is `void or void_musl`), the package manager each block declares `native:`
  (apt/dnf/pacman/zypper/apk/xbps/brew — brew is fedora_atomic's native, elsewhere on glibc an
  ordinary `via: brew`; the **native-less** kde_linux and chimera declare none, so `via: native`
  isn't a candidate there), `scale-root:` version markers, `provides:` (the environment's baseline
  capabilities: `linux` provides python3, `glibc_linux` glibc), and optional `detect:`
  (osdetect.py), `driver-preference:` and `advisory:`; the block owning a version line carries
  `releases:`, the release registry (maintenance data swept by `tools/osaudit.py`, linted by `check`
  as `os-release`; the resolver reads only a derivative release's `base:`, so `ubuntu >= 24.04`
  reaches Zorin 18 / Mint 22).
- `drivers:` — per-driver config: inherent `requires:` (closed for every binding of that via, e.g.
  appImage->[libfuse2, glibc, curl], brew->homebrew), an optional driver-wide `standing:` (snap ships
  `never-auto`), and **driver gates**, validity-only (routing-model §8a): DERIVED — a driver is valid
  only where its own `requires:` can be met (`resolve.gated_context`, reading HARD pins only, so
  `pins: { glibc: gcompat }` opens appImage on Alpine) — and EXPLICIT, a driver-wide `when:` for a
  fact that isn't a requirement (brew `glibc_linux`, aur `arch`). Both apply to a `via: native`
  binding that reaches that manager, neither adds specificity, and `where` names the reason
  (`resolve.driver_gate_reason`). Merged across every layer, the top config last — except an
  ordinary plugin's preference knobs on an entry a lower layer defined, ignored with a
  `plugin-preference` warning (routing-model §10b).
- `facets:` — detected machine traits beyond OS/cpu, usable as `when:` atoms (`gpu:nvidia`;
  docs/facets.md); a `detect:` probe carries a command, so a plugin's facets merge only when trusted.
- `components:` — each is a named **capability** plus an `install:` list of context-selected
  **bindings** `{ via: <driver>  when: "<expr>"  ...details }`. `via: native` resolves to the OS's
  package manager (name defaults to the component's; a driver-keyed `name:` map with `default:`;
  `installed-name:` takes the same shape, read through the frozen `Driver.installed_name`). `when:`
  is a boolean DSL (predicate.py) over OS atoms (bare = subtree membership; versioned e.g. `ubuntu <
  23.04`), `cpu:` and facets, with `and`/`or`/`not`. **`when:` states VALIDITY ONLY** (does this
  method work here), never preference. A binding is a **candidate** (`resolve._matching`) when its
  `when:` holds, its driver isn't in `disabled-drivers:` (for `via: native`, nor the manager it
  reaches) or gated out, it passes the trust gate (below), it covers this cpu (`cpu-names:` / a
  cpu-keyed `asset:` — validity WITHOUT specificity, unlike a `when: cpu:` clause), and it isn't
  `via: native` on a native-less OS. The default among candidates (`resolve._select`; callers ask
  `Resolver.select` under the machine's `SelectionPolicy`): drop `standing: never-auto` methods
  unless every candidate is one -> most-specific comparable `when:` -> per-binding `standing:` rank
  (a narrow author signal, so it outranks the machine order) -> `driver-preference` (default
  `resolve.DEFAULT_DRIVER_PREFERENCE` = native, aur, flatpak, snap, native-pkg-file, appImage, brew,
  tarball, source, script; a FALLBACK CHAIN of OS-block lists, then the setting, then the default —
  `resolve._effective_preference`); a remaining tie is an error naming the preference channel (never
  `when:`); a user binding-pin overrides. **`standing:`** is the ONE preference knob (on a binding,
  a `drivers:` block, or a component): `never-auto` = valid+listed+pinnable but never the
  auto-default (on a component-provider: never auto-pulled to satisfy a `requires:`); an INTEGER = a
  rank, higher wins (on a component it ranks a capability's providers — `resolve._pick_provider`;
  an equal top rank is an ambiguity error). The old `prefer:`/`candidate-only:`/`opt-in:` are
  retired (`routes.RETIRED_STANDING_KEYS`). A versioned capability adds `provides: { cap: N }` +
  `requires: { cap: ">=N" }` (routing-model §11, docs/versioned-requires.md). Two bindings of the
  SAME `via:` that overlap incomparably are a load-time error (`routecheck.check_component`);
  different-`via:` overlap is a legal multi-method choice decided by preference. A component may
  also declare `provides:`/`requires:`/`suggests:` (capabilities; `requires:` is HARD, `suggests:`
  SOFT — pulled in if resolvable, skipped silently if not), `parts:` (a pure aggregator, no unit of
  its own), `standing:`, `description:` and `attrs:` (kind tags; docs/component-attrs.md) — any
  other key is a load error. Config and shell setup are ordinary companion components the component
  `suggests:` — `<name>-dotfiles` (a `via: dotfiles` binding) and `<name>-glue` — there is no
  special dotfiles field.

Any layer may also patch without redefining a component: `component-names: { <driver>: { <comp>:
<pkg> | {} } }` (per-driver package name, `{}` = none there; routing-model §10a) and
`version-floors:` (sets an existing `requires:` floor by layer precedence; never adds one;
docs/config-format.md).

Resolution (resolve.py; the app runs `resolve_resilient`; routing-model §9) is a worklist to a
fixpoint over one fixed machine context: seed the wanted components + what they provide, close
`requires` (component, driver and binding level) and pull resolvable `suggests`, reusing
existing/env-provided providers; no backtracking (unmet HARD require / ambiguous providers = error);
dedup by unit key; a provider never satisfies its own requirement (`_self_held`). A `never-auto`
provider is used only when explicitly wanted, required by its own name, version-constrained, or
provider-pinned. `resolve_resilient` collects per-pick errors (`Context.resolve_errors`) and prunes
units whose hard requirement failed, so one bad pick is an error row, not a brick. Only the load
pipeline's resolve (`record=True`) writes the shared Resolver's per-resolve state; every other
passes `out=`. Loading is memoized (`routes._VALIDATED`; the specificity grid in
`<state>/grid-memo.json`). **Pins** (binding-pin component->via, provider-pin
capability->provider; one flat namespace, `resolve.pin_via_names`) are a filter, not a suggestion
(an unrealizable pin is an error) — merged per key repo < primary < user, edited with `configsys pin
set|unset|list|promote` (`actions.validate_pin`, shared with the TUI picker). Effective order: user
pins > opt-in `auto-tighten:` floor pins > detected-installed soft pins (`detection.detect_pins`,
`adopt-installed:`) > reuse > auto default (routing-model §10). A user pin that misses a floor
auto-tighten would fix raises a `pin-floor` warning (`flooradvise.advise`); a soft pin that can't be
honored is dropped, never an error (`Resolver.dropped_soft_pins`). The result `{unit_key: Unit}`
(`driver\comp`) maps through `adapt.to_resolved_components` onto `{unit_key: ResolvedComponent}`,
which the drivers consume unchanged.

The user file overlays the repo section by section: machine settings (`picks:`/`machine:`/`scope:`/
`pins:`/`driver-preference:`/`disabled-drivers:`/`dirs:`/`locations:`/… — THE registry is
`configsys/settings.py`: one `Setting` row per setting (kind, nature, choices, top_only, routing,
layout, getter, editable), from which `layers.MACHINE_SETTING_SECTIONS` / `SETTING_CHOICES` /
`TOP_CONFIG_ONLY` / `BOOL_SETTINGS` and `actions.CONFIG_SETTINGS` / `SETTING_NATURE` derive, so a
new setting is one row; `config show|get|set|unset|move` edit every `editable` row; one bool dialect,
`layers.parse_bool`; every file parsed through `layers.read_tree`; read only from the
repo/primary/user layers, `config._MACHINE_ROLES`; an edit routes by nature — uniform → the primary
plugin when blessed, machine → the local top config, and `config move` / TUI Config `m` carries one
across — docs/config-format.md "Where a machine-setting edit lands"), `components:` (route
overrides: bindings merge ADDITIVELY across layers by `(via, when)` identity,
`routes._merge_component_chain` — add a method, override a matching binding, `drop:` one, or `{}`
removes the component; to merely choose an existing method, pin it), `profiles:`, `os:`/`drivers:`
(highest precedence), `facets:` (in the top config a value map, not probe specs), and the cosmetic
`theme:`/`keys:` (merged from every layer). `configsys where <component>` explains a component's
source layer + resolution (every candidate, the default, the deciding rule); `configsys check`
lints the whole merged config.

**Layer stack (configsys/layers.py).** Every config/routes file is a LAYER (role repo / plugin /
primary / user / include); a file may `include:` others (relative to the including file; a leading
`~` expands against the configsys home, so `--home`/`CONFIGSYS_HOME` apply). Layers overlay
lowest-first — repo (routes.hu + config.hu, the shipped profile catalog + default `keys:`) < plugins
< primary < the top user file, includes sitting below their includer — merging by section and, for
components/profiles, by name. **The uniform layer rule:** every layer may DEFINE (components,
profiles, os blocks, drivers; facet probe specs still need plugin trust); only the top config and
the primary plugin may SET machine settings — an include or a non-primary plugin that sets one is
ignored with a `check` / `!` warning (`layers._forbidden_by_role`). An include of a root layer is
ignored and a plugin's includes stay inside its checkout (routing-model §10b). A bad plugin/primary
file is skipped with a warning, a bad repo/user file is loud (`layers.expand_tolerant`). Every
section edit configsys makes to a `.hu` file (`plugins.set_section` / `remove_sections`) is
re-parsed before it is written and refused, file untouched, if anything besides that section would
change (`plugins._checked_write`). Provenance (`Component.source`, `Config.profile_source`) flows
through so `where`/`check` attribute to the right file. A plugin is just another source in the
stack.

**Plugins (configsys/plugins.py; docs/plugins.md).** `plugins: [ { source: "github:x/y"  ref: v1 } ]`
(also `gitlab:`, a git URL, a local path / `file:`; optional `sha256:`) in the top config; `configsys
plugin sync` clones each to `~/.config/configsys/plugins/<name>/` at the pinned ref (git via the
runner), and a manifest (`plugin.hu`) may declare further `plugins:`, synced transitively. Its `.hu`
data files become `plugin`-role layers (components, profiles, drivers AND os blocks). Unsynced /
ABI-incompatible (`requires-abi` vs `ABI_SUPPORTED`) / sha256-mismatched (quarantined) / malformed
plugins are skipped, never fatal. A clone holding work configsys would lose
(`primarygit.local_work`) is never deleted without `--force`. `plugin add <source> --local` makes a
**machine-level plugin** — a non-primary top-config entry that applies to this box only (the
replacement for the removed CWD `.configsys.hu` discovery; docs/plugins.md §9).

**The primary plugin** (`primary: true`, granted only by the top config — `plugin bless`) is the
user's portable personal layer: last among plugins, may set machine settings, where `plugin add`
writes by default; it FOLLOWS A BRANCH (normally `main`), never re-pinned to a tag by default.
configsys COMMITS its own edits to it from a WRITE JOURNAL (`primarygit`): every configsys writer
into the primary calls `primarygit.will_write(path)` BEFORE writing (a code plugin's driver: the
frozen `Driver.will_write`) — a new writer must too; `test/test_primary_journal.py` `WRITES` fails
until it is — and `commit()` commits exactly the recorded paths that changed (never your hand edits;
nothing on a detached primary or under --pretend). Every git call goes through
`primarygit.PrimaryRepo`; `.hu` files merge structurally (`humerge`, git's merge driver for that one
command only); humon TEXT surgery is ONE module, `configsys/hutext.py`. Publishing (`plugin push` /
Plugins `P`: one undoable combine, every question a `primarygit.Question`), the `primary-push`
modes, the ↑↓● state, `primary-verify: signed` (top config only) and `plugin log` / `plugin undo`
→ docs/plugins.md §8 (behavior) and §8a (how it is built).

**Trust (`trustgate.py`; docs/plugins.md §6).** Code plugins (a manifest `code:` module exporting
`DRIVERS` / `SPLASHES`, plus `register_version_source` / `register_transport`) load only when
trusted at their exact content hash (`configsys plugin trust`, `plugins.plugin_identity`,
`plugin-trust.hu`; a `code:`/`data:` entry resolving outside the checkout never loads). **The trust
gate:** an UNTRUSTED plugin layer may define anything, but `resolve._matching` makes its binding a
candidate only when the driver is a `trusted_registry` (native managers, flatpak, snap, brew — a
package by name) and the binding sets none of the driver's `command_fields` and no
`version: { url: }` — every download/build/script/glue/dotfiles/service/group binding waits for
trust (`routes.load` → `ctx.untrusted_sources`; a new field that adds a repo or key to a trusted-registry driver MUST
join its `command_fields`). `run_plan` re-checks each step (`actions._layer_may_run`) and receipts
record their source; an untrusted plugin's `facets:` `detect:` probes and `keys:` are dropped
(`plugins.command_source_trusted`). Your primary follows the top-config-only `primary-trust:`
(`identity` default / `content` / `signed`) for its data and code alike. Root-written vendor paths
are confined (`routecheck.vendor_path_problem`), downloads may carry `sha256:`
(`Driver.verify_download`), version fetches are https-only. Review + lock (`plugin diff`, `plugin
lock`; `actions.plugin_review_plan`, `plugin-locks.hu`): docs/plugins.md §6a.

**Stranded installs (configsys/stranded.py; docs/stranded-installs.md).** When routes stop offering
a component's installed method, it reads `switch` (installing it runs the method swap, removing the
old install), `unmet` (routable only with a disabled driver back on) or `dangling` (no method left
here; never removed for you). Installs stay findable through the install RECEIPT the ledger
(`ledger.py`, `state.hu`) records on every successful install/upgrade/set-version (none for
dotfiles/glue).

**System Updates (configsys/sysupdates.py; docs/system-updates.md).** Everything the OS reports
upgradable OUTSIDE the picks, from each manager's own `upgradable_index` (rpm-ostree omitted), tiered
kernel/core/standard/apps (`classify_index`) and applied by each manager's `upgrade_all`: `configsys
updates`, `upgrade --system`, the TUI's System Updates group. Within-release only; never modeled as
components (docs/principles.md).

Drivers are defined in code (configsys/drivers/, base class configsys/driver.py — the frozen plugin
ABI) behind a uniform op set: get_version, get_latest, is_locked, install, uninstall, upgrade,
set_version, lock, unlock, location — plus the optional hooks (batched `installed_index` /
`batch_index` / `latest_index`, the orphan-scan and System Updates hooks, `outdated_signal`) and the
helpers a subclass may call (`will_write`, `installed_name`), all in the FROZEN list of the
`driver.py` docstring, pinned by test/test_abi_surface.py with the splash ABI; underscore members
stay internal (docs/plugins.md §7a). An `installed_index` of None means "can't tell" (per-unit
probes follow); a manager that isn't installed at all answers a true `{}`. Shared bases:
`drivers/_native.NativePkgManager` (apt/dnf/pacman/zypper/apk/xbps), `drivers/_module.ModuleDriver`
(the ten module installers: TOOL / CMDS / VERSION_SPEC / SCOPE_FLAGS / LIST_CMD as data, overriding
only what is bespoke), `drivers/_alt.AltDriver` (gcc/clang alternatives, gcc-toolset). Every `rm
-rf` / move-over of a component's own directory goes through `Driver.unsafe_dir_reason` /
`replace_dir_refusal` (never a system tree, a shared dir or the home; a dir configsys didn't install
needs `--force`; and never `rm` a path derived from `$HOME` — docs/principles.md). Each `via:` value
names a Driver 1:1: the OS package managers apt, dnf, pacman, aur, zypper, apk, xbps, brew,
rpm-ostree; tarball, native-pkg-file (an upstream release's .deb/.rpm installed with the OS package
tool — its own via, since it doesn't ride `apt upgrade`), flatpak, snap, appImage, font, script
(declared commands), source (a declarative build; only in a tree it cloned or one you `install
--adopt`ed, and `remove` deletes only a clean tree it created); the config drivers dotfiles (an
app's own config: a `.cfs` store dir + manifest, linked into place) and glue (per-shell `conf.d`
snippets in load-order bands, the `configsys-glue` preludes, user glue, the shell-writes guard —
docs/shell-glue.md), both placing links only through
`drivers/_linked.link`/`unlink`, which move whatever they displace to `.pre-configsys[.N]` and never
overwrite; the language toolchains and their module/version installers cargo, pip, pipx, npm, gem,
opam, luarocks, cabal, go-install, pyenv, sdkman, gcc, gcc-toolset, clang; and the post-install
primitives service (systemd or runit) and group (usermod) — except `via: native` (resolves to the
OS's package-manager driver) and `via: parts` (a pure aggregator, no driver of its own). Each native
manager (an `os:` block's `native:`) is also declared in exactly one map of each pair, never exempted
by name: its refresh style — `cli.refresh._NATIVE_REFRESH` (index-only, so also run before a batch
per `refresh-before-execute`) or `cli.refresh._FULL_UPGRADE_REFRESH` (pacman: only a full `-Syu` is
safe, which `configsys refresh` asks before running and nothing runs automatically); its reboot
check — `rebootcheck._REBOOT_CHECKS` or `_NO_REBOOT_CHECK` {manager: why none}; its name sweep —
`namesweep.MANAGERS` or `UNSWEPT` {manager: what checks the names instead}. More drivers can be added
in core or by a trusted code plugin (playbook: `/add-driver`, enforced by
test/test_driver_inventory.py; `register_driver`).

Every command runs through `runner.Runner.run`, with an activated Python virtualenv dropped from its
env (`runner.child_env` — else `python3` is the venv's, pip `--user` refuses and pipx's apps read
uninstalled); a streamed child that already started is never re-run when the relay fails
(`runner.ChildStarted`). The brew driver finds `brew` off PATH in Homebrew's standard prefixes
(`drivers/brew.brew_env`, appended — a same-batch `homebrew` install isn't on the process's PATH),
and `homebrew-glue` puts that prefix on your shells' PATH after the system's.

(History: routes.hu replaced a `\family`-blocks + OS-cascade + wildcard model in place, proven
byte-equivalent before the flip; `test/routing_golden.json` freezes the resolution as a regression
gate.)

The bash bootstrap (configsys.sh) is minimal: resolve its own symlink to find the repo, export
`CONFIGSYS_INVOKED_CWD` (the app changes back to it, so relative CLI paths mean your directory), take
a fast path when the `.venv` is healthy, else find python >= 3.10 (`$PYTHON`, else the first of
python3, python3.14 … python3.10) — it stops with a message rather than install one, the one
exception being apt's `pythonX.Y-venv` — then create/repair `.venv` under a flock, install
pyproject.toml's `dependencies` (`humon` + `packaging`), and `exec .venv/bin/python -m configsys`;
under `CONFIGSYS_NO_BOOTSTRAP` (a shell start) it never repairs, exiting 75. Everything else is
python. (pyproject.toml can build a `configsys-cli` wheel — PyPI's `configsys` is taken — but it is
unpublished; the project runs clone-first.)

## Docs and maintenance tooling

- `docs/` holds living reference specs (routing-model.md, config-format.md [the source of
  configsys.hu(5)], plugins.md, principles.md, facets.md, shell-glue.md, stranded-installs.md,
  theming.md, component-attrs.md, system-updates.md, orphans.md, tui-architecture.md,
  versioned-requires.md, …); `docs/todo/` = unfinished plans; `docs/done/` = finished or
  superseded plans (dated header, historical body); `docs/history/` = a separate archive;
  `docs/INDEX.md` records every doc's location, status and dates.
- `docs/glossary.hu` is the canonical vocabulary (it generates README's Glossary; its `retired:`
  terms are flagged by `tools/docaudit.py check`). The `/update-docs` skill + `tools/docaudit.py`
  keep every doc true; man pages are generated by `tools/gen_manpages.py` (configsys.1 from
  argparse, configsys.hu.5 from docs/config-format.md).
- `/add-component` and `/update-component` (+ `tools/compaudit.py`, cached upstream probes) are the
  playbooks for adding and auditing components; `/add-driver` is the checklist for a new `via:`
  driver (the class contract, routing placement, the hard-coded driver sets, every doc that lists
  drivers); `tools/namesweep.py` (+ `test/run-name-sweep-in-podman.sh`) checks native package names
  exist per distro in podman containers (brew has none — `namesweep.UNSWEPT`; `compaudit`'s
  `probe_brew` checks formulae against formulae.brew.sh).
- `/add-os` (a new distro / derivative / environment: lineage, numbering, detection, its release
  registry) and `/update-os` (a new or pre-release of a known line, plus re-verifying every live
  older one with `tools/osaudit.py`, per-release podman name sweeps and driver-lifecycle harnesses;
  EOL releases frozen, not swept). Run `/update-os` before `/update-component`.
- `/review-code` is the full code review (the 2026-09 review made repeatable): one reviewer per
  area of `.claude/skills/review-code/areas.hu` (+ cross-cutting security and CLI/TUI parity), an
  adversarial checker for every serious finding, `/update-os` then `/update-component` (report
  only), a dated `docs/review-YYYY-MM/` with ranked tiers whose `[open]`/`[done <commit>]` tags are
  its ledger, the user's chosen fixes applied test-first, then `/update-docs` last.
  `tools/reviewaudit.py coverage` lists files no area owns. The latest full run is
  `docs/review-2026-11-2/`.
- Tests (`.venv/bin/python -m pytest test/…`) are HERMETIC by default (`test/conftest.py`
  `_hermetic`): a temp `HOME`, `CONFIGSYS_*`/`XDG_*` scrubbed, git config isolated, a failing fake
  `sudo` first on PATH, `Runner.run` refusing to execute unless the runner is `--pretend` or the
  test is `@pytest.mark.real_runner`, and no network unless `@pytest.mark.network`. Shared doubles
  (`FakeRunner`, `git`, `primary_remote`) live in `test/fakes.py`. Inventory tests fail until a new
  thing is wired in: `test_driver_inventory.py` (a driver), `test_pretend_sweep.py` `VERBS` /
  `test_tui_pretend_sweep.py` (a write path), `test_primary_journal.py` `WRITES` (a primary
  writer), `test_abi_surface.py` (the frozen ABI), and `test_parity.py` — `configsys/parity.py`
  classifies every CLI verb and TUI screen action (its counterpart, `cli-only:`/`tui-only:` with
  why, or a named `tui-gap:`), so a new verb or key needs a row; `test_cli_verbs_main.py` drives the
  verbs through `main`, `test_golden.py` holds resolution to `test/routing_golden.json`.

## Some considerations

The load-bearing, cross-cutting principles (safety rules, routing invariants like "`when:` is
validity not preference", the "no surprises" posture, what we deliberately don't model) live in
`docs/principles.md` — read it before making a decision that touches those axes.

User should have control of what each machine picks; profiles are a browse aid, not the install set. Components that are wanted from several directions (picks, requires, suggests) shouldn't be doubled up; a conflict (ambiguous providers, equally-preferred methods) is an error the user is told to fix — an error row plus a `check` / `!` issue, never a silent guess — while the rest of the picks still resolve. In general, take a posture of 'no surprises'; user should know what's installed, what's going to be when they do an operation, and what's not. However, user does not need all details about package dependencies in apt, for example.
