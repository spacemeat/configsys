# Managed orphans — finding installed things that aren't in your active profiles

**Goal.** Surface software on the machine that configsys **could manage** (a known component, or an
install via a package manager cf drives) but that **isn't in any active profile** — so the user can
adopt it into a profile, remove it, or dismiss it. Explicitly out of scope: arbitrary files outside
configured dirs / known package managers (unfindable). In scope: native packages (apt/dnf/pacman/
zypper/apk/brew), flatpak, snap, and the language-global + path drivers (cargo/pipx/npm/gem/…,
tarball/appImage in `CONFIGSYS_APP_DIR`).

An orphan has **two orthogonal fields** — a **kind** (what it is) and a **status** (whether you've
silenced it). Keep them separate; don't collapse them into one enum. An ignored orphan keeps its
kind, so "ignored foreign flatpak" and "ignored lurking apt package" are both expressible.

**Kind** (mutually exclusive — classify by the priority ladder below, top wins):

|Kind       |  In cf routes  |  In any profile  |  Net-active?     |  Meaning                                                                 |
| --- | --- | --- | --- | --- |
|Excluded   |  Yes           |  Yes             |  No, `~`'d out   |  in an active profile's closure but explicitly removed by `~component`/`~subprofile` |
|Lurking    |  Yes           |  Yes             |  No              |  has a recipe and lives in some profile, but no active profile selects it |
|Forgotten  |  Yes           |  No              |  No              |  has a recipe but sits in no profile at all                              |
|Foreign    |  No            |  n/a             |  n/a             |  no cf recipe matches the installed key                                  |

**Status** (orthogonal to kind — a flag, not a kind):

|Status    |  Meaning                                                          |
| --- | --- |
|Tracking  |  surfaced as a to-do (adopt / activate / remove / …)              |
|Ignored   |  acknowledged via the ignore list — kept quiet, but keeps its kind |

### Classifying into a kind

The conditions overlap on a single component (it can be `~`'d out of an active profile *and* sit in
an inactive one), so classification is a **priority ladder — the first match wins**:

1. **Net-active → not an orphan.** A component that is a *member* of any active profile is managed,
   even if another path `~`'d it — member-wins (the same rule as the Profiles catalog `~` marker). It
   never reaches classification.
2. **Excluded** — in no active member set, but in the removal closure of an active profile (that
   profile, or a subprofile it includes, `~`'d it out). The loudest signal: *you said you didn't want
   this here, yet it's installed.*
3. **Lurking** — in some profile, but no active profile references it (member or `~`) at all.
4. **Forgotten** — maps to a component that's in no profile.
5. **Foreign** — maps to no component.

Excluded outranks lurking: an explicit `~` is a stronger statement than mere non-activation. (A
component excluded via a subprofile buried in an active meta-profile is *transitively* excluded —
detecting that needs a closure-aware removal check, not just a profile's direct `~terms`; see
Caveats.) One installed key can map to several components (the reverse index value is a list);
classify per (key, component) and, when they differ, surface the highest-priority kind — it's the
most actionable.


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
honoring the per-driver `name:` maps). This is what tells excluded/lurking/forgotten (all map to a
real component — you have a recipe, it's just not active) apart from **foreign** (maps to nothing),
and it also decides what we even *list*:

- **Native managers** (apt/dnf/pacman/zypper/apk/brew): only the `known` intersection (excluded/
  lurking/forgotten). Unknown keys are dropped — apt/dnf carry hundreds of dependency packages and
  listing them is noise.
- **User-facing drivers** (flatpak, snap, appImage/tarball in cf dirs): list foreign too — they're
  almost always deliberate app installs and few in number.

## The scan (`configsys/orphans.py`, new)

```
scan_orphans(ctx, units) -> [Orphan]  # Orphan = {driver, key, version, component|None, kind, ignored}
```
1. `active = { (rc.driver, driver.index_key(rc)) for rc in units.values() }`.
2. For each driver present (native ones + the user-facing set), `installed_index()` (reuse the
   detection cache — pass it in, don't re-enumerate).
3. `installed − active`, then classify each remaining key via the reverse index **plus the profile
   graph** — `config.profiles_containing(name)` and each active profile's removal closure feed the
   priority ladder above (so the scan now depends on the full profile graph, not just the active
   `units`):
   - matches a component → attach the name, classify as excluded / lurking / forgotten.
   - no match + user-facing driver → `foreign`.
   - no match + native driver → dropped (dependency noise).
4. **Filter to explicitly-installed by default.** Each driver's `explicit_keys()` (apt-mark
   showmanual, `pacman -Qeq`, `dnf repoquery --userinstalled`, `brew leaves --installed-on-request`;
   None when a driver draws no such distinction — then everything counts) names what the user
   *chose* vs what came in as an auto-pulled dependency. The scan drops the auto-installed ones — on
   a real box that's the difference between ~600 chosen packages and ~4000 total (foreign 7754 → 433).
   `--include-auto` bypasses it. User-facing drivers already self-filter (flatpak lists `--app`, so
   runtimes never appear; pipx/npm-global/pip surface only top-level).
5. **Tag every foreign orphan with its OS-origin tier** (apt Priority via `origin_index()`:
   required/important/standard/optional/extra; '' where a driver has no such notion). The tier rides
   on the orphan (kept as data — `--json` exposes it), but the base tiers (required/important/
   standard) are hidden from the foreign list by default; `--system` reveals them (a user CAN still
   choose to manage even systemd). On a real box that's another ~207 foreign that recede, leaving the
   optional/extra ones — the actual apps-you-added + recipe-gaps worklist.
6. Stamp `ignored` from the ignore list (below) — an ignored orphan keeps its `kind`, it's just
   filtered out of the default surfaces.

Cost: same batched `installed_index()` calls detection already makes (share the cache), plus one
cheap `explicit_keys()` query per enumerated native driver, + pure set math. No network, no per-item
subprocess.

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
- `configsys orphans --adopt <name> [--profile P]` → add the (known) component to a profile in the
  primary config (defaults to a review profile, or `--profile`). Foreign items have no recipe to
  adopt — they're instead grouped under a synthetic `foreign` profile so they're at least visible.
- `configsys orphans --remove <name>` → uninstall via the owning driver (confirm; reuses the remove op).
- `configsys orphans --ignore <name|glob>` → append to the ignore list so it stops surfacing.

### TUI (phase 4 — the design)

**Decided: the known kinds live on TUI::Profiles; foreign gets a read-only node in the same tree.**
The catalog scan + CLI verbs (phases 1–3) ship. This is the finalized TUI design.

- The three `known` kinds (**excluded / lurking / forgotten**) are fundamentally **profile-relative**
  — their whole definition is membership, and their actions (adopt, activate, un-`~`) are profile
  edits. The **staging-profile workflow settled the Profiles-vs-dedicated-screen question**: in
  practice you triage orphans by parking them in a non-active staging profile (e.g. `orphans-lurking`)
  and moving names into the real base profiles — which *is* Profiles-page editing. So **Profiles is
  the home**; a dedicated Orphans screen stays only as a fallback if the volume ever explodes.
- **Orphan-ness is a separate axis, not a fourth membership marker.** The catalog's existing markers
  are all one axis; "installed" is another, and a component holds a value on *each* at once:
    - **Membership axis** (config, relative to the *selected* profile): `●`/`↳` member · `~` excluded
      · blank absent. Already rendered.
    - **Install axis** (machine, *global* — same regardless of which profile is selected): present on
      disk or not. Not rendered today.
  So the orphan signal is a **second glyph/tint overlaid on the row, never a replacement for the
  membership marker**. The cell that matters most is **`~` (excluded) AND installed**: the config says
  "not here," the disk says "present."
- **Why excluded+installed earns its own visibility.** It's the genuinely *ambivalent* row — you're
  about equally likely to want to **activate it into a profile** or **uninstall it**. And because
  \*nix package names are cryptic and forgettable, surfacing that duality *on the row* (rather than
  making the user cross-reference `configsys orphans` output against their config from memory) is
  where the value is — you may not recall what the thing even is, only that an unresolved decision is
  attached to it. This is exactly the `excluded` orphan kind, made visible in place.
- **Containment (relaxed):** install-state *display* is welcome here as long as it stays
  **read-only, informative feedback** — Profiles shows what's on disk; it doesn't become a place you
  *drive installs* from. The still-firm line: keep the *detail* light (install presence + the orphan
  bit), not full install state — version / latest / locked stay on Components. The only *actions*
  remain profile edits (adopt / activate / un-`~`), since those are config, which is Profiles' domain.
- **Rendering the two axes (endorsed direction):** encode them on *different visual channels* so they
  read independently:
    - **Installed → underline** the component name. A text attribute, so it composes with the member
      background tint and the selection bar, and — key — it survives the mono / 8–16-colour paths
      where a colour can't. Blank (no underline) = not on disk yet = an install to-do.
    - **Orphan → a distinct foreground colour** on the name, **not** a background highlight: the row
      background is already claimed by the member tint + selection/residual bars, and two backgrounds
      can't stack — a foreground colour layers cleanly over the tint *and* the underline, so all three
      signals (member-of-selected / installed / orphan) stay visible at once. An orphan is installed
      by definition, so orphan rows are underlined *and* orphan-coloured; the flagship `~`+installed
      cell reads as `~` glyph + underline + orphan colour.
    - **Low-colour / mono fallback:** underline carries the install axis unchanged; the orphan colour
      degrades (underline-only, or a trailing marker) — acceptable, since `configsys orphans` is the
      authoritative kind view.
    - **Not hardcoded — themeable roles.** The underline/colour above are just *defaults*: expose
      `installed` and `orphan` (and the `~`+installed combination, if it earns its own) as palette
      **roles** carrying their own colour + effect, user-overridable like every other role. The
      existing `effects=full/reduced/none` machinery then governs the attribute degradation for free,
      and a user who wants a different look just retheme the roles.
- **Toggle, not per-profile suppression:** make the install axis an on/off **toggle** so a user who
  wants Profiles as pure config can switch it off. On the selected-vs-active subtlety: both signals
  are *global machine truths* (true regardless of which profile is selected), so neither is suppressed
  for an inactive selected profile — a member of an inactive profile reading as an orphan is itself
  informative ("this profile isn't active, so its installed members are unmanaged"). The toggle is the
  cleaner control than blanking the axis per-profile.
- **Foreign** is the odd kind out — no recipe, no profile home. It surfaces as a **synthetic,
  read-only `foreign` node** in the profiles tree (a sibling of the real profiles), tier-tagged
  (base tiers folded away by default, `--system`-style reveal), purely to *see and identify* recipe-
  less installs — never to adopt (there's nothing to adopt). Its only actions are ignore and (future)
  file a component-request through **configsys-issues**.

**Actions (keys on the catalog row / the left tree).** All reuse the phase-3 verbs, so the TUI is a
thin front for `actions.set_profile_membership` / the remove op / `orphans-ignore`:

- **`A` adopt** → add the (known) orphan to the **selected** profile. On a foreign row it's inert
  (nothing to adopt).
- **`s` stage** → adopt into the configurable **staging profile** (an `orphans-adopt-target` machine
  setting, default a review profile like `orphans-lurking`) — the "park it for later triage" move the
  manual workflow proved out. Bulk-select + `s` parks a batch at once.
- **un-`~` / activate** → for an `excluded` orphan, the adopt path is re-including it (drop the `~`);
  for a `lurking` one, activating its profile. Both are ordinary Profiles edits (`~`/membership keys).
- **`x` remove** → uninstall via the owning driver (confirm; the remove op). The other half of the
  excluded+installed decision.
- **`.` ignore** → append the name/key to `orphans-ignore` (silences it; the locale/font/hardware
  bulk is a few globs).

**The staging-profile loop, first-class.** `s` → park in the staging profile (kept out of `configs:`,
so parked items read as *lurking*, not installed-by-surprise) → the user opens that profile and moves
names into `dev`/`graphics`/… with normal membership edits → deletes the staging profile when drained.
The TUI just makes the `orphans` scan the entry point to a loop the Profiles page already supports.

A dedicated **Orphans screen** (7th tab) remains the fallback only if per-machine volume ever makes
the overlay-on-Profiles too noisy.

## Config

- `orphans-ignore: [ <name-or-glob>, … ]` — a machine setting (nature: **machine**, like `scope`),
  so acknowledged one-offs on THIS box don't nag. `--ignore` appends here; `check` can warn on stale
  entries (ignored name no longer installed).

## Caveats / honesty (surface these in the output, don't hide them)

- **Findable only where cf looks**: things outside configured dirs / known managers won't appear —
  say so in a footer (`scanned: apt, flatpak, snap, cargo, pipx; not: arbitrary ~/ files`).
- **Reverse-index fidelity**: the `(driver, name)`→component map must honor every per-driver `name:`
  override, or a known package reads as foreign. Test against the name-sweep data.
- **Transitive exclusion** (handled): an `excluded` orphan may be `~`'d out by a subprofile nested
  inside an active meta-profile, not by the active profile's own terms. The scan classifies via
  `Config.profile_removed_closure(profile)` — the union of `~`-removals across the profile's
  NET-ACTIVE include closure (`active_subprofiles`, so a `~`'d-out subprofile's own internal `~`s
  don't leak back in) — so such an orphan reads as *excluded*, not *lurking*.
- **Version-scoped providers**: `python3.11` installed while the active set wants `python3.13` —
  that's a *known* orphan of the version-scoped component, not foreign. The reverse index keys on the
  provider's own name, so this falls out naturally; add a test.
- **`--pretend`/immutable**: on atomic distros native removal is layered — `--remove` must route
  through the real driver (rpm-ostree/brew), which it does by reusing the op path.

## Phasing

1. Reverse index + `scan_orphans` + tests (pure-ish; mock `installed_index`). **DONE.**
2. `configsys orphans` report (share detection's index cache). **DONE** — plus the manual/auto
   filter (explicit_keys), the OS-origin tier tag, native-backed cross-indexing, and cross-distro
   pip/npm noise-trimming (INSTALLER=pip + `--not-required`; node-bundled exclusion).
3. `--adopt` / `--remove` / `--ignore` + `orphans-ignore:` setting. **DONE** — `--ignore <glob…>`
   appends to the machine-nature `orphans-ignore:` (registered in CONFIG_SETTINGS); `--adopt <comp>
   --profile P` adds a known orphan to a profile; `--remove <comp>` uninstalls a known orphan via its
   driver (confirm unless `--yes`; foreign keys are declined — no recipe). Still TODO: a `check`
   stale-ignore warning (ignored pattern that matches nothing installed).
4. TUI surface — **designed, not built** (see the TUI section). Decided: the install axis overlays
   TUI::Profiles (themed `installed`/`orphan_*` roles, toggle), foreign is a read-only tree node, and
   the actions (`A` adopt / `s` stage / `x` remove / `.` ignore / un-`~`) are thin fronts over the
   phase-3 verbs, with a configurable `orphans-adopt-target` staging profile. Build items: the
   overlay rendering + role plumbing, the `s`/adopt-target setting, and the synthetic `foreign` node.

## Open questions (for the user)

- Default adopt target for known orphans: a dedicated review profile vs prompting for one? (Lean: a
  review profile in the primary config, easy to sort later.) Note the three known kinds may deserve
  *different* defaults — forgotten → adopt, lurking → activate-its-profile-or-adopt, excluded →
  remove-or-un-`~` — so "adopt" isn't one-size-fits-all.
- `foreign` profile: is a synthetic pseudo-profile the right home for recipe-less items, or should
  they stay a flat CLI-only list until the configsys-issues request hook exists?
- Foreign flatpak/snap by default in the list, or opt-in like native? (Lean: show them — they're
  user apps and few.)
- Should the scan run opportunistically during normal inspect (a badge: "7 installed items aren't in
  a profile") or only on demand via `configsys orphans`? (Lean: on-demand first; a badge later once
  the false-positive rate is known.)
