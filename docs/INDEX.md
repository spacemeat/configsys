# Docs index

Last full audit: 2026-10-09 at f25cb60 (`/update-docs`, committed as d958cf9); bug batch + decisions 2026-10-10.

Where every doc lives and what state it's in. Created = first git commit of the file; finished = the commit that landed the last phase (from the doc's Status header). Maintained by the `/update-docs` skill.

## Reference — `docs/`
How things work now. Maintained, never "done".

| doc | status | created | finished | summary |
|---|---|---|---|---|
| [component-attrs.md](component-attrs.md) | REFERENCE | 2026-08-19 | — | `attrs:` kind tags, their vocabulary and auto-derivation. |
| [config-format.md](config-format.md) | REFERENCE | 2026-07-24 | — | Every config and routes key (source of `man configsys.hu`), incl. `keys:`. |
| [facets.md](facets.md) | REFERENCE | 2026-08-08 | — | `facets:` — detected environment atoms (gpu, cuda, …) usable in `when:`. |
| [glossary.hu](glossary.hu) | REFERENCE | 2026-10-09 | — | Canonical vocabulary; README's Glossary is generated from it. |
| [name-sweep-test.md](name-sweep-test.md) | REFERENCE | 2026-07-24 | — | The native package-name existence sweep (podman) and its allowlist. |
| [orphans.md](orphans.md) | REFERENCE | 2026-10-09 | — | Managed orphans: finding installed things you don't pick; adopt / ignore. |
| [plugins.md](plugins.md) | REFERENCE | 2026-07-17 | — | Plugins: add, sync, pin, trust; data vs code plugins; the driver ABI and hooks. |
| [principles.md](principles.md) | REFERENCE | 2026-09-23 | — | Load-bearing policies: safety, routing invariants, no surprises, what we don't model. |
| [routing-model.md](routing-model.md) | REFERENCE | 2026-07-16 | — | The capability/component routing model as built: bindings, `when:`, selection, resolution. |
| [shell-glue.md](shell-glue.md) | REFERENCE | 2026-09-24 | — | Glue loaders per shell, user startup space, and the shell-writes guard. |
| [stranded-installs.md](stranded-installs.md) | REFERENCE | 2026-10-08 | — | Stranded-install detection and the `switch` / `unmet` / `dangling` statuses. |
| [system-updates.md](system-updates.md) | REFERENCE | 2026-10-09 | — | System updates: non-component upgrades, tiers, `updates` / `upgrade --system`. |
| [theming.md](theming.md) | REFERENCE | 2026-07-30 | — | The `theme:` section, the Theme editor screen, color depth and effects. |
| [tui-architecture.md](tui-architecture.md) | REFERENCE | 2026-10-09 | — | How the TUI is built: MVVM screens (build_vm / draw / handle), router, surfaces. |
| [versioned-requires.md](versioned-requires.md) | REFERENCE | 2026-08-02 | — | Version floors, version-scoped providers, `version-floors:`, auto-tighten; Python versions. |

## To do — `docs/todo/`
Unfinished plans: not started, in progress, or deferred.

| doc | status | created | finished | summary |
|---|---|---|---|---|
| [community-routes-registry.md](todo/community-routes-registry.md) | DEFERRED | 2026-09-23 | — | Design note: crowdsourcing route data safely (catalog → curated repo → federated). *design note only, never scheduled; nothing built (no `plugin search`/`browse`, no catalog, no community repo).* |
| [method-broadening-plan.md](todo/method-broadening-plan.md) | IN PROGRESS | 2026-08-27 | — | Offer every working install method (`when:` is validity, not preference). *Phase 1 done (8a15ff5); Phase 2 partly done (tools/regsweep.py + 4 identity-confirmed cargo adds, 9659a5d); Phase 2b flatpak backlog (foot/jmeter/racket/wine) and the pipx/npm ecosystem sweeps not started.* |
| [source-plugin-plan.md](todo/source-plugin-plan.md) | IN PROGRESS | 2026-08-02 | — | configsys-source: additive build-from-source bindings. *pilot (configsys-source 2927311), batch 2+ (batches 3–8, folly, suckless; configsys-source through 946e242) and the toolchain-floor follow-up (rustup d9db757, Go tarball bdf8a1b) done; heavy-app spin-outs partly done (configsys-blender/-kicad/-opencv exist), configsys-ghostty/-hyprland/-cosmic not started.* |

## Done — `docs/done/`
Finished or superseded plans. The body is historical; the header says where the behavior is specified now.

| doc | status | created | finished | summary |
|---|---|---|---|---|
| [d2-mvvm-findings.md](done/d2-mvvm-findings.md) | DONE | 2026-09-20 | 2026-09-20 (aef1da9) | Findings log kept during the MVVM rewrite. |
| [d2-mvvm-plan.md](done/d2-mvvm-plan.md) | DONE | 2026-09-20 | 2026-09-20 (5641778) | TUI rewrite to MVVM screens + a lazy router. |
| [docs-audit-fixes-2026-10.md](done/docs-audit-fixes-2026-10.md) | DONE | 2026-10-10 | 2026-10-10 | The audit bug batch + grilled decisions (uniform layers, brew routes, glue bands). |
| [dotfiles-capture-plan.md](done/dotfiles-capture-plan.md) | DONE | 2026-07-25 | 2026-07-26 (40f24f3) | Capture/adopt on-system dotfiles into your store; clobber-proof linking. |
| [dotfiles-glue-split-plan.md](done/dotfiles-glue-split-plan.md) | DONE | 2026-09-15 | 2026-10-10 (2a577c0) | Separate glue from dotfiles. |
| [dotfiles-redesign.md](done/dotfiles-redesign.md) | DONE | 2026-08-16 | 2026-08-17 (a4e081e) | Two kinds of dotfiles, user-owned links, managed-even-when-empty. |
| [driver-resilience-plan.md](done/driver-resilience-plan.md) | DONE | 2026-08-26 | 2026-08-26 (269817d) | Diagnose broken sources, rotated-key self-heal, validate-then-commit. |
| [expansion-plan.md](done/expansion-plan.md) | DONE | 2026-07-24 | 2026-07-24 (0be7bcc) | Languages, tools, desktops and `configsys request`. |
| [glue-customization-plan.md](done/glue-customization-plan.md) | DONE | 2026-09-24 | 2026-09-24 (d597377) | Customize shipped glue; a user startup space; portability to primary. |
| [immutable-distros.md](done/immutable-distros.md) | DONE | 2026-07-22 | 2026-07-22 (7feec73) | Immutable/atomic distros: brew + rpm-ostree, the fedora_atomic block. |
| [install-methods-plan.md](done/install-methods-plan.md) | DONE | 2026-07-29 | 2026-07-29 (2711a3e) | Install-method selection. |
| [keybindings-plan.md](done/keybindings-plan.md) | DONE | 2026-08-21 | 2026-08-21 (dec31b4) | User-configurable TUI keybindings (`keys:`). |
| [managed-orphans-plan.md](done/managed-orphans-plan.md) | DONE | 2026-08-21 | 2026-08-25 (34ec1b8) | Discover installed things that aren't picked. |
| [many-installs-including-src.md](done/many-installs-including-src.md) | SUPERSEDED | 2026-07-29 | — | Early notes on multiple install options incl. source. *by docs/done/install-methods-plan.md (shipped as multi-method selection + the declarative `source` driver), 2026-07-29.* |
| [plugin-init-plan.md](done/plugin-init-plan.md) | DONE | 2026-07-26 | 2026-07-26 (621a0a3) | `configsys plugin init`: assemble a personal plugin from local bits. |
| [profiles-derive-plan.md](done/profiles-derive-plan.md) | SUPERSEDED | 2026-09-05 | — | Profiles via a `^derive` primitive + ballot UX. *by docs/done/profiles-disposition-plan.md (the `^derive` machinery built in steps 1–6 + A-hier was removed in b589ce1), 2026-09-09; that plan was in turn superseded by docs/done/profiles-matrix-plan.md (the picks matrix).* |
| [profiles-disposition-plan.md](done/profiles-disposition-plan.md) | SUPERSEDED | 2026-09-09 | — | Profiles v2: the disposition model. *by docs/done/profiles-matrix-plan.md (the picks matrix), 2026-09-10.* |
| [profiles-matrix-plan.md](done/profiles-matrix-plan.md) | DONE | 2026-09-10 | 2026-09-14 (406546f) | Profiles v3: the component × machine picks matrix. |
| [profiles-plan.md](done/profiles-plan.md) | DONE | 2026-07-24 | 2026-07-25 (3d4f228) | The first profiles pass. |
| [python-versions-plan.md](done/python-versions-plan.md) | DONE | 2026-08-12 | 2026-08-12 (f48080d) | Python versions as version-scoped components. |
| [routing-overhaul-plan.md](done/routing-overhaul-plan.md) | DONE | 2026-08-11 | 2026-08-11 (9d3b791) | Version-scoped providers, one `standing` knob, detection-first, where picker. |
| [shell-writes-switch.md](done/shell-writes-switch.md) | DONE | 2026-08-18 | 2026-08-18 (58c8c4b) | Stop installers scribbling in rc files. |
| [startup-perf-plan.md](done/startup-perf-plan.md) | DONE | 2026-08-12 | 2026-08-12 (c24a056) | Startup performance investigation + fixes (~50s → ~5s). |
| [system-update-coverage-plan.md](done/system-update-coverage-plan.md) | DONE | 2026-09-21 | 2026-09-23 (cd65037) | configsys as the single updater: system updates P0–P3. |
| [theme-redesign.md](done/theme-redesign.md) | DONE | 2026-08-03 | 2026-08-04 (cadaaa7) | Shared color map + per-page role styles. |
| [tui-screens-plan.md](done/tui-screens-plan.md) | DONE | 2026-08-03 | 2026-08-03 (dad4f31) | The TUI screen set. |

## Archive — `docs/history/`, `docs/review-2026-09/`
Early plans, previous definitions of terms, and dated reviews. Links are kept working; content is never rewritten.

| doc | status | created | finished | summary |
|---|---|---|---|---|
| [IMPLEMENTATION.md](history/IMPLEMENTATION.md) | ARCHIVE | 2026-07-13 | — | Milestone 1 (apt vertical slice) implementation steps. |
| [PLAN.md](history/PLAN.md) | ARCHIVE | 2026-07-13 | — | The original plan & decisions doc. |
| [README.md](history/README.md) | ARCHIVE | 2026-07-30 | — | What is archived here. |
| [wire-in.md](history/wire-in.md) | ARCHIVE | 2026-07-16 | — | v2 resolver wire-in log. |
| [review-2026-09/](review-2026-09/README.md) | ARCHIVE | 2026-09-20 | — | Full-tree code review (11 reviewers): security, correctness, perf, docs sync. |

