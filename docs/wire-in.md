# v2 wire-in — scoping

Status: **scoping** (no code yet). The v2 routing engine (`configsys/v2/`, `routes2.hu`) is
content-complete and proven graph-equivalent to the live `RouteResolver` across the current
OS set (414 tests; whole-port audit = 0 missing components, byte-identical closures on every
real path). This doc scopes plugging v2 into the running app **behind a flag**, validating it
against the podman integration suites, and flipping per context.

## 1. The seam

The app's resolve→execute pipeline is small and already cleanly separated:

```
app.Context.load_pipeline()  /  app._dispatch_op()
     └─ ctx.routes.resolve_names(names)        -> {key: ResolvedComponent}   ← THE SEAM
        apply_scope_default(units)             (mutates rc.fields['scope'])
        InstallState(...).inspect(units)       -> {key: ComponentState}
        expand_plan(base_plan, units)          (orders by rc.deps)
        for op,key,rc in plan:
            get_family(rc.family).install(rc)   (families read rc.family/name/fields/vars)
```

**Everything downstream of the resolver consumes a `{key: ResolvedComponent}` dict and nothing
else.** So the wire-in is: introduce a v2 code path that produces *the same dict shape*, gated
by a flag. Planning, install-state, the families, and the TUI are untouched.

`ResolvedComponent` (the contract the whole app depends on):

| field | who reads it | v2 source |
|-------|--------------|-----------|
| `.family` | `get_family()` dispatch | `unit.mechanism` |
| `.comp` | markers, alternatives link/ver defaults | `unit.component` |
| `.name` (=`fields['name'] or comp`) | apt/dnf/pacman/flatpak/appImage/… | `unit.package` |
| `.fields` | **every family**, for install details | `binding.details` (⚠ see §3) |
| `.vars` | `resolve_version` `$VERSION/$SDKVERSION` fallback | binding varmap (mostly empty now) |
| `.deps` | `expand_plan` / `dependency_order` | `unit.deps` |
| `.requested_as` | confirm summaries, TUI infoblock | `unit.requested_as` |
| `.key`, `.source` | dedup identity, diagnostics | `unit.key`, binding address |

## 2. The gift: mechanism ↔ family is 1:1

Every `Family.name` matches a v2 mechanism string exactly — by construction, since v2 mechanisms
were *named after the families* (that's why the equivalence unit keys line up):

```
apt dnf pacman aur tarball flatpak appImage dotfiles debian-font
cargo gcc gcc-toolset clang pip pipx
```

`via: native` resolves through `cascade.native(block)` to apt/dnf/pacman — also family names.
`via: parts` produces **no unit** (pure aggregator), so it never reaches a family. So
`get_family(unit.mechanism)` needs **zero translation**. The dispatch layer is free.

## 3. The real work: FIELD PARITY (what the equivalence harness never checked)

The equivalence harness compares `(mechanism, component, package)` tuples and closure key sets.
It says the **dependency graph** is right. It says **nothing** about whether each unit carries
the fields its family needs to actually *install*. And `routes2.hu` was authored to satisfy the
*resolver* — several bindings dropped or restructured install-execution fields. Verified deltas
(old `rc.fields` vs v2 `binding.details`):

| unit | family reads | OLD fields | V2 details | gap |
|------|--------------|-----------|-----------|-----|
| neovim, arduino | url, path, version, name | ✓ | ✓ | **none** (scope stamped by app) |
| vulkan-sdk | version, url, installDir | ✓ | ✓ | **none** |
| tree-sitter-cli, ripgrep, btop, steam… | name, version, foreign-arch | ✓ | ✓ | **none** |
| **fastfetch** (apt deb-mode) | `deb`, `version:{github,asset-glob}`, name | `deb:true`, `version:{github,asset}` | `deb-source:"github:…"`, `asset:{x86_64,aarch64}` | restructured: no `deb`, no `version`, cpu-keyed `asset` |
| **gcc-13/14/15**, clang-* | `slaves`, packages, ppa, (link/ver derived) | `slaves:[g++]`, packages, ppa | packages, ppa, `requires` | **missing `slaves`** (→ /usr/bin/g++ alt not registered); stray `requires` |
| **mononoki-nerd** (debian-font) | version, url | version, `url:"…$VERSION…"` | version only | **missing `url`** (may still work via github asset discovery — verify) |
| **chrome** (flatpak) | `name`(app id), `hub` | `hub:flathub`, `name` | `app:` | `app`→`name` needed; `hub` absent (family default?) |

Two orthogonal kinds of gap:
- **Mechanical (adapter fills):** `name ← unit.package`; strip resolver-only keys (`requires`,
  `parts`); pass `version/url/path/installDir/ppa/foreign-arch/packages` straight through.
- **Semantic (data or family must change):** fastfetch deb-mode reshape, gcc `slaves`, font
  `url`, flatpak `app`/`hub`. These are places v2's data is *cleaner* (cpu-keyed asset, `app:`)
  but the families don't speak it yet.

### Two ways to close the semantic gaps
- **(A) Adapter normalizes** v2 details → the old fields shape. Families untouched; fastest flip.
  Cost: a permanent-ish translation layer that enshrines old field names as the target.
- **(B) Enrich `routes2.hu` + teach families v2 shapes** (add `slaves`/font-`url` back; make apt
  read `deb-source`+cpu-`asset`, flatpak read `app`). Ends with families speaking v2 natively,
  no adapter. More work, spread across families.

**Recommendation: A-as-bridge, then B.** Ship the adapter to get a *validated* flip quickly,
gated by the field-parity harness below; then migrate families to v2 shapes one at a time and
retire each adapter special-case. Lets us flip early and de-risk incrementally.

## 4. New gate: a field-parity harness

Mirror the equivalence harness, but at the field level. For each ported unit × context, build the
old `ResolvedComponent` and the v2-adapted one, and assert the **fields each family actually reads**
match (after adapter normalization). Concretely, per family declare its "install-relevant field
set" (apt: name, deb, version, foreign-arch, repo-component; _alt: link, version, slaves, packages,
ppa; appImage: url, path, version, name; …) and diff only those keys. This is what makes "the flip
is safe" a *proof*, not a hope — and it's the harness that would have caught fastfetch/gcc today.

## 5. Adapter shape (proposed)

- Have `v2/resolve.py` attach the selected `binding` (and varmap) to each `Unit` as it's created
  (main unit, inline-dotfile unit, dep-added units), so the adapter has the details without
  re-running `select_binding`. `parts` still emits no unit.
- New `configsys/v2/adapt.py`: `to_resolved_components(units, names, cascade) -> ({key: ResolvedComponent}, roots)`
  — one `ResolvedComponent` per `Unit`, `fields` = normalized `binding.details`, `name` from
  `unit.package`, `vars` from the varmap. Roots = the requested names that produced ≥1 unit.
- New `configsys/v2/normalize.py` (or inline): the per-family field translations from §3.

## 6. Flag + rollout

- Selection: `CONFIGSYS_RESOLVER=v2` env (matches the existing `CONFIGSYS_*` override style) and/or
  a `routing: v2` key in the per-machine `configsys.hu`. Default stays `v1` until flipped.
- `Context.routes` (or a new `Context.resolve(names)`) branches on the flag: v1 →
  `RouteResolver.resolve_names`; v2 → `routes2.load` + `resolve` + `adapt.to_resolved_components`.
  Both return the identical `{key: ResolvedComponent}` dict, so `load_pipeline`/`_dispatch_op` don't
  change.
- Validate: run the podman integration suites under `CONFIGSYS_RESOLVER=v2` on each OS image; the
  field-parity harness gates unit-level correctness, the integration suites gate real installs.
- Flip per context (Debian family first — most units, simplest fields; toolchains/EL last).

## 7. Notes / smaller items

- `apply_scope_default` mutates `rc.fields['scope']` on scope-honoring families — works unchanged on
  adapted RCs (it operates on the dict, source-agnostic). v2 appImage/tarball don't carry `scope` in
  details (old didn't either; the app stamps it). ✓
- `--pretend`, `Runner`, `Ledger`, `versions.discover` (github/pypi/aur/static) are all resolver-agnostic
  — reused as-is.
- The two **intentional graph divergences** (bare-`gcc`-on-Debian → alias dotfile; `epel-release`
  direct-on-Fedora → no binding) are on dead paths and don't affect the flip.
- `install EXECUTION` is entirely unchanged — v2 decides *what* + *deps*; the existing families still
  *do* the installs. This wire-in is purely resolver-substitution + field marshalling.
