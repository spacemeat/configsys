# D2 MVVM rewrite — findings log (fix SEPARATELY, not mid-refactor)

The rewrite holds a strict pixel-preservation bar (docs/d2-mvvm-plan.md). Any pre-existing bug or
rough edge noticed while migrating a screen is recorded HERE and left behavior-identical, so the
refactor stays provably neutral. Address these in their own commits afterward.

## Open

- **Profiles `ps._res` goes stale after a components-side method pin.** When you pin a component's
  install method from the Components screen (`method` action), the Profiles screen's resolved-method
  cache (`ProfileScreen._res`) is not invalidated, so a later visit to Profiles can show the
  pre-pin `[via]`. Profiles invalidates its own cache when IT changes a pin, but not when Components
  does. Surfaced by the run()-dispatch map. Low impact (cosmetic until the next Profiles reload).
  Fix: have the components `method` path (or `ctx.invalidate()`) also drop `ps._res`, or key
  `_res` on a resolution generation that `ctx.invalidate()` bumps.

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

## Resolved during the refactor
- The note-display drop above (fixed as part of the migration, not deferred).
