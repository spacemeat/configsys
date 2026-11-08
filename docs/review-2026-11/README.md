# configsys code review — 2026-11-07

Baseline: `c25bb0a` · reviewers: opus, effort xhigh; checker: opus, effort max
Areas: 1 (`primary` — configsys/primarygit.py, configsys/humerge.py; a calibration run of `/review-code`:
`--areas primary --no-os --no-components --no-docs`) · not reviewed: the other 15 areas (out of scope)
Health at baseline: 2219 tests passed (448 s; the same tree, run just before `c25bb0a` was committed);
`check` 0 errors / 1 warning (this host's python 3.10) on pop_os!, fedora, arch, alpine, opensuse,
rhel, fedora_atomic, void, void_musl (sandbox home); docaudit 0 findings
Findings: 0 CRITICAL · 6 HIGH · 8 MED · 17 LOW · 3 NIT (after verification: 6 checked, 6 confirmed,
0 plausible, 0 refuted; primary-01 CRITICAL → HIGH) · OS releases / components: not run

**Status:** 14/37 items done (+ B1 in part), 0 declined, 22 open.

The primary-push code (built 2026-10, phases 1–4) works on its tested paths — all 58 of its tests pass —
but a review finds the failure paths are where it is weakest. `_combine` has five hand-written abort paths
and no single way to undo; none runs on an exception or Ctrl-C, and none considers the hand edits that
`--autostash` re-applies. The git layer is shell strings over `bash -c` with strict decoding and the ambient
environment, which produces five separate bugs. The merge driver ran as an ordinary Python process inside
the checkout (fixed during the review). And which edits get committed is inferred from `git status`
differences around an action rather than recorded at the writers, which both misses real writes and sweeps
in yours.

The brief (the user's words, given to every reviewer):

> Let's do a thorough and complete code review. *Take your time.* I think you know in general what good
> quality code looks like, but focus on:
> - Code reuse, where it makes sense.
> - Data-driven presentations. Think MVVM-style stacks, which could use real or mock data.
> - Good linting. Many of the comments are for your own future edification, so don't feel the need to erase
>   them, but ensure any comments are up-to-date with the code.
> - Good, human-readable variable names.
> - Don't be bashful about looking for performance enhancements. Examine how often a computation is
>   performed in inner loops, and whether caching or memoizing makes sense. Remember too that this is
>   python, and it is in general slow and mostly single-threaded.
> - Don't be bashful about adding tests. *Do* be bashful about removing tests, unless there is no codepath
>   they cover. Adding tests is great.
> - Look for dead code. We've made lots of changes over the development. There may be straggling bits. Do
>   bear in mind that this is a plugin architecture, so some parts may be called from the outside,
>   especially in plugins.
> - Be judicious about security. We're evaluating script in some places, and doing other things that make
>   the security question vague--the trust model for plugins is great, but what else might slip in?
>   Besides the usual supply chain attacks any user of, say, flatpak might encounter anyway.
> - Feel free to make suggestions about broader refactors. If an overhaul is worthy, I'd like to consider
>   it. We've been iterating a long time.
> - If there's any features missing in your mind, call them out. If there's any imparity between CLI and
>   TUI, call them out. *Most* things CLI can do *should* be elevated to TUI as well, but not necessarily
>   all.
> - I remain the only user (but not for long). If an ABI or major interface ought to change, so be it.
>   Let's tackle that now, before we break anybody.
> - Synchronize all public docs (README.md and anything it links to), man pages, etc. to current
>   functionality. Look for outdated terms or language, and aim to reduce new terms and to be consistent
>   with terms like component, driver and via, dotfiles vs. glue.

The detail for every item — file:line, the reproduction, the proposed fix — is in [primary.md](primary.md).

## Progress (updated as work lands)
- A1 (primary-01): the `.hu` merge driver runs isolated (`python -I -c`), so code committed to the
  primary can't shadow its imports — `34d6a20`.
- A4, B2, B6, primary-18, D1 part 1: `PrimaryRepo` — argv, bytes, literal pathspecs on stdin, a scrubbed
  env, your ssh command kept — `efa9c38`.
- A2, A3, D1 part 2: one undoable combine (stash, replay, restore on any non-success exit incl.
  Ctrl-C), overlapping hand edits asked about first, a primary mid-merge refused — `da323ea`.
- B1 (immediate part): `select` is bracketed, so Config/Theme space edits commit; decision 1:
  configsys's own commits skip hooks — `f5e0340`. (B1's durable fix, the write journal, has its own
  plan: docs/todo/primary-journal-plan.md, awaiting go.)
- B7, B8, B16, B18: auto quit asks nothing; a never-pushed primary shows as not pushed; a Markdown
  underline isn't a conflict; the combine's scratch copies are removed and notes printed once — `e03afa8`.
- A5, B12, B13: remote text made safe in every question; settings numbered within a file (and "show me
  the file" says it sets earlier answers aside); git failures matched by a rules table, host-aware —
  batch 2.

## 0. Fixed during the review
- **primary-01** — reported CRITICAL, confirmed by the lead (a planted `subprocess.py` ran inside the
  driver), fixed with the user's go-ahead in `34d6a20` before the rest of the review; the checker
  re-confirmed the fix and moved it to HIGH (see A1).

## 1. The earlier review
Nothing to carry over: primarygit.py and humerge.py are new since docs/review-2026-09/.

## 2. Cross-cutting themes
Within the one area reviewed (the cross-area patterns need the other reviewers):
- **No transaction around `_combine`** (primary-02, -03, -14): one context manager that records HEAD and
  the stash and restores on any exit that isn't a commit closes the whole class.
- **The git layer as shell strings** (primary-05, -06, -10, -18): argv lists, bytes → fsdecode,
  `--literal-pathspecs` / `--pathspec-from-file`, a scrubbed env — one `PrimaryRepo` helper (D1).
- **The driver promises "never worse than git's merge" and isn't** (primary-08, -09, -16).
- **Commits inferred, not recorded** (primary-04, -07, -13): a write journal at the writers would replace
  the action allowlist and most of the per-keypress cost (decision 2).
- **A lead for the plugins / dotfiles-glue reviewers** (from the checker): a user-glue snippet stored in the
  primary (`glue add`) is linked into `conf.d` and follows the remote's content after a plain `plugin sync`
  with no trust step — so "whoever can push to your primary runs code as you" was already true before
  primary-01. docs/plugins.md §6 says a primary's glue needs trust. Not reviewed here.

## 3. Act-on-these, ranked

### Tier A — security + safety
- **A1 [HIGH] The merge driver imported code from the primary's checkout.** Git runs the driver from the
  work tree and `python -m` puts it first on `sys.path`. (primary-01) · effort S · [done 34d6a20]
- **A2 [HIGH] `_combine` isn't exception-safe.** Ctrl-C at a prompt, a binary conflict or a malformed
  `plugins:` entry leaves the primary mid-merge with your hand edits stashed, and the CLI then stages the
  conflict-marked file. Fix: a transaction (record HEAD + stash, restore on any non-commit exit) — the core of
  D1. (primary-02) · effort M · [done da323ea]
- **A3 [HIGH] Overlapping hand edits become conflict markers while push reports success.** On the rebase
  (`--autostash`) and merge (`_unstash`) paths; a conflicted `.hu` data file is then skipped at load, so your
  picks silently disappear (only `inspect` / `!` say so). Fix depends on decision 3. (primary-03) · effort M ·
  [done da323ea]
- **A4 [HIGH] Ambient `GIT_DIR` / `GIT_WORK_TREE` redirect every primary git call.** In a vcsh / yadm session:
  pushes the dotfiles repo's commits as "the primary's", and a conflict there stashes every untracked file in
  your home. Fix: scrub `GIT_*` from the env of every primary git call. (primary-06) · effort S · [done efa9c38]
- **A5 [LOW] Remote text goes raw into conflict prompts** — terminal escapes can spoof the question. Fix:
  sanitize control characters in every UI string built from file content. (primary-17) · effort S · [done — small fixes, batch 2]

### Tier B — correctness
- **B1 [HIGH] Config and Theme `space` edits are written to the primary but never committed**, and from then
  on configsys treats the file as your hand edit. (primary-04) · effort S · [partly done f5e0340 — the journal: docs/todo/primary-journal-plan.md]
- **B2 [HIGH] The snapshot/commit bracket isn't best-effort.** One uncommitted non-UTF-8 file name crashes
  every CLI command (`check`, `picks list`, `inspect`); a 2000-file `dotfiles capture` overflows the command
  line. (primary-05; with primary-18, paths as globs) · effort M · [done efa9c38]
- **B3 [MED] Your edits made during a long action are committed under configsys's message** (and pushed
  under `auto`). (primary-07; decision 2) · effort M · [open]
- **B4 [MED] Profile term lists are merged as sets**, though their order matters — and the driver replaces
  git's clean, order-correct result with the reordered one. (primary-08; decision 5) · effort S · [open]
- **B5 [MED] The merge drops comments** in combined lists, and takes one side's whole text when the result
  equals it. (primary-09) · effort M · [open]
- **B6 [MED] The non-interactive ssh setup is wrong both ways**: push's `GIT_SSH_COMMAND` overrides your
  `core.sshCommand`; the background fetch has no `BatchMode`. (primary-10) · effort S · [done efa9c38]
- **B7 [MED] Under `auto` / `auto-on-quit`, quitting the TUI can still pop push questions**, though the docs
  say nothing is asked. (primary-11) · effort S · [done e03afa8]
- **B8 [LOW] A never-pushed primary is invisible** — no "not pushed yet" line, chip or quit prompt.
  (primary-15) · S · [done e03afa8]
- **B9 [LOW] The driver's "git's own result" isn't** — temp-file labels, CRLF → LF, a NUL truncates, invalid
  UTF-8 crashes it. (primary-16) · S · [open]
- **B10 [LOW] Backtick strings and `\` trip humerge's scanner** → a whole-file question. (primary-19) · S ·
  [open]
- **B11 [LOW] `plugins:` merged in mine's order** — theirs' reorder (layer precedence) is lost; a duplicate
  source collapses. (primary-20) · S · [open]
- **B12 [LOW] Per-key questions are numbered by file; "show me the file" discards answers already given.**
  (primary-21) · S · [done — small fixes, batch 2]
- **B13 [LOW] `explain_git_failure` calls an HTTPS 403 "offline?" and gives GitHub fixes for GitLab.**
  (primary-22) · S · [done — small fixes, batch 2]
- **B14 [LOW] The tag-to-branch switch writes `ref:` before the checkout** — half applied when refused.
  (primary-23) · S · [open]
- **B15 [LOW] The "no git identity" note is wrong for env identities; `user.name` is never checked.**
  (primary-24) · S · [open]
- **B16 [LOW] A Markdown `=======` underline reads as an unresolved conflict.** (primary-25) · S · [done e03afa8]
- **B17 [LOW] Type-change conflicts are misdescribed; "keep this machine's" pushes `<path>~HEAD`.**
  (primary-26) · M · [open]
- **B18 [NIT] Repeated notes, leftover scratch copies, `.git` assumed to be a directory.** (primary-34) · S ·
  [done e03afa8]
- **B19 [LOW] Commits name the hostname and fall back to a `<login>@<host>` identity** — use the configsys
  machine name; with no git identity, say so and don't commit. (decision 4; primary-24) · S · [open]

### Tier C — performance
- **C1 [MED] Every non-navigation TUI keypress costs 6 git spawns, 2 config parses, ~23 ms** (63 ms with 500
  untracked files), mostly recomputing a state nothing changed. Largely dissolved by decision 2's journal.
  (primary-13) · effort M · [open]

### Tier D — refactors
- **D1 [MED] A `PrimaryRepo` git helper + a transactional combine.** argv lists, bytes → fsdecode, literal
  pathspecs / pathspec-from-file, scrubbed env, one restore-on-exit transaction. Collapses A2, A4, B2, B6 and
  primary-18 into one place. (primary-14) · effort M · [done efa9c38, da323ea]
- **D2 [LOW] One source for push modes, choices and commit logic** — `PUSH_MODES` is defined and never read
  (`Config.primary_push` hard-codes the tuple), the choice/commit/branch/error logic is hand-copied, and
  `primary-push` values go unvalidated; hold the mode policy, chip and failure wording as data.
  (primary-27, -28) · effort S · [open]
- **D3 [LOW] One shared module for humon text surgery** (humerge's span helpers and plugins.py's).
  (primary-29) · effort M · [open]
- **D4 [NIT] Naming: `mine` means two things in one module; single-letter git results.** (primary-33) · S ·
  [open]

### Tier E — docs vs code
- **E1 [NIT] Docstrings that describe what the code no longer does.** (primary-32) · S · [open]

### Tier F — interfaces (none plugin-facing; neither module is in the frozen ABI)
- **F1 `PushUI` as one `ask(Question) -> answer`**, with kind, sanitized text, file/key index and count, and
  the allowed answers from a shared table — CLI and TUI render the same data, tests script it; fixes B12's
  numbering and carries A5's sanitizing. · effort M · [open]
- **F2 `primarygit.state()` as a `PrimaryState` dataclass** (with `first_push`, fixing B8). · effort S · [open]
- **F3 `humerge.main(argv)`** so the isolated entry point (A1) and the tests share it. · effort S · [open]

### Tier G — features + parity
- **G1 [MED] `plugin push` gives no preview of what will leave the machine**, and `--pretend plugin push` says
  nothing useful. (primary-12; decision 6) · effort M · [open]
- **G2 [LOW] No way to see or undo configsys's commits from configsys.** (primary-30) · effort M · [open]
- **G3 [LOW] The CLI `plugin list` never fetches the primary**, so it can't show `↓` the way the TUI does.
  (primary-31) · effort S · [open]
- **G4 [MED] Verify primary commit signatures on sync** (an opt-in setting): `plugin sync` refuses primary
  commits not signed by your key(s), closing "whoever can push to your primary runs code as you" (the
  shape behind A1 and the glue lead in §2). Useful once you sign (decision 1). Added from the decisions;
  not a reviewer finding. · effort M · [open]

## 4. Test gaps
None of the 58 primary tests covers any of the six HIGH findings. The full list (13 groups) is in
[primary.md § Test gaps](primary.md#test-gaps); the ones that pay most: an exception-safety test for
`_combine` (a `Scripted(raise_on=…)` UI), overlapping hand edits on both paths, non-UTF-8 names and huge
path lists in the bracket, a test that every TUI write action is bracketed, `GIT_*` env isolation, and
the pretend sweep with a real git primary (it currently stops at "you have no primary plugin"). The driver
isolation test landed with A1.

## 5. OS releases and the catalog
Not run in this calibration (`--no-os --no-components`).

## 6. Suggested sequencing
1. **A4** (S) — the scrubbed env, now; it is the cheapest HIGH.
2. **D1** — build `PrimaryRepo` + the transaction, which IS the fix for **A2**, **B2**, **B6** and primary-18,
   with **A3**'s refuse-and-ask (decision 3) inside it.
3. **B1**, **B7**, **A5** — small and user-visible.
4. Decision 2 (write journal) → **B3** + **C1** together.
5. The humerge items (**B4**, **B5**, **B9**–**B11**) with **D3**.
6. **F1** with **B12**; **G1** with decision 6.

## 7. Decisions (the user, 2026-11-07)
1. **Hooks and signing:** configsys's own auto-commits skip hooks (`--no-verify`) but follow your signing
   setting, so they're signed whenever you sign (and a future signature check, G4, covers them).
2. **Commit by write journal:** each configsys writer to the primary records the path it wrote, and
   `commit()` commits exactly those — no action allowlist, no sweep-in of concurrent edits (B3), most of
   the per-keypress cost gone (C1); B1 becomes "the Config/Theme writers journal their writes".
3. **Overlapping hand edits (A3): refuse and ask** — detect the overlap before combining and ask "include
   your edits in this push, or stop"; nothing is left half-applied.
4. **Machine name, not hostname:** commit bodies say "Made by configsys on <machine>" (the configsys
   machine name, your picks column); `<login>@<host>` is never used as an identity — with no git identity,
   configsys says so and doesn't commit. (New item B19.)
5. **Profiles (B4): an order-preserving merge** — both sides' additions and removals, each term kept in
   place relative to its neighbors; asked only when both sides reorder the same terms differently.
6. **Confirm before `plugin push` (G1)** on a terminal: list the outgoing commits and files and ask;
   `--yes` skips it; `auto` / `auto-on-quit` stay silent; `--pretend` shows the same list.

## 8. Calibration notes (this run tuned `/review-code`)
- One reviewer (opus xhigh: ~33 min, 116 tool calls) and one checker (opus max: ~25 min, 96 tool calls)
  on ~1k lines produced 34 findings; the checker refuted none of the six serious ones and corrected the
  scope of two (primary-05, -06).
- The checker's severity call (CRITICAL → HIGH: a pusher to your primary could already run code through its
  linked glue) is the kind of threat-model anchoring the reviewer brief should ask for up front: "what could
  this attacker already do without the bug?"
- The CRITICAL interrupt worked as written: confirmed by the lead in one script, fixed with a go-ahead,
  re-verified by the checker against both the baseline and the fix.
