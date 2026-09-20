# Review: config overlay, layer stack, plugin data/sync/trust/transport

Scope: `configsys/config.py`, `configsys/layers.py`, `configsys/plugins.py`, `configsys/troveio.py`,
`configsys/ledger.py`; coverage gauged via `test/test_config_overlay.py`, `test_plugins.py`,
`test_plugin_trust.py`, `test_plugin_code.py`, `test_plugin_transport.py`, `test_plugin_hooks.py`,
`test_includes.py`, `test_overrides.py`, `test_picks.py`, `test_config_edit.py`.
Read-only; every finding below was verified by reading the cited lines and, where marked
**(demonstrated)**, by running a probe script in the repo venv.

## Cross-cutting themes

- **The trust boundary is "does it ship `code:`", but DATA already executes.** A data-only plugin
  (no trust gate, syncs freely, docs say "just data can't do too much harm") can define or amend a
  component with a `via: script` / `via: source` binding whose `install:`/`build:` fields are run
  verbatim through `bash -c` (with `sudo` for privileged drivers), add an apt `source-line:`
  vendor repo, or drop dotfiles/glue into shell rc files. Specificity-first selection means such a
  binding can hijack an EXISTING picked component's default. The trust model gates the wrong axis.
- **Attacker-controlled strings reach `git` argv and the filesystem unvalidated.** `source:`/`ref:`
  values — which any synced plugin's manifest `plugins:` can supply transitively (not just the
  primary, contrary to docs) — become git options if they start with `-`, and `dir_name()` yields
  `..`/`.`/`''` for crafted sources, so `plugin remove` can `rmtree` the whole config or plugins
  dir.
- **The layer stack dedups includes by realpath without regard to role.** A lower layer that
  `include:`s the user's own `~/.config/configsys/configsys.hu` demotes it to an `include`-role
  layer and the user's `scope`/`pins`/`picks` are silently dropped (demonstrated).
- **Setting knowledge is scattered across four registries** (`config.py` per-method getters,
  `layers._KNOWN_TOP_KEYS`, `layers._SETTING_SECTIONS`, `actions.py` nature table) — and they have
  already drifted: `locations:` and `reboot-advice:` are live settings that `check` reports as
  "unrecognized top-level key" (demonstrated); non-primary plugins setting `picks:`/`dirs:`/`splash:`
  etc. are ignored with NO warning because `_SETTING_SECTIONS` only lists `configs/scope/pins`.
- **`plugins.py` has grown a second, hand-rolled Humon I/O layer** (8 near-identical `read_*`
  readers, 5 map emitters, a comment-aware span scanner *and* a `source_text`-based remover that
  disagree about what's reliable) beside `troveio.emit_hu`/`load`. The scanner has real gaps
  (backslash before a closing quote, backtick strings, brace-less/empty files, a `}` inside a
  trailing comment) that corrupt the user's config on write (demonstrated).
- **The named profile-authoring writers are already gone.** `set_profile_membership`,
  `read_profiles/set_profiles/_emit_profiles`, `read_configs/set_configs`,
  `read_machines/set_machines/_emit_machines` do not exist anywhere in the tree. What *is* left
  over: `Config._profiles` (computed, never read), the phantom `'machine'` layer role, the
  `dispositions` side-store (live callers, but its model is superseded), and stale docs/docstrings.

---

## Findings

### [HIGH] security — data-only plugins can execute arbitrary commands (trust gates the wrong axis)
- `configsys/plugins.py:992-993` — `load_code` returns early for a manifest without `code:` ("data-only: nothing to gate"); `layer_files` (`:258-277`) admits any synced+ABI-ok plugin's `.hu` files with no trust check.
- `configsys/drivers/script.py:41,51` — `rc.fields.get(key)` → `self.runner.run(cmd)`; `configsys/runner.py:432` — `argv = ['sudo','bash','-c',cmd] if sudo else ['bash','-c',cmd]`. `configsys/drivers/source.py:92` (`build:`), `:183` (`uninstall-cmd`), `configsys/drivers/apt.py:171-181` (`source-line:` vendor repos) are the same shape.
- `docs/plugins.md:142-144` — "Data-only plugins: sync freely, no prompt. Worst case is bad component definitions … just data can't do too much harm."

**Why:** bindings merge additively across layers by `(via, when)` and a narrower `when:` wins by specificity before `driver-preference`, so a data plugin can add `{ via: script  when: "linux and cpu: x86_64"  install: "curl … | sudo sh" }` to `btop` and become the default for a component the user has already picked; the next `install`/`upgrade` runs it as root. Nothing in `plugin list`, `check`, or the plan distinguishes this from a benign route. The content-hash trust store, checksum quarantine and ABI gate all sit on the `code:` path and are bypassed entirely.

**Recommendation:** treat "executable data" like code: (a) at load time, tag bindings whose driver runs declared command strings (`script`, `source`, `native-pkg-file`, apt `source-line`, `dotfiles`/`glue` writes into `$HOME`) and require the same `plugin trust` approval for a plugin layer that contributes them, OR (b) at minimum surface them — `plugin list` "ships executable recipes (N)", `check` warning, and the install plan line naming the plugin whose binding won. Fix `docs/plugins.md:142` to stop promising the data half is harmless. Also consider refusing a non-primary plugin binding from *out-ranking* a repo binding for an already-installed component unless pinned.

### [HIGH] security — `dir_name()` path traversal → `rmtree` of the config/plugins dir **(demonstrated)**
- `configsys/plugins.py:222-228` — `dir_name('github:a/..') == '..'`, `dir_name('github:a/.') == '.'`, `dir_name('github:') == ''`.
- `configsys/actions.py:791-794` — `pdir = plugins_dir / dir_name(...)`; `shutil.rmtree(pdir)` on `plugin remove`.
- `configsys/plugins.py:1311` (`sync` → `plugins_dir / name`), `:268` (`layer_files`), `:88-108` (`effective_declared` follows any synced plugin's manifest `plugins:`).

**Why:** a source is user-typed *or* comes from a transitive manifest (attacker-controlled once any data plugin is synced). `..` maps to `~/.config/configsys` (so `_data_files` globs `configsys.hu`, `versions.hu`, `state.hu`, `plugin-trust.hu` in as `plugin`-role layers, and `plugin remove` deletes the whole config dir); `.` maps to the plugins dir itself (remove wipes every plugin). `_git_transport` on an existing non-repo dir returns `'updated'` (`:1058-1060` — no ref/no origin/HEAD → `True`), so the bad entry looks healthy.

**Recommendation:** validate in one place: `dir_name` must return a single path segment matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, not `.`/`..`; raise `ConfigError` (and have `_decl` drop the entry with a warning). Assert `(plugins_dir / name).resolve().parent == plugins_dir.resolve()` before any `rmtree`/clone. Add a test.

### [HIGH] security — git option injection via `source:` / `ref:` (no `--` separator)
- `configsys/plugins.py:1183` — `git clone --quiet {shlex.quote(clone_url(source))} {dq}`; `:1206,1214` — `git ls-remote --tags --refs {dq}` where `dq = shlex.quote(clone_url(source))`; `:1263` — `git -C … fetch --quiet {dq} {rq}` (url AND target_ref); `:1061` — `git checkout --quiet --force --detach {shlex.quote(target)}` where `target = ref` is unverified.
- `configsys/plugins.py:162-174,177-187` — `source_url`/`clone_url` pass any non-shorthand string through unchanged; **(demonstrated)** `source_url('--upload-pack=touch /tmp/pwn')` returns it verbatim.
- `configsys/runner.py:432` — whole string runs under `bash -c`; `shlex.quote` prevents *shell* injection but a quoted token that starts with `-` is still parsed by git as an option.

**Why:** `--upload-pack=<cmd>` on `clone`/`fetch`/`ls-remote` executes `<cmd>` locally when the transport is `file`/local (the classic git-client CVE pattern); `--config`/`-c`, `--template`, `--separate-git-dir` are other live options. Inputs reach here from the top config (user's own) *and* from transitive manifest `plugins:` of any synced data plugin (`effective_declared`, `sync:1316-1319`, `_locate_decl` in `actions.py:679-685`), so `plugin update --latest` / `plugin sync` on a poisoned transitive entry is the attack path. Ref names are also unvalidated (`_git_checkout` branch path is safe because `_has()` must succeed first, but the detached path is not).

**Recommendation:** (1) put `--` before every positional in the git commands (`git clone --quiet -- <url> <dest>`, `git ls-remote --tags --refs -- <url>`, `git fetch --quiet -- <url> <ref>`, `git checkout … --detach -- <ref>` is not valid — use `git rev-parse --verify` first as the branch path does); (2) reject sources/refs beginning with `-` in `_decl`; (3) test with a `-`-prefixed source that the runner's recorded call contains `--`.

### [HIGH] correctness/security — include dedup by realpath demotes the user's top config **(demonstrated)**
- `configsys/layers.py:84-105` — `_visit` keys `done` on `realpath` only; `:88-89` returns early for a path already visited regardless of the role it was visited *as*.
- Probe: roots `[(repo,'repo'), (plug,'plugin'), (user,'user')]` where `plug.hu` has `include: [<user path>]` → layers came back as `repo / user(include) / plugin`; `Config.default_scope()` returned the repo value, `pins()` was `{}`, and the only signal was two `ignored_section_warnings` entries (only visible in diagnostics/`check`).

**Why:** the user's machine settings (`scope`, `pins`, `picks`, `uninstall`, `dirs`, `splash`, `machine`…) are silently neutralised. A naive plugin author (or `configsys plugin init` scaffolding that copies sections) could do this by accident; a malicious data plugin does it on purpose to strip a user's pins before its own bindings take over (compounds finding 1). Same hazard for the repo `config.hu`/`routes.hu` roots if a plugin includes them (they would be re-tagged as `include`, dropping `os:`/`drivers:`).

**Recommendation:** in `expand_tolerant`, precompute the realpaths of all roots; in `_visit`, when an include resolves to a root path, skip it with a warning ("include of a root layer ignored") instead of merging it under the include's role. Alternatively visit roots in precedence order and let a later root *upgrade* the role of an already-visited path (re-tag + move to its root position). Add a regression test in `test_includes.py`.

### [MED] security/docs — transitive `plugins:` are followed for EVERY synced plugin, not just the primary
- `configsys/plugins.py:96-107` (`effective_declared`), `:119-125` (`declared_tree`), `:1316-1319` (`sync`) — iterate `read_manifest(...).get('plugins')` for every declared entry.
- `docs/plugins.md:93-95` — "`plugins:` is a machine SETTING … repo/user only … The blessed **primary** plugin is the exception among plugins: it may … carry transitive `plugins:`." `docs/config-format.md:14` shows the same intent.

**Why:** any data plugin can pull in an unbounded set of further plugins from arbitrary sources at floating refs (no `sha256`, `ref` may be a branch), each becoming a `plugin`-role layer (os blocks, components, `keys:`, `theme:`) — a supply-chain fan-out the user never declared, with `plugin list` the only visibility. Combined with findings 1-3 it is the delivery vehicle.

**Recommendation:** either follow manifest `plugins:` only for the entry marked `primary` (matching the docs), or keep the behaviour and (a) document it, (b) make non-primary transitive decls require a `sha256:` to load, (c) print them under their parent in `plugin sync` output. Add a test either way — today `test_effective_declared_pulls_transitive_from_manifest` asserts the permissive behaviour without a primary.

### [MED] security — manifest `code:`/`data:` paths are not confined to the plugin dir; trust hash does not cover out-of-tree code
- `configsys/plugins.py:936` — `code_file = pdir / manifest['code']` (no `resolve()`/containment check); `:254` — `_data_files` joins `data:` entries the same way.
- `configsys/plugins.py:314-328` — `plugin_identity` hashes `root.rglob('*')` only; on Python < 3.13 `rglob('**')` does not descend symlinked directories.

**Why:** `code: ../../somewhere/x.py` is imported after `trust`, but the approved identity only covers files *under* the tree, so the imported module can change without the "changed since trust" state ever appearing — this breaks the documented guarantee (`docs/plugins.md:153-156`, "Any change to the plugin's files … changes the hash"). A symlinked subdirectory holding the code module has the same property. `data:` traversal is lower impact (it only yields more `.hu` layers) but lets a plugin silently load another plugin's files or the user's own config under its role (see the include finding).

**Recommendation:** resolve both and require `path.resolve().is_relative_to(pdir.resolve())`, else skip with a `check` warning; in `plugin_identity`, walk with `os.walk(followlinks=False)`, and either refuse symlinks outright or hash the link *target path* as content so a retargeted link changes the identity.

### [MED] correctness — `_KNOWN_TOP_KEYS` is missing live settings → `check` false positives **(demonstrated)**
- `configsys/layers.py:265-274` — no `locations`, no `reboot-advice`.
- `configsys/config.py:182-188` (`locations()`), `:268-273` (`reboot_advice()`); `docs/config-format.md:53,69-72` documents `locations:`; `actions.py:319+` nature table and `test/test_config_edit.py:102` list `reboot-advice` as a real setting.
- Probe: `unknown_section_warnings` on a layer with both → "unrecognized top-level key `locations:` (typo, or retired?)" and the same for `reboot-advice:`.

**Recommendation:** derive `_KNOWN_TOP_KEYS` from a single settings registry (see the data-driven finding below) or at least add a test that every key read by any `Config` getter / the `actions.py` settings table is in `_KNOWN_TOP_KEYS`.

### [MED] data-driven separation — machine-setting knowledge lives in four places and has drifted
- `configsys/layers.py:23` — `_SETTING_SECTIONS = ('configs', 'scope', 'pins')`; `:243-249` `_FORBIDDEN_BY_ROLE` uses it to decide what a `plugin`/`include` layer is warned about.
- `configsys/config.py` — ~25 getters each hard-code the key and `_MACHINE_ROLES` (`:93-345`, `:359-373`, `:464-470`).
- `configsys/layers.py:265-280` — `_KNOWN_TOP_KEYS` / `_RETIRED_TOP_KEYS`; `configsys/actions.py:319-360` — kind/nature/desc table.

**Why:** a non-primary plugin (or include) that sets `picks:`, `uninstall:`, `dirs:`, `splash:`, `locations:`, `disabled-drivers:`, `machine:`, `driver-preference:`… is silently ignored by the `_MACHINE_ROLES` filters with **no** warning, because only `configs/scope/pins` are in `_SETTING_SECTIONS`. Meanwhile `configs` is both in `_SETTING_SECTIONS` and `_RETIRED_TOP_KEYS`, so a plugin carrying `configs:` gets two warnings. This is the same drift that produced the `locations`/`reboot-advice` bug.

**Recommendation:** one `SETTINGS = {key: Setting(kind, nature, default, roles, desc…)}` table (probably in `config.py` or a new `settings.py`) from which `_KNOWN_TOP_KEYS`, `_SETTING_SECTIONS`, the `Config` getters (a generic `setting(key)` + typed wrappers) and the `actions.py` view are all generated. Ten boolean getters (`auto_tighten`, `reboot_advice`, `block_installer_shell_writes`, `detect_coexisting`, `adopt_installed`, `install_overlay_default`…) re-implement truthy parsing with three different token sets — `('true','yes','on','1')` vs `not in ('false','no','off','0')` vs `not in ('allow','false',…)` — a `_bool_setting(key, default)` helper collapses them.

### [MED] correctness — `humon.from_file` in the layer stack rejects `{}` files (BADENCODING) while `troveio.load` already knows this **(demonstrated)**
- `configsys/layers.py:56,93` — `humon.from_file(...)` for `read_setting` and every layer; `configsys/troveio.py:23-40` — "from_file sniffs the byte encoding and rejects very short files (e.g. a `{}` ledger) with BADENCODING … We always write UTF-8".
- Probe: a file containing `{}\n` → `DeserializeError: BADENCODING`.

**Why:** a plugin data file of `{}` is skipped with a misleading "could not read (Unable to make trove: BADENCODING)"; a user config reduced to `{}` (e.g. after `remove_sections` strips everything, or a hand-edit) is a **fatal** `ConfigError` for the `user` role. Two parse paths with different failure modes for the same file type.

**Recommendation:** make `_visit`/`read_setting`/`read_manifest`/`read_trust` all go through `troveio.load`/`load_string` (one chokepoint, one error message, BOM-tolerant), and delete the direct `humon.from_file` calls.

### [MED] correctness — the surgical section scanner desyncs on real Humon strings and mis-inserts **(demonstrated)**
- `configsys/plugins.py:536-541` — `_skip_trivia` treats `\` as an escape inside `"…"`/`'…'`; `troveio.py:60` — "Humon has no escapes". Probe: `{ path: "C:\"\n pins: {…}\n plugins: [] }` — humon parses three keys, `_locate_section_span(text,'plugins')` returns `None`.
- `:536` — backtick strings are not recognised; probe: `{ x: \`a"b\`  plugins: [ … ] }` → `None`. Yet `_scalar` (`troveio.py:63-68`) *emits* backtick strings, so configsys can write a file its own scanner cannot re-read.
- `:629-630` — fallback insert uses `text.rstrip().rfind('}')`; probe: a file ending in `// trailing }` got `scope: user` inserted *inside the comment line* (setting silently lost); an empty file produced `    pins: { a: b }\n` with no braces (invalid).

**Why:** when the span is `None` the writer appends a second `plugins:`/`pins:` block → duplicate top-level key; when the brace heuristic misfires the edit is lost or the file becomes unparsable. These are the write paths for `pin set`, `config set`, `plugin add/remove`, picks, dispositions, theme.

**Recommendation:** drop the escape handling (match Humon: a quoted string ends at the next same quote), add `` ` `` as a third quote, and in `set_section` locate the root's closing brace with the same depth-aware scan (last `}` at depth 0) rather than `rfind`; if the file is empty/brace-less, write a fresh `{ … }` document. Add these three cases to `test_plugins.py::test_locate_section_span_*`.

### [MED] refactor — `remove_sections` still relies on `node.source_text` that `set_section` declared unreliable
- `configsys/plugins.py:612-619` — docstring: "the span is located by a comment/string-aware scan (NOT humon's node.source_text, whose comment-binding mis-reported the span and corrupted the file)".
- `configsys/plugins.py:867-906` — `remove_sections` uses `node.source_text`, then heuristically strips bound leading comments (`:885-894`), then `text.find(span)` (`:891`, first occurrence — wrong if the same text appears earlier, e.g. in a comment).

**Recommendation:** implement `remove_sections` on top of `_locate_section_span` (it already returns the exact key→value-end span) and delete the comment-stripping heuristic; keep `test_remove_sections_keeps_bound_leading_comments` as the regression.

### [MED] performance — plugin trees are content-hashed and manifests re-parsed many times per startup
- `plugin_identity` (`plugins.py:307-328`, reads every file under the tree): called from `layer_files→checksum_ok` (`:269`, when pinned), `status` (`:400`, for every code plugin — invoked from `Context` diagnostics at `app.py:211`, `plugin list`, the TUI Plugins screen `menu.py:4534`), and `load_code` (`:994` via `checksum_ok` **and** `:1000` — two full hashes per pinned code plugin). A primary plugin carries `dotfiles/`+`glue/`, so this is not a few files.
- `read_manifest` (`:231-239`) re-reads and re-parses `plugin.hu` in `effective_declared` (per decl, per traversal — called ≥5× per run from `app.py:153,210,258` and `actions.py`), `layer_files`, `status`, `splash_plugins`, `declared_conflicts`, `find_decl` (per decl per lookup), `sync`.
- `read_trust` (`:331-341`) re-reads the store for every `is_trusted` call inside `load_code`.

**Recommendation:** memoise per process keyed on `(path, mtime_ns, size)` for `read_manifest` and on the directory's newest-mtime for `plugin_identity` (or just once per `Context`, invalidated by `ctx.invalidate()`); read the trust store once in `load_code`.

### [MED] performance — `profiles_containing` is O(profiles × expansion) and is called per orphan
- `configsys/config.py:472-494` — expands `profile_own_components` and `profile_components` for every profile, for one `name`; `configsys/orphans.py:121` calls it once per known orphan.

**Recommendation:** build a memoised `{component: (direct, indirect)}` index once per `Config` (like `user_layer_components` at `:158-173`) and have `profiles_containing` read it. Same pattern is cheap to apply to `picks()` (`:359-373`, rebuilt on every `included()`/`requested()` call) and `theme()`/`keys()`.

### [MED] docs drift — `docs/config-format.md` describes retired constructs as current
- `:33,59` — `configs: [ dev ]` "which profiles apply to THIS machine" — retired (`layers.py:277` warns "retired — the matrix model installs from picks:").
- `:45,120-145` — a user-level `profiles:` is presented as the way to author; `layers.py:295-297` now warns "`profiles:` is retired in a user config".
- `:210` — "a per-binding **`prefer:`** rank" — CLAUDE.md: `standing` replaced `prefer:`; the names are gone.
- `:84` — default splash "`plain`" — renamed `braille-bar` (`docs/plugins.md:292`).
- `:91-93` — theme "a named `palette:` of styles" vs `Config.theme()` docstring `config.py:197` "the old `elements`/`palette` schema is ignored (a check warning)".
- No mention of `picks:`, `machine:`, `uninstall:`, `keys:`, `reboot-advice`, `orphans-ignore`, `disabled-drivers`, `installer-shell-writes*`, `adopt-installed`, `refresh-before-execute`, `install-overlay`, `effects`, `version-floors` — all live keys in `_KNOWN_TOP_KEYS`.

**Recommendation:** regenerate the "Your config file" block from the settings registry proposed above; this file is "the source for the configsys.hu(5) man page", so drift here ships to users.

### [MED] comment/code drift — stale module docstrings and design notes
- `configsys/plugins.py:10-13` — "P2b/P2c will add trusted loading … and the trust model" — both built (the file contains them).
- `configsys/layers.py:1-13` — machine settings listed as "configs / scope / pins"; `configs` retired; `:50-52` `read_setting` docstring cites "(e.g. `discover:`)" — discovery was removed (memory: discovery-removed).
- `configsys/config.py:1-8` — "`configs` (which profiles apply) … are machine SETTINGS"; `:15-20` comment lists `configs / scope / pins`.
- `configsys/config.py:144-181` — the dispositions block's docstrings describe "the disposition model" (`include/exclude live in the profiles themselves`) which was superseded by the matrix model; the code is still live (`actions.py:84-93,177-184`, `app.py:1436-1461`, `menu.py:2880,2920`) — verify whether `dispositions:`/NEW triage is still intended under picks, and either re-document or retire it.
- `configsys/plugins.py:281-282,304` — `_norm_sha` docstring vs `is_trusted` (`:370-373`) exact-compare: checksum decl compare is prefix/case-normalised, trust compare is not.

### [LOW] security — `CONFIGSYS_GIT_TOKEN` leaks into the command log and `--pretend` output
- `configsys/plugins.py:184-186` — token embedded in the URL; `configsys/runner.py:422-427` — `self.calls.append(full)` and `[pretend] {full}` echo the full command line.

**Recommendation:** pass the token via `GIT_ASKPASS`/`http.extraheader` in the env (`_noninteractive_git_env` already builds one), or redact `://<token>@` in `Runner.echo`/`calls`.

### [LOW] security — `plugin_identity` is not length-prefixed → constructible collisions **(demonstrated)**
- `configsys/plugins.py:322-327` — `path\0content\0` concatenation. Probe: tree `{a: b"X", b: b"Y"}` and tree `{a: b"X\0b\0Y"}` produce the **same** identity.

**Why:** not exploitable for `.py` code today (CPython rejects NUL in source) but any binary asset in a trusted tree (fonts, images a splash plugin might ship) makes the boundary ambiguous, and the identity is the trust anchor.

**Recommendation:** hash `len(path)\0path\0len(content)\0content` or hash each file's sha256 into a manifest list; bump the trust store format (existing approvals will read as `changed` once — document it).

### [LOW] security/no-surprises — `keys:` (TUI keybindings) merges from EVERY layer, including untrusted plugins
- `configsys/config.py:233-250` — "contributed by EVERY layer … (later wins per action)"; not in `_SETTING_SECTIONS`, so no `_FORBIDDEN_BY_ROLE` warning.
- `docs/config-format.md:22-24` and `docs/plugins.md:96-99` say `theme:` is "the one" cosmetic exception.

**Why:** a data plugin can rebind e.g. the uninstall/execute keys — not cosmetic. Recommend restricting `keys:` to `_MACHINE_ROLES` (repo < primary < user) or documenting it as a second exception and having `check` list which plugin layers contribute bindings.

### [LOW] security — trusted plugin code can claim a reserved transport scheme (only warned)
- `configsys/plugins.py:1278-1292` — `register_transport('github', fn)` overrides `_git_transport` for every other plugin's sync; `_RESERVED_SCHEMES` (`:38`) only feeds a `check` conflict string (`:1030-1031`).
- Acceptable given the code is trusted (it already runs as the user), but the docs (`docs/plugins.md:274-275`, "git stays the default") imply built-ins win as they do for version sources (`:1028-1029` "built-ins win"). Make the two hooks consistent: refuse reserved schemes in `register_transport` like `versions.register_source` does for built-ins.

### [LOW] dead code — leftovers from the profile/matrix iterations (verified against callers)
- **Do not exist (already removed):** `set_profile_membership`, `read_profiles`, `set_profiles`, `_emit_profiles`, `read_configs`, `set_configs`, `read_machines`, `set_machines`, `_emit_machines` — zero hits tree-wide (`grep -rn` over `*.py`, docs, tests). Nothing to delete; docs/plans that still name them are historical.
- `configsys/config.py:53` — `self._profiles = layers.merge_named(...)` is assigned and never read (the `_chain` built at `:58-63` replaced it); `layers.merge_named` (`layers.py:139-151`) then has no caller outside its own module except this dead assignment — **appears unused, verify** before removing (it is a plausible plugin-facing helper, but nothing in `__all__`/docs exports it).
- `configsys/config.py:20` — `_MACHINE_ROLES = ('repo', 'primary', 'machine', 'user')`: no code path ever assigns a layer the role `'machine'` (`Config.load:71-80`, `routes.load:223-227`, `app.py:1957-1960` only produce `repo/plugin/primary/user/include`). The `'machine'` entries in `role_ceilings` (`:411`) and `user_layer_components` (`:163`) are likewise phantom; the word collides with the `machine:` *setting* and the `actions.py` "machine nature", which is confusing. Remove or add a comment explaining it is reserved.
- `configsys/config.py:334-337` — `if v is False / if v is True` in `splash()`: humon materialises `true` as the string `'true'` (**demonstrated**), so these branches are unreachable for file-loaded layers.
- `configsys/config.py:32-34` — module-level `_selected_machine` exists only to be called from the method at `:350`; inline it.
- `configsys/plugins.py:951-958` — `_import_drivers`: only `test/test_example_plugin.py:35` uses it (docstring admits "stays for … its tests"). Move into the test or have the test use `load_code`.
- `configsys/plugins.py:684-699` — `_emit_map_packed` is used only by `set_dispositions`; if dispositions are retired it goes with them.
- `configsys/layers.py:281-282,295-297` — `_PROFILE_AUTHORING_ROLES` warns that a user/primary `profiles:` is retired, yet `Config.user_layer_components` (`:158-173`) and `profile_relation`/`role_ceilings` still give user-authored profiles semantic weight (menu attribution, NEW triage). One of the two is stale.

### [LOW] code reuse — eight near-identical single-file readers and five map emitters in `plugins.py`
- Readers with the identical skeleton "exists? → `materialize_string(read_text)` → `.get(key)` → shape filter": `read_manifest:231`, `read_trust:331`, `read_pins:639`, `read_dispositions:670`, `read_picks:711`, `read_dirs:744`, `read_scalar_section:777`, `read_list_section:795`, `read_theme:829`. `read_pins`/`read_dispositions`/`read_dirs` are byte-for-byte the same filter.
- Emitters: `_emit_pins:652`, `_emit_map_packed:684`, `set_dirs`'s inline lambda `:761-763`, `_emit_kv:813` (already handles dict/list/bool/scalar generically), `_emit_picks:725`, `write_trust:351`, `scaffold_primary:917-926`, plus `troveio.emit_hu` which none of them use.
- `_flat` (`plugins.py:767-773`) duplicates `config._leaves` (`config.py:23-29`) except for `str()`.
- The "remove when empty" prologue is repeated in `set_pins:664`, `set_dispositions:705`, `set_picks:738`, `set_dirs:758`, `set_scalar_section:789`, `set_list_section:806`, `set_theme:841`.
- `layers.merge_name_overrides:170` and `merge_version_floors:190` are the same two-level dict overlay with a different section name.

**Recommendation:** `_read_top(config_file, key, shape='map'|'list'|'scalar'|'raw')` + `_write_top(config_file, key, value, packed=False)` built on `_emit_kv` (which already covers every shape used), leaving the specific names as one-line wrappers. Move `_scalar` out of `troveio`'s private namespace (`plugins.py:30` imports `troveio._scalar`) into a public `quote()`.

### [LOW] naming — misleading or overloaded names
- `plugins.set_section(user_config_file, …)` (`:612`) — the parameter is any `.hu` file (primary `plugin.hu`, plugin data files); rename to `path`. Same for `remove_sections`, `config_sections_text`.
- `Config.load(paths, plugin_files=…)` accepts either bare paths or `(path, role)` tuples (`:73-74`) while `routes.load` uses `_pf()` for the same; pick one shape.
- `status()` row key `'local'` (`:407`) means "authored in place", `'primary'` means "blessed"; `_decl` accepts `primary: true/'true'/'yes'` (`:75`) but not `on`/`1`, unlike every `Config` bool.
- `Config.PICKS_PROFILE = '@picks'` (`:357`) and `ALL_PROFILE = '!all'`/`UNINSTALL_PROFILE = '!uninstall'` use different reserved-prefix conventions; `PICKS_PROFILE` has no reader in this module.
- `layers.Layer.role` docstring (`:71`) lists `'include'` but not the `'machine'` value `config.py` tests for; `_FORBIDDEN_BY_ROLE` has no entry for `'user'`, `'repo'`, `'primary'` (correct) — say so in the comment rather than only for primary.

### [LOW] ABI/interface — `__all__` of the "frozen surface" mixes app-internal orchestration with the ABI
- `configsys/plugins.py:59-65` — `__all__` includes `declared, source_url, dir_name, read_manifest, layer_files, status, sync, set_declared, set_section, read_pins, set_pins` next to `Driver/register_*`; `test/test_abi_surface.py:13-20` only asserts the ABI names are present, so the internal names are implicitly promised but ungated. Meanwhile things plugin code plausibly needs (`plugin_identity`, `register_transport`'s `fn(runner, dest, source, ref)` contract, `Result` construction) are documented only in docstrings.
- Break candidates if the fixes above land: `dir_name` raising on bad input; `set_section`'s `emit(indent)` callback signature; `status()` row dict keys; `layer_files` returning `(path, role)`; the trust-store identity format (length-prefixing); `effective_declared` no longer following non-primary manifests. Each is used by `actions.py`/`app.py`/`tui/menu.py` and by external plugin repos only through the CLI — bumping `ABI_VERSION` is *not* needed for these, but trim `__all__` to the real ABI and document the rest as internal so the next change doesn't have to guess.

### [LOW] test gaps (against the ten coverage files)
- No test for: `dir_name` on `..`/`.`/empty; a `-`-prefixed source/ref reaching git; an include that resolves to a root layer path; a `{}` data/user file; `_locate_section_span` with a backslash before a closing quote, a backtick string, an empty file, or a `}` inside a trailing comment; manifest `code:`/`data:` outside the plugin dir; symlinked dirs in `plugin_identity`; `unknown_section_warnings` accepting every key the settings table knows (`locations`, `reboot-advice` would fail today); a non-primary plugin setting `picks:`/`dirs:` being ignored *with* a warning; `keys:` contributed from a plugin layer; `plugin_identity` collision resistance; `plugin remove` never deleting outside `plugins_dir`.
- `test_plugin_trust.py::test_is_trusted_requires_exact_commit` name is stale (identity is a content hash, not a commit).
- Good coverage exists for the happy paths: sync/branch/tag/detach semantics, checksum quarantine, trust lifecycle, section writer round-trips, primary/plugin role gating for `scope`/`pins`, `+self`/`~` profile algebra, picks read/write. The gap is adversarial input, not features.

### [NIT] `ledger.py` / `troveio.py`
- `ledger.py:41-46` — `ch['locked']` on a humon node: a missing key returns `None` (fine) but a key whose value is a dict/list will `.value` to `None`/crash; harmless for a machine-written file. `Ledger.load` reads the file twice (`:32` `read_text` to test blankness, then `load(p)`), and `troveio.load_string` already raises `'empty humon document'` — catch that instead.
- `troveio._scalar:52-68` — `None` serialises as `""` (an empty string, indistinguishable from `''` on reload); `emit_hu` is unused by the section writers that would benefit from it.
- `layers.materialize:36` silently drops dict children with an empty key.
- `plugins.py:1004-1005` — `dict(versions._SOURCES)` / `dict(_TRANSPORTS)` / `dict(splashes._SPLASHES)` snapshot-diff is done per plugin, O(registrations × plugins); fine today.
- `plugins.py:97,1304` — `stack.pop(0)` on a list (use `collections.deque`).
- `plugins.py:938-942` — `sys.modules[f'configsys_plugin_{pdir.name}']` is derived from the dir name; two plugins whose dir names differ only by characters invalid in identifiers still get distinct keys, but the name is never cleaned — cosmetic.
