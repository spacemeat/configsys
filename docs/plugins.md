# Plugins — scoping

Status: **scoping** (no code yet). Design settled; decisions locked in conversation
2026‑07‑17. This is the north‑star for extending configsys with shareable, remote,
optionally‑code‑carrying layers. It builds directly on the layer stack (`configsys/layers.py`)
and the `Family` registry (`configsys/families/`).

## 1. Why

configsys is now usable enough to share. Other people won't care about *apod* or native
Steam on Pop; they'll want to add their own favorite OSs and route things differently — and,
crucially, some of that needs **code** (a new package manager = a new `Family`). Plugins let a
person publish, in a git repo, a self‑contained bundle that a configsys user can pull in:
routing data (+ profiles) and, when needed, Python `Family` extensions as first‑class siblings.

The archetype: a single plugin *is* "openSUSE support" — an `opensuse` os block, a `zypper`
`Family`, and `via: zypper` components — installed and working next to apt/dnf.

## 2. What a plugin is

A directory synced from a remote repo to `~/.config/configsys/plugins/<name>/`:

```
plugins/opensuse-support/
├── plugin.hu          # manifest (below)
├── routes.hu          # data: os / mechanisms / components (a layer)
├── profiles.hu        # data: profiles (optional; any .hu the manifest lists)
└── families.py        # optional: Python Family subclasses (the code escalation)
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
    code:         [ families.py ]              // Python modules to load — PRESENCE = "ships code"
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
Ubuntu, apt). A *new* mechanism needs a `Family` = code.

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
may still load (definitions), but if its `Family` isn't registered (untrusted/incompatible),
`via: <its-mechanism>` is unknown → components that need it surface as **resilient error rows**
(see the inspect/TUI resilience) telling you *why* ("plugin opensuse‑support is untrusted; run
`configsys plugin trust opensuse-support`"). You are never bricked and never silently
mis‑installed.

## 6. Trust model

The dividing line is **does it ship code** (`code:` in the manifest):

- **Data‑only plugins**: sync freely, no prompt. Worst case is bad component definitions,
  caught by `configsys check`, and installs stay explicit — "just data can't do too much harm."
- **Code plugins**: **explicit per‑commit opt‑in**. On sync / first use configsys prompts:

  > Plugin `opensuse-support` ships code (families: zypper). It runs with **your privileges**
  > during installs. Trust commit `abc123`? [y/N]

  Approval is recorded per `(plugin, commit)` in the state dir. A code update = a new commit =
  **re‑prompt** (never auto‑trust changed code). Until trusted, the plugin's code is not
  imported and its families are not registered (degrade per §5). This is direnv's `allow`, but
  per‑commit, because the blast radius is root.

Trust records live alongside the ledger (e.g. `~/.config/configsys/plugin-trust.hu`:
`{ opensuse-support: abc123def... }`).

## 7. The ABI (one coarse number — KISS)

The `Family` base + registration + the data schema + the `ResolvedComponent` shape together are
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

### 7a. Freeze + document the `Family` surface (the prerequisite work)

To version honestly, the public contract must be explicit and stable. Ship a
`configsys/plugins.py` that re‑exports the frozen surface (one import for plugin authors:
`from configsys.plugins import Family, register_family`). The contract, from today's
`configsys/component.py`:

**Class attributes a Family sets:** `name`, `privileged`, `default_scope`, `honors_scope`.

**Methods a Family MUST implement:** `get_version(rc)`, `get_latest(rc)`, `is_locked(rc)`,
`install(rc)`, `uninstall(rc)`, `upgrade(rc)`, `set_version(rc, version)`, `lock(rc)`,
`unlock(rc)`. Optional: `location(rc)`, `ensure_prereqs(rc)`.

**Provided helpers a Family MAY use (must stay stable per ABI):** `resolve_version(rc)`,
`download_url(rc, version)`, `scope(rc)`, and — currently underscore‑private but genuinely
needed by fetch/tarball‑like mechanisms — `_scoped_dir`, `_sudo`, `_arch`,
`_apply_placeholders`, `_disco_spec`. **Task: promote these to public names** (e.g.
`scoped_dir`, `sudo`, `arch`) or explicitly bless the underscore names as ABI‑stable, and
document them.

**Injection contract:** `__init__(self, runner, paths)`.
- `runner.run(cmd, *, sudo=False, capture=True) -> Result` (Result has `.ok`, `.returncode`,
  `.stdout`). Honors `--pretend`.
- `paths`: `.home`, `.env`, `.dotfiles_dir`, `.expand(path)` (+ the doc'd subset).

**`ResolvedComponent` (what a family reads):** `.family`, `.comp`, `.name` (property =
`fields['name'] or comp`), `.fields` (dict), `.vars`, `.requested_as`, `.deps`, `.key`.

**Registration:** a code module exports `FAMILIES = [SubclassOfFamily, ...]`; configsys imports
it (only if trusted) and registers each into the family registry **before resolution**, so
`via: <name>` resolves. Explicit export, not subclass‑scanning (no accidental registration).

Add `ABI_VERSION` from day one even if it never changes for a year — the affordance is *having*
it; retrofitting versioning after plugins exist is the expensive path.

## 8. Phasing (cross‑yourself order)

- **P1 — data plugins + sync.** Manifest, `plugins:` declaration, `plugin add/list/sync/
  update/remove`, git sync to pinned refs, plugin‑role layers in the stack, os‑block additions
  that reuse existing mechanisms. **No code, light trust.** Proves the whole distribution
  machinery on low‑risk data. Reuses ~everything.
- **P2 — code plugins.** `configsys/plugins.py` (the frozen, documented ABI surface) +
  `ABI_VERSION`/`ABI_SUPPORTED` + the manifest `requires-abi` gate; trusted‑only import of
  `code:` modules with per‑commit approval and the trust store; registration into the family
  registry; degradation for untrusted/incompatible. The big, careful one — built on P1's proven
  sync.

Mirrors how overrides shipped: prove the mechanism on the safe subset, then add the escalation.

## 9. Decisions locked

1. **Declarative `plugins:` list + `plugin sync`** (not imperative‑as‑source‑of‑truth); rich CLI.
2. **Piecemeal**: P1 (data + sync) then P2 (code + trust + ABI).
3. **One coarse ABI integer** (KISS); freeze + document the `Family` surface (`configsys/plugins.py`).
4. **Per‑commit trust for code**; data‑only plugins sync freely.

## 10. Open / deferred

- **Trust store format + `plugin trust`/`untrust` commands** (P2 detail).
- **Sync transport edge cases**: private repos (ssh/tokens), offline, checksum/signature
  verification of a pinned ref (belt‑and‑suspenders beyond commit pinning).
- **Plugin‑vs‑plugin ordering / conflicts**: two plugins define the same component or mechanism
  — declaration order wins (like other layers); surface collisions in `plugin list`/`check`.
- **Non‑Family extension points** (e.g. a plugin adding a version‑discovery source, or a new
  `source:` transport). Out of scope until asked; the ABI number covers them when they arrive.
- **README.md**: a user‑facing plugins section (and an overall project section) once P1 lands.
- **Windows/macOS**: still deferred; a plugin adding another OS root + `native` mechanism is
  exactly the shape that would absorb them, but no test path yet.
