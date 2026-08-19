---
name: add-component
description: Playbook for adding one or more components to configsys routes.hu across the full OS/driver matrix — a comprehensive row of install methods (native + fallbacks) available everywhere it can be, optional build-from-source in the configsys-source plugin, profile placement, validation, and the podman sweep/real-install tests. Use whenever adding/expanding components or when the user says "/add-component <names...>", "add these tools", or asks to route a package across distros.
---

# add-component — routing new components across the OS matrix

Adding a component means giving one **capability** a comprehensive set of **bindings** so it
installs the best way on every OS it can, with graceful fallbacks where the best way is absent.
The authoritative spec is `docs/routing-model.md`; this is the operational playbook.

**Golden rule:** for each tool, fill the matrix — one *native* method per package manager where the
tool is packaged, plus non-native fallbacks (tarball/appImage/flatpak/snap/aur/cargo/pip/…) for the
gaps — so the component *resolves* on every base OS, or declines honestly where nothing works.

---

## The matrix you are filling

Base OS families (atoms) and their native package manager:

| family        | atoms (examples)                                   | native mgr | notes |
|---------------|----------------------------------------------------|------------|-------|
| debian        | `debian` `ubuntu` `pop_os!` `elementary` `linuxmint` `kali` | apt  | Ubuntu extras live in `repo-component: universe` |
| redhat        | `redhat` = `fedora` + `rhel`(EL)                    | dnf        | Fedora ≠ EL. EL (`rhel` `rocky` `almalinux` `centos`) needs `requires: epel` / `rpmfusion` for many pkgs |
| arch          | `arch` `manjaro` `endeavouros` `cachyos` `garuda`   | pacman     | community pkgs via `via: aur when: "arch"` |
| opensuse      | `opensuse` `opensuse_leap` `opensuse_tumbleweed`    | zypper     | |
| alpine        | `alpine`                                            | apk        | **musl** — glibc tarballs/appImages don't run here; needs a musl asset or native |
| atomic/brew   | `fedora_atomic` (Bazzite/uBlue)                     | brew       | immutable: prefer flatpak + brew; no system pkg installs |

A "comprehensive row" = a `native` binding wherever the tool is in-repo + fallbacks covering the
rest. Verify the final routing with the per-OS resolve check (below) — the target is *every* OS
resolves to *something*, and the method is the one a human would pick there.

---

## Step-by-step

### 0. Research each tool (do this first, don't guess)
For every name the user gives, establish: what it is, its **binary name** (may differ from the pkg —
`bottom`→`btm`, `superfile`→`spf`), the **upstream repo** (for tarball/source/version discovery),
and its **native package name per distro** (may differ — `espeak`→`espeak-ng`, `iproute2`→`iproute`
on dnf). Use WebSearch for anything uncertain — **flatpak app-ids and release asset globs must be
exact or the binding silently fails.** Confirm: Flathub app-id (search "<tool> flathub"), the GitHub
release asset filename pattern, and whether it's in EPEL (EL) / universe (Ubuntu).

### 1. Read a few existing components that match the shape
Match the house style. Good exemplars in `routes.hu`:
- native everywhere, EL via EPEL, Ubuntu universe → `htop`, `btop`, `mc`
- native + cargo/tarball fallback for EL → `bottom`, `micro`, `nushell`
- vendor apt/dnf repo (key + source) + AUR + flatpak → `chrome`, `brave`, `vivaldi`, `tor-browser`
- upstream `.deb`/`.rpm` release file → `yazi` (`via: native-pkg-file`)
- name differs per distro → `iproute2`, `cython`, `python3-pip` (`name:` maps)
- AppImage fallback for a musl/arch gap → `ghostty`
- install script → `zed`

### 2. Write the component in routes.hu
A component is `name: { description: "…"  install: [ <bindings> ] }`. Each binding is
`{ via: <driver>  when: "<expr>"  …fields }`. Put it near siblings of the same kind (monitors,
editors, browsers, file-managers, …). Rules:
- **`description:` is mandatory** — one present-tense line naming the tool and what it does, with the
  real binary in backticks when it differs from the name (``System monitor (`btm`) …``). It's
  user-facing (TUI rows, `configsys request`, `check`), so write it for a human scanning the catalog,
  not a package blurb. It only needs to be defined once; for a component modified in layers downstream
  of the most base definition, the existing description will be used, so don't rewrite it.
- **`via: native`** resolves to the OS's package manager; package name defaults to the component
  name — override with `name: <pkg>` (scalar = all managers) or `name: { apt: …  dnf: …  default: … }`.
- **`when:`** states *validity only* (does this method work here), never preference. Bare atom =
  subtree membership; combine with `and/or/not`, parens. Most-specific `when:` wins among candidate
  bindings of comparable specificity; two SAME-`via:` bindings that overlap incomparably = a
  load-time ambiguity error (routecheck catches it). Two bindings of the SAME via where one has a
  narrower `when:` (e.g. `when: "rhel"`) and the other is unconditional is fine — the narrow one wins
  on that OS (that's the EPEL pattern).
- **`requires:`** is HARD (`epel`, `rpmfusion`, `glibc`, a toolchain like `go`/`cargo`, or another
  component). **`suggests:`** is SOFT (pulled if resolvable, else skipped — the mechanism for
  attaching `<name>-dotfiles`).
- **`standing: never-auto`** = valid + listed + pinnable but never the auto-default (use for an
  opt-in method that shouldn't be picked automatically). `standing: <int>` = a preference rank.
- Write a **one-line comment** explaining any non-obvious gating (why a `when:`, why EPEL, why a
  tarball) — every existing component does.
- **`attrs:` is expected on every real component** (an end-user tool/app/lib — not the `-dotfiles`/
  `-service` companions, which self-tag). It's a free-form multi-tag list for cross-cutting filtering,
  ORTHOGONAL to profiles. Assign tags across the axes (full vocabulary + case rules in
  `docs/component-attrs.md`): **interface** `CLI`/`TUI`/`GUI`/`daemon`/`web`; **role**
  `lib`/`SDK`/`app`/`toolchain`/`runtime`/`driver`/`font`/`theme`/`plugin`/`game`; **license** (combine
  all that apply) `FOSS`/`FOSSish`/`proprietary`/`source-available`/`GNU`/`copyleft`/`permissive`;
  **data** `tele`/`tele-optin`/`account`/`cloud`/`online`/`ads`/`paid`; **pedigree** `electron`/
  `patent`/`legacy`. Case: ALL-CAPS acronyms (`CLI FOSS SDK GNU`), lowercase words. Interface/role you
  can read off the tool; **the license + data axes you MUST research per tool** (does it phone home?
  what license?) — only a human knows. `via: dotfiles`/`service`/`font` auto-derive `dotfiles`/
  `service`/`font`, so companions need no `attrs:`. Example: ``mpv: { … attrs: [ CLI GUI FOSS GPL ] … }``.

### 3. Fill the fallbacks (pick the right driver — see catalog below)
Order native-first, then fallbacks. Typical comprehensive rows:
- **Rust tool** (ripgrep, bottom, btop): `native` where packaged + `cargo` (or a release `tarball`
  with `requires: glibc`, plus a musl asset for alpine) for the rest.
- **Go tool** (micro, superfile, lazygit): `native` + release `tarball` (nested `bin/` is fine — the
  driver finds the binary).
- **GUI app / browser** (tor-browser): vendor `native` where it exists + `via: aur when: "arch"` +
  `via: flatpak hub: flathub app: <id>` (flatpak is the universal + atomic-only method).
- **Upstream ships a .deb/.rpm** but not in-repo (fastfetch, yazi): `via: native-pkg-file when:
  "debian"` with `asset: { x86_64: …deb  aarch64: …deb }`.
- Language-ecosystem tools: `cargo`/`pip`/`pipx`/`npm`/`gem`/`opam`/`luarocks`/`cabal`/`go-install`/
  `sdkman` — each takes `name:` (the crate/pkg/candidate) and often `requires: <toolchain>`.

### 4. Add a `-dotfiles` companion whenever the tool has config (implied — don't skip)
If a new component stores configuration (reads `$XDG_CONFIG_HOME/<name>`, a `~/.<name>rc`, …) OR
needs shell integration (PATH for a `~/apps` tarball/appImage install, aliases, env, completions),
give it a `<name>-dotfiles` companion and add `suggests: <name>-dotfiles` to the parent. Two shapes:

- **Shell glue** — the tool needs PATH/aliases/env to work (a `~/apps` install that isn't on PATH,
  like yazi/superfile aliasing `yazi`/`spf`; a completions or env line). **You author and ship it**
  in the base repo at `dotfiles/shell/bash/<glue>.sh`, then declare a `glue:` NAME (the driver
  expands it to a per-shell spec — `shell/<shell>/<glue>.<ext>` → `~/.config/<shell>/conf.d/
  <glue>.<ext>` — for every shell that ships a variant; bash today):
  ```
  <name>-dotfiles: { install: [ { via: dotfiles  requires: bash-dotfiles  glue: <name> } ] }
  ```
  Add a `dotfiles/shell/fish/<glue>.fish` later and fish users light up with ZERO component edits.
  For a tool that needs BOTH a config dir AND glue, mix them — the config as a named spec, the glue
  nested: `{ via: dotfiles  requires: bash-dotfiles  config: { src: <name>  dst: … }  aliases: { glue: <name> } }`.
- **App config** — the tool reads its own config dir/file:
  ```
  <name>-dotfiles: { install: [ { via: dotfiles  config: { src: <name>  dst: $XDG_CONFIG_HOME/<name> } } ] }
  ```
  `config:` is one named spec; add more named specs for stray files, each with its own `dst`. The
  content usually **isn't shipped** — it lives in the user's personal layer, captured with `configsys
  dotfiles capture <name>` (which stores it under a `<name>-dotfiles.cfs/` marker dir + `manifest.hu`
  in the capture root, auto-excluding secret-shaped paths). Installing a config `-dotfiles` stamps
  that `.cfs` marker even with no content yet, so the location reads as *managed*. `dotfiles/` content
  resolves relative to the .hu that *defined* the component (base repo, else a plugin/user layer), so
  a package can offer a config that simply doesn't attach where the content is absent.

`suggests:` is SOFT: the parent installs fine whether or not the `-dotfiles` content exists, and the
user can opt the whole mechanism out with `disabled-drivers: [ dotfiles ]`. Links are edit-through
and back up any pre-existing real file to `<dst>.pre-configsys`. **Rule of thumb:** if installing the
tool leaves a config it would read or a PATH/alias it needs to be useful, add the `-dotfiles` — a
shell snippet you write and ship, or an app-config spec you scaffold for capture.

### 5. (Optional) build-from-source in the configsys-source plugin
`~/src/configsys-source` (a data plugin, its own repo) adds ADDITIVE `via: source` bindings to core
components — a buildable method for people who want it. If the user wants a source option, add to
`sources.hu`:
```
<component>: { install: [ { via: source  repo: "https://github.com/owner/repo"
    version: { github: owner/repo  strip-v: true }  tag-prefix: "v"  requires: <toolchain>
    build: "<shell to build + install into $PREFIX/bin>" } ] }
```
The binding merges into the existing core component by name (additive — doesn't replace core
methods). Plugin changes need **re-sync + re-trust** to take effect locally (core routes.hu is live
immediately). Source recipes with a build floor feed the `version-floors:` derivation (see the
Versions section).

### 6. Profile placement (config.hu) — only where it clearly belongs
Components install by name regardless of profiles. Add to a profile only for a natural fit:
`tor-browser` → the `web-browsers` **catalog** (pick-one lists that aren't auto-installed — safe to
extend). Be cautious adding to role profiles that auto-install (e.g. `terminal`, which `user`
pulls in) — that changes what everyone gets. When unsure, leave it out and mention it.

### 7. Validate (always, before committing)
```
.venv/bin/python -m configsys --os pop check          # lint the merged config (0 errors)
```
Run `check` across a spread of OSes (pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic) — all must
be **0 errors**, and warning count must not rise. Then confirm each new component resolves to the
*expected* method per OS with a resolve sweep (adapt this):
```python
# reschk.py — prints "<comp>=<via>" per OS; ERR/EXC means it failed to route
from configsys.app import Context, build_parser
comps = ['<comp1>', '<comp2>']
for os in ('pop','fedora','arch','alpine','opensuse','rhel','fedora_atomic'):
    r = Context(build_parser().parse_args(['--home','/tmp/nohome','--os',os,'inspect'])).routes
    row = []
    for c in comps:
        units, errs = r.resolve_resilient([c])
        keys = [k for k in units if units[k].name == c or c in k]
        via = keys[0].split('\\')[0] if keys else ('ERR' if any(c in str(e) for e in errs) else '—')
        row.append(f'{c}={via}')
    print(f'{os:14} ' + '  '.join(row))
```
Run with `CONFIGSYS_NO_DISCOVER=1 .venv/bin/python reschk.py`. Also handy: `configsys --os <os>
where <component>` (source layer + resolution) and `configsys --os <os> request <component>`.

### 8. Regenerate the golden gate + run the suite
Adding components changes the frozen resolution snapshot (`test/routing_golden.json`, every
component × 9 contexts). Regenerate and confirm it's **purely additive**:
```
CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py -q   # writes the golden
```
Then semantic-diff vs HEAD — the ONLY changes should be the new component keys appearing in each
context, with `changed=[]` (nothing existing perturbed). Reject the change if any existing
resolution shifted (means a new binding leaked into another component's routing).
```python
import json, subprocess
old = json.loads(subprocess.run(['git','show','HEAD:test/routing_golden.json'],capture_output=True,text=True).stdout)
new = json.load(open('test/routing_golden.json'))
for ctx in sorted(set(old) & set(new)):
    a = set(new[ctx]) - set(old[ctx]); c = [x for x in set(old[ctx]) & set(new[ctx]) if old[ctx][x] != new[ctx][x]]
    if a or c: print(f'{ctx}: +{sorted(a)}  changed={sorted(c)}')
```
Finally: `.venv/bin/python -m pytest test/ -q` (full suite green — no known flakes).

### 9. Sweeps & real-install (podman) — for confidence / when names are uncertain
These need **podman** and are NOT part of pytest (slow, networked, container-only):
- **Name-existence sweep** (does the resolved native pkg still exist in each distro's repos —
  catches renames/removals like redis→valkey): `bash test/run-name-sweep-in-podman.sh [manager]`.
  Host-side extractor is `tools/namesweep.py` (`--manager apt` lists names, `--json` the full map);
  false-positives go in `test/namesweep-allowlist.hu` with a one-line reason. Gates apt/dnf/pacman/
  zypper/apk. **Run this after adding native bindings** — it's the cheap 80%-of-breakage catch.
- **Real-install lifecycle** (actually install/upgrade/remove in a throwaway container):
  `bash test/run-in-podman.sh [PKG]` (apt), plus targeted `test/run-{dnf,pacman,zypper,flatpak,
  clang,langs,…}-in-podman.sh` and `test/Containerfile.*` per distro. Use when a new method needs
  real verification (a vendor repo, a .deb file, a toolchain build).
- **Version-floor sweep** (if you added versioned `requires:`/source floors):
  `.venv/bin/python tools/versionsweep.py` (and `--derive` to emit a `version-floors:` block from
  source recipes). Networked; reflects THIS machine's repos — run in per-distro containers for full
  coverage.

### 10. Commit
Commit **locally** (the user pushes). Base identity + trailer:
```
git -c user.name="Trevor Schrock" -c user.email="spacemeat@gmail.com" commit -m "components: add <names>

<one line per component: the methods it routes to and any notable gating>

Golden regenerated — purely additive. check: 0 errors across <OSes>.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
routes.hu/config.hu live immediately; `configsys-source` (plugin) changes are a separate repo/commit
and need re-sync+re-trust to load.

---

## Driver catalog (`via:` → when to reach for it)

**OS package managers** (`via: native` resolves to the right one; only name via a driver when
pinning): `apt` `dnf` `pacman` `zypper` `apk` `brew`. Plus `aur` (Arch community, `when: "arch"`),
`rpm-ostree` (atomic layering — rarely; prefer flatpak/brew there).

**Upstream distribution:**
- `native-pkg-file` — install an upstream release `.deb`/`.rpm`/`pkg` with the OS tool (rides
  neither the repo nor `apt upgrade`). Fields: `when:`, `version: { github: owner/repo }`,
  `asset: { x86_64: <name>.deb  aarch64: <name>.deb }`.
- `tarball` — a release archive unpacked under a scoped dir + PATH. Fields: `installDir:
  "$CONFIGSYS_APP_DIR/<x>"`, `requires:` (`glibc`, `unzip`), `version: { github: … strip-v: …
  asset: "…$ARCH…tar.gz" }`. Provide a **musl** asset (or gate `not alpine`) for Alpine.
- `appImage` — `name:`, `scope:`, `version: {…}`, `path: ~/apps/<x>.appimage` (needs libfuse2).
- `flatpak` — `hub: flathub  app: <exact.app.id>`. The universal GUI method + only method on atomic.
- `snap` — `name: <snap>` (Ubuntu-centric; Chromium's real method there).
- `script` — declarative installer: `install-cmd`, `version-cmd`, `version-re`, `uninstall-cmd`,
  `location`.
- `source` — build from a git checkout/archive (lives in the configsys-source plugin, §5).

**Language toolchains & their module installers** (take `name:` = crate/pkg/candidate, often
`requires: <toolchain>`): `cargo` `pip` `pipx` `npm` `gem` `opam` `luarocks` `cabal` `go-install`
`sdkman`. Toolchains themselves: `gcc` `gcc-toolset` `clang` `pyenv`.

**Post-install primitives:** `service` (systemd unit — `<name>-service` components), `group`
(usermod — `<name>-group`, opt-in, `requires:` the group the pkg creates), `dotfiles`
(`suggests: <name>-dotfiles`; `config: { src: dst: }` or `src:`/`dst:`, `requires: bash-dotfiles`).

**Aggregator:** `parts` — a component that is the union of its `parts:` (no unit of its own). Prefer
a **profile** over a parts-component for user-facing bundles.

## `version:` sources (for tarball / native-pkg-file / appImage / source / latest-check)
`{ github: owner/repo  strip-v: true  asset: "<glob with $ARCH>" tag-prefix: "v" }` |
`{ url: "<page>"  regex: "<ver-capture>" }` | `{ static: "<pinned>" }` |
`{ crates: <crate> }` | `{ pypi: <pkg> }` | `{ aur: <pkg> }` | `tag-re:` for odd tag schemes.
`asset` is a glob resolved against the GitHub release (no hand-templated URL); `$ARCH` expands.

## Versions — visibility, version-scoped providers, floors
Three distinct things (full model in `docs/versioned-requires.md` — but note that doc predates the
`standing` rename: where it says `opt-in:`, the current keyword is **`standing: never-auto`**):
- **`configsys versions <name> [--min VERSION] [--refresh]`** — shows, per install method, what
  version it *would* install (native-vs-upstream-tip lag called out), marks which meet `--min`, and
  how to pin one. Use it to confirm a new component's methods aren't shipping something ancient, and
  to help a user pick a method by version. `--refresh` bypasses the version cache
  (`state_dir/versions.hu`) and re-queries each method's `get_latest` live.
- **Version-scoped providers** — a component providing a *specific version* of a capability:
  `provides: { <cap>: N }` on the provider + `requires: { <cap>: ">=N" }` on the consumer (the
  constraint selects a resident by version and can even ENABLE a `standing: never-auto` provider).
  This is how `python3.11/12/13/14` and `jdk-17/21/25` coexist — each versioned provider is
  `standing: never-auto` so it never shadows the unversioned default. Add this only when the new
  component is a *versioned alternative* of something, or genuinely needs a minimum version.
- **Version floors** — a HARD minimum: `requires: { <toolchain>: ">=X" }`, plus the authored
  `version-floors:` section. A `via: source` recipe's build-toolchain floor auto-derives via
  `.venv/bin/python tools/versionsweep.py --derive` (emits a ready-to-commit `version-floors:`
  block). Run `tools/versionsweep.py` (podman, per-distro) if you add a versioned requirement or a
  source recipe with a toolchain minimum — it fails if a floor is stranded (no method meets it) or
  dishonestly claimed.

## Common gotchas
- **Fedora ≠ EL.** `fedora` is fine for base repos; `rhel` is EL and usually needs `requires: epel`
  (or `rpmfusion` for media). Newer Rust/Go tools are often NOT in EPEL → use cargo/tarball for EL.
- **Ubuntu universe.** Many tools are in `universe`, not `main` — add `repo-component: universe` to
  the native binding (harmless on non-apt).
- **musl (Alpine).** glibc tarballs/appImages won't run. Give Alpine a native pkg, a musl asset, or
  let it decline (`when: "not alpine"`).
- **Name drift.** `name:` maps per distro; the name-sweep catches renames/removals — run it.
- **Binary ≠ package name.** Note the real binary in the description (`btm`, `spf`, `nvim`, `hx`).
- **Metapackage installed via its parts.** If a component installs an apt METAPACKAGE that a system
  often has WITHOUT (Debian/Ubuntu/Pop ship LibreOffice as `libreoffice-core`/`-calc`/… without the
  `libreoffice` meta), probing the meta falsely reports "missing". Add `installed-name: <a-part>` to
  the native binding — apt READS state from it while `name` still installs the meta (`libreoffice`
  detects via `libreoffice-core`). apt-only; other drivers ignore it.
- **Exactness.** Flatpak app-ids and asset globs fail silently if wrong — verify by search, and by
  the resolve sweep + (ideally) a podman real-install for the risky ones.
