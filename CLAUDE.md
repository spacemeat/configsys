# configsys

Configsys is a single tool for setting up a new operating system installation and account from a config and TUI application. The notion is that not only are dotfiles able to be synchronized across systems (via a remote git repository) but that, whether the system is linux, unix, or macos, we are able to, from a TUI tool and bash, select a user profile and quickly sync os-native packages, appImages, flatpaks, SDKs, distributed binaries, or other means of software distribution. We want total control over updating, version locking, and removal of any such component, and to be able to easily modify the config and routes files to further refine the (relatively) uniform setup.

## Architecture

Every system we care about either comes with a version of python3, or that must be the first requirement of the system. Additionally, there is a python library in PyPI called humon, which we can use as well (see skill). From there, we are able to read and use routes.hu and config.hu to:
- determine, depending on the OS, the install/update driver for a component
- determine the installation state (whether installed, what version, is it latest, is it version-locked) of a component
- install a component to latest version
- change a component to a particular version or upgrade to its latest
- lock / unlock a component version

The application should be python3, and so python3 and humon must be the first to synchronize; this can be done via bash, since we need these components for the rest of the app. The app should be an interactive TUI, and slick looking on a 24-bit RGB terminal. It should be menu-driven, with single-key actions and menu navigation via VIM-like controls.

On start, the user config file (~/.config/configsys/configsys.hu; a legacy ~/configsys.hu is migrated there) should be present. If it is not, one must be generated from a template config from the repo. If it contains a top-level node called 'configs' with a single value or list, those values are the profiles that concern this installation. For each profile that matches another top-level node (example: dev) the app will search the system to find all the installed components already on the system and evaluate their versions. From that known state, an interactive menu will let user:

- view the install state of each component
- interactively mark installed components for an operation (upgrade, remove, etc)
- quickly mark all components for an operation (select all in profile)

In the repo, routes.hu is a **capability/component model** (see `docs/routing-model.md` for
the full spec). Its three sections:
- `os:` — the OS layer: `using` inheritance (pop_os! -> ubuntu -> debian -> linux; fedora/rhel
  -> redhat -> linux), which package manager each block declares `native:` (apt/dnf/pacman),
  version `scale-root:` markers, and `provides:` (capabilities baseline in that environment).
- `drivers:` — per-driver config, currently just each driver's inherent
  `requires:` (appImage->libfuse2, flatpak->flatpak, cargo->cargo, pipx->pipx, aur->[base-devel,
  git], tarball->curl, pip->python3-pip, debian-font->[fontconfig,unzip]).
- `components:` — each component is a named **capability** plus a list of context-selected
  **bindings**. A binding is `{ via: <driver>  when: "<expr>"  ...details }`. `via: native`
  resolves to the OS's declared package manager (name defaults to the component name, override
  with a `name:` map keyed by driver). `when:` is a boolean DSL over OS atoms (bare = subtree
  membership; versioned e.g. `ubuntu < 23.04`, scale-bound) and `cpu:`, with and/or/guarded-not.
  The most specific matching binding wins (set-inclusion order; overlapping-but-incomparable is a
  load-time ambiguity error). A component may also declare `provides:`/`requires:`/`suggests:`
  (capabilities), and `parts:` (a `via: parts` binding is a pure aggregator = the union of its
  parts, no unit of its own). `requires:` is HARD (unmet = error); `suggests:` is SOFT — pulled
  in if resolvable in the loaded layers, skipped silently if not (both work at component and
  binding level). Dotfiles are just ordinary components with a `via: dotfiles` binding (so they
  can carry `when:` too); a package that ships config `suggests:` its `<name>-dotfiles` component
  (soft, so the config can live only in a user's plugin layer and simply doesn't attach where
  it's absent) — there is no special dotfiles field.

Resolution (resolve.py) is a worklist to a fixpoint over one fixed machine context: seed the
explicitly-wanted components + what they provide, then close `requires` (and pull resolvable
`suggests`) reusing existing/env-provided providers; no backtracking (unmet HARD require /
ambiguous = error; an unmet suggest is skipped); dedup by unit key. A suggested component's own
`requires` stay hard once it is pulled.
Per-machine `pins` (binding-pin component->via, provider-pin capability->provider) sit at top
precedence — set in `~/.config/configsys/configsys.hu`'s `pins:` section (the light reroute that doesn't require
redefining a component). The result is `{unit_key: ResolvedComponent}` (`driver\comp`), which
the drivers consume unchanged.

The user file `~/.config/configsys/configsys.hu` overlays the repo section by section: `configs:`/`scope:`
(machine settings), `profiles:` (shadowed per name), `components:` (route overrides — redefine
all-or-nothing, add, or remove with `{}`), and `pins:`. `configsys where <component>` explains
a component's source layer + resolution; `configsys check` lints the whole merged config.

**Layer stack (configsys/layers.py).** Every config/routes file is a LAYER; a file may
`include:` others (paths relative to the including file's directory). Layers overlay
lowest-first — repo (routes.hu + config.hu) < discovered project files < the top user file,
with includes sitting below the file that includes them — merging by section and, for
components/profiles, by name. Includes are DEFINITIONS-ONLY: their `components:`/`profiles:`
merge in, but `configs:`/`scope:`/`pins:`/`ignore-profiles:` (machine settings) and
`os:`/`drivers:` (code-adjacent) are ignored (a `check` warning). Cycles/missing files
error clearly; provenance (`Component.source`, `Config.profile_source`) flows through so
`where`/`check` attribute to the right file. This is the shared substrate the plugin model
will reuse — a plugin is just another source in the stack.

**Data plugins (configsys/plugins.py — P1).** `plugins: [ { source: "github:x/y"  ref: v1 } ]`
in the user config, then `configsys plugin sync` clones each to `~/.config/configsys/plugins/
<name>/` at the pinned ref (git via the runner). Its `.hu` data files become `plugin`-role
layers (repo < plugins < discovered < user); a plugin may add components AND os blocks
(derivative distros — `merge_dict_section` unions os/drivers from repo+plugin). Loading uses
what's on disk; unsynced / ABI-incompatible (manifest `requires-abi` vs `ABI_VERSION`/
`ABI_SUPPORTED`) / malformed plugins are skipped, never fatal. `configsys plugin list` shows
status. Code plugins (Python `Driver` subclasses) + trust are P2 — see docs/plugins.md.

**Project discovery (developer-in-source-tree).** configsys walks up from the CWD to the
nearest dir holding `.configsys.hu` (base — ships in a bundle) and/or `.configsys-*.hu`
(named variants like `-dev`, source-tree only), and adds them as `discover`-role layers whose
profiles **auto-activate** (union into `configs`, minus a user `ignore-profiles:`). Bounded by
`$HOME` (not a project) and the FS root; disabled by `CONFIGSYS_NO_DISCOVER`; the CWD is
`CONFIGSYS_CWD` or os.getcwd(). Resilience: a malformed discovered file (or component) is
SKIPPED, never fatal (repo/user errors still raise); and `inspect` resolves the active set
resiliently (Context.resolve_errors), so one bad auto-activated entry becomes an error row,
not a brick. Activation never installs — install stays explicit.

Drivers are defined in code (configsys/drivers/) behind a uniform op set: get_version,
get_latest, is_locked, install, uninstall, upgrade, set_version, lock, unlock, location. apt
has various commands for these; as does flatpak, etc. Each `via:` value names a Driver 1:1
(apt, dnf, pacman, aur, tarball, flatpak, appImage, dotfiles, debian-font, cargo, gcc,
gcc-toolset, clang, pip, pipx) — except `via: native` (resolves to the OS's package-manager
driver) and `via: parts` (a pure aggregator, no driver of its own). More drivers can be
added as needed.

(History: routes.hu was previously a `\family` blocks + OS-cascade + `*: apt\*` wildcard model
resolved by a `RouteResolver`. That was replaced in-place by the capability model above, built
in parallel and proven byte-equivalent before the flip; the old resolver/data are deleted.
`test/routing_golden.json` freezes the proven resolution as a regression gate.)

The bash bootstrap must be minimal; ensure an adequate python3 version is installed globally (3.10 is a fine choice), and a virtual environment exists (.venv) in the repo directory, and humon is installed. From there, the rest of the app should be in python.

## Some considerations

User should have control of what goes into profiles and which profiles they wish to use. Components that overlap in profiles shoudln't be doubled up; if there are driver conflicts between components, user should be notified to fix the conflict before other things can proceed. In general, take a posture of 'no surprises'; user should know what's installed, what's going to be when they do an operation, and what's not. However, user does not need all details about package dependencies in apt, for example.

