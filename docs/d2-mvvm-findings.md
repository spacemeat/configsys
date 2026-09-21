# D2 MVVM rewrite — findings log (fix SEPARATELY, not mid-refactor)

The rewrite holds a strict pixel-preservation bar (docs/d2-mvvm-plan.md). Any pre-existing bug or
rough edge noticed while migrating a screen is recorded HERE and left behavior-identical, so the
refactor stays provably neutral. Address these in their own commits afterward.

## Open

- **ProfileScreen._warm_cache resolves into shared ctx.routes caches from a daemon thread.** Each
  ProfileScreen spawns a background sweep that calls `_resolve` (which reads/writes ctx-level
  detection caches) for the whole catalog. With a single ProfileScreen per session (production) this
  is fine, but two ProfileScreens sharing one ctx resolve concurrently and can race those caches. It
  surfaced only in the render-equivalence harness (many sample ProfileScreens over one ctx): a
  component's shown via/pin occasionally differed between two renders. Worked around in the SAMPLE
  fixture (abort the warm thread + pre-resolve synchronously); the underlying per-`_resolve` shared
  cache mutation is worth making thread-safe or instance-local if the TUI ever runs two profile
  views over one ctx.
- **Migrated screens must render the transient status note.** The legacy painters append the loop's
  `note` to the status line; four migrated screens (plugins/glue/dotfiles/config) initially dropped
  it and the theme screen too — the equivalence harness renders with `note=''` so it did not catch
  this. Fixed in-refactor (each VM carries a `note` slot the router fills; each draw appends it).

## Resolved
- The note-display drop above (fixed as part of the migration, not deferred).
- **Profiles `ps._res` staleness after a components-side (or config/plugin) pin — FIXED.**
  `ProfileScreen._resolve` now drops `_res` whenever `id(ctx.routes)` differs from when the cache was
  built. A pin/route/plugin edit calls `ctx.invalidate()` (fresh Resolver → new id) so the stale
  `[via]` is dropped even when the edit came from another screen; a membership/profile edit does NOT
  invalidate, so the cache survives (the perf win is kept). test_screen_profiles.py
  `test_res_cache_drops_when_ctx_routes_rebuilt` pins it.
