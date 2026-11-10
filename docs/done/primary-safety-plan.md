# Primary push: a safe git layer, an undoable combine, a write journal

> **Status: DONE** — finished 2026-11-07 (0c62c22). Phases 1 (efa9c38), 2 (da323ea), 4 (e03afa8,
> fd0e94f, ab5c941) and 5 (a4e5132, 3e8be8a, 17643aa, 0aa1606, 0c62c22) shipped; phase 3 was split
> out to docs/done/primary-journal-plan.md (its decision-1 part shipped, f5e0340).
> Lives on in: docs/plugins.md §8 (publishing your primary) and §8a (primarygit / humerge / hutext).

The review of `configsys/primarygit.py` and `configsys/humerge.py` (docs/review-2026-11/primary.md)
found that the push works on its tested paths and fails badly off them: an interrupted or failed combine
leaves the primary half-merged with your edits stashed, overlapping hand edits become conflict markers
while push reports success, the ambient git environment can redirect every call to another repository,
one non-UTF-8 file name crashes every command, and which edits get committed is guessed from `git
status` around an action. Decisions are in the review's §7.

## Phases

1. **`PrimaryRepo`: one safe way to run git on the primary** (D1 part 1; fixes A4, B2, B6, primary-18).
   argv lists (no `bash -c`), bytes in and `os.fsdecode` out, `--literal-pathspecs`, path lists through
   `--pathspec-from-file=- --pathspec-file-nul` on stdin, an env with git's repository-locating variables
   removed (`git rev-parse --local-env-vars`), and one non-interactive network env that keeps your
   `core.sshCommand` and adds `-o BatchMode=yes` (fetch and push alike, both through the push URL). The
   snapshot/commit bracket and `state()` become best-effort: they never raise.
2. **An undoable combine** (D1 part 2; fixes A2, A3). Refuse to start while the primary is mid-merge or
   mid-rebase. Before combining, find hand edits that overlap what came in and ask "include them in this
   push, or stop" (decision 3). Then one transaction: record HEAD, stash the remaining edits explicitly (no
   `--autostash`), rebase or merge, and on ANY exit that isn't a commit — a stop, a failure, an exception,
   Ctrl-C — abort, restore HEAD and pop the stash, then re-raise. `_settle_hu` falls back to the per-file
   question on any humerge error; a binary conflict is settled by side, never decoded.
3. **The write journal** — split out to its own plan, docs/done/primary-journal-plan.md (it reaches the
   dotfiles and glue writers). Done here: B1's immediate fix and decision 1 (f5e0340). Originally:
   (B1, B3, C1; decisions 1 and 2). Each configsys writer to the primary records the
   path it wrote; `commit()` commits exactly those (no action allowlist, no sweep-in of edits you make
   meanwhile, far fewer git spawns per keypress). configsys's commits pass `--no-verify` and follow your
   signing setting.
4. **The small fixes** — B7, A5, B19, B8, B12–B16, B18 (the review's Tier A/B LOW items).
5. **Merge quality and the push preview** — B4 (order-preserving profile merge, decision 5), B5, B9–B11,
   D3, G1 (list what leaves and confirm on a terminal, decision 6).

Each item lands test-first with its own commit, and its status tag in docs/review-2026-11/README.md.
