# configsys

One tool to bring a fresh OS install up to *your* setup — the same software, the same
versions, the same dotfiles — whether the machine runs Debian/Ubuntu/Pop!\_OS/Mint/Zorin,
Fedora/RHEL/Rocky/Alma/Oracle Linux/Amazon Linux, Arch/Manjaro/EndeavourOS/CachyOS, openSUSE,
Alpine, Void (glibc or musl), or an immutable system like Bazzite/Fedora Atomic — over 30 distros
in all, with more (Proxmox, …) available as plugins. Distro missing? `configsys request-os` asks
for it.

You describe **what** you want in a git-synced config; configsys works out **how** to get
it on *this* machine (apt vs dnf vs pacman, a Flatpak, an AppImage, a tarball, a Cargo
crate, a Nerd Font, a symlinked dotfile…) and gives you one interface — a slick, VIM-keyed
TUI — to install, upgrade, version-lock, and remove any of it, and to apply the rest of the
system's pending updates too, with no surprises about what's about to change.

```console
$ ./configsys.sh            # bootstrap + launch the TUI
$ ./configsys.sh inspect    # or run any subcommand non-interactively
```

## Quick start

configsys needs **git** and **python3 ≥ 3.10**; it sets up everything else itself.
(`humon`, the config parser, compiles from source, so a minimal install also needs a C compiler
and the Python headers — e.g. `xbps-install python3 python3-devel gcc` on Void, `apk add python3
python3-dev build-base` on Alpine. `configsys.sh` names the right packages if the build fails,
and on Debian/Ubuntu it installs the missing `python3.X-venv` package itself, with sudo.)

```console
$ git clone https://github.com/spacemeat/configsys ~/src/configsys
$ cd ~/src/configsys
$ ./configsys.sh
```

`configsys.sh` is the only bash — a tiny, idempotent shim: it checks for python ≥ 3.10
(set `PYTHON` to use a different interpreter), creates a repo-local `.venv`, installs
[`humon`](https://pypi.org/project/humon/) (the `.hu` config parser) and `packaging`, then
hands off to the python app. Re-running it is always safe.

On first run it writes a starter config to `~/.config/configsys/configsys.hu`, offers to
connect your [primary plugin](#glossary) if you already keep your config in one (press Enter to
skip), and opens the TUI:

1. Press `2` for the **Profiles** screen, browse the catalog, and **track** what this machine
   should have — `t` tracks the highlighted component, `T` a whole profile. On a machine that's
   already set up, `C` claims everything installed. (From a shell: `./configsys.sh picks add <name>`.)
2. Press `1` for the **Components** screen. `I` stages everything missing or outdated (`i` stages
   one row); `X` shows the batch and runs it once you confirm. If anything needs root, configsys
   asks for your sudo password once, up front, and the rest runs unattended.

> **Dry run:** put `--pretend` before the command — `./configsys.sh --pretend install btop` — to
> print the commands configsys *would* run instead of running them. Nothing is changed, probed
> or downloaded, so every component reads as missing, and nothing is saved — not even an edit to
> your config.

The rest of this README writes `configsys` for short. Until you install the `configsys-glue`
component (it's in the `user` profile), run `./configsys.sh` instead; once installed, `configsys`
— and its short alias `cfs` — works in every shell, wherever your clone lives. (Set
`CONFIGSYS_LAUNCHER` to run a different launcher.)

## Concepts

- **Component** — a thing you want by name: `neovim`, `btop`, `gcc-15`, `steam`. A named
  capability, resolved through `routes.hu` into one or more concrete **units**.
- **Binding** / **via** — one way to acquire a component in some context: `{ via: <driver>
  when: "<expr>"  …details }`. The `via:` names the install method; `when:` says where that
  method is *valid*.
- **Driver** — the code behind a `via:`: it performs one install mechanism behind a uniform set
  of operations (install, uninstall, upgrade, version, lock, …). configsys ships 35, and plugins
  can add more: system package managers
  **apt, dnf, pacman, aur, zypper, apk, xbps, brew, rpm-ostree**; distribution drivers **flatpak,
  snap, appImage, tarball, native-pkg-file** (an upstream `.deb`/`.rpm` file), **source, font,
  script**; the config drivers **dotfiles** and **glue**; language-ecosystem installers
  **cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install, pyenv, sdkman**; the **gcc /
  gcc-toolset / clang** toolchains; and post-install primitives **service** (systemd or runit) and
  **group** (usermod). `via: native` picks the right system manager per OS; `via: parts`
  aggregates.
- **Unit** — a resolved component + driver pair, keyed `driver\comp` (`apt\btop`,
  `flatpak\firefox`). It is the dedup identity: however many things want a component, its
  unit installs once.
- **Picks** — the components chosen for each machine. `picks:` in your config is a component ×
  machine matrix (`picks: { laptop: [ btop  neovim ] }`), and `machine:` names this box's column
  (default `this-machine`). This machine's picks are its install set — what `inspect` reports and
  the TUI keeps current — together with whatever they require.
- **Profile** — a **read-only browse lens** over the catalog (`user`, `dev-tools`, `net-tools`, …),
  defined in the repo's `config.hu`, by a plugin, or in your own config (a `profiles:` section of
  your own categories). Browsing a profile never changes your
  system; you pick from it. On the command line, `profile:<name>` expands to a profile's
  components (`configsys install profile:net-tools`).
- **Pin** — a light per-machine reroute (`pins:`): force a component's install method, or which
  provider satisfies a capability, without redefining anything — `v` in the TUI, or
  `configsys pin set steam flatpak`.
- **Dotfiles vs glue** — two config drivers. **Dotfiles** (`via: dotfiles`) manage an app's *own*
  config from your content store; **glue** (`via: glue`) is the small per-shell `conf.d` snippet
  (PATH, aliases, completions) a tool needs to be usable. Your own startup snippets are **user
  glue** (`configsys glue add <name>`), and `configsys glue override <component>` forks a tool's
  shipped glue for you to edit. See [Dotfiles and glue](#dotfiles-and-glue).
- **State** — the live system is the source of truth (dpkg/rpm/flatpak/marker files). A small
  **ledger** (`state.hu`, under `~/.config/configsys/`) records only what the system can't tell
  configsys — version locks, the files it manages, and an install **receipt** per unit, so an
  install stays findable even after routes stop offering its method — next to caches
  (discovered versions, last refresh, …). A version lock uses the package manager's own hold
  where it has one (`apt-mark hold`, `dnf versionlock`, `zypper addlock`, `xbps-pkgdb -m hold`,
  `brew pin`, `snap refresh --hold`, `flatpak mask`) and the ledger otherwise; pacman and apk
  upgrade everything together with no per-package hold, so there configsys declines to lock.
- **Status** — each component reads `installed`, `outdated`, `missing`, `locked`, `partial`, … or a
  **routing status** about its install method: `switch` when routes no longer offer the method it
  was installed with (a **stranded** install — installing it swaps methods; configsys never
  reroutes or removes it on its own), `dangling` when no method works on this OS, and `unmet` when
  only a disabled driver could install it.
- **System Updates** — pending OS updates for everything that *isn't* one of your components.
  `configsys updates` lists them by tier (kernel, core, standard, apps); `configsys upgrade
  --system` applies them with each package manager's own bulk upgrade (within the current
  release), and the TUI shows them as a group on the Components screen — so configsys can be your
  one updater.

## routes.hu — how components resolve

A component is a capability plus a list of context-selected **bindings**. Each binding
names its **driver** with `via:`, guards itself with an optional `when:` boolean
expression (over the OS lineage + CPU arch + declared facets), and carries driver-specific
details:

```hu
os: {
    linux:       { }
    glibc_linux: { using: linux        provides: glibc }
    debian:      { using: glibc_linux  native: apt }     // lineage + this OS's package manager
    ubuntu:      { using: debian }
    pop_os!:     { using: ubuntu }
    arch:        { using: glibc_linux  native: pacman }
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
    vulkan-dev: { install: [ { via: parts  parts: [ cpp-toolchain, make, vulkan-sdk ] } ] }
}
```

Key ideas:

- **`via: native`** resolves to this OS's package manager (apt, dnf, pacman, zypper, apk, xbps or
  brew) — one binding covers every distro. On KDE Linux, which has no system package manager,
  native bindings aren't candidates and a component falls through to Flatpak or another method.
  Chimera Linux is recognized but its package names aren't mapped yet, so very little installs
  there (configsys tells you so when it starts).
- **OS blocks inherit** via `using:`, forming a **lineage** (`pop_os! → ubuntu → debian →
  glibc_linux → linux`). configsys picks this machine's block from `/etc/os-release` (`ID=pop` →
  `pop_os!`). A binding with `when: "debian"` applies to the whole Debian family.
- **`when:`** states where a binding is *valid* — a boolean expression over the OS lineage
  (`"rhel"`, `"ubuntu < 23.04"`), CPU arch (`cpu: aarch64`), and any declared **facet**
  (`gpu:nvidia`; see [docs/facets.md](docs/facets.md)). It never expresses preference. Three more
  things decide validity: a binding's `cpu-names:` map lists the CPUs its download exists for; a
  driver is valid only where its own prerequisites can be installed (no snap methods where snapd
  can't be installed, no AppImages on musl systems or where FUSE 2 can't be installed, such as
  Fedora Atomic and KDE Linux), and it can also carry its own `when:` in the `drivers:` section
  (`brew` is valid only on glibc systems, `aur` only on Arch); and a driver you turn off with
  `disabled-drivers:` takes its bindings out of the running. When a driver rule takes out a
  method, `configsys where` says which one and why.
- **Choosing among valid methods** is a separate, deterministic order. A method marked
  **`standing: never-auto`** stays listed and pinnable but is never the automatic choice while any
  other method works here (snap methods are marked this way). Among the rest, the most specific
  `when:` wins; then a binding's **`standing:`** rank (an integer, higher wins); then the machine's
  **`driver-preference`** list (by default: native, aur, flatpak, snap, native-pkg-file,
  appImage, brew, tarball, source, script). Your own `driver-preference` only needs the drivers you
  care about — the ones it leaves out follow in the default order. An already-installed method is
  adopted over the default, and a **pin** beats everything.
- **Homebrew** (`via: brew`) is an ordinary method on glibc distros, and on Fedora Atomic it is the
  native package manager. It ranks after a native package, the AUR, a Flatpak, an upstream
  `.deb`/`.rpm` and an AppImage, but ahead of a tarball, an install script or a language toolchain
  (cargo, pipx, npm, …); since a snap is never the automatic choice, brew wins over a snap too. The
  first time a brew method is chosen, configsys installs Homebrew itself (the `homebrew`
  component); a component you already installed another way keeps that method.
- **`requires:`** is a hard dependency on a capability — another component, a version floor
  (`requires: { go: ">=1.21" }`), or a driver's own prerequisite (a `cargo` binding needs
  `cargo`). It installs first, in dependency order; if it can't resolve here, the component errors.
  **`suggests:`** is soft: pulled in when it can install here, silently skipped when it can't —
  how a tool attaches its `-dotfiles` and `-glue` companions.
- **`via: parts`** is a pure aggregator — a component that is just the union of its parts,
  with no unit of its own.
- **`scope: user|system`** — install scope. Scope-honoring drivers (appImage, flatpak,
  tarball, source, font, npm, gem, luarocks) default to `user`; set it per-binding or
  machine-wide via `scope:` in your config. User scope lands under your home (e.g. `~/apps`),
  system scope under `/opt` (with sudo); `dirs:` moves either base. Fixed-scope drivers
  (apt/dnf/pacman = system, dotfiles/cargo/pipx = user) ignore it.

Run `configsys where <name>` to see a component's bindings and which one resolves here.

Bindings can also **discover** versions instead of hard-coding them — from GitHub releases,
crates.io, PyPI, the AUR, Hackage, the Go module proxy, a web page plus a regex, or a `static:`
pin. Discovered versions are cached for a day (`configsys refresh` re-checks now), and `$VERSION`
and `$ARCH` fill in at install time — `$ARCH` through the binding's `cpu-names:` map
(`{ x86_64: amd64  aarch64: arm64 }`) when upstream spells CPUs its own way. A `via: dotfiles`
binding links an app's config into place from your own content store, so your edits land there
(and travel with your primary plugin) — see [Dotfiles and glue](#dotfiles-and-glue).

> **Full format reference:** [**docs/config-format.md**](docs/config-format.md) — also
> installed as the **`configsys.hu(5)`** man page (`configsys manpages install`). It is the
> single source for layers, machine settings, picks, profiles, the `when:` expression, method
> choice, version discovery, dotfiles/glue, and the driver list.

## Your config: `~/.config/configsys/configsys.hu`

Every `.hu` file is a **[layer](#glossary)**, overlaid section-by-section, lowest precedence first (a file you `include:` sits just below the file that includes it):

```
repo (routes.hu + config.hu)  <  plugins  <  primary plugin  <  ~/.config/configsys/configsys.hu
```

Your machine's file always wins:

```hu
{
    machine: laptop                  // which picks: column is THIS box (default: this-machine)

    picks: {                         // the install set, one list per machine (the matrix)
        laptop:  [ btop, neovim, gcc-15, gdb ]
        desktop: [ btop, neovim, steam, blender ]
    }

    // scope: system                 // default install scope for scope-honoring drivers

    // include: [ ~/src/myproject/configsys.hu ]   // pull in more component definitions

    // plugins: [ { source: "github:spacemeat/configsys-proxmox"  ref: v0.1.2 } ]

    // pins: { steam: flatpak }       // force a component's method (binding-pin) or a capability's provider (provider-pin)

    // components: { apod: {} }        // add or amend a component's bindings (they merge additively), or remove it with {}
}
```

- Lives at `$XDG_CONFIG_HOME/configsys/configsys.hu` — `~/.config/configsys/configsys.hu` when
  `XDG_CONFIG_HOME` is unset; `--config <file>` (or `CONFIGSYS_CONFIG`) uses another file. If it's
  missing, configsys writes a commented starter on first run (and, in a terminal, offers to point
  at your primary plugin). A legacy `~/configsys.hu` is moved there automatically.
- **`picks:` / `machine:`** — the component × machine matrix. `configsys picks add|rm|list`
  edits this box's column (or `--machine <name>` another's); `configsys machine list|show|add|
  rm|use` manages the columns. Picks are meant to travel: when you have a primary plugin, picks
  edits land there by default, and `configsys picks to-primary` moves any picks still in this
  file into it. The TUI **Profiles** screen (key `2`) is the same matrix, interactively.
- **`include:`** — pull component definitions from other files (definitions only; paths
  resolve against the including file's dir). Handy for a project's own components — for example
  a `via: parts` bundle of its build dependencies — which you then add to your picks. An included
  file can't set picks or other machine settings (`configsys check` warns if it tries). A path
  starting with `~` means your home.
- **Local plugins** — to let a source repo or an installed application add components to
  *this* box only, run `configsys plugin add <source> --local`. It's declared in this file, so it
  adds components (and OS blocks or drivers) here but can't change machine settings, and it
  doesn't travel to your other machines — without `--local`, a new plugin rides your primary
  plugin when you have one.

- **Machine settings** — everything else is optional. `configsys config show` lists each
  setting with its value and where it's set; `configsys config set|unset|move` (or the TUI
  **Config** screen, key `6`) edits it. Each setting has a nature: a *uniform* one lands in your
  primary plugin by default so it travels, a *machine* one stays in this file.
  Only this file and your primary plugin can set machine settings; an ordinary plugin or an
  included file that sets one is ignored, and `configsys check` says so.
  The full list, with defaults, is in [docs/config-format.md](docs/config-format.md).
- **Definitions** — like any layer, this file can also define `components:`, `profiles:` (your
  own browse categories — they never install anything), OS blocks (`os:`) and driver settings
  (`drivers:`). Here they win over every other layer, and they stay on this machine.
- **Retired keys** — the old `configs:`, `machines:` and `orphans-adopt-target:` no longer do
  anything (the install set is `picks:`); `configsys check` warns if your file still has them.

### Your config, as a plugin

To make your config portable, keep it in a **primary plugin**: an ordinary data-only plugin (a
git repo) that travels to every machine and may also carry your uniform machine settings. It
holds a `plugin.hu` manifest (its `name:`, `requires-abi:`, an optional `data:` list of its `.hu`
files, and any `plugins:` it brings along), one or more `.hu` files with your `components:`,
picks and settings, and your captured dotfiles and glue. Declare it in
`~/.config/configsys/configsys.hu`:

``` hu
{
    plugins: [
        { source: "github:you/my-configsys" ref: v0.1.0 primary: true }
    ]
}
```

Then run `./configsys.sh plugin sync`: it fetches your plugin and every plugin it declares. (Or
skip the hand edit: `configsys plugin bless github:you/my-configsys` declares it as primary and
syncs it in one step.)

**The fast path — `configsys plugin init`.** Rather than hand-building the plugin, get set up
locally first (capture your dotfiles, pick your components, amend routes), then let configsys
assemble the plugin for you:

```console
$ ./configsys.sh plugin init --dry-run  # see the plan first; then run it without --dry-run
$ ./configsys.sh plugin init            # or: plugin init <name>   (default: configsys-<user>)
```

With no primary plugin yet it **creates** one in `~/.config/configsys/plugins/<name>/`: it moves
in your captured dotfiles, your own glue snippets and glue overrides, and your `components:` and
`profiles:` sections (removing them from configsys.hu), lists your other declared plugins in its
manifest so they come along, `git init`s it, and makes it your primary plugin. If you already have
a primary, it moves your captured dotfiles and glue into it instead; your `components:` and
`profiles:` sections stay where they are (move them by hand). Picks, pins and settings move separately:
`configsys picks to-primary`, `configsys pin promote <name>`, `configsys config move <key>`. It's a real git repo you author in place; when you're ready to
share it, push it and repoint the source:

```console
$ cd ~/.config/configsys/plugins/configsys-<user>
$ git remote add origin git@github.com:you/configsys-<user>.git && git push -u origin main
$ ./configsys.sh plugin set-source configsys-<user> github:you/configsys-<user>
```

## Commands

Run a command as `./configsys.sh <command>` from your clone (or `.venv/bin/python -m configsys
<command>`). Pick the `configsys-glue` component and your shells also get a plain `configsys`
command, which the examples below use. With no command, the **TUI** opens. `configsys <command>
-h` shows per-command help; the full reference is the **`configsys(1)`** man page — `configsys
manpages install` puts it (and `configsys.hu(5)`) under `~/.local/share/man`.

```
configsys [tui]                    # interactive TUI (default; prints the inspect table when not on a terminal)
configsys inspect                  # install-state table for this machine's picks, then any issues
configsys install  <name>...       # install (pulls dependencies first, ordered) [--force] [--no-deps]
configsys install --picks [--yes]  # install every pick of this machine that isn't installed yet
configsys remove   <name>...       # uninstall
configsys upgrade  <name>...       # upgrade to latest [--force] [--no-deps]
configsys upgrade --picks [--yes]  # upgrade every outdated pick of this machine
configsys upgrade --system [--yes] # upgrade all system updates via each package manager's own bulk upgrade
configsys updates                  # list system updates: upgradable packages that aren't configsys components
configsys lock|unlock <name>...    # version-lock / unlock
configsys set-version <name> <ver> # install a specific version where the method can target one (can downgrade; `lock` holds it)
configsys fix-scope [<name>...]    # reconcile user/system scope mismatches (moves the install)

configsys picks   <list|add|rm|to-primary>   # this machine's picks — the install set [--machine]
configsys machine <list|show|add|rm|use>     # the picks matrix columns; `use` sets this box's machine
configsys profile <list|show>      # browse profiles — the repo's, your plugins', your own (read-only)
configsys disp    <list|get|set>   # component dispositions: seen / interesting / new
configsys orphans                  # installed software your picks don't cover [--adopt|--remove NAME] [--ignore GLOB]

configsys where <name> [-p]        # explain a component: source layer + bindings + resolution (-p: a profile)
configsys location <name> [--all]  # print a component's absolute install location
configsys versions <name>          # the version each install method would give here, flagging any behind the newest [--min V] [--refresh]
configsys pin <list|set|unset|promote>   # view/change install-method & provider pins
configsys config <show|get|set|unset|move>   # machine settings (scope, driver-preference, …)
configsys theme <show|list|set|unset|save|load>   # the TUI theme; save/load shareable theme plugins
configsys keys                     # the effective TUI keybindings (merged `keys:`)
configsys show <routes|config> [--path]   # print a shipped base file (or its location)
configsys check                    # lint the merged config (repo + your file + includes + plugins)
configsys refresh                  # re-query latest versions + refresh the native package index

configsys dotfiles <status|capture|staged|activate|discard>   # your dotfiles + staged glue (see below)
configsys glue    <add|override>   # your own shell snippets (add), or your editable copy of a component's glue (override)
configsys plugin  <list|sync|add|remove|update|bless|unbless|trust|untrust|init|set-source>   # declare, sync and trust plugins; bless or init your primary (see Plugins)
configsys report  [<name>] [--print]      # file an install-failure report (default: the last failure; you approve the text first)
configsys request <name> [--print]        # ask upstream for full cross-platform support (coverage matrix)
configsys request-os [--print]            # suggest this OS for support, or report that an update broke it (you approve first)
configsys manpages <install|status>       # install/check the man pages (configsys(1), configsys.hu(5)) [--prefix DIR]
```

**Syncing your picks.** `install --picks` installs everything this machine picks that isn't there
yet, and `upgrade --picks` upgrades every pick with a newer version. Both show the plan and ask
first (`--yes` skips the question), act only on this machine (not with `--machine` naming
another), and combine with any names you add. Picks that can't install here are skipped with a
one-line notice.

`install`/`upgrade` take **`--force`**: when a component's dotfiles would replace a real file you
haven't captured, back that file up to `<name>.pre-configsys` and replace it instead of refusing.
An earlier backup is never overwritten — the next one is `<name>.pre-configsys.1`, then `.2`, and
so on. Usually you want `dotfiles capture` first, so the link points at your own content.

**`set-version`** needs a method that can install a chosen version — a package manager or a
language toolchain, for example. Methods that install only the version their route names
(tarballs, AppImages, fonts, `.deb`/`.rpm` files, the AUR, …) refuse; pin a method that supports
versions first.

**Rebuilding a component.** `install <name>` runs even when the component is already present:
package managers re-run their install (a no-op if it's current), and a **`via: source`** component
always rebuilds from a clean checkout. So to pick up a recipe change at an unchanged version, or to
recover a half-finished build, just `install` it again. **`--no-deps`** runs the op on **only the
named component(s)** — no dependency installs and no `auto-tighten` upgrades — so you rebuild that
one thing without its whole dependency tree — e.g. `configsys install --no-deps blender-5.2`
(from the [configsys-blender](#known-plugins) plugin) rebuilds Blender alone, leaving its compiler
and CUDA toolkit as they are.

Any `<name>` may be **`profile:<name>`**, which expands to that profile's components — e.g.
`configsys install profile:finders btop`. The `profile:` prefix disambiguates from a component of
the same name. Profile members with no install method on this machine are skipped with a one-line
notice (a component you name yourself still errors). This installs the components without picking
them (so `configsys orphans` lists them); to make them this machine's picks, track them on the
Profiles screen (`T`) or with `configsys picks add`.

**`refresh`** re-queries the latest version of everything you've picked *and* refreshes the OS
package index (`apt-get update`, `dnf makecache`, …; sudo may prompt). On Arch the only safe
refresh is a full `pacman -Syu`, so `refresh` asks before running it. Every install or upgrade
batch — from the CLI or the TUI — also refreshes the index once up front when it includes a native
install or upgrade (the `refresh-before-execute` setting: `auto`, `always` or `never`). Arch is the
exception: there a refresh means a full upgrade, so a batch never runs one for you.

When the index refresh fails, configsys tells you why instead of leaving you with a raw apt or dnf
error. It names the likely cause (a missing or rotated signing key, a dead repository URL, …) and the
source file at fault, and says whether configsys wrote that file for one of your components or
something else added it. For a source configsys manages, it offers to re-fetch a rotated signing key
and retry. It also offers to remove sources it added for components you no longer pick. It never
touches a source it didn't create. Installs fail safe in the same spirit: a new apt/dnf source that
breaks the index is rolled back, and tarball and AppImage installs build to the side and swap into
place only when complete. A failed install's output is classified the same way: the cause is
shown in brackets after the error, and as **Likely cause** in `configsys report`.

**System updates.** `configsys updates` lists the packages your package managers (the OS's own,
flatpak, snap) report upgradable that aren't configsys components, grouped by tier — kernel, core,
standard, apps. `configsys upgrade --system` refreshes the index, shows that list, asks, then runs
each manager's own bulk upgrade (`--yes` skips the question). Held packages stay held, and it never
moves you to a new OS release. The TUI shows the same list as its **System Updates** group. On
Arch, install `pacman-contrib` for a live list: without its `checkupdates`, the list only knows
your last full `pacman -Syu`, and configsys says so under the list and on the `!` page.

Global flags (they go before the command): `--pretend` (dry run — prints the commands configsys
would run, including the queries that read install state, so the plan can list things you already
have; makes no changes and no network calls, and saves no config edits, locks, install records or
starter config; a download whose version isn't cached yet shows as `<latest release>` — `configsys
refresh` caches versions), `--os <block>`, `--home <dir>` and `--config <file>` (run as if on
another OS block, with another home directory or config file — together they sandbox a run),
`--machine <name>` (view and edit another machine's picks for this run; installs still act
on this box), `--color {auto,24bit,256,16,8,none}` / `--nocolor` (cap the TUI color depth),
`--effects {full,reduced,none}` (TUI motion), `--probe` (print the resolved color and motion mode,
and why, then exit), `--splash-linger` (keep the startup splash up until you press a key), `-v` /
`-vv` (stream load detail to stderr), `-q` / `--silent` (print nothing while loading, not even
errors; they still show on the TUI `!` page and in `inspect`'s issue list).

Environment variables (a flag in parentheses sets the same thing for one run):

| variable | effect |
| --- | --- |
| `CONFIGSYS_OS`, `CONFIGSYS_OS_VERSION` | use this OS block / version instead of detecting them (`--os` sets the block) |
| `CONFIGSYS_ARCH` | use this CPU instead of the detected one — for `cpu:` in `when:` and `$ARCH` in download names |
| `CONFIGSYS_FACET_<name>` | set a facet instead of detecting it, e.g. `CONFIGSYS_FACET_gpu=nvidia` |
| `CONFIGSYS_HOME` | the home directory every `~` path resolves under (`--home`) |
| `CONFIGSYS_CONFIG` | your config file (`--config`; default `~/.config/configsys/configsys.hu`) |
| `CONFIGSYS_STATE_DIR` | configsys's own directory — your config, the ledger, caches, synced plugins and local stores (default `$XDG_CONFIG_HOME/configsys`, else `~/.config/configsys`) |
| `CONFIGSYS_REPO` | the data directory holding the shipped `routes.hu` and `config.hu` (default: this clone) |
| `CONFIGSYS_USERSCOPE_DIR`, `CONFIGSYS_SYSTEMSCOPE_DIR` | base directories for user- and system-scope installs (default `~`, `/opt`) |
| `CONFIGSYS_APP_DIR`, `CONFIGSYS_SDK_DIR`, `CONFIGSYS_SRC_DIR` | app, SDK and source-tree directories under that base (default `apps`, `sdks`, `src`); these five win over the `dirs:` setting |
| `CONFIGSYS_COLOR`, `NO_COLOR` | cap the TUI color depth, same values as `--color`; any `NO_COLOR` value means monochrome |
| `CONFIGSYS_EFFECTS` | TUI motion: `full`, `reduced` or `none` (`--effects`) |
| `CONFIGSYS_SPLASH` | `always` shows the startup splash even on a fast load; `linger` also keeps it up until you press a key (`--splash-linger`) |
| `CONFIGSYS_NO_SPLASH` | set to anything to turn the startup splash off |
| `CONFIGSYS_GLUE_SHELLS` | comma-separated shells to set up glue for, instead of detecting them |
| `CONFIGSYS_PM` | `apt` or `dnf`: the package manager the gcc / clang toolchain drivers use (default: dnf if present, else apt) |
| `CONFIGSYS_GITHUB_TOKEN` (or `GITHUB_TOKEN`) | a GitHub API token for release lookups, lifting the anonymous rate limit |
| `CONFIGSYS_GIT_TOKEN` | a token for cloning private `github:` / `gitlab:` plugins over https (it is saved in the clone's `.git/config`) |
| `CONFIGSYS_LAUNCHER` | the launcher the shell `configsys` / `cfs` command (from `configsys-glue`) runs when no `configsys` is on your `PATH` (default: the clone configsys recorded when it set up your shells, else `~/src/configsys/configsys.sh`) |

`where` explains how a component resolves on this machine — every binding, the default here, and
why:

```console
$ ./configsys.sh where steam
steam
  defined in  routes.hu
  bindings
    - via native   when: pop_os!   name=steam:i386  foreign-arch=i386  <- default here
    - via native   when: ubuntu   name=steam-installer  repo-component=multiverse  foreign-arch=i386  (shadowed — pinning via:native resolves a more-specific binding above)
    - via native   when: debian and not ubuntu   name=steam-installer  repo-component=non-free  foreign-arch=i386
    - via native   when: arch   name=steam
    - via native   when: fedora   name=steam  requires=rpmfusion-nonfree
    - via native   when: opensuse   name=steam
    - via flatpak   when: always   hub=flathub  app=com.valvesoftware.Steam  (alternative here — pin to use)
    default: via native  (by most-specific when:)

  on pop_os! (x86_64):
    apt\steam  pkg steam:i386
```

A method ruled out by its driver's own `when:` says so — on Alpine, for example, `where btop`
marks its brew binding `(not a candidate: the brew driver isn't valid here (drivers: brew when:
glibc_linux))`.

## The TUI

Seven screens; press a number key (shown in the top chip bar) to switch:

1. **Components** — this machine's picks as a tree (profile → component → unit) with `driver`,
   `scope`, `status`, `installed` and `latest` columns. The three lines under the tree show the
   current component's description and capabilities, every install method it has here (the one
   in use in `[brackets]`), and its versions and install location. Stage ops on the current row or
   the selection (`space`; `a` selects everything in view): `i` install (or upgrade, if it's
   already there), `u` upgrade, `x` remove, `L` lock/unlock, and `I` / `U` for every tracked
   component. `X` shows the plan and runs it after you confirm. `v` picks an install method
   (writes a pin), `w` shows the full `where` explanation, `R` refreshes versions and the package
   index, and `c` unstages the current row (or the selection) and clears the selection. `M`
   cycles the view: `to-do` (only what needs action — the default) / `tracked` (every pick) /
   `installed+tracked` (plus installed components you haven't picked).
2. **Profiles** — the component × machine matrix. Browse the catalog by profile on the left
   (`!all` lists every component); the right side shows each component with a column per
   machine. Track a component (`t`, or `T` for the selection or the whole profile) on the target
   machines (`M`), or set one component's machines directly (`m`); mark it seen / interesting
   (`s` / `i`); pin its install method (`v`); show its `where` explanation (`w`); stage an
   uninstall (`x`); track everything already installed here (`C`); toggle the install-state overlay
   (`O`); and filter by attrs (`f`).
3. **Plugins** — declared plugins with their ref, ABI and trust status, plus a diff of what
   updating the selected one would change: add (`a`), remove (`x`), sync (`s`, `S` all), update
   (`u`, `U` all), bless / unbless your primary (`b` / `B`), trust (`t`, `T` all), set its ref (`v`).
4. **Glue** — shell snippets grouped by installed shell, your own user glue included; activate
   (`a`, or `A` for the whole shell's group) or deactivate (`x`).
5. **Dotfiles** — each managed config's state and where its content lives; manage / unmanage
   (`m` / `u`, `M` / `U` for all), move between your local store and your primary plugin
   (`s` / `S`).
6. **Config** — every machine setting, its value and where it's stored; `Enter` edits it, `m`
   moves it between local and your primary plugin, `t` opens the theme editor.
7. **Theme** — live palette, role and gradient editing (see [docs/theming.md](docs/theming.md)).

**Statuses.** The `status` column reads `installed`, `outdated` (a newer version is available),
`missing`, `locked`, `partial` (some of its units installed), `unsupported` (no driver for its
method here), `untrusted` (it needs a plugin you haven't trusted) or `error` — or, when the
problem is the install method itself, a routing status ([details](docs/stranded-installs.md)):
`switch` (installed via a method routes no longer offer here; install it to swap methods), `unmet`
(only a disabled driver could install it) or `dangling` (no method on this OS). `[R]` after a
latest version means upstream has released something newer than the version its recipe builds.
The badge at the left edge shows what's staged: `I` install, `U` upgrade, `X` remove, `L` lock,
`l` unlock, `*` mixed (its rows differ); `✗` marks a row whose last run failed.

**Header.** The Components header shows the OS block, `[PRETEND]` on a dry run, the view mode, how
long ago you last ran `refresh` (in the warning color after 30 days, or if never), `⚠ reboot advised`,
`⟳ N system updates`, and `⚠ N issues — press ! to view`.

**System Updates.** The last group in the tree lists what your package managers report upgradable
that isn't a configsys component, by tier (kernel, core, standard, apps; in the standard and apps
tiers, packages pulled in only as dependencies are dimmed). It applies in bulk: `i` or `u` anywhere in it stages the whole group,
and `X` runs each manager's own upgrade before your other staged ops.

**Issues (`!`).** From any screen, `!` lists every issue — config warnings, picks that can't route,
routing statuses, scope drift, version-floor advisories. It is also where you file upstream: `r`
reports a failed install, `f` requests full support for a component, `s` suggests this OS. You see
the full text before anything is sent.

Navigation is VIM-style everywhere: `j`/`k` and `h`/`l` (or the arrow keys), `g`/`G` for top and
bottom, `PgDn`/`PgUp` (or `ctrl-j`/`ctrl-k`) a page at a time, `Enter` to open, `Tab` to switch
panes (on Components it expands or collapses the whole tree), `/` find, `F` filter, `space` select,
`!` issues, `?` help, `q` quit (`Q` quits without asking). Keys are **rebindable** in a `keys:`
section of your config; `?` in the TUI and `configsys keys` show the effective bindings, which are
the authoritative list. A screen's own bindings come first, so a screen can reuse any key — even
`q`, `!`, `?` or a number key. When your rebind takes a key another action had, the key moves to
yours; `configsys check` points out each key taken that way, and any screen left with no way to
quit.

Colors, per-element styles, and the background gradient are fully configurable — see
[**docs/theming.md**](docs/theming.md).

## Dotfiles and glue

configsys treats your dotfiles as **yours** — it ships **no personal config templates** and will
not overwrite anything it didn't create. Two drivers share the work:

- **Dotfiles** (`via: dotfiles`) — an application's *own* config (`~/.config/htop/htoprc`, …). A
  component only declares *where* a config lives (its `src`→`dst` mapping); the **content**
  comes from your own store, resolved by a search-path (first hit wins):

  ```
  ~/.config/configsys/dotfiles/<component>.cfs/<src>   (machine-local — where capture lands with no primary plugin)
  <primary-plugin>/dotfiles/<component>.cfs/<src>      (portable — travels in your primary plugin)
  <defining layer>/dotfiles/<component>.cfs/<src>      (a template, only if some layer ships one)
  ```

  The `<component>.cfs/` **marker dir** (with a `manifest.hu` recording the src→dst layout and
  any exclude globs) tells configsys it owns that config — even before it holds any files. Install
  creates it; `capture` fills it.
- **Glue** (`via: glue`) — the per-shell snippet a tool needs to be usable (PATH, an alias like
  `fdfind`→`fd`, a `zoxide init`). Glue is *shipped* (in the repo's or a plugin's
  `glue/shell/<shell>/`), never captured: it materializes into a machine-local store and links into
  the uniform `~/.config/<shell>/conf.d/` of each **installed** shell (elvish/nushell inline it into
  the rc). Snippets load in a fixed order, set by a numbered [band](#glossary): configsys's own
  setup (`00-`), then each tool's glue (`50-`), then your user glue (`90-`), then your `99-user`
  snippet last. A tool `suggests:` its `<name>-glue` companion, and each companion requires
  `shell-glue`, which makes every installed shell load its `conf.d/`. Opt out per machine with
  `disabled-drivers: [ glue ]` (or `dotfiles`) to manage your shell startup files yourself.

Dotfiles commands:

```console
$ ./configsys.sh dotfiles status     # every dotfile and glue snippet your picks pull in, with its state
$ ./configsys.sh dotfiles capture    # adopt your existing on-system dotfiles into your store
```

- **`status`** shows each config as **managed** (linked to your content), **unmanaged** (needs
  action — an on-system file to `capture`, or stored content ready to link; marked `!`), or
  **no config** (nothing stored or on-system yet), and each glue snippet as **active**,
  **available**, **inactive**, or **changed** (the shipped snippet was updated — reinstall to pick
  it up). The SRC column shows where the content lives, or `→` where `capture` will put it. Your
  own user glue gets a table of its own.
- **`capture`** copies your real on-system files *into* your store (your primary plugin's
  `dotfiles/` if you have one, else the local dir) so a later install links **your** content. It is
  read-only on the system side — it never modifies or deletes an on-system file. Name components to
  capture only those. It asks before copying (`--yes` skips the prompt), `--dry-run` previews, and
  `--force` overwrites content already in the store. Secret-looking files in a captured folder
  (`.env`, `id_*`, `*.pem`, `*.key`, shell history, …) go on the config's `exclude:` list the first
  time, so they're skipped and git-ignored.
- **Install won't clobber.** A real on-system file you haven't captured is never silently
  replaced. With no stored content to link, `install` leaves it alone and reminds you to `capture`
  it; where a shipped template would replace it, `install` **refuses** (capture first, or pass
  `--force` to back it up to `<name>.pre-configsys` and replace it). When content you captured
  links over a real file, that file is backed up to `<name>.pre-configsys` first. A backup never
  overwrites an earlier one (the next is `.pre-configsys.1`, `.2`, …).
- **Installers don't scribble in your rc files.** When an installer (sdkman, nvm, rustup, …) edits
  `~/.bashrc`, `~/.zshrc` or another shell startup file, configsys puts the file back and
  **stages** the removed lines on this machine for you to review: `dotfiles staged` lists them,
  `dotfiles activate <component>` makes them your own [user glue](#glossary) (in your primary
  plugin if you have one; `--local` keeps them here), `dotfiles discard <component>` drops them.
  configsys's own loader lines in your rc files are left alone. Set `installer-shell-writes: allow`
  to turn this off, or list components in `installer-shell-writes-allow:` to let just those edit
  your rc files.

Glue commands:

```console
$ ./configsys.sh glue add aliases       # your own snippet, opened in $EDITOR
$ ./configsys.sh glue override zoxide   # copy a tool's shipped glue into your layer to edit
```

- **`glue add`** keeps your own aliases, env and functions in a `user.d/` folder; they load after
  component glue, so yours win. The first time configsys hooks up a shell it also creates a
  `99-user` snippet for you.
- **`glue override`** copies a tool's shipped glue into your layer, where it replaces the shipped
  one; `configsys check` tells you when the shipped version later changes.
- Both write to your primary plugin if you have one, so they travel to your other machines;
  `--local` keeps them on this machine, `--shell` picks the shell.

See [docs/shell-glue.md](docs/shell-glue.md) for how each shell loads its glue.

The natural flow: `dotfiles capture` your setup, then [`plugin init`](#your-config-as-a-plugin) to
package it into a portable personal plugin.

## Plugins

Plugins are git repos (or local folders) that add components, OS blocks, profiles, drivers or
startup splashes to the layer stack. Declare them in your config and sync:

```console
$ ./configsys.sh plugin add "github:spacemeat/configsys-proxmox" --ref v0.1.2
$ ./configsys.sh plugin list      # declared plugins + their sync/ABI status
$ ./configsys.sh plugin sync      # clone/fetch all declared plugins to their pinned refs
```

They clone to `~/.config/configsys/plugins/<name>/`, pin to a ref, and are ABI-gated so an
incompatible plugin degrades instead of breaking the tool. `add` / `remove` / `update` edit
your `plugins:` list **in place, preserving your comments**. If you have a primary plugin, `add`
declares the new plugin there so it travels to your other machines; `--local` keeps it on this
one. `update --latest` moves a plugin to its newest tag, and `--pin` locks it to the synced
content's sha256 (if the content stops matching, the plugin is set aside).

One plugin can be your **primary** — a personal config plugin that may set machine settings and
carry its own (transitive) plugins, so a fresh machine bootstraps from a one-line config.
`plugin bless <source>` designates an existing one; `plugin init` [creates one from your local
bits](#your-config-as-a-plugin); `plugin set-source <name> <source>` repoints it and its synced
clone (e.g. local path → `github:you/name` after you push); `plugin unbless` clears the designation.

A plugin can also ship **code** — Python that adds a driver (a new install method, such as a
package manager or a from-source build), a version source, a sync transport, or a startup splash.
Code runs with your privileges, so it stays inert until you approve the plugin's exact contents.
The same holds for a plugin whose *data* runs shell commands (`via: script` / `via: source`
recipes, apt source lines, shell glue, [facet](#glossary) detection probes):

```console
$ ./configsys.sh plugin trust <name>     # binds to a content hash; any change to the plugin re-arms it
```

`plugin list` shows which plugins are waiting for trust; `plugin untrust <name>` revokes it.

[`examples/examplos/`](examples/examplos/) is a complete, copy-able example — the fictional
**ExamplOS** distro with a `toybox` driver + an `examplos` OS block, walked through step by step
in [its WALKTHROUGH](examples/examplos/WALKTHROUGH.md). It's deliberately fictional so it never
rots. See [docs/plugins.md](docs/plugins.md) for the full model and the ABI a code plugin targets.

### Known plugins

Real, published plugins — each its own repo, `plugin add github:spacemeat/<name>`:

| Plugin | Adds | Kind |
| --- | --- | --- |
| [configsys-void](https://github.com/spacemeat/configsys-void) | A worked example of a real OS plugin (Void Linux: an `xbps` driver + a name map). Void support ships in core, so you don't need it to run Void — and loading it makes its `xbps` driver replace core's (`check` warns) | code (trust-gated) |
| [configsys-proxmox](https://github.com/spacemeat/configsys-proxmox) | Proxmox VE (a Debian derivative) with `/etc/pve` detection + a `proxmox-admin` profile | data-only |
| [configsys-blender](https://github.com/spacemeat/configsys-blender) | Blender built from source (editor + `bpy`), one component per version (`blender-4.3`, `blender-5.2`) with pinnable GPU flavors — a `blender-build` driver; base `blender` stays the default | code (trust-gated) |
| [configsys-kicad](https://github.com/spacemeat/configsys-kicad) | KiCad built from source (scripting + SPICE + 3D) — a `kicad-build` driver | code (trust-gated) |
| [configsys-source](https://github.com/spacemeat/configsys-source) | A build-from-source (`via: source`) method for most buildable CLI/TUI tools and libraries | data, with recipes (trust-gated) |
| [configsys-opencv](https://github.com/spacemeat/configsys-opencv) | OpenCV built from source with optional CUDA / HIP — an `opencv-build` driver adding methods to base `opencv` | code (trust-gated) |
| [configsys-versions](https://github.com/spacemeat/configsys-versions) | Up-to-date minimum toolchain versions for from-source builds (a Rust or Go floor), refreshed daily without a release; configsys-source brings it along | data-only |
| [configsys-bigdata](https://github.com/spacemeat/configsys-bigdata) | The Apache Hadoop stack (Hadoop, Hive, HBase, Sqoop, Spark, Flink) with shell glue that wires them together | data, with glue (trust-gated) |
| [configsys-user](https://github.com/spacemeat/configsys-user) | The author's own primary plugin — a real example of a personal config: picks, uniform settings, components, captured dotfiles, and the plugins it brings along | data-only (a primary) |
| [configsys-neovim](https://github.com/spacemeat/configsys-neovim) | Neovim built from source, for musl systems (Void musl, Alpine) where the AppImage can't run | data, with recipes (trust-gated) |
| [configsys-splash-ocean](https://github.com/spacemeat/configsys-splash-ocean), [-blocks](https://github.com/spacemeat/configsys-splash-blocks), [-maze](https://github.com/spacemeat/configsys-splash-maze), [-cityscape](https://github.com/spacemeat/configsys-splash-cityscape) | Startup splash animations — choose one with the `splash:` setting | code (trust-gated) |

The void and proxmox repos also carry name-existence sweeps (`test/run-name-sweep.sh`) that keep
their package names honest against a real container image as upstream repos roll.

## Design notes

- **No surprises.** Browsing a profile or picking a component never changes your system;
  installs are always an explicit, reviewable action, and `check` lints the whole merged config
  without touching anything.
- **Resilient.** A malformed plugin or single component surfaces as an
  error row — it can't brick the tool.
- **One term, one meaning.** Everything about *how* software is acquired is a **driver**;
  everything about *what* you want is a **component**; what *this machine* gets is its
  **picks**.
- **No doubling up, no stranding.** Switching a component's install method removes the old
  install first, and a route change never strands an install silently — it shows as `switch`
  until you act.
- **Trust by content.** Plugin code, and plugin data that runs shell commands, runs only after
  you approve its exact content.

## Development

```console
$ .venv/bin/python -m pytest test/   # fast unit suite (mocked runner/fetch)
$ bash test/run-in-podman.sh         # real apt lifecycle in a disposable container
$ bash test/run-flatpak-in-podman.sh # gated: real flatpak --user lifecycle (slow, networked)
```

`test/` also holds per-driver `integration_*.sh` checks and `run-*-in-podman.sh` harnesses for
dnf, pacman (with AUR), zypper, xbps, clang and the language toolchains, plus
`run-name-sweep-in-podman.sh` — a container sweep that checks every native package name configsys
maps to still exists in a representative distro for each package manager (apt, dnf, pacman,
zypper, apk, xbps), catching upstream renames and removals; Homebrew formula names are checked by
`tools/compaudit.py` instead. The design docs cover routing
([routing-model.md](docs/routing-model.md)), the plugin system ([plugins.md](docs/plugins.md)), and
the name sweep ([name-sweep-test.md](docs/name-sweep-test.md)).

Routing changes are gated by a golden snapshot, `test/routing_golden.json` (how every component
resolves on 13 reference machines). After an intentional change, regenerate it and review the diff:

```console
$ CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py -q
```

Maintenance tools live in `tools/`: `gen_manpages.py` regenerates the man pages (`--check` is run
by the test suite), `namesweep.py` and `versionsweep.py` are the networked package-name and
version-floor sweeps, `regsweep.py` finds crates.io / PyPI / npm / Flathub methods a component
could add, `compaudit.py` probes components for upstream drift, and `docaudit.py`
checks the docs against the code and renders the Glossary below from `docs/glossary.hu`. If you
use Claude Code, `.claude/skills/` has playbooks for the common jobs: `/add-component`,
`/update-component`, `/add-driver` and `/update-docs`; `test/test_driver_inventory.py` fails until a
new driver is wired through everything `/add-driver` lists.

## Glossary

<!-- glossary:begin — generated from docs/glossary.hu by `tools/docaudit.py glossary --write`;
edit that file, not this section -->

- **ABI** (`requires-abi:`) — The plugin interface version. A plugin declares the ABI it needs; configsys skips (never loads) a plugin it isn't compatible with. *See also:* **plugin**.
- **also-present** — Another install of the same component via a different method than the one configsys manages — shown so you can adopt it (pin) or swap it out. *See also:* **swap**, **stranded**.
- **attrs** (`attrs:`) — Free-form tags on a component for filtering (`CLI`, `GUI`, `FOSS`, `proprietary`, `tele`, `electron`, …), independent of profiles. *See also:* **component**, **profile**.
- **band** (`00-` / `50-` / `90-` / `99-`) — The load-order prefix on each conf.d link: shells load conf.d in name order, so configsys's own setup (`00-`) comes first, then component glue (`50-`), then your user glue (`90-`), then your `99-user` snippet. A snippet already named `NN-…` keeps its prefix. *See also:* **conf.d**, **glue**, **user-glue**.
- **binding** (an entry in a component's `install:` list) — One way to install a component on some set of machines: `{ via: <driver>  when: "…"  …fields }`. A component usually has several; configsys picks one per machine. *See also:* **via**, **when**, **standing**, **candidate**.
- **bless** (`configsys plugin bless`) — Making a declared plugin your primary plugin (TUI Plugins `b`); unbless clears it. *See also:* **primary-plugin**.
- **candidate** — A binding whose `when:` holds on this machine, whose driver isn't disabled or gated out here (its own prerequisites can't be installed here, or a `drivers:` block's own `when:` excludes this machine), and that covers this CPU. Among the candidates, configsys picks the default; the rest stay pinnable. *See also:* **binding**, **specificity**, **standing**, **pin**.
- **capability** — A named feature a component offers or needs (`provides:` / `requires:`), optionally versioned (`provides: { jdk: 21 }`). Resolution satisfies a `requires:` with a component that provides it. *See also:* **requires**, **suggests**, **provider**.
- **capture** (`configsys dotfiles capture`) — Adopting config files that already exist on your machine into your content store, so configsys manages and syncs them from then on. *See also:* **dotfiles**, **content-store**.
- **claim** — Tracking every component already installed on this box onto a machine's picks in one step — adopting an existing system into configsys (TUI Profiles `C`). *See also:* **track**, **picks**.
- **companion** — A small helper component named after its parent — `<name>-dotfiles` (its config), `<name>-glue` (its shell setup), `<name>-service` (start its daemon), `<name>-group` (add you to its group). *See also:* **dotfiles**, **glue**, **suggests**.
- **component** — One installable thing, by name (`ripgrep`, `firefox`, `jdk-21`): a capability plus the list of ways to install it (its bindings). Defined in routes.hu or a plugin. *See also:* **binding**, **capability**, **unit**. *Not:* “package”, “app”.
- **conf.d** — The per-shell folder (`~/.config/<shell>/conf.d/`) every glue snippet is linked into; shell-glue makes each installed shell load it. *See also:* **glue**, **shell-glue**, **band**.
- **content-store** — Where your captured dotfiles live — your primary plugin if you have one, else a local store — one `<name>-dotfiles.cfs/` folder (with a manifest) per app. *See also:* **dotfiles**, **capture**.
- **cpu-names** (`cpu-names:`) — A binding's map from CPU to the spelling upstream uses in file names (`{ x86_64: amd64  aarch64: arm64 }`): `$ARCH` expands through it, and its keys are the CPUs the download exists for. *See also:* **binding**.
- **detection** — configsys reading what's already installed and adopting it: an installed method or provider beats the bare default (precedence: pin > detected > default). *See also:* **pin**, **also-present**.
- **disposition** (`dispositions:`) — Your triage mark on a catalog component — `seen` or `interesting` — kept per machine; it never installs anything. *See also:* **picks**.
- **dotfiles** (`via: dotfiles`) — An app's own configuration (its `~/.config/<app>` files), kept in your content store and linked into place. Usually captured from your machine, not shipped. *See also:* **glue**, **capture**, **content-store**, **companion**. *Not:* “shell config”.
- **driver** — The code that performs one install mechanism behind a uniform set of operations (install, uninstall, upgrade, version, lock, …). Each `via:` value names one driver; plugins can add more. *See also:* **via**. *Not:* “backend”, “provider”.
- **driver-preference** (`driver-preference:`) — A machine setting: the order of install mechanisms used to choose among equally specific candidates (default: native, aur, flatpak, snap, native-pkg-file, appImage, brew, tarball, source, script). Your list only needs the drivers you care about — the ones it leaves out follow in the default order. *See also:* **standing**, **specificity**.
- **facet** — A detected machine trait beyond the OS — CPU, GPU, and so on — usable in `when:` (`cpu: x86_64`). *See also:* **when**.
- **glue** (`via: glue`) — A small shipped shell snippet that wires a tool into your shells (PATH, aliases, init hooks), installed into each shell's `conf.d`. Distinct from dotfiles: glue is shipped, not captured. *See also:* **dotfiles**, **shell-glue**.
- **golden** (test/routing_golden.json) — A frozen snapshot of how every component resolves on 13 reference machines; a test fails if routing changes unexpectedly.
- **install-dirs** (`dirs:`) — Where user-space installs land — the `user`, `system`, `app`, `sdk` and `src` directories; set in your config (environment variables override). *See also:* **scope**.
- **install-overlay** (`install-overlay:`) — The Profiles screen's installed-state layer (an installed column, underlines, orphan colors); `O` toggles it. *See also:* **orphan**.
- **issues** — The diagnostics list — the TUI `!` page, `configsys check`, and the end of `configsys inspect`: config warnings, picks that can't route, routing statuses, scope drift, version-floor advisories. *See also:* **routing-status**.
- **layer** — One config/routes file in the stack configsys merges, lowest first: repo < plugins < primary plugin < your user config (includes sit below the file that includes them). *See also:* **plugin**, **primary-plugin**.
- **ledger** (`state.hu`) — configsys' small local state file: version locks, managed markers and install receipts. The system itself stays the source of truth for what's installed. *See also:* **receipt**, **lock**.
- **lineage** — An OS block's chain of parents (`pop_os!` → ubuntu → debian → glibc_linux → linux). A bare `when:` atom matches a block and all its descendants. *See also:* **OS-block**.
- **lock** — Holding a component at its current version: the package manager's own hold where it has one, else recorded in the ledger. *See also:* **ledger**.
- **machine** (`machine:`) — Which picks column this box is (default `this-machine`). `configsys machine …` lists, adds and switches them. *See also:* **picks**.
- **name-sweep** — A container test that checks every native package name configsys would install really exists in each distro's repos.
- **native** (`via: native`) — The OS's own package manager, whichever it is here (apt, dnf, pacman, zypper, apk, xbps, brew). A `native` binding installs through it; its package name can differ per manager (`name: { apt: …  dnf: … }`). *See also:* **via**, **OS-block**.
- **never-auto** (`standing: never-auto`) — Marks a binding (or provider) as valid and pinnable but never the automatic choice — used where it's the only method, or when you pin it. *See also:* **standing**, **pin**.
- **orphan** — Something installed that this machine's picks don't account for, but that configsys could manage — listed so you can track it, remove it, or ignore it. *See also:* **picks**.
- **OS-block** (an entry in routes.hu `os:`) — configsys' model of a distro: its parent (`using:`), package manager (`native:`), version numbering (`scale-root:`) and built-in capabilities (`provides:`). `when:` atoms name these. *See also:* **lineage**, **scale-root**, **native**. *Not:* “distro-profile”.
- **parts** (`via: parts`) — A component that is just the union of other components (an aggregate): installing it installs its parts; it has no install of its own. *See also:* **component**, **via**.
- **picks** (`picks:`) — What each machine installs: a component × machine matrix in your config (`picks: { <machine>: [ components ] }`). This machine's column is its install set. *See also:* **machine**, **profile**. *Not:* “active profiles”, “configs”.
- **pin** (`pins:`) — A per-machine override at top precedence: a binding-pin forces a component's method (`pins: { yazi: tarball }`), a provider-pin forces which component satisfies a capability. *See also:* **candidate**, **provider**.
- **plugin** — A git repo (or local dir) that adds components, OS blocks, profiles, drivers or splash screens; declared in `plugins:` and fetched with `configsys plugin sync`. A data plugin ships only `.hu` files; a code plugin also ships Python. Code — and data that runs shell commands, like build recipes or shell glue — loads only after you trust it. *See also:* **layer**, **primary-plugin**, **trust**, **transitive-plugin**.
- **primary-plugin** (`primary: true`) — Your personal plugin: travels with you across machines and may also set machine settings that should be uniform. *See also:* **plugin**, **setting-nature**.
- **profile** — A named, read-only list of components for BROWSING (`terminal`, `dev-tools`, `dam-tools`) — shipped by the repo or a plugin, or written in your own config as your own category. Profiles never install anything themselves; you pick from them. *See also:* **picks**, **subprofile**. *Not:* “install set”.
- **provider** — A component that `provides:` a capability another component `requires:` (e.g. `jdk-21` provides `jdk`). *See also:* **capability**, **pin**.
- **receipt** — The ledger's record of each unit configsys installed (method, package name, fields), so the install stays findable and removable after routes stop offering that method. *See also:* **stranded**, **ledger**.
- **recipe-pin** (`[R]`) — A method that builds a fixed version its route pins (for example a from-source build). `[R]` means upstream has released something newer; upgrading rebuilds the same pinned version — reaching the new release takes a route change. *See also:* **status**.
- **refresh** (`configsys refresh`) — Re-checking upstream versions and refreshing the OS package index. Where the only safe refresh is a full system upgrade (Arch's `pacman -Syu`), configsys asks before running it.
- **requires** (`requires:`) — A HARD dependency: the capability must resolve here or the component errors. *See also:* **suggests**, **capability**.
- **resolution** — Turning wanted component names into concrete units for THIS machine: pick a binding per component, close its requires/suggests, dedupe. *See also:* **unit**, **candidate**.
- **routing-status** — A component status about its install METHOD, shown instead of the version status: `switch` (stranded install), `unmet` (only a disabled driver could install it), `dangling` (no method on this OS). *See also:* **stranded**, **status**.
- **scale-root** (`scale-root: true`) — Marks an OS block that numbers its own releases (Mint 21, Zorin 18), so a versioned parent atom like `ubuntu >= 24.04` doesn't misread its version. *See also:* **OS-block**.
- **scope** (`scope:`) — Where a user-space install lands: `user` (your home, e.g. `~/apps`) or `system` (`/opt`, needs sudo). Distro package managers are always system; Homebrew, in its user-owned prefix, is always user.
- **setting-nature** — Whether a machine setting is uniform (belongs in your primary plugin, same everywhere) or machine-local (belongs in this box's config). `configsys config move` carries one across. *See also:* **primary-plugin**.
- **shell-glue** — The component that makes every installed shell load its `~/.config/<shell>/conf.d/` snippets — the substrate every `-glue` companion needs. *See also:* **glue**.
- **shell-writes-guard** (`installer-shell-writes:`) — Protection against installers that edit your shell startup files: by default configsys reverts such edits and keeps the removed lines as inactive glue you can review. *See also:* **glue**.
- **specificity** — Tie-breaking among candidates: a binding with a narrower `when:` (e.g. `rhel`) beats a broader one, before any preference applies. *See also:* **candidate**, **standing**, **driver-preference**.
- **staged** — In the TUI, an operation marked to run (install, upgrade, remove, …) but not yet executed; `X` runs everything staged after a confirmation. *See also:* **staged-glue**.
- **staged-glue** (`configsys dotfiles staged`) — Shell startup lines an installer tried to add, reverted by the shell-writes guard and held, inactive, on this machine until you activate them (they become your user glue) or discard them. Not the same as a staged TUI operation. *See also:* **shell-writes-guard**, **user-glue**, **staged**.
- **standing** (`standing:`) — The one preference knob on a binding, driver or provider: `never-auto` (listed and pinnable, never chosen automatically) or an integer rank (higher wins). *See also:* **never-auto**, **driver-preference**, **specificity**.
- **status** — A component row's state (TUI and `configsys inspect`): `installed`, `outdated` (newer available), `missing`, `locked`, `partial` (some of its units installed), `unsupported` (configsys has no driver for its method here), `untrusted` (needs a plugin you haven't trusted), `error`, or a routing status. *See also:* **routing-status**, **lock**, **recipe-pin**.
- **stranded** — Installed via a method routes no longer offer on this machine (removed, gated out, or its driver disabled). Shown as the `switch` status; installing the component swaps it out. *See also:* **routing-status**, **receipt**, **swap**.
- **subprofile** — A profile included in another with `+name` (and removable with `~name`). *See also:* **profile**.
- **suggests** (`suggests:`) — A SOFT dependency: pulled in when it can be installed here, silently skipped when it can't (how a tool attaches its optional `-dotfiles` / `-glue` companions). *See also:* **requires**, **companion**.
- **swap** — Switching a component's method: the old install is removed first, then the new one installs — never both at once. *See also:* **also-present**, **pin**.
- **system-updates** (`configsys updates`, `upgrade --system`) — The OS packages with pending updates that aren't configsys components — shown and applied in bulk, so configsys can be your one updater. *See also:* **tier**.
- **tier** — How System Updates groups pending OS updates, most fundamental first: kernel, core, standard, apps. *See also:* **system-updates**.
- **top-config** (`~/.config/configsys/configsys.hu`) — This machine's own config file — the highest layer, never shared. Machine-local settings and `--local` edits land here. *See also:* **layer**, **setting-nature**, **primary-plugin**.
- **track** — Adding a component to a machine's picks (TUI Profiles `T` / `t`, or `configsys picks add`). Tracked components are that machine's install set. *See also:* **picks**, **claim**.
- **transitive-plugin** — A plugin declared inside another plugin's manifest; it is synced and loaded along with the plugin that declares it. *See also:* **plugin**.
- **trust** (`configsys plugin trust`) — Approving a plugin's exact content (pinned by hash) before configsys runs its code or command-carrying data. *See also:* **plugin**.
- **uninstall-queue** (`uninstall:`) — Removals you've staged on this machine for installs outside its picks (the TUI's `!uninstall` view); kept machine-local until you run them. *See also:* **orphan**, **picks**.
- **unit** (unit key `driver\comp`) — One concrete install the drivers act on — a component bound to a driver (`apt\ripgrep`, `flatpak\gimp`). Two requests resolving to the same unit install it once. *See also:* **resolution**, **component**.
- **user-glue** (`configsys glue add`) — Your own shell startup snippets, not tied to any component, kept in a `user.d` folder and loaded after component glue (so yours win); a `99-user` snippet is scaffolded for you. *See also:* **glue**, **conf.d**, **band**.
- **version-floor** — A hard minimum version a component needs from a capability (`requires: { go: ">=1.21" }`); configsys surfaces methods that cannot meet it rather than silently upgrading. *See also:* **capability**.
- **via** (`via:`) — The install mechanism a binding uses — names a driver (`apt`, `flatpak`, `tarball`, `cargo`, …), or `native` (this OS's package manager) or `parts` (an aggregate). *See also:* **driver**, **native**.
- **view-mode** — The Components screen's filter, cycled with `M`: to-do (what needs action — the default), tracked (every pick), installed+tracked (also installed components you haven't picked). *See also:* **picks**, **track**.
- **when** (`when:`) — A binding's validity condition — an expression over the OS (`debian`, `ubuntu >= 24.04`), CPU and facets. It says only whether the method WORKS here, never whether it is preferred. *See also:* **binding**, **standing**, **specificity**.

**Retired terms** — you may still meet these in older docs (`docs/done/`) or configs:

| retired | use instead | |
|---|---|---|
| `active profiles` | this machine's picks | profiles are browse-only; picks are the install set |
| `bash-dotfiles` | `shell-glue` (a `-glue` companion) | shell setup moved from dotfiles to the glue driver |
| `candidate-only:` | `standing: never-auto` | standing is the one preference knob |
| `configs:` | `picks:` | the install set is this machine's picks column, not a list of active profiles |
| `discovered layer` | a machine-level plugin (`configsys plugin add <dir> --local`) | CWD project discovery was removed |
| `machines:` | `picks:` (each key is a machine) | picks is the machine registry |
| `opt-in:` | `standing: never-auto` | standing is the one preference knob |
| `orphans-adopt-target:` | (adopting an orphan picks it) | no staging profile any more |
| `prefer:` | `standing: <integer>` | standing is the one preference knob |
| `RouteResolver` | the capability resolver (resolve.py) | the v1 resolver was deleted |

<!-- glossary:end -->
