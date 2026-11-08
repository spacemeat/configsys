# Primary commits from a write journal

> **Status: DONE** — finished 2026-11-07 (commit d99c1b3; review-2026-11 decision 2; items B1 durable fix, B3, C1).
> Lives on in: docs/plugins.md §8 ("configsys commits its own edits"), the `primarygit` module docstring.

## Why

configsys commits its own edits to the primary by **snapshot difference**: `primarygit.snapshot()`
records `git status` before a CLI command or a TUI action, `commit()` commits whatever became dirty
in between. The review (docs/review-2026-11/primary.md, primary-04/-07/-13) found the three costs of
guessing:

- **missed writes** — a writer the bracket doesn't expect (Config/Theme `select`, fixed narrowly in
  f5e0340) leaves its file dirty, and from then on configsys treats it as YOUR hand edit;
- **swept-in edits** — anything you change in the primary while a long command or action runs is
  committed under configsys's message (and pushed under `auto`);
- **cost** — every non-navigation TUI keypress spends ~6 git spawns, 2 config parses, ~23 ms
  (63 ms with 500 untracked files) to learn that nothing was written.

Decision 2: each configsys writer to the primary records what it wrote, and `commit()` commits
exactly that.

## Design

- **`primarygit.will_write(path)`** — called by a writer BEFORE it writes a file or a directory tree
  that may be inside the primary. If a bracket is open and `path` is under the primary's root, it
  records `path` and, once per path, whether it (or anything under it) was already dirty — one
  `git status -z -- <path>` per recorded path, only when something is actually written.
- **`snapshot(ctx)`** opens the bracket and costs nothing (no git, the primary root cached per
  user-config mtime); **`commit(ctx, snap, message)`** commits the recorded paths that are dirty now
  and weren't before (`git status -z -- <recorded paths>`, then `_commit_paths`), and notes:
  - a recorded path that was already dirty — "also has edits of your own, left uncommitted" (today's
    note, now exact);
  - **dirty paths nobody recorded** (an unknown writer, or you, during the action) are NOT committed;
    they are left for you, with one note naming them when they appeared during a configsys action.
    That turns a missed writer from a silent misclassification into a visible note — and a test
    failure, below.
- A TUI action that records nothing costs no git call at all; the header chip refreshes only after a
  real commit.

## The writers (each calls `will_write` before writing)

| writer | what it writes into the primary |
|---|---|
| `plugins.set_section`, `plugins.remove_sections` | a section of a data file (`edit_target` → the primary's `<name>.hu`; picks, uniform settings, `plugins:`, theme, keys) |
| `plugins.scaffold_primary` | a new primary's `plugin.hu` + data file (`plugin init`) |
| `actions._writable_primary_file` | the empty `<name>.hu` created on a primary's first write |
| `actions.plugin_add` (primary manifest edits go through `set_section`) | covered by `set_section`; its dir rename is outside the primary |
| `drivers/dotfiles.Dotfiles._write_manifest_at`, `.capture`, `.relocate`, `._materialize_to` (when the store is the primary) | a `<name>-dotfiles.cfs/` tree + `manifest.hu` |
| `drivers/glue.Glue.new_user_snippet`, `.add_user_glue`, `.override`, `._deploy_user_glue` (when user glue lives in the primary) | `glue/…` user snippets, the `99-user` scaffold |
| `app._sweep_glue_to_primary` | glue moved into the primary + its manifest |

(Writes to the state dir, `conf.d`, rc files, caches and the top config are outside the primary and
need nothing.)

## Tests

- **Every writer, under the bracket** — a parametrized test that runs each writer above against a
  sandbox primary (the CLI verb or TUI action that reaches it) and asserts the tree is clean after the
  commit and no "nobody recorded" note appeared. This is the guard that a new writer is wired in; it
  fails until it is (like test_driver_inventory for drivers).
- An edit you make during an action (simulated mid-action) is left uncommitted, with the note.
- A recorded path you'd already edited stays uncommitted (today's behavior).
- A navigation action makes no git call (count `PrimaryRepo.git` calls) — the C1 measurement.

## Phases

1. `will_write` + the journal in `snapshot`/`commit`, with the unrecorded-paths note; wire
   `set_section` / `remove_sections` / `_writable_primary_file` / `scaffold_primary`.
2. Wire dotfiles and glue writers + `_sweep_glue_to_primary`; the every-writer test.
3. Drop `_NO_WRITE_ACTIONS` (the bracket no longer guesses from action names) and the per-keypress
   status/state work; measure (C1).

## As built (2026-11-07)

All three phases, with these differences from the design above:
- **The baseline is lazy and whole-tree:** the first `will_write` of a bracket runs one full `git status`
  (not one per recorded path), and `commit()` one more. That one baseline gives both "a recorded file
  you'd already edited" and "a change nobody recorded" (named in a note) — and an action that writes
  nothing still runs no git at all.
- **Every TUI key is bracketed**, not just the ones with a keymap action — opening a journal is free.
  The chip and the Plugins row re-read the primary's state only after a key that wrote into it.
- `PrimaryRepo.in_progress` asks for its five markers in one `rev-parse` (it was five spawns).
- `primary_root` is cached per user-config file (path, mtime, size).
- `plugin init` (create) has no bracket — there is no primary until it runs; its own
  `_git_init_commit` commits the scaffold. `scaffold_primary` still calls `will_write`, for any caller
  that writes into an existing primary.
- Wired writers: `plugins.set_section` / `remove_sections` / `scaffold_primary`;
  `actions._writable_primary_file` / `save_theme_plugin`; `Dotfiles._write_manifest_at` / `capture` /
  `relocate` (both sides — content leaving the primary is a write to it); `Glue.new_user_snippet` /
  `add_user_glue` / `override` / `_record_override` / the 99-user scaffold / the x-bit fix in
  `_deploy_user_glue`; `app._sweep_glue_to_primary` and `_plugin_init_merge`'s dotfiles move.

Measured (C1; a primary with 500 untracked files): an action that writes nothing went from 63 ms and 6
git spawns to 0.16 ms and none; one that writes a file, commits it and refreshes the chip costs 45 ms
and 10 spawns. Tests: test/test_primary_journal.py (`WRITES` is the every-writer guard).
