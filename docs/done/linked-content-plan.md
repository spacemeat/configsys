# One link, one unlink, one shell table (review-2026-11-2 D4)

> **Status: DONE** — finished 2026-11-09 (commit fa2b781, review-2026-11-2 D4).
> Lives on in: `configsys/drivers/_linked.py` and `configsys/shells.py` (module docstrings), docs/shell-glue.md.

The config drivers (dotfiles, glue) place content by symlink and, before this, each built its own
shell script for it: `ln -sfn` behind a `[ -e t ] && [ ! -L t ]` backup guard, a restore-on-uninstall
fragment, and their own idea of which link is "ours". Four copies, four slightly different safety
properties (dotfiles-glue-03/05/06/17/29). Per-shell knowledge sits in eight tables
(`_SHELL_EXT`, `_SHELL_CONFD`, `_GLUE_SHELLS`, `_SHELL_COMPONENT`, `_SHELL_RC`, `_INLINE_SHELLS`,
shellguard's `GUARDED` / `GUARDED_DIRS`).

## What changes

1. **`configsys/drivers/_linked.py`** — `link(runner, src, dst, *, owned, absorb=None)` and
   `unlink(runner, dst, *, owned, absorb=None)`, in Python, honoring `--pretend` (they echo what they
   would do and touch nothing). The rules, the same for every caller:
   - `link`: dst already resolves to src → nothing. A symlink we own (it resolves inside one of the
     `owned` roots) is re-pointed. Anything else at dst — a real file or dir, or **another tool's
     link** (stow, chezmoi) — is moved aside first: into `absorb` when given and free (made
     executable), else to the first free `<dst>.pre-configsys`, `.1`, `.2`, … (an earlier backup is
     never overwritten). Before, another tool's link was silently replaced by `ln -sfn`.
   - `unlink`: removes dst only when it is a symlink we own; then puts back what we displaced — the
     absorbed file, else `<dst>.pre-configsys` — only into the gap it leaves. A real file there, or
     someone else's link, is left and reported. Before, glue removed **any** symlink at its
     destination and never restored its backup.
   `free_backup` moves here; the shell fragment `backup_cmd` goes.
2. **`configsys/shells.py`** — one frozen `ShellSpec(name, ext, confd, rc, mode, component, guarded,
   guarded_dirs)` row per shell (`mode` ∈ native / rc-block / inline). glue's tables and shellguard's
   `GUARDED` / `GUARDED_DIRS` are derived from it, so adding a shell is one row (plus its loader code
   when its mode is new).
3. **`SpecState`** — `spec_states` returns named tuples (`name target state src_root src_rel here
   kind`) instead of a positional 7-tuple unpacked in three places.

## Tests

`test/test_linked.py` — the rules above on a real tmp tree (ours re-pointed, foreign link backed up,
numbered backups, absorb, unlink-only-ours, restore-into-the-gap, pretend touches nothing). The
existing dotfiles/glue tests keep passing; the two that asserted on the old shell script assert the
behavior instead.
