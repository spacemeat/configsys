# configsys

One tool to set up a new OS install and account from a declarative config. It syncs
OS-native packages, AppImages, Flatpaks, downloaded SDKs/tarballs, fonts, and dotfiles
across machines (Linux/unix/macOS) from a git-synced config, with total control over
install, version-lock, upgrade, and removal — driven by a slick, VIM-keyed TUI.

## Quick start

```sh
./bootstrap.sh            # verify python3>=3.10, create .venv, install humon, launch TUI
./bootstrap.sh inspect    # non-interactive: show install state of your active profiles
```

`bootstrap.sh` is the only bash; everything else is python. On first run it generates
`~/configsys.hu` (your per-machine selection) from a template.

## Concepts

- **Profile** — a flat list of component names in the repo's `config.hu` (shared, git-synced).
  `~/configsys.hu` picks which profiles apply to *this* machine (`configs: [dev]`) and can
  override anything locally.
- **Component** — a thing you want (e.g. `neovim`, `firefox`, `vulkan-dev`). Resolved through
  `routes.hu` into one or more concrete **units** (`apt\btop`, `flatpak\firefox`, …). The unit
  key `family\comp` is the dedup identity, so overlapping components install once.
- **Family** — an install medium with a uniform op set (install / uninstall / upgrade /
  set-version / lock / unlock / inspect). Implemented: **apt, tarball, flatpak, appImage,
  dotfiles, debian-font**.
- **State** — the live system is the source of truth (dpkg/flatpak/marker files); a small
  ledger (`~/.config/configsys/state.hu`) stores only lock intent and configsys-managed
  bookkeeping. Version-lock uses native mechanisms where they exist (`apt-mark`, `flatpak mask`).

## Commands

```
configsys                     # interactive TUI (default)
configsys inspect             # per-component install state table
configsys install  <name>...  # install (pulls dependencies first, ordered)
configsys remove   <name>...
configsys upgrade  <name>...
configsys lock|unlock <name>...
configsys set-version <name> <version>
configsys refresh             # re-query latest versions from their sources
```

Global flags: `--pretend` (dry-run; prints commands), `--os <block>`, `--home <dir>`,
`--config <file>` (all make runs sandboxable).

The TUI is a **profile → component → unit** tree. Profiles are expanded by default and
list their components; a component that resolves to one unit is a leaf (shown with its
family), while a composite like `vulkan-dev` or one with dependencies collapses to an
aggregated row you can expand (`enter`/`→`) to reveal and individually select its units.
Family is its own column, and versions are split into `INSTALLED` and `LATEST` (what you
could install — discovered for download families). An infoblock above the footer shows the
current unit's full versions and its install location (`at: ~/vulkan`, the appimage path,
the font dir, dotfile targets, …). Ops can be staged on any node — a profile stages all its
units, a component its units, a unit just itself — and staging is unit-keyed, so a mark
shows everywhere that unit appears.

Keys: `j/k` move, `enter`/`→` expand, `←` collapse, `tab` expand/collapse all, `space`
select, `a` all, `i/u/x` install/upgrade/remove, `L/l` lock/unlock, `c` clear, `X` execute,
`q` quit.

## routes.hu — how components resolve

```humon
{
    \apt: { btop: { name: btop  repo-component: universe } }   // a family block

    \flatpak: {
        !depends: flatpak                       // family prerequisite (installed first)
        firefox: { hub: flathub  name: org.mozilla.firefox }
    }

    linux: { }
    debian: {
        !using: linux                           // OS cascade (inherit routes)
        *: apt\*                                // wildcard: any name -> apt\<name>
        vulkan-dev: [ build-essential, vulkan-sdk ]   // list = multi-part component
        firefox: flatpak\firefox                // family\component binding
    }
    ubuntu:  { !using: debian }
    pop_os!: { !using: ubuntu }
}
```

Key mechanisms:
- **`!using`** — OS blocks cascade (`pop_os! → ubuntu → debian → linux`). Detected via
  `/etc/os-release` (`ID=pop` → `pop_os!`).
- **`*: apt\*`** — wildcard maps any unlisted name to that family.
- **`family\comp`** — bind a component to a family's implementation.
- **list** — a multi-part component; each entry resolved independently and deduped.
- **`!depends`** — a family's required tools (e.g. `\flatpak !depends: flatpak`); resolved
  through the cascade and installed *before* the component (dependency-ordered execution).
- **`scope: user|system`** — install scope (default `user`). `system` uses sudo and system
  locations (e.g. `/opt` for a bare-relative `installDir`). Set per-component, or machine-wide
  via `scope:` in `~/configsys.hu`.

### Versions — discovered, not hardcoded

Download-based routes declare *how* to find the latest version:

```humon
neovim: {
    version: { github: neovim/neovim  asset: "nvim-linux-$ARCH.appimage" }
    url: "https://github.com/neovim/neovim/releases/download/$VERSION/nvim-linux-$ARCH.appimage"
    path: ~/apps/nvim.appimage
    name: Neovim
}
```

- **`{ github: owner/repo [strip-v] }`** — latest release tag. Optional `asset: <glob>` also
  resolves the exact download URL from the release assets (robust to file renames).
- **`{ url: … [regex: …] }`** — fetch a page and extract the version.
- **`{ static: … }`** — a deliberate pin.
- `$VERSION` / `$ARCH` are filled into the URL at install time. Discovered versions are cached
  (`~/.config/configsys/versions.hu`, 24h TTL); `configsys refresh` re-queries. Set
  `CONFIGSYS_GITHUB_TOKEN` (or `GITHUB_TOKEN`) to lift GitHub's unauthenticated rate limit.

### dotfiles

A dotfiles component maps link specs `{ src (under repo `dotfiles/`), dst }`; `dst` is
env-var/`~` expanded (`$XDG_CONFIG_HOME/nvim`). Install symlinks `dst → src` (edits flow back
to git), backing up any existing non-symlink; uninstall restores the backup.

## Development

```sh
.venv/bin/python -m pytest test/   # fast unit suite (mocked runner/fetch)
bash test/run-in-podman.sh         # real apt lifecycle + repo-component prereq (disposable)
bash test/run-flatpak-in-podman.sh # gated: real flatpak --user lifecycle (slow, networked)
```

See `docs/PLAN.md` (decisions) and `docs/IMPLEMENTATION.md` (build plan) for the full design.
