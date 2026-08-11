# Routing model v2 — capabilities, components, bindings

**Status:** SHIPPED — this is the routing model as built; it is the sole resolver. It replaced the
old `\family`-block resolver **in place** (built in parallel, proven byte-equivalent, then flipped;
the old resolver and its data are deleted, and `test/routing_golden.json` freezes the proven
resolution as a regression gate). §1 and §14 below are kept as *motivating history* — the tangle
this design removed and the migration that removed it. See CLAUDE.md for the current summary.

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

> **A component *is* a named capability. A binding *is* a provider. Selecting how to
> install a component and selecting who satisfies a requirement are the same operation.**

- **Component** — the abstract thing you want (`btop`, `neovim`, `cargo`, `C++20`):
  an identity plus a set of context-selected **bindings**.
- **Binding** — one way to acquire the component in some context: a driver + a
  `when:` predicate + driver-specific details. Also a *provider* of the component's
  capability.
- **Driver** — knows how to drive install/query/remove for a class of
  bindings: `native` (the OS package manager), `flatpak`, `appImage`, `cargo`, `tarball`,
  `aur`, `gcc-toolset`, … (see configsys.hu(5) for the full registered set).

Because a component's own bindings and any *external* provider of the same capability
go into one candidate pool, there is a **single selection engine** used everywhere.

## 3. Component and binding shape

Legal humon (every dict entry is `key: value`; `when:` is a string expression):

```
<name>: {
    provides:  <cap | [caps]>      // optional; a component always implicitly provides its own name
    requires:  <cap | [caps]>      // HARD method-independent needs (unmet here = error)
    suggests:  <cap | [caps]>      // SOFT needs: pulled in if resolvable in the loaded layers,
                                   //   skipped silently if not (a package `suggests:` its
                                   //   `<name>-dotfiles`, which may live only in a user's plugin)
    parts:     <cap | [caps]>      // composition (installed together; parent "installed" iff all parts are)
    opt-in:    <bool>              // if true, this component's `provides:` are NEVER auto-pulled to
                                   //   satisfy someone else's `requires:` — only used when the
                                   //   component is explicitly wanted (a profile) or provider-pinned.
                                   //   For best-effort/caveated providers (e.g. gcompat, a glibc shim)

    install: [                     // ordered list of bindings (providers)
                                   //   a dotfile component's binding is `{ via: dotfiles ... }`
        { via: <driver>  when: "<predicate>"  ...driver details... }
        ...
    ]
}
```

- A **binding** names its driver with `via:`, guards itself with an optional `when:`
  (absent = matches any context), and carries driver details. Any detail value may be
  a **cpu- or os-keyed map** (see [arch](#7-cpu-arch)).
- The `install:` list is **disjunctive selection** — "here are the ways; pick the best
  match" — *not* an implicit and/or. All logic lives in `when:`.
- Trivial sugar (open for bikeshed): `btop: { via: native }` as shorthand for a single
  default binding.

### `native` — the sugar that kills the boilerplate

`via: native` resolves to the OS's package manager, declared **once per OS block**:

```
linux:   { }
debian:  { using: linux    native: apt }
ubuntu:  { using: debian }
pop_os!: { using: ubuntu }
fedora:  { using: linux    native: dnf }
rhel:    { using: fedora }                 // native inherits dnf
arch:    { using: linux    native: pacman }
```

The package name defaults to the component's own name; override only where it differs:

```
btop:       { via: native }
python-pip: { via: native  name: { pacman: python-pip, default: python3-pip } }
libfuse2:   { via: native  name: { dnf: fuse-libs, pacman: fuse2, default: libfuse2 } }
```

This deletes all `\apt btop` / `\dnf btop` / `\pacman btop` triplicate entries and the
`*: apt\*` wildcard. The OS blocks shrink to *lineage + which manager is native*.

## 4. Capabilities

A capability is **a label**. `provides:` declares it, `requires:` matches it (by
equality — no version math). The resolver never inspects a capability directly; it is
**satisfied when a provider is installed**, and the provider's presence *is*
discoverable (via the provider's binding).

Two flavors, same kind of atom:

- **Concrete** — has a component that installs it directly: `cargo`, `chrome`, `epel`.
- **Virtual** — only ever appears in `provides:`, nothing installs it directly:
  `cc`, `C++20`, `C11`. Pure labels, authored data, unverified by configsys. They exist
  to *abstract over incompatible numbering* — `C++20` is meaningful across gcc and clang;
  `compiler >= 18` is not.

```
// SHIPPED: routes.hu gives every versioned gcc/clang these standard capabilities, all opt-in
// (so a plain `requires: cxx` still resolves to the unversioned cpp-toolchain, no ambiguity).
gcc-15:   { provides: [ cc, cxx, C11, C17, C23, "C++17", "C++20", "C++23", "C++26" ]  opt-in: true  install: [...] }
clang-18: { provides: [ cc, cxx, C11, C17, C23, "C++17", "C++20", "C++23" ]           opt-in: true  install: [...] }
some-app: { requires: "C++20" }   // pick a versioned compiler by wanting it, or a provider-pin
```

The unversioned `cc`/`cxx` (`c-toolchain`/`cpp-toolchain`) are the always-on *system default*
compiler; the versioned ones layer specific-standard labels on top, opt-in so they never shadow
the default. `requires: "C++20"` is thus satisfied by any co-wanted / pinned versioned compiler;
teaching the *default* toolchain which standard it supports per OS-version is the remaining piece.

The **C++ standard library is its own capability**, `cxx-stdlib`, separate from the compiler —
because g++ bundles its library (libstdc++) but clang doesn't (on Linux it uses gcc's libstdc++
by default, or LLVM's libc++ via `-stdlib=libc++`). So `clang-NN requires: [ c-toolchain,
cxx-stdlib ]` (the gcc runtime it needs + *a* stdlib), never the g++ compiler; `cxx-stdlib`
defaults to the `libstdc++` component (non-opt-in) and `libc++` is an opt-in alternate provider you
select with a provider-pin (`pins: { cxx-stdlib: libc++ }`). Note clang requires the *component*
`c-toolchain`, not the `cc` capability: clang itself `provides: cc` (opt-in), and requiring the
capability would let it self-satisfy and never pull gcc — requiring the component sidesteps that.

**Environment capabilities.** An OS block can `provides:` capabilities that are baseline
in that environment, so requiring them is free there and pulls a provider elsewhere:

```
fedora: { using: linux  native: dnf  provides: epel }   // EPEL is baseline on Fedora
epel-release: { provides: epel  install: [ { via: native  when: "rhel" } ] }
// any component: `requires: epel`  -> no-op on Fedora, pulls epel-release on EL
```

This turns per-package EPEL/`universe` special-casing into a few named capabilities.

**Design boundary:** the `provides:` lists are *your data*, not knowledge configsys
claims. configsys stays a mechanical string-matcher; it never reasons about C++
standards. The cost is that a wrong label installs the wrong thing silently — treat the
lists as carefully-authored, one-line-to-fix data.

## 5. The `when:` predicate language

`when:` is a single boolean expression string; configsys owns a small recursive-descent
parser. The context is ⟨os-lineage, version, cpu⟩.

**Atoms:**
- bare OS — `debian`, `ubuntu`, `pop_os!`, `fedora`, `arch` — **subtree membership**
  (`debian` matches Debian *and* everything deriving from it, honoring `using`).
- versioned OS — `ubuntu < 23.04`, `debian >= 12`, `fedora = 41` — subtree membership
  **and** the system is on that OS's version scale (see [scales](#6-os-lineage-version-scales-identity))
  **and** the comparison holds.
- cpu — `cpu: x86_64`, `cpu: [ x86_64, aarch64 ]`.

**Operators:** `and`, `or`, `not` (or `!`), parentheses. Precedence `not > and > or`.

**Negation.** `not` (or `!`) complements any atom — an OS subtree, a `cpu:`/facet set, or a
versioned bound. (It was historically restricted to OS atoms to keep the ambiguity checker's
complement to "subtree minus subtree"; the grid-based checker handles the general case now, so that
restriction is lifted — evaluation and the checker both accept `not`/`or` over any atom.) It is
exactly enough to carve subtree members apart:

```
{ via: native  name: snapd  when: "ubuntu and not pop_os!" }   // snaps on bare Ubuntu, not Pop
```

Examples:

```
when: "(debian < 12) or (ubuntu < 23.04)"       // old debian OR old ubuntu, correct scales
when: "(fedora or arch) and cpu: x86_64"
when: "pop_os!"                                  // this OS or derivatives (Pop is a leaf)
```

## 6. OS lineage, version scales, identity

- **Identity** = which block. `pop_os!` and `ubuntu` are *different OSes*, always. The
  cascade makes Pop *inherit* Ubuntu's routes; it never merges them. You can always
  discretize with `X and not Y`.
- **Version scale** = which number system `< 23.04` is read in. Mark cascade nodes as
  **scale-roots**: `debian` (integers) and `ubuntu` (YY.MM) are scale-roots; `pop_os!`
  is **not** — it borrows Ubuntu's line (Pop 22.04 *is* Ubuntu 22.04).
- A **bare** OS atom is pure subtree membership (any version). A **versioned** OS atom
  matches only systems whose scale-root is that OS. So `debian < 12` matches Debian
  proper, **not** Pop; `ubuntu < 23.04` matches Ubuntu and Pop; `debian` (bare) still
  matches Pop.

Identity and scale are orthogonal: sharing a version line does not make two OSes the
same OS.

## 7. CPU arch

Arch matters only for **fetch-a-prebuilt-artifact** bindings (appImage, tarball,
`deb`/`rpm`, raw binaries). `native` is arch-transparent (the package manager handles
it). Arch does two jobs:

1. **Selection / availability** — via a `cpu:` clause in `when:`. If a binding is
   x86_64-only and you're on aarch64, it's filtered out and the component falls to
   another binding.
2. **Token rendering** — via **cpu-keyed value maps** on any detail. This kills the
   `amd64` vs `x86_64` naming swamp — you write the actual token each ecosystem uses,
   and a missing key means "unsupported on this arch" (availability for free):

```
fastfetch: {
    requires: epel                                       // no-op off EL
    install: [
        { via: native  when: "fedora or arch" }
        { via: tarball  when: "debian"
          version: { github: fastfetch-cli/fastfetch }
          asset:  { x86_64: fastfetch-linux-amd64.tar.gz, aarch64: fastfetch-linux-aarch64.tar.gz } }
    ]
}
```

Call the axis **cpu**, not `arch` — `arch:` collides with Arch Linux.

## 8. Specificity and ambiguity

Selection among matching candidates (bindings of a component, or providers of a
capability) is by **specificity = set inclusion**: A beats B iff A's match-set ⊆ B's
(strictly). Per dimension: OS = subtree containment; version = interval containment;
cpu = set containment; a missing dimension = the whole axis.

**The rule that makes it unambiguous** applies **per driver**: for any two bindings of the
*same* `via:` whose match-sets *overlap*, one must be a subset of the other. If every such
pair is comparable, resolution within a driver is provably unambiguous for every machine. An
**overlapping-but-incomparable same-driver** pair is a **static (load-time) error** — never a
silent tiebreak (`routecheck.py` skips pairs of different `via:`). In practice the idiom "one
broad default binding + narrower overrides" keeps every pair comparable by construction.

Bindings of **different drivers** may overlap freely — that is a component with several valid
install methods in one context (native + flatpak on Ubuntu), not an error. `when:` states
**validity only** (does this method work here); *which* valid method becomes the default is a
separate preference channel (§8a). A genuine tie there is a resolve-time error and a `check`
warning that names the preference channel — not a load-time error, and never a reason to
narrow a validity `when:`.

## 8a. Choosing among valid methods

The bindings valid in a context (their `when:` matches) form its **candidate set**
(`candidate_bindings`, resolve.py). One is chosen as the default, deterministically:

0. **`never-auto` filter** — bindings with `standing: never-auto` are dropped from the default pool
   *unless every valid method here is never-auto*. They stay in the candidate set (still listed /
   pinnable), they just can't win the auto-default.
1. **most specific** among *comparable* candidates (the §8 subset order);
2. per-binding **`standing:`** rank — an integer, a NARROW per-binding author signal, so it
   **outranks** the broad `driver-preference` below: a targeted per-package decision beats a blanket
   machine-wide order (the machine owner still overrides any specific case with a **pin**);
3. **`driver-preference`** — a global driver order (a machine setting), overridable per OS
   block (so e.g. flatpak > native lives in the `os:` data on `fedora_atomic`, not smuggled
   into a `when:`).

If the preorder still ties, it is an error whose message names the preference channel (set a
`driver-preference` order or a `standing:` rank) — never `when:`. A user **binding-pin** (§10)
overrides the default outright, and the detection tier adopts an installed method over the default
(precedence: pin > detected-installed > standing default).

**`standing:` — the one preference knob.** It unified the old `prefer:` / `candidate-only:` /
`opt-in:` trio (which remain deprecated aliases). A binding, an `os:` `drivers:` block, or a
component may carry `standing:`:
- **`never-auto`** — valid + listed + pinnable, but never the auto-default (on a binding/driver),
  or never auto-pulled to satisfy a `requires:` (on a component-provider). Was `candidate-only:` /
  `opt-in:`.
- an **integer** — a preference rank, higher wins. Was `prefer:`.

`never-auto` exists because a method like snap must be gated `when: ubuntu` for *validity* (snapd
only ships there) — which would make it the §8 most-specific candidate and hijack the Ubuntu default
over a broad `native` binding, even though snap is only meant to be *offered*. `standing: never-auto`
decouples "valid here" from "should win here" without abusing `when:`. At the **driver** level
(`snap: { standing: never-auto }`) it covers every binding of that via; at the **binding** level it
scopes to one method — e.g. `native-pkg-file` is the sensible debian default for a versioned GitHub
`.deb` (dbeaver/bruno), but for a *rolling* vendor `.deb` under a universal flatpak (discord) you
want the flatpak to stay default and the `.deb` merely available. On a **component-provider** it is
the old `opt-in` (the non-default of a versioned pair, or a caveated shim like gcompat). It is
overlaid like the rest of `drivers:` (repo → plugin → primary), and a binding-pin still forces such a
method. If a `never-auto` method is the *only* valid one (e.g. chromium on Ubuntu, snap-only), it
wins normally. Because `when:` is validity-only, `configsys where <comp>` can show every candidate
method, the default, and *which rule decided it*.

**Checker shape:** decidable and cheap. Enumerate the finite (OS-block × cpu-value)
grid; in each cell the predicate collapses to a set of version intervals *in that
cell's scale*; then it's interval algebra — containment for ⊆, non-empty intersection
for "overlap." `not`/`or` are handled generally (per-cell complement/union).

## 9. Resolution

Context is **fixed** (one machine, one ⟨os, version, cpu⟩). There is no context
fixpoint — only a dependency one. **No backtracking:** unsatisfiable or ambiguous is an
error, not a silent retreat. The algorithm is "what a careful human does":

```
context   = detect()                          // fixed
inventory = { capabilities the OS environment provides }
worklist  = profile components                // explicit wants first

// Phase 1: lay out the shopping list, note what each provides.
for each explicit want:
    select its binding (most-specific when:, then preference — §8a; pins first — see §10)
    on success, add its provides to the inventory

// Phase 2: fill gaps, reusing what's already there. Iterate to a fixpoint.
loop until nothing new:
    take an unresolved requirement R
    if R in inventory (OS-provided or already chosen): continue      // reuse
    provider = most-specific provider of R in context                // ambiguous -> ERROR
    if none: ERROR(R unsatisfiable in this context)
    add provider; select its binding; enqueue its requires; add its provides

detect cycles; report all errors together
```

Key rules:

- **Explicit wants and their provides are established *before* requirements are
  resolved**, so an implicitly-pulled provider never overrides something you asked for
  ("I'm already installing rustup, so tree-sitter's `cargo` need is covered").
- **Reuse is graph-wide** and runs to a fixpoint, so resolution is order-independent and
  never installs the same capability twice.
- A **provider never satisfies its own requirement.** Source-building `gcc-16` requires
  `cc`; it must be met by a *different* compiler already in the inventory. If none →
  clear error. This is the bootstrap-cycle guard.

**Two selection moments, one engine.** *Provider selection* ("who supplies `cargo`?") is
inventory-aware (prefer existing). *Binding selection* ("given we install neovim, how?")
is context first — most-specific valid `when:`, then the preference channel (§8a) when
candidates are equally specific or of different drivers. Same specificity math; don't
conflate them.

## 10. Pins

Per-machine control lives in `~/.config/configsys/configsys.hu` and sits at the **top of
precedence** — above reuse, above auto:

```
pins: {
    chrome: flatpak       // binding-pin: component -> method
    C++20:  clang-18      // provider-pin: capability -> provider
}
```

- **binding-pin** forces a component's method (test apt vs flatpak; control which
  version-space you're in).
- **provider-pin** forces which provider satisfies an ambiguous capability.

A pin is a **filter**, not a suggestion: it restricts candidates to the pinned one, then
selection runs on that set of one. It must be **realizable** in context (the pinned
binding's `when:` must match) or it's an error — the tool never silently ignores a pin
and never silently falls back.

Precedence overall: **pin > reuse > auto**.

## 10a. Per-driver name patches (`component-names`)

A component's `name:` map (§3) is driver-keyed and lives *in the component definition*. But a
**higher layer** — typically a plugin OS — often needs to correct a package name for an
existing core component without owning that component. `components:` now merges additively (a
higher layer can override a single binding by its `(via, when)` identity, add a binding,
retract one with a `drop:` binding `{ via: X  when: Y  drop }`, or clear the whole component
with `{}`), but `component-names` remains the lightest patch for the common "docker is
`docker` under xbps" case — driver-keyed and not tied to a specific binding's `when:`:

```
component-names: {
    xbps: {                        // keyed by DRIVER
        docker-engine: docker      // override the package name under this driver
        r:             R
        nmap:          {}          // `{}` (or null): this driver has no package for it -> drop
    }
}
```

It overlays across the layer stack (repo < plugin < discovered < user), later wins per
`(driver, component)`, and applies during resolution *after* the binding + driver are chosen:
a string replaces the resolved package name; `{}` drops the unit as a silent no-op (not offered,
never an error row — exactly like a `{}`-removed component). It is **driver-keyed**, so it
expresses cross-driver name facts (a plugin distro's package names) but deliberately does *not*
address same-driver splits like Ubuntu-vs-Debian `perf` (both `apt`) — those remain `when:`
splits. This is the substrate the Void plugin uses to supply its xbps names for the ~10 core
components whose Void name differs, kept honest by the plugin's name-existence sweep.

## 11. Tool-version vs OS-version

Two different words, both "version":

- **Tool-version = component identity.** `gcc-16` is a *different component* than
  `gcc-13`, with its own binding list. "gcc-16 comes from Copr on Fedora, AUR on Arch,
  source on Debian" is just gcc-16's `install:` with OS predicates.
- **OS-version = context** (`fedora >= 42` in a `when:`).

No comparative math on tool-versions or on capability labels — gcc's and clang's
numbers are unrelated, and labels are equality-matched.

## 12. What the old constructs became (historical)

This maps the pre-migration `\family`/OS-cascade constructs (the "old" column — that resolver + data
are now deleted) onto the capability model.

| old (deleted v1) | capability model |
| --- | --- |
| `\apt btop {name: btop}` (×3 families) | `btop: { via: native }` |
| `*: apt\*` wildcard | `debian: { native: apt }` |
| family `!depends` (e.g. `\appImage !depends libfuse2`) | per-driver config: `drivers { appImage { requires: libfuse2 } }` |
| OS-route `chrome: flatpak\chrome` | a binding in the `chrome` component |
| version variant `"ubuntu@<23.04"` | a `when:` on a binding/provider |
| `\app` method selection (neovim, steam) | the general case — every component works this way |
| EL `depends: [epel-release]` per package | `requires: epel` + `fedora provides: epel` |
| `steam: apt` in `pop_os!` | binding-pin, or a `when: "pop_os!"` binding |

## 13. Open questions

- **Sugar** for the trivial single-binding component (`btop: { via: native }` vs a bare-string
  form) — never built; ~37 components spell out `install: [ { via: native } ]`. Still a live
  decision: add the sugar or leave it explicit.

Resolved since the first draft: **driver-specific binding fields** DO hang off the binding as
driver-scoped fields, ignored by non-matching drivers (`repo-component:`, `debconf:` shipped);
**capability-name hygiene** is the `dangling-requires` lint in routecheck (the "nothing provides
X → warn" path), not a registry.

The larger consolidation now under way — folding the preference cluster into one `standing`,
version-scoped providers, detection-first resolution — lives in `docs/routing-overhaul-plan.md`.

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
`winget`/`scoop` or Homebrew `native:` driver). Deferred for two honest reasons: no
test path (podman is Linux-only, so they can't get the throwaway-box rigor everything
else has), and little overlap with the Linux model. Parked, not abandoned.
