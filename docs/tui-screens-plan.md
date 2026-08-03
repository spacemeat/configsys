# TUI screens plan

Status: **Decisions locked 2026-08-03** — ready to build in the order at the bottom. One item parked:
making install directories editable (C1) — read-only for v1, revisit later.

The TUI is a **skin over the CLI**: every screen shows live state and turns key-presses into calls
on the *same* functions the CLI uses. We do not erase or bypass any CLI command. Where a screen needs
an action that has no reusable function today (most profile/config edits, and the plugin add/bless
*orchestration*), we factor that logic out of the `cmd_*` handler into a callable function **and** give
it a symmetric CLI subcommand. Net effect: the TUI and CLI stay in lockstep, and CLI surface grows.

Grounding (from the code map):
- The TUI is one render loop (`tui/menu.py:1017`) with a single `show_diag` bool as its only "screen
  switch". Rendering is immediate-mode (full redraw each keystroke). `ctx` (`app.py:108`) is the single
  source of truth; `ctx.load_pipeline` inspects state, `_reload` (`menu.py:733`) does a partial requery
  after a change, `ctx.invalidate()` drops cached config after a write.
- Config `.hu` files are edited surgically by `plugins.set_section(file, section, emit)`
  (`plugins.py:424`, span-replaces one top-level node, preserving comments) and `remove_sections`. Pins
  already have an emitter; **profiles / configs / scope / driver-preference / auto-tighten / theme do
  not** — those emitters are the new writers we need.
- Theme is already fully config-driven: `resolve_theme` (`theme.py:130`) merges a `theme:` section
  (`theme.colors.*`, `theme.elements.*`, `theme.gradient`) over defaults. The colors screen is an
  editor over that section — no new theming model.

---

## Foundation (prerequisite for all screens)

### F1 — Screen router + nav bar
Replace the `show_diag` bool with a `screen` value and a small router: a dict `{screen: (draw_fn,
handle_key_fn)}`, each screen owning its own view-state object (like today's `MenuState`). The main
loop draws shared chrome (nav bar + status/help footer), then dispatches draw+input to the current
screen. Diagnostics (`!`) and a help overlay (`?`) become overlays any screen can raise.

Nav bar: a chip row under the title — `[1]Components [2]Profiles [3]Plugins [4]Dotfiles [5]Config` —
current highlighted; switch by **number key (1–5)** only. `Tab` is reserved for in-screen panel focus,
so it deliberately does NOT cycle screens (LOCKED N1).

### F2 — Rendering primitives
- `panel(rect, title, focused)` — a bordered box (generalize the inline box in `_popup_choose`
  `menu.py:788`), with a focused/unfocused border style.
- `listpanel` — a scrollable, cursor-tracking list inside a panel (reused by every new screen).
- Two-panel focus: a `focus` index; `Tab`/`h`/`l` move focus between panels, `j`/`k` within.
- `input_box(prompt, initial)` — a single-line text-input modal. **New**: the TUI has no text input
  today (only `_popup_choose`). Needed for plugin source entry, profile rename, config values, RGB.

### F3 — Shared action layer (the spine, LOCKED A1)
New reusable functions, each also exposed as a CLI subcommand (symmetry). The CLI subcommands are
**first-class** — precise args, real `--help`, man coverage — not thin shims; the CLI stays a fully
valid way to drive configsys.

| Domain | New function(s) | Built on | New/!extracted | CLI subcommand |
|---|---|---|---|---|
| Profiles | `edit_profile_membership(file, profile, comp, add\|remove)`, `edit_configs(file, profile, on\|off)`, `create/rename/delete_profile` | `set_section` + Config term-algebra readers | new | `configsys profile add\|rm\|activate\|deactivate\|new\|rename\|del` |
| Scope/settings | `set_scope`, `set_driver_preference`, `set_auto_tighten`, `set_ignore_profiles` | `set_section` | new | `configsys config get\|set\|show` |
| Theme | `set_theme(file, overrides)`, `save_theme_plugin(name, overrides, force)`, `load_theme(name)` | `set_section` + `scaffold_primary` | new | `configsys theme set\|save\|load` |
| Plugins | `plugin_add`, `plugin_remove`, `plugin_bless`, `plugin_update`, `pin_promote` | existing `set_declared`/`sync`/`_upsert_decl`/`ensure_branch` | **extract** from `cmd_plugin`/`_bless_primary` | (existing) |
| Dotfiles | `DotFiles.capture(rc, force)` | existing `capture_plan` + move the inline copy loop in | **extract** from `cmd_dotfiles_capture` | (existing) |

Also (optional cleanup): collapse the duplicated execute paths — TUI `execute_plan` (`menu.py:421`)
vs CLI `_dispatch_op` (`app.py:555`) — into one shared function, so the TUI truly skins it.

The **profile term-algebra writer** is the subtle one. Toggling component X in profile P must respect
where X's membership *comes from* (read via `profile_layout` / `profile_own_components` / the per-name
layer `_chain`):
- add, P owned in the edit-target layer → append bare `X`.
- add, P defined only in a lower layer → amend with `+self` then `X` (inherit + add).
- remove, X is P's own term here → delete the term.
- remove, X inherited (from a lower layer or via `+other`) → append `~X`.
The screen surfaces this provenance so the toggle is legible, not magic.

---

## Screen 1 — Profiles

**Goal:** see, without opening several `.hu` files, what's in which profile and where to change it.

**Layout — two panels:**
- LEFT: profiles list. Every defined profile (active ones — those in `configs:` — marked ●, inactive
  ○). Expand a profile to show its member components inline (today's tree idea). Also a synthetic
  `all`.
- RIGHT: the full component catalog — *every* component in the merged routes+plugins, each row:
  name · availability (routable here, or **grayed** if unroutable on this machine) · install state
  (installed/version, from `states`) · membership marker vs the LEFT-selected profile (● in · ○ out ·
  ↳ via-include · ~ removed, with provenance).

**Actions (→ shared-layer functions):**
- `space`/`enter` on a right-panel component → toggle its membership in the left-selected profile →
  `edit_profile_membership`.
- `a` on a left profile → toggle active → `edit_configs`.
- `m` on a component → install-method pin (reuse `_pick_method` `menu.py:830`).
- `n`/`r`/`d` → new/rename/delete profile (uses `input_box`).
- `g` → jump to the component on the Components screen.

**Write target:** default to the **primary plugin** if one is set (portable across machines), else the
top config. Shown in the footer; a key toggles target. (Fork P1.)

---

## Screen 2 — Plugins

**Goal:** add/remove/sync plugins and see the layer stack visually; manage local-config vs primary.

**Layout — list + detail:**
- LEFT: the layer stack in precedence order (repo < plugins < primary < discovered < top-config),
  each plugin a row with status glyphs from `plugins.status()`: synced/unsynced/failed · ABI ok/incompat
  · trust (code plugins) · primary★ · checksum/quarantine. Transitive plugins (a plugin's own
  `plugins:`) shown indented under their parent.
- RIGHT: detail for the selected plugin — source · ref · HEAD/branch · manifest (provides,
  requires-abi, data files, has-code) · what it contributes (components / os blocks) · trust state ·
  on-disk path.

**Actions (→ extracted plugin orchestration):**
- `a` add (source+ref via `input_box`) → `plugin_add`; `x` remove → `plugin_remove`; `s` sync
  (all / selected) → `plugins.sync`; `u` update ref → `plugin_update`; `b`/`B` bless/unbless →
  `plugin_bless`; `t`/`T` trust/untrust code → `set_trust`; `S` set-source.
- A "**local vs primary**" strip: shows which machine settings sit in the top config vs the primary
  plugin, with `p` = promote a pin/setting into the primary (`pin_promote`, generalized).

Links to the **Dotfiles** screen (`4`) since dotfiles live in the primary plugin's `dotfiles/`.

---

## Screen 3 — Dotfiles  *(recommended: its own screen — Fork D1)*

**Why separate:** dotfiles are a per-file *link-state* domain, distinct from the plugin screen's
*layer-source* domain. The connection (they live in the primary plugin) is a link between screens, not
a merged panel.

**Layout — a table**, one row per dotfile spec across active dotfiles units (`DotFiles.spec_states`
`dotfiles.py:138`): name · content location + tier (user store `~/.config/configsys/dotfiles` /
primary plugin / defining-layer template) + rel path · link target (`~/…`) · state
(linked / adopted / unmanaged / template / empty) · defining layer (provenance → plugin screen).

**Actions:**
- `l` link/relink → `DotFiles.install`; `x` unlink → `DotFiles.uninstall` (restores backup).
- `c` capture/adopt an on-system file into the store → **new** `DotFiles.capture` (extracted). Preview
  first via `capture_plan`; clobber-proof warnings surface as confirm modals.
- Shows the content search-path resolution so "which dotfile lives where" is legible at a glance.

---

## Screen 4 — Config (machine settings + theme)

**Layout — a settings form** (field · current value · provenance layer):
- `default_scope` (user/system) — toggle → `set_scope`.
- `driver-preference` (ordered vias) — reorder editor → `set_driver_preference`.
- `auto-tighten` (bool) — toggle → `set_auto_tighten`.
- `ignore-profiles` (list) — editor → `set_ignore_profiles`.
- `configs:` / `pins:` — **display + link** to Profiles/Components (edited there, not duplicated here).
- **Install directories** (`$CONFIGSYS_*_DIR`) — today these are **env-driven** (`paths.py`), *not*
  `.hu` fields. Options (Fork C1): (a) show read-only with a note; (b) add a `dirs:` config source so
  they're editable. Recommend (a) for v1.

There should be a small descriptor for each of these, explaining (briefly) what they do, with a man
reference for further info.

**Theme editor** — a sub-screen (`t`) over the `theme:` section:
- List semantic colors (`SEMANTIC`), element styles (`ELEMENTS`), gradient endpoints — each a swatch +
  RGB. Edit a color (via `input_box` / +/- nudges) → **live preview** (re-instantiate `Palette` and
  redraw). Write via `set_theme`.
- `save`/`load` named theme templates. **Save writes a theme PLUGIN** — a `theme:`-only plugin
  (scaffolded like a primary) so it's portable/shareable through the plugin model — with an
  **overwrite warning** when the target already exists. `load` applies a theme plugin's `theme:` over
  the current config. (LOCKED T1: full per-role editor + live preview + plugin-backed templates.)

---

## Navigation & keys (shared)
- `1`–`5` screens; No `Tab` cycle because it conflicts with in-screen Tab; `!` diagnostics overlay; `?` help overlay; `q` quit.
- Within a screen: `j/k` move, `h/l`/`Tab` panel focus, `g/G` top/bottom, `space/enter` primary action,
  per-screen action letters shown in the footer.

## Decisions (LOCKED 2026-08-03)
- **A1 action layer** — extract the `cmd_*` orchestration into reusable functions + add first-class,
  user-friendly CLI subcommands (the CLI stays a valid way to use configsys). NOT TUI-only wrappers.
- **N1 nav** — tab-bar chip row for orientation; switch screens by **number key only** (Tab is
  in-screen panel focus).
- **P1 profile/config edit target** — primary plugin if one is set (portable), else top config, with a
  visible per-session toggle.
- **D1 dotfiles** — its **own** screen (not a panel on the plugin screen).
- **T1 theme editor** — full per-role editor + live preview; **save writes a theme PLUGIN** with an
  overwrite warning.
- **C1 directories** — read-only for v1. **Parked**: making them editable (an editable `dirs:` config
  source) is a later revisit.

## Candidate future screens
- **Versions** — the per-method version view (`configsys versions` / `versionreport`): what each install
  method offers, floors, "lags latest". A natural TUI table given the versioned-requires work.
- **Request/coverage** — the component-request coverage matrix (`configsys request`).
- Diagnostics already exists as the `!` overlay; keep it.

## Build order (proposed)
1. F1 router + F2 primitives (incl. `input_box`) + F3 shared action layer with CLI subcommands.
2. Screen 1 Profiles (exercises the term-algebra writer + two-panel + method pin).
3. Screen 2 Plugins (exercises extracted orchestration + detail panel).
4. Screen 3 Dotfiles.
5. Screen 4 Config + Theme editor.
Each screen ships behind its nav chip; the existing Components screen is screen 1-slot `1`, unchanged.
