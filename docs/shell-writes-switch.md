# Shell-writes switch — installers must not scribble in your rc files

Status: **BUILT (2026-08-18).** The rc-writes guard + staged-glue review loop ships in
`configsys/shellguard.py` (snapshot/revert/capture/stage/activate/discard), wired into BOTH op
paths (`app._dispatch_op`, `tui/menu.execute_plan`) via `shellguard.arm()`/`finish()`, with the
`installer-shell-writes` (default block) + `installer-shell-writes-allow` machine settings in
`config.py` and `configsys dotfiles staged | activate | discard` CLI. Remaining from the design:
the per-recipe non-interactive fixes (quicklisp) are a SEPARATE mechanism (below), and TUI
surfacing of staged candidates on the Dotfiles page is a nice-to-have not yet added. Original
decisions kept below for reference.

## Problem
Some installers (sdkman, nvm, rustup, conda, …) append to `~/.bashrc`/`.zshrc`/`.profile` on install —
surprising, un-managed, and redundant with configsys's glue layer (which already owns shell
integration via `~/.config/<shell>/conf.d/`). And some (quicklisp) prompt interactively mid-batch.
configsys's posture is "no surprises" + "configsys owns shell integration", so both are wrong here.

## Decisions (from the grill)
1. **Two separate mechanisms.** The interactive-prompt problem (quicklisp's "Press Enter") is a
   *per-recipe non-interactive* fix — same shape as the apt `DEBIAN_FRONTEND=noninteractive` /
   `NEEDRESTART_MODE=a` and pipx `--backend pip` fixes already shipped. It is NOT part of the switch;
   fix the offending recipes directly (stdin detached + the recipe's own batch answer).
2. **The switch = rc-writes.** A machine setting `installer-shell-writes` (name TBD), **default ON
   (block)**, with a per-component escape hatch to allow one installer to write.
3. **Snapshot-revert ALWAYS** (not installer flags). Rationale (user): passing each installer's
   "--no-modify-path"-style flag is opaque — you can't tell what it suppressed. Instead: snapshot the
   rc files before EACH component install, run it, diff, and revert exactly the lines it added.
   Guarded files: `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.bash_profile` (extensible).
4. **Auto-extract the reverted block into a STAGED glue candidate** (not per-tool authored glue —
   the user pushed back: it's the individual component *installs* that write rc, so there's nothing
   to pre-author; capture what actually happened). The removed lines become a glue snippet named for
   the component, written into the store, **staged for review**: uncommitted + INACTIVE, so the user
   vets it (edits out fragility) and then promotes+commits it into their managed glue. Never silently
   finalized/activated. (DEFAULT: inactive-until-promoted — the strictest reading of "remove the
   fragility before committing." Flippable to active-but-uncommitted if a just-installed tool should
   work immediately.)

## Shape (to build)
- Machine setting `installer-shell-writes: block` (default) | `allow`; per-component override.
- A capture wrapper around a component install (in the op loop / a driver hook): snapshot rc files →
  install → diff → revert additions → write the diff as `<store>/shell/<shell>/<component>.sh` in a
  PENDING state (inactive) → report "reverted N rc lines from <component>; staged as glue — review +
  `configsys dotfiles activate <component>`".
- A review/promote step: show the staged block (`dotfiles status`/a new `review`), let the user edit,
  then `activate` (promote to active glue: link it, and it lives in their managed layer for commit).
- Non-interactive: per-recipe (quicklisp: pipe its answer / non-interactive flag).

## Open / to nail during build
- The staging location + promote command names (reuse the dotfiles glue machinery — the captured
  snippet is just glue that starts inactive).
- Cross-shell: a reverted `.bashrc` block is bash glue; a `.zshrc` block is zsh glue. Route the
  captured block to the right `shell/<shell>/` by which rc file it came from.
- Detecting "which component wrote it": snapshot/diff is per-install, so the writer is known.
