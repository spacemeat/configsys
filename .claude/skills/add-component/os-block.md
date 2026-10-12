# Adding an OS block — routes.hu `os:` section

An **OS block** is not a component. It's an entry in routes.hu's `os:` section that teaches configsys
about a distro/environment: its lineage, its package manager, its version numbering, and the
capabilities it provides for free. Components then route onto it through `when:` atoms and `via:
native`. Read this instead of the main component steps when the user is adding a distro/OS (a new
Debian/Fedora/Arch derivative, a corporate distro, an immutable/atomic environment, an alt-libc
target). The authoritative model is `docs/routing-model.md` + the routing section of CLAUDE.md.

## The shape of a block

```
<name>: { using: <parent>  [native: <mgr>]  [scale-root: true]  [provides: <caps>]  [detect: {…}] }
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
   `native:`/`scale-root:`/`provides:`). Declare `native:`/`provides:` only where they change.
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
     (SKILL.md step 7: pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic/void/void_musl) so a
     shared-parent edit didn't regress them.
   - Resolve sweep on the new atom: force `--os <block>` (`--os <block>:<version>` for a versioned
     block — without one, every version condition reads false) and confirm a handful of components resolve
     to the method a human would pick there (the `reschk.py` pattern in SKILL.md, with your block in
     the OS list).
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
7. **Commit locally** (base identity + trailer, per SKILL.md step 10). Note the block, its lineage,
   scale-root decision, and detection mechanism in the message.

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
