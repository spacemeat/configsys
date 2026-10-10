# Theming the TUI

> **Status: REFERENCE** — the `theme:` section, the Theme editor screen, color depth and motion;
> maintained.

The whole TUI palette is yours. A `theme:` section in your config
(`~/.config/configsys/configsys.hu`) — or in a theme **plugin** — sets the colors and each page's
background gradient. Everything has a built-in default; you override only what you care about, and
you can do it **live** on the Theme screen (nav key `7`, or `t` on the Config screen).

The model is two tiers:

- a shared **color map** — `colors:` maps a **name → #rrggbb**; and
- **pages** — `pages.<page>` gives each screen's **roles** a style `{ fg, bg, bold, underline,
  reverse }`, where **fg/bg name a map color or are a literal**, plus that page's **gradient**.

```humon
theme: {
    colors: {                                    // the shared map (top-left list in the editor)
        accent:  "#c88cf0"
        ink:     "#dcdcdc"
        ink_dim: "#9a9a9a"
        green:   "#5ac878"
    }
    pages: {
        components: {                            // per-page roles (bottom-left list; F1-F7 pick the page)
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

Retinting one map color retints every role that references it — that's the point of the map.

## Where it lives, and precedence

`theme:` is purely **cosmetic**, so — deliberately — **any layer can contribute it**, deep-merged
per map color and per page role across the full stack:

> **repo < plugins < primary < your top config**

Later wins, so *your* config always has the last word. A theme-only plugin (just a `theme:` block)
applies whether you declare it directly or your **primary** plugin brings it in. Because the merge
is per key, you can adopt a theme plugin wholesale and still retune one color or one page role on
top.

From the command line:

| Command | What it does |
| --- | --- |
| `configsys theme show` | the theme overrides currently in effect |
| `configsys theme set <key> <value> [--local]` | set one value: `colors.<name>`, `pages.<page>.<role>.<fg\|bg\|bold\|underline\|reverse>`, or `pages.<page>.gradient.<from\|to\|enabled>` |
| `configsys theme unset <key> [--local]` | remove one value |
| `configsys theme save <name> [--force]` | snapshot your complete look into a shareable theme plugin |
| `configsys theme list` | the saved theme plugins |
| `configsys theme load <name> [--local]` | apply a saved theme plugin, replacing your theme overrides |

Edits go to your primary plugin when you have one (so your look travels), else to this machine's
config; `--local` always writes this machine's config.

## Color values

Anywhere a color value is expected (a `colors:` entry, a role fg/bg literal, a gradient endpoint),
three forms work:

| form | example |
|------|---------|
| hex  | `"#c88cf0"`, short `"#abc"` |
| rgb list | `[ 200, 140, 240 ]` |
| rgb string | `"200,140,240"` |

## `colors:` — the shared map

`colors:` maps **any name** to a color. Override a built-in name or invent your own to reference
from `pages`. The built-in names:

`header` · `title` · `accent` · `dim` · `ink` · `ink_dim` · `installed` · `outdated` · `partial` ·
`missing` · `locked` · `unsupported` · `untrusted` · `error` · `switch` · `unmet` · `dangling` ·
`orphan_lurking` · `op_install` · `op_upgrade` · `op_remove` · `op_lock` · `op_unlock` · `sel_bg` ·
`row_desc` · `method_dim` · `dep_dim` · `menu_new`

## `colors-basic:` — the 8/16-color look

On a terminal limited to 8 or 16 colors, squeezing the 24-bit map into a handful of ANSI hues
muddies everything, so each built-in color name is pinned to a hand-picked ANSI color instead.
`colors-basic:` overrides that choice per map name, using `black`, `red`, `green`, `yellow`, `blue`,
`magenta`, `cyan`, `white`, their `bright-` forms, `grey`, `default` (the terminal's own color), or
a slot number 0–15:

```humon
theme: {
    colors-basic: { accent: bright-cyan  sel_bg: blue }
}
```

It has no effect at 256 colors or above.

## `pages:` — per-screen role styles + gradient

Each page is one screen: `components`, `profiles`, `plugins`, `glue`, `dotfiles`, `config`,
`theme`. Under a page, every key is a **role** except the reserved **`gradient`**. A role's value
is a style:

- **`fg` / `bg`** — a **color-map name** (`ink`, `accent`, …) or a literal (`"#rrggbb"`). Omit `bg`
  and the role sits on the page's gradient background; give it one for a solid chip.
- **`bold` / `underline` / `reverse`** — `true`/`false`.

A role you don't mention keeps its built-in default (the same on every page), so a page's block
lists only what *differs*. `selection` is the cursor row; its `bg` is the selected-row bar. The
roles:

`label` · `os` · `issue_error` · `issue_warning` · `menu_header` · `select_marker` · `profile` ·
`link` · `component` · `unit` · `driver` · `scope` · `scope_choice` · `version` · `row_error` ·
`methods` · `method_dim` · `dependents` · `menu_new` · `row_desc` · `info` · `info_dim` ·
`status_line` · `footer` · `selection` · `installed` · `outdated` · `partial` · `missing` ·
`locked` · `unsupported` · `untrusted` · `error` · `switch` · `unmet` · `dangling` ·
`orphan_lurking` · `op_install` · `op_upgrade` · `op_remove` · `op_lock` · `op_unlock` ·
`op_mixed` · `diff_add` · `diff_del` · `diff_hunk` · `diff_meta`

A few of them, by what they color:

- **status roles** (`installed` … `error`) color a component's status. `switch`, `unmet` and
  `dangling` are the routing statuses — an install whose method routes no longer offer, a
  component only a disabled driver could install, and one with no method on this OS.
- **`orphan_lurking`** marks, on the Profiles page, a component that is installed but not picked
  for this machine, and one staged for uninstall. One you've told configsys to ignore
  (`orphans-ignore`, `.` on Profiles) gets its `⊙` marker in **`info_dim`** instead.
- **`method_dim`** / **`dependents`** — the install-method label and the "required by" line in
  the Profiles detail pane; **`menu_new`** — offered (new) profile items; **`row_desc`** — the
  faded description after a row's name.
- **`op_*`** — staged-operation badges (`op_mixed` for a row whose parts have different staged
  operations).
- **`diff_*`** — the Plugins page's update diff: added and removed lines, hunk headers, file
  metadata.

## `gradient:` — a page's background

A dark diagonal wash behind the page (top-left → bottom-right). **Every page has a distinct
default** — purple, teal, blue, green, amber, indigo and rose — for the whims.

```humon
gradient: { from: "#160a22"  to: "#050208" }
```

- `from` / `to` — the diagonal endpoints: a map color name or a literal.
- The step count is **adaptive** — one shade per distinct 8-bit level across your range — so a
  wider range renders a smoother ramp. Keep both endpoints dark so the gradient never fights the
  text.
- `gradient: false` (or `gradient: { enabled: false }`) turns that page's background off.

The gradient is painted only with **24-bit color** and **full motion** (see below). Otherwise the
background is left at the terminal default; foreground colors still apply, approximated to what the
terminal can show.

## Color depth and motion

configsys detects what your terminal can render; these let you override it.

| Control | Effect |
| --- | --- |
| `--color auto\|24bit\|256\|16\|8\|none` (or `CONFIGSYS_COLOR`) | caps the color depth. It only lowers the detected depth — except `24bit`, which forces direct RGB even without `COLORTERM`. `16` uses the hand-tuned bright ANSI set (`colors-basic`); `8` forces the base 8. |
| `--nocolor` / `--no-color`, or `NO_COLOR` set to anything | monochrome: no colors or gradient and no splash; reverse video and bold still mark the cursor and headers. |
| `--effects full\|reduced\|none`, or the `effects:` setting | motion: `full` = gradient + splash, `reduced` = no gradient and a calmer splash, `none` = neither. Unset, it picks `reduced` over SSH and `full` otherwise. The flag overrides the setting. |
| `configsys --probe` | prints the resolved color mode and motion and why (including the TERM curses actually uses), then exits. Honors the flags above. |

**Direct color is preferred.** Most truecolor terminals still say `TERM=xterm-256color` and
advertise 24-bit through `COLORTERM=truecolor`. When they do — or another sign says so (a TERM
like `xterm-kitty`/`alacritty`/`foot`/`xterm-ghostty`, which survives SSH where `COLORTERM`
doesn't; `TERM_PROGRAM`/`LC_TERMINAL` such as iTerm2 or WezTerm; Windows Terminal, Konsole, VTE ≥
0.52), or you pass `--color 24bit` — configsys starts curses against the sibling `-direct` terminfo
entry (`xterm-direct`, `foot-direct`, …), so colors go out as real 24-bit escape codes. Those
entries ship in `ncurses-term`, which fresh Debian/Ubuntu/Pop!_OS installs lack; then configsys
builds one itself (from `$TERM` plus the direct-color capabilities, honoring a terminal's private
`TERMINFO` such as kitty's) into `~/.cache/configsys/terminfo`, in pure Python or with `tic` —
so minimal containers without ncurses tools work too. Inside tmux direct color is used as well
(tmux downconverts for an outer terminal that can't show it); GNU screen keeps `$TERM`.

Without any truecolor sign (or with a Python curses limited to 256 colors, such as macOS's system
Python), configsys falls back to redefining palette slots. That is fragile: a terminal that
ignores palette redefinition (COSMIC's terminal, for one) shows its stock 256-color cube in those
slots, so every color comes out wrong.

The Theme screen's status line shows the **detected color mode** — `direct 24-bit`, `24-bit`,
`256-color (approx)`, `16-color`, `8-color`, or `none (monochrome)`. If it reads
`256-color (approx)` rather than 24-bit, colors that collapse or collide are your terminal
quantizing, not the theme.

## The Theme screen (key 7)

- **Top-left — the color map**: name → swatch + hex, in **two columns** when the panel is wide
  enough. `Enter` sets a color, `n` adds one, `x`/`r` removes an override. `h`/`l` move between
  columns.
- **Bottom-left — the focused page's roles**: only the roles *that page actually uses*, each with
  its fg/bg references and effects; the list swaps as you change pages. It also lists the two
  **gradient endpoints** (`gradient from` / `gradient to`) as single-color rows — edit them like
  any role (a map name or `#hex`). `Enter` sets fg, `B` sets bg, `o`/`u`/`v` toggle
  bold/underline/reverse, `r`/`x` reset the role on this page.
- **`Tab`** switches between the two lists (`h`/`l` also cross between them); **`F1`–`F7`**
  select which page you're editing (the `theme.page-1` … `page-7` keybindings, rebindable via
  `keys:`); **`p`** toggles the page's gradient on or off; **`D`** copies this page's styles and
  gradient onto another page.
- **Right — the sample page**: a mock of that *actual* screen (its layout and its own roles) in the
  page's colors and gradient, so changing pages shows a faithful preview. Edits repaint live.
- **Edits save as you go** — every color, role, or gradient edit is written as a *difference from
  the defaults* to your primary plugin (or, with no primary, this machine's config), shown in the
  status line. So your theme already lives in the right place, and theme plugins still show
  through the parts you haven't touched. `s` is only for deliberate **full-snapshot** saves:
  - **export theme pack…** — writes the *complete* look (every map color, every page role, the
    gradients) to a named theme plugin, loadable later with `L` and shareable. A full snapshot
    reproduces exactly even if the built-in defaults change later.
  - **promote full theme → primary** (only when a primary plugin is blessed and synced) — writes
    the complete look into your primary and removes the local copy. This is deliberately
    **absolute**: a full theme in the primary overrides any theme plugin, so it asks first.
- **`L`** loads a saved theme plugin, replacing your theme overrides — retune on top afterwards.
