# Driver resilience plan — isolate, diagnose, and self-heal external stumbles

Status: **Phases 0–2 + the dnf half of Phase 4 BUILT** (commits dd04d9b, eacaac9, 90dd3a8,
a41fe9b, 8b30745). Phase 3 (manifest) is deliberately DEFERRED per Open-Q2's accepted default
(introduce it only when reconciliation needs it). The rest of Phase 4 (flatpak/tarball/source
transactional guards + pre-flight) is not built — the P0 taxonomy already classifies their
failures; the transactional rollback is done for apt+dnf, the two with a real poison-pill history.

Captures the design agreed after a real Jenkins repo-key rotation broke `configsys refresh` on a
live machine (see the `jenkins` route comment in `routes.hu` and commit `edfd5f3`). Three themes,
one shared substrate, phased so the highest-pain / lowest-risk work lands first.

## What shipped

- **P0 (`configsys/failures.py`, `Result.classified()`):** a category + remediation taxonomy;
  reportgen prints "Likely cause"; the TUI fail-detail appends "[category] — hint".
- **P1 (`app.diagnose_index_failure`):** the native index refresh is captured + classified;
  names the culprit source file and, if ours, the owning component. Diagnose-only.
- **P2 (`app._offer_rekey`, apt `_commit_source`):** refresh PROMPTS to re-fetch a rotated key
  for a configsys-managed source and retries (self-heals an existing install); the apt driver
  validate-then-commits a vendor source and rolls back a newly-written one that won't verify.
- **P4-dnf (dnf `_commit_repo`):** same validate-then-commit/rollback for a newly-written
  `.repo` (reachability/repomd; GPG-at-install stays dnf's own later check).

## Motivating incident

Jenkins rotated the key signing its apt/dnf repos but didn't republish it at the keyfile URL
the route fetched. That produced three separate failures, each a general weakness:

1. **A foreign source bricked a shared step.** One bad `.list` made `apt-get update` (the
   index refresh, `app.py:~898`) fail wholesale, dumping a raw `NO_PUBKEY` / `not signed`
   error with no hint at *which* source, *which* component wrote it, or *what to do*.
2. **A rotated key never re-fetched.** The apt driver fetches the keyring only when the file
   is ABSENT (`[ -f {kp} ] || sudo curl … {ku}`, `apt.py:83`; same shape for source files at
   `:90/:104/:111`, dnf key import at `dnf.py:84`, flatpak `remote-add --if-not-exists`). Once
   a stale keyring is on disk, no `refresh` or reinstall ever corrects it.
3. **A half-valid install left a poison pill.** The source `.list` was written even though the
   key never verified the repo — so a *failed* setup persisted and broke every later apt op.

The batch **install** loop is already resilient (planning.py continues past a failed unit and
collects outcomes) — so the gaps are specifically around (a) shared prerequisite steps, (b)
persisted system side effects, and (c) opaque, uncategorised failures.

---

## Theme 1 — Isolate & diagnose broken third-party sources

**Goal:** a failing source (ours or foreign) yields a *named culprit + cause + fix*, never a
raw dump, and never silently poisons later operations.

- **Capture, don't stream, the index refresh.** `cmd_refresh`'s native step runs
  `capture=False`; switch to captured output so we can parse it. (Keep streaming as a `-v`
  fallback.)
- **Classify against a signature table.** apt `NO_PUBKEY <id>` / `is not signed` / `Failed to
  fetch`; dnf `repomd.xml … GPG … NOKEY` / `Cannot download`; zypper/apk equivalents. Each maps
  to a **failure category** (see Theme 3) + a remediation template.
- **Attribute to a file and (if ours) a component.** Map the failing repo URL → the owning
  `/etc/apt/sources.list.d/*.list` or `*.repo` → and, when configsys wrote it (its
  `source-path` matches a route binding), the owning component. Foreign sources are named by
  file only, explicitly flagged "not managed by configsys."
- **Surface, then optionally remediate.** Default is **diagnose-only** (print culprit + cause +
  suggested command). For a configsys-owned source we may *offer* (prompt, never silent):
  re-fetch a rotated key (Theme 2), or remove a stale source whose component is no longer wanted
  (tie-in to the `!uninstall` / orphans model). **Never touch a foreign source.**

Note: `apt-get update` already refreshes the *good* repos and only errors on the bad one, so
the index isn't left wholly stale — the harm is the noise + the unverifiable repo at install
time. So Theme 1 is diagnosis + attribution + remediation *hint*, not true mid-run skipping
(excluding a source via `-o Dir::Etc::…` is fragile and parked).

---

## Theme 2 — Keep vendor keys & sources fresh (survive rotation)

**Goal:** a key/source that upstream rotates or moves is corrected automatically, not stranded
by the `[ -f ]` existence guard.

- **Stop trusting bare existence for correctness.** `[ -f file ] || write` proves *presence*,
  not *currentness*. Reconcile the on-disk artifact against **what the route specifies now**.
- **Cheap first step (rotation-triggered re-fetch):** when Theme 1 detects a signature failure
  for a configsys-owned source, re-run the route's `pubkey-url` fetch *overwriting* the stale
  keyring (the fetch is fingerprint/URL-pinned by the route, so this is safe), then re-verify.
  This alone fixes the Jenkins class of failure at `refresh` time.
- **Fuller step (manifest reconciliation):** a small **manifest of configsys-managed system
  artifacts** — `state/managed-artifacts.hu`: `path → { kind: apt-source|keyring|dnf-repo|
  flatpak-remote, owner-component, route-fingerprint }`. `refresh` reconciles disk vs route:
  route changed (new `pubkey-url`/`source-line`) → re-materialize; component gone → offer
  removal; artifact missing → note. This is the substrate Themes 1 & 3 also draw on, and it
  reuses the provenance plumbing `where`/orphans already have.

---

## Theme 3 — Uniform per-driver stumble guards

**Goal:** every driver's external touchpoint fails the same *shape* — categorised, isolated,
cleaned up — so no single stumble is opaque or leaves a poison pill.

- **A failure taxonomy on `Result`.** Add a `category` + `remediation` to `Result.fail`
  (`runner.py:160`): `network-unreachable`, `auth/permission`, `signature/trust`,
  `not-found/moved`, `dependency-missing`, `build-failed`, `partial-state-left`. Drivers map
  their raw errors into it; `reportgen` (`failure_from_result`) renders category + hint
  uniformly. Purely additive — a driver that doesn't classify still works.
- **Transactional side effects (validate-then-commit / rollback).** Any step that persists a
  system side effect — write a source file, import a key, `remote-add`, extract a tarball —
  must either validate *before* committing or roll back on failure, so a failed setup never
  persists. The poster child: **fetch + verify the key BEFORE writing the `.list`**, so a bad
  key can't yield a written-but-broken source (this alone would have prevented the Jenkins
  brick). Precedent to reuse: `shellguard` already snapshots/reverts installer-touched rc
  files; extend the same posture to driver-written system artifacts.
- **Cheap pre-flight where it pays.** Validate reachability/trust before the expensive or
  side-effecting action when it's cheap (key verifies the repo; flatpak remote resolves; a
  release asset URL 200s). Highest value first: apt/dnf vendor repos.

---

## Shared substrate

The **managed-artifacts manifest** (Theme 2) + the **`Result` failure taxonomy** (Theme 3) are
the two reusable pieces; Theme 1 consumes both. Existing mechanisms to reuse rather than
reinvent: `shellguard` (transactional system-file handling), the orphans/`!uninstall` model
(removing stale things), `refreshstate` (the refresh cadence + stamp), and route provenance
(`Component.source`, `where`).

---

## Phasing (highest-pain / lowest-risk first)

- **Phase 0 — taxonomy foundation.** `Result` gains `category` + `remediation`; `reportgen`
  renders them. Additive; unblocks the rest.
- **Phase 1 — index-refresh diagnosis.** Capture + classify + attribute the native index
  refresh; print culprit + cause + fix. Non-destructive. *Directly fixes the Jenkins-visibility
  pain.*
- **Phase 2 — validate-then-commit + rotation re-fetch for apt/dnf vendor repos.** Verify the
  key before writing the source; on a detected signature failure, re-fetch the route's key
  overwriting the stale one. *Prevents the poison pill and self-heals rotation.*
- **Phase 3 — managed-artifacts manifest + reconciliation.** Disk-vs-route reconcile at
  `refresh`: re-materialize changed, offer-remove orphaned. Ties into orphans/`!uninstall`.
- **Phase 4 — generalise transactional cleanup + pre-flight across the remaining drivers**
  (flatpak remote, tarball/appImage partial extract, source build, script) using the taxonomy.

---

## Open questions (proposed defaults — user can veto)

1. **Auto-remediation aggressiveness.** *Proposed:* diagnose-only by default; **prompt** before
   re-fetching a key or removing a *configsys-owned* source; **never** touch a foreign one.
2. **Manifest now or later.** *Proposed:* ship the cheap rotation-triggered re-fetch (Phase 2)
   first; introduce the manifest (Phase 3) only when reconciliation needs it — avoid a new
   state file before it earns its keep.
3. **How much pre-flight per driver.** *Proposed:* validate-then-commit only where a persisted
   side effect can break unrelated ops (apt/dnf sources first); elsewhere rely on the taxonomy +
   post-hoc cleanup, not upfront probing.
4. **Foreign-source posture.** *Proposed:* configsys diagnoses and names foreign broken sources
   but never modifies them — surfacing beats silently editing another tool's files.

## Parked

- Mid-`apt-get update` source exclusion (`-o Dir::Etc::sourceparts`) — fragile; diagnosis is
  enough.
- A generic driver "capability/reachability probe" framework — revisit if Phase 4 wants it.
- Re-verifying keys on a cadence independent of `refresh` — refresh is the natural hook.
