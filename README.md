# configsys

One tool to bring a fresh OS install up to *your* setup — the same packages, the same
versions, the same dotfiles — whether the machine runs Debian/Ubuntu/Pop!\_OS/Mint,
Fedora/RHEL/Rocky/Alma, Arch/Manjaro/EndeavourOS/CachyOS, openSUSE, Alpine, or an immutable
spin like Bazzite/Fedora Atomic — with still more (Void, Proxmox, …) available as plugins.

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
  Ships ~30: system package managers **apt, dnf, pacman, aur, zypper, apk, brew, rpm-ostree**;
  distribution drivers **flatpak, appImage, tarball, dotfiles, font, script**; language-ecosystem
  installers **cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install**; the **gcc /
  gcc-toolset / clang** toolchains; and post-install primitives **service** (systemd) and **group**
  (usermod). `via: native` picks the right system manager per OS; `via: parts` aggregates.
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

Bindings can also **discover** versions (GitHub / URL / static pins, with `$VERSION`/`$ARCH`
filled in at install time and cached), manage **dotfiles** (symlinked into place from your own
content store so edits flow back to git — see [Dotfiles](#dotfiles)), and target any of ~30
drivers.

> **Full format reference:** [**docs/config-format.md**](docs/config-format.md) — also
> installed as the **`configsys.hu(5)`** man page (`configsys manpages install`). It is the
> single source for layers, profiles (the `+include` / `~remove` / `+self` term algebra), the
> `when:` expression, version discovery, dotfiles, and the driver list.

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

    // plugins: [ { source: "github:spacemeat/configsys-void"  ref: v0.1.0 } ]

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

### Your config, as a plugin

Probably the best way to manage your config and make it portable is to build it as a plugin.
It's just a standard plugin--likely a data-only plugin, containing a plugin.hu, a routes
file (named anything you want), and any other files you want to be included (such as
dotfiles). The plugin.hu file contains details about your plugin, a pointer to the routes
file, and any other plugins you want to be transitively included. Reference the plugin in
your `~/.config/configsys/configsys.hu`:

``` hu
{
    plugins: [
        { source: "github:you/my-configsys" ref: v0.1.0 primary: true }
    ]
}
```

When you then run `./configsys.sh plugin sync` all the transitive plugins will be fetched.

**The fast path — `configsys plugin init`.** Rather than hand-building the plugin, get set up
locally first (capture your dotfiles, define your profiles/components), then let configsys assemble
the plugin for you:

```console
$ ./configsys.sh plugin init            # or: plugin init <name>   (default: configsys-<user>)
```

With no primary plugin yet it **creates** one in `~/.config/configsys/plugins/<name>/` from your
local bits — your captured dotfiles, your `profiles:`/`components:`, and your other declared
plugins carried along as transitive — `git init`s it, and blesses it primary. (If you already have
a primary, it **merges** those local bits in instead.) It's a real git repo you author in place;
when you're ready to share it, push it and repoint the source:

```console
$ cd ~/.config/configsys/plugins/configsys-<user>
$ git remote add origin git@github.com:you/configsys-<user>.git && git push -u origin main
$ ./configsys.sh plugin set-source configsys-<user> github:you/configsys-<user>
```

## Commands

Run as `./configsys.sh <command>` (or `python -m configsys <command>` inside the venv).
With no command, the **TUI** opens.

Run `configsys <command> -h` for per-command help.

```
configsys                          # interactive TUI (default)
configsys inspect                  # install-state table for the active profiles
configsys install  <name>...       # install (pulls dependencies first, ordered) [--force]
configsys remove   <name>...       # uninstall
configsys upgrade  <name>...       # upgrade to latest [--force]
configsys lock|unlock <name>...    # version-lock / unlock
configsys set-version <name> <ver> # pin to a specific version
configsys fix-scope [<name>...]    # reconcile user/system scope mismatches (moves the install)
configsys where <name>             # explain a component: source layer + bindings + resolution
configsys check                    # lint the merged config (repo + your file + includes + plugins)
configsys refresh                  # re-query latest versions from their sources
configsys dotfiles <status|capture>   # inspect / adopt your dotfiles (see Dotfiles below)
configsys plugin  <list|sync|add|remove|update|bless|unbless|trust|untrust|init|set-source>   # (see Plugins)
configsys report  [<name>]         # file an install-failure report (you approve the text first)
configsys request <name>           # ask upstream for full cross-platform support (coverage matrix)
configsys manpages <install|check> # install/check the man pages (configsys(1), configsys.hu(5))
```

`install`/`upgrade` take **`--force`** — for dotfiles, overwrite an un-adopted on-system file
(backing it up to `<name>.pre-configsys`) instead of refusing. Prefer `dotfiles capture` first.

Any `<name>` may be **`profile:<name>`**, which expands to that profile's components — e.g.
`configsys install profile:dev blender`. The `profile:` prefix disambiguates from a component of
the same name.

Global flags: `--pretend` (dry-run — prints commands, makes no changes and no network calls),
`--os <block>`, `--home <dir>`, `--config <file>` (the last three sandbox a run), `-v`/`-vv`
(stream load detail to stderr), `-q` (quiet).

Environment: `CONFIGSYS_OS` / `CONFIGSYS_OS_VERSION` (override the detected OS), `CONFIGSYS_HOME`
/ `CONFIGSYS_CONFIG` (relocate paths), `CONFIGSYS_NO_DISCOVER=1` (disable project discovery),
`CONFIGSYS_CWD`, `CONFIGSYS_ARCH`, `CONFIGSYS_GITHUB_TOKEN` (private-plugin auth). Full list in
`configsys -h`.

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

## Dotfiles

configsys treats your dotfiles as **yours** — it ships **no personal config templates** and will
not overwrite anything it didn't create. A `via: dotfiles` component only declares *where* a config
lives (its `src`→`dst` mapping); the **content** comes from your own store, resolved by a
search-path (first hit wins):

```
~/.config/configsys/dotfiles/<src>      (machine-local — where capture lands with no plugin)
<primary-plugin>/dotfiles/<src>         (portable — travels in your primary plugin)
<defining layer>/dotfiles/<src>         (a template, only if some layer ships one)
```

Two commands:

```console
$ ./configsys.sh dotfiles status     # every dotfile in your active profiles + its state
$ ./configsys.sh dotfiles capture    # adopt your existing on-system dotfiles into your store
```

- **`status`** shows each target as **linked** (managed), **adopted** (captured, not yet linked),
  **unmanaged** (a real on-system file you haven't adopted — *at risk*), **template** (a shipped
  template), or **empty** (declared, no content anywhere), plus where its managed source lives.
- **`capture`** copies your real on-system files *into* your store (your primary plugin's
  `dotfiles/` if you have one, else the local dir) so a later install links **your** content. It is
  read-only on the system side — it never modifies or deletes an on-system file. `--dry-run` to
  preview, `--force` to overwrite content already in the store.
- **Install won't clobber.** If a real on-system file exists that you haven't adopted, `install`
  **refuses** (with guidance to `capture`, or `--force` to back it up to `<name>.pre-configsys` and
  replace) — never a silent overwrite.

The natural flow: `dotfiles capture` your setup, then [`plugin init`](#your-config-as-a-plugin) to
package it into a portable personal plugin.

## Plugins

Plugins are git repos that add routing data (and new drivers) to the layer stack.
Declare them in your config and sync:

```console
$ ./configsys.sh plugin add "github:spacemeat/configsys-void" --ref v0.1.0
$ ./configsys.sh plugin list      # declared plugins + their sync/ABI status
$ ./configsys.sh plugin sync      # clone/fetch all declared plugins to their pinned refs
```

They clone to `~/.config/configsys/plugins/<name>/`, pin to a ref, and are ABI-gated so an
incompatible plugin degrades instead of breaking the tool. `add` / `remove` / `update` edit
your `plugins:` list **in place, preserving your comments**.

One plugin can be your **primary** — a personal config plugin that may set machine settings and
carry its own (transitive) plugins, so a fresh machine bootstraps from a one-line config.
`plugin bless <source>` designates an existing one; `plugin init` [creates one from your local
bits](#your-config-as-a-plugin); `plugin set-source <name> <source>` repoints it (e.g. local path →
`github:you/name` after you push); `plugin unbless` clears the designation.

A plugin can also ship **code** — a new driver (package manager) written in Python. Code runs
with your privileges during installs, so it stays inert until you approve its exact contents:

```console
$ ./configsys.sh plugin trust <name>     # binds to a content hash; any code change re-arms it
```

[`examples/examplos/`](examples/examplos/) is a complete, copy-able example — the fictional
**ExamplOS** distro with a `toybox` driver + an `examplos` OS block, walked through step by step
in [its WALKTHROUGH](examples/examplos/WALKTHROUGH.md). It's deliberately fictional so it never
rots. See [docs/plugins.md](docs/plugins.md) for the full model and the ABI a code plugin targets.

### Known plugins

Real, published plugins — each its own repo, `plugin add github:spacemeat/<name>`:

| Plugin | Adds | Kind |
| --- | --- | --- |
| [configsys-void](https://github.com/spacemeat/configsys-void) | Void Linux as a first-class OS — an `xbps` driver + a verified per-distro name map | code (trust-gated) |
| [configsys-proxmox](https://github.com/spacemeat/configsys-proxmox) | Proxmox VE (a Debian derivative) with `/etc/pve` detection + a `proxmox-admin` profile | data-only |
| [configsys-blender](https://github.com/spacemeat/configsys-blender) | Blender built from source (editor + `bpy`), GPU backends — a `blender-build` driver overriding base `blender` | code (trust-gated) |
| [configsys-kicad](https://github.com/spacemeat/configsys-kicad) | KiCad built from source (scripting + SPICE + 3D) — a `kicad-build` driver | code (trust-gated) |

The void and proxmox repos also carry name-existence sweeps (`test/run-name-sweep.sh`) that keep
their package names honest against a real container image as upstream repos roll.

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

`test/` also holds per-driver `integration_*.sh` checks and `run-*-in-podman.sh` harnesses for
dnf/pacman/aur/toolchains, plus `run-name-sweep-in-podman.sh` — a container sweep that verifies
every native package name configsys maps to still exists in each distro's repos (catching upstream
renames/removals). Deeper design docs live in [`docs/`](docs/): the routing model
([routing-model.md](docs/routing-model.md)), the plugin system ([plugins.md](docs/plugins.md)), and
the name sweep ([name-sweep-test.md](docs/name-sweep-test.md)).
