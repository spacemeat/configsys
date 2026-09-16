# Glue / dotfiles separation

Split the conflated `via: dotfiles` mechanism into two first-class, separately-modeled concerns:

- **glue** — shell-integration *enablement* germane to a component's install: PATH, aliases, env,
  completions, and the shell loaders. Becomes its own **`via: glue`** driver; every glue snippet
  lives in an `X-glue` component.
- **config-dotfiles** — a component's actual user config, optionally configsys-managed as linked,
  repositable files (`.cfs` marker + `manifest.hu` + capture/absorb). Stays **`via: dotfiles`**.

## Locked decisions (grilled)

- **One generic substrate, `shell-glue`** (supersedes the earlier `bash-glue` idea). Investigation
  showed `bash-dotfiles` is really *bash's conf.d loader* (peer of `zsh-glue`/`fish-glue`), doubling
  as the universal `requires:` of ~71 snippets — wrong, since a snippet needs "conf.d loading wired
  for MY shell(s)," not bash specifically. So:
  - **Collapse** `bash-dotfiles` + `zsh-glue` + `fish-glue` into a single **`shell-glue`** component.
    Its install wires up the loader for EVERY installed shell (bash `~/.bash_aliases`-absorb + zsh
    rc-marker + fish dir + nu punt) via the driver's existing `_installed_shells` /
    `_ensure_shell_loader`. The bash `~/.bash_aliases` link+absorb (today a *config* spec on
    `bash-dotfiles`) moves INTO `shell-glue`'s bash-loader path.
  - **Every glue snippet `requires: shell-glue`** (replacing `requires: bash-dotfiles`).
  - Bonus: this auto-fixes a latent gap — today a zsh/fish user gets snippets deployed to their
    `conf.d` but the zsh/fish *loader* isn't wired unless they manually add `zsh-glue`/`fish-glue`.
- **Third-class orphans** (`best-ps1`, the apod shell-hook — user-authored mini-programs, no
  repo/version yet): **parked** out of the glue/dotfiles taxonomy now; real home (a repo +
  `via: script`/`source` + version scheme) is a later phase.
- **Phasing:** **Phase 1 (this plan) = data model + `via: glue` driver + full routes/plugin split +
  suggests rewiring + tests/golden/manpages.** Phase 2 = separate *glue* and *dotfiles* TUI pages
  with per-page UX (designed then). Phase 3 = real homes for the parked orphans.
- **Glue is a standalone driver** (extract the glue machinery out of the dotfiles driver).

## Current-state inventory (125 `via: dotfiles` bindings)

- **50 config-only** (all core) — real dotfiles (`television`, editors' config dirs, …).
- **63 glue-only** — 62 core + `best-ps1` (primary).
- **10 mixed** (glue *and* config in one component): core `neovim-`, `btop-`, `ghostty-`, `helix-`,
  `k9s-`, `lazydocker-`, `micro-`, `nushell-`, `zed-dotfiles`; primary `apod-dotfiles`.
- **2 loaders** (`zsh-glue`, `fish-glue`, via `loader:`).
- **Plugins carrying glue:** only **configsys-user** (primary) and **configsys-bigdata** (4 glue
  comps). No other plugin has any `via: dotfiles` binding.
- **~118 `suggests: *-dotfiles` edges** to rewire.

## Key code seams

- `configsys/routes.py:43` `_VIA_ATTR = {'dotfiles','service','font','group'}` → add `'glue':'glue'`
  (auto-derives a `glue` attr, parallel to the others).
- `configsys/resolve.py:266` `if binding.via == 'dotfiles':` → mirror for `via == 'glue'`.
- Driver factory `get_driver('dotfiles', …)` → register `glue`.
- `configsys/actions.py:951` `dotfiles_units` filters `driver == 'dotfiles'` → a `glue_units`
  sibling (mostly Phase 2, but the split lands here).
- CLI dispatch `app.py:3436 'dotfiles': cmd_dotfiles` → a `glue` command is Phase 2.

## Part A — the `via: glue` driver

1. New `configsys/drivers/glue.py` (`GlueDriver`): move the glue machinery out of `dotfiles.py` —
   `_glue_specs` / `_glue_variants` / `_installed_shells` / the loader hookup (`_ensure_shell_loader`
   / `_remove_shell_loader` / `_rc_block`), the `_SHELL_CONFD` / `_SHELL_EXT` / `_SHELL_RC` /
   `_RC_*` maps, and `GLUE_STATE_LABEL`. Ops: `get_version` (snippet present/active?), `install`
   (write `conf.d/<name>.<ext>`), `uninstall`, `location`; `is_locked`/`lock`/… no-op as today.
2. **`shell-glue`** is a `via: glue` component with no `glue:` snippet — a *loader* form (e.g.
   `loader: all`). Its `install` runs `_ensure_shell_loader(shell)` for each `_installed_shells()`;
   the **bash branch** now also creates the `~/.bash_aliases` → `conf.d/*.sh` link and absorbs any
   pre-existing `~/.bash_aliases` (logic lifted from the old `bash-dotfiles` config spec).
   `get_version` = are all installed shells' loaders hooked? `uninstall` = `_remove_shell_loader`
   per shell. Drop the standalone `bash-dotfiles`/`zsh-glue`/`fish-glue` COMPONENTS.
3. `dotfiles.py` keeps ONLY config specs: inline/named `src`/`dst`, `.cfs` marker, `manifest.hu`,
   capture/absorb/backup. Drop the `kind ∈ {config,glue}` split (all specs are config now) and the
   glue branches in `_specs`.
4. Share small helpers (`_home` / `_env` / `_content_roots` / `_defining_root`) via a tiny common
   module or a base mixin — no duplication.
5. `routes.py _VIA_ATTR` += `glue`; `resolve.py` mirror; register the driver.

## Part B — routes.hu split (core)

- **config-only (50):** unchanged.
- **glue-only (62):** rename `X-dotfiles` → `X-glue`; `via: dotfiles` → `via: glue`;
  `requires: bash-dotfiles` → `requires: shell-glue`; `glue:` / `aliases.glue` → top-level `glue:`.
  Update each parent's `suggests: X-dotfiles` → `X-glue`.
- **mixed (9 core):** split into `X-dotfiles` (config spec, `via: dotfiles`) + new `X-glue`
  (`via: glue  requires: shell-glue  glue: <name>`). Parent `suggests: [ X-dotfiles  X-glue ]`.
- **base/loaders:** replace `bash-dotfiles` + `zsh-glue` + `fish-glue` with the single **`shell-glue`**
  (`via: glue`, loader-for-all-installed-shells; see Part A #2). Replace `bash-dotfiles` in the
  `config.hu` `user:` profile with `shell-glue`.
- **`clang-select` / `gcc-select`** (glue-shaped, not `-dotfiles`): switch to `via: glue` AND rename
  to `clang-glue` / `gcc-glue`; repoint their parents' `suggests:`.
- Content files under `dotfiles/shell/<shell>/…` **stay put** — the glue driver reads the same
  layout, so no content move and the deployed `conf.d/<name>.<ext>` files are stable across the
  rename (they're keyed by glue name, not component name). The bash `bash_aliases` content file also
  stays; it's just installed by `shell-glue`'s bash branch now.

## Part C — plugins (each its own repo, local commit; re-sync+re-trust to load)

- **configsys-user (primary):** split `neovim-dotfiles` → config + `neovim-glue`; migrate `apod`'s
  hook and `best-ps1` per Part E; repoint `requires: bash-dotfiles` → `shell-glue`; update any
  profile that lists renamed/orphan names.
- **configsys-bigdata:** its 4 glue comps → `via: glue` / `-glue`, `requires: shell-glue`.

## Part D — tests / golden / manpages

- Update every test touching `via: dotfiles` glue, `bash-dotfiles`, `-dotfiles` glue names, or the
  glue rows of `dotfiles_units`.
- Add glue-driver tests (snippet install/uninstall/location, loader hookup) paralleling the dotfiles
  tests; keep the config-dotfiles tests.
- Regenerate `test/routing_golden.json`; **semantic diff expected** = new `glue\…` unit keys +
  removed `dotfiles\{bash-dotfiles,zsh-glue,fish-glue}` + the glue renames/splits; **no
  config-dotfiles resolution perturbed.**
- `check` lint: flag any lingering reference to a removed/renamed name (`X-dotfiles`→`X-glue`,
  `bash-dotfiles`/`zsh-glue`/`fish-glue`→`shell-glue`) — a rename-straggler catch. Regenerate man
  pages (`tools/gen_manpages.py`).

## Part E — park the orphans

Move `best-ps1` and the apod shell-hook out of the glue/dotfiles taxonomy into a clearly-marked
holding spot in the primary (a `parked`/`local-scripts` area or commented block) so they no longer
resolve as glue/dotfiles. Real home = Phase 3.

## Consequence for the "45 NEW you can't see" wart

Once glue and dotfiles carry their own attrs and (Phase 2) own their own TUI pages, the
Components/Profiles catalog and its NEW badge exclude them — obviating that wart. Phase-1 stopgap if
desired: exclude `glue`+`dotfiles` attrs from the NEW count.

## Verification

- `check` 0 errors across pop/fedora/arch/alpine/opensuse/rhel; golden semantic diff = renames + new
  glue keys only, config-dotfiles untouched; full suite green.
- Real smoke on this box: a glue install still lands `~/.config/bash/conf.d/<name>.sh` and the loader
  still hooks; a config-dotfiles link + capture still works.

## Deferred follow-ups

- **Purify the bash loader** (agreed, later): today `shell-glue`'s bash loader ships
  `dotfiles/bash_aliases` verbatim, which mixes the real loader job (source `conf.d/*.sh`) with
  stray user config (`alias x="xdg-open"`, a `PYTHONPATH` export). Split those concerns: the loader
  file becomes just the conf.d shim; the aliases/env move to a small glue snippet (or drop). Kept
  as-is in Phase 1 to stay behavior-preserving.

## Status (Phase 1)

- **DONE — commit 1 (`06db74e`):** `via: glue` driver added (additive), wired (`_VIA_ATTR`,
  resolve, registry) + driver tests.
- **DONE — commit 2 (`39b3f28`):** core `routes.hu` cutover — 62 glue-only → `-glue`, 9 mixed
  split, loaders collapsed into `shell-glue` (bash `~/.bash_aliases` folded into its bash branch),
  ~118 `suggests:` rewired, `config.hu` `user:` → `shell-glue`, TUI/CLI dispatch per-driver, golden
  regen (verified NO real install unit changed), tests fixed, manpages. 1295 green.
- **DONE — configsys-bigdata (`6b2d8a6`, its repo):** 4 glue comps → `-glue`/`shell-glue`.
- **TODO — commit 3:** trim `dotfiles.py` to config-only (remove the now-dead glue/loader code) and
  migrate `test_dotfiles.py`'s glue tests into `test_glue_driver.py`. Move `GLUE_STATE_LABEL`
  imports (app.py, menu.py) from `.drivers.dotfiles` → `.drivers.glue`.
- **PENDING USER — configsys-user (Part C + E):** the local `~/src/configsys-user` is behind
  origin (`a558dee`, picks-migrated). The user updates it themselves; then apply IN-PLACE (a) the
  picks rename across laptop/desktop/homelab (`bash-dotfiles→shell-glue`, drop `zsh-glue`/
  `fish-glue`, `clang/gcc-select→-glue`, each glue `X-dotfiles→X-glue`; config `X-dotfiles` stay),
  and (b) park the orphans (`apod` hook, `best-ps1`) into `dotfiles/bash_aliases` (sourced there,
  temporary). NOTE: in the current version `apod-dotfiles` is a mixed `config+glue: apod` and
  `best-ps1` is `glue: ps1` — reshape accordingly when the source is current.

## Suggested commits

1. glue driver + `_VIA_ATTR`/resolve/`get_driver` wiring (+ driver tests).
2. core `routes.hu` split + `suggests` rewiring (+ golden + manpages).
3. plugin splits (configsys-user, configsys-bigdata — separate repos, local commits).
4. park the orphans.
