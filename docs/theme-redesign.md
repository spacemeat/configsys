# Theme redesign — shared color map + per-page role styles

Reworks the `theme:` model to two tiers: a shared **color map** (`colors:` — name → #rrggbb) and
**per-page role styles** (`pages.<page>.<role>` → `{ fg, bg, effects }`, fg/bg referencing a map
name or a literal), each page owning a **background gradient**. Drives a standalone Theme screen
(nav key 6) with two editable lists (map + focused page's roles) beside one live sample page.

(Earlier iterations of this doc described a "named palette of full styles + per-page role→name
bindings". That collapsed into the current map+role-styles model — the map holds *colors*, roles
hold *styles that reference colors* — after the two-list editor made the split concrete.)

## Locked (decided)

- **Two tiers.** `theme.palette` maps a **name → full style** `{ fg, bg, bold, underline,
  reverse }` (fg/bg are literal colors — hex / `#rgb` / `[r,g,b]` / `"r,g,b"`). `theme.pages.
  <page>` binds that page's **roles → palette name(s)** and carries the page's **gradient**.
  ("Named roles per page" fork.)
- **Roles default to identity.** A role resolves to the palette entry of the *same name* unless
  the page remaps it. So a page's `roles:` only spells out what *differs* — the built-in look is
  uniform across pages, and per-page divergence is opt-in ("for the whims"). A role may map to a
  **list** of palette names → the renderer **zebra-stripes** rows by index (`row: [ink, ink_dim]`).
- **Per-page gradient.** Each page owns `gradient: { from, to, selected }` (or `false` to drop
  it). Built-in defaults give every page a **distinct dark hue** (purple / teal / blue / amber /
  slate / rose).
- **Pages** = the five content screens `components profiles plugins dotfiles config` (+ the Theme
  screen previews all five). Chrome roles (label, os, footer, nav, panel, status_line, …) are
  ordinary roles, identity-default, overridable per page.
- **Clean break.** New built-in defaults reproduce today's look. The old `theme.colors` /
  `theme.elements` schema is **ignored** (a `check` warning points at the new shape). No
  released userbase (clone-first, pre-0.1.0), so no migration path is kept.
- **Theme is its own nav screen** (key `6`), not a Config sub-screen — it's a different page even
  though it writes the same files.

## Schema

```humon
theme: {
    palette: {
        ink:      { fg: "#dcdcdc" }
        ink_dim:  { fg: "#9a9a9a" }
        selection:{ fg: "#f0f0f0"  bg: "#3a2258"  bold: true }
        header:   { fg: "#8ac8ff"  bold: true }
        installed:{ fg: "#5ac878" }
        // …users add their own names
    }
    pages: {
        components: {
            gradient: { from: "#160a22"  to: "#050208"  selected: "#3a2258" }
            roles: {
                component:  [ ink  ink_dim ]      // zebra rows
                menu_header: header
                installed:  installed             // (identity — could be dropped)
            }
        }
        profiles: { gradient: { from: "#08221e"  to: "#020806" } }   // just a different bg
    }
}
```

## Editor (Theme screen, key 6)

- Left: the **palette** (name → swatch + fg/bg/effects), editable; add/remove entries.
- Right: one **sample page** — a mock full screen (all representative fields) in the focused
  page's live colors + gradient; cycle which page it shows with `a`–`e`. Editing a palette entry
  or a page's gradient repaints instantly (re-instantiate `Palette`). One page at a time keeps
  color-pair usage bounded (a 5-page grid could exhaust a 256-pair terminal).
- **No random color** anywhere in the UI — only the startup splash's water is random. The splash
  allocates its random colors into the shared curses palette, so after it plays the menu rebuilds
  its `Palette` from a clean allocator; otherwise those colors leak in and vary run-to-run.
- Save/Load a theme **plugin** (unchanged mechanism — a plugin whose only content is a `theme:`).

## Open / deferred

- Reordering color-map entries (low value — built-in order is fixed; only user-added colors carry
  order in the file).

Done: per-role hex/ref **validation** (invalid input is rejected with a note), palette-name
**autocomplete** in the fg/bg/gradient inputs (Tab-complete with a dim ghost), and **duplicate a
page's look** onto another (`D`).
