# Publishing your primary plugin — commit, push, and conflicts without git expertise

> **Status: IN PROGRESS** — phases 0 and 1 done (2026-10-21); phases 2–4 not started. Tag-pinned primaries
> stay supported (decided 2026-10-21).

## Why

configsys edits the primary plugin in place: `picks add`, a uniform setting, `dotfiles capture`,
`glue add`, `plugin add` / `update` (a transitive plugin's entry and ref), `picks to-primary`,
`config move`. Today it never commits any of it. It prints "commit + push + re-tag … and bump its
ref" and leaves the rest to you. That's a git chore after every change, and it gets harder as
configsys reaches people who don't know git. When two machines both changed the primary, the
person is left with a rebase conflict in a file format they've never seen.

Goal: the primary stays in step across your machines with one obvious action, and a conflict reads
as a plain question ("this machine says X, your other one says Y"), never as a raw git state.

## The ground rule: a primary follows a branch

**A primary plugin follows a branch (normally `main`) and is never version-tagged. That's the
default, and it's always supported.** Every edit is committed on that branch and pushed to it, and
your other machines pick it up on their next `plugin sync`. No tags, no re-tagging, no ref bumps.
This is how primaries are meant to be used. Changes come too often for tagging to be worth it.

Consequences, all deliberate:

- **`plugin init` and `plugin bless` record the branch** (`ref: main`, or whatever the repo's
  default branch is). A primary with no `ref:` is treated as following its remote's default branch.
- **Sync keeps the primary attached to its branch.** It never detaches the primary, and it never
  runs `--force` against a primary.
- **`plugin update [--latest]` / `U` never move a primary off its branch.** A primary already
  follows its branch, so update just re-syncs it. Today `--latest` takes the newest version tag
  whenever one exists, so one stray `v1.0` tag would re-pin your primary to it. The `latest_ref`
  rule stays as it is for other plugins.
- **Tag-pinned primaries are tolerated, not encouraged.** If someone deliberately pins their
  primary to a tag, sync honours it (frozen at that tag) but still never discards edits
  (phase 0). `plugin push` explains that a tag pins your other machines in place and offers once
  to switch the declaration to the branch. It never re-tags for you.
- **Transitive plugins keep their tags.** Plugins your primary pulls in (`configsys-blender @v0.1.16`)
  are someone's releases, and pinning them to tags is right. Bumping one is just a primary edit
  (its ref changes in the primary's manifest), so it gets committed and pushed like any other.

## Phase 0 — make sync safe for a primary (bug fixes, needed regardless) — DONE 2026-10-21

Built: `plugins._git_checkout` never forces (a blocked checkout → `kept`), reports `diverged` /
`ahead` (`_ahead_behind`), won't strand commits on a detached HEAD (`_orphan_commits`), and with
`follow_default` (sync passes it for a primary) keeps a no-ref primary on its default branch;
`plugins.sync_note` words each outcome (CLI `_print_sync`, the TUI sync note); `branch_state` /
`follows_branch` / `default_branch` helpers; `bless` syncs as a primary and records the branch,
`init` records `ref: main`; `actions.plugin_update` keeps a branch-following primary on its branch
under `--latest`. Tests: test/test_primary_sync_safety.py. Note: the fix applies to every plugin,
not only the primary — no sync forces a checkout any more.

1. **Never discard uncommitted primary edits.**
   - **Today:** a primary with a tag ref or no ref is checked out with
     `git checkout --force --detach`, which silently discards uncommitted edits to tracked files.
   - **Fix:** a primary (or any locally edited plugin) with uncommitted changes is never
     force-checked-out. Sync reports "configsys-user has unsaved changes — not updated (`plugin
     push` saves and publishes them)" and leaves it alone.
2. **Say so when the primary diverged.**
   - **Today:** on a branch, sync runs `merge --ff-only`, which quietly does nothing once the
     branch has both local and remote commits. That machine then stops receiving your other
     machines' changes, with no message.
   - **Fix:** sync detects ahead / behind / diverged and says so ("configsys-user: 2 local changes
     and 3 from your other machines — `plugin push` combines them").
3. **No-ref primary = its default branch, attached.** Covers primaries `plugin init` made before
   it records `ref:`.
4. **`plugin update` / `U` never re-pin a primary to a tag** (see the ground rule).

Tests: a sandbox primary with a dirty tree survives `sync` under each ref kind. Diverged, ahead and
behind each produce their message. `update --latest` on a primary whose repo has a `v1.0` tag
keeps `ref: main`.

## Phase 1 — commit every configsys edit to the primary, locally — DONE 2026-10-21

Built differently from the sketch below, more robustly: instead of wiring a commit into each writer,
`configsys/primarygit.py` brackets every CLI command (`app.main`) and every non-navigation TUI action
(the router, `menu._commit_primary_action`; navigation keys are `menu._NO_WRITE_ACTIONS`). `snapshot()`
records the primary's dirty paths (and hashes them); `commit()` commits exactly the paths that became
dirty in between, so every writer — present and future — is covered with no per-writer code. A file
that was already dirty and that configsys changed further is left uncommitted with a note. Messages:
the CLI command as typed minus global flags (`app._command_words`, `--machine` kept as a suffix), or
`<screen>: <action label> — <note>`; body `Made by configsys on <host>.`. Not done: squashing a TUI
batch into one commit (each action commits on its own). Tests: test/test_primary_autocommit.py.

### The original sketch

Every writer that lands in the primary commits right after its write, with a message saying what
changed: `picks: add btop to laptop`, `setting: splash = plain`, `dotfiles: capture btop`,
`glue: add mine (bash)`, `plugins: configsys-blender v0.1.16 → v0.1.17`.

- **Where the writers are:** they already route through a few places (`actions._writable_primary_file`,
  `plugins.set_section` / `set_declared` / `set_picks` / … called with the primary's file, the
  dotfiles driver's `capture` / `relocate`, the glue driver's user.d writers,
  `actions.move_picks_to_primary`, `save_theme_to_primary`).
- **A small helper,** `primary.commit(ctx, message)`, makes the commit:
  - It runs `ensure_branch` first and commits only the paths it just wrote (`git add -- <paths>`),
    so a hand edit you're in the middle of stays yours to commit.
  - A TUI batch that edits the primary several times may squash into one commit at the end of the
    batch.
- **Never under `--pretend`:** the pretend sweep (`test/test_pretend_sweep.py`) covers it.
- **Missing git identity:** if `user.name` / `user.email` aren't set, commit with a local fallback
  identity scoped to that repo (`configsys <user@host>`), and say so once.
- **Edits you made by hand:** configsys doesn't commit them, but the indicator shows them (●) and
  `plugin push` offers to include them.
- Replaces the "commit + push + re-tag … bump its ref" messages with "saved to configsys-user —
  push to share (`plugin push`)".

Why commit locally at all: commits are local, instant and undoable, and they're what makes
conflicts manageable. git can replay commits onto another machine's changes, but it can't replay
uncommitted edits.

## Phase 2 — show where the primary stands

- **Plugins screen, primary row:**
  - `↑N` — N commits not pushed yet.
  - `↓N` — N commits on the remote, which `sync` brings in.
  - `↕` — both (push combines them).
  - `●` — edits not committed yet.
  - The counts come from a background `git fetch` of the primary, on the thread that already
    resolves remote-refs, and read against `origin/<branch>`.
- **A header chip** (like the reboot advisory) when the primary has something to push, shown when
  `primary-push` is `ask` or `manual`.
- **`plugin list`** prints the same state in words ("2 changes not pushed; 1 change from another
  machine not synced").
- `?` page and docs/plugins.md explain the glyphs.

## Phase 3 — `configsys plugin push` (and the TUI key)

A separate command, not part of `sync`. `sync` only brings things in; it's safe to run anytime and
safe in scripts, and it must not fail because of a push problem. Steps:

1. Commit any configsys-made changes still uncommitted. Edits you made yourself are listed, and
   you're asked whether to include them.
2. Fetch, then replay your commits on top of the remote's (`git pull --rebase` in effect).
3. Push to the branch.
4. Report: "Pushed 3 changes to github:you/configsys-user. Your other machines get them on their
   next `plugin sync`."

**Conflicts** (phase 3 ships the general fallback; phase 4 makes most of them disappear):

- If the replay stops on a conflict, configsys backs it out completely (`rebase --abort`). You're
  never left in a half-rebased repo.
- Then ask per file: **keep this machine's / keep the other machine's / open both in my editor**
  (an editor or mergetool for people who want it). After the choices, it redoes the replay and the
  push.
- Anything configsys can't settle ends with your work intact and committed, plus a one-line note
  on how to finish by hand.

**Credentials and remotes:**

- A refused push gets a plain explanation and fix: "GitHub refused the push — sign in with `gh auth
  login`" (and `gh auth setup-git` when gh is present), or "set up an SSH key". The ssh push URL
  configsys sets for `github:`/`gitlab:` sources (`_set_push_remote`) stays.
- **No remote yet** (a primary `plugin init` made from local files): explain, and point at
  `plugin set-source <name> github:you/<name>` once the repo exists.
- **Tag-pinned primary:** the explanation and one-time offer from the ground rule.

**When it runs** — a setting, `primary-push: ask | auto | manual` (uniform nature, so it travels in
the primary):

- **`ask`** (default) — when you quit the TUI with changes not pushed, a small prompt: "3 changes
  to configsys-user aren't pushed. Push now / Later." It never blocks quitting, and Esc means
  Later.
- **`auto`** — push at the end of a TUI batch and on quit; the CLI pushes after each command that
  edited the primary. A failure (offline, credentials) is a one-line note, retried at the next
  trigger.
- **`manual`** — only the indicator and chip.
- **Plugins screen:** `P` pushes the primary.

Pushing is outward-facing, so `auto` is opt-in and `ask` is the default ("no surprises"). Nothing
is pushed under `--pretend`.

## Phase 4 — a `.hu`-aware merge

Most primary conflicts are in configsys's own files (the primary's `configsys.hu`, `plugin.hu`),
and most of those aren't real disagreements. The common case: two machines each add picks to
their own column, and git sees neighbouring lines and calls it a conflict. configsys knows the
structure, so it can do a three-way merge per section:

- **`picks:`** — merge per machine column; each column takes whichever side changed it. Both sides
  changing the same column = merge the lists (union of adds, honour removes).
- **Scalar settings** — a real conflict only when both sides changed the same key, to different
  values.
- **`plugins:`** (transitive) — per entry by source. Both bumped the same plugin = take the newer
  version and say so.
- **`components:` / `profiles:` / `pins:`** — per name or key.

Wired in as a git merge driver for `*.hu` in the primary (`.gitattributes` + a repo-local
`merge.configsys.driver` pointing at configsys). It runs during phase 3's replay and falls back to
the per-file question when it can't decide. A real conflict is asked about in plain words: "This
machine set `splash: plain`; your other machine set `splash: ocean`. Keep this one / keep the other
/ show me."

Tests: fixtures for each section kind (both machines edit their own column, both bump the same
plugin, a real scalar conflict), checked through the driver and end to end through `plugin push`
between two sandbox clones.

## Out of scope

- Version-tagging the primary (deliberately: see the ground rule).
- Hosting or creating the remote repo for you (`gh repo create`) — maybe later; for now
  `set-source` plus a pointer.
- Pushing plugins other than the primary. A plugin you author separately is your own git project.
