---
name: update-os
description: Keep configsys correct across OS RELEASES — onboard a new or pre-release of a known OS line (Fedora 45, Ubuntu 26.10, Alpine 3.25, EL 11) and re-verify every live older release: fill its registry entry (releases: on the os block) from its own image, find what it dropped / renamed / newly packages across the whole catalog (per-release podman name sweep, arrivals), the release-pinned bindings that stop short of it, its per-release repos and PPAs, package-manager behavior (driver lifecycle in podman), toolchain and test-fixture drift — then fix what the user approves with release-scoped gates so older releases keep resolving exactly as before. Marks EOL releases frozen. Use when the user says "/update-os <line> [release]", "/update-os *", "Fedora 45 is out/coming", or asks to support a new distro release. A brand-new distro (not a release) is /add-os.
---

# update-os — new releases in, old releases still right

configsys routes per OS release — `when: "fedora >= 43"` (packaged from 43), `not (fedora >= 44)`
(retired in 44), `fedora = 42` (a parallel compiler only that release carries). Each new release
moves those boundaries, and nothing moves them for you: a release-pinned binding simply doesn't
reach Fedora 45, a vendor repo may not publish for it yet, a package-manager rewrite (dnf4 → dnf5)
changes what the driver parses. Meanwhile the older releases are still in use and must stay
correct and updatable. This skill does both:

- **the new release** gets a registry entry read from its own image, a catalog-wide sweep, its
  gaps filled (release-scoped, never by narrowing an older release), and its package manager
  exercised for real;
- **every live older release** is re-swept, so an error in an old gate surfaces too;
- **EOL releases are frozen**: marked `status: eol`, their gates kept, routable and installable,
  no longer swept (their repos move to archive mirrors) unless the user unfreezes one.

The registry is `releases:` on the os block that owns the version line (routes.hu;
docs/routing-model.md §6). The mechanics are `tools/osaudit.py` (`releases`, `facts`, `delta`,
`pinned`, `sweep`, `repos`, `snapshot`/`compare`, `fixtures`). Fixes follow the
**`/add-component`** house rules (`when:` is validity only; a one-line comment on every
non-obvious gate; fallbacks so a component still routes where its native package is gone). A
brand-new distro is **`/add-os`**. Run this BEFORE **`/update-component`**: a component audit
should judge each tool against an OS layer that is already current.

## Arguments

| form | does |
|---|---|
| `/update-os fedora 45` | onboard that release (new, or a prerelease reaching GA), and re-verify the line's live releases |
| `/update-os fedora` | re-verify the line: staleness, the live releases' sweep, the pinned report |
| `/update-os *` | every registered line (the `/review-code` form) — staleness everywhere, then each line |

Flags: `--report-only` (stop after the report), `--no-lifecycle` (skip the podman driver run),
`--unfreeze <release>` (sweep an EOL release too — its image must still reach its repos).

The lines today, each with a registry: `debian`, `ubuntu` (+ the borrowers pop_os!), `fedora` (+
nobara), `fedora_atomic`, `rhel` (rocky/alma/centos/ol/scientific borrow it; keyed by major),
`amzn`, `opensuse_leap`, `alpine` (keyed by series, 3.22), and the own-numbering apt derivatives
`elementary`, `linuxmint`, `zorin`, `lmde`, `mx` — these have no container images, so their
registries are facts and dates only (`note:` names the base release) and the sweeps reach them
through their base. `pikaos` (Debian sid) and `kde_linux` (a build stamp) are scale-roots no
`when:` compares — `releases` prints them as `unversioned`, no registry needed. Rolling blocks
(arch, tumbleweed, void, kali, chimera) have no releases; their drift is the plain name sweep's
(`tools/namesweep.py`) and `/update-component`'s.

## Phase 0 — preflight

1. `git status` (clean before applying). `podman` present? Without it the sweep, facts and
   lifecycle phases can't run — say so and do the offline phases only.
2. `.venv/bin/python tools/osaudit.py releases [line]` — the registry and its staleness:
   `eol-passed` (mark it eol), `prerelease-past-ga` (this run should mark it released),
   `no-registry` (a versioned line with no table — fill it, Phase 1), `no-image` (can't be swept).
3. **What is the newest upstream release?** For each line in scope, check the distro's lifecycle
   (its release page, or `https://endoflife.date/api/<product>.json` — fedora, ubuntu, debian,
   rhel/almalinux, alpine, opensuse, amazon-linux) for a release newer than the registry's, and
   for a branched prerelease image (`podman pull <image>` succeeds). A newer one is in scope even if
   the user named another.
4. **Snapshot before anything changes:** `osaudit.py snapshot <line> --out $RUN/before-<line>.json`
   (every live release's resolution) — Phase 7 compares against it.

`$RUN` = a scratchpad dir for this run.

## Phase 1 — the registry entry (facts from the image)

For the new release (and any live release missing facts):

```
.venv/bin/python tools/osaudit.py facts <line> <release> --image <fully-qualified image>
```

It runs the image and reads VERSION_ID (must equal the key — EL is keyed by its major), codename,
glibc, the repo's python3 and gcc, and the package-manager version, then prints a paste-ready
entry and any mismatch with what the registry already says. Add `status:` (`prerelease` until
GA), `released:` / `eol:` from the lifecycle source (an expected date is fine for a prerelease —
add `note: "expected"`), and keep the image reference fully qualified. For `fedora_atomic`, add
the matching release too (its image is not sweepable — brew is its native; record the facts).

**Compare the facts with the release before it** — every difference is a lead for Phase 5:
- **glibc** rose → nothing to do for a `>=`-gated line, but check the long glibc-floor gates (the
  "`(ubuntu >= 22.04) or (debian >= 12) or …`" lists) name this line at all;
- **python3** changed → the configsys bootstrap floor (≥ 3.10: below it, the release needs a
  python3.X route like EL9's), and the `python3.X` interpreter components (which minors are now
  native, which left);
- **gcc** major changed → the parallel `gcc-NN` / `clang-NN` components and their release pins;
- **manager** version changed (a major: dnf4 → dnf5, apt 2 → 3, apk 2 → 3) → Phase 4 is mandatory,
  and read the driver for version-specific parsing (`configsys/drivers/<mgr>.py`).

Mark EOL releases `status: eol` here too (Phase 0's `eol-passed`).

## Phase 2 — offline: what the registry says will change

```
.venv/bin/python tools/osaudit.py delta <line> <previous> <new>
.venv/bin/python tools/osaudit.py pinned <line>
```

- **`delta`** — every component whose own unit resolves differently on the new release (lost /
  gained / changed; dependents that only follow a changed dependency are folded). For a release
  no gate names yet this is usually small — it is the `=` and `<` gates speaking.
- **`pinned`** — every binding whose `when:` bounds the line's version, with the registered
  releases it covers:
  - `stops-short` — covers older releases, not the newest: a **retirement** (read its comment:
    "retired from Fedora 44" — confirm with the sweep that it is still gone) or an **upper bound
    that must move** (a vendor repo that now publishes for the new release);
  - `exact` / `release-pin-gap` — a per-release binding (`fedora = 42` gcc14): the new release
    needs its own line, or the component honestly doesn't exist there (say which);
  - `no-live-release` — a gate that only reaches EOL releases: frozen, leave it.

## Phase 3 — podman: the per-release sweep (names, retirements, arrivals)

```
.venv/bin/python tools/osaudit.py sweep <line> --json > $RUN/sweep-<line>.json   # every live release
.venv/bin/python tools/osaudit.py sweep <line> <new release>                         # just the new one
```

Per release it resolves the whole catalog in that release's context and checks every native name
in that release's image (namesweep's checks + allowlist, the line's repo setup). Read:
- **missing** on the new release → retired or renamed there. Find out which (packages site:
  packages.fedoraproject.org, packages.ubuntu.com, packages.debian.org, pkgs.alpinelinux.org,
  software.opensuse.org; the distro's change list for that release). A rename gets a
  release-split binding; a retirement gets `not (<line> >= N)` on the native binding PLUS a
  fallback that still routes there (flatpak, brew, tarball, …, the add-component §3 matrix) — or an
  honest "no method on N" if none exists.
- **missing on an OLDER live release** → an old gate is wrong (the package arrived later than the
  gate says, or was retired earlier). Fix the gate's bound — this is the "keep old releases
  correct" half, and as important as the new release.
- **boundaries** — names missing on some swept releases and present on others: the exact release
  where each moved; gate there.
- **arrivals** — names now in the release's repos for a component that doesn't route natively
  there: `release-gated` (its own native binding is gated off by a version bound — the bound can
  move, or it was retired and has COME BACK), `named` (its binding names this manager's package but
  is gated off the family), `name-only` (low confidence: the component's own name exists — verify
  it is the same software before proposing a native binding). Arrivals are how gaps get filled.

An `allowlisted` name is expected missing (test/namesweep-allowlist.hu, with a reason); a name
there that now exists should leave the allowlist.

## Phase 4 — the new release for real: repos and the package manager

**Per-release sources** (network):

```
.venv/bin/python tools/osaudit.py repos <line> <new release>
```

probes every source whose URL depends on the release — dnf/zypper `repo-url` + `pubkey-url` with
`$releasever`, apt `source-line` with `$CODENAME`, PPAs for the codename — and flags a
**literal codename** in a source line (it names another release: use `$CODENAME`). A 404 on a
prerelease is normal (vendors publish at or after GA): propose a release gate on that binding so
the new release falls through to a fallback until the vendor publishes, and list it for the GA
recheck. A 404 on a released release: the vendor dropped it, or the URL scheme changed — research.

**Driver lifecycle** (podman; skip with `--no-lifecycle` only when the manager version is
unchanged). The real install → lock → unlock → remove cycle on the new release:

| line | harness |
|---|---|
| fedora | `FEDORA=<rel> bash test/run-dnf-in-podman.sh` (+ `run-fedora-toolchain-in-podman.sh <rel>`) |
| rhel | `bash test/run-rhel-toolchain-in-podman.sh almalinux:<rel>`, `bash test/run-el-rpmfusion-in-podman.sh almalinux:<rel>` |
| ubuntu / debian | `BASE=ubuntu:<rel>` (or `debian:<rel>`) `bash test/run-in-podman.sh` |
| opensuse_leap | `bash test/run-zypper-in-podman.sh btop registry.opensuse.org/opensuse/leap:<rel>` |
| alpine, amzn | no harness yet — report it as a gap; don't improvise a destructive one |

A failure is a driver finding (often parsing: a new output format). Read the driver, reproduce
the command in the container by hand, and propose the fix with a test.

## Phase 5 — toolchains, fixtures, the long gates

- The Phase 1 fact differences (python3 / gcc / glibc / manager) → walk the components they touch:
  `python3.1N`, `gcc-NN`, `clang-NN`, the jdks, the glibc-floor gates. `delta` already shows the
  routing effect; this is about what SHOULD route there now.
- **Fixtures:** `.venv/bin/python tools/osaudit.py fixtures` — the golden contexts
  (`test/test_golden.py` `CONTEXTS`), the single-release name sweep (`tools/namesweep.py`
  `MANAGERS`) and the Containerfile defaults, against the registry. A newly RELEASED release gets a
  golden context (prereleases don't); keep the older contexts — they are the old-release guard.
  Bump `MANAGERS` to the newest released release. Containerfile defaults stay unless the user asks.

## Phase 6 — report and decide

Write `$RUN/report.md` and show the user, in the terminal:
- the registry changes (new entry, status moves to released / eol);
- per category, numbered: **broken on the new release** (missing names with no fallback, driver
  failures, dead repos), **old-release corrections** (wrong gates on live releases), **gaps to
  fill** (release-pin gaps, arrivals, upper bounds that can move), **prerelease waits** (vendor
  repos not yet published — recheck at GA), **fixtures**;
- each with the proposed edit (exact humon) and its evidence (the sweep line, the URL fetched, the
  harness output).

Ask what to apply (`AskUserQuestion`: "all broken + corrections + gaps", numbers, or none). With
`--report-only`, stop here (registry edits included — they are facts, but still the user's call).

## Phase 7 — apply, then prove older releases unchanged

Apply serially (routes.hu is one file; never parallel edits). Rules:
- **Scope every change to the releases it is true for.** A retirement is `not (<line> >= N)`, an
  arrival is `<line> >= N`, a rename is a release-split pair — never an edit that changes what an
  older release resolves unless that older release is the thing being corrected.
- Keep the add-component house rules: a one-line `//` comment with the release and the reason
  ("retired from Fedora 45", "packaged from Ubuntu 26.04"), `attrs:`/`description:` untouched, a
  fallback wherever a native package leaves.
- Registry entries: facts as read, statuses as decided.

Then validate:
1. `osaudit.py compare $RUN/before-<line>.json` — **every older release unchanged** except the
   corrections the user approved for it (a unit whose package is the same but whose fields moved —
   a repo URL, a key — shows as `~fields`). Anything else changing on an old release is a leaked
   edit: fix it before going on. (Forgot the Phase 0 snapshot? `git show HEAD:routes.hu > F` and
   `osaudit.py snapshot <line> --routes F --out …` takes it from HEAD.)
2. `osaudit.py sweep <line>` again — the fixed names are gone from `missing`; `osaudit.py repos`
   again for fixed sources.
3. `configsys --home $RUN/home --os <line>:<new release> check` and the usual spread (pop_os!,
   fedora, arch, alpine, opensuse, rhel, fedora_atomic, void, void_musl) — 0 errors, warnings not
   up; no `os-release` warnings. Use the sandbox `--home`: without it `check` also reads YOUR config,
   and your own pins (an `appImage` pin on a musl box) show up as errors that aren't the routes'.
4. Golden: `CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_golden.py -q`, then the
   semantic diff vs HEAD (add-component §8) — changes only in the edited components (and a new
   context, if one was added).
5. `.venv/bin/python -m pytest test/ -q` — all green.

## Phase 8 — commit and follow-ups

1. Commit locally, never push (base identity; the attribution line the system provides):
   `os: <line> <release> — <registry change>; <n> gates, <m> fixes` with one body line per change.
2. **A prerelease** stays `status: prerelease`. Tell the user what waits for GA (vendor repos, the
   golden context) and that `/update-os <line> <release>` at GA finishes it (offer to schedule it,
   once, if they'd like a reminder).
3. Update the os-releases memory/plan if the run changed what's supported.

## Notes

- **The registry is facts, not policy.** It says what a release ships; whether configsys routes
  something there is still the components' `when:`. The resolver doesn't read `releases:` (yet —
  docs/todo/os-releases-plan.md phase 5).
- **EL is keyed by major** (`9`, `10`): its `$releasever` is the major, and minor-release drift
  inside a major is the plain sweep's.
- **Plugin OS lines** (a plugin's own os block with `releases:`): osaudit covers core routes only;
  use `tools/namesweep.py --plugin` per release and the plugin's own repo for edits.
- Cost: offline phases take seconds; a sweep is ~10 min per release (the catalog index is one
  query, but every arrival candidate that ISN'T in the repos falls back to the manager's slow
  per-name query); a lifecycle harness ~5–10 min. Run the sweep in the background and do Phase 2 and
  the repo probes meanwhile.
- **Verify what the tools can't see.** The sweep checks names that resolve; a binding that reaches
  NO live release (a `= 41` pin after 41's EOL) is invisible to it — `pinned` is what finds those,
  and a quick `dnf repoquery` / `apt-cache policy` per live release settles what to pin next.
- **A 404 on every release is not a release problem** — compare `repos` across the live releases
  first. The first run found RPM Fusion's per-release key URL dead since Fedora 33 and Jellyfin's
  Fedora repo deprecated: old-release corrections, found by the new-release probe.
