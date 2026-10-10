# Routing model — capabilities, components, bindings

> **Status: REFERENCE** — the routing model as built; maintained. It is the sole resolver
> (`configsys/routes.py` loads, `configsys/predicate.py` evaluates `when:`, `configsys/resolve.py`
> resolves, `configsys/routecheck.py` lints, `configsys/detection.py` adopts installed reality).
> It replaced the old `\family`-block resolver **in place** (built in parallel, proven
> byte-equivalent, then flipped; the old resolver and its data are deleted, and
> `test/routing_golden.json` freezes the proven resolution as a regression gate). §1, §12 and §14
> are **history** — the tangle this design removed and the migration that removed it. CLAUDE.md
> carries the short summary; `docs/principles.md` the cross-cutting invariants.

---

## 1. Why (history — the pre-v2 system, now deleted)

Before this redesign `routes.hu` tangled three different concerns, so "where does this go?" had no
single answer:

- **Family blocks** (`\apt`, `\dnf`, `\pacman`, …) hold per-component package data keyed
  by install mechanism.
- **OS blocks** (`debian`, `ubuntu`, `fedora`, version variants) form the cascade and
  route names to families via `*: apt\*` + explicit per-OS entries.
- **`\app` blocks** (neovim, steam) are the *only* place a component gets a real
  identity (method-independent deps + per-method bindings).

Symptoms of the tangle:

- **No first-class Component layer.** For `btop`, the "component" is just a bare name
  the cascade binds directly, so identity and method-independent dependencies have
  nowhere to live. When `\cargo` needed a dotfile dependency, it had to be bolted onto
  the *family* `!depends` (wrong scope — shared by every crate) because there was no
  `cargo` component to hang it on.
- **Family-name / package-name collision.** `\cargo` (a mechanism: "install a Rust
  crate") shares a name with `cargo` (a package/tool). Same for `\gcc`, `\pip`, etc.
- **Dependencies live in four places** (family `!depends`, component `depends`, OS-route
  `depends`, list bundles) with no rule for which.
- **Boilerplate.** Every native package needs an entry in each family block it appears
  in (`\apt btop`, `\dnf btop`, `\pacman btop`), usually just echoing its own name.
- **Two ways to vary by OS** (per-OS routes vs. `\app` methods) with no principle.
- **No CPU-arch selection**, only `$ARCH` string substitution (which mis-renders:
  `amd64` vs `x86_64`).

## 2. The core idea

> **A component *is* a named capability; each of its bindings is one way to acquire it.**

- **Component** — the thing you want (`btop`, `neovim`, `cargo`, `jdk-21`): an identity plus an
  ordered list of context-selected **bindings**. A component always implicitly provides its own
  name as a capability, and may `provides:` more.
- **Binding** — one way to install the component in some set of contexts: `via: <driver>` + an
  optional `when:` validity predicate + driver-specific fields.
- **Driver** — the code behind one install mechanism (configsys/drivers/). Each `via:` value names
  a driver 1:1 (`apt`, `flatpak`, `appImage`, `cargo`, `tarball`, `aur`, `gcc-toolset`, …; see
  configsys.hu(5) for the registered set), except `via: native` (resolves to this OS's package
  manager, §3) and `via: parts` (a pure aggregator, no driver).

There are two selection moments, and they share one notion of **validity** (a binding is a
*candidate* when it passes `_matching`, §8a; a provider is *viable* when one of its bindings can be
selected here) but **not** one ranking rule:

- **Binding selection** ("given we install neovim, how?") — specificity, then `standing:`, then
  `driver-preference` (§8, §8a).
- **Provider selection** ("who supplies `cxx-stdlib`?") — reuse what is already in the inventory,
  else the unique auto-eligible viable provider; several = an ambiguity error that needs a
  provider-pin (§9). Providers are **not** ranked by specificity.

## 3. Component and binding shape

Schema (placeholders in `<…>`; every real entry is humon `key: value`, `when:` a string):

```text
<name>: {
    provides:  <cap | [caps]>      // optional; a component always implicitly provides its own name.
                                   //   A versioned entry is a map: `provides: { python3: "3.13" }` (§11)
    requires:  <cap | [caps]>      // HARD method-independent needs (unmet here = error).
                                   //   Versioned: `requires: [ { go: ">=1.21" } ]` (§11)
    suggests:  <cap | [caps]>      // SOFT needs: pulled in if resolvable in the loaded layers,
                                   //   skipped silently if not (a package `suggests:` its
                                   //   `<name>-dotfiles` / `<name>-glue`, which may live only in a plugin)
    standing:  never-auto          // on a component-provider: its capabilities are NEVER auto-pulled
                                   //   to satisfy someone else's `requires:` — only used when wanted
                                   //   directly, required by its own name, version-constrained, or
                                   //   provider-pinned (gcompat, libc++, versioned gcc/clang). An
                                   //   integer here is accepted but has no effect (§8a)
    description: "<one line>"      // shown in the TUI infobox / catalog
    attrs:     [ <tags> ]          // cross-cutting kind tags (CLI/TUI/GUI/FOSS/…; docs/component-attrs.md)
    parts:     <cap | [caps]>      // accepted for back-compat and counted by Resolver.dependents, but
                                   //   IGNORED by resolution — aggregation lives on a `via: parts` binding

    install: [                     // ordered list of bindings
        { via: <driver>  when: "<predicate>"  standing: <never-auto | int>
          requires: … suggests: … provides: …     // binding-level edges (only when THIS method wins)
          …driver fields… }
        { via: parts  parts: [ <components> ] }   // aggregator: the union of its parts, no unit of its own
        { via: dotfiles  … }  { via: glue  glue: <name> }   // config / shell-glue companions
    ]
}
```

Any other top-level key is a load error (`routes._check_component_keys`) — a typo or a removed
construct must fail loudly, not vanish.

- A **binding** names its driver with `via:` (required), guards itself with an optional `when:`
  (absent = valid everywhere), and carries driver fields. Common fields: `name:` (package name, a
  per-driver map for `native`), `packages:` (a native multi-package set), `installed-name:` (below),
  `version:` (a version source), `asset:` / `cpu-names:` (§7), `scope:`, `installDir:`.
- Binding-level `requires:`/`suggests:` are edges taken only when that binding wins. A binding-level
  `provides:` contributes **no** capability names to resolution (providers are indexed from the
  component's `provides:` only); its versions feed the version-floor sweep/advisory (§11).
- `requires`, `suggests`, `parts`, `app` and `standing` are resolver keys stripped before the fields
  reach a driver (`resolve._RESOLVER_KEYS`); everything else is handed to the driver unchanged.
- The `install:` list is **disjunctive selection** — "here are the ways; pick the best match" —
  *not* an implicit and/or. All validity logic lives in `when:`; preference lives in `standing:` /
  `driver-preference` (§8a). List order matters only for display and for the `{}`/merge identity.
- A component whose merged `install:` is empty (a `{}` override, §10a) is **removed**: naming it is
  a silent no-op, distinct from a component that has bindings but none valid here (an error).

### `native` — the sugar that kills the boilerplate

`via: native` resolves to the OS's package manager, declared **once per OS block** and inherited
down the lineage (`OsCascade.native` walks `using` to the nearest `native:`). Excerpt of the real
`os:` section:

```humon
{ os: {
    linux:       { provides: python3 }
    glibc_linux: { using: linux  provides: glibc }
    debian:      { using: glibc_linux  native: apt   scale-root: true }
    ubuntu:      { using: debian    scale-root: true }
    pop_os!:     { using: ubuntu }                       // borrows ubuntu's apt and version scale
    redhat:      { using: glibc_linux  native: dnf }     // fedora + EL share dnf
    fedora:      { using: redhat    scale-root: true }
    rhel:        { using: redhat    scale-root: true }
    arch:        { using: glibc_linux  native: pacman }
    alpine:      { using: linux  native: apk }           // musl: under linux, not glibc_linux
    kde_linux:   { using: glibc_linux  provides: [ flatpak  curl  git  unzip  xz ]  scale-root: true }
    chimera:     { using: linux }
} }
```

The package name defaults to the component's own name; override per driver where it differs
(`name.get(<driver>) or name.get(default) or <component name>`, `resolve._package`):

```humon
{
    btop:        { install: [ { via: native } ] }
    python3-pip: { install: [ { via: native  name: { pacman: python-pip  zypper: python313-pip  apk: py3-pip } } ] }
    libfuse2:    { install: [ { via: native  repo-component: universe
                                name: { xbps: fuse  dnf: fuse-libs  pacman: fuse2  apk: fuse  default: libfuse2 } } ] }
}
```

**Native-less OS blocks.** An OS block whose lineage declares no `native:` has no system package
manager — `kde_linux` (image-based, pacman removed) and `chimera` (apk-tools v3, but not Alpine's
package names, so no `native:` until Chimera-named bindings are verified). `OsCascade.context` sets
`Context.has_native = False` there, and `resolve._matching` drops every `via: native` binding — it
is simply not a candidate, like a false `when:` — so components fall through to flatpak, tarballs,
cargo, pipx, …, and distro-package-only components decline honestly (unroutable, not an error
about a missing driver). Such blocks list what the image already ships in `provides:` so those
methods' prerequisites (`tarball requires: curl`, `source requires: git`, `flatpak`) are met for
free. (`linux`/`glibc_linux` are native-less abstract parents; no machine detects as them.)

**`installed-name:` — detect a metapackage by a part.** `name` drives install/remove/upgrade;
`installed-name` is the package configsys PROBES for install-state and version when it differs
from what it installs. It is read by every OS package-manager driver built on
`drivers/_native.NativePkgManager._probe_name` (apt, dnf, pacman, zypper, apk, xbps; not brew).
Without it the probe reads the first of `packages:`, else `name`. The motivating case: Debian/
Ubuntu/Pop commonly ship LibreOffice as its parts (`libreoffice-core`/`-calc`/…) without the
`libreoffice` meta, so probing the meta falsely reports "missing":

```humon
{ libreoffice: { install: [ { via: native  when: "(not fedora_atomic) and not amzn"  repo-component: universe
                              name: { pacman: libreoffice-fresh }  installed-name: libreoffice-core } ] } }
```

(The field is driver-agnostic: a binding that reaches several managers probes `installed-name` on
every one of them, so it must name a package that exists under each.)

This deletes all `\apt btop` / `\dnf btop` / `\pacman btop` triplicate entries and the
`*: apt\*` wildcard. The OS blocks shrink to *lineage + which manager is native*.

## 4. Capabilities

A capability is **a label**. `provides:` declares it, `requires:`/`suggests:` match it by name. The
resolver never inspects a capability directly; it is **satisfied when a provider is in the
inventory** (an environment capability, or a resolved unit that provides it). A capability may
also carry a **version** (`provides: { python3: "3.13" }` / `requires: { python3: ">=3.11" }`):
names still close exactly as unversioned ones, and the version only selects among providers or
raises an advisory — see §11.

Two flavors, same kind of atom:

- **Concrete** — has a component that installs it directly: `cargo`, `chrome`, `epel`.
- **Virtual** — only ever appears in `provides:`, nothing installs it directly:
  `cc`, `cxx`, `cxx-stdlib`, `C++20`, `C11`. Pure labels, authored data, unverified by configsys.
  They exist to *abstract over incompatible numbering* — `C++20` is meaningful across gcc and
  clang; `compiler >= 18` is not.

```humon
{
    // abridged from routes.hu. Every versioned gcc/clang carries the standard labels, all `standing: never-auto`
    // (so a plain `requires: cxx` still resolves to the unversioned cpp-toolchain, no ambiguity).
    gcc-15:   { provides: [ cc, cxx, C11, C17, C23, "C++17", "C++20", "C++23", "C++26" ]  standing: never-auto
                install: [ { via: gcc  when: "debian"  packages: [ gcc-15, g++-15 ] }  { via: gcc-toolset  when: "rhel" } ] }
    clang-18: { provides: [ cc, cxx, C11, C17, C23, "C++17", "C++20", "C++23" ]  standing: never-auto
                requires: [ c-toolchain, cxx-stdlib ]
                install: [ { via: clang  when: "debian"  packages: [ clang-18 ] }  { via: clang  when: "fedora"  packages: [ clang18 ] } ] }
    some-app: { requires: "C++20"  install: [ { via: native } ] }   // satisfied by a wanted or provider-pinned versioned compiler
}
```

The unversioned `cc`/`cxx` providers (`c-toolchain`/`cpp-toolchain`) are the always-on *system
default* compiler; the versioned ones layer specific-standard labels on top, `never-auto` so they
never shadow the default. Because the default toolchains do not (yet) declare which standard they
support, `requires: "C++20"` is satisfied only by a co-wanted or provider-pinned versioned
compiler — with none, it errors "nothing auto-provides" and names the pin to add.

The **C++ standard library is its own capability**, `cxx-stdlib`, separate from the compiler —
g++ bundles its library (libstdc++) but clang doesn't (on Linux it uses gcc's libstdc++ by default,
or LLVM's libc++ via `-stdlib=libc++`). So `clang-NN requires: [ c-toolchain, cxx-stdlib ]` (the
gcc runtime it needs + *a* stdlib) rather than the g++ compiler. `cxx-stdlib` resolves to the
`libstdc++` component (auto-eligible) — whose Debian and Alpine bindings install `g++`, since the
default C++ dev headers ship only with it there — and `libc++` is a `never-auto` alternate selected
with a provider-pin (`pins: { cxx-stdlib: libc++ }`). Note clang requires the *component*
`c-toolchain`, not the `cc` capability: clang itself `provides: cc`, and requiring the capability
would let it satisfy itself and never pull gcc (see the bootstrap-guard caveat in §9).

**Environment capabilities.** An OS block can `provides:` capabilities that are baseline in that
environment (`OsCascade.provides` unions them over the lineage); the inventory starts with them, so
requiring one is free there and pulls a provider (or declines) elsewhere:

```humon
{
    os: {
        linux:       { provides: python3 }                 // the bootstrap guarantees a python3
        glibc_linux: { using: linux  provides: glibc }     // every glibc family inherits `glibc`
        alpine:      { using: linux  native: apk }         // musl: no `glibc`
    }
    drivers: { appImage: { requires: [ libfuse2, glibc ] } }
    components: {
        gcompat: { provides: glibc  standing: never-auto  install: [ { via: apk  when: "alpine" } ] }
    }
}
```

An AppImage method's `glibc` need is free on a glibc distro; on Alpine it fails ("nothing
auto-provides glibc … e.g. pins: { glibc: gcompat }") because the only provider there is the
best-effort `gcompat` shim, which is `never-auto` — opt in with that provider-pin. Repo enablement uses the same shape:
EL-only bindings carry a binding-level `requires: epel`, satisfied by the `epel-release`
component (`provides: epel`).

**Design boundary:** the `provides:` lists are *your data*, not knowledge configsys
claims. configsys stays a mechanical string-matcher; it never reasons about C++
standards. The cost is that a wrong label installs the wrong thing silently — treat the
lists as carefully-authored, one-line-to-fix data.

## 5. The `when:` predicate language

`when:` is a single boolean expression string, parsed by a small recursive-descent parser
(`predicate.parse`; an absent/empty `when:` is `ALWAYS`). It is evaluated against a fixed
`predicate.Context`: the OS lineage, the OS version, the cpu, the scale-roots, and the detected
facets.

**Atoms** (identifiers are `[A-Za-z_][A-Za-z0-9_]*` with an optional trailing `!`, so OS block
names use `_`, never `-`: `opensuse_leap`, `pop_os!`):
- **bare OS** — `debian`, `ubuntu`, `pop_os!`, `fedora`, `arch` — **subtree membership**
  (`debian` matches Debian *and* everything deriving from it via `using`).
- **versioned OS** — `ubuntu < 23.04`, `debian >= 12`, `fedora = 41` (operators `<` `<=` `>` `>=`
  `=` `==`) — subtree membership **and** the system is on that OS's version scale
  (see [§6](#6-os-lineage-version-scales-identity)) **and** the comparison holds.
- **cpu** — `cpu: x86_64`, `cpu: [ x86_64, aarch64 ]` (commas optional). True when the machine's
  cpu is in the set.
- **facet** — a declared detected fact (`facets:` section; see `docs/facets.md`): categorical
  `gpu:nvidia` / `gpu:[nvidia amd]` (same `ns:value` syntax as cpu — cpu is just the categorical
  namespace `cpu`), or versioned `cuda >= 12` (a versioned atom whose name is not in this lineage
  but is a detected version facet). An undetected facet makes its atom false.

**Operators:** `and`, `or`, `not`, parentheses. Precedence `not > and > or`. (There is no `!`
operator — `!` is only legal as the last character of an identifier.)

**Negation.** `not` complements any atom — an OS subtree, a `cpu:`/facet set, or a versioned
bound. (It was historically restricted to OS atoms to keep the ambiguity checker's complement to
"subtree minus subtree"; the grid-based checker handles the general case, so evaluation and the
checker both accept `not`/`or` over any atom.) It is exactly enough to carve subtree members apart:

```humon
{ snapd: { install: [ { via: native  when: "(debian or redhat) and not amzn"  name: snapd }   // apt/dnf snapd, not Amazon Linux
                      { via: aur     when: "arch"  name: snapd } ] } }
```

Examples:

```text
when: "(debian < 12) or (ubuntu < 23.04)"       // old debian OR old ubuntu, correct scales
when: "(fedora or arch) and cpu: x86_64"
when: "void or void_musl"                        // siblings (different libc parents): name both
when: "pop_os!"                                  // this OS or derivatives (Pop is a leaf)
```

A `when:` naming an OS block that doesn't exist (and isn't a declared facet) silently never
matches, so `configsys check` warns `unknown-os` (`routecheck.validate`).

## 6. OS lineage, version scales, identity

- **Identity** = which block. `pop_os!` and `ubuntu` are *different OSes*, always. The
  cascade makes Pop *inherit* Ubuntu's routes; it never merges them. You can always
  discretize with `X and not Y`.
- **Version scale** = which number system `< 23.04` is read in. Blocks marked `scale-root: true`
  own a numbering: `debian` (integers) and `ubuntu` (YY.MM) are scale-roots; `pop_os!` is **not** —
  it borrows Ubuntu's line (Pop 22.04 *is* Ubuntu 22.04). Mint, LMDE, Zorin, elementary, MX and
  PikaOS each own their numbers, so each is its own scale-root and a versioned `ubuntu`/`debian`
  atom never misreads them.
- A **bare** OS atom is pure subtree membership (any version). A **versioned** OS atom matches only
  when the atom's nearest scale-root equals the system's (`Context.scale_root_of` /
  `system_scale_root`). So `debian < 12` matches Debian proper, **not** Pop or Mint; `ubuntu < 23.04`
  matches Ubuntu and Pop; `debian` (bare) still matches all of them. Rolling blocks (arch,
  tumbleweed, void) have no version, so only their bare atoms are meaningful.

Identity and scale are orthogonal: sharing a version line does not make two OSes the
same OS.

**OS block fields** (the `os:` section; merged from repo + plugin + primary layers,
`layers.merge_dict_section` — a plugin may add a derivative distro): `using:` (parent),
`native:` (package-manager driver, inherited; absent on native-less blocks, §3), `scale-root:`,
`provides:` (environment capabilities, §4), `driver-preference:` (an OS-specific preference order,
§8a), and `detect:` (`{ id: …  marker: <path> }`, for os-release ambiguity — `pios`, `void_musl`;
read by osdetect, not the resolver). The C library is a lineage axis: glibc families hang off
`glibc_linux` (which `provides: glibc`); musl ones (`alpine`, `void_musl`, `chimera`) off bare
`linux`.

## 6a. Image-based and package-manager-less OS blocks

Most OS blocks assume a mutable system package manager behind `via: native`. Two kinds of
environment break that assumption, and both are modeled as **OS-layer data** — a block's `native:`
and `provides:` — rather than new resolver semantics. The selection machinery (§8/§8a) runs
unchanged; what changes is which bindings are candidates and which capabilities come free.

### Fedora Atomic / uBlue — `fedora_atomic`

Silverblue, Kinoite, Sericea, Onyx, the `*-atomic` spins, and the uBlue images built on them
(Bazzite, Bluefin, Aurora) boot a read-only ostree root. Their own published guidance is Flatpak
for apps, Homebrew for CLI tools, and `rpm-ostree` layering only as a last resort. configsys mirrors
that with ONE block:

```humon
{ os: { fedora_atomic: { using: glibc_linux  native: brew  provides: flatpak  scale-root: true } } }
```

- **`using: glibc_linux`, deliberately NOT under `fedora`/`redhat`.** A Fedora Atomic system is a
  different *environment*, not a Fedora variant: every dnf-specific binding (`when: "fedora"`,
  `when: "rhel"  requires: epel`, RPM Fusion, `repo-component:`) simply isn't valid there, which is
  correct (brew needs none of it). The cost is the identity rule (§6) applied: bare `fedora` does
  **not** match an atomic box, so a binding meant for both must name both (`when: "fedora or
  fedora_atomic"`).
- **`native: brew`.** Every plain `via: native` binding resolves to `brew install <name>` (the
  name-map key is `brew`; `drivers/brew.Brew`, user-scope, never sudo). Homebrew's formula set
  covers most CLI tools under their usual names, so most `via: native` CLI components route with no
  atomic-specific data. Where a component's only valid method is a broad `via: native` naming
  something that has no Linux formula (a GUI app whose brew name is a macOS cask, a Linux-kernel
  tool), the binding is gated `not fedora_atomic` and the component gets a flatpak method or
  declines. Conversely `{ via: native  when: "fedora_atomic" }` is the idiom for "brew has it here":
  it is narrower than any broad binding, so it wins by specificity (§8).
- **`provides: flatpak`.** Flatpak ships in the image, so an app's `flatpak` driver requirement is
  met by the environment instead of resolving to `brew install flatpak`.
- **`scale-root: true`.** The block owns its VERSION_ID (which tracks Fedora's), so
  `fedora_atomic >= 41` reads it, while `fedora`'s dnf version line never applies.

**Detection folds every variant into the block** (`osdetect.detect` → `_is_fedora_atomic`): the
system must be Fedora-family (`ID=fedora`, or `fedora` in `ID_LIKE`) AND either report an atomic
`VARIANT_ID` (`_FEDORA_ATOMIC_VARIANTS`: silverblue, kinoite, sericea, onyx, sway-/budgie-/cosmic-/
xfce-/lxqt-atomic) or have the ostree-booted marker `/run/ostree-booted`. The marker is the
load-bearing signal: some uBlue images report `VARIANT_ID=fedora`, so VARIANT_ID alone would miss
them. `OsInfo.id`/`version` keep the real os-release values for display and version atoms; only
the block changes. `--os`/`CONFIGSYS_OS` forcing bypasses the fold entirely. Finer per-image identity
(Bazzite vs Bluefin) is not modeled — nothing routes on it.

**`via: rpm-ostree` is explicit layering only.** `drivers/rpm_ostree.RpmOstree` (system scope,
sudo) exists, but no shipped component has an `rpm-ostree` binding, `rpm-ostree` is not in
`DEFAULT_DRIVER_PREFERENCE`, and it is never any block's `native:` (that would route *everything*
through layering, which is reboot-gated and grows every future deployment). You layer something by
writing the binding yourself in a higher layer (§10a); the name-map key is `rpm-ostree`. Because
`when: "fedora_atomic"` is narrower than a broad `via: native`, an rpm-ostree binding ADDED to a
component that already has one would become the default by specificity — mark it
`standing: never-auto` to keep it an offered, pinnable alternative:

```humon
{ components: {
    htop: { install: [ { via: rpm-ostree  when: "fedora_atomic"  standing: never-auto } ] }   // brew stays default; `pin set htop rpm-ostree` layers it
    v4l2loopback-akmod: { description: "v4l2loopback kernel module, layered into the image."
                          install: [ { via: rpm-ostree  when: "fedora_atomic"  name: akmod-v4l2loopback } ] }
} }
```

The driver is honest about what layering can't do: `install`/`uninstall` stage a NEW deployment
(`rpm-ostree install -y`) and say "staged — reboot (or set apply-live) to activate"; a binding's
`apply-live: true` adds `--apply-live` (userspace packages only — rpm-ostree refuses it for
kernel-level changes). `get_version` reads the *running* system (`rpm -q`), so a staged-not-booted
package reads as absent; `get_latest` is None (the image carries the version); `upgrade`,
`set_version` and `lock` are no-ops that say why rather than upgrading the whole OS.
`rebootcheck` runs no native reboot probe for brew — the rpm-ostree driver prints its own reboot
line — and the System Updates lane (`sysupdates`) covers brew but omits rpm-ostree.

**The advisory.** `osdetect.ATOMIC_BLOCKS` (today just `fedora_atomic`; an openSUSE MicroOS block
would join it) feeds `osdetect.is_atomic`, and `app.Context.diagnostics` emits an `atomic` warning
on inspect and the TUI `!` page: atomic routing is new and not hardware-validated; CLI tools go via
Homebrew, apps via Flatpak, `via: rpm-ostree` is reboot-gated; dev toolchains, the GPU/Vulkan stack,
docker and AppImages are not managed here (use distrobox, podman or rpm-ostree). Those exclusions
are routing facts, not just text — e.g. `python-build-deps` has no route there, so the `python3.X`
components (pyenv-only on this block) are unroutable.

Homebrew itself is assumed present (uBlue ships it configured); no component installs or
`provides:` brew, so on a plain Silverblue/Kinoite without Homebrew every brew-routed component
reads "not installed" and installs fail at the driver.

### No system package manager — `kde_linux`, `chimera`

A block whose lineage declares no `native:` (`OsCascade.native` returns None) has no system package
manager (introduced in §3). `OsCascade.context` sets `predicate.Context.has_native = False`, and
`resolve._matching` then drops every `via: native` binding — **not a candidate, exactly like a false `when:`** (same
treatment as a `disabled-drivers:` via). That is the invariant: a native-less block never produces
a "no native package manager" error from a component's bindings (`resolve._driver` raises that only
as a backstop); components fall through to whatever non-native methods are valid, and a component
offered only as a distro package becomes unroutable — a dangling routing status (`stranded`), not
an error about a missing driver. With no `native:` there is also no native index refresh
(`app.refresh_native_index` finds no command) and no native reboot check.

- **`kde_linux`** (os-release `ID=kde-linux`, aliased in `osdetect._ALIASES` because the `when:`
  DSL has no `-`): KDE's image-based distro, built from Arch packages with pacman removed from the
  image — so it hangs off `glibc_linux`, not `arch`. Its `provides: [ flatpak  curl  git  unzip
  xz ]` lists what the image ships, which is what makes the non-native methods work at all:
  flatpak apps (driver `requires: flatpak`), tarballs (`requires: curl`), `source` builds
  (`requires: git`) and `script` methods such as rustup (→ `cargo`) resolve with nothing to
  install first. The `pipx` and `python3-pip` tools have only native routes, so `via: pipx` and
  `via: pip` components currently decline here. It ships fuse3 only and libfuse2 has no non-native
  route, so the appImage driver's `requires: libfuse2` is unmet and **AppImages decline**. VERSION_ID is a build timestamp
  (YYYYMMDDHHMM); `scale-root: true` keeps any parent's versioned atom from misreading it.
  Diagnostics add an `immutable` warning (alpha, no system package manager, Flatpak + userland
  methods only).
- **`chimera`** (Chimera Linux: musl, LLVM, BSD userland, rolling): `{ using: linux }` — under bare
  `linux`, so glibc-requiring bindings (`requires: glibc`) decline as on Alpine. It has apk-tools v3
  but not Alpine's package names (`-devel` not `-dev`, `python` not `python3`), so every `apk:`
  name in the routes would be wrong there; it gets **no `native:` until Chimera-named
  `via: apk  when: "chimera"` bindings are verified** (a name sweep in the chimeralinux image).
  It declares no `provides:` beyond `linux`'s, so as shipped even the non-native methods are
  mostly unmet (tarballs need `curl`, flatpak apps need `flatpak`, and those have only native
  routes) and most components decline. Diagnostics add a `partial-os` warning.

Writing a native-less block: omit `native:`, list in `provides:` exactly the tools the image
ships (each entry is a promise that satisfies a driver requirement for free — overclaiming
produces installs that fail at run time), and add a `native:` only once that manager's package
names are verified for the distro (the `name-sweep`).

## 7. CPU arch

Arch matters only for **fetch-a-prebuilt-artifact** bindings (appImage, tarball,
`native-pkg-file`, raw binaries). `native` is arch-transparent (the package manager handles
it). Arch does two jobs:

1. **Selection / availability.** Either a `cpu:` clause in `when:` (which also makes the binding
   more specific), or a binding that *declares the cpus it ships for* — `resolve.arch_ok` drops it
   from the candidates on any other cpu, without touching specificity. An undetected cpu never
   declines.
2. **Token rendering** — upstreams spell cpus their own way (`amd64`/`arm64`/`x64`). This is
   handled by the two cpu-keyed forms below; there is no general "any field may be a cpu-keyed
   map" mechanism.

**A cpu-keyed `asset:` map** (top-level on the binding): each key is a cpu, the value that cpu's
artifact (`resolve.resolve_asset`; native-pkg-file also accepts format-then-cpu
`asset: { deb: { x86_64: … } }`, whose inner keys are unioned). Its keys gate availability at
resolve time — a cpu the map doesn't list makes the binding a non-candidate:

```humon
{ fastfetch: { suggests: fastfetch-dotfiles  install: [
    { via: native-pkg-file  when: "debian"
      version: { github: fastfetch-cli/fastfetch }
      asset: { x86_64: fastfetch-linux-amd64.deb  aarch64: fastfetch-linux-aarch64.deb } }
    { via: native  when: "rhel"  requires: epel }
    { via: native  when: "(not debian) and not amzn" } ] } }
```

**`cpu-names:` — one glob, each upstream's spelling.** When the artifact is a single `$ARCH` glob
or `url:` template (a github `version: { asset: … }`), give the binding a `cpu-names:` map
`{ <cpu>: <upstream token> }`. `$ARCH` then expands through it (`resolve.arch_token`, used by
`Driver.arch_token` for asset globs and `url:` templates), and — like a cpu-keyed asset map — its
keys are the cpus upstream ships, so the binding declines elsewhere (`resolve.cpu_names`,
`arch_ok`):

```humon
{
    lazygit: { install: [
        { via: tarball  cpu-names: { x86_64: x86_64  aarch64: arm64 }  installDir: "$CONFIGSYS_APP_DIR/lazygit"
          version: { github: jesseduffield/lazygit  strip-v: true  asset: "lazygit_*_Linux_$ARCH.tar.gz" } } ] }
    julia: { install: [
        { via: tarball  cpu-names: { x86_64: x86_64 }  installDir: "$CONFIGSYS_APP_DIR/julia"  requires: glibc
          version: { static: 1.12.6 }
          url: "https://julialang-s3.julialang.org/bin/linux/x64/1.12/julia-1.12.6-linux-x86_64.tar.gz" } ] }   // x86-only
}
```

`routecheck.check_component` rejects a malformed `cpu-names:` at load (it must be a non-empty map
of string tokens). Prefer it over a `when: "… and cpu: x86_64"` clause for an x86-only download: a
`when:` clause makes the binding MORE SPECIFIC, so it would start out-ranking broader bindings (an
ungated flatpak) on x86 — `cpu-names`/cpu-keyed asset maps gate validity without touching
specificity. Two same-`via:` bindings whose `cpu-names:` key sets are disjoint are never
ambiguous (routecheck skips the pair). `tools/compaudit.py` flags an x86-only literal with neither
gate (`arch-unguarded`). In a `source` build command `$ARCH` stays the raw machine cpu.

Call the axis **cpu**, not `arch` — `arch:` collides with Arch Linux.

## 8. Specificity and ambiguity

Among a component's candidate bindings, **specificity = set inclusion**: A beats B iff A's
`when:` match-set ⊆ B's (`predicate.subset`). Per dimension: OS = subtree containment; version =
interval containment on that OS's scale; cpu and categorical facets = set containment; a missing
dimension = the whole axis. (Arch gating by `cpu-names:`/asset maps is *not* part of the
match-set — §7.) Specificity ranks **bindings only**; providers of a capability are not ranked by
it (§9).

**The rule that makes it unambiguous** applies **per `via:`**: for any two bindings of the *same*
`via:` string whose match-sets *overlap*, one must be a subset of the other. An
**overlapping-but-incomparable same-`via:`** pair is a **load-time error**
(`routecheck.check_component`, raising `AmbiguityError` with a witness context) — never a silent
tiebreak — because only `when:` can say which variant of one method applies. Pairs of different
`via:`, and same-`via:` pairs with disjoint `cpu-names:` key sets, are skipped. `routes.load` runs
the check on every merged component: an offending component from a plugin layer is skipped with a
warning (never bricks the rest); from the repo or the user's own config it is an attributed
`ConfigError`. In practice the idiom "one broad default binding + narrower overrides" keeps every
pair comparable by construction.

Bindings of **different `via:`** may overlap freely — that is a component with several valid
install methods in one context (native + flatpak on Ubuntu), not an error. `when:` states
**validity only** (does this method work here); *which* valid method becomes the default is the
separate preference channel (§8a). A genuine tie there is a resolve-time error, and `configsys
check` warns `method-tie` (`routecheck._method_tie_warnings`, judged against the built-in
`DEFAULT_DRIVER_PREFERENCE` and ignoring binding-level `never-auto` bindings) — not a load-time
error, and never a reason to narrow a validity `when:`.

**Checker shape:** decidable and cheap (`predicate._cells`). Enumerate a finite grid: every OS
block as a possible leaf × each categorical namespace's mentioned values plus an "other" sentinel ×
each version axis (the OS version, plus any version facet) sampled just below / at / just above
every boundary the predicates mention. A predicate is then a boolean per cell, and ⊆ / overlap are
cell-wise compares, so `or`/`not`/versioned atoms all fall out for free.

## 8a. Choosing among valid methods

**The candidate set** (`resolve._matching`, exposed as `candidate_bindings`) is every binding that
passes all of:

- a **binding-pin** filter, if the component is pinned (§10) — only that `via:` survives;
- **not a disabled driver** — the machine setting `disabled-drivers:` makes those vias' bindings
  non-matching, exactly like a false `when:` (a `suggests:` then skips silently; a hard require or
  a pick errors — classified as `unmet` routing status, docs/stranded-installs.md);
- **not `via: native` on a native-less OS** (§3);
- **`arch_ok`** — the cpu is among those a `cpu-names:`/cpu-keyed `asset:` declares (§7);
- its **`when:`** holds.

One candidate is chosen as the default, deterministically (`resolve._select`, which also returns
the deciding rule — `configsys where <comp>` prints it):

0. **Only one candidate** → it wins (`only method here`).
1. **`never-auto` filter** — drop candidates whose via is `standing: never-auto` in the `drivers:`
   section, or whose binding carries `standing: never-auto`, *unless that would leave none* (then
   they compete normally — e.g. chromium on Ubuntu, snap-only). They stay in the candidate set
   (listed, pinnable). One left → it wins (`only ordinary method here`).
2. **Most specific** — the unique remaining binding whose `when:` ⊆ every other remaining
   binding's (`_most_specific_binding`; `most-specific when:`). If none is (incomparable `when:`s,
   or several share the narrowest one), specificity is set aside and the whole pool goes to:
3. **`standing:` rank** — an integer, higher wins (default 0). A NARROW per-binding author signal,
   so it **outranks** the broad `driver-preference` below: a targeted per-package decision beats a
   blanket order (the machine owner still overrides any case with a **pin**).
4. **`driver-preference`** — the nearest OS block's `driver-preference:` walking the lineage, else
   the `driver-preference:` setting, else the built-in `DEFAULT_DRIVER_PREFERENCE` (`native, flatpak,
   snap, native-pkg-file, appImage, tarball, source, script`). It matches `via:` names (`native`,
   not `apt`); vias absent from the order rank last and tie among themselves.

If steps 3–4 still tie, `_by_preference` raises an error naming the preference channel (set a
`driver-preference` order or a `standing:` rank) — never `when:`. A user **binding-pin** (§10)
overrides the default outright, and the detection tier adopts an installed method over the default
(precedence: pin > detected-installed > default; §10).

**`standing:` — the one preference knob.** It replaced the old `prefer:` / `candidate-only:` /
`opt-in:` trio (history: those names are gone — at component level they are unknown-key errors,
on a binding they are inert driver fields). `resolve._standing` reads it
from a binding, a `drivers:`-section block, or a component:
- **`never-auto`** — valid + listed + pinnable, but never the auto-default (on a binding or a
  driver), or never auto-pulled to satisfy a `requires:` (on a component-provider, §9). Was
  `candidate-only:` / `opt-in:`.
- an **integer** — a preference rank among bindings, higher wins. Was `prefer:`. Meaningful only on
  a binding: provider selection has no ranking, so an integer on a component is inert.

`never-auto` exists because a validity gate can hijack the default: a method gated narrowly for
*validity* would be the §8 most-specific candidate and beat a broad `native` binding, even when it
is only meant to be *offered*. `standing: never-auto` decouples "valid here" from "should win here"
without abusing `when:`. At the **driver** level (`drivers: { snap: { standing: never-auto … } }`
in routes.hu) it covers every binding of that via; at the **binding** level it scopes to one
method — e.g. `native-pkg-file` is the sensible debian default for a versioned GitHub `.deb`
(dbeaver/bruno), but for a *rolling* vendor `.deb` under a universal flatpak (discord) you want the
flatpak to stay default and the `.deb` merely available. On a **component-provider** it marks the
non-default of a versioned pair or a caveated shim like gcompat. The `drivers:` section is overlaid
repo → plugin → primary (`layers.merge_dict_section`), so a primary plugin can add
`flatpak: { standing: never-auto }`. A binding-pin still forces such a method. Because `when:` is
validity-only, `configsys where <comp>` can show every candidate method, the default, and *which
rule decided it*.

## 9. Resolution

Context is **fixed** (one machine: OS block, version, cpu, facets, disabled drivers). There is no
context fixpoint — only a dependency one. **No backtracking:** unsatisfiable or ambiguous is an
error, not a silent retreat. As built (`resolve._State`):

```text
ctx       = OsCascade.context(block, version, cpu, disabled)       // fixed
inventory = { cap: ∅  for cap in OsCascade.provides(block) }       // env-provided: no unit needed

// Phase 1 — the explicit wants (the machine's picks, Config.requested()), in order
for name in wants: add_component(name)

add_component(name):
    {} / no bindings            -> contributes nothing (removed component)
    binding = _select(...)      // §8a; pins first
    via: parts                  -> add_component(each part); no unit of its own
    driver  = native ? OsCascade.native(block) : via
    component-names drop        -> contributes nothing (§10a)
    unit key "driver\name"      -> reuse if already built (dedup), else build it
    for cap in provides ∪ {name}: if cap ∉ inventory: inventory[cap] = this unit   // first = resident
    enqueue HARD edges:  component requires + drivers[via].requires + binding requires
    enqueue SOFT edges:  component suggests + binding suggests

// Phase 2 — drain the FIFO queue to a fixpoint
while queue: (unit, cap, constraint, soft) = pop
    got = satisfy(cap, constraint)      // unmet SOFT edge -> skipped silently; unmet HARD -> error
    unit.deps |= got

satisfy(cap, constraint):               // _satisfy
    provider-pin on cap (value is a component, not a via) -> must be viable, wins over reuse
    constrained                         -> §11
    cap ∈ inventory                     -> reuse (keys, or ∅ for env)
    viable = providers of cap with a selectable binding here, excluding the requirer itself
    auto   = viable minus never-auto providers (unless the provider's name == cap)
    exactly one -> add_component it;  none -> error (names a pin if only never-auto ones exist);
    several -> "ambiguous providers … needs a provider-pin"
```

`drivers[via]` is keyed by the binding's `via:` string, so driver prerequisites are declared for
`flatpak`, `appImage`, `cargo`, `tarball`, … — a `drivers: { apt: … }` block would never apply to
`via: native` bindings.

**Strict vs resilient.** `resolve`/`resolve_roots` raise on the first failure. The app uses
`resolve_resilient`: a pick that can't route is recorded (`{root: first error}`) and everything
else still resolves; `_prune_failed` then drops each unit whose HARD requirement failed, every unit
that hard-depends on it, and anything only those reached — a parent that merely *suggests* a failed
unit keeps going without it. `resolve_roots` also returns the unit keys bound directly by the
named components (a parts aggregator contributes its parts'), which the app applies an op to;
`propagate_requested` records which picks pulled each dependency.

Key rules:

- **Explicit wants and their provides are established *before* requirements are resolved**, so an
  implicitly-pulled provider never overrides something you asked for ("I'm already installing
  rustup, so tree-sitter's `cargo` need is covered").
- **Reuse is graph-wide** and runs to a fixpoint, so a capability is installed once, whichever
  edge reaches it first. The one order sensitivity: when two *explicit wants* provide the same
  capability, the first-listed becomes its resident.
- **A requirement never pulls its own requirer** (`_bindable_viable` excludes it): source-building
  `gcc-16` that requires `cc` must be met by a *different* compiler; if none → a clear error. This
  is the bootstrap-cycle guard. *Caveat, as built:* the guard covers pulling a new provider, not
  the reuse path — a component's own `provides:` enter the inventory before its requires drain, so
  a component that both provides and requires `cc` reuses itself unless another `cc` provider got
  there first. That is why clang-NN requires the `c-toolchain` *component* (§4); treat the same
  shape as mandatory for any self-hosting compiler (a known gap in the guard).
- **Requirements are not validity.** A binding's (and its driver's) `requires:` play no part in
  choosing it: if the selected method's HARD requirement can't be met, the component errors — it
  does not fall back to another method (no backtracking; e.g. an appImage-only component on
  Alpine). That is deliberate for `requires: glibc`: a musl box gets a diagnostic naming the opt-in
  pin rather than a silent method switch.
- **Never-auto providers** are used only when wanted directly, required by their own name
  (`requires: gcc-10`), selected by a version constraint (§11), or provider-pinned.
- Cycles terminate naturally: a unit is built once per key, and a capability already in the
  inventory is reused.

## 10. Pins

Per-machine control lives in `~/.config/configsys/configsys.hu`'s `pins:` section (one flat
namespace for both kinds) and sits at the **top of user precedence** — above reuse, above auto:

```humon
{ pins: {
    chrome:     flatpak       // binding-pin: component -> method (via)
    cxx-stdlib: libc++        // provider-pin: capability -> provider component
    "C++20":    clang-18
} }
```

- A value that names a via — `native`, `parts`, or any registered driver
  (`resolve.pin_via_names`) — is a **binding-pin**; it forces that component's method (test apt vs
  flatpak; control which version-space you're in). Classifying via-first matters when a name is
  both a via and a component (pyenv, flatpak, clang, cabal); `resolve`, `app._validate_pin` and
  routecheck all use the same rule.
- Otherwise, a value naming a component is a **provider-pin**: it forces which provider satisfies
  that capability whenever the capability is required (it may name a `never-auto` provider, and
  overrides reuse of an existing resident). A provider-pin on a capability nothing requires is inert.

A pin is a **filter**, not a suggestion: it restricts candidates to the pinned one, then
selection runs on that set. It must be **realizable** here — a binding-pin to a via the component
has no binding for, or whose bindings are all invalid here (a false `when:`, a disabled driver),
is an error; a provider-pin to a provider that can't bind here (or can't meet the constraint) is an
error. The tool never silently ignores a pin and never silently falls back.

The app layers two more pin sources per resolve (`Resolver.resolve_resilient`): **detected** soft
pins *below* the user's (the detection tier, below) and, with the opt-in `auto-tighten` setting,
**floor** pins *above* them (§11). Effective precedence: auto-tighten > user pin > detected-installed
> reuse > auto default.

**Detection tier (`adopt-installed`, on by default).** Resolution is otherwise blind to the disk.
After a first resolve, `detection.detect_pins` probes installed state (one batched
`installed_index()` per package-manager driver, per-method `get_version` for the rest; no network)
and proposes soft pins, then the app resolves again with them:
- **method adoption** — a resolved component installed via a *different* candidate method → pin
  that via (only for components with more than one candidate via);
- **provider adoption** — a capability provided by a resolved unit whose resolved provider is *not*
  installed while another provider of it *is* → pin that provider (cuda-toolkit-11 vs -12).

User-pinned components/capabilities are left alone. It is skipped under `--pretend` and returns
nothing on a fresh machine, so resolution there is byte-identical (the golden never runs it — it
lives in the app pipeline, not the pure `Resolver`).

## 10a. Overrides across layers (`components:` merge, `component-names`)

**Component merge.** Every layer (repo < plugins < primary < user, includes below their includer)
may define `components:`; `routes._merge_component_chain` merges a component's definitions
**additively**, lowest first:
- `install:` bindings union keyed by **(via, `when:` text as written, stripped)**: a higher binding
  with the same identity overrides the lower; a new identity adds a method; a binding with
  `drop: true` and a matching identity retracts the inherited one;
- `provides`/`requires`/`suggests`/`parts`/`standing`/`description` override per field (a layer
  that omits one keeps the lower); `attrs` union;
- an empty spec `{}` is a tombstone that clears everything below (whole-component removal).

```humon
{ components: { steam: { install: [ { via: native  when: "pop_os!"  drop: true } ] } } }
```

Each surviving binding remembers its contributing layer (`Binding.source`), so a dotfiles binding's
content root and `configsys where` provenance follow the defining layer. To merely *choose* among
existing methods, use a `pins:` entry instead.

**`component-names` — per-driver name patches.** A component's `name:` map (§3) lives *in the
component definition*. A higher layer — typically a plugin OS — often needs to correct a package
name for an existing core component without owning it. `component-names` is the lightest patch for
the common "docker is `docker` under xbps" case — driver-keyed, not tied to a binding's `when:`:

```humon
{ component-names: {
    xbps: {                        // keyed by DRIVER
        docker-engine: docker      // override the package name under this driver
        r:             R
        nmap:          {}          // `{}` (or null / ""): this driver has no package for it -> drop
    }
} }
```

It overlays across the whole layer stack, later wins per `(driver, component)`
(`layers.merge_name_overrides`), and applies during resolution *after* the binding + driver are
chosen (`resolve._name_override`): a string replaces the resolved package name; `{}` drops the unit
as a silent no-op (not offered, never an error row — exactly like a `{}`-removed component). It is
**driver-keyed**, so it expresses cross-driver name facts (a plugin distro's package names) but
deliberately does *not* address same-driver splits like Ubuntu-vs-Debian `perf` (both `apt`) —
those remain `when:` splits. The configsys-void example plugin uses it to supply xbps names for core
components; Void itself has since graduated into core, where those facts live as ordinary `xbps:`
entries in each binding's `name:` map.

## 11. Tool-version vs OS-version, and versioned capabilities

Three different things, all "version":

- **Tool-version as identity.** `gcc-16` is a *different component* than `gcc-13`, with its own
  binding list. "gcc-16 comes from Copr on Fedora, AUR on Arch, source on Debian" is just gcc-16's
  `install:` with OS predicates. Capability *labels* (`C++20`) stay equality-matched; gcc's and
  clang's numbers are never compared with each other.
- **OS-version = context** (`fedora >= 42` in a `when:`, §5–§6).
- **Capability versions** — a provider may declare the version of a capability it provides, and a
  consumer may constrain it (constraints reuse the `when:` comparison vocabulary: `>=1.96`, `<12`,
  `=2.0`, `,`-AND ranges; `versionsweep.meets`). `cap_names` feeds the resolver the names
  unchanged; `cap_constraints` carries the versions alongside.

```humon
{   // abridged from routes.hu (the real ones also carry native bindings)
    python3.13: { provides: { python3: "3.13" }  install: [ { via: pyenv  version: "3.13" } ] }
    python3.12: { provides: { python3: "3.12" }  standing: never-auto  install: [ { via: pyenv  version: "3.12" } ] }
    some-tool:  { requires: [ { python3: ">=3.11" } ]  install: [ { via: pipx } ] }
}
```

Resolution with a constraint (`_State._satisfy_constrained`):
1. reuse the default resident if its provided version meets the constraint (the environment's
   unversioned `python3` does not);
2. else reuse a resident already pulled for the same `(cap, constraint)`, so two consumers wanting
   different versions coexist side by side;
3. else pull a viable provider whose **component-level** provided version meets it — the
   constraint itself *enables* `never-auto` providers (ordinary ones preferred on a tie); among
   several **version-scoped** providers the highest satisfying version wins; a provider-pin must
   also meet the constraint.
4. If no provider meets it: for a **version-scoped** capability (some provider declares a
   component-level version — python3.X, jdk-NN, cuda-toolkit-NN) it is an error. For a capability
   whose version lives only on a method (go, ghc — a binding-level `provides: { go: ">=1.21" }`),
   the constraint is a **soft floor**: the default provider resolves, and the floor becomes an
   advisory (`flooradvise`) — or, with the opt-in `auto-tighten` setting, a floor pin selecting a
   method that meets it (§10).

The `version-floors:` section (`{ <component>: { <cap>: "<constraint>" } }`, overlaid across layers
by `layers.merge_version_floors`) patches floors onto existing components without redefining them;
it only tightens a requirement the component (or one of its bindings) already has, never creates
one. `configsys check` warns `unsatisfiable-constraint` when every provider declares a concrete
version and none meets a constraint, and flags provider-pins that conflict with a consumer's
constraint. Details: docs/versioned-requires.md.

## 12. What the old constructs became (history)

This maps the pre-migration `\family`/OS-cascade constructs (the "old" column — that resolver + data
are now deleted) onto the capability model.

| old (deleted v1) | capability model |
| --- | --- |
| `\apt btop {name: btop}` (×3 families) | `btop: { install: [ { via: native } ] }` |
| `*: apt\*` wildcard | `debian: { native: apt }` |
| family `!depends` (e.g. `\appImage !depends libfuse2`) | per-driver config: `drivers: { appImage: { requires: [ libfuse2, glibc ] } }` |
| OS-route `chrome: flatpak\chrome` | a binding in the `chrome` component |
| version variant `"ubuntu@<23.04"` | a `when:` on a binding |
| `\app` method selection (neovim, steam) | the general case — every component works this way |
| EL `depends: [epel-release]` per package | a binding-level `requires: epel` on the `when: "rhel"` binding (`epel-release provides: epel`) |
| `steam: apt` in `pop_os!` | binding-pin, or a `when: "pop_os!"` binding |

## 13. Open questions

- **Sugar** for the trivial single-binding component (a bare `btop: { via: native }` or string
  form) — never built; a component must spell `install: [ { via: native } ]` (~44 do exactly that),
  and `via:` at component level is rejected as an unknown key. Still a live decision: add the sugar
  or leave it explicit.

Resolved since the first draft: **driver-specific binding fields** DO hang off the binding as
driver-scoped fields, ignored by non-matching drivers (`repo-component:`, `debconf:`,
`installed-name:` shipped); **capability-name hygiene** is the `dangling-requires` lint in
routecheck (the "nothing provides X → warn" path), not a registry.

The larger consolidation — folding the preference cluster into one `standing`, version-scoped
providers (`provides: { cap: N }` / `requires: { cap: ">=N" }`), and the detection tier
(`adopt-installed`: pin > detected-installed > default) — has **shipped**; §8a, §10 and §11
describe it as built. `docs/todo/routing-overhaul-plan.md` is the historical plan.

## 14. Migration (parallel, iterated) — DONE (history)

This is how the migration was carried out (now complete; the old resolver + data are deleted and
`test/routing_golden.json` freezes the result). The plan was: do **not** rewrite `routes.hu`
big-bang — build the new resolver beside the old and prove equivalence before flipping:

1. **New resolver, no new data.** Implement the v2 model (parser for `when:`, the
   selection engine, the worklist) as a separate module. It reads a *new-format* routes
   file (start it empty).
2. **Equivalence harness.** For a given machine context and profile, resolve with the
   **old** resolver (current `routes.hu`) and the **new** one (v2 file), and diff the
   resolved unit sets + dependency edges. Wire this into the test suite across the OS
   contexts we already exercise (Debian/Ubuntu/Pop, Fedora, EL, Arch × a couple of cpu
   values).
3. **Port components in batches**, easiest first: trivial natives (`btop`, `ripgrep`,
   …), then name-overrides (`python-pip`, `libfuse2`), then flatpak/appImage/tarball,
   then the capability cases (`cargo`/crates, EPEL), then the toolchains and `steam`.
   After each batch, the equivalence diff must stay green for the ported names.
4. **Flip per context, then globally.** Once the new file covers a profile on a context
   and the diff is empty, switch that path to the v2 resolver. When all contexts are
   covered, retire the old family/OS-block data (mechanism *code* stays).

The existing podman integration suites remain the ground truth throughout — they pin
real install behavior, so "the diff is empty and podman still passes" is the bar for
each flip.

## 15. Deferred

**Windows / macOS.** The architecture would absorb them cleanly (a new OS root plus a
`winget`/`scoop` driver, or the existing `brew` driver — today the `native:` of `fedora_atomic` — as
macOS's `native:`). Deferred for two honest reasons: no test path (podman is Linux-only, so they
can't get the throwaway-box rigor everything else has), and little overlap with the Linux model.
Parked, not abandoned.
