# OS releases: a registry, `/add-os`, `/update-os`

> **Status: IN PROGRESS** — phases 1–3 being built 2026-11-07; phase 4 (the first `/update-os
> fedora 45` run) and phase 5 (engine uses) not started.

## Why

configsys routes per OS *release* (`when: "fedora >= 43"`, `not (fedora >= 44)`, `fedora = 42`), but
nothing records which releases exist or are supported. That knowledge is scattered across `when:`
expressions, the golden's fixed contexts (`test/test_golden.py` `CONTEXTS`), container defaults
(`Containerfile.fedora` = 41), and the name sweep, which checks exactly one release per manager
(`tools/namesweep.py` `MANAGERS`: fedora 44, ubuntu 24.04, alpine 3.24). So:

- older releases are never verified — F41–F43 are correct only if nobody slipped;
- a new release (Fedora 45) gets no systematic pass: release-pinned bindings (`fedora = 42` gcc14 /
  clang19) don't reach it, retirements (`not (fedora >= 44)`) and arrivals (`fedora >= 43`) are
  found by accident, per-release repos (`$releasever` in RPM Fusion / Jellyfin / MongoDB, PPAs per
  Ubuntu codename) are never probed for it, and a package-manager change (dnf4 → dnf5) is found
  by a failing install.

## Decisions (the user, 2026-11-07)

- **The registry lives in routes.hu `os:` blocks** — `releases:` on the block that owns a version
  line. One source of truth; maintenance tools read it now; the engine may use it later (phase 5).
- **Old releases: swept while live, frozen at EOL.** Every upstream-supported release is verified
  each run. At EOL a release keeps its gates and stays routable/installable, is marked
  `status: eol`, and is no longer swept (its repos move to archive mirrors) unless unfrozen on
  request.
- **New-release depth: names + repos + driver lifecycle** — the per-release name sweep, probes of
  every per-release repo URL / PPA, and the native driver's real install → lock → unlock → remove
  in podman on the new release.
- **Pre-releases are in scope**, as `status: prerelease` (gaps filled against the branched image,
  rechecked at GA, kept out of the golden until released).
- `/add-os` takes over `add-component/os-block.md`; `/update-os` owns release-level drift (what a
  release added, dropped or renamed); `/update-component` keeps per-tool drift. `/review-code`
  chains `/update-os` → `/update-component` → fixes → `/update-docs`.

## Phases

1. **Schema** — `releases:` on OS blocks: `OsCascade.version_line` / `releases`, a `check` lint
   (`routecheck.release_registry_issues`), docs (routing-model §6, config-format), tests.
2. **`tools/osaudit.py`** — `releases` (the table + staleness: an EOL date passed, a prerelease past
   its release date), `delta LINE OLD NEW` (offline: how every component's resolution differs
   between two releases — lost / gained / changed), `pinned LINE` (bindings with an upper bound or
   an exact release on the line, and the releases each covers — the gaps a new release falls
   into), `repos LINE RELEASE` (probe per-release repo URLs, PPAs and codename source lines),
   `sweep LINE [RELEASE…]` (the podman name sweep per release, reusing namesweep), `fixtures` (the
   golden contexts, namesweep defaults and Containerfile defaults vs the registry).
3. **Skills** — `/add-os` (from os-block.md, plus the registry entry), `/update-os`, the
   add-component dispatch, `/update-component`'s scope note, `/review-code`'s chain; CLAUDE.md,
   README.
4. **First run** — populate the registry (fedora + fedora_atomic first, then every line) and run
   `/update-os fedora 45`.
5. **Engine uses (later, each its own decision)** — `check` / `!` note an EOL or unknown-newer
   release on this machine; per-release `provides: { glibc: … }` so the 14 copies of the long
   glibc-2.35 distro list become `requires: { glibc: ">=2.35" }` (docs/versioned-requires.md's
   "env-provided capabilities" slice).
