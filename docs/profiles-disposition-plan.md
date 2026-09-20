# Profiles v2 — the disposition model (replaces `^derive`)

> **Status: HISTORICAL — SUPERSEDED by docs/profiles-matrix-plan.md (the picks matrix; profiles are read-only browse lenses). Preserved at tag `profiles-disposition-model`.**

## Context

The `^derive` run (docs/profiles-derive-plan.md) produced good scaffolding but the `^` primitive itself
never stopped being confusing: a `^sub` term that *looks* like `+sub` but resolves oppositely, treated
differently per level, hard to track and reason about in a disjoint hierarchy. This plan **replaces
`^`** with a clearer, more controllable model, keeping everything good the run produced (layering,
`machines:`, source-grouping, the catalog + attrs/filters + info box + state markers, `!uninstall`,
dotfiles, `machine`/user selection, new/rename/delete of user profiles, `where`).

Core idea: **system profiles (repo/plugin) are a read-only *source* you browse; user profiles are your
own curated sets; every component has a DISPOSITION** (include / exclude / new / interesting, plus
seen = acknowledged-not-new). New upstream components/profiles are automatically NEW. You triage by
browsing system profiles and adding to / marking components, or by cloning a whole system profile.

## Locked decisions (from grilling, 2026-09-09)

1. **No more `^`.** Drop the derive primitive, ballot, pin, structural-menu, `sub_engagement`, and the
   whole per-level `^`/`+` distinction. New = undispositioned.
2. **User profiles are COPIES, not references.** Adding/cloning MATERIALIZES component names into a
   user profile — no live link to a system profile, so system growth never auto-installs; it surfaces
   as NEW. A system profile that `+`-includes others is **deep-cloned** (its sub-profiles cloned as
   user profiles, referenced by `+include` between the user copies) — never flattened inline, so you
   can restate a whole sub-profile as a unit.
3. **State home = profiles + a side-store.** include = the component is a member of a user profile;
   exclude = a `~name` term in a user profile; **seen/interesting live in a `dispositions:` section**
   (layered like machine settings, written to local `.config`); NEW = undispositioned (absence).
4. **Disposition scope = global per component** — mark a component seen/interesting once, it's that
   wherever it appears. **Persistence = local per-machine** (this box's triage; a fresh box re-triages).
   include/exclude follow their user-profile's layer (top config / primary / `machines:`) — they
   travel/scope exactly as today.
5. **Same-name clones + per-layer pane.** Clones keep the system name (no prefixes). The pane renders
   a profile FROM EACH LAYER that defines it: system `languages` under `repo catalog` (base contents),
   your clone under `this machine`. A system-profile node's catalog reads its OWN-layer members, so the
   browse-source stays pristine; resolution still merges (your clone wins for the active set).
6. **Catalog marker = selected-profile membership + global disposition.** Include/exclude shown
   relative to the CURRENT profile (`● member here` / `~ excluded here`); new/seen/interesting are the
   component's global disposition when it isn't a member of the current profile.
7. **`A` clones a selected sub-profile as a UNIT** (deep clone → `+include` of a user clone); selected
   loose components add flat. `A`/`I`/`S`/`X` all clear NEW (you acted on it).

## The model

**Layers (unchanged):** repo/plugin (system) < primary < `machines:[m]` < local top config. Grouped by
source in the left pane. **New:** the pane renders per-layer (no dedup) so a same-named profile appears
under each defining layer.

**Dispositions.** A `dispositions: { <component>: seen | interesting }` section — merged via the
existing layer machinery (`merge_*` in layers.py, `_MACHINE_ROLES`), authored to the local top config.
- **NEW** = a component offered by some system profile AND not (`seen` ∨ `interesting` ∨ member of any
  user-layer profile ∨ in `!uninstall`). NEW is the default; nothing stores it.
- **seen** (`·`) = acknowledged, no longer NEW. **interesting** (`☆`) = bookmarked, not installed, not
  NEW. **include** (`●`) = member of the current user profile. **exclude** (`~`) = `~name` in it.

**Keys (catalog, act on the multi-selection, else the cursor):**
- `A` → modal picking target user profile(s) (multi-select). **Smart default:** the same-named user
  profile if one exists (you're replicating structure); else user profiles that already contain
  components from the same system profile(s) as the selection. Adds components; a selected sub-profile
  is offered as a whole-unit clone.
- `I` interesting · `S` seen · `X` → `!uninstall`.

**Clone (a system profile, or `all`):** deep-clones its hierarchy + components into user profiles
(same names by default, per-layer pane) or a chosen target, via a modal with the same smart default.

**`*` is a MODE, not a filter** (on by default): the catalog scopes to the current profile's
members+submembers and follows selection as you move; toggle off → full catalog. System profile → its
own-layer members; user profile → its members.

**`all`** is a normal (visible, cloneable) system profile: every component, no `+`profiles.

**Everything else stays:** `machines:` + the `M` target selector, user/machine layer selection,
new/rename/delete of user profiles + subprofiles (legal names), install/execute, `!uninstall`, dotfiles,
attrs/filters, `where`.

## What gets removed (the `^` machinery)

config.py: `^` in `_split_term`/`_expand`/`_layout`; `_menu_structural`/`_compute_menu`/`profile_menu`/
`profile_menu_items`/`profile_new`/`is_derived`/`profile_derive_terms`/`check_derives`/`profile_relation`
(pinned)/`subprofile_state`/`sub_engagement`/`hierarchy_children`/`plan_subprofile_state_edit`. actions.py:
`pin_profile`, `set_subprofile_state`, the ballot/decline/clear paths, `synth=pin`. menu.py: the derive
tree kind, `_ensure_path_engaged`, `_pin_or_track_modal`, `_ballot_new_count`, `watch`/definition box's
derive bits (keep the plain-def box), the ballot keys. app.py: `reconcile`-as-derive, the `where -p`
derive/menu/new lines, `profile decline|offer`, `--pin`/`--track`. Tests: test_profile_derive.py,
the ballot/pin/hierarchical cases in test_profile_edit.py, derive smokes.
**Kept:** layers.py, machines: (config.py `_inject_machine_layer` etc.), grouping, `profile_layout`/
`profile_children`/`profile_components`/`profile_includes`/`profile_excludes`/`active_subprofiles`,
`plan_membership_edit` (add/remove only), `plan_subprofile_edit`, the machine target selector, catalog,
attrs, `!uninstall`, dotfiles, `where -p` (layers + relation only).

## Phased build

- **Phase 1 — remove `^`.** Strip the derive machinery above; simplify the pane back to plain
  profiles + `+include` children; keep green. (Big, mechanical; regen golden, man.)
- **Phase 2 — dispositions store.** `dispositions:` section (read/merge/write, local), `Config`
  accessors (`disposition(comp)`, `set` via a writer), NEW computation, `configsys disp` CLI
  (get/set/list) for testing.
- **Phase 3 — per-layer pane + system/user browse.** `visible_pnodes` renders per-layer (no dedup); a
  system-profile node reads its own-layer members; catalog markers = selected membership + global disp.
- **Phase 4 — the catalog workflow.** Multi-select in the catalog; `A` (add-to-user-profile modal +
  smart default + whole-subprofile clone), `I`/`S`/`X`; the `*` mode.
- **Phase 5 — clone.** `configsys profile clone <system> [target]` + TUI action: deep-clone hierarchy
  + components into user profiles (smart default target).

## Open / defaults (veto in review)

- **`reconcile` repurposed**, not dropped: `configsys reconcile` = list NEW (undispositioned) components
  across active/system profiles — the CLI dual of the catalog's NEW markers.
- **Catalog multi-select:** `space` toggles a component into a selection set (was membership-toggle);
  `A`/`I`/`S`/`X` act on the set, else the cursor. In a USER profile, a second key (or `space` when no
  set) toggles include/exclude membership.
- **Activation:** `configs:` may name a user OR system profile; a system name resolves to your clone if
  you have one (shadow), else the base.
- **Migration:** no `^` exists on disk (pins were never applied), so removal is clean; existing plain
  `ts-*` / `+include` profiles keep working unchanged. `pin_profile.py` (scratchpad) is retired.

## Parked

- Encoding the hierarchy directly in nested humon — rejected for now (layering makes it confusing; the
  layer stack still stacks the same, so flat per-layer profile lists stay the representation).
