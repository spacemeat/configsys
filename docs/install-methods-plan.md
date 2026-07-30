# Install-method selection — plan

Fleshes out `docs/many-installs-including-src.md`: let a component expose *multiple*
install methods per context, let the user **see and pick** one, store that choice as a pin
(local or portable), and (later) make build-from-source a first-class declarative driver.

Status: **SHIPPED.** The multi-method engine (candidate bindings, the validity-only `when:`
invariant, `driver-preference` + per-binding `prefer:`, the same-driver-only ambiguity gate),
additive component merge, per-key pin merge with `pin set`/`unset`/`promote`, the TUI method
picker (`m`), and the declarative `source` driver are all in the tree. This doc is kept for the
design rationale and the locked decisions; the phase list below is history.

## The core shift

Today the routing model is **single-winner and sound**: for any machine context the matching
bindings must resolve to *exactly one*. `routecheck.check_component` (routecheck.py:22-30)
*rejects at load time* any two bindings that overlap but are incomparable (`AmbiguityError`
with a witness). So multiple methods per OS aren't merely unsupported — they're forbidden as a
soundness violation.

The shift: **keep the default deterministic; widen the alternatives.**

- A context's `when:`-matching bindings become a **candidate set** (the methods available here).
- Exactly one is still the **default**, chosen deterministically (see tiebreak below).
- A user **pin** selects a non-default candidate. This is nearly what a binding-pin already
  does (`select_binding`, resolve.py:65-80: filter to `b.via == pin`, still honor `when:`);
  today there is simply never more than one candidate to choose between.

An un-pinned machine still resolves one way, reproducibly — the routing golden gate
(`test/routing_golden.json`) stays green because today's data has zero incomparable-overlapping
pairs and the default must reproduce current picks exactly.

## Invariant: `when:` is validity only (no double duty)

Today `when:` conflates two independent questions, and that conflation is the thing to kill:

1. **Validity** — does this method *work* in this context? (steam native needs i386 foreign-arch;
   firefox is `MozillaFirefox` on zypper). Honest facts about where a binding applies.
2. **Disambiguation** — which single method do we pick? Historically authors *narrowed* `when:`
   below true validity purely to dodge the single-winner ambiguity error — a lie by omission:
   reading `routes.hu` you cannot tell that chrome-flatpak is perfectly valid on Ubuntu when the
   clause was tightened only to force native to win.

**Rule: `when:` expresses validity *only*. Disambiguation lives in a separate, dedicated
channel.** This makes `routes.hu` honest, queryable data — a context's candidate set is the true
set of available methods — and no author is ever forced to narrow a validity-`when:` to make
resolution decide.

Holding this requires the disambiguation channel to be **total**: it must always yield a unique
default so a tie can never push an author back to `when:`. The default is chosen by this ordered,
total preorder over the candidate set (candidates = the `when:`-valid bindings):

1. **most-specific** among *comparable* candidates (predicate ⊆) — legitimate *specialization*
   (e.g. `native when:rhel requires:epel` ⊂ `native`), not double-duty; keep it;
2. **driver-preference order** — a global list, optionally overridden **per OS block** (so
   context-dependent preference, e.g. flatpak > native on `fedora_atomic`, lives in the `os:`
   data as its own inspectable field, *not* smuggled into a binding's `when:`);
3. **per-binding `prefer:`** — a local rank override for the odd component.

If the preorder still ties, it is a **load-time error whose message names the preference channel
(add `driver-preference`/`prefer:`) — never `when:`.** So the *only* way to resolve a tie is to
add honest preference data; narrowing validity is never the fix. `routecheck`'s job flips from
"overlap+incomparable ⇒ error (which forced `when:` narrowing)" to "compute candidates from
validity-`when:`; if preference doesn't yield a unique default, error pointing at preference."

Payoff (the reason this matters beyond aesthetics): routes become **introspectable data for the
user**. `configsys where <comp>` / a routes view can show, per context, *all* candidate methods,
which is the default, and *which rule decided it* — impossible while `when:` was doing double duty.

## Locked decisions

1. **Default = a total preorder, in a channel separate from `when:`** (see the *Invariant*
   above). Order: most-specific among comparable candidates → global `driver-preference` (list,
   overridable per OS block) → per-binding `prefer:`. A remaining tie is a load-time error that
   names the preference channel — **never** `when:`. `when:` is validity only; the candidate set
   is honest data. We never silently guess.

2. **Components merge ADDITIVELY across layers** (was: replace-per-name). Union the bindings as
   encountered. This replaces `+self`/`add-bindings:` — no amend ceremony. Forced definitions:
   - **Binding identity = `(via, when)`.** A higher-layer binding with the same identity
     **overrides** the lower one (recovers "correct the base"; subsumes some `component-names:` uses).
   - **Targeted remove** marker (`{ via: X  when: Y  drop }`) retracts an inherited binding.
   - **Whole-component `{}`** still drops the entire component (unchanged sentinel).
   `Binding` already retains raw `when` (routes.py:18), so the identity key is available.

3. **Pin storage: existing `pins:` at two machine-roles, per-key merge.**
   - Local (per-machine, TUI-written) → top user config `pins:` (`~/.config/configsys/configsys.hu`).
   - Portable → the **primary plugin**'s `pins:` (primary is already a machine-role allowed to
     set pins).
   - **`Config.pins()` becomes a per-key merge** across `_MACHINE_ROLES` (today it is
     `merge_scalar` = whole-block last-writer-wins, layers.py:209 — which would make a single
     local pin *wipe* all portable pins). No new file, no new layer role.
   - `configsys pin promote <comp>` moves a key from the top config up into the primary plugin.

4. **Method-picker first; declarative source driver later.** Phases 0-3 ship "see / pick / pin /
   promote" among methods that already exist per-OS. The `via: source` driver is Phase 4, a clean
   follow-on.

Rejected / deferred: a separate pins file (needless new layer); component override-*properties*
for method selection (the pin already *is* the light override — CLAUDE.md); side-by-side installs
(the `driver\comp` unit key can represent two installs, but "both on PATH, no conflict" is
per-component-feasible and unsafe to generalize — later explicit opt-in, must not block the picker).

## Phases

Each phase is independently shippable and golden-gated.

### Phase 0 — enabling, invisible
- Extract a `set_section(path, section, text)` primitive from `plugins.set_declared`
  (plugins.py:395) so the *only* new "TUI writes config" surface is one audited span-replace.
- Change `Config.pins()` (config.py:108) from `merge_scalar` to a per-key merge across
  `_MACHINE_ROLES`. Fixes the pin-wipe bug. Safe: zero populated `pins:` blocks in the tree today.

### Phase 1 — multi-method engine
- `resolve.py`: add `candidate_bindings(comp, ctx)` (all `when:`-valid bindings = the honest
  candidate set); default selection = the total preorder (most-specific → `driver-preference`
  → `prefer:`), returning the deciding rule alongside the winner (for introspection).
- `routecheck.py`: flip the ambiguity gate (check_component:22-30) — compute candidates from
  validity-`when:`; error only when the preference preorder yields no unique default, and word the
  error to point at `driver-preference`/`prefer:`, **never** at narrowing `when:`.
- Add `driver-preference` as data: a global list (a machine setting) with optional per-OS-block
  override in the `os:` layer.
- Introspection: `configsys where <comp>` shows all candidates, the default, and the deciding
  rule (validates the *Invariant* holds — that routes read as data).
- Golden gate must reproduce today's picks exactly.

### Phase 2 — additive component merge
- `routes.py:143` (`merge_named` for components): union bindings across layers with `(via, when)`
  override + the `drop` marker; keep `{}` = whole-component removal.
- routecheck runs the ambiguity/tiebreak gate on the **unioned** set.
- Now base/plugins/user *add* alternatives (source, flatpak, appImage) without redefining.

### Phase 3 — TUI picker + pins
- Per component: show the current `via:` and a picker of `candidate_bindings` (with each method's
  resolved version where cheap). The TUI currently shows only the *resolved concrete driver* in
  the DRIVER column — the picker is new UI.
- Selecting a non-default method **stages a pin-write** to the top config `pins:` via
  `set_section`, behind an explicit confirm (this is the first user-intent config write from the
  TUI beyond the lock ledger `state.hu` — treat it like `X` execute).
- Show pin **provenance** (local vs primary).
- `configsys pin promote <comp>` (top config → primary plugin, then remind to commit/push — same
  as every plugin-repo workflow) and optional `pin localize` (primary → local one-off; per-key
  merge already lets a local pin override without demoting, so this is convenience only).

### Phase 4 — declarative source driver
- A `source` driver = the `script` driver's declarative lifecycle (install-cmd / version-cmd /
  version-re / uninstall-cmd / upgrade-cmd / set-version-cmd / location — all route data, no
  per-app Python) **plus** a fetch/checkout step, a prefix/scope model, and an artifacts/alias
  step. Version pinning = checkout a tag (tarball.py's version-templated-reinstall is the analog);
  discovery reuses the `version:` spec / `version-cmd`+`version-re`.
- Base offers `via: source` alternatives (added via the additive merge) for the *simple* majority
  (`configure && make install` into a prefix, alias into bash.d). The gnarly builds
  (blender-build's GPU-SDK resolution, EULA, `install_linux_packages.py`) **stay plugin drivers**.
- A "gentoo-ish" source *plugin layer* can add `via: source` across many components at once —
  which is exactly what the additive merge (Phase 2) makes tractable.

## Risks & invariants

- **Determinism of the default is load-bearing.** Alternatives may exist; the default must not
  become nondeterministic. The tiebreak must always decide or error — never guess.
- **`when:` cleanup is data work, not engine work — and it's the larger cost.** With the engine
  invariant in place (validity-only `when:`, total preference channel), the cleanup is *widening*
  historic narrowings back to true validity so alternatives surface as candidates — the engine
  never *forces* a narrowing, so this is pure data curation, not a correctness risk. It must not
  delete genuine *validity* `when:`s (steam native = Pop i386 foreign-arch; firefox
  `MozillaFirefox` name on zypper): those are facts, not opinions. Curate per-component,
  golden-gated; a `namesweep`-style audit can enumerate "which components could gain a
  flatpak/appImage/source alternative." Until a component is curated it keeps its current single
  candidate and resolves exactly as today.
- **Golden gate** (`test/routing_golden.json`) fronts every phase. Base `routes.hu` is one layer,
  so the additive merge is a no-op for the frozen snapshot; cross-layer merges (plugins/user) are
  where behavior changes.

## Highest-value slice

Phases **0 + 1 + 3 without the source driver**: see and pick among methods that already exist,
stored as portable-or-local pins. Phase 4 is fully separable.
