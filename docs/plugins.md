# Plugins — scoping

Status: **P1 BUILT** (data plugins + sync — `configsys/plugins.py`, `configsys plugin
list/sync`); **P2 (code + trust + ABI gate) scoped, not built.** This is the north‑star for
extending configsys with shareable, remote, optionally‑code‑carrying layers. It builds
directly on the layer stack (`configsys/layers.py`) and the `Driver` registry
(`configsys/drivers/`).

P1 in a nutshell: `plugins: [ { source: "github:x/y"  ref: v1 } ]` in the user config, then
`configsys plugin sync` clones each to `~/.config/configsys/plugins/<name>/` at the pinned
ref; its `.hu` data files become `plugin`‑role layers (repo < plugins < discovered < user).
A plugin can add components AND os blocks (derivative distros). Unsynced / ABI‑incompatible /
malformed → skipped, never fatal (components degrade to resilient error rows). `ABI_VERSION`/
`ABI_SUPPORTED` live in `plugins.py`; the manifest `requires-abi` is already gated. NOTE: a
`github:`/`gitlab:` source has a colon, so it must be **quoted** in the .hu file.

## 1. Why

configsys is now usable enough to share. Other people won't care about *apod* or native
Steam on Pop; they'll want to add their own favorite OSs and route things differently — and,
crucially, some of that needs **code** (a new package manager = a new `Driver`). Plugins let a
person publish, in a git repo, a self‑contained bundle that a configsys user can pull in:
routing data (+ profiles) and, when needed, Python `Driver` extensions as first‑class siblings.

The archetype: a single plugin *is* "openSUSE support" — an `opensuse` os block, a `zypper`
`Driver`, and `via: zypper` components — installed and working next to apt/dnf.

## 2. What a plugin is

A directory synced from a remote repo to `~/.config/configsys/plugins/<name>/`:

```
plugins/opensuse-support/
├── plugin.hu          # manifest (below)
├── routes.hu          # data: os / mechanisms / components (a layer)
├── profiles.hu        # data: profiles (optional; any .hu the manifest lists)
└── drivers.py        # optional: Python Driver subclasses (the code escalation)
```

A plugin is **a layer (data) + optional code**. The data half is inherited wholesale from the
layer stack; the code half is the new, careful part.

### Manifest — `plugin.hu`

```
{
    name:         opensuse-support
    version:      1.2.0                 // the plugin's own version (informational)
    requires-abi: 1                     // the configsys plugin ABI it targets (see §7)
    provides:     { os: [ opensuse ]  mechanisms: [ zypper ] }   // informational / for `plugin list`
    data:         [ routes.hu, profiles.hu ]   // .hu layer files (default: all .hu but plugin.hu)
    code:         [ drivers.py ]              // Python modules to load — PRESENCE = "ships code"
}
```

`code:` present ⇒ this is a **code plugin** and requires trust (§6). Absent ⇒ **data‑only**.

## 3. Layer integration (mostly free)

Each synced plugin's `data:` files become `plugin`‑role layers in the stack. Precedence,
lowest → highest:

```
repo (routes.hu + config.hu)  <  plugins (declaration order)  <  discovered project files  <  user config
```

Plugins sit **above the repo but below your project and your machine config** — so your
`.configsys.hu` and `~/.config/configsys/configsys.hu` always win over a plugin. Merge, per‑name
override, provenance (`Component.source` → the plugin file), and `where`/`check` attribution all
come from the existing engine. A plugin can add os blocks and components; **os/mechanism blocks
that reuse an existing mechanism are pure data** (the derivative‑distro case, e.g. Linux Mint →
Ubuntu, apt). A *new* mechanism needs a `Driver` = code.

## 4. Distribution — declarative + `plugin sync`

The user config declares plugins; `sync` reconciles the plugins dir to match. Declarative (not
imperative add/remove as source of truth) so it travels with your config and is reproducible.

```
// ~/.config/configsys/configsys.hu
plugins: [
    { source: github:someone/configsys-opensuse   ref: v1.2.0 }
    { source: gitlab:me/mytools                    ref: 3f9a1c2 }
]
```

- `ref` is a **pinned** tag/commit (never a floating branch for code; §6). Fetched to
  `plugins/<name>/` at exactly that ref.
- `plugins:` is a machine SETTING (like `configs:`/`pins:`) — repo/user only, not settable by
  includes or discovered files.

### CLI (the nice experience)

- `configsys plugin add github:x/y[@ref]` — append to `plugins:` (+ optional immediate sync).
- `configsys plugin sync` — clone/fetch every declared plugin to its pinned ref; prune
  undeclared ones; report what changed; prompt for trust on new/changed **code** plugins.
- `configsys plugin list` — installed plugins: name, version, ref, data‑only|code, trust
  status, what they provide.
- `configsys plugin update [name]` — move the pin forward (re‑prompts trust on code change).
- `configsys plugin remove name` — drop from `plugins:` and delete the dir.

`git` is the transport (already a dependency‑world assumption); `source:` shorthands
(`github:`/`gitlab:`) expand to clone URLs, arbitrary git URLs allowed too.

## 5. Resilience / graceful degradation (inherited + extended)

A plugin that fails — unreachable, malformed, ABI‑incompatible, or an untrusted code plugin —
is **skipped with a warning**, never fatal, exactly like a bad discovered file. Its data layer
may still load (definitions), but if its `Driver` isn't registered (untrusted/incompatible),
`via: <its-mechanism>` is unknown → components that need it surface as **resilient error rows**
(see the inspect/TUI resilience) telling you *why* ("plugin opensuse‑support is untrusted; run
`configsys plugin trust opensuse-support`"). You are never bricked and never silently
mis‑installed.

## 6. Trust model

The dividing line is **does it ship code** (`code:` in the manifest):

- **Data‑only plugins**: sync freely, no prompt. Worst case is bad component definitions,
  caught by `configsys check`, and installs stay explicit — "just data can't do too much harm."
- **Code plugins**: **explicit per‑commit opt‑in**, via an explicit command (not an inline
  sync prompt — the CLI stays non‑interactive and scriptable):

  ```
  $ configsys plugin list          # a code plugin shows: ships code — untrusted
  $ configsys plugin trust opensuse-support   # records the on-disk commit
  ```

  Approval is recorded per `(plugin, commit)` in the trust store. A code update = a new commit
  = the trust no longer matches → `plugin list` shows *changed since trust* and the driver stays
  unregistered until you `trust` again (never auto‑trust changed code). Until trusted, the
  plugin's code is not imported and its drivers are not registered (degrade per §5). This is
  direnv's `allow`, but per‑commit, because the blast radius is root. (A convenience
  prompt‑on‑sync could layer on top later; the store + gate don't depend on it.)

Trust records live in the state dir (`~/.config/configsys/plugin-trust.hu`, keyed by the
plugin's dir name — stable across commits, unlike the manifest name:
`{ opensuse-support: abc123def... }`).

## 7. The ABI (one coarse number — KISS)

The `Driver` base + registration + the data schema + the `ResolvedComponent` shape together are
the contract a plugin codes against. Version the whole thing with **one coarse integer**:

- `configsys.ABI_VERSION = 1` — the current plugin contract.
- `configsys.ABI_SUPPORTED = frozenset({1})` — the set this build can load.
- A plugin manifest declares `requires-abi: N`.
- **Load rule**: `requires-abi ∈ ABI_SUPPORTED`, else refuse the *whole* plugin with a clear
  message — *"plugin needs configsys with plugin ABI 2 — upgrade configsys"* or *"plugin targets
  ABI 1, no longer supported — update the plugin"*. Skipped → components degrade (§5).
- **Bump** `ABI_VERSION` on any breaking change to the surface. Old versions stay in
  `ABI_SUPPORTED` **only if we ship a compat shim** — that's the whole affordance: the number is
  the *hook* to make a deliberate keep‑old‑plugins‑working decision instead of breaking silently.

Deliberately NOT split into data‑ABI vs code‑ABI for now (KISS); split later only if they
diverge.

### 7a. Freeze + document the `Driver` surface (the prerequisite work) — ✅ BUILT

To version honestly, the public contract must be explicit and stable. The frozen surface is
re‑exported from `configsys/plugins.py` — one import for plugin authors:
`from configsys.plugins import Driver, register_driver` (plus `ABI_VERSION`/`ABI_SUPPORTED`).
The `Driver` base class docstring (`configsys/driver.py`) is the authoritative contract, and
`test/test_abi_surface.py` is the regression gate. `register_driver(cls)` binds a subclass so
`via: <cls.name>` resolves (usable as a decorator; rejects a nameless driver).

**Design goal for the freeze (per the P2 decision): keep the surface MINIMAL and cogent.**
Don't just promote every underscore helper 1:1 — while freezing, consolidate: bundle related
helpers by co‑usage into a smaller, coherent public API, without losing functionality. E.g. the
fetch/version helpers (`resolve_version`, `download_url`, `_disco_spec`, `_apply_placeholders`,
`_arch`) form one cluster ("resolve + fetch an artifact"); the path/scope helpers
(`_scoped_dir`, `_sudo`, `scope`) another ("where + with what privilege does this install").
Present each cluster as a tight, documented set so a plugin author reads a small, obvious API,
not a pile of underscore methods. The contract inventory, from today's `configsys/component.py`:

**Class attributes a Driver sets:** `name`, `privileged`, `default_scope`, `honors_scope`.

**Methods a Driver MUST implement:** `get_version(rc)`, `get_latest(rc)`, `is_locked(rc)`,
`install(rc)`, `uninstall(rc)`, `upgrade(rc)`, `set_version(rc, version)`, `lock(rc)`,
`unlock(rc)`. Optional: `location(rc)`, `ensure_prereqs(rc)`.

**Provided helpers a Driver MAY use (ABI‑stable), promoted to clean public names and clustered
by co‑usage:**
- *resolve + fetch an artifact* — `resolve_version(rc, *, refresh=False)`,
  `download_url(rc, version)`, `arch()`.
- *install location / privilege / display* — `scoped_dir(raw, rc)`, `sudo(rc)`, `scope(rc)`,
  `display_path(p)`.

`_scope`, `_apply_placeholders`, and `_disco_spec` stay underscore‑internal — implementation
details behind the public helpers, changeable without an ABI bump. (`_scope` == `scope` for the
scope‑honoring drivers that used to call it, so subclasses now just call `scope(rc)`.)

**Injection contract:** `__init__(self, runner, paths)`.
- `runner.run(cmd, *, sudo=False, capture=True) -> Result` (Result has `.ok`, `.returncode`,
  `.stdout`). Honors `--pretend`.
- `paths`: `.home`, `.env`, `.dotfiles_dir`, `.expand(path)` (+ the doc'd subset).

**`ResolvedComponent` (what a driver reads):** `.driver`, `.comp`, `.name` (property =
`fields['name'] or comp`), `.fields` (dict), `.vars`, `.requested_as`, `.deps`, `.key`.

**Registration:** a plugin's code module exports `DRIVERS = [SubclassOfDriver, ...]`; the
trusted loader imports the module and calls `register_driver(cls)` (re‑exported from
`configsys.plugins`) on each **before resolution**, so `via: <cls.name>` resolves. Explicit
export, not subclass‑scanning — no accidental registration (a module may also call
`register_driver` itself for dynamic cases). Built.

Add `ABI_VERSION` from day one even if it never changes for a year — the affordance is *having*
it; retrofitting versioning after plugins exist is the expensive path.

## 8. Phasing (cross‑yourself order)

- **P1 — data plugins + sync. ✅ BUILT.** `configsys/plugins.py` (declared/source_url/dir_name/
  read_manifest/layer_files/status/sync), `plugins:` declaration, `configsys plugin list/sync`,
  git sync to pinned refs, `plugin`‑role layers in the stack, os‑block additions (derivative
  distros), `ABI_VERSION`/`ABI_SUPPORTED` + the `requires-abi` gate already live.
- **P1.5 — the nice CLI. ✅ BUILT.** `configsys plugin add <source> [--ref R]` (declare + sync),
  `remove <name>` (undeclare + delete the synced dir), `update <name> [--ref R]` (re-pin +
  re-sync). Edits the `plugins:` list IN PLACE via a comment-preserving surgical rewrite
  (`plugins.set_declared` replaces the `plugins:` node's exact `source_text` span, or inserts a
  block before the root's closing brace — every other line, comments and all, is untouched).
- **P2 — code plugins.** Built on P1's proven sync, in slices:
  - **P2a — freeze the ABI surface. ✅ BUILT.** `configsys/plugins.py` re‑exports `Driver`,
    `register_driver`, `Result` (the mutating‑op return type), `ABI_VERSION`, `ABI_SUPPORTED`;
    the helper surface is promoted/clustered (§7a); the `Driver` docstring is the contract;
    `test/test_abi_surface.py` gates it.
  - **P2b — trusted loading + trust store.** The big, careful one, in two steps:
    - *trust store + commands: ✅ BUILT.* `~/.config/configsys/plugin-trust.hu` maps
      `dir_name(source) → approved commit sha` (keyed by dir name — stable across commits,
      unlike the manifest name). `configsys plugin trust <name>` records the on-disk HEAD;
      `untrust` revokes; `plugin list` classifies each code plugin (trusted / untrusted /
      changed-since-trust) and nudges. Per-commit: a moved HEAD reads as `changed` → re-approve.
    - *the import gate: ✅ BUILT.* `plugins.load_code` imports a plugin's `code:` module and
      registers its `DRIVERS` export **iff** synced + ABI‑ok + trusted at the on‑disk commit;
      `Context.ensure_plugin_code` runs it once before resolution (via the `routes` property
      and `check`). Untrusted/incompatible/broken code is skipped (collected into
      `plugin_code_warnings`, surfaced by `check`) so its `via:` stays unknown and the
      component degrades to a resilient error row — never fatal.
  - **P2c — registration hooks beyond drivers. ✅ BUILT.** Two more `register_*` hooks on the
    frozen surface, gated identically (only trusted plugin code ever calls them):
    `register_version_source(name, fn)` adds a `version: { <name>: <arg> }` discovery backend
    (`fn(spec, fetch) -> (version, url)`; built-ins win over a same-named registration), and
    `register_transport(scheme, fn)` claims a `source: "<scheme>:..."` sync scheme (git stays the
    default; `dir_name` now strips any `scheme:` prefix). Caveat: per-commit code trust needs a
    git commit id, so a non-git transport can carry DATA but its `code:` stays untrusted until a
    content-identity scheme exists — transports are for data plugins today. `test_plugin_hooks.py`.
  - **Example plugin. ✅ BUILT** — `examples/configsys-alpine/` (`plugin.hu` + `routes.hu` +
    `driver.py`): an `apk` `Driver` + an `alpine` os block + a `via: apk` component (`doas`). A
    copy‑able reference/template that dogfoods the whole code‑plugin path — and shows the payoff
    that one `os: { alpine: { native: apk } }` block makes every repo `via: native` component
    (btop, ripgrep, …) install on Alpine. `test/test_example_alpine.py` exercises it
    add→trust→resolve. (Publish it as a standalone git repo to `plugin add` it for real.)

Mirrors how overrides shipped: prove the mechanism on the safe subset, then add the escalation.

## 9. Decisions locked

1. **Declarative `plugins:` list + `plugin sync`** (not imperative‑as‑source‑of‑truth); rich CLI.
2. **Piecemeal**: P1 (data + sync) then P2 (code + trust + ABI).
3. **One coarse ABI integer** (KISS); freeze + document the `Driver` surface (`configsys/plugins.py`).
4. **Per‑commit trust for code**; data‑only plugins sync freely.

## 10. Open / deferred

**Resolved:**
- ~~Trust store + `plugin trust`/`untrust`~~ — P2b.
- ~~Non‑Driver extension points~~ — P2c added `register_version_source` + `register_transport`
  as the small `register_*` set on the frozen surface, all trust+ABI gated.
- ~~README plugins section~~ — done (README.md + `examples/configsys-alpine/`).
- ~~Untrusted‑driver `via:` reads as a scary unknown‑via *error*~~ — fixed: a declared‑but‑gated
  code plugin's `provides.drivers` are treated by `check` as *pending trust* (suppressed as an
  error), so the single signal is the "run `plugin trust`" nudge. Declaring `provides: { drivers:
  [...] }` in the manifest is what enables this — without it, an unregistered `via:` still reads
  as unknown.
- ~~Plugin‑vs‑plugin conflict surfacing~~ — `plugins.declared_conflicts` finds names (component /
  os block / driver via `provides.drivers`) claimed by 2+ synced+compatible plugins, from
  manifests + data files (no code run). `plugin list` prints them as a footer and `check` as
  warnings, both with attribution and "(last declared wins)". `test/test_plugin_conflicts.py`.
  Gap: version‑source / transport *registration* collisions are code‑only (self‑registered), so
  they aren't detected declaratively — deferred with the non‑git‑identity work.

**Still open:**
- **Non‑git code trust identity.** Per‑commit trust binds to a git commit sha, so a plugin
  fetched by a non‑git transport can supply DATA but its `code:` can't be trusted. A
  content‑hash identity (hash the plugin tree) would let tarball/OCI code plugins be trusted too.
- **Sync transport edge cases**: private repos (ssh/tokens), offline, checksum/signature
  verification of a pinned ref (belt‑and‑suspenders beyond commit pinning).
- **Windows/macOS**: still deferred; a plugin adding another OS root + `native` driver is exactly
  the shape that would absorb them, but no test path yet.
