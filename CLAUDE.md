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

On start, the user config file (`~/.config/configsys/configsys.hu`, i.e. `$XDG_CONFIG_HOME/configsys/` — the state dir that also holds the ledger `state.hu` and the synced `plugins/`; `CONFIGSYS_CONFIG` / `CONFIGSYS_STATE_DIR` / `CONFIGSYS_HOME` override) must be present: `Context._migrate_user_config` moves a legacy `~/configsys.hu` there, and if it is still absent `Context.ensure_user_config` writes one from `app.USER_CONFIG_TEMPLATE` (an interactive first run also offers to bless a primary plugin). What a machine installs is its **picks**: `picks:` is a component × machine matrix (`{ <machine>: [ components ] }`, merged repo < primary < user, a higher layer replacing a machine's whole list) and `machine:` names which column this box is (default `this-machine`). The install set (`Config.requested()`) is exactly this machine's picks — **profiles are read-only browse lenses** (definable in ANY layer, the top config included — a user's `profiles:` are their own browse categories, never an install set; `+include` / `~remove` / `+self` term algebra; `configsys profile list|show`, the TUI Profiles screen, `profile:<name>` expansion on CLI ops, where members with no route here are skipped with a one-line notice while an explicitly named component still errors). The old `configs:`, `machines:` and `orphans-adopt-target:` are RETIRED (each emits a `check` warning — `layers._RETIRED_TOP_KEYS` via `layers.unknown_section_warnings`). `configsys picks add|rm|list|to-primary` and `configsys machine list|show|add|rm|use` (+ the global `--machine` working-target flag) edit the matrix; `picks` is uniform-nature, so edits land in the primary plugin when one is blessed, else the top config. `dispositions:` (seen/interesting triage) and `uninstall:` (staged removals) are machine-local side-stores. For each picked component the app searches the system to find what is already installed and evaluates versions. From that known state, an interactive menu lets the user:

- view the install state of each component
- interactively mark installed components for an operation (upgrade, remove, etc)
- quickly mark all components for an operation (select all)

**TUI (configsys/tui/).** Seven screens on keys 1–7: Components (this machine's picks as a tree
with state/versions, plus the System Updates group), Profiles (the component × machine matrix:
track `t`/`T`, claim `C`, dispositions, stage uninstall `x`), Plugins, Glue, Dotfiles, Config
(settings; `m` moves one local ⇄ primary), Theme. vim navigation (`j/k/h/l`, `g/G`), `/` find,
`F` filter, `!` issues, `?` help; on Components stage `i`/`u`/`x` (`I`/`U` for all, `a` select-all,
`v` pick method, `L` lock, `w` where — also on Profiles), then `X` runs everything staged after a
confirmation. Each screen is a `Screen` (build_vm / draw / handle in configsys/tui/screens/)
painting through a `Surface` (`BufferSurface` = headless render tests). Keys are rebindable via
`keys:` (tui/keyspec.py): a screen's own scope is consulted FIRST, even over `q`/`!`/`?`/screen
numbers (router actions `keyspec.ROUTER_ACTIONS` — quit/quit-force/issues/help — bound in a screen
scope work there); a higher layer's rebind takes the key from the lower layer's other action in the
same scope, and `check` reports each cross-layer steal and any page left with no quit key
(`keyspec.lint_merged`). Color
depth (direct 24-bit via a `-direct` terminfo; `--color`, `NO_COLOR`) and motion (`effects:`,
auto-reduced over SSH) degrade gracefully; the startup splash is a pluggable provider (`splash:`).

**CLI (`app.build_parser`).** No command = the TUI. Ops `inspect` / `install` / `remove` / `upgrade`
(`--system` = System Updates) / `lock` / `unlock` / `set-version` / `fix-scope`; the matrix `picks` /
`machine` / `profile` / `disp`; `pin`, `where`, `check`, `versions`, `location`, `show`; `config` /
`theme` / `keys`; `plugin …` (incl. `set-source`, which also retargets the synced clone's origin);
`dotfiles …` (`activate [--local]` turns a staged block into user glue), `glue add|override`;
`orphans`; `updates`, `refresh`; `report` / `request` / `request-os`; `manpages`. Global
`--pretend`, `--os`, `--home` (sandbox), `--machine`, `--config`. `install --picks` (missing picks) /
`upgrade --picks` (outdated picks) = `app._picks_selection`: this box only (refused when
`--machine` names another), unioned with any names, plan shown + confirmed unless `--yes`; bare
`install` with neither names nor `--picks` errors. `set-version` refuses up front on a driver whose
class attribute `targets_version = False` (tarball, appImage, font, native-pkg-file, aur,
rpm-ostree, gcc/clang alternatives, gcc-toolset, glue, dotfiles, service, group —
`actions.targets_version`). **`--pretend` is a full dry run**: the runner echoes instead of
executing (so probes read empty → everything reads missing), and no ledger/receipt/lock, `.cfs`
marker, `last-failure.hu`, config edit (CLI `app._pretend_edit`; TUI writers in actions.py return
`(False, actions.PRETEND_NOT_SAVED)`), user-config generation or legacy-config move happens, and no
false "NOT DETECTED"; an uncached download prints a `<latest release>` placeholder
(`actions.pretend_unresolved_download`). Any new write path must honor `ctx.runner.pretend`.

In the repo, routes.hu is a **capability/component model** (see `docs/routing-model.md` for
the full spec). Its sections:
- `os:` — the OS layer: `using` inheritance (pop_os! -> ubuntu -> debian -> glibc_linux -> linux;
  fedora/rhel -> redhat -> glibc_linux; arch, opensuse, void, fedora_atomic, kde_linux ->
  glibc_linux; the musl blocks alpine, chimera, void_musl -> linux directly — so `void` and
  `void_musl` are siblings and a Void-wide gate is `void or void_musl`), which package manager each
  block declares `native:` (apt/dnf/pacman/zypper/apk/xbps/brew — brew is fedora_atomic's CLI
  native, and elsewhere on glibc an ordinary `via: brew` method; the **native-less** blocks kde_linux and chimera declare none, so `via: native` bindings
  aren't candidates there and components fall through to flatpak/tarball/cargo/…), version
  `scale-root:` markers, `provides:` (capabilities baseline in that environment: `linux` provides
  python3, `glibc_linux` provides glibc), optional `detect:` (id + on-disk marker refinement,
  osdetect.py), and an optional per-OS `driver-preference:`.
- `drivers:` — per-driver config: each driver's inherent `requires:`, closed for every binding of
  that via (e.g. appImage->[libfuse2, glibc], flatpak->flatpak, cargo->cargo, tarball->curl,
  source->git, aur->[base-devel, git], font->[fontconfig, unzip], pyenv->[pyenv,
  python-build-deps], brew->homebrew), an optional driver-wide `standing:` (snap ships `standing:
  never-auto`), and two kinds of **driver gate** (validity-only — a gated driver's bindings are not
  candidates). The DERIVED gate: **a driver is valid only where its own `requires:` can be met**
  (`resolve.gated_context` — a greatest fixpoint that tries each driver's requires with the real
  `_State` and gates the failures; it reads your HARD pins, never soft ones, so `pins: { glibc:
  gcompat }` opens appImage on Alpine; reasons in `ctx.derived_gates`). So snap isn't offered where
  snapd has no method, appImage on musl (no glibc) or fedora_atomic/kde_linux (no libfuse2), pyenv
  where python-build-deps has no route — no hand-written expression. The explicit gate `when:` is
  for facts that aren't requirements: brew ships `when: "glibc_linux"` (Linuxbrew refuses musl even
  with gcompat), aur ships `when: "arch"` (Void has base-devel too). Driver `requires:`/`standing:`/
  gates also apply to a `via: native` binding that resolves to that manager. `routes._driver_gates`
  parses the explicit gate into `OsCascade.driver_gates`, `OsCascade.context` evaluates it into
  `ctx.gated_drivers`, `gated_context` adds the derived ones (cached per load × context × pins;
  `Resolver.context()` and both resolve entry points go through it, so `where`/the picker/resolution
  agree), `resolve.driver_gated` drops the bindings in `_matching`, a "no binding" error appends
  each gated method's reason (`_gate_note`), and a gate adds NO specificity — `routecheck.gated` intersects it with
  `when:` to judge OVERLAP only (specificity stays on the raw `when:`); `where` names the reason
  (`resolve.driver_gate_reason`). Merged across every layer (`layers.merge_dict_section` over
  `ALL_ROLES`), the top config last.
- `facets:` — detected machine traits beyond OS/cpu, usable as `when:` atoms (`gpu:nvidia`;
  `docs/facets.md`). A `detect:` probe is command-carrying data, so a plugin's facets merge only
  when that plugin is trusted.
- `components:` — each component is a named **capability** plus an `install:` list of
  context-selected **bindings**. A binding is `{ via: <driver>  when: "<expr>"  ...details }`.
  `via: native` resolves to the OS's declared package manager (name defaults to the component
  name, override with a `name:` map keyed by driver, plus `default:`; `installed-name:` — the
  package probed for state — takes the same driver-keyed map shape, a scalar applying to every
  manager, `drivers/_native.py`). `when:` is a boolean DSL
  (predicate.py) over OS atoms (bare = subtree membership; versioned e.g. `ubuntu < 23.04`,
  scale-bound), `cpu:` and facets, with `and`/`or`/`not` (negation is general, over any atom).
  `when:` states VALIDITY ONLY (does this method work here), never preference. A binding is a
  **candidate** (`resolve._matching`) when its `when:` holds, its driver isn't in
  `disabled-drivers:` or gated out (explicit `drivers:` `when:`, or derived: its requires can't be
  met here), it covers this cpu, and it isn't
  `via: native` on a native-less OS. CPU
  coverage of a download is stated with `cpu-names: { <cpu>: <upstream token> }` (or a cpu-keyed
  `asset:` map): its keys are the cpus upstream ships and `$ARCH` expands through it — this gates
  validity WITHOUT adding specificity, unlike a `when: cpu:` clause (routing-model §7). Among the
  candidates, the default (`resolve._select`) is: drop `standing: never-auto` methods unless every
  candidate is one -> most-specific comparable `when:` -> per-binding `standing:` rank (a NARROW
  author signal, so it outranks the broad machine order below) -> `driver-preference` (a machine
  setting, default `resolve.DEFAULT_DRIVER_PREFERENCE` = native, aur, flatpak, snap, native-pkg-file,
  appImage, brew, tarball, source, script; overridable per OS block; a FALLBACK CHAIN —
  `resolve._effective_preference`: OS-block lists, then the setting, then the default, each adding
  only the drivers the earlier ones don't name, so a stale list still ranks a new driver; only
  drivers named in no list are least preferred and tie; aur sits right after native, so an aur binding needs no `when: "arch"`
  of its own (the aur gate covers validity) except where a competitor valid on Arch has a narrower
  `when:` that would win on specificity first (a version-gated AppImage, a cpu-gated tarball); brew sits just ahead of tarball so it beats tarball/script/
  cargo/pipx/npm/sdkman but never a native/flatpak/snap/.deb/AppImage default; CLI tools,
  toolchains and servers carry a `{ via: brew  name: <formula> }` binding — libs, keg-only
  formulae and curl/git, which `homebrew` itself requires, don't); a remaining tie is an error naming
  the preference channel (never `when:`), a user binding-pin overrides. **`standing:`** is the ONE
  preference knob (on a binding, a `drivers:` block, or a component): `standing: never-auto` =
  valid+listed+pinnable but never the auto-default (on a binding/driver; it still wins when it is
  the only valid method) or never auto-pulled to satisfy a `requires:` (on a component-provider);
  an INTEGER = a preference rank (higher wins) — on a component it RANKS PROVIDERS of a capability
  (`resolve._pick_provider`, after pins / soft pins / version selection / reuse; an equal top rank
  is an ambiguity error naming both fixes, a provider-pin or a `standing:` rank; `where` prints
  `providers  <cap> by standing: N`). (History: `standing` replaced the old
  `prefer:`/`candidate-only:`/`opt-in:` trio — `routes.RETIRED_STANDING_KEYS`: on a binding or a
  `drivers:` block they raise a `retired-key` check warning, on a component an unknown-key load
  error naming the replacement.) A versioned capability adds
  `provides: { cap: N }` + `requires: { cap: ">=N" }` (a constraint selects a resident by version
  and ENABLES a `never-auto` provider; on a cap whose providers carry no component-level version —
  go, ghc — it is a soft floor surfaced as an advisory, auto-picked only under `auto-tighten:`;
  routing-model §11). An installed provider/method is also adopted over the default by
  the detection tier (`detection.detect_pins` -> soft pins for a second resolve pass;
  `adopt-installed:`, default on; precedence: pin > detected > standing default). Two bindings of
  the SAME `via:` that overlap incomparably are a load-time ambiguity error
  (`routecheck.check_component`; disjoint `cpu-names:` sets never overlap); different-`via:`
  overlap is a legal multi-method choice decided by preference (a genuine tie there is a
  resolve-time error + a `check` warning). A component may also declare
  `provides:`/`requires:`/`suggests:` (capabilities), `parts:` (a `via: parts` binding is a pure
  aggregator = the union of its parts, no unit of its own; a component-level `parts:` with no
  `install:` is shorthand for that implicit binding, and alongside an `install:` it is ignored
  with a `parts-ignored` check warning), `standing:`, `description:` and
  `attrs:` (kind tags, unioned across layers; docs/component-attrs.md) — any other key is a load
  error. `requires:` is HARD (unmet = error); `suggests:` is SOFT — pulled in if resolvable in the
  loaded layers, skipped silently if not (both work at component and binding level). Dotfiles are
  just ordinary components with a `via: dotfiles` binding (so they can carry `when:` too); a
  component that ships config `suggests:` its `<name>-dotfiles` companion (soft, so the config can
  live only in a user's plugin layer and simply doesn't attach where it's absent; its shell setup
  is likewise a `<name>-glue` companion) — there is no special dotfiles field.

Any layer may also patch without redefining a component: `component-names: { <driver>: { <comp>:
<pkg> | {} } }` (per-driver package-name patch, `{}` = no package there; routing-model §10a) and
`version-floors:` (tightens an existing `requires:`, never adds one).

Resolution (resolve.py; the app runs `resolve_resilient`) is a worklist to a fixpoint over one
fixed machine context: seed the explicitly-wanted components + what they provide, then close
`requires` (component-level + the driver's `drivers:` requires + binding-level) and pull resolvable
`suggests`, reusing existing/env-provided providers; no backtracking (unmet HARD require /
ambiguous providers = error; an unmet suggest is skipped); dedup by unit key; a provider never
satisfies its own requirement (enforced on the reuse path too — `_self_held`). A `never-auto` provider is used only when explicitly wanted,
required by its own name, version-constrained, or provider-pinned. A suggested component's own
`requires` stay hard once it is pulled. `resolve_resilient` collects per-pick errors (surfaced as
`Context.resolve_errors`) and prunes units whose hard requirement failed, so one bad pick is an
error row, not a brick.
Per-machine `pins` (binding-pin component->via, provider-pin capability->provider; one flat
namespace — a value naming a via is a binding-pin, `resolve.pin_via_names`) are a filter, not a
suggestion (an unrealizable pin is an error, never silently ignored) — merged
per key repo < primary < user, edited with `configsys pin set|unset|list|promote` (the light
reroute that doesn't require redefining a component). The app's second resolve pass
(`routes.Resolver.resolve_resilient`) adds two machine-derived pin sets: effective order user pins >
opt-in `auto-tighten:` floor pins > detected-installed soft pins > reuse > auto default
(routing-model §10). A user pin always wins; when it keeps a method that misses a floor
auto-tighten would fix, `flooradvise.advise` raises a `pin-floor` warning (`!` / inspect — not
`check`, which doesn't probe versions). Detected pins are SOFT: one that can't be honored (fails a
version constraint, names a method not valid here) is dropped for that resolution, never an error
(`Resolver.dropped_soft_pins`, shown verbosely). The result is `{unit_key: Unit}` (`driver\comp`), mapped by
`adapt.to_resolved_components` onto `{unit_key: ResolvedComponent}`, which the drivers consume
unchanged.

The user file `~/.config/configsys/configsys.hu` overlays the repo section by section: machine
settings (`picks:`/`machine:`/`scope:`/`pins:`/`driver-preference:`/`disabled-drivers:`/`dirs:`/
`locations:`/… — the registry is `layers.MACHINE_SETTING_SECTIONS` ∪ the keys of
`actions.CONFIG_SETTINGS` (`layers.machine_setting_sections`; `config set|unset|show|move` cover
`locations` [machine nature, `component=path` tokens], `detect-coexisting`,
`installer-shell-writes` and `installer-shell-writes-allow` [uniform]); read only from the
repo/primary/user layers, `config._MACHINE_ROLES`; `actions.SETTING_NATURE` routes an edit:
uniform → the primary plugin when blessed, machine → the local top config, and `configsys config
move` / TUI Config `m` carries one across), `components:` (route overrides — bindings
merge ADDITIVELY across layers by `(via, when)` identity, `routes._merge_component_chain`: a higher
layer adds an install method, overrides a matching binding, `drop:`s one, or `{}` removes the whole
component; the other fields override with inheritance; to merely pick an existing method, use a
`pins:` entry), `profiles:`, `os:`/`drivers:` (honored at highest precedence — machine-local
driver tweaks), `facets:` (in the top config a facet VALUE map, not probe specs; docs/facets.md),
and the cosmetic `theme:`/`keys:` (merged from every layer). A primary plugin with no data file
gets an empty `<name>.hu` on its first write. `configsys where
<component>` explains a component's source layer + resolution (every candidate, the default, and
the rule that decided it); `configsys check` lints the whole merged config.

**Layer stack (configsys/layers.py).** Every config/routes file is a LAYER (role repo / plugin /
primary / user / include); a file may `include:` others (paths relative to the including file's
directory; a leading `~` expands against the configsys home, so `--home`/`CONFIGSYS_HOME` apply).
Layers overlay lowest-first — repo (routes.hu + config.hu, the shipped profile catalog + default
`keys:`) < plugins < primary < the top user file, with includes sitting below the file that
includes them — merging by section and, for components/profiles, by name. **The uniform layer
rule:** every layer may DEFINE (components, profiles, os blocks, drivers; facet probe specs still
need plugin trust); only the top config and the primary plugin may SET machine settings — an
include or a non-primary plugin that sets one is ignored with a `check` / `!` warning
(`layers._forbidden_by_role` → `ignored_section_warnings`). Cycles/missing
files error clearly (a bad plugin/primary file is skipped with a warning; a bad repo/user file is
loud — `layers.expand_tolerant`); provenance (`Component.source`, `Config.profile_source`) flows
through so `where`/`check` attribute to the right file. The plugin model reuses this substrate — a
plugin is just another source in the stack.

**Plugins (configsys/plugins.py; docs/plugins.md — fully built).** `plugins: [ { source:
"github:x/y"  ref: v1 } ]` (also `gitlab:`, a git URL, a local path / `file:`; optional `sha256:`)
in the top config, then `configsys plugin sync` clones each to `~/.config/configsys/plugins/
<name>/` at the pinned ref (git via the runner); a plugin's manifest (`plugin.hu`) may declare
further `plugins:`, synced transitively. Its `.hu` data files become `plugin`-role layers; a plugin
may add components, profiles, drivers AND os blocks (derivative distros). Loading uses what's on disk; unsynced / ABI-incompatible (manifest
`requires-abi` vs `ABI_VERSION`/`ABI_SUPPORTED`) / sha256-mismatched (quarantined) / malformed
plugins are skipped, never fatal. Only the top config may grant `primary: true` (`configsys plugin
bless`): the **primary plugin** is the user's portable personal layer — it sorts last among plugins
and may set machine settings; `plugin add` writes to it by default. **Code plugins** (a manifest
`code:` module exporting `DRIVERS = [Driver subclasses]` / `SPLASHES`, plus
`register_version_source` / `register_transport`) load only when trusted at their exact content
hash (`configsys plugin trust`; `plugin_identity`, `plugin-trust.hu`); command-carrying DATA
(script/source recipes, apt `source-line`/`ppa`, `facets:` `detect:` probes, and ANY shipped glue —
it is sourced at every shell start) is gated by the same trust (`command_source_trusted`;
`ships_executable_data` makes such a data-only plugin trustable). `configsys plugin list` (and the TUI Plugins screen) shows status.

**Machine-level plugins (was: project discovery).** (History: the old CWD-walk-up scan for
`.configsys.hu`/`.configsys-*.hu`, which auto-activated layers, was REMOVED.) A source repo or app
install now contributes components to a machine by being declared as a **plugin** in the top user
config — `configsys plugin add <source> --local` writes a non-`primary` entry to
`~/.config/configsys/configsys.hu`'s `plugins:`, so it applies here (a `plugin`-role layer:
components/os/drivers, synced and trust-gated like any plugin, no machine-setting authority)
without traveling to the user's other machines the way a `primary` plugin does. `inspect` still
resolves this machine's picks resiliently (`Context.resolve_errors`) so one bad entry is an error
row, not a brick.

**Stranded installs (configsys/stranded.py).** When routes stop offering a component's installed
method (binding removed/gated, driver disabled), the component reads `switch` — nothing staged;
installing it (`i`; `v` to choose another method first) runs the method-swap, removing the old
install; no method left on this OS = `dangling` (never removed for you); only a disabled driver's
method = `unmet`. Installs stay findable via an install RECEIPT the ledger (`state.hu`) records on
every successful install/upgrade/set-version (cleared on remove; none for dotfiles/glue) + a
`pacman -Qm` `<comp>-<variant>` heuristic for pre-receipt AUR installs. See
`docs/stranded-installs.md`.

**System Updates (configsys/sysupdates.py).** Everything the OS reports upgradable OUTSIDE the
picks, from each manager's own `upgradable_index` (apt/dnf/pacman/zypper/apk/xbps/brew +
flatpak/snap; rpm-ostree omitted), grouped into tiers kernel/core/standard/apps
(`classify_index`): `configsys updates`, `upgrade --system`, and the TUI Components "System
Updates" group, applied via each manager's own `upgrade_all`. Within-release only; never modeled
as components (docs/principles.md).

Drivers are defined in code (configsys/drivers/, base class configsys/driver.py — the frozen
plugin ABI) behind a uniform op set: get_version, get_latest, is_locked, install, uninstall,
upgrade, set_version, lock, unlock, location (plus the optional hooks — batched `installed_index`/
`batch_index` with the public `batch` attribute + `batched_version(rc)`, the orphan-scan and System
Updates hooks, `outdated_signal` — all in the FROZEN list of the `driver.py` docstring since
2026-10-10, pinned by test/test_abi_surface.py; underscore members stay internal). apt has various commands for these; as does flatpak, etc. Each `via:` value
names a Driver 1:1 (the OS package managers apt, dnf, pacman, aur, zypper, apk, xbps, brew,
rpm-ostree; tarball, native-pkg-file [install an upstream release's .deb/.rpm/pkg file with the OS
package tool — its own via, distinct from repo `native`, because it doesn't ride `apt upgrade`;
ranked after native in driver-preference], flatpak, snap, appImage [`desktop-id:` names its menu
entry after the app's own desktop id, so the compositor matches the window], font, script
[declared install/version/uninstall commands], `source` [declarative build from a git checkout or
archive]; the config drivers dotfiles [an app's own config: `.cfs` marker dir + manifest in the
user's content store, linked into place; a displaced real file goes to `.pre-configsys`, then
`.pre-configsys.1`, `.2`, … — never overwritten] and glue [per-shell `conf.d` enablement snippets,
shipped not captured, its own `glue/` roots, linked in load-order BANDS `00-configsys` / `50-<component
glue>` (`component_link_stem`) / `90-<user glue>` (`user_link_name`) / `99-user` (an existing `NN-`
prefix is kept; legacy links migrated); plus the user-glue namespace — `configsys glue add`
(`user.d/`, a scaffolded `99-user`) and `glue override` (fork a component's shipped glue; `check`
flags drift). The `configsys-glue` preludes (all five shells) define `configsys` → the real
launcher ($CONFIGSYS_LAUNCHER, else `<state>/launcher` written on shell hookup by
`Glue._record_launcher`, else `$HOME/${CONFIGSYS_SRC_DIR:-src}/configsys/configsys.sh`) and the
`cfs` alias; the shared loaders carry nothing personal. The shell-writes guard (shellguard.py)
exempts configsys's own marker blocks and stages an installer's rc edits machine-locally in
`<state>/staged-glue/`; `dotfiles activate` turns one into user glue — see docs/shell-glue.md]; the language toolchains and their module/version installers
cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install, pyenv, sdkman, gcc, gcc-toolset,
clang; and the post-install primitives service [systemd or runit] and group [usermod]) — except
`via: native` (resolves to the OS's package-manager driver) and `via: parts` (a pure aggregator, no
driver of its own). More drivers can be added in core or by a trusted code plugin
(`register_driver`).

(History: routes.hu was previously a `\family` blocks + OS-cascade + `*: apt\*` wildcard model
resolved by a `RouteResolver`. That was replaced in-place by the capability model above, built
in parallel and proven byte-equivalent before the flip; the old resolver/data are deleted.
`test/routing_golden.json` freezes the proven resolution as a regression gate.)

The bash bootstrap (configsys.sh) is minimal: require python3 >= 3.10 (it stops with a message
rather than installing one — the one exception is apt's `pythonX.Y-venv` when venv/ensurepip is
missing), create/repair the repo `.venv`, install `humon` + `packaging` into it, then `exec
.venv/bin/python -m configsys`. Everything else is python. (pyproject.toml can build a
`configsys-cli` wheel — PyPI's `configsys` is taken — but it is unpublished; the project runs
clone-first.)

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
  playbooks for adding and auditing components; `tools/namesweep.py` (+
  `test/run-name-sweep-in-podman.sh`) checks native package names exist per distro.

## Some considerations

The load-bearing, cross-cutting principles (safety rules, routing invariants like "`when:` is
validity not preference", the "no surprises" posture, what we deliberately don't model) live in
`docs/principles.md` — read it before making a decision that touches those axes.

User should have control of what each machine picks; profiles are a browse aid, not the install set. Components that are wanted from several directions (picks, requires, suggests) shouldn't be doubled up; a conflict (ambiguous providers, equally-preferred methods) is an error the user is told to fix — an error row plus a `check` / `!` issue, never a silent guess — while the rest of the picks still resolve. In general, take a posture of 'no surprises'; user should know what's installed, what's going to be when they do an operation, and what's not. However, user does not need all details about package dependencies in apt, for example.
