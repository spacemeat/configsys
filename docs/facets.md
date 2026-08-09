# Facets — detected environment atoms for `when:`

## The idea

The machine **context** that `when:` gates on is today `⟨OS-lineage, OS-version, cpu⟩`. A **facet**
extends it with any other *detected* fact about the machine — GPU vendor, an installed tool's
version, a kernel feature — so a binding can be gated on hardware / environment, not just the OS.

This generalizes the existing `cpu:` atom (a categorical, detected, non-OS dimension) to a
*declarable, open* set. The first customers are the OpenCV GPU build (gate the CUDA variant on an
NVIDIA GPU) and CUDA-version-dependent deps (cuDNN 8 vs 9), but nothing here is CUDA-specific.

## Declaring facets — the `facets:` section

A new top-level section (mergeable across layers like `os:`/`drivers:`; a plugin may add facets):

```
facets: {
    gpu:  { kind: categorical
            detect: "lspci"
            match: { nvidia: "NVIDIA"  amd: "AMD/ATI|Advanced Micro Devices.*\\[.*Radeon" } }
    cuda: { kind: version
            detect: "nvcc --version"
            version-re: "release ([0-9]+(?:\\.[0-9]+)*)" }
}
```

- `kind: categorical` → the facet's value is a SET of tags. `match:` maps a tag to a regex tested
  against the probe output (a machine can match several — two GPUs). Gated with `gpu:nvidia`.
- `kind: version` → the probe output yields ONE version via `version-re` (first capture group).
  Gated with `cuda >= 12`, `cuda < 11.6`, etc.
- `detect:` is the probe command. It runs **once** per invocation, read-only, and any failure
  (command missing, no match) leaves the facet **absent** — a `when:` referencing it simply doesn't
  match, so a GPU binding degrades to the CPU one rather than erroring.

## Gating on facets in `when:`

- Categorical: `gpu:nvidia`, `gpu:[nvidia, amd]` — mirrors `cpu:` exactly (`ns:value` / `ns:[…]`).
- Versioned: `cuda >= 12`, `cuda < 11.6` — same `IDENT CMP VERSION` shape as a versioned OS atom.
  Disambiguation is at EVAL time: if the name is a declared version-facet, compare its detected
  version; else it's an OS atom (in-lineage, scale-bound). Names don't collide in practice.

So OpenCV's bindings become real (no more commented templates):

```
opencv: { install: [
    { via: opencv-build  ... }                                      // CPU — broad, always valid
    { via: opencv-build  gpu:[nvidia]  when: "gpu:nvidia"  requires: [ …, cuda-toolkit, cudnn ] }
    { via: opencv-build  gpu:[hip]     when: "gpu:amd"     requires: [ …, rocm-hip ] }
] }
```

On an NVIDIA box the CUDA binding is valid AND more specific than the broad CPU one, so it wins —
automatically, the same way OS-specific bindings beat broad ones. AMD → HIP. Neither → CPU. Because
the source build stays opt-in (native apt is opencv's default; you pin `opencv → opencv-build` to
build from source), hardware only picks the *variant* once you've asked for a source build — no
surprise 30-minute compiles.

CUDA-version-dependent deps ride the version facet, e.g. cuDNN:

```
cudnn: { install: [
    { via: script  when: "debian and cuda >= 12"  install-cmd: 'apt-get install -y libcudnn9-dev-cuda-12 && ldconfig' … }
    { via: script  when: "debian and cuda < 12"    install-cmd: 'apt-get install -y libcudnn8-dev && ldconfig' … }
] }
```

## Detection, testing, `--pretend`

- Probes run once and cache. `--pretend` still probes (read-only) so a dry run reflects reality.
- Every facet is overridable by env: `CONFIGSYS_FACET_gpu=nvidia`, `CONFIGSYS_FACET_cuda=12.4`.
  This is how tests inject a machine shape without the hardware, and how a user can force/scope a
  build (`CONFIGSYS_FACET_gpu=` to disable GPU selection).
- Absent facet = the `when:` atom is false. GPU bindings therefore never mis-fire on a CPU box.

## The decidability grid (routecheck / specificity)

`predicate.subset` decides specificity (and routecheck decides ambiguity) over a finite grid of
`(OS-block × cpu × version-samples)` cells. Facets extend the grid the same way:

- A **categorical facet** adds one more finite dimension (its mentioned tags + an "other"
  sentinel) — a direct parallel to `cpu`.
- A **version facet** adds its own version-sample axis (the boundaries its atoms mention, each
  probed just-below / at / just-above) — a parallel to the OS version axis, but keyed by facet name
  (so `cuda`'s boundaries don't mix with the OS version's). The cascade carries the declared facet
  names so `_collect` routes each versioned atom's bounds to the right axis.

Two same-`via` bindings differing only by disjoint facet values (`gpu:nvidia` vs `gpu:amd`) are
disjoint → no ambiguity. A facet-gated binding is strictly more specific than one without → it wins
where it applies. So the existing "broad default + narrow overrides" idiom carries over unchanged.

## Scope / status

Staged: (1) predicate engine — categorical + version facet atoms in eval AND the grid, unit-tested
via env-injected facets; (2) the `facets:` section + probe detection wired into the Context; (3)
data — `gpu`/`cuda` facets in routes.hu, OpenCV real bindings, cuDNN cuda-gated. GPU/CUDA *detection*
(the probe regexes) needs validation on real NVIDIA/AMD hardware; the mechanism is hardware-agnostic
and testable without it.
