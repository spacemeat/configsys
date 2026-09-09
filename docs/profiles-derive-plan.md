# Profiles: the `^derive` primitive + ballot UX — design/plan

Status: DESIGN, not built. 2026-09-05. Captures the profiles-UX exploration (Fable memo +
review). May or may not be implemented; this is the settled design so it survives context loss.

Criteria, in priority order (the project north star): **(1) no surprises · (2) clarity in both
the .hu text and the TUI · (3) discoverability · (4) precise control.** Everything must be
achievable from the TUI, not just the text file.

---

## The three problems this solves

1. **Editing a default (repo) profile is obfuscatory.** The TUI correctly writes only the delta to
   the user's layer (a `+self` amend), never the repo — but it forms a *relationship* ("repo changes
   now flow into your version forever") as a silent side effect of pressing space, and it's unclear
   how a repo profile *changing underneath* (new configsys versions) reflects in the user's copy.
2. **Per-machine profile sets pile up.** The author crafts `ts-desktop` / `ts-laptop` /
   `ts-home-server` (more coming), which share *parts* of other profiles; the current move is renamed
   copies (`ts-*`) — partly to avoid corrupting the dev-facing defaults — and they clutter
   TUI::Profiles.
3. **Clone-and-cull auto-includes parent growth.** `ts-ai-tools: [ +ai-tools ~aider ~codex ]` keeps
   the parent's components visible while culling — but a configsys update that ADDS to `ai-tools`
   silently joins the set and gets accidentally installed. The fresh-list alternative
   (`[ claude-code ollama ]`) has the opposite flaw: no visibility of the parent's menu, no discovery
   of new options.

The common thread: `+include`/`+self` are **opt-out** relations (live union; parent growth flows in).
There is no **opt-in** dual (pin my picks; offer — don't apply — parent growth).

---

## The primitive: `^derive` — the opt-in dual, the 4th cell of a 2×2

```
                     opt-OUT (live union, parent changes FLOW)   opt-IN (pinned picks, changes OFFERED)
 another profile      +other   (include)                          ^other
 same name, lower     +self    (amend)                            ^self
```

`+other`/`+self` are one operation pointed at two targets; `^other`/`^self` are their opt-in dual.

**`^p` is a VIEW term, not a SET term — it contributes zero members.** Membership stays carried by
the bare names you already write. `^p` only declares a live *provenance link*: "render me against
`p`'s menu; when `p` grows, tell me — don't change me." That is why it's closed under parent growth
where clone-and-cull is not: `+p ~a ~b` encodes your selection as *the complement of your rejections
against a moving set*; `^p a b` encodes it as *your picks against a visible set*.

### Sigil / humon note
`^` collides with humon's heredoc-name syntax (and `@` is taken by metatags), so a derive term must
be **quoted**: `"^languages"` (any quote — `'` `"` `` ` ``). The algebra is lexer-agnostic; if humon's
heredoc/`@` chars move later (reflection-syntax pressure), `^` can become bare. `?` was rejected
(reads interrogative; a one-char typo next to `+` would silently flip opt-in to opt-out — the worst
possible failure for a no-surprises tool). Never spell it `+p?` for the same reason: it would name the
op "include" while contributing no members — the exact obfuscation of Problem 1.

---

## The ballot model — three states, and "the profile IS the lockfile"

Under a `^` menu every catalog item is in one of three states, **all derivable from the text alone**:

- **picked** — a bare `name` in the list → a member.
- **declined** — a `~name` in the list → deliberately not a member, quiet forever.
- **unballoted** — in the menu, mentioned nowhere → not a member, and **NEW** (surfaced).

So there is **no hidden "seen" state** — no lockfile, no timestamps, no per-machine baseline. The
`.hu` file is the complete record of every decision; anything not in it is, by definition,
pending-and-visible. "N new since you last looked" is free, because *looking + ballotting in the TUI
writes the file*. This is the no-surprises property **by construction**: nothing can reach an install
without first appearing as an unballoted NEW option. Doc philosophy in one line: **the profile is the
lockfile.**

`~` needs no new dual — it **unifies to one meaning everywhere**: "x is not a member of this profile,
deliberately." Under `+` it subtracts; under `^` it declines; identical set semantics
(remove-if-present), only the rendering differs. One new sigil, no new marks.

---

## The algebra (closed, non-leaky)

For a profile `P`, over its ordered terms:

- **members(P)** — the resolved component set:
  - bare `name` → add
  - `+q` → add members(q)                  (live include)
  - `^q` → no change                       (menu-only)
  - `~x` → remove x if a leaf, else members(x)   (decline / exclude, **transitive**, sub-subprofiles included; a subprofile's own internal `~` never leaks up — existing semantics)
- **menu(P)** = ⋃ members(qᵢ) over each `^qᵢ` term.  (a plain, `^`-free profile has menu = ∅ — it is not a derivation)
- **menu(^p) = members(p)** — what `p` *is*, not what it could offer. Recursive: a plain profile's
  full transitive expansion; a *derived* profile's *picks*.
- **NEW(P)** = menu(P) − members(P) − declined-closure(P).

Consequences (worked from the author's examples):

- `ts-languages: [ "^languages" "^dotnet-lang" ]` → menu = members(languages) ∪ members(dotnet-lang)
  = members(languages) (dotnet-lang ⊆ languages, so the 2nd term is **subsumed** → lint). No bare
  picks ⇒ members = ∅ (all-menu, nothing selected; a starting point).
- `ts-desktop-languages: [ "^ts-languages" ~jvm-lang ]` → **derivation of a derivation is a
  NARROWING**: menu = members(ts-languages) = *ts-languages' picks*, not all of `languages`. You can
  only offer/pick what the parent selected; you cannot un-narrow by deriving. To reach beyond it, add
  a second menu: `[ "^ts-languages" "^languages" ~jvm-lang ]` (union of curated picks + full catalog).
- `ts-laptop-languages: [ "^python-lang" "^ocaml-lang" ]` → **multi-parent = union** of two full
  sub-catalogs; pick across both.

Mixing composes freely: `+q` live-includes (members flow), `^q` offers (menu), bare = pick,
`~x` = decline. A bare name not in any menu is just an ordinary member (a plain profile still works).

### Subprofiles carry the `?`-NEW state too (fractal ballot)
A configsys update that adds a whole subprofile to a parent (e.g. `languages` gains `+zig-lang`)
surfaces `zig-lang` as a **collapsed NEW group**, not N loose leaves. Three one-decision moves, plus
drill-in:
- **decline wholesale** → `~zig-lang` (transitive over its sub-subprofiles)
- **take it live** → `+zig-lang` (opt-out; future zig-lang growth flows in)
- **derive it** → `"^zig-lang"` (pin; drill in, pick members, future growth offered)

**Open declines:** `~dotnet-lang` also swallows *future* additions to dotnet-lang (auto-declined).
That is the correct no-surprise default (a decline can never surprise-*install*; at worst it
under-*discovers*). The discovery debt is repaid by a collapsed "auto-declined (via ~dotnet-lang)"
section in the reconcile view — quiet, never hidden. Contrast: an *unballoted* subprofile's new
members DO surface as NEW.

### `^self` over a middle-layer `+self` (plugin composition) — validated
Layer stack: repo < plugin(s) < user. `^self`/`^name` resolves its menu to **the merged definition in
the next layer down** (the same rule `+self` already uses). So with configsys-source doing
`science: [ +self fastdds … ]` (a plugin extending base `science`, live, for all its consumers) and
the user doing `science: [ "^self" fastdds claude-code ~opencv ]`:

- `menu(^self)` = the science defined below the user = base ∪ plugin's `+self` additions (already
  merged). The plugin's contributions are **offered**, not lost (a `^self` refers to the lower layer,
  doesn't shadow it).
- When configsys-source updates and its `+self` gains `newlib`, the merged menu gains it → it shows
  as **NEW** in the user's derived science → offered, not installed.

This reads as two opt-ins at two scopes: the **plugin author** opts-in-for-everyone-live (`+self`);
**you** opt-in-for-yourself-pinned (`^self`). They stack, no special cases. Invariant it imposes:
same-name resolution must be strictly *next-lower-layer, chained* (base → plugin `+self` → user
`^self`) — the same discipline `+self` needs today, so `^self` inherits it. Baseline for NEW = the
merged menu *at first ballot*; only later additions (repo OR any plugin's `+self`) count as NEW, so a
mid-stack plugin update and a repo update surface identically.

---

## Text syntax — examples

```hu
# Problem 3 — pinned picks, parent growth OFFERED not applied:
ts-ai-tools: [ "^ai-tools"  claude-code  ollama  ~aider  ~codex ]
#               └ menu       └── picks ──┘        └ declines ┘
# repo adds `goose` -> NEW badge, NOT installed

# Problem 1 — pin your own name over the repo profile (^self), keep its menu live:
dev-tools: [ "^dev-tools"  gh  git  lazygit  jq  just  obsidian  ~perf  ~jenkins ]
# repo adds `grex` to dev-tools -> NEW in YOUR dev-tools; nothing installs

# subprofile auto-extension is automatic (menu is transitive); choose the relationship per sub:
ts-languages: [ "^languages"  +python-lang  "^c-cpp-lang" gdb cmake ninja  zig odin  ~jvm-lang ]
#               menu(all)      live-whole    derive-within + picks           picks    open-decline
```

Rejected alternatives: a structured dict form (`{ menu:, pick:, pass: }`) — self-documenting but
forces every consumer to branch on list|dict shape and doesn't fit ordered mixed terms; keep it in
the back pocket for the day a derivation needs per-menu options (Alt A migrates to it mechanically).

---

## TUI design (all of it doable there)

**Ballot view.** Star a derived profile → its catalog becomes a ballot (reuses `_include_closure` +
the `*` star machinery, taught to chase `^`; `vcatalog`'s allowed-set gains the third state):

```
┌ profiles ──────────────┐┌ components — in "ts-ai-tools"  ^ai-tools  2 new ─┐
│ ● ts-desktop      ⁺2   ││ ▸● claude-code  native │ ?? goose         NEW    │
│  ▸▾● ts-ai-tools  ⁺2   ││  ● ollama       script │ ?? crush         NEW    │
│ ○ ts-laptop           ││  ~ aider               │                          │
└────────────────────────┘└──────────────────────────────────────────────────┘
 ● picked   ~ declined   ? new (offered, not installed)      edits → configsys-user
```

- **Ballot key:** space cycles `? → ● → ~ → ?` (matches the attr-filter modal's `· ✓ ✗` convention),
  each press writing the term edit through the existing planner path (pick = add bare; decline =
  `~name`; clear = delete term). Un-picking lands on *declined*, not pending (turning something off
  must not re-badge it NEW).
- **NEW routing:** NEW items badge in place (catalog order, `menu_new` theme role) and **bubble a
  `⁺N` up the tree** so they're visible from whatever root you're looking at.
- **`req` annotation** (apt manual/auto borrow): an unpicked menu item that a pick's `requires:` pulls
  anyway shows `↳req` — "declining won't remove it; claude-code needs it." Kills the one residual
  surprise (declined-but-present-via-dependency); reuses the resolver's dependents data.

**Reconcile overlay** (a `!`-adjacent `review` action, suggested key `N`): triage all NEW across
active profiles at once, grouped by source, with a first-class **"later"** (the badge persists;
nothing nags harder than a count) and the collapsed **auto-declined** section for open declines.

**Create a derivation** (`derive` action, suggested key `^`, mirroring `+`=include): name field
pre-filled with the parent's own name so **"pin in place" is the one-key default** and "renamed copy"
is the deliberate act (inverting today's incentive toward `ts-*`). `start-full` = clone-and-cull
replacement; `start-empty` = pick-from-catalog. A `writes: …` preview shows the exact term list.
Offer `derive` on a subprofile node too (converts a wholesale include into an in-place derivation).

**Pin-or-track modal (the Problem-1 fix).** First time a membership edit targets a profile whose top
definition is in a non-editable layer (the case where `+self` is synthesized today), interpose ONE
modal naming the relationship and **showing the exact text to be written**:

```
┌ dev-tools is defined by the repo (config.hu) ───────────────────────┐
│ Your edit saves to configsys-user (your primary plugin).            │
│ ▸ TRACK (+dev-tools)  repo changes apply automatically; future      │
│         repo additions WILL install.                                │
│   PIN   ("^dev-tools") you pick; repo changes are offered as NEW,    │
│         never applied.                                               │
│ writes: dev-tools: [ "^dev-tools"  gh git lazygit ... obsidian ]     │
└──────────────────────────────────────────────────────────────────────┘
```

A `profile-edit-mode: track|pin|ask` machine setting (uniform nature) skips it once decided; default
`ask`. PIN seeds picks with the current effective members, so behavior is identical *today* and only
diverges when the repo moves — exactly when you want to be asked.

**`where` for profiles** (provenance): infobox + `configsys where -p dev-tools` showing each layer's
definition, the relation (pinned/tracked/shadowed), and `members/menu/declined/new` counts. Plus a
one-glyph provenance badge in the profiles pane (below).

---

## Problem 2 — the `ts-*` pile

- **The derive primitive dissolves most renames.** They exist because (a) fear that editing a default
  corrupts it — already false (the layer stack never writes the repo), just invisibly false, which
  the modal + `where` fix; (b) fear of `+parent` auto-inclusion — fixed by `^`. So `ts-ai-tools`
  collapses to a same-named pinned `ai-tools:` in the primary. The genuine composition roots
  (`ts-desktop`/`ts-laptop`) stay — not clutter.
- **Layer-grouped profiles pane** with provenance badges: group by the top definition's layer (this
  machine · your primary · repo-catalog collapsed-by-default). Badge column: (blank) repo-untouched ·
  `^` pinned · `+` tracked · `⊘` shadowed (the `⊘` doubles as a nudge to convert a full shadow into a
  pin). Keep a flat-sort toggle for muscle memory.
- **(Deferred) `machines:` section** in the primary: `machines: { ts-laptop: [ user dev-tools ] … }`
  + a `machine: ts-laptop` setting per box; precedence local `configs:` > `machines:[machine]` > repo
  `configs:`, surfaced in the Config provenance row. Payoff: a fresh box's top config is two lines;
  the primary is a fleet registry. Risk: a *second* profile-selection channel — must be surfaced or it
  violates clarity. Ship only after the derive work proves out.

Do NOT invent name-based namespacing (`machine/foo` keys, prefix parsing) — provenance grouping +
`machines:` cover it without a naming law.

---

## Rejected (with reasons)

- **Tags-as-profiles / attr-driven membership** — an upstream *retag* would silently change what
  installs (maximally opt-out; fails criterion 1; muddies the profiles⊥attrs orthogonality). Attrs
  stay filters.
- **State-dir "seen" baselines** (so plain `+includes` could badge NEW) — hidden per-machine state,
  doesn't travel with the primary, diverges across boxes, duplicates what declines express. The
  sync-time delta report covers the tracked case at the moment of change instead.
- **Date/version-stamped derives** (`^ai-tools@2026-09`) — needs versioned parents + a second time
  axis; the ballot makes it unnecessary.

---

## Recommended build order

Steps 1–3 dissolve all three stated problems; 4–6 are polish.

1. **DONE.** `^` semantics + `menu`/`NEW` computation + `check` lints. `_split_term` recognizes `^`;
   `_expand` skips it (zero members); `_layout` emits `('derive', ref)`. New `Config` API:
   `profile_menu` (⋃ members(^q); `^self` → next-lower layer), `profile_new` (menu − members −
   declines; open declines via `profile_removed`), `profile_derive_terms`, `is_derived`,
   `check_derives`. `check`: undefined-`^` error, `^p`-alongside-`+p` warning, subsumed-`^` warning,
   and menu-`~` exemption from "removes nothing". Sigil authored quoted (`"^p"`). Tests in
   test/test_profile_derive.py (15). No behavior change to existing (`^`-free) profiles.
2. **DONE.** Ballot rendering + tri-state key + NEW badges + provenance. Catalog: a derived
   profile's OFFERED items render in a `menu_new` theme role marked `?` (● pick / ↳ inherited / ~
   decline stay); the `*` star filter surfaces the derive's menu (`_starred_menu`/`_starred_new`,
   `vcatalog.allowed` unions the menu). Space is a 3-state ballot on a derived profile's menu item —
   NEW→pick→decline→NEW (new `plan_membership_edit` actions `decline`/`clear`; `set_profile_membership`
   effect-check generalized) — a plain profile stays 2-state add/remove. Profiles pane: a `^` badge
   marks a ballot, `⁺N` counts offered items (`subtree_new` bubbles a derived subprofile's count up a
   `+include` parent). Catalog title reads `ballot "<p>"  ⁺N offered`. `_emit_profiles` quotes `^`
   terms so writes round-trip. Tests: test/test_profile_edit.py (ballot writers + ProfileScreen view
   + quoting round-trip) and a derived-ballot render smoke in test/test_tui_smoke.py.
3. **DONE.** Pin-or-track modal + `writes:` previews + `where` for profiles + `profile-edit-mode`
   setting. `plan_membership_edit` gained a `synth='track'|'pin'` arg: on the FIRST amend of a
   lower-layer-only profile, TRACK writes `+self` (historical), PIN writes `^self` seeded with the
   current effective members as picks (add appends the pick; remove snapshots-minus + `~decline`) so
   behavior is identical today and upstream growth is later OFFERED as NEW. `Config.profile_relation`
   (pinned/tracked/shadowed/base), `profile_amends_lower` (the synth predicate), `profile_layer_defs`,
   and `profile_edit_mode()` added. The TUI space handler interposes `_pin_or_track_modal` (naming
   both choices + the exact `writes: <p>: [...]` term list per selection) when the setting is `ask`;
   `track`/`pin` skip it. Profiles pane badge is now provenance (`^`pin/`+`track/`⊘`shadow) + `⁺N`
   offered; `w` opens a full-page profile-`where` (layers, relation, member/menu/declined/new counts),
   also `configsys where -p <profile>`. `profile-edit-mode: track|pin|ask` machine setting (uniform,
   default ask). Tests: planner synth + relation + amends-lower + edit-mode + where in
   test_profile_edit.py; a pin-or-track/where render smoke in test_tui_smoke.py.
4. **DONE.** Reconcile overlay + sync-time member-delta report. `configsys reconcile` (CLI) +
   the TUI `N`/`review` global overlay (`_run_reconcile`) triage OFFERED (NEW) items across the
   ACTIVE derived profiles (active + their `+include` closure), grouped by profile, each pickable
   (space)/declinable (d)/later (l), with a collapsible auto-declined section whose items re-offer
   (x). Shared data via `app.reconcile_data`/`reconcile_report`/`active_closure`. Plugin `sync`/
   `update` now print a member-delta (`app.active_snapshot`/`print_sync_delta`): TRACKED growth shows
   as `+/-` in the active set, PINNED growth as an "N new offering(s) — run reconcile" nudge (this is
   the no-baseline substitute for execute "(new via X)" tagging — the delta is reported at the moment
   of change). CLI gained `profile decline`/`offer` verbs and `--pin`/`--track` on `add`/`rm` (else
   the profile-edit-mode setting decides). Tests: test/test_reconcile.py + a reconcile-overlay render
   smoke in test_tui_smoke.py.
5. **5a DONE; 5b skipped (by decision).** Layer-grouped pane: the profiles pane now partitions roots
   by their top-definition layer into `this machine` / `your primary` / `plugins` / `repo catalog`
   (collapsed by default — the noise), each a fold header (enter/h/l), with `L` toggling back to the
   flat A-Z sort; a live filter forces all groups open. ProfileScreen gains `grouped`/
   `collapsed_groups`/`_profile_group`/`toggle_grouping`/`is_group_header`; `visible_pnodes` emits
   `_GKEY`-prefixed header rows; `cur_profile` returns None on a header. New `group: L` profiles
   keybinding. The `configsys profile pin` converter is NOT built as repo code — per the decision it's
   a run-once on the user's primary (hand-rolled when the `ts-*` pile is actually collapsed). Tests in
   test_profile_edit.py + smoke coverage (L toggle, repo-group unfold) in test_tui_smoke.py.
6. `machines:` section — now with a **working-target selector** (curate/plan ANY declared machine from
   any box; execute stays local-only). See the curation-model "Multi-machine authoring" note. No longer
   just per-box activation.
   - **v1 FOUNDATION DONE.** A machine is a COMPOSING LAYER, not a container: shared profiles live at the
     primary's top level (travel) and a `machines: { <name>: { configs?, profiles? } }` entry overlays
     them by name. `_inject_machine_layer` (config.py) splices the selected machine's profiles/configs in
     as a `machine`-role rung — above primary/plugins/repo, below the local top config — so `^self`/
     `+self`, `where -p`, reconcile and layer-grouping all flow through unchanged (`^graphics-tools` in a
     machine == `^self` over the shared one). `machine:` is a machine-nature setting (local; unset = no
     machine layer); `Config.selected_machine()`/`machines()`; `machine` added to `_MACHINE_ROLES` so a
     machine's `configs:` drives the active set (local `configs:` still overrides). Pane gains a `machine:
     <name>` group; `check` warns on a selected-but-undefined machine. Tests: test/test_machines.py.
   - **FAST-FOLLOW DONE.** The working-target selector + writers. `--machine <name>` global flag
     (Config.load override) curates/plans ANY machine from any box; `machines:` surgical writers
     (plugins.read_machines/set_machines); `configsys machine list|show|add|rm|use`; machine-scoped
     profile edits (`--machine X profile add|rm|decline|offer`) write into `machines:[X].profiles`
     (actions._set_machine_membership, planned against the machine rung via plan_membership_edit's
     `layer_idx`). TUI: `M` (`machine-target`) picks the target machine (rebuilds against its rung),
     edits scope to its namespace, status shows `edits → machine <name>`; pin-or-track flows through
     (`profile_amends_lower`/plan gained `layer_idx`). Tests: test/test_machines.py + a TUI selector
     smoke. Execute stays local-only. **Still deferred:** cloning one machine's set to seed another.

If only ONE thing ships: **`^self` + the pin-or-track modal** — it converts the #1 daily friction
(editing defaults; fear of corruption; surprise-on-update) into an explicit, visible act.

## A-hierarchical — `^aggregate` offers sub-profiles as tristate units  [grill 2026-09-08]

Grilled + LOCKED: **Q1 uniform structural `^`** and **Q4 algebra+CLI first**. Q2 (sub pick gesture)
and Q3 (TUI navigation) are TUI concerns, parked for the fast-follow with leanings recorded.

**Locked — the semantics change.** `profile_menu(^q)` becomes q's DIRECT CHILDREN: its `+sub` includes
as sub-profile UNITS + its bare components — NOT the flattened member set. A leaf `^p` (no sub-profiles)
still menus its components, so leaf derives are UNCHANGED. Recursion is emergent: deriving a sub-unit
(`^sub`) adds `sub`'s children to the menu in turn (verified: `^languages ^jvm-lang` → java-lang/
kotlin-lang/scala-lang appear as NEW sub-units). A `^`-derive inside the SOURCE is skipped (its own
curation), so deriving a derived profile still NARROWS to its structure. NEW is per-kind: a sub-unit is
NEW unless MENTIONED (`+sub`/`^sub`/`~sub`); a direct component is NEW unless a member (picked) or
`~`-declined — so a brand-new sub-profile upstream surfaces as a NEW unit, attributed to its level.

**v1 BUILT (algebra + CLI).** `Config._menu_structural` (subs, comps), `profile_menu_items`
(`{subprofiles, components}`), rewritten `profile_new` (new_subs = menu_subs − mentioned; new_comps =
menu_comps − members − declined). `reconcile`/`where -p` flag sub-units (`‹sub-profile — derive to
curate›` / `‹sub›`, menu count split subs+comps). Compat: two derive tests that asserted the old
flat-aggregate menu were updated to structural; no on-disk `^aggregate` exists, so nothing live
changed; the flat expansion is still reachable by deriving leaves (`pin_profile --structured`). Tests:
test/test_profile_derive.py (structural menu, recursion, new-sub detection, mention-removes-from-NEW).

**Q2 (parked, lean TRISTATE).** In the ballot, a sub-profile cycles `NEW → derive(^sub) → exclude(~sub)
→ NEW` — same gesture as a component (pick=derive). Include-WHOLE (`+sub`, track-live) is a deliberate
SECONDARY key, not a cycle stop (it's the opposite of the ballot's purpose and a one-keypress footgun).
Rationale: one mental model, `+` needs intent, fewer keys for the common decline. Lock at TUI-build.

**Q3 (parked, lean DRILL-DOWN).** A sub-unit row is distinct (`▸`/folder glyph + `⁺N`); enter/`l`
drills in (catalog becomes that sub's ballot, breadcrumb `languages › jvm-lang`); `h`/esc pops up.
Drilling into a NEW sub and picking inside auto-adds `^sub` ("explore then commit"). Left profile pane
unchanged; drill-down lives in the right catalog. Open (user flagged UI state/continuity to revisit):
breadcrumb jump-to-level; reconcile as an indented path vs a flat path column; an expand-to-NEW jump.

## Open questions
- **Ballot verbosity** on wide flat parents (pick 3 of 40 ⇒ many `~`, or many lingering NEW). Is the
  steady NEW-triage trickle welcome curation or friction? A per-profile "decline all current, keep
  offering future" bulk action helps but edges toward opt-out — design carefully.
- **Sigil** stays quoted `"^…"` until/unless humon frees `^`.
- **`machines:`** — worth the second selection channel? Defer and decide from real use.

---

## Curation model — "the profile IS the lockfile" (Model A)  [design, 2026-09-08]

Deep design pass (with the user, who authors the base profiles). Committed to **Model A**: a machine's
curation lives ENUMERATED in its own profile text — no companion lockfile, no hidden per-machine state.
Captured here so the reasoning survives; drives the remaining build (A-hierarchical + seeding).

**The one hard constraint.** To flag anything as NEW you need a stored baseline of what's "known", and
the algebra has exactly two honest places to keep it: (a) IN THE PROFILE TEXT (enumerated picks), or
(b) in a COMMITTED, diffable lockfile. Model A picks (a) — literally "the profile is the lockfile".
Everything else (a `=` snapshot sigil, concision) is ergonomics that only pays off under (b), which is
why a `=`-style term implies the `machines:`/lockfile world (part 6). We are NOT going there yet.

**Verb semantics — and where `^` lives.**
- `+profile` = a **definition** you inherit wholesale (tracks upstream growth; it auto-installs).
- `^profile` = a **menu of suggestions** you ballot against (opt-in; growth surfaces as NEW).
- So making `^` the norm RESTORES profiles to their original *suggestion* role — it is `+`, not `^`,
  that reifies a profile into a hard definition. **Decision: `^` is a CONSUMER / machine-layer verb and
  never appears in a shipped repo/base definition.** A base profile stays a concrete, usable bundle so
  `+` and composition keep working; the choice to treat it as a menu belongs to the machine that
  derives it. (Baking `^` into `languages` was tried and reverted — it zeroed the base's members and
  broke every `+languages` consumer.)

**Two kinds of NEW — this is what makes both user classes first-class.**
- **Profile-NEW** — a profile you `^`-track gained a member. INHERENTLY OPT-IN: you only get promotions
  for menus you chose to watch. The ballot / `reconcile` surface (built).
- **Catalog-NEW** — routes.hu gained a *component* (or a whole new profile appeared). Universe-relative,
  matters to everyone. The `orphans`/`request`/attrs surface — profile-INDEPENDENT.
- Class 1 (happy to curate the base profiles) lives on Profile-NEW. Class 2 (rejects the bases, builds
  crosscutting profiles) is served by Catalog-NEW and simply opts out of Profile-NEW by not deriving —
  correct, not a gap. You never "promote base membership" to a base-ignorer; you promote *catalog*
  additions through the profile-independent axis.

**The three onboarding workflows are three SEEDING strategies for a derivation's pick-set** — after
seeding, all three are the same steady-state ballot:
- new machine / new user → seed EMPTY, pick from the menu.
- old machine / new user (lots already installed) → seed FROM INSTALLED REALITY ("you have gcc/clang/
  cmake → pre-pick those; the rest of c-cpp-lang is NEW"). **This is the one missing primitive** — an
  adopt/orphans flow pointed at a `^`-derivation instead of a flat profile (call it *seed-from-installed*).
- established machine, repo just grew → derivations exist; `reconcile` shows Profile-NEW per menu (built).

**Sub-profile tristate ⇒ A-hierarchical (a GO).** `^`-inherited sub-profiles should be tristate
(include / exclude / NEW) exactly like components — because the base profiles are genuinely nested
(`languages → jvm-lang → java-lang`). Staging:
- **A-flat** (available today): derive at the LEAF profiles (`^c-cpp-lang`, `^java-lang`, …), skipping
  the aggregates. Full tristate on components now, no algebra change. The `pin_profile.py --structured`
  run-once already emits this shape.
- **A-hierarchical** (wanted): `^p` on an aggregate offers p's DIRECT children — sub-profiles as
  tristate *units* + bare components — instead of the flattened member set; picking a sub-profile unit
  offers include-whole (`+`) vs derive-and-recurse (`^`); recursion handles depth. A-flat is a strict
  subset, so nothing built for A-flat is wasted. This is the next real build.

**TUI gap to carry into A-hierarchical: a derived profile's `^`-menu sources are invisible.** They add
no members, so nothing in the pane/catalog shows *what a profile is watching*. Fine today, wrong for
A-hierarchical (where the `^`-menu IS the navigable structure). Surface the `^` parents as a first-class
part of the profile view — dim `^name` rows in the pane tree and/or a "watching:" line in the detail
box — so the ballot's provenance ("these are the menus I'm curating") reads at a glance. `where -p`
already lists them in text; the pane does not.

**Multi-machine authoring (reshapes `machines:`, part 6).** A user curates SEVERAL machines' profile
sets, not just the box they're on, and needs to pick which one they're "jamming on". This turns
`machines:` from an activation registry into a multi-target authoring surface, and forces a split:
- **Active machine** — the physical box (`machine:` setting). Drives inspect/install/reconcile-that-run,
  and EXECUTE is local-only (you can't install on a box you're not sitting at; remote exec is out of scope).
- **Working / target machine** — which machine's curation you're editing, ANY declared one, independent
  of the box. Selecting a non-local target = a curate + PLAN/preview mode (edit its derivations + its
  active set, see what it WOULD install/what's NEW for it) — writes land in the primary (shared), so
  authoring ts-desktop from ts-laptop just works; only execute stays gated to the active machine.
Fits Model A cleanly — derivations already live shared in the primary; the selector only moves the
EDITING FOCUS. Consequence for the layer-grouped pane: the `this machine` group generalizes to
`target machine`, and a machine-picker (TUI selector + a `--machine <name>` CLI scope) gates which set
the Profiles/reconcile views act on. So `machines:` when built is NOT just per-box activation — the
working-target selector is core to it.
