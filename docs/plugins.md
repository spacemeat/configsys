# Plugins

> **Status: REFERENCE** — what a plugin is, how you add, sync, pin and trust one, your primary
> plugin, machine-level plugins, and the ABI a code plugin targets; maintained.

A plugin is a git repository — remote or on your disk — that adds to configsys: components, OS
blocks, profiles, name patches, a theme, and, when it ships code, new drivers, version sources,
sync transports, or startup splash screens. You declare plugins in your config, `configsys plugin sync`
fetches them, and their data merges into the same layer stack as the shipped `routes.hu`. A plugin
that ships anything configsys would run as a program stays inert until you trust its exact content.

For a guided build of a complete code plugin, see
[examples/examplos/WALKTHROUGH.md](../examples/examplos/WALKTHROUGH.md).

## 1. What a plugin is

A plugin is a directory synced to `~/.config/configsys/plugins/<name>/`:

```
plugins/examplos/
├── plugin.hu      # the manifest (below)
├── routes.hu      # data: os blocks / components / profiles / component-names (a layer)
└── driver.py      # optional: Python code (drivers, splashes, hooks)
```

A plugin is **a layer (data) plus optional code**. Data alone covers most needs: an OS block that
reuses a package manager configsys already has (a derivative distro, say, on apt) is pure data.
A *new* package manager needs a `Driver` subclass, which is code.

The `<name>` directory is the last segment of the plugin's source, minus any `.git`
(`github:you/configsys-mine` → `configsys-mine`).

## 2. The manifest — `plugin.hu`

```humon
{
    name:         examplos
    requires-abi: 1                          // the plugin ABI it targets (§7)
    provides:     { os: [ examplos ]  drivers: [ toybox ] }   // what it brings (see below)
    data:         [ routes.hu ]              // layer files (default: every top-level .hu but plugin.hu)
    code:         driver.py                  // ONE Python module to load; its presence = "ships code"
    plugins: [                               // optional: further plugins this one brings along
        { source: "github:someone/configsys-extras"  ref: v1.0.0 }
    ]
}
```

The manifest is optional for a data-only plugin: without one, every top-level `.hu` file loads.

- **`name`** — what `plugin list` shows and what plugin commands accept (the directory name works
  too).
- **`requires-abi`** — configsys loads the plugin only if this number is in its supported set
  (§7). Omitted means the current ABI.
- **`provides`** — mostly informational, read without running any code. `provides.drivers`
  matters: it tells `check` that an unregistered `via: toybox` is *waiting for trust*, not a
  typo, so you get one "run `configsys plugin trust`" nudge instead of an unknown-driver error. It
  also lets `plugin list` and `check` warn when a plugin's driver replaces a built-in one.
  `provides.splashes` names the splash screens the plugin's code registers (§7b).
- **`code:`** — present means this is a **code plugin** and needs trust (§6). Absent means
  data-only.
- **`plugins:`** — any plugin may list further plugins here; `sync` fetches them and they load
  like plugins you declared yourself. Your primary plugin (§8) uses this to bring your whole plugin
  set to a new machine. A plugin listed here can never be primary.

## 3. Where plugin data sits

Each synced plugin's data files become layers. Precedence, lowest to highest:

```
repo (routes.hu + config.hu)  <  plugins (declaration order)  <  primary plugin  <  your config
```

Your `~/.config/configsys/configsys.hu` always wins over a plugin. What a plugin's data may
contribute:

- **`components:`** — new components, or additions to existing ones. Bindings merge across layers
  by `(via, when)`, so a plugin can add an install method to a shipped component without restating
  the rest.
- **`os:`** and **`drivers:`** — new OS blocks (derivative distros) and driver settings.
- **`component-names:`** — per-driver package-name patches for components it doesn't own
  (`{ toybox: { ripgrep: rg  nmap: {} } }`: a string renames, `{}` means "not packaged here").
- **`profiles:`** — browse-only profiles. A profile with the same name as a lower layer's replaces
  it, unless its term list includes itself (`+<its own name>`), which amends the lower definition
  in place instead.
- **`theme:`** and **`keys:`** — cosmetic, so every layer may contribute them, merged per key
  (see [theming.md](theming.md)). A theme-only plugin works however it is wired in.
- **`facets:`** — detection probes; these run shell commands, so they load only once the plugin is
  trusted (§6).

A plain plugin may **not** set machine settings (`picks:`, `machine:`, `scope:`, `pins:`, …);
they are ignored. Only your primary plugin (§8) may.

`configsys where <component>` shows which file defined a component, plugin files included.

## 4. Adding, syncing and updating plugins

Your config declares plugins; `sync` makes the plugins directory match. Because the list lives in
your config, it travels with it and reproduces on another machine.

```humon
// ~/.config/configsys/configsys.hu
plugins: [
    { source: "github:someone/configsys-mydistro"   ref: v1.2.0 }
    { source: "gitlab:me/mytools"                    ref: 3f9a1c2 }
    { source: "/home/me/src/configsys-local" }
]
```

A `github:`/`gitlab:` source contains a colon, so **quote it** in a `.hu` file.

**Sources.** `github:owner/repo` and `gitlab:owner/repo` expand to https clone URLs. Any git URL,
an ssh source (`git@host:owner/repo.git`), a `file:` URL, or a local path works too. A local source
must be a git repository: configsys clones it, so `sync` picks up what you have *committed* there.
A local path is saved as an absolute path when you add it.

**Refs.** `ref:` is a tag, commit, or branch. A tag or commit checks out exactly that; a branch
fast-forwards to the remote's tip on each sync; no `ref:` follows the remote's default branch.
For a plugin that ships code, pin a tag or commit — trust re-arms on any content change anyway
(§6).

**Content pin.** An optional `sha256:` on an entry locks the plugin to an exact content hash. If
the synced tree doesn't match (a moved tag, a compromised mirror, tampering), the plugin is
**quarantined**: neither its data nor its code loads, and `plugin list` shows `CHECKSUM MISMATCH`.
`plugin add --pin` / `plugin update --pin` fill the hash in from what was just synced.

**Private repos.** Fetches never prompt for credentials — an unreachable or private repo fails
fast. To reach a private repo, use an ssh source, a credential-bearing URL, or a configured git
credential helper. For CI, `CONFIGSYS_GIT_TOKEN` embeds a token into a `github:`/`gitlab:` https
clone URL (it then persists in the synced repo's `.git/config`, so prefer ssh or a helper on a
personal machine). For `github:`/`gitlab:` sources, configsys sets the clone's *push* URL to ssh,
so you can push a plugin you author without a token.

### The commands

| Command | What it does |
| --- | --- |
| `configsys plugin add <source> [--ref R] [--pin] [--local] [--replace]` | Sync the source first; only if that works, declare it. With a primary plugin set, the entry goes into the primary's manifest (so it travels); `--local` keeps it in this machine's config instead (§9). `--replace` swaps out an already-declared plugin of the same name from another source. |
| `configsys plugin sync` | Fetch every declared plugin (and the plugins they list) to its ref, and report how your component set changed. New or changed code stays inert until trusted. |
| `configsys plugin list` | Each plugin: source, ref, `[primary]` / `[via primary]`, and status — not synced, ok, incompatible ABI, checksum mismatch, local (unpushed), and whether its code or recipes are trusted. Also lists name conflicts between plugins and built-in drivers a plugin replaces. |
| `configsys plugin update [name] [--ref R \| --latest] [--pin]` | Re-pin and re-sync one plugin. `--latest` pins the newest stable version tag on the remote (`v1.2.3` style; pre-release tags ignored), else `main`/`master`. Omit the name (or pass `--all`) to update every plugin; locally authored ones are skipped, and it exits 1 if any fail. |
| `configsys plugin remove <name>` | Undeclare the plugin (wherever it's declared) and delete its synced copy. |
| `configsys plugin trust [name \| --all]` / `untrust <name>` | Approve / revoke a plugin's current content (§6). No name, or `--all`, trusts every currently untrusted or changed plugin. |
| `configsys plugin bless <source>` / `unbless` | Make a plugin your primary (§8), or clear that. `bless none` also clears. |
| `configsys plugin init [name] [--dry-run] [--force]` | Create your primary plugin from local bits, or merge them into the existing one (§8). |
| `configsys plugin set-source <name> <source>` | Repoint a plugin you authored in place (such as one `plugin init` made) to its pushed remote, e.g. `github:you/name`; `sync` then fetches from there. To move a plugin configsys cloned to a different source, use `plugin add <source> --replace`. |

The TUI **Plugins** screen (key `3`) shows the same tree, with a diff of what updating the
selected plugin to its remote ref would change — review it before you trust. Keys: `a` add, `x`
remove, `s`/`S` sync one/all, `u`/`U` update one/all, `v` set the ref, `t`/`T` trust one/all,
`b`/`B` bless/unbless.

## 5. When a plugin fails

A plugin that is unsynced, unreachable, malformed, ABI-incompatible, quarantined, or untrusted is
**skipped with a warning — never fatal**. Where its data still loads but its driver isn't
registered (untrusted code), components that need that driver show the `untrusted` status with a
"run `configsys plugin trust <name>`" note; nothing is bricked and nothing is silently installed
the wrong way. An offline sync just leaves the plugin as it was.

**Conflicts.** When two plugins define the same component, OS block, or driver name, the one
declared last wins. `plugin list` and `check` name such collisions. A plugin driver with the same
name as a built-in one *replaces* it everywhere — legitimate as a deliberate override, but
reported, because the plugin's copy then runs instead of core's fixes. Collisions that only show
up when code runs (two plugins registering the same version source, transport or splash) are
reported by `check`.

## 6. Trust

The dividing line is **does configsys run something from it as a program** — and some data does.

- **Inert data plugins** — components installed through package managers and downloads (apt,
  flatpak, tarball, …), OS blocks, profiles, themes. These sync and load freely. The worst case
  is bad definitions, which `configsys check` catches, and installs stay explicit.
- **Command-carrying data** — a `via: script` or `via: source` binding, an apt
  `source-line:`/`ppa:`/`apt-source:`, a glue snippet with a `#!cs-eval` directive, or a
  `facets:` `detect:` probe. configsys runs these as shell commands, so they need the same trust as
  code: until you approve the plugin, its recipes are refused with a "run `configsys plugin trust
  <name>`" message, and its facets are ignored.
- **Code plugins** (a `code:` module) — not imported, and their drivers not registered, until
  trusted.

Trust is an explicit command, never an inline prompt, so the CLI stays scriptable:

```console
$ configsys plugin list
  examplos               github:you/configsys-examplos @v0.1.0
                         ok  [ships code — untrusted; run: configsys plugin trust examplos]
$ configsys plugin trust examplos
configsys: trusted examplos @ bd14ddac0922 — its code will run
```

An approval records the plugin's **content hash** — a sha256 over every file in the plugin
directory except `.git/`, `__pycache__/` and `*.pyc`. Any change to the files, from a new release
or from tampering with the synced copy, changes the hash: `plugin list` then shows *changed since
trust* and the code stays off until you trust it again. Because the hash covers content rather
than a git commit, it works for plugins fetched by any transport. Approvals live in
`~/.config/configsys/plugin-trust.hu`, keyed by the plugin's directory name.

Your primary plugin follows the same rule: if it carries code or command-carrying data, trust it
too.

## 7. Writing code: the ABI

Everything a code plugin may use is re-exported from one module:

```python
from configsys.plugins import (Driver, Result, register_driver, register_version_source,
                               register_transport, Splash, SplashFrame, register_splash,
                               ABI_VERSION, ABI_SUPPORTED)
```

Import nothing else from configsys — everything outside this list is internal and can change.

The contract is versioned by **one integer**:

- `configsys.plugins.ABI_VERSION` — the current plugin ABI (`1`).
- `configsys.plugins.ABI_SUPPORTED` — the set this configsys can load (`{1}`).
- A manifest declares `requires-abi: N`; configsys loads the plugin only if `N` is in
  `ABI_SUPPORTED`. Otherwise the whole plugin is skipped and `plugin list` shows `incompatible
  (needs plugin ABI N)`.

The number is bumped on any breaking change to the surface. An old number stays supported only
when configsys ships a compatibility shim for it.

### 7a. The `Driver` surface

A driver class subclasses `Driver` and is listed in a module-level `DRIVERS = [...]` export; the
loader calls `register_driver` on each **before resolution**, so `via: <name>` resolves. (A module
may also call `register_driver` itself for dynamic cases.) The `Driver` docstring is the
authoritative contract; in summary:

- **Class attributes:** `name`, `privileged` (mutations need sudo), `default_scope` (`user` or
  `system`), `honors_scope` (whether user/system is selectable per component).
- **Ops to implement:** `get_version(rc)`, `get_latest(rc)`, `is_locked(rc)` (reads; no root),
  and `install(rc)`, `uninstall(rc)`, `upgrade(rc)`, `set_version(rc, version)`, `lock(rc)`,
  `unlock(rc)` (mutations; return a `Result`). Implement what your manager supports.
- **Optional overrides:** `location(rc)`, `scope(rc)`. More optional hooks — batched enumeration, System Updates, version
  signals — are listed under [Optional hooks](#optional-hooks) below.
- **Helpers you may call:**
  - *resolve and fetch an artifact* — `resolve_version(rc, *, refresh=False)`,
    `download_url(rc, version)`, `download_target(rc, version=None)` (returns `(version, url)`:
    the URL plus the version of the release it actually fetches — record that one),
    `upstream_version(rc)`, `arch()`;
  - *install location and privilege* — `scoped_dir(raw, rc)`, `sudo(rc)`, `scope(rc)`,
    `display_path(p)`.
- **Construction:** `__init__(self, runner, paths=None)`. `runner.run(cmd, *, sudo=False,
  capture=True)` returns a `Result` (`.ok`, `.returncode`, `.stdout`) and honors `--pretend`.
  `paths` offers `.home`, `.env`, `.expand(path)`, and friends.
- **What a driver reads — `ResolvedComponent`:** `.key` (`driver\comp`), `.driver`, `.comp`,
  `.name` (`fields['name']` or the component name), `.fields` (the binding's fields),
  `.requested_as`, `.deps`.

Underscore members of `Driver` are internal and may change without an ABI bump.

#### Optional hooks

Beyond the ops above, the base `Driver` defines hooks the core calls when it needs more than one
unit at a time, or a signal the version string can't give. Each has a working default on the base
class, so a driver that overrides none of them still works — every unit is just probed one at a time,
and the driver stays out of the bulk features (System Updates, the orphan scan's package
enumeration). Override the ones your manager can answer.

The `Driver` docstring's frozen list names only some of these (the class attributes, `sudo(rc)`,
`scope(rc)` and `upstream_version(rc)`). The rest are public methods of the base class the core
calls today, but they are not yet in that list, so the ABI guarantee above does not cover them.

**Class attributes**

| attribute | default | what the core does with it |
|---|---|---|
| `privileged` | `False` | `True` = mutations need root. `actions.run_plan` asks `privileged` or `sudo(rc)` to decide whether to authenticate sudo once up front for the whole batch. (A plugin driver is assumed to need root regardless, so for plugin code this only documents intent.) It does **not** add sudo to your commands: pass `sudo=` to `runner.run` yourself, usually `sudo=self.sudo(rc)`. |
| `default_scope` | `'user'` | Your scope when the unit sets none: returned by `scope(rc)`, assumed by the default `get_installed`, and read by `sudo(rc)`. |
| `honors_scope` | `False` | `True` = user/system is selectable per unit. The core then stamps the machine's `scope:` setting onto your units that lack a `scope` field (`apply_scope_default`), flags it in the issues list (the TUI `!` page, the end of `configsys inspect`) when the installed scope differs from the declared one, and lets `configsys fix-scope` call `reconcile_scope`. Override `get_installed` too, so the scope you report is where the unit really is. |
| `holds_version` | `True` | `False` for a rolling manager that can neither hold a package nor install an older version (pacman, apk). The unit then never reads as locked, a `lock` op records no ledger hold, and the UI doesn't offer lock or set-version. Make `lock()` decline as well. |
| `native_backed` | `False` | `True` when your installs register in the OS package database (a `.deb`/`.rpm` installed with dpkg/rpm, a makepkg build installed with pacman). The orphan scan then looks for your units' packages under the native manager's index too (so they don't show as foreign orphans), and stranded-install detection treats the same package name under the native manager as the same install. |

**Scope and privilege**

- **`sudo(rc) -> bool`** — default: `True` exactly when the unit's effective scope (its `scope` field,
  else `default_scope`) is `system`. Called by `run_plan`'s up-front sudo check; your own ops use it
  for `runner.run(…, sudo=…)`.
- **`get_installed(rc) -> (version, scope)`**, or `(None, None)` when not installed — what inspection
  calls (instead of `get_version`) to learn where the unit actually is; `configsys location` uses it
  to show the real path. Default: `get_version(rc)` with `default_scope`. A scope-honoring driver
  overrides it to probe both scopes.
- **`reconcile_scope(rc, detected, target) -> Result`** — `configsys fix-scope` calls it when an
  installed unit sits in `detected` but its config says `target`. Default: install at `target` first,
  then uninstall at `detected` (a failed install leaves the old copy alone). Override it if you can
  move an install in place cheaply.

**Batched installed state** — one subprocess per manager instead of one per unit. This is the main
startup-time win; any driver whose manager can list what it has installed should implement it.

- **`installed_index() -> {key: version} | None`** — everything the manager has installed, from one
  enumeration. Used by: the detection tier (which method or provider is already installed — through
  the shared probe cache, pre-warmed for all drivers in parallel); the coexisting-install pass ("also
  present"); the orphan scan and the TUI install overlay; and the default `batch_index`. Return
  `None` if the manager isn't enumerable **or the command failed** — callers then fall back to a
  per-unit `get_version`. Never return `{}` on failure: that claims nothing is installed. Default:
  `None`.
- **`index_key(rc) -> str`** — the key a unit occupies in `installed_index()` (and in
  `upgradable_index()`). Default: `rc.name`. Override when your install identity isn't the resolved
  name (flatpak uses the app id).
- **`batch_index(rcs) -> context | None`** — the inspection prepass. Once per inspection, for each
  driver, the core passes the list of that driver's `ResolvedComponent`s it is about to probe; the
  drivers' prepasses run in parallel. Whatever you return is set on your driver instance as
  `self._batch` before `get_installed`/`get_latest`/`is_locked` run for each unit, so they can answer
  from memory. `None` or an exception = no batch, and each unit is probed on its own. Default:
  `{'installed': self.installed_index()}` (or `None`); a `get_version` can read it through
  `self._batched_version(rc)`, which returns `(version, hit)`. Override to fetch more in the same pass
  (apt adds its held and candidate sets; flatpak its remotes) — and if your context isn't the default
  shape, override `batch_installed_index` to match.
- **`batch_installed_index(batch) -> {key: version} | None`** — pulls the plain installed map back out
  of your batch context. After the prepass the core collects these per driver and seeds the TUI
  install overlay with them, so the overlay doesn't enumerate again. Default: `batch['installed']`.

`self._batch` and `_batched_version` are underscore members — internal by the rule above — even
though a batching driver needs them.

**Orphan scan**

- **`explicit_keys() -> set | None`** — the installed keys the user chose (manual / on-request), as
  opposed to dependencies. The orphan scan lists only these unless asked for everything; the TUI's
  System Updates group dims the rest (in the `standard` and `apps` tiers). `None` (default) = no such distinction, so every key counts as chosen.
- **`origin_index() -> {key: tier} | None`** — how fundamental each installed package is to the OS
  (apt's Priority: `required`/`important`/`standard`/`optional`/`extra`). The orphan scan carries the
  tier and hides the base tiers unless asked. Default: `None`.

**System Updates** — the bulk lane for upgradable OS packages that aren't configsys components (see
[system-updates.md](system-updates.md)). It consults only the OS's `native:` manager plus `flatpak`
and `snap`, so a plugin driver takes part when an OS block names it as `native:` (or when it replaces
one of those by name).

- **`upgradable_index() -> {key: (installed_version, candidate_version)} | None`** — everything the
  manager reports upgradable, in the same key space as `installed_index()`. Read the local index only
  (`configsys refresh` keeps it fresh); never refresh from here. `None` (default) = no bulk notion or
  the query failed; `{}` = up to date. Either way the manager is left out of the list.
- **`update_dedup_key(key) -> str`** — maps an upgradable key to the identity the managed-component
  exclusion compares against (what `index_key` gives for a component). A row is dropped when
  `(driver, update_dedup_key(key))` is a package some component could install here. Default: the key
  itself (flatpak maps its full ref to the app id).
- **`held_keys() -> set | None`** — keys held at the manager level (`apt-mark hold`, a flatpak mask,
  `snap --hold`). Those rows are marked held. Default: `None`.
- **`classify_index(keys) -> {key: tier}`** — sorts each upgradable key into one of
  `driver.UPDATE_TIERS` (`kernel`, `core`, `standard`, `apps`) so the list is grouped. `keys` is the
  upgradable set. Default: by name — kernel packages (`linux-image-*`, `linux-headers-*`, `kernel*`, …) →
  `kernel`, libc/glibc/musl → `core`, everything else → `apps`. A key you leave out is shown as `apps`.
- **`upgrade_all() -> Result | None`** — the apply step: the manager's own bulk upgrade (`apt
  upgrade`, `flatpak update`, `snap refresh`), not tied to any unit. Called by `configsys upgrade
  --system` after its confirmation, and by the TUI after it refreshes the native index. The manager
  itself keeps held packages back. `None` (default) = no bulk command; the CLI prints that it was
  skipped.

**Version signals**

- **`outdated_signal(rc) -> bool | None`** — inspection calls it only for an installed unit. `True` or
  `False` decides "outdated" outright; `None` (default) falls back to comparing the installed version
  with `get_latest`. flatpak overrides it because an update there is a new commit, often under the
  same version string.
- **`upstream_version(rc) -> str | None`** — the newest upstream release for a method that builds a
  version its route pins (a source recipe's `ref:`). The default reads the binding's
  `upstream: { <version spec> }` (the same spec forms as `version:`) and returns `None` if it is
  absent or can't be discovered; inspection and `configsys versions` call it only for bindings that
  declare `upstream:`. When it is newer than `get_latest` (the pinned version), the unit is a recipe
  pin behind upstream — `[R]` in `configsys inspect`, a detail line in the TUI — and is **not**
  outdated: upgrading rebuilds the pin. You normally declare `upstream:` rather than override this.
- **`version_advisory(rc) -> str | None`** — not on the base class; the core looks for it with
  `getattr`. If present, `configsys versions` shows the returned line as that method's note (pipx
  uses it to say a venv's python caps the installable version). It is never called during
  inspection, so it may do its own network read.

### 7b. Other hooks

All registered the same way — only trusted plugin code ever runs them.

- **Version sources** — `register_version_source(name, fn)` adds a `version: { <name>: <arg> }`
  backend. `fn(spec, fetch) -> (version, download_url_or_None)`; `fetch(url)` is the HTTP getter
  configsys injects (so caching and offline behavior stay in core). Built-in sources win over a
  registration with the same name.
- **Sync transports** — `register_transport(scheme, fn)` makes a `source: "<scheme>:..."` sync
  through `fn(runner, dest, source, ref)` instead of git. Because trust binds to content, a plugin
  fetched by a non-git transport can still ship trusted code.
- **Splash screens** — a startup wait-screen animation. Subclass `Splash`, set `name`, implement
  `render(frame)`, and export `SPLASHES = [...]` (alongside or instead of `DRIVERS`). configsys
  owns the frame loop, skip key and deadline, and hands each frame a `SplashFrame(progress,
  counts, label, dt, elapsed, done)`. List the names in the manifest's `provides.splashes`. Pick
  one with the `splash:` setting: a provider name, `random`, `off`, or unset for the built-in
  `braille-bar`. A plugin's own name also works when it provides exactly one splash (`splash:
  configsys-splash-blocks` is the same as `splash: blocks`). The **configsys-splash-ocean** plugin
  is a reference to copy.

The fictional ExamplOS plugin in [`examples/examplos/`](../examples/examplos/) is a complete,
copyable code plugin: an OS block, a `toybox` driver, a `via: toybox` component and a
`component-names:` map. Its one `os: { examplos: { using: linux  native: toybox } }` block makes
every shipped `via: native` component install through toybox on ExamplOS. Real OS plugins live in
their own repos (for example **configsys-proxmox**, and **configsys-void**, kept as a worked
example now that Void support ships in core — loading it makes its `xbps` driver replace the
built-in one, which `check` and `plugin list` report).

## 8. Your primary plugin

Your **primary plugin** is your personal configuration as a plugin: it travels with you to every
machine, and unlike other plugins it may also set **machine settings** (`picks:`, `scope:`,
`pins:`, `driver-preference:`, …). It sits just below your top config, so a local setting still
wins.

Only your top config can grant this — the entry carries `primary: true`, which
`configsys plugin bless <source>` writes for you (exactly one plugin is primary). A plugin listed
in another plugin's manifest is never primary.

On a fresh machine, a one-line top config that declares your primary is enough: `plugin sync`
fetches it and every plugin its manifest lists.

**Creating one.** `configsys plugin init [name]` (default name `configsys-<user>`) builds a
primary plugin in `~/.config/configsys/plugins/<name>/` from what you have locally:

- your captured dotfiles and your own glue snippets move into it;
- your config's `components:` overrides are copied into it (and removed from `configsys.hu`);
- the other plugins you declared move into its manifest's `plugins:`;
- it is `git init`ed, committed, and blessed. Its source is its own directory, so `sync` leaves
  it alone until you add a remote, push it, and run
  `configsys plugin set-source <name> github:you/<name>`.

If you already have a primary, `plugin init` merges your local dotfiles and glue into it instead
(`--force` overwrites ones already there; `--dry-run` shows the plan). Your picks move separately,
with `configsys picks to-primary`.

**Where edits go.** Each machine setting is either uniform (belongs in the primary, same on every
machine) or machine-local (belongs in this machine's config). configsys writes each edit to the
right place, and `configsys config move` (TUI Config screen `m`) carries a setting across. A new
`plugin add` lands in the primary's manifest too, unless you pass `--local`. Changes to a primary
reach your other machines once you commit, push, and bump its ref there.

## 9. Machine-level plugins

To make a source tree or an app's own `.hu` files contribute components to *this machine only*,
add it as a plugin with `--local`:

```console
$ configsys plugin add ~/src/myproject --local
```

The directory must be a git repository; configsys clones it, and `configsys plugin sync` picks up
what you commit there. This writes an ordinary (non-primary) entry to this machine's
`~/.config/configsys/configsys.hu`, even when you have a primary plugin, so it does not travel to
your other machines. It behaves like any plugin: it may add components, OS blocks and driver
settings, needs trust for anything that runs commands, and cannot set machine settings.

## 10. Not supported yet

- **Signature verification** (GPG) of plugin sources. The `sha256:` content pin is the practical
  form for now.
- **Windows and macOS** OS plugins. A plugin adding another OS root plus its package-manager
  driver is the shape that would cover them, but there is no test path yet.
