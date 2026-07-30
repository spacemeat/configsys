# the configsys configuration and routing format

configsys reads Humon (`.hu`) files. This is the reference for their structure: how your
per-machine config selects what to install, how `routes.hu` describes where each component
comes from on any OS, and how the two combine. It is the source for the **configsys.hu(5)**
man page and is linked from the README.

## Layers

Every `.hu` file is a **layer**. Layers overlay section-by-section, lowest precedence first,
and the highest-precedence definition of a thing wins:

```
repo (routes.hu + config.hu)  <  plugins  <  primary  <  discovered project files  <  your config
```

Your machine's own config (`~/.config/configsys/configsys.hu`) always wins. The **primary**
layer is one plugin you designate as trusted to carry machine settings (see
docs/plugins.md) — it sits above the ordinary plugins but below your config. A file may
`include:` other files (paths relative to the including file's directory), which sit just
below it. Includes are definitions-only: their `components:` and `profiles:` merge in, but
machine settings (`configs:`, `scope:`, `pins:`, `ignore-profiles:`, `discover:`) and
code-adjacent sections (`os:`, `drivers:`) are ignored. The one exception is `theme:`, which
is purely cosmetic and is merged from every layer (see docs/theming.md).

## Your config file

Lives under `$XDG_CONFIG_HOME` (defaults to `~/.config/configsys/configsys.hu`); a legacy
`~/configsys.hu` is migrated automatically on first run. Every section is optional:

```hu
{
    configs: [ dev ]                 // which profiles apply to THIS machine

    scope: system                    // default install scope for scope-honoring drivers

    include: [ ~/src/myproject/configsys.hu ]   // pull in more profiles/components

    plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    pins: { steam: flatpak }         // force a driver (binding-pin) or a provider

    driver-preference: [ native, flatpak, appImage ]   // tiebreak among valid methods

    profiles: { dev: [ btop, neovim, gcc-15, gdb ] }   // define or shadow a profile

    components: { apod: {} }         // amend a route, add one, or remove one with {}

    ignore-profiles: [ gaming ]      // suppress an auto-activated project profile

    discover: false                  // opt out of project discovery on this machine
}
```

- **`configs:`** is the set of profiles active on this machine.
- **`scope:`** sets the default install scope (`user` or `system`) for scope-honoring drivers.
- **`pins:`** reroutes without redefining: a binding-pin forces a component's driver, a
  provider-pin forces which component satisfies a capability.
- **`driver-preference:`** is a global tiebreak order over drivers, used to pick the default
  when a component has several valid install methods (see "Choosing among methods" below). It
  replaces the whole list across layers (repo < primary < user).
- **`components:`** *amends* a route: bindings merge **additively** across layers by
  `(via, when)` identity — a higher layer adds an install method, overrides a matching
  binding, retracts one with a `drop:` binding, or removes the whole component with `{}`.
- **`theme:`** restyles the TUI (colors, per-element styles, background gradient). It is the
  one cosmetic section any layer may set; see docs/theming.md.

## Profiles

A profile is a named list of components. Its value is a list of **terms**, applied
left-to-right:

- a bare `name` adds a component;
- `+name` splices in another profile's members (recursively);
- `~name` removes a component added so far;
- `+self` means "the same profile from the next layer down", so a higher layer **amends** a
  profile in place instead of replacing it wholesale.

```hu
profiles: {
    base: [ btop, git, curl ]
    dev:  [ +base, neovim, gcc-15, ~curl ]   // base, plus tools, minus curl
    dev:  [ +self, valgrind ]                // (higher layer) amend dev in place
}
```

Order matters: a `~` after a `+` drops what the include brought in; a later add re-adds it.

**`all`** is a built-in synthetic profile — every defined component. You don't declare it; use it
as `configsys install profile:all` or add it to `configs:` to browse the full menu in `inspect`/
the TUI (it shows as a `+all` note rather than a listed profile, and `inspect` resolves it
resiliently, so components that don't route on this OS just show as errors rather than blocking).

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
  capabilities a component satisfies.
- **`scope: user|system`** sets the install scope. Scope-honoring drivers (appImage, flatpak,
  tarball, source, font, npm, gem, luarocks) default to `user`; fixed-scope drivers
  (apt/dnf/pacman = system, cargo/pipx/dotfiles = user) ignore it.

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
- a **CPU** atom (`cpu: aarch64`).

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

1. **most specific** among comparable valid bindings (a narrower `when:` beats a broader one);
2. **`driver-preference`** — the global tiebreak list (overridable per OS block);
3. a per-binding **`prefer:`** rank.

If that still ties, it is an error that names the preference channel — never a prompt to
narrow a validity `when:`. To override the default on one machine, `configsys pin set <name>
<driver>` writes a binding-pin (or edit `pins:` directly); `configsys where <name>` shows all
candidates and which rule decided.

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

- **`{ github: owner/repo }`** — the latest release tag; optional `strip-v`; optional
  `asset: <glob>` also resolves the exact download URL from the release assets.
- **`{ url: "..."  regex: "..." }`** — fetch a page and extract the version.
- **`{ static: "..." }`** — a deliberate pin.

`$VERSION` and `$ARCH` are filled into the URL at install time. When a `github` asset name is
literal (no glob), configsys can fall back to the API-free `releases/latest/download/<asset>`
URL, so installs keep working when the GitHub API is unreachable. Discovered versions are
cached (`~/.config/configsys/versions.hu`, 24h TTL); `configsys refresh` re-queries; and
`--pretend` never touches the network (cache-only). Set `CONFIGSYS_GITHUB_TOKEN` (or
`GITHUB_TOKEN`) to lift GitHub's unauthenticated rate limit.

## dotfiles

A `via: dotfiles` component maps link specs `{ src, dst }`: `dst` is where the config belongs
(env-var and `~` expanded), and `src` is resolved through a content **search-path** — the first of
these that has it wins:

- `~/.config/configsys/dotfiles/<src>` — your machine-local store
- `<primary plugin>/dotfiles/<src>` — your portable, git-tracked config
- `<defining layer>/dotfiles/<src>` — a template, only if some layer ships one

configsys ships **no personal config templates**: a component may declare `src`/`dst` with no
content anywhere, in which case it is simply not linked (a no-op) until you supply content. Install
symlinks `dst -> src` so edits flow back to git.

Because your existing config is precious, install **refuses** to symlink over a real on-system file
that resolves only to an un-adopted template, printing how to adopt it (`configsys dotfiles
capture`) — or `install --force` to back it up to `<name>.pre-configsys` and replace. Adopted
content (in your store) links freely; an `absorb-into` spec relocates a pre-existing file into a
loader dir instead of backing it up (e.g. a stray `~/.bash_aliases`). `uninstall` removes the
symlink and restores any backup.

`configsys dotfiles status` reports each dotfile's state — **linked** / **adopted** / **unmanaged**
/ **template** / **empty** — and where its managed content lives; `configsys dotfiles capture`
copies your existing on-system dotfiles into your store (read-only on the system side). A package
that ships config `suggests:` its `<name>-dotfiles` component (soft, so it attaches only where that
config exists).

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
`apk`, `aur`, `brew`, `rpm-ostree`), `flatpak`, `appImage`, `tarball` (also bare-binary and
`.zip` archives), `source` (build from a git checkout or source archive with declared
`build:` commands), `dotfiles`, `font`, `script` (declared install/version/uninstall
commands), the language toolchains and their module installers (`cargo`, `pip`, `pipx`,
`npm`, `gem`, `go-install`, `opam`, `luarocks`, `cabal`, `gcc`, `clang`, `gcc-toolset`), and
the post-install primitives `service` (systemd) and `group` (usermod). Two `via:` values are
special: `native` (resolves to the OS's package manager) and `parts` (a pure aggregator).

## Project discovery

configsys walks up from your working directory for `.configsys.hu` (a base file) and
`.configsys-*.hu` (named variants), and **auto-activates** their profiles — so a source tree
can declare its own dependency set. Discovery is bounded by `$HOME` and the filesystem root,
disabled by `CONFIGSYS_NO_DISCOVER=1` (or `discover: false` in your config), and starts from
`CONFIGSYS_CWD` (or the current directory). A malformed discovered file is skipped, never
fatal.

## See also

**configsys(1)** for the command-line interface; the README for a narrative overview.
