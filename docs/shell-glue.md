# Shell glue — conf.d loaders, user glue, overrides

> **Status: REFERENCE** — the glue driver's shell loaders (`shell-glue`), the conf.d load-order bands, the user-glue namespace (`user.d`, `99-user`), `configsys glue add`/`override`, the glue preludes (`configsys`/`cfs`, launcher lookup, caches), and the shell-writes guard with its staged glue; maintained.

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
| bash | the distro `~/.bash_aliases` convention | `~/.bash_aliases` → a link to the shipped `glue/bash_aliases` loader (via the store), which sources every readable `conf.d/*.sh` in lexical order and does nothing else (it carries no personal settings). A pre-existing real `~/.bash_aliases` is absorbed into `conf.d/pre-configsys-aliases.sh`, so it keeps running (unprefixed, it sorts after every band below). |
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
The guard recognizes configsys's own `# >>> configsys… >>>` blocks and leaves them alone.

**conf.d load order (bands).** Every loader sources conf.d in lexical order, so a link's NAME is its
load order. The glue driver names every link it makes into one of four bands:

| band | what | link name |
|---|---|---|
| `00-` | the configsys prelude (`configsys-glue`) | `00-configsys.<ext>` (the glue name already carries the prefix) |
| `50-` | component glue (`glue: <name>`) | `50-<name>.<ext>` — `drivers/glue.py` `component_link_stem` |
| `90-` | user glue: `user.d` snippets — `configsys glue add`, activated staged blocks | `90-<file>` — `user_link_name` |
| `99-` | the scaffolded `99-user` home | `99-user.<ext>` |

A name that already starts with a two-digit `NN-` keeps it (`00-configsys`, `99-user`, a deliberate
`10-early` of yours), so you can place a snippet in any band by naming it. Links made before the bands
existed (unprefixed `<name>.<ext>`) are migrated on install, relink and status
(`Glue._migrate_legacy_component` for component glue; `_deploy_user_glue` for user.d links): the store
mirror is renamed to the banded name and the old link is replaced — but only when it is a symlink
pointing into a glue root configsys owns (`_owned_glue_roots`: the local store, the primary plugin's
`glue/`, the repo `glue/`, the component's defining layer). A real file, or a link elsewhere, is never
touched. Under `--pretend` nothing is migrated, and status still reads an un-migrated link as active
(`_legacy_linked`). Uninstall removes a component's legacy link too.

**Snippet resolution.** A `glue: <name>` snippet is authored at `glue/shell/<shell>/<name>.<ext>`
next to the defining `.hu` file (repo or plugin; extensions `sh zsh fish elv nu`). The source is the
highest content root that has it — the machine-local store (`<state>/glue/`), then the primary
plugin's `glue/`, then the defining layer — and it is materialized into the store's deploy mirror
(`<state>/glue/<shell>/conf.d/50-<name>.<ext>`) and linked from there into
`~/.config/<shell>/conf.d/50-<name>.<ext>`, so links never point into the repo. Only shells that are installed **and** have a variant get the snippet.

**The preludes and their caches.** `configsys-glue` ships `00-configsys.<ext>` (the `00-` sorts it
first). It defines a `configsys` function that defers to a real `configsys` on PATH (a pipx install,
say) and otherwise runs the clone's launcher, found in this order: `$CONFIGSYS_LAUNCHER`; the path
recorded in `<state>/launcher` (the glue driver's `Glue._record_launcher` writes the clone's resolved
`configsys.sh` there on every shell hookup, so the lookup works wherever the clone lives); else
`$HOME/${CONFIGSYS_SRC_DIR:-src}/configsys/configsys.sh`. Every prelude (bash, zsh, fish, elvish,
nushell) also defines `cfs` as interactive shorthand for `configsys`. The shipped loaders and preludes
carry nothing personal — your own aliases and env belong in user glue. In every shell the prelude
also defines `cs_loc <component>` (elvish/nushell: `cs-loc`) — the managed
install location, which tarball/AppImage/source snippets use to find off-PATH binaries. `cs_loc` reads
`glue-locations.tsv` in the state dir (`<comp>\t<path>`, written by `configsys location --all`, deleted
by `actions.invalidate_location_cache` on a pin, pick or provider edit and a plugin sync); a cache under 60 minutes old is read in ~1 ms, and only
a cold/stale one spawns one `configsys location --all`. In bash/zsh/fish, `cs_cached <key> <tool> <cmd…>` caches slow init
output (`pyenv init -`, `luarocks path`) under `~/.cache/configsys/glue-eval/<key>`, regenerated only
when `<tool>`'s executable is newer than the cache. Glue authors: never spawn `configsys` per snippet —
use these.

The TUI Glue screen (`4`) lists every component's glue grouped by installed shell, each group headed
by its loader status, plus your own user glue (user.d snippets, flagged as yours, with a count in the
status line); `a`/`A` activate (for user glue, `a` relinks that shell's user.d namespace, and `A` also
relinks it), `x` deactivates component glue — on a user-glue row it only explains that configsys
never edits your snippets (delete or move the file to stop it loading). `configsys dotfiles status`
lists the same user glue in its own table (state, shell, conf.d link, snippet).

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
`conf.d/99-user.<ext>` (the `99-` loads it after component glue and your other user glue, so your
aliases win). Edit it freely;
configsys links it but never touches its contents, and doesn't re-create it if you delete it while
`user.d/` still exists. user.d links point straight at the layer file, so editing the linked snippet
edits the portable source. Where both roots hold a same-named snippet, the local store wins.

To add more of your own:

```
configsys glue add <name> [--shell <shell>] [--local]
```

Creates `user.d/<name>.<ext>` (a trailing `.<ext>` in `<name>` is optional), opens it in
`$VISUAL`/`$EDITOR`, and links it in as `conf.d/90-<name>.<ext>` (re-inlining the block for a gestalt
shell); name it with your own `NN-` prefix to pick another band. Default shell is your
`$SHELL` when it's a glue shell, else bash. It's written to your **primary plugin** if you have one
(so it travels), else the machine-local store — `--local` forces local.

## Changing a component's glue

Two ways, depending on how much you're changing:

- **Add an alias / a line** → `glue add` a snippet. User glue (`90-`) loads after every component's
  (`50-`), so yours wins. configsys's snippet stays pristine and keeps updating.
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
  `installer-shell-writes-allow:`. Both are machine settings of uniform nature (in the settings
  registry, so `configsys config set` edits them and `config show` lists them; repo < primary <
  user, the highest layer's list wins whole).
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

**configsys's own blocks are exempt.** A marker block `# >>> configsys<tag> >>>` … `# <<< configsys<tag>
<<<` (the glue driver's zsh loader block is ` glue`) is never an installer write — installing
`shell-glue` writes it inside the guard's window. `_split_cs_blocks` pulls such blocks out of both the
snapshot and the current text before diffing: a change that is ONLY a configsys block is kept as
written (no revert, no capture); when an installer also wrote lines, those are reverted and captured
while the configsys block is carried through as it now stands (`_restore_with_cs_blocks`: replaced in
place, dropped, or appended). An unterminated begin marker is ordinary text.

**Staging.** `stage(paths, component, per_shell)` writes each shell's kept block to
`<state>/staged-glue/<shell>/<component>.<ext>` (`shellguard.stage_dir`; `.sh`/`.zsh` per the glue
driver's shell extensions), inactive (linked nowhere). Staged blocks are machine-local state — never
written into a plugin tree. A later capture for the same component and shell replaces the earlier
file. The op prints one line through `run_plan`'s output (the terminal for the CLI, the execute
output in the TUI); the count is the installer's non-blank lines, not the `# from ~/…` headers:

```
-> guarded: reverted 3 line(s) sdkman tried to add to your bash rc (configsys owns shell
   integration). Staged as inactive glue — review with `configsys dotfiles staged`, enable with
   `configsys dotfiles activate sdkman`.
```

**Reviewing staged glue.**

- `configsys dotfiles staged` lists every candidate: component, shell, line count, and the block.
  The listing itself (`shellguard.list_staged`) is read-only; blocks still in the old layout are
  listed where they sit.
- `configsys dotfiles activate <component>… [--local]` turns each of that component's staged blocks
  into ordinary **user glue** (`shellguard.activate` → `Glue.add_user_glue`): the user.d snippet
  `<component>.<ext>` in the same root `glue add` writes — your primary plugin's glue root, unless
  `--local` or you have no primary, then the local store — linked into conf.d as
  `90-<component>.<ext>`, then removed from staging. An existing snippet of that name keeps its
  content; the block is appended unless it is already there, so re-activating never clobbers your
  edits. Exits 1 for a component with nothing staged.
- `configsys dotfiles discard <component>…` deletes the staged copies without activating anything.

Once activated, the block is user glue like any other: it shows in the TUI Glue screen and in the
`dotfiles status` user-glue table, travels with your primary plugin, and loads in zsh as well as bash
(the link carries the shell's own extension). A staged (not yet activated) block shows up only in the
op line and in `dotfiles staged`.

**Migrating the old layout.** Earlier builds staged under the dotfiles capture root
(`<capture-root>/staged-glue/<component>.<shell>.sh`) and activated to
`<capture-root>/shell/<shell>/<component>.sh`. `shellguard.migrate_legacy` carries both over: staged
blocks move into `<state>/staged-glue/` (merged into a same-named block, never dropped); activated
blocks — recognized by the guard's capture header, anything else is left alone — become user glue
(a primary capture root's into the primary glue root, the local store's locally), their old
`conf.d/<component>.sh` link is removed when it points at that file, and the old file is deleted only
after its content was written. The CLI's `dotfiles staged`, `activate` and `discard` run it first
(skipped under `--pretend`, which writes nothing); `activate`/`discard` also migrate staged blocks on
their own (`list_staged(migrate=True)`).
