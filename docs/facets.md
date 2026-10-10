# Facets — detected environment atoms for `when:`

> **Status: REFERENCE** — the `facets:` section, facet detection (`routes.detect_facets`), facet atoms in `when:` (predicate.py), and `CONFIGSYS_FACET_*` overrides; maintained. Referenced from docs/config-format.md §The `when:` expression.

## The idea

The machine **context** a `when:` gates on is `⟨OS-lineage, OS-version, cpu, facets⟩`. A **facet**
is any other *detected* fact about the machine — GPU vendor, an installed tool's version, a kernel
feature — so a binding can be gated on hardware / environment, not just the OS. Like every `when:`,
a facet atom states **validity only** (does this method work here), never preference.

Facets generalize the `cpu:` atom: cpu is simply the categorical facet named `cpu`
(`predicate.Cpu` = `Categorical('cpu', …)`; the Context folds the machine cpu into
`facets_cat['cpu']`). Nothing here is CUDA-specific; the shipped customers are the GPU-variant
source builds in the configsys-opencv and configsys-blender plugins.

## Declaring facets — the `facets:` section

A top-level definitions section. Its probe **specs** are merged across the repo, plugin, primary and
included layers, **later layer wins per facet name** (the top config's `facets:` is different: it holds
*values*, see below):

```
// base routes.hu — shared, so any plugin can gate on gpu:nvidia / gpu:amd
facets: {
    gpu: { kind: categorical
           detect: 'lspci 2>/dev/null || { command -v nvidia-smi >/dev/null 2>&1 && echo NVIDIA; command -v rocminfo >/dev/null 2>&1 && echo "AMD/ATI"; }'
           match: { nvidia: "NVIDIA"  amd: "AMD/ATI" } }
}
// configsys-opencv plugin — adds an opencv-specific version facet
facets: {
    cuda: { kind: version  detect: "nvcc --version"  version-re: "release ([0-9]+[.0-9]*)" }
}
```

- `kind: categorical` → the facet's value is a SET of tags. `match:` maps a tag to a regex tested
  against the probe output (a machine can match several — two GPUs). Gated with `gpu:nvidia`.
- `kind: version` → the probe output yields ONE version via `version-re` (first capture group;
  default: the first dotted number). Gated with `cuda >= 12`, `cuda < 11.6`, etc.
- `detect:` is the probe — a shell command (15 s timeout). Any failure (command missing, no match)
  leaves the facet **absent** — a `when:` referencing it simply doesn't match, so a GPU binding
  degrades to the CPU one rather than erroring.

**Facets are command-carrying data.** A `detect:` probe runs on every resolve/startup with no user
action, so `routes.load` merges a plugin's (or the primary's) `facets:` only when that plugin's content
is trusted (`command_trust` → `plugins.command_source_trusted`); an untrusted plugin's facets are
dropped with a warning naming `configsys plugin trust`, and `plugin trust` accepts a data-only plugin
whose only executable data is a facet probe (`plugins.ships_executable_data`). The repo's always
merge. An `include:`d file carries its includer's trust: a file inside a synced plugin needs that
plugin trusted, while an include of your own (from your top config, or the repo's) is trusted as you.

Each spec entry must be a map (`{ kind: …  detect: …  match: … }`). A non-map entry in a plugin,
primary or include — typically a *value* like `gpu: nvidia` written in the wrong layer — is skipped
with a warning pointing at the top config, rather than crashing detection later. The top user
config never contributes *declarations*: its `facets:` is a value map (see values, below), so it never
triggers the untrusted-plugin warning; only a spec-shaped (map) entry there is flagged (define the
facet in a plugin) and ignored.

Only nvidia/amd are auto-detected for `gpu`: Intel iGPUs vs the compute-capable path are too
ambiguous to auto-pick, so an Intel variant (configsys-blender's `gpu:intel` oneAPI build) is reached
by declaring the value.

## Facet values — detected, declared, or forced

A facet's value comes from, in precedence order (`routes.detect_facets`):

1. **env** `CONFIGSYS_FACET_<name>` — `CONFIGSYS_FACET_gpu=nvidia`, `CONFIGSYS_FACET_cuda=12.4`
   (categorical: comma/space-separated tags). An empty value forces the facet absent
   (`CONFIGSYS_FACET_gpu=` disables GPU selection). This is how tests inject a machine shape without
   the hardware.
2. **config** — a `facets:` *value map* in the top user config (`~/.config/configsys/configsys.hu`),
   e.g. `facets: { cuda: 12 }` or `facets: { gpu: intel }`: the user's declared machine fact. Key for
   bootstrap — on a box without CUDA yet, it states the target. Read with `layers.read_setting`
   from that one file only (not includes, not the primary plugin), and only for facets some layer
   declares. A categorical facet also takes a list — `facets: { gpu: [ nvidia amd ] }` is both tags,
   the same as `gpu: "nvidia amd"` (`routes._facet_value` joins it); for a version facet a list
   takes its first item, and a map is no value (left unset).
3. **probe** — the declaration's `detect:`, classified per `kind`.

Probes are read-only and cached per process (keyed on the specs + overrides), so repeated Resolver
builds don't re-probe. `--pretend` still probes, so a dry run reflects reality. No `facets:`
declared anywhere → no probing at all.

## Gating on facets in `when:`

- Categorical: `gpu:nvidia`, `gpu:[nvidia, amd]` — exactly the `cpu:` syntax (`ns:value` /
  `ns:[…]`); matches when the machine's tag set intersects.
- Versioned: `cuda >= 12`, `cuda < 11.6` — the same `IDENT CMP VERSION` shape as a versioned OS
  atom. Disambiguation is at EVAL time (`predicate.Os.eval`): if the name isn't in this machine's OS
  lineage and a version facet of that name was detected, compare the facet's version; otherwise it's
  an OS atom (in-lineage, scale-bound). An absent facet → false. `routecheck` exempts names in the
  declared `facets:` from its unknown-OS-atom check. A bare facet name (no comparison) is never true.

Shipped use — configsys-opencv adds from-source `opencv` methods, each its own `via:`, beside base's
native package (which stays the default; you reach a build by pinning it, so hardware never triggers
a surprise compile):

```
opencv: { install: [
    { via: opencv-build   …  requires: [ cmake, cpp-toolchain, git ] }                   // CPU — valid everywhere
    { via: opencv-cuda11  …  when: "gpu:nvidia and cuda < 12"   requires: [ …, cuda-toolkit-11, cudnn-8, gcc-10 ] }
    { via: opencv-cuda12  …  when: "gpu:nvidia and cuda >= 12"  requires: [ …, cuda-toolkit-12, cudnn-9 ] }
    { via: opencv-hip     …  when: "gpu:amd"                    requires: [ …, rocm-hip ] }
] }
```

The `when:` clauses limit which methods are *offered* (and pinnable) on this machine — an
nvidia+CUDA-12 box lists `opencv-cuda12`, not `-cuda11`/`-hip`. `when:` tests stable facts only; the
exact CUDA/cuDNN versions ride versioned capabilities in `requires:` (base routes.hu's
`cuda-toolkit-11`/`-12` provide `{ cuda-toolkit: N }`; cuDNN 8 vs 9 is selected by its
`cuda-toolkit` constraint, not by a facet). configsys-blender gates its `blender-cuda`/`-optix`/
`-hip`/`-oneapi` methods on `gpu:nvidia`/`gpu:amd`/`gpu:intel` the same way.

Where several same-`via:` bindings differ only by facet, the general rules apply: a facet-gated
binding is strictly more specific than an ungated one, so the "broad default + narrow overrides"
idiom carries over unchanged.

## The decidability grid (routecheck / specificity)

`predicate.subset` decides specificity (and routecheck decides ambiguity) over a finite grid of
cells (`predicate._cells`): OS leaf × each categorical dimension × each version axis. `_collect`
discretizes what the predicates mention:

- A **categorical facet** (cpu included) adds one finite dimension: its mentioned tags + an "other"
  sentinel.
- A **version facet** adds its own version-sample axis (each boundary its atoms mention, probed
  just-below / at / just-above), keyed by facet name so `cuda`'s boundaries don't mix with the OS
  version axis. A versioned atom whose name is not an OS block is routed to a facet axis.

Two same-`via` bindings differing only by disjoint facet values (`gpu:nvidia` vs `gpu:amd`) are
disjoint → no ambiguity. With no facets mentioned the product collapses to the OS × cpu × OS-version
grid.

## Validation status

The mechanism is hardware-agnostic and unit-tested via env-injected facets. The probe regexes
(`lspci`/`nvidia-smi`/`rocminfo` for `gpu`, `nvcc --version` for `cuda`) still want validation on
real NVIDIA/AMD hardware.
