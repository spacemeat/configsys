# Theming the TUI

The whole TUI palette is yours. A `theme:` section in your config
(`~/.config/configsys/configsys.hu`) — or a theme **plugin** — sets the colors and the per-page
background gradients. Everything has a built-in default; you override only what you care about,
and you can do it **live** on the Theme screen (nav key `6`).

The model is two tiers:

- a shared **color map** — `colors:` maps a **name → #rrggbb**; and
- **pages** — `pages.<page>` gives each screen's **roles** a style `{ fg, bg, bold, underline,
  reverse }` where **fg/bg name a map color or are a literal**, plus that page's **gradient**.

```humon
theme: {
    colors: {                                    // the shared map (list 1 in the editor)
        accent:  "#c88cf0"
        ink:     "#dcdcdc"
        ink_dim: "#9a9a9a"
        green:   "#5ac878"
    }
    pages: {
        components: {                            // per-page roles (list 2; a-e cycles pages)
            component: { fg: ink }               // fg references a map color…
            driver:    { fg: ink_dim }
            selection: { fg: "#ffffff"  bg: accent  bold: true }   // …or bg does; literals work too
            installed: { fg: green }
            gradient:  { from: "#160a22"  to: "#050208" }
        }
        profiles: { gradient: { from: "#08221e"  to: "#020806" } }   // just a different backdrop
    }
}
```

Retinting one map color re-tints every role that references it — that's the point of the map.

## Where it lives, and precedence

`theme:` is purely **cosmetic**, so — deliberately — **any layer can contribute it**, deep-merged
per map-color and per page-role across the full stack:

> **repo < plugins < primary < discovered < your top config**

Later wins, so *your* config always has the last word. A theme-only plugin (just a `theme:` block)
applies whether you declare it directly or your **primary** plugin links it. Because the merge is
per key, you can adopt a theme plugin wholesale and still retune one color or one page-role on top.

Save your current look as a theme plugin from the Theme screen (`s`), or `configsys theme save
<name>`; load one with `L` / `configsys theme load <name>`.

## Color values

Anywhere a color value is expected (a `colors:` entry, or a role fg/bg literal), three forms work:

| form | example |
|------|---------|
| hex  | `"#c88cf0"`, short `"#abc"` |
| rgb list | `[ 200, 140, 240 ]` |
| rgb string | `"200,140,240"` |

## `colors:` — the shared map

`colors:` maps **any name** to a color. Override a built-in name or invent your own to reference
from `pages`. The built-in names:

`header` · `title` · `accent` · `dim` · `ink` · `ink_dim` · `installed` · `outdated` · `partial` ·
`missing` · `locked` · `unsupported` · `untrusted` · `error` · `op_install…op_unlock` · `sel_bg`

## `pages:` — per-screen role styles + gradient

Each page is one screen: `components`, `profiles`, `plugins`, `dotfiles`, `config`. Under a page,
every key is a **role** except the reserved **`gradient`**. A role's value is a style:

- **`fg` / `bg`** — a **color-map name** (`ink`, `accent`, …) or a literal (`"#rrggbb"`). Omit `bg`
  and the role sits on the page's gradient background; give it one for a solid chip.
- **`bold` / `underline` / `reverse`** — `true`/`false`.

A role you don't mention inherits its built-in default (uniform across pages), so a page's block
only lists what *differs* — per-page divergence is opt-in. `selection` is the cursor row; its `bg`
is the selected-row bar. The roles:

`label` · `os` · `menu_header` · `select_marker` · `profile` · `link` · `component` · `unit` ·
`driver` · `scope` · `scope_choice` · `version` · `row_error` · `methods` · `info` · `info_dim` ·
`status_line` · `footer` · `selection` · `installed` · `outdated` · `partial` · `missing` ·
`locked` · `unsupported` · `untrusted` · `error` · `op_install…op_unlock` · `op_mixed` ·
`issue_error` · `issue_warning`

## `gradient:` — a page's background

A dark diagonal wash behind that page (top-left → bottom-right). **Every page has a distinct
default** (purple / teal / blue / amber / indigo), for the whims.

```humon
gradient: { from: "#160a22"  to: "#050208" }
```

- `from` / `to` — the diagonal endpoints.
- The step count is **adaptive** — one shade per distinct 8-bit level across your range — so a
  wider range renders a smoother ramp. Keep both endpoints dark so it never fights the text.
- `gradient: false` (or `gradient: { enabled: false }`) turns that page's background off.

**24-bit only.** The gradient is painted only on a terminal that can render true color — either a
direct-color terminal (`TERM=*-direct`) or one that allows palette redefinition
(`init_color`/`can_change_color`, e.g. `xterm-256color` with the `ccc` capability). Otherwise the
background is left default; foreground colors still apply, cube-approximated. The Theme screen
shows the **detected color mode** (`direct 24-bit` / `24-bit` / `256-color (approx)` / `8-color`)
so you can tell what your terminal gave us.

## The Theme screen (key 6)

- **Top-left — the color map**: name → swatch + hex, laid out in **two columns** when the panel is
  wide enough. `↵` set a color, `n` add, `x`/`r` remove an override. `h`/`l` move between columns.
- **Bottom-left — the focused page's roles**: only the roles *that page actually uses*, each with
  its fg/bg refs + effects; the list swaps as you cycle pages. It also lists the two **gradient
  endpoints** (`gradient from` / `gradient to`) as single-color rows — edit them like any role
  (a map name or `#hex`), no bg/effects. `↵` set fg, `B` set bg, `o`/`u`/`v` toggle
  bold/underline/reverse, `r` reset the role on this page.
- **`Tab`** toggles focus between the two lists (`h`/`l` also cross the boundary); **`a`–`e`** cycle
  which page you're editing; **`p`** toggles the focused page's gradient on/off.
- **Right — the sample page**: a mock of that *actual* screen (its layout + its own roles) in the
  page's colors + gradient, so cycling shows a faithful, distinct preview. Edits repaint live.
- **`s` save** opens a destination picker: **into primary plugin** (writes the look into your
  primary plugin's data file, so it travels/versions with the rest of your config — shown only when
  a primary is blessed + synced), **local config** (this machine's top config), or **standalone
  theme plugin** (a named pack, loadable later with `L`). **`L`** loads a saved theme plugin.
- The status line shows the **detected terminal color mode** — if it reads `256-color (approx)`
  rather than `24-bit`, color collapse/collisions are your terminal quantizing, not the theme.
