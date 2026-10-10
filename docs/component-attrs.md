# Component attributes (`attrs:`)

> **Status: REFERENCE** — the `attrs:` tag vocabulary, its auto-derivation, and the Profiles attr filter; maintained.

`attrs:` is a free-form list of **cross-cutting tags** that describe a component's *kind* —
orthogonal to profiles. Profiles say "what this is *for*" (editor, browser, monitor); attrs say
"what *kind* of thing it is" (a FOSS TUI, a proprietary GUI that phones home). They exist so the
Profiles page can filter the catalog by kind **regardless of profile** — "show only CLI + FOSS",
"hide anything proprietary or that sends telemetry", etc. Attrs never affect resolution or
installation.

```
ripgrep:  { …  attrs: [ CLI  FOSS  permissive ]  … }
firefox:  { attrs: [ GUI  web  app  FOSS  copyleft  tele ]  … }
discord:  { attrs: [ GUI  app  proprietary  electron  account  cloud  online  tele  freemium ]  … }
```

## Model: axes, not a flat bag

Tags group into a few **axes**. This is what makes the filter UI clean (per-axis include/exclude)
and tells you which tags combine vs conflict. Tags are **free-form multi** across *and within* every
axis — a component may carry several from one axis (a tool that's both `CLI` and `GUI`; a project
that's `FOSS`, `copyleft`, and `GNU` all at once, so a user who likes copyleft but dislikes GNU can
filter each independently). There is **no single mandatory value** anywhere.

The vocabulary below is exactly `ATTR_AXES` in `configsys/tui/menu.py` — the tags the filter modal
offers. A tag outside it still loads and shows in the infobox, but can't be selected in the filter,
so author only these.

### 1. Interface — how you interact with it
`CLI` · `TUI` · `GUI` · `daemon` (background service/server) · `web` (browser-accessed / self-hosted
web UI) · `headless` (no UI — libs, pure daemons)

### 2. Role — what it is
`lib` · `SDK` · `app` (end-user application) · `toolchain` (compiler/interpreter) · `runtime`
(language/VM runtime) · `driver` (kernel/hardware/DKMS) · `font` · `theme` · `plugin` (extends
another app) · `game` · `service` (a `-service` companion) · `group` (a `-group` usermod companion) ·
`dotfiles` (a `-dotfiles` companion) · `glue` (a `-glue` shell-startup companion)

### 3. License / openness — free-form, combine as many as apply
`FOSS` (OSI-free) · `FOSSish` (partly non-free — open core) · `proprietary` (closed) ·
`source-available` (visible but non-OSI: BSL/SSPL) · `freeware` (gratis but closed) · `GNU` (a GNU
project) · `copyleft` (GPL-family) · `permissive` (MIT/BSD/Apache)

> `proprietary` is deliberately its own tag (not "absence of FOSS") so "hide non-free" is an
> unambiguous *exclude*. `GNU`/`copyleft`/`permissive` are independent so the license-minded can
> include/exclude each on its own. There is no per-license tag (`GPL`, `MIT`, …): a GPL project is
> `copyleft`.

### 4. Data / autonomy — what it does behind your back
`tele` (telemetry on by default) · `tele-optin` (telemetry present but **off** by default) ·
`account` (requires a login) · `cloud` (depends on a remote service) · `online` (nonfunctional
offline) · `ads` (carries advertising) · `paid` (costs money) · `freemium` (free tier + paid tier)

### 5. Pedigree / caveats
`electron` (an Electron app) · `patent` (patent-encumbered codecs — the RPM-Fusion crowd) ·
`legacy` (unmaintained / dead upstream) · `beta` (pre-release / alpha)

## Case convention

- **ALL-CAPS** for acronyms: `CLI TUI GUI FOSS FOSSish GNU SDK`.
- **lowercase** for words: `lib app daemon web headless toolchain runtime driver font theme plugin
  game service group dotfiles glue proprietary source-available freeware copyleft permissive tele
  tele-optin account cloud online ads paid freemium electron patent legacy beta`.
- Stored **as authored** (for display); the filter **matches case-insensitively**, so a stray
  `Cli` still filters correctly — but author them in canonical case.

## Auto-derivation (don't hand-tag the obvious)

Some attrs are inferred from the route at load time (`routes._derived_attrs`, table `_VIA_ATTR`)
and **unioned** with the authored `attrs:`, so companion/asset components tag themselves and the
~800 base components don't all need hand tagging:

| condition                        | derived attr |
|----------------------------------|--------------|
| a binding is `via: dotfiles`     | `dotfiles`   |
| a binding is `via: glue`         | `glue`       |
| a binding is `via: service`      | `service`    |
| a binding is `via: group`        | `group`      |
| a binding is `via: font`         | `font`       |

(Both `dotfiles` and `glue` are on the role axis, so the modal can toggle each — see the default
exclusion below.) Interface/role could be derived further later — e.g. `via: cargo`/`pip` →
`CLI`, a dev-headers component → `lib` — but the **license / data / pedigree axes must always be
authored**: only a human knows Audacity phones home. Authored tags win/merge; the derivation only
*adds*.

## Merging

`attrs:` is a valid component-level key (`routes._COMPONENT_KEYS`). Across layers it **unions**
(`_merge_component_chain`): a plugin or user layer can add a tag to a core component without
restating the rest; a `{}` tombstone clears it with everything else. `Component.attrs` = authored ∪
derived, deduped case-insensitively, first spelling kept. The add-component skill assigns attrs to
every new real component (companions get theirs by derivation).

## Profiles-view behaviour

- The highlighted component's tags render in the Profiles **detail box** (an `attrs:` line above
  `required by:`; `attrs: (untagged)` when there are none); a tag that's part of the active filter is
  prefixed `✓` (included) / `✗` (excluded) so you can see why a row shows or hides.
- **`f`** (action `attr-filter`; `F` is the live substring filter) opens the **faceted filter
  modal**: rows grouped by axis, `space` cycles a tag `· → ✓(include) → ✗(exclude) → ·`, `c` clears
  all, `enter` applies, `esc`/`q` cancels. Filter semantics (`_attr_pass`): a component passes when it
  has **none of the excluded** tags AND, for every axis you included a tag from, **at least one** of
  that axis's included tags (per-axis OR, cross-axis AND). It narrows the catalog (right pane) on top
  of the selected browse profile's membership and the substring filter.
- **`dotfiles`- and `glue`-tagged companions are hidden by default** (they live on the Dotfiles/Glue
  pages and are noise for most filtering) — the initial exclude set is `{dotfiles, glue}`; **`service`
  stays visible**. `c` in the modal clears both to reveal them, or toggle either tag on its own. The catalog title shows a `✓/✗` chip
  (`attr_summary`) once the filter deviates from that default.
- Implementation: `ProfileScreen.attr_inc`/`attr_exc` (lowercased sets), `_attr_pass()`,
  `_attr_filter_modal()`, `ATTR_AXES` in `configsys/tui/menu.py`; drawn by
  `configsys/tui/screens/profiles.py`.
