# `configsys plugin init` — assemble a personal plugin from local bits (plan)

Get set up locally (capture dotfiles, define profiles/components, declare plugins), then package
it all into a personal **primary** plugin you develop in place and push to a remote when ready.
Leans on the dotfiles content search-path: a personal plugin ships *content*, not component
redefinitions.

## Locked decisions

1. **Local bits** folded in: the captured **dotfiles** store (`~/.config/configsys/dotfiles/`),
   your portable **`profiles:`** and custom **`components:`** from `configsys.hu`, and your other
   declared **`plugins:`** — carried into the personal plugin's manifest as **transitive**
   plugins, so a fresh machine bootstraps the whole set from the one primary. Machine settings
   (`configs:`/`scope:`/`pins:`) stay in the local `configsys.hu` (per-machine).
2. **Authored in place, sync-exempt.** The plugin lives at `~/.config/configsys/plugins/<name>/`
   (where `capture` already targets it once it's primary), is a git repo with no remote yet, and
   is declared primary with a **local-path source pointing at its own dir**. `sync` treats a
   plugin whose source resolves to its own dir as **`local`** (no clone/fetch). It IS the repo you
   later push.
3. **Command:** `configsys plugin init [name]` — creates the personal plugin, or merges local bits
   into the existing primary.

## Create flow (no primary yet)

`configsys plugin init myconfig`:

1. Pick `<name>` (arg, else prompt; default e.g. `<os-user>-config`). Refuse if `plugins/<name>`
   exists.
2. Scaffold `plugins/<name>/`:
   - `plugin.hu` — data-only manifest:
     ```hu
     { name: <name>  requires-abi: <ABI>  data: [ <name>.hu ]
       plugins: [ <your other declared plugins, primary stripped> ] }
     ```
   - `dotfiles/` — **move** `~/.config/configsys/dotfiles/*` here (the local capture store).
   - `<name>.hu` — `{ profiles: {…}  components: {…} }` copied from `configsys.hu`.
3. `git init` + an initial commit.
4. Rewrite `configsys.hu` (comment-preserving, via the existing `set_declared`): add
   `plugins: [ { source: "<abs path to plugins/<name>>"  primary: true } ]`. Machine settings
   stay; the copied `profiles:`/`components:` are now redundant (the primary layer provides them)
   — flag them for optional manual removal (auto-removal is a stretch goal, see Open).
5. Print the ship-it hint (below). `capture` now targets `plugins/<name>/dotfiles/`.

## Merge flow (primary exists)

`configsys plugin init` with a primary already blessed → target = the primary's dir:

1. **Move** any leftover `~/.config/configsys/dotfiles/*` into `<primary>/dotfiles/` (skip
   entries already present; `--force` to overwrite) — the same copy discipline as `capture`.
2. Report `profiles:`/`components:`/extra `plugins:` in `configsys.hu` that could move into the
   primary, with the exact blocks. Auto-merging into the primary's existing `.hu`
   (comment-preserving) is a stretch goal; MVP reports and lets you paste.
3. Never touches machine settings.

## Sync-exempt mechanism

`sync` must not try to clone a locally-authored plugin over itself:

```
# in _git_transport / _transport_for:
if source is a local path and Path(source).resolve() == dest.resolve():
    return 'local'      # authored here, nothing to fetch
```

`dir_name("<abs path>")` already yields the basename, so status/lists key it correctly. A `local`
action shows in `plugin list` as "local (unpushed)".

## Ship to a remote

Once it's good, the plugin is a normal git repo:

```
$ cd ~/.config/configsys/plugins/configsys-myconfig
$ git remote add origin git@github.com:you/configsys-myconfig.git && git push -u origin main
$ configsys plugin set-source myconfig github:you/configsys-myconfig   # swap local -> remote
```

`plugin set-source <name> <source>` (new, small) rewrites the declaration's `source` (keeping
`primary: true`); thereafter it syncs like any plugin. MVP alternative: edit the `source:` in
`configsys.hu` by hand.

## Implementation sketch

- **`plugins.py`**: `_git_transport` local-source==dest → `'local'`; a `scaffold_primary(dir,
  name, transitive_decls)` writing `plugin.hu`; `set_source(config, name, source)`.
- **`app.py`**: `cmd_plugin_init` (create vs merge on `primary_name(decls)`); wire into the
  `plugin` subparsers; a `plugin set-source`. Reuse `_bless_primary`, `set_declared`, the
  `capture` copy helper, and `_active_dotfiles`/the local store path.
- **content move**: shared with `dotfiles capture` (copy-then-verify; never delete a source until
  the copy lands). The dotfiles store move is a directory rename when the target is empty.

## Open / defaults (proposals)

- **Config auto-move vs report**: MVP *copies* `profiles:`/`components:` into the plugin (create)
  and *reports* them (merge); it does **not** auto-strip them from `configsys.hu` (risky
  section-editing). Stretch: comment-preserving move + cleanup.
- **Name default**: `configsys-<os-user>` (e.g. `configsys-schrock`); `--name` overrides; prompt on a TTY.
- **`git init` details**: default branch `main`, an initial commit, a generated `README.md` +
  `.gitignore` (`__pycache__/`). No remote.
- **Idempotence / safety**: refuse to overwrite an existing `plugins/<name>` in create mode;
  `--force` only affects dotfile-content overwrites, mirroring `capture`.
- **Dry run**: `--dry-run` prints the plan (files to create, dotfiles to move, config to add).

## Test plan

- create: scaffolds plugin.hu (with transitive plugins) + dotfiles moved + `<name>.hu` with
  profiles/components; declares primary (local source); git repo initialized; local store emptied.
- sync-exempt: a primary with a local source == its dir → `sync` returns `local`, no clone, files
  intact.
- merge: local-store dotfiles move into the existing primary; existing entries skipped unless
  `--force`; machine settings untouched.
- set-source: swaps source, keeps `primary: true`; subsequent sync uses the remote.
- read-only where it should be: never deletes a dotfile source before the copy is verified.

## Phasing

1. **DONE** — `_git_transport` local sync-exempt (`is_local_authored`) + `plugin list` "local
   (unpushed)" status.
2. **DONE** — `plugin init` create: `scaffold_primary` (plugin.hu with transitive plugins +
   `<name>.hu` from `config_sections_text` verbatim), move the local dotfiles store in, `git init`,
   collapse `configsys.hu`'s `plugins:` to the sole local primary. Default name `configsys-<user>`.
3. **DONE** — `plugin init` merge: move leftover local-store dotfiles into the existing primary
   (skip present, `--force`); report movable config.
4. **DONE** — `plugin set-source <name> <source>` + the ship-it hint.
5. **create-path DONE** — `plugin init` now auto-strips the copied `profiles:`/`components:` from
   `configsys.hu` (comment-preserving span removal, `plugins.remove_sections`), so it collapses
   toward the one-line bootstrap. *(Still deferred: auto-MERGING config into an existing primary's
   `.hu` in the merge path — that needs a comment-preserving dict union or a data-file append; the
   merge path still just moves dotfiles + reports movable config.)*
