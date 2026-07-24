# the configsys configuration and routing format

configsys reads Humon (`.hu`) files. This is the reference for their structure: how your
per-machine config selects what to install, how `routes.hu` describes where each component
comes from on any OS, and how the two combine. It is the source for the **configsys.hu(5)**
man page and is linked from the README.

## Layers

Every `.hu` file is a **layer**. Layers overlay section-by-section, lowest precedence first,
and the highest-precedence definition of a thing wins:

```
repo (routes.hu + config.hu)  <  plugins  <  discovered project files  <  your config
```

Your machine's own config (`~/.config/configsys/configsys.hu`) always wins. A file may
`include:` other files (paths relative to the including file's directory), which sit just
below it. Includes are definitions-only: their `components:` and `profiles:` merge in, but
machine settings (`configs:`, `scope:`, `pins:`, `ignore-profiles:`) and code-adjacent
sections (`os:`, `drivers:`) are ignored.

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

    profiles: { dev: [ btop, neovim, gcc-15, gdb ] }   // define or shadow a profile

    components: { apod: {} }         // override a route, add one, or remove one with {}

    ignore-profiles: [ gaming ]      // suppress an auto-activated project profile
}
```

- **`configs:`** is the set of profiles active on this machine.
- **`scope:`** sets the default install scope (`user` or `system`) for scope-honoring drivers.
- **`pins:`** reroutes without redefining: a binding-pin forces a component's driver, a
  provider-pin forces which component satisfies a capability.
- **`components:`** overrides a route all-or-nothing, adds a new one, or removes one with `{}`.

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
  tarball, npm, gem, luarocks) default to `user`; fixed-scope drivers (apt/dnf/pacman =
  system, cargo/pipx/dotfiles = user) ignore it.

The most specific matching binding wins. Run `configsys where <name>` to see a component's
bindings and which one resolves here.

## The `when:` expression

`when:` is a boolean expression that selects a binding by machine context. Its atoms are:

- an **OS name** — bare (`ubuntu`, `redhat`) matches that block and everything that inherits
  from it; versioned (`ubuntu < 23.04`) matches a version range on a scale;
- a **CPU** atom (`cpu: aarch64`).

Combine atoms with `and`, `or`, and a guarded `not`. OS blocks form a lineage via `using:`
(`pop_os! -> ubuntu -> debian -> linux`), detected from `/etc/os-release` (`ID=pop` ->
`pop_os!`), so a route written on `debian` applies to the whole family. Two bindings whose
match-sets overlap must be comparable (one more specific than the other) or configsys reports
a load-time ambiguity.

A derivative distro that does not rebrand `/etc/os-release` (Proxmox VE reports `ID=debian`)
can still be detected by a **marker**: an os block declares `detect: { id: <base>  marker:
<path> }` (marker may be a list). When the detected block is that base — or a descendant — and
every marker exists on disk, configsys routes to the more-specific block. This is the
data-driven form of the built-in Fedora-Atomic ostree-marker detection, so a plugin can add a
detectable OS with no code (see `examples/configsys-proxmox`).

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

A `via: dotfiles` component maps link specs `{ src, dst }` — `src` under the defining layer's
`dotfiles/` directory, `dst` env-var and `~` expanded. Install symlinks `dst -> src` (so edits
flow back to git), backing up any existing non-symlink; uninstall restores the backup. A
package that ships config `suggests:` its `<name>-dotfiles` component (soft, so it attaches
only where that config exists).

## Drivers

Each `via:` value names a driver: the OS package managers (`apt`, `dnf`, `pacman`, `zypper`,
`apk`, `aur`, `brew`, `rpm-ostree`), `flatpak`, `appImage`, `tarball` (also bare-binary and
`.zip` archives), `dotfiles`, `font`, `script` (declared install/version/uninstall commands),
the language toolchains and their module installers (`cargo`, `pip`, `pipx`, `npm`, `gem`,
`go-install`, `opam`, `luarocks`, `cabal`, `gcc`, `clang`, `gcc-toolset`), and the
post-install primitives `service` (systemd) and `group` (usermod). Two `via:` values are
special: `native` (resolves to the OS's package manager) and `parts` (a pure aggregator).

## Project discovery

configsys walks up from your working directory for `.configsys.hu` (a base file) and
`.configsys-*.hu` (named variants), and **auto-activates** their profiles — so a source tree
can declare its own dependency set. Discovery is bounded by `$HOME` and the filesystem root,
disabled by `CONFIGSYS_NO_DISCOVER=1`, and starts from `CONFIGSYS_CWD` (or the current
directory). A malformed discovered file is skipped, never fatal.

## See also

**configsys(1)** for the command-line interface; the README for a narrative overview.
