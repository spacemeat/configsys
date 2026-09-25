# Customizing your shell startup (glue)

configsys ships **glue** — small snippets that give a component what it needs at shell startup (a
PATH line, an alias, an env var, completions). They deploy into `~/.config/<shell>/conf.d/` and are
sourced by every interactive shell (the gestalt shells, elvish and nushell, *inline* the same
snippets into their rc because they can't source a directory). You can add your own startup and
override what a component ships — layered, so your changes stay separate from cfs's and travel to
your other machines.

## Two lanes

- **conf.d / user.d — the portable lane.** Named snippets. Yours live in the **user-glue namespace**
  and cfs links them into `conf.d`; put them in your primary plugin and they travel. This is where
  anything you want to keep should go.
- **Your rc, outside cfs's block — the machine-local escape hatch.** cfs only ever rewrites its own
  marked block (`# >>> configsys glue >>> … # <<< configsys glue <<<`). *Everything else in your
  `.zshrc` / `rc.elv` / `config.nu` is yours and untouched.* Good for one-off, machine-specific
  tweaks; it does not travel.

## Your own startup

The first time cfs hooks up a shell it scaffolds a blessed home — `conf.d/99-user.<ext>` (the `99-`
loads it after component glue, so your aliases win). Edit it freely; cfs links it but never touches
its contents.

To add more of your own:

```
configsys glue add <name> [--shell <shell>] [--local]
```

Creates `<name>.<ext>` in your user-glue namespace, opens it in `$EDITOR`, and links it in. Default
shell is your `$SHELL`. It's written to your **primary plugin** if you have one (so it travels),
else the machine-local store — `--local` forces local.

## Changing a component's glue

Two ways, depending on how much you're changing:

- **Add an alias / a line** → just `glue add` a snippet named to sort *after* the component's (yours
  loads later and wins). cfs's snippet stays pristine and keeps updating.
- **Replace it wholesale** →

  ```
  configsys glue override <component> [--shell <shell>] [--local]
  ```

  Forks the component's shipped snippet into your layer and opens it; your copy then shadows cfs's by
  layer precedence. cfs records what you forked from, so if the shipped version later changes,
  `configsys check` nudges you (non-blocking) — re-run `glue override` to take the new upstream, or
  keep yours.

Prefer *add* for small additions (it never drifts); reserve *override* for real replacement.

## Portability

Anything in your **primary plugin's** glue root travels to every machine that plugin reaches; the
local store does not. `configsys plugin init` sweeps your local user-glue (snippets + overrides) into
the primary for you. If you `glue add`/`override` without `--local` and have a primary, it lands there
already. Raw rc text (outside cfs's block) is inherently machine-local — express anything you want to
share as a named snippet instead.
