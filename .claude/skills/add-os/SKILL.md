---
name: add-os
description: Playbook for adding an OS to configsys — a new distro, derivative or environment as a routes.hu `os:` block (lineage, package manager, version numbering, detection, provided capabilities) plus, for a versioned line, its release registry (`releases:`) and sweep setup. Use when the user says "/add-os <distro>", asks to support a new distro/derivative/immutable or musl environment, or /add-component's dispatch sends an OS block here. A NEW RELEASE of an OS configsys already knows (Fedora 45, Ubuntu 26.10) is /update-os, not this.
---

# add-os — a new OS block (routes.hu `os:` section)

An **OS block** is not a component. It's an entry in routes.hu's `os:` section that teaches configsys
about a distro/environment: its lineage, its package manager, its version numbering, the
capabilities it provides for free, and — for a versioned line — which releases exist (the release
registry). Components then route onto it through `when:` atoms and `via: native`. Use this when the
user is adding a distro/OS (a new Debian/Fedora/Arch derivative, a corporate distro, an
immutable/atomic environment, an alt-libc target). The authoritative model is
`docs/routing-model.md` §6 + the routing section of CLAUDE.md.

**Not this skill:** a new release of a line configsys already has (Fedora 45, Ubuntu 26.10,
Alpine 3.25) is **`/update-os <line> <release>`** (`.claude/skills/update-os/SKILL.md`) — it fills
the release's registry entry, sweeps it, and closes the gaps while keeping the older releases
correct. Once a block you add here has a registry, `/update-os` maintains it.

## The shape of a block

```
<name>: { using: <parent>  [native: <mgr>]  [scale-root: true]  [provides: <caps>]  [detect: {…}]
          [releases: { <VERSION_ID>: { status: …  … } }] }
```

- **`using: <parent>`** — single-parent lineage. Everything cascades: the parent's `native:`,
  `provides:`, and `when:`-subtree membership are inherited. The spine is
  `linux → glibc_linux → {debian, redhat, arch, opensuse, fedora_atomic, kde_linux, void}` and
  `linux → {alpine, chimera, void_musl}` (musl). A bare atom in a `when:` matches a block AND all its descendants (inheritance by identity).
- **`native: <mgr>`** — the OS package manager `via: native` resolves to: `apt`/`dnf`/`pacman`/
  `zypper`/`apk`/`xbps`/`brew`. **Declare it only where it CHANGES** from the parent; a pure rebrand inherits
  it. (Debian declares `apt`; Pop/Mint/Kali just `using` a parent and inherit it.) A block may also
  have NO native manager at all (`kde_linux`, `chimera`) — see *Native-less blocks* below.
- **`scale-root: true`** — this block OWNS a version-numbering line. **The load-bearing decision.**
  A distro whose version numbers are *identical* to its parent's borrows the parent's scale (NO
  scale-root — Pop 22.04 IS Ubuntu 22.04). A distro with its OWN numbering (Mint 21 ≠ Ubuntu 22.04,
  Amazon Linux 2023, elementary 8, Zorin 17/18 — whose VERSION_ID is the major only) MUST be a
  scale-root, so a versioned parent atom
  (`when: "ubuntu < 23.04"`) does not misfire on it. Rolling distros (Arch, Tumbleweed, Kali) have no
  scale at all — bare membership, no scale-root.
- **`provides: <cap|[caps]>`** — capabilities satisfied *for free* here, so a `requires:` is met with
  nothing installed: `glibc` (on `glibc_linux`), `python3` (on `linux`, the bootstrap guarantee),
  `flatpak` (on `fedora_atomic`, pre-installed), `[ flatpak  curl  git  unzip  xz ]` (on `kde_linux`,
  per its image's package lists). Add one only when the environment genuinely ships the capability.
- **`detect: { id: <base>  marker: <path|[paths]> }`** — see *Runtime detection* below; only for a
  derivative that does NOT rebrand `/etc/os-release`.
- **`releases:`** — the release registry; only on the block that OWNS a version line (see *The
  release registry* below).

## The libc axis (orthogonal to family)

glibc distros hang off **`glibc_linux`** (inherit the `glibc` capability). musl distros (Alpine, a
musl Void) hang off **`linux`** directly — so glibc-only methods cleanly DECLINE there instead of
installing a binary that can't run: a tarball's `requires: glibc`, the appImage driver's own
`requires: [ libfuse2, glibc ]` (the derived driver gate), and brew's explicit `when: "glibc_linux"`
gate. If the new OS is musl, do NOT put it under `glibc_linux`.

## Native-less blocks

An environment whose package manager configsys can't use declares no `native:` (and hangs off a
parent that has none — `glibc_linux` or `linux`), so every `via: native` binding declines there and
only portable methods route (flatpak, brew on glibc, musl/glibc tarballs, scripts, cargo, …) — and
only where their prerequisites are met (`provides:`, or a portable route to them). Two shapes today:
`kde_linux` (immutable, no package manager for users; `provides:` the tools its image ships, so
tarball/source prerequisites are met) and `chimera` (musl; apk-tools v3 but NOT Alpine's package
names, so the `apk:` names in routes would be wrong — no `native:` until Chimera-named
`via: apk  when: "chimera"` bindings are verified by a name sweep; it provides no curl, so tarball
and cargo can't work there and practically only dotfiles/glue and self-contained scripts route).
Prefer this to inheriting a manager whose names don't fit.

## Runtime detection — how a machine maps to your block (osdetect.py)

Three mechanisms; pick based on what `/etc/os-release` reports:

1. **os-release `ID` == block name (the default, no code).** `block_for_id` returns the ID
   unchanged, so **name the block exactly the lowercased os-release `ID`** and detection just works
   (Rocky's `ID=rocky` → `rocky:` block). This is why cheap descendants are one-liners.
2. **Name can't equal the ID → an alias in `osdetect.py`.** Only when the block name can't be the ID:
   a punctuation/format clash (`ID=pop` → block `pop_os!`; hyphens → `opensuse_leap`, `kde_linux`,
   since the `when:` DSL has no `-` — use `_`), or a distro you deliberately fold into another block
   (`steamos` → `arch`, `raspbian` → `pios`). Add an entry to `_ALIASES` in `configsys/osdetect.py`.
3. **Derivative that keeps a base's os-release ID → a `detect:` marker (data-driven, no code).** A
   distro that reports a base ID (Proxmox VE reports `ID=debian`; Raspberry Pi OS Bookworm+ too)
   declares `detect: { id: <base>  marker: <path> }` (marker may be a list). When the detected block
   is that base (or a descendant) AND every marker exists on disk, `refine()` routes to your more-
   specific block. `pios` (marker `/etc/rpi-issue`) and `void_musl` (`id: void`, marker the musl
   loader `/lib/ld-musl-x86_64.so.1`) are the examples; `fedora_atomic` is the built-in
   ostree-marker special case. A forced `CONFIGSYS_OS` is never second-guessed.

`VERSION_ID` (osversion.py) feeds the `when:` version atoms; a `scale-root` governs which versioned
atoms bind. Nothing to author for versions — just get `scale-root` right.

## Cheap descendant (the common case)

A distro that's just a rebrand of a base — same package manager, same or borrowed version line — is
**one line**: `<name>: { using: <base> }`. It buys identity (`when: "<name>"`, correct display, a
name for pins/overrides) with zero routing change. Add `scale-root: true` **iff** it numbers its own
releases. Add a `native:` only if the manager differs. That's usually the whole job — most of the
`os:` section is these one-liners with a `//` comment naming the distro and its numbering.

## The release registry — `releases:` on the line owner

Every **versioned line** carries its releases, so "which releases do we support" has one answer
that the maintenance tools sweep (`tools/osaudit.py`; docs/routing-model.md §6). The owner is the
block `OsCascade.version_line` names: a scale-root, or a block with no scale-root above it that
declares `releases:` (alpine). A borrower (`pop_os!`, `nobara`, `rocky`) declares nothing — it reads
its parent's table; an own-numbering derivative (`linuxmint`, `zorin`) gets its OWN table, never
its parent's. Rolling blocks (arch, tumbleweed, void, kali) have none.

```
fedora: { using: redhat  scale-root: true
    releases: {
        42: { status: released  released: 2025-04-15  eol: <date>  image: "docker.io/library/fedora:42"
              glibc: 2.41  python3: 3.13  gcc: 15  manager: "dnf5 version 5.2.x" }
        45: { status: prerelease  image: "docker.io/library/fedora:45"  … }
    } }
```

- **Keys** are the VERSION_ID os-release reports (`22.04`, `13`, `3.24`; EL by its major, `9`).
- **`status:`** (required) `prerelease` / `released` / `eol`. List every release still in use
  (released and supported upstream), the next one once it has a branched image, and recently EOL'd
  ones the routes still mention (`status: eol`) — an EOL release keeps its gates and stays
  routable; it just isn't swept.
- **Facts** — read them from the release's own image, never from memory:
  `.venv/bin/python tools/osaudit.py facts <line> <release> --image <image>` prints VERSION_ID,
  codename, glibc, the repo's python3 / gcc and the package-manager version, plus a paste-ready
  entry. Dates (`released`, `eol` — YYYY-MM-DD) come from the distro's own lifecycle page (or
  `https://endoflife.date/api/<product>.json`); `codename:` is required for apt lines (PPAs and
  `$CODENAME` source lines are probed with it); `image:` is a fully qualified reference
  (`docker.io/library/…`) — without one the release can't be swept.
- **Sweepable?** `tools/osaudit.py sweep` needs a container-side repo setup for the line in
  `osaudit._SETUPS` (enable the repos its routes assume: universe, EPEL + CRB, RPM Fusion, Alpine
  community, …). Add one for a new line with an image; a line with no public image (most
  desktop derivatives) is simply not swept — say so.

## Where it lives — base vs plugin

- Core/mainstream distro → base **routes.hu** `os:` section (live immediately).
- A niche derivative or corporate distro can ship in a **plugin**: `merge_dict_section` unions
  `os:`/`drivers:` from repo + plugin, so a plugin adds os blocks (and `detect:` markers) with no
  core edit. Plugin changes need re-sync + re-trust to load.

## Steps

1. **Identify the lineage + libc.** Which family (apt/dnf/pacman/zypper/apk/xbps/brew)? glibc or musl?
   Read `/etc/os-release` (`ID`, `ID_LIKE`, `VERSION_ID`, `VARIANT_ID`) on a real image or from docs.
   Find the closest existing block to `using`.
2. **Decide `scale-root`.** Does it number releases with its OWN scheme, or share the parent's exact
   numbers, or roll? Own scheme → `scale-root: true`. This is the one you must not get wrong.
3. **Write the block** next to its siblings, with a one-line `//` comment (distro, numbering, why any
   `native:`/`scale-root:`/`provides:`). Declare `native:`/`provides:` only where they change. If
   it owns a version line, add its `releases:` (above) — every live release, facts from
   `osaudit facts`.
4. **Wire detection** (only if needed): name == ID (nothing), else an `_ALIASES` entry, else a
   `detect:` marker. If you fold it into an existing block instead of giving it its own, that's an
   alias, not a block.
5. **Native package names.** `via: native` defaults to the component name; if this manager names
   packages differently, existing components may need `name: { <mgr>: … }` maps — the name-sweep
   (below) catches these. A brand-new manager also needs a driver — the **`/add-driver`** playbook
   (`.claude/skills/add-driver/SKILL.md`, §4 for a native manager) — but the seven listed above
   already exist. If the OS's manager exists but its package names don't match the existing maps,
   go native-less (above) rather than inheriting broken names.
6. **Validate:**
   - `.venv/bin/python -m configsys --os <block> check` → 0 errors; also run the existing spread
     (add-component SKILL.md §7: pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic/void/void_musl)
     so a shared-parent edit didn't regress them. `check` also lints the `releases:` shape
     (`os-release` warnings) — none allowed.
   - Resolve sweep on the new atom: force `--os <block>` (`--os <block>:<version>` for a versioned
     block — without one, every version condition reads false) and confirm a handful of components resolve
     to the method a human would pick there (the `reschk.py` pattern in add-component SKILL.md, with
     your block in the OS list). For a versioned line, `tools/osaudit.py releases <block>` shows the
     registry with no staleness warnings, and `tools/osaudit.py sweep <block>` (when it has an
     image + setup) is the name sweep across its live releases — it supersedes the single-release
     sweep below for that line.
   - **Name-existence sweep** for the manager (podman): `bash test/run-name-sweep-in-podman.sh
     <manager>` — the cheapest catch for native-name drift on the new OS.
   - Golden gate: `CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py -q`, then
     semantic-diff vs HEAD. The golden covers a FIXED list of 13 contexts (`CONTEXTS` in
     `test/test_golden.py`), so a new block adds no column by itself — and existing contexts must be
     unchanged (`changed=[]`); a shift means a new atom leaked into a sibling's routing (or a parent
     edit changed it). Add the block to `CONTEXTS` only for a new base family worth freezing.
   - Add an **osdetect test** (`test/test_osdetect.py`; markers in `test/test_detect_marker.py`)
     asserting your ID/marker/alias maps to the block, and (if `scale-root`) that a versioned parent
     atom does NOT bind on it.
   - Full suite: `.venv/bin/python -m pytest test/ -q`.
7. **Commit locally** (base identity + trailer, per add-component SKILL.md step 10). Note the block,
   its lineage, scale-root decision, detection mechanism and registered releases in the message.

## Gotchas

- **scale-root is the trap.** Forget it on an own-numbering distro and versioned parent atoms
  (`ubuntu >= 24.04`) misfire on it; add it spuriously on a version-sharing rebrand and the parent's
  versioned bindings stop reaching it. Match the real numbering.
- **`_` not `-` in block names** — the `when:` DSL has no `-`. os-release's hyphenated IDs alias in.
- **Fedora ≠ EL.** EL rebuilds (`rocky`/`almalinux`/`centos`/`ol`/`scientific`) `using: rhel` and
  often need `requires: epel`; Fedora derivatives `using: fedora` (`nobara`). A Fedora-derived distro
  with its own repos and numbering and no EPEL (`amzn`) sits directly under `redhat` as a scale-root.
  Don't cross them.
- **Atomic/immutable** environments model as their own block off `glibc_linux` (like `fedora_atomic`),
  NOT under the mutable family — keeps dnf/EPEL/repo-component bindings from misfiring; prefer
  flatpak + brew, `provides: flatpak` (or native-less, like `kde_linux`). Don't hand-gate AppImage
  or snap off it: with no libfuse2 / snapd route those drivers are already not offered (derived
  gates). Add a brew/rpm-ostree-style atomic block to `ATOMIC_BLOCKS` in osdetect.py for the
  not-hardware-validated advisory.
- **musl under `glibc_linux`** installs binaries that can't run — put musl distros under `linux`.
- **A shared-parent edit is global.** Editing a base block (debian/redhat/…) to fit a new child can
  change every descendant — re-run `check` + the golden diff across the family.
