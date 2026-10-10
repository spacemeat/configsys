---
name: update-docs
description: The go-to skill for making ALL configsys documentation true and current — README.md (+ its generated Glossary), every markdown it links, CLAUDE.md, everything in docs/ (reference specs, plans, the docs/done/ archive and docs/INDEX.md), the man pages (via their sources), argparse help strings, the TUI `?` help pages and key labels, the config.hu template's comments, DEFERRED.md, and the .claude/skills playbooks. Use when the user says "/update-docs", "update the docs", "make the docs current", "check the documentation", or after a batch of feature work. Verifies line by line with high-effort subagents against ground truth extracted from the code, normalizes terminology to docs/glossary.hu, keeps plan-doc status honest and moves finished plans to docs/done/, regenerates man pages, validates, commits.
---

# update-docs — make every piece of documentation true again

Docs drift in the same few ways every time, and the September 2026 review
(`docs/review-2026-09/docs-sync.md`) is the catalogue: a model change (profiles → picks) that never
reached the public docs; a README command list ~40% short of the real CLI; a shipped subsystem
(glue) documented nowhere; renamed keywords (`prefer:`/`opt-in:` → `standing:`) still taught; plan
docs still saying "NOT built" months after shipping; a man page byte-current with its source and
therefore faithfully wrong. This skill exists so that never accumulates again.

## Mission

1. **Accuracy.** Every factual claim on every surface below matches the code *as it is now* —
   commands, flags, defaults, config keys, file paths, behaviors, statuses, keybindings, examples.
2. **Lifecycle honesty.** A plan doc says exactly what's built and what isn't. Finished plans move to
   `docs/done/` with a dated DONE header; `docs/INDEX.md` records every doc's created / finished dates.
3. **One vocabulary.** `docs/glossary.hu` is canonical. README's Glossary is generated from it, and
   every doc, help string and `?` page uses its terms — one word per concept, retired words gone.
4. **Right voice per reader.** Public surfaces (README, man pages, `--help`, `?` pages) read cleanly
   for a human who has never seen configsys. `docs/` and CLAUDE.md are precise working references for
   developers — and especially for Claude: dense, current, cross-linked, no stale claims.

## The surfaces (and where their truth lives)

| surface | who reads it | edit HERE | never edit |
|---|---|---|---|
| `README.md` | users, first contact | the file (Glossary section is generated) | between the `glossary:begin/end` markers |
| markdown linked from README | users | the file | |
| `man/configsys.1` | users (`man configsys`) | argparse `help=`/`description=`/`_EPILOG` in `configsys/app.py` | `man/*` directly — run `tools/gen_manpages.py` |
| `man/configsys.hu.5` | users | `docs/config-format.md` (a controlled Markdown subset) | `man/*` |
| `configsys … --help` | users | the same argparse strings | |
| TUI `?` pages | users | `_HELP` (per-screen `desc` + `glossary`) in `configsys/tui/menu.py`; `ACTION_LABELS` in `configsys/tui/keyspec.py`; the `keys:` comments in `config.hu` | |
| `config.hu` comments | users (it's the template new configs are generated from) | `config.hu` | |
| `CLAUDE.md` | Claude, every session | the file | |
| `docs/*.md` reference specs | devs + Claude | the file | |
| `docs/*-plan.md` + design docs | devs + Claude | the file's Status header + phase markers | |
| `docs/done/` | history | header/links only (see Lifecycle) | the historical body |
| `docs/history/`, `docs/review-*/` | archive | links only | content |
| `docs/INDEX.md` | everyone | the file | |
| `docs/glossary.hu` | everyone, via README | the file | |
| `DEFERRED.md` | devs + Claude | the file | |
| `.claude/skills/**` | Claude (playbooks) | the files — a stale playbook makes every future task wrong | |
| plugin repos (`~/src/configsys-*`) READMEs/docs | plugin users | that repo (scope `plugins` only; separate commits) | |
| module docstrings, in-app advisories/messages | devs, users | the code (scope `--deep` only) | |

## Arguments

`/update-docs` = everything above except plugins and `--deep`. Narrow with scope words:
`readme`, `public` (README + linked md + CLI help/man + `?` pages + config.hu comments), `docs`,
`claude` (CLAUDE.md + skills), `plugins`, or explicit paths. Flags: `--check-only` (report, change
nothing), `--deep` (also module docstrings and user-facing in-app strings), `--since <ref>` (focus on
surfaces touching code changed since `<ref>`; default for a routine run is the last audit commit
recorded in `docs/INDEX.md`, but a full run still covers everything).

## Phase 0 — preflight + ground truth

1. `git status` — start clean so the final diff is reviewable. Read `docs/principles.md` (some doc
   statements are deliberate policy, not descriptions) and `docs/glossary.hu`.
2. Make a run dir in the scratchpad and extract ground truth with **`tools/docaudit.py`**:
   ```
   .venv/bin/python tools/docaudit.py facts --json     > $RUN/facts.json      # CLI tree, env vars, config keys
   .venv/bin/python tools/docaudit.py inventory --json > $RUN/inventory.json  # every md: class, status, git dates
   .venv/bin/python tools/docaudit.py check --json     > $RUN/check.json      # mechanical drift
   ```
   `facts` = every subcommand/option/help string (from `build_parser()`), the `CONFIGSYS_*` env vars
   the code reads, top-level config keys + retired keys, the settings registry (`CONFIG_SETTINGS` +
   nature), component keys, drivers, OS blocks, TUI screens / key defaults / action labels / `?`
   glossaries, component statuses. `check` = broken links, retired terms in live docs (and in argparse
   help + `?` text), `configsys …` examples that don't parse, humon snippets that don't parse,
   subcommands/flags/env vars/settings the docs omit or invent, missing Status headers, stale man
   pages, stale README glossary. Mechanical findings are leads, not verdicts — an agent confirms each.
3. `git log --oneline <last-audit>..HEAD` (last audit commit: top of `docs/INDEX.md`) and skim the
   changed files: new features are where docs are most likely missing; renamed things are where
   they're most likely wrong.

## Phase 1 — vocabulary first (you, before any fan-out)

Fix the language before you ask 30 agents to enforce it.
1. Reconcile `docs/glossary.hu` with `facts.json` + the recent log: a new concept (a status, setting,
   driver family, field like `cpu-names:`, a UI noun) gets an entry; a removed or renamed one moves to
   `retired:` with its replacement (add `match:` when the bare word over-matches).
2. Each entry: `def` written for someone who has never seen configsys — what it IS, in one or two
   plain sentences, no jargon that isn't itself an entry. `see:` must name existing entries (test-
   enforced). `avoid:` lists words that must NOT be used for this concept (e.g. *component*, not
   "package"; *picks*, not "active profiles").
3. If the code and the glossary disagree on a NAME (code says "unit", docs said "package"), the
   glossary follows the code's concept and the docs follow the glossary. Renaming a glossary term is a
   deliberate, all-docs change — note it in the report.
4. `.venv/bin/python tools/docaudit.py glossary --write` (regenerates README's Glossary; the
   `?` pages' per-screen glossaries are hand-written in `_HELP` and must agree with these defs).

## Phase 2 — fan-out audit (high-effort subagents)

Spawn `general-purpose` subagents **in parallel (up to 10 per message)**, each with the brief below.
Effort: **`xhigh`** for README chunks, `docs/config-format.md`, CLAUDE.md and the CLI-help unit;
**`high`** for everything else (the user asked for high or better). Units:

| unit | files | mode |
|---|---|---|
| README, one per `##` section group (≤ ~150 lines each) | README.md | **findings only** — you apply them (one voice for the front page) |
| each markdown README links to | that file | edit |
| CLI help → `configsys(1)` | argparse strings + `_EPILOG` in `configsys/app.py` (read each subcommand's handler to verify) | edit strings only |
| config reference → `configsys.hu(5)` | `docs/config-format.md` | edit |
| TUI help | `_HELP` (menu.py), `ACTION_LABELS` (keyspec.py), `config.hu` `keys:` comments | edit strings/comments only |
| config template | `config.hu` comments (outside `keys:`) | edit comments only |
| CLAUDE.md | CLAUDE.md | edit |
| reference specs, ~1–3 per agent by size | `docs/*.md` classified reference | edit |
| plans / done-candidates, ~3–4 per agent | `docs/*.md` classified plan or `done?` | status + dates verdict, edit header/phase markers (no moves — you do moves) |
| skills | `.claude/skills/**` | edit |
| DEFERRED.md | DEFERRED.md | edit (is each item still deferred, done, or dropped?) |
| plugins (scope `plugins`) | one repo each | edit, in that repo |

Every editing unit OWNS its files exclusively — no other agent touches them, so edits never collide.
Each writes `$RUN/report-<unit>.json` and replies with one line.

### The brief (fill `{UNIT}`, `{FILES}`, `{MODE}`, `{RUN}`)

> You are auditing configsys documentation for accuracy. configsys is at /home/schrock/src/configsys
> (read CLAUDE.md first; `docs/principles.md` holds deliberate policies). Ground truth extracted from
> the code: `{RUN}/facts.json` (CLI tree with every option and help string, env vars, config keys and
> settings, drivers, OS blocks, TUI screens/keys/help). Mechanical leads: `{RUN}/check.json` (filter
> to your files). Canonical vocabulary: `docs/glossary.hu`.
>
> Your unit: **{UNIT}** — files: {FILES}. Mode: **{MODE}** (`edit` = fix your files in place and
> touch NOTHING else; `findings` = change nothing, report proposed replacements).
>
> Go through your files **line by line**. For every factual claim — a command, flag, default, config
> key, field, path, env var, behavior, status, glyph, keybinding, number, example, link — verify it
> against the CODE (read the implementing function; `facts.json` is a shortcut, not a substitute),
> and where cheap, by running it: `configsys --help`, `configsys <cmd> --help`, `configsys --home
> <scratch dir> --os <block> <cmd>` or `--pretend` (never against the real home, never a real
> install). Then:
> - **Wrong / stale** → rewrite to match the code. **Missing** (a shipped feature, flag, setting the
>   doc should cover) → add it, in the doc's existing structure. **Removed** → delete or mark history.
> - **Terminology** → use `docs/glossary.hu` terms; never a term's `avoid:` words or a `retired:`
>   term (except when explicitly narrating history). A concept with no glossary entry → report it.
> - **Doc says X, code does Y, and X looks INTENDED** (a principle, a documented guarantee, an
>   obvious bug) → do NOT bend the doc to the bug. Report it as `code-bug` with evidence.
> - **Plans / design docs** (if in your unit): decide the true status phase by phase — check the code,
>   tests, and `git log --grep` / `git log -S '<symbol>'`. Recover dates: created = `git log --follow
>   --diff-filter=A --format=%as -- <file> | tail -1`; finished = the commit that landed the last
>   phase, or that flipped the status header (cite the hash), else `unknown (≤ YYYY-MM-DD)`. Set the
>   header to one of: `> **Status: PLAN** — not started` / `> **Status: IN PROGRESS** — phases A, B
>   done; C not started` / `> **Status: DONE** — finished YYYY-MM-DD (commit abc1234)` / `> **Status:
>   SUPERSEDED** by docs/X.md` / `> **Status: DEFERRED** — why`. Recommend `move-to-done` for DONE and
>   SUPERSEDED plans, and name the reference doc (if any) where the shipped behavior now lives.
> - **Voice:** public surfaces (README, linked guides, `--help`, man source, `?` pages, config.hu
>   comments) — second person, present tense, task-first, short paragraphs, plain words; every
>   non-obvious term is a glossary term (README may link `#glossary`); no internal history ("v2", "the
>   old model"), no file:line refs, no session lore; examples must run. Dev docs (`docs/`, CLAUDE.md,
>   skills) — precise, dense, cite code by module/function name (not line numbers), state invariants
>   and *why*, link the reference doc instead of duplicating it, label history as history.
> - argparse `help=` strings: one or two sentences, what the option does, its default if non-obvious.
>   `docs/config-format.md` must stay within the Markdown subset `tools/gen_manpages.py` converts.
>
> Write `{RUN}/report-{UNIT}.json`:
> `{"unit": "...", "files": [...], "changed": ["file: one line per change"],
>   "findings": [{"file", "line", "kind": "wrong|stale|missing|removed|terminology|voice|broken-link|code-bug|new-term|status",
>                "current", "proposed", "evidence": "code ref / command output", "confidence": "high|medium|low"}],
>   "status_verdicts": [{"file", "status_header", "created", "finished", "finished_evidence", "move_to_done": bool, "lives_on_in": "docs/X.md|null"}],
>   "questions": ["anything only the user can decide"]}`
> In `findings` mode put every proposed edit in `findings` (with exact replacement text). Reply with
> exactly one line: `{UNIT}: <n> changed, <f> findings, <b> code-bugs, <q> questions`.

## Phase 3 — integrate (you)

1. **Apply README findings** yourself, top to bottom, keeping one voice. Verify each high-impact claim
   (commands, defaults) with a quick run before writing it.
2. **Review every agent edit**: `git diff` per file. Revert anything that bends a doc to a reported
   `code-bug`, invents behavior, or drifts voice.
3. **Lifecycle moves** (below) for every `move_to_done` verdict.
4. **Consistency sweep**: `tools/docaudit.py check` again — zero errors; every remaining warning either
   fixed or consciously accepted (say why in the report). Grep the changed set for glossary `avoid:`
   words. Make sure the `?` page glossaries agree with `docs/glossary.hu`.
5. **CLAUDE.md last**: it summarizes everything else; update it after the specs settle, and repoint
   any path that moved.

## Lifecycle: docs/done/ and docs/INDEX.md

- A **reference** doc describes how something works *now* (`routing-model.md`, `config-format.md`,
  `principles.md`, `plugins.md`, `stranded-installs.md`, …). It is never "done" — it is maintained.
  It stays in `docs/`.
- A **plan / design** doc describes work. When every phase has shipped (or it's superseded), `git mv`
  it to `docs/done/`, prepend the DONE/SUPERSEDED header (keep the historical body untouched), and
  where the shipped behavior is specified elsewhere, add `Lives on in: docs/<reference>.md`. If the
  shipped behavior is specified NOWHERE else, that's a `missing` finding: fold the essentials into
  the right reference doc first — a done plan is history, not the spec.
- After moves, fix every inbound link (`grep -rn '<old path>'` across the repo, CLAUDE.md, skills,
  and the user's memory directory — repoint memory notes that cite moved docs).
- `docs/history/` and `docs/review-*/` are archives: fix links only. (Fold `docs/history/` into
  `docs/done/history/` if the user agrees — ask once.)
- **`docs/INDEX.md`** — create on the first run, then maintain. Top line: `Last full audit:
  YYYY-MM-DD at <commit>`. Then one table per class (reference / in progress / plans / done /
  archive) with columns: doc · status · created · finished · one-line summary. Created comes from
  `inventory` (git). Finished comes from the agents' `status_verdicts` (with the evidence commit);
  when it can't be recovered, write `unknown (≤ YYYY-MM-DD)` using the date the status header first
  said done. Don't fabricate dates.

## Phase 4 — regenerate + validate

```
.venv/bin/python tools/docaudit.py glossary --write
.venv/bin/python tools/gen_manpages.py              # after any argparse or config-format.md change
.venv/bin/python tools/docaudit.py check            # 0 errors; warnings triaged
.venv/bin/python -m pytest test/ -q                 # test_docs + test_manpages + everything (app.py strings changed)
.venv/bin/python -m configsys --help | head -30     # read the result like a newcomer would
```
Run every README `configsys` example you touched (sandbox `--home`, or `--pretend`). Read the
regenerated `man configsys` / `man configsys.hu` once (`man -l man/configsys.1`) — formatting
breakage only shows there.

## Phase 5 — report + commit

1. Report to the user, in the terminal (offer a page if it's long): what changed per surface;
   docs moved to `docs/done/`; glossary terms added/retired/renamed; every **code-bug** (doc right,
   code wrong) with evidence — these are the most valuable output; open **questions**; accepted
   warnings and why.
2. Commit locally (never push): one commit for the docs/glossary/help/man changes, separate commits
   for plugin repos. Update `docs/INDEX.md`'s `Last full audit` line in the same commit.

## What makes a run comprehensive (checklist)

- [ ] Every top-level subcommand and global flag appears in README (and every documented one exists).
- [ ] Every `CONFIGSYS_*` env var the code reads is documented once, with its effect.
- [ ] Every config key / setting is in `docs/config-format.md` (→ man 5) with type, default, nature.
- [ ] Every component status, glyph and badge the TUI can show is explained on its `?` page.
- [ ] Every keybinding default in `config.hu` matches the `?` labels and README.
- [ ] Every driver (`via:` value) is listed where drivers are enumerated (README, CLAUDE.md).
- [ ] Every OS family / notable OS block is reflected where supported platforms are listed.
- [ ] Every example runs; every humon snippet parses; every link resolves.
- [ ] Every plan doc has an honest Status header; every DONE plan is in `docs/done/`; INDEX current.
- [ ] No retired term outside narrated history; no glossary `avoid:` word for its concept.
- [ ] CLAUDE.md matches the architecture as built, and points at docs that exist.
- [ ] Skills' instructions match current fields, components and commands.
- [ ] Man pages regenerated; `test_docs` / `test_manpages` green.

## Notes

- `tools/docaudit.py` is deliberately conservative (warnings, not failures, for most kinds). When a
  run shows a check is noisy or blind, fix the tool in the same commit — the audit should get sharper
  every run.
- `test/test_docs.py` keeps README's Glossary generated-current in CI; the full drift check stays
  with this skill (it's judgment-heavy).
- Cost: a full run is ~25–35 high/xhigh agents. `--since` and narrow scopes keep routine runs small.
