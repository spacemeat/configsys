# Review: OS package-manager + distribution drivers + Driver base

Scope: `configsys/driver.py`, `configsys/drivers/__init__.py`, `configsys/drivers/{apt,dnf,pacman,
zypper,apk,brew,aur,rpm_ostree,native_pkg_file,snap,flatpak}.py`, plus `_alt.py` (referenced by
apt/gcc/clang). Gauge tests: `test/test_apt_driver.py`, `test_dnf_driver.py`, `test_flatpak_driver.py`
(also read: `test_pacman/zypper/aur/brew/snap/native_pkg_file/rpm_ostree_driver.py`,
`test_apt_commit_source.py`, `test_dnf_commit_repo.py`, `test_abi_surface.py`). Baseline: the 13
in-scope test files pass (128 green under `.venv`). READ-ONLY — nothing modified.

Execution model that frames everything below (`configsys/runner.py:432`): **every** driver command
is a shell string run as `bash -c <cmd>` (or `sudo bash -c <cmd>` for `sudo=True`). So every
f-string interpolation in a driver IS shell code, and any route/plugin field that reaches a
command unquoted is a shell injection into a (often root) shell.

## Themes

- **Reuse: five "native package manager" drivers (apt/dnf/pacman/zypper/apk) plus brew/snap/
  rpm-ostree re-implement the same 9-op skeleton by hand, and the rpm/pacman/dpkg query idioms are
  copy-pasted 3-4x across dnf/zypper/rpm_ostree/native_pkg_file/aur/pacman.** `_alt.py` even carries
  its own private apt/dnf command table. A declarative `NativePkgManager` base (command templates +
  a few parser hooks) would collapse ~600 lines to ~200 and make the batch/enumeration hooks
  uniform instead of apt-only.
- **Performance is apt-shaped only.** apt and flatpak have `batch_index`; dnf, zypper, pacman, apk,
  brew and snap do NOT — on a Fedora/openSUSE/Arch/Alpine/Bazzite host startup inspection is back to
  2-4 serial-ish subprocesses per unit (dnf's `repoquery` ~1-3 s each, brew's `info --json` ~1 s
  each). This is the exact regression class the startup-perf work fixed for apt.
- **Security: quoting is mostly right, but there are real holes where route/plugin data reaches a
  root shell unquoted** — `_alt.py` (ppa, deb line, link/version/slaves), apt's `$CODENAME`
  source-line path, rpm-ostree's `echo "..."`. Plus predictable `/tmp` paths written as root
  (native-pkg-file) and a shared fixed `/tmp/configsys-aur` build root.
- **Behavioral drift between siblings:** native-pkg-file's dpkg probe lacks the config-files status
  guard apt fixed; native-pkg-file and `_alt` run `apt-get` without `_APT_ENV` (debconf/needrestart
  can prompt); apt's lock/set_version use `rc.name` as ONE token while `_pkgs()` says it may be a
  whitespace-separated set; flatpak `install` emits a literal `''` arg when a binding has no `hub`.
- **ABI documentation drift.** `driver.py`'s docstring (the contract) omits `location_override`
  (called by 3 external plugins today), `ensure_prereqs`, `installed_index`/`index_key`/
  `explicit_keys`/`origin_index`/`batch_index`/`batch_installed_index`/`get_installed`/
  `reconcile_scope`/`native_backed`; `batch_index` isn't even declared on the base (discovered by
  `getattr`). `test_abi_surface.py` doesn't pin them either.
- **Test gaps:** `apk` has no test at all; native-pkg-file has 2 tests (both about the file
  extension); no test exercises apt's multi-block `_parse_policy`/held/candidate batch; nothing
  anywhere asserts a name with shell metacharacters is quoted (no injection regression gate).

---

## Findings

### [HIGH] security — `_alt.py` interpolates route fields unquoted into a root shell

`configsys/drivers/_alt.py:135` `f'add-apt-repository -y ppa:{ppa}'` — `ppa` comes straight from
`rc.fields['ppa']` (routes.hu / a plugin layer), unquoted, and `install()` runs the joined script
with `sudo=True` (`_alt.py:171`). Compare `apt.py:153` which quotes the same field.
`_alt.py:145` `f'echo "deb {deb}" | tee ...'` — `deb` (from `apt-source.deb` / `default_source`)
sits inside double quotes, so `$(...)`, backticks and `$VAR` in it are expanded/executed as root
(the `$CODENAME` resolution is *why* it's unquoted, but that only needs `$CODENAME`, not full
expansion). `_alt.py:152-155` `update-alternatives --install /usr/bin/{link} {link} /usr/bin/{link}-{v} {v}` and
`--slave /usr/bin/{s} {s} ...` — `link`, `version`, `slaves` (all route fields) unquoted, root.
`_alt.py:139-140` `key-path`/`list` are quoted; the rest aren't.
Why: plugins are content-trusted but not root-trusted; a typo'd/hostile `slaves: [ "g++; rm -rf /" ]`
executes. Recommendation: `shlex.quote` every field; for the `$CODENAME` line, substitute a quoted
`"$CODENAME"` fragment into an otherwise single-quoted string
(`shlex.quote(deb).replace('$CODENAME', "'\"$CODENAME\"'")`) or resolve the codename in Python via
`/etc/os-release` before building the command. Add a regression test with a metachar-laden field.

### [HIGH] performance — no `batch_index` for dnf / zypper / pacman / apk / brew / snap

Only `apt.py:278` and `flatpak.py:83` implement `batch_index`; `installState._build_batch`
(`installState.py:165`) falls back to per-unit probes for every other driver. Per unit that means:
dnf 3 subprocesses (`rpm -q` :54, `dnf -q repoquery` :62 which loads repo metadata ~1-3 s,
`dnf versionlock list` :71); zypper 3 (`rpm -q`, `zypper info`, `zypper locks`); pacman 2-4
(`-Q` then `-Qg` on a miss :55-61, `-Si` then `-Sg` :64-71); brew 3 (`list --versions`,
`info --json=v2` :74 ~1 s of Ruby startup, `list --pinned` :85); snap 3 (`snap list` twice —
:58 and :85 — plus `snap info` :72). With ~100 units on a Fedora box that is ~300 spawns, i.e. the
pre-cf290a7 apt situation. Every one of these has a one-call enumeration equivalent:
`rpm -qa --qf` (already in `dnf.installed_index` :35), `dnf -q repoquery --qf '%{name} %{version}' pkg...`
(one call for all names), `dnf versionlock list` once; `zypper --no-refresh info pkg...` + `zypper locks`
once; `pacman -Q`/`-Qg` + `pacman -Si pkg...`/`-Sg` once; `brew info --json=v2 --installed` +
`brew list --pinned` once; `snap list` + `snap info` per snap (unavoidable) but at least dedupe the
double `snap list`. Recommendation: give the base a default `batch_index` built from
`installed_index()` + two optional hooks `latest_index(names)` / `locked_keys()`, so each native
driver supplies 3 parsers and inherits batching (ties into the reuse item below).

### [HIGH] reuse — a declarative `NativePkgManager` base is overdue

The five native drivers are the same 9 ops with different verbs:

| op | apt | dnf | zypper | pacman | apk |
|---|---|---|---|---|---|
| install | `apt-get install -y X` | `dnf install -y X` | `zypper --non-interactive install X` | `pacman -S --noconfirm X` | `apk add X` |
| uninstall | `apt-get remove -y` | `dnf remove -y` | `zypper -n remove` | `pacman -R --noconfirm` | `apk del` |
| upgrade | `apt-get install --only-upgrade -y` | `dnf upgrade -y` | `zypper -n update` | `pacman -S --noconfirm` | `apk add --upgrade` |
| set_version | `X=V` | `X-V` (+downgrade) | `X=V --oldpackage` | (none) | `X=V` |
| lock/unlock | `apt-mark hold/unhold` | `versionlock add/delete` | `addlock/removelock` | ledger | ledger |

And the query idioms are literally duplicated: `rpm -q --qf '%{VERSION}\n'` appears in
`dnf.py:54`, `zypper.py:39`, `rpm_ostree.py:51`, `native_pkg_file.py:80`; the `pacman -Q` parse in
`pacman.py:55-58`, `aur.py:35-39`, `native_pkg_file.py:82-88`; `apt-mark showhold` membership in
`apt.py:339-340` and `native_pkg_file.py:97-98`; `apt-mark hold/unhold` in `apt.py:384-390` and
`native_pkg_file.py:150-157`; `_alt.py:84-92` re-declares apt/dnf install/remove/upgrade strings
(without `_APT_ENV`, see below). `native_pkg_file._install_cmd`/`uninstall` (:103-141) is a third
copy of the same per-format switch. Recommendation: one base with class-level command templates
(`INSTALL = 'dnf install -y {pkgs}'` ...), a `pkgs(rc)` hook (apt's `_pkgs`), `installed_index`/
`latest_index`/`locked_keys` parser hooks, and a shared `ENV` prefix; apt keeps its prereq/source
machinery as an override. `native_pkg_file` and `_alt` then *delegate* to the resolved native
driver (`get_driver(native).install_file(...)` / `.lock()`) instead of re-encoding it — which also
fixes the two drift bugs below in one place. `app.py:1068-1070` and `:1173-1175` carry a second,
duplicated per-manager refresh table (`_NATIVE_REFRESH`) that belongs on the same class.

### [MED] security — apt `source-line` with `$CODENAME` is expanded inside double quotes

`apt.py:189-192`: `f'echo "{src_line}" | sudo tee {sp} ...'` — the raw route string is placed
inside double quotes so bash expands `$(...)`, backticks and every `$VAR`, and a `"` in the line
breaks out entirely. The non-`$CODENAME` branch (:194) quotes correctly. Runs as the user (only
`tee` is sudo'd) but the file it writes is a root-owned apt source. Current routes.hu lines are
benign (checked: no `"` in any `source-line:`), the exposure is plugin layers. Recommendation: same
fix as `_alt` — quote everything except a `"$CODENAME"` splice, or resolve the codename in Python.

### [MED] security — rpm-ostree `echo "... {pkg} ..."` re-expands the quoted name

`rpm_ostree.py:67-71`: `pkg = shlex.quote(name)` is then embedded in
`f'... && echo "configsys: {verb} {pkg} applied live ..." >&2'` under `sudo=True`. Inside double
quotes the single quotes from `shlex.quote` are literal, so a name like `foo$(id)` becomes
`"... 'foo$(id)' ..."` and `$(id)` runs as root. The `rpm-ostree` invocation itself is safe; the
message isn't. Recommendation: `echo {shlex.quote(f"configsys: {verb} {name} ...")}`, or emit the
advisory from Python after the Result instead of from the shell.

### [MED] security — native-pkg-file writes a predictable `/tmp` path as root

`native_pkg_file.py:126-128`: `tmp = /tmp/configsys-{rc.comp}.{ext}`, then
`PKG=...; curl -fSL URL -o $PKG && apt-get install -y $PKG && rm -f $PKG` under `sudo=True`. (a)
Classic CWE-377: another local user pre-creates a symlink at that name; root's `curl -o` follows
it and clobbers an arbitrary file, and the install then consumes whatever is there. (b) `$PKG` is
expanded unquoted at every use (quoting was applied to the *assignment*), so any whitespace/glob in
`rc.comp` word-splits. Recommendation: `PKG="$(mktemp --suffix=.{ext})"` (root-owned, unpredictable)
and `"$PKG"` everywhere; or download as the user into `paths.cache` and only sudo the install step.
`aur.py:20` has the same shape: a fixed shared `/tmp/configsys-aur/<pkg>` that is `rm -rf`'d and
re-cloned as the user, then `makepkg -si` sudo's the result — a hostile pre-existing directory
owned by another user makes `rm -rf` fail (set -e aborts, fine) but a symlink race between
`rm -rf` and `git clone` is possible. Use `mktemp -d` or `paths`' cache dir.

### [MED] correctness — flatpak `install` passes a literal `''` when a binding has no `hub`

`flatpak.py:183-185`: `hub = shlex.quote(rc.fields.get('hub', ''))` → `shlex.quote('')` is the
two-character string `''`, so the command becomes `flatpak install --user -y '' org.foo.Bar` —
flatpak receives an empty positional and errors ("Nothing matches" / usage). All 72 flatpak
bindings in routes.hu carry `hub:` so it's latent, but a user/plugin binding without one hits it
(`ensure_remote` tolerates a missing hub, so the driver *looks* like it supports that case).
Recommendation: omit the hub token when unset, or make routecheck lint it.

### [MED] correctness — apt `lock`/`unlock`/`set_version`/`is_locked` disagree with `_pkgs`

`apt.py:345-354` `_pkgs` documents that `rc.name` "may itself be a whitespace-separated set" and
that a `packages: [...]` binding installs the set. But `lock`/`unlock` (:384-390) quote `rc.name`
as ONE token (`apt-mark hold 'a b'`), `set_version` (:378) pins only `rc.name` (not the
`packages:` list), and `is_locked` (:336-340) checks bare `rc.name` membership. So a multi-package
binding installs N packages but holds/pins one (or a nonsense token). Recommendation: route every
package-name op through `_pkgs` (and hold/unhold all of them); have `is_locked` report locked iff
every package is held. Same `installed-name` asymmetry: `get_version`/`get_latest` probe
`installed-name`, `is_locked` probes `name` — probably intended, but worth a comment.

### [MED] drift — native-pkg-file's dpkg probe lacks the config-files status guard

`native_pkg_file.py:78`: `dpkg-query -W -f='${Version}\n'` — no `${db:Status-Status}` filter.
`apt.py:300-316` explains why that's wrong: after `apt-get remove` the package stays in
`config-files` state and dpkg-query still prints a version, so a removed native-pkg-file component
reports as installed forever. This is the exact bug fixed in apt, re-introduced in the sibling.
Recommendation: delegate to `Apt.get_version` (see the reuse item) or copy the guard.

### [MED] drift — native-pkg-file and `_alt` run `apt-get` without `_APT_ENV`

`native_pkg_file.py:106` `apt-get install -y {tmp}`, `_alt.py:85-92` `apt-get install -y` /
`remove` / `--only-upgrade` — none prepend `DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a`
(`apt.py:26`), so a vendor `.deb` with debconf questions (common) or Ubuntu's needrestart hook
can paint a whiptail dialog mid-batch, the very thing `_APT_ENV` exists to prevent. Recommendation:
export `_APT_ENV` from one place (the native base) and use it in every apt-get invocation.

### [MED] correctness — package-format/PM detection probes binaries instead of the resolved OS

`native_pkg_file.py:36-44` picks `deb` if `dpkg` OR `apt-get` is on PATH, before `rpm`/`dnf`;
`_alt.py:82` picks `dnf` iff `dnf` is on PATH else `apt`. Both diverge from the resolver, which
already knows the machine's manager (`cascade.native(block)`, used by `app.py:1078`, `:1172`,
`resolve.py:251`). Fedora ships `dpkg` in its repos (pulled by `alien`, some CI images), Debian can
have `dnf` installed; then native-pkg-file installs a `.deb` on Fedora or `_alt` runs `dnf` on
Ubuntu. Also `_alt` is apt/dnf-only, so a `via: gcc` on zypper/pacman silently runs `apt-get`.
Recommendation: inject the resolved native driver name onto the unit (the way `location-override`
is injected, `driver.py:155-163`) and dispatch on that; keep `shutil.which` only as a fallback.

### [MED] robustness — apt `ensure_prereqs` ignores the result of four of its six steps

`apt.py:136-160`: the `foreign-arch`, `repo-component`, `ppa`, and `pubkey-url` steps call
`runner.run(...)` and drop the Result; only `source-url`/`source-line` go through
`_commit_source` and can abort. A failed `add-apt-repository -y ppa:deadsnakes/ppa` (no
`software-properties-common`, no network) is followed by `apt-get install python3.12`, which then
fails with a misleading "Unable to locate package". `dnf.ensure_prereqs` (`dnf.py:97-106`) drops
the `rpm --import` / `config-manager` results the same way. Recommendation: return the first
failing classified Result (the `_commit_source` pattern) — cheap and consistent with the
resilience plan's "validate-then-commit".

### [MED] correctness/sudo — apt's inline `sudo ...` under `capture=True` cannot prompt

`apt.py:74` `run('sudo apt-get update', capture=True)`, `:88-89`, `:101`, `:108`, `:113`,
`:166-167`, `:192`, `:195` (`_commit_source` and the source-writing `write_cmd`s) embed `sudo` in
the string with `capture=True`. `runner.run` (`runner.py:474-476`) gives a captured child
`stdin=DEVNULL`, and the per-batch pre-auth (`_ensure_sudo`, `:385`) only fires lazily on the first
`sudo=True` op — which is the `apt-get install` that runs AFTER `ensure_prereqs`. So on a fresh
batch whose first unit has a vendor source, the very first sudo the user sees is a captured one
that cannot prompt → "sudo: a terminal is required" → classified AUTH (definitive, no retry) →
"vendor repo setup failed ... (source rolled back)". The earlier `pubkey` step runs `capture=False`
(`:159`) and can prompt, but on a real tty that goes through `_run_teed` (a NEW pty), and under
`tty_tickets` that credential does not carry to the captured child's real tty — the mechanism
documented in the sudo-tty memory. Recommendation: call `self.runner._ensure_sudo()` (or a public
`runner.warm_sudo()`) at the top of `ensure_prereqs` when any privileged prereq is declared, and
prefer `sudo=True` over string-embedded `sudo` so the runner owns the policy. Verify on a live box
with a cold sudo ticket; this is reasoned from the runner code, not observed.

### [MED] tests — coverage gaps

- `apk.py`: **no test file** (only incidental refs in `test_steam.py`/`test_os_blocks.py`).
  Command shapes, `_version_from_apk_list` prefix guard (`gcc` vs `gcc-doc`), set_version — untested.
- `native_pkg_file.py`: `test_native_pkg_file.py` has 2 tests, both on the temp-file extension.
  Untested: format dispatch order, arch-keyed vs format-then-arch `asset:` maps (`:46-55`),
  `uninstall`/`lock`/`unlock` per format, `get_version` parsing for all three formats, the
  no-format error path.
- apt: `_parse_policy` multi-block parsing (`:29-45`), `batch_index`'s held/candidate paths and
  `is_locked`-from-batch are only touched incidentally by `test_installed_name_...` (`:63-80`).
  `explicit_keys` (`:247`) untested (origin_index is, in `test_orphans.py:221`).
- dnf/pacman/brew/snap `installed_index`/`explicit_keys` parsers: untested.
- No driver test anywhere feeds a name/field containing a shell metacharacter and asserts it is
  quoted — an injection regression gate would have caught the `_alt` findings.
- `_alt` is covered via `test_gcc_driver.py`/`test_clang_driver.py`/`test_toolchain_dnf.py` but
  none assert quoting of `ppa`/`slaves`/`link`.

### [MED] ABI — the documented `Driver` contract omits methods plugins already depend on

`driver.py:15-29` (the docstring `docs/plugins.md:190` calls "the authoritative contract") and
`test/test_abi_surface.py:23-35` list: name/privileged/default_scope/honors_scope, the 9 ops,
location/scope, and `resolve_version`/`download_url`/`arch`/`scoped_dir`/`sudo`/`display_path`.
Not listed but public and load-bearing:
- `location_override(rc)` (`driver.py:155`) — called by three external plugins today
  (`~/src/configsys-kicad/kicad.py:61`, `configsys-blender/blender.py:76`,
  `configsys-opencv/opencv.py:84`). Renaming it would break all three and no test would notice.
- `ensure_prereqs(rc)` (docs/plugins.md:208 mentions it; driver.py docstring doesn't).
- The enumeration/batch hooks the host calls on ANY driver: `installed_index`, `index_key`,
  `explicit_keys`, `origin_index`, `batch_installed_index`, `get_installed`, `reconcile_scope`,
  `native_backed`, and `batch_index(rcs)` — the last is not even declared on the base
  (`installState.py:165` `getattr(drv, 'batch_index', None)`), and the host writes the
  underscore attribute `drv._batch` onto plugin instances (`installState.py:195`).
`driver.py:28` says the internal set is `_scope, _apply_placeholders, _disco_spec`; it is really
also `_batch`, `_offline`, `_extract_cmd`, `_fetch_and_extract`, `_installed_across_scopes`.
Recommendation: declare `batch_index(self, rcs): return None` on the base; add the hooks to the
docstring's "Overridable (optional)" line and to `test_driver_public_contract_present`; decide
whether `_batch` is ABI (it is de facto — rename to `batch` or document it).

### [MED] performance — dnf lock/unlock reinstall the versionlock plugin every call

`dnf.py:167-169` `_ensure_versionlock` runs `dnf install -y python3-dnf-plugin-versionlock`
unconditionally before every `lock`/`unlock` — a metadata-loading dnf transaction (seconds) even
when the plugin is present. Recommendation: guard with `rpm -q` (or `dnf versionlock list` exit
status, which `is_locked` already interprets).

### [LOW] correctness — dnf writes `gpgkey=None` when a repo has no `pubkey-url`

`dnf.py:96, 110-111`: `key = f.get('pubkey-url')` may be None, yet the `.repo` body is
`f'...gpgcheck=1\ngpgkey={key}\n'` → literal `gpgkey=None` with gpgcheck on, so the first install
fails signature verification. Every current `repo-id:` binding in routes.hu has a key (checked all
21), so latent. Also `content` interpolates `repo-id`/`repo-name`/`repo-url` raw into INI: a
newline in a plugin value appends arbitrary keys (`gpgcheck=0`). Recommendation: require the key
(routecheck lint) or omit `gpgkey=`/set `gpgcheck=0` explicitly with a warning; reject newlines.

### [LOW] comment-vs-code drift — flatpak docstring says `get_latest` is deferred

`flatpak.py:11-13`: "Known limitation (deferred): get_latest returns None, so installed flatpaks
show as installed rather than outdated". `get_latest` (`:151-167`) is fully implemented (remote-ls
batch + remote-info fallback) and `test_flatpak_driver.py:104-115` tests it. The test at `:140`
`test_get_latest_deferred_none` is likewise stale (it passes only because the fixture has no hub).
Recommendation: delete the paragraph; rename the test to `..._none_without_hub` (there's already a
`test_get_latest_none_without_hub` at `:123` — the two are duplicates).

### [LOW] comment-vs-code drift — `drivers/__init__.py` docstring lists an old driver set

`__init__.py:3-7` names "apt, dnf, pacman, aur ... tarball, native-pkg-file, flatpak, appImage,
dotfiles, font, cargo, brew, pip, pipx, rpm-ostree, gcc/clang/gcc-toolset, service, group" — missing
zypper, apk, snap, glue, npm, gem, opam, luarocks, cabal, go-install, sdkman, pyenv, script, source.
Recommendation: point at `_REGISTRY` instead of enumerating.

### [LOW] naming/drift — `Driver.scope` vs `Driver._scope` disagree on who honors the field

`driver.py:59-73`: `scope()` says non-`honors_scope` drivers "have a fixed scope", but `_scope()`
(used by `sudo()`, `scoped_dir()`) reads `rc.fields['scope']` regardless of `honors_scope`. So a
stray `scope: system` on an apt binding changes `sudo(rc)`/`scoped_dir` while `scope(rc)` still
reports `system` only because apt's default is system — for a `user`-default non-honoring driver
the two would disagree. Recommendation: make `_scope` delegate to `scope` (one truth) or document
the asymmetry.

### [LOW] performance — zypper / apk / rpm-ostree / aur lack `installed_index`

`driver.py:213` says a package-manager driver should enumerate once; `detection.py:34,58` and
`orphans.py:160` fall back to per-unit `get_version` when it returns None. `zypper.py` and
`rpm_ostree.py` could reuse dnf's `rpm -qa --qf` (`dnf.py:35`), `apk.py` has `apk list --installed`
(one call), `aur` is `native_backed` so it rides pacman's — but `aur` doesn't set `index_key` and
`pacman.installed_index` (`:36`) skips groups, fine. Recommendation: inherit from the shared
rpm-backed base (reuse item) so these come for free.

### [LOW] correctness — substring matching in `is_locked`

`flatpak.py:175` `any(appid in line ...)` — `org.foo.Bar` matches `org.foo.Bar2`/`org.foo.Bar.Extra`
(the batched path at `:172` uses an exact set, so the two paths can disagree). `snap.py:88`
`self._snap(rc) in ln and 'held' in ln` — same, plus a snap whose *version* string contains "held".
Recommendation: split columns and compare tokens.

### [LOW] naming/style — snap `install` builds the command then `.replace('  ', ' ')`

`snap.py:94`: the double-space fix-up papers over `_extra()` returning `''`. Build a token list and
`' '.join(t for t in tokens if t)`. Also `_extra` parses `classic:` truthiness inline (`:32`)
while `rpm_ostree.py:29` has `_truthy` for the identical job — share it.

### [LOW] reuse — small duplicated helpers

- `_as_list`: `apt.py:56` (staticmethod) vs `dnf.py:20` (module fn) — identical.
- `_truthy` (`rpm_ostree.py:29`) vs inline in `snap.py:32`.
- flatpak's tab-or-space column parse is copy-pasted 3x (`flatpak.py:72-77`, `:92-97`, `:110-113`).
- Trivial identity accessors `_pkg`/`_formula`/`_snap`/`_appid` (`aur.py:29`, `brew.py:33`,
  `snap.py:26`, `flatpak.py:37`, `rpm_ostree.py:43`) all return `rc.name` — one base `pkg(rc)`.
- `native_pkg_file.py:36-38` `_FORMATS` and `:125` the `ext` map are two tables keyed by the same
  format — merge into one `{'deb': (tools, ext, install, remove), ...}` record.

### [LOW] correctness — apt `set_version` ignores `packages:` and `ensure_prereqs` re-runs on every op

`apt.py:374-382` pins `rc.name` only (see the `_pkgs` finding). Separately, `install`/`upgrade`/
`set_version` each call `ensure_prereqs`, which for a source-line binding runs `test -f`, a
guarded write, and possibly `apt-get update` every time — fine for correctness, but `upgrade` on a
20-component vendor-repo batch re-checks 20x. Idempotent, so LOW.

### [NIT] perf — pacman/brew/dnf `explicit_keys` and dnf `repoquery --userinstalled` hit metadata

`dnf.py:47` `dnf repoquery --userinstalled` loads repo metadata (may go to the network) for what is
an rpmdb question; `dnf repoquery --userinstalled --installed` or `dnf history userinstalled` avoids
it. `pacman -Qeq`/`brew leaves` are fine.

### [NIT] naming — `Apt._probe_name` is a staticmethod on apt only

The `installed-name:` concept (probe one package, install a set) is generic — dnf/zypper/pacman
would want the same for metapackages. Lift `_probe_name`/`_pkgs` to the native base.

### [NIT] docs — `driver.py` docstring says "paths.home/.env/.expand(p)/..." and `__init__(runner, paths)`

Fine, but `Driver.__init__` accepts `paths=None` and several helpers branch on it (`arch`,
`scoped_dir`, `display_path`), while `resolve_version` passes `self.paths` (None) into
`versions.discover` — worth one sentence saying which helpers are paths-optional for plugin authors.

---

## Counts

HIGH 3 · MED 12 · LOW 9 · NIT 3 — 27 findings.

Top three to act on: (1) quote every route field in `_alt.py` (root shell), (2) a shared
`NativePkgManager` base with a default `batch_index` — it deletes the copy-paste AND fixes the
non-Debian startup-perf hole in one change, (3) mktemp for native-pkg-file's root-written download.
