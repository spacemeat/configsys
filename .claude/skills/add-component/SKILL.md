---
name: add-component
description: Playbook for adding one or more components to configsys routes.hu across the full OS/driver matrix — a comprehensive row of install methods (native + fallbacks) available everywhere it can be, optional build-from-source in the configsys-source plugin, profile placement, validation, and the podman sweep/real-install tests. Use whenever adding/expanding components or when the user says "/add-component <names...>", "add these tools", or asks to route a package across distros. Two special cases have their own sub-playbooks in this skill dir (dispatch below): adding an OS block (os-block.md) and adding a new shell (add-shell.md).
---

# add-component — routing new components across the OS matrix

Adding a component means giving one **capability** a comprehensive set of **bindings** so it
installs the best way on every OS it can, with graceful fallbacks where the best way is absent.
The authoritative spec is `docs/routing-model.md`; this is the operational playbook.

**Golden rule:** for each tool, fill the matrix — one *native* method per package manager where the
tool is packaged, plus non-native fallbacks (tarball/appImage/flatpak/snap/aur/cargo/pip/…) for the
gaps — so the component *resolves* on every base OS, or declines honestly where nothing works.

---

## Dispatch: two special cases have their own sub-playbook

Most requests are ordinary components — stay in this file. But **two kinds are handled differently;
when the request is one of them, read that file in this skill's directory and follow it instead of
the steps below** (they're kept separate so this playbook stays about routing a normal tool):

- **Adding an OS block** — a distro/environment in routes.hu's `os:` section (a Debian/Fedora/Arch
  derivative, a corporate or immutable distro, an alt-libc target). It's lineage + package manager +
  version scale + detection, not a `via:` row. → read **`os-block.md`**.
- **Adding a new shell** — a shell (elvish, xonsh, oil, tcsh, …) that needs glue snippets and a
  `conf.d` loader wired the way bash/zsh/fish are. It's an ordinary component PLUS glue-driver +
  content wiring. → read **`add-shell.md`** (it points back here for the component's own routing).

Anything else — a CLI tool, GUI app, library, font, service, `-dotfiles`/`-glue` companion — is this file.

---

## The matrix you are filling

Base OS families (atoms) and their native package manager:

| family        | atoms (examples)                                   | native mgr | notes |
|---------------|----------------------------------------------------|------------|-------|
| debian        | `debian` `ubuntu` `pop_os!` `elementary` `linuxmint` `zorin` `lmde` `mx` `kali` `pikaos` `pios` | apt  | Ubuntu extras live in `repo-component: universe`. `elementary`/`linuxmint`/`zorin`/`lmde`/`mx`/`pikaos` are scale-roots (own numbering — Zorin's VERSION_ID is the major only: 17 = Ubuntu 22.04, 18 = 24.04), so a versioned parent atom (`ubuntu >= 24.04`, `debian >= 12`) doesn't reach them; list them explicitly in a versioned `when:` |
| redhat        | `redhat` = `fedora` (+`nobara`) + `rhel`(EL) + `amzn` | dnf        | Fedora ≠ EL. EL (`rhel` `rocky` `almalinux` `centos` `ol` `scientific`) needs `requires: epel` / `rpmfusion` for many pkgs. `amzn` (Amazon Linux 2023) sits under `redhat`, not `rhel` — own version line, **no EPEL** |
| arch          | `arch` `manjaro` `endeavouros` `cachyos` `garuda` `omarchy` | pacman | community pkgs via `{ via: aur }` (the aur driver gate is Arch-only; aur ranks right after native) |
| opensuse      | `opensuse` `opensuse_leap` `opensuse_tumbleweed`    | zypper     | |
| alpine        | `alpine`                                            | apk        | **musl** — glibc tarballs/appImages don't run here; needs a musl asset or native |
| void          | `void` (glibc) + `void_musl`                        | xbps       | rolling, Arch-fresh. The flavors are **siblings** (different libc parents) — a Void-wide gate is `void or void_musl`; bare `void` misses musl. Nonfree pkgs `requires: void-repo-nonfree` |
| atomic/brew   | `fedora_atomic` (Bazzite/uBlue)                     | brew       | immutable: prefer flatpak + brew; no system pkg installs |
| native-less   | `kde_linux` (glibc, immutable) · `chimera` (musl)   | —          | no `native:`, so `via: native` declines: only portable methods route (flatpak, tarball, cargo, pipx, …). `kde_linux` `provides:` flatpak/curl/git/unzip/xz, has no libfuse2 (AppImages decline); `chimera` uses apk-tools but not Alpine's package names |

A "comprehensive row" = a `native` binding wherever the tool is in-repo + fallbacks covering the
rest. Verify the final routing with the per-OS resolve check (below) — the target is *every* OS
resolves to *something*, and the method is the one a human would pick there.

---

## Step-by-step

### 0. Parse the arguments, then research each tool (do this first, don't guess)
**Argument syntax:** each entry is a component name, **optionally followed by a bracketed list of
base profiles** — `<name> [profile1, profile2]` (e.g. `ripgrep [dev-tools, cli-tools]`, `mpv
[audio-tools]`, `foo` with no bracket). Strip the `[…]` to get the name to research; **carry the
profile list to step 6** — those are base profiles the component MUST be placed in. Entries are
comma/space-separated: `foo [a], bar [b, c], baz`.

For every name the user gives, establish: what it is, its **binary name** (may differ from the pkg —
`bottom`→`btm`, `superfile`→`spf`), the **upstream repo** (for tarball/source/version discovery),
and its **native package name per distro** (may differ — `espeak`→`espeak-ng`, `iproute2`→`iproute`
on dnf). Use WebSearch for anything uncertain — **flatpak app-ids and release asset globs must be
exact or the binding silently fails.** Confirm: Flathub app-id (search "<tool> flathub"), the GitHub
release asset filename pattern, and whether it's in EPEL (EL) / universe (Ubuntu).

**Void names** follow Fedora-ish conventions more than Debian's: dev headers are `<pkg>-devel`
(`libX11-devel`, `SDL2-devel`, `gtk+3-devel`), Python modules `python3-<Mod>` (`python3-Cython`),
and some renames (`fish-shell`, `openjdk21`, `apache-maven`, `openbsd-netcat`, `lm_sensors`, `R`).
A few packages live only in the `nonfree` repo (nmap, unrar). Check existence fast without a VM:
`podman run --rm ghcr.io/void-linux/void-glibc xbps-query -R <pkg>` (after `xbps-install -S`) — and
`void-musl` for the musl flavor, which lacks a handful of glibc-only packages (virtualbox-ose,
torbrowser-launcher).

### 1. Read a few existing components that match the shape
Match the house style. Good exemplars in `routes.hu`:
- native everywhere, EL via EPEL, Ubuntu universe → `htop`, `btop`, `mc`
- native + cargo/tarball fallback for EL → `bottom`, `micro`, `nushell`
- vendor apt/dnf repo (key + source) + AUR + flatpak → `chrome`, `brave`, `vivaldi`; distro launcher
  package + AUR + flatpak → `tor-browser`
- upstream `.deb`/`.rpm` release file → `yazi`, `fastfetch` (`via: native-pkg-file`); both formats in
  one binding (`asset: { deb: {…}  rpm: {…} }`) → `bruno`, `insomnia`
- Void name map + Void-only native binding → `fish` (`name: { xbps: fish-shell }`), `doas`
  (`{ via: native  when: "void or void_musl"  name: opendoas }`); nonfree repo → `nmap`; native only
  on musl where the glibc binary declines → `neovim` (`when: "void_musl or alpine"`)
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
- **AUR bindings need no `when: "arch"`**: the `aur` driver carries its own Arch-only gate and
  ranks right after native in driver-preference. Add `when: "arch"` only when another binding valid
  on Arch has a narrower `when:` (a glibc-version-gated AppImage listing `arch`, a `cpu:`-gated
  tarball) — that one would otherwise win on specificity before preference. Likewise don't gate
  snap/AppImage/flatpak bindings by OS: a driver whose own `requires:` can't be met somewhere (no
  snapd, no glibc, no libfuse2) is automatically not offered there.
- **`requires:`** is HARD (`epel`, `rpmfusion`, `glibc`, a toolchain like `go`/`cargo`, or another
  component). **`suggests:`** is SOFT (pulled if resolvable, else skipped — the mechanism for
  attaching `<name>-dotfiles`).
- **`standing: never-auto`** = valid + listed + pinnable but never the auto-default (use for an
  opt-in method that shouldn't be picked automatically). `standing: <int>` = a preference rank.
- Write a **one-line comment** explaining any non-obvious gating (why a `when:`, why EPEL, why a
  tarball) — every existing component does.
- **`attrs:` is expected on every real component** (an end-user tool/app/lib — not the `-dotfiles`/
  `-glue`/`-service`/`-group` companions, which self-tag). It's a free-form multi-tag list for
  cross-cutting filtering, ORTHOGONAL to profiles. Assign tags across the axes (full vocabulary + case
  rules in `docs/component-attrs.md`): **interface** `CLI`/`TUI`/`GUI`/`daemon`/`web`/`headless`;
  **role** `lib`/`SDK`/`app`/`toolchain`/`runtime`/`driver`/`font`/`theme`/`plugin`/`game`; **license**
  (combine all that apply) `FOSS`/`FOSSish`/`proprietary`/`source-available`/`freeware`/`GNU`/
  `copyleft`/`permissive`; **data** `tele`/`tele-optin`/`account`/`cloud`/`online`/`ads`/`paid`/
  `freemium`; **pedigree** `electron`/`patent`/`legacy`/`beta`. Case: ALL-CAPS acronyms (`CLI FOSS SDK
  GNU`), lowercase words. Interface/role you can read off the tool; **the license + data axes you MUST
  research per tool** (does it phone home? what license?) — only a human knows. `via: dotfiles`/`glue`/
  `service`/`group`/`font` auto-derive `dotfiles`/`glue`/`service`/`group`/`font` (`routes._VIA_ATTR`),
  so companions need no `attrs:`. Example: ``mpv: { … attrs: [ CLI GUI app FOSS copyleft ] … }``.

### 3. Fill the fallbacks (pick the right driver — see catalog below)
Order native-first, then fallbacks. Typical comprehensive rows:
- **Rust tool** (ripgrep, bottom, btop): `native` where packaged + `cargo` (or a release `tarball`
  with `requires: glibc`, plus a musl asset for alpine) for the rest.
- **Go tool** (micro, superfile, lazygit): `native` + release `tarball` (nested `bin/` is fine — the
  driver finds the binary).
- **GUI app / browser** (tor-browser): vendor `native` where it exists + `{ via: aur }` +
  `via: flatpak hub: flathub app: <id>` (flatpak is the universal + atomic-only method).
- **Upstream ships a .deb/.rpm** but not in-repo (fastfetch, yazi): `via: native-pkg-file when:
  "debian"` with `asset: { x86_64: …deb  aarch64: …deb }` (or format-keyed `asset: { deb: { x86_64: … }
  rpm: { x86_64: … } }` with `when: "debian or redhat"` to cover both in one binding).
- **Raw binary download** (no archive — kubectl/bazelisk style): `via: tarball  archive: none  binary:
  <name>` (a single gzip-compressed binary is `archive: gz`).
- Language-ecosystem tools: `cargo`/`pip`/`pipx`/`npm`/`gem`/`opam`/`luarocks`/`cabal`/`go-install`/
  `sdkman` — each takes `name:` (the crate/pkg/candidate) and often `requires: <toolchain>`.

### 4. Add `-glue` / `-dotfiles` companions whenever the tool needs shell setup or has config (implied — don't skip)
Two kinds of companion, kept apart (glue is SHIPPED shell integration; dotfiles are the user's own
app config, captured). Give the parent a soft `suggests:` for each one you add.

- **Shell glue → `<name>-glue`** — the tool needs PATH/aliases/env/init to work (a `~/apps`
  tarball/appImage install that isn't on PATH, like yazi/superfile aliasing `yazi`/`spf`; a
  completions or `init` line). **You author and ship it** in the base repo as
  `glue/shell/<shell>/<name>.<ext>` — one variant per shell: `bash/<name>.sh`, `zsh/<name>.zsh`,
  `fish/<name>.fish`, `nu/<name>.nu`, `elvish/<name>.elv` (start from an existing snippet; find an
  off-PATH install with the substrate's cached `cs_loc <component>` helper, never a per-snippet
  `configsys location`). Then declare the companion with a `glue:` NAME:
  ```
  <name>-glue: { description: "<name> shell setup, linked into place."
      install: [ { via: glue  requires: shell-glue  glue: <name> } ] }
  ```
  and add `suggests: <name>-glue` to the parent. The glue driver emits one spec per INSTALLED shell
  that ships a variant (materialized into the machine glue store, linked into
  `~/.config/<shell>/conf.d/<name>.<ext>`); a shell with no variant is a clean no-op, so adding a
  variant file later lights that shell up with ZERO component edits. nushell and elvish inline every
  snippet into one rc block, so their variants must self-guard (`add-shell.md` Part B has the idioms).
  (Onboarding a WHOLE NEW shell — its `conf.d` loader + driver wiring, not just one variant file — is
  its own playbook: **`add-shell.md`**.)
- **App config → `<name>-dotfiles`** — the tool reads its own config dir/file:
  ```
  <name>-dotfiles: { description: "<name> config, linked into place."
      install: [ { via: dotfiles  config: { src: <name>  dst: $XDG_CONFIG_HOME/<name> } } ] }
  ```
  `config:` is one named spec; add more named specs for stray files, each with its own `dst`
  (`micro-dotfiles` has four). The content usually **isn't shipped** — it lives in the user's content
  store, captured with `configsys dotfiles capture <name>` (which stores it under a
  `<name>-dotfiles.cfs/` marker dir + `manifest.hu`, auto-excluding secret-shaped paths). Installing a
  config `-dotfiles` stamps that `.cfs` marker even with no content yet, so the location reads as
  *managed*. Content resolves from the user's store first, then the primary plugin, then a `dotfiles/`
  dir next to the .hu that *defined* the component (base repo, else a plugin/user layer), so a package
  can offer a config that simply doesn't attach where the content is absent.
- **Both** (a tool with config AND shell setup — `neovim`, `zellij`): two separate companions,
  `suggests: [ <name>-dotfiles  <name>-glue ]`.

`suggests:` is SOFT: the parent installs fine whether or not the companion resolves, and the user can
opt a whole mechanism out with `disabled-drivers: [ dotfiles ]` (or `glue`). Links back up any
pre-existing real file to `<dst>.pre-configsys`. **Rule of thumb:** if installing the tool leaves a
PATH/alias/init it needs to be useful, add a `-glue` you write and ship; if it reads a config, add a
`-dotfiles` spec the user can capture into.

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

### 6. Profile placement — the `[…]` protocol, else only where it clearly belongs
**The bracket protocol (explicit, honor it):** if the argument named the component with a bracketed
profile list — `<name> [profile1, profile2]` (from step 0) — those are **base profiles the component
MUST be added to.** This is a direct instruction that overrides the default caution below. Add the
component as a member of each named profile: append it to that profile's list in `config.hu` (for a
base component) — e.g. `ripgrep [dev-tools]` → add `ripgrep` to the `dev-tools:` list in its
`profiles:` section. The named profiles are expected to **already exist**; if a bracketed name matches
NO existing base profile, treat it as a typo and ask rather than inventing one.

**Where the placement lives — base vs plugin.** A profile edit goes in the layer that DEFINES the
component, so base never references a plugin-only component:
- component added to base `routes.hu` → edit the base profile in `config.hu` (append the member).
- component added to a plugin (a `via: source` recipe in configsys-source, or any plugin) → put the
  membership in that **plugin's** `profiles.hu` as a `+<profile>` self-amend
  (`science: [ +science  <name> ]`), which augments the base profile only when the plugin loads —
  NOT in base `config.hu`. (`profiles:` must be a MAP `{ name: [ … ] }`, never an array
  `[ name: … ]`, which is a humon syntax error.)

**No bracket → judgment, default out.** Profiles are read-only browse lenses: membership never
installs anything (each machine installs exactly its `picks:`), so a profile edit only changes what
users see and can track from it. Add to one only for a natural fit: `tor-browser` → the
`web-browsers` list. Be deliberate with widely-used ROLE profiles (`user`, which folds in `+terminal`,
…): a user tracking that profile wholesale (TUI Profiles `T`) picks up everything in it. When unsure
and unbracketed, leave it out and mention it.

### 7. Validate (always, before committing)
```
.venv/bin/python -m configsys --os pop check          # lint the merged config (0 errors)
```
Run `check` across a spread of OSes (pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic/void/void_musl) — all must
be **0 errors**, and warning count must not rise. Then confirm each new component resolves to the
*expected* method per OS with a resolve sweep (adapt this):
```python
# reschk.py — prints "<comp>=<via>" per OS; ERR/EXC means it failed to route
from configsys.app import Context, build_parser
comps = ['<comp1>', '<comp2>']
for os in ('pop','fedora','arch','alpine','opensuse','rhel','fedora_atomic','void','void_musl'):
    r = Context(build_parser().parse_args(['--home','/tmp/nohome','--os',os,'inspect'])).routes
    row = []
    for c in comps:
        units, errs = r.resolve_resilient([c])
        keys = [k for k in units if units[k].name == c or c in k]
        via = keys[0].split('\\')[0] if keys else ('ERR' if any(c in str(e) for e in errs) else '—')
        row.append(f'{c}={via}')
    print(f'{os:14} ' + '  '.join(row))
```
Run with `.venv/bin/python reschk.py`. Also handy: `configsys --os <os>
where <component>` (source layer + resolution) and `configsys --os <os> request <component>`.

### 8. Regenerate the golden gate + run the suite
Adding components changes the frozen resolution snapshot (`test/routing_golden.json`, every
component × 13 contexts, incl. void + void_musl). Regenerate and confirm it's **purely additive**:
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
  zypper/apk/xbps (xbps on void-glibc with the nonfree repo enabled; for musl names, the
  configsys-void plugin's `test/run-name-sweep.sh` sweeps both flavors). **Run this after adding native bindings** — it's the cheap 80%-of-breakage catch.
- **Real-install lifecycle** (actually install/upgrade/remove in a throwaway container):
  `bash test/run-in-podman.sh [PKG]` (apt), plus targeted `test/run-{dnf,pacman,zypper,xbps,flatpak,
  clang,langs,…}-in-podman.sh` and `test/Containerfile.*` per distro. Use when a new method needs
  real verification (a vendor repo, a .deb file, a toolchain build).
- **Version-floor sweep** (if you added versioned `requires:`/source floors):
  `.venv/bin/python tools/versionsweep.py` (and `--derive` to emit a `version-floors:` block from
  source recipes). Networked; reflects THIS machine's repos — run in per-distro containers for full
  coverage.

### 10. Commit
Commit **locally** (the user pushes). Base identity + trailer (use the attribution line the system
currently provides; this is today's):
```
git -c user.name="Trevor Schrock" -c user.email="spacemeat@gmail.com" commit -m "components: add <names>

<one line per component: the methods it routes to and any notable gating>

Golden regenerated — purely additive. check: 0 errors across <OSes>.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
routes.hu/config.hu live immediately; `configsys-source` (plugin) changes are a separate repo/commit
and need re-sync+re-trust to load.

---

## Driver catalog (`via:` → when to reach for it)

**OS package managers** (`via: native` resolves to the right one; name a manager directly only to
pin it, or for a binding valid on just one, e.g. `{ via: apk  when: "alpine" }`): `apt` `dnf` `pacman`
`zypper` `apk` `xbps` `brew`. Plus `aur` (Arch community, `when: "arch"`), `rpm-ostree` (atomic
layering — rarely; prefer flatpak/brew there).

**Upstream distribution:**
- `native-pkg-file` — install an upstream release `.deb`/`.rpm`/`pkg` with the OS tool (rides
  neither the repo nor `apt upgrade`). Fields: `when:`, `version: { github: owner/repo }`,
  `asset: { x86_64: <name>.deb  aarch64: <name>.deb }` or format-keyed `asset: { deb: { x86_64: … }
  rpm: { x86_64: … } }` (the driver picks this machine's format), or a fixed `url:`.
- `tarball` — a release archive unpacked into its own `installDir:` (never a shared base — the dir is
  replaced on every (re)install). Fields: `installDir: "$CONFIGSYS_APP_DIR/<x>"`, `requires:` (`glibc`,
  `unzip`), `version: { github: … strip-v: … asset: "…$ARCH…tar.gz" }` or a `url:` template
  (`$VERSION`/`$ARCH`), `strip:` (drop leading tar path components), `archive: none` + `binary:` for a
  raw executable, `archive: gz` for a single gzipped binary. Provide a **musl** asset (or gate `not
  alpine`) for Alpine / void_musl.
- `appImage` — `name:` (menu label), `scope:`, `version: {…}` or `url:`, `path: ~/apps/<x>.appimage`,
  optional `icon:` and `desktop-id:` (the app's Wayland app_id, so its menu entry and dock icon match)
  (needs libfuse2).
- `flatpak` — `hub: flathub  app: <exact.app.id>` (`hub-url:` for a non-built-in remote). The
  universal GUI method + only method on atomic.
- `snap` — `name: <snap>`, optional `classic: true`, `channel:` (Ubuntu-centric; Chromium's real
  method there).
- `script` — declarative installer: `install-cmd`, `version-cmd`, `version-re`, `latest-cmd`,
  `uninstall-cmd`, `upgrade-cmd`, `set-version-cmd`, `location`.
- `font` — a downloadable font archive into the fonts dir + `fc-cache` (`name:`, `url:`/`version:`;
  requires fontconfig + unzip).
- `source` — build from a git checkout/archive (`repo:`/`url:`, `build:`, `tag-prefix:`; recipes live
  in the configsys-source plugin, §5).

**Language toolchains & their module installers** (take `name:` = crate/pkg/candidate, often
`requires: <toolchain>`): `cargo` `pip` `pipx` `npm` `gem` `opam` `luarocks` `cabal` `go-install`
`sdkman`. Toolchains themselves: `gcc` `gcc-toolset` `clang` `pyenv`.

**Post-install primitives:** `service` (`<name>-service` components — systemd `unit:`, or runit
`runit:` on Void; `start: false` enables without starting), `group` (usermod — `<name>-group`,
opt-in, `requires:` the group the pkg creates).

**Config:** `dotfiles` (`<name>-dotfiles`; named specs `config: { src: dst: }` or a top-level
`src:`/`dst:`), `glue` (`<name>-glue`: `{ via: glue  requires: shell-glue  glue: <name> }`; the
`shell-glue` substrate itself is `{ via: glue  loader: all }`). See §4.

**Aggregator:** `parts` — a component that is the union of its `parts:` (no unit of its own). Prefer
a **profile** over a parts-component for user-facing bundles.

## `version:` sources (for tarball / native-pkg-file / appImage / font / source / `latest-check:`)
`{ github: owner/repo  strip-v: true  asset: "<glob with $ARCH>" }` (+ `tag-re: "<regex>"` to pull the
version out of a decorated/monorepo tag like `core@1.2.3`, `pick: highest` for repos whose newest tag
isn't the highest) | `{ url: "<page>"  regex: "<ver-capture>" }` | `{ static: "<pinned>" }` |
`{ crates: <crate> }` | `{ pypi: <pkg> }` (+ `python:`) | `{ aur: <pkg> }` | `{ hackage: <pkg> }` |
`{ goproxy: <module> }`. `asset` is a glob resolved against the GitHub release (no hand-templated
URL); `$ARCH` expands (through `cpu-names:`). `tag-prefix:` is a `via: source` BINDING field (the git
tag = prefix + version), not a `version:` key. A `static:` pin can add a binding-level `latest-check:`
(a github or `url:`+`regex:` source) so `refresh`/`check` advise when upstream moves past the pin.

## Versions — visibility, version-scoped providers, floors
Three distinct things (the live reference is `docs/config-format.md` — "Choosing among methods" and
"Versions"; the full model, including floors and version-scoped providers, is `docs/versioned-requires.md`):
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
- **musl (Alpine, void_musl).** glibc tarballs/appImages won't run (`requires: glibc` makes them
  decline cleanly). Give musl a native pkg, a musl asset, or let it decline.
- **Void flavors are siblings.** `when: "void"` does NOT match `void_musl` — write `void or void_musl`
  (or just `void` deliberately, for a glibc-only package). Extending an existing or-list
  (`"debian or fedora or arch"` → `"… or void or void_musl"`) is house style; don't extend a binding
  that carries `requires: epel`/`ppa:`/vendor-repo fields — add a separate Void binding instead.
- **Services on Void use runit.** A `-service` component's `{ via: service  unit: X }` also works
  under runit when Void's service dir is `/etc/sv/X`; if it differs add `runit: <name>` (a list, or
  a glob like `"postgresql[0-9]*"` for versioned dirs) — check with `xbps-query -R -f <pkg> | grep
  /etc/sv/`.
- **Name drift.** `name:` maps per distro; the name-sweep catches renames/removals — run it.
- **Binary ≠ package name.** Note the real binary in the description (`btm`, `spf`, `nvim`, `hx`).
- **Metapackage installed via its parts.** If a component installs an apt METAPACKAGE that a system
  often has WITHOUT (Debian/Ubuntu/Pop ship LibreOffice as `libreoffice-core`/`-calc`/… without the
  `libreoffice` meta), probing the meta falsely reports "missing". Add `installed-name: <a-part>` to
  the native binding — apt READS state from it while `name` still installs the meta (`libreoffice`
  detects via `libreoffice-core`). Honored by the repo package managers apt/dnf/pacman/zypper/apk/xbps
  (as is `packages: [...]`, a set installed/removed together, detected via `installed-name:` else its
  first member) — NOT by `brew`.
- **CPU (aarch64).** A download that names a cpu (`amd64`, `x86_64`, `x64`, `linux64`, `64bit`)
  must say which cpus it covers: `$ARCH` + `cpu-names: { x86_64: <token>  aarch64: <token> }` (the
  tokens upstream actually uses — check the release assets), or `cpu-names: { x86_64: <token> }`
  alone when there's no arm64 build. Never a bare x86 literal (it installs an x86 binary on ARM),
  and not `when: "cpu: x86_64"` (that out-specifics other methods). See docs/routing-model.md §7.
- **Exactness.** Flatpak app-ids and asset globs fail silently if wrong — verify by search, and by
  the resolve sweep + (ideally) a podman real-install for the risky ones.
