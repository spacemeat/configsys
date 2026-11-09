# Adding a new shell — glue + conf.d wiring

configsys treats every shell uniformly: small snippets under `~/.config/<shell>/conf.d/` plus a
per-shell LOADER that runs them (the `via: glue` driver, `configsys/drivers/glue.py`). bash/zsh/fish/
elvish/nushell are all wired (elvish AND nushell via a GESTALT/inline loader — see Part A class 4).
Adding a shell `<sh>` means one `ShellSpec` row in `configsys/shells.py` (plus loader code only for
an rc-block shell's source loop), then porting the glue content into its language.
Read this when the user adds a shell (elvish, xonsh, oil/osh, tcsh, …) — it's a component (route it
across the OS matrix like any other, per SKILL.md) PLUS the glue wiring below.

## Architecture — a shell is THREE concerns, three drivers, two storage roots

Never conflate these. Getting the seam wrong re-creates the fish whole-dir/glue tangle.

1. **The shell binary** — an ordinary component (`via: native` + fallbacks), routed across the OS
   matrix like any tool.
2. **Glue** (`via: glue`, the `<tool>-glue` companions + the `shell-glue` substrate) — shell
   INTEGRATION that configsys ships and owns: PATH/aliases/env/completions/init snippets that live
   under the shell's conf.d dir (`ShellSpec.confd` — `<config>/<sh>/conf.d/`), plus the per-shell
   LOADER that makes the shell source that dir.
   Storage is the **`glue/` root** (segregated from dotfiles): authoring `glue/shell/<sh>/<name>.<ext>`
   → machine store `<state>/glue/<sh>/conf.d/50-<name>.<ext>` (the store mirrors the deployed layout) →
   symlinked into `<config>/<sh>/conf.d/50-<name>.<ext>` (load-order bands: `00-configsys`, `50-` component glue —
   `glue.component_link_stem`, `90-` user glue, `99-user`; a name that already has an `NN-` prefix
   keeps it).
   (The authoring dir is the shell's KEY — `nu` for nushell — while the conf.d dir is its
   `ShellSpec.confd`: `$XDG_CONFIG_HOME/nushell/conf.d/`.)
   Shared across tools — one `fzf-glue` ships a bash/zsh/fish/… variant each.
3. **Config** (`via: dotfiles`, the `<sh>-dotfiles` companion) — the USER's own shell config, captured
   into their layer (their primary plugin, else local), stored as `dotfiles/<sh>-dotfiles.cfs/`.

**THE RULE that keeps them apart:** `conf.d/` belongs to GLUE; the shell's **rc file** belongs to
config-dotfiles; they never share a directory. So **`<sh>-dotfiles` targets the rc FILE, NEVER the
whole `~/.config/<sh>` dir.** A whole-dir `dst` (`$XDG_CONFIG_HOME/<sh>`) swallows the glue-owned
`conf.d/` into the config capture — the fish split-brain (glue baked into the .cfs, "unmanaged"
nags, source-column lies). The dotfiles driver deploys a config spec as ONE whole-thing symlink and
`exclude:` only affects capture/.gitignore, NOT deployment — so targeting the rc file is the only fix.
Precedent: `fish→config.fish`, `zsh→~/.zshrc`. **bash, elvish, and nushell have NO `<sh>-dotfiles`** —
no `bash` component ships at all (bash is the floor, wired by the `~/.bashrc` block — a STATIC block like
zsh's), and elvish's rc.elv / nushell's config.nu ARE the glue gestalt block (glue-owned, regenerated —
see class 4; capturing it would freeze the block).

## Part A — register the shell: one `ShellSpec` row (`configsys/shells.py`)

Every per-shell fact lives in ONE table, `shells.SHELLS` — a `ShellSpec(name, ext, confd, rc, mode,
component, guarded, guarded_dirs)` row per shell. The glue driver's views (`glue._SHELL_EXT`,
`_SHELL_CONFD`, `_GLUE_SHELLS`, `_SHELL_RC`, `_INLINE_SHELLS`, `_SHELL_COMPONENT`) and the
shell-writes guard's `shellguard.GUARDED` / `GUARDED_DIRS` are all DERIVED from it, so never edit
those — add the row:

- `name` — the shell id: the `glue/shell/<name>/` authoring dir and the `CONFIGSYS_GLUE_SHELLS`
  word (`nu` for nushell).
- `ext` — a snippet's file extension (bash `sh`, zsh `zsh`, fish `fish`, nu `nu`, elvish `elv`).
- `confd` — the conf.d dir its loader sources: `$XDG_CONFIG_HOME/<shell>/conf.d` for a shell that
  reads its own config under XDG (fish, nushell, elvish), `~/.config/<shell>/conf.d` where the dir is
  configsys's own choice (bash, zsh). `shells.expand` makes one absolute.
- `rc` — the rc file a loader block goes in, or `None` when the shell sources conf.d natively.
- `mode` — the loader class (below): `'native'`, `'rc-block'` or `'inline'`.
- `component` — the component that installs the shell, for the managed-install check (`nushell` for
  `nu`). A shell counts as installed when `shutil.which(<name>)` finds it OR configsys manages it
  (`_managed_shell_dirs`: its binary sits in that component's managed install dir, per the
  glue-locations cache). Only installed shells get glue; bash is the floor if none are found.
- `guarded` / `guarded_dirs` — the rc files an installer may scribble in, and dirs whose every file
  the shell sources, so the shell-writes guard snapshots them (docs/shell-glue.md).

Then the shell's **loader class** — how it comes to run its conf.d (`mode`):

1. **`native` — auto-source** (like fish): the shell reads its conf.d itself. `rc: None`;
   `_ensure_shell_loader` just ensures the dir. Simplest; prefer it if the shell supports a native
   conf.d/`vendor_conf.d`.
2. **`rc-block`** (bash, zsh): the shell needs an rc line to source conf.d. Set `rc` and add the
   source loop to `glue._RC_SOURCE['<sh>']` (`{confd}` is filled in, shell-quoted) — the one piece of
   loader CODE a new rc-block shell needs. shell-glue then writes ONE marker-delimited
   (`# >>> configsys glue >>>`) block into that rc — idempotent (replaced in place) and cleanly
   removed on uninstall. The loop MUST be empty-glob-safe (zsh's `(N)` glob qualifier; bash's
   `[ -r "$_f" ]` guard) so an empty conf.d doesn't error. A captured/managed rc (a configsys
   symlink) OWNS its own source line — `_ensure_shell_loader` skips it; don't fight that. (bash also
   gets a login profile that sources `~/.bashrc` where none exists — `_ensure_bash_profile`; its old
   `~/.bash_aliases` link is retired, history.)
3. **Punt**: dir only, no auto-source, no rc block. Snippets deploy but aren't sourced until you
   implement (1), (2) or (4). Acceptable as an explicit first cut — but say so; glue is inert until the
   loader lands. (No shell ships this way today; nushell used to, before it became inline.)
4. **`inline` — gestalt** (like `elvish` and `nushell`): for a shell that can't dynamically source a
   dir of snippets into the interactive scope — either its `eval`/`source` ISOLATES namespaces so a
   source loop DISCARDS each file's defs (elvish), or it parses the whole program up front so `source`
   needs a parse-time-CONSTANT path and a conf.d loop is impossible (nushell). Set `mode: 'inline'`
   and `rc`; the loader's marker block then **inlines the concatenated conf.d snippet contents**
   directly (so defs run in the interactive namespace), regenerated on every (de)activation via
   `_inline_block`. Trade-off: one erroring snippet aborts the rest of the block, so **every snippet
   must SELF-GUARD** (no bare command that can throw — wrap a failing init in the shell's
   swallow-error form). This is heavier than (2) — reach for it only when (1)/(2) genuinely can't
   persist definitions (test first: does a `fn` defined in a sourced conf.d file survive into the
   interactive shell?).

A `mode` that is none of these three is new loader code in glue.py (`_ensure_shell_loader`,
`_rc_block`, `_remove_shell_loader`, `_loader_ok`) — not just a row.

Once the row exists and the shell is installed, the **shell-glue substrate** (`loader: all`) picks
it up automatically — `_loader_shells('all')` == `_installed_shells()`. No edit to shell-glue.

## Part B — data + content

1. **The shell component** in routes.hu — route it across the matrix like any tool (SKILL.md steps
   0–3; `nushell` is the good tarball-fallback exemplar), and wire the companions:
   ```
   <sh>: { attrs: [ CLI FOSS <license> ]  suggests: [ <sh>-dotfiles, shell-glue ]
       description: "…"  install: [ { via: native … } <+ fallbacks> ] }
   ```
   `suggests: shell-glue` is what makes the loader substrate come along (soft — installs fine without).
2. **`<sh>-dotfiles` config companion** — target the shell's **rc FILE**, never the whole dir (see
   Architecture). Content isn't shipped; it's captured into the user's layer later.
   ```
   <sh>-dotfiles: { description: "<sh> config (<rc-file>), linked into place."
       install: [ { via: dotfiles  config: { src: <rc-file>  dst: $XDG_CONFIG_HOME/<sh>/<rc-file> } } ] }
   ```
   Which rc file — and whether to have a `<sh>-dotfiles` at all — depends on the loader class (Part A):
   - **native auto-source** (fish): the rc is genuinely user-only (glue lives in `conf.d/`, untouched)
     → `config.fish`. Reads "no config" until the user captures one. Cleanest.
   - **rc marker-block, STATIC** (zsh): glue writes a fixed source-the-dir block INTO the rc, so the rc
     always exists → `<sh>-dotfiles` reads "unmanaged" until the user captures it ONCE (then glue
     defers to the managed symlink — `_ensure_shell_loader` skips a symlinked rc). Capture-the-rc works
     here because the block is STATIC (unchanged as snippets come and go). `zsh→~/.zshrc`.
   - **gestalt/inline** (elvish, nushell): the block is DYNAMIC (regenerated from the snippet set), so
     the rc **must be glue-owned and can NOT be captured** — a captured symlink freezes the block. So a
     gestalt shell gets **NO `<sh>-dotfiles`** (like bash). Real user config, if any, lives in the rc
     OUTSIDE the marker block (glue appends its block, preserving the rest), but isn't configsys-synced.
     `elvish→rc.elv`, `nushell→config.nu`.
   If the shell is glue-ONLY for realistic use (no meaningful rc), have NO `<sh>-dotfiles` at all, like
   bash/elvish — don't add a companion that can only ever nag "unmanaged."
3. **Port the glue snippets** into the shell's language. A `glue: <name>` snippet lights up on `<sh>`
   the moment `glue/shell/<sh>/<name>.<ext>` exists — the driver's `_glue_variants` discovers it,
   **zero component edits**. So authoring content is the whole job:
   - **Start with the substrate**: `glue/shell/<sh>/00-configsys.<ext>` — the helpers every other
     snippet relies on, so it must run first (the `00-` prefix orders it first in the conf.d sweep),
     translated from `glue/shell/bash/00-configsys.sh`: a `configsys` wrapper function (defers to a
     real `configsys` on PATH, else the clone's launcher — `$CONFIGSYS_LAUNCHER`, then the
     `<state>/launcher` path the glue driver records on hookup, then
     `$HOME/${CONFIGSYS_SRC_DIR:-src}/configsys/configsys.sh`), the `cfs` alias, and `cs_loc
     <component>` — a component's managed install location read from the `glue-locations.tsv` cache
     (refreshed by ONE `configsys location --all` only when cold/stale; a per-snippet `configsys
     location` costs a whole process and made startup take most of a minute). bash/zsh/fish also
     define `cs_cached` (caches a slow init command's output until the tool's binary changes); nushell
     names its helpers `cs-loc`/`cs-bash-env`/`cs-prepend`. Plus, for loader class (2), whatever the
     `_RC_SOURCE` block sources.
   - Then port the specific snippets you want on `<sh>` (aliases/env/init) from their
     `glue/shell/bash/<name>.sh` originals — only the ones that make sense there.
   - Snippets you don't port simply don't attach on `<sh>` (a glue component with no `<sh>` variant
     yields no spec for that shell — a clean no-op, not an error).
   - **Gestalt shells (class 4) — persistence + self-guard idioms.** Since snippets are inlined and
     one throw aborts the rest: (a) a conditional definition must NOT be a bare `fn`/`def`/`alias`/`var`
     inside an `if`/`for` (that's block-local and won't persist) — use the shell's inject-into-the-
     interactive-namespace form (elvish: `edit:add-var name~ {…}`; **nushell: there is none** — a `def`
     is parse-time-scoped, so define it UNCONDITIONALLY at top level and self-guard INSIDE the body:
     `def --wrapped X [...r] { if (which --all X | where type == external | is-not-empty) { ^X ...$r }
     else { ^fallback ...$r } }`); (b) helpers the substrate shares (a `configsys` wrapper, a location
     helper) are TOP-LEVEL defs in `00-configsys.<ext>` (inlined first, so later snippets can call
     them); (c) PATH/env mutations persist even inside an `if` (elvish `set paths`/`set-env`; nushell
     top-level `$env.PATH = ($env.PATH | prepend … | uniq)` — but a top-level `let` does NOT reach the
     REPL, so cache a load-time value in `$env.__cs_*` if a def must read it later); (d) wrap any
     command that can fail (a tool's `init <sh>` on an old version) in the shell's swallow-error form
     (elvish: `?()`; nushell: `do --ignore-errors { … }`) so it can't abort the block. Skip a snippet
     whose tool has no `<sh>` target or that sources a *bash* env script.
   - **Init-eval tools (the `#!cs-eval` generator directive).** A tool like `zoxide`/`atuin`/`starship`
     emits shell code to be eval'd at startup. Elvish evals inline (`eval (zoxide init elvish | slurp)`);
     nushell has NO runtime source/eval, so instead a snippet whose body is `#!cs-eval <cmd>` is a
     GENERATOR — the inline loader (`_inline_block`) runs `<cmd>` at (de)activation and inlines its
     STDOUT into the block (see `_eval_directive`/`_run_eval` in glue.py). So `glue/shell/nu/zoxide.nu`
     is just `#!cs-eval zoxide init nushell`. It SELF-GUARDS: a tool that's absent or too old to emit a
     nu init exits non-zero and nothing is inlined. Only works when the tool has a real nu init
     (`zoxide init nushell`, `atuin init nu`, `starship init nu`); a tool whose `init`/`env` emits only
     bash uses the bash-env bridge instead (next bullet). The directive is generic to any inline shell,
     but elvish doesn't need it (it evals inline).
   - **Bash-env bridge (nushell's `bass`).** A tool that ships only a bash env-setup script
     (`sdkman`/`vulkan-sdk`/`gnustep`/`miniforge`) or whose init emits bash (`pyenv`/`opam`/`luarocks`)
     is handled by the `cs-bash-env <bash-command>` substrate helper: it runs the bash command, then
     imports the env CHANGES (PATH → deduped list, other vars) into `$env`. So `glue/shell/nu/sdkman.nu`
     is one line: `cs-bash-env 'export SDKMAN_DIR=...; source ...sdkman-init.sh'`. Caveat: a bash
     FUNCTION the script defines (`sdk`/`conda`/`pyenv`) does NOT cross to nu — only the PATH/env does
     (installed toolchains stay usable; drive install/switch from bash). Self-guards (a failed bash run
     imports nothing).
   - **Line-editor keybindings (`fzf`).** A tool whose integration is interactive KEYBINDINGS
     (fzf's Ctrl-R/Ctrl-T/Alt-C) is neither env nor eval-able — bash/zsh/fish install them via
     readline/zle/`bind`, which nushell (Reedline) doesn't share, and fzf has no nu target. Author them
     as NATIVE nu keybindings: append records to `$env.config.keybindings` (APPEND — `($env.config.keybindings? | default []) | append [...]` — never overwrite the user's), each an
     `event: { send: executehostcommand cmd: '<nu that runs the tool and calls commandline edit>' }`.
     `glue/shell/nu/fzf.nu` is the worked example. This is hand-authored, not generated.
4. **If the shell installs off-PATH (a tarball), add a PATH glue** so `<sh>` execs and `which <sh>`
   finds it. `_installed_shells()` also counts a configsys-managed install (the glue-locations cache),
   but that cache can be cold, so don't rely on it alone. Add `<sh>-glue`
   (`{ via: glue  requires: shell-glue  glue: <sh> }`) with bash/zsh/fish variants that prepend
   `cs_loc <sh>` to PATH (a shell must be ON PATH, not aliased — see `glue/shell/bash/elvish.sh`), and
   `suggests: <sh>-glue`.
   For a tarball whose upstream ships via its own server (not GitHub assets), use a `url:` template,
   not an `asset:` glob (elvish: `dl.elv.sh`, GitHub releases are empty).

## Tests (mirror `test/test_glue_driver.py`)

Drive with `CONFIGSYS_GLUE_SHELLS='<sh>'` to force the installed-shell set. Assert:
- a snippet materializes to `<store>/<sh>/conf.d/50-<name>.<ext>` (executable) and links into
  `~/.config/<sh>/conf.d/`;
- the loader wires for `<sh>` — the rc marker block appears (class 2), the dir exists (class 1), or
  the block INLINES the snippet content (class 4; assert a snippet's code is in the rc block and that
  deactivating one regenerates the block without it — see `test_elvish_gestalt_loader_inlines_snippets_into_rc`),
  and `get_version` reads `linked`;
- `uninstall` removes the hookup (rc block / link) and leaves content alone.
Then a routes `check` + golden regen for the new `<sh>` component (purely additive).

## Gotchas

- **Edit `shells.SHELLS`, never glue.py's `_SHELL_*` views or `shellguard.GUARDED`** — they derive
  from the row; an rc-block shell additionally needs its `glue._RC_SOURCE` loop, or the block is a
  `KeyError`.
- **Empty-glob safety** in the `_RC_SOURCE` snippet — an empty conf.d must not error the shell at
  startup (`null_glob` / a `[ -e ]` guard).
- **Managed rc**: if the user has captured `~/.<sh>rc` as a configsys dotfile (symlink), the loader
  hookup skips it — the capture owns the source line. That's correct; wire the source line into the
  captured content instead.
- **conf.d belongs to glue, the rc file to config-dotfiles** (the Architecture rule, restated because
  it's the #1 trap). `<sh>-dotfiles` must target the rc file, NEVER `~/.config/<sh>` whole. Symptoms of
  getting it wrong: glue reads "not linked" through the dir-symlink, the Glue source column shows a raw
  path instead of `<repo>`, and the config capture bakes in the glue snippets (the fish split-brain).
- **Gestalt: capture freezes the block.** A gestalt (class 4) rc is dynamic and glue-owned — never
  give such a shell a `<sh>-dotfiles`. If its rc is a captured symlink, `_ensure_shell_loader` skips it
  and the block freezes at whatever it was when captured (a stale loader, silently).
- **Gestalt: one throw aborts the block; defs in `if`/`for` don't persist.** Every inlined snippet
  self-guards, and conditional aliases use the interactive-inject form, not a bare `fn`/`var` (Part B).
- **`configsys location` exits 0 when a resolved component has no managed dir** (a native/PATH install
  — a valid empty answer, message on stderr). So a location snippet just checks for empty output; no
  exit-swallowing needed. Unroutable still exits 1.
- **Editing a shipped snippet? re-activate it.** The deployed conf.d file is a store COPY; an authoring
  edit only lands after a re-activate (drift-refresh). Glue-page `A` re-installs every snippet in the
  cursor's shell group (refreshing drifted-but-active ones too), so use `A` after editing several —
  single `a` for one.
- **Login shell ≠ installed.** Glue targets every INSTALLED shell (`which`, or configsys-managed), not `$SHELL` — a user
  with fish as login but bash present gets both wired. Don't gate on `$SHELL`.
