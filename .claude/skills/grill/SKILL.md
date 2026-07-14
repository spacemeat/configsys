---
name: grill
description: Drive a structured requirements-grilling loop before detailed planning or development. Use when starting a new component/feature, when a spec leaves load-bearing decisions open, or whenever the user says "grill me", "ask me questions", or "what do you need to know" before building. Surfaces the decisions that change what gets built, asks dependent follow-ups in rounds, tracks answered vs. open, knows when enough is settled to proceed, and records the outcome durably.
---

# Grill: requirements elicitation before building

The goal is to extract the decisions that *change what you build* before you build it — and
to know when you have enough to stop asking and start working. Asking too little produces
rework; asking too much exhausts the user on choices that have obvious defaults. This skill
is the disciplined middle.

## Core principle: load-bearing first

Order questions by **how much the answer changes downstream work**, not by component order
or convenience. A question is *load-bearing* if different answers lead to materially
different architectures. Ask those first. Examples of load-bearing vs. not:

- Load-bearing: which external vendor an interface must mirror; local vs. cloud compute;
  build-a-model-first vs. heuristic-first; strictly-free vs. paid data; legal/ToS constraints.
- Not load-bearing (use a default, mention it, move on): linter choice, directory names,
  test framework, log format.

If you can pick a sensible default and cheaply change it later, **don't ask** — state your
choice and proceed.

## The loop

1. **Read everything first.** The spec, existing code, any prior decisions doc. Never ask
   what the materials already answer.
2. **Draft the load-bearing set.** List the decisions that gate the most work. For each,
   know your own recommendation and *why*.
3. **Ask in rounds of ≤4** via the `AskUserQuestion` tool. Each question:
   - has 2–4 concrete, mutually-exclusive options;
   - leads with your recommended option, suffixed " (Recommended)", and says why in its
     description;
   - includes a "Discuss / not sure" option when the trade-off is genuinely subtle.
   Before the tool call, in prose, briefly say *why these four now* — the dependency logic.
4. **Honor dependent questions.** Some questions only make sense after earlier answers
   (e.g. "which news API" only matters once "use paid news at all?" is yes). Hold them for a
   later round; don't ask everything at once.
5. **When the user says "discuss"**, don't re-fire the picker — actually lay out the
   trade-offs in prose, give a recommendation, *then* offer the choice again.
6. **Reflect answers back as design impact.** After each round, restate each answer as the
   concrete thing it changes in the build ("score-weighted top-N → the scorer must emit a
   magnitude, not just a rank"). This catches misunderstandings early and shows the user
   their answers matter.

## Knowing when to stop

Stop grilling when the **only** remaining decisions are lower-tier (good defaults exist,
cheap to change). At that point:

- Don't run another full round. Instead, list the remaining items with your proposed
  default for each, marked as proposals the user can veto.
- Present a single "how do you want to proceed" checkpoint: draft the plan now (with defaults
  written in as overridable proposals) vs. keep grilling.

This is the "know when your questions are answered so you can get to work" behavior the
elicitation is for. Don't seek certainty on everything — seek certainty on the load-bearing
set, and reasonable defaults on the rest.

## Capture decisions durably

Record outcomes as you go so they survive context loss and become the source of truth:

- Write a planning/decisions doc (e.g. `docs/PLAN.md`) with sections: **Locked** (decided +
  rationale), **Parked** (deferred on purpose + why), **Open/defaults** (proposed, awaiting
  ratification), and an **open-questions backlog** for future rounds.
- Commit it. Reference it from later work.
- Park what can't be decided yet rather than forcing a premature answer (e.g. don't design a
  model before you have data to design it against).

## Anti-patterns

- Asking what the spec/code already says.
- Surveying options without a recommendation ("here are six libraries…"). Recommend one.
- Grinding on trivia (names, formats) that a default settles.
- One giant round of 15 questions. Batch, sequence by dependency, reflect, iterate.
- Treating "publicly available" as "permitted" — surface legal/ToS/licensing as real
  constraints when relevant, and don't assume away the user's stated values.
- Continuing to ask after the load-bearing set is settled. Switch to "propose defaults +
  proceed."
