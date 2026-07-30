# Theming the TUI

The whole TUI palette is yours. A `theme:` section in your config
(`~/.config/configsys/configsys.hu`) sets the colors, per-element styles, and the background
gradient. Nothing here is required — every value has a built-in default; you override only what
you care about.

```humon
theme: {
    colors: {
        accent:    "#c88cf0"          // override a built-in palette color
        my-purple: "#8a5cff"          // …or define your OWN name to reference below
    }
    elements: {
        profile:   { fg: accent  bold: true }
        os:        { fg: "#78c8ff"  underline: true }
        installed: { fg: "#5ac878" }
        label:     { fg: "#f0f0f0"  bg: my-purple  bold: true }
    }
    gradient: { from: "#160a22"  to: "#050208"  selected: "#3a2258" }
}
```

## Where it lives, and precedence

`theme:` is a **machine setting**, read from the same layer stack as `scope`/`pins`:
**repo < a `primary` plugin < your top config**, merged **per key** (your override of one color
doesn't wipe the rest). So a personal "primary" plugin — or, in the future, a plugin whose whole
job is to ship a theme — can set a base look, and this machine's config tweaks it. An ordinary
(non-primary) plugin cannot set machine settings, so it can't silently reskin your TUI.

## Color values

Anywhere a color is expected, three forms work:

| form | example |
|------|---------|
| hex  | `"#c88cf0"`, short `"#abc"` |
| rgb list | `[ 200, 140, 240 ]` |
| rgb string | `"200,140,240"` |

## `colors:` — the palette (an open map)

`colors:` maps **any name** to a color. Use it to override a built-in palette color *or* to define
new names you reference from `elements:`. The built-in names:

`header` · `title` · `accent` · `dim` · `installed` · `outdated` · `partial` · `missing` ·
`locked` · `unsupported` · `untrusted` · `error` · `op_install` · `op_upgrade` · `op_remove` ·
`op_lock` · `op_unlock`

## `elements:` — per-element style

Each element takes `fg`, `bg`, `bold`, `underline`, `reverse`. `fg`/`bg` may name a palette color
(built-in or your own) or be a literal color value; omit `bg` and the element sits on the gradient
background (give it a `bg` for a solid chip, like `label`). Booleans are `true`/`false`.

| element | what it styles |
|---------|----------------|
| `label` | the `configsys` chip (top-left) |
| `os` | the OS block + `[PRETEND]` on the top line |
| `issue_error` / `issue_warning` | the `⚠ N issues` badge (by severity) |
| `menu_header` | the column header row (`COMPONENT`, `FAMILY`, …) |
| `select_marker` | the `»` selection marker |
| `profile` | a profile row |
| `link` | an `+include` link row |
| `component` | a composite component row (expands to units) |
| `unit` | a leaf/unit row (also the default text color) |
| `family` | the driver/`FAMILY` column |
| `scope` / `scope_choice` | the `SCOPE` column (`_choice` = a non-default scope) |
| `version` | the `INSTALLED` / `LATEST` columns |
| `row_error` | an op-failure message on a row |
| `installed` `outdated` `partial` `missing` `locked` `unsupported` `untrusted` `error` | the `STATUS` column, by state |
| `op_install` `op_upgrade` `op_remove` `op_lock` `op_unlock` `op_mixed` | the staged-op badge |
| `methods` | the "install methods" line |
| `info` / `info_dim` | the two infoblock detail lines |
| `status_line` | the `selected:/staged:` line |
| `footer` | the two key-hint footer bars |

## `gradient:` — the menu background

A dark diagonal wash behind the menu (top-left → bottom-right):

```humon
gradient: { from: "#160a22"  to: "#050208"  selected: "#3a2258" }
```

- `from` / `to` — the diagonal endpoints; `selected` — the highlighted-row bar.
- The step count is **adaptive** — one shade per distinct 8-bit level across your range — so a
  wider range renders a smoother ramp automatically. Keep both endpoints dark so it never fights
  the text.
- `gradient: false` (or `gradient: { enabled: false }`) turns the background off.

**24-bit only.** The gradient is painted only on a terminal that can render true color — either a
direct-color terminal (`TERM=*-direct`) or one that allows palette redefinition
(`init_color`/`can_change_color`, e.g. `xterm-256color` with the `ccc` capability). Otherwise the
background is left default (the 256-color cube is too coarse for dark purples); foreground colors
still apply, cube-approximated.

## Tips

- Edit `theme:`, relaunch the TUI — no restart of anything else, no code changes.
- To move the *built-in defaults* (not just your overrides), see
  `configsys/tui/theme.py` (`SEMANTIC`, `ELEMENTS`, `GRAD_A`/`GRAD_B`, `SEL_BG`, `GRAD_MAX_BANDS`).
