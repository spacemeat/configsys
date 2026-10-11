# Name-existence sweep — design & tool reference

> **Status: REFERENCE** — the native package-name sweep (`test/run-name-sweep-in-podman.sh` →
> `tools/namesweep.py`, allowlist `test/namesweep-allowlist.hu`) and its plugin-OS mode; maintained.

**Goal:** catch the single most likely cross-distro failure — a native package being **renamed or
removed** (redis→valkey, Fedora dropping `sagemath`, a `-dev` suffix change) — automatically,
before a user hits it. This does NOT install anything; it only asks each distro's repos "does this
package exist?". Fast, container-only, no kernel/GPU/GUI/hardware needed, so it's fully automatable
(unlike the real-install matrix).

## Why this is the high-value cheap test

configsys's routing is already frozen by the golden gate (`test/routing_golden.json`: every
component × 13 reference machines). What the golden CANNOT know is whether the package *name* it
resolves to still exists upstream — repos drift under us. This sweep closes exactly that gap, and only that gap. It's the 20% that catches 80% of
real breakage.

## Architecture — three stages

```
  extractor (host, Python)        verifier (container, per manager)      differ
  resolve every component     ->  query each pkg exists in real repos ->  report renames/removals
  collect native pkg names        (apt-cache / dnf / pacman / ... / xbps) (exit nonzero on drift)
```

### 1. Extractor (`tools/namesweep.py`)

Resolves every component in a representative context per manager (`namesweep.MANAGERS`: ubuntu
24.04=apt, fedora 42=dnf, arch=pacman, opensuse=zypper, alpine 3.20=apk, void=xbps) and collects
the **native** package names each maps to (`_native_names`, `Resolver.resolve_names` per component,
so its `requires:` closure's native units count too) — respecting `when:` (only what routes there)
and `name:` (the real per-distro name). A multi-package unit contributes each of its real
`packages:`. Skipped:
non-native units (flatpak app-ids, pipx/npm/cargo dists, tarball URLs, `script`) — a different
verification — and native units that first wire a third-party repo or fetch a package file
(`_NON_REPO_FIELDS`: `source-line:`, `ppa:`, `deb-source:`, `repo-url:`, …), whose names only
exist after that setup.
Current volume: **~320–420 packages per manager** (~2,300 across the six).

```
$ python3 tools/namesweep.py                 # count per manager (apt 401 / dnf 392 / pacman 417 / zypper 344 / apk 320 / xbps 408)
$ python3 tools/namesweep.py --manager apt   # one name per line -> feed a container
$ python3 tools/namesweep.py --json          # {manager: {pkg: [components]}}
```

It already reflects known drift: `apt=redis-server`, `dnf=valkey`, `pacman=valkey`.

**Which managers are swept.** Every OS block's `native:` manager sits in exactly one of
`namesweep.MANAGERS` (swept; it then also needs a `_CHECK` verb and a `_VERIFIERS` image + setup
entry) or `namesweep.UNSWEPT` (`{manager: what checks its names instead}`) —
test/test_driver_inventory.py enforces both. Today `UNSWEPT` holds only brew: there is no container
repo to query, so its formulae are checked by `tools/compaudit.py` (`probe_brew`, against the
formulae.brew.sh index). The default sweep set (`_DEFAULT_MANAGERS`) is derived from `MANAGERS`, so
a new swept manager joins the gate without a second edit.

### 2. Verifier — per-manager existence query (the container half)

One throwaway container per manager, from a stock upstream image (`podman run --rm`, no image
build): enable the repos configsys itself uses, refresh metadata once, then check each name. All
names for a manager go through one container run, which prints the **missing** ones. The images
and query verbs (all read-only, nothing installed):

- **apt** — `ubuntu:24.04`; `apt-cache show "$p"` (enables `restricted universe multiverse`;
  `apt-get update`)
- **dnf** — `fedora:41`; `dnf -q info "$p" || dnf -q provides "$p"` (enables RPM Fusion free +
  nonfree)
- **pacman** — `archlinux:latest`; `pacman -Si "$p" || pacman -Sg "$p"` (groups like `xfce4`;
  `pacman -Sy`)
- **zypper** — `opensuse/tumbleweed:latest`; `zypper -n se -x "$p"`, requiring a package row
  (`zypper -n ref`)
- **apk** — `alpine:latest`; `apk search -x "$p"` (adds the `community` repo; `apk update`)
- **xbps** — `void-linux/void-glibc:latest`; `xbps-query -R "$p"` (enables `void-repo-nonfree`,
  which components there `requires:`; xbps names are the same on musl)

### 3. Differ + report

Missing names → the components that map to them (the extractor's reverse map), printed as
`DRIFT  dnf: package "sagemath" NOT FOUND  (component: sagemath)`. Exit 1 if any survive the
allowlist; `namesweep.py --sweep` exits 2 if podman is missing (the wrapper script checks first and
exits 127).

## The allowlist (avoid false alarms)

Some names are *expected* to be unfindable by this sweep even though the routing is correct:

- packages only in a repo we deliberately don't enable in the check (AUR, a COPR, Packman);
- a component intentionally gated so it declines on a manager (already handled — the extractor
  won't emit it there);
- brand-new packages not yet mirrored.

`test/namesweep-allowlist.hu` — `{ dnf: [ ... ]  apk: [ ... ] }`, keyed by manager — is subtracted
before failing. Every entry carries a `//` reason so it's revisited, not forgotten; today it holds
GPU/accelerator SDKs from vendor repos and Arch's opt-in `multilib` `steam`. Prefer fixing the
route over allowlisting. An allowlisted name that the sweep now finds prints a `note` asking you to
remove the entry.

## Scope, and what it has caught

The default sweep gates on **every `MANAGERS` entry** — today the six families apt/dnf/pacman/
zypper/apk/xbps. Its first runs caught, among others:

- **nim** and **lazygit** aren't in Fedora repos → gated / retargeted to the tarball.
- **gcc-cpp** lacked apt/pacman names → gated redhat; **gst-libav** is `gstreamer1-plugin-libav` on
  Fedora → renamed.
- **~14 vulkan/xcb building blocks** were `via: native` ungated — they'd fail if installed on the
  wrong distro → gated to their family.
- a pile of **openSUSE/Alpine renames** (`firefox`→`MozillaFirefox`, `node`→`nodejs-default`,
  `docker.io`→`docker`, `ninja`→`samurai` on Alpine, `python3-pip`→`py3-pip`/`python313-pip`, ...)
  and genuinely-absent packages gated away (ffmpeg needs Packman on openSUSE; gap/maxima/paraview/
  supercollider not in Alpine).

Run everything with `bash test/run-name-sweep-in-podman.sh`, or a subset with
`bash test/run-name-sweep-in-podman.sh zypper,apk`. openSUSE's versioned names
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

`--plugin` loads the plugin's routes file (its `os:` block + components) as a plugin layer, resolves the whole catalog on
`--context`, collects the `--manager` package names, and verifies them in `--image` (after
`--setup`), reusing the core allowlist for that manager (union in a plugin-local one with
`--allowlist`). The test itself lives WITH the plugin (image + setup are the plugin's business);
core just provides the mode. Two plugins use it:

- **configsys-proxmox** (`apt` on `debian:12` + the PVE repo). Because it checks against real
  Debian, not Ubuntu, it's a *stricter* apt check — it's what caught `perf` naming Ubuntu's
  `linux-tools-generic` (Debian/Proxmox = `linux-perf`).
- **configsys-void** (`xbps` on `void-glibc`) — a worked example of an OS plugin. Void itself is
  supported in core, whose own `xbps` sweep (the core gate above) is authoritative. The plugin
  keeps its `component-names:` map (§10a of the routing model) as the teaching form of the same
  name facts core carries as `xbps:` names; it also ships a plugin-local allowlist (`--allowlist`)
  keyed by its driver.

## Gating & cadence

- **NOT part of `pytest`** — it's networked and container-bound. It's a separate `run-name-sweep-
  in-podman.sh`, like the other `run-*-in-podman.sh` scripts.
- Run **on a schedule** (weekly cron / CI) and on-demand before a release. Repo drift is slow, so
  weekly is plenty; a failure is a heads-up, not a build blocker for unrelated work.
- Wall-clock: 6 image pulls + 6 metadata refreshes + ~2,300 cheap queries ≈ a few minutes (each
  verifier times out after 20 minutes and is skipped).

## What it deliberately does NOT do

- Install anything (that's the representative integration tier).
- Check flatpak app-ids, npm/pipx/cargo/gem dist names, tarball URLs, or `script` endpoints —
  each is a separate, lighter check (an HTTP HEAD for URLs; `flatpak remote-info` for app-ids;
  a registry API for dist names). Worth their own sketch later; the native sweep is the first win.
- Cover managers/OSes without a verifier image: brew (`UNSWEPT` — compaudit's `probe_brew` checks
  formulae instead), rpm-ostree (no OS block's `native:`), macOS, Windows.

## Not yet done

- A scheduled CI job for the core sweep that surfaces drift as an issue. (The plugin repos
  `configsys-void` / `configsys-proxmox` carry their own `test/run-name-sweep.sh`.)
- *(stretch)* sibling checks: URL HEADs for tarball/`script`, app-id checks for flatpak.
