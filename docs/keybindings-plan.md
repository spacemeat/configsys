# Configurable keybindings — plan

**Goal.** Let the user rebind TUI keys from a humon file in their primary config (no TUI editor).
Share generic navigation (`h/j/k/l`, `g/G`, arrows, `PgUp/PgDn`, `Tab` to switch panes, …) across every
screen, plus per-page action keys. The key legend/footer must reflect the active bindings.

## Locked decisions (user, 2026-08-21)

1. **The base keymap is humon, layer-merged like `theme:`** — NOT a Python `DEFAULT_KEYMAP` dict. It
   lives as a `keys:` section in the repo's `config.hu`; `Config.keys()` merges it up the stack
   (repo < plugins < primary < top config) per action.
2. **Primary keys share the primary plugin's `configsys.hu`** — a `keys:` block sits beside
   `profiles:`/`components:`; no separate file needed. (Falls straight out of #1: keys are
   contributed by any layer, like theme.)

## Progress

- **DONE (commit pending):** `tui/keyspec.py` (`parse_key`/`key_name`/`Keymap`), the `keys:` section
  in `config.hu` (`screens` + `global` scopes), `Config.keys()` layer-merge, `configsys keys` CLI,
  tests. Wired the truly-global keys — **quit / issues / screen-switch** — through the keymap, and the
  nav-bar legend now reads from it. Generic nav + per-page actions are DECLARED in `global:` but still
  enforced by the (unchanged) hardcoded per-screen handlers.
- **TODO:** wire each screen's block to `keymap.action_for(scope, ch)` — one screen per commit
  (components, profiles, plugins, dotfiles, config, theme) — moving its keys into a per-page `keys:`
  scope and generating its footer legend from the map. Then `check` lint for bad action/key names +
  conflicts.

## Current state (what we're refactoring)

- The event loop in `menu.run()` (~`configsys/tui/menu.py:3168`+) dispatches on RAW key codes —
  **122** `ch == ord('x')` / `ch in (ord('x'), curses.KEY_…)` checks, grouped as: a **global** block
  (every screen, ~`:3303`) then per-screen blocks — profiles `:3340`, dotfiles `:3485`, plugins
  `:3553`, config `:3684`, theme `:3793`.
- Legends are **hardcoded strings** scattered through the draw functions: `_draw_nav` (the screen-tab
  chip bar), and per-screen `nav`/`nav1`/`nav2`/`navf`/`legend`/`status_line` literals
  (`:952`, `:2112`, `:2302`, the `_SAMPLES` `nav` entries, the sample-page footers, …). Nothing ties a
  legend to the code that actually handles the key — they drift (the user already noticed casing/order
  nits).

## Design

Dispatch on **actions**, not keys. A `Keymap` resolves `(screen, key_code) → action`; the loop
switches on the action. Legends are generated from the same map, so they can't drift.

### 1. Action inventory (the contract)

Enumerate every handled key today and give it a stable **action id** + **scope**:

- **global** (all screens): `down up left right page-down page-up top bottom switch-pane
  next-screen prev-screen screen-1..screen-6 quit issues find find-next help`.
- **components**: `mark-install mark-upgrade mark-remove mark-lock mark-unlock clear-mark
  select-all apply method-picker change refresh where …`.
- **profiles**: `toggle-member star toggle-include reveal-removed delete-profile new-profile
  attr-filter scroll-left scroll-right …`.
- **plugins**: `sync sync-all bless bless-all update update-all set-ref trust trust-all add remove
  focus-diff …`.
- **dotfiles**: `link capture migrate link-all capture-all migrate-all discard …`.
- **config**: `edit move-setting …`.
- **theme**: `set-color save cycle-page-a..f …`.

Deliverable: a `DEFAULT_KEYMAP = { scope: { action: [key, …] } }` that reproduces **today's bindings
byte-for-byte**, plus an `ACTIONS = { scope: { action: "short legend label" } }` table (label +
optional ordering weight) driving the footer text.

### 2. Key spelling ⇄ code (`configsys/tui/keyspec.py`, new, pure/no-curses-at-import)

- `parse_key(name) -> int | None`: letters (`a`, `A`), digits, `enter`/`ret`, `tab`, `esc`,
  `space`, `up/down/left/right`, `pgup/pgdn`, `home/end`, `backspace/del`, `ctrl-<x>` (→ `x & 0x1f`),
  `f1..f12`. Names are case-insensitive except bare single letters (which ARE case-sensitive — `g`
  vs `G`).
- `key_name(code) -> str`: inverse, for legends (`curses.KEY_DOWN → "↓"`, `9 → "tab"`, `ord('/') →
  "/"`). Prefer glyphs (`↑↓←→ ⏎`) where they read well.
- `Keymap`: built from `DEFAULT_KEYMAP` overlaid by the user's `keys:` section. API:
  `action_for(screen, code) -> str | None` (page scope wins over global), `keys_for(screen, action)
  -> [code]`, `legend_items(screen) -> [(keyglyph, label)]` (ordered by the ACTIONS weight).

### 3. Config plumbing

- `keys:` in the user/primary config. Two tiers — `keys.global` and `keys.<page>` — each `action ->
  a key or list of keys`:
  ```
  keys: {
    global:     { down: [ j  down ]   up: [ k  up ]   left: h   right: l
                  page-down: [ pgdn  ctrl-f ]   top: g   bottom: G
                  switch-pane: tab   find: /   quit: q   issues: "!" }
    components: { mark-install: i   mark-remove: [ r  del ]   apply: enter }
    profiles:   { star: "*"   toggle-member: [ enter  space ] }
  }
  ```
- `Config.keys()` — layer-merge the `keys:` section like `theme()` (repo defaults are code, not
  data; user layers overlay per action). A user only spells the actions they want to change.
- Build one `Keymap` at TUI start (in `run()`), thread it into the draw + dispatch.
- **`check` lint**: unknown action id, unparseable key name, and same key bound to two actions in one
  scope (page+its globals) → a warning with the offending line's provenance.

### 4. Refactor the event loop (the bulk — do it incrementally)

Replace `if ch == ord('i'):` with `action = keymap.action_for(screen, ch)` then `if action ==
'mark-install':`. Order: global block first, then one page at a time, each landing as its own commit
with the smoke test green. `DEFAULT_KEYMAP` guarantees no behavior change. Watch the interleaving
(`continue`/fallthrough, order-dependent checks like `!` vs a page's own `!`), and the modal
shortcuts (`_popup_choose` — leave as-is, or later feed it from the keymap too).

### 5. Generate legends from the keymap

Replace the hardcoded `nav`/`navf`/`legend` strings with
`" · ".join(f"{glyph} {label}" for glyph, label in keymap.legend_items(screen))`, split across the
one/two footer rows as today. `_draw_nav`'s tab chips stay (they're screen-switch, not rebindable —
or bind them to `screen-1..6` and render from `keys_for`). The marker legend (●◐○ etc.) is separate
and unchanged. This is where the casing/order nit gets fixed for free — labels live in one table.

### 6. Tests

- `keyspec`: `parse_key`/`key_name` roundtrip; case sensitivity of bare letters; `ctrl-*`.
- `Keymap`: page overrides global; multi-key actions; unknown-action/bad-key handling; **`DEFAULT_KEYMAP`
  reproduces the exact current bindings** (guard against drift during the refactor).
- `Config.keys()` layer merge; `check` catches conflicts/typos.
- PTY smoke: a user config that remaps (e.g. `quit: x`) actually quits on `x`; legend shows `x`.

### 7. Discoverability (no TUI editor, per the ask)

- `configsys keys [--defaults]` CLI: prints the effective bindings per screen (and which layer set
  each), so a humon-only user can see what's active without a UI.
- Document the schema in the config-template comment + `docs/keybindings.md`.

## Phasing / sequencing

1. `keyspec.py` + `DEFAULT_KEYMAP` + `ACTIONS` + tests (no wiring yet — pure, safe).
2. `Config.keys()` + `Keymap` build + `check` lint + `configsys keys` CLI.
3. Legend generation from the keymap (visible win, low risk — swap the strings).
4. Event-loop dispatch refactor, **one screen per commit**, smoke-green each.
5. Docs + template comment.

## Risks / open questions

- The event loop is long and stateful; the refactor is mechanical but easy to get subtly wrong.
  Mitigate with the byte-identical `DEFAULT_KEYMAP` test + incremental commits.
- Some keys are context-sensitive within a screen (focus == left/right pane changes what `h/l` do).
  The action model handles this: `h/l` map to `left/right`, and the handler already branches on
  focus. No per-focus keymaps needed initially.
- Modal/`_popup_choose` keys and the theme editor's `a-f` page cycle: keep hardcoded for round one;
  fold into the keymap later if wanted.
- **Parked**: chords/sequences (`g g`), per-OS or per-terminal key profiles — not now.
