# Shell glue — conf.d loaders, user glue, overrides

> **Status: REFERENCE** — the glue driver's shell loaders (`shell-glue`), the user-glue namespace (`user.d`, `99-user`), `configsys glue add`/`override`, the glue preludes' caching, and the shell-writes guard; maintained.

configsys ships **glue** — small snippets that give a component what it needs at shell startup (a
PATH line, an alias, an env var, completions, an init hook). They deploy into
`~/.config/<shell>/conf.d/` and are loaded by every interactive shell. Glue is **shipped, never
captured** (that's dotfiles' job). You can add your own startup and override what a component ships
— layered, so your changes stay separate from configsys's and travel to your other machines.

## Mechanism

**The substrate.** `shell-glue` (`{ via: glue  loader: all }`) hooks up every installed shell to load
its conf.d; every `<tool>-glue` companion (`{ via: glue  glue: <name> }`) `requires: shell-glue`, and
the shells suggest it (directly, or through their own `-glue`). "Installed" = the shell's binary is on PATH **or** sits in its
configsys-managed install dir (read from the location cache, so a just-installed tarball shell is
hooked up before a new shell puts it on PATH) — not `$SHELL`, which is only the login shell.
`CONFIGSYS_GLUE_SHELLS` (comma-separated) forces the set; bash is the fallback when none is found.

Per-shell loaders (`drivers/glue.py` `_ensure_shell_loader`):

| shell | how conf.d loads | what configsys writes |
|---|---|---|
| bash | the distro `~/.bash_aliases` convention | `~/.bash_aliases` → a link to the shipped `glue/bash_aliases` loader (via the store), which sources `conf.d/*.sh` in lexical order. A pre-existing real `~/.bash_aliases` is absorbed into `conf.d/pre-configsys-aliases.sh`, so it keeps running. |
| zsh | an rc block that sources the dir | one marker block in `~/.zshrc` |
| fish | native `conf.d` auto-source | nothing but the dir |
| elvish, nushell | **inline** ("gestalt") — the rc block *contains* the concatenated conf.d snippets | one marker block in `~/.config/elvish/rc.elv` / `~/.config/nushell/config.nu`, regenerated on every glue (de)activation |

Elvish and nushell can't source a directory into the interactive scope (elvish's per-file `eval`
isolates namespaces; nushell's `source` takes only a parse-time constant path), so their block is a
snapshot of conf.d. Consequence: their rc is glue-owned and has no `-dotfiles` companion. A snippet
carrying a `#!cs-eval <cmd>` line is a **generator**: the inline loader runs `<cmd>` and inlines
its stdout (how zoxide/atuin init reaches nushell); a failing command inlines nothing. `#!cs-eval` is
command-carrying data, so a plugin shipping one needs `configsys plugin trust`. If the rc file is a
symlink (a captured/managed rc), the loader never writes into it.

configsys only ever rewrites its own marked block (`# >>> configsys glue >>>` … `# <<< configsys
glue <<<`); everything else in `.zshrc` / `rc.elv` / `config.nu` is yours. Separately, the
shell-writes guard (`installer-shell-writes:`) reverts lines an *installer* scribbles into your rc
files and stages them as inactive glue (`configsys dotfiles staged|activate|discard`) — see [The shell-writes guard](#the-shell-writes-guard).

**Snippet resolution.** A `glue: <name>` snippet is authored at `glue/shell/<shell>/<name>.<ext>`
next to the defining `.hu` file (repo or plugin; extensions `sh zsh fish elv nu`). The source is the
highest content root that has it — the machine-local store (`<state>/glue/`), then the primary
plugin's `glue/`, then the defining layer — and it is materialized into the store's deploy mirror
(`<state>/glue/<shell>/conf.d/`) and linked from there into `~/.config/<shell>/conf.d/`, so links
never point into the repo. Only shells that are installed **and** have a variant get the snippet.

**The preludes and their caches.** `configsys-glue` ships `00-configsys.<ext>` (the `00-` sorts it
first). It defines a `configsys` function (a real `configsys` on PATH, else the clone launcher /
`$CONFIGSYS_LAUNCHER`) and, in every shell, `cs_loc <component>` (elvish/nushell: `cs-loc`) — the managed
install location, which tarball/AppImage/source snippets use to find off-PATH binaries. `cs_loc` reads
`glue-locations.tsv` in the state dir (`<comp>\t<path>`, written by `configsys location --all`, deleted
by `actions.invalidate_location_cache` on a pin, pick or provider edit and a plugin sync); a cache under 60 minutes old is read in ~1 ms, and only
a cold/stale one spawns one `configsys location --all`. In bash/zsh/fish, `cs_cached <key> <tool> <cmd…>` caches slow init
output (`pyenv init -`, `luarocks path`) under `~/.cache/configsys/glue-eval/<key>`, regenerated only
when `<tool>`'s executable is newer than the cache. Glue authors: never spawn `configsys` per snippet —
use these.

The TUI Glue screen (`4`) lists every component's glue grouped by installed shell, each group headed
by its loader status; `a`/`A` activate, `x` deactivates.

## Two lanes for your own startup

- **conf.d via user.d — the portable lane.** Named snippets in the **user-glue namespace**
  (`<glue-root>/shell/<shell>/user.d/`), linked into conf.d; put them in your primary plugin and
  they travel. This is where anything you want to keep should go.
- **Your rc, outside configsys's block — the machine-local escape hatch.** Good for one-off,
  machine-specific tweaks; it does not travel.

## Your own startup (`user.d`, `99-user`)

The first time configsys hooks up a shell and finds no `user.d/` for it in any glue root, it
scaffolds a blessed home, `user.d/99-user.<ext>`, in the primary plugin's glue root if you have one,
else the local store (`<state>/glue/shell/<shell>/user.d/`). It is linked into conf.d as
`conf.d/99-user.<ext>` (the `99-` loads it after component glue, so your aliases win). Edit it freely;
configsys links it but never touches its contents, and doesn't re-create it if you delete it while
`user.d/` still exists. user.d links point straight at the layer file, so editing the linked snippet
edits the portable source. Where both roots hold a same-named snippet, the local store wins.

To add more of your own:

```
configsys glue add <name> [--shell <shell>] [--local]
```

Creates `user.d/<name>.<ext>` (a trailing `.<ext>` in `<name>` is optional), opens it in
`$VISUAL`/`$EDITOR`, and links it in (re-inlining the block for a gestalt shell). Default shell is your
`$SHELL` when it's a glue shell, else bash. It's written to your **primary plugin** if you have one
(so it travels), else the machine-local store — `--local` forces local.

## Changing a component's glue

Two ways, depending on how much you're changing:

- **Add an alias / a line** → `glue add` a snippet named to sort *after* the component's (yours
  loads later and wins). configsys's snippet stays pristine and keeps updating.
- **Replace it wholesale** →

  ```
  configsys glue override <component> [--shell <shell>] [--local]
  ```

  `<component>` is the tool or its `-glue` companion. Forks the component's shipped snippet(s) — for
  every installed shell it ships, or just `--shell` — into your glue root at the same
  `shell/<shell>/<name>.<ext>` path (never clobbering an existing fork), opens them, and redeploys;
  your copy then shadows the shipped one by content-root precedence. The forked-from sha256 is
  recorded in that root's `glue-overrides.json`, so if the shipped version later changes,
  `configsys check` warns (non-blocking) — re-run `glue override` to take the new upstream, or keep
  yours.

Prefer *add* for small additions (it never drifts); reserve *override* for real replacement.

## Portability

Anything in your **primary plugin's** glue root travels to every machine that plugin reaches; the
local store does not. `configsys plugin init` sweeps your local user glue (`<state>/glue/shell/**` —
user.d snippets + overrides — and `glue-overrides.json`; not the regenerated deploy mirror) into the
primary for you. If you `glue add`/`override` without `--local` and have a primary, it lands there
already. Raw rc text (outside configsys's block) is inherently machine-local — express anything you
want to share as a named snippet instead.

## The shell-writes guard

configsys owns shell integration (conf.d, through glue), so an installer that appends to your rc
files (sdkman, nvm, rustup, conda, …) is both a surprise and a duplicate. The **shell-writes guard**
(`configsys/shellguard.py`) puts those files back and keeps what the installer wanted to add as
**staged glue**: inactive until you review it.

**When it runs.** `actions.run_plan` (the one op loop the CLI and the TUI execute path share) calls
`shellguard.arm(paths, config, component, op)` before each step and `shellguard.finish(paths,
component, snap)` after it, in a `finally`, so a failed or `^C`-aborted install is reverted too.
`arm` takes a snapshot only when all of these hold; otherwise it returns `None` and `finish` does
nothing:

- the op is `install`, `upgrade` or `set-version` (`remove`, `lock`, `unlock` are never guarded);
- `Config.guard_shell_writes(component)` is true: `installer-shell-writes:` is not `allow` (also
  read as off: `false`/`no`/`off`/`0`; default `block`), **and** the component is not listed in
  `installer-shell-writes-allow:`. Both are machine settings (repo < primary < user; the highest
  layer's list wins whole).
- the config has the accessor at all (a stub context degrades to unguarded, so the guard never blocks
  an install).

Writes outside `run_plan` are not guarded: the TUI Glue screen's `a`/`A`/`x` (it calls the glue
driver directly) and the System Updates bulk apply (`Driver.upgrade_all`, from
`configsys upgrade --system` or the TUI).

**Guarded files** (`shellguard.GUARDED`, relative to `$HOME`; the shell decides where a captured block
is routed):

| file | shell |
|---|---|
| `~/.bashrc`, `~/.bash_profile`, `~/.profile` | bash |
| `~/.zshrc`, `~/.zprofile` | zsh |

Nothing else is watched — not fish's `config.fish`, elvish's `rc.elv`, nushell's `config.nu`,
`~/.bash_aliases`, or the conf.d dirs. Extending the list means editing `GUARDED`.

**Snapshot → revert → capture.** `snapshot(home)` reads every guarded file into `{path: text | None}`
(`None` = absent). After the op, `revert_and_capture` compares each file with its snapshot: an
unchanged file is left alone; a changed one is written back to its exact prior bytes (or deleted, if
the op created it), so any edit — an append, an in-place change, a deletion — is undone. The
lines the op **added** (difflib `insert`/`replace` opcodes, so a block inserted mid-file is caught)
are kept, grouped per shell, each source file under a `# from ~/<file> (captured by configsys —
installer wanted to write this)` header. A change that only removed lines is reverted with nothing
to keep. The restore is whole-file, so an edit you make to a guarded file while an install is running
is reverted along with the installer's. (Snapshot-and-revert was chosen over passing each installer
its own `--no-modify-path`-style flag: a flag hides what it suppressed; the diff shows exactly what
the install added.)

**Staging.** `stage()` writes each shell's kept block to
`<capture-root>/staged-glue/<component>.<shell>.sh`, inactive (linked nowhere). The capture root is
the primary plugin's `dotfiles/` (`paths.primary_dotfiles_dir`) if you have one, else the
machine-local store's (`paths.user_dotfiles_dir`, `~/.config/configsys/dotfiles/`). A later capture
for the same component and shell overwrites the earlier file. The op prints one line through
`run_plan`'s output (the terminal for the CLI, the execute output in the TUI):

```
-> guarded: reverted 3 line(s) sdkman tried to add to your bash rc (configsys owns shell
   integration). Staged as inactive glue — review with `configsys dotfiles staged`, enable with
   `configsys dotfiles activate sdkman`.
```

**Reviewing staged glue.**

- `configsys dotfiles staged` lists every candidate: component, shell, line count, and the block.
- `configsys dotfiles activate <component>…` promotes each of that component's staged blocks: copies
  it to `<capture-root>/shell/<shell>/<component>.sh` (made executable), symlinks
  `~/.config/<shell>/conf.d/<component>.sh` to it, and deletes the staged copy. Re-activating relinks
  in place. Exits 1 for a component with nothing staged.
- `configsys dotfiles discard <component>…` deletes the staged copies without activating anything.

Staged glue shows up **only** in that op line and in `dotfiles staged` — neither `configsys dotfiles
status` nor the TUI Glue screen lists it (both read the glue roots, and staged glue sits under the
capture root).

**Known gaps, as built:**

- Staging and activation use the **dotfiles** capture root, not the glue roots
  (`paths.user_glue_dir` / `primary_glue_dir`). So an activated block lives at
  `<capture-root>/shell/<shell>/`, which the glue driver never reads: it is invisible to the Glue
  screen, `dotfiles status` and glue drift detection. With a primary plugin, staged
  blocks land in that plugin's git tree.
- `activate` always names the conf.d link `<component>.sh`, but the zsh loader sources only
  `conf.d/*.zsh`, so an activated **zsh** block never loads. Only bash activation takes effect.
- The guard does not exempt configsys's own loader writes. Installing (or upgrading) `shell-glue`
  through `run_plan` on a machine with zsh writes the `# >>> configsys glue >>>` block into
  `~/.zshrc` inside the guard's window, so the guard reverts it and stages it as
  `shell-glue.zsh.sh`. Until that is fixed, hook zsh up from the TUI Glue screen (not guarded) or add
  `shell-glue` to `installer-shell-writes-allow:`.
