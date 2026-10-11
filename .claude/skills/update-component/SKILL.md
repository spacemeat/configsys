---
name: update-component
description: Audit existing configsys components for upstream drift and fix what the user approves — repo renames/archival, license and other attrs changes, broken or newly-available install methods, asset/version-source breakage, `when:` gating (glibc floors, arch support), requires/suggests, -dotfiles/glue/service changes, deprecation/successors. Use when the user says "/update-component <names...>", "/update-component *" (all of base routes.hu), "/update-component <plugin>/*" (all of one plugin), or asks to check/refresh/re-verify components. Fans out read-only audit subagents for large scopes, aggregates one report, applies only approved fixes.
---

# update-component — audit components for upstream drift

Components rot quietly: a repo moves, a release renames its assets, a package leaves the AUR for
`[extra]`, a project relicenses to BSL or grows telemetry, a tool moves its config under XDG. This
skill finds that drift and fixes what the user approves. It is the maintenance counterpart of
**add-component** (`.claude/skills/add-component/SKILL.md`) — every fix you apply follows that
playbook's house rules (`when:` is validity only, a `description:` + `attrs:` on every real
component, a one-line comment on non-obvious gating, plugin data in the plugin's own repo).

Two halves:
- **Mechanical** — `tools/compaudit.py`: enumerates the scope, groups each component with its
  companions (`-dotfiles`/`-glue`/`-service`/`-group`) into one *unit*, and probes upstreams with a
  cache (GitHub rename/gone/latest release [+archived/license with a token — see Phase 0], and asset globs
  checked the way the driver resolves them — latest, then recent releases incl. prereleases,
  case-insensitive; Flathub published/end-of-life/renamed; AUR missing/promoted-to-`[extra]`/
  orphaned/out-of-date; Homebrew formula missing/alias/renamed/deprecated/disabled/keg-only on
  Linux/macOS-only (one fetch of the full formulae.brew.sh index); crates/PyPI/npm
  missing/deprecated; and a static check for x86-64-only
  downloads with neither a `cpu-names:` map nor a `cpu:` gate). ~40 s for the whole catalog. A per-unit **ledger** makes
  routine `*` runs incremental.
- **Judgment** — audit subagents, one per batch of units, doing the web research the probes can't.
  They are READ-ONLY on the routes; they write findings files. You aggregate, the user decides,
  you apply serially.

## Arguments

Space-separated targets, plus optional flags:

| target | scope | units |
|---|---|---|
| `ripgrep yazi` | base routes.hu | those (a companion name selects its parent's unit) |
| `*` | base routes.hu | all, **incremental** (see ledger) |
| `configsys-blender/*` | that plugin | everything its data files define or amend |
| `configsys-source/ripgrep` | that plugin | that unit — only the plugin's layer is audited |

Several targets may mix scopes (`* configsys-blender/*`) — run phases 1–3 per scope, then one
combined report. Flags: `--full` (ignore the ledger: deep-audit every unit), `--due-days N`
(default 30), `--report-only` (stop after the report; apply nothing).

A plugin name resolves to its **dev checkout** — `$CONFIGSYS_PLUGIN_SRC/<name>`, else a sibling of
this repo (`~/src/<name>`) — never the synced clone under `~/.config/configsys/plugins/` (which
`plugin sync` overwrites; compaudit falls back to it only to READ). Edits go to the dev checkout.

**Named targets are always deep-audited.** `*` / `<plugin>/*` deep-audit only units that are
*due*: never audited, definition changed since the last audit, last audited > `--due-days` ago,
or flagged by a probe this run. Everything is still probed every run (it's cheap).

## Phase 0 — preflight

1. `git status` in each scope's repo. A dirty tree is fine to audit, but say so — you'll want a
   clean diff to apply fixes into.
2. **GitHub token — ALWAYS check, ALWAYS remind.** The user has said they WILL forget this, so it
   is never skipped. Run `.venv/bin/python tools/compaudit.py token` (exit 0 = a token is
   available from `$CONFIGSYS_GITHUB_TOKEN`, `$GITHUB_TOKEN`, or a logged-in `gh` CLI via
   `gh auth token` — no export needed). Exit 1 = none: without it the probes still catch
   renames / gone repos / releases / asset globs, but SKIP archived-repo and license-change facts.
   Then, BEFORE anything else in your reply, show this reminder as its own block:
   > ⚠ **No GitHub token.** Archived-repo and license-change checks will be skipped. One-time fix
   > (it persists): type `! gh auth login` — compaudit then picks the token up automatically.
   - Whole-scope run (`*`, `<plugin>/*`, `--full`): ask (AskUserQuestion) "Log in first" vs
     "Continue without license/archived checks". A degraded full run is expensive to redo. If they
     log in, re-run `compaudit.py token` to confirm before continuing.
   - Named targets: remind and continue.
   - Either way, repeat the one-line reminder at the END of the Phase 3 report (`summary.json`
     has `"github_token": "none"` for a degraded run) — that's where the user is reading when
     they're done.
3. For `*`/`--full`, state the scale before fanning out: "N units due → M subagents". A first full
   base run is ~660 units / ~44 agents at batch 15; later runs are incremental. Proceed without
   waiting unless the user has said to confirm large runs.

## Phase 1 — mechanical scan

```
.venv/bin/python tools/compaudit.py scan <scope> [names...] [--full | --due-days N] --batch-size 15
```
(`<scope>` = `base`, or the plugin name.) It prints the run directory and writes there:
- `summary.json` — `units_total`, `units_due`, `due_reasons`, `skipped_recent`, and every
  `probe_findings` entry (keyed by unit) — including units NOT due for a deep audit.
- `batch-NN.json` — the due units: each unit's raw per-layer spec (`layers[].spec`, with
  `source`, `line`, and `in_scope` marking which layer is this scope's), `probes` (targets),
  `probe_facts` (what upstream said: latest tag + asset list, flatpak/AUR/registry facts),
  `probe_findings`, and `glue_files` (shipped variants per referenced `glue:`; an empty list = a
  broken glue reference).

`compaudit.py list <scope>` shows the units without probing.

## Phase 2 — deep audit (fan-out)

- **≤ 3 units:** do the audit yourself, following the brief below, no subagents.
- **More:** one `general-purpose` subagent per batch file. Launch them **in parallel, up to 10 per
  message** (several messages for more batches; don't wait for one wave to finish before you start
  aggregating it). Give each the brief below with `{BATCH}`, `{OUT}`, `{NN}` and `{SCOPE_ROOT}`
  filled in. Don't set a model or effort unless the user asked for one.
- Subagents write `{OUT}/findings-{NN}.json` and reply with ONE line (counts). Don't ask them to
  return findings in their reply — 40 agents' worth would flood your context; you read the files.
- If an agent fails or returns without writing its file, re-run that batch once; if it fails
  again, list its units as "not audited" in the report (and don't `record` them).

### The subagent brief (send verbatim, placeholders filled)

> You are auditing configsys components for upstream drift. configsys (repo:
> /home/schrock/src/configsys — read its CLAUDE.md; routing rules in docs/routing-model.md and
> docs/principles.md; attrs vocabulary in docs/component-attrs.md; the add-component playbook in
> .claude/skills/add-component/SKILL.md) routes each component to install methods ("bindings":
> `{ via: <driver>  when: "<os expr>"  ...}`) across Debian/Ubuntu, Fedora/EL, Arch, openSUSE,
> Alpine, Void and Fedora Atomic.
>
> Your batch: `{BATCH}` (JSON). Each unit = a component + its companions. For each component,
> `layers[]` holds its raw definition per layer file; audit ONLY layers with `in_scope: true`
> (others are context — e.g. the base definition a plugin amends). `probe_facts` /
> `probe_findings` are already-gathered upstream facts: build on them, but they are heuristics —
> when one looks wrong, check how the driver really behaves (configsys/drivers/,
> configsys/versions.py) and report the false positive as a `note`. Do NOT call api.github.com
> (rate-limited) — use github.com web pages via WebFetch if you need more.
> Scope root (where in-scope files and glue/ live): `{SCOPE_ROOT}`.
>
> You are READ-ONLY: do not edit any file except your output file. For every unit, check:
> 1. **Identity** — upstream alive? renamed/moved (GitHub→Codeberg etc.)? archived/abandoned
>    (archived, or no release in ~2 years)? a successor fork that the ecosystem moved to
>    (exa→eza, redis→valkey)? binary renamed? Is `description:` still accurate (real binary in
>    backticks)?
> 2. **Attrs** — license still matches the license tags (relicensing to BSL/SSPL/source-available/
>    proprietary is high-value)? telemetry/account/cloud/ads/electron tags still true (look for
>    new telemetry, opt-in vs opt-out)? interface/role tags right? Missing `attrs:` on a real
>    component?
> 3. **Each in-scope binding still works** — native package names still exist where gated
>    (packages.ubuntu.com, packages.debian.org, packages.fedoraproject.org, archlinux.org/packages,
>    pkgs.alpinelinux.org, software.opensuse.org, Void's xbps-src templates on GitHub); EPEL still
>    carries it for `rhel` bindings; vendor apt/dnf repo URL + key still valid (fetch
>    `pubkey-url`/`repo-url`; keys rotate); `url:`/install-script URLs live; asset globs vs
>    `probe_facts.latest_assets` (also check the `$ARCH` spelling — `aarch64` vs `arm64`, `x86_64`
>    vs `amd64`); `version:` source still finds the right tag (tag scheme, `strip-v`, `tag-re`,
>    prereleases-only projects).
> 4. **Gating** — upstream's glibc floor rose (a binary now needs newer glibc → narrow `when:`)?
>    new arch builds (aarch64)? a distro newly packages it (widen a native `when:`) or dropped it?
>    musl builds appeared/disappeared? Remember `when:` states validity only, never preference.
> 5. **requires/suggests** — new runtime deps (libfuse3 vs 2, webkit2gtk-4.1), toolchain floors
>    (MSRV for cargo/source, Go version for go-install) that should be versioned requires.
> 6. **New or removed methods** — now packaged somewhere it isn't routed (Ubuntu universe, Debian,
>    Fedora, EPEL, Arch extra — AUR packages that got promoted vanish from the AUR — Alpine,
>    openSUSE, Void, Flathub, snap)? a CLI tool, toolchain or server with no `{ via: brew  name:
>    <formula> }` binding while Homebrew has a Linux formula (add one, no `when:` — but not for a
>    library, a formula keg-only on Linux, or curl/git; add-component §3 "Homebrew")? upstream
>    now ships a .deb/.rpm/AppImage/musl tarball? a method gone (Flathub delisted, AUR deleted,
>    PPA dead, brew formula disabled)?
> 7. **Config & shell** — config path still right (XDG moves, file renames, format changes)? a
>    tool that now keeps config but has no `-dotfiles` companion, or a `-dotfiles` pointing at a
>    path the tool no longer reads? glue still correct (changed `init` syntax for shell hooks,
>    completions, PATH for `~/apps` installs)? `glue_files` empty for a referenced glue = broken.
>    `-service` unit / `-group` names still right?
>
> Report only real problems or opportunities WITH evidence (a URL you actually fetched). No
> "verified OK" entries. Prefer breadth: a quick pass on every unit, deep digging only where
> something smells. Write `{OUT}/findings-{NN}.json`:
> ```json
> {"batch": "{NN}", "audited": ["<every unit you actually checked>"],
>  "findings": [{
>    "unit": "<unit>", "component": "<component>",
>    "severity": "broken | drift | opportunity | note",
>    "category": "<slug: repo-renamed, repo-archived, successor, license, telemetry, attrs, description,
>                 binary-rename, binding-broken, asset-glob, version-source, when-gating, glibc-floor,
>                 arch-support, requires, new-method, method-gone, native-name, epel, vendor-repo,
>                 dotfiles, glue, service, group, other>",
>    "binding": "via:<x> when:\"<expr>\"  (or null for component-level)",
>    "summary": "<one sentence>",
>    "evidence": ["<url>", "..."],
>    "current": "<the exact current humon text/field>",
>    "proposed": "<exact humon replacement or new binding, ready to paste; or a short instruction>",
>    "confidence": "high | medium | low"}]}
> ```
> Severity: **broken** = a binding fails today; **drift** = works but the data is now wrong
> (rename, license/attrs, description, config path, deprecation); **opportunity** = a better or
> additional method exists, or a dead method can go; **note** = FYI / low confidence.
> Reply with exactly one line: `batch {NN}: <n> units audited, <b> broken, <d> drift, <o> opportunity, <t> note`.

## Phase 3 — aggregate and report

1. Merge every `findings-NN.json` with `summary.json`'s `probe_findings` (probe findings for units
   that weren't deep-audited still count). Dedupe: a probe finding and an agent finding about the
   same unit + category + binding are one entry (keep the agent's richer `proposed`); an agent
   `note` that refutes a probe finding drops it.
   **Group cross-cutting patterns:** when one category hits many units (e.g. `arch-unguarded` on
   dozens of tarballs), present it as ONE item listing the units. The right fix for a pattern is
   often a single driver/model change (like `cpu-names:` was for arch-unguarded) rather than N route
   edits — say so, and let the user choose between the systemic fix and per-unit edits.
2. Sanity-check before presenting: drop findings without evidence, and spot-verify every
   **broken** finding yourself (one fetch each) — a false "broken" is the most expensive kind.
3. Write `<run dir>/report.md`: severity sections (broken → drift → opportunity → note), each
   finding numbered, with unit, binding, summary, evidence, and the proposed edit.
4. Show the user, in the terminal: counts per severity; every **broken** and **drift** finding
   (number, unit, one line); the opportunity/note counts (offer to list them); units not audited
   and why. If any scope ran without a GitHub token, end with the reminder line (`! gh auth
   login` once, then re-run for license/archived checks). For a large report, offer it as a page. Then ask what to apply — e.g. "all broken +
   drift", specific numbers, or nothing. With `--report-only`, stop here (still do Phase 6's
   `record`).

## Phase 4 — apply (only what the user approved)

Apply serially yourself — never let subagents edit (parallel edits to routes.hu collide). For each
approved finding:
- Edit the IN-SCOPE layer only: base findings → `routes.hu` / `config.hu` / `glue/`; plugin
  findings → the plugin's dev checkout (its data `.hu`, `profiles.hu`, `glue/`). A problem found in
  a base binding during a plugin-scope run is reported, not fixed there.
- Follow add-component's rules: comment non-obvious gating, keep `attrs:` complete, `name:` maps
  for per-distro names, add-component §4 for a new `-dotfiles`/glue companion.
- **Removals and successor swaps are the user's call.** Never delete a component, binding, or
  profile membership unless that exact finding was approved; for a dead project, prefer proposing
  the successor (or `standing: never-auto` for a still-working-but-abandoned method) and let the
  user choose.
- Renames of a COMPONENT name (not just its repo) ripple: profiles in `config.hu`/plugin
  `profiles.hu`, `pins:` users may hold, companions. Flag it rather than doing it silently.

## Phase 5 — validate

Same gates as add-component §7–9, with one twist for the golden:
1. `configsys --os <os> check` across pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic/void/
   void_musl — 0 errors, warning count not up.
2. Regenerate the golden (`CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py
   -q`) and semantic-diff vs HEAD (add-component §8's script). Changes are EXPECTED here — but only
   in the units you edited (and anything that `requires` them). Any other key changing means an
   edit leaked into unrelated routing: investigate before committing.
3. Re-run `compaudit.py scan <scope> <edited units>` — the fixed probe findings should be gone.
4. Changed native names → `bash test/run-name-sweep-in-podman.sh <manager>` (if podman is
   available; else say it wasn't run). Changed `version:`/asset → `configsys versions <comp>
   --refresh` resolves the current tip.
5. `.venv/bin/python -m pytest test/ -q` — all green.

## Phase 6 — record and commit

1. Record every unit that was actually deep-audited (whether or not it had findings, whether or
   not fixes were applied — declined findings resurface when the definition changes, after
   `--due-days`, or whenever a probe still flags them):
   `.venv/bin/python tools/compaudit.py record <scope> <units...>`. Record AFTER applying fixes, so
   the ledger stores the fixed definition's hash. Never record units that weren't audited.
2. Commit locally — base and each plugin repo separately — never push:
   ```
   git -c user.name="Trevor Schrock" -c user.email="spacemeat@gmail.com" commit -m "components: update-component audit — <scope>

   <one line per applied fix: unit — what changed (finding category)>

   Audited N units (M probe + K deep findings; A applied, D declined). check: 0 errors across
   <OSes>. Golden: changes confined to the edited units.

   Co-Authored-By: <the attribution line the system provides>"
   ```
   Plugin commits need `configsys plugin sync` + `plugin trust` to take effect locally — say so.

## Notes

- The probe cache (`~/.cache/configsys/compaudit/http`, TTL 24h, `--ttl` to change) makes a re-run
  the same day nearly free; `--offline` probes from cache only.
- Repology's API refuses this client (403), so distro-presence questions are the subagents'
  (web lookups) plus the podman name sweep.
- Probe categories: `aur-promoted` = the AUR package was deleted because Arch moved it into
  `[extra]`/`[core]` — the fix is `{ via: native when: "arch" }`; `aur-missing` with no official
  package = renamed or dropped (research it); `asset-glob-miss` = no recent release carries the
  asset (`probe_facts.latest_assets` lists what does — usually an arch-token change like
  `aarch64`→`arm64`); `asset-not-in-latest` = only an older release has it (upstream dropped it?);
  `brew-renamed` = the formula's old name (use the new one); `brew-alias` = works, but an alias
  can be repointed (`openssl` → `openssl@4`) — name the real formula; `brew-keg-only` = keg-only
  on Linux (a versioned formula like `openjdk@21` — not on PATH), so the brew binding (or a
  native `brew:` name on fedora_atomic) installs something unusable — drop it or route atomic
  elsewhere; `brew-deprecated`/`brew-disabled` = on its way out / already uninstallable;
  `prerelease-only` = resolves from a nightly/prerelease (rolling version, updates invisible);
  `arch-unguarded` = an x86-64-only download with no cpu gate (wrong binary on aarch64) — fix with
  `$ARCH` + `cpu-names:` (docs/routing-model.md §7), `{ x86_64: … }` alone if there's no arm64 build.
- Cost: a trial audit of 5 units took one agent ~7 min and ~110k tokens, so a first `--full` base
  run (~660 units, ~44 agents) is large — tell the user before fanning out. Routine `*` runs are
  much smaller: the ledger skips units audited within `--due-days` whose definition hasn't
  changed and that no probe flags.
