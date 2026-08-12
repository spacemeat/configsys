# Startup performance — investigation + fix plan

Status: INVESTIGATION COMPLETE, fixes NOT built (awaiting go-ahead). 2026-08-12. Numbers profiled on
the user's Pop!_OS box; claims below verified against the code, not just profiler output.

## The verdict: yes, it's genuinely slow, and it's all serial subprocess I/O

- `configsys inspect` ≈ **50–52s**, cold == warm. Under cProfile: **98% of wall time is `select.poll`
  waiting on subprocesses** (`runner.py` → `subprocess.run`). CPU work (layer/routes parse, resolve,
  predicate eval) sums to **<1s**. So this is not an algorithm problem — it's **441 serial subprocess
  spawns**, one probe at a time.
- `InstallState.inspect` loops `inspect_one` over ~149 units; each does `get_installed` + `get_latest`
  + `is_locked` = 3 spawns/unit. No batching, no concurrency.
- Two drivers are the whole minute: **apt ≈ 35s** and **flatpak ≈ 20s**.

## Verified hot spots

| # | What | Where | Cost | Why |
|---|------|-------|------|-----|
| 1 | `flatpak remote-info` ×8 | `drivers/flatpak.py` get_latest | ~20s | **2.48s each** (not the ~10ms the comment claims) |
| 2 | `apt-cache policy <pkg>` ×99 | `drivers/apt.py` get_latest | ~14.6s | one spawn per component; the cmd takes many pkgs at once |
| 3 | `apt-mark showhold` ×90 | `drivers/apt.py` is_locked | ~14s | **ignores its arg** — returns the full hold list every call |
| 4 | `dpkg-query -W <pkg>` ×102 | `drivers/apt.py` get_version | ~6s | one per component; `apt.installed_index()` already batches this |
| 5 | detection second pass | `detection.py` | ~3.3s | partially batched, falls back to per-method get_version |

## The most surprising finding: the cache built for this is bypassed

`method-versions.hu` (`versionreport.py`) is a per-method `get_latest` TTL cache, added precisely
because "native queries are slow." It's wired into `flooradvise`, `versionsweep`, and `configsys
versions` — but **`InstallState.inspect_one` calls `drv.get_latest(rc)` directly** and never consults
it. So every startup re-runs all 99 `apt-cache policy` + 8 `flatpak remote-info` from scratch, which is
why warm == cold.

## Fix plan (phased; ratios are from the profile)

**Phase A — pure batching, no semantic change (safe, ~34s off).** A per-inspect prepass that, for each
driver present in the unit set, runs its enumerable queries once and hands the results to `inspect_one`
(the detection pass already does this shape). Per apt:
- `is_locked`: fetch the hold set **once** → in-process membership. ~14s → ~0.15s.
- `get_version`/`get_installed`: route through `installed_index()` (already exists) — one `dpkg-query`.
  ~6s → ~0.1s.
- `get_latest`: one `apt-cache policy pkg1 pkg2 …` for all apt units, parse the per-package blocks.
  ~14.6s → ~0.3s. (This one has real parse work — associate output blocks with packages carefully.)

Mechanism choice to decide: pass a batch-context object into `inspect_one` → the driver (opt-in;
only apt/flatpak implement it, others fall back to per-unit), vs. a driver method-signature change.
The context-object route keeps the driver interface intact.

**Phase B — use the cache + go lazy (fixes flatpak, makes warm fast; has a staleness tradeoff).**
Route inspect's `get_latest` through `method-versions.hu` (TTL), and/or compute "latest" lazily — only
for units actually shown/acted on, not all 149 up front. Flatpak ~20s → ~0 on a warm cache; also
collapse `flatpak mask` (16→2, arg-ignored like showhold) and gate `remote-info` behind the cache.
**Decision for you:** cached-latest can be up to TTL stale — acceptable for the "outdated?" chip, or do
you want fresh-every-start accuracy (and keep it slow)? A short TTL + a manual `refresh` is the usual
answer.

**Phase C — parallelize `inspect_one` (bigger, orthogonal).** The probes are read-only, captured, and
already stdin-detached — a thread pool over units would cut wall time several-fold even without A/B.
More moving parts (ordering, progress callback, error handling), so last.

Realistic target: **~50s → a few seconds** with A+B; A alone ≈ 16s.

## Recommendation

Do **Phase A** first (pure win, no behavior change, testable against the install-state tests), then
decide **B**'s staleness tradeoff, then **C** if still wanted. Hold until you're back to greenlight —
this is the correctness-critical path, and the prepass mechanism + B's TTL choice are yours to make.
