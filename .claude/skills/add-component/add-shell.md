# Adding a new shell — glue + conf.d wiring

configsys treats every shell uniformly: small snippets under `~/.config/<shell>/conf.d/` plus a
per-shell LOADER that makes the shell source that dir (the `via: glue` driver, `configsys/drivers/
glue.py`). bash/zsh/fish are wired; nushell (`nu`) is present but punted (dir only). Adding a shell
`<sh>` means teaching the glue driver about it, then porting the glue content into its language.
Read this when the user adds a shell (elvish, xonsh, oil/osh, tcsh, …) — it's a component (route it
across the OS matrix like any other, per SKILL.md) PLUS the glue wiring below.

## Part A — register the shell in the glue driver (`configsys/drivers/glue.py`)

Three module-level constants, all required (a missing one is a `KeyError` in `_glue_specs`/`_confd`):

- `_SHELL_EXT['<sh>'] = '<ext>'` — the snippet file extension (bash `sh`, zsh `zsh`, fish `fish`).
- `_SHELL_CONFD['<sh>'] = '~/.config/<sh>/conf.d'` — its conf.d dir (keep the uniform shape).
- add `'<sh>'` to the **`_GLUE_SHELLS`** tuple — the set `_installed_shells()` iterates and probes
  with `shutil.which('<sh>')`. (Only shells on PATH get glue; bash is the floor if none are found.)

Then pick the shell's **loader class** — how it comes to source its conf.d. Four kinds:

1. **Native auto-source** (like fish): the shell reads `~/.config/<sh>/conf.d/*` itself. Add nothing
   to `_SHELL_RC`/`_RC_SOURCE` — `_ensure_shell_loader` just ensures the dir (its `rc_rel` is `None`).
   Simplest; prefer it if the shell supports a native conf.d/`vendor_conf.d`.
2. **rc marker-block** (like zsh): the shell needs an rc line to source conf.d. Add
   `_SHELL_RC['<sh>'] = '~/.<sh>rc'` (its rc file) and `_RC_SOURCE['<sh>'] = '<code to source
   {confd}/*.<ext>>'`. shell-glue then writes ONE marker-delimited (`# >>> configsys glue >>>`)
   block into that rc — idempotent (replaced in place) and cleanly removed on uninstall. The source
   snippet MUST be empty-glob-safe (zsh uses `null_glob`; a POSIX shell needs a `[ -e ]` guard or
   `nullglob`) so an empty conf.d doesn't error. A captured/managed rc (a configsys symlink) OWNS its
   own source line — `_ensure_shell_loader` returns False and skips it; don't fight that.
3. **Convention ride** (bash only): bash has no native conf.d, so it rides `~/.bash_aliases` →
   the shipped `bash_aliases` loader. A new shell won't reuse this; it's bash-specific.
4. **Punt** (like `nu` today): dir only, no auto-source, no rc block. Snippets deploy but aren't
   sourced until you implement (1) or (2). Acceptable as an explicit first cut — but say so; glue is
   inert until the loader lands.

Once `<sh>` is in `_GLUE_SHELLS` and installed, the **shell-glue substrate** (`loader: all`) picks it
up automatically — `_loader_shells('all')` == `_installed_shells()`. No edit to shell-glue.

## Part B — data + content

1. **The shell component** in routes.hu — route it across the matrix like any tool (SKILL.md steps
   0–3; `nushell` is the good tarball-fallback exemplar), and wire the companions:
   ```
   <sh>: { attrs: [ CLI FOSS <license> ]  suggests: [ <sh>-dotfiles, shell-glue ]
       description: "…"  install: [ { via: native … } <+ fallbacks> ] }
   ```
   `suggests: shell-glue` is what makes the loader substrate come along (soft — installs fine without).
2. **`<sh>-dotfiles` config companion** if the shell reads its own config dir/file (it does):
   ```
   <sh>-dotfiles: { description: "<sh> config, linked into place."
       install: [ { via: dotfiles  config: { src: <sh>  dst: $XDG_CONFIG_HOME/<sh> } } ] }
   ```
   (or a single rc file as its `dst`, like `zsh-dotfiles` → `~/.zshrc`). Content isn't shipped — it's
   captured into the user's layer later. This is the DOTFILES driver, separate from glue.
3. **Port the glue snippets** into the shell's language. A `glue: <name>` snippet lights up on `<sh>`
   the moment `glue/shell/<sh>/<name>.<ext>` exists — the driver's `_glue_variants` discovers it,
   **zero component edits**. So authoring content is the whole job:
   - **Start with the substrate**: `glue/shell/<sh>/00-configsys.<ext>` — the `CONFIGSYS_*_DIR`
     exports that must run first (the `00-` prefix orders it first in the conf.d sweep), translated
     to `<sh>` syntax. Plus, for loader class (2), whatever the `_RC_SOURCE` block sources.
   - Then port the specific snippets you want on `<sh>` (aliases/env/init) from their
     `glue/shell/bash/<name>.sh` originals — only the ones that make sense there.
   - Snippets you don't port simply don't attach on `<sh>` (a glue component with no `<sh>` variant
     yields no spec for that shell — a clean no-op, not an error).

## Tests (mirror `test/test_glue_driver.py`)

Drive with `CONFIGSYS_GLUE_SHELLS='<sh>'` to force the installed-shell set. Assert:
- a snippet materializes to `<store>/<sh>/conf.d/<name>.<ext>` (executable) and links into
  `~/.config/<sh>/conf.d/`;
- the loader wires for `<sh>` — the rc marker block appears (class 2) or the dir exists (class 1),
  and `get_version` reads `linked`;
- `uninstall` removes the hookup (rc block / link) and leaves content alone.
Then a routes `check` + golden regen for the new `<sh>` component (purely additive).

## Gotchas

- **Both `_SHELL_EXT` and `_SHELL_CONFD` must carry `<sh>`**, or `_glue_specs`/`_confd` `KeyError`.
- **Empty-glob safety** in the `_RC_SOURCE` snippet — an empty conf.d must not error the shell at
  startup (`null_glob` / a `[ -e ]` guard).
- **Managed rc**: if the user has captured `~/.<sh>rc` as a configsys dotfile (symlink), the loader
  hookup skips it — the capture owns the source line. That's correct; wire the source line into the
  captured content instead.
- **Whole-dir dotfiles vs per-file glue.** If `<sh>-dotfiles` manages the ENTIRE `~/.config/<sh>` as
  one dir-symlink, a glue snippet's dst under `~/.config/<sh>/conf.d/` resolves THROUGH that symlink
  into the dotfiles content, not the glue store — so it can read "not linked" even when present (the
  fish/`fzf-glue` case). The seam is the `conf.d` subdir: prefer capturing the shell's config such
  that `conf.d/` stays a real dir the glue driver owns, or scope the dotfiles spec below `conf.d/`.
- **Login shell ≠ installed.** Glue targets every INSTALLED shell (`which`), not `$SHELL` — a user
  with fish as login but bash present gets both wired. Don't gate on `$SHELL`.
