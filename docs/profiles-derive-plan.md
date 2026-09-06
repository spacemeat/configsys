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
2. Ballot rendering + tri-state key in the starred view; NEW badges + `⁺N` bubbling; provenance badges.
3. Pin-or-track modal + `writes:` previews + `where` for profiles + `profile-edit-mode` setting.
4. Reconcile overlay + sync-time member-delta report + execute-confirmation "(new via repo X)" tagging.
5. Layer-grouped pane + a `configsys profile pin <name>` converter (clone-and-cull → pinned derivation). The converter does not need to be in repo code though; that's a run-once on user's primary, and user is still the only user of configsys.
6. `machines:` section.

If only ONE thing ships: **`^self` + the pin-or-track modal** — it converts the #1 daily friction
(editing defaults; fear of corruption; surprise-on-update) into an explicit, visible act.

## Open questions
- **Ballot verbosity** on wide flat parents (pick 3 of 40 ⇒ many `~`, or many lingering NEW). Is the
  steady NEW-triage trickle welcome curation or friction? A per-profile "decline all current, keep
  offering future" bulk action helps but edges toward opt-out — design carefully.
- **Sigil** stays quoted `"^…"` until/unless humon frees `^`.
- **`machines:`** — worth the second selection channel? Defer and decide from real use.
