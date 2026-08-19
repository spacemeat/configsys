# Component attributes (`attrs:`)

`attrs:` is a free-form list of **cross-cutting tags** that describe a component's *kind* —
orthogonal to profiles. Profiles say "what this is *for*" (editor, browser, monitor); attrs say
"what *kind* of thing it is" (a FOSS TUI, a proprietary GUI that phones home). They exist so the
Profiles page can filter the catalog by kind **regardless of profile** — "show only CLI + FOSS",
"hide anything proprietary or that sends telemetry", etc.

```
mpv:       { description: "…"  attrs: [ CLI  GUI  FOSS  GPL ]  install: [ … ] }
audacity:  { description: "…"  attrs: [ GUI  FOSS  tele ]      install: [ … ] }
spotify:   { description: "…"  attrs: [ GUI  proprietary  account  ads  cloud ]  install: [ … ] }
```

## Model: axes, not a flat bag

Tags group into a few **axes**. This is what makes the eventual filter UI clean (per-axis
include/exclude) and tells you which tags combine vs conflict. Tags are **free-form multi** across
*and within* every axis — a component may carry several from one axis (a tool that's both `CLI` and
`GUI`; a project that's `FOSS`, `copyleft`, and `GNU` all at once, so a user who likes copyleft but
dislikes GNU can filter each independently). There is **no single mandatory value** anywhere.

### 1. Interface — how you interact with it
`CLI` · `TUI` · `GUI` · `daemon` (background service/server) · `web` (browser-accessed / self-hosted
web UI) · `headless` (no UI — libs, pure daemons)

### 2. Role — what it is
`lib` · `SDK` · `app` (end-user application) · `toolchain` (compiler/interpreter) · `runtime`
(language/VM runtime) · `driver` (kernel/hardware/DKMS) · `font` · `theme` · `plugin` (extends
another app) · `game` · `service` (a `-service` companion) · `dotfiles` (a `-dotfiles` companion)

### 3. License / openness — free-form, combine as many as apply
`FOSS` (OSI-free) · `FOSSish` (partly non-free — open core) · `proprietary` (closed) ·
`source-available` (visible but non-OSI: BSL/SSPL) · `freeware` (gratis but closed) · `GNU` (a GNU
project) · `copyleft` (GPL-family) · `permissive` (MIT/BSD/Apache)

> `proprietary` is deliberately its own tag (not "absence of FOSS") so "hide non-free" is an
> unambiguous *exclude*. `GNU`/`copyleft`/`permissive` are independent so the license-minded can
> include/exclude each on its own.

### 4. Data / autonomy — what it does behind your back
`tele` (telemetry on by default) · `tele-optin` (telemetry present but **off** by default) ·
`account` (requires a login) · `cloud` (depends on a remote service) · `online` (nonfunctional
offline) · `ads` (carries advertising) · `paid` / `freemium` (costs money / paid tier)

### 5. Pedigree / caveats
`electron` (an Electron app) · `patent` (patent-encumbered codecs — the RPM-Fusion crowd) ·
`legacy` (unmaintained / dead upstream) · `beta` (pre-release)

## Case convention

- **ALL-CAPS** for acronyms: `CLI TUI GUI FOSS FOSSish GNU SDK GPL`.
- **lowercase** for words: `lib app daemon web headless toolchain runtime driver font theme plugin
  game service dotfiles proprietary source-available freeware copyleft permissive tele tele-optin
  account cloud online ads paid freemium electron patent legacy beta`.
- Stored **as authored** (for display); the filter **matches case-insensitively**, so a stray
  `Cli` still filters correctly — but author them in canonical case.

## Auto-derivation (don't hand-tag the obvious)

Some attrs are inferred from the route at load time and **unioned** with the authored `attrs:`, so
companion/asset components tag themselves and ~600 components don't all need hand tagging:

| condition                        | derived attr |
|----------------------------------|--------------|
| a binding is `via: dotfiles`     | `dotfiles`   |
| a binding is `via: service`      | `service`    |
| a binding is `via: font`         | `font`       |

(Interface/role could be derived further later — e.g. `via: cargo`/`pip` → `CLI`, a dev-headers
component → `lib` — but the **license / data / pedigree axes must always be authored**: only a human
knows Audacity phones home.) Authored tags win/merge; the derivation only *adds*.

## Profiles-view behaviour (built)

- The active tags render in the component **infobox** (`attrs:` line above required-by); a tag that's
  part of the active filter is marked `✓` (included) / `✗` (excluded) so you can see why a row shows
  or hides.
- **`A`** opens a **faceted filter modal**: rows grouped by axis, `space` cycles a tag
  `· → ✓(include) → ✗(exclude) → ·`, `c` clears, `enter` applies, `esc` cancels. Filter semantics:
  a component passes when it has **none of the excluded** tags AND, for every axis you included a tag
  from, **at least one** of that axis's included tags (per-axis OR, cross-axis AND).
- **`dotfiles`-tagged components are hidden by default** (companions are noise for most filtering) —
  it's a preset `✗dotfiles` you clear in the modal to reveal them; **`service` stays visible**. The
  catalog title shows a `✓/✗` chip once the filter deviates from that default.
- Implementation: `ProfileScreen.attr_inc`/`attr_exc` (lowercased sets), `_attr_pass()`,
  `_attr_filter_modal()`, `ATTR_AXES` in `configsys/tui/menu.py`.

## Where this lives

`attrs:` is a valid component-level key (parsed into `Component.attrs` = authored ∪ derived, deduped
case-insensitively). The add-component skill assigns attrs to every new component. The filter UI reads
`Component.attrs`.
