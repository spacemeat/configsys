# configsys

One tool to bring a fresh OS install up to *your* setup — the same packages, the same
versions, the same dotfiles — whether the machine runs Ubuntu, Pop!\_OS, Fedora,
RHEL/Rocky/Alma, or Arch.

You describe **what** you want in a git-synced config; configsys works out **how** to get
it on *this* machine (apt vs dnf vs pacman, a Flatpak, an AppImage, a tarball, a Cargo
crate, a Nerd Font, a symlinked dotfile…) and gives you one interface — a slick, VIM-keyed
TUI — to install, upgrade, version-lock, and remove any of it, with no surprises about
what's about to change.

```console
$ ./configsys.sh            # bootstrap + launch the TUI
$ ./configsys.sh inspect    # or run any subcommand non-interactively
```

## Quick start

configsys needs only **python3 ≥ 3.10** on the system; it sets up everything else itself.

```console
$ git clone <your-fork> ~/src/configsys
$ cd ~/src/configsys
$ ./configsys.sh
```

`configsys.sh` is the only bash — a tiny, idempotent shim: it checks for python ≥ 3.10,
creates a repo-local `.venv`, installs [`humon`](https://pypi.org/project/humon/) (the
`.hu` config parser), then hands off to the python app. Re-running it is always safe.

On first run it drops a starter config at `~/.config/configsys/configsys.hu` and opens the
TUI. Edit that file to pick your **profiles**, then inspect and act.

> Dry run: pass `--pretend` to print the commands configsys *would* run instead of running
> them.

## Concepts

- **Component** — a thing you want by name: `neovim`, `btop`, `gcc-15`, `steam`. Resolved
  through `routes.hu` into one or more concrete **units** (`apt\btop`, `flatpak\firefox`,
  …). The unit key `driver\comp` is the dedup identity, so components that overlap between
  profiles install once.
- **Profile** — a flat list of component names (`user`, `dev`, …), shared in the repo's
  `config.hu` and git-synced. Your machine's config picks which profiles apply here.
- **Driver** — the code that installs/queries/removes one *class* of software, behind a
  uniform op set (install / uninstall / upgrade / set-version / lock / unlock / inspect).
  Ships: the native managers **apt, dnf, pacman, aur**, plus **flatpak, appImage, tarball,
  dotfiles, debian-font, cargo, pip, pipx**, and the **gcc / clang / gcc-toolset**
  toolchains.
- **State** — the live system is the source of truth (dpkg/rpm/flatpak/marker files); a
  small ledger (`~/.config/configsys/state.hu`) stores only lock *intent* and configsys
  bookkeeping. Version-lock uses native holds where they exist (`apt-mark`, `dnf
  versionlock`, `flatpak mask`).

## routes.hu — how components resolve

A component is a capability plus a list of context-selected **bindings**. Each binding
names its **driver** with `via:`, guards itself with an optional `when:` boolean
expression (over the OS lineage + CPU arch), and carries driver-specific details:

```hu
os: {
    linux:  { }
    debian: { using: linux    native: apt }     // OS cascade + the "native" driver
    ubuntu: { using: debian }
    pop_os!:{ using: ubuntu }
    arch:   { using: linux    native: pacman }
}

components: {
    btop: {
        install: [
            { via: native  when: "rhel"  requires: epel }   // EL: needs EPEL enabled
            { via: native  repo-component: universe }        // everywhere else
        ]
    }
    firefox: { install: [ { via: native  repo-component: universe } ] }
    chrome:  { install: [ { via: flatpak  hub: flathub  app: com.google.Chrome } ] }
    vulkan-dev: { install: [ { via: parts  parts: [ build-essential, vulkan-sdk ] } ] }
}
```

Key ideas:

- **`via: native`** resolves to whatever the OS uses (apt / dnf / pacman) — one route
  covers every distro.
- **OS blocks cascade** via `using:` (`pop_os! → ubuntu → debian → linux`), detected from
  `/etc/os-release` (`ID=pop` → `pop_os!`). A route written on `debian` applies to the
  whole family.
- **`when:`** selects among bindings by context — a boolean expression over the OS lineage
  (`"rhel"`, `"ubuntu < 23.04"`) and CPU arch. The most specific match wins.
- **`requires:`** pulls in capabilities (another component, or a driver's prerequisites)
  first, dependency-ordered.
- **`via: parts`** is a pure aggregator — a component that is just the union of its parts,
  with no unit of its own.
- **`scope: user|system`** — install scope. Scope-honoring drivers (appImage/flatpak/
  tarball) default to `user`; set it per-binding or machine-wide via `scope:` in your
  config. Fixed-scope drivers (apt/dnf/pacman = system, dotfiles/cargo = user) ignore it.

Run `configsys where <name>` to see a component's bindings and which one resolves here.

### Versions — discovered, not hardcoded

Download-based bindings declare *how* to find the latest version:

```hu
neovim: {
    install: [ { via: appImage  name: Neovim  scope: user
                 version: { github: neovim/neovim  asset: "nvim-linux-$ARCH.appimage" }
                 url: "https://github.com/neovim/neovim/releases/download/$VERSION/nvim-linux-$ARCH.appimage"
                 path: ~/apps/nvim.appimage } ]
}
```

- **`{ github: owner/repo [strip-v] }`** — latest release tag; optional `asset: <glob>`
  also resolves the exact download URL from the release assets (robust to file renames).
- **`{ url: … [regex: …] }`** — fetch a page and extract the version.
- **`{ static: … }`** — a deliberate pin.
- `$VERSION` / `$ARCH` are filled into the URL at install time. Discovered versions are
  cached (`~/.config/configsys/versions.hu`, 24h TTL); `configsys refresh` re-queries. Set
  `CONFIGSYS_GITHUB_TOKEN` (or `GITHUB_TOKEN`) to lift GitHub's unauthenticated rate limit.

### dotfiles

A `via: dotfiles` component maps link specs `{ src (under the repo's `dotfiles/`), dst }`;
`dst` is env-var / `~` expanded (`$XDG_CONFIG_HOME/nvim`). Install symlinks `dst → src`
(so edits flow back to git), backing up any existing non-symlink; uninstall restores the
backup. A component's config rides along as a required `-dotfiles` component, so it can
carry its own `when:` conditions too.

## Your config: `~/.config/configsys/configsys.hu`

Every `.hu` file is a **layer**, overlaid section-by-section, lowest precedence first:

```
repo (routes.hu + config.hu)  <  plugins  <  discovered project files  <  ~/.config/configsys/configsys.hu
```

Your machine's file always wins:

```hu
{
    configs: [ dev ]                 // which profiles apply to THIS machine

    // scope: system                 // default install scope for scope-honoring drivers

    // include: [ ~/src/myproject/configsys.hu ]   // pull in more profiles/components

    // plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    // pins: { steam: flatpak }       // force a driver (binding-pin) or a provider

    // profiles: { dev: [ btop, neovim, gcc-15, gdb ] }   // define or shadow a profile

    // components: { apod: {} }        // override a route, or remove one with {}
}
```

- Lives under `$XDG_CONFIG_HOME` (defaults to `~/.config/configsys/`). A legacy
  `~/configsys.hu` is migrated automatically on first run.
- **`include:`** — pull profiles/components from other files (definitions only; paths
  resolve against the including file's dir). Handy for per-project dependency sets.
- **Project discovery** — configsys walks up from your CWD for `.configsys.hu` /
  `.configsys-*.hu` and auto-activates their profiles, so a source tree can declare its own
  dependencies. Disable with `discover: false`, or suppress a profile with
  `ignore-profiles: [ … ]`.

## Commands

Run as `./configsys.sh <command>` (or `python -m configsys <command>` inside the venv).
With no command, the **TUI** opens.

```
configsys                      # interactive TUI (default)
configsys inspect              # install-state table for the active profiles
configsys install  <name>...   # install (pulls dependencies first, ordered)
configsys remove   <name>...
configsys upgrade  <name>...
configsys lock|unlock <name>...
configsys set-version <name> <version>
configsys where <name>         # explain a component: source layer + bindings + resolution
configsys check                # lint the merged config (repo + your file + includes + plugins)
configsys refresh              # re-query latest versions from their sources
configsys plugin <list|sync|add|remove|update>   # data plugins (see below)
```

Global flags: `--pretend` (dry-run; prints commands), `--os <block>`, `--home <dir>`,
`--config <file>` — the last three make runs sandboxable.

```console
$ ./configsys.sh where steam
steam
    - via native   when: pop_os!   name=steam:i386  foreign-arch=i386  <- selected here
    - via flatpak  when: always    hub=flathub  app=com.valvesoftware.Steam
    apt\steam  pkg steam:i386
```

## The TUI

A **profile → component → unit** tree. Profiles are expanded by default and list their
components; a component that resolves to one unit is a leaf (shown with its **driver**),
while a composite like `vulkan-dev` or one with dependencies collapses to an aggregated row
you can expand (`enter`/`→`) to reveal and individually select its units. Driver is its own
column; versions split into `INSTALLED` and `LATEST` (discovered for download drivers). An
infoblock above the footer shows the current unit's full versions and its install location
(`at: ~/vulkan`, the AppImage path, the font dir, dotfile targets, …). Ops can be staged on
any node — a profile stages all its units, a component its units, a unit just itself — and
staging is unit-keyed, so a mark shows everywhere that unit appears.

Keys: `j/k` move, `g/G` top/bottom, `enter`/`→` expand, `←` collapse, `tab` expand/collapse
all, `space` select, `a` all, `i/u/x` install/upgrade/remove, `L/l` lock/unlock, `c` clear,
`X` execute, `q` quit.

## Plugins

Plugins are git repos that add routing data (and, later, new drivers) to the layer stack.
Declare them in your config and sync:

```console
$ ./configsys.sh plugin add "github:someone/configsys-opensuse" --ref v1.2.0
$ ./configsys.sh plugin list      # declared plugins + their sync/ABI status
$ ./configsys.sh plugin sync      # clone/fetch all declared plugins to their pinned refs
```

They clone to `~/.config/configsys/plugins/<name>/`, pin to a ref, and are ABI-gated so an
incompatible plugin degrades instead of breaking the tool. `add` / `remove` / `update` edit
your `plugins:` list **in place, preserving your comments**.

A plugin can also ship **code** — a new driver (package manager) written in Python. Code runs
with your privileges during installs, so it stays inert until you approve its exact commit:

```console
$ ./configsys.sh plugin trust <name>     # per-commit; a code change re-arms the gate
```

[`examples/configsys-alpine/`](examples/configsys-alpine/) is a complete, copy-able example —
an `apk` driver + an `alpine` OS block. See [docs/plugins.md](docs/plugins.md) for the full
model and the ABI a code plugin targets.

## Design notes

- **No surprises.** Selecting a profile never changes your system; installs are always an
  explicit, reviewable action, and `check` lints the whole merged config without touching
  anything.
- **Resilient.** A malformed plugin, discovered file, or single component surfaces as an
  error row — it can't brick the tool.
- **One term, one meaning.** Everything about *how* software is acquired is a **driver**;
  everything about *what* you want is a **component**.

## Development

```console
$ .venv/bin/python -m pytest test/   # fast unit suite (mocked runner/fetch)
$ bash test/run-in-podman.sh         # real apt lifecycle in a disposable container
$ bash test/run-flatpak-in-podman.sh # gated: real flatpak --user lifecycle (slow, networked)
```

`test/` also holds per-driver `integration_*.sh` checks and `run-*-in-podman.sh` harnesses
for dnf/pacman/aur/toolchains. Deeper design docs live in
[`docs/`](docs/): the routing model ([routing-model.md](docs/routing-model.md)) and the
plugin system ([plugins.md](docs/plugins.md)).
