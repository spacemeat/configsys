# Routing model + TUI overhaul — plan

Status: **decisions locked 2026-08-11.** Planning only — no code yet. Derived from a six-facet
parallel audit (control taxonomy, resolution semantics, TUI coverage, install-situation catalogue,
evolution cruft, forward design). Verdict: **targeted overhaul, not a rewrite.**

## Mandate

Clarity; reduce complexity in the routing model AND the TUI; TUI expressibility; maximize control —
especially options and **concurrent component residency**.

The audit found the model has a sound spine and one overgrown limb:
- **Sound (leave the semantics):** the *validity* layer (`when:` DSL, `using:` lineage, scale-roots,
  facets, OS-block `provides:`) and the *dependency* layer (provides/requires/suggests, env-provides,
  bootstrap guard). These are what make `configsys where` crisp.
- **Overgrown:** default-steering — "which valid method/provider wins?" is answered by **seven**
  overlapping mechanisms (cross-via `when:` specificity, `prefer:`, global `driver-preference`, per-OS
  `driver-preference` [0 uses], driver-level `candidate-only`, binding-level `candidate-only`,
  `opt-in`). Two exist only to patch a third; one is vestigial; the documented order contradicts code.
- **Two real expressiveness gaps:** the *variant axis* (build flavors must mint a code-backed via;
  version lines fork the component name) and *concurrent residency* (per-consumer provider choice).
  They are the same missing concept: *one identity, several resident versions* — bounded by what each
  driver can actually co-host.

## Decisions locked

1. **Concurrent residency = version-scoped providers**, NOT full variant-aware identity.
2. **Control consolidation = one `standing` concept** (`when:`-scopable, multi-scope, layered)
   replacing `prefer:` + both `candidate-only`s + `opt-in`; `driver-preference` becomes `standing`
   declared at via-scope in the machine layer.
3. **Precedence = specificity-first, layer as tie-breaker.** Narrow beats broad; owner beats author
   at equal scope; a pin is absolute; detected-installed is preferred over defaults.
4. **Detection-first**, delivered through the existing `extra_pins` second-pass channel (the one
   `auto-tighten` already uses); golden-gated to byte-identical when nothing is detected.
5. **TUI = per-row "where" detail + a single unified "choices" picker** (fold `m`/`P`).
6. **No steamroll/`strict` escape hatch for now** — "be specific to override specific." Keeps the knob
   count low; can be layered on later if we find we lack the control.

## Non-goals / deferred

- Full variant-aware unit identity (`driver\comp\variant`) and same-component-same-driver
  multi-version instances (e.g. two `nvim` tarballs as one component). Deferred until a concrete case
  demands it; name-forking covers the rare need, and the driver-concurrency reality (below) mostly
  defeats the alternative anyway.
- A per-driver concurrency sublanguage — unneeded under version-scoped providers.

## Why version-scoped providers (the driver-concurrency argument)

Concurrency is a property of **(driver × how upstream packages it)**, not something the model can
grant:

| driver class | two versions co-resident? | mechanism |
|---|---|---|
| native (apt/dnf/pacman/…) | only if the distro ships them as **distinct packages** (gcc-10 & gcc-11; python3.10 & 3.11; cuda-toolkit-11-8 & -12-6) | distinct package names |
| flatpak / snap | generally **no** (one per app-id/channel) | — |
| tarball / appImage / source / build / font | **yes** | distinct install dirs (`locations:`) |
| toolchain-managed (update-alternatives gcc, pyenv) | many installed, **one active** | active-switch |
| cargo / pipx / npm-global | typically **no** (one "current") | — |

**Version-scoped providers respects this for free** — each resident stays its own component/unit, a
normal single-version install, so no driver is ever asked to hold two versions of one thing. **Full
variant-aware identity fights it** — it must encode per-driver concurrency, refuse illegal
co-residency, destabilize the frozen `driver\comp` unit key + ledger + golden + every driver op — and
*even then* the native case still needs a distinct package name per variant, so it doesn't eliminate
the name-fork it set out to remove.

## Target model

### Residency: version-scoped providers

- The capability inventory becomes **multi-resident**: `cap → [residents]`, each resident carrying
  its provided version (from the existing `prov_versions`).
- `provides: { cuda-toolkit: 12 }` declares a versioned capability.
- `requires: { cuda-toolkit: ">=12" }` is a **validity filter** on residents (a constraint, not a
  preference). Unconstrained `requires: cuda-toolkit` is eligible for any resident.
- Residents remain distinct components → each is a normal single-version install.
- `opt-in` is no longer needed to keep a generic capability unambiguous (constraints + standing
  disambiguate); it folds into `standing: never-auto` where still wanted (e.g. the `gcompat` glibc
  shim).

Before → after (the cuda case):
```
# today: name-fork + opt-in + by-name require
cuda-toolkit-11: { opt-in: true  provides: cuda-toolkit  install: [{ via: native  name: nvidia-cuda-toolkit }] }
cuda-toolkit-12: {               provides: cuda-toolkit  install: [{ via: script  …cuda-toolkit-12-6… }] }
opencv: {…  via: opencv-cuda12  requires: [ cuda-toolkit-12 ] }     # by name (bypasses the capability)

# target: versioned provides + constraint
cuda-toolkit-11: { provides: { cuda-toolkit: 11 }  install: [{ via: native  name: nvidia-cuda-toolkit }] }
cuda-toolkit-12: { provides: { cuda-toolkit: 12 }  install: [{ via: script  …cuda-toolkit-12-6… }] }
opencv: {…  via: opencv-cuda12  requires: [ { cuda-toolkit: ">=12" } ] }
blender:{…  via: blender-optix  requires: [ cuda-toolkit ] }        # any resident → detected/default
```

**"Installed -11 vs a consumer's `>=12`":** the constraint is *validity* — `-11` is simply ineligible
for that consumer (never considered), while it stays eligible + detected for unconstrained consumers.
Constraint (validity) and detection (preference among the valid) never collide.

### Control: one `standing`

Replaces `prefer:` (positive rank), driver- and binding-level `candidate-only` (never-auto), and
`opt-in` (never-auto for providers). `standing` is:
- settable at **scopes**: binding ▸ component ▸ via/driver ▸ global;
- **`when:`-scopable** (a binding can carry different standing per context — this is what lets one
  construct express both "narrow-validity/low-preference" and "broad-validity/preferred-here", the two
  cases that today force `candidate-only` and the unused per-OS override);
- **layered** (repo author < machine owner).
- `driver-preference` = `standing` declared at via-scope in the machine layer.

```
# "valid via snap everywhere, but the default only ON ubuntu"
snap-binding: { via: snap  standing: [ { when: "ubuntu"  rank: normal }  { rank: never-auto } ] }
```

### Precedence — one rule

For a given need, among candidates that pass the **validity gate** (`when:` holds; version
constraints filter eligible residents/bindings):

1. **Explicit choice** — a `choices:`/`pins:` entry (or owner-layer `standing`) at the most-specific
   matching scope; owner layer beats author layer at equal scope. A pin = max scope + top layer.
2. **Detected-installed** — a candidate matching an on-disk install wins the auto-slot over defaults
   (soft: skipped if it somehow became invalid).
3. **Standing** — most-specific scope wins; `never-auto` excluded unless it's the sole candidate.
4. **Validity-order default** — first by via-preference order.
5. Residual tie → error naming the standing/preference channel — **never `when:`**.

`when:` never contributes preference. This kills cross-via specificity-as-preference (the doctrine
violation, the bug source, and the reason `candidate-only` was invented). Two kinds of "specificity"
were tangled: **directive-scope** specificity (a per-binding standing is a narrower *preference
statement* than a global one — legitimate, should win) vs **validity** specificity (`when:` narrowness
leaking into preference — the bug). We keep the first, kill the second.

*Fine-point to finalize in Phase 1:* the exact rank of detected-installed vs a per-component **author**
standing. Working default: explicit-owner > detected > author-default > via-order.

## Phased plan

Each phase is independently valuable and golden-gated. Ordering: de-risk with free wins, then the two
mechanisms that change *what resolves* (small, individually gate-able), then the consolidation
(build-beside/prove-equivalent/flip — the playbook this project already ran for v1→v2), then the TUI
which depends on the earlier phases' provenance.

### Phase 0 — Free wins & truth (no design; land first)
- **D3 (bug):** `routecheck` binding-level requires must go through `cap_names` (today `_as_list` →
  `TypeError` on a versioned entry). Latent — component-level is already safe.
- **D1 (bug):** a provider-pin must beat inventory-reuse — consult the pin before the reuse
  short-circuit (`resolve.py:487` vs `:495`); a pin is never silently ignored. (May move the golden
  where a pin was being dropped — verify.)
- **D2 (doc):** correct §8a + CLAUDE.md — a narrow `prefer:`/standing legitimately outranks a broad
  `driver-preference`; the code is right, the docs are wrong.
- **Pins namespace:** validate binding-pin vs provider-pin at load (a name that is both a component
  and a required capability collides) — error clearly, or namespace.
- **Explicit-vs-explicit capability claim** (`resolve.py:453` `setdefault`): surface a warning instead
  of silent profile-order dependence.
- **Variant-detection false negative** (blender-optix "not installed"): diagnose the real build dir
  (marker vs path vs kernel probe) and fix.
- **Dead code:** `resolve_one`, `Unit.as_tuple`, `ResolvedComponent.vars` (+ the `driver.py` fallback
  + test scaffolding), `sug_versions`, `Component._KEYS`, the empty `configsys/v2/` dir;
  `merge_name_overrides`/`merge_version_floors` → one `merge_nested`; `config.py:53-58` should reuse
  `collect_named`.
- **`adapt.py`:** give `Unit` the `comp`/`fields` property names (or construct `ResolvedComponent`
  directly) and delete the double-object; strip the "v2" ghost from docstrings.
- **Doc drifts:** `~/configsys.hu` → `~/.config/configsys/configsys.hu`; guarded-`not` (enforce or
  delete the doctrine); §13 "open questions" (settled); `Layer` role list.

### Phase 1 — Detection tier
- Build `detected = {component: (via, version)}` from the batched enumeration `detect_coexisting`
  already runs (cached off the refresh stamp; no per-candidate probing).
- Inject as a **soft** precedence tier in `_select`/`_satisfy` via the `extra_pins` second-pass shape,
  merged **below** user pins. Soft = skip-if-invalid, not the hard pin-realizability error.
- Record provenance in the existing `reason` string ("default: detected installed via X") for `where`
  + the TUI.
- Probe only where it can change a choice (>1 valid method / >1 viable provider) to keep inspect flat.
- **Golden:** empty detection ⇒ byte-identical.
- Delivers: no more "pushed toward -12 when -11 is already installed."

### Phase 2 — Version-scoped providers
- Inventory → multi-resident; `_satisfy` filters residents by constraint (from `prov_versions`).
- Migrate `cuda-toolkit-11/-12` to `provides: { cuda-toolkit: N }`; move consumers from by-name to
  constraints (by-name stays as sugar = "= that identity"). Same for other versioned lines as they
  come up.
- Retire `opt-in` on versioned siblings (still expressible as `standing: never-auto` until Phase 3).
- `routecheck`: lint unsatisfiable constraint combinations.
- **Golden:** regen for the intended cuda/gcc/clang changes; verify only those move.

### Phase 3 — `standing` consolidation + `choices:`
- Introduce `standing`; translate existing `prefer:`/`candidate-only`/`opt-in` into it and **prove
  byte-equivalent**, then flip; delete the old flags and the `candidate_only` frozenset threaded
  through the load→Resolver→resolve signatures.
- `driver-preference` → via-scope `standing` in the machine layer.
- `choices:` config section unifying binding-choice / provider-choice / constraint; `pins:` kept as an
  alias; this resolves the pin-namespace collision structurally.
- Rewrite the model docs to the single precedence story (validity → standing → pin, with detection).
- **Golden:** stable through the flip (semantics preserved).

### Phase 4 — TUI: per-row "where" detail + unified picker
- One per-row detail overlay (reuse `cmd_where` logic): capability edges
  (requires/provides/suggests/parts, visually distinct), candidate methods + why-invalid, standing/pin
  state **with unpin**, floors, detected-state; machine facets shown in the header.
- Fold `m`/`P` into a single "choices" picker over the row's choice-points (method | provider |
  constraint), each row showing alternatives + the deciding tier + detected-state.
- `also present:` becomes an **adoptable** row, not a passive footnote.
- No golden impact.

### Phase 5 — deferred
Variant-aware identity / same-driver multi-version instances, only on a concrete case.

## Risks & mitigations
- **Phase 3 breadth** (resolve/_select, config pins, `pin promote`, both pickers, where/check): the
  build-beside + golden gate is the mitigation — the exact v1→v2 playbook.
- **Detection cost:** gate on the existing `detect-coexisting` setting; probe only where it can change
  a choice.
- **Constraint matching** erodes the "no version math on capabilities" boundary (already crossed by
  floors, floors-only) — document the change honestly rather than let it drift.

## Evidence appendix (audit, file:line)

- **Seven default-steering mechanisms:** specificity `resolve.py:146-153,217-219`; `prefer:`
  `resolve.py:119-124,176-177`; global/per-OS `driver-preference` `resolve.py:136-143`, config
  `config.py:197-202`; driver `candidate-only` `routes.py:239-241`; binding `candidate-only`
  `resolve.py:127-133`; `opt-in` `routes.py:106-110`, `resolve.py:400-402,501-508`. Per-OS override:
  **0 uses in routes.hu**.
- **D1 reuse-before-pin:** `resolve.py:487` (reuse) precedes `:495` (pin). Contradicts routing-model
  §10 ("pin > reuse", "never silently ignores a pin").
- **D2 prefer > driver-preference:** `resolve.py:177` sorts `-_prefer_rank` first; docs §8a say the
  reverse; shipped data (mitmproxy `routes.hu:601`, k3s `:1209`) depends on the code order.
- **D3 routecheck crash:** `routecheck.py:152` iterates `_as_list(b.details.get('requires'))`; a
  versioned entry yields a dict → `TypeError: unhashable`.
- **Multi-resident single-provider invariant:** `inventory` `resolve.py:396-397`, `setdefault`
  `:452-453`, `_satisfy` `:486-516`; `extra_pins` second pass `routes.py:372-385` (auto-tighten
  `app.py:419-427`).
- **TUI output-vs-input split:** dep units bucketed by `requested_as` `menu.py:143-154`, rendered as
  depth-2 children `menu.py:179-185`; the two pickers `_pick_method` `menu.py:~948` / `_pick_provider`
  `menu.py:~1029`; `cmd_where` (the detail source) `app.py:856-901`.
</content>
</invoke>
