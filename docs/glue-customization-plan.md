# Glue customization & user startup — plan

Shipped glue is cfs's *opinion* of what a component needs at shell startup (a PATH line, an alias,
an env var, completions). Three things the current model doesn't serve well:

1. **A component's glue may not be what the user wants** — a different alias name, an extra alias,
   a tweak to the PATH line.
2. **The user wants their own free-form startup space** — arbitrary shell shenanigans cfs never
   touches. Fine-ish in `conf.d` shells (drop a file); murkier in the **gestalt/inline** shells
   (elvish, nushell) whose rc is a single cfs-managed block.
3. **Some of that should travel** to the user's other machines (the primary plugin), not stay local.

Grilled 2026-09-24. The reframe: **almost none of this is new plumbing.** The substrate already
does the hard part; what's missing is ergonomics, a blessed home, and a save-to-primary path.

## What already exists (build on it, don't reinvent)

- **`conf.d` is the single source of truth on every shell.** `conf.d` shells source
  `~/.config/<shell>/conf.d/*`; the gestalt/inline shells (elvish/nu) *inline* the concatenation of
  the same `conf.d` into their rc block (`glue._inline_block` reads every `conf.d` file). So a
  snippet in `conf.d` runs everywhere.
- **cfs rewrites ONLY its own marked block.** `glue._ensure_shell_loader` replaces just the
  `# >>> configsys glue >>> … # <<< configsys glue <<<` block via a scoped `re.sub`, preserving all
  surrounding rc content verbatim. So for gestalt shells the "user's untouched space" already exists:
  *anything outside the block.* cfs demarcates ITS territory; the rest is the user's by default —
  the user never has to fence their own sections.
- **Glue content resolves through a search path** (`glue._content_roots`): `user_glue_dir` (local
  store) → `primary_glue_dir` (primary plugin) → the defining layer (repo). A same-named snippet in
  a higher root *overrides* the repo's. This is both the customization and the portability lever,
  already wired.

## Locked decisions

- **Two verbs, explicit intent** (not one smart command, not docs-only):
  - `configsys glue add <name> [--shell S] [--local]` — scaffold your OWN new snippet.
  - `configsys glue override <comp> [--shell S] [--local]` — copy a component's SHIPPED glue into
    your layer and open it, to replace what cfs links.
- **Auto-scaffold the user home on shell hookup.** The first time cfs hooks up a shell it drops a
  labeled, empty `99-user.<ext>` snippet (in the user-glue namespace, §A), so there is always an
  obvious "your startup goes here" home — discoverable, not a convention the user must know.
- **Destination = primary-if-set, else local.** New snippets/overrides default to the primary
  plugin's glue root (they travel) when a primary plugin exists; else the machine-local store.
  `--local` forces local.
- **Drift advisory in `check`.** When a user override shadows a component's shipped glue and the repo
  later ships a newer version of that snippet, `check` surfaces a non-blocking advisory (like the
  stale-pin one); the override stays authoritative. Never auto-updated.
- **The portable lane is `conf.d`; free-form rc (outside the block) is the machine-local escape
  hatch.** Portable startup is expressed as a NAMED `conf.d` snippet (travels via the primary);
  raw-rc text stays local by nature. We steer users into `conf.d` for anything they want to keep.

## Design

### A. A component-independent "user glue" namespace (concerns #2 + #3)

Today the glue driver deploys the snippets of *active glue components*. A user's own startup isn't a
component, so it has no home in the portable store. Add a reserved **user-glue namespace** that the
glue driver ALWAYS deploys, independent of any component, resolved through the same content roots:

- Stored at `glue/shell/<shell>/user.d/<name>.<ext>` (a `user.d/` sub-namespace) in any glue root —
  so `primary_glue_dir/.../user.d/*` travels, `user_glue_dir/.../user.d/*` is machine-local.
- On shell hookup, the glue driver links/inlines the union of `user.d/` across the content roots into
  `~/.config/<shell>/conf.d/` alongside component glue. `_inline_block` already inlines everything in
  `conf.d`, so gestalt shells pick it up for free.
- Because it's just glue content in the roots, **portability is automatic**: a `user.d` snippet in
  the primary plugin deploys on every machine the primary reaches — no user-glue *component* needed.

This is the "save to primary" mechanism (concern #3): write to `primary_glue_dir/.../user.d/`.

### B. The blessed `99-user` home (auto-scaffold)

On first hookup of a shell with no existing user-glue, write an empty labeled
`user.d/99-user.<ext>` (numbered last so it runs after everything) with a header:
`# your own startup — configsys links this but never overwrites its contents`. It deploys via §A.
For gestalt shells, ALSO emit a one-line hint outside the managed block ("edit freely outside this
block") the first time the block is written. The `99-` prefix guarantees it loads after component
glue so the user can override earlier aliases.

### C. `glue add` / `glue override` (concern #1 + ergonomics)

- **`glue add <name>`**: create `user.d/<name>.<ext>` in the destination root (primary-if-set, §
  decisions), open `$EDITOR`, deploy. Pure user content — "my aliases," not tied to a component.
- **`glue override <comp>`**: find the component's shipped glue snippet(s) for the target shell(s),
  copy each to the destination root at its real path (`shell/<shell>/<name>.<ext>`, NOT `user.d/`, so
  the search path shadows the repo snippet), record the forked-from source hash (§E), open `$EDITOR`,
  redeploy. This is "change this component's glue." Non-destructive: the repo copy is untouched; the
  override just wins by search-path precedence.
- Both honor `--shell` (default: every hooked-up shell that has a variant) and `--local`.
- **Augment vs override:** for "just add one alias to a component's glue," the guidance is `glue add`
  a small snippet named to sort AFTER the component's (its aliases win) — NOT `override` (which forks
  the whole snippet and drifts). `override` is for wholesale replacement. `glue add`/`status` docs say so.

### D. Destination resolution

`_dest_glue_root(ctx, local)`: `paths.primary_glue_dir` when a primary plugin is configured and
`not local`, else `paths.user_glue_dir`. A `glue add`/`override` with no primary and no `--local`
writes local and prints a one-liner ("saved locally; `configsys plugin bless` a primary to make your
glue portable").

### E. Drift advisory (`check`)

`glue override` records `{ "<shell>/<name>": "<forked-from sha256>" }` in a small store manifest
(`user_glue_dir/overrides.hu` or the primary's, matching where the override landed). `check` (a new
glue lint pass) hashes the repo's CURRENT `shell/<shell>/<name>.<ext>` and, if it differs from the
recorded fork hash, warns: `glue override <name> (<shell>) shadows a newer shipped version — re-run
\`glue override\` to refresh, or keep yours`. Non-blocking; mirrors `refreshstate.read_stale_pins`.

## New primitives / touch points

1. **glue.py** — `user.d/` deploy path (link + inline, in `_ensure_shell_loader` / the snippet
   deploy step); the `99-user` scaffold; helpers to enumerate a component's glue snippet paths (for
   `override`) and to hash a repo snippet (for drift).
2. **paths.py** — already has `user_glue_dir`/`primary_glue_dir`; add `_dest_glue_root` helper
   (actions or glue).
3. **CLI (app.py)** — a `glue` subcommand group: `add`, `override`, `status` (extend the existing
   glue status if any), each with `--shell`/`--local`. `$EDITOR` open helper (reuse whatever
   `config`/`theme` editing uses, else `EDITOR` env).
4. **check** — the glue-override drift pass (reads the overrides manifest).
5. **plugin init** — sweep existing user `conf.d` additions + `user.d/` into the primary's glue root
   (portability capture), alongside the dotfiles sweep it already does.
6. **docs** — a short "customizing your shell startup" section (docs/routing-model.md or a new note):
   the two verbs, the `99-user` home, conf.d = portable / rc = local.

## Phasing

- **P0 — user-glue namespace + `99-user` home: DONE.** `glue._deploy_user_glue(shell)` (called from
  `_ensure_shell_loader` after `_ensure_confd`, before the per-shell branches) scaffolds the blessed
  `99-user.<ext>` home on first hookup — gated on the `user.d/` DIR existing, so emptying it doesn't
  resurrect it — into `_dest_glue_root()` (primary-if-its-glue-dir-exists, else local), then links
  every `<root>/shell/<shell>/user.d/*.<ext>` (local wins over primary) into `~/.config/<shell>/
  conf.d/`, **pointing straight at the layer file** (edit-in-layer, portable when the layer is the
  primary). conf.d shells source them; gestalt shells inline them (the block reads all of conf.d —
  verified on elvish). Snippets chmod'd a+x (loaders source only executables). Delivers concern #2
  (a real, blessed, untouched space) and #3 (a `user.d` snippet in the primary travels), no new
  commands. Tests: user.d scaffold+link, no-resurrect, gestalt inline. 1522 green.
- **P1 — `glue add`: DONE.** `configsys glue add <name> [--shell S] [--local]` — `Glue.new_user_snippet`
  creates `user.d/<name>.<ext>` in `_dest_glue_root` (primary-if-set else local; `--local` forces),
  headered + a+x, trailing-ext-tolerant, no-op on an existing name (preserves content); the CLI opens
  `$VISUAL`/`$EDITOR` (falls back to printing the path off a terminal), then `Glue.deploy_user_glue`
  links it into conf.d (+ refreshes the gestalt block). Default shell = `$SHELL` if a glue shell else
  bash. Prints portable-vs-local + a bless-a-primary nudge. --pretend reports without writing. Tests
  + man page regen. 1523 green.
- **P2 — `glue override` + drift advisory: DONE.** `configsys glue override <comp> [--shell S]
  [--local]` — resolves the tool name or its `-glue` companion to a glue unit, `Glue.override` forks
  each shipped snippet from the DEFINING layer into `_dest_glue_root` at its real `shell/<shell>/…`
  path (shadowing the repo by search-path precedence; never clobbers an existing override), records
  the forked-from sha256 in a `glue-overrides.json` manifest in that root, then `install(rc)`
  redeploys (the override wins). `$EDITOR` on the forked files. `check` gained a glue-drift pass:
  `Glue.override_drift` re-hashes each recorded override's current shipped source and warns
  (non-blocking) when it moved on. Verified live (override btop → forked+redeployed; mangled hash →
  drift warning). Tests + man page. 1524 green.
- **P3 — `plugin init` capture + docs.** Sweep existing user glue into the primary; write the
  user-facing guidance.

## Parked / open

- **Per-alias override** (change ONE alias in a comp's glue without forking the whole snippet) — the
  `glue add`-a-later-snippet pattern covers it by convention; a structured "patch this line" is out
  of scope (too clever, drift-prone).
- **Free-form rc portability** — deliberately NOT solved: raw rc text outside the block is
  machine-local; portable startup goes in `conf.d`/`user.d`. Revisit only if a real need appears.
- **A `glue diff`** (your override vs the current shipped snippet) — a nicety on top of P2's manifest;
  parked.
