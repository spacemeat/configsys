# Adding a new shell — glue + conf.d wiring

configsys treats every shell uniformly: small snippets under `~/.config/<shell>/conf.d/` plus a
per-shell LOADER that runs them (the `via: glue` driver, `configsys/drivers/glue.py`). bash/zsh/fish/
elvish/nushell are all wired (elvish AND nushell via a GESTALT/inline loader — see Part A class 5).
Adding a shell `<sh>` means teaching the glue driver about it, then porting the glue content into its
language.
Read this when the user adds a shell (elvish, xonsh, oil/osh, tcsh, …) — it's a component (route it
across the OS matrix like any other, per SKILL.md) PLUS the glue wiring below.

## Architecture — a shell is THREE concerns, three drivers, two storage roots

Never conflate these. Getting the seam wrong re-creates the fish whole-dir/glue tangle.

1. **The shell binary** — an ordinary component (`via: native` + fallbacks), routed across the OS
   matrix like any tool.
2. **Glue** (`via: glue`, the `<tool>-glue` companions + the `shell-glue` substrate) — shell
   INTEGRATION that configsys ships and owns: PATH/aliases/env/completions/init snippets that live
   under `~/.config/<sh>/conf.d/`, plus the per-shell LOADER that makes the shell source that dir.
   Storage is the **`glue/` root** (segregated from dotfiles): authoring `glue/shell/<sh>/<name>.<ext>`
   → machine store `<state>/glue/<sh>/conf.d/<name>.<ext>` → symlinked into `~/.config/<sh>/conf.d/`.
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
bash's config is purely glue (`~/.bash_aliases`), and elvish's rc.elv / nushell's config.nu ARE the
glue gestalt block (glue-owned, regenerated — see class 5; capturing it would freeze the block).

## Part A — register the shell in the glue driver (`configsys/drivers/glue.py`)

Three module-level constants, all required (a missing one is a `KeyError` in `_glue_specs`/`_confd`):

- `_SHELL_EXT['<sh>'] = '<ext>'` — the snippet file extension (bash `sh`, zsh `zsh`, fish `fish`).
- `_SHELL_CONFD['<sh>'] = '~/.config/<sh>/conf.d'` — its conf.d dir (keep the uniform shape).
- add `'<sh>'` to the **`_GLUE_SHELLS`** tuple — the set `_installed_shells()` iterates and probes
  with `shutil.which('<sh>')`. (Only shells on PATH get glue; bash is the floor if none are found.)

Then pick the shell's **loader class** — how it comes to run its conf.d. Five kinds:

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
4. **Punt**: dir only, no auto-source, no rc block. Snippets deploy but aren't sourced until you
   implement (1), (2) or (5). Acceptable as an explicit first cut — but say so; glue is inert until the
   loader lands. (No shell ships this way today; nushell used to, before it became gestalt (5).)
5. **Gestalt / inline** (like `elvish` and `nushell`): for a shell that can't dynamically source a dir
   of snippets into the interactive scope — either its `eval`/`source` ISOLATES namespaces so a source
   loop DISCARDS each file's defs (elvish), or it parses the whole program up front so `source` needs a
   parse-time-CONSTANT path and a conf.d loop is impossible (nushell). Add `'<sh>'` to
   **`_INLINE_SHELLS`** and `_SHELL_RC['<sh>']` (its rc file); the
   loader's marker block then **inlines the concatenated conf.d snippet contents** directly (so defs run
   in the interactive namespace), regenerated on every (de)activation via `_inline_block`. Trade-off:
   one erroring snippet aborts the rest of the block, so **every snippet must SELF-GUARD** (no bare
   command that can throw — wrap a failing init in the shell's swallow-error form). This is heavier
   than (2) — reach for it only when (1)/(2) genuinely can't persist definitions (test first: does a
   `fn` defined in a sourced conf.d file survive into the interactive shell?).

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
   - **Start with the substrate**: `glue/shell/<sh>/00-configsys.<ext>` — the `CONFIGSYS_*_DIR`
     exports that must run first (the `00-` prefix orders it first in the conf.d sweep), translated
     to `<sh>` syntax. Plus, for loader class (2), whatever the `_RC_SOURCE` block sources.
   - Then port the specific snippets you want on `<sh>` (aliases/env/init) from their
     `glue/shell/bash/<name>.sh` originals — only the ones that make sense there.
   - Snippets you don't port simply don't attach on `<sh>` (a glue component with no `<sh>` variant
     yields no spec for that shell — a clean no-op, not an error).
   - **Gestalt shells (class 5) — persistence + self-guard idioms.** Since snippets are inlined and
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
4. **If the shell installs off-PATH (a tarball), add a PATH glue** so `which <sh>` finds it — the
   `_installed_shells()` detection is `shutil.which`, and a shell that isn't detected gets NO glue at
   all (chicken-and-egg). Add `<sh>-glue` (`glue: <sh>`) with bash/zsh/fish variants that prepend
   `configsys location <sh>` to PATH (a shell must be ON PATH, not aliased), and `suggests: <sh>-glue`.
   For a tarball whose upstream ships via its own server (not GitHub assets), use a `url:` template,
   not an `asset:` glob (elvish: `dl.elv.sh`, GitHub releases are empty).

## Tests (mirror `test/test_glue_driver.py`)

Drive with `CONFIGSYS_GLUE_SHELLS='<sh>'` to force the installed-shell set. Assert:
- a snippet materializes to `<store>/<sh>/conf.d/<name>.<ext>` (executable) and links into
  `~/.config/<sh>/conf.d/`;
- the loader wires for `<sh>` — the rc marker block appears (class 2), the dir exists (class 1), or
  the block INLINES the snippet content (class 5; assert a snippet's code is in the rc block and that
  deactivating one regenerates the block without it — see `test_elvish_gestalt_loader_inlines_snippets`),
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
- **conf.d belongs to glue, the rc file to config-dotfiles** (the Architecture rule, restated because
  it's the #1 trap). `<sh>-dotfiles` must target the rc file, NEVER `~/.config/<sh>` whole. Symptoms of
  getting it wrong: glue reads "not linked" through the dir-symlink, the Glue source column shows a raw
  path instead of `<repo>`, and the config capture bakes in the glue snippets (the fish split-brain).
- **Gestalt: capture freezes the block.** A gestalt (class 5) rc is dynamic and glue-owned — never
  give such a shell a `<sh>-dotfiles`. If its rc is a captured symlink, `_ensure_shell_loader` skips it
  and the block freezes at whatever it was when captured (a stale loader, silently).
- **Gestalt: one throw aborts the block; defs in `if`/`for` don't persist.** Every inlined snippet
  self-guards, and conditional aliases use the interactive-inject form, not a bare `fn`/`var` (Part B).
- **`configsys location` exits 0 when a resolved component has no managed dir** (a native/PATH install
  — a valid empty answer, message on stderr). So a location snippet just checks for empty output; no
  exit-swallowing needed. Unroutable still exits 1.
- **Editing a shipped snippet? re-activate it.** The deployed conf.d file is a store COPY; an authoring
  edit only lands after a re-activate (drift-refresh). Glue-page `A` re-installs the whole group
  (refreshing drifted-but-active snippets), so use `A` after editing several — single `a` for one.
- **Login shell ≠ installed.** Glue targets every INSTALLED shell (`which`), not `$SHELL` — a user
  with fish as login but bash present gets both wired. Don't gate on `$SHELL`.
