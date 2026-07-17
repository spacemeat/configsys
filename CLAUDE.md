# configsys

Configsys is a single tool for setting up a new operating system installation and account from a config and TUI application. The notion is that not only are dotfiles able to be synchronized across systems (via a remote git repository) but that, whether the system is linux, unix, or macos, we are able to, from a TUI tool and bash, select a user profile and quickly sync os-native packages, appImages, flatpaks, SDKs, distributed binaries, or other means of software distribution. We want total control over updating, version locking, and removal of any such component, and to be able to easily modify the config and routes files to further refine the (relatively) uniform setup.

## Architecture

Every system we care about either comes with a version of python3, or that must be the first requirement of the system. Additionally, there is a python library in PyPI called humon, which we can use as well (see skill). From there, we are able to read and use routes.hu and config.hu to:
- determine, depending on the OS, the install/update mechanism for a component
- determine the installation state (whether installed, what version, is it latest, is it version-locked) of a component
- install a component to latest version
- change a component to a particular version or upgrade to its latest
- lock / unlock a component version

The application should be python3, and so python3 and humon must be the first to synchronize; this can be done via bash, since we need these components for the rest of the app. The app should be an interactive TUI, and slick looking on a 24-bit RGB terminal. It should be menu-driven, with single-key actions and menu navigation via VIM-like controls.

On start, a file called configsys.hu should be present in ~. If it is not, one must be generated from a template config from the repo. If it contains a top-level node called 'configs' with a single value or list, those values are the profiles that concern this installation. For each profile that matches another top-level node (example: dev) the app will search the system to find all the installed components already on the system and evaluate their versions. From that known state, an interactive menu will let user:

- view the install state of each component
- interactively mark installed components for an operation (upgrade, remove, etc)
- quickly mark all components for an operation (select all in profile)

In the repo, routes.hu is a **capability/component model** (see `docs/routing-model.md` for
the full spec). Its three sections:
- `os:` — the OS layer: `using` inheritance (pop_os! -> ubuntu -> debian -> linux; fedora/rhel
  -> redhat -> linux), which package manager each block declares `native:` (apt/dnf/pacman),
  version `scale-root:` markers, and `provides:` (capabilities baseline in that environment).
- `mechanisms:` — per install-medium config, currently just each mechanism's inherent
  `requires:` (appImage->libfuse2, flatpak->flatpak, cargo->cargo, pipx->pipx, aur->[base-devel,
  git], tarball->curl, pip->python3-pip, debian-font->[fontconfig,unzip]).
- `components:` — each component is a named **capability** plus a list of context-selected
  **bindings**. A binding is `{ via: <mechanism>  when: "<expr>"  ...details }`. `via: native`
  resolves to the OS's declared package manager (name defaults to the component name, override
  with a `name:` map keyed by mechanism). `when:` is a boolean DSL over OS atoms (bare = subtree
  membership; versioned e.g. `ubuntu < 23.04`, scale-bound) and `cpu:`, with and/or/guarded-not.
  The most specific matching binding wins (set-inclusion order; overlapping-but-incomparable is a
  load-time ambiguity error). A component may also declare `provides:`/`requires:` (capabilities),
  and `parts:` (a `via: parts` binding is a pure aggregator = the union of its parts, no unit of
  its own). Dotfiles are just ordinary components with a `via: dotfiles` binding (so they can
  carry `when:` too); a package that ships config `requires:` its `<name>-dotfiles` component —
  there is no special dotfiles field.

Resolution (resolve.py) is a worklist to a fixpoint over one fixed machine context: seed the
explicitly-wanted components + what they provide, then close `requires` reusing existing/
env-provided providers; no backtracking (unsatisfiable/ambiguous = error); dedup by unit key.
Per-machine `pins` (binding-pin component->via, provider-pin capability->provider) sit at top
precedence — set in `~/configsys.hu`'s `pins:` section (the light reroute that doesn't require
redefining a component). The result is `{unit_key: ResolvedComponent}` (`family\comp`), which
the families consume unchanged.

The user file `~/configsys.hu` (see configsys/config.py + the overlay in configsys/routes.py)
overlays the repo section by section: `configs:`/`scope:` (machine settings), `profiles:`
(shadowed per name), `components:` (route overrides — redefine all-or-nothing, add, or remove
with `{}`), and `pins:`. `configsys where <component>` explains a component's source layer +
resolution; `configsys check` lints the whole merged config.

Families are defined in code according to their major operations: getVersion, install,
uninstall, upgrade, setVersion, lockVersion, unlockVersion. apt has various commands for doing
these; as does flatpak, etc. Each `via:` mechanism name maps 1:1 to a Family (apt, dnf, pacman,
aur, tarball, flatpak, appImage, dotfiles, debian-font, cargo, gcc, gcc-toolset, clang, pip,
pipx). More families can be added as needed.

(History: routes.hu was previously a `\family` blocks + OS-cascade + `*: apt\*` wildcard model
resolved by a `RouteResolver`. That was replaced in-place by the capability model above, built
in parallel and proven byte-equivalent before the flip; the old resolver/data are deleted.
`test/routing_golden.json` freezes the proven resolution as a regression gate.)

The bash bootstrap must be minimal; ensure an adequate python3 version is installed globally (3.10 is a fine choice), and a virtual environment exists (.venv) in the repo directory, and humon is installed. From there, the rest of the app should be in python.

## Some considerations

User should have control of what goes into profiles and which profiles they wish to use. Components that overlap in profiles shoudln't be doubled up; if there are family conflicts between components, user should be notified to fix the conflict before other things can proceed. In general, take a posture of 'no surprises'; user should know what's installed, what's going to be when they do an operation, and what's not. However, user does not need all details about package dependencies in apt, for example.

