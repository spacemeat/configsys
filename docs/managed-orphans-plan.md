# Managed orphans — finding installed things that aren't in your active profiles

**Goal.** Surface software on the machine that configsys **could manage** (a known component, or an
install via a package manager cf drives) but that **isn't in any active profile** — so the user can
adopt it into a profile, remove it, or dismiss it. Explicitly out of scope: arbitrary files outside
configured dirs / known package managers (unfindable). In scope: native packages (apt/dnf/pacman/
zypper/apk/brew), flatpak, snap, and the language-global + path drivers (cargo/pipx/npm/gem/…,
tarball/appImage in `CONFIGSYS_APP_DIR`).

## What we already have (reuse, don't rebuild)

- Every package-manager driver has **`installed_index()`** (one batched enumeration → `{key: version}`)
  and **`index_key(rc)`** (the key a resolved component maps to). `detection.detect_pins` already
  pre-warms these **in parallel**, and `installState.detect_coexisting` already does the
  "walk up to a machine and see everything installed via a component's OTHER methods" pass
  (`state.also_present`). The orphan scan is the *complement*: installed items with **no active
  component at all**.
- The active resolved set (`units` from `load_pipeline`) gives every `(driver, index_key)` we DO
  manage — the set to subtract.

## The one new primitive: a reverse index

`routes → { (driver, package_key): [component_name, …] }`, built by walking every component's
bindings and, for each, the `name:` it resolves to per driver (defaulting to the component name;
honoring the per-driver `name:` maps). This lets us classify an installed key we didn't put there:

- **known orphan** — the key maps to a component that exists in routes but isn't in the active set
  (you have a recipe for it; it's just not in a profile). *This is the useful signal.*
- **unknown/foreign** — the key matches no component. For **user-facing** drivers (flatpak, snap,
  appImage/tarball in cf dirs) we still list these (they're almost always deliberate app installs,
  few in number). For **native** managers we do **NOT** list unknown keys — apt/dnf have hundreds of
  dependency packages; listing them is noise. Native is filtered to the `known` intersection.

## The scan (`configsys/orphans.py`, new)

```
scan_orphans(ctx, units) -> [Orphan]      # Orphan = {driver, key, version, component|None, kind}
```
1. `active = { (rc.driver, driver.index_key(rc)) for rc in units.values() }`.
2. For each driver present (native ones + the user-facing set), `installed_index()` (reuse the
   detection cache — pass it in, don't re-enumerate).
3. `installed − active`, then classify each remaining key via the reverse index:
   - matches a component → `known` orphan (attach the component name).
   - no match + user-facing driver → `foreign` orphan.
   - no match + native driver → dropped (dependency noise).
4. Honor an **ignore list** (below) — acknowledged orphans stay quiet.

Cost: same batched `installed_index()` calls detection already makes (share the cache) + pure set
math. No network, no per-item subprocess.

## UX

Two surfaces, CLI first (cheap, scriptable), TUI later.

### `configsys orphans` (CLI, phase 1)

Grouped by driver, e.g.:
```
Installed, not in your active profiles (dev, base):

  apt        htop 3.0.6        → component 'htop'      [add to a profile · remove · ignore]
             ncdu 1.16                                  (known recipe, unprofiled)
  flatpak    org.blender.Blender 4.1   → 'blender'
             com.acme.Thing 2.0        (foreign — no cf recipe)
  cargo      bacon 2.14        → component 'bacon'

12 known · 3 foreign   ·   `configsys orphans --adopt htop` to add to a profile
```
Flags: `--driver X` (one driver), `--foreign` (include foreign for native too, opt-in), `--json`
(scripting). Actions:
- `configsys orphans --adopt <name> [--profile P]` → add the component to a profile in the primary
  config (defaults to a `caught`/user profile, or `--profile`).
- `configsys orphans --remove <name>` → uninstall via the owning driver (confirm; reuses the remove op).
- `configsys orphans --ignore <name|glob>` → append to the ignore list so it stops surfacing.

### TUI (phase 2, once the CLI + scan are proven)

Options, cheapest first:
- A **filter/section on the Components screen** — "also installed, not in a profile" rows, greyed,
  with `A` add-to-profile / `x` remove / `.` ignore. Reuses the components list machinery.
- Or a dedicated **Orphans screen** (7th tab) if the volume warrants it. Decide after seeing real
  counts on the user's machine.

## Config

- `orphans-ignore: [ <name-or-glob>, … ]` — a machine setting (nature: **machine**, like `scope`),
  so acknowledged one-offs on THIS box don't nag. `--ignore` appends here; `check` can warn on stale
  entries (ignored name no longer installed).

## Caveats / honesty (surface these in the output, don't hide them)

- **Findable only where cf looks**: things outside configured dirs / known managers won't appear —
  say so in a footer (`scanned: apt, flatpak, snap, cargo, pipx; not: arbitrary ~/ files`).
- **Reverse-index fidelity**: the `(driver, name)`→component map must honor every per-driver `name:`
  override, or a known package reads as foreign. Test against the name-sweep data.
- **Version-scoped providers**: `python3.11` installed while the active set wants `python3.13` —
  that's a *known* orphan of the version-scoped component, not foreign. The reverse index keys on the
  provider's own name, so this falls out naturally; add a test.
- **`--pretend`/immutable**: on atomic distros native removal is layered — `--remove` must route
  through the real driver (rpm-ostree/brew), which it does by reusing the op path.

## Phasing

1. Reverse index + `scan_orphans` + tests (pure-ish; mock `installed_index`).
2. `configsys orphans` report (share detection's index cache).
3. `--adopt` / `--remove` / `--ignore` + `orphans-ignore:` setting + `check` stale-ignore warning.
4. TUI surface (Components filter first; dedicated screen only if counts justify it).

## Open questions (for the user)

- Default adopt target: a dedicated `caught` profile vs prompting for one? (Lean: a `caught` profile
  in the primary config, easy to review later.)
- Foreign flatpak/snap by default in the list, or opt-in like native? (Lean: show them — they're
  user apps and few.)
- Should the scan run opportunistically during normal inspect (a badge: "7 installed items aren't in
  a profile") or only on demand via `configsys orphans`? (Lean: on-demand first; a badge later once
  the false-positive rate is known.)
