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

## Resolved during the refactor
(none yet)
