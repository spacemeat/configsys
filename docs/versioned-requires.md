# Versioned requirements & per-method version visibility (design)

> **Status: REFERENCE** — the version-floor model (min-version `requires:`, `version-floors:`, the floor and resident-floor advisories, `auto-tighten`, `configsys versions`); every roadmap stage shipped by 2026-08-02 (09579c7). The design sections (Syntax, Resolution semantics, Posture, Scope decisions) date from then and are annotated where what shipped differs — chiefly the version-scoped-provider resolver (66b764b), which "Python interpreters as versioned providers" documents as built, and whose rules live in docs/routing-model.md §11; maintained.

Captures the model, the data/caching story, and a staged plan
for two linked capabilities that share one substrate:

1. **User-facing version visibility** — see, per install method (native/tarball/source/flatpak/…),
   what version a component would install, with the native-vs-tip lag called out; filter methods by
   a version floor and pin one.
2. **Version-constrained requirements** — a `requires:` may carry a minimum version
   (`requires: { cargo: ">=1.96" }`); the resolver can tell which methods satisfy it and cascade
   the constraint through the dependency chain — surfacing the choice, not silently swapping.

The direct motivator is the **toolchain-floor** finding from [source-plugin-plan.md](todo/source-plugin-plan.md): a correct
source recipe (ripgrep needs Rust ≥1.96, lazygit Go ≥1.25) still fails when the *default* method
(native) ships an older toolchain. Versioned requires is the general, principled form of that fix;
version visibility is the same data made useful to the user directly.

## The core tension: static vs dynamic versions

configsys has two kinds of "version," and they live in different worlds:

- **OS version** (`when: "ubuntu < 23.04"`) is a **static fact of the machine context** — known
  before resolution runs. That's why the boolean `when:` checks are clean.
- A component's **provided version** is **dynamic and install-time**: `versions.py` discovers it
  over the network, lazily, only when installing or reporting; `resolve.py` never discovers one. The
  resolver closes over capability **names** (`resolve.cap_names`, provider index = `cap → {units}`);
  the only versions it compares are ones DECLARED in route data (`resolve.cap_constraints` — a
  provider's `provides: { python3: "3.13" }`, a consumer's `requires: { python3: ">=3.11" }`).

So `requires: { cargo: ">=1.96" }` asks the resolver a question it structurally can't answer live
without breaking three invariants at once — resolution is **offline**, **deterministic** (the
golden gate depends on it), and **backtrack-free**. Discovering candidate versions at resolve time
is therefore rejected. The design instead makes the needed version facts **static annotations** (or
cached reality), mirroring how `when:` stays static.

## Substrate that already exists

**Every driver implements `get_latest`** — "what version would *this* method install."
Native (apt/dnf/pacman/zypper/apk/xbps/brew), tarball, source, cargo, flatpak, all of them. So
"versions available per method" is answerable per binding. What was missing at design time —
presentation, a caching policy for those results, and the authored-floor layer — is now built
(Roadmap below). `versions.py` caches network discovery in `<state>/versions.hu` with a TTL (one
TTL cache class for both caches, `cachefile.TTLRecords`).

## The data splits into three layers (this IS the maintenance story)

| layer | example | nature | cache | honesty mechanism |
| --- | --- | --- | --- | --- |
| **1. globally-discoverable** | `version: { github: … }`, crates/pypi latest | machine-independent reality | `versions.hu`, TTL (exists) | none authored — refresh |
| **2. machine-local per-method** | apt/dnf candidate version | per-machine reality | `method-versions.hu`, 24 h TTL (versionreport — every method, not only native) | none authored — refresh |
| **3. authored-static** | `static:` pins; provided-version floors; requirement floors (inline or `version-floors:`) | authored intent | none (shipped route data) | **version-sweep** |

The split is the whole point: **layers 1–2 are cached reality (refresh, don't sweep); layer 3 is
authored intent (sweep, don't cache).** Only layer 3 drifts *as data* — and it drifts because
upstreams change (a new ripgrep bumps its MSRV), exactly the kind of thing a sweep catches.

### The version-sweep (sibling to the name-sweep)

For each component × method, discover the real version (layers 1–2) and check:
- **(a) honesty** — each binding actually delivers the floor it *claims* (`provides` floor ≤ real);
- **(b) not stranded** — some method still meets each *requirement* floor here;
- **(c) lag** — optionally report native-vs-tip gaps.

`tools/versionsweep.py` (pure core `configsys/versionsweep.py`) runs (a) and (b) against THIS
machine's repos and discovery and exits nonzero on any finding; (c) is what `configsys versions`
shows. No container harness ships for it (unlike `test/run-name-sweep-in-podman.sh`) — for
cross-distro coverage, run it inside a per-distro container. Turns "silently broke six months later"
into "the sweep flags a stale floor."

## Syntax

**Requirement with a floor** — a `requires:` entry may be a bare capability or a
`{ cap: constraint }` map (as a list item, or the whole `requires:` value); it reuses the `when:`
comparison vocabulary — `>=`, `>`, `<`, `<=`, `=` (a bare version is exact) and `,`-AND ranges
(`">=1.2,<2"`), checked by `osversion.meets`:

```
ripgrep-source: { requires: [ { cargo: ">=1.96" } ]  … }        # floor
htop-source:    { requires: [ cc, make, ncurses ]  … }          # bare (unchanged)
```

**Provided version** — a binding that pins `version: { static: X }` needs no claim (its
`get_latest` is X, which the advisory reads); otherwise a binding declares a *guaranteed floor*,
or a component a fixed version, via an extended `provides:` map:

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

*Design (2026-08-02):* filter a provider's candidate **bindings** to those whose declared or derived
version satisfies the floor, then apply the normal selection among survivors (specificity,
`standing:`, `driver-preference`), with in-resolver monotonic tightening. **What shipped** is
narrower and keeps resolution offline and deterministic — the full rules are docs/routing-model.md
§11 (`resolve._State._satisfy_constrained`):

- **Version-scoped capability** — some provider declares a COMPONENT-level version (`python3.X`,
  `jdk-NN`, `cuda-toolkit-NN`; `_State._version_scoped`): the constraint **selects** a provider by
  that declared version, enables `never-auto` providers, and is a hard error when none carries it.
  Worked example: "Python interpreters as versioned providers" below.
- **Method-versioned capability** — the version lives on a binding (`go`, `cargo`, `ghc`: the rustup
  method's `provides: { cargo: ">=1.97" }`): the constraint is a **soft floor**. The default
  provider resolves as if unconstrained, and the floor is checked afterwards against real
  per-method versions by `flooradvise` (stage 3a) — an advisory, never a silent swap. The opt-in
  "make it meet the floor" step is `auto-tighten` (stage 4): a floor pin on the provider and a
  second resolve, not a search inside the resolver.

**Cascade is nearly free.** The worklist already closes `requires` transitively, so a selected (or
floor-pinned) provider's own `requires` close normally — including any floors of its own. No new
cascade machinery.

**No backtracking — monotonic tightening** (the design rationale `auto-tighten` realizes). The hard
case: a provider is shared, and a stricter floor arrives *after* the provider was already chosen
(first-demand-wins reuse). Treating the per-capability state as **"provider chosen at ≥ the max
floor demanded so far"** keeps it monotonic: a stricter floor only ever moves the provider to a
method meeting the new max (floors only rise, finitely many methods ⇒ it terminates). The only
failure is "max floor exceeds what any method guarantees" → an advisory naming that no install
method here meets it.

## Posture: available, not automatic

Auto-swapping an install method can break things, so the **default is surface-and-choose**, not
silent substitution:

- **Fresh resolution, default method can't meet a floor** → an advisory naming the methods that
  *can* and the exact `configsys pin set`, and the user **pins** one. Monotonic auto-tightening —
  the gentoo-ish "just make it meet the floor" — is the **opt-in** `auto-tighten` setting (default
  off), never the default.
- **Replacing an already-installed method** (e.g. adding a component that needs `cargo≥1.96` when
  rust is installed as native 1.75) is **always an explicit action**. The advisory *reports* the
  need and that the provider is installed via the too-old default; `auto-tighten` never pins such a
  provider. Pinning it is your call, and installing the provider after the pin runs the ordinary
  method-switch swap (`installState.plan_with_swaps`), shown in the plan before you confirm.

## User-facing visibility

`configsys versions <component> [--min V] [--refresh]` (`cli/where.cmd_versions` over
`versionreport.report`): per candidate method, the version it would install, with the default (or
pinned) method, any installed version and the lag behind the newest ("tip") called out —

```
ripgrep   (tip 15.2.0)
  native (apt)  14.1.0   [default, installed, lags tip]
  tarball       15.2.0
  source        15.2.0
```

A method with a one-line advisory gets a `⚠` line under it (pipx: the interpreter caps the
installable release; a recipe-pinned build behind upstream). Read-only, on `get_latest`; it
delivers "the user should know," exercises the layer-1/2 substrate + caching, and made drift
*visible before anything was automated*. "Specify a version" is a filter on this view: `--min 15`
tags each method `meets ≥15` / `below ≥15` and, when the default is below, prints the
`configsys pin set` that selects one that meets it. (The design's `where --versions` alias was not
built; `where` annotates a floored capability instead — stage 2.)

## Scope decisions

**Locked**
- Floors (`>=`) are first-class; **ceilings (`<=`) on a method-versioned capability are deferred.**
  They're not the mirror of floors: a floor can be guaranteed by a latest-tracking binding, but a
  ceiling cannot (latest may exceed it next week), so ceilings force pinned bindings and are
  inherently fragile. Revisit only if a real need appears. Upper bounds DO work where the version
  is a component's fixed identity (version-scoped providers: `requires: { cuda-toolkit: "<12" }`
  selects `cuda-toolkit-11`, `"<3.12"` a `python3.11`), because a declared version can't drift.
- **Surface-and-choose is the default**; auto-tightening is opt-in (shipped, stage 4); method
  *replacement* is always explicit.
- Data model: cache reality (layers 1–2), sweep authored intent (layer 3).

**The easy first slice — env-provided capabilities (designed, NOT built).** Some capabilities have
no unit (the OS *is* the provider: glibc, the platform). The idea: an OS block declaring
`provides: { glibc: 2.39 }` makes `requires: { glibc: ">=2.35" }` a pure static check, identical in
character to `when:`. OS-block `provides:` still takes bare names only (`glibc_linux: { provides:
glibc }`), so a glibc floor is written as an OS-version `when:` gate on the binding instead (mojo's
manylinux_2_34 wheels: `when: "not (rhel < 9) and not (debian < 12)"`); the release registry's
`glibc:` field is maintenance data the resolver doesn't read.

**Settled since the design** (each was an open question on 2026-08-02)
- The recent-toolchain bindings this leans on — the [source-plugin-plan.md](todo/source-plugin-plan.md)
  "toolchain-floor follow-up" — shipped with it: rust's rustup `via: script` method (d9db757) and
  go's official-tarball method (bdf8a1b).
- The per-method version cache: `<state>/method-versions.hu`, 24 h TTL (`versionreport.LATEST_TTL`),
  every method rather than native only.
- `provides:` accepts a `{cap: version}` map alongside the bare form (no `provides-version:` field).
- A constraint is written inline in `requires:` (a `{cap: constraint}` list item or map, at
  component or binding level) or patched on by the `version-floors:` section — no
  `requires-version:` block.

## Auto-derived floors + the `version-floors:` patch section

Floors are *knowledge about a recipe*, so they should write themselves rather than be hand-kept:

- **Derivation (SHIPPED — `configsys/floorderive.py`, `tools/versionsweep.py --derive`).** For each
  `via: source` recipe, read the build manifest straight from its repo and extract the toolchain
  minimum: Rust MSRV (`Cargo.toml` `rust-version`), Go (`go.mod` `go` directive). Emits
  `{ component: { cap: ">=X" } }`, rendered as a ready-to-commit `version-floors:` block
  (`floorderive.emit_floors`). Verified live at the time: ripgrep→cargo 1.96, lazygit→go 1.25,
  superfile→go 1.26 (HEAD values — see the built-ref rule below). Pure (fetch injected), unit-tested
  offline. Run it with the configsys-source plugin loaded (its recipes carry the `via: source`
  repos); the maintainer commits the printed block to the configsys-versions plugin's `floors.hu`
  (no CI job ships for it — it is a manual maintenance run).

- **The `version-floors:` section (SHIPPED — stage 3b).** A mergeable section, a sibling of
  `component-names:` — it PATCHES a floor onto a component's requirement for a capability without
  redefining the component:

  ```
  version-floors: { ripgrep: { cargo: ">=1.96" }  lazygit: { go: ">=1.25" } }
  ```

  Folding reuses existing machinery: (1) `layers.merge_version_floors` overlays it low→high per
  `(component, cap)` (a later layer wins); (2) after components build, `routes._apply_version_floors`
  sets each constraint wherever that component ALREADY requires `cap` — at component level and on
  every binding that requires it. It constrains an existing requirement and never creates one (a
  floor for a cap the component doesn't require is ignored); for that cap it replaces an inline
  constraint. (3) Everything downstream — the resolver, the advisories, the sweep — reads the same
  `req_versions` maps, so a patched floor behaves exactly like one written in place (it selects a
  version-scoped provider; on a method-versioned cap it is a soft floor). Precedence is normal layer
  order (a user's `version-floors` > a plugin's > the repo's), so recipes ship BARE
  `requires: cargo` and the **`main`-keyed** [configsys-versions](https://github.com/spacemeat/configsys-versions)
  data plugin (in README's known plugins; configsys-source brings it along) supplies the floors,
  updated daily with no version bump — the plugin ABI gate still guards code/data skew. This is the
  out-of-band data channel done with the mechanism that already exists (a data plugin), not a
  bespoke live file.

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
| `python3.10` | `{ python3: "3.10" }` | `never-auto` | configsys's minimum line; upstream end-of-life |
| `python3.11` | `{ python3: "3.11" }` | `never-auto` | |
| `python3.12` | `{ python3: "3.12" }` | `never-auto` | |
| `python3.13` | `{ python3: "3.13" }` | (ordinary) | the modern default |
| `python3.14` | `{ python3: "3.14" }` | `never-auto` | |
| `python3.15` | `{ python3: "3.15" }` | `never-auto` | the newest stable line |

The fixed **component-level** version is what makes the cap version-scoped
(`resolve._State._version_scoped`: some provider of the cap declares `prov_versions[cap]`), and that flips
two behaviors relative to a toolchain cap like `go`, whose version lives on a binding: a constraint
**selects** a provider by its declared version, and an unsatisfiable constraint is a **hard error**
(`nothing provides "python3 >=3.16" here`) rather than a soft floor that falls back to the default
provider and becomes an advisory.

**Methods.** Each line carries some of:

- `{ via: native  when: "ubuntu and not (ubuntu >= 26.10)"  packages: [ python3.X, python3.X-venv,
  python3.X-dev ]  ppa: deadsnakes/ppa  requires: software-properties-common }` — Ubuntu LTS series'
  non-default lines come from the deadsnakes PPA (apt's `ppa:` field runs `add-apt-repository`);
  harmless where the line is the base version. deadsnakes publishes no 26.10 suite and nothing for
  Debian, so the gate tracks what it carries (`python3.10` also lists `python3.10-minimal`).
- native bindings where the distro ships the line itself, each gated to the releases that carry it:
  Debian's own release python (`debian >= 12 and debian < 13` → 3.11, trixie → 3.13), the newer
  Ubuntu archive (26.04 → 3.14, 26.10 → 3.15), Fedora, and EL AppStream / EPEL (`python3.13` on EL
  9/10 `requires: epel`).
- `{ via: pyenv  version: "3.X" }` — unconditional: `drivers/pyenv.Pyenv` compiles the line's latest
  patch user-scope under `~/.pyenv/versions/` (driver `requires: [ pyenv, python-build-deps ]`);
  `get_version` reports the newest installed patch on the line.
- `{ via: brew  name: "python@3.X" }` (3.11 and newer) — Homebrew's keg, valid only on glibc (the
  brew driver's `when:` gate).

Where a native binding is valid it is the default by specificity; elsewhere brew beats pyenv on
driver-preference (pyenv is in no preference list, so it ranks last), and on musl (Alpine), where
brew is gated out, pyenv is the default. Choose pyenv with a binding-pin, `pins: { python3.13: pyenv }`.
That pin is classified as a binding-pin because its value is a via — even though `pyenv` is also a
component name (`resolve._State._satisfy_pinned` checks `pin_via_names` first, matching
`actions.validate_pin` and routecheck). Where `python-build-deps` has no route (`fedora_atomic`,
`kde_linux` — §6a of `docs/routing-model.md`) the pyenv driver is derived-gated and brew is the only
method. Each method installs a distinct `python3.X` binary, so several lines coexist as ordinary
residents. **configsys never repoints the system `python3`** (apt and distro tools depend on it); a
tool selects a line by calling `python3.X` or a venv built from it.

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

**Selection — `resolve._State._satisfy_constrained`, in order:**

1. reuse the cap's default resident if its provided version meets the constraint (for `python3`
   the default is the versionless baseline, so this never fires);
2. reuse a resident already pulled for the same `(cap, constraint)` (`_State.constrained`);
3. otherwise filter providers to those whose declared version meets the constraint. A provider-pin
   (`pins: { python3: python3.12 }`) wins if it is among them, and is a hard error if not. Unpinned,
   the pool is the ordinary (non-`never-auto`) survivors, else all survivors — **a constraint
   enables `never-auto` providers**, because it is itself an explicit selection. One survivor wins;
   several on a version-scoped cap resolve to the **highest provided version**
   (`osversion.parse_version`, name as the final tiebreak) — the newest interpreter meeting the bound
   is the unsurprising choice, and it keeps a plain range pin-free and deterministic.

So, on ubuntu 24.04: `">=3.11"` → `python3.13` (the only ordinary survivor), `">=3.14"` →
`python3.15` (the highest of the two `never-auto` survivors, both enabled by the constraint),
`"<3.12"` → `python3.11` (likewise, over 3.10), bare `python3` → the baseline. Two consumers with different constraints
get two coexisting residents. Requiring a line **by name** (`requires: python3.14`) also bypasses
`never-auto` — the required cap is the provider's own name (`p == cap` in `_State._satisfy_pinned`).

```humon
{ components: {
    my-tool: { requires: { python3: ">=3.11" }       // resolves python3.13; ">=3.14" would enable python3.15
               install: [ { via: pipx  name: my-tool } ] }
} }
```

**The interpreter pin — the `python:` binding field.** A `via: pip` or `via: pipx` binding may name
the interpreter to install with:

- **pip** (`drivers/pip.Pip._pip`) runs `<python> -m pip install --user`, so the package lands in
  that interpreter's user site; `get_version` probes that interpreter directly (`<python> -m pip
  list --user`) because the batched index enumerates only the default `python3`. Every pip read is
  user-site only — a plain `pip list` also shows the distro's Python packages, which aren't pip
  installs (see the `drivers/pip.py` docstring, which also covers PEP 668). Its "latest" is scoped
  to the release that interpreter can install (`Pip._disco_spec`: the pinned python's version, else
  the default `python3`'s), as pipx's is below.
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
consumers do exactly that (`pywal16`/`mitmproxy`/`qtile` on Ubuntu < 24.04: `python:
"/usr/bin/python3.13"  requires: python3.13`, and on EL < 10 / Amazon Linux the same with
`python3.12`; `home-assistant`: `requires: [ python3.14, … ]` + `python: python3.14`).
By name, not by constraint: a constraint picks *some* line at resolve time, while `python:` must
name one binary, and a by-name require is what keeps the two in agreement. A full `/usr/bin/…` path
guards against `PATH` resolving the bare name to a pyenv/uv build — and correspondingly assumes the
native method (a `pins: { python3.13: pyenv }` leaves `/usr/bin/python3.13` absent).

**`configsys check`.** Related lints: (1) the **python floor warning** — when the interpreter
configsys itself runs on (the system python the `.venv` inherits) is at the 3.10 minimum, `check`
warns to upgrade the system python before it ages out, noting that a `python3.X` component installs
a newer interpreter *alongside* and doesn't change the one configsys runs on; (2)
`routecheck.pin_constraint_conflicts` flags a provider-pin whose provided version fails a
component-level constraint on the same cap (`pins: { python3: python3.12 }` against a
`requires: { python3: ">=3.13" }`), which could never resolve for that consumer; (3)
`unsatisfiable-constraint` (`routecheck.validate`) warns when every provider of a cap declares a
concrete version and none meets a constraint (component or binding level); (4) `bad-constraint`
errors on a constraint whose operand doesn't parse (`">=3.1x"`), which would otherwise never be met.

## Roadmap (each stage is useful alone and de-risks the next)

1. **Visibility — SHIPPED.** `configsys versions <component> [--min V] [--refresh]` lists each
   candidate method with the version it would install, the newest ("tip"), lag flags, and (with
   `--min`) which methods meet a floor + the pin to use one. Reusable core in
   `configsys/versionreport.py` (per-binding `get_latest` via `resolve.unit_for_binding`, cached
   machine-locally in `method-versions.hu` with a TTL; installed versions read live). **TUI:** the
   `v` install-method picker (`tui/flows._pick_method_name`) shows each method's version + a "lags"
   flag and the tip in its title, so switching methods is version-informed. Read-only, low risk.
2. **Authored floors + version-sweep — SHIPPED (machinery).** Versioned `requires:`/`provides:`
   syntax parses ADDITIVELY: a `{ cap: ">=1.96" }` entry contributes exactly its capability name to
   the resolver (closure unchanged — golden byte-identical; the later version-scoped-provider
   resolver made a constraint SELECT among versioned providers) while its constraint is stored on the
   Component/Binding (`req_versions`/`prov_versions`) for the sweep + floor-aware resolution.
   `resolve.cap_names`/`cap_constraints` do the split (component, binding, and driver-level
   requires). `configsys where` annotates a capability with its floor (`cargo (>=1.96)`). The
   **version-sweep** (`configsys/versionsweep.py` pure core + `tools/versionsweep.py` CLI, a
   networked maintenance tool like the name-sweep) checks two things against real per-method
   versions (via versionreport): **stranded** requirements (a floor no method here can meet) and
   **dishonest** provides (a method delivering below its claimed floor). Real floors landed with
   the satisfying bindings in stage 3, so a floor is never shipped stranded; routes.hu now carries
   them inline (hyperfine's cargo binding `requires: { cargo: ">=1.97" }`, goimports'
   `{ go: ">=1.26" }`, …), and configsys-versions patches the source recipes'.
3. **Floor-aware resolution, surface-and-choose** — resolve-time advisory + pin; explicit
   method-replacement flow.
   - **3a SHIPPED — the advisory.** `configsys/flooradvise.py`: over the resolved plan, for each
     ACTIVE floored requirement (component-level, plus the WINNING binding's — a resolved unit now
     carries its `via`), if the provider's DEFAULT method can't meet the floor, emit an advisory
     naming the methods that can and the exact `configsys pin set` — never a silent swap (the
     locked posture). Reuses versionreport (real per-machine versions) + `versionsweep.meets` (full
     constraint eval); abstains when a version is unknown (no false alarm). A method with no
     version source counts as meeting the floor when its own `provides:` promise implies it
     (`flooradvise._provides_meets`, `osversion.implies` — ghcup's `>=9.4` meets `>=9.2`). When YOUR
     pin keeps a below-floor method, the advisory is tagged `pin-floor` and names the unpin / the
     pin that satisfies it (a user pin always wins, even over `auto-tighten`). Surfaced through
     `ctx.diagnostics` (inspect + the TUI `!` page) and, for an install-ish plan, shown before the
     confirm on both surfaces (`actions.build_plan` returns them as `advisories`); a no-op until
     floors are active. Verified live:
     ripgrep-via-source needs cargo ≥1.96, box's apt rust is 1.95 → "no install method here meets
     cargo ≥1.96".
   - **3b SHIPPED.** Three pieces, working end-to-end:
     - **`version-floors:` section** (`layers.merge_version_floors` + `routes._apply_version_floors`)
       — a mergeable patch (sibling of `component-names`) that sets a floor on an existing
       requirement without redefining the component; only where the cap is required (never creates
       one). A `main`-keyed data plugin (configsys-versions) folds floors into bare recipes.
     - **First recent-toolchain binding** — `rust` gains a `via: script` rustup method (latest
       stable, userland `~/.cargo`, least-preferred so native stays default), with a `provides:
       { cargo }` floor and a `url`-regex version source (the stable channel manifest). Fixed a
       general bug: the `url` version kind now returns the regex CAPTURE GROUP, not the whole match.
     - **Method-replacement caveat** — the advisory now becomes ACTIONABLE ("pin rust to script")
       and, when the too-old provider is already INSTALLED via the default method, adds an explicit
       "switching won't remove it — remove it after" note — replacement stays a deliberate act,
       never automatic. *(Since the method-switch swap, b68a645, the note says what happens instead:
       installing a named provider via the pinned method swaps the old install out; one pulled in
       only as a dependency installs alongside it, so the note points at `configsys install
       <provider>` — `flooradvise._replace_note`.)*
     - Verified live: a `version-floors` floor of cargo ≥1.96 on ripgrep-via-source → "pin rust to
       script (script meets it): `configsys pin set rust script` (rust is installed via native;
       switching won't remove it)".
   - **Resident floors.** The method check asks "can a method produce ≥ the floor?"; the resident
     check (`flooradvise.resident_advise`, also on the `!` page) asks whether the provider that is
     ALREADY INSTALLED (and reused via `adopt-installed`) is new enough — e.g. a resident go 1.18 for
     a `go >=1.21` consumer — and points at `configsys upgrade <provider>`. A version-scoped provider
     the constraint excludes (`cuda-toolkit-12` for a `<12` consumer) is never flagged.
4. **Opt-in auto-tightening — SHIPPED.** The `auto-tighten` setting (uniform; default off). When
   on, `Context.load_pipeline` (and `actions.resolve_targets`, for CLI ops) runs
   `flooradvise.tighten_pins` after the first resolve — for each unmet floor with a satisfying
   method, it floor-pins the provider to that method and RE-RESOLVES
   (`Resolver.resolve_resilient(extra_pins=…)`, which layers the pins on for that resolve only:
   your pins > floor pins > detected soft pins > default, routing-model §10). The monotonic step: it
   only ever moves a provider to a higher-versioned method. A provider YOU pinned is never
   floor-pinned (the `pin-floor` advisory says what that costs). **Replacement stays explicit even
   here** — a provider already INSTALLED via the too-old default method is skipped (it remains an
   advisory, not an auto-swap). For a resident provider below a consumer's floor, an install-ish
   plan gains an `upgrade` of it (`flooradvise.resident_upgrades_probed` in `actions.build_plan`;
   dependency order puts it before the consumer). Verified live: on a box with rust installed,
   auto-tighten yields `{}` and the advisory still fires; the tighten path is unit-tested for the
   fresh case (`{rust: tarball}`).

## ✅ 3c — the source build finds a floor-pinned toolchain (SHIPPED)

The advisory/tighten machinery selects the right toolchain, but a source build runs in a fresh
non-interactive shell, so a NON-native toolchain (rustup's cargo in `~/.cargo/bin`) wouldn't be
found. The `source` driver prepends the managed toolchains' bin dirs (`Driver.toolchain_bindirs`:
rustup's `~/.cargo/bin`, the go tarball's `$CONFIGSYS_SDK_DIR/go/bin` at user then system scope,
and `go install`'s GOBIN / `~/go/bin`), plus any recipe `build-path:`, to `$PATH` for the `build:`
command —
a native toolchain on the system PATH still works; a missing dir is harmlessly ignored. This turns
floor-driven *selection* into a working *build*: pin rust→rustup, and ripgrep-from-source's
`cargo build` finds the recent cargo.

Interactive use comes from shell glue, not the installer: the rustup binding uses
`--no-modify-path`, so it never edits your rc, and `rust` instead `suggests: rust-glue`, whose
shipped snippet puts `~/.cargo/bin` on your shells' PATH (docs/shell-glue.md). The recent-Go tarball
binding (bdf8a1b) follows the same pattern: `go-glue` puts the tarball's `bin/` and GOBIN on PATH.
