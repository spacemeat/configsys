# Versioned requirements & per-method version visibility (design)

> **Status: REFERENCE** — the version-floor model (min-version `requires:`, `version-floors:`, floor advisory, `auto-tighten`, `configsys versions`); every roadmap stage shipped by 2026-08-02 (09579c7); written before the `standing:` rename (its preference wording now reads `standing:`) and the version-scoped-provider resolver (66b764b), which "Python interpreters as versioned providers" below documents as built; maintained.

Captures the model, the data/caching story, and a staged plan
for two linked capabilities that share one substrate:

1. **User-facing version visibility** — see, per install method (native/tarball/source/flatpak/…),
   what version a component would install, with the native-vs-tip lag called out; filter methods by
   a version floor and pin one.
2. **Version-constrained requirements** — a `requires:` may carry a minimum version
   (`requires: { cargo: ">=1.96" }`); the resolver can tell which methods satisfy it and cascade
   the constraint through the dependency chain — surfacing the choice, not silently swapping.

The direct motivator is the **toolchain-floor** finding from `source-plugin-plan.md`: a correct
source recipe (ripgrep needs Rust ≥1.96, lazygit Go ≥1.25) still fails when the *default* method
(native) ships an older toolchain. Versioned requires is the general, principled form of that fix;
version visibility is the same data made useful to the user directly.

## The core tension: static vs dynamic versions

configsys has two kinds of "version," and they live in different worlds:

- **OS version** (`when: "ubuntu < 23.04"`) is a **static fact of the machine context** — known
  before resolution runs. That's why the boolean `when:` checks are clean.
- A component's **provided version** is **dynamic and install-time**: `versions.py` discovers it
  over the network, lazily, only when installing; `resolve.py` never inspects a concrete version.
  Capabilities are **versionless names** today (`provides: cargo`, provider index = `cap → {units}`).

So `requires: { cargo: ">=1.96" }` asks the resolver a question it structurally can't answer live
without breaking three invariants at once — resolution is **offline**, **deterministic** (the
golden gate depends on it), and **backtrack-free**. Discovering candidate versions at resolve time
is therefore rejected. The design instead makes the needed version facts **static annotations** (or
cached reality), mirroring how `when:` stays static.

## Substrate that already exists

**Every driver already implements `get_latest`** — "what version would *this* method install."
Native (apt/dnf/pacman/zypper/apk/brew), tarball, source, cargo, flatpak, all of them. So
"versions available per method" is already answerable per binding. What's missing is presentation,
a caching policy for those results, and the authored-floor layer. `versions.py` already caches
network discovery in `state_dir/versions.hu` with a TTL.

## The data splits into three layers (this IS the maintenance story)

| layer | example | nature | cache | honesty mechanism |
| --- | --- | --- | --- | --- |
| **1. globally-discoverable** | `version: { github: … }`, crates/pypi latest | machine-independent reality | `versions.hu`, TTL (exists) | none authored — refresh |
| **2. machine-local native** | apt/dnf candidate version | per-machine reality | **new**: per-machine cache + TTL | none authored — refresh |
| **3. authored-static** | `static:` pins; **new** provided-version floors; requirement floors | authored intent | none (shipped route data) | **version-sweep** |

The split is the whole point: **layers 1–2 are cached reality (refresh, don't sweep); layer 3 is
authored intent (sweep, don't cache).** Only layer 3 drifts *as data* — and it drifts because
upstreams change (a new ripgrep bumps its MSRV), exactly the kind of thing a sweep catches.

### The version-sweep (sibling to the name-sweep)

For each component × method, discover the real version (layers 1–2) and check:
- **(a) honesty** — each binding actually delivers the floor it *claims* (`provides` floor ≤ real);
- **(b) not stranded** — some method still meets each *requirement* floor here;
- **(c) lag** — optionally report native-vs-tip gaps.

Runs in containers for the native-across-distros part (like `run-name-sweep-in-podman.sh`), reuses
the discovery cache for the rest. Turns "silently broke six months later" into "CI flags a stale
floor."

## Syntax

**Requirement with a floor** — a `requires:` entry may be a bare capability (as today) or a
`{ cap: constraint }` map; reuse the `when:` comparison vocabulary (`>=`, `>`, `=`):

```
ripgrep-source: { requires: [ { cargo: ">=1.96" } ]  … }        # floor
htop-source:    { requires: [ cc, make, ncurses ]  … }          # bare (unchanged)
```

**Provided version** — derive it for free where a binding pins `version: { static: X }`; otherwise
a binding (or component) declares a *guaranteed floor* via an extended `provides:` map:

```
rust: {
  provides: cargo                                         # bare name (unchanged) — versionless
  install: [
    { via: native }                                       # guarantees nothing (distro-dependent)
    { via: tarball  version: { static: 1.97.1 } … }       # provided = 1.97.1, derived for free
    { via: script   provides: { cargo: ">=1.97" }  … }    # rustup: an authored guaranteed floor
  ]
}
```

The useful asymmetry: **native usually declares nothing**, so a floored requirement filters it out
automatically and points at a method that *can* guarantee the floor. You never need native's exact
version — only which methods can promise the floor.

## Resolution semantics

**Selection = filter, then the existing preference machinery.** When a requirement carries a floor,
filter the provider's candidate bindings to those whose (declared or derived) version satisfies it,
then apply the normal selection among survivors (specificity, `standing:`, `driver-preference`).
If none satisfy → a clear error naming the channel, never a silent wrong pick.

**Cascade is nearly free.** The worklist already closes `requires` transitively. Make each
provider-selection step version-aware and the constraint propagates: A needs `cargo≥1.96` → the
satisfying rust binding is chosen → *its* own `requires` close normally (including any of its own
floors). No new cascade machinery.

**No backtracking needed — monotonic tightening.** The one hard case: a provider is shared, and a
stricter floor arrives *after* the provider was already chosen (first-demand-wins reuse). Resolve it
by raising the per-capability state from "provider chosen" to **"provider chosen at ≥ the max floor
demanded so far."** A stricter floor **tightens** the binding to the lowest one meeting the new max
and re-enqueues its dependents. This is monotonic (floors only rise, finitely many bindings ⇒ it
terminates) and stays inside the existing fixpoint — it is *not* search-with-backtracking. The only
failure is "max floor exceeds what any binding guarantees" → a clean, terminating error.

## Posture: available, not automatic

Auto-swapping an install method can break things, so the **default is surface-and-choose**, not
silent substitution:

- **Fresh resolution, default method can't meet a floor** → a resolve-time advisory naming the
  methods that *can*, and the user **pins** one. (Monotonic auto-tightening is a later **opt-in**
  convenience — the gentoo-ish "just make it meet the floor" — never the default.)
- **Replacing an already-installed method** (e.g. adding a component that needs `cargo≥1.96` when
  rust is installed as native 1.75) is **always an explicit action**. The resolver *computes* and
  *reports* the need ("rust is native 1.75; X needs ≥1.96; switching to the source/rustup method
  replaces it — proceed?"); the destructive swap only happens on the user's say-so.

## User-facing visibility

`configsys versions <component>` (and/or `where --versions`): per binding, the version it would
install, with the native lag called out —

```
ripgrep
  native   (apt)      14.1.0     ← installed; lags tip
  tarball             15.2.0
  source              15.2.0  (builds tip)
```

Read-only, mostly buildable **today** on `get_latest`; it delivers "the user should know," exercises
the layer-1/2 substrate + caching, and makes drift *visible before we automate anything*. "Specify
a version" is a filter on this view: `--min 15` dims methods that don't clear the floor and offers to
pin one.

## Scope decisions

**Locked**
- Floors (`>=`) are first-class; **ceilings (`<=`) are deferred.** They're not the mirror of floors:
  a floor can be guaranteed by a latest-tracking binding, but a ceiling cannot (latest may exceed it
  next week), so ceilings force pinned bindings and are inherently fragile. Revisit only if a real
  need appears.
- **Surface-and-choose is the default**; auto-tightening is opt-in and later; method *replacement*
  is always explicit.
- Data model: cache reality (layers 1–2), sweep authored intent (layer 3).

**The easy first slice — env-provided capabilities.** Some capabilities have no unit (the OS *is*
the provider: glibc, the platform). Their version is a **static fact of the context**: an OS block
declaring `provides: { glibc: 2.39 }` makes `requires: { glibc: ">=2.35" }` a pure static check,
identical in character to `when:` — no binding selection, no discovery. This reuses machinery
already trusted and is the lowest-risk place to introduce the floor syntax.

**Parked / open**
- The recent-toolchain bindings this leans on (rustup / a pinned recent Go) don't exist yet — the
  `source-plugin-plan.md` "toolchain-floor follow-up." This feature is the *mechanism*; those are
  its first *payload*. They can land together.
- Exact per-machine native-version cache location + TTL (next to the ledger; TTL tuning).
- Whether `provides:` gains a version map or a sibling `provides-version:` field (leaning: extend
  `provides:` to accept a `{cap: floor}` map, keeping the bare form).
- Constraint syntax for a requirement inside a list vs a dedicated `requires-version:` block.

## Auto-derived floors + the `version-floors:` patch section

Floors are *knowledge about a recipe*, so they should write themselves rather than be hand-kept:

- **Derivation (SHIPPED — `configsys/floorderive.py`, `tools/versionsweep.py --derive`).** For each
  `via: source` recipe, read the build manifest straight from its repo and extract the toolchain
  minimum: Rust MSRV (`Cargo.toml` `rust-version`), Go (`go.mod` `go` directive). Emits
  `{ component: { cap: ">=X" } }`. Verified live: ripgrep→cargo 1.96, lazygit→go 1.25, superfile→
  go 1.26 (matches the hand-found values). Pure (fetch injected), unit-tested offline. The
  maintainer's daily sweep runs this and publishes the result.

- **The `version-floors:` section (DESIGNED).** A new mergeable section, a sibling of
  `component-names:` — it PATCHES a floor onto a component's requirement for a capability without
  redefining the component:

  ```
  version-floors: { ripgrep: { cargo: ">=1.96" }  lazygit: { go: ">=1.25" } }
  ```

  Folding reuses existing machinery: (1) `merge_version_floors(layers)` unions it low→high (a copy
  of `merge_name_overrides`); (2) after components build, apply each `(component, cap, constraint)`
  wherever that component ALREADY requires `cap` — a patch only TIGHTENS an existing requirement,
  never creates one (additive-safe, like inline floors); (3) consumers (sweep, stage-3 resolution)
  read the same `req_versions` maps, unchanged. Precedence is normal layer order (a user's
  `version-floors` > a plugin's > the repo's), so recipes ship BARE `requires: cargo` and a
  **`main`-keyed** `configsys-versions` data plugin supplies the floors, updated daily with no
  version bump — the plugin ABI gate still guards code/data skew. This is the out-of-band data
  channel done with the mechanism that already exists (a data plugin), not a bespoke live file.

**Floors are per-BINDING, and track the version that binding builds.** A toolchain floor is a
BUILD requirement, so it exists only on the `via: source` binding (native/tarball install prebuilt
binaries — no toolchain need); a component-keyed floor lands there automatically because the cap is
required only there. And it's derived from the ref the binding actually BUILDS — its `ref:` or
resolved release tag, NOT HEAD (`floorderive.built_ref`), since HEAD can carry an unreleased MSRV
bump higher than the tag you'd compile (observed: superfile HEAD wanted go 1.26 but the built
`v1.6.0` only needs 1.25.7).

**(b) — per-`via` keying, DEFERRED.** The rare case that genuinely needs a floor to differ per
method for the SAME cap is a RUNTIME floor on prebuilt methods (native Foo v2.9 needs `glibc
≥2.31`, the tarball's v3.1 needs `≥2.35`) — each prebuilt artifact has its own runtime needs. It's
hard to auto-derive and usually moot (the packager already ensured native compat). If it ever
matters, extend `version-floors:` to nest by via — `version-floors: { foo: { tarball: { glibc:
">=2.35" } } }` — applied to just that binding. Not built until a real case appears; component→cap
stays the common form.

## Python interpreters as versioned providers

The version-scoped-provider resolver's most complete worked instance (the same mechanism as
`jdk-17/21/25` → `jdk` and `cuda-toolkit-11/12` → `cuda-toolkit`; built 2026-08, history in
`docs/done/python-versions-plan.md`). Each supported CPython line is its own component and a
**version-scoped provider** of one shared `python3` capability:

| component | `provides:` | `standing:` | role |
| --- | --- | --- | --- |
| `python3.10` | `{ python3: "3.10" }` | `never-auto` | configsys's minimum line |
| `python3.11` | `{ python3: "3.11" }` | `never-auto` | |
| `python3.12` | `{ python3: "3.12" }` | `never-auto` | |
| `python3.13` | `{ python3: "3.13" }` | (ordinary) | the modern default |
| `python3.14` | `{ python3: "3.14" }` | `never-auto` | newest stable; held back until the ecosystem catches up |

The fixed **component-level** version is what makes the cap version-scoped
(`Resolver._version_scoped`: some provider of the cap declares `prov_versions[cap]`), and that flips
two behaviors relative to a toolchain cap like `go`, whose version lives on a binding: a constraint
**selects** a provider by its declared version, and an unsatisfiable constraint is a **hard error**
(`nothing provides "python3 >=3.15" here`) rather than a soft floor that falls back to the default
provider and becomes an advisory.

**Methods.** Every line has the same three bindings:

- `{ via: native  when: "debian"  packages: [ python3.X, python3.X-venv, python3.X-dev ]
  ppa: deadsnakes/ppa  requires: software-properties-common }` — Ubuntu's non-default lines come
  from the deadsnakes PPA (apt's `ppa:` field runs `add-apt-repository`); harmless where the line is
  the base version. (`python3.10` also lists `python3.10-minimal`.)
- `{ via: native  when: "fedora or redhat"  packages: [ python3.X ] }` — Fedora/EL ship the lines
  directly.
- `{ via: pyenv  version: "3.X" }` — unconditional: `drivers/pyenv.Pyenv` compiles the line's latest
  patch user-scope under `~/.pyenv/versions/` (driver `requires: [ pyenv, python-build-deps ]`);
  `get_version` reports the newest installed patch on the line.

On debian/fedora/EL lineages the gated native binding is the default by specificity; choose pyenv
with a binding-pin, `pins: { python3.13: pyenv }`. That pin is classified as a binding-pin because
its value is a via — even though `pyenv` is also a component name (`Resolver._satisfy` checks
`pin_via_names` first, matching `app._validate_pin` and routecheck). Everywhere else only pyenv is
valid, so it is the default — and where `python-build-deps` has no route (`fedora_atomic`, §6a of
`docs/routing-model.md`) the interpreter components are unroutable. Each method installs a distinct
`python3.X` binary, so several lines coexist as ordinary residents. **configsys never repoints the
system `python3`** (apt and distro tools depend on it); a tool selects a line by calling `python3.X`
or a venv built from it.

**The unversioned baseline.** `linux: { provides: python3 }` in routes.hu `os:` — the bootstrap
guarantees a system python3 ≥ 3.10 everywhere, so a bare `requires: python3` (e.g. `cython`) is
environment-satisfied and installs nothing. That baseline carries **no version**, and
`versionsweep.meets` treats an unknown version as not meeting a floor, so ANY constrained
`requires: { python3: … }` pulls a `python3.X` component even when the system interpreter would
qualify. Constraints never consult the live `python3 -V` — resolution stays offline and
deterministic. Installed reality enters only through the detection tier (`adopt-installed`,
`detection.detect_pins`): when the resolved line isn't installed but another `python3` provider
is, it soft-pins `python3` to the installed one — below user pins, and still subject to the
constraint check in step 3 below.

**Selection — `Resolver._satisfy_constrained`, in order:**

1. reuse the cap's default resident if its provided version meets the constraint (for `python3`
   the default is the versionless baseline, so this never fires);
2. reuse a resident already pulled for the same `(cap, constraint)` (`Resolver.constrained`);
3. otherwise filter providers to those whose declared version meets the constraint. A provider-pin
   (`pins: { python3: python3.12 }`) wins if it is among them, and is a hard error if not. Unpinned,
   the pool is the ordinary (non-`never-auto`) survivors, else all survivors — **a constraint
   enables `never-auto` providers**, because it is itself an explicit selection. One survivor wins;
   several on a version-scoped cap resolve to the **highest provided version**
   (`osversion.parse_version`, name as the final tiebreak) — the newest interpreter meeting the bound
   is the unsurprising choice, and it keeps a plain range pin-free and deterministic.

So, on ubuntu 24.04: `">=3.11"` → `python3.13` (the only ordinary survivor), `">=3.14"` →
`python3.14` (enabled by the constraint), `"<3.12"` → `python3.11` (the highest of the two
`never-auto` survivors), bare `python3` → the baseline. Two consumers with different constraints
get two coexisting residents. Requiring a line **by name** (`requires: python3.14`) also bypasses
`never-auto` — the required cap is the provider's own name (`p == cap` in `Resolver._satisfy`).

```humon
{ components: {
    my-tool: { requires: { python3: ">=3.11" }       // resolves python3.13; ">=3.14" would enable python3.14
               install: [ { via: pipx  name: my-tool } ] }
} }
```

**The interpreter pin — the `python:` binding field.** A `via: pip` or `via: pipx` binding may name
the interpreter to install with:

- **pip** (`drivers/pip.Pip._pip`) runs `<python> -m pip install --user`, so the package lands in
  that interpreter's user site; `get_version` probes that interpreter directly (`<python> -m pip
  list --user`) because the batched index enumerates only the default `python3`. Every pip read is
  user-site only — a plain `pip list` also shows the distro's Python packages, which aren't pip
  installs (see the `drivers/pip.py` docstring, which also covers PEP 668).
- **pipx** (`drivers/pipx.Pipx._py_flag`) adds `--python <python>` to the venv-creating ops (install,
  `set_version`). `upgrade` becomes `pipx reinstall --python …`, the only pipx op that rebuilds a
  venv on a new interpreter (`pipx upgrade` keeps the venv's interpreter and `install --force`
  ignores `--python`), so an interpreter bump also picks up the latest release. `get_latest` scopes
  PyPI's latest to the release that interpreter can run (`_target_python`: the pin's `X.Y`, else the
  installed venv's interpreter), so a python-capped package doesn't read as outdated with no way
  forward; `configsys versions` adds a one-line `version_advisory` naming the capping interpreter and
  a pin that lifts it.

`python:` is a static string handed to the driver; it is not a resolver key and installs nothing.
Pair it with a **by-name** `requires:` on the matching line so the binary exists — the shipped
consumers do exactly that (`pywal16`/`mitmproxy` on debian: `python: "/usr/bin/python3.13"
requires: python3.13`; `home-assistant`: `requires: [ python3.14, … ]` + `python: python3.14`).
By name, not by constraint: a constraint picks *some* line at resolve time, while `python:` must
name one binary, and a by-name require is what keeps the two in agreement. A full `/usr/bin/…` path
guards against `PATH` resolving the bare name to a pyenv/uv build — and correspondingly assumes the
native method (a `pins: { python3.13: pyenv }` leaves `/usr/bin/python3.13` absent).

**`configsys check`.** Two related lints: (1) the **python floor warning** — when the interpreter
configsys itself runs on (the system python the `.venv` inherits) is at the 3.10 minimum, `check`
warns to upgrade the system python before it ages out, noting that a `python3.X` component installs
a newer interpreter *alongside* and doesn't change the one configsys runs on; (2)
`routecheck.pin_constraint_conflicts` flags a provider-pin whose provided version fails a
component-level constraint on the same cap (`pins: { python3: python3.12 }` against a
`requires: { python3: ">=3.13" }`), which could never resolve for that consumer.

## Roadmap (each stage is useful alone and de-risks the next)

1. **Visibility — SHIPPED.** `configsys versions <component> [--min V] [--refresh]` lists each
   candidate method with the version it would install, the newest ("tip"), lag flags, and (with
   `--min`) which methods meet a floor + the pin to use one. Reusable core in
   `configsys/versionreport.py` (per-binding `get_latest` via `resolve.unit_for_binding`, cached
   machine-locally in `method-versions.hu` with a TTL; installed versions read live). **TUI:** the
   `m` install-method picker now shows each method's version + a "lags" flag and the tip in its
   title, so switching methods is version-informed. Read-only, low risk.
2. **Authored floors + version-sweep — SHIPPED (machinery).** Versioned `requires:`/`provides:`
   syntax parses ADDITIVELY: a `{ cap: ">=1.96" }` entry contributes exactly its capability name to
   the resolver (closure unchanged — golden byte-identical) while its constraint is stored on the
   Component/Binding (`req_versions`/`prov_versions`) for the sweep + floor-aware resolution.
   `resolve.cap_names`/`cap_constraints` do the split (component, binding, and driver-level
   requires). `configsys where` annotates a capability with its floor (`cargo (>=1.96)`). The
   **version-sweep** (`configsys/versionsweep.py` pure core + `tools/versionsweep.py` CLI, a
   networked maintenance tool like the name-sweep) checks two things against real per-method
   versions (via versionreport): **stranded** requirements (a floor no method here can meet) and
   **dishonest** provides (a method delivering below its claimed floor). *Real floors aren't
   authored in shipped data yet* — they land in stage 3 with the satisfying bindings, so a floor is
   never shipped stranded.
3. **Floor-aware resolution, surface-and-choose** — resolve-time advisory + pin; explicit
   method-replacement flow.
   - **3a SHIPPED — the advisory.** `configsys/flooradvise.py`: over the resolved plan, for each
     ACTIVE floored requirement (component-level, plus the WINNING binding's — a resolved unit now
     carries its `via`), if the provider's DEFAULT method can't meet the floor, emit an advisory
     naming the methods that can and the exact `configsys pin set` — never a silent swap (the
     locked posture). Reuses versionreport (real per-machine versions) + `versionsweep.meets` (full
     constraint eval); abstains when a version is unknown (no false alarm). Surfaced through
     `ctx.diagnostics` (inspect + the TUI `!` page); a no-op until floors are active. Verified live:
     ripgrep-via-source needs cargo ≥1.96, box's apt rust is 1.95 → "no install method here meets
     cargo ≥1.96".
   - **3b SHIPPED.** Three pieces, working end-to-end:
     - **`version-floors:` section** (`layers.merge_version_floors` + `routes._apply_version_floors`)
       — a mergeable patch (sibling of `component-names`) that TIGHTENS an existing requirement's
       floor without redefining the component; only where the cap is required (never creates one),
       so resolution is byte-identical. A `main`-keyed data plugin folds floors into bare recipes.
     - **First recent-toolchain binding** — `rust` gains a `via: script` rustup method (latest
       stable, userland `~/.cargo`, least-preferred so native stays default), with a `provides:
       { cargo }` floor and a `url`-regex version source (the stable channel manifest). Fixed a
       general bug: the `url` version kind now returns the regex CAPTURE GROUP, not the whole match.
     - **Method-replacement caveat** — the advisory now becomes ACTIONABLE ("pin rust to script")
       and, when the too-old provider is already INSTALLED via the default method, adds an explicit
       "switching won't remove it" note — replacement stays a deliberate act, never automatic.
     - Verified live: a `version-floors` floor of cargo ≥1.96 on ripgrep-via-source → "pin rust to
       script (script meets it): `configsys pin set rust script` (rust is installed via native;
       switching won't remove it)".
4. **Opt-in auto-tightening — SHIPPED.** The `auto-tighten` machine setting (default OFF). When on,
   `load_pipeline` runs `flooradvise.tighten_pins` after the first resolve — for each unmet floor
   with a satisfying method, it auto-pins the provider to that method and RE-RESOLVES
   (`Resolver.resolve_resilient(extra_pins=…)`, which layers pins on without mutating the resolver).
   The monotonic step: it only ever moves a provider to a higher-versioned method. **Replacement
   stays explicit even here** — a provider already INSTALLED via the too-old default method is
   skipped (it remains an advisory, not an auto-swap). Verified live: on a box with rust installed,
   auto-tighten yields `{}` and the advisory still fires; the tighten path is unit-tested for the
   fresh case (`{rust: tarball}`).

## ✅ 3c — the source build finds a floor-pinned toolchain (SHIPPED)

The advisory/tighten machinery selects the right toolchain, but a source build runs in a fresh
non-interactive shell, so a NON-native toolchain (rustup's cargo in `~/.cargo/bin`) wouldn't be
found. The `source` driver now prepends the well-known userland toolchain bin dirs
(`~/.cargo/bin`, `~/go/bin`, plus any recipe `build-path:`) to `$PATH` for the `build:` command —
a native toolchain on the system PATH still works; a missing dir is harmlessly ignored. This turns
floor-driven *selection* into a working *build*: pin rust→rustup, and ripgrep-from-source's
`cargo build` finds the recent cargo.

Interactive use is deliberately NOT shipped as a bash.d snippet — that's personal shell config, and
configsys ships none (the rustup binding uses `--no-modify-path`, so it never edits your rc). Put
`~/.cargo/bin` on PATH yourself for interactive `cargo`. The recent-Go tarball binding (deferred)
follows the same pattern; its `~/go/bin` is already covered by the build-PATH prepend.
