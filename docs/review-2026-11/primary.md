# Review: Primary plugin: commits, push, merge

Baseline: `c25bb0a` · 2026-11-07 · reviewer: opus, effort xhigh
Scope: `configsys/primarygit.py` (606 lines), `configsys/humerge.py` (405 lines), read line by line.
Context: CLAUDE.md, docs/principles.md, docs/plugins.md §8 (and §6 trust), docs/done/primary-push-plan.md;
`configsys/plugins.py` (declared / primary_name, `_skip_trivia` / `_scan_value_end` / `_locate_section_span` /
`set_section`, the emitters, `_git_checkout` / `_ahead_behind` / `branch_state` / `default_branch`, `sync` /
`_git_transport`, `_noninteractive_git_env`, the trust helpers, `layer_files`); `configsys/app.py` (`_CliPushUI`,
`_edit_conflict`, `cmd_plugin` push/list, `_command_words`, `_after_primary_commit`, `main`); `configsys/tui/menu.py`
(`_NO_WRITE_ACTIONS`, `_commit_primary_action`, `_TuiPushUI`, `_push_primary`, `_quit_push`, `PluginScreen.reload` /
`_start_remote`, the router bracket); `configsys/tui/screens/{plugins,components,config,theme}.py` (the P handler,
the header chip, select/confirm writes); `configsys/runner.py` (`Runner.run`, `Result`); `configsys/troveio.py`;
`configsys/config.py` (`primary_push`, the profile term algebra `_expand`); `configsys/actions.py` (`edit_target`,
`CONFIG_SETTINGS`, `SETTING_NATURE`); `configsys/failures.py`; `test/test_pretend_sweep.py`.
Tests read: test/test_humerge.py, test/test_primary_state.py, test/test_primary_push.py,
test/test_primary_autocommit.py (all 58 pass at baseline).

Every **(reproduced)** item was run against throwaway repos under
`/tmp/claude-1000/-home-schrock-src-configsys/ee26ccb3-21d9-4cf2-af6f-f787f6c091af/scratchpad/review-2026-11-07/scratch/primary/`.
The fixture (`harness.py` there) is the one the tests use: a bare "remote", a second clone standing in for "your
other machine", and a sandbox `--home` whose blessed primary is cloned from the remote. Each `rNN_*.py` script
named below is a self-contained reproduction.

**Verification** (2026-11-07, checker: opus, effort max): primary-01 … primary-06, the CRITICAL/HIGH set. No MED
finding here is `security`/`safety`. Each was reproduced independently with its own harness and scripts
(`vNN_*.py` under `…/scratch/verify-primary/tools/`). Git config was isolated, `PYTHONPATH` unset, and the code ran
from `git archive` snapshots of `c25bb0a` (the baseline), plus `34d6a20` for primary-01's fix, which landed during
verification. Mostly through the real CLI in a sandbox `--home`. At the baseline the four primary test files pass
(58/58), and none of them covers these six. Result: 6 confirmed, 0 refuted; primary-01 moves CRITICAL → HIGH.

## Carried over from (none)
| earlier finding | status | evidence |
|---|---|---|
| none: this code is new since the 2026-09 review, so there is nothing to carry over | n/a | docs/review-2026-09/ has no primarygit/humerge entries |

## Cross-cutting themes
- **`_combine` has no single way to undo its work.** It has five hand-written abort paths
  (`rebase --abort`, `merge --abort` + `_unstash` + `_intact`, three times over). None of them runs when an
  exception or Ctrl-C arrives, and none of them looks at the hand edits that `--autostash`, or the explicit stash,
  re-applies afterwards. Several ways out leave the primary half-merged or full of conflict markers while
  configsys reports success (primary-02, -03). One context manager that records HEAD and the stash, and restores
  on any exit that is not a commit, would close the whole class.
- **The git layer is shell strings over `bash -c` with strict text decoding.** Paths are glob pathspecs, every
  path is one argv element, and the env is ambient (`GIT_DIR`, `GIT_SSH_COMMAND`, cwd). Each of these is a
  separate bug: a non-UTF-8 file name crashes every command (05), a large capture overflows the argument limit
  (05), `GIT_DIR` redirects commits into another repository (06), a glob stages your hand edits (18), and
  `BatchMode` overrides your `core.sshCommand` (10). One small `PrimaryRepo` helper fixes all of them (14): argv
  lists, bytes in and fsdecode out, `--literal-pathspecs`, `--pathspec-from-file`, a scrubbed env.
- **The merge driver runs as an ordinary Python process inside the checkout.** Remote content can therefore
  execute (01), and its fallbacks are not git's own result (16). The docstring promise "never worse than git's
  merge" fails in four reproduced ways (08, 09, 16).
- **Which edits get committed is inferred, not recorded.** The bracket diffs `git status` around an action and
  decides what to bracket from an allowlist of action names. Real writes are missed (04: `select` writes the
  primary), and concurrent hand edits get swept into commits (07). Recording each write at the few writers that
  touch the primary would make both problems disappear and also remove most of the per-keypress cost (13).
- **Text from the remote is treated as trusted for display.** Values, keys, paths and git's stderr go raw into
  terminal prompts (17), so a hostile branch can spoof the very question that decides which side to keep.

## Findings

### primary-01 [HIGH] security — the `.hu` merge driver imports Python modules from the primary's checkout, so code in unreviewed remote commits runs during `plugin push`
`configsys/primarygit.py:439-446` (`_merge_driver`): the driver is `{sys.executable} -m configsys.humerge …`. Git runs
it with cwd set to the top of the primary's work tree, and `python -m` puts that directory first on `sys.path`.
`humerge` imports `subprocess` on its first line, and `configsys.layers` pulls in `humon`, `packaging` and the
`configsys` package itself. A top-level `subprocess.py`, `packaging/` or `configsys/__init__.py` in the primary
therefore wins over the real modules.

The rebase checks out the upstream tree before it replays local commits. So whoever can push to the primary's
remote gets code execution as you, the next time this machine runs `plugin push`, or after any committing CLI
command under `primary-push: auto`, or on TUI quit under `auto` / `auto-on-quit`. That code has not been reviewed
(`plugin diff`) and is not trusted: trust is per exact content hash, and the primary is gated like any other
plugin (`plugins.command_source_trusted`). No real conflict is needed, because git calls a custom driver for
every three-way file merge. Two different lines of `p.hu` touched on each side are enough. The driver also runs
inside `rebase --autostash`'s stash apply (seen in primary-03).
- **Who controls it:** anyone with push access to your primary's remote.
- **When it runs:** a push while behind.
- **With whose privileges:** yours.
- **Consent first:** none.

**(reproduced)** `r03_driver_cwd.py`. The other machine commits a pick plus a top-level `subprocess.py` that
writes a marker file. This machine adds an ordinary pick and pushes. Output:
`trusted? False` → `ok = True pushed 1 change …` → `marker exists: True ran in …/plugins/prim`.

**Fix:** run the driver isolated, with no cwd and no env-driven paths on `sys.path`:
`{python} -I -c 'import sys; sys.path.insert(0, PKG); from configsys.humerge import driver; sys.exit(driver(*sys.argv[1:6]))' NOTES %O %A %B %P`.
`r37` shows that a shadowing `subprocess.py` aborts the current `-m` form ("SHADOWED subprocess imported"), while
the `-I -c` form merges correctly. Also drop the `PYTHONPATH` env, and add a test with a planted
`subprocess.py` / `configsys/__init__.py`. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity CRITICAL → HIGH.
- **Reproduction.** A different vector from the reviewer's: a planted top-level `configsys/__init__.py` that chains to
  the real package, run through the real CLI. `v01_driver_isolation.py`: the other machine pushes a pick plus the
  package; this machine runs `configsys picks add fzf`, then `configsys plugin push`. Result:
  `MARKER exists: True RAN cwd=…/home/.config/configsys/plugins/prim argv0=-m`, and the merge still succeeded
  (`desk: [ jq  yq ]`).
- **No push command needed.** The same happens under `primary-push: auto`, where `configsys picks add fzf` is the only
  thing typed. The primary was never trusted. The planted package's `__pycache__/` was then committed by configsys
  as "plugin push".
- **Fixed at 34d6a20.** Against that snapshot the same script gives `MARKER exists: False`, and the merge is still
  correct. Its new regression test fails on the c25bb0a code ("code from the primary ran inside the merge driver")
  and passes on 34d6a20.
- **Why HIGH and not CRITICAL.** The only actor is whoever can push to your own primary's remote: you, your other
  machines, or someone who already holds your account or credentials. That actor already gets code execution by
  design, through the primary's linked shell glue. `v01b_byd_design_glue.py`: a `configsys glue add` snippet,
  stored in the primary and linked at `~/.config/bash/conf.d/90-myaliases.sh`, holds the remote's rewritten
  content after a routine `plugin sync`, and also after `plugin push` while behind. bash sources it at the next
  start, and `plugin-trust.hu` is never created. So this bug makes execution immediate and in-process, reaches
  primaries with no linked glue or dotfiles, and bypasses the documented content-hash gate. It is a real exposure,
  and Tier A and the fix stand. But for that actor it opens no boundary that normal use doesn't already open.
- **Aside for the glue/plugins reviewers.** plugins.md §6 says a primary's snippets "under a glue/ directory" need
  trust. The primary's user glue is linked, and then follows the remote, with no trust.

### primary-02 [HIGH] safety — `_combine` is not exception-safe: Ctrl-C at a prompt, a binary conflict, or a malformed `plugins:` entry leaves the primary mid-merge with your hand edits stashed, and the CLI then stages the conflict-marked file
`configsys/primarygit.py:478-512` (`_combine`), `:515-541` (`_settle_hu`, which catches only `humerge.Unmergeable`),
`:559-561` (`_stage`, strict UTF-8 via `Runner.run`'s `text=True`); `configsys/app.py:2980-2987` (`_CliPushUI._ask`,
which catches only `EOFError`) and `:4862-4871` (`main`'s `finally` commits anyway).

After `stash push --include-untracked` and `merge --no-commit`, any exception skips every abort path. Three
reproduced triggers:
- a `KeyboardInterrupt` at the "keep this machine's / the other's / edit / stop" prompt. Ctrl-C is the obvious way
  to stop, and the TUI's `_push_primary` catches only `Exception`.
- `UnicodeDecodeError` from `_stage` on any binary file that conflicts. A captured dotfile can be binary.
- `TypeError: unhashable type: 'dict'` from `humerge._Merge.plugins` when a remote `plugins:` entry has a map as
  its `source:` (`humerge.py:162-165`).

The repo is left with `MERGE_HEAD`, conflict markers in the file, and your uncommitted edits in `stash@{0}`, and
nothing tells you. On the CLI, `main()`'s `finally` then runs `commit()`. That `git add`s the conflicted file,
markers and all, as resolved. Only git's "cannot do a partial commit during a merge" prevents the actual commit.

**(reproduced)**
- `r01_interrupt.py`: `KeyboardInterrupt escaped push()` →
  `{'status': 'UU notes.txt', 'MERGE_HEAD': True, 'stash': 'stash@{0}: On main: configsys plugin push'}`, and the
  hand edit to `plugin.hu` is gone from the tree.
- `r01b_cli.py`, through `main()` with Ctrl-C at the prompt: `configsys: interrupted` →
  `configsys: could not commit to prim: fatal: cannot do a partial commit during a merge.` → `'status': 'M  notes.txt'`
  (the conflict markers are now staged).
- `r04_binary.py`: `EXCEPTION escaped push(): UnicodeDecodeError …` → `MERGE_HEAD: True`, the stash is held.
- `r08_settle_typeerror.py`: `EXCEPTION escaped push(): TypeError unhashable type: 'dict'` → `'UU plugin.hu', MERGE_HEAD: True`.

**Fix:**
1. Wrap the merge phase in `try/except BaseException`: `merge --abort`, then `_unstash`, then `_intact`, then
   re-raise a `KeyboardInterrupt`.
2. Make `_settle_hu` catch every exception from `humerge.merge` and fall back to the per-file question.
3. Read stages as bytes and treat undecodable content as "binary: keep one side".
4. `keyed()` should reject non-string sources.
5. `push()` should refuse to start, and `commit()` should refuse to `git add`, while `MERGE_HEAD`, `rebase-merge`
   or `rebase-apply` exists, saying "the primary is mid-merge: finish or `git merge --abort`".

**Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept.
- **Ctrl-C, through a real pty.** `v02a_ctrl_c_pty.py`: a per-key `splash` conflict plus an uncommitted
  README.txt hand edit. Answer `n` to "Include them", then press Ctrl-C at `[s] stop:`. The terminal shows
  `^Cconfigsys: prim: README.txt also has edits of your own, so configsys left it uncommitted`, which is false (the
  edit is in the stash), then `configsys: could not commit to prim: fatal: cannot do a partial commit during a
  merge.` and `configsys: interrupted`, exit 130.
- **The state it leaves.** `{'status': 'M  prim.hu', 'MERGE_HEAD': True, 'stash': 'stash@{0}: On main: configsys
  plugin push'}`, with prim.hu staged at stage 0 with its markers. The next `configsys picks list` gives
  `picks for this-machine (0)`.
- **A second `plugin push` doesn't recover.** The markers stay in prim.hu, and the hand edit stays in the stash,
  never mentioned.
- **Binary conflict.** `v02b_binary.py`: a binary capture changed on both sides, pushed from the non-tty CLI. rc 1,
  `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x89`, and `MERGE_HEAD: True`.
- **Malformed `plugins:` entry.** `v02c_typeerror.py`: on a remote `source: { x: y }`, `humerge.merge` raises
  `TypeError unhashable type: 'dict'`, not `Unmergeable`.
- **The TUI too.** It runs cbreak (`tui/screen.py`), so Ctrl-C there is also a KeyboardInterrupt, and it gets past
  `_push_primary`'s `except Exception`.

### primary-03 [HIGH] safety — hand edits that overlap incoming changes end up as conflict markers in your working tree while push reports success; a conflicted data file silently drops your picks
`configsys/primarygit.py:469-471` (`rebase --autostash`, then success is returned without checking the autostash
result), `:375-376` (the "left out … still here, uncommitted" line), `:544-551` (`_unstash`).

In the clean-replay path, `--autostash` re-applies your declined hand edits after the rebase. When they overlap
what came in, git stores them as `stash@{0}: autostash`, writes conflict markers into the file (unmerged `UU`),
and still exits 0. `push()` then pushes and reports
`1 file with edits of your own left out of the push (still here, uncommitted)`, which is false.

The merge path's `stash pop` fails the same way. The tree gets markers, and the message says only that your edits
"are kept in git's stash — `git stash pop` brings them back". That pop would now fail, because the file "needs merge".

When the file is a data file, the next run cannot parse it, and the primary layer is skipped: `picks list` shows
0 picks for this machine. The doc's promise "your work intact" is broken without anything visible.

**(reproduced)**
- `r02_autostash.py`: `ok = True … left out of the push (still here, uncommitted)` →
  `{'status': 'UU notes.txt', 'stash': 'stash@{0}: autostash'}`, with `<<<<<<< Updated upstream … >>>>>>> Stashed changes`
  in the file.
- `r02b_autostash_hu.py`: the same with a `p.hu` hand edit. Afterwards `configsys picks list` →
  `picks for this-machine (0)` and `✗ …/prim/p.hu: could not read (Trove has syntax errors …`.
- `r23_unstash.py` (merge path): `ok True` with "your uncommitted edits are kept in git's stash", while
  `plugin.hu` (the manifest) holds markers (`UU plugin.hu`).

**Fix:** stop using `--autostash`. Stash explicitly before combining and pop afterwards. When the pop conflicts,
restore the tree with `git checkout -- <paths>` (safe: the stash still holds the edits) and report it plainly:
"your edits to X conflict with what came in; they are in `stash@{0}` — `git stash pop` to settle them". Better
still, check before fetching or combining: if a dirty path is touched by `HEAD..upstream`, ask "include them, or
stop". Pop with the humerge `-c` options as well, so `.hu` hand edits merge by key the way the autostash path
already does. **Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept.
- **A plain file.** `v03_autostash.py` (i): a configsys commit plus an uncommitted README.txt edit that overlaps the
  remote's. `configsys plugin push` returns rc 0 and says "1 file with edits of your own left out of the push (still
  here, uncommitted)" and "pushed 1 change". Afterwards: `'UU README.txt'`, `stash@{0}: autostash`, and
  `<<<<<<< Updated upstream … >>>>>>> Stashed changes` in the file.
- **The primary's data file.** (ii): the same, with a hand edit to `prim.hu` on the same key the remote changed.
  rc 0. `prim.hu` is then `UU` with markers labelled `.merge_file_…`, so the humerge driver ran inside the autostash
  apply. `configsys picks list` gives `picks for this-machine (0)`.
- **Quieter than the finding says.** `configsys check` reports `0 error(s)`. Only `inspect`, and the TUI `!` page,
  mention the skipped layer.
- **The merge path.** `v03c_unstash.py`, answering `m` through a pty: exit 0, with "your uncommitted edits are kept
  in git's stash — `git … stash pop` brings them back". README.txt holds markers, and that advised `git stash pop`
  fails with `README.txt: needs merge`.

### primary-04 [HIGH] correctness — Config and Theme edits made with `space` are written to the primary but never committed, and from then on configsys treats that file as your hand edit
`configsys/tui/menu.py:658-660` (`_NO_WRITE_ACTIONS` contains `'select'`), `:4981-4982` (no snapshot for those
actions); `configsys/tui/screens/config.py:242-250` (`select` toggles a bool and also sets scope / splash);
`configsys/tui/screens/theme.py:251,291,314` (`select` edits colors through `actions.set_theme_value`, whose
target is `edit_target`, i.e. the primary).

The uniform bools (`reboot-advice`, `adopt-installed`, `auto-tighten`, `install-overlay`, `detect-coexisting`)
land in the primary. The router skips the bracket for `select`, so the write is never committed. The next writing
action's `snapshot()` then sees `p.hu` as already dirty. Every later configsys edit to that file is left
uncommitted with "also has edits of your own", and `plugin push` asks whether to include "edits you made by hand"
that configsys made itself. The primary's main data file stops auto-committing until you commit by hand.

**(reproduced)** `r18_select_write.py`, using the real keymap, `ConfigScreen.handle` and the router's bracket logic:
`space on Config -> select | in _NO_WRITE_ACTIONS: True` → `note: reboot-advice = false` →
`primary status after the toggle: 'M p.hu' | HEAD: A`, then on the next action:
`['prim: p.hu also has edits of your own, so configsys left it uncommitted …']`.

**Fix:** remove `select` from `_NO_WRITE_ACTIONS` now. Durably, stop guessing from action names: a write journal
(primary-07), or an `Intent.wrote` flag (`ConfigScreen` already tracks `wrote`). Add a test that drives every
screen's write actions under the bracket. **Effort:** S (S+M for the durable fix). **Tier:** B.

**Verified:** CONFIRMED (reproduced). HIGH kept.
- **Setup.** `v04_select.py` drives the real keymap (`Keymap(config_keys(...))`: space is `select`, Enter (13) is
  `confirm`), `ConfigScreen.handle`, and the router's exact bracket condition.
- **Space.** Space on `reboot-advice` gives `bracketed=False note='reboot-advice = false'`, primary status
  `'M prim.hu'`, log `['seed']`. The next edit, Enter on `auto-tighten`, gives `prim: prim.hu also has edits of your
  own, so configsys left it uncommitted …`, and still nothing is committed.
- **Control.** The same two edits with Enter make two commits (`config: activate / open — reboot-advice = false`,
  `… auto-tighten = true`) and leave the tree clean.
- **Context.** config.hu itself says "confirm OR select edits the setting". By reading, Theme's `select` writes
  through `actions.set_theme_value` → `edit_target`: theme.py handles `select` alongside `confirm` at all three of
  its edit sites.

### primary-05 [HIGH] correctness — the snapshot/commit bracket is not best-effort: one non-UTF-8 file name in the primary crashes every CLI command, and a large capture overflows the command line
`configsys/primarygit.py:57-71` (`_dirty`: `status -z` prints raw path bytes, and `Runner.run` decodes them
strictly, `runner.py:500`), `:113-119` (all changed paths joined into one `bash -c` string);
`configsys/app.py:4864` (`snapshot` runs before every command and outside any `try`);
`configsys/tui/menu.py:4981-4997` (no `try` around the bracket).

A file name that is not valid UTF-8 crashes `snapshot()` with `UnicodeDecodeError` before any CLI command runs,
read-only ones included. It also crashes every writing TUI keypress. Such a name can come from an old file, an
archive extracted from Windows, or a hostile remote commit that lands through `plugin sync`. This turns one bad
entry into a brick, against the resilience rule in CLAUDE.md.

Separately, the whole path list goes into a single argv element. A capture of about 1800 files exceeds Linux's
128 KiB per-argument limit (`MAX_ARG_STRLEN`), and `commit()` raises `OSError` from the CLI's `finally`, or
inside the TUI loop.

**(reproduced)**
- `r29_nonutf8_name.py`: one `dotfiles/app.cfs/caf\xe9.conf` → `main(['picks','list'])` →
  `EXCEPTION from main(): UnicodeDecodeError 'utf-8' codec can't decode byte 0xe9 …`.
- `r28_argmax.py`: 1800 captured files → `EXCEPTION from commit(): OSError [Errno 7] Argument list too long: 'bash'`.

**Fix:**
- Make the bracket best-effort: `snapshot`, `commit` and `state` catch everything and return None, or a note.
- Read `status -z` / `diff -z` as bytes and `os.fsdecode` them, or have the runner use `errors='surrogateescape'`.
- Pass paths with `--pathspec-from-file=- --pathspec-file-nul` on stdin, for both `add` and `commit`.
- See primary-14.

**Effort:** S–M. **Tier:** B.

**Verified:** CONFIRMED (reproduced). HIGH kept, with one trigger corrected.
- **A clean sync doesn't trigger it.** A non-UTF-8 name that lands cleanly through `plugin sync` is harmless, because
  a clean tracked file never appears in `status -z`. `v05a_nonutf8.py`: after syncing a Latin-1-named file,
  `check`, `picks list`, `where fzf` and `plugin list` all return rc 0.
- **A dirty name does, and arises naturally.** Config dirs are symlinked into the primary. `v05bc_capture.py` (c):
  `picks add tmux-dotfiles`, `dotfiles capture tmux-dotfiles --yes` and `install tmux-dotfiles` leave
  `~/.config/tmux` → `…/plugins/prim/dotfiles/tmux-dotfiles.cfs/tmux`. When an app then writes `caf\xe9-theme.conf`
  into `~/.config/tmux/`, `check`, `picks list` and `inspect` all fail with
  `rc=1 UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`.
- **The argument limit.** (b): a real `configsys dotfiles capture tmux-dotfiles --yes` of a 2000-file config dir gives
  `rc=1 OSError: [Errno 7] Argument list too long: 'bash'`. The 2001 captured files stay uncommitted. The next
  command (`picks add fzf`) commits only its own change, so from then on configsys treats the capture as your hand
  edits.
- **The TUI.** There is no `try` around the router's `snapshot()` or around the loop (menu.py ~4810–4994), so the
  first writing keypress ends the TUI. Startup is fine: `branch_state` uses the quoted, non-`-z` status.

### primary-06 [HIGH] security — `GIT_DIR` / `GIT_WORK_TREE` in the environment (a vcsh or yadm session) send every primary git call to a different repository: an auto-commit committed an untracked secret from `$HOME` there
`configsys/primarygit.py:53-54` (`_git`: `git -C root …` with the ambient env), `:259-265`, `:440-441` (`_git_env`,
`_merge_driver` copy `os.environ` wholesale).

`git -C` changes directory, but `GIT_DIR` and `GIT_WORK_TREE` override repository discovery. Inside
`vcsh enter` / `yadm enter`, `snapshot` and `commit` therefore run against your dotfiles repository with `$HOME`
as its work tree. `add -A -- <paths>` staged and committed an untracked `$HOME/secret.txt` there, with the
message `picks add fzf`, and the primary got nothing. Under `primary-push: auto`, `push()` would go on to
`rebase --autostash`, `stash` and `push` that repository. The same ambient env reaches `plugins.py`'s
`checkout --detach` during sync; that is outside this area, so it is noted for the plugins reviewer.
- **Who controls it:** the user's own environment, by accident.
- **What happens without consent:** files are committed, and possibly pushed, to the wrong remote.

**(reproduced)** `r34_gitdir_env.py`: `snapshot sees dirty: []` → `commit notes: []` →
`dotfiles repo log: ['picks', 'add', 'fzf', 'secret.txt', 'dotfiles', '.bashrc']` → `primary log: A`.

**Fix:** have one env builder for every git call in this module (and in plugins.py) that removes git's
repository-locating variables. The authoritative list is `git rev-parse --local-env-vars` (`GIT_DIR`,
`GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_COMMON_DIR`, `GIT_NAMESPACE`, …). Add a test that
exports them. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). HIGH kept. The commit half holds only in the reviewer's layout, but `push()` is
worse than written.
- **Ordinary runs commit nothing.** `v06_gitdir.py`, real CLI, with `GIT_DIR` and `GIT_WORK_TREE` exported for a bare
  dotfiles repo: `configsys picks add fzf` committed nothing anywhere, in both layouts and under both `ask` and
  `auto`. The primary's commit is simply skipped (`'M prim.hu'`, and no note).
- **A path that becomes dirty mid-command** (`v06b_midcommand.py`):
  - *The reviewer's layout* (work tree outside the configsys home): `.cache/session-token` and a changed `.bashrc`
    were committed to the dotfiles repo as "picks add fzf". Under `auto` they were pushed to its remote, together
    with that repo's unpushed WIP commit, reported as "pushed 2 changes to …/prim.git".
  - *The default yadm/vcsh layout* (the work tree is the home that holds `~/.config/configsys`): git applies the cwd
    prefix to status's root-relative paths, so the commit fails with `could not commit to prim (fatal: pathspec
    '.bashrc' did not match any files)`. But `push()`, whether explicit or as on TUI quit, still pushed the dotfiles
    repo's unpushed commit to its remote, reported as the primary's push.
- **Your home's untracked files get stashed.** `v06c_stash_home.py`: when that repo is ahead and behind with a
  conflict, `_combine`'s `stash push --include-untracked` runs over `$HOME`. While the question was up,
  `Documents/thesis.txt` was gone from disk.
- **A Ctrl-C there leaves them gone.** The files, `~/.config/configsys/configsys.hu` included, stay in the dotfiles
  repo's `stash@{0}`, with `MERGE_HEAD` set. Only `GIT_DIR=… git merge --abort && git stash pop` recovers them; the
  advised `git -C <primary> stash pop` says "No stash entries found" (`v06d_pop_fails.py`).
- **Why not raised to CRITICAL.** It needs a `yadm enter` / `vcsh enter`-style environment, and the files can be
  recovered from the stash.

### primary-07 [MED] correctness — hand edits made while a long command or action runs are committed under configsys's message (and pushed under `auto`)
`configsys/primarygit.py:95-98` (`commit` treats "became dirty between snapshot and commit" as "configsys wrote
it"); `configsys/app.py:4864-4871`; `menu.py:4981-4997` (the `X` execute action brackets the whole install batch).

The doc says "Edits you make by hand are never swept in". But a file you save in your editor while
`configsys upgrade --picks` or a TUI `X` batch runs gets committed with that command's message, and under
`primary-push: auto` it is pushed to your other machines half-finished.

**(reproduced)** `r17c.py`. A stand-in command writes nothing, while "the user" saves `plugin.hu` 0.2 s in:
`HEAD: versions btop | files: plugin.hu` → `hand edit committed: True`, followed by "saved to prim — 1 change not
pushed yet".

**Fix:** keep the snapshot, but intersect `changed` with a write journal. That means a one-line
`primarygit.note_write(path)` at the few writers that touch the primary (`plugins.set_section` and its wrappers,
dotfiles capture/relocate, the glue user.d writers, `_primary_data_file`). Paths in `changed - journal` are
reported as "changed during the command, not by configsys — left for you". This also fixes primary-04's class
and allows skipping `git status` entirely when the journal is empty (primary-13). **Effort:** M. **Tier:** B.

### primary-08 [MED] correctness — profile term lists are order-sensitive but merged as sets, and the driver even replaces git's clean, order-correct merge with the reordered result
`configsys/humerge.py:40-49` (`SET_LISTS` includes `('profiles', '*')`, under the comment "Lists whose order
carries no meaning"), `:153-156` (theirs' additions are appended at the end), `:391-398` (`driver`: when git's
line merge is clean but its data differs, humerge's text wins). Compare `configsys/config.py:629-634`:
"order-sensitive, like ~component: a later add re-adds".

Theirs inserts `+editors` before `~vim`, meaning "editors, but still no vim". Mine appends `htop`. The merge gives
`[btop ~vim htop +editors]`, which brings vim back. `configsys install profile:mine` would then install it. Git's
own line merge was clean and correct, but the driver discards it whenever the data differs. This contradicts the
module docstring's "never worse than git's merge" and the doc's "when git's line merge is clean it keeps git's
text (and result)".

**(reproduced)**
- `r19_profile_order.py` → `merged mine: ['btop', '~vim', 'htop', '+editors']`. `configsys profile show mine` on
  each order gives `expands to (3): btop, emacs, htop` versus `expands to (4): btop, htop, vim, emacs`.
- `r21_worse_than_git.py` → `git line merge clean: True -> ['btop', '+editors', '~vim', 'htop']`, but
  `driver rc 0 -> ['btop', '~vim', 'htop', '+editors']`.

**Fix:** drop `('profiles', '*')` from `SET_LISTS`, which turns these into a per-key question, or implement an
order-preserving list merge (diff3 over sequences). In `driver`, when git's line merge is clean, keep git's
result unless it differs only by duplicate set items (the case the override was meant for). Add both cases as
tests. **Effort:** S. **Tier:** B.

### primary-09 [MED] correctness — the merge drops your comments: combined lists are re-emitted without them, and when the result equals one side, that side's whole text is taken
`configsys/humerge.py:200-203` (`merge`: `merged == m` returns mine's text, `merged == t` returns theirs'),
`:283-286`, `:347-353` (`_emit` / `_rewrite` write a combined list fresh, on one line).

plugins.md §8 says "The lines and comments around a setting are kept as they were". Two cases break it:
- **A list combined from both sides loses its comments.** A picks column or profile with `// shells` /
  `// editors` group comments comes back as `desk: [ zsh  neovim  helix  micro ]`. configsys's own `set_picks`
  also re-emits picks whole, but profiles are only ever written by hand.
- **Your comment-only edit is lost.** If this machine added only a comment (no data change) next to a line the
  other machine changed, git's line merge conflicts, `merged == t`, theirs' text is taken wholesale, and your
  comment disappears without a question. Without humerge, git would have asked.

**(reproduced)**
- `r06_list_comments.py` → `desk: [ zsh  neovim  helix  micro ]`, comments gone, both through `merge()` and
  through the driver.
- `r35_comment_only.py` → `rc 0 | my comment kept: False`.

**Fix:**
- Always rewrite from mine's text. Drop the `merged == t` shortcut when mine's text differs from base's.
- Combine lists in place. Keep mine's list text, delete theirs' removed tokens, and insert theirs' additions
  before the closing bracket in the list's own layout, the way `_insert` already does for maps.
- Say in plugins.md that comments theirs added outside a changed key are not carried over.

**Effort:** M. **Tier:** B.

### primary-10 [MED] correctness — the non-interactive ssh setup is wrong both ways: push's `GIT_SSH_COMMAND` overrides your `core.sshCommand`, and the background fetch has no `BatchMode` at all
`configsys/primarygit.py:259-265` (`_git_env`: `env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes')`),
`:159-168` (`fetch`: only `plugins._noninteractive_git_env()`, and the fetch URL rather than the push URL).

- **Push ignores your ssh config.** `GIT_SSH_COMMAND` takes precedence over `core.sshCommand`. Anyone who reaches
  their primary through a specific key or proxy set in `core.sshCommand` gets "Permission denied (publickey)" on
  every TUI push and every `auto` push (both use the non-interactive UI). That is then explained as "the remote
  refused this machine's SSH key", while `configsys plugin push` from a terminal works.
- **The background fetch can prompt.** The Plugins screen's `fetch()` runs ssh without `BatchMode`, on a daemon
  thread while curses owns the terminal. A passphrase-protected key, or an unknown host, can then prompt on the
  tty mid-TUI. This contradicts plugins.md's "In the TUI, git never prompts".
- **The two paths fetch different URLs.** `fetch()` uses the fetch URL while `push()` deliberately fetches through
  the push URL, so `↓` can stay stale on a private primary.

**(reproduced)**
- `r14/t.py`: with `core.sshCommand` set to a marker command, a fetch under `_git_env(False)` runs plain ssh
  (`ssh: Could not resolve hostname example.invalid`), and the marker never prints.
- `r15_fetch_batch.py`: `primarygit.fetch` runs the user's ssh with `argv: -G -o SendEnv=GIT_PROTOCOL git@example.invalid`
  / `GIT_SSH_COMMAND=` (no BatchMode).

**Fix:** build one non-interactive env. Take the effective ssh command (`$GIT_SSH_COMMAND`, else
`git config core.sshCommand`, else `ssh`) and append `-o BatchMode=yes`. Use it in `fetch()` and `push()`, and
have `fetch()` use the same push-URL refspec as `push()`. **Effort:** S. **Tier:** B.

### primary-11 [MED] correctness — under `primary-push: auto` or `auto-on-quit`, quitting the TUI pops push questions, although the doc says "Nothing is asked"
`configsys/tui/menu.py:738-740` (`_quit_push` calls `_push_primary`, which uses `_TuiPushUI`, the asking UI).

plugins.md §8 says that under auto, "quitting the TUI pushes without asking. Nothing is asked: your own edits stay
out, and a conflict leaves it unpushed with a one-line note". As built, quitting with hand edits pops "push them
too?". A conflict would pop per-key and per-file dialogs. Under `auto-on-quit`, even `Q` ("quit without
confirming") stops for these dialogs. `test_quit_under_auto_pushes_and_force_never_stops` stubs `_push_primary`,
so it does not catch this.

**(reproduced)** `r36_auto_quit_asks.py` → `popups shown under auto-on-quit (doc: "nothing is asked"): ['prim: 1 file you edited by hand — push them too?']`.

**Fix:** under auto modes, pass a cautious UI to `primarygit.push`: the base `PushUI`, plus a `progress` that
paints the status line. Keep `_TuiPushUI` for `P` and for the `ask` prompt's "Push, then quit". **Effort:** S. **Tier:** B.

### primary-12 [MED] feature — `plugin push` gives no preview of what will leave the machine, and `--pretend plugin push` says nothing useful
`configsys/primarygit.py:331-332` (pretend returns before any read-only check), `:395-417` (the count is reported
only after the push); `configsys/tui/menu.py:741` (the quit prompt shows only a count).

docs/principles.md asks for preview first and for confirming outward-facing actions. The push publishes commits,
possibly to a public repository, and possibly including a freshly captured dotfile that holds a token. Neither the
CLI nor the TUI lists which commits or files will go out, and under `auto` nothing is shown at all.
`--pretend plugin push` returns `[pretend] would commit, combine and push prim — nothing sent`, even when nothing
is ahead or no remote exists.

**(verified by reading** `push()`; the pretend line is asserted by `test_pretend_pushes_nothing`.)

**Fix:** list `git log --oneline origin/<branch>..HEAD` (local and read-only, so allowed under `--pretend`) and
`--stat` file names before pushing. On a terminal, confirm. Let `--pretend` run the read-only checks (remote
present, ahead/behind as of the last fetch) and print that list. In the TUI, show the list in the quit prompt and
under `P`. **Effort:** M. **Tier:** G.

### primary-13 [MED] performance — every non-navigation TUI keypress costs 6 git spawns, 2 config parses and about 23 ms (63 ms with 500 untracked files), mostly to recompute a state nothing changed
`configsys/tui/menu.py:4981-4994` (snapshot, then commit, then `primarygit.state` and `push_mode` after every
non-navigation action, staging keys included); `configsys/primarygit.py:74-80,90-98,145-156`.

**(reproduced)** Measured with `r10_perf.py` on this machine (fast NVMe), over 20 iterations of one
non-navigation action that writes nothing:
- `per non-navigation TUI action (nothing written): 23.3 ms, 6 git spawns, 2 config parses`. The spawns are
  `status` twice, then `symbolic-ref`, `rev-parse`, `rev-list` and `status`.
- With 500 untracked files in the primary (an uncommitted capture): `62.7 ms`. Both snapshot and commit hash
  every dirty file.

That exceeds a 16 ms frame on staging keys such as `i`/`u`/`x`/`a`.

**Fix:**
- Skip the post-action `state()` unless `snap.committed`. The `dirty` bit can come from the `now` set that
  `commit()` already computed.
- Cache `primary_root` per ctx, keyed on the top config's mtime.
- Hash lazily, only the dirty paths that `now` still reports.
- With the journal from primary-07, skip both `git status` calls when nothing was written.

The expected cost is about 1 spawn per writing action and 0 per non-writing one. **Effort:** S–M. **Tier:** C.

### primary-14 [MED] refactor — a single `PrimaryRepo` git helper plus a transactional combine
`configsys/primarygit.py` throughout: 15 hand-built `git -C {shlex.quote(...)} …` strings, three inline
`ctx.runner.run(f'git -C …')` calls that bypass `_git` only to pass `env`, and five abort sequences.

Proposal: a `PrimaryRepo(root, runner)` with
- `status_paths()` (bytes-safe), `branch()`, `commit_paths(paths, subject, body)`,
  `stage_text(n, path) -> bytes`, `ahead_behind(upstream)`, `fetch(url)` and `push(ref)`;
- argv lists rather than `bash -c`, or a runner `run_argv`; `--literal-pathspecs`; pathspecs through stdin;
- one scrubbed, non-interactive env, as in primary-06 and primary-10;
- a context manager `combining()` that records HEAD and the stash, and on any exit that is not a commit runs
  `merge --abort`, `rebase --abort` and the unstash, then returns the `_intact` line.

This removes these bug classes: quoting and injection, the decode crash (05), the argument-limit crash (05),
globbing (18), env leaks (06, 10), and missing aborts (02, 03). It also removes duplication with
`plugins.branch_state` / `ensure_branch` / `_git_checkout`, which could move onto it. **Effort:** M. **Tier:** D.

### primary-15 [LOW] correctness — a primary that has never been pushed is invisible: no "not pushed yet" line, no chip, no quit prompt
`configsys/primarygit.py:145-156` (`state` returns None when `origin/<branch>` is missing, via `plugins.branch_state`);
`configsys/app.py:4833-4837`; `configsys/tui/menu.py:729-733`.

After `plugin init` and then `set-source` to a new, empty repository, `origin/main` does not exist. `state()`
returns None, so under the default `ask` mode configsys never says the primary is unpublished. That first push is
the one that matters most.

**(reproduced)** `r27_first_push_state.py` → `state(): None` → `_quit_push: (None, [])` → `commits never pushed: 2`.
No "saved to prim — … not pushed yet" line was printed.

**Fix:** when the branch exists and a push URL exists but `origin/<branch>` does not, have `state()` return
`ahead = rev-list --count HEAD` with `first=True`, matching what `push()` already computes. **Effort:** S. **Tier:** B.

### primary-16 [LOW] correctness — the driver's "git's own result" isn't: temp-file labels, CRLF becomes LF, a NUL byte truncates the file, invalid UTF-8 crashes the driver
`configsys/humerge.py:360-363` (`_line_merge`: no `-L` labels, `text=True`, so universal newlines and strict
decoding), `:380-389` (`driver`: reads in text mode; on a `merge-file` error the empty stdout is written to `%A`).

The docstring promises conflict-marker text "exactly what git's built-in merge would have left", and "never
worse than git's merge". In practice:
- markers read `<<<<<<< .merge_file_9mPl1X` (in your editor, and in an autostash conflict);
- every CRLF file is rewritten as LF, although git keeps CRLF;
- a `.hu` file containing a NUL byte (git treats it as binary, `merge-file` exits 255) leaves `%A` empty, so the
  per-file "edit both" then opens an empty file;
- invalid UTF-8 crashes the driver, so `%A` keeps only mine's text, without markers.

**(reproduced)**
- `r09_labels.py`: the editor shows `<<<<<<< .merge_file_9mPl1X … >>>>>>> .merge_file_0Q7uhB`.
- `r05_crlf.py`: `CRLF in: 5 CRLF out: 0`, against `git merge-file CRLF out: 5`.
- `r13_driver_errors.py`: `NUL byte (git: binary) rc=1 %A now 0 bytes (mine was 81)`, and `invalid UTF-8 rc=1 … UnicodeDecodeError`.

**Fix:**
- Pass `-L 'this machine' -L base -L 'your other machine'`.
- Use `%L` for the marker size.
- Do the I/O as bytes with `newline=''` and keep the file's own line ending.
- On a `merge-file` error, leave `%A` untouched and exit 1.
- Wrap the whole driver body in the `try` (`_line_merge` sits outside it today).

**Effort:** S. **Tier:** B.

### primary-17 [LOW] security — remote-controlled text goes raw into conflict prompts, so a branch can inject terminal escapes and spoof the question
`configsys/humerge.py:62-64,75-85` (`Conflict.words` / `_did` embed values and keys verbatim);
`configsys/app.py` (`_CliPushUI.resolve_value` / `resolve` `print` them, and file names from `_unmerged -z`);
`configsys/primarygit.py:296` (git's first stderr line, which can be a `remote:` line).

A value such as `"\x1b]52;c;…\x07\x1b[2K\rocean"` writes your clipboard (OSC 52) and erases and rewrites the
prompt line. That can make "keep the other machine's" look harmless.
- **Who controls it:** anyone who can push to the remote (or a hostile git server, through stderr).
- **When:** during `plugin push`.

**(reproduced)** `r26_escape.py` → `raw ESC/BEL in the prompt text: True True`.

**Fix:** strip or escape C0/C1 control characters (keeping `\t`) and show newlines as `⏎`. Do it in `_did`, for
file names, and for git-derived text, with one `_printable()` helper used by both UIs. **Effort:** S. **Tier:** A.

### primary-18 [LOW] correctness — `git add -A -- <paths>` treats paths as globs, so a file configsys writes can stage your hand edits
`configsys/primarygit.py:113-117` (also `:367-368`).

A captured `dotfiles/app.cfs/a[bc].conf` makes `git add` match your hand-edited `ab.conf` and stage it.
`commit -- paths` matched only the literal file, so the edit is not committed, but your index is changed without
asking. Names that start with `:` are parsed as pathspec magic.

**(reproduced)** `r16_pathspec.py` → `committed files: ['dotfiles/app.cfs/a[bc].conf']`, `status after: 'M  dotfiles/app.cfs/ab.conf'`
(staged by configsys).

**Fix:** `git --literal-pathspecs …`, or `GIT_LITERAL_PATHSPECS=1`, on every path-taking call (see primary-14).
**Effort:** S. **Tier:** B.

### primary-19 [LOW] correctness — humerge relies on a humon scanner that doesn't skip backtick strings and treats `\` as an escape, so files with script commands fall back to a whole-file question
`configsys/humerge.py:238-249` (`_key` → `plugins._locate_section_span`); `configsys/plugins.py:820-825`
(`_skip_trivia`: no backtick case, and `i += 2 if text[i] == '\\'`).

The humon skill says there are three quote styles, including backticks, and no escape mechanism. A primary
`components:` override whose `install-cmd:` is a backtick string containing `'` or braces breaks the span
scanner. Every key after it then becomes "not found", and the merge gives up. It falls back to the whole-file
question, and the verify guard keeps the result correct. humerge's own `_scalar_end` handles backticks correctly,
so the two scanners disagree.

**(reproduced)** `r11_backtick.py` → `span of splash: None` → `Unmergeable: could not find \`effects\``.

**Fix:** add the backtick case to `_skip_trivia`, drop the backslash-escape step, and share one scanner (see
primary-29). **Effort:** S. **Tier:** B.

### primary-20 [LOW] correctness — `plugins:` entries are merged in mine's order, so theirs' reordering (plugin layer precedence) is silently lost, and a duplicate source collapses
`configsys/humerge.py:160-183` (`_Merge.plugins`: `list(mk) + [new in tk]`, and `{d['source']: d}`);
`configsys/plugins.py:285-295` (`layer_files`: declaration order is overlay order among plugins).

**(reproduced)** `r20_plugin_order.py`. Base `[a, b]`, mine bumps a, theirs reorders to `[b, a]`, giving
`conflicts: [] | order: ['github:me/a', 'github:me/b']`.

**Fix:** if theirs' relative order of the shared sources differs from base, and mine's does not, take theirs'
order. If both reordered differently, raise a conflict at `('plugins',)`. Treat a duplicate source as
Unmergeable. **Effort:** S. **Tier:** B.

### primary-21 [LOW] correctness — per-key questions are numbered by file, and choosing "show me the file" discards the answers you already gave for that file
`configsys/primarygit.py:528-531` (`resolve_value(name, path, c.words(), i, n)` passes the file index), `:530-531`
(an `edit` answer returns before applying `answers`).

**(reproduced)** `r32_multi_key.py`. Two keys conflict in one file. Both prompts say `(1/1)`. After you answer
"mine" for `splash` and then "show me" for `effects`, the editor shows raw markers for both keys.

**Fix:** pass the key index and count (e.g. `(key 2 of 2, file 1 of 1)`, or let a question object carry them, as
proposed in the ABI section). On `edit`, merge with the answers given so far, so that only the unanswered keys
get markers, or at least say that earlier answers are dropped. **Effort:** S. **Tier:** B.

### primary-22 [LOW] correctness — `explain_git_failure` calls an HTTPS 403 "offline?" and always gives GitHub fixes, even for a GitLab source
`configsys/primarygit.py:268-296`.

GitHub's `Permission to x denied to y … unable to access … error: 403` matches `'unable to access'`, so the user
reads "couldn't reach … — offline?". The ssh advice hard-codes `ssh -T git@github.com` and `gh ssh-key add` for
every host.

**(reproduced)**
- A 403 gives `prim: couldn't reach github:me/prim — offline? Nothing was pushed; try again later.`
- A `gitlab:` source with a host-key failure gives `… (\`ssh -T git@github.com\`, answer yes) …`.

**Fix:** make it a rules table like `failures._RULES`: regex → template, with the host derived from the source
(`plugins.ssh_url`). Check `denied to`, `403` and `[remote rejected]` before the network patterns. **Effort:** S. **Tier:** B.

### primary-23 [LOW] correctness — the tag-to-branch switch writes `ref:` to your top config before the checkout, so a refused checkout leaves it half applied
`configsys/primarygit.py:353-359` (`set_declared` first, then `plugins.sync`, and on `kept` it returns failure
without restoring).

**(reproduced)** `r25_switch.py`. A tag-pinned primary with an uncommitted edit; answer yes. Result:
`ok False` with the `kept` note, `declared ref now: main | HEAD: main`. Push says it failed, but the config and
HEAD were both switched (and HEAD is behind).

**Fix:** run the checkout first, through `_git_checkout` on a copy of the decl, and write `ref:` only on
`updated`/`ahead`/`ok`. Otherwise restore the previous `ref` and the detached HEAD. Ask about including hand edits
before switching, since they are what blocks the checkout. **Effort:** S. **Tier:** B.

### primary-24 [LOW] correctness — the "no git identity is set" note is wrong when your identity comes from the environment, and `user.name` is never checked
`configsys/primarygit.py:131-140` (`_ident` checks only `git config user.email`).

With `GIT_AUTHOR_*` / `GIT_COMMITTER_*` (or `EMAIL`) set and no config, configsys prints "commits … are signed
schrock@pop-os" while git really uses the env identity. With `user.email` set but no `user.name` and an empty
GECOS field, the commit fails ("empty ident name").

**(reproduced)** `r24_ident.py` → `configsys: no git identity is set, so commits to prim are signed schrock@pop-os …`,
then `author of the commit: t <t@t>`.

**Fix:** probe with `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`, and use the fallback only when
git cannot form one. Cache the result per ctx, which also saves one spawn per commit. **Effort:** S. **Tier:** B.

### primary-25 [LOW] correctness — `_has_markers` reads a Markdown `=======` underline as an unresolved conflict, so an edited README stops the push
`configsys/primarygit.py:601-606`.

**(reproduced)** `r31`: `README with a setext heading reads as unresolved: True`.

**Fix:** require a `<<<<<<< ` line or a `>>>>>>> ` line, and count `=======` only between them. **Effort:** S. **Tier:** B.

### primary-26 [LOW] correctness — type-change conflicts are misdescribed, and "keep this machine's" pushes the file renamed to `<path>~HEAD`
`configsys/primarygit.py:564-573` (`_what_changed` assumes a missing stage means a deletion), `:576-598` (`_take`).

The remote turned `notes.txt` into a symlink while this machine modified it. You are asked "this machine deleted
it; your other machine changed it" for `notes.txt`, and separately about `notes.txt~HEAD`. Answering "mine" to
both pushes a tree containing `notes.txt~HEAD`. No write escaped the repository: the victim file stayed
untouched, and `_take` writes only regular files.

**(reproduced)** `r33_symlink.py` → `asked: [('resolve', 'notes.txt', 'this machine deleted it; …'), ('resolve', 'notes.txt~HEAD', …)]`.
The remote tree then holds `notes.txt~HEAD p.hu plugin.hu`.

**Fix:** detect type and file/directory conflicts (`git ls-files -u` modes, and the `~HEAD` / `~<branch>`
siblings), describe them as such, and resolve the pair together: keep mine means `git mv` the `~HEAD` file back.
Or treat them as "stop and settle by hand". **Effort:** S–M. **Tier:** B.

### primary-27 [LOW] reuse — the same commit, branch, error and choice logic is hand-copied, and the push-mode list exists twice while `primary-push` values go unvalidated
Copies:
- **The commit sequence is written twice:** `_ident`, then `add -A -- paths`, then `commit -m -m -- paths`, then
  the error text. `configsys/primarygit.py:112-123` (`commit`) and `:366-373` (`push` include-own).
- **Two ways to find the primary:** `primary_root` (`:37-50`) and `_primary` (`:305-313`), with different checks.
- **The current-branch lookup is repeated:** `symbolic-ref --short -q HEAD` at `:106` and `:343`, plus
  `plugins.branch_state`, `ensure_branch` and `_orphan_commits`.
- **Error text is extracted four ways:** `((r.stderr or r.stdout or "") if r else "").strip()[:200|160]` at
  `:117,121-122,372-373,476-477`.
- **The choice tables are copied in both UIs:** `{'m': 'mine', 't': 'theirs', 'e': 'edit'}` and the labels, in
  `app._CliPushUI` and `menu._TuiPushUI`, and the wording already differs ("keep this machine's" versus "Keep this one").
- **Pluralization is inline:** "them/it", alongside `_count`. `_quit_push` says "1 change … shares them".

`PUSH_MODES` (`:219`) is unused, while `Config.primary_push` hard-codes the same tuple (`config.py:328`). Nothing
validates the value: **(reproduced)** `configsys config set primary-push autoo` → `set primary-push = autoo`,
rc 0, no `check` warning, and at runtime it silently means `ask`.

**Fix:** `_commit_paths(...)`, `_err(r, n)`, and one `PUSH_CHOICES` table that both UIs render. Make
`Config.primary_push` use `primarygit.PUSH_MODES`, and have `set_config_setting` and `check` reject or warn on
unknown values. **Effort:** S. **Tier:** D.

### primary-28 [LOW] data-driven — push-mode policy, the header chip and git-failure wording are spread through code instead of held as data
- **The mode policy is scattered.** Which modes push after a CLI command, which push on quit or on `Q`, and which
  hide `↑` is split across `configsys/app.py:4827-4837`, `configsys/tui/menu.py:733-745` and
  `configsys/tui/screens/components.py:144-146`.
- **The chip is computed during drawing.** The last of those, in components.py, calls `primarygit.chip(...)`
  inside `draw()` rather than `build_vm`.
- **The failure wording is an if-chain.** `explain_git_failure` duplicates the shape of `failures._RULES`.

**Fix:** a `PUSH_POLICY = {'ask': {cli: 'hint', quit: 'prompt', quit_force: 'note', hide_ahead: False}, …}` table
in primarygit, read by all three call sites. Put the chip on the Components VM, which lets a mock state drive it
in render tests. Turn the failure rules into a table (primary-22). **Effort:** S. **Tier:** D.

### primary-29 [LOW] refactor — one shared module for humon text surgery
`configsys/humerge.py:229-295` imports five private names across modules: `plugins._scan_value_end`,
`plugins._locate_section_span` and `plugins._emit_block`, plus `troveio._scalar` and `troveio._UNSAFE`. It also
keeps its own `_skip`, `_scalar_end` and `_emit`, which near-duplicate `troveio._emit` and `plugins._emit_kv`.

**Fix:** a `hutext.py` that owns the scanner (with backtick and no-escape semantics, primary-19), `key_span`,
`set_section`, the scalar quoting and the emitters, used by plugins, troveio and humerge. That fixes the scanner
once and makes `_emit`'s list layout match configsys's own writers. **Effort:** M. **Tier:** D.

### primary-30 [LOW] feature — no way to see or undo configsys's commits from configsys
The docs sell the auto-commits as "small, undoable commits", but undoing one takes git by hand: there is no
`configsys plugin log` or `plugin undo` in the CLI, and nothing in the TUI.

**Fix:** `plugin log [-n]` (subjects plus files, from `git log origin/<branch>~..HEAD`), and `plugin undo`, which
reverts the last configsys-made unpushed commit (a `git revert` once pushed). Add a Plugins-screen view. This
pairs with the push preview (primary-12). **Effort:** M. **Tier:** G.

### primary-31 [LOW] parity — the TUI fetches the primary to count `↓`, but the CLI `plugin list` never does
`configsys/app.py:3194-3197` (`describe(state(ctx))`, local only) versus `menu.PluginScreen._start_remote`
(fetches first).

On the CLI, "N changes from your other machines" stays as stale as the last sync, so a machine that only uses the
CLI never learns it is behind.

**Fix:** `plugin list --fetch`, or a `plugin status` that runs `primarygit.fetch` (non-interactive, primary-10)
before `describe`. **Effort:** S. **Tier:** G.

### primary-32 [NIT] comment-drift — docstrings that describe what the code no longer does
- `configsys/primarygit.py:421`: `_merge_driver` claims to return "(git -c options, env)", but it returns `(opts, env, notes)`.
- `:317-320`: `push` says "A conflict is asked about per file (`ui.resolve`)", but `.hu` files are asked per key (`resolve_value`).
- `:13`: "a repo-local fallback (`<user>@<host>`)". It is per-command `-c`, and nothing is written to the repo config.
- `configsys/humerge.py:40-41`: `SET_LISTS` "Lists whose order carries no meaning" is false for profiles (primary-08).
- `configsys/humerge.py:18-27`: the "built from MINE's text", "exactly what git's built-in merge would have left"
  and "never worse than git's merge" claims are broken by primary-08, -09 and -16.

**Fix:** update the wording with the fixes. **Effort:** S. **Tier:** E.

### primary-33 [NIT] naming — `mine` means two things in one module, and git results get single-letter names
`configsys/primarygit.py:363-376`: `mine` is "your hand-edited paths", while in `_combine`, `_settle_hu` and
`_take` `mine` is "this machine's version". The git results are named `c`, `f`, `p`, `m`, `s`, `r`, plus `bs`
and `drv` (an options string, next to the `driver` function).

**Fix:** `hand_edited`, `fetch_result` / `push_result` (or the PrimaryRepo methods), and `driver_opts`. **Effort:** S. **Tier:** D.

### primary-34 [NIT] correctness — repeated notes, leftover scratch copies, and `.git` assumed to be a directory
- The "also has edits of your own" note is returned on every action that touches a mixed file, and
  `menu.py:4998,5021` prints every copy after exit, unde-duplicated.
- `_merge_driver` and `_take` leave `.git/configsys-merge/{attributes,notes,base,mine,theirs}` behind. The last
  three are full copies of your file contents.
- `root / '.git' / 'configsys-merge'` fails when `.git` is a gitlink file (a worktree or submodule primary), while
  `primary_root` accepts that layout.

**Fix:** de-duplicate `pending_notes`. Remove the scratch directory in a `finally`. Use `git rev-parse --git-dir`.
**Effort:** S. **Tier:** B.

## Test gaps
Against test/test_humerge.py, test_primary_push.py, test_primary_state.py and test_primary_autocommit.py:
1. **No exception-safety test for `_combine`.** Nothing covers a `KeyboardInterrupt` or `OSError` from a UI
   method, a binary conflict, or a malformed `plugins:` entry mid-merge (primary-02). A `Scripted(raise_on=…)`
   UI, like the one in `harness.py`, is enough.
2. **No hand edits that overlap incoming changes**, on either the rebase path (autostash) or the merge path
   (`_unstash`) (primary-03). `test_hand_edits_survive_a_conflicted_combine` covers only the non-overlapping case.
3. **No test that the merge driver is isolated from the checkout's files** (a planted `subprocess.py` /
   `configsys/__init__.py`) (primary-01).
4. **No non-UTF-8 or binary content or names** in snapshot, commit or `_stage`, and no NUL or invalid UTF-8 in
   the driver (primary-05, -16).
5. **No test that every TUI write action is bracketed.** Config/Theme `select` is the live miss (primary-04).
   The existing `test_the_tui_bracket_commits_one_action` calls `_commit_primary_action` directly.
6. **No `GIT_DIR` / `GIT_WORK_TREE` isolation test**, and no test for `GIT_SSH_COMMAND` versus `core.sshCommand`
   or for `fetch()`'s BatchMode (primary-06, -10).
7. **Auto-mode quit asks nothing:** `_quit_push` tests stub `_push_primary`, so the UI it really uses is never
   exercised (primary-11).
8. **humerge cases with no test:**
   - profile order, against git's clean merge (primary-08);
   - comments inside a combined list, and a comment-only edit hitting the `merged == t` shortcut (primary-09);
   - CRLF, and `plugins:` reorder or duplicates (primary-20);
   - a dict `source:`, and backtick strings (primary-19);
   - quoted keys;
   - `_remove` of a key with a trailing comment (it leaves the orphan comment);
   - the verify guard actually firing ("did not read back the same"), e.g. by monkeypatching `_rewrite`.
9. **Several conflicts in one file:** mixed answers, then `edit`, and the numbering (primary-21).
10. **`explain_git_failure` cases:** 403, a `gitlab:` host, and `[remote rejected]` (primary-22). The push-path
    failures are also untested: a fetch failure, a push rejected by a race, and a hand-edit commit failure.
11. **Paths:** more than 128 KiB of paths, glob characters, `:`-prefixed names, and spaces (primary-05, -18).
12. **Odd primaries and conflicts:** `state()` for a never-pushed primary (primary-15); the tag switch when sync
    returns `kept` (primary-23); `_take` for delete/modify and type changes; the `_what_changed` variants
    (primary-26); `_has_markers` false positives (primary-25).
13. **Pretend:** the sweep (`test/test_pretend_sweep.py`) has no git primary, so `plugin push` there stops at
    "you have no primary plugin" and the snapshot/commit bracket never runs against a real primary.
    `test_pretend_pushes_nothing` checks only the remote, not that the clone and home are byte-identical.

## Dead code
- `configsys/primarygit.py:219` `PUSH_MODES` is defined and never read. Grepped `configsys/`, `test/`, `examples/`
  and `~/src/configsys-*/`: the only hit is its definition. `Config.primary_push` hard-codes the tuple instead.
  Folded into primary-27: make it the single source rather than deleting it.
- `configsys/humerge.py:56` `Conflict.base` is stored and never read: no reader in primarygit, app, menu or the
  plugin repos. It is harmless as data for a future "what it was" UI, so keep it, unless the question object
  proposed in the ABI section uses it.
- No other dead code. Every other public and private name in both modules has a live caller. Checked: `glyphs`,
  `chip`, `describe`, `state`, `fetch`, `push_mode`, `explain_git_failure`, `merge_data`, `Result.merged` (read by
  `driver`), and `_driver_notes`. Neither module is on the frozen ABI list in `configsys/driver.py`'s docstring,
  and no plugin repo imports either one.

## ABI / interface candidates
None of this is plugin-facing: no plugin repo imports `primarygit` or `humerge`, and neither is in the frozen ABI.
Internal interfaces worth changing now:
- **`PushUI` as a question object.** Today it has five methods with positional `(name, path, what|words, i, n)`,
  where `i, n` count files even for per-key questions (primary-21). Make it one `ask(Question) -> answer`, where
  `Question` carries `kind` (`include_own` | `switch_branch` | `file` | `key`), the text (already sanitized,
  primary-17), the file and key index/count, and the allowed answers from a shared `PUSH_CHOICES` table. The CLI
  and TUI then render from the same data (primary-27) and tests can script it.
- **`primarygit.state()` as a dataclass.** Today it is a dict with string keys. A
  `PrimaryState(name, branch, ahead, behind, dirty, first_push)` lets `glyphs`, `chip` and `describe` become
  properties or VM fields, and `first_push` fixes primary-15.
- **The merge-driver command line.** Moving from `-m configsys.humerge` to `-I -c …` (primary-01) is internal,
  but `humerge`'s `__main__` should become a named `main(argv)` so the isolated entry point and the tests share it.

## Questions for the user
1. **Should configsys's own auto-commits bypass your git hooks and signing?** That would mean `--no-verify` and
   `-c commit.gpgsign=false` on the commits it makes for its own edits. Today a global `init.templateDir`
   pre-commit hook, or `commit.gpgsign=true`, runs or prompts (pinentry) on every TUI action that writes, and
   fails or garbles the screen. Not reproduced, since it depends on your git config. Verified by reading:
   `commit()` passes neither flag.
2. **Commit by write journal instead of by snapshot difference?** (primary-07 and -04.) It needs one
   `note_write` call at each writer to the primary, but removes the action allowlist, the concurrency sweep-in
   and most of the per-keypress cost.
3. **What should happen to hand edits that overlap incoming changes** (primary-03)? The options are: refuse to
   push and ask "include them, or stop"; or push, stash the edits and say so plainly. The first follows the "no
   surprises" principle more closely.
4. **Is it fine to publish your machine name and login to a possibly public remote?** Every commit body carries
   `Made by configsys on <hostname>`, and the identity fallback is `<login>@<hostname>`.
5. **Profiles in `SET_LISTS`** (primary-08): drop them (both sides changing one profile becomes a question), or
   build an order-preserving list merge?
6. **Should `plugin push` on a terminal list the outgoing commits and confirm** (primary-12), given that
   principles.md says outward-facing actions are confirmed? Or is typing the command consent enough, with
   `--yes` for scripts?

## Refuted on verification
None. All six checked findings (primary-01 … primary-06) were confirmed by reproduction. Two of them carry a
correction in their **Verified** line:
- primary-05: a clean `plugin sync` does not trigger the crash.
- primary-06: in the default yadm/vcsh layout, the auto-commit does not land in the other repo.
