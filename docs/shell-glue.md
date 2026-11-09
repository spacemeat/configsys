# Shell glue — conf.d loaders, user glue, overrides

> **Status: REFERENCE** — the shell table (`configsys/shells.py`), the glue driver's shell loaders (`shell-glue`), the conf.d load-order bands, the user-glue namespace (`user.d`, `99-user`), `configsys glue add`/`override`, the glue preludes (`configsys`/`cfs`, launcher lookup, caches), and the shell-writes guard with its staged glue; maintained.

configsys ships **glue** — small snippets that give a component what it needs at shell startup (a
PATH line, an alias, an env var, completions, an init hook). They deploy into each shell's
`conf.d/` — `~/.config/<shell>/conf.d/` for bash and zsh, `$XDG_CONFIG_HOME/<shell>/conf.d/`
(default `~/.config`) for fish, nushell and elvish, which read their own config there — and are
loaded by every interactive shell. Glue is **shipped, never captured** (that's dotfiles' job). You
can add your own startup and override what a component ships — layered, so your changes stay
separate from configsys's and travel to your other machines.

## Mechanism

**The shell table.** Everything the glue driver, the shell-writes guard and the TUI know about a
shell is one `ShellSpec` row in `configsys/shells.py` `SHELLS`: `name` (the shell id — `bash`,
`zsh`, `fish`, `nu`, `elvish`; nushell's id is `nu`, so `--shell nu`, `glue/shell/nu/`,
`CONFIGSYS_GLUE_SHELLS=nu`), `ext` (`sh zsh fish nu elv`), `confd`, `rc` (None for fish), `mode`
(`native` fish, `rc-block` bash/zsh, `inline` nushell/elvish), `component` (the component that
installs it, for managed-install detection — `nushell` for `nu`), `guarded` (the rc files the
shell-writes guard watches) and `guarded_dirs`. `drivers/glue.py`'s per-shell tables and
`shellguard.GUARDED`/`GUARDED_DIRS` are views of it, so adding a shell is one row (plus loader code
when its `mode` is new); `shells.expand` makes a row's `~/…` / `$XDG_CONFIG_HOME/…` path absolute.

**The substrate.** `shell-glue` (`{ via: glue  loader: all }`) hooks up every installed shell to load
its conf.d; every `<tool>-glue` companion (`{ via: glue  glue: <name> }`) `requires: shell-glue`, and
the shells suggest it (directly, or through their own `-glue`). "Installed" = the shell's binary is on PATH **or** sits in its
configsys-managed install dir (read from the location cache, so a just-installed tarball shell is
hooked up before a new shell puts it on PATH) — not `$SHELL`, which is only the login shell.
`CONFIGSYS_GLUE_SHELLS` (comma-separated) forces the set; bash is the fallback when none is found.

Per-shell loaders (`drivers/glue.py` `_ensure_shell_loader`):

| shell | how conf.d loads | what configsys writes |
|---|---|---|
| bash | a `~/.bashrc` marker block | One configsys-owned block in `~/.bashrc` (created if absent) that sources every readable `conf.d/*.sh` in lexical order; where no login profile exists at all (`~/.bash_profile`, `~/.bash_login`, `~/.profile`), a `~/.bash_profile` that sources `~/.bashrc` is written too, so login shells load it. A `~/.bashrc` that is a link to a captured config is never edited — the install reports bash as not hooked up and prints the block to add (an older `~/.bash_aliases` link of ours is left in place there, so a captured Debian-skel bashrc that sources it keeps loading conf.d). (History: before 2026-11-08 bash rode the Debian-only `~/.bash_aliases` convention; reinstalling `shell-glue` retires that link — `Glue._retire_bash_aliases_link` drops only our own link, never a real file or another tool's link.) |
| zsh | an rc block that sources the dir (`*.zsh(N)`, so no `null_glob` leaks into your session) | one marker block in `~/.zshrc` |
| fish | native `conf.d` auto-source | nothing but the dir |
| elvish, nushell | **inline** ("gestalt") — the rc block *contains* the concatenated conf.d snippets | one marker block in `$XDG_CONFIG_HOME/elvish/rc.elv` / `$XDG_CONFIG_HOME/nushell/config.nu`, regenerated on every glue (de)activation |

Elvish and nushell can't source a directory into the interactive scope (elvish's per-file `eval`
isolates namespaces; nushell's `source` takes only a parse-time constant path), so their block is a
snapshot of conf.d. Consequence: their rc is glue-owned and has no `-dotfiles` companion. The block
records a `# cs-inputs: <hash>` of what it was built from (`Glue._inline_inputs` — each snippet's
text, and a generator's tool path + mtime); when conf.d no longer matches (a user.d edit, a primary
sync, an upgraded tool) the loader reads `off` until the next (de)activation rebuilds it. Before
writing, the block is parse-checked with the shell itself (`nu-check` / `elvish -compileonly`,
`Glue._valid_parts`): a snippet that breaks it is left out and named, so one bad snippet can't
disable the whole rc (skipped when the shell binary is absent or under `--pretend`). A snippet
carrying a `#!cs-eval <cmd>` line in its leading comment header is a **generator**: the inline
loader runs `<cmd>` (cut off after 10 s, `_EVAL_TIMEOUT`) and inlines its stdout (how zoxide/atuin
init reaches nushell); a failing command inlines nothing. Only a conf.d file that resolves into a
glue root configsys owns is run as a generator — anything else dropped into conf.d is inlined as
text. `#!cs-eval` is command-carrying data, so a plugin shipping one needs `configsys plugin trust`.
If the rc file is a symlink (a captured/managed rc), the loader never writes into it: installing
`shell-glue` then reports that shell as not hooked up and prints the block to add yourself, and
removing it leaves the linked rc alone.

configsys only ever rewrites its own marked block (`# >>> configsys glue >>>` … `# <<< configsys
glue <<<`); everything else in `.bashrc` / `.zshrc` / `rc.elv` / `config.nu` is yours. Separately, the
shell-writes guard (`installer-shell-writes:`) reverts lines an *installer* scribbles into your rc
files and stages them as inactive glue (`configsys glue staged|activate|discard`, also under `dotfiles`) — see [The shell-writes guard](#the-shell-writes-guard).
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
existed (unprefixed `<name>.<ext>`) are no longer migrated: `Glue.legacy_links` finds any unprefixed
symlink in a conf.d that points into a glue root configsys owns (`_owned_glue_roots`: the local store,
the primary plugin's `glue/`, the repo `glue/`, the component's defining layer), and `configsys check`
names each one to delete — the banded `50-`/`90-` link loads the same snippet, so the old one
double-loads it. (History: earlier builds renamed them on install/relink/status; that shim was retired
with the 2026-11 review, docs/review-2026-11-2/README.md §7.16.)

**Snippet resolution.** A `glue: <name>` snippet is authored at `glue/shell/<shell>/<name>.<ext>`
next to the defining `.hu` file (repo or plugin; extensions `sh zsh fish elv nu`). The source is the
highest content root that has it — the machine-local store (`<state>/glue/`), then the primary
plugin's `glue/`, then the defining layer — and it is materialized into the store's deploy mirror
(`<state>/glue/<config-dir>/conf.d/50-<name>.<ext>`, mirroring the conf.d path under the config
base) and linked from there into the shell's `conf.d/50-<name>.<ext>`, so links never point into
the repo. Only shells that are installed **and** have a variant get the snippet. Glue is code your
shells source, so a plugin's snippet goes live only when that plugin is trusted
(`Driver.command_trusted`), and the file that actually resolved — your primary's override of a repo
snippet, say — must be trusted too (`Glue._source_trusted`; your primary per `primary-trust:`).

**Placing links** (`drivers/_linked.py`, shared with the dotfiles driver). `_linked.link` re-points
a link configsys owns; anything else at the conf.d name — a real file, or another tool's link (a
conf.d can be communal, fish's especially) — is moved aside to the first free
`<name>.pre-configsys`, `.pre-configsys.1`, `.2`, … (an earlier backup is never overwritten, and no
one else's link is silently replaced). `_linked.unlink` removes only a link configsys owns and puts
`<name>.pre-configsys` back into the gap; a real file or another tool's link there is left and
reported. Both are pretend-aware (they echo and touch nothing).

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
by `actions.invalidate_location_cache` on a pin, pick or provider edit, a plugin sync, and a
settings edit that can move where things install or which method applies (`settings.LAYOUT`:
`dirs.*`, `locations`, `scope`, `machine`, `pins`, `picks`, `driver-preference`,
`disabled-drivers`, `facets`); the prelude loads it once per shell start into a lookup table
(a bash/zsh associative array, fish parallel lists, an elvish map / nushell record), so each call
is a hash hit. A cache under 60 minutes old is read in ~1 ms, and only a cold/stale one spawns one
`configsys location --all` — with `CONFIGSYS_NO_BOOTSTRAP=1`, so a shell start never repairs the
launcher's venv (`configsys.sh` exits 75 instead of running pip or `sudo apt-get` behind a hidden
stderr); if that run fails, the stale cache is kept rather than an empty one. In bash/zsh/fish, `cs_cached <key> <tool> <cmd…>` caches slow init
output (`pyenv init -`, `luarocks path`) under `~/.cache/configsys/glue-eval/<key>`, regenerated only
when `<tool>`'s executable is newer than the cache. Glue authors: never spawn `configsys` per snippet —
use these.

The TUI Glue screen (`4`) lists every component's glue grouped by installed shell, each group headed
by its loader status, plus your own user glue (user.d snippets, flagged as yours, with a count in the
status line). `a` activates the row's snippet for its shell only (on a user-glue row it relinks that
shell's user.d namespace); `A` (re)activates the row's whole shell group — every component snippet,
then one loader hookup that relinks your user glue (an inline block is rebuilt once, not per
snippet); `x` deactivates component glue — on a user-glue row it only explains that configsys never
edits your snippets (delete or move the file to stop it loading). `n` is `glue add` for the row's
shell, `o` is `glue override` of the row's component for that shell, and `S` lists the staged glue
the shell-writes guard captured, to activate or discard one. `configsys dotfiles status` lists the
same user glue in its own table (state, shell, conf.d link, snippet).

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
edits the portable source. Where both roots hold a same-named snippet, the local store wins. Every
hookup relinks the namespace (`Glue._deploy_user_glue`): a user-band link of ours whose snippet is
gone is pruned, and a snippet in a primary that `primary-trust:` doesn't trust right now is not
linked (its old link goes too, and the hookup names it).

To add more of your own:

```
configsys glue add <name> [--shell <shell>] [--local]
```

Creates `user.d/<name>.<ext>` (a trailing `.<ext>` in `<name>` is optional), opens it in
`$VISUAL`/`$EDITOR` (on a terminal; otherwise it prints where the file is), and links it in as `conf.d/90-<name>.<ext>` (re-inlining the block for a gestalt
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
  `configsys check` warns (non-blocking). Re-running `glue override` never overwrites your fork: it
  says the fork already exists, reopens it and records the new shipped hash on it, which acknowledges
  the change and silences the warning. It finds the fork in either glue root, so one made locally
  before you blessed a primary is reused, not copied a second time into the primary. To start over
  from the new upstream, delete your fork first, then re-run it.

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
`shellguard.arm(paths, config, component, op, driver)` before each step and `shellguard.finish(paths,
component, snap)` after it, in a `finally`, so a failed or `^C`-aborted install is reverted too. A
guard error never aborts the batch (the step runs unguarded, with a note). Under `--pretend` nothing
runs, so nothing is armed. `arm` takes a snapshot only when all of these hold; otherwise it returns
`None` and `finish` does nothing:

- the op is `install`, `upgrade`, `set-version` or `fix-scope` (a reinstall at the declared scope);
  `remove`, `lock`, `unlock` are never guarded;
- the step's driver is not one of configsys's own config drivers (`dotfiles`, `glue` —
  `shellguard._OWN_DRIVERS`): linking your captured `~/.zshrc` into place is not an installer
  scribbling in it;
- `Config.guard_shell_writes(component)` is true: `installer-shell-writes:` is not `allow` (default
  `block`; the value is a choice — `config set` refuses anything else and `check` warns on it),
  **and** the component is not listed in `installer-shell-writes-allow:`. Both are machine settings
  of uniform nature (in the settings registry, so `configsys config set` edits them and `config show`
  lists them; repo < primary < user, the highest layer's list wins whole).
- the config has the accessor at all (a stub context degrades to unguarded, so the guard never blocks
  an install).

Writes outside `run_plan` are not guarded: the TUI Glue screen's keys (they call the glue driver
directly) and the System Updates bulk apply (`sysupdates.apply_bulk` → `Driver.upgrade_all`, from
`configsys upgrade --system` or the TUI).

**Guarded files** (`shellguard.GUARDED`, built from each `ShellSpec.guarded`; paths are under `$HOME`
or `$XDG_CONFIG_HOME`, default `~/.config`; the shell decides where a captured block is routed).
Every supported shell is covered, login and env files included:

| file | shell |
|---|---|
| `~/.bashrc`, `~/.bash_profile`, `~/.bash_login`, `~/.profile` | bash |
| `~/.zshrc`, `~/.zprofile`, `~/.zshenv`, `~/.zlogin` | zsh |
| `$XDG_CONFIG_HOME/fish/config.fish` | fish |
| `$XDG_CONFIG_HOME/nushell/config.nu`, `$XDG_CONFIG_HOME/nushell/env.nu` | nu |
| `$XDG_CONFIG_HOME/elvish/rc.elv` | elvish |

**Guarded dirs** (`shellguard.GUARDED_DIRS`, from `ShellSpec.guarded_dirs`): directories a shell
sources every file of, where an installer may drop a file of its own — today fish's
`$XDG_CONFIG_HOME/fish/conf.d`. A new *regular* file there (never a link — configsys's glue links
live there too) is captured whole and removed. `~/.bash_aliases` and the other conf.d dirs are not
watched. Extending coverage means editing the shell's `ShellSpec` row.

**Snapshot → revert → capture.** `snapshot(home, env)` reads every guarded file into `{path: text |
None}` (`None` = absent; bytes round-trip exactly, a non-UTF-8 or CRLF rc included), records what
each path *is* (a file, absent, or a link to a given target) and lists each guarded dir. After the
op, `revert_and_capture` compares each file with its snapshot: an unchanged file is left alone; a
changed one is written back to its exact prior bytes (or deleted, if the op created it), so any
edit — an append, an in-place change, a deletion — is undone. A path that became, stopped being or
re-pointed a symlink is left alone (that is a config being linked into place, and writing the
snapshot back would go through the new link into your captured config), and nothing is ever
written through a link: when an install adds lines to a guarded file that IS a link (a `~/.zshrc`
that `zsh-dotfiles` linked into place), the file is left as written — not reverted, not staged
(the lines are still live, so activating a staged copy would double them) — and the op prints a
note naming the file, its link target and the lines, so you can review them there. The lines the op **added** (difflib `insert`/`replace` opcodes, so a block
inserted mid-file is caught) are kept, grouped per shell, each source file under a `# from ~/<file>
(captured by configsys — installer wanted to write this)` header. A change that only removed lines
is reverted with nothing to keep. The restore is whole-file, so an edit you make to a guarded file
while an install is running is reverted along with the installer's. (Snapshot-and-revert was chosen over passing each installer
its own `--no-modify-path`-style flag: a flag hides what it suppressed; the diff shows exactly what
the install added.)

**configsys's own blocks are exempt.** A marker block `# >>> configsys<tag> >>>` … `# <<< configsys<tag>
<<<` (the glue driver's bash/zsh/elvish/nushell loader block, and the `~/.bash_profile` it may write, use ` glue`) is never an installer write — installing
`shell-glue` writes it inside the guard's window. `_split_cs_blocks` pulls such blocks out of both the
snapshot and the current text before diffing: a change that is ONLY a configsys block is kept as
written (no revert, no capture); when an installer also wrote lines, those are reverted and captured
while the configsys block is carried through as it now stands (`_restore_with_cs_blocks`: replaced in
place, dropped, or appended). An unterminated begin marker is ordinary text.

**Staging.** `stage(paths, component, per_shell)` writes each shell's kept block to
`<state>/staged-glue/<shell>/<component>.<ext>` (`shellguard.stage_dir`; `<shell>` is the shell id
and `<ext>` its `ShellSpec.ext`), inactive (linked nowhere). Staged blocks are machine-local state — never
written into a plugin tree. A later capture for the same component and shell replaces the earlier
file. The op prints one line through `run_plan`'s output (the terminal for the CLI, the execute
output in the TUI); the count is the installer's non-blank lines, not the `# from ~/…` headers:

```
-> guarded: reverted 3 line(s) sdkman tried to add to your bash rc (configsys owns shell
   integration). Staged as inactive glue — review with `configsys glue staged`, enable with
   `configsys glue activate sdkman`.
```

**Reviewing staged glue.** Each verb is under both `configsys glue …` and `configsys dotfiles …`
(the same commands); the TUI Glue screen's `S` offers activate / discard per candidate.

- `configsys glue staged` lists every candidate: component, shell, line count, and the block. The
  listing (`shellguard.list_staged`) is read-only.
- `configsys glue activate <component>… [--local]` turns each of that component's staged blocks
  into ordinary **user glue** (`shellguard.activate` → `Glue.add_user_glue`): the user.d snippet
  `<component>.<ext>` in the same root `glue add` writes — your primary plugin's glue root, unless
  `--local` or you have no primary, then the local store — linked into conf.d as
  `90-<component>.<ext>`, then removed from staging. An existing snippet of that name keeps its
  content; the block is appended unless it is already there, so re-activating never clobbers your
  edits. Exits 1 for a component with nothing staged.
- `configsys glue discard <component>…` deletes the staged copies without activating anything
  (exits 1 for a component with nothing staged).

Once activated, the block is user glue like any other: it shows in the TUI Glue screen and in the
`dotfiles status` user-glue table, travels with your primary plugin, and loads in the shell it was
captured for (the snippet carries that shell's own extension). A staged (not yet activated) block
shows up only in the op line, in `glue staged` and behind the Glue screen's `S`.

(History: earlier builds staged under the dotfiles capture root; the one-time migration from that
layout, `shellguard.migrate_legacy`, was retired with the 2026-11 review —
docs/review-2026-11-2/README.md §7.16.)
