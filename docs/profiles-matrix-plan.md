# Profiles v3 — the component × machine matrix

Supersedes the disposition-model Profiles page (preserved at tag
`profiles-disposition-model` / branch `profiles-disposition-model-snapshot`). Reuses most of that
work (layer stack, machines, dispositions, install-probe, drivers, `check`); retires user-profile
*authoring* (clone, add-to-profile, per-layer pane).

## The idea

Users shouldn't have to *author structure* (profiles, includes, clones) to say "I want this on this
box." Collapse it to a **matrix**: components (rows) × machines (columns), with direct per-component
state. Repo/plugin profiles become a pure **browse lens** on the left; you page through them and mark
what you want. Discovery, not composition.

## Locked decisions (grilled 2026-09-10)

1. **Install set = per-component Included marks only.** A machine installs exactly the components
   marked Included *for it*. Repo/plugin profiles are browse-only; the old `configs:`/user-profile
   install path retires. (Repo `configs:` is ignored as an install driver.)
2. **Preserve the old page in git only** (tag + branch). Build the matrix page in place on `main`.
3. **Bulk marking = multi-select + "select all in view"**, then A/D/I act on the set. No
   whole-profile auto-include — you always choose.
4. **Machine selection is plural.** Editing fans out: A/D on the selected component(s) applies to
   every selected machine's Included set. Dispositions (seen/interesting) stay GLOBAL per component.

## Data model

- **`picks:` section** (new, local — per-machine, like `pins:`/`dispositions:`):
  `picks: { <machine>: [ <component> … ] }`. The set of components Included on each machine.
- **Current machine identity:** the `machine:` setting if set, else a default key (hostname, else
  `this-machine`). One-machine users just have one entry.
- **Dispositions unchanged:** `dispositions: { comp: seen|interesting }` stays GLOBAL + local.
- **NEW** stays derived: undispositioned & not Included anywhere & not `!uninstall`.

## Engine reuse — one reserved profile, zero resolver change

The whole install path goes through `requested()` → `active_profiles` → `profile_components`. So:

- Reserve `@picks`. `Config.profile_components('@picks')` returns `picks[current-machine]`.
- In this model `active_profiles` == `['@picks']` (repo `configs:` no longer drives installs).
- `requested()` (unchanged) then yields the picks; **install, inspect, orphans, reports, Components
  execute all work untouched.** `!uninstall` / orphans-adopt-target reserved profiles stay as they are.
- Labels/reports special-case `@picks` (show "picks", not the raw token).

## Build phases

- **A — data + storage.** `plugins.read_picks/set_picks`; `Config.picks()/included(machine)/
  current_machine()`; `actions.set_included(ctx, comp, machines, on)` (plural fan-out, local writes).
  Tests. (Self-contained, low risk.)
- **B — wire the install set.** `@picks` reserved profile → `profile_components`/`active_profiles`;
  regen golden (installs now seed from picks). Migrate: seed `picks[current]` from today's active
  profiles' members once, so nothing silently drops. The risky step — do it behind tests.
- **C — matrix TUI.** Left = repo/plugin browse groups only. Right = ONE vertical list (a table):
  columns `sel · name · installed · included · new · interesting · <machine…>`. Keys: `A` include /
  `D` exclude (fan out to selected machines), `I` interesting, `S` seen, `space` multi-select,
  select-all-in-view, `M` plural machine-target. Scope-to-browsed-profile paging stays. Keep the
  install-probe underline + `?` help.
- **D — retire authoring** from the screen (clone/add-to-profile/per-layer pane/⁺N-into-clones);
  code stays in git. Keep `⁺N`/`*N` counts as browse-lens triage hints if still useful.

## Open / defaults (overridable)

- Per-machine columns show DESIRED (Included) state; the single `installed` column is THIS machine's
  reality only (other machines' install reality isn't knowable without connecting).
- `M` machine-target defaults to the current machine; toggling adds/removes edit targets.
- A one-time migration (B) turns the user's current active-profile membership into `picks[current]`.
