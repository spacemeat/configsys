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
TUI. Browse the catalog on the **Profiles** screen and **pick** the components this machine
should have (`t` tracks one; or `configsys picks add <name>`), then inspect and act on the
**Components** screen.

> Dry run: pass `--pretend` to print the commands configsys *would* run instead of running
> them.

## Concepts

- **Component** — a thing you want by name: `neovim`, `btop`, `gcc-15`, `steam`. A named
  capability, resolved through `routes.hu` into one or more concrete **units**.
- **Binding** / **via** — one way to acquire a component in some context: `{ via: <driver>
  when: "<expr>"  …details }`. The `via:` names the install method; `when:` says where that
  method is *valid*.
- **Driver** — the code behind a `via:`: it installs/queries/removes one *class* of software
  behind a uniform op set (get_version / get_latest / is_locked / install / uninstall /
  upgrade / set_version / lock / unlock / location). Ships ~35: system package managers
  **apt, dnf, pacman, aur, zypper, apk, brew, rpm-ostree**; distribution drivers **flatpak,
  snap, appImage, tarball, native-pkg-file** (an upstream `.deb`/`.rpm` file), **source, font,
  script**; the config drivers **dotfiles** and **glue**; language-ecosystem installers
  **cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install, pyenv, sdkman**; the **gcc /
  gcc-toolset / clang** toolchains; and post-install primitives **service** (systemd) and
  **group** (usermod). `via: native` picks the right system manager per OS; `via: parts`
  aggregates.
- **Unit** — a resolved component + driver pair, keyed `driver\comp` (`apt\btop`,
  `flatpak\firefox`). It is the dedup identity: however many things want a component, its
  unit installs once.
- **Pick** — a component you've selected for a machine. The per-machine `picks:` lists in your
  config ARE the install set: a machine installs exactly what is picked for it.
- **Profile** — a **read-only browse lens** over the catalog (`user`, `dev`, `networking`, …),
  defined in the repo's `config.hu` or by a plugin. Browsing a profile never changes your
  system; you pick from it. (`profile:<name>` still expands on the command line.)
- **Pin** — a light per-machine reroute (`pins:`): force a component's install method, or which
  provider satisfies a capability, without redefining anything.
- **Dotfiles vs glue** — two config drivers. **Dotfiles** (`via: dotfiles`) manage an app's *own*
  config from your content store; **glue** (`via: glue`) is the small per-shell `conf.d` snippet
  (PATH, aliases, completions) a tool needs to be usable. See [Dotfiles and glue](#dotfiles-and-glue).
- **State** — the live system is the source of truth (dpkg/rpm/flatpak/marker files); a
  small ledger plus caches under `~/.config/configsys/` store only lock *intent* and configsys
  bookkeeping (version caches, last refresh, …). Version-lock uses native holds where they exist
  (`apt-mark`, `dnf versionlock`, `flatpak mask`).

## routes.hu — how components resolve

A component is a capability plus a list of context-selected **bindings**. Each binding
names its **driver** with `via:`, guards itself with an optional `when:` boolean
expression (over the OS lineage + CPU arch + declared facets), and carries driver-specific
details:

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
- **`when:`** states where a binding is *valid* — a boolean expression over the OS lineage
  (`"rhel"`, `"ubuntu < 23.04"`), CPU arch (`cpu: aarch64`), and any declared **facet**
  (see docs/facets.md). It never expresses preference.
- **Choosing among valid methods** is a separate, deterministic order: the most specific
  `when:` wins; then a binding's **`standing:`** rank (an integer; `standing: never-auto`
  keeps a method listed and pinnable but never the auto-default); then the machine's
  **`driver-preference`** list. An already-installed method is adopted over the default, and a
  **pin** beats everything.
- **`requires:`** pulls in capabilities (another component, or a driver's prerequisites)
  first, dependency-ordered; **`suggests:`** does the same softly (skipped if unresolvable).
- **`via: parts`** is a pure aggregator — a component that is just the union of its parts,
  with no unit of its own.
- **`scope: user|system`** — install scope. Scope-honoring drivers (appImage, flatpak,
  tarball, source, font, npm, gem, luarocks) default to `user`; set it per-binding or
  machine-wide via `scope:` in your config. Fixed-scope drivers (apt/dnf/pacman = system,
  dotfiles/cargo/pipx = user) ignore it.

Run `configsys where <name>` to see a component's bindings and which one resolves here.

Bindings can also **discover** versions (GitHub / URL / static pins, with `$VERSION`/`$ARCH`
filled in at install time and cached), manage **dotfiles** (symlinked into place from your own
content store so edits flow back to git — see [Dotfiles and glue](#dotfiles-and-glue)), and
target any of the drivers above.

> **Full format reference:** [**docs/config-format.md**](docs/config-format.md) — also
> installed as the **`configsys.hu(5)`** man page (`configsys manpages install`). It is the
> single source for layers, machine settings, picks, profiles, the `when:` expression, method
> choice, version discovery, dotfiles/glue, and the driver list.

## Your config: `~/.config/configsys/configsys.hu`

Every `.hu` file is a **layer**, overlaid section-by-section, lowest precedence first:

```
repo (routes.hu + config.hu)  <  plugins  <  primary  <  ~/.config/configsys/configsys.hu
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

    // plugins: [ { source: "github:spacemeat/configsys-void"  ref: v0.1.0 } ]

    // pins: { steam: flatpak }       // force a driver (binding-pin) or a provider

    // components: { apod: {} }        // amend a route (bindings merge additively), or remove with {}
}
```

- Lives under `$XDG_CONFIG_HOME` (defaults to `~/.config/configsys/`). A legacy
  `~/configsys.hu` is migrated automatically on first run.
- **`picks:` / `machine:`** — the component × machine matrix. `configsys picks add|rm|list`
  edits this box's column (or `--machine <name>` another's); `configsys machine list|show|add|
  rm|use` manages the columns; `picks to-primary` moves your picks into your primary plugin so
  they travel. The TUI **Profiles** screen is the same matrix, interactively.
- **`include:`** — pull component definitions from other files (definitions only; paths
  resolve against the including file's dir). Handy for per-project dependency sets.
- **Local plugins** — to let a source repo or app install add components to *this* box only,
  declare it as a plugin in your top config: `configsys plugin add <source> --local` (a
  `plugin`-role layer here, not carried to your other machines the way a `primary` plugin is).

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
locally first (capture your dotfiles, pick your components, amend routes), then let configsys
assemble the plugin for you:

```console
$ ./configsys.sh plugin init            # or: plugin init <name>   (default: configsys-<user>)
```

With no primary plugin yet it **creates** one in `~/.config/configsys/plugins/<name>/` from your
local bits — your captured dotfiles, your `components:` overrides, and your other declared
plugins carried along as transitive — `git init`s it, and blesses it primary. (If you already
have a primary, it **merges** those local bits in instead.) Your picks move separately with
`configsys picks to-primary`. It's a real git repo you author in place; when you're ready to
share it, push it and repoint the source:

```console
$ cd ~/.config/configsys/plugins/configsys-<user>
$ git remote add origin git@github.com:you/configsys-<user>.git && git push -u origin main
$ ./configsys.sh plugin set-source configsys-<user> github:you/configsys-<user>
```

## Commands

Run as `./configsys.sh <command>` (or `python -m configsys <command>` inside the venv).
With no command, the **TUI** opens. Run `configsys <command> -h` for per-command help; the
full reference is the **`configsys(1)`** man page (`configsys manpages install`).

```
configsys [tui]                    # interactive TUI (default)
configsys inspect                  # install-state table for this machine's picks
configsys install  <name>...       # install (pulls dependencies first, ordered) [--force] [--no-deps]
configsys remove   <name>...       # uninstall
configsys upgrade  <name>...       # upgrade to latest [--force] [--no-deps]
configsys lock|unlock <name>...    # version-lock / unlock
configsys set-version <name> <ver> # pin to a specific version
configsys fix-scope [<name>...]    # reconcile user/system scope mismatches (moves the install)

configsys picks   <list|add|rm|to-primary>   # this machine's picks — the install set [--machine]
configsys machine <list|show|add|rm|use>     # the picks matrix columns; `use` sets this box's machine
configsys profile <list|show>      # browse the shipped profile catalog (read-only lenses)
configsys disp    <list|get|set>   # component dispositions: seen / interesting / new
configsys orphans                  # installed software no pick accounts for — adopt/remove/ignore

configsys where <name> [-p]        # explain a component: source layer + bindings + resolution (-p: a profile)
configsys location <name> [--all]  # print a component's absolute install location
configsys versions <name>          # the version each install method would give, with tip lag [--min V] [--refresh]
configsys pin <list|set|unset|promote>   # view/change install-method & provider pins
configsys config <show|get|set|unset|move>   # machine settings (scope, driver-preference, …)
configsys theme <show|list|set|unset|save|load>   # the TUI theme; save/load shareable theme plugins
configsys keys                     # the effective TUI keybindings (merged `keys:`)
configsys show <routes|config> [--path]   # print a shipped base file (or its location)
configsys check                    # lint the merged config (repo + your file + includes + plugins)
configsys refresh                  # re-query latest versions + refresh the native package index

configsys dotfiles <status|capture|staged|activate|discard>   # your dotfiles + staged glue (see below)
configsys plugin  <list|sync|add|remove|update|bless|unbless|trust|untrust|init|set-source>   # (see Plugins)
configsys report  [<name>] [--print]      # file an install-failure report (you approve the text first)
configsys request <name> [--print]        # ask upstream for full cross-platform support (coverage matrix)
configsys manpages <install|status>       # install/check the man pages (configsys(1), configsys.hu(5))
```

`install`/`upgrade` take **`--force`** — for dotfiles, overwrite an un-adopted on-system file
(backing it up to `<name>.pre-configsys`) instead of refusing. Prefer `dotfiles capture` first.

**Rebuilding a component.** `install <name>` is not skipped when the component is already
present — package-manager drivers re-run their install (a no-op if it's current), and a
**`via: source` component always REBUILDS from a pristine checkout** (fetch → force-checkout the
ref → `git clean` → build). So to pick up a recipe change *at an unchanged version* (or recover a
half-finished build), just `install` it again — no separate "reinstall" verb. **`--no-deps`** runs
the op on **only the named component(s)**, skipping the dependency-install fan-out (and
auto-tighten) — so you rebuild just that one thing instead of dragging its whole (already-built)
dependency tree along: e.g. `configsys install --no-deps folly`.

Any `<name>` may be **`profile:<name>`**, which expands to that profile's components — e.g.
`configsys install profile:dev blender`. The `profile:` prefix disambiguates from a component of
the same name.

**`refresh`** re-queries every discovered version source *and* refreshes the OS package index
(`apt-get update` etc., via sudo). Staged TUI ops do this automatically once per batch when they
include a native install/upgrade (the `refresh-before-execute` setting).

Global flags: `--pretend` (dry-run — prints commands, makes no changes and no network calls),
`--os <block>`, `--home <dir>`, `--config <file>` (the last three sandbox a run), `--machine
<name>` (curate/plan another machine's picks; execution still acts locally), `--color
{auto,24bit,256,16,8,none}` / `--nocolor` (cap the TUI color depth), `--effects
{full,reduced,none}` (TUI motion), `--probe` (print the resolved color/motion mode and exit),
`--splash-linger`, `-v`/`-vv` (stream load detail to stderr), `-q` (quiet).

Environment: `CONFIGSYS_OS` / `CONFIGSYS_OS_VERSION` (override the detected OS),
`CONFIGSYS_HOME` / `CONFIGSYS_CONFIG` (relocate the HOME base / the config file),
`CONFIGSYS_STATE_DIR` (the ledger dir) / `CONFIGSYS_REPO` (the data root holding
`config.hu`/`routes.hu`), `CONFIGSYS_ARCH`, `CONFIGSYS_USERSCOPE_DIR` / `CONFIGSYS_SYSTEMSCOPE_DIR` /
`CONFIGSYS_APP_DIR` / `CONFIGSYS_SDK_DIR` / `CONFIGSYS_SRC_DIR` (install layout; win over `dirs:`),
`CONFIGSYS_COLOR` / `NO_COLOR` / `CONFIGSYS_EFFECTS` (TUI look), `CONFIGSYS_SPLASH`
(`always`/`linger` to force or hold the splash) / `CONFIGSYS_NO_SPLASH`, `CONFIGSYS_GLUE_SHELLS`
(override which shells glue treats as installed), `CONFIGSYS_FACET_*` (override a detected facet),
`CONFIGSYS_GITHUB_TOKEN` / `CONFIGSYS_GIT_TOKEN` / `GITHUB_TOKEN` (private-plugin auth, GitHub rate
limit).

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

## The TUI

Seven screens, switched with the number keys in the top chip bar:

1. **Components** — this machine's picks as a component → unit tree, with driver, `INSTALLED`
   and `LATEST` columns, and an infoblock showing the current unit's versions and install
   location. Stage ops on any node (`i` install, `u` upgrade, `x` remove, `L` lock, `I`/`U` all),
   pick a method with `v` (writes a pin), `w` for the full `where` graph, `R` to refresh, then
   `X` executes the reviewed batch. `M` cycles the view **mode**: `to-do` (needs action) /
   `tracked` (every pick) / `installed+tracked` (plus installed-but-unpicked).
2. **Profiles** — the component × machine matrix: browse the catalog by profile (left), see
   which machines pick each component (right), and toggle picks (`t`/`T`), dispositions
   (`s`/`i`), machines (`m`/`M`), the install-state overlay (`O`), and kind filters (`f`).
3. **Plugins** — declared plugins with sync/ABI/trust status; add, sync, update, bless, trust.
4. **Glue** — shell snippets grouped per installed shell; activate (`a`/`A`) or deactivate (`x`).
5. **Dotfiles** — each managed config's state; manage/unmanage (`m`/`u`, `M`/`U` all), move
   between stores (`s`/`S`).
6. **Config** — every machine setting, its value and where it lives; edit in place, `m` moves it
   local ↔ primary, `t` opens the theme editor.
7. **Theme** — live palette/role/gradient editing (see [docs/theming.md](docs/theming.md)).

Navigation is VIM-style everywhere (`j/k`, `h/l`, `g/G`, `/` find, `F` filter, `space` select,
`!` issues, `?` help, `q` quit). Keys are **rebindable** via a `keys:` section; `?` in the TUI and
`configsys keys` print the effective legend, which is the authoritative list.

Colors, per-element styles, and the background gradient are fully configurable — see
[**docs/theming.md**](docs/theming.md).

## Dotfiles and glue

configsys treats your dotfiles as **yours** — it ships **no personal config templates** and will
not overwrite anything it didn't create. Two drivers share the work:

- **Dotfiles** (`via: dotfiles`) — an application's *own* config (`~/.config/htop/htoprc`, …). A
  component only declares *where* a config lives (its `src`→`dst` mapping); the **content**
  comes from your own store, resolved by a search-path (first hit wins):

  ```
  ~/.config/configsys/dotfiles/<component>.cfs/<src>   (machine-local — where capture lands with no plugin)
  <primary-plugin>/dotfiles/<component>.cfs/<src>      (portable — travels in your primary plugin)
  <defining layer>/dotfiles/<component>.cfs/<src>      (a template, only if some layer ships one)
  ```

  The `<component>.cfs/` **marker dir** (with a `manifest.hu` recording the src→dst layout and
  any exclude globs) is what makes a config *managed* — even when it holds no files yet.
- **Glue** (`via: glue`) — the per-shell snippet a tool needs to be usable (PATH, an alias like
  `fdfind`→`fd`, a `zoxide init`). Glue is *shipped* (repo `glue/shell/<shell>/`), never captured:
  it materializes into a machine-local store and links into the uniform `~/.config/<shell>/conf.d/`
  for each **installed** shell (elvish/nushell inline it into the rc). A tool `suggests:` its
  `<name>-glue` companion, so it attaches only where the shell is present. Opt out per machine with
  `disabled-drivers: [ glue ]` (or `dotfiles`) to manage your own shell config.

Dotfiles commands:

```console
$ ./configsys.sh dotfiles status     # every dotfile in this machine's picks + its state
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
- **Installers don't scribble in your rc files.** An installer that appends to `~/.bashrc` /
  `~/.zshrc` (sdkman, nvm, rustup, …) is reverted and its block **staged** as inactive glue for
  you to review: `dotfiles staged` lists, `activate` promotes, `discard` drops it (the
  `installer-shell-writes` setting).

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

- **No surprises.** Browsing a profile or picking a component never changes your system;
  installs are always an explicit, reviewable action, and `check` lints the whole merged config
  without touching anything.
- **Resilient.** A malformed plugin or single component surfaces as an
  error row — it can't brick the tool.
- **One term, one meaning.** Everything about *how* software is acquired is a **driver**;
  everything about *what* you want is a **component**; what *this machine* gets is its
  **picks**.

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
