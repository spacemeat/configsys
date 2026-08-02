# configsys-source — a build-from-source plugin (plan)

Status: **in progress** (pilot batch). Goal: give (most) genuinely-buildable components a
selectable `via: source` install method, so that (1) a contributor can build any tool from source
on any OS, and (2) an OS lacking a binary method for a tool can still install it. Discussed and
scoped 2026-08-02.

## Locked decisions

1. **Delivery — a new `configsys-source` DATA plugin** (`~/src/configsys-source`, published to
   GitHub like the other plugins). It ships NO code: its `.hu` data files additively add a
   `via: source` binding to each covered component (the additive `(via, when)` merge makes this a
   pure data overlay — no redefinition, no driver). Opt-in; `routes.hu` stays clean. The `source`
   driver already lives in core (`configsys/drivers/source.py`) and is fully capable.
2. **Scope — genuinely buildable tools & libraries.** A component qualifies if it has a public
   git repo (or source archive) and a standard build system (autotools / cmake / meson / cargo /
   go / zig / plain make). EXCLUDED (see rationale below): language toolchains/runtimes, module-
   manager installs, fonts/dotfiles/services/groups, `parts` aggregators, OS-enabler
   metapackages, and proprietary/binary-only GUI apps.
3. **Verification — research every recipe, container-build a representative subset.** Each recipe
   is transcribed from the project's own build docs with correct `requires:`; a subset (≥1 per
   build system + every genuine gap-filler) is actually built in a container. Un-verified recipes
   are shipped but clearly marked `// UNVERIFIED: from upstream build docs` so honesty is preserved.
4. **Rollout — pilot first.** Nail the scaffold + shared build-toolchain `requires:` + a
   build-deps check, ship ~15–25 exemplars spanning every build system, prove end-to-end, then
   fan out follow-on batches with the pattern locked.

## Excluded categories (and why)

- **Toolchains / runtimes** (gcc, clang, rust, go, node, python, jdk, zig itself): building a
  compiler/runtime from source is a separate epic; not worth it as a routine method.
- **Module-manager installs** (npm, pip, pipx, gem, cargo-crate, opam, luarocks, cabal,
  go-install): these already compile from source at install time — a git-source build is
  redundant.
- **fonts / dotfiles / services / groups / `parts`**: not built software.
- **OS-enabler metapackages** (base-devel, epel-release, rpmfusion-free, gcompat, doas,
  software-properties-common) and **versioned compiler aliases** (gcc-14, clang-20, *-select):
  structural, OS-specific; source is meaningless.
- **System graphics/vulkan/xcb dev libs** (libxcb*, vulkan-*, mesa-*, libavcodec-extra): building
  the graphics stack from source is a rabbit hole and the wrong layer.
- **Proprietary / binary-only GUI apps** (chrome, slack, zoom, postman, discord, spotify, …): no
  public source to build.

## Parked — heavy apps & DEs get their OWN bespoke plugins

Following the Blender / KiCad precedent (a dedicated plugin with a real build driver + recipe),
these are too gnarly for the declarative `via: source` data plugin and each warrants its own repo:

- **ghostty** (Zig + GTK4/libadwaita) — `configsys-ghostty`
- **hyprland** (+ its ecosystem: aquamarine, hyprutils, hyprlang, …) — `configsys-hyprland`
- **cosmic** (Rust, huge workspace) — `configsys-cosmic`
- large creative/GUI apps already handled or to follow: blender ✓, kicad ✓; (krita, inkscape,
  darktable, godot, … candidates)

`configsys-source` links to these from its README so users know where the heavy builds live.

## Build-system taxonomy + the `requires:` vocabulary

Core already provides the capability/component atoms recipes lean on:
- `cc` / `cxx` (provided by gcc/clang), `cargo` (provided by rust), and the components
  `make`, `cmake`, `ninja`, `meson`, `go`, `zig`.
- **Missing, to add** (as small `via: native` components — in the plugin, or promoted to core if
  broadly useful): `pkg-config`, `autoconf`, `automake`, `libtool`, `scdoc`, `nasm`. These are
  common build-time tools with per-distro name differences; add them once with a `name:` map.
- **System dev-library capabilities** (libssl-dev/openssl-devel, zlib, ncurses, …): the real
  cost. Handled the same way the existing `libxcb-*` dev components are — a capability component
  per lib with a per-distro `name:` map, pulled via `requires:`. The pilot deliberately favours
  tools with MINIMAL system deps (pure Go/Rust/Zig, or C/C++ needing only libc + ncurses) to
  prove the pattern before we grind out dev-lib components in later batches.

## Recipe shape (declarative, in the plugin's data file)

```
components: {
    ripgrep: { install: [
        { via: source  when: "<optional gate>"
          repo: "https://github.com/BurntSushi/ripgrep"
          version: { github: BurntSushi/ripgrep }  tag-prefix: ""
          requires: cargo
          build: "cargo build --release && install -Dm755 target/release/rg $PREFIX/bin/rg" }
    ] }
    ...
}
```

- `build:` may be a list (run in sequence). `$PREFIX`, `$SRC`, `$VERSION`, `$ARCH` are substituted.
- Prefer installing the built artifact into `$PREFIX/bin` explicitly (many tools have no
  `make install`), so the binary lands on PATH (~/.local/bin at user scope) with no alias.
- Where a tool MUST run from its build dir / needs a launch cwd, add a companion bash.d alias like
  `lazygit.sh` (a `<name>-source-dotfiles` component) — this is the "alias with a starting cwd"
  case. (Possible future: a first-class `run-cwd:`/`alias:` field on the source driver.)
- `uninstall-cmd:` where `make uninstall` exists; otherwise the recipe installs to a known prefix
  path the driver removes.

## Verification harness

Reuse the podman pattern (`test/run-*-in-podman.sh`). A source-build check: in a per-distro
container, install the recipe's `requires:`, run `build:`, assert the binary exists + `--version`
works. The pilot verifies a representative subset; a `run-source-builds-in-podman.sh` in the
plugin becomes the ongoing gate (like the name-sweep).

## Pilot batch (~build-system exemplars)

| build system | pilot components |
| --- | --- |
| cargo (Rust) | ripgrep, fd, bat |
| go | lazygit, superfile |
| autotools | htop, tmux |
| cmake | fastfetch (already in core — mirror/confirm) |
| plain make | btop (already in core — mirror/confirm) |
| meson | (find a clean-dep exemplar, else defer to batch 2) |

Verify in containers: ripgrep (ubuntu), htop (fedora), lazygit (alpine) at minimum.

## Pilot results (2026-08-02)

Plugin scaffolded at `~/src/configsys-source` (data-only: `plugin.hu` + `tools.hu` +
`sources.hu`). Pilot batch of 5 recipes across 3 build systems shipped:
- **cargo**: ripgrep  · **go**: lazygit, superfile  · **autotools**: htop, tmux
- Shared build-tool/dev-lib components added in `tools.hu`: pkg-config, autoconf, automake,
  libtool, bison, ncurses, libevent (per-distro `name:` maps).
- **Rule enforced: the plugin only ADDS `source` to components that already have a binary method**
  (so `source` is always an alternative, never the sole/default method). fd and bat were dropped
  from the pilot for exactly this reason — they aren't in core, so shipping them here would make
  them build-by-default. Follow-up: add fd/bat to core with native bindings (mind Debian's `batcat`
  binary rename), then a later batch adds their source alternative.

**Resolution verified** (all 7, across arch/ubuntu/fedora): the `source` binding is selected under
a `pins: {comp: source}` and its full `requires:` closure maps to the right per-distro packages
(cargo→rust, cc→c-toolchain, autotools chain, ncurses/libevent). `source` never wins by default
(confirmed lowest-but-one preference).

**Container builds verified**: htop → fedora:41 ✓ (3.6.0-dev; exercised the ncurses-devel /
pkgconf-pkg-config name maps), lazygit → archlinux ✓, ripgrep → archlinux ✓ (15.2.0, rustc 1.97).
Recipes are **correct**.

**Key finding — toolchain floor.** Distro-packaged Rust/Go can be OLDER than a project's build
floor, so a correct recipe still fails on an old-toolchain distro:
- Ubuntu 24.04 ships **cargo 1.75** but ripgrep needs MSRV 1.96 (bat 1.88, fd 1.90) → "failed to
  parse manifest". Arch's rust 1.97 builds all three.
- `go` installs distro Go (~1.22 on Ubuntu) but lazygit needs **1.25**, superfile **1.26**.
This is documented per-recipe (caveat comments) rather than hidden. **Future improvement (parked):**
teach the `rust`/`go` components to optionally provide a RECENT upstream toolchain (rustup / the Go
release tarball) so source builds get a modern compiler regardless of distro — this would lift the
floor for the whole plugin. Tracked as a follow-up, not a pilot blocker.

## Roadmap

1. **Pilot — DONE** (above). Ship configsys-source v0.1.0 (local repo; push when ready).
2. **Batch 2+** — fan out research agents over the eligible set in build-system cohorts (cmake,
   meson, plain-make, more cargo/go, C libs); add dev-lib capability components as needed; grow the
   verified subset via `test/run-source-builds-in-podman.sh`.
3. **Toolchain-floor follow-up** — optional recent-Rust/Go providers so builds aren't gated by
   distro toolchain age.
4. Spin out the parked heavy apps/DEs as their own plugins (ghostty, hyprland, cosmic, …).
