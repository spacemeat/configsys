# Review: Primary plugin: commits, push, merge

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/primarygit.py` (1328 lines), `configsys/humerge.py` (535 lines), read line by line.
Context: CLAUDE.md, docs/principles.md, docs/plugins.md (§6a locks, §8 the primary), docs/done/primary-push-plan.md,
`configsys/plugins.py` (`declared` / `_decl` / `set_section` / `set_declared`, `_git_checkout`, `branch_state`,
`default_branch`, `_git_transport`, `sync`, `unsigned_commits`, `ssh_url` / `_set_push_remote`), `configsys/hutext.py`
(what humerge calls), `configsys/app.py` (`main`'s bracket, `_after_primary_commit`, `_CliPushUI`, `_plugin_log` /
`_plugin_undo`, `cmd_plugin` push/list), `configsys/tui/menu.py` (`_commit_primary_action`, `_TuiPushUI`,
`_TuiAutoPushUI`, `_push_primary`, `_quit_push`, the router bracket, `PluginScreen.reload` / `_start_remote`),
`configsys/tui/screens/plugins.py` (`P`, `H`), `configsys/actions.py` (lock helpers, theme writers, `set_included`),
`configsys/drivers/dotfiles.py` (capture, the generated `.gitignore`).
Tests read: test/test_humerge.py, test/test_primary_push.py, test/test_primary_safety.py, test/test_primary_journal.py,
test/test_primary_autocommit.py, test/test_primary_state.py, test/test_primary_verify.py, test/test_hutext.py
(146 pass at baseline, 66 s), and test/test_pretend_sweep.py's fixture.

Every **(reproduced)** item was run against throwaway repos under
`/tmp/claude-1000/-home-schrock-src-configsys/ee26ccb3-21d9-4cf2-af6f-f787f6c091af/scratchpad/review-2026-11-08/scratch/primary/`.
`harness.py` there is the tests' fixture (a bare "remote", a second clone standing in for "your other machine", a
sandbox `--home` whose blessed primary is cloned from the remote) with `GIT_CONFIG_GLOBAL=/dev/null`; each `rNN_*.py`
is a self-contained reproduction.

**Verification pass (2026-11-08, an independent checker, started fresh):** checked every HIGH, and every
safety/security finding at MED or above (primary-01, -02, -03, -05, -06, -07, -08). Also checked primary-04, which
turned up while setting up primary-03. Each was re-run from scratch, not through the reviewer's scripts. An earlier
checker's partial `vh.py` / `v*.py` were not used either.
- **Harness:** `ch.py` in `…/review-2026-11-08/scratch/verify-primary/c/`. It runs the real CLI as a subprocess:
  `.venv/bin/python -m configsys --home …/verify-primary/home/<case> --os pop …`.
- **Isolation:** `HOME` is set to the sandbox too, and the caller's `GIT_*` / `CONFIGSYS_*` / `XDG_*` variables are
  dropped. git runs with no system or global config.
- **Prompts:** a pty is used wherever a question must really be asked.
- **Files:** each `cNN_*.py` there is one check, and its output is in `cNN.out`.
- **Scope of the runs:** nothing was installed. Only plugin / picks / config verbs ran, against local repositories.

**Result:** all eight confirmed, none refuted, one severity changed (primary-03 HIGH → MED). Each result is the
**Verified:** line under its finding. Two reach further than the reviewer wrote:
- **primary-05:** inside a yadm session, the switch also fast-forwarded the dotfiles repository and set its push URL
  to the primary's.
- **primary-04:** a later `config set` also cut the line the duplicate key was on.

## Carried over from docs/review-2026-11/primary.md (baseline c25bb0a) and docs/review-2026-09/
| earlier finding | status | evidence |
|---|---|---|
| primary-01 merge driver imports code from the checkout | fixed | `34d6a20`; `_merge_driver` runs `python -I -c` with configsys's own path (primarygit.py:1046-1054); its test passes |
| primary-02 `_combine` not exception-safe | fixed | `da323ea`; `except BaseException` → `_restore` + `_unstash` + re-raise (1093-1098) |
| primary-03 overlapping hand edits → markers, push "ok" | fixed | `da323ea`; no `--autostash`, `overlap` question first (843-853). New holes in the same promise: primary-03, primary-06 below |
| primary-04 `select` writes not committed | fixed | `f5e0340`, `d99c1b3` (write journal; `_NO_WRITE_ACTIONS` gone) |
| primary-05 non-UTF-8 name / argv overflow | fixed | `efa9c38` (`PrimaryRepo`: bytes, `--pathspec-from-file`) |
| primary-06 ambient `GIT_DIR` | fixed for every `PrimaryRepo` call (`efa9c38`) | residual: the tag-to-branch switch still goes through `plugins.sync` / `default_branch` with the ambient env — primary-05 below |
| primary-07 mid-command hand edits committed | fixed | `d99c1b3` (journal; `stray` note) |
| primary-08 profile terms merged as sets | fixed | `17643aa` (`ORDERED_LISTS`, `_merge_sequence`); residual: one term added at two points — primary-10 below |
| primary-09 comments dropped | fixed | `17643aa` (`_relist` in place; `merged == t` only when mine changed nothing) |
| primary-10 ssh env wrong both ways | fixed | `efa9c38` (`network_env`); nit about `GIT_SSH` in primary-24 |
| primary-11 auto quit asks | fixed | `e03afa8` (`_TuiAutoPushUI`) |
| primary-12 no push preview | fixed | `0aa1606` (confirm-push, `_pretend_preview`); TUI shows no files — primary-15 |
| primary-13 per-keypress git cost | fixed | `d99c1b3`; `test_an_action_that_writes_nothing_runs_no_git` |
| primary-14 `PrimaryRepo` + transactional combine | fixed | `efa9c38`, `da323ea` |
| primary-15 never-pushed primary invisible | fixed | `e03afa8`; `state()` `first_push` (437-443) |
| primary-16 driver fallback not git's own | fixed | `a4e5132` (labels, bytes, CRLF, binary untouched) |
| primary-17 remote text raw in prompts | fixed for questions (`fd0e94f`, `question()` → `_printable`) | residual: driver notes and the "settled" line are printed raw — primary-11 below |
| primary-18 globs in pathspecs | fixed | `efa9c38` (`--literal-pathspecs`) |
| primary-19 scanner vs backticks / `\` | fixed | `3e8be8a`; hutext.skip_trivia |
| primary-20 `plugins:` order lost | fixed for shared entries (`3e8be8a`) | residual: a NEW entry is always appended — primary-10 below |
| primary-21 per-key numbering / edit drops answers | fixed | `fd0e94f` (`index`/`count` per key; "sets aside the answers above") |
| primary-22 `explain_git_failure` wording | fixed | `fd0e94f`, `6f77f95` (`_FAILURES` table, host-aware) |
| primary-23 tag switch writes `ref:` first | fixed | `ab5c941` (sync first, `ref:` after; restore `was`) |
| primary-24 identity note wrong | fixed | `ab5c941` (`git var`) |
| primary-25 Markdown `=======` | fixed | `e03afa8` |
| primary-26 type-change conflicts | fixed | `5e2bd33`; residual: a real `x~` file is mistaken for git's rename — primary-09 below |
| primary-27 copied logic, unused `PUSH_MODES` | fixed | `6f77f95` (`layers.SETTING_CHOICES`, `_commit_paths`, `_err`, `_them`) |
| primary-28 push policy / chip as data | fixed | `6f77f95` (`PUSH_POLICY`, chip in the Components VM) |
| primary-29 one humon text module | fixed | `0c62c22` (`configsys/hutext.py`) |
| primary-30 no log / undo | fixed | `ad01667` (`history` / `undo`, `plugin log|undo`, Plugins `H`); new undo issues: primary-08, primary-20 |
| primary-31 CLI never fetches | fixed | `b1de32d` (`plugin list --fetch`) |
| primary-32 comment drift | fixed | `d783030`; one new drift in primary-23 |
| primary-33 naming | fixed | `d783030` (`hand_edited`, `left_out`, `driver_opts`) |
| primary-34 repeated notes, scratch copies, `.git` as dir | fixed | `e03afa8` (`--absolute-git-dir`, `finally: rmtree`) |
| 2026-09 open items (A5, A7, A10, D2–D9, Tier F) | obsolete for this area | primarygit.py / humerge.py postdate that review; D8's humon text surgery now lives in hutext.py (config-layers area) |

## Cross-cutting themes
- **"Put everything back" only knows about the files git shows it.** `_combine` stashes what `git status` reports and
  restores with `reset --hard` / `merge --abort`. Three kinds of local state fall outside that model, and each loses
  or disturbs the user's work: ignored files (primary-03: a secret deleted on "Stop"), a stash entry that was never
  created (primary-06: the user's older stash is popped), and a lock the user set (primary-02: combined in anyway).
- **Two paths still run git outside `PrimaryRepo`.** The tag-to-branch switch calls `plugins.sync` /
  `plugins.default_branch`. They are transitive, lock-unaware, use the ambient env and have no BatchMode (primary-05).
  Everything the 2026-11 safety plan bought (scrubbed env, one repository, non-interactive) is missing on that one path.
- **"git's clean merge is the authority" trusts git where git is structurally blind.** A line merge cannot see
  duplicate keys, so the driver keeps a file with `splash:` twice. That happens both when humerge had found a real
  conflict and when it had cleanly de-duplicated the key (primary-04). The same blind spot shows in the order merges
  (primary-10).
- **humerge's text scanner trusts its input to make progress.** One unhandled token (`:` from a metatag in a list)
  turns into an infinite loop that also allocates without limit (primary-01). The re-read guard runs only after the
  rewrite, so it can't catch a scan that never ends.
- **Git-level undo of filesystem-level effects.** `plugin undo` reverts the commit but not what the commit recorded:
  files moved in from outside the primary, or linked from outside it (primary-08).
- **Outward-facing actions that run after the user said stop or no.** An auto push in `main()`'s `finally` after
  Ctrl-C (primary-07). A combine that stays in place after "Don't push" (primary-13).

## Findings

### primary-01 [HIGH] correctness — a metatag inside a list makes humerge loop forever, allocating without limit: `plugin push` (and every auto push) hangs and eats memory
`configsys/humerge.py:358-377` (`_list_items`). For a scalar it calls `_scalar_end(text, i)` and continues from `i = j`.
At a `:` the token is empty (`:` is one of `scalar_end`'s delimiters), so `j == i`, an empty item is appended, and the
loop never advances.

humon accepts a metatag after a list item: `[ btop @why: work  fzf ]` reads as `['btop', 'fzf']`. Whenever both
machines change such a list, the driver reaches `_relist` → `_list_items`. That covers a picks column, any `SET_LISTS`
or profile list. git runs the driver as a child of `rebase`, so `plugin push` never returns. Under
`primary-push: auto` the hang follows any CLI edit, and in the TUI it follows `P` or quit.

The `out` list grows by about 50 MiB/s, so a machine left waiting runs out of memory. The input is valid humon,
written either by the user or by anyone who can push to the primary.

**(reproduced)**
- `r16_list_hang.py` with `faulthandler` → `Timeout (0:00:05)! … hutext.py line 145 in skip_blank / humerge.py line
  363 in _list_items / line 385 in _relist / line 435 in _rewrite`.
- `r16b_mem.py`: the merge's RSS grew `65 → 118 → 160 MiB` over 3 s.
- `r16c_push_hang.py` (end to end): `primarygit.push` never returned (`timeout 12` → exit 124), and killing it left the
  primary in `interactive rebase in progress`.

**Fix:** in `_list_items`, raise `Unmergeable('a list item humerge cannot read')` when `j == i`. That covers metatags
and any other zero-width token, and the file then falls back to the whole-file question. Add a test with
`[ a @k: v  b ]` changed on both sides. As a backstop, give the driver a time budget (e.g. `signal.alarm`, then return
1 with git's text). **Effort:** S. **Tier:** B.

**Verified:** CONFIRMED (reproduced). Three levels, each bounded by its own process group, a 3 GiB address-space
cap and a wall-clock kill:
- **The function** (`c/c01_metatag_hang.py`): `humerge._list_items("[ btop @why: work  htop ]")` under `timeout 5`
  → exit 124. humon reads that list as `['btop', 'htop']`.
- **The merge driver**, run the way git runs it during a rebase. `%A` is the other machine's text with the note, `%B`
  is this machine's `picks add fzf`. It never returned. RSS went 118 → 259 → 395 → 536 MiB at 4 / 8 / 12 / 16 s,
  about 35 MiB/s.
- **End to end:** the other machine pushes `this-machine: [ btop @why: work  htop ]`, this machine runs
  `picks add fzf`, then `configsys plugin push --yes`. After 20 s it was still running, with the driver at 764 MiB.
  After the kill, the primary was in `interactive rebase in progress` and the remote never got fzf.
- **Under auto** (`c/c01b_auto_hang.py`): with `primary-push: auto`, the plain `picks add fzf` never returned. The
  driver was at 855 MiB after 19 s, and the primary was left mid-rebase.

No hand edit on this machine is needed. In a rebase the driver's MINE is the remote's text, so a note written on the
*other* machine is what loops. HIGH kept.

### primary-02 [HIGH] safety — `plugin push` combines the remote into a primary you have LOCKED, and under `primary-push: auto` any CLI edit does it without a push command
`configsys/primarygit.py:751-884` (`push`). Nothing in the module reads `plugin-locks.hu`. `actions.plugin_lock`
(actions.py:1563) accepts the primary.

docs/plugins.md §6a says a lock "holds a plugin where it is on this machine — typically because its review diff shows
something you don't want". `plugin sync` honours it and reports `locked`. `push`, however, fetches and rebases this
machine onto `origin/<branch>`, and that brings the held-back commits into the checkout. From there they load as the
primary's data on the next run, and the primary's linked shell glue is sourced at the next shell start.

- **Who controls it:** whoever can push to the primary's remote. The user's defence (the lock) is the thing bypassed.
- **When it runs:** an explicit `plugin push`, `P`, or "Push, then quit". Under `auto`, also the next `configsys picks
  add …` or any other command that writes the primary.
- **Consent:** none; nothing mentions the lock.

**(reproduced)** `r02_locked_primary.py`. `plugin lock prim`, then the other machine pushes `ALARMING`. `plugin sync`
gives `locked prim` and `after sync, ALARMING here? False`. Then `config set primary-push auto` → `pushed 1 change …`,
and `after … (auto-pushed), ALARMING here? True`.

**Fix:** in `push()`, read `actions._locks(ctx)`. If the primary is locked and `behind > 0`, refuse to combine:
"prim is locked — the remote has N changes you held back; `plugin unlock prim` to take them in". Pushing when not
behind can still be allowed. `_quit_push` and `_after_primary_commit` then just report it. Alternatively, make
`plugin lock` refuse the primary and point at `primary-verify: signed`. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced) with the real CLI (`c/c02_locked_primary.py`). The other machine pushes
`laptop: [ htop  ALARMING ]` and `glue/bash/alarm.sh`.
- **The lock holds sync:** `plugin lock prim` → `locked prim — no sync, update or trust until you unlock it`.
  `plugin sync` → `locked   prim`, and alarm.sh is not here (`False`).
- **Push takes it in anyway:** `picks add fzf`, then `plugin push` (no terminal) → `p.hu: both machines changed it —
  combined key by key.` / `pushed 1 change …`. Now alarm.sh is here (`True`) and so is ALARMING in p.hu (`True`).
  `plugin-locks.hu` still holds `prim: 2026-11-08`, and `--machine laptop picks list` lists `ALARMING`.
- **Under auto:** `config set primary-push auto` alone → `pushed 1 change …`. The primary's log is now `picks add jq`,
  `config set primary-push auto`, `other: something alarming`, `initial`.
- **No guard anywhere:** read `push`, `cmd_plugin push`, `_push_primary`, `_quit_push` and `_after_primary_commit`;
  none checks a lock.

HIGH kept.

### primary-03 [MED] safety — an ignored file of yours (a secret a `.cfs` `.gitignore` keeps out of git) is deleted when you answer "Stop", and replaced by the other machine's copy when you go on
`configsys/primarygit.py:1086-1115` (`_combine` / `_restore`). `stash push --include-untracked` leaves ignored files
alone. `_restore`'s docstring says "the tree holds nothing of yours to lose", which is false here.
`push()`'s overlap check (843) sees only `dirty()`.

dotfiles writes a `.gitignore` into each `.cfs` dir "so secrets never sync" (drivers/dotfiles.py:201-214). The real
secret then lives inside the primary as an ignored file, behind the linked config dir. Suppose another machine stops
ignoring that path, by dropping the exclude and capturing its own copy. This machine's rebase or merge then
overwrites the local file silently, because git treats ignored files as expendable. If the user stops, `merge --abort`
/ `reset --hard` deletes it as "not in HEAD". The message is "nothing was pushed, and your work is committed here as
it was", and the secret is in no commit and no stash.

**(reproduced)** `r04_ignored.py`. `secret.env` = "MY SECRET" is ignored here, and the other machine commits
`secret.env` = "OTHER MACHINE":
- answering `stop` → `ok False | … nothing was pushed …` → `secret.env now: GONE | stash: ''`;
- answering `mine` → `secret.env now: 'OTHER MACHINE\n'`.

**Fix:** before combining, compute `ignored = git ls-files --others --ignored --exclude-standard -z` ∩
`repo.incoming(upstream)`. Treat a hit like an overlapping hand edit, with a question: "your ignored file X would be
replaced by the other machine's: stop / move yours aside to `X.pre-configsys`". Fix `_restore`'s docstring. Pass this
to the plugins reviewer too: a plain `plugin sync` fast-forward overwrites the same file. **Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced) on a pty (`c/c03_ignored_secret.py`). Setup: here, `app.cfs/app/secret.env` =
`MY SECRET` is ignored by `app.cfs/.gitignore`. The other machine drops the exclude and commits its own `secret.env`,
plus a change to a line of `notes.txt` that this machine also committed.
- **A. Stop:** at `notes.txt (1 of 1) — both machines changed the same lines`, answer `[s] Stop` → `nothing was
  pushed, and your work is committed here as it was`. HEAD is unchanged, but `secret.env now: GONE`. The stash is
  `''`, and `MY SECRET` is in no commit.
- **B. Keep mine:** `[m]`, then `[p] Push` → `secret.env now: 'OTHER MACHINE\n'`.
- **C. Decline:** with no conflict at all, `[n] Don't push` → replaced too.
- **D. Plain sync:** with no local commits, `plugin sync` (`updated prim`) → replaced too.

**Severity HIGH → MED.** The loss needs another machine to start tracking the very path this machine ignores. Here
that was dropping the exclude from the shared `.gitignore`; the other route is a machine-local or global ignore that
differs between machines. The replace-on-continue half is git's own treatment of ignored files, and `plugin sync`
does the same. What is configsys's own is the Stop/abort path: it deletes the file while saying nothing changed. That
is real data loss, but on an uncommon path, the same reach as primary-06 and primary-08.

### primary-04 [MED] correctness — the driver keeps git's "clean" merge even when it holds a key twice: a real disagreement is settled without a question, and the file is left so that later `config set` has no effect
`configsys/humerge.py:501-504` (`driver`). When humerge finds conflicts, git's text is written with `return 0 if
clean`. Separately, at `:506-515`, a clean git text is kept whenever its data equals humerge's.

A line merge can't see that both machines added `splash:` at different places, so it merges "cleanly" into a map
with two `splash:` keys. humon reads the last one, and `plugins.set_section` edits the first. Two consequences:
- **The disagreement is decided silently.** This machine's `splash: plain` against the other's `splash: ocean` is
  pushed with no question, and one side is lost.
- **Equal values are kept twice.** When both sides added the same value, humerge's own result (key once) is thrown away
  in favour of git's text (key twice).

From then on, `configsys config set splash X` reports success and changes nothing. `check` doesn't notice.

**(reproduced)**
- `r05_dupkey.py`: `humerge.merge conflicts: [Conflict(splash)]` → `driver rc: 0 (0 = settled, no question)`, the
  output holds `splash: plain … splash: ocean`, and it reads as `'splash': 'ocean'`.
- `r05b_dupkey_push.py`, end to end: `push ok: True | questions asked: ['confirm-push']`, and the remote `p.hu` has
  both keys. Then `config set splash blocks` → `set splash = blocks (in prim)`, while `config show` still says
  `splash  plain`.
- `r05c_dupkey_same.py`: `humerge.merge: conflicts [] | text has splash once: True` → `driver rc 0 | splash:
  occurrences in the result: 2`.

**Fix:** a `hutext.duplicate_keys(text)` scan, or a strict materialize that flags repeated keys.
- In `driver`, never take git's clean text when it holds a key twice that humerge's merged data doesn't.
- When humerge found conflicts, return 1 even if git was clean, so the per-key question runs. That costs little: the
  only clean-but-conflicted cases are this one and two reorders that compose.
- Have `check` warn on a duplicate key in any layer file.

**Effort:** S. **Tier:** B.

**Verified (incidental: outside this checker's scope, hit while setting up primary-03):** CONFIRMED (reproduced)
(`c/c04_dupkey.py`).
- **No question:** the other machine sets `{ splash: ocean  picks: …`, and this machine runs `config set splash
  plain`. `plugin push` on a pty asks only `[p] Push  [n] Don't push`, with no value question.
- **Key twice:** the pushed `p.hu` is `'{ splash: ocean  picks: {…}     splash: plain\n}\n'`, and `config show` →
  `splash plain`.
- **A later edit corrupts the file:** `config set splash blocks` then edited the FIRST key. That key shares its line
  with `picks: {`, so `picks: {` was cut too, by config-layers-01's span that runs to the end of the line. The file no
  longer parses (`TOOMANYROOTS`), and `config show` lists no splash at all.

### primary-05 [MED] safety — the tag-to-branch switch bypasses `PrimaryRepo`: `plugins.sync` updates every plugin the manifest lists (locked ones included, unreported), and inside `yadm enter` it acts on the dotfiles repo
`configsys/primarygit.py:780-803`: `plugins.default_branch(ctx.runner, root)` at 783, and
`plugins.sync(ctx.runner, …, [dict(decl, ref=target)], verify_primary=…)` at 790. `plugins.sync` (plugins.py:1700) is
a transitive fixpoint, is called without `locked=`, and its transport uses `{**os.environ, …}`, with no scrub and no
BatchMode.

This is a residual of primary-06 (A4). plugins.md:587 promises that the primary's "git commands always act on the
primary, even inside a `vcsh enter` / `yadm enter` session". The switch breaks that, and two more things:
- **Locks.** A locked transitive plugin is fetched and checked out, which contradicts plugins.md:251-252.
- **No report.** Every transitive plugin's update goes unreported.
- **GIT_DIR.** With `GIT_DIR` / `GIT_WORK_TREE` set, the checkout runs in the dotfiles repository, whose work tree is
  `$HOME`. It detached that repo's HEAD. Push then wrote `ref: main` into the top config and said "prim now follows
  main here", while the primary stayed detached at the tag.

**(reproduced)**
- `r01_switch_locks.py`: `lock extra`. The plain `plugin sync` gives `locked extra` and `moved? False`. The push with
  switch=yes then gives `extra HEAD moved after push? True | ALARMING on disk: True`.
- `r12_gitdir_switch.py`: `prim now follows main here …`. Afterwards `dotfiles.git/HEAD` = a raw sha (it was
  `ref: refs/heads/main`), the config has `ref: main  primary: true`, and the primary is `(HEAD, tag: v1, main)`,
  i.e. detached.

**Fix:** do the switch with the primary's own repo: `repo.git('checkout', '--quiet', target)` (DWIM-tracking), then an
ff-only merge of `origin/<target>`, after the signature check (`plugins.unsigned_commits` takes a `dq`; move it onto
`PrimaryRepo` too). Replace `plugins.default_branch` with `repo.text('rev-parse', '--abbrev-ref', 'origin/HEAD')`.
Nothing else gets synced. Add a test that exports `GIT_DIR` during a switch and a test with a locked transitive
plugin. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced), with a wider impact than reported (`c/c05_tag_switch.py`, on a pty, answering
`[y] Yes, follow main`).
- **(a) A locked transitive plugin.** The primary is pinned to `v1`, and its manifest declares `extra`.
  `plugin lock extra`, then `plugin sync` → `locked   extra`, and its HEAD stays `extra: first`. Then `plugin push` →
  `prim now follows main here …` / `nothing to push`. Now extra's HEAD is `extra: ALARMING` (on disk: `True`), while
  the lock file still says `extra: 2026-11-08`. Nothing in the output mentions extra.
- **(b) Inside a `yadm enter` session.** The same switch, with `GIT_DIR=<dotfiles>/.git GIT_WORK_TREE=<dotfiles>`
  exported, and the primary's source `github:checker/prim`:
  - the dotfiles repo was fetched and FAST-FORWARDED: HEAD `9e87158 dot: v1` → `af49ba0 dot: v2`, and its work-tree
    `.bashrc` went from `version 1` to `version 2 (not pulled here yet)`;
  - its `remote.origin.pushurl` went from unset to `git@github.com:checker/prim.git`, so a later `yadm push` aims at
    the primary's repository;
  - the config now says `ref: main`, but the primary is still `HEAD, tag: v1`, detached.

  The reviewer's "detached that repo's HEAD" is the variant where the dotfiles repo has no `origin/main`.

MED kept. It needs a tag-pinned primary (opt-in) and a push from inside a vcsh / yadm session. Even so, it outright
breaks plugins.md's promise that the primary's git commands always act on the primary.

### primary-06 [MED] safety — `_combine` assumes "the tree was dirty" means "my stash push made an entry"; a submodule with untracked content makes `stash push` save nothing, and the pop then applies and drops YOUR older stash
`configsys/primarygit.py:1088-1092` (`stashed = True` after any successful `stash push`), and `:1267-1276`
(`_unstash` pops `stash@{0}`, whatever it is).

`git status` shows ` M sub` for a submodule with untracked content, but `git stash push -u` saves nothing there: exit
0, "No local changes to save", no entry. `_combine` still sets `stashed = True`. After the combine, `stash pop` takes
the newest entry, which is the user's own parked work. That work is applied to the combined tree and the entry is
dropped, all under a push that reports success. A plain git probe (`runs/nested/sm`) confirms the git half:
`M sub`, `rc=0`, and the stash list unchanged.

**(reproduced)** `r07b_old_stash_submodule.py`:
`stash before: 'stash@{0}: On master: my parked WIP' | dirty(): {'vendor/thing'}` → `push ok: True` →
`stash after: ''` → `parked WIP now applied to notes.txt: True`.

**Fix:** read `git rev-parse -q --verify refs/stash` before and after the push, and set `stashed = after != before`.
Better, use `git stash create` and keep the returned commit, then `stash store` / `stash apply <sha>` / `stash drop
<sha>` by identity, never by `stash@{0}`. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced) (`c/c06_stash_identity.py`).
- **git alone:** a submodule holding an untracked `doc/tags` → `status --porcelain` gives ` M sub`, and
  `stash push --include-untracked` exits 0, saves nothing and leaves the stash list empty.
- **End to end:** a vendored submodule holding `doc/tags` (what vim's `:helptags` leaves behind), plus
  `stash@{0}: On main: my parked WIP`. This machine runs `picks add fzf`, and the other machine pushes. `plugin push`
  (no terminal) → `pushed 1 change …`. Afterwards the stash is `''`, status shows ` M notes.txt` and ` M vendor/thing`,
  and the parked WIP now sits in notes.txt.
- **With no older stash:** the same push says `your uncommitted edits don't apply cleanly … kept in git's stash — …
  stash pop brings them back` after a `reset --hard`. There is nothing in the stash.

MED kept.

### primary-07 [MED] safety — Ctrl-C (or any exception) after a command wrote into the primary still commits it under the command's message, and under `primary-push: auto` then pushes it
`configsys/app.py:4919-4927` (`main`): `finally: … primarygit.commit(…)` and `if snap.committed:
_after_primary_commit(ctx)` run on every way out, `KeyboardInterrupt` included.

A long multi-write command interrupted halfway, such as `dotfiles capture` of a big dir or `plugin init`'s merge, is
committed as if it had finished. With `auto` set, configsys then performs a network push to every machine *after*
the user pressed Ctrl-C to stop it. principles.md calls that kind of outward-facing action out ("confirm
hard-to-reverse or outward-facing actions").

**(reproduced)** `r10_interrupt_autopush.py` wraps `picks` to write and then raise `KeyboardInterrupt`:
`configsys: interrupted` → `configsys: pushed 1 change to …` → `rc 130` → `remote now has fzf: True | remote log:
['picks add fzf', …]`.

**Fix:** let `main` record whether the command returned. On an exception, still commit, so the change stays undoable,
with the subject suffixed `(interrupted)` or `(failed)`. Skip `_after_primary_commit`'s push and print the "not
pushed yet" hint instead. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced) (`c/c07_ctrl_c.py`). The command is the real `picks add fzf`, wrapped only so it
keeps running after its write. The interrupt is a real SIGINT to its process group, which is what a terminal's
Ctrl-C sends.
- **Under `auto`:** `fzf picked on this-machine (in prim)` → SIGINT → `configsys: interrupted` and `configsys: pushed
  1 change …`, rc 130. The remote log is `['picks add fzf', 'config set primary-push auto', 'initial']`, and the
  remote p.hu has fzf (`True`).
- **Order of events:** the push runs in `main`'s `finally`, before `except KeyboardInterrupt` prints "interrupted".
  The captured output shows them the other way round only because stdout is block-buffered.
- **Under `ask`:** the write is committed as `picks add fzf`, with the "not pushed yet" hint, and nothing is pushed.

MED kept.

### primary-08 [MED] safety — `plugin undo` of a commit that moved files INTO the primary deletes the only copy on disk
`configsys/primarygit.py:941-989` (`undo`): `reset --keep HEAD~1` (971) or `revert` (979) reverts the tree, and
nothing knows that the commit's files were moved in from outside.

`plugin init` with an existing primary moves your local dotfiles and glue into it (`_plugin_init_merge`,
`_sweep_glue_to_primary`), and their local copies are deleted. The newest configsys commit is then `plugin init`. A
`plugin undo` (`--yes`, or the TUI `H` popup's "Undo it") drops that commit, and with it the files, which are then
left only in git's object store. The message, "it was never pushed, so it is simply gone (`reflog` still has it)", is
accurate but is not what "undo plugin init" means. The confirm lists the files but doesn't say they will be deleted
from disk. An undo of a capture whose content is linked into place (`~/.config/app` → the store) similarly leaves a
dangling link.

**(reproduced)** `r15_undo_init.py`: `moved 1 dotfile + 1 glue item(s) into "prim"` → `local copy left? False | in
primary? True` → `plugin undo` → `undid "plugin init" … simply gone` → `foo.conf anywhere on disk now: NOWHERE (only
in the reflog)`.

**Fix:** refuse to undo a commit that added files. At the least, refuse ones whose subject is a moving verb
(`plugin init`, a store move), or always confirm "this deletes N files from disk: …". Better: before dropping or
reverting, copy the files the commit added into `<state>/undo/<sha>/` and say where they went. **Effort:** M.
**Tier:** A.

**Verified:** CONFIRMED (reproduced) (`c/c08_undo_init.py`). Setup: a local `dotfiles/foo.cfs/foo.conf` and
`glue/shell/bash/user.d/mine.sh`.
- **The move:** `plugin init` → `moved 1 dotfile + 1 glue item(s) into "prim"`. The local copies are gone; the only
  copies are in the primary.
- **The confirm:** `plugin undo` on a terminal shows `undo 0773725 "plugin init" (not pushed yet)
  [dotfiles/foo.cfs/foo.conf, dotfiles/foo.cfs/manifest.hu, glue/shell/bash/user.d/mine.sh]` / `Undo it? [y/N]`.
  Nothing says the files leave the disk.
- **The undo:** answer `y` → `undid "plugin init" … simply gone (… reflog still has it)`. foo.conf and mine.sh are
  now `NOWHERE on disk`; only the reflog holds them.
- **Off a terminal:** the CLI confirms by itself (`_plugin_undo` returns True when not a tty).

MED kept.

### primary-09 [MED] correctness — a real file named `x~` (an editor backup a capture swept in) that conflicts next to `x` is read as git's type-change rename: a nonsense question, and `x~` is deleted from the pushed tree
`configsys/primarygit.py:1173-1184` (`_type_renames`: any conflicted `p` containing `~` whose `p.rsplit('~', 1)[0]` is
also conflicted, or is a folder). `:1194-1229` (`_settle_type_change` never checks that the two kinds differ, and
unlinks both names).

This is a residual of primary-26 (B17). git names its parked side `x~HEAD` / `x~<branch>`, but the test accepts any
suffix, the empty one included. Captured config dirs commonly carry `config~` backups.

**(reproduced)** `r08_tilde.py`: both machines change `config` and `config~`, and the only question asked is
`type-change | … config (1 of 1) — this machine changed the file; your other machine made it a file`. After answering,
the remote tree is `['…/app/config', 'notes.txt', 'p.hu', 'plugin.hu']`: `config~` is gone, and `config` was taken
whole from one side.

**Fix:** accept `x~<suffix>` only when the suffix is `HEAD` or the other side's label, *and* the unmerged entries show
two different kinds. Make `_settle_type_change` fall back to the ordinary `file` question when `km == kt`. Add a test
with `config` + `config~`. **Effort:** S. **Tier:** B.

### primary-10 [LOW] correctness — order-sensitive merges still mis-place NEW items: one profile term added at two points is kept twice (theirs' meaning wins), and theirs' new plugin is appended last (highest precedence) even when it was put first
`configsys/humerge.py:136-169` (`_merge_sequence`: two inserts of the same term at different points are separate
groups, so both are applied). `:254-256` (`_Merge.plugins`: `first + [s for s in second if s not in first]`).

These are residuals of primary-08 (B4) and primary-20 (B11).

**(reproduced)** `r06_order.py`:
- mine `[ +editors btop ~vim ]` ("no vim") against theirs `[ btop ~vim +editors ]` ("vim") gives
  `['+editors', 'btop', '~vim', '+editors']`. `configsys profile show` then gives `a` → `emacs, btop`,
  `b` → `btop, vim, emacs`, and `merged` → `emacs, btop, vim`;
- plugins: base `[a b]`, mine appends `x`, theirs prepends `c` → `['a', 'b', 'x', 'c']`, so `c` now overrides `a`,
  `b` and `x`.

**Fix:**
- In `_merge_sequence`, after merging, if a term inserted by one side also appears among the other side's inserts at a
  different position, return None so the question is asked.
- In `plugins()`, place each new entry next to its neighbour in its own side's list (the same anchor logic `_relist`
  uses), not at the end.

**Effort:** S. **Tier:** B.

### primary-11 [LOW] security — remote-controlled text still reaches the terminal raw: driver notes (file names, plugin source/ref) and the "settled as you chose" line
`configsys/primarygit.py:1128,1167-1169` (`f'{name}: {n}'` for each `_driver_notes` line, and `", ".join(conflicted)`).
`configsys/humerge.py:263,520` (notes carry `src`, `v["ref"]` and the `%P` path).

This is a residual of primary-17 (A5): `question()` sanitizes, but these lines are printed by `cmd_plugin push`, or
queued as TUI notes, without `_printable`. git does quote `%P`: an injection attempt through a hostile `.hu` file name
ran nothing.

**(reproduced)** `r03_path_injection.py` → `line: 'prim: a$(touch PWNED_SUBST);…\x1b]0;TITLE\x07.hu: both machines
changed it — combined key by key.'` and `line: 'prim: combined — esc\x1b[31mred.txt settled as you chose.'`, with
`PWNED files anywhere: []`. The OSC 0 sequence (which sets the window title) and the colour escape go out raw.
- **Who controls it:** anyone who can push to the primary.
- **What's new:** terminal spoofing in the very output that reports what the merge did.

**Fix:** `_printable` each driver note line and each path in `_replay`'s lines, or once in `push()` over all returned
lines. **Effort:** S. **Tier:** A.

### primary-12 [LOW] correctness — under `auto` only the push's last line is shown, so the "kept the newer" notes plugins.md promises vanish; and a combine that absorbs all of this machine's commits still asks "push 0 changes?" and reports "pushed 0 changes"
`configsys/app.py:4887` (`lines[-1]`), `configsys/tui/menu.py:744` (`lines[-1:]`), `configsys/primarygit.py:871-884`
(no "nothing left to push" check after `_combine`).

plugins.md:568 says "the newer is kept and you're told". Under auto that note isn't printed, and neither is "N files
… left out of the push". Separately, when the merge keeps theirs' change for every one of mine's commits, the rebase
drops mine's now-empty commits, so `ahead` becomes 0. push still confirms and pushes a no-op.

**(reproduced)** `r13_auto_notes.py` / `r13b_auto_notes.py`. The same plugin bump on both sides gives:
- explicit `plugin push`: `left out …`, `both machines moved plugin github:me/blender — kept the newer, v0.3.0.`,
  `… combined key by key.`, then `pushed 0 changes to …`;
- under auto, after `picks add fzf`: only `pushed 1 change to …`.

**Fix:** under auto, print (or queue) every line that isn't progress, and certainly every driver note. After
`_combine`, if `ahead == 0`, return "nothing left to push — your changes were already on the remote" before the
confirm. **Effort:** S. **Tier:** B.

### primary-13 [LOW] correctness — "Don't push" at the confirm leaves the other machine's commits combined into this checkout, and the message doesn't say so
`configsys/primarygit.py:865-874`: `_combine` runs first, then `confirm-push` is asked. A "no" returns "not pushed —
your changes stay committed here".

The user sees "what will leave" and declines, but the remote's data, glue and code are already checked out here.
That is an effective sync, done without saying so.

**(reproduced)** `r18_decline.py` → `['prim: not pushed — your changes stay committed here.']`, then `HEAD moved: True |
other machine's change now here: True`.

**Fix:** on "no", either `_restore(repo, head)` back to the pre-combine HEAD, the way stop does (keep the stash logic),
or say it: "your other machines' N changes were combined in here; `plugin undo` / `git reset --keep ORIG_HEAD` takes
that back". See the question below. **Effort:** S. **Tier:** B.

### primary-14 [LOW] feature — a `.hu` file settled in the editor (or by side) isn't checked to parse; a typo is pushed and every machine skips the file
`configsys/primarygit.py:1154-1159` (after `ui.edit`, only `_has_markers` is checked) and `:1300-1319` (`_take`'s
line-level result goes unvalidated).

**(reproduced)** `r17_broken_edit.py`: the edit leaves a brace short → `push ok: True` → `picks for this-machine (0)`.

**Fix:** for `*.hu`, `humerge._load` the result before staging. If it fails, re-offer the editor (or stop) with
humon's error message. **Effort:** S. **Tier:** G.

### primary-15 [LOW] parity — the TUI's confirm-push popup never lists the files about to leave (the CLI lists 20 commits and the files)
`configsys/tui/menu.py:672-681` (`_TuiPushUI.ask` puts at most three commit subjects into the title and never reads
`q.files`), against `configsys/app.py:2993` (`q.listing()`).

plugins.md:556 says push "lists the changes and the files about to leave". The files are what would show a freshly
captured dotfile holding a token. **(verified by reading)**

**Fix:** render `q.listing()` in the popup body (a scrollable list, or `_popup_choose` with a body), so both UIs come
from the same Question data. **Effort:** S. **Tier:** G.

### primary-16 [LOW] correctness — after `P` (or `H` → undo) the TUI keeps showing the pre-push picks and config
`configsys/tui/screens/plugins.py:379-383` (`P`: `pl.reload()` but no `ctx.invalidate()` and no `dirty = True`) and
`:65-90` (`_history` invalidates but leaves `dirty` false).

Compare `s` (sync) at :322-328, which sets `dirty = True` after `actions.plugin_sync` invalidates. A push that combined
the other machine's picks leaves Components and Profiles stale until some other action rebuilds them.
`actions.save_theme_to_primary` writes `full_snapshot(ctx.config.theme())`, so a promote after `P` would write the
stale theme back over the combined one. **(verified by reading)**

**Fix:** when `push` / `undo` moved HEAD, have the handler `ctx.invalidate()` and set `dirty = True`. `push` could
return a `moved` flag. **Effort:** S. **Tier:** B.

### primary-17 [LOW] safety — `PrimaryRepo.git(..., paths=[])` means "every path": `_commit_paths` with an empty list would stage and commit the whole tree, your hand edits included
`configsys/primarygit.py:101-110` (an empty list still adds `--pathspec-from-file=-` with empty stdin), and `:368-377`.

git treats an empty pathspec file as no pathspec. Today every caller guards against an empty list (`if not changed`,
`if hand_edited`, `if overlap`), so this is latent. `_commit_paths`' contract, "exactly `paths`", is the opposite of
what it would do.

**(reproduced at the git level)** `printf '' | git add -A --pathspec-from-file=- --pathspec-file-nul` → `M a`, `A n`
(everything staged). The same with `commit` → a commit of everything.

**Fix:** in `git()`, `if paths is not None and not paths:` return a no-op `GitResult(0, b'', b'')` or raise. Add a unit
test. **Effort:** S. **Tier:** A.

### primary-18 [LOW] correctness — `dirty()` reads a worktree rename (` R`, after `git add -N`) as two entries, inventing a path and dropping the deletion
`configsys/primarygit.py:145` checks only the index column (`entry[:1] in (b'R', b'C')`). porcelain v1 can also put
`R` in the worktree column.

Downstream, the invented name is listed in "include them?". `_commit_paths` then fails with "pathspec did not match",
so push fails.

**(reproduced)** `runs/nested/rn` (`mv orig.txt renamed.txt && git add -N renamed.txt`): porcelain gives
` R renamed.txt\0orig.txt\0`, and `PrimaryRepo('rn').dirty()` → `{'renamed.txt', 'g.txt'}`.

**Fix:** test `b'R' in entry[:2] or b'C' in entry[:2]`, or switch to `--porcelain=v2 -z`, whose records are
unambiguous. **Effort:** S. **Tier:** B.

### primary-19 [LOW] performance — `history()` spawns one `git diff-tree` per commit (undo asks for 50)
`configsys/primarygit.py:919-930`.

**(reproduced)** `r09_history_perf.py` on a 61-commit primary:
- `history(n=10): 40 ms, 14 git spawns`;
- `n=15` (the `H` popup): `50 ms`;
- `n=50` (`undo`): `142 ms, 54 git spawns`;
- `one git log --name-only -z for 50: 6 ms`.

**Fix:** a single `git log -n{n} -z --name-only --format=%x1e%H%x1f%h%x1f%as%x1f%s%x1f%P%x1f%b` and split it. That
also fixes a commit body containing `\x1e` / `\x1f` (remote-controlled), which today makes that commit vanish from the
list. **Effort:** S. **Tier:** C.

### primary-20 [LOW] feature — `plugin undo` takes back the newest configsys change from ANY machine, and its confirm doesn't say which
`configsys/primarygit.py:930` (`by_configsys` = "Made by configsys" in the body, from any machine) and `:936-938`.

After a sync, the newest "configsys change" may be the laptop's `picks add x` on its own column. Undo on the desktop
reverts it. The body names the machine (`Made by configsys on laptop.`), but neither `undoable()` nor the confirm reads
it. **(verified by reading)**

**Fix:** parse the machine from the body into `Change.machine`. Prefer this machine's newest change, or name the
machine in the confirm ("made on laptop"). **Effort:** S. **Tier:** G.

### primary-21 [LOW] feature — under `primary-verify: signed`, push doesn't warn that its outgoing commits are unsigned (your other machines will refuse them)
`configsys/primarygit.py:855-864` checks incoming signatures only.

A machine that sets `primary-verify: signed` but lacks `commit.gpgsign` publishes unsigned journal, rebased and
combine commits. Every other verifying machine then answers `unsigned` on sync. **(verified by reading)**

**Fix:** when `_verify(ctx)` is on, check `%G?` over `_outgoing`'s commits and put "N of these aren't signed — your
other machines will refuse them" into the confirm. **Effort:** S. **Tier:** G.

### primary-22 [LOW] abi — `primarygit.will_write` is documented as what a code plugin's driver must call, but isn't part of the frozen plugin surface
docs/plugins.md:510-512 tells a plugin driver to call `configsys.primarygit.will_write(path)`. It is absent from:
- the frozen list in `configsys/driver.py`'s docstring;
- `plugins.__all__` (plugins.py:60-66);
- test/test_abi_surface.py.

Grepping `~/src/configsys-*/` finds no plugin calling it yet. So the hook is plugin-facing without being frozen. A
rename would silently turn a plugin's writes into "hand edits".

**Fix:** freeze it now as a `Driver` method (`self.will_write(path)`, delegating to primarygit), add it to the
docstring's frozen list and the ABI test, and point plugins.md at that method. **Effort:** S. **Tier:** F.

### primary-23 [LOW] refactor — `push()` is one 135-line function with eight steps; make it a small session object over `PrimaryRepo`
`configsys/primarygit.py:751-884`. The steps are:
1. find the primary;
2. the pretend preview;
3. the tag switch;
4. busy and identity checks;
5. hand edits;
6. fetch + overlap + verify;
7. combine;
8. confirm + send.

Each step appends to `lines`, and several patch earlier lines (`lines[:-1]` at 846). The tag switch is the step that
escaped `PrimaryRepo` (primary-05). The lock check (primary-02) and the ignored-file check (primary-03) have no
natural home.

**Fix:** a `_PushSession(ctx, ui, repo, name, branch, upstream)` with one method per step, each returning
`ok | (False, line)`. The lock, ignored and verify checks become a `preflight()` list. Everything git-related goes
through `PrimaryRepo`, including the switch and `unsigned_commits`. This collapses primary-02, -03 and -05 into one
place and makes "what can stop a push" a readable table. **Effort:** M. **Tier:** D.

### primary-24 [NIT] comment-drift — two docstrings describe what the code doesn't do
- `configsys/humerge.py:21-27` says "only a map entry combined from both sides is written fresh". In fact
  `_rewrite` recurses into maps both sides changed and edits them in place (436-440). What is written fresh is a key
  both sides *added*, with a combined value, or one whose theirs-text can't be reused.
- `configsys/primarygit.py:1109-1110` (`_restore`) says "the tree holds nothing of yours to lose". It does: ignored
  files (primary-03).

**Fix:** reword both along with their fixes. **Effort:** S. **Tier:** E.

### primary-25 [NIT] correctness — small rough edges in the combine path
- **The merge's error is dropped.** `primarygit.py:1136-1137`: a `merge` that fails with nothing unmerged returns
  `(False, [])` without `_err(merged)`, so the user sees only `_intact`.
- **Per-key answers can be asked twice.** `:1256-1259`: when the *answered* rewrite raises (a quoted key, say), the
  per-key answers are discarded and the whole file is asked again. Probe the rewrite with all-`mine` answers before
  asking.
- **Mixed line endings.** `:1262` writes `res.text` as is. `driver` normalizes CRLF, but this path leaves inserted LF
  lines in a CRLF file.
- **A stale count.** `:820-822` / `:850-853`: the "N files … left out of the push" line stays when the overlap
  question then includes some of them.
- **`GIT_SSH` is overridden.** `:97-98`: `network_env` sets `GIT_SSH_COMMAND`, which overrides a user's `GIT_SSH`. git's
  order is `GIT_SSH_COMMAND` > `core.sshCommand` > `GIT_SSH`.
- **Editor work is discarded silently.** Stop after editing file 1 of 2 discards the editor resolution without saying so.

**Effort:** S. **Tier:** B.

### primary-26 [NIT] naming — look-alike helpers with different contracts
- `humerge._skip` is `hutext.skip_blank`, which does not skip strings, while `plugins._skip_trivia` does.
- `humerge._emit_kv(k, v, indent, top)` and `plugins._emit_kv(key, value, indent)` share a name but not a contract.

**Fix:** import `skip_blank` under its own name, and rename humerge's `_emit_kv` → `_emit_entry`. **Effort:** S.
**Tier:** D.

## Test gaps
Against the eight test files above (all 146 pass):
1. **Hostile list content (primary-01).** No test has a metatag, or any zero-width token, inside a list that both sides
   change. Add one with a time limit.
2. **Duplicate keys (primary-04).** No test of the driver against a git line merge that duplicates a key, for both the
   conflicting-value and the same-value case.
3. **Locks.** Nothing checks that `push` respects a locked primary (primary-02), or that the tag switch leaves locked
   and unrelated transitive plugins alone (primary-05).
4. **The switch and `GIT_DIR`.** `test_an_ambient_git_dir_never_redirects_the_primary` covers snapshot, commit and
   state only, not the tag switch (primary-05).
5. **Ignored files.** No test covers an ignored file at a path the remote now tracks, on stop or on continue
   (primary-03).
6. **The stash entry.** Nothing checks that `_combine` pops only its own entry: an older user stash plus a dirtiness
   `stash push` can't save (primary-06).
7. **`x~` names.** No conflicted `name~` file next to `name` (primary-09).
8. **Undo.** No undo of a commit that added files (`plugin init`'s merge, primary-08), and no undo when the newest
   configsys commit came from another machine (primary-20).
9. **Interrupted commands.** No CLI command interrupted after a write, under `auto` (primary-07).
10. **Printed lines.** No test that driver notes and "settled" lines are printable (primary-11).
11. **Auto-mode output.** No test of what auto mode prints (notes kept), and none of the "pushed 0 changes" path
    (primary-12).
12. **Declining the confirm** after a combine (primary-13), and **an edited `.hu` that no longer parses** (primary-14).
13. **The TUI confirm** popup's content (files), primary-15. `test_every_question_renders_the_same_choices_on_both_uis`
    checks the choices, not the listing.
14. **Carried from 2026-11 and still open:**
    - the verify-by-reread guard actually firing (monkeypatch `_rewrite` to drop a key);
    - `_remove` of a key with a trailing comment;
    - quoted keys;
    - `GIT_SSH`.
15. **The pretend sweep.** test/test_pretend_sweep.py still has no blessed git primary: `plugin push` / `plugin undo`
    there stop at "no primary". `test_pretend_push_lists_what_would_leave` and `test_undo_under_pretend_changes_nothing`
    check HEAD, not that the clone and home are byte-identical.
16. **`dirty()` parsing** of a worktree rename, and `git(paths=[])` (primary-17, -18).

## Dead code
Grepped `configsys/`, `test/`, `examples/`, `~/src/configsys-*/` and the frozen list in `configsys/driver.py`:
- **`humerge.Conflict.base`** is still stored and never read (no reader in configsys, the tests or any plugin repo).
  It is harmless data for a "what it was" UI. Keep it, or show it in the `value` question ("it was `ocean`").
- **`primarygit.PUSH_MODES`** is an alias of `layers.SETTING_CHOICES['primary-push']`, read only by
  `test_every_push_mode_has_a_policy`. Keep it or point the test at `layers`, either is fine.
- **`Question.detail` / `ref` / `branch` / `path` / `index` / `count`** are read only by tests. Their docstring says so
  ("for a UI or a test that wants them"). Not dead.
- No other unused names. Checked: `GitResult`, `PrimaryRepo.unmerged_entries` / `incoming` / `in_progress` / `has_ref`,
  `Snapshot.*`, `_names`, `glyphs`, `chip`, `describe`, `history`, `undoable`, `Change.*`, `merge_data`,
  `Result.merged`, `_as_sets` and `_note`. All have live callers.

## ABI / interface candidates
- **`will_write` as a frozen `Driver` method** (primary-22). This is the one plugin-facing name in this area.
- **`Question`** is internal, but the TUI renders only part of it (primary-15). Give it a `view()` (title, body lines,
  choices) that both UIs draw from, so the next field can't be dropped by one UI.
- **`push()`** could return something richer than `(ok, lines)`, e.g. `PushResult(ok, lines, moved_head: bool,
  notes)`. That lets the TUI invalidate after a combine (primary-16) and lets auto mode keep notes apart from
  progress (primary-12).

## Questions for the user
1. **A locked primary (primary-02):** should `plugin push` refuse to combine while locked (pushing only when it isn't
   behind), or should `plugin lock` refuse the primary and point at `primary-verify: signed`?
2. **Ignored files the remote now tracks (primary-03):** stop and ask, like overlapping hand edits, or move yours
   aside to `X.pre-configsys` and say so?
3. **Undo of a commit that moved content in (primary-08):** refuse it, or save the files to `<state>/undo/<sha>/` first?
4. **Undo scope (primary-20):** should `plugin undo` only take back changes made on this machine?
5. **"Don't push" after a combine (primary-13):** put HEAD back as it was ("nothing changed", like Stop), or keep the
   combine and say so?
6. **Duplicate keys (primary-04):** should `check` / `!` flag a key that appears twice in any layer file? humon accepts
   it silently; readers take the last occurrence and configsys's writers edit the first.

## Refuted on verification
None. All eight findings the checker re-ran were confirmed: primary-01, -02, -03, -05, -06, -07 and -08 (the
mandated set), plus primary-04 (incidental).
