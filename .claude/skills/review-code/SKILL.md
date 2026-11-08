---
name: review-code
description: The full configsys code review — the September 2026 review (docs/review-2026-09/) made repeatable. Fans out one high-effort reviewer per AREA of the tree (areas.hu) plus cross-cutting security and CLI/TUI-parity reviewers, all applying the user's lens set (reuse, MVVM/data-driven presentation, comment drift, naming, performance, tests, dead code, security, refactors, parity/features, ABI); verifies every serious finding adversarially; chains /update-component for the component catalog; writes a dated docs/review-YYYY-MM/ with ranked tiers; lets the user choose what to fix; applies the chosen fixes with tests; and finishes with /update-docs so the docs describe the fixed code. Use when the user says "/review-code", "review the code", "do a full code review", or asks to resume one ("/review-code status", "/review-code apply A3 B1").
---

# review-code — review everything, fix what the user chooses, make the docs true

configsys has been built by long iteration; review is how its quality bar holds. The September 2026
review (`docs/review-2026-09/README.md`) set that bar: 11 reviewers, ~260 findings ranked into
tiers, and one finding — the tarball driver would run `rm -rf $HOME` — that justified the whole
exercise. This skill makes that review repeatable and complete:

```
Phase 0  preflight      clean tree, baseline health, area-map coverage, the earlier review
Phase 1  review         one reviewer per area + security + parity          (fan-out, read-only)
Phase 2  verify         an adversarial checker per area for serious findings (fan-out, read-only)
Phase 3  components     /update-component, phases 0–3 (report only)        (its own fan-out)
Phase 4  synthesize     docs/review-YYYY-MM/README.md: themes, ranked tiers; commit the review
Phase 5  decide         the user picks tiers / items; policy questions asked
Phase 6  apply          serially, test-first, one commit per item; plan docs for the big ones
Phase 7  docs           /update-docs, last, so the docs describe the fixed code
Phase 8  close out      progress, INDEX, memory, the final report
```

It composes the other maintenance skills instead of copying them: **`/update-component`**
(`.claude/skills/update-component/SKILL.md`) owns the component catalog, **`/update-docs`**
(`.claude/skills/update-docs/SKILL.md`) owns every doc surface. When those playbooks change, this
skill inherits the change.

## Arguments

| form | does |
|---|---|
| `/review-code` | a full new review: every area, then phases 1–8 |
| `/review-code --since <ref>` | only areas whose owned files changed since `<ref>` (`reviewaudit.py since`), plus the cross-cutting areas and every open item carried over from the earlier review |
| `/review-code --areas routing,primary` | only those areas (plus the carry-over for them) |
| `/review-code status` | the latest review's tiers with each item's status; no agents |
| `/review-code apply <IDs \| tier letters>` | resume the latest review at Phase 6 (`apply A3 B1 B4`, `apply C`), then Phases 7–8 |

Flags: `--model opus|fable|sonnet` (the reviewer + checker model, default **opus**);
`--no-components` (skip Phase 3); `--no-docs` (skip Phase 7); `--plugins` (also audit each plugin
repo's components in Phase 3 and run `/update-docs plugins` in Phase 7); `--report-only` (stop after
Phase 5's report — no apply, no docs).

A full review is the default because the brief below asks for thoroughness. `--since` is for a
routine check between full reviews.

## The brief (the user's words — the north star of every reviewer)

This is the prompt the 2026-09 review was run from. Every reviewer gets it verbatim; when a lens
below and this text seem to disagree, this text wins.

> Let's do a thorough and complete code review. *Take your time.* I think you know in general what
> good quality code looks like, but focus on:
> - Code reuse, where it makes sense.
> - Data-driven presentations. Think MVVM-style stacks, which could use real or mock data.
> - Good linting. Many of the comments are for your own future edification, so don't feel the need
>   to erase them, but ensure any comments are up-to-date with the code.
> - Good, human-readable variable names.
> - Don't be bashful about looking for performance enhancements. Examine how often a computation is
>   performed in inner loops, and whether caching or memoizing makes sense. Remember too that this
>   is python, and it is in general slow and mostly single-threaded.
> - Don't be bashful about adding tests. *Do* be bashful about removing tests, unless there is no
>   codepath they cover. Adding tests is great.
> - Look for dead code. We've made lots of changes over the development. There may be straggling
>   bits. Do bear in mind that this is a plugin architecture, so some parts may be called from the
>   outside, especially in plugins.
> - Be judicious about security. We're evaluating script in some places, and doing other things that
>   make the security question vague--the trust model for plugins is great, but what else might slip
>   in? Besides the usual supply chain attacks any user of, say, flatpak might encounter anyway.
> - Feel free to make suggestions about broader refactors. If an overhaul is worthy, I'd like to
>   consider it. We've been iterating a long time.
> - If there's any features missing in your mind, call them out. If there's any imparity between CLI
>   and TUI, call them out. *Most* things CLI can do *should* be elevated to TUI as well, but not
>   necessarily all.
> - I remain the only user (but not for long). If an ABI or major interface ought to change, so be
>   it. Let's tackle that now, before we break anybody.
> - Synchronize all public docs (README.md and anything it links to), man pages, etc. to current
>   functionality. Look for outdated terms or language, and aim to reduce new terms and to be
>   consistent with terms like component, driver and via, dotfiles vs. glue.

The last bullet is Phase 7 (`/update-docs`), not a reviewer lens. Reviewers still report in-code
comments and docstrings that drift (lens 5), and a doc that states an intended behavior the code
breaks (a correctness finding).

## The lenses (category slugs)

Each finding carries exactly one category:

| # | category | what to look for |
|---|---|---|
| 1 | `correctness` | bugs, edge cases, hostile input; violations of `docs/principles.md` and the reference specs (a spec stating an *intended* behavior the code breaks is a bug in the code) |
| 2 | `security` | anything a plugin, route data, upstream text or env can make configsys run, write or delete beyond what the user consented to |
| 3 | `safety` | configsys-specific posture: `--pretend` honored on every write path; destructive ops contained (rm/rmtree/mv/`ln -sf` targets never resolve to `$HOME`, a scope base, `/`, a shared dir); never overwrite a user's file; no surprises |
| 4 | `reuse` | the same logic hand-copied N times; a shared helper that one copy forgot |
| 5 | `comment-drift` | comments / docstrings that describe what the code no longer does (keep the notes-to-self; fix the stale ones) |
| 6 | `data-driven` | presentation built by hand instead of from a view model or a table; logic that should be data |
| 7 | `naming` | names a newcomer would misread; retired vocabulary living on as identifiers (`docs/glossary.hu` `retired:`) |
| 8 | `performance` | work repeated in inner loops, per frame, per unit, per command; subprocess spawns; missing or mis-keyed caches. **Measure** before claiming (time it, count the calls) |
| 9 | `test-gap` | an untested codepath, especially adversarial and edge inputs; a test that asserts nothing |
| 10 | `dead-code` | unreachable or unused code — only after grepping the plugin repos (`~/src/configsys-*`), `examples/`, and the frozen ABI list in `configsys/driver.py` |
| 11 | `refactor` | a broader restructuring worth its cost; say what it collapses and which bug classes it removes |
| 12 | `parity` | a CLI capability missing from the TUI (or the reverse) that should be there |
| 13 | `feature` | something a user would reasonably expect and not find |
| 14 | `abi` | a plugin-facing or major interface that should change now, before collaborators depend on it |

## Severity, effort, tiers

**Severity** — `CRITICAL` (data loss, or code execution / privilege across a trust boundary, reachable
in normal use — the `rm -rf $HOME` class), `HIGH` (a real bug or exposure a user can hit, or a large
measured cost), `MED`, `LOW`, `NIT`. **Effort** — `S` (one small commit), `M` (a focused change),
`L` (needs a plan doc first).

**Tiers** (the README's ranking; letters match 2026-09 so reviews compare):
A security + safety · B correctness · C performance · D refactors · E docs-vs-code (only what
`/update-docs` can't settle: the doc is right and the code is wrong, or the user must decide) ·
F ABI / interface · G features + parity. Test gaps and dead code are listed under the tier of the
code they touch, or in the README's own Test-gaps section.

**IDs** — a finding is `<area>-NN` in its area file (`routing-07`), a ranked README item is
`<tier><n>` (`A3`) and cites the findings it covers. IDs never change once committed.

## Rules for every agent this skill launches

- **Read-only on the repo.** The only files an agent writes are the ones its brief names (its own
  review file, its own JSON) and scratch files under `$RUN/scratch/<area>/`. No `git commit`,
  `checkout`, `stash`, `reset`, or `push`; `git log` / `show` / `blame` / `diff` are fine.
- **Never touch the real home.** Run configsys only as `.venv/bin/python -m configsys --home
  $RUN/scratch/<area>/home …` and/or `--pretend`. Never a real install, never `sudo`.
- **Never `rm` a path derived from `$HOME`**, not even a reassigned one — clean up only literal
  `$RUN/...` paths.
- No `api.github.com` calls (rate-limited); no sending the user's email anywhere.
- Run targeted tests only (`pytest test/test_x.py -q`); Phase 0 already ran the whole suite.
- Reply with ONE line (counts). Findings live in files — 16 agents' worth would flood the context.

## Phase 0 — preflight (you)

1. `git status` must be clean before Phase 6 (applying into a dirty tree mixes diffs); a dirty tree
   can still be reviewed — say so. `BASE=$(git rev-parse --short HEAD)`.
2. Directories: the review dir `REV=docs/review-$(date +%Y-%m)` (append `-2`, `-3` if it exists); the
   run dir `RUN=<scratchpad>/review-<date>/` for JSON and scratch work (it does not survive the
   session — everything durable goes in `$REV`).
3. **Area-map coverage:** `.venv/bin/python tools/reviewaudit.py coverage` must exit 0. An `unowned`
   file goes to the area that fits it (a new subsystem over ~1k lines gets its own area, with a
   `focus:` and a `context:`); a `dead glob` or `missing context` is fixed in
   `.claude/skills/review-code/areas.hu`. Map changes are committed with the review. Then
   `reviewaudit.py areas` — and for `--since`, `reviewaudit.py since <ref>` — gives the area list.
4. **The earlier review:** `reviewaudit.py prior --before $REV --json` gives its dir, its baseline
   commit, and each area's inherited files. Read its README: every ranked item not marked done
   (`[done …]`, or "DONE" in the 2026-09 Progress prose) is an **open carry-over**. Every reviewer
   gets its inherited files.
5. **Baseline health,** recorded in the README header:
   - the whole suite in the background, with timings for the tests-tools reviewer:
     `.venv/bin/python -m pytest test/ -q --durations=40 > $RUN/pytest.txt 2>&1` (~10 min);
   - `configsys --os <os> check` for pop_os!, fedora, arch, alpine, opensuse, rhel, fedora_atomic,
     void and void_musl (error and warning counts);
   - `.venv/bin/python tools/docaudit.py check` (counts).
6. **State the scale** before fanning out, e.g. "16 reviewers (opus, xhigh; security max) + up to 16
   checkers + a component audit (N units due → M agents) + `/update-docs` (~30 agents)". Proceed
   without waiting unless the user has asked to confirm large runs.

## Phase 1 — area review (fan-out)

Launch one `general-purpose` agent per area, **up to 10 per message**, with `model` = the run's model
(default `opus`) and `effort` = the area's `effort:` (security: `max`), else `xhigh`. Put
`tests-tools` in the last wave so `$RUN/pytest.txt` is likely done (it can wait for the file). While
the agents run, start Phase 3's mechanical scan.

**A CRITICAL interrupts.** When a reply reports `critical > 0`, read that finding at once, confirm it
yourself (a `--pretend` run or a scratch script), and tell the user immediately — don't wait for the
synthesis. Recommend fixing it first; fix it only with their go-ahead (Phase 6's rules).

### The reviewer brief (send verbatim, placeholders filled)

> You are reviewing one area of configsys, at /home/schrock/src/configsys (read CLAUDE.md first,
> then docs/principles.md — some code shapes are deliberate policy). This is a thorough, high-bar
> code review: take your time, read every owned file line by line, and verify every claim against
> the code — by reading the implementing function, and wherever it is cheap, by **running** it (a
> scratch script with `.venv/bin/python`, or configsys itself in a sandbox:
> `.venv/bin/python -m configsys --home {RUN}/scratch/{AREA}/home --os <block> <cmd>`, or
> `--pretend`). Mark a finding **(reproduced)** only when you ran it, and quote the command and its
> output.
>
> Area **{AREA} — {TITLE}**. Owned files (review line by line): {OWNED}. Context (read to judge
> them, don't review them): {CONTEXT}. Find this area's tests (`grep -l` test/ for imports of the
> owned modules) and read them too — test gaps are judged against them. Area focus, on top of the
> lenses: {FOCUS}.
>
> The user's brief, verbatim: {BRIEF}
> The lenses and their category slugs: {LENSES}
> Severity: CRITICAL / HIGH / MED / LOW / NIT (see {SEVERITY}); effort S / M / L.
>
> **Carry-over.** The earlier review of this code: {INHERITED} (baseline {PRIOR_BASE}); its
> still-open ranked items: {OPEN_ITEMS}. For every earlier finding in your scope, decide: `fixed`
> (cite the commit — `git log -S '<symbol>'` / `git log --grep`), `open` (re-report it as a
> finding with `carried_from` set), or `obsolete` (the code is gone or changed so it no longer
> applies — say why). Don't re-report fixed ones.
>
> **Dead code** is only dead after you grep `~/src/configsys-*/` (the plugin repos, read-only),
> `examples/`, the tests, and the frozen ABI list in configsys/driver.py's docstring — this is a
> plugin architecture. **Performance** claims need a measurement (time it, count calls on the real
> catalog). **Security** findings say who controls the input, when it runs, with whose privileges,
> and what consent preceded it.
>
> Rules: read-only on the repo — write ONLY `{REV}/{AREA}.md` and `{RUN}/area-{AREA}.json` (scratch
> work under `{RUN}/scratch/{AREA}/`). No git writes. Never touch the real home, never install,
> never sudo, never `rm` a path derived from `$HOME`. No api.github.com. Targeted tests only.
>
> Write `{REV}/{AREA}.md` in this shape:
> ```
> # Review: {TITLE}
>
> Baseline: `{BASE}` · {DATE} · reviewer: {MODEL}, effort {EFFORT}
> Scope: <owned files>. Context: <context read>. Tests read: <test files>.
>
> ## Carried over from <earlier file(s)>
> | earlier finding | status | evidence |
>
> ## Cross-cutting themes
> - <what recurs across the area — the shape behind several findings>
>
> ## Findings
> ### {AREA}-01 [HIGH] correctness — <title>
> `configsys/x.py:120-134` (`function_name`): <what is wrong, and why it matters to a user>.
> **(reproduced)** `<command>` → `<output>`   (or: verified by reading `<file:line>`)
> **Fix:** <concrete change>. **Effort:** S. **Tier:** B.
>
> ## Test gaps
> ## Dead code   (each entry: what you grepped to be sure)
> ## ABI / interface candidates
> ## Questions for the user
> ```
> Order findings by severity. File:line references are a snapshot against `{BASE}`.
> Write `{RUN}/area-{AREA}.json`:
> `{"area", "baseline", "files_read": [...], "findings": [{"id", "severity", "category", "title",
>   "where": ["file:line (function)"], "summary", "evidence", "reproduced": true|false, "fix",
>   "effort": "S|M|L", "tier": "A-G", "carried_from": null|"<earlier id or title>",
>   "confidence": "high|medium|low"}], "carryover": [{"earlier", "status": "fixed|open|obsolete",
>   "evidence"}], "themes": [...], "questions": [...]}`
> Reply with exactly one line: `{AREA}: <n> findings (<c> critical, <h> high, <m> med, <l> low,
> <t> nit), <k> carried over, <f> earlier fixed, <q> questions`.

`{OWNED}`, `{CONTEXT}`, `{FOCUS}`, `{TITLE}`: from `reviewaudit.py areas --json` (`owned`, not the
raw globs). `{INHERITED}`, `{PRIOR_BASE}`: from `reviewaudit.py prior`. `{BRIEF}`, `{LENSES}` and
`{SEVERITY}`: paste the sections above. `{OPEN_ITEMS}`: the open
carry-over items whose cited findings fall in this area (all of them for the cross-cutting areas).

If an agent fails or returns without both files, re-run it once; then list the area as "not
reviewed" in the README.

## Phase 2 — verify (fan-out)

Serious findings get a second agent whose job is to **refute** them. A false HIGH costs a wasted fix;
a false CRITICAL costs trust. For every area with at least one CRITICAL or HIGH finding, or any
`security`/`safety` finding at MED or above, launch one checker (`model` = the run's model, `effort`
= `max`), up to 10 per message:

> You are checking another reviewer's findings in configsys (/home/schrock/src/configsys; read
> CLAUDE.md). Findings to check: in `{REV}/{AREA}.md` and `{RUN}/area-{AREA}.json`, every CRITICAL
> and HIGH, and every `security`/`safety` finding at MED or above. Your job is to try to **refute**
> each one: read the code yourself, look for the guard the reviewer missed, the caller that makes
> it unreachable, the test that already covers it; then try to reproduce it (scratch script, or
> configsys in a sandbox `--home {RUN}/scratch/verify-{AREA}/home` / `--pretend`). Same rules as
> the reviewer: read-only on the code, never the real home, never sudo, never `rm` a `$HOME`-derived
> path, no git writes.
> Verdicts: `CONFIRMED (reproduced)` — you ran it, quote command and output; `CONFIRMED (by
> reading)`; `PLAUSIBLE` — real but you couldn't show it; `REFUTED` — say exactly why. You may
> change a severity (say why).
> You now own `{REV}/{AREA}.md`: add a `**Verified:** <verdict> — <evidence>` line under each
> finding you checked; move REFUTED findings, verdict included, to a final `## Refuted on
> verification` section (kept, for calibration); apply severity changes. Write
> `{RUN}/verify-{AREA}.json`: `{"area", "verdicts": [{"id", "verdict", "severity_was",
> "severity_now", "evidence"}]}`. Reply with one line: `{AREA}: <n> checked, <c> confirmed, <p>
> plausible, <r> refuted, <s> severity changed`.

## Phase 3 — the component catalog (`/update-component`, report only)

Unless `--no-components`: read `.claude/skills/update-component/SKILL.md` and run its **Phases 0–3**
for scope `*` (plus `<plugin>/*` for each plugin repo with `--plugins`), with three changes:
- don't ask its apply question at the end of its Phase 3 — its findings join this review's Phase 5;
- copy its `report.md` to `$REV/components.md` (its run dir is in the scratchpad);
- its Phases 4–6 (apply, validate, record + commit) run inside this skill's Phase 6, for the
  findings the user approves.
Its GitHub-token check still applies, and a whole-scope run asks before continuing without a token.
Start its mechanical scan (`compaudit.py scan`) while Phase 1 runs; its subagents launch in the
waves after the reviewers.

## Phase 4 — synthesize (you)

Read every area file, not just the JSON. Then write `$REV/README.md`:

```
# configsys code review — YYYY-MM-DD

Baseline: `<BASE>` · reviewers: <model>, effort xhigh (security max), checkers effort max
Areas: <n> (<list>) · not reviewed: <none | list + why>
Health at baseline: <N> tests passed (<time>); `check` <errors>/<warnings> across <OSes>;
docaudit <counts>
Findings: <c> CRITICAL · <h> HIGH · <m> MED · <l> LOW · <t> NIT (after verification: <x>
confirmed, <y> plausible, <z> refuted) · components: <broken>/<drift>/<opportunity>/<note>

<one paragraph: the state of the tree and the shape of the findings>

The brief: <the user's brief, verbatim>

## Progress (updated as work lands)
- <one line per landed item: ID, what, commit>

## 0. Fixed during the review           (CRITICALs fixed with the user's go-ahead, if any)
## 1. The earlier review                 (each carried-over item: fixed <commit> / still open → ID / obsolete)
## 2. Cross-cutting themes               (what recurs across ≥ 3 areas, with the areas named)
## 3. Act-on-these, ranked               (Tier A … G; each item one line + a short paragraph)
   - **A1 [HIGH] <title>.** <what, why, fix>. (security-03, plugins-05) · effort M · [open]
## 4. Test gaps
## 5. The component catalog              (counts + every broken/drift item; detail in components.md)
## 6. Suggested sequencing
## 7. Decisions needed from you
```

- **Dedupe across areas.** The same problem found by the security reviewer and an area reviewer is
  ONE ranked item citing both IDs.
- **Rank within a tier by value per line changed.** A refactor that collapses duplication *and*
  removes a bug class outranks one that only tidies.
- **Status tags** end every ranked item: `[open]`, `[done <commit>]`, `[declined]`,
  `[deferred → DEFERRED.md]`, `[superseded by <ID>]`. They are this review's ledger — `status` and
  `apply` read them.
- Then: add the review to `docs/INDEX.md`'s archive table (status `IN PROGRESS` until every item is
  done/declined/deferred, then `ARCHIVE`), run `tools/docaudit.py check` on `$REV`, and **commit the
  review** before anything is fixed:
  `git -c user.name="Trevor Schrock" -c user.email="spacemeat@gmail.com" commit -m "review-YYYY-MM:
  full code review — <counts>" ` with the attribution line the system currently provides. A review
  dir is a living log until its items close; after that it is archive (`/update-docs` fixes its
  links only).

## Phase 5 — decide (the user)

In the terminal: the counts; every CRITICAL and HIGH as one line (ID, title, effort); per tier, the
item count with how many are `S`; the component broken/drift lines; the decisions needed. Offer the
README as a page in one line if the user would rather read it there. Then ask with
`AskUserQuestion`:
- the policy decisions first (trust-model direction, an interface break, a removal) — one question
  each, the recommended option first;
- then what to apply: tiers (multi-select), with "specific IDs" via Other, and the component
  findings ("all broken + drift", numbers, none).

With `--report-only`, stop here.

## Phase 6 — apply (serially, by you)

Never let subagents edit in parallel — they collide. Order: what the user chose, in tier order
A → B → C → G → D → F, the component findings, then Phase 7. Bundle a Tier F interface change into
the refactor that touches the same surface, so it is one break.

For each item:
1. **Prove it first.** A bug or a security item gets a failing test (or a reproduction script, for
   what a unit test can't reach) before the fix.
2. **Fix it at the root,** in the house style (comment density, naming and idiom of the surrounding
   code). Follow the playbook the change falls under: `/add-driver` for driver changes,
   `/add-component` for route data, `docs/principles.md` for policy.
3. **Add tests freely; remove one only when no codepath remains for it.**
4. **Keep the house gates green:** every new write path honors `ctx.runner.pretend` and a new verb
   joins `test/test_pretend_sweep.py`'s `VERBS`; driver changes pass `test_driver_inventory.py`;
   ABI changes update `configsys/driver.py`'s FROZEN list and `test_abi_surface.py`; routing
   changes regenerate `test/routing_golden.json` and get a semantic diff (changes only where
   intended); `configsys --os <os> check` stays 0-error across the Phase 0 OSes.
5. **Targeted tests,** then **commit** — one item (or one coherent group) per commit, message
   `review-YYYY-MM <ID>: <what changed>`, with the item's README status tag and a Progress line
   updated in the same commit.
6. After each tier, the whole suite in the background; report failures with their output.

**`L` items** (most of Tier D, a big Tier F break): write `docs/todo/<slug>-plan.md` first — phases,
what each delivers, the tests that prove it — show the user, and build phase by phase only on their
go (the way the primary-push plan was built). Mark the README item `[plan → docs/todo/<slug>-plan.md]`
until it lands.

**Component findings:** `/update-component`'s Phases 4–6 (apply, validate, record + commit), for the
approved findings only.

If a fix turns out wrong or larger than its effort said, stop and tell the user; don't widen it on
your own.

## Phase 7 — docs (`/update-docs`, last)

Unless `--no-docs`: invoke the `update-docs` skill with `--since <BASE>` (and `plugins` with
`--plugins`) — after every fix, so the docs describe the code as fixed. Every `code-bug` it reports
(the doc is right, the code is wrong) becomes a new README item in Tier B or E, ID `docs-NN`, and is
put to the user like any other.

## Phase 8 — close out

1. The README's Progress section and status tags current; its header gets
   `Status: <done>/<total> items done, <declined> declined, <open> open`.
2. `docs/INDEX.md`: the review's row status.
3. Memory: update the review's project memory (create one for a new review) — the review dir,
   what landed, what remains open — and its MEMORY.md line.
4. The final report, in the terminal: what landed (by tier, with commits), what was declined or
   deferred, what remains open; the verification numbers (confirmed / plausible / refuted per area —
   the quality signal when comparing `--model` runs); the suite before and after; the agents used.
   Commits are local; never push.

## `status` and `apply` (resuming a review in a later session)

The run dir is gone by then; the review dir is the state.
- `status`: read the latest `docs/review-*/README.md`; print each tier's items with their status
  tags, then the counts. No agents.
- `apply <IDs | tiers>`: Phase 0 steps 1 and 5 (clean tree, baseline suite), then Phase 6 for those
  items (each item's area file has the detail — file:line refs are a snapshot at the review's
  baseline, so re-locate the code first), then Phases 7–8.

## Cost

A full run is large: 16 reviewers at xhigh / max, up to 16 checkers at max, the component audit (a
first full catalog run is ~44 agents; later runs are incremental via its ledger), and `/update-docs`
(~25–35 agents). `--since`, `--areas`, `--no-components` and `--no-docs` trim it. Record the model
and efforts in the README header every run, so reviews made with different `--model` values can be
compared on their refute rates.
