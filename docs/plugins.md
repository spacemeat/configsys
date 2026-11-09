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

A plugin may also ship `dotfiles/` (app config content) and `glue/` (shell snippets) trees.

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

Your `~/.config/configsys/configsys.hu` always wins over a plugin. The same rule holds for every
layer — the repo, each plugin, your primary, your top config, and any file one of them includes: any
layer may **define** things (the sections below); only your top config and your primary plugin may
**set machine settings**. What a plugin's data may contribute:

- **`components:`** — new components, or additions to existing ones. Bindings merge across layers
  by `(via, when)`, so a plugin can add an install method to a shipped component without restating
  the rest.
- **`os:`** and **`drivers:`** — new OS blocks (derivative distros) and driver settings. A
  `drivers:` entry's `requires:`, `standing:` and `when:` apply to every binding that driver
  installs, including `via: native` bindings that resolve to it on an OS whose `native:` it is (on
  Fedora Atomic, `brew`'s requires cover every `via: native` component). Its `requires:` also
  decides where the driver is valid at all: where they can't be met, none of its bindings is a
  candidate (the derived driver gate); `when:` is the explicit gate for a fact that isn't a
  requirement ([routing-model.md §8a](routing-model.md#8a-choosing-among-valid-methods)). The
  preference knobs — an OS block's `driver-preference:`, a `drivers:` entry's `standing:` and
  `when:` — count from an ordinary (non-primary) plugin only on a block or driver that plugin
  defines itself; on one a lower layer already defined they are ignored, and `check` names each
  (`plugin-preference`). Your primary and your top config may set them anywhere.
- **`component-names:`** — per-driver package-name patches for components it doesn't own
  (`{ toybox: { ripgrep: rg  nmap: {} } }`: a string renames, `{}` means "not packaged here").
- **`profiles:`** — browse-only profiles. A profile with the same name as a lower layer's replaces
  it, unless its term list includes itself (`+<its own name>`), which amends the lower definition
  in place instead.
- **`theme:`** — cosmetic, so every layer may contribute it, merged per key (see
  [theming.md](theming.md)). A theme-only plugin works however it is wired in.
- **`keys:`** — key rebindings, merged per key like `theme:`, but a plugin's count only once the
  plugin is trusted (§6): a rebind could turn a harmless key into "trust every plugin". `check`
  names the ones it ignores.
- **`facets:`** — detection probes; these run shell commands, so they load only once the plugin is
  trusted (§6).

A plugin's data file may `include:` other files, but only inside its own checkout; an include
that leaves the checkout, or that names a root layer (your top config, your primary's file, the
repo's), is ignored with a warning.

A plain plugin may **not** set machine settings (`picks:`, `machine:`, `scope:`, `pins:`, …), and
neither may a file pulled in with `include:`. They are ignored, and `configsys check` (and the TUI
`!` page) warns about each one so it isn't a silent drop. The machine settings are the
machine-setting sections of the one settings registry, `settings.SETTINGS` (`settings.SECTIONS`,
which `layers.MACHINE_SETTING_SECTIONS` is). Only your primary plugin (§8) may set them, and even
it not the two read only from your top config (`primary-verify`, `primary-trust`).

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
(§6). A source or `ref:` that starts with `-` would reach git as an option, so such an entry is
dropped.

**Sync never throws away your work.** A sync that would overwrite edits you haven't committed in a
plugin's directory leaves the plugin as it is and reports it `kept`, with how to commit or discard
them. A branch that can't fast-forward because it has commits of its own *and* new ones on the
remote is reported `diverged` (not updated); one with commits not pushed yet is reported `ahead`.

**Content pin.** An optional `sha256:` on an entry locks the plugin to an exact content hash. If
the synced tree doesn't match (a moved tag, a compromised mirror, tampering), the plugin is
**quarantined**: neither its data nor its code loads, and `plugin list` shows `CHECKSUM MISMATCH`.
`plugin add --pin` / `plugin update --pin` fill the hash in from what was just synced.

**Private repos.** Fetches never prompt for credentials — an unreachable or private repo fails
fast. To reach a private repo, use an ssh source, a credential-bearing URL, or a configured git
credential helper. For CI, `CONFIGSYS_GIT_TOKEN` authenticates the https fetches of
`github:`/`gitlab:` sources: it reaches git as an HTTP `Authorization` header through the
environment, so it never appears in a URL, the command log or the clone's `.git/config`. For
`github:`/`gitlab:` sources, configsys sets the clone's *push* URL to ssh (once, on the first
clone — a push URL you set by hand is kept), so you can push a plugin you author without a token.

### The commands

| Command | What it does |
| --- | --- |
| `configsys plugin add <source> [--ref R] [--pin] [--local] [--replace]` | Sync the source first; only if that works, declare it. With a primary plugin set, the entry goes into the primary's manifest (so it travels); `--local` keeps it in this machine's config instead (§9). `--replace` swaps out an already-declared plugin of the same name from another source: the old copy is kept as `<name>.replaced-<date>` if it holds work found nowhere else, and a primary stays primary. A locked plugin's name is refused. |
| `configsys plugin sync` | Fetch every declared plugin (and the plugins they list) to its ref, and report how your component set changed. New or changed code stays inert until trusted. A locked plugin is left as it is (`locked`); a primary under `primary-verify: signed` that would take in unsigned commits is left as it is (`unsigned`, §8). |
| `configsys plugin list [--fetch]` | Each plugin: source, ref, `[primary]`, or `[via <plugin>]` naming the plugin that declared it, and status — not synced, ok, incompatible ABI, checksum mismatch, local (unpushed), whether its code or recipes are trusted, and whether it is locked — plus what it provides. Also lists name conflicts between plugins and built-in drivers a plugin replaces. |
| `configsys plugin diff <name> [--to REF]` | The review diff (§6a): what taking the plugin would change, before you sync, update or trust it. `--to` compares against that ref instead of the newest version tag. |
| `configsys plugin lock <name>` / `unlock <name>` | Hold a plugin where it is on this machine (§6a): no sync, update, bless or trust until you unlock it. |
| `configsys plugin update [name] [--ref R \| --latest] [--pin]` | Re-sync one plugin, moving its `ref:` with `--ref` or `--latest`. It syncs the new ref first and changes the declaration only if that works. `--latest` pins the newest stable version tag on the remote (`v1.2.3` style; pre-release tags ignored), else `main`/`master` — except on a primary that follows a branch, which stays on it (§8). Omit the name (or pass `--all`) to update every plugin; locked ones are skipped, under `--latest` so are locally authored ones, and it exits 1 if any fail. |
| `configsys plugin remove <name> [--force]` | Undeclare the plugin — from your top config or your primary's manifest — and delete its synced copy. Refused, naming what would be lost, while the copy holds work found nowhere else (uncommitted edits, unpushed commits, stashes, no remote, or authored in place), unless `--force`. A plugin only another plugin declares is refused: that plugin's manifest isn't yours to edit (remove or lock it, or declare the plugin yourself). |
| `configsys plugin trust [name \| --all [--yes]]` / `untrust <name>` | Approve / revoke a plugin's current content (§6). No name, or `--all`, lists every currently untrusted or changed plugin with what it ships and what would run, then trusts them once you say yes (locked and unsynced ones are skipped); off a terminal it is refused unless `--all --yes`. |
| `configsys plugin bless <source>` / `unbless` | Make a plugin (a source, or a declared plugin's name) your primary (§8), or clear that. It syncs the plugin first; nothing changes if that fails. `bless none` also clears. |
| `configsys plugin log [-n N]` | Your primary's last N commits (default 10), newest first, with the files each changed: `↑` not pushed yet (as of the last fetch), `*` made by configsys. |
| `configsys plugin undo [--yes]` | Take back the newest change configsys committed to your primary (§8): dropped if it was never pushed and is the last commit, else reverted by a new `Undo: …` commit (undo again to redo). Refused while you have uncommitted edits to its files. Shows the change and asks first on a terminal; off a terminal it needs `--yes`. |
| `configsys plugin push [--include-edits] [--yes]` | Publish your primary plugin (§8): commit, combine with what your other machines pushed (asking about any file both changed), list what will leave this machine and ask, then push to its branch. Edits you made by hand are included only if you say yes (or pass `--include-edits`); `--yes` pushes without the final question. |
| `configsys plugin init [name] [--dry-run] [--force]` | Create your primary plugin from local bits, or merge them into the existing one (§8). |
| `configsys plugin set-source <name> <source>` | Repoint a plugin's declared source (such as one `plugin init` made) to its pushed remote, e.g. `github:you/name`, and point the synced clone's `origin` at it too, so the next `sync` fetches from there. The clone is left alone when the new source syncs into a different directory (configsys tells you), isn't git-transported, or is the clone itself. To move a plugin to a source with a different name, use `plugin add <source> --replace`. |

The TUI **Plugins** screen (key `3`) shows the same tree, and below it the review diff (§6a) for
the selected plugin, fetched in the background as the cursor settles. Its `provides` column lists
everything a plugin brings as short codes (spelled out on the screen's `?` page): `cm` components,
`pr` profiles, `os` OS blocks, `dr` drivers, `fa` facets, `nm` package-name patches, `vf` version
floors, `ms` machine settings, `th` theme, `ky` key bindings, `sp` splashes, `tp` sync transports,
`vs` version sources, `df` dotfiles content, `gl` shell glue, `pl` further plugins. They're read
from what the plugin actually ships — its data files' sections, its manifest's `provides:` and
`plugins:`, its `dotfiles/` and `glue/` directories — so they're only known once it's synced (until
then the manifest's own `provides:` stands in). A plugin another plugin declares sits under it in
the tree (`├─`). Keys:

- `a` add — asks for the source (with a "replace an existing plugin of the same name" toggle) and an
  optional ref. A local path is added for this machine only (it can't sync anywhere else); a remote
  source, when you have a primary, asks "all your machines" (into the primary) or "this machine
  only".
- `x` remove (refused, like `plugin remove`, while the copy holds work found nowhere else), `s`/`S`
  sync one/all, `u`/`U` update one/all to the newest version tag (`--latest`), `v` set the ref.
- `t` trust/untrust one, `T` trust every untrusted or changed one (it lists them and asks first),
  `L` lock/unlock (a locked plugin's name carries `⊘`).
- `b`/`B` bless/unbless, `P` push your primary, `H` its recent changes (and undo the newest one
  configsys made), `n` create your primary from local content (`plugin init`: shows the plan, asks,
  runs), `O` give the current plugin a new source (`plugin set-source`), `M` move this machine's
  local picks into your primary (`picks to-primary`) — all §8.

## 5. When a plugin fails

A plugin that is unsynced, unreachable, malformed, ABI-incompatible, quarantined, or untrusted is
**skipped with a warning — never fatal**. Where its data still loads but its driver isn't
registered (untrusted code), components that need that driver show the `untrusted` status with a
"run `configsys plugin trust <name>`" note; nothing is bricked and nothing is silently installed
the wrong way. An offline sync just leaves the plugin as it was.

**Conflicts.** When two plugins define the same component, OS block, or driver name, the one
declared later sits higher in the stack and wins where they differ (a component's bindings still
merge by `(via, when)`, §3). `plugin list` and `check` name such collisions. When a component the
repo or your config defines turns malformed or ambiguous only because plugins added to it, the
plugins' parts are left out of that component, with a warning naming them. A plugin driver with the same
name as a built-in one *replaces* it everywhere — legitimate as a deliberate override, but
reported, because the plugin's copy then runs instead of core's fixes. Collisions that only show
up when code runs (two plugins registering the same version source, transport or splash) are
reported by `check`.

## 6. Trust

The dividing line is **does configsys run, build, download or privilege something from it** — and
most install methods do. An untrusted plugin may still *define* things; what it may not do is make
configsys execute them.

- **What an untrusted plugin may contribute** — components, profiles, OS blocks, drivers' data,
  themes, and **install bindings that name a package from a registry your system already trusts**:
  a `via: native` package from your distro's repos, a Flathub app, a Snap Store snap, a Homebrew
  core formula (drivers marked `trusted_registry`) — as long as the binding sets none of that
  driver's `command_fields` (an apt `ppa:`/`source-*`/`pubkey-*`/`debconf:`/`foreign-arch:`, a
  dnf `repo-*`/`pubkey-url:`/`enable-repo:`, a flatpak `hub-url:`, a snap `classic:`) and no
  `version: { url: }`.
- **Everything else waits for trust** — vendor repos and keys, upstream `.deb`/`.rpm` files
  (`native-pkg-file`), tarballs, AppImages, fonts, every language installer (cargo, pip, npm, …),
  `aur`, `script`, `source`, the gcc/clang alternatives, services, group membership, shipped
  dotfiles content, **any shipped glue** (sourced at every shell start), any driver a plugin's own
  code adds (ExamplOS's `via: toybox`), `facets:` `detect:` probes, and `keys:` (a rebind could
  turn a harmless key into "trust every plugin"). Such a binding is not a
  candidate: `where` names it "from an untrusted plugin layer — review it, then `configsys plugin
  trust`", and a pick that has no other method shows that as its error. The gate sits at resolution
  (`trustgate.py`), so every surface agrees, and the op loop checks it again before any step runs.
  `plugin trust` accepts a data-only plugin that ships any of these (`plugins.ships_executable_data`),
  so the nudge can always be acted on.
- **Code plugins** (a `code:` module) — not imported, and their drivers not registered, until
  trusted. A `code:` or `data:` entry that resolves outside the plugin's checkout is never loaded
  (it isn't covered by the content hash); `check` names it.

Downloads can also be pinned to their bytes: a `sha256:` on a tarball, AppImage, font or
native-pkg-file binding (a digest, or a map by cpu / package format) is checked right after the
download, before anything is unpacked or installed. It pairs with a pinned `version:`. Two more
limits hold for every layer: a version lookup fetches over https only, and a file a binding writes
as root (an apt `pubkey-path:` / `source-path:`, the `.repo` a dnf `repo-id:` names) must sit
directly in the system's keyring or source directory — a binding that names anything else is
refused when the routes load.

Trust is an explicit command, never an inline prompt, so the CLI stays scriptable:

```console
$ configsys plugin list
  examplos               github:you/configsys-examplos @v0.1.0
                         ok  [ships code + recipes — untrusted; run: configsys plugin trust examplos]
                         provides: components, os, drivers, component-names
$ configsys plugin trust examplos
configsys: trusted examplos @ a2f1664d9e5f — its code + recipes will run
```

(`code + recipes`: besides its `code:` module, ExamplOS's own `via: toybox` binding is data that
runs only once trusted.) In the TUI, `T` lists every plugin it would trust and asks first.

An approval records the plugin's **content hash** — a sha256 over every file in the plugin
directory except `.git/`, `__pycache__/` and `*.pyc`, each length-prefixed (so two different trees
can't hash alike); a symlink counts as its link text, never what it points at. (The hash format
changed on 2026-11-08; an approval or `sha256:` pin recorded in the old format still matches the
same content, and any change is re-approved in the new one.) Any change to the files, from a new release
or from tampering with the synced copy, changes the hash: `plugin list` then shows *changed since
trust* and the code stays off until you trust it again. Because the hash covers content rather
than a git commit, it works for plugins fetched by any transport. Approvals live in
`~/.config/configsys/plugin-trust.hu`, keyed by the plugin's directory name.

Your primary plugin is yours, so by default whatever syncs into it is trusted (`primary-trust:
identity`): its command-carrying data — glue, dotfiles, recipes, facet probes, keys — counts
without a `plugin trust`. The `primary-trust` setting changes that: `content` treats it like any
plugin (a sync that changes it needs `plugin trust` again), and `signed` trusts it while its newest
commit carries a good signature (pair it with `primary-verify: signed`), else by content. The
setting is read only from your top config, so a commit pushed to the primary can't grant itself
trust.

### 6a. Review before you take it, and lock what alarms you

**The review diff** (`configsys plugin diff`, and the Plugins screen's lower pane) shows what a
plugin would change before you let it:

- **Synced:** your on-disk copy against the remote-ref (the Plugins screen's column: the newest
  stable version tag on the remote, else `main`/`master`) — exactly what `update` would pull in.
- **Not synced:** its declared `ref:` against the remote-ref; or, when there's no `ref:` or the ref
  is already the newest, everything at that ref — what a sync would download.

For an unsynced plugin the objects are fetched into an inert bare repository under
`~/.config/configsys/plugin-review/` (created without hook templates, diffed with external diff
drivers and textconv off). Nothing there is checked out, loaded as a layer, or run, so you can read
a plugin before it ever reaches the plugins directory. Only git sources can be reviewed this way.

**A lock** (`configsys plugin lock <name>`, or `L` on the Plugins screen) holds a plugin where it
is on this machine — typically because its review diff shows something you don't want:

- `sync` leaves it alone (reported `locked`), so a `ref:` moved elsewhere — say, by updating the
  primary plugin that declares it — is never fetched into the plugins directory;
- `update`, `update --all` (skipped), `bless`, `add` and `trust` / `trust --all` (skipped)
  refuse it;
- a locked primary is still pushed when its remote has nothing new, but `plugin push` never
  combines the commits your lock is holding back (it names them: `plugin diff` shows them,
  `plugin unlock` takes them in).

A lock doesn't unload anything: a synced copy keeps loading as it is, with the trust it already
had. To stop using it, remove it. Locks are machine-local, like trust — they live in
`~/.config/configsys/plugin-locks.hu` keyed by the plugin's directory name — and `plugin unlock`
lifts one.

## 7. Writing code: the ABI

Everything a code plugin may use is re-exported from one module:

```python
from configsys.plugins import (Driver, Result, ResolvedComponent, register_driver,
                               register_version_source, register_transport,
                               Splash, SplashFrame, register_splash,
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
  `system`), `honors_scope` (whether user/system is selectable per component), `targets_version`
  (whether `set_version` can install a requested version; `False` makes configsys refuse
  set-version), `holds_version`, `native_backed`, and `trusted_registry` + `command_fields` (§6) —
  each described under [Optional hooks](#optional-hooks).
- **Ops to implement:** `get_version(rc)`, `get_latest(rc)`, `is_locked(rc)` (reads; no root),
  and `install(rc)`, `uninstall(rc)`, `upgrade(rc)`, `set_version(rc, version)`, `lock(rc)`,
  `unlock(rc)` (mutations; return a `Result`). Implement what your manager supports.
- **Optional overrides:** `location(rc)`, `scope(rc)`, `get_installed(rc)`, `reconcile_scope(rc, detected, target)`. More optional hooks — batched enumeration, System Updates, version
  signals — are listed under [Optional hooks](#optional-hooks) below.
- **Helpers you may call:**
  - *resolve and fetch an artifact* — `resolve_version(rc, *, refresh=False)`, `version_spec(rc)`
    (the version-discovery spec as this driver looks it up), `download_url(rc, version)`,
    `download_target(rc, version=None)` (returns `(version, url)`: the URL plus the version of the
    release it actually fetches — record that one), `download_failure(rc, version)` (why there is
    no URL, for the failure you return), `upstream_version(rc)`, `arch()`, `arch_token(rc)` (what
    `$ARCH` expands to for this unit, through its `cpu-names:`), `expected_sha256(rc, *keys)` and
    `verify_download(rc, file_q, *keys)` (the binding's `sha256:`, and a shell fragment to splice
    right after the download that fails the command on a mismatch — `''` when none is declared);
  - *install location and privilege* — `scoped_dir(raw, rc)`, `sudo(rc)`, `scope(rc)`,
    `location_override(rc)` (the user's `locations:` path for this component, or `None` — a
    path-based driver should prefer it over its computed target), `display_path(p)`, `home()`
    (configsys's home, `--home` aware — never a bare `$HOME`), `toolchain_bindirs()` (the managed
    rust/go bin dirs, for a build command's `PATH`);
  - *install markers* — `MARKER_PREFIX`, `marker_path(dir, rc, kind='version')` (the
    `.configsys-<comp>.<kind>` file a path driver keeps in its install dir) and `read_marker(path)`
    (its version; `'installed'` when it is empty, `None` when absent);
  - *command trust* — `command_trusted(rc)` (whether this binding's layer may run declared shell)
    and `untrusted_command_result(rc)` (the failure to return when it may not);
  - *files and names* — `will_write(path)` (call it BEFORE writing into a content root such as your
    primary's dotfiles or glue tree, so the write journal commits it — §8) and
    `installed_name(rc, driver=None)` (the binding's `installed-name:` for one manager, scalar or
    driver-keyed map — read the field through it, never by hand).
- **Construction:** `__init__(self, runner, paths=None)`. `runner.run(cmd, *, sudo=False,
  capture=True)` returns a `Result` (`.ok`, `.returncode`, `.stdout`) and honors `--pretend`.
  `paths` offers `.home`, `.env`, `.expand(path)`, and friends.
- **What a driver reads — `ResolvedComponent`:** `.key` (`driver\comp`), `.driver`, `.comp`,
  `.via` (the winning binding's `via:`), `.name` (`fields['name']` or the component name),
  `.fields` (the binding's fields), `.requested_as`, `.deps`, `.source` (the file that defined the
  component) and `.native` (this machine's native manager).
- **Routing it:** the driver's `drivers:` block (`requires:`, optional `standing:` / `when:`) is
  data in the plugin's layer files, not code, and its `requires:` doubles as the driver's validity
  gate (§3). A plugin driver is in no built-in preference list (`DEFAULT_DRIVER_PREFERENCE`), so
  when one of its bindings competes with another method at equal specificity it ranks after every
  listed driver, and against another unlisted driver it ties — a resolve error. Rank it with a
  `driver-preference:` that names it (on an OS block the plugin itself defines — elsewhere a
  plugin's list is ignored, §3 — or in your own setting) or a per-binding `standing:`, or make it
  an OS block's `native:` so `via: native` bindings reach it (as ExamplOS does). Until the plugin is
  trusted its driver isn't registered: the plugin's own bindings of it aren't candidates (§6), and
  a component another layer routes to it shows `untrusted` (§5).

Underscore members of `Driver` are internal and may change without an ABI bump.

#### Optional hooks

Beyond the ops above, the base `Driver` defines hooks the core calls when it needs more than one
unit at a time, or a signal the version string can't give. Each has a working default on the base
class, so a driver that overrides none of them still works — every unit is just probed one at a time,
and the driver stays out of the bulk features (System Updates, the orphan scan's package
enumeration). Override the ones your manager can answer.

Every hook and attribute in this section is part of the frozen surface: the `Driver` docstring's
frozen list names each one, and `test/test_abi_surface.py` pins the names and the defaults below.
Within one `ABI_VERSION` they keep their names, signatures and default behavior.

**Class attributes**

| attribute | default | what the core does with it |
|---|---|---|
| `privileged` | `False` | `True` = mutations need root. `actions.run_plan` asks `privileged` or `sudo(rc)` to decide whether to authenticate sudo once up front for the whole batch. (A plugin driver is assumed to need root regardless, so for plugin code this only documents intent.) It does **not** add sudo to your commands: pass `sudo=` to `runner.run` yourself, usually `sudo=self.sudo(rc)`. |
| `default_scope` | `'user'` | Your scope when the unit sets none: returned by `scope(rc)`, assumed by the default `get_installed`, and read by `sudo(rc)`. |
| `honors_scope` | `False` | `True` = user/system is selectable per unit. The core then stamps the machine's `scope:` setting onto your units that lack a `scope` field (`apply_scope_default`), flags it in the issues list (the TUI `!` page, the end of `configsys inspect`) when the installed scope differs from the declared one, and lets `configsys fix-scope` call `reconcile_scope`. Override `get_installed` too, so the scope you report is where the unit really is. |
| `holds_version` | `True` | `False` for a rolling manager that can neither hold a package nor install an older version (pacman, apk). The unit then never reads as locked, a `lock` op records no ledger hold, and the UI doesn't offer lock or set-version. Make `lock()` decline as well. |
| `targets_version` | `True` | `False` when `set_version` can't reach a requested version — the artifact is fixed by the route (a version-templated tarball/AppImage/font URL, the current AUR PKGBUILD, a package-fixed toolchain like `gcc-13`) or there is no version at all (glue, service, group). `configsys set-version` and the op loop (`actions.targets_version`) then refuse with a clear message before anything runs, instead of reinstalling the routed version and reporting success. |
| `native_backed` | `False` | `True` when your installs register in the OS package database (a `.deb`/`.rpm` installed with dpkg/rpm, a makepkg build installed with pacman). The orphan scan then looks for your units' packages under the native manager's index too (so they don't show as foreign orphans), and stranded-install detection treats the same package name under the native manager as the same install. |
| `trusted_registry` | `False` | `True` only when a unit is a package BY NAME from a registry the system already trusts (the distro's repos, Flathub, the Snap Store, Homebrew core). An untrusted plugin layer's binding of the driver is then a candidate (§6). Leave it `False` for anything that runs, builds or downloads code. |
| `command_fields` | empty | With `trusted_registry`: the binding fields that change system configuration as root or run a command (apt's `ppa`, `source-*`, `pubkey-*`, `debconf`, `foreign-arch`; flatpak's `hub-url`). An untrusted layer's binding that sets one waits for trust. |

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
  per-unit `get_version`. Never return `{}` on failure: that claims nothing is installed. The
  exception is a manager that isn't installed at all (the shell's command-not-found, exit 127):
  then nothing *is* installed through it, so `{}` is the true answer — and it spares every unit a
  doomed per-unit probe (the brew driver also marks its batch `missing` so `get_latest`/`is_locked`
  skip their spawns). Default:
  `None`.
- **`index_key(rc) -> str`** — the key a unit occupies in `installed_index()` (and in
  `upgradable_index()`). Default: `rc.name`. Override when your install identity isn't the resolved
  name (flatpak uses the app id).
- **`batch_index(rcs) -> context | None`** — the inspection prepass. Once per inspection, for each
  driver, the core passes the list of that driver's `ResolvedComponent`s it is about to probe; the
  drivers' prepasses run in parallel. Whatever you return is set on your driver instance as
  `self.batch` before `get_installed`/`get_latest`/`is_locked` run for each unit, so they can answer
  from memory. `None` or an exception = no batch, and each unit is probed on its own. Default:
  `{'installed': self.installed_index()}` (or `None` when that is `None`), plus `'candidate'` from
  one `latest_index(...)` query over every unit's `index_key` and `'held'` from `held_keys()`, each
  only when it answers. The reads use it through `self.batched_version(rc)`,
  `self.batched_latest(rc)` and `self.batched_held(rc)`, each returning `(value, hit)` — `hit`
  False means "not batched, probe this unit yourself". Override to fetch more in the same pass
  (apt adds its own held and candidate sets; flatpak its remotes) — and if your context isn't the
  default shape, override `batch_installed_index` to match.
- **`latest_index(names) -> {key: candidate_version} | None`** — the candidate version of every
  given key in ONE query (dnf repoquery, pacman -Si, brew info --json, …), which the default
  `batch_index` carries as `'candidate'`. A key the query didn't answer is simply absent (that unit
  falls back to `get_latest`). Default: `None` (probe per unit).
- **`batch_installed_index(batch) -> {key: version} | None`** — pulls the plain installed map back out
  of your batch context. After the prepass the core collects these per driver and seeds the TUI
  install overlay with them, so the overlay doesn't enumerate again. Default: `batch['installed']`.

(`self.batch` and `batched_version` were `_batch` / `_batched_version` before they were frozen.)

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
  `snap --hold`). Those rows are marked held, and the default `batch_index` carries the set for
  `batched_held`. Default: `None`.
- **`classify_index(keys) -> {key: tier}`** — sorts each upgradable key into one of
  `driver.UPDATE_TIERS` (`kernel`, `core`, `standard`, `apps`) so the list is grouped. `keys` is the
  upgradable set. Default: by name — kernel packages (`linux-image-*`, `linux-headers-*`, `kernel*`, …) →
  `kernel`, libc/glibc/musl → `core`, everything else → `apps`. A key you leave out is shown as `apps`.
- **`upgrade_all() -> Result | None`** — the apply step: the manager's own bulk upgrade (`apt
  upgrade`, `flatpak update`, `snap refresh`), not tied to any unit. Called by `configsys upgrade
  --system` after its confirmation, and by the TUI after it refreshes the native index. The manager
  itself keeps held packages back. `None` (default) = no bulk command; the CLI prints that it was
  skipped.
- **`upgradable_advisory() -> str | None`** — not on the base class; the core looks for it with
  `getattr` right after `upgradable_index()`. Return a line when the list you just gave may be
  incomplete (pacman without `checkupdates` lists from its last full sync); it is shown under
  `configsys updates` and on the TUI `!` page, even when the list is empty. `None` = nothing to add.

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
  fetched by a non-git transport can still ship trusted code. The built-in schemes (`github`,
  `gitlab`, `git`, `http`, `https`, `file`, `ssh`) are refused with a `ValueError`, so one plugin
  can't change how every other plugin syncs.
- **Splash screens** — a startup wait-screen animation. Subclass `Splash`, set `name`, implement
  `render(frame)`, and export `SPLASHES = [...]` (alongside or instead of `DRIVERS`). configsys
  owns the frame loop, skip key and deadline: it constructs your class once as `Splash(scr, pal,
  size, seed)` (a curses window, a palette — `pal.depth` is the color depth it paints at — the
  screen's `(h, w)`, and a seed for `self.rng`) and hands each frame a `SplashFrame(progress,
  counts, label, dt, elapsed, done)`. Draw onto `self.scr` without refreshing, and return True once
  the animation is at rest. Class attributes `fps` and `min_duration` tune the loop; `raw = True`
  makes `render` return an ANSI string the host writes as is (for truecolor gradients). This surface
  is pinned by `test/test_abi_surface.py` like the `Driver` one. List the names in the manifest's
  `provides.splashes`. Pick one with the `splash:` setting: a provider name, `random`, `off`, or
  unset for the built-in `braille-bar` (under `--effects none` or no color, always the plain
  built-in bar). A plugin's own name also works when it provides exactly one splash (`splash:
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

**It follows a branch.** A primary is meant to follow a branch — normally `main` — rather than be
version-tagged: it changes too often for tagging to be worth it, and your other machines pick up
whatever you push to the branch on their next `plugin sync`. `bless` and `init` record the branch
as its `ref:`; a primary with no `ref:` follows its remote's default branch, checked out on the
branch (never detached), and `plugin update --latest` / `U` re-sync it without moving it to a tag.
You *can* pin a primary to a tag deliberately; it then stays at that tag (`update --latest` moves
it to the newest one), and sync still never discards your edits.

**configsys commits its own edits.** Whatever configsys writes into your primary — a pick, a uniform
setting, a captured dotfile, your own glue, a plugin added to its manifest — is committed right away
on its branch, locally, with a message saying what was done: the command as you typed it (`picks add
btop`), or the TUI action (`profiles: toggle tracking: highlighted — tracking btop`). Nothing is
pushed by this — see "Publishing it" below. Only what configsys itself wrote is committed — each of its
writers records the files it is about to write, and the commit takes exactly those — so edits you make
by hand are never swept in: a file you had already changed is left uncommitted for you (configsys says
so), and a file you change while a command is running is left for you too, and named. (A code plugin
whose driver writes into the primary calls `self.will_write(path)` before writing, or its changes are
left as yours.) A command you interrupt (Ctrl-C) still has what it wrote committed, marked
`(interrupted)`, and that commit is never pushed automatically. A primary pinned to a tag or commit isn't committed to, and with no git
identity (no `user.name` / `user.email`, nor `GIT_AUTHOR_*` in your environment) nothing is
committed — configsys says how to set one, and never makes one up. A commit's body names the
configsys machine it was made on (your `machine:` setting), not the computer's hostname.
These commits skip your git hooks (a global pre-commit hook doesn't run on every TUI edit) but follow
your signing setting, so they're signed whenever your own commits are. Nothing is committed under
`--pretend`.

**Seeing where it stands.** The Plugins screen marks your primary's remote-ref column with `↑N` (changes not
pushed yet), `↓N` (changes your other machines pushed — `s` syncs them in) and `●` (edits not committed
yet); both arrows at once mean the two sides need combining before a push. The screen fetches the
primary in the background to count `↓`. The Components header shows `<primary>: ↑N to push, ↓N to
sync` whenever there's something either way (under `primary-push: auto` or `auto-on-quit`, only the `↓` part), and
`plugin list` says the same in words (`↓` there is as of the last fetch or sync; `plugin list --fetch`
fetches first).

**Only signed changes, if you like.** Whoever can push to your primary's repository can put data,
shell glue or code on every machine that syncs it. If you sign your commits (`git config --global
commit.gpgsign true`; configsys's own commits follow that setting), set `configsys config set
primary-verify signed` on each machine: from then on the primary takes in commits from its remote
only when every one has a good signature from a key git trusts there — a GPG key in your keyring, or
an SSH key listed in `gpg.ssh.allowedSignersFile`. `plugin sync` leaves the primary as it was and
says which commits aren't signed; `plugin bless` on a new machine doesn't clone a primary whose
newest commit isn't signed; `plugin push` doesn't combine with unsigned commits. The setting is read
only from your top config, so a commit pushed to the primary can't switch it off.

**Seeing and undoing configsys's changes.** `configsys plugin log` (or `H` on the Plugins screen)
lists the primary's recent commits, marking the ones configsys made (`*`) and the ones not pushed yet
(`↑`). `configsys plugin undo` (or "Undo" at the top of `H`'s list) takes back the newest change
configsys made: if it was never pushed and nothing came after it, it is dropped (`git reset --keep` —
your uncommitted edits stay, and `git reflog` still has it); otherwise a new commit, `Undo: <what it
did>`, reverses it — itself a configsys change, so a second undo redoes it. Your own commits are never
undone, and an undo is refused while you have uncommitted edits to the files it would change. Before
it takes back a change that added files, it saves them under `<state>/undo/<commit>/`; and when the
change was made on another of your machines, the confirmation says so.

**Publishing it.** `configsys plugin push` (or `P` on the Plugins screen) shares your primary with
your other machines, in three steps:

1. Edits you made by hand and haven't committed are listed, and you're asked whether to include
   them (`--include-edits` says yes up front). Left out, they stay here, uncommitted.
2. It fetches the remote — through the push URL, so a private repo you can push to is one you can
   fetch from — and puts this machine's commits on top of what your other machines pushed. If an
   edit you left out touches a file your other machine also changed, combining would bury it in
   conflict markers, so you're asked first: include it in this push, or stop (nothing pushed,
   nothing here changed).
3. It lists the changes and the files about to leave this machine and asks before sending them
   (`--yes` skips the question; a script with no terminal, and `primary-push: auto` / `auto-on-quit`,
   push without asking). Then it pushes to the branch and says how many changes went out. Your other
   machines get them on their next `plugin sync`. Under `primary-verify: signed` it also warns when
   your own outgoing commits aren't signed.

Your primary's `.hu` files are merged by what they mean, not line by line, so most changes on two
machines combine with no question. Each machine adding picks to its own column, both adding to the
same column (additions and removals from both sides are kept), different settings, components or pins
changed on each side, and plugins added on each side all combine. A profile's terms keep their order
(`+editors ~vim` is not `~vim +editors`): edits from both sides combine where they don't overlap, and
both machines reordering the same terms differently is asked. `plugins:` order is layer precedence,
so one side's reordering is kept and both reordering differently is asked. When both sides moved the
same plugin to different version tags, the newer is kept and you're told. What's left is a real
disagreement, asked about one setting at a time: *This machine set `splash: plain`; your other machine
set `splash: ocean`* — keep this one, keep the other, show me the file in your editor, or stop. The
lines and comments around a setting are kept as they were, inside a combined list too; a comment
your other machine added next to a setting you both changed is not carried over.

When this machine and another changed the same lines of any other file (or a `.hu` file configsys
can't read as a map), the replay is backed out completely
(you are never left mid-rebase), and you're asked, per file: keep this machine's version, keep the
other machine's, or edit both in your editor (`$VISUAL`/`$EDITOR`, else nano or vi; the file holds
both versions between `<<<<<<<` and `>>>>>>>` lines). Keeping one side keeps it only where the two
overlap — the other side's changes elsewhere in the file survive. The two are then merged with your
answers and pushed. Stop (or leave markers in an edited file) and nothing is pushed: your work stays
committed here as it was, and configsys names the git commands to finish by hand.

Combining is one undoable step. Your uncommitted edits are set aside first and come back afterwards,
and any way out that isn't a combined result — a stop, a git failure, an error, Ctrl-C at a question —
puts everything back as it was: the commits, the files, your edits. A file git ignores here that the
other machine now tracks is moved aside first (back in place on a stop, kept as `.pre-configsys` once
combined). A primary that is already in the
middle of a merge or rebase (one you started by hand) is never pushed or committed into until it is
finished or aborted; configsys says which. Its git commands always act on the primary, even inside a
`vcsh enter` / `yadm enter` session whose `GIT_DIR` points elsewhere.

A refused push is explained with its fix: an SSH key the remote doesn't know, a host you've never
connected to, a remote that wants you signed in (`gh auth login` and `gh auth setup-git` when `gh` is
installed), a repository that doesn't exist yet, or being offline. A primary with no remote yet (one
`plugin init` made) is told to create an empty repository, then `plugin set-source`. A primary pinned
to a tag is explained — a tag pins your other machines in place — and you're asked whether to make
it follow its branch instead (it is checked out on the branch, and its `ref:` here changes; run `plugin
update <name> --ref main` on your other machines). configsys never tags for you. In the TUI, git never
prompts: an SSH key that needs its passphrase fails with a note (load it with `ssh-add`, or push from
the command line). The TUI's background fetch never prompts either, and both keep the ssh command
you configured (`core.sshCommand` or `GIT_SSH_COMMAND`), only adding `BatchMode`. Nothing is pushed
under `--pretend`: `--pretend plugin push` lists what a push would send, as of the last fetch, and
sends nothing.

**When it's pushed** is the `primary-push` setting (uniform, so it travels in the primary):

- `ask` (default) — quitting the TUI with changes not pushed asks *Push, then quit / Quit, push later
  / Keep working* (Esc keeps working, like the plain quit confirm). After a command that changed the
  primary, the CLI says it isn't pushed yet.
- `auto` — the CLI pushes after each command that changed the primary, and quitting the TUI pushes
  without asking. Nothing is asked: your own edits stay out, and a conflict leaves it unpushed with a
  one-line note (`plugin push` settles it). A failure is retried the next time.
- `auto-on-quit` — like `auto`, but only quitting the TUI pushes, `Q` included. After a command that
  changed the primary, the CLI says it isn't pushed yet.
- `manual` — only `plugin push` / `P`, the marks and the header chip.

Quitting with `Q` (quit without confirming) pushes only under `auto-on-quit`; under `ask` or `auto` it
leaves a note instead.

**Creating one.** `configsys plugin init [name]` (default name `configsys-<user>`) builds a
primary plugin in `~/.config/configsys/plugins/<name>/` from what you have locally:

- your captured dotfiles and your own glue snippets move into it;
- your config's `components:` and `profiles:` are copied into it (and removed from `configsys.hu`);
- every live dotfiles link is re-pointed at the plugin's copy;
- the other plugins you declared move into its manifest's `plugins:`;
- it is `git init`ed, committed, and blessed. Its source is its own directory, so `sync` leaves
  it alone until you create an empty repository for it, run
  `configsys plugin set-source <name> github:you/<name>`, and `configsys plugin push`.

If you already have a primary, `plugin init` merges your local dotfiles and glue into it instead
(`--force` overwrites ones already there; `--dry-run` shows the plan); your config's `components:`
and `profiles:` are only named, not merged. Your picks move separately, with `configsys picks
to-primary` (Plugins `M`). On the Plugins screen, `n` runs `plugin init`: it shows the plan and
asks first.

**Where edits go.** Each machine setting is either uniform (belongs in the primary, same on every
machine) or machine-local (belongs in this machine's config). configsys writes each edit to the
right place, and `configsys config move` (TUI Config screen `m`) carries a setting across. A new
`plugin add` lands in the primary's manifest too, unless you pass `--local`. Changes to a primary
reach your other machines once you push them (`plugin push`) and they sync.

A primary that has no data file yet (a `plugin init` with no components or profiles to move writes
only the manifest) gets an empty `<name>.hu` the first time configsys writes a setting, pin or pick
to it — provided it is synced, ABI-compatible, has no `sha256:` pin (a new file would change its
hash) and its manifest has no explicit `data:` list (a new file would be ignored). Never under
`--pretend`.

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
settings, needs trust for anything that runs commands, and cannot set machine settings. On the
Plugins screen, `a` with a local path does the same.

## 10. Not supported yet

- **Signature verification** of plugins other than your primary (your primary has
  `primary-verify: signed`, §8). For any other plugin, the `sha256:` content pin is the practical
  form for now.
- **Windows and macOS** OS plugins. A plugin adding another OS root plus its package-manager
  driver is the shape that would cover them, but there is no test path yet.
