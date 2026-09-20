# Review: TUI presentation support (theme / keyspec / splash / screen)

Scope: `configsys/tui/theme.py`, `configsys/tui/keyspec.py`, `configsys/tui/splash.py`,
`configsys/tui/screen.py`, `configsys/splashes.py` (lives at package root, curses-free ABI surface;
reviewed here because `tui/splash.py` is its host), `configsys/tui/__init__.py`.
Coverage gauged from `test/test_theme.py`, `test_theme_edit.py`, `test_keyspec.py`, `test_splashes.py`
(63 tests, all green on `.venv`). `menu.py` was read only to cross-check what each page paints.

## Themes

1. **The role/page model has drifted from the renderer.** `PAGE_ROLES` is the editor's source of truth
   for "what can I color on this page", but it was hand-maintained through the glue split, the orphan
   prune and the plugins/profiles sample work. Result: 8 roles the Components page really paints are
   not editable there (`issue_error`, `select_marker`, `op_unlock`, `op_mixed`, `profile`, `link`,
   `unsupported`, `error`), five `ROLE_DEFAULTS` roles are editable on NO page, and `os`/`unit`/`missing`
   are listed on pages that never paint them. Nothing tests the list against the draw functions.
2. **Silent degradation under user-authored gradients.** Both curses budgets — 255 pairs per frame and
   ~240 color slots per session — are within reach of the defaults (173/240 slots) and are blown by the
   exact thing `docs/theming.md` recommends ("a wider range renders a smoother ramp"). Overflow is
   silent: `A_NORMAL` text and cube-quantized backgrounds on whichever page allocates last.
3. **Snapshot/promote can lose edits.** `full_snapshot` iterates `DEMO_PAGES` × `PAGE_ROLES` only, and
   `save_theme_to_primary` MOVES (clears the local theme) after writing it — so overrides on the `theme`
   page, or on any used-but-unlisted role, vanish on promote.
4. **Keymap lint is per-layer, dispatch is per-dict-order.** A user rebind that collides with a repo
   binding in the same scope is never reported and resolves by insertion order. Labels for the `?` help
   are ~40% missing/stale.
5. **Splash host has two "no surprises" holes:** an unguarded provider constructor (a trusted plugin can
   brick startup) and un-drained input after a skip (mashed keys land in the menu as actions).
6. **Docs describe a previous TUI.** `theming.md`/`theme-redesign.md` still say key `6`, `a–e`, five pages,
   a `discovered` layer, and the deleted `orphan_*` trio; `colors-basic` is undocumented.

---

## PAGE_ROLES vs. actually-rendered roles

Derived by reading every `pal.style(...)`/`pal.fill(...)` in each `_draw_<page>` plus the shared chrome
they all call (`_draw_nav` → `label`/`menu_header`/`info_dim`/`footer`; `_panel` → `menu_header`/
`info_dim` border + `label`/`menu_header` title; `_scrollbar_v/_h` → `select_marker`/`info_dim`;
selection bar → `selection` via `fill(selected=True)`).

| page | listed in PAGE_ROLES but NEVER painted | painted but NOT listed (not editable on this page, not in snapshots) |
|---|---|---|
| components (`menu.py:1220-1365`) | — | `issue_error` (1264), `select_marker` (1315, 2087), `op_unlock` + `op_mixed` (1304 via `OPS`), `profile` + `link` (1289 `_KIND_ELEM`), `unsupported` + `error` (1328 status column; the sample test *asserts* these statuses render) |
| profiles (`3288-3692`) | `os` | `select_marker` (scrollbars) |
| plugins (`4643-4743`) | `os`, `unit`, `missing` | `select_marker` |
| glue (`4884-4951`) | `os`, `unit`, `missing` (`_DF_STATE_ELEM` only yields installed/outdated/info_dim) | `select_marker` |
| dotfiles (`4954-5027`) | `os`, `unit`, `missing` | `select_marker` |
| config (`3852-3973`) | `os` | `select_marker` |
| theme (`4393-4498`) | — | `select_marker`; `unit` (4470, nested preview only) |

`os` is painted only by `_draw` (components, 1240); every other page draws `_draw_nav` alone.
Roles in `ROLE_DEFAULTS` that appear in **no** page list: `issue_error`, `op_mixed`, `op_unlock`,
`select_marker`, `unsupported` (+ passthroughs `dim`, `title`). Map colors referenced by **no**
built-in role: `ink`, `ink_dim` (`ink` is used once as a pseudo-role by `pal.get('ink')`, `menu.py:1068`).

Overlays/modals (`_help_modal` 1051, `_draw_diagnostics` 1121, `_draw_where` 1147, `_popup_choose` 1452,
`_input_box` 3696, `_attr_filter_modal` 2275, `_machines_modal` 2396, `_busy` 1442) paint with
`pal.get('accent'|'dim'|'title'|'error'|'outdated'|'installed'|'label'|'ink')` — map colors over the
default background, so they are neither per-page themeable nor gradient-aware.

---

## Findings

### [HIGH] performance/correctness — per-frame color-PAIR budget overflows with a wide gradient
`theme.py:123` (`GRAD_MAX_BANDS = 96`), `:475-477` (`n = max(16, min(96, span+1))`), `:587-588`
(`if n > 255: return curses.A_NORMAL`), `:637-639` (text pair = `(fg, band)`).
Every text cell over the gradient allocates a pair keyed on `(fg_idx, band_idx)`; each fg role visible
down a column sweeps ~n/2 bands, so pairs/frame ≈ (visible fg roles) × n/2 + n fills + selection pairs.
Defaults (17–24 bands) land ~130–180. A user gradient with span ≥ ~50 (e.g. `#000000`→`#303030`,
exactly what theming.md line 104-105 encourages) needs > 255 → `_pair` silently returns `A_NORMAL`:
whatever is drawn last that frame (status line, footer, the Theme page's own lists under a sample)
loses color and background, and the effect shifts as draw order changes. Nothing surfaces it.
**Recommend:** budget bands against `COLOR_PAIRS`/255 at Palette build (`n ≤ (255 - roles×2) / roles`,
i.e. cap ≈ 24–32), or quantize `band()` for *text* to a coarser sub-band than for fills; log the clamp
in `color_mode`. Add a fake-curses test that renders a worst-case frame and asserts no `A_NORMAL`
fallback.

### [HIGH] data loss — `full_snapshot` omits the `theme` page and unlisted roles; promote then CLEARS local
`theme.py:329` (`for page in DEMO_PAGES`), `:332` (`for role in PAGE_ROLES.get(page, [])`);
`actions.py:655-658` (`set_theme(target, full_snapshot(...))` then `set_theme(user_config_file, {})`).
The editor lets you F7 into the `theme` page and write `pages.theme.<role>` (`menu.py:5977`, `6081`),
and a hand-authored config can override any `ROLE_DEFAULTS` role on any page. The snapshot keeps neither
(it iterates `DEMO_PAGES`, not `ALL_PAGES`, and `PAGE_ROLES`, not the rendered set), so "promote full
theme → primary" writes an incomplete look and then deletes the local overrides that held the rest.
Also `colors-basic` keys unknown to `BASIC_MAP` are kept only if parseable — fine — but page-level
`gradient: false` (bare bool) survives only via `enabled: False`, OK.
**Recommend:** snapshot `ALL_PAGES`, and for roles use `ROLE_DEFAULTS` ∪ any role present in the user
spec (or fix PAGE_ROLES per the next finding and also include user-spec extras). Test: override
`pages.theme.component` + `pages.components.select_marker`, snapshot, assert both present.

### [MED] data-driven — `PAGE_ROLES` drifted from the renderers (table above)
`theme.py:191-209`. Consequences: (a) Components can't retheme its op badges `l`/`*`, the `»` select
marker, the diagnostics `issue_error` badge, or `error`/`unsupported` statuses — yet the sample tree was
deliberately built to *show* them (`test_theme.py:262-276`); (b) `select_marker` (every scrollbar thumb)
is themeable nowhere; (c) the editor offers `os` on five pages where it is dead, and `unit`/`missing` on
three; (d) `EDITABLE_ROLES` (`:183`) says passthrough roles are "internal" while `PAGE_ROLES` lists
`accent` (plugins) and `header` (config) — contradictory intent, and `EDITABLE_ROLES` itself is unused
anywhere (`grep -rn EDITABLE_ROLES` → definition only).
**Recommend:** make the list *derived*: render each `_sample_*_state` through a recording Palette stub
(`style/at/fill/get` append the role) and either generate `PAGE_ROLES` from that at import, or keep it
static and add a test asserting `rendered ⊆ listed` and `listed ⊆ rendered ∪ chrome`. Add
`select_marker`, `issue_error`, `op_unlock`, `op_mixed`, `profile`, `link`, `unsupported`, `error` to
components; drop `os` from non-components pages; drop `unit`/`missing` from plugins/glue/dotfiles;
delete `EDITABLE_ROLES`.

### [MED] performance — eager slot allocation for all 7 pages; docstring claims a bound that no longer holds
`theme.py:462-477` (every page's `grad_bg` allocated in `__init__`), `:539` (`_next_color < COLORS`
→ silently falls through to `rgb_to_256`), `:503-504` ("Color SLOTS persist (they're bounded by the
theme's distinct colors, < 256)").
Defaults use 148 gradient + 25 map = 173 of the 240 slots above 16. Any widened gradient (worst case
7 × 96 = 672) exhausts slots; later pages (dict order: dotfiles, config, theme) get cube-quantized
backgrounds — a dark 20-step ramp collapses to 2–3 grey levels — with no indication. The docstring's
"< 256" is false once gradients are counted.
**Recommend:** allocate a page's bands lazily in `use_page` (slots are a session-global allocator, so
either free/reuse the previous page's band slots or cap per-page bands to `(COLORS-16-len(map))/len(ALL_PAGES)`);
report the clamp in `color_mode` (e.g. `24-bit (gradient reduced)`); fix the docstring.

### [MED] security/correctness — key-conflict lint is per-layer; merged conflicts resolve by dict order
`keyspec.py:223-262` (`seen` is reset per layer, per scope), `:103-110` (`action_for` returns the FIRST
action whose codes contain `code`), `config.py:239-250` (merge keeps the repo's insertion position for an
overridden action, appends new ones), `app.py:2081-2082` (lint runs on `layer_list` only).
A user layer `components: { where: i }` merges next to repo `op-install: i`: no warning, and `where`
wins only because it was declared earlier in `config.hu` — a rebind of `op-install: w` would be shadowed
the other way. Plugin layers (blessed content, not the user's own file) contribute `keys:` with no role
restriction, so this is also the vector by which a third-party plugin can silently retarget a key.
**Recommend:** run `lint_keys` on the MERGED map as well (one synthetic layer named "merged"), and in
`Keymap.__init__` build a reverse `{code: action}` per scope so a conflict is deterministic (last layer
wins) and cheap; `configsys keys` should print the winning layer per action (plan §7 promised this).

### [MED] robustness — splash provider construction is unguarded; a bad plugin bricks TUI start
`splash.py:145` (`provider = provider_cls(scr, pal, (h, w), seed)` outside the try), `:131-143`
(docstring: "Never raises for a misbehaving provider"), `menu.py:5074` (`run_splash(...)` not wrapped).
`test_splashes.py:208` covers a raising `render`, not a raising `__init__`. A trusted code plugin whose
splash constructor throws (bad `size`, missing attr) propagates out of `run()` under curses.
**Recommend:** move construction inside the try (fall to `_draw_progress_text`, set `splash_note`), and
add the `__init__`-raises test.

### [MED] UX/no-surprises — input typed after a splash skip is delivered to the menu as actions
`splash.py:182-190`: once `animate` is False the loop never calls `getch()` again, so every key pressed
while the plain progress line finishes inspection stays in the input queue; `menu.py:5074-5121` has no
`curses.flushinp()` between `run_splash` and the event loop (flushes exist only around ops, 6270/6292/6317).
A user hammering keys to dismiss the splash can arrive at Components with `x`/`i`/`X` already queued.
**Recommend:** `curses.flushinp()` in `run_splash`'s `finally`, or drain `getch()` in the text branch.

### [MED] feature gap — modals/overlays are not themeable per page and ignore the gradient
`menu.py:1068` (`'ink'` pseudo-role), `1082`, `1126-1142`, `1154-1172`, `1448-1484`, `2286-2307`,
`3706-3707`, `3785` all use `pal.get(<map color>)`. `theming.md:3` says "The whole TUI palette is
yours", but border, modal title, popup text, diagnostics/where pages only follow the map, are drawn over
the terminal default background (a visible rectangle hole in the gradient), and the `?` help uses a map
color (`ink`) that no role references.
**Recommend:** introduce `modal_border`, `modal_title`, `modal_text`, `overlay_title` roles (+ a
`Palette.style_at(role, y, x)`-style helper that paints over the gradient) and list them under a
pseudo-page `overlays` in `PAGE_ROLES` so the editor can reach them.

### [MED] docs drift — `docs/theming.md` and `docs/theme-redesign.md` describe a prior TUI
- key `6` → Theme is now `7` (`config.hu:178`, `menu.py:1196-1198`): `theming.md:6,115`;
  `theme-redesign.md:6,31,60`.
- `a`–`e` page cycle → `F1`–`F7` (`config.hu:292-298`): `theming.md:23,124`; `theme-redesign.md:64`.
- pages "components, profiles, plugins, dotfiles, config" → + `glue`, and the editor previews `theme`
  (`theme.py:186-187`): `theming.md:71`; gradient hue list `:97` lacks green/rose.
- precedence "repo < plugins < primary < **discovered** < your top config" — discovery was removed
  (`theming.md:42`).
- role list `:82-92` still names `orphan_excluded/forgotten/foreign` (deleted, `test_theme.py:308-314`)
  and the "one per orphan kind" paragraph; it lacks `row_desc`, `method_dim`, `dependents`, `menu_new`,
  `diff_*`; the color-name list `:66` lacks `row_desc`, `method_dim`, `dep_dim`, `menu_new`,
  `orphan_lurking`.
- `colors-basic` (a real, tested user knob: `theme.py:42-61`, `config.py:206-207`) is documented nowhere
  in `docs/`.
- `theme-redesign.md` "Locked (decided)" + "Schema" (`:12-58`) still specify the abandoned
  `palette:`/`roles:`/zebra-list/`selected:` model its own preamble says collapsed.
**Recommend:** regenerate the role/color lists from `ROLE_DEFAULTS`/`COLOR_MAP` (a tiny doc test or a
`configsys theme roles` printer), and collapse theme-redesign.md's Locked section to a pointer.

### [MED] feature gap — `ACTION_LABELS` is ~40% incomplete/stale; the `?` overlay shows raw ids
`keyspec.py:182-212`. Known actions with no label (21): `activate`, `activate-group`, `deactivate`,
`manage`, `manage-all`, `unmanage`, `unmanage-all`, `move-store`, `move-store-all`, `new`,
`op-install-all`, `op-upgrade-all`, `page-down`, `page-up`, `page-1..7`. Labels for actions that no
longer exist (4): `unlink`, `capture`, `capture-all`, `link-all`. Duplicate literal key `'select-all'`
(`:189` and `:201`; the second silently wins). `help_rows` (`:128-151`) hardcodes `'page-7'`/`'F1-F7'`.
**Recommend:** a test `set(ACTION_LABELS) == union(KNOWN_ACTIONS) | _GLOBAL_ACTIONS`; derive the page
range from `len(theme.ALL_PAGES)`.

### [LOW] dead code / stragglers
- `theme.py:183` `EDITABLE_ROLES` — unused anywhere.
- `theme.py:641-650` `Palette.at()` — no caller (`grep pal\.at\(` → none); `row=` kwarg on `style`/`at`
  (`:622`, `:626` "accepted for call-site compatibility") — no caller passes it.
- `theme.py:667-670` `STATUS_COLOR` is an identity dict used only as a membership test (`menu.py:1328`).
- `theme.py:27` `ink_dim` map color referenced by nothing; `ink` only by the help modal.
- `theme.py:39,161` comments: `menu_new` is "a derived profile's OFFERED (NEW, `?`) items" — the derive
  model was ripped out; it now paints the ◆ NEW (undispositioned) marker (`menu.py:3611,3647`).
- `theme.py:185` "The five content screens" — six.
- `splash.py:74` `MIN_DURATION` duplicates `Splash.min_duration` (`splashes.py:56`); `run_splash`'s
  `deadline` kwarg (`:131`) is never passed by the only caller (`menu.py:5074`).
- `menu.py:1200` `KEY_TO_SCREEN` (superseded by `Keymap.screen_for`) — other agent's file, noted only.
- `config.hu:181-182` "per-screen enforcement is rolling out screen by screen" — all wired.
- `docs/keybindings-plan.md:26-29` "six screens", "F1-F6", "57 references"; §1 still promises a Python
  `DEFAULT_KEYMAP`, contradicting locked decision #1.

### [LOW] code reuse — the role-overlay and off-token logic is triplicated
`theme.py:293-297` (`resolve_theme`), `:333-336` (`full_snapshot`), `menu.py:4307-4312`
(`ThemeScreen.role_ref`) each do `st = dict(ROLE_DEFAULTS[role]); st.update(spec.get(role))`.
Off-token sets: `(False,'false','no','off')` at `theme.py:309,313`, `menu.py:4320`; bg-none set
`(None,'','none','false',False)` at `theme.py:300,338`, `menu.py:4381`; `_flag` (`:228`) is the only
one that also honours `'0'`/`'on'`. One `effective_role(theme, page, role)` + `_off(v)`/`_none(v)`.

### [LOW] naming/refactor — six booleans encode one color depth
`theme.py:430-449` (`have256`, `direct`, `truecolor`, `mono`, `have16`, `lowcolor`); `color_mode`
(`:487-496`) re-derives an enum; `splash.py:50-53` re-derives it AGAIN via `getattr` chains. Expose a
single `Palette.depth ∈ {'none','8','16','256','truecolor','direct'}` and derive the flags. Also
`style(element, …)` vs docs/`ROLE_DEFAULTS` "role" — pick one word.

### [LOW] ABI — splash page count and Palette subset are implicit contracts
- `keys.theme.page-N` ties action ids to `len(ALL_PAGES)`; adding a page (as the glue split did,
  `1efc4fb`) changed `config.hu`, `KNOWN_ACTIONS`, `help_rows`, `_FALLBACK` and `SCREENS` by hand.
  Consider `page-next`/`page-prev` or binding page ids.
- `splashes.py:34-38` documents `pal.rgb_attr/rgb_pair/get` but the host (`splash.py:50-53`) also
  reads `pal.truecolor/direct/mono/have256/have16`; plugins will too. Document that subset as frozen
  (it is not on `plugins.__all__`), or pass a `depth` string in `SplashFrame`/ctor.
- `menu.py:5881` imports the private `splashes._BUILTIN_SPLASH_NAMES`; expose `is_builtin(name)`.
- `Keymap._m` is read from `app.py:2717,2722` — add a public iterator.

### [LOW] security — keyspec input hygiene
- `keyspec.py:42-43` `isinstance(name, int)` accepts `bool` (a Python `True` would bind code 1 =
  ctrl-a) and any int (negative/huge) unflagged; guard `bool` and range-check.
- `lint_keys` (`:255,258`) and `Keymap.glyph`/legends echo raw user/plugin strings; a `keys:` value
  containing ESC sequences (from a blessed third-party plugin layer) is printed verbatim by `check`
  and painted into footers. Use `repr()` in lint output and strip C0 controls in `key_name`.

### [LOW] screen.py — cursor and signal state after `suspended()`
`screen.py:86-98`: `endwin()` restores the shell's cursor; `reset_prog_mode()` does not re-apply
`curs_set(0)` (only `curses_screen`, `:69`, and `_input_box`, `menu.py:3763`, do) — after an apt run
the TUI can show a blinking cursor until the next input box. `siginterrupt(SIGINT, True)` (`:65`) is
never reset on teardown (harmless for a CLI that exits, but leaks into `--probe`/`curses.wrapper` paths).

### [LOW] performance — `_fill_bg` recomputes `band()` for every cell every frame
`menu.py:1177-1192` calls `pal.band` w×h times (~10k float ops/frame at 200×50) to find segment edges
that are analytic: for row y, band changes at `x = ceil(((k/n) - y/(h-1)/2) * 2 * (w-1))`. A
`Palette.row_segments(y, h, w) -> [(x0, x1, band)]` (cached per (h, w)) removes the inner loop. Low
because effects=`reduced` already disables it over SSH.

### [LOW] test gaps
- No test that `PAGE_ROLES[page]` ⊇ roles rendered by `_draw_<page>` (the sample states + a recording
  Palette stub make this cheap and would have caught every row in the table above).
- No fake-curses `Palette` tests at all: pair overflow, slot budget, `color_mode` clamping
  (`env_color_cap` × `COLORS`), `use_page` swap, `fill(bg=)`, `new_frame`. `test_contrast_guard`
  (`test_theme.py:83`) shows the stub pattern.
- `full_snapshot` round-trip for the `theme` page / an unlisted role (finding 2).
- `Keymap.help_rows`, `key_name` of an unknown code (`'?'`), `parse_key(True)`, merged-layer conflicts.
- Splash: `__init__` raising, `deadline`, `fps_cap`, input flush, `_draw_progress_text`; `env_effects`.
- keybindings-plan §6's "PTY smoke: `quit: x` actually quits" is not implemented (no test greps for a
  remapped `keys:`).

### [NIT] `_GLYPH` style inconsistency
`keyspec.py:31` renders 10/11 as `ctrl-j`/`ctrl-k` while `key_name` (`:67-68`) renders every other
control char as `^x`; legends mix both.

### [NIT] `_r()` / `_flag()` names
`theme.py:126,228` — `_role_style()` / `_truthy()` read better at the 40+ call sites.

### [NIT] `resolve_theme` silently ignores an unknown role key
`theme.py:293-297` iterates `ROLE_DEFAULTS`, so a typo (`componnet:`) in `pages.<page>` is dropped;
`check` (`app.py:1971-1979`) only flags the legacy `palette/elements/gradient` keys. A one-line
"unknown role" warning would match the `keys:` lint.
