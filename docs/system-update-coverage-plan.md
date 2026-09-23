# System-wide update coverage — plan

cfs today tracks and updates a machine's **picks** (the curated set). Everything else the OS
knows is upgradable — base packages, dependencies, flatpak runtimes/extensions, snaps — is
invisible to cfs, so the user still reaches for Pop!_Shop / GNOME Software / `apt upgrade`. This
plan makes cfs the **single updater** for a machine *without modeling the system as components*.

Grilled 2026-09-21. The load-bearing reframe: **cfs does not model base-OS / dependencies.** Every
"what's base vs a dep, per OS version, across dist-upgrades" question is answered by the *package
manager*, not by cfs. cfs asks each manager "what's upgradable?" and drives the manager's own bulk
upgrade. Nothing is hardcoded, so a dist-upgrade changes nothing in cfs.

## Locked decisions

- **Enumerate + selectable, NON-component.** System updates come from each manager's own upgradable
  list. Items are **not** routes.hu components — no binding, no `provides`, no version-lock modeling.
  They are the manager's list, surfaced. (Picks stay the curated layer; a picked component that's
  also upgradable shows in its normal picks row, not here — System Updates = *upgradable − managed*.)
- **Surface inside TUI::Components**, not a separate screen — reusing the existing synthetic-group
  machinery. Components already builds an `('(other)', …)` group (menu.py:1703) for installed things
  in no profile, fed by a background orphan scan. Add a sibling synthetic top group **“System
  Updates”** with **tier subprofiles** the user can expand / select / star — “automatic profiles and
  subprofiles you can muck with.” `update all` acts on the top group; expand to select a subset.
- **Within-release only.** Routine package updates via each manager’s own upgrade command. cfs
  **never** runs `do-release-upgrade` / `dnf system-upgrade` / a distro release jump — those aren’t
  reliably automatable (confirmed: Fedora experience). When a release upgrade *is* available, cfs
  shows an **advisory** (like the reboot advisory) and hands it to the user.
- **List everything, grouped by tier.** Base/kernel/libc are shown, not hidden — but bucketed into
  tiers so the list stays edifying rather than a wall. `update all` patches the whole system.
- **De-dup with picks and with holds.** A held (locked) package stays held and is marked, not
  silently upgraded. Upgradables that map to a tracked pick are excluded from this lane (shown in
  their pick row instead).

## Tier taxonomy (coarse, universal, per-driver — apt-rich now, others incremental)

A literal required/important/standard split is **apt-shaped** (Debian `Priority`, read today by
`apt.priority_index` / `orphans._tier`). No other manager has an equivalent: dnf/rpm has `@core`/
`@standard` comps + protected pkgs, pacman has the `base` group, zypper has patterns, apk has
`world`-vs-deps, flatpak has runtimes-vs-apps. So classification is a small set of **coarse buckets**
each driver maps its native notion into, degrading gracefully:

| bucket        | apt (Priority)        | dnf/rpm            | pacman        | flatpak                     | fallback (any) |
|---------------|-----------------------|--------------------|---------------|-----------------------------|----------------|
| **kernel**    | name `linux-image*`   | `kernel*`          | `linux*`      | —                           | name match     |
| **core**      | required + important  | `@core`, glibc     | `base` group  | runtimes/extensions (`.Platform`/`.GL.`/`.codecs`/`.VAAPI`) | libc by name |
| **standard**  | standard              | `@standard`        | —             | —                           | — |
| **apps/tools**| optional + extra      | everything else    | everything    | apps                        | everything else |

A manager with no tier notion → kernel/libc by name, everything else in **apps/tools**. Each driver
contributes what it can; the bucket set is fixed so the grouping is consistent across OSs.

## New primitives to build

1. **`Driver.upgradable_index()`** (batched, parallel to `installed_index()`): `{key: (installed,
   candidate)}` for what the manager reports upgradable. Reads the native index (kept fresh by
   `configsys refresh`, which already runs `apt-get update` et al.). Per-manager:
   `apt list --upgradable` · `dnf -q check-update` · `pacman -Qu` · `zypper -q list-updates` ·
   `apk list --upgradable` · `flatpak remote-ls --updates` (exists) · `snap refresh --list` ·
   `brew outdated` · `rpm-ostree upgrade --check`.
2. **Tier classification** — a `Driver.classify(key) -> bucket` (or a batched tier map). apt reuses
   `priority_index`; others start with name heuristics + group queries, incremental.
3. **Bulk + targeted upgrade** — the manager’s own all-upgrade (`apt upgrade`, `flatpak update -y`,
   `dnf upgrade`, …) for the top group; a targeted form (`apt install --only-upgrade <pkgs>`,
   `flatpak update <ids>`, …) for a selected subset. Held packages excluded. Runs through the same
   confirm + reboot-advisory path as pick ops (“no surprises”: preview what changes first).
4. **Release-upgrade advisory** — a per-OS "a release upgrade is available" probe, surfaced like the
   reboot advisory; never auto-run.
5. **Components integration** — a synthetic **System Updates** group + tier subprofiles built into
   the Components tree/overlay (sibling to `(other)`), reusing select / op-stage / execute. A header
   count chip; `R` refresh already refreshes the index that feeds it.

## Phasing

- **P0 — pipeline proof (this machine): DONE.** `Driver.upgradable_index()` / `held_keys()` /
  `upgrade_all()` (base no-ops) implemented for apt + flatpak + snap; `configsys/sysupdates.py`
  aggregates upgradable − managed picks (`gather`); CLI `configsys updates` (list, grouped by
  manager, `installed -> candidate`, `[held]` marks) + `configsys upgrade --system` (index refresh →
  preview → confirm → each manager's own bulk upgrade → reboot advisory). apt bulk = `apt-get upgrade
  --with-new-pkgs -y` (gets new-kernel ABI, never removes). flatpak is keyed by full REF (not app id)
  so multi-branch runtimes stay distinct rows matched to their own installed version; `update_dedup_key`
  maps a ref back to the app id for the managed-picks exclusion. Verified live (171 apt + 16 flatpak
  upgradable, correct exclusion). Tests in test/test_system_updates.py. No TUI yet.
- **P1 — tiers: DONE.** Fixed `UPDATE_TIERS = (kernel, core, standard, apps)` + `tier_by_name`
  fallback (kernel/libc by name) in driver.py; `Driver.classify_index(keys)` (base = name heuristic)
  overridden by apt (Priority required/important→core, standard→standard, optional/extra→apps, with
  kernel split off by name — reuses origin_index) and flatpak (runtime/app split: `.Platform`/`.Sdk`
  ids → core, else apps). `UpdateRow.tier` carried through `gather`; CLI `updates` /
  `upgrade --system` preview now sub-group each manager by tier, most-fundamental first. Verified
  live (apt: 4 kernel / 46 core / … ; flatpak: 15 runtimes→core, Chrome→apps). Tests extended.
- **P2 — TUI:** the System Updates synthetic group + tier subprofiles in Components; select + upgrade
  + header count.
- **P3 — remaining managers:** dnf / pacman / zypper / apk / brew / rpm-ostree `upgradable_index()`
  + tier classify.
- **P4 — release advisory.**

## Parked / open (defaults, overridable)

- **Lightweight holds in the system lane** — `apt-mark hold` works on any package with no modeling;
  offer a hold from the System Updates row later (not P0). Default: show held, don’t upgrade.
- **firmware (fwupd) lane** — a natural 4th lane; parked.
- **Exact bucket labels + per-manager depth** — coarse buckets are the default; refine per driver as
  real OSs are exercised (podman).
- **Worth gate:** P0–P2 (apt+flatpak+snap, the user’s machine) is the high-value / modest-cost core.
  P3 is breadth; P4 is a nicety. Stop after P2 if the value isn’t landing.
