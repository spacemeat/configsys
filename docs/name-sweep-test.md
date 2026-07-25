# Name-existence sweep — design sketch (future work)

**Goal:** catch the single most likely cross-distro failure — a native package being **renamed or
removed** (redis→valkey, Fedora dropping `sagemath`, a `-dev` suffix change) — automatically,
before a user hits it. This does NOT install anything; it only asks each distro's repos "does this
package exist?". Fast, container-only, no kernel/GPU/GUI/hardware needed, so it's fully automatable
(unlike the real-install matrix).

## Why this is the high-value cheap test

configsys's routing is already frozen by the golden gate (every component × 9 contexts). What the
golden CANNOT know is whether the package *name* it resolves to still exists upstream — repos drift
under us. This sweep closes exactly that gap, and only that gap. It's the 20% that catches 80% of
real breakage.

## Architecture — three stages

```
  extractor (host, Python)        verifier (container, per manager)      differ
  resolve every component     ->  query each pkg exists in real repos ->  report renames/removals
  collect native pkg names        (apt-cache / dnf / pacman / ...)        (exit nonzero on drift)
```

### 1. Extractor — DONE (`tools/namesweep.py`)

Resolves every component in a representative context per manager (ubuntu24=apt, fedora42=dnf,
arch=pacman, opensuse=zypper, alpine=apk) and collects the **native** package names each maps to —
respecting `when:` (only what routes there) and `name:` (the real per-distro name). Non-native
units (flatpak app-ids, pipx/npm/cargo dists, tarball URLs, `script`) are skipped — a different
verification. Current volume: **~130–150 packages per manager** (~675 total with overlap).

```
$ python3 tools/namesweep.py                 # apt 138 / dnf 140 / pacman 150 / zypper 129 / apk 128
$ python3 tools/namesweep.py --manager apt   # one name per line -> feed a container
$ python3 tools/namesweep.py --json          # {manager: {pkg: [components]}}
```

It already reflects known drift: `apt=redis-server`, `dnf=valkey`, `pacman=valkey`.

### 2. Verifier — per-manager existence query (the container half)

One container per manager (reuse `test/Containerfile.*`), enable the repos configsys itself uses,
refresh metadata once, then check each name. The query verbs (all read-only, no install):

- **apt** — `apt-cache show "$p"` (enable `universe`+`multiverse`; `apt-get update`)
- **dnf** — `dnf -q info "$p"` (enable RPM Fusion free + EPEL, matching `requires: rpmfusion/epel`)
- **pacman** — `pacman -Si "$p" || pacman -Sg "$p"` (groups like `xfce4`; `pacman -Sy`)
- **zypper** — `zypper -n se -x "$p"` (`zypper -n ref`)
- **apk** — `apk search -x "$p"` (add the `community` repo; `apk update`)

Batch all names in one container run per manager (not one container per package). Emit the set of
**missing** names.

### 3. Differ + report

Missing names → look up the components that map to them (the extractor's reverse map) and print,
e.g. `dnf: 'sagemath' (component: sagemath) NOT FOUND`. Exit non-zero if any survive the allowlist.

## The allowlist (avoid false alarms)

Some names are *expected* to be unfindable by this sweep even though the routing is correct:

- packages only in a repo we deliberately don't enable in the check (AUR, a COPR, Packman);
- a component intentionally gated so it declines on a manager (already handled — the extractor
  won't emit it there);
- brand-new packages not yet mirrored.

Keep a small, commented `test/namesweep-allowlist.hu` — `{ dnf: [ ... ]  apk: [ ... ] }` — and
subtract it before failing. Every allowlist entry needs a one-line reason (so it's revisited, not
forgotten). A found-but-allowlisted name should *warn* ("allowlist entry no longer needed").

## Gating & cadence

- **NOT part of `pytest`** — it's networked and container-bound. It's a separate `run-name-sweep-
  in-podman.sh`, like the other `run-*-in-podman.sh` scripts.
- Run **on a schedule** (weekly cron / CI) and on-demand before a release. Repo drift is slow, so
  weekly is plenty; a failure is a heads-up, not a build blocker for unrelated work.
- Wall-clock: 5 container builds + 5 metadata refreshes + ~675 cheap queries ≈ a few minutes.

## What it deliberately does NOT do

- Install anything (that's the representative integration tier).
- Check flatpak app-ids, npm/pipx/cargo/gem dist names, tarball URLs, or `script` endpoints —
  each is a separate, lighter check (an HTTP HEAD for URLs; `flatpak remote-info` for app-ids;
  a registry API for dist names). Worth their own sketch later; the native sweep is the first win.
- Cover managers/OSes without a Containerfile (fedora_atomic/brew, macOS, Windows).

## Roadmap

1. **(done)** extractor `tools/namesweep.py`.
2. per-manager verifier script + `run-name-sweep-in-podman.sh` (reuse the sweep pattern already in
   the tree).
3. allowlist file + differ.
4. wire into a weekly CI job; surface drift as an issue.
5. *(stretch)* sibling checks: URL HEADs for tarball/`script`, app-id checks for flatpak.
