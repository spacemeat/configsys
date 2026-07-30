# docs/history — archived planning docs

These are superseded planning and milestone documents, kept for provenance. They describe
decisions and sequencing as they stood at the time; the **current** behavior is documented in
the live reference docs one level up (`../routing-model.md`, `../config-format.md`,
`../plugins.md`, `../theming.md`) and in the top-level `README.md` / `CLAUDE.md`.

- **PLAN.md** — the original plan & decisions doc (Milestone 1 onward).
- **IMPLEMENTATION.md** — the Milestone 1 (apt vertical slice) implementation plan, derived
  from `PLAN.md`.
- **wire-in.md** — the record of cutting over to the capability engine as the sole resolver
  (v1 deleted, commit `f26d740`).

Feature-scoping docs for shipped features that are still cited by code or kept for rationale
(e.g. `../install-methods-plan.md`, `../immutable-distros.md`, `../expansion-plan.md`,
`../plugin-init-plan.md`, `../dotfiles-capture-plan.md`) remain alongside the live docs, each
carrying a **SHIPPED** status header.
