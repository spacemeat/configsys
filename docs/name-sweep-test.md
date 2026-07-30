# Name-existence sweep — design & tool reference

Status: **SHIPPED** — the sweep is a real, runnable tool: `test/run-name-sweep-in-podman.sh`
(with `test/namesweep-allowlist.hu`), plus the plugin-side `test/run-name-sweep.sh` in the
`configsys-void` / `configsys-proxmox` repos. This doc is the living reference for how it works.

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

### 2. Verifier — per-manager existence query (the container half) — DONE

One container per manager (reuse `test/Containerfile.*`), enable the repos configsys itself uses,
refresh metadata once, then check each name. The query verbs (all read-only, no install):

- **apt** — `apt-cache show "$p"` (enable `universe`+`multiverse`; `apt-get update`)
- **dnf** — `dnf -q info "$p"` (enable RPM Fusion free + EPEL, matching `requires: rpmfusion/epel`)
- **pacman** — `pacman -Si "$p" || pacman -Sg "$p"` (groups like `xfce4`; `pacman -Sy`)
- **zypper** — `zypper -n se -x "$p"` (`zypper -n ref`)
- **apk** — `apk search -x "$p"` (add the `community` repo; `apk update`)

Batch all names in one container run per manager (not one container per package). Emit the set of
**missing** names.

### 3. Differ + report — DONE

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

## Scope & what the first runs caught

The default sweep gates on **all five families** (apt/dnf/pacman/zypper/apk) — all green. Getting
there paid off immediately; the sweep caught, and we fixed:

- **nim** and **lazygit** aren't in Fedora repos → gated / retargeted to the tarball.
- **gcc-cpp** lacked apt/pacman names → gated redhat; **gst-libav** is `gstreamer1-plugin-libav` on
  Fedora → renamed.
- **~14 vulkan/xcb building blocks** were `via: native` ungated — they'd fail if installed on the
  wrong distro → gated to their family.
- a pile of **openSUSE/Alpine renames** (`firefox`→`MozillaFirefox`, `node`→`nodejs-default`,
  `docker.io`→`docker`, `ninja`→`samurai` on Alpine, `python3-pip`→`py3-pip`/`python313-pip`, ...)
  and genuinely-absent packages gated away (ffmpeg needs Packman on openSUSE; gap/maxima/paraview/
  supercollider not in Alpine).

Run a subset with `bash test/run-name-sweep-in-podman.sh zypper,apk`. openSUSE's versioned names
(`python313-pip`, `ffmpeg-7`) will drift as Tumbleweed rolls — the sweep flags it, you bump the
`name:` map. That's the maintenance loop working, not a false alarm.

## Sweeping a plugin OS

A plugin that adds an OS block (Proxmox, Void, …) can reuse this sweep for its own catalog. The
per-manager existence CHECK is split from the base-image SETUP, so a plugin supplies its own image
+ repo setup and reuses the check verb:

```
$ python3 tools/namesweep.py --sweep --plugin <plugin>/routes.hu \
      --context proxmox --manager apt \
      --image docker.io/library/debian:12 --setup <plugin>/test/pve-repo-setup.sh
```

`--plugin` loads the plugin's layers (its `os:` block + components), resolves the whole catalog on
`--context`, collects the `--manager` package names, and verifies them in `--image` (after
`--setup`), reusing the core allowlist for that manager (union in a plugin-local one with
`--allowlist`). The test itself lives WITH the plugin (image + setup are the plugin's business);
core just provides the mode. Two plugins use it:

- **configsys-proxmox** (`apt` on `debian:12` + the PVE repo). Because it checks against real
  Debian, not Ubuntu, it's a *stricter* apt check — it's what caught `perf` naming Ubuntu's
  `linux-tools-generic` (Debian/Proxmox = `linux-perf`).
- **configsys-void** (`xbps` on `void-glibc`). Void diverges from the generic/Debian defaults, so
  the plugin carries a `component-names:` map (§10a of the routing model) for ~10 core components
  (`docker`, `R`, `openjdk21`, `fish-shell`, …) and drops `nmap` (absent on Void); the sweep is
  what keeps that map honest as Void rolls, and unions the plugin's own vendor-SDK allowlist.

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
2. **(done)** per-manager verifier script + `test/run-name-sweep-in-podman.sh`.
3. **(done)** allowlist file (`test/namesweep-allowlist.hu`) + differ.
4. wire into a weekly CI job; surface drift as an issue. *(The plugin repos `configsys-void` /
   `configsys-proxmox` carry their own `test/run-name-sweep.sh`; a scheduled CI job for the core
   sweep is not yet wired.)*
5. *(stretch)* sibling checks: URL HEADs for tarball/`script`, app-id checks for flatpak.
