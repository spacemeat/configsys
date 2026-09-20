# the configsys configuration and routing format

configsys reads Humon (`.hu`) files. This is the reference for their structure: how your
per-machine config selects what to install, how `routes.hu` describes where each component
comes from on any OS, and how the two combine. It is the source for the **configsys.hu(5)**
man page and is linked from the README.

## Layers

Every `.hu` file is a **layer**. Layers overlay section-by-section, lowest precedence first,
and the highest-precedence definition of a thing wins:

```
repo (routes.hu + config.hu)  <  plugins  <  primary  <  your config
```

Your machine's own config (`~/.config/configsys/configsys.hu`) always wins. The **primary**
layer is one plugin you designate as trusted to carry machine settings (see
docs/plugins.md) — it sits above the ordinary plugins but below your config. A file may
`include:` other files (paths relative to the including file's directory), which sit just
below it. Includes are definitions-only: their `components:` and `profiles:` merge in, but
machine settings (`picks:`, `machine:`, `pins:`, `scope:`, … — see the settings table) and
code-adjacent sections (`os:`, `drivers:`) are ignored. The cosmetic/UI sections `theme:` and
`keys:` are the exception: they are merged from every layer (see docs/theming.md).

## Your config file

Lives under `$XDG_CONFIG_HOME` (defaults to `~/.config/configsys/configsys.hu`); a legacy
`~/configsys.hu` is migrated automatically on first run. Every section is optional:

```hu
{
    machine: laptop                  // which picks: column is THIS box (default: this-machine)

    picks: {                         // the install set: one component list per machine
        laptop:  [ btop, neovim, gcc-15, gdb ]
        desktop: [ btop, neovim, steam ]
    }

    scope: system                    // default install scope for scope-honoring drivers

    include: [ ~/src/myproject/configsys.hu ]   // pull in more component definitions

    plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    pins: { steam: flatpak }         // force a driver (binding-pin) or a provider

    driver-preference: [ native, flatpak, appImage ]   // tiebreak among valid methods

    components: { apod: {} }         // amend a route, add one, or remove one with {}

    disabled-drivers: [ glue ]       // turn an install method off here (manage your own shell config)

    adopt-installed: true            // prefer an already-installed method over the default (default on)

    reboot-advice: true              // post-op "reboot advised" via the distro's native check (default on)

    splash: ocean                    // startup wait-screen animation (name / random / off / unset=default)

    effects: reduced                 // TUI motion: full / reduced / none (unset: reduced over SSH)

    dirs: { sdk: "~/toolchains"  system: /srv/opt }   // relocate install-layout dirs

    locations: { blender: ~/dev/blender-git  kicad: /opt/kicad }   // per-component: find/manage HERE

    detect-coexisting: false         // skip the "also present (unmanaged)" pass (default on)

    keys: { components: { method: p } }   // rebind TUI keys (see `configsys keys`)
}
```

### Machine settings

Each setting has a **kind** and a **nature** (where a fresh edit lands — see the next section).
`configsys config show` prints the same table with live values and sources.

| setting | kind | nature | default | what it does |
| --- | --- | --- | --- | --- |
| `machine` | scalar | machine | `this-machine` | This box's machine name — which `picks:` column is "this machine". |
| `picks` | map | uniform | `{}` | `{ <machine>: [ components ] }` — the install set per machine (the matrix). |
| `uninstall` | list | machine | `[]` | Components staged for removal (the TUI `x` queue; runs at execute). |
| `dispositions` | map | machine | `{}` | `{ component: seen \| interesting }` triage marks; unlisted = NEW. |
| `scope` | scalar | machine | `user` | Default install scope for scope-honoring drivers: `user` (`~`) or `system` (`/opt`, sudo). |
| `pins` | map | machine | `{}` | Binding-pins (`component: via`) and provider-pins (`capability: component`). |
| `driver-preference` | list | uniform | built-in | Order ties between equally-valid install methods break in; replaces the whole list per layer. |
| `disabled-drivers` | list | machine | `[]` | Vias to turn OFF here — their bindings stop matching (a soft `suggests:` is skipped, a hard `requires:` errors). E.g. `dotfiles`/`glue` to manage your own shell config, or `snap`. |
| `auto-tighten` | bool | uniform | off | Auto-pick a floor-satisfying install method (versioned `requires:`) instead of only advising. |
| `adopt-installed` | bool | uniform | on | Prefer an already-installed method/provider over the default (the detection tier). |
| `refresh-before-execute` | scalar | uniform | `auto` | Refresh the OS package index once before staged ops: `auto` (when the batch has a native install/upgrade), `always`, `never`. |
| `install-overlay` | bool | uniform | on | Open TUI Profiles with the install-state overlay on (`O` toggles). |
| `reboot-advice` | bool | uniform | on | After an op (and as a TUI chip), advise when a reboot / service restart is needed, via the distro's native check. |
| `splash` | scalar | uniform | `braille-bar` | Startup wait-screen: a splash-provider name, `random`, `off`, or unset for the built-in default. |
| `effects` | scalar | machine | auto | TUI motion: `full` (gradient + splash), `reduced`, `none`. Unset auto-picks `reduced` over SSH. |
| `orphans-ignore` | list | machine | `[]` | Name-or-glob patterns whose orphans stay quiet in `configsys orphans`. |
| `dirs` | map | mixed | see below | Install-layout dirs: `user`/`system` (machine), `app`/`sdk`/`src` (uniform). |
| `locations` | map | hand-edited | `{}` | Per-component absolute install-location override (`component: path`). |
| `detect-coexisting` | bool | hand-edited | on | Probe each component's OTHER install methods after inspect and surface "also present (unmanaged)". |
| `installer-shell-writes` | scalar | hand-edited | `block` | `block`: snapshot/revert rc files an installer scribbles in, staging the removed block as inactive glue; `allow` turns the guard off. |
| `installer-shell-writes-allow` | list | hand-edited | `[]` | Components exempt from the shell-writes guard. |
| `version-floors` | map | hand-edited | `{}` | Maintainer-authored minimum-version `requires:` tightening (`{ component: { cap: ">=X" } }`). |
| `facets` | map | hand-edited | `{}` | Declared detected-environment atoms usable in `when:` (docs/facets.md). |
| `keys` | map | cosmetic | built-in | TUI keybinding overrides, merged from every layer (`configsys keys` shows the result). |
| `theme` | map | cosmetic | built-in | TUI palette/roles/gradients, merged from every layer (docs/theming.md). |

A **hand-edited** setting is merged like the others (repo < primary < your config, later wins) but
is not offered by `configsys config set` / the Config screen — edit the file.

Notes on a few:

- **`dirs:`** relocates the install-layout directories without a shell env var. Keys: `user`
  (user-scope base, default `~`), `system` (system-scope base, default `/opt`), and the category
  dirs `app`/`sdk`/`src` (defaults `apps`/`sdks`/`src`, referenced in routes as `$CONFIGSYS_APP_DIR`
  etc.). Precedence is **default < `dirs:` < env** — the `CONFIGSYS_USERSCOPE_DIR` /
  `CONFIGSYS_SYSTEMSCOPE_DIR` / `CONFIGSYS_APP_DIR` / `CONFIGSYS_SDK_DIR` / `CONFIGSYS_SRC_DIR` env
  vars still win, so `dirs:` is the durable setting and the env var the per-invocation override.
  (Bootstrap paths — where the config/state/repo live — stay env-only; they're needed before the
  config loads.)
- **`locations:`** is "find/manage THIS component's install here": an absolute, scope-bypassing
  path honored by the path-based drivers (source builds, appImage, tarball, font, and the build
  plugins) over their computed dir. Distinct from `dirs:`, which relocates a whole category.
- **`detect-coexisting:`** — package managers are enumerated once (batched), so the cost is a
  handful of "list installed" calls, not one per component. `configsys versions <name>` shows
  per-method state regardless.
- **`pins:`** reroutes without redefining: a binding-pin forces a component's driver, a
  provider-pin forces which component satisfies a capability. `configsys pin set|unset|promote`.
- **`splash:`** — fancier splashes are shipped by code plugins (`SPLASHES` export — e.g.
  **configsys-splash-ocean**; see docs/plugins.md) and must be trusted before they load;
  `CONFIGSYS_NO_SPLASH`, `--nocolor`, `--effects none` and `--verbose` also suppress the splash.
- **`components:`** *amends* a route: bindings merge **additively** across layers by
  `(via, when)` identity — a higher layer adds an install method, overrides a matching
  binding, retracts one with a `drop:` binding, or removes the whole component with `{}`.

## Where a machine-setting edit lands

`configsys config set …` and the TUI **Config** screen route each setting by its **nature**
(the table above):

- **uniform** settings are the same on every machine, so an edit defaults into your **primary
  plugin** (portable — commit + push + re-tag the primary + `plugin sync` to propagate; it's
  effective on this machine immediately). `picks:` is uniform too — the install set is meant to
  travel (`configsys picks to-primary` moves this box's local picks there).
- **machine** settings are a truth about *this* box, so an edit defaults to your **top config**
  (`~/.config/configsys/configsys.hu`), local and unshared. `dispositions:` (your NEW/seen triage)
  and `uninstall:` are machine-local too.

When no primary is blessed, everything lands local. An edit to a setting you've *already* set
goes to the layer it lives in (so a lower layer can't silently shadow it). The Config screen
shows each setting's current home (`local` / `primary: <name>` / `built-in default`) and its
nature, and `config show` prints the same.

- `config set <key> <value> --local` forces this-machine-only (bypasses the uniform default).
- `config move <key>` (TUI: **`m`**) carries a setting the other way — `local ↔ primary` —
  writing its value at the destination and clearing the source. Direction is inferred from where
  it lives now; a setting still at its built-in default has nothing to move.

An **env var always wins** over both (the per-invocation escape hatch), and is surfaced as the
source when set.

## Picks — what a machine installs

The install set is the **component × machine matrix**: `picks:` holds one component list per
machine, and `machine:` says which column *this* box is. A machine installs exactly the
components picked for it — nothing is inferred from profiles.

```hu
machine: laptop
picks: {
    laptop:  [ btop, neovim, gcc-15 ]
    desktop: [ btop, neovim, steam, blender ]
    build-box: [ ]                    // an empty column is still a machine
}
```

- `configsys picks list|add|rm [--machine M]` edits a column (default: this box's);
  `picks to-primary` moves this box's local picks into the primary plugin so they travel.
- `configsys machine list|show|add|rm|use` manages the columns; `machine use <name>` sets this
  box's `machine:` (no name clears it). `--machine NAME` on any command curates/plans another
  machine's set for the run; install/execute still act on the local machine only.
- The TUI **Profiles** screen is the same matrix interactively (`t`/`T` toggle picks, `m`/`M`
  choose machines); the **Components** screen shows this machine's picks with their state.
- **`dispositions:`** is a side-store of triage marks (`seen` / `interesting`; unlisted = NEW)
  so the catalog can be worked through once — `configsys disp list|get|set`. **`uninstall:`** is
  the queue of components staged for removal (TUI `x`), run at execute.
- `configsys orphans` lists installed software no pick accounts for; `--adopt` picks it.

The retired `configs:` and user-authored `profiles:` sections now only produce `check` warnings.

## Profiles — read-only browse lenses

A profile is a named list of components — defined in the repo's `config.hu` or by a plugin — used
to **browse** the catalog (`configsys profile list|show`, the TUI Profiles screen). Browsing a
profile never changes your system; you pick from it. On the command line, `profile:<name>`
expands to a profile's members (`configsys install profile:dev`).

For repo/plugin authors, a profile's value is a list of **terms**, applied left-to-right:

- a bare `name` adds a component;
- `+name` splices in another profile's members (recursively);
- `~name` removes a component (or a whole spliced sub-profile) added so far;
- `+self` means "the same profile from the next layer down", so a higher layer **amends** a
  profile in place instead of replacing it wholesale.

```hu
profiles: {
    base: [ btop, git, curl ]
    dev:  [ +base, neovim, gcc-15, ~curl ]   // base, plus tools, minus curl
    dev:  [ +self, valgrind ]                // (higher plugin layer) amend dev in place
}
```

Order matters: a `~` after a `+` drops what the include brought in; a later add re-adds it.

**`all`** is a built-in synthetic profile — every defined component. You don't declare it; use it
as `configsys install profile:all`, or cycle the Components screen's view mode (`M`) to see the
full installed+tracked picture.

## Components and bindings

`routes.hu`'s `components:` section defines each component as a capability plus a list of
context-selected **bindings**. A binding names its **driver** with `via:`, guards itself
with an optional `when:` expression, and carries driver-specific details:

```hu
components: {
    btop: {
        install: [
            { via: native  when: "rhel"  requires: epel }   // EL: needs EPEL enabled
            { via: native  repo-component: universe }        // everywhere else
        ]
    }
    chrome:     { install: [ { via: flatpak  hub: flathub  app: com.google.Chrome } ] }
    discord:    { install: [ { via: flatpak  hub: flathub  app: com.discordapp.Discord }
                             { via: native-pkg-file  when: debian  standing: never-auto  url: "…" } ] }
    vulkan-dev: { install: [ { via: parts  parts: [ build-essential, vulkan-sdk ] } ] }
}
```

- **`via: native`** resolves to whatever the OS uses (apt / dnf / pacman / zypper / apk /
  brew) — one route covers every distro. `name:` maps the package name per driver.
- **`via: parts`** is a pure aggregator: a component that is just the union of its parts,
  with no unit of its own.
- **`requires:`** pulls in capabilities (another component, or a driver's prerequisites)
  first, dependency-ordered — a hard dependency (unmet is an error). **`suggests:`** is soft
  (pulled in if resolvable here, skipped otherwise). **`provides:`** declares extra
  capabilities a component satisfies; a versioned capability is `provides: { cap: N }` matched
  by `requires: { cap: ">=N" }`.
- **`standing:`** is the one preference knob, on a binding, a driver, or a component:
  `never-auto` keeps a method valid, listed and pinnable but never the auto-default (on a
  component, never auto-pulled to satisfy a `requires:`); an **integer** is a preference rank
  (higher wins). See "Choosing among methods".
- **`scope: user|system`** sets the install scope. Scope-honoring drivers (appImage, flatpak,
  tarball, source, font, npm, gem, luarocks) default to `user`; fixed-scope drivers
  (apt/dnf/pacman = system, cargo/pipx/dotfiles/glue = user) ignore it.
- **`description:`** (one line) and **`attrs:`** (kind tags — CLI/TUI/GUI/FOSS/…; see
  docs/component-attrs.md) describe a component for the catalog and its filters.

Bindings **merge additively** across layers. A binding's identity is its `(via, when)` pair,
so a higher layer (a plugin or your config) can *add* a new install method, *override* a
matching binding, *retract* an inherited one with a `drop:` binding
(`{ via: X  when: Y  drop }`), or clear the whole component with `{}` — none of which requires
redefining the component.

Among the bindings that are **valid** here (their `when:` matches), one is chosen — see
"Choosing among methods" below. Run `configsys where <name>` to see a component's bindings,
which are valid here, and which one resolves.

## The `when:` expression

`when:` is a boolean expression that selects a binding by machine context. Its atoms are:

- an **OS name** — bare (`ubuntu`, `redhat`) matches that block and everything that inherits
  from it; versioned (`ubuntu < 23.04`) matches a version range on a scale;
- a **CPU** atom (`cpu: aarch64`);
- a declared **facet** atom — any other detected fact about the machine (a GPU vendor, a tool's
  version), declared in a `facets:` section; see docs/facets.md.

Combine atoms with `and`, `or`, and a guarded `not`. OS blocks form a lineage via `using:`
(`pop_os! -> ubuntu -> debian -> linux`), detected from `/etc/os-release` (`ID=pop` ->
`pop_os!`), so a route written on `debian` applies to the whole family. `when:` expresses
**validity only** — whether a method works here — never which method to prefer. Two bindings
of the **same driver** whose match-sets overlap must be comparable (one more specific than
the other) or configsys reports a load-time ambiguity; overlapping bindings of *different*
drivers are legal alternatives, decided by preference (see below).

## Choosing among methods

A component can have several valid install methods in one context (e.g. `native` and
`flatpak` both work on Ubuntu). configsys picks one default deterministically, in this order:

0. bindings marked **`standing: never-auto`** are set aside (unless every valid method is);
1. **most specific** among comparable valid bindings (a narrower `when:` beats a broader one);
2. a per-binding **`standing:`** integer rank — a narrow, per-package author signal, so it
   outranks the blanket order below;
3. **`driver-preference`** — the global tiebreak list (a machine setting, overridable per OS
   block).

If that still ties, it is an error that names the preference channel — never a prompt to
narrow a validity `when:`. Above the default sit two overrides: with `adopt-installed` on (the
default), a method that is **already installed** is adopted over the computed default; and a
**pin** beats everything (`configsys pin set <name> <driver>` writes a binding-pin, or edit
`pins:` directly). Precedence: **pin > installed > standing default**. `configsys where <name>`
shows all candidates and which rule decided.

A derivative distro that does not rebrand `/etc/os-release` (Proxmox VE reports `ID=debian`)
can still be detected by a **marker**: an os block declares `detect: { id: <base>  marker:
<path> }` (marker may be a list). When the detected block is that base — or a descendant — and
every marker exists on disk, configsys routes to the more-specific block. This is the
data-driven form of the built-in Fedora-Atomic ostree-marker detection, so a plugin can add a
detectable OS with no code (the `configsys-proxmox` plugin does exactly this).

## Versions — discovered, not hardcoded

Download-based bindings declare *how* to find the latest version rather than pinning one:

```hu
neovim: {
    install: [ { via: appImage  name: Neovim  scope: user
                 version: { github: neovim/neovim  asset: "nvim-linux-$ARCH.appimage" }
                 url: "https://github.com/neovim/neovim/releases/download/$VERSION/nvim-linux-$ARCH.appimage" } ]
}
```

- **`{ github: owner/repo }`** — the latest release tag (pre-release tags skipped); optional
  `strip-v`; optional `asset: <glob>` also resolves the exact download URL from the release assets.
- **`{ url: "..."  regex: "..." }`** — fetch a page and extract the version.
- **`{ static: "..." }`** — a deliberate pin.

`$VERSION` and `$ARCH` are filled into the URL at install time. When a `github` asset name is
literal (no glob), configsys can fall back to the API-free `releases/latest/download/<asset>`
URL, so installs keep working when the GitHub API is unreachable. Discovered versions are
cached (`~/.config/configsys/versions.hu`, 24h TTL); `configsys refresh` re-queries (and also
refreshes the native package index); `configsys versions <name>` shows what every method would
install; and `--pretend` never touches the network (cache-only). Set `CONFIGSYS_GITHUB_TOKEN`
(or `GITHUB_TOKEN`) to lift GitHub's unauthenticated rate limit.

## dotfiles

A `via: dotfiles` component manages an application's **own config**. It maps link specs
`{ src, dst }`: `dst` is where the config belongs (env-var and `~` expanded), and `src` is
resolved through a content **search-path** — the first of these that has it wins:

- `~/.config/configsys/dotfiles/<component>.cfs/<src>` — your machine-local store
- `<primary plugin>/dotfiles/<component>.cfs/<src>` — your portable, git-tracked config
- `<defining layer>/dotfiles/<component>.cfs/<src>` — a template, only if some layer ships one

The **`<component>.cfs/` marker dir** is what makes a config *managed*: it holds the content plus a
`manifest.hu` recording the src→dst layout and any `exclude:` globs (secret-shaped files are
suggested into it on first capture). A managed config with no files yet is still managed — the
marker, not the content, is the state.

configsys ships **no personal config templates**: a component may declare `src`/`dst` with no
content anywhere, in which case it is simply not linked (a no-op) until you supply content. Install
symlinks `dst -> src` so edits flow back to git; links never point into the repo.

Because your existing config is precious, install **refuses** to symlink over a real on-system file
that resolves only to an un-adopted template, printing how to adopt it (`configsys dotfiles
capture`) — or `install --force` to back it up to `<name>.pre-configsys` and replace. Adopted
content (in your store) links freely; an `absorb-into` spec relocates a pre-existing file into a
loader dir instead of backing it up (e.g. a stray `~/.bash_aliases`). `uninstall` removes the
symlink and restores any backup.

`configsys dotfiles status` reports each dotfile's state — **linked** / **adopted** / **unmanaged**
/ **template** / **empty** — and where its managed content lives; `configsys dotfiles capture`
copies your existing on-system dotfiles into your store (read-only on the system side). The TUI
**Dotfiles** screen does the same per row (`m`/`u` manage/unmanage, `M`/`U` all, `s`/`S` move
between the local and primary stores). A package that ships config `suggests:` its
`<name>-dotfiles` component (soft, so it attaches only where that config exists).

## glue

A `via: glue` component is the **shell integration** a tool needs to be usable — PATH, an alias
(`fdfind`→`fd`, `batcat`→`bat`), an init hook (`zoxide init`), completions — as a small snippet
per shell:

```hu
zoxide-glue: { install: [ { via: glue  requires: shell-glue  glue: zoxide } ] }
```

- Glue is **shipped, never captured**: a snippet is authored at `glue/shell/<shell>/<name>.<ext>`
  in the repo or a plugin, materialized into the machine-local glue store
  (`~/.config/configsys/glue/<shell>/conf.d/`), and linked into the uniform
  `~/.config/<shell>/conf.d/` for each **installed** shell that has a variant. elvish and nushell
  can't source a directory, so their snippets are inlined into the rc file instead.
- **`shell-glue`** is the one loader component: it wires every installed shell to source its
  `conf.d` (bash via `~/.bash_aliases`, zsh via an rc marker block, fish natively). Every snippet
  `requires:` it.
- A tool `suggests:` its `<name>-glue` companion, so the snippet attaches only where the tool is
  picked. Glue is "active" or not — it has no version — and lives on its own TUI **Glue** screen
  (`a`/`A` activate, `x` deactivate), grouped per shell. `CONFIGSYS_GLUE_SHELLS` overrides which
  shells count as installed.
- Opt out per machine with `disabled-drivers: [ glue ]` (and/or `dotfiles`) to manage your own
  shell config; the guard below keeps installers from scribbling in it.

**Installer shell writes.** With `installer-shell-writes: block` (the default), an installer that
appends to `~/.bashrc` / `~/.zshrc` / `~/.profile` (sdkman, nvm, rustup, conda, …) has the file
reverted to its prior bytes and the removed block **staged** as an inactive glue candidate:
`configsys dotfiles staged` lists them, `activate` links one into `conf.d`, `discard` drops it.
`installer-shell-writes-allow` exempts named components.

## component-names

A higher layer (typically a plugin) can patch the package name a component maps to under a given
driver — or drop it where that driver has no package — without redefining the whole component:

```
component-names: {
    xbps: { docker-engine: docker  r: R  nmap: {} }   // rename; {} = no package here (drop)
}
```

Keyed by driver and overlaid across the layer stack (later wins): a string replaces the resolved
package name; `{}` (or null) means "not available via this driver," so the component isn't offered
there. See the routing model (docs/routing-model.md §10a) for the full rules.

## Drivers

Each `via:` value names a driver: the OS package managers (`apt`, `dnf`, `pacman`, `zypper`,
`apk`, `aur`, `brew`, `rpm-ostree`), the distribution drivers `flatpak`, `snap`, `appImage`,
`tarball` (also bare-binary and `.zip` archives), `native-pkg-file` (an upstream release's
`.deb`/`.rpm` installed with the OS package tool — distinct from repo `native`, since it doesn't
ride `apt upgrade`), `source` (build from a git checkout or source archive with declared
`build:` commands), `font`, `script` (declared install/version/uninstall commands); the config
drivers `dotfiles` and `glue`; the language toolchains and their module/version installers
(`cargo`, `pip`, `pipx`, `npm`, `gem`, `go-install`, `opam`, `luarocks`, `cabal`, `pyenv`,
`sdkman`, `gcc`, `clang`, `gcc-toolset`); and the post-install primitives `service` (systemd) and
`group` (usermod). Two `via:` values are special: `native` (resolves to the OS's package manager)
and `parts` (a pure aggregator). Plugins may add drivers.

## Local plugins

To let a source repo or an app install contribute components (or os/driver blocks) to *this*
machine only, declare it as a **local plugin** in your top config rather than your portable
primary:

```
configsys plugin add github:owner/their-configsys-plugin --local
```

`--local` writes the entry to `~/.config/configsys/configsys.hu`'s `plugins:` list, so it
applies here and doesn't travel to your other machines the way a **primary** plugin does. It
loads as a `plugin`-role layer: it may add `components:`/`profiles:`/`os:`/`drivers:`, but not
machine settings (those stay `primary`/top-config only), and code plugins still require an
explicit `configsys plugin trust`. Without `--local`, `plugin add` rides your primary plugin
when one is set. See docs/plugins.md for the plugin model.

## See also

**configsys(1)** for the command-line interface; the README for a narrative overview.
