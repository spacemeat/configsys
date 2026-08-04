# Theming the TUI

The whole TUI palette is yours. A `theme:` section in your config
(`~/.config/configsys/configsys.hu`) — or a theme **plugin** — sets the colors and the per-page
background gradients. Everything has a built-in default; you override only what you care about,
and you can do it **live** on the Theme screen (nav key `6`).

The model is two tiers:

- a **palette** — a name → full **style** (`fg` / `bg` / effects); and
- **pages** — each screen binds its **roles** to palette names and owns a background **gradient**.

```humon
theme: {
    palette: {
        accent: { fg: "#c88cf0"  bold: true }        // override a built-in style
        ink:    { fg: "#dcdcdc" }                     // …or define your OWN named style
        ink_dim:{ fg: "#9a9a9a" }
        sel:    { fg: "#f0f0f0"  bg: "#3a2258"  bold: true }
    }
    pages: {
        components: {
            roles: { component: [ ink  ink_dim ]  selection: sel }   // zebra rows + cursor bar
            gradient: { from: "#160a22"  to: "#050208"  selected: "#3a2258" }
        }
        profiles: { gradient: { from: "#08221e"  to: "#020806" } }   // just a different backdrop
    }
}
```

## Where it lives, and precedence

`theme:` is purely **cosmetic**, so — deliberately — **any layer can contribute it**, deep-merged
per palette-entry and per page across the full stack:

> **repo < plugins < primary < discovered < your top config**

Later wins, so *your* config always has the last word. Two consequences:

- **Theme plugins work — however they're wired.** A plugin whose whole job is a theme (just a
  `theme:` block) applies whether you declare it directly or your **primary** plugin *links* it.
  (Unlike `scope`/`pins`/`configs`, which only a `primary` may set — a theme only changes how the
  TUI looks, so it isn't trust-gated.)
- **You always override.** Because the merge is per key, you can adopt a theme plugin wholesale
  and still retune a single palette entry or one page's gradient on top of it.

Save your current look as a theme plugin from the Theme screen (`s`), or `configsys theme save
<name>`; load one with `L` / `configsys theme load <name>`.

## Color values

Anywhere a color is expected (a palette entry's `fg`/`bg`), three forms work:

| form | example |
|------|---------|
| hex  | `"#c88cf0"`, short `"#abc"` |
| rgb list | `[ 200, 140, 240 ]` |
| rgb string | `"200,140,240"` |

## `palette:` — named styles (an open map)

`palette:` maps **any name** to a style. A style is `{ fg  bg  bold  underline  reverse }` — `fg`
required, `bg` optional (omit it and the role sits on the page's gradient background; give it one
for a solid chip, like `label`/`selection`), effects are `true`/`false`. Override a built-in name
or invent your own to reference from `pages`. A bare color (`accent: "#c88cf0"`) is shorthand for
`{ fg: "#c88cf0" }`.

The built-in names (each reproduces today's look — override any):

`header` · `title` · `accent` · `dim` · `installed` · `outdated` · `partial` · `missing` ·
`locked` · `unsupported` · `untrusted` · `error` · `op_install…op_unlock` · `op_mixed` · `label` ·
`os` · `menu_header` · `select_marker` · `profile` · `link` · `component` · `unit` · `driver` ·
`scope` · `scope_choice` · `version` · `row_error` · `methods` · `info` · `info_dim` ·
`status_line` · `footer` · `issue_error` · `issue_warning`

## `pages:` — per-screen role bindings + gradient

Each page is one screen: `components`, `profiles`, `plugins`, `dotfiles`, `config`. A page has:

- **`roles:`** — a map of that page's UI role → a palette **name** (or a **list** of names, which
  zebra-stripes successive rows). A role you don't mention defaults to the **same-named palette
  entry** (identity), so a page's `roles:` only spells out what *differs*. This is why the built-in
  look is uniform and per-page divergence is opt-in.
- **`gradient:`** — that page's background wash (below).

The roles are the palette names above, in the context of that page. The ones you'll reach for
most: `component`/`unit` (row text), `selection` (the cursor bar — give it a `bg`), `menu_header`
(column headers), `driver`/`version`/`scope` (columns), the `installed…error` status colors, and
the chrome (`label`, `os`, `status_line`, `footer`).

```humon
pages: {
    components: {
        roles: {
            component:   [ ink  ink_dim ]     // alternate row colors
            selection:   sel                  // the highlighted row
            menu_header: header
            installed:   installed            // (identity — could be omitted)
        }
    }
}
```

## `gradient:` — a page's background

A dark diagonal wash behind that page (top-left → bottom-right). **Every page has a distinct
default** (purple / teal / blue / amber / indigo), for the whims.

```humon
gradient: { from: "#160a22"  to: "#050208"  selected: "#3a2258" }
```

- `from` / `to` — the diagonal endpoints; `selected` — the highlighted-row bar.
- The step count is **adaptive** — one shade per distinct 8-bit level across your range — so a
  wider range renders a smoother ramp. Keep both endpoints dark so it never fights the text.
- `gradient: false` (or `gradient: { enabled: false }`) turns that page's background off.

**24-bit only.** The gradient is painted only on a terminal that can render true color — either a
direct-color terminal (`TERM=*-direct`) or one that allows palette redefinition
(`init_color`/`can_change_color`, e.g. `xterm-256color` with the `ccc` capability). Otherwise the
background is left default (the 256-color cube is too coarse for dark purples); foreground colors
still apply, cube-approximated.

## The Theme screen (key 6)

- **Left** — the palette: each entry's swatch (in its own colors) + `fg`/`bg`/effects. `↵` sets
  `fg`, `B` sets `bg` (empty clears), `o`/`u`/`v` toggle bold/underline/reverse, `n` adds an entry,
  `r` resets one to the built-in default.
- **Right** — one live **sample page**: a mock full screen (chrome, columns, status colors, op
  badges, info/status/footer) rendered in the focused page's colors + gradient, so you see every
  color *in place*. `a`–`e` cycle which page it shows; `p` edits that page's gradient (from / to /
  selected / on-off).
- `s` save the current look as a theme plugin, `L` load one. Every edit repaints instantly.

## Tips

- Edit `theme:` (or use key 6), relaunch the TUI — no restart of anything else, no code changes.
- Role remapping (per-page `roles:`) is authored in the config today; the Theme screen edits the
  palette + gradients live. See `docs/theme-redesign.md` for the full model.
