# Review: TUI theme, keys, splash, terminfo

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/tui/theme.py`, `configsys/tui/keyspec.py`, `configsys/tui/splash.py`,
`configsys/tui/terminfo.py`. Context: `docs/theming.md`, `config.hu`, plus (to judge callers and the
ABI) `configsys/splashes.py`, `configsys/tui/screen.py`, `configsys/tui/menu.py` (`_route_key`,
`_help_modal`, `_chosen_splash`, `run()`'s splash block, `ThemeScreen`), `configsys/tui/screens/{plugins,theme,components,config}.py`,
`configsys/config.py` (`theme`/`keys`), `configsys/actions.py` (theme writers, `plugin_trust*`),
`configsys/app.py` (`cmd_keys`, `_probe_color`, the `check` key/theme lint), `configsys/layers.py`
(role rules), `docs/plugins.md` §93, `docs/config-format.md` §35/§846-880, the four splash plugins
(`~/src/configsys-splash-{ocean,blocks,maze,cityscape}`, read-only).
Tests read: `test/test_keyspec.py`, `test/test_theme.py`, `test/test_splashes.py`,
`test/test_terminfo.py`, `test/test_direct_color.py`, `test/test_fix_tui_c.py` (keys §8-11),
`test/test_review_regressions.py` (theme A4), `test/_render_harness.py`, `test/test_abi_surface.py`.
The five owned-module test files pass (`83 passed in 3.57s`).

Scratch scripts behind every **(reproduced)** mark live in
`$RUN/scratch/tui-theme/` (`direct_cap.py`, `pairs.py`, `slots.py`, `roles.py`, `keys_pty*.py`,
`palprof.py`, `paltime.py`); sandbox homes under `$RUN/scratch/tui-theme/home/`.

Verified 2026-11-08 by an adversarial checker. Every HIGH, plus every security/safety finding at MED or
above (01, 02, 03, 10), was re-run independently. Scripts and sandbox homes are under
`$RUN/scratch/verify-tui-theme/` (`scripts/v01_*.py`, `v02_*.py`, `v03_promote.py`, `v10_pty*.py`; homes
`home`, `home-remove`, `home-promote`). All four were confirmed. Severity changes: 02 HIGH → MED (now listed
after 03), 10 MED → LOW.

## Carried over from docs/review-2026-09/tui-theme.md

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] per-frame color-PAIR budget overflows with a wide gradient | open | → tui-theme-07. `theme.py:594-595` still returns `A_NORMAL` past pair 255; measured 133 fallbacks/frame on Profiles with a `#404040→#000000` gradient |
| [HIGH] `full_snapshot` omits the `theme` page + unlisted roles; promote then clears local | open | → tui-theme-03. `theme.py:334` still `for page in DEMO_PAGES`, `:337` `PAGE_ROLES`; `actions.py:1175-1176` still clears the local theme |
| [MED] `PAGE_ROLES` drifted from the renderers | open | → tui-theme-08 (re-derived against the MVVM screens) |
| [MED] eager slot allocation; "< 256" docstring false | open | → tui-theme-02 — worse than reported: an over-budget color is ALIASED to an unrelated redefined slot, not cube-quantized |
| [MED] key-conflict lint per-layer; merged conflicts by dict order | fixed | `2a577c0` added `merge_layer_keys` (rebind-wins), cross-layer steal warnings and `lint_merged`; tests `test_fix_tui_c.py:403-436`. Its two residuals are re-reported: the "third-party plugin can silently retarget a key" vector (→ tui-theme-01, now a demonstrated trust bypass) and "`configsys keys` should print the winning layer" (→ tui-theme-22) |
| [MED] splash provider construction unguarded | open | → tui-theme-09 (`splash.py:145`; `menu.py:4748` still unwrapped) |
| [MED] input typed after a splash skip reaches the menu | open | → tui-theme-10 (no `flushinp` anywhere near the splash) |
| [MED] modals/overlays not themeable per page | open | → tui-theme-23 (`menu.py:1309-1374` still `pal.get(<map color>)`) |
| [MED] docs drift in `theming.md` / `theme-redesign.md` | fixed | `acfdecc` + `d958cf9` (key 7, F1-F7, glue page, discovery removed, role/colour lists regenerated, `colors-basic` documented; `theme-redesign.md` stamped DONE). New drift is in tui-theme-24 |
| [MED] `ACTION_LABELS` ~40% incomplete; duplicate `select-all` | fixed | `d958cf9`: every `KNOWN_ACTIONS` action now has a label except `page-1..7` (collapsed by `help_rows`); no labels for unknown actions; one `select-all` (checked with a scratch script) |
| [LOW] dead code / stragglers | open | → tui-theme-26 (`EDITABLE_ROLES`, `Palette.at`, `row=`, `STATUS_COLOR`, `MIN_DURATION`, `deadline`) and tui-theme-24 (stale `menu_new` / "five content screens" comments). The config.hu "rolling out screen by screen" comment is gone (fixed) |
| [LOW] role-overlay + off-token logic triplicated | open | → tui-theme-14 (now 5 copies, and they disagree — reproduced) |
| [LOW] six booleans encode one color depth | open | → tui-theme-20 (and it is the root of tui-theme-06) |
| [LOW] ABI: page count + Palette subset implicit; `_BUILTIN_SPLASH_NAMES`; `Keymap._m` | open | → tui-theme-19, -21, -22 (`_BUILTIN_SPLASH_NAMES` now imported by `screens/config.py:264`; `app.py:3521-3522` still reads `km._m`) |
| [LOW] keyspec input hygiene (bool, raw strings echoed) | open | → tui-theme-17 (raw echo reproduced); the `bool` part is unreachable from humon (it materializes strings) → NIT in tui-theme-27 |
| [LOW] screen.py cursor / `siginterrupt` after `suspended()` | open | not re-reported: `screen.py` is now owned by tui-core. Still true at `956208e` (`screen.py:247-258` never re-applies `curs_set(0)`) |
| [LOW] `_fill_bg` recomputes `band()` per cell per frame | fixed | `f253bc2` caches the segment geometry (`menu.py:1545-1575`, `_FILL_BG_SEGS`) |
| [LOW] test gaps | open | partly closed by `2a577c0` (merged-layer steals, lockout, help rows); the Palette / PAGE_ROLES / splash-ctor / snapshot gaps remain — see Test gaps |
| [NIT] `_GLYPH` style inconsistency | open | → tui-theme-27 |
| [NIT] `_r()` / `_flag()` names | open | → tui-theme-27 |
| [NIT] `resolve_theme` silently ignores an unknown role | open | → tui-theme-15 (broadened: no theme lint at all) |

## Cross-cutting themes

- **"Cosmetic" layers aren't cosmetic.** `keys:` (and `theme:`) are honored from EVERY layer —
  including an untrusted, possibly transitively-declared plugin — on the premise that they're
  cosmetic (`docs/plugins.md:93`, `config-format.md:35`, `layers.py:381-382`). But a key binding
  decides what a keypress DOES, and the Plugins screen's single-key actions (trust, trust-all,
  bless, remove) have no confirmation. That combination is a demonstrated trust-gate bypass
  (tui-theme-01); `theme:` can also paint a warning invisible.
- **Per-scope merge logic vs. a cross-scope router.** `merge_layer_keys` / `lint_keys` reason one
  scope at a time; `_route_key` resolves page-own → global router actions → `screens` → global nav.
  Every keys finding (01, 04, 05, 11) lives in that gap: shadowing across scopes is silent, legends
  show keys a page shadows, and a steal is computed on intermediate rather than final bindings.
- **Silent degradation under budgets.** Both curses budgets (≤255 pairs/frame, ≤240 redefinable
  slots) are close at the defaults and blown by the wider gradients `theming.md:151` invites;
  overflow is silent and — for slots — produces *wrong* colors (02, 07). `color_mode` never says so.
- **Color depth is six booleans re-derived in three places** (`theme.py:435-457`, `color_mode`,
  `splash._sgr_downconvert`), and one of them (`direct`) conflates "the terminfo numbers colors as
  packed RGB" with "we emit 24-bit" — the root of the `--color` bug on `-direct` terminals (06, 20).
- **Hand-maintained lists that must agree**: the page list (≈9 copies, 21), `PAGE_ROLES` vs. what
  screens paint (08), the off-token sets (14), `help_rows`' order vs. `_GLOBAL_ACTIONS`.
- **Performance is fine here (measured).** Palette public calls are 4.5-12.6% of a profiled frame
  (`palprof.py`: Profiles 1191 calls/frame, 11.5 ms of 253 ms profiled); `Palette()` builds in
  1.25 ms; `merge_layer_keys` 0.36 ms, `lint_keys` 1.14 ms, `action_for` 3 µs. No perf findings.

## Findings

### tui-theme-01 [HIGH] security — an untrusted plugin's `keys:` can turn `j` on the Plugins screen into "trust every plugin"
`configsys/tui/keyspec.py:91-132` (`merge_layer_keys`), `:173-183` (`own_action`);
`configsys/tui/menu.py:1604-1619` (`_route_key`); `configsys/tui/screens/plugins.py:316-372`
(`remove`, `bless`, `trust`, `trust-all` — no confirmation); `configsys/actions.py:1501-1527`
(`plugin_trust_all`); `configsys/plugins.py:277-296` (`layer_files` loads a plugin's data files with
no trust check); `docs/plugins.md:93` ("`keys:` — cosmetic, so every layer may contribute").
Any synced plugin — one the user declared but never trusted, or one pulled in transitively by a
plugin they did declare — contributes `keys:` with no role restriction. A page-scope binding wins
over `global` on that page, and `lint_keys` deliberately does not flag a page key that shadows a
global one, so `keys: { plugins: { trust-all: j } }` silently makes the **down** key on the Plugins
screen trust every untrusted plugin, including the attacker's code, at its current hash. The user
is on that screen precisely to review the untrusted plugin. The same trick binds `bless` (become
the primary → set machine settings: picks, pins, `primary-push: auto`, transitive `plugins:`),
`remove` (rmtree a plugin dir) or `update-all` to a navigation key. Who controls the input: any
plugin author; when: the next TUI session; privileges: the user's; consent: none (the trust store is
the consent gate this forges). What the attacker could already do: an untrusted data plugin can
already override a core component's binding (e.g. a tarball URL), which runs their binary when the
user next installs/upgrades that component — so this is not a new class of power, but it converts
"runs when you install X" into "runs at your next start" and defeats the one explicit consent step
the plugin model advertises. `configsys check` reports only "untrusted code"; `plugin list` shows
`provides: keys` with no warning. A malicious `theme:` can additionally colour the Plugins
`untrusted` marker into the gradient.
**(reproduced)** sandbox `$RUN/scratch/tui-theme/home/evil`, a local plugin `evil` (`code: evil.py`,
`data: [ evil.hu ]`, `evil.hu` = `{ keys: { plugins: { trust-all: j } } }`), then driving the real
`PluginsScreen.handle(ord('j'), …)` under `--pretend`:
`plugin list` → `ok  [ships code — untrusted; run: configsys plugin trust evil]  provides: keys`;
`check` → only `warn plugin evilsrc: untrusted code`;
`j on the Plugins screen -> (None, None) own action: trust-all`;
`note after pressing j: '[pretend] would trust 1 plugin(s) — not saved\n  evil'`.
**Fix:** (1) treat `keys:` like a machine setting for authority: honored only from repo / primary /
top config; a plain `plugin` or `include` layer's `keys:` is ignored with a `check` / `!` warning
(add it to `layers._forbidden_by_role` and re-word plugins.md §93 / config-format §35); (2) defense
in depth — a confirm popup (`_popup_choose`, cautious default) on the TUI's trust, trust-all, bless
and remove; (3) the cross-scope lint of tui-theme-04 would at least have named it. Regression test:
the sandbox above as a unit test on `Config` layers. **Effort:** S (1+2). **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays HIGH. My own sandbox `$RUN/scratch/verify-tui-theme/home` has a synced, never-trusted plugin `evil` (`code: evil.py`, `evil.hu` = `{ keys: { plugins: { trust-all: [ j down ] } } }`). `plugin list` shows `ok  [ships code — untrusted; run: configsys plugin trust evil]` / `provides: keys`. `check` gives only `warn plugin evilsrc: untrusted code`. `configsys keys` lists `trust-all  j / ↓` under `[plugins]` and names no layer. `scripts/v01_trust_j.py` drives the real `menu._route_key` and `PluginsScreen.handle` on a `--pretend` Context (layers `repo config.hu`, `plugin evil.hu`, `user configsys.hu`): `route 106 on plugins -> (None, None) | screen action: trust-all`, and the same for `KEY_DOWN` (258). After `j` the cursor is still 0 and the note is `'[pretend] would trust 1 plugin(s) — not saved\n  evil'`. ↓ gives the same. I found no guard: `handle` passes `km.action_for('plugins', ch)` straight to `actions.plugin_trust_all` with no popup, `layers._forbidden_by_role` doesn't list `keys`, and `Config.keys()` / `config_keys` merge every layer. No test covers a plugin layer's `keys:`. It is worse than written in two ways:
1. The trusted code runs in the same session, not only at the next start. `plugin_trust` calls `ctx.invalidate()`, which resets `_plugin_code_loaded`, so the Components reload that follows (`menu_dirty` → `_reload` → `load_pipeline` → `routes` → `ensure_plugin_code`) imports it. I confirmed this by reading; I did not grant trust for real.
2. The `remove` variant needs no code at all. In `home-remove`, a data-only plugin (`evil2.hu` = `{ keys: { plugins: { remove: [ j down ] } } }`) shows plain `ok` / `provides: keys` in `plugin list`, and `check` says nothing about it. With the cursor on the primary (row 0 there), `j` gives `'[pretend] would remove file:…/mysrc and delete its synced dir'`. `plugin_remove` has no guard for the primary or for unpushed work (this compounds actions-01), and each further `j` takes the next row.

Why not CRITICAL: the same untrusted plugin can already run code at the next install through an overridden binding (security-01/-02). What this adds is a navigation-key trigger and a forged consent step, and this series rates that shape HIGH.

### tui-theme-03 [HIGH] correctness — "export theme pack" / "promote full theme → primary" drop the Theme page and every unlisted role, then promote deletes the local originals
`configsys/tui/theme.py:324-365` (`full_snapshot`: `:334` iterates `DEMO_PAGES`, not `ALL_PAGES`;
`:337` iterates `PAGE_ROLES[page]`, which misses roles the screens paint — tui-theme-08);
`configsys/actions.py:1162-1178` (`save_theme_to_primary`: writes the snapshot, then
`set_theme(user_config_file, {})`); `docs/theming.md:212-218` promises "the *complete* look (every
map color, every page role, the gradients)".
The editor lets you edit the `theme` page (F7) and a hand-written config can override any role on
any page; neither survives the snapshot, and promote then removes the local theme that held them —
the user's work is gone (the primary only has the incomplete snapshot). `load_theme` of such a pack
also replaces the user's overrides wholesale.
**(reproduced)** `full_snapshot({'pages': {'theme': {'component': {'fg': '#ff0000'}, 'gradient': …},
'components': {'select_marker': …, 'op_mixed': …, 'issue_error': …}}})` →
`theme page in snapshot: False` · `components.select_marker: None` · `components.op_mixed: None` ·
`components.issue_error: None`. The clear is verified by reading `actions.py:1175-1176`.
**Fix:** snapshot `ALL_PAGES`, and per page every role in `ROLE_DEFAULTS` (minus the passthrough
four) ∪ any role key present in the user's spec — a "complete" snapshot should not depend on a
hand-kept list. Test: override `pages.theme.component` + `pages.components.select_marker`, snapshot,
re-resolve, assert both survive. **Effort:** S. **Tier:** B.

**Verified:** CONFIRMED (reproduced). Stays HIGH. I ran it end to end in `$RUN/scratch/verify-tui-theme/home-promote`. The primary `primsrc` is a synced copy with no `.git`. The top config's `theme:` sets:
- `pages.theme.component.fg #ff0000` and the theme-page gradient `#300010`
- `pages.components.select_marker #00ff00`, `op_mixed #0000ff` and `component #123456`

`scripts/v03_promote.py` calls `actions.save_theme_to_primary(ctx)`, the Theme screen's `s` → promote path, with no journal bracket open and a recording runner that took 0 calls. It returns `(True, 'primsrc')`. A fresh Context then resolves `theme.component fg=(235, 235, 235)` and the theme gradient from `(32, 11, 24)`, both built-ins. `components.select_marker` and `op_mixed` resolve to the default `(200, 140, 240)`, while the listed `components.component` keeps `(18, 52, 86)`. The top config's `theme:` block is gone, and the primary's snapshot holds pages `components … config` only, with no `theme`, `select_marker` or `op_mixed`. `Config.theme()` passes every page and role through, so the loss is entirely in `full_snapshot` (`DEMO_PAGES` × `PAGE_ROLES`). Export (`save_theme_plugin`) uses the same snapshot. The promote popup reads "promote pins the FULL look into the primary … continue?". The Theme page can be edited in the editor (F7), so a TUI-only user can lose work this way. No test covers it. One mitigation the text misses: once a primary is blessed, every live edit and every `theme set` lands in the primary (`actions.edit_target`). The TUI journals every action, so a promote that overwrites a primary-held theme becomes a configsys commit that `plugin undo` reverts. The loss can't be undone in the case shown here: a top-config theme written before the primary was blessed, or edited by hand.

### tui-theme-02 [MED] correctness — palette-slot exhaustion paints UNRELATED colors (white bands on the Config page)
`configsys/tui/theme.py:536-564` (`Palette._color`), `:467-487` (all seven pages' gradient bands
allocated eagerly in `__init__`), `:503-510` (`new_frame` docstring: "Color SLOTS persist (they're
bounded by the theme's distinct colors, < 256)").
In palette-redefinition truecolor mode (`have256 and can_change_color()` but no `-direct` entry —
tmux/SSH without a truecolor signal, a Python curses without extended colors, a failed direct
build) every distinct color takes one of the 240 slots 16..255. The defaults already use 172. When
they run out, `_color` falls back to `rgb_to_256(rgb)` — but in this mode those indexes **are** the
redefined slots, so the color shows whatever earlier theme color holds that slot: not an
approximation, an arbitrary wrong color. Pages allocate in dict order, so the later pages
(dotfiles, config, theme) and any map color the user adds in the editor take the hit.
`theming.md:151` encourages exactly the trigger ("a wider range renders a smoother ramp").
**(reproduced)** `.venv/bin/python -I $RUN/scratch/tui-theme/slots.py` (fake curses, COLORS=256,
can_change_color, seven distinct 49-band gradients) → `slots used 240` …
`config: gradient top-left wants (16, 16, 48), gets slot 17 which holds (235, 235, 235)` (the
`title` near-white) · `theme: … wants (48, 0, 16), gets slot 52 which holds (36, 0, 36)`.
**Fix:** when slots are exhausted in redefinition mode, return the NEAREST already-allocated slot
(min rgb distance over `_color_cache`) instead of `rgb_to_256`; allocate a page's bands lazily in
`use_page` with a per-page budget (`(COLORS - 16 - len(map)) // len(ALL_PAGES)` ≈ 30) capping `n`;
surface the clamp in `color_mode` (`24-bit (gradient reduced)`); fix the docstring. Fake-curses test:
seven wide gradients → no gradient band resolves to a slot whose rgb differs by > a threshold.
**Effort:** S-M. **Tier:** B.

**Verified:** CONFIRMED (reproduced). Severity HIGH → MED. `scripts/v02_pty.py` runs real ncurses under a pty (`TERM=xterm-256color`, no `COLORTERM`) and gets `COLORS 256`, `can_change_color True` and `color_mode '24-bit'`. Widening ONE page (`components` gradient `#600060 → #000000`, 96 bands) uses all 240 slots, and the Theme page's last bands resolve to `[255, 16, 16, 16, 16, 16, 16, 16]`. curses emits `\x1b]4;16;rgb:78/C7/FF\x1b\\` (slot 16 holds the sky-blue `header` color), then `\x1b[38;5;16m\x1b[48;5;16m` for the bottom-right cell: a bright band where near-black rose was asked for. Fake-curses counts from `scripts/v02_slots.py`:

| theme | slots used | colors aliased |
|---|---|---|
| defaults | 172 | 0 |
| one page at 96 bands | 240 | 7 |
| three pages at 49 bands | 240 | 16 |
| two pages at 96 bands | 240 | 79 (onto slot 17, the near-white `title`) |
| the reviewer's seven pages at 49 bands | 240 | 120 |

Rendering every screen sample on the defaults adds only one lazy slot (173). `#400040` on one page reaches 217 with nothing aliased. Gradients are dark, so almost every overflowed band quantizes to cube index 16, which holds the first map color (`header`). The wrong color is therefore consistent, not random. Corrections to the text:
- Stock tmux never reaches this mode. `tmux-256color` and `screen-256color` have no `ccc` (per infocmp), so they take the cube path, which can't alias.
- Over SSH the gradient is off by default (effects auto-reduced), so no bands are allocated unless `effects: full` is set.
- A map color added in the editor is allocated first, so it never aliases. It pushes the last pages' bands over the limit instead.

No test covers redefinition mode. Why the severity changed: the effect is cosmetic, with no data or safety impact. It needs palette-redefinition mode (a local xterm/urxvt-style 256-color terminfo with `ccc` and no truecolor signal, or a failed `-direct` build) and a theme about 70 colors past the defaults. That matches the reach and effect of tui-theme-06/-07, which this file rates MED.

### tui-theme-04 [MED] correctness — a higher layer's `screens:` / `global` rebind is silently shadowed on some pages; config.hu's own example makes `t` TRUST on Plugins
`configsys/tui/keyspec.py:91-132` (steals only within one scope), `:318-364` (`lint_keys`: "A page key
that shadows a `global` one is NOT flagged"); `configsys/tui/menu.py:1604-1619` (page-own first, then
global router actions, then `screens`, then global nav); `config.hu:195` (the documented example
`keys: { global: { quit: [ q ctrl-c ] }  screens: { theme: t } }`), `config.hu:202-204` ("None of the
shipped page sections take them").
Page-wins is intentional when the repo authors both bindings. But when the USER (a higher layer)
binds `screens: { theme: t }` or `global: { quit: x }`, a LOWER layer's page binding of the same key
still wins on that page, and `check` says nothing. With config.hu's example, `t` switches to Theme on
four screens but is `track-one` on Profiles, `theme` on Config, and **`trust` on Plugins** (no
confirmation — the cursor plugin is trusted). Likewise `global: { quit: x }` quits only on Dotfiles
and Config; elsewhere `x` stages a remove / removes a plugin / resets a role. And a `screens:` key
beats global navigation everywhere (`screens: { theme: j }` → `j` no longer moves down), also
unreported. (Related: `lint_merged`'s lockout check is skipped when `global` itself has no quit key
left — `exits` is empty — though Ctrl-C still exits via SIGINT, see tui-theme-12.)
**(reproduced)** repo `config.hu` + a user layer, routing every screen with `menu._route_key`:
`{ keys: { screens: { theme: t } } }` → `check warnings: []`, `profiles 't' -> (None, None) screen
action track-one`, `plugins 't' -> (None, None) screen action trust`, `config … theme`, others
`(None, 'theme')`. `{ keys: { global: { quit: x } } }` → `check warnings: []`; `x` is quit only on
dotfiles/config. `{ keys: { screens: { theme: j } } }` → `check: []`, `j on components -> (None,
'theme') (global says down)`.
**Fix:** make rebind-wins follow the router's precedence: a higher layer's `global` router-action or
`screens` binding of key k takes k from lower-layer PAGE scopes (warning per page "on plugins, 't'
now switches to theme instead of trust (config.hu)"), and a `screens` binding takes k from lower
`global` nav actions; same-layer page-wins stays. At minimum, lint the shadow. Change config.hu's
example to a free key. Tests: the three reproductions. **Effort:** M. **Tier:** B.

### tui-theme-05 [MED] correctness — a key stolen by a middle layer stays dead after the top layer rebinds the stealing action
`configsys/tui/keyspec.py:107-131` (`merge_layer_keys` steals sequentially, layer by layer).
Steals are computed against intermediate bindings, not final ones. A plugin binds
`components: { where: i }` (taking `i` from `op-install`); the user, disliking it, sets
`components: { where: w }` — `where` moves back, but `op-install` stays UNBOUND, so the core
install key does nothing on Components. `check` names only the plugin's steal ("op-install is now
unbound"), which the user's own edit already superseded.
**(reproduced)** layers repo `config.hu` < plugin `{ keys: { components: { where: i } } }` < user
`{ keys: { components: { where: w } } }` → `final where: w | op-install: None`,
`'i' on components -> None`, `check: ["x.hu: keys.components.where: 'i' takes the key from
'op-install' (config.hu) — 'op-install' is now unbound in keys.components"]`.
**Fix:** two passes: (1) the winning spec + owner layer per (scope, action) (plain per-action
overlay); (2) for each code held by more than one FINAL action in a scope, keep it on the
highest-owner action and strip it from the others, warning once. **Effort:** S. **Tier:** B.

### tui-theme-06 [MED] correctness — `--color 256` / `--color 16` on a terminal whose TERM is already a `-direct` entry paints near-black / blue text
`configsys/tui/theme.py:435-454` (the cap clears `self.direct`), `:542-562` (`_color` then emits
xterm-256 / ANSI-16 indexes); `configsys/tui/screen.py:150-153` (`direct_color_setup` keeps a TERM
that already contains `direct`).
A `-direct` terminfo (`xterm-direct`, `tmux-direct` — a common tmux `default-terminal` for truecolor —
`foot-direct`, …) numbers colors as packed RGB: index 210 is `rgb(0,0,210)`, 9 is `rgb(0,0,9)`. The
cap turns `direct` off, so `_color` hands curses cube / ANSI indexes, which the terminfo encodes as
near-black blues: every role becomes unreadable — exactly when the user asked for a safer depth.
`color_mode` / `--probe` still report "256-color (approx)" / "16-color".
**(reproduced)** `$RUN/scratch/tui-theme/direct_cap.py` under a pty, painting the `error` role:
`TERM xterm-direct cap 256` → SGR `\x1b[38:2::0:0:210m` (`MODE=256-color (approx) COLORS=16777216
idx=210`); `cap 16` → `\x1b[38:2::0:0:9m`; the same caps on `xterm-256color` → `\x1b[38;5;210m` /
`\x1b[91m` (correct); auto on `xterm-direct` → `\x1b[38:2::235:95:95m` (correct).
**Fix:** keep "the terminfo numbering is direct" (`curses.COLORS >= 1<<24`, fixed at initscr)
separate from the depth cap: when numbering is direct and the cap is lower, quantize the rgb to the
capped palette, then pack the QUANTIZED rgb (indexes 0..7 stay ANSI under `-direct`; the bright 8..15
pack their standard rgb). Or, in `curses_screen`, start against the non-direct sibling when a cap
< truecolor is set. Add a pty test like `direct_cap.py`. **Effort:** S. **Tier:** B.

### tui-theme-07 [MED] correctness — the per-frame 255-pair budget overflows on Profiles with a modestly wider gradient; overflow is silent
`configsys/tui/theme.py:127` (`GRAD_MAX_BANDS = 96`), `:479-482` (`n = max(16, min(96, span + 1))`),
`:588-603` (`_pair`: `if n > 255: return curses.A_NORMAL`), `:644-646` (a text cell's pair is
`(fg, band)`).
Every (fg role, gradient band) combination is a pair, so pairs/frame ≈ visible fg roles × bands
crossed. The defaults sit at 45-151 pairs/frame (Theme ≈150), but Profiles reaches 251 with a
`#303030→#000000` gradient (49 bands) and overflows with `#404040` (65 bands): those cells drop to
the terminal's default colors with no gradient behind them — readable, but holes and wrong colors
that shift with draw order. Nothing reports it. (Downgraded from the 2026-09 HIGH: the result is
legible, unlike tui-theme-02.)
**(reproduced)** `$RUN/scratch/tui-theme/pairs.py` (real Palette, fake curses, every screen's sample
through its real `build_vm`/`draw`): defaults → max `theme 50x200: pairs= 151`; `#303030` →
`profiles 60x240: pairs= 251`; `#404040` → `profiles 40x120: pairs= 255  A_NORMAL fallbacks=42`,
`50x200 … 94`, `60x240 … 133`.
**Fix:** quantize `band()` for TEXT to a coarse sub-band (≈8-12 — a one-level bg difference behind a
glyph is invisible) while `fill()` keeps full resolution; or budget `n` against
`(255 - n_fill) / visible_fg_roles`; on overflow reuse the nearest cached pair with the same fg
rather than `A_NORMAL`; count overflows into `color_mode`. Fake-curses test asserting no
`A_NORMAL` fallback for the samples at 60x240 with a 65-band gradient. **Effort:** S-M. **Tier:** B.

### tui-theme-08 [MED] data-driven — `PAGE_ROLES` still disagrees with what the screens paint (the editor can't reach several roles; it offers dead ones)
`configsys/tui/theme.py:194-214` (`PAGE_ROLES` — "The roles each SCREEN actually uses"), consumed by
the editor's role list (`menu.py:4140-4143`) and by `full_snapshot` (tui-theme-03).
Rendering every screen's sample through a recording palette (and a static scan of each
`screens/*.py`) shows: Components paints `select_marker`, `op_mixed`, `profile`, `link`, `error`,
`unsupported`, `issue_error` — none listed, so `»`, the scroll thumbs, the mixed-op badge, and the
error/unsupported statuses (which the sample deliberately shows, `test_theme.py:262-276`) can't be
retinted there; Profiles paints `installed` (unlisted); Plugins `locked`, `select_marker`; Glue and
Config `select_marker`; Theme `unit`, `select_marker`. Meanwhile `os` is listed on six pages and
painted only by Components (`screens/components.py:127`); `unit`/`missing` are listed on
Plugins/Glue/Dotfiles and never painted. `select_marker` is themeable on no page.
**(reproduced)** `$RUN/scratch/tui-theme/roles.py` → e.g. `[components -> page components] painted
(style/at) but NOT in PAGE_ROLES: ['error', 'op_mixed', 'profile', 'select_marker', 'unsupported']`;
`[profiles …] ['installed', 'select_marker']`; `[plugins …] in PAGE_ROLES but never painted here:
['missing', 'os', 'outdated', 'selection', 'unit']` (static scan adds `issue_error`, `link` on
Components and `locked` on Plugins).
**Fix:** a test that renders each sample through a recording palette and asserts painted ⊆ listed
and listed ⊆ painted ∪ {`selection`} (the scratch script is ~30 lines); then correct the table (or
generate it at test time and check it in). **Effort:** S. **Tier:** B.

### tui-theme-09 [MED] correctness — a splash provider whose constructor raises bricks TUI start (no fallback)
`configsys/tui/splash.py:145` (`provider = provider_cls(scr, pal, (h, w), seed)` sits outside the
`try`), `:146-150` (`fps` / `min_duration` read unvalidated from the class); `configsys/tui/menu.py:4748`
(`run_splash(...)` unwrapped inside `curses_screen()`); docstring `:138-139` "Never raises for a
misbehaving provider frame".
A trusted splash plugin whose `__init__` fails (an attribute a newer/older Palette lacks, a bad size
assumption) propagates out of `run()` — the TUI never starts, and the user's only way out is to
know about `splash: off` / `CONFIGSYS_NO_SPLASH`. The host likewise trusts `fps` (negative → a busy
loop at 100% CPU; `1e-6` → `time.sleep` of ~10⁶ s, the TUI never appears) and `min_duration`
(`None` → `TypeError` outside the try). Trusted code can do worse deliberately; this is about a
buggy provider failing safe, which the host promises.
**(reproduced)** a `Splash` subclass raising `AttributeError` in `__init__`, run through
`host.run_splash` with a fake window → `constructor raise ESCAPES run_splash: AttributeError
'Palette' object has no attribute 'depth'`.
**Fix:** construct inside the `try` (on failure: `animate=False`, text fallback, and a
`splash_note` naming the provider); clamp `fps` to [1, 120] and coerce `min_duration` to a float ≥ 0.
Tests: `__init__` raising; `fps = -1`. **Effort:** S. **Tier:** B.

### tui-theme-10 [LOW] safety — keys mashed to dismiss the splash land in Components as actions; a terminal resize counts as "skip"
`configsys/tui/splash.py:182-190` (after a skip, the text branch never calls `getch()`), `:204-208`
(`finally` has no `curses.flushinp()`); `menu.py:4748-4760` (none either — the only `flushinp`
calls are in `screens/components.py:390-445`).
Once the animation is skipped, every key typed while the progress line finishes stays queued and is
dispatched on Components: `x` / `L` / `i` stage ops, `R` immediately runs `configsys refresh` (index
update under sudo), `q` opens the quit prompt, a digit switches screen. Separately, `KEY_RESIZE`
(SIGWINCH) is just "a key": resizing the window skips the animation, and ends a `--splash-linger`
show. No surprises says the dismiss key should dismiss and nothing else.
**(reproduced)** fake window with keys `[' ', 'x', 'L', 'X']`, inspection still running for six frames
→ `getch calls by the host: 1 | keys left queued for the menu: ['x', 'L', 'X']`; with
`[KEY_RESIZE]` and `linger=True` → `linger splash ended by KEY_RESIZE after 1 frames`.
**Fix:** `curses.flushinp()` in `run_splash`'s `finally` (or drain `getch()` in the text branch);
ignore `KEY_RESIZE` in the skip test (optionally re-read `getmaxyx()`). Tests: the two above.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity MED → LOW. `scripts/v10_pty.py` runs real curses under a pty with the real `run_splash` and `BrailleBarSplash`. I pressed space (skip), then typed `x`, `L`, `R` while inspection was still running: `{"splash_returned_after_s": 2.01, "menu_would_receive": ["x", "L", "R"]}`. A real pty resize plus SIGWINCH ended a `linger=True` splash 0.5 s in. The control run (`v10_pty_control.py`, no resize) lasted until a key at 2.54 s. Nothing flushes between `run_splash` and the menu loop: a grep for `flushinp` finds only `screens/components.py:390, 422, 445`. Why the severity changed:
- The dismiss key itself is consumed, so only type-ahead after it reaches the menu.
- The natural skip keys do nothing harmful on Components. Space marks a row, Enter toggles expansion and Esc is unbound. `q` opens "Really quit?", which starts on "No" and is cancelled by q or Esc.
- Staged ops are visible and `c` unstages them. Running them takes `X`, then a typed `y` + Enter at the cooked `Proceed? [y/N]` prompt.
- The only immediate side effects need deliberate keys: `R` (an announced, sudo-prompting index refresh), or a digit followed by a Plugins single-key action.
- A resize skipping the animation is cosmetic.

One trade-off for the fix: `flushinp` also discards type-ahead the user meant to send.

### tui-theme-11 [LOW] correctness — the `?` help and the nav-bar legend show keys a page shadows; a page-scope `page-down` turns into "F1-F7 preview sample page"
`configsys/tui/keyspec.py:202-205` (`glyph` falls back to `global` without checking the page
shadows that key), `:207-230` (`help_rows`: global rows list global keys verbatim; `:222`
`a.startswith('page-')` also matches `page-down`/`page-up`; `:225-226` hard-codes `page-7` /
`'F1-F7'`; `:216` doesn't dedupe glyphs); `menu.py:1590-1598` (nav-bar hint). Module docstring
`:1-4` promises "bindings and their on-screen hints can never drift".
Shipped config: Components' help lists `tab` as both "switch pane" and "expand / collapse all"
(only the latter is true there), and every page shows `⏎/⏎ activate / open` (enter + kpenter).
With `components: { where: q }` the nav bar still says `q quit` and help shows `q` for both. With
`components: { page-down: n }` the help row becomes "F1-F7 preview sample page" (the theme screen's
own handler checks `isdigit()`, `screens/theme.py:220`; `help_rows` doesn't).
**(reproduced)** repo + `{ keys: { components: { page-down: n  quit: Z } } }` → help rows include
`'F1-F7' preview sample page` on components; repo + `{ keys: { components: { where: q } } }` →
`nav-bar hint glyph for quit on components: q`, help rows `'q' quit (asks to confirm)` and
`'q' explain component (where)`; repo alone → `components {'⏎': ['activate / open', 'activate /
open'], 'tab': ['switch pane', 'expand / collapse all']}`.
**Fix:** `Keymap.effective_codes(scope, action)` = the action's page codes, else the global codes
minus every code the page binds to something else; `glyph`/`help_rows` use it, drop a global row
whose effective codes are empty, dedupe glyphs, and match `page-<digits>` only (range from
`len(theme.ALL_PAGES)`). **Effort:** S. **Tier:** B.

### tui-theme-12 [LOW] correctness — keyspec binds keys the TUI can never receive (`ctrl-c`, `ctrl-s`, `ctrl-q`, `ctrl-z`, non-ASCII); config.hu's own example binds one
`configsys/tui/keyspec.py:38-60` (`parse_key` accepts any `ctrl-<letter>` and any single
character), `:318-364` (`lint_keys` doesn't flag them); `configsys/tui/screen.py:7-8, 221-227` (cbreak
keeps ISIG; IXON is left on); `config.hu:195` (`quit: [ q  ctrl-c ]`).
Under the TUI's cbreak mode Ctrl-C raises SIGINT (KeyboardInterrupt → `app.py:4930` "interrupted",
skipping the TUI quit path — e.g. the `auto-on-quit` primary push), Ctrl-S/Ctrl-Q are XON/XOFF flow
control, Ctrl-Z is SIGTSTP, and a non-ASCII literal arrives from `getch()` as UTF-8 bytes. Such a
binding is dead, silently.
**(reproduced)** `$RUN/scratch/tui-theme/keys_pty.py` (the real `curses_screen()` under a pty):
typing `é` then Ctrl-C → `getch saw: [195, 169, 'KeyboardInterrupt']` while
`parse_key('é') = 233`, `parse_key('ctrl-c') = 3`; `keys_pty3.py`: Ctrl-S, `a`, Ctrl-Q, `b` →
`getch saw: [97, 98, -1, -1]` (17/19 never delivered).
**Fix:** reject (or `check`-warn on) codes 3, 17, 19, 26, 28 and any single char ≥ 128 in
`parse_key`/`lint_keys` ("never reaches the TUI: the terminal uses it for …"); fix the config.hu
example; route Ctrl-C to the quit path (a SIGINT handler around the loop) if it should quit
gracefully. **Effort:** S. **Tier:** B.

### tui-theme-13 [LOW] correctness — `colors-basic:` is keyed by RGB, so overriding one name recolors every name that shares its RGB
`configsys/tui/theme.py:105-124` (`resolve_basic` → `{rgb: slot}`), `:557-558` (`_color` looks the
slot up by rgb); `docs/theming.md:87-93` ("overrides that choice **per map name**").
Built-in names share rgb (`installed` = `op_install` = `diff_add` (via `installed`), `error` =
`op_remove`, `outdated` = `op_upgrade`, `locked` = `op_lock`), so `colors-basic: { op_install: cyan }`
also turns the installed status and diff additions cyan in 8/16-color mode; and retinting a 24-bit
`colors.<name>` onto another name's rgb silently adopts (or overrides) that name's ANSI slot. The
existing test enshrines the keying (`test_theme.py:63-73`).
**(reproduced)** fake curses COLORS=16: `{}` → `installed fg 10 op_install fg 10 diff_add fg 10`;
`{'colors-basic': {'op_install': 'cyan'}}` → `installed fg 6 op_install fg 6 diff_add fg 6`.
**Fix:** resolve the basic slot by NAME: keep each role's fg/bg map-name ref alongside its rgb in
`resolve_theme` and let `Palette` look up `basic[name]` before falling back to the rgb quantizer
(literal colors keep the rgb path). **Effort:** S-M. **Tier:** B.

### tui-theme-14 [LOW] correctness — off-token parsing is hand-rolled five times and disagrees: `theme set …gradient.enabled 0` "succeeds", changes nothing, and `theme show` then hides it
`configsys/tui/theme.py:305, 314, 318` (`(False, 'false', 'no', 'off')`), `:233-238` (`_flag` honours
`'0'`/`'on'`/case); `configsys/actions.py:1000` (`theme_overrides`, same 4-token set),
`:957, 978-979` (`set_theme_value` coerces only bold/underline/reverse); `configsys/tui/menu.py:4192-4194`
(`page_gradient_enabled`), `:2207-2212` (`_chosen_splash`). The role-overlay
(`dict(ROLE_DEFAULTS[role]); st.update(ov)`) is also copied three times (`theme.py:298-302`,
`:338-341`, `menu.py:4178-4186`).
`enabled: 0`, `False`, `OFF`, `no ` keep the gradient on, and because `theme_overrides` drops the
unrecognised `enabled` key, `theme show` reports "no theme overrides" for a value the user just set.
**(reproduced)** sandbox: `configsys --home H --os pop theme set pages.components.gradient.enabled 0`
→ `set pages.components.gradient.enabled = 0  (in top config)`; `theme show` → `no theme overrides
(using built-in defaults)`; `resolve_theme(ctx.config.theme())` → `components gradient enabled =
True`. Pure: `'0'/'False'/'OFF'/'no '` → `gradient.enabled -> True` while `_flag(v) -> False`.
**Fix:** one `theme.is_off(v)` (built on `_flag`'s parser) and one
`theme.effective_role(theme, page, role)`, used by all five sites; add `enabled` to
`_THEME_BOOL_ATTRS`. **Effort:** S. **Tier:** B.

### tui-theme-15 [LOW] feature — no theme lint: typo'd roles/pages, unparseable colors and CSS-style names are accepted by `theme set` and ignored by `check`
`configsys/tui/theme.py:286-321` (`resolve_theme` iterates `ROLE_DEFAULTS` and `ALL_PAGES`, so
unknown keys vanish; an unparseable fg falls back to `(235,235,235)`), `:241-268` (`parse_color`'s
hex path doesn't clamp: `'#-1-1-1'` → `(-1, -1, -1)` while the list/"r,g,b" paths clamp);
`configsys/app.py:2450-2461` (`check` flags only the legacy `palette`/`elements`/`gradient` keys).
Keys have `lint_keys`; the theme has nothing comparable.
**(reproduced)** sandbox: `theme set pages.components.componnet.fg red`,
`pages.profile.component.fg #ff0000`, `colors.accent #12345`, `pages.components.component.fg reddish`
→ all `set … (in top config)`; `check` → `0 error(s), 1 warning(s)` (only the python-floor warning).
**Fix:** `theme.lint_theme(layers)` (unknown page / role / top key, non-map role style, unparseable
color, a ref that is neither a map name nor a literal) wired into `check` and `theme set`; clamp the
hex path. **Effort:** S. **Tier:** G.

### tui-theme-16 [LOW] correctness — `rgb_to_256` assumes a linear 6-level cube; 22 of 28 map colors miss their nearest xterm-256 entry (the selection bar turns light slate)
`configsys/tui/theme.py:368-375` (`round(c / 255 * 5)`; the real cube levels are 0, 95, 135, 175,
215, 255; the grey ramp is `8 + 10k`, and near-greys never consider it). Used for every color on the
"256-color (approx)" path and by `splash._sgr_encode` for raw splashes.
**(reproduced)** nearest-neighbour comparison over `COLOR_MAP` → `sel_bg (58, 34, 88) -> 60 (95, 95,
135) err 85  nearest 237 (58, 58, 58) err 38` · `row_desc … err 59 nearest … err 15` · `error (235,
95, 95) -> 210 (255, 135, 135) err 60  nearest 167 (215, 95, 95) err 20` · `22 of 28 map colors not
at their nearest xterm-256 entry`.
**Fix:** snap each channel to the nearest real cube level, compare against the nearest grey-ramp
entry, return the closer (a 256-entry precomputed table also works). **Effort:** S. **Tier:** B.

### tui-theme-17 [LOW] security — `configsys check` prints raw layer strings, so a plugin's `keys:` can emit terminal escape sequences
`configsys/tui/keyspec.py:337, 340-341, 347-348, 353, 356-357` (scope / action / key interpolated
with `'{…}'`, while the steal warning at `:124` already uses `repr`).
Who: any plugin layer (no trust needed — `keys:` loads from every layer); when: `configsys check`;
effect: OSC/CSI sequences reach the terminal (title, clear, OSC 52 clipboard write on terminals that
allow it). An untrusted plugin can likely already reach the terminal through other printed strings
(component names / descriptions in `inspect`/`where`), so this is hygiene. Legends are safe
(`key_name` emits only printable ASCII / known glyphs).
**(reproduced)** `lint_keys([layer{'keys': {'components': {'where': '\x1b]0;pwned\x07',
'\x1b[2Jx': 'q'}}}])` → `"evil.hu: keys.components.where: unparseable key '\x1b]0;pwned\x07'"`,
`"evil.hu: unknown action 'keys.components.\x1b[2Jx' (not a components action)"` (raw ESC bytes).
**Fix:** `repr()` (or strip C0/C1 controls) every layer-supplied string in lint output — one
`_shown(s)` helper. **Effort:** S. **Tier:** A.

### tui-theme-18 [LOW] security — `terminfo.build_direct` uses the TERM-derived name as a path without containment; the temp file name is shared
`configsys/tui/terminfo.py:181-182` (`entry_path` joins `name[0]`, `name`), `:185-192`
(`find_compiled`), `:195-213` (`build_direct`, `tmp = dest + '.tmp'`); the name comes from `$TERM`
(`screen.py:154-158`).
ncurses refuses a TERM containing `/` or `..`; the pure-Python builder writes wherever the name
points. TERM is the user's own environment (and an SSH client's), so there is no privilege
boundary — defense in depth only. Two TUIs building the same entry concurrently share
`<dest>.tmp`: one's `os.replace` can install the other's half-written file, which
`_terminfo_exists` then trusts forever (the cache is never rebuilt — also stale after a terminal
upgrade changes its base entry).
**(reproduced)** `terminfo.build_direct('../../../escaped-direct', 'xterm-256color', ['/lib/terminfo'],
out)` → `True`, file written at `$S/ti/escaped-direct`, three levels above `out`.
**Fix:** refuse a name/term that isn't a single safe segment (no `/`, NUL, `.`/`..`); write via
`tempfile.mkstemp(dir=…)`; rebuild when the base entry's mtime is newer than the cached one
(`screen._build_direct_entry`). **Effort:** S. **Tier:** A.

### tui-theme-19 [LOW] abi — the splash provider ABI is re-exported as frozen but not pinned, and under-specified
`configsys/splashes.py:20-67` (`SplashFrame`, `Splash`), `configsys/plugins.py:62` (`__all__`
re-exports `Splash`, `SplashFrame`, `register_splash`); `test/test_abi_surface.py` (pins the Driver
surface only); `configsys/tui/splash.py:50-53` (the host reads `pal.truecolor/direct/mono/have256/
have16`), `:146-151` (class attrs `fps`, `min_duration`, `raw`; `at_rest`), `:131-208` (never calls
`pal.new_frame()` during a splash).
Gaps a third-party splash author will hit: (a) nothing pins `SplashFrame._fields`, the constructor
signature, the class attrs or `register_splash`/`get_splash`; (b) the `pal` contract
(`rgb_attr`/`rgb_pair`/`get`) is documented in a docstring only, and `get(name)` is map-first, not
"get(role)" as documented; a raw provider has no way to learn the resolved depth except private
flags; (c) attr lifetime/budget is undocumented — attrs stay valid for the whole splash (the host
never recycles pairs, which is why ocean/blocks/maze can pre-allocate in setup), so a provider that
allocates per frame silently exhausts the 255 pairs (→ `A_NORMAL`) and, in redefinition mode, the
slots (→ tui-theme-02's aliasing); (d) two "at rest" conventions (the return value vs.
`self.at_rest` for raw); (e) size is fixed at construction and resize skips (tui-theme-10).
**Fix:** before third parties ship splashes: pin the surface in `test_abi_surface` (fields, ctor,
attrs, registry functions, the three Palette methods); add a `depth` string to `SplashFrame` (a
defaulted namedtuple field keeps old providers working) or `Palette.depth`; document "attrs live for
the whole splash; ≤ ~150 pairs / ~150 colors; allocate in `__init__`". **Effort:** S. **Tier:** F.

### tui-theme-20 [LOW] refactor — color depth is six booleans re-derived three times
`configsys/tui/theme.py:435-457` (`have256`, `direct`, `truecolor`, `mono`, `have16`, `lowcolor`),
`:491-501` (`color_mode` re-derives an enum), `configsys/tui/splash.py:50-53` (re-derives it again via
`getattr`). The conflation inside `direct` (numbering vs. output depth) is the bug in tui-theme-06.
**Fix:** `Palette.depth ∈ {'none','8','16','256','truecolor','direct'}` plus a separate
`direct_numbering` fact; derive the flags (keep them as properties for the splash plugins until
tui-theme-19 lands). Collapses `color_mode` and `_sgr_downconvert`'s ladder. **Effort:** S.
**Tier:** D.

### tui-theme-21 [LOW] refactor — the screen/page list is hand-copied in about nine places
`theme.py:191-192` (`DEMO_PAGES`/`ALL_PAGES`), `:196-214` (`PAGE_ROLES` keys), `:218-226`
(`BUILTIN_GRADIENTS`); `keyspec.py:78-82` (`_FALLBACK['screens']`), `:239` (`SCREEN_IDS`),
`:240-257` (`KNOWN_ACTIONS` scopes + `page-1..7`), `:225-226` (`'page-7'`, `'F1-F7'`);
`menu.py:1579-1582` (`SCREENS`, `IMPLEMENTED`, `KEY_TO_SCREEN`); `app.py:3518-3519` (`cmd_keys`
order); `config.hu:198, 320-326`.
Adding a page (the glue split did) means editing all of them; tui-theme-11's `F1-F7` and
tui-theme-08's drift are symptoms. **Fix:** one screen registry (id, title, default key, page
index) in `tui/__init__` or `theme`, from which these derive; consider `page-next`/`page-prev` (or
binding page ids) instead of positional `page-N` actions. **Effort:** M. **Tier:** D.

### tui-theme-22 [LOW] feature — `configsys keys` can't say where a binding came from, what was stolen or shadowed, and reads a private field
`configsys/app.py:3512-3528` (`cmd_keys` iterates `km._m`), `configsys/tui/keyspec.py:99`
(`merge_layer_keys` tracks the owner layer, then discards it).
After tui-theme-01/04/05 the most useful question is "why does `j` do that here?", and neither the
CLI nor the TUI can answer: no per-binding layer, no "shadowed on <page>" note. Neither surface can
edit bindings either (`keys:` is humon-only; `theme` has `set/unset`). **Fix:** have
`merge_layer_keys` return owners; `Keymap.bindings()` (public) yields `(scope, action, codes,
layer)`; `configsys keys` prints the layer and any per-page shadow; optionally
`configsys keys set|unset <scope>.<action> <key…>` mirroring `theme set`. **Effort:** S (show) /
M (edit). **Tier:** G.

### tui-theme-23 [LOW] feature — modals and overlays aren't themeable and ignore the gradient
`configsys/tui/menu.py:1309-1374` (`_help_modal`: `pal.get('accent')`, the `ink` pseudo-role) and the
other overlays (diagnostics, where, popups, input box) — the paint is tui-core's, but the role model
that lacks them is `theme.py:146-185`/`:194-214`.
They paint map colors over the terminal default background (a rectangle hole in the gradient) and
no page-role edit reaches them, while `theming.md:6` says "the whole TUI palette is yours".
**Fix:** `modal_border` / `modal_title` / `modal_text` roles under a pseudo-page `overlays` in
`PAGE_ROLES` (editor-reachable), painted via `style()`. **Effort:** M. **Tier:** G.

### tui-theme-24 [LOW] comment-drift — stale comments, docstrings and doc lines in and about the area
- `theme.py:42`, `:64`, `:165` — `menu_new` is "a derived profile's OFFERED (NEW, `?`) items" /
  "offered, not the installed set" / "OFFERED (NEW) ballot rows": the derive model is gone; it marks
  NEW (undispositioned) components (`screens/profiles.py:207, 398, 432`).
- `theme.py:190` "The five content screens" — six.
- `theme.py:194-195` "The roles each SCREEN actually uses" — not true (tui-theme-08).
- `theme.py:508-509` (`new_frame`) "SLOTS … bounded by the theme's distinct colors, < 256" — false
  (tui-theme-02). `theme.py:3` points at `docs/done/theme-redesign.md` for the model; the live spec
  is `docs/theming.md`.
- `keyspec.py:1-4` "bindings and their on-screen hints can never drift" — they can (tui-theme-11).
- `docs/theming.md:167-168` — "monochrome: … and no splash", "`none` = neither": the code keeps
  the plain built-in progress splash under both (`menu.py:2213-2216`, deliberately — "a progress bar
  is feedback, not eye-candy"); `:198` "only the roles *that page actually uses*"; `:212-215`
  "every page role" (tui-theme-03); `:151` invites wider gradients without the budget caveat.
- `config.hu:195` (example rebinds `t`, shadowed on three pages; binds the dead `ctrl-c`) and
  `:202-204` ("None of the shipped page sections take them" — they take the example's `t`).
**Fix:** edit the comments with the fixes above; the theming.md lines are `/update-docs` material
once the user settles question 4. **Effort:** S. **Tier:** E.

### tui-theme-25 [LOW] reuse — `menu._commit_primary_action` re-implements `Keymap.label`; `config_keys` duplicates `Config.keys()`
`configsys/tui/menu.py:657-660` (`keyspec.ACTION_LABELS.get(f'{screen}.{act}') or
keyspec.ACTION_LABELS.get(act, act)` — exactly `Keymap.label`, `keyspec.py:196-200`, used here as the
primary commit message); `keyspec.py:135-141` (`config_keys` calls `merge_layer_keys(config._layers)`,
which is what `Config.keys()` already returns, `config.py:234-241`, while reaching into the private
`_layers`; used by `menu.py:4775`, `app.py:3516`, the render harness and tests).
**Fix:** call `Keymap.label`; replace `config_keys(cfg)` with `cfg.keys()` and delete the wrapper
(update the tests' imports). **Effort:** S. **Tier:** D.

### tui-theme-26 [NIT] dead-code — stragglers in theme.py / splash.py
`theme.py:187-188` `EDITABLE_ROLES`; `:648-657` `Palette.at()`; `:629, 632-633` the `row=` kwarg on
`style` ("accepted for call-site compatibility" — no caller passes it); `:674-678` `STATUS_COLOR`, an
identity dict used only as a membership test (`screens/components.py:239`); `splash.py:131, 194`
`run_splash(deadline=)` (never passed); `splash.py:74` `MIN_DURATION` duplicates
`Splash.min_duration` (0.6; every provider subclasses `Splash`). See the Dead code section for the
greps. **Fix:** delete them (`STATUS_COLOR` → a `frozenset` of statuses; drop `at`/`row` from
`RecordingPalette` too). **Effort:** S. **Tier:** D.

### tui-theme-27 [NIT] naming — small readability items
`theme.py:130` `_r()` → `_role_style()`, `:233` `_flag()` → `_truthy()` (40+ call sites);
`keyspec.py:29-31` `_GLYPH` renders 10/11 as `ctrl-j`/`ctrl-k` while `key_name` renders every other
control char as `^x` (`:67-68`) — legends mix both; `Palette.get(name)` (`:605-611`) is map-first
(a page role override never affects it) though the splash ABI documents it as `get(role)`;
`keyspec.py:42-43` `parse_key` accepts any `int` incl. `bool` (unreachable from humon, which
materializes strings — Python callers only). **Effort:** S. **Tier:** D.

## Test gaps

- **No fake-curses Palette tests** (the stub pattern exists: `scratch/tui-theme/pairs.py`,
  `slots.py`): slot exhaustion must never alias (02); pairs at 60×240 with a 65-band gradient (07);
  `-direct` numbering under `--color 256/16` (06, as a pty test like `direct_cap.py`); `color_mode`
  under each cap; `use_page` swap; `fill(bg=)`; `new_frame`.
- **`PAGE_ROLES` vs. painted roles** — a recording-palette render of every sample (08;
  `scratch/tui-theme/roles.py`).
- **`full_snapshot`** of `pages.theme.*` and of a role outside `PAGE_ROLES` (03).
- **keys**: an untrusted plugin layer's `keys:` (01); cross-scope shadow lint for `screens`/`global`
  rebinds (04); the stale steal (05); `help_rows` with a page-scope `page-down` and a shadowed global
  key, and the shipped `tab` on Components (11); `parse_key`/lint of tty-intercepted and non-ASCII
  keys (12); lint output with control characters (17).
- **splash**: constructor raising, `fps <= 0`, input drained after a skip, `KEY_RESIZE` (09, 10);
  `_draw_progress_text`; `deadline` (or delete it).
- **theme**: `resolve_theme` / `theme_overrides` with `enabled: '0' | 'False'` (14); a `lint_theme`
  once it exists (15); `rgb_to_256` nearest-entry property (16); `test_theme.py:63-73` currently
  ENSHRINES the rgb keying of `colors-basic` and must change with 13.
- **terminfo**: a `..`/`/` name is refused (18).
- **ABI**: `test_abi_surface.py` has nothing for the splash surface (19).

## Dead code

- `theme.EDITABLE_ROLES` — `grep -rn EDITABLE_ROLES configsys/ test/ examples/ ~/src/configsys-*/` →
  only its definition.
- `Palette.at()` — `grep -rn '\.at(' configsys/ test/ examples/ ~/src/configsys-*/ --include=*.py` →
  no caller (only the `RecordingPalette.at` mirror in `test/_render_harness.py:105`); the four splash
  plugins use only `rgb_attr`/`rgb_pair`/`get`.
- `style(row=)` / `at(row=)` — `grep -rn 'row='` → no palette caller passes it (hits are
  `cur_row=` and the harness mirror).
- `run_splash(deadline=)` — the only caller (`menu.py:4748`) doesn't pass it; no test passes
  `deadline=` (`grep -rn 'deadline=' test/`); the splash plugins' READMEs mention the host's
  deadline as a concept only.
- `splash.MIN_DURATION` — consulted only as a `getattr` default for providers that don't subclass
  `Splash`; every provider found (`~/src/configsys-splash-*/*.py`) subclasses it and sets its own.
- `theme.STATUS_COLOR` — an identity dict; `grep -rn STATUS_COLOR` → `menu.py:27` (re-export),
  `screens/components.py:17, 239` (membership only).
- Not dead (checked): `ink_dim` (a documented map name users reference, `app.py:71-75` template
  example); `config_keys` (used, but redundant — tui-theme-25); everything else in `terminfo.py`
  (round-tripped by `test_terminfo.py`). None of the owned names is in the frozen list of
  `configsys/driver.py`'s docstring; the splash names in `plugins.__all__` are all used.

## ABI / interface candidates

- **`keys:` authority** (tui-theme-01): moving `keys:` out of "every layer" changes the documented
  layer contract (`docs/plugins.md:93`, `config-format.md:35`) — do it before collaborators ship
  plugins that rely on it.
- **Splash surface** (tui-theme-19): pin it in `test_abi_surface`; add a `depth` (SplashFrame field
  with a default, or `Palette.depth`); document attr lifetime and the pair/slot budget; consider one
  at-rest convention.
- **`Keymap` public iteration** (`bindings()` with owner layers) instead of `app.cmd_keys` reading
  `km._m` (tui-theme-22).
- **`splashes.is_builtin(name)`** instead of `screens/config.py:264` importing the private
  `_BUILTIN_SPLASH_NAMES` (owned by subsystems/tui-screens; carried from 2026-09).
- **`theme.page-N` actions** tie key ids to page positions (tui-theme-21): page ids or
  `page-next`/`page-prev` before users bind them.

## Questions for the user

1. **Should `keys:` (and `theme:`) be honored from non-primary plugins at all?** Options: (a) only
   repo / primary / top config (my recommendation for `keys:`; theme plugins keep `theme:`); (b)
   plugins may bind only keys no lower layer uses; (c) keep "every layer" but put a confirmation on
   the TUI's trust / trust-all / bless / remove. (b) or (c) still leave `j` rebindable by a plugin.
2. **Cross-scope precedence for YOUR rebinds**: should a higher layer's `global`/`screens` binding
   take the key from a lower layer's page binding (your rebind wins everywhere), or should page-wins
   stay absolute and `check` only warn per page? (tui-theme-04)
3. **`NO_COLOR` vs. `--color`**: no-color.org's FAQ says per-invocation flags override `NO_COLOR`;
   configsys makes `NO_COLOR` win (`--color 256` with `NO_COLOR=1` is monochrome, and the help text
   says so). Keep it?
4. **Splash under `NO_COLOR` / `--effects none`**: the code shows the plain built-in progress bar
   ("feedback, not eye-candy"); `docs/theming.md:167-168` says "no splash". Which is intended?
5. **Freeze the splash ABI now** (tui-theme-19) — pin it and add `depth` — or leave it informal until
   a third-party splash exists?

## Refuted on verification

None. All four checked findings (01, 02, 03, 10) were confirmed (reproduced).
