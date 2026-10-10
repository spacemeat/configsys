# the configsys configuration and routing format

configsys reads Humon (`.hu`) files. This page is the reference for their structure: how your
per-machine config chooses what to install, how routes describe where each component comes from on
any OS, and how the two combine.

## Layers

Every `.hu` file is a **layer**. Layers overlay section by section, lowest precedence first, and the
highest-precedence definition of a thing wins:

```
repo (routes.hu + config.hu)  <  plugins  <  primary plugin  <  your config
```

Your machine's own config, the **top config** (`~/.config/configsys/configsys.hu`), always wins.
The **primary plugin** is the one plugin your top config marks `primary: true` (see "Plugins and
includes"): your personal configuration as a plugin, which travels with you and may set machine
settings. It sits above the ordinary plugins and below your top config. A file may `include:` other
files, which sit just below the file that includes them.

What each layer may contribute follows one rule: **every layer may define things; only your top
config and your primary plugin may set machine settings.**

- **Definitions** come from any layer, including an ordinary plugin, a file you include, and your
  top config: `components:`, `profiles:`, `os:` blocks, `drivers:`, `component-names:`,
  `version-floors:` and `facets:` probes. A facet probe runs a command, so one from a plugin is used
  only once you trust that plugin.
- **Machine settings** (`picks:`, `machine:`, `scope:`, `pins:`, `dispositions:`, `uninstall:`,
  `driver-preference:`, `disabled-drivers:`, `dirs:`, `locations:` and the rest of "Machine
  settings" below) are read from the repo, your primary plugin and your top config. An ordinary
  plugin or an included file that sets one is ignored, and `configsys check` warns about it.
- **`plugins:`** is read from your top config (and from plugin manifests); see "Plugins and
  includes".
- **`theme:`** and **`keys:`** are cosmetic: every layer may contribute them.

Your top config's `os:` and `drivers:` entries sit above every plugin's, so you can tweak a driver
or an OS block on this machine alone, for example
`drivers: { flatpak: { requires: flatpak  standing: never-auto } }`.

`components:` and `profiles:` merge by name (a component merges its bindings additively; see
"Overriding a component"). `os:` and `drivers:` merge by block name, field by field: a higher layer's
block changes only the fields it sets (a field it restates, such as a list, is replaced whole), so
`drivers: { snap: { standing: never-auto } }` keeps snap's shipped `requires:`. `theme:` and `keys:` merge per
key from every layer. `configsys check` warns about a key configsys doesn't recognize, a retired
key, and a section a layer isn't allowed to set.

## Your config file

Your top config is `$XDG_CONFIG_HOME/configsys/configsys.hu` (by default
`~/.config/configsys/configsys.hu`); `CONFIGSYS_CONFIG` or `--config` names a different file. If it
doesn't exist, the first command that needs it generates it from a commented template. A legacy
`~/configsys.hu` is moved there automatically. Every section is optional:

```hu
{
    machine: laptop                  // which picks: column is THIS box (default: this-machine)

    picks: {                         // the install set: one component list per machine
        laptop:  [ btop, neovim, gcc-15, gdb ]
        desktop: [ btop, neovim, steam ]
    }

    scope: system                    // default install scope for scope-honoring drivers

    include: [ ~/src/myproject/configsys.hu ]   // pull in more component definitions

    plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    pins: { steam: flatpak }         // force a method (binding-pin) or a provider (provider-pin)

    driver-preference: [ native, flatpak, appImage ]   // tiebreak among valid methods

    components: { apod: {} }         // amend a route, add one, or remove one with {}

    disabled-drivers: [ glue ]       // turn an install method off here (manage your own shell config)

    adopt-installed: true            // prefer an already-installed method over the default (default on)

    reboot-advice: true              // post-op "reboot advised" via the distro's native check (default on)

    splash: ocean                    // startup wait-screen (a splash name / random / off; unset = built-in)

    effects: reduced                 // TUI motion: full / reduced / none (unset: reduced over SSH)

    dirs: { sdk: "~/toolchains"  system: /srv/opt }   // relocate install-layout dirs

    locations: { blender: ~/dev/blender-git  kicad: /opt/kicad }   // per-component: find/manage HERE

    detect-coexisting: false         // skip the "also present (unmanaged)" pass (default on)

    facets: { gpu: nvidia }          // declare a machine fact for when: (overrides detection)

    keys: { components: { method: p } }   // rebind TUI keys (see `configsys keys`)
}
```

## Machine settings

A machine setting has a **kind** (scalar, bool, list or map) and a **nature**, which decides where
an edit lands by default (see "Where a machine-setting edit lands"): a **uniform** setting belongs
in your primary plugin, a **machine** setting in your top config. Machine settings are read from the
repo, your primary plugin and your top config; an ordinary plugin or an included file can't set
them (it is ignored, and `check` warns). `configsys config show` lists every setting below with its
effective value and where it lives.

### Settings you change with config set

- **`machine`** (scalar, machine; default `this-machine`): this box's machine name, i.e. which
  `picks:` column is "this machine". `configsys machine use <name>` sets it.
- **`scope`** (`user` or `system`, machine; default `user`): the install scope for scope-honoring
  drivers when a binding doesn't set one. `user` installs under `~`, `system` under `/opt` (needs
  sudo).
- **`driver-preference`** (list, uniform; default `[ native, aur, flatpak, snap, native-pkg-file,
  appImage, brew, tarball, source, script ]`): the order that breaks ties between equally valid install
  methods (see "Choosing among methods"). A layer's list replaces the whole list. An OS block that
  declares its own `driver-preference:` takes precedence on that OS. Drivers your list doesn't name
  aren't dropped: they follow the ones it names, in the default order, so a list written before a
  new driver existed still ranks it. Only drivers named in no list tie, and a tie is an error.
- **`disabled-drivers`** (list of via names, machine; default none): turns install methods off on
  this machine. Their bindings stop matching, like a false `when:`, so a `suggests:` that needs one
  is skipped and a `requires:` that needs one is an error. Use `dotfiles` and `glue` to manage your
  own shell config, or for example `snap`.
- **`auto-tighten`** (bool, uniform; default off): when a component's default method can't meet a
  version floor, pick a method that can, instead of only advising. An already-installed provider is
  never replaced automatically.
- **`adopt-installed`** (bool, uniform; default on): prefer a method or provider that is already
  installed over the computed default (detection).
- **`refresh-before-execute`** (scalar, uniform; default `auto`): refresh the OS package index once
  before running staged operations: `auto` (when the batch includes a native install or upgrade),
  `always`, or `never`.
- **`install-overlay`** (bool, uniform; default on): open the TUI Profiles screen with the
  install-state overlay on (`O` toggles it).
- **`reboot-advice`** (bool, uniform; default on): after an operation, and as a TUI header chip,
  advise when a reboot or a service restart is needed, using the distro's own check.
- **`splash`** (scalar, uniform; default unset): the startup wait-screen. A splash name (or the
  name of the plugin that ships it), `random` for a different one each run, or `off`. Unset uses
  the built-in `braille-bar`.
- **`effects`** (scalar, machine; default unset): TUI motion. `full` (gradient and splash),
  `reduced` (no gradient, a calmer splash) or `none` (no gradient; only the plain built-in progress
  bar). Unset picks `reduced` over SSH, else `full`. `--effects` overrides it.
- **`orphans-ignore`** (list of name-or-glob patterns, machine; default none): orphans whose
  component name or installed package matches stay quiet in `configsys orphans`. `orphans --ignore`
  adds patterns.
- **`detect-coexisting`** (bool, uniform; default on): after inspecting, look for each component
  installed through its other methods and show those installs as "also present (unmanaged)".
  Package managers are listed once per run, so the cost is a handful of calls, not one per
  component. `configsys versions <name>` shows every method's state either way.
- **`installer-shell-writes`** (`block` or `allow`, uniform; default `block`): the shell-writes
  guard. With `block`, when an installer edits `~/.bashrc`, `~/.bash_profile`, `~/.profile`,
  `~/.zshrc` or `~/.zprofile` during an install or upgrade, configsys restores the file and keeps
  the removed lines as an inactive glue candidate (see "glue"). `allow` turns the guard off.
- **`installer-shell-writes-allow`** (list of components, uniform; default none): components whose
  rc-file edits are wanted and left alone.
- **`locations`** (map of component to path, machine; default empty): "find and manage this
  component's install here". An absolute path, regardless of scope, that the path-based drivers
  (`source`, `appImage`, `tarball`, `font`, and plugin build drivers) use instead of the directory
  they would compute. Unlike `dirs:`, it moves one component, not a whole category. On the command
  line it takes `component=path` tokens, which replace the whole map in the file they're written
  to: `configsys config set locations blender=/srv/blender-git kicad=/opt/kicad`.
- **`dirs`** (map; default `{ user: ~  system: /opt  app: apps  sdk: sdks  src: src }`): the
  install-layout directories, set one key at a time (`configsys config set dirs.sdk ~/toolchains`).
  `dirs.user` and `dirs.system` are machine; `dirs.app`, `dirs.sdk` and `dirs.src` are uniform.

The rest of the machine settings have their own commands: `picks:` (`configsys picks`), `pins:`
(`configsys pin`), `dispositions:` (`configsys disp`) and `uninstall:` (the TUI Profiles screen).

### How settings merge

- A scalar or bool: the highest layer that sets it wins.
- A list (`driver-preference`, `disabled-drivers`, `orphans-ignore`,
  `installer-shell-writes-allow`, `uninstall`): the highest layer's whole list wins; lists from
  different layers are not combined.
- A map merges per key: `pins`, `dispositions`, `locations` and `dirs`. Your top config can
  override one entry of your primary plugin's map without restating the rest.
- `picks:` merges per machine: a higher layer's list for a machine replaces that machine's list.

Notes:

- **`dirs:`** keys are `user` (the user-scope base, default `~`), `system` (the system-scope base,
  default `/opt`), and the category directories `app`, `sdk` and `src` (defaults `apps`, `sdks`,
  `src`), which routes reference as `$CONFIGSYS_APP_DIR`, `$CONFIGSYS_SDK_DIR` and
  `$CONFIGSYS_SRC_DIR`. A relative category directory sits under the scope base; an absolute or `~`
  one is used as is. Precedence is built-in default < `dirs:` < environment variable
  (`CONFIGSYS_USERSCOPE_DIR`, `CONFIGSYS_SYSTEMSCOPE_DIR`, `CONFIGSYS_APP_DIR`, `CONFIGSYS_SDK_DIR`,
  `CONFIGSYS_SRC_DIR`), so `dirs:` is the durable setting and the variable a per-run override. The
  paths configsys needs before it can read your config (its state directory, your top config, the
  repo) are set only by environment variables.
- **`splash:`** splashes other than the built-in come from code plugins (for example
  **configsys-splash-ocean**; see docs/plugins.md), which you must trust before they load; a name
  that isn't available falls back to the built-in with a note. `CONFIGSYS_NO_SPLASH` and
  `--verbose` turn the splash off; `--effects none` and `--nocolor` swap any plugin splash for the
  plain built-in bar.

## Where a machine-setting edit lands

`configsys config set …` and the TUI **Config** screen route each setting by its **nature**:

- **uniform** settings are the same on every machine, so an edit defaults to your **primary
  plugin** (portable: commit, push and re-tag the primary, then `plugin sync` elsewhere; it takes
  effect on this machine immediately). `picks:` is uniform too, because the install set is meant to
  travel (`configsys picks to-primary` moves this box's local picks there).
- **machine** settings are a fact about *this* box, so an edit defaults to your **top config**,
  local and unshared. `dispositions:` (your seen/interesting triage) is machine too, and the
  `uninstall:` queue and `pins:` (`configsys pin set`) are written to your top config.

When you have no primary plugin (or it isn't synced), everything lands in your top config. An edit
to a setting you've *already* set goes to the layer it lives in, so a lower layer can't silently
shadow it. The Config screen shows, for each setting, whether it is at its built-in default, set by
you, or overridden by an environment variable, and its store (your primary plugin or your top
config), which is where an edit lands; `config show` prints the same.

- `config set <key> <value> --local` writes to your top config, bypassing the uniform default.
- `config move <key>` (TUI: **`m`**) carries a setting the other way, between your top config and
  your primary plugin: it writes the value at the destination and clears the source. The direction
  follows from where the setting lives now; a setting at its built-in default has nothing to move.
- `configsys pin promote <name>` does the same for one pin.

An environment variable always wins over both (the per-run escape hatch), and is shown as the
source when set.

## Picks: what a machine installs

The install set is the **component × machine matrix**: `picks:` holds one component list per
machine, and `machine:` says which column *this* box is. A machine installs exactly the components
picked for it; nothing is inferred from profiles.

```hu
machine: laptop
picks: {
    laptop:  [ btop, neovim, gcc-15 ]
    desktop: [ btop, neovim, steam, blender ]
    build-box: [ ]                    // an empty column is still a machine
}
```

- `configsys picks list|add|rm [--machine M]` edits a column (default: this box's); `picks
  to-primary` moves this box's local picks into the primary plugin so they travel.
- `configsys machine list|show|add|rm|use` manages the columns; `machine use <name>` sets this
  box's `machine:` (no name clears it). `--machine NAME` on any command curates or plans another
  machine's set for that run; install and execute still act on the local machine only.
- The TUI **Profiles** screen is the same matrix, interactively (`t`/`T` track, `m`/`M` choose
  machines); the **Components** screen shows this machine's picks with their state.
- **`dispositions:`** (a map of component to `seen` or `interesting`; an unlisted component is
  NEW) is a side-store of triage marks, so you can work through the catalog once; it never installs
  anything. `configsys disp list|get|set`.
- **`uninstall:`** (a list) is the queue of removals you stage on the TUI Profiles screen (`x`),
  shown as its `!uninstall` lens; they run when you execute.
- `configsys orphans` lists installed software no pick accounts for; `--adopt NAME` picks it.

The retired `configs:` section is ignored, and `check` warns about it. A `profiles:` section you
write yourself, in your top config, your primary plugin or an include, defines browse categories
like any other layer's; it never installs anything.

## Pins

`pins:` reroutes a component without redefining it, at the top of the precedence order (your pin
beats `auto-tighten` and an adopted install; see "Choosing among methods"):

- a **binding-pin** (`component: via`) forces a component's install method, for example
  `pins: { steam: flatpak }`. The component must have a binding with that `via:` that is valid here,
  or resolving it is an error.
- a **provider-pin** (`capability: component`) forces which component satisfies a capability, for
  example `pins: { jdk: jdk-17 }`. It may name a `standing: never-auto` provider.

A pin whose value names a via (a driver, `native` or `parts`) is a binding-pin; any other value is a
provider-pin. `pins:` merges per key. `configsys pin list|set|unset|promote` manages them: `set`
and `unset` edit your top config, and `promote` moves a pin into your primary plugin. In the TUI,
`v` picks a component's method or provider.

If your pin keeps a component on a method that is too old for something that needs it (a version
floor), configsys doesn't override you: inspect and the TUI issues page (`!`) show a `pin-floor`
warning naming the floor, what your pinned method gives, and how to fix it (unpin, or pin a method
that meets it).

## Plugins and includes

### plugins:

A **plugin** is a git repository (or a local directory) that adds components, OS blocks, profiles,
drivers or splash screens. Your top config declares them; `configsys plugin sync` fetches each one
into `~/.config/configsys/plugins/<name>/` at its pinned ref:

```hu
plugins: [
    { source: "github:someone/configsys-mydistro"  ref: v1.2.0 }
    { source: "github:me/configsys-me"  primary: true }
    { source: /home/me/src/configsys-local }
]
```

- **`source:`** is `github:owner/repo`, `gitlab:owner/repo`, any git URL, an ssh source, a `file:`
  URL, or a local path (which must be a git repository; configsys clones it). A source containing a
  colon must be quoted.
- **`ref:`** is a tag, commit or branch. A tag or commit checks out exactly that; a branch follows
  the remote tip; no `ref:` follows the default branch.
- **`sha256:`** (optional) pins the plugin's exact content; a mismatch quarantines it.
- **`primary: true`** makes it your primary plugin (only one; `configsys plugin bless <source>`
  writes it for you).

Only your top config's `plugins:` list is read. A plugin's own manifest may list further plugins,
which are fetched with it but are never primary. An unsynced, incompatible or malformed plugin is
skipped, never fatal. A plugin that runs code or commands must be trusted first
(`configsys plugin trust`). `configsys plugin add <source>` declares and syncs one: with a primary
plugin it goes into the primary's manifest so it travels; with `--local` it goes into your top
config, so it applies to this machine only (handy for a source tree or an app install that ships its
own `.hu` files). See docs/plugins.md.

### include:

`include:` is a path or a list of paths to more `.hu` files. A relative path resolves against the
including file's directory, and `~` against the configsys home: your home directory, or the
directory `--home` / `CONFIGSYS_HOME` names, so a sandboxed run reads the sandbox's includes. An
included file sits just below the file that includes it. It may define anything a layer can
(components, profiles, OS blocks, drivers, component names, version floors, facet probes, theme
and keys), but not machine settings or `plugins:` (see "Layers"). A missing include or an include
cycle is an error.

## Profiles: read-only browse lenses

A profile is a named list of components, defined in the repo's `config.hu`, by a plugin, in a
file you include, or in your own config. Profiles exist to **browse** the catalog (`configsys profile list|show`, the TUI
Profiles screen); browsing a profile never changes your system, you pick from it. On the command
line, `profile:<name>` expands to a profile's members (`configsys install profile:dev`).

A profile's value is a list of **terms**, applied left to right:

- a bare `name` adds a component;
- `+name` splices in another profile's members (recursively);
- `~name` removes a component added so far, or every member of a profile named `name`;
- `+<the profile's own name>` means "the same profile from the next layer down", so a higher layer
  **amends** a profile in place instead of replacing it.

```hu
profiles: {
    base: [ btop, git, curl ]
    dev:  [ +base, neovim, gcc-15, ~curl ]   // base, plus tools, minus curl
}
```

and in a higher layer (a plugin that loads later, or your own config):

```hu
profiles: {
    dev:  [ +dev, valgrind ]                  // amend dev in place: everything above, plus valgrind
}
```

Order matters: a `~` after a `+` drops what the splice brought in; a later add re-adds it. A
redefinition without the self term replaces the lower profile wholesale.

**`!all`** is a built-in browse lens listing every defined component; it heads the TUI Profiles
screen, and you don't declare it. To see everything installed or tracked on the Components screen,
cycle its view mode (`M`).

## Components and bindings

`routes.hu`'s `components:` section defines each component as a capability plus a list of
context-selected **bindings** (its `install:` list). A binding names its **driver** with `via:`,
guards itself with an optional `when:` expression, and carries driver-specific fields:

```hu
components: {
    btop: {
        install: [
            { via: native  when: "rhel"  requires: epel }   // EL: needs EPEL enabled
            { via: native  repo-component: universe }        // everywhere else
        ]
    }
    chrome:     { install: [ { via: flatpak  hub: flathub  app: com.google.Chrome } ] }
    discord:    { install: [ { via: flatpak  hub: flathub  app: com.discordapp.Discord }
                             { via: native-pkg-file  when: debian  standing: never-auto  url: "…" } ] }
    vulkan-dev: { install: [ { via: parts  parts: [ build-essential, vulkan-sdk ] } ] }
}
```

A component may carry these keys (an unrecognized key is an error):

- **`install:`** the bindings.
- **`requires:`** capabilities it needs, installed first and dependency-ordered. A hard dependency:
  if nothing can provide one here, the component is an error.
- **`suggests:`** soft dependencies: pulled in when they can be installed here, skipped silently
  otherwise. A suggested component's own `requires:` stay hard once it is pulled in.
- **`provides:`** extra capabilities it satisfies (a component always provides its own name).
- **`standing:`** `never-auto` keeps the component from being pulled in automatically to satisfy a
  `requires:`; it is used only when you pick it, require it by name, provider-pin it, or a version
  constraint selects it. An **integer** ranks the component among the providers of a capability
  (higher wins): when several components could satisfy a `requires:`, the highest rank is pulled
  in, and a tie at the top is an error that asks for a provider-pin or a rank.
- **`parts:`** a list of components, as shorthand for a pure bundle: a component with `parts:` and
  no `install:` gets the single binding `{ via: parts  parts: [...] }`. With an `install:` as well,
  `parts:` is ignored and `check` warns; for a bundle that differs by OS, put `parts:` on
  `when:`-guarded `via: parts` bindings.
- **`description:`** (one line) and **`attrs:`** (kind tags such as CLI, TUI, GUI, FOSS; see
  docs/component-attrs.md) describe it for the catalog and its filters.

A capability may be versioned: a provider declares `provides: { jdk: 21 }` and a consumer
`requires: { jdk: ">=21" }`. A constraint uses `>=`, `>`, `<=`, `<` or `=`, and a comma joins
clauses (`">=3.10,<3.13"`). It selects a provider whose version meets it (and may select a
`never-auto` one); for a capability whose version lives on the install method instead, it is a
floor that configsys surfaces when it isn't met (see `auto-tighten`). `requires:`, `suggests:` and
`provides:` may also sit on a single binding, applying only when that binding is chosen.

### Binding fields

Every binding may use:

- **`via:`** (required) the driver; see "Drivers". **`via: native`** resolves to this OS's package
  manager (apt, dnf, pacman, zypper, apk, xbps or brew), so one binding covers every distro; on an
  OS with no package manager, native bindings aren't candidates. **`via: parts`** is a pure
  aggregator: its **`parts:`** list is installed and it has no install of its own.
- **`when:`** the validity condition (see "The when: expression"); absent means always valid.
- **`standing:`** the one preference knob. `never-auto` keeps the binding valid, listed and
  pinnable but never the automatic default (unless every valid method is `never-auto`); an
  **integer** is a preference rank, higher wins (see "Choosing among methods").
- **`name:`** the package or distribution name, defaulting to the component name. On a `via:
  native` binding it may be a map keyed by package manager, with an optional `default:`
  (`name: { apt: fd-find  default: fd }`).
- **`scope:`** `user` or `system`, for scope-honoring drivers (`appImage`, `flatpak`, `tarball`,
  `source`, `font`, `npm`, `gem`, `luarocks`); it beats the `scope:` setting. Other drivers have a
  fixed scope (OS package managers are system; `cargo`, `pipx`, `dotfiles`, `glue` are user) and
  ignore it.
- **`packages:`** (native, and the versioned `gcc`/`clang` drivers) a list of packages installed and
  removed together as one unit; install state is read from the first.
- **`installed-name:`** (native) the one package to read install state and version from, when it
  differs from what is installed (a metapackage a system often lacks). Like `name:` it may be a map
  keyed by package manager, with an optional `default:`
  (`installed-name: { apt: libreoffice-core  dnf: libreoffice-core }`); a manager the map doesn't
  name reads the ordinary package. A plain value applies to every package manager the binding
  reaches.
- **`cpu-names:`** a map from CPU to upstream's spelling (`{ x86_64: amd64  aarch64: arm64 }`).
  `$ARCH` expands through it, and its keys are the CPUs the download exists for: on any other CPU
  the binding isn't valid, without making it more specific.
- **`version:`**, **`url:`**, **`asset:`** and **`latest-check:`** for download-based drivers (see
  "Versions").

Driver-specific fields include:

- **apt** (`via: native` on Debian-family): `repo-component:` (an archive component such as
  `universe`), `ppa:`, `foreign-arch:` (for example `i386`), `pubkey-url:` + `pubkey-path:` (a
  signing key), `source-url:` or `source-line:` + `source-path:` (a vendor source list;
  `$CODENAME` in a source line becomes the release codename), and `debconf:` (preseeded answers).
  A vendor source that breaks the package index is rolled back.
- **dnf** (`via: native` on the Red Hat family): `enable-repo:` (turn on a repo that ships
  disabled, such as `crb`), `repo-id:` + `repo-name:` + `repo-url:` (a vendor `.repo` file, verified
  with `pubkey-url:`).
- **flatpak**: `hub:` (the remote, such as `flathub`), `app:` (the application ID), `hub-url:` (a
  remote configsys doesn't know).
- **snap**: `name:`, `classic: true`, `channel:`.
- **appImage**: `path:` (the target file), `url:` and/or `version:`, `name:` (the menu label),
  `desktop-id:` (the app's desktop ID, so its menu entry and dock icon share one `.desktop` file).
- **tarball**: `installDir:` (required; it is replaced on every install), `url:` and/or
  `version:`, `archive:` (`none` for a bare executable, `gz` for a single gzipped binary, `zip`),
  `binary:` (the file name for `none`/`gz`), `strip:` (leading path components to drop).
- **native-pkg-file**: `version:` plus `asset:` (CPU-keyed, or format-then-CPU-keyed such as
  `{ deb: { x86_64: … }  rpm: { x86_64: … } }`), or `url:`.
- **source**: `build:` (required; a command or list, run in the tree with `$PREFIX`, `$SRC`,
  `$VERSION`, `$ARCH`), `repo:` (a git URL) or `url:`/`version:` (a source archive), `ref:`,
  `tag-prefix:`, `strip:`, `installDir:`, `prefix:`, `uninstall-cmd:`.
- **script**: `install-cmd:` (required), `version-cmd:` + `version-re:`, `latest-cmd:`,
  `uninstall-cmd:`, `upgrade-cmd:`, `set-version-cmd:`, `location:`.
- **pipx** and **pip**: `name:`, `python:` (the interpreter), `version: { pypi: <dist> }`.
- **service**: `unit:`, `start: false`, `runit:` (the runit service name or names, where they
  differ). **group**: `name:` (the group).
- **dotfiles** and **glue**: see their sections.

See docs/routing-model.md for the complete binding model.

### Overriding a component

Components **merge additively** across layers. A binding's identity is its `(via, when)` pair, with
`when:` compared as written, so a higher layer (a plugin or your config) can:

- **add** an install method: a binding whose `(via, when)` is new joins the list;
- **override** one: a binding with the same `(via, when)` replaces the inherited one (restate all
  its fields);
- **retract** one: `{ via: X  when: "Y"  drop: true }` removes the inherited binding with that
  identity;
- **remove the whole component**: `{}` as its value discards everything below it.

The component's other keys override with inheritance: a layer that sets `requires:` replaces it, a
layer that omits it keeps the lower one. `attrs:` combine across layers. To merely choose among
existing methods, use a pin instead.

```hu
components: {
    btop: { install: [
        { via: tarball  drop: true }                                    // retract the shipped tarball method
        { via: flatpak  hub: flathub  app: io.github.aristocratos.btop } // add a method
    ] }
    apod: {}                                                            // remove apod entirely
}
```

Among the bindings that are **valid** here, one is chosen (see "Choosing among methods").
`configsys where <name>` shows a component's source layer, its bindings, which are valid here, and
which one resolves.

## The when: expression

`when:` is a boolean expression over the machine's context. It states **validity only** (whether a
method works here), never which method to prefer. Its atoms are:

- an **OS block name**, bare or versioned. Bare (`ubuntu`, `redhat`) matches that block and every
  block that inherits from it. Versioned (`ubuntu < 23.04`, `debian >= 12`, with `<`, `<=`, `>`,
  `>=`, `=` or `==`) additionally requires the machine to be on that block's version scale and the
  comparison to hold, so `debian < 12` never matches Ubuntu, which numbers its own releases.
- a **CPU** atom: `cpu: aarch64`, or `cpu: [ x86_64, aarch64 ]`.
- a **facet**: a detected fact declared in a `facets:` section. Categorical facets read like CPU
  (`gpu:nvidia`, `gpu:[nvidia, amd]`); version facets like a versioned OS (`cuda >= 12`). An
  undetected facet makes its atom false. See docs/facets.md.

Combine atoms with `and`, `or`, `not` and parentheses (`not` binds tightest, then `and`, then
`or`); `not` applies to any atom, for example `"ubuntu and not pop_os!"`.

OS blocks form a lineage through `using:` (`pop_os!` -> `ubuntu` -> `debian` -> `linux`), so a
binding written for `debian` applies to the whole family. The machine's block comes from
`/etc/os-release`'s `ID`; a few IDs map to a differently named block, because block names can't
contain `-` (`ID=pop` -> `pop_os!`, `ID=opensuse-leap` -> `opensuse_leap`). A `when:` naming an unknown OS block is a `check` warning, since it would never
match. Two bindings of the **same driver** whose conditions overlap must be comparable (one more
specific than the other), or configsys reports a load-time ambiguity; overlapping bindings of
*different* drivers are legal alternatives.

## Choosing among methods

A component can have several valid install methods in one context (for example `native` and
`flatpak` both work on Ubuntu). A binding is **valid** here when its `when:` holds, its CPU is
covered (`cpu-names:` or a CPU-keyed `asset:`), its driver isn't in `disabled-drivers:`, its
driver's own `when:` gate holds (see "OS blocks and drivers"), and it isn't `via: native` on an OS
with no package manager. Among the valid ones, configsys picks one default deterministically:

- bindings and drivers marked **`standing: never-auto`** are set aside (unless every valid method
  is);
- then the **most specific** valid binding wins (a narrower `when:` beats a broader one), across
  drivers;
- then a binding's **`standing:`** integer rank (a narrow, per-package author signal, so it
  outranks the blanket order below);
- then **`driver-preference`**, the global tiebreak list (a machine setting, overridable per OS
  block). The default order is `native, aur, flatpak, snap, native-pkg-file, appImage, brew,
  tarball, source, script`, so on Arch an AUR package beats a flatpak or a download, and on a glibc
  distro a Homebrew formula beats a plain download but never a distro package, flatpak, snap,
  release `.deb`/`.rpm` or AppImage.

If that still ties, it is an error that names the preference channel, never a request to narrow a
validity `when:`. Above the default sit three overrides, highest first:

- your **pin** (`configsys pin set <name> <via>`, or edit `pins:`) beats everything;
- with `auto-tighten` on, a method chosen to meet a version floor;
- with `adopt-installed` on (the default), a method or provider that is **already installed**. This
  one is soft: if the installed choice can't be used here (its method isn't valid, or it fails a
  version requirement), it is skipped for that run and the normal default applies, never an error.

`configsys where <name>` shows all candidates, why any binding isn't one, and which rule decided.

## OS blocks and drivers

Any layer may add `os:` blocks and `drivers:` entries: the repo, a plugin, an include, or your top
config (whose entries win, for this machine only). A higher layer's block overlays the lower block
of the same name field by field: it changes only the fields it sets.

An `os:` block describes one distro:

- **`using:`** its parent block (the lineage);
- **`native:`** its package manager (`apt`, `dnf`, `pacman`, `zypper`, `apk`, `xbps`, `brew`),
  inherited when absent;
- **`scale-root: true`** marks a block that numbers its own releases, so versioned atoms on a parent
  don't misread its version;
- **`provides:`** capabilities the OS has out of the box;
- **`driver-preference:`** an OS-specific tiebreak order that overrides the machine setting there;
- **`detect: { id: <base>  marker: <path> }`** detects a derivative that doesn't rebrand
  `/etc/os-release` (Proxmox VE reports `ID=debian`). When the detected block is that base, or a
  descendant of it, and every marker exists on disk (`marker:` may be a list), configsys routes to
  this block. This lets a plugin add a detectable OS with no code; the **configsys-proxmox** plugin
  does exactly this.

A `drivers:` entry configures one driver. Each field also applies to a `via: native` binding when
this OS's package manager is that driver:

- **`requires:`** capabilities every binding of that driver needs (`appImage` requires `libfuse2`
  and `glibc`; `cargo` requires `cargo`; `brew` requires `homebrew`, which configsys installs with
  Homebrew's official installer). They also decide where the driver works at all: **a driver is
  valid only where its own requirements can be met.** Where one can't be installed, none of that
  driver's methods is offered. Snap methods don't appear where snapd has no install method, and
  AppImage methods don't appear on musl systems (no glibc) or on Fedora Atomic and KDE Linux (no
  libfuse2). Your provider pins count: on Alpine, `pins: { glibc: gcompat }` opts in to the gcompat
  shim and makes AppImage methods valid there.
- **`standing: never-auto`** makes every binding of that driver a listed, pinnable alternative that
  never wins by default (the shipped `snap` entry does this).
- **`when:`** a validity gate for the whole driver, in the same expression language as a binding's
  `when:`, for a fact that isn't a requirement. Where it is false, no binding of that driver is
  valid. Unlike a binding's `when:`, it never makes a binding more specific, so it can't change
  which method is the default where the driver works. Two entries ship one: `brew` has `when:
  "glibc_linux"` (Homebrew's Linux bottles need glibc, so brew methods are valid on every glibc
  distro and on none of the musl ones), and `aur` has `when: "arch"` (the AUR is Arch's).

`configsys where` names the reason whenever a driver is ruled out, for example "the snap driver
can't work here: nothing provides "snapd" here".

```hu
drivers: {
    brew:     { requires: homebrew  when: "glibc_linux" }
    aur:      { requires: [ base-devel, git ]  when: "arch" }
    appImage: { requires: [ libfuse2, glibc ] }
}
```

A `drivers:` entry in your config merges field by field over the shipped one, so you can change one
field and keep the rest — for example `drivers: { flatpak: { standing: never-auto } }` keeps flatpak
methods available but stops them winning by default.

## Versions: discovered, not hardcoded

Download-based bindings declare *how* to find the latest version rather than pinning one:

```hu
neovim: {
    install: [ { via: appImage  name: Neovim  scope: user  path: ~/apps/nvim.appimage
                 cpu-names: { x86_64: x86_64  aarch64: arm64 }
                 version: { github: neovim/neovim  asset: "nvim-linux-$ARCH.appimage" }
                 url: "https://github.com/neovim/neovim/releases/download/$VERSION/nvim-linux-$ARCH.appimage" } ]
}
```

A `version:` is a discovery source, or a literal version string:

- **`{ github: owner/repo }`**: the newest stable release tag (pre-releases skipped). Options:
  `strip-v: true` drops a leading `v`; `tag-re: "<regex>"` keeps only matching tags and extracts the
  version from the first capture group (for monorepo or decorated tags); `pick: highest` takes the
  highest version rather than the newest; `asset: "<glob>"` also finds the download URL among the
  release's assets.
- **`{ crates: <crate> }`**, **`{ pypi: <dist> }`** (optionally with `python:`, to find the newest
  release that supports that interpreter), **`{ aur: <package> }`**, **`{ hackage: <package> }`**,
  **`{ goproxy: <package path> }`**: the registry's latest version.
- **`{ url: "..."  regex: "..." }`**: fetch a page and extract the version (the first capture group
  if the regex has one).
- **`{ static: "..." }`**: a deliberate pin. Add **`latest-check:`** (any discovery source) so
  `configsys refresh` notices when upstream moves past it and `check` reminds you.

Plugins may register further sources.

An **`asset:`** may also sit directly on the binding as a CPU-keyed map
(`{ x86_64: foo-amd64.tar.gz  aarch64: foo-arm64.tar.gz }`); its keys gate validity like
`cpu-names:`. `$VERSION` and `$ARCH` are filled into `url:` and asset globs at install time. When a
`github` asset name is literal (no glob), configsys can fall back to the API-free
`releases/latest/download/<asset>` URL, so installs keep working when the GitHub API is unreachable.

Discovered versions are cached (`~/.config/configsys/versions.hu`, 24-hour lifetime); `configsys
refresh` re-queries them (and refreshes the native package index); `configsys versions <name>` shows
what every method would install; and `--pretend` never touches the network (cache only). Release
tags come from GitHub's public feeds; a release asset's URL needs the GitHub API, so set
`CONFIGSYS_GITHUB_TOKEN` (or `GITHUB_TOKEN`) if you hit its unauthenticated rate limit.

## dotfiles

A `via: dotfiles` component manages an application's **own config**. Its binding lists link specs,
either top-level `src:`/`dst:` or named specs (`<name>: { src  dst }`):

```hu
btop-dotfiles: { install: [ { via: dotfiles  config: { src: btop  dst: $XDG_CONFIG_HOME/btop } } ] }
```

`dst` is where the config belongs (environment variables and `~` expanded), and `src` is resolved
through a content **search path**; the first of these that has it wins:

- `~/.config/configsys/dotfiles/<component>.cfs/<src>`, your machine-local store;
- `<primary plugin>/dotfiles/<component>.cfs/<src>`, your portable, git-tracked config;
- `<defining layer>/dotfiles/<component>.cfs/<src>`, a template, only if some layer ships one.

The **`<component>.cfs/`** marker directory is what makes a config *managed*: it holds the content
plus a `manifest.hu` recording the src-to-dst layout and any `exclude:` globs (secret-looking files
are suggested on first capture and kept out of git). A managed config with no files yet is still
managed; the marker, not the content, is the state.

configsys ships **no personal config templates**: a component may declare `src`/`dst` with no
content anywhere, in which case it is not linked (a no-op) until you supply content. Install
symlinks `dst` to your copy of the content, so edits land in your store or primary plugin; links
never point into the configsys repo.

Because your existing config is precious, install **refuses** to replace a real file with an
un-adopted template and tells you how to adopt it (`configsys dotfiles capture`), or to run
`install --force`, which backs the file up to `<name>.pre-configsys` and replaces it. Content you
have captured links freely (backing up whatever was there); an `absorb-into:` path on a spec moves a
pre-existing file into a loader directory instead of backing it up (for example a stray
`~/.bash_aliases`). `uninstall` removes the symlink and restores any backup.

`configsys dotfiles status` reports each config as **managed**, **unmanaged** (an on-system file to
capture, or stored content ready to link) or **no config**, with where its content lives, and lists
glue rows separately. `configsys dotfiles capture` copies your existing on-system dotfiles into your
store (read-only on the system side). The TUI **Dotfiles** screen does the same per row (`m`/`u`
manage/unmanage, `M`/`U` all, `s`/`S` move between the local and primary stores). A package that
ships config `suggests:` its `<name>-dotfiles` component (soft, so it attaches only where that
config exists).

## glue

A `via: glue` component is the **shell integration** a tool needs to be usable (PATH, an alias such
as `fdfind` for `fd`, an init hook such as `zoxide init`, completions), as a small snippet per
shell:

```hu
zoxide-glue: { install: [ { via: glue  requires: shell-glue  glue: zoxide } ] }
```

- Glue is **shipped, never captured**: a snippet is authored at `glue/shell/<shell>/<name>.<ext>`
  in the repo or a plugin, copied into the machine-local glue store
  (`~/.config/configsys/glue/<shell>/conf.d/`), and linked into `~/.config/<shell>/conf.d/` for
  each **installed** shell that has a variant. elvish and nushell can't source a directory, so
  their snippets are inlined into the rc file instead.
- **`shell-glue`** is the loader component: its `loader: <shell>` bindings wire every installed
  shell to read its `conf.d` (bash through `~/.bash_aliases`, zsh through a marked block in
  `~/.zshrc`, fish natively). Every snippet `requires:` it.
- A tool `suggests:` its `<name>-glue` companion, so the snippet attaches only where the tool is
  picked. Glue is active or not (it has no version) and has its own TUI **Glue** screen (`a`/`A`
  activate, `x` deactivate), grouped per shell. `CONFIGSYS_GLUE_SHELLS` (comma-separated) overrides
  which shells count as installed.
- Your own startup snippets live in a `user.d` folder and load after component glue:
  `configsys glue add` creates one, and `configsys glue override <name>` copies a shipped snippet
  into your layer to customize it.
- Opt out on a machine with `disabled-drivers: [ glue ]` (and/or `dotfiles`) to manage your own
  shell config; the shell-writes guard still keeps installers from editing it.

**Installer shell writes.** With `installer-shell-writes: block` (the default), an installer that
appends to your shell startup files (sdkman, nvm, rustup, conda, …) has the file restored to its
prior contents and the removed lines **staged** as an inactive glue candidate:
`configsys dotfiles staged` lists them, `activate` turns one into your own user glue (in your
primary plugin, or this machine's store with `--local`), and `discard` drops it.
`installer-shell-writes-allow` exempts named components.

## component-names

A higher layer (typically a plugin) can patch the package name a component maps to under a given
driver, or drop it where that driver has no package, without redefining the component:

```hu
component-names: {
    xbps: { docker-engine: docker  r: R  nmap: {} }   // rename; {} = no package here (drop)
}
```

It is keyed by driver and overlaid across the layer stack (later wins per driver and component): a
string replaces the resolved package name; `{}` (or an empty value) means "not available through
this driver", so the component isn't offered there. See docs/routing-model.md for the full rules.

## version-floors

`version-floors:` tightens version requirements without redefining components:

```hu
version-floors: {
    goimports: { go: ">=1.22" }
}
```

A floor applies only where the component already `requires:` that capability (at the component
level or on a binding); a floor for a capability it doesn't require is ignored, so this section
never adds a dependency. Later layers win per component and capability.

## facets

A **facet** is a detected fact about the machine (a GPU vendor, a tool's version) that `when:` can
test. The repo, plugins and included files declare facets with probes:

```hu
facets: {
    gpu:  { kind: categorical  detect: "lspci"  match: { nvidia: "NVIDIA"  amd: "AMD/ATI" } }
    cuda: { kind: version  detect: "nvcc --version"  version-re: "release ([0-9.]+)" }
}
```

A `categorical` facet's value is the set of `match:` tags whose regex matches the probe's output; a
`version` facet's value is the first capture group of `version-re:`. A probe that fails leaves the
facet undetected. A plugin's probes run only once you trust the plugin. A facet entry that isn't
a map of this shape is skipped with a warning.

In your top config, `facets:` instead **declares** values for facets defined elsewhere, overriding
their probes: a version (`cuda: 12`), or for a categorical facet a tag, several tags separated by
spaces or commas, or a list (`gpu: nvidia`, `gpu: [ nvidia amd ]`). Use it to target hardware or a
toolkit that isn't installed yet. A probe definition (a map) in your top config is ignored with a
warning; define probes in a plugin or an included file. `CONFIGSYS_FACET_<name>` overrides both.
See docs/facets.md.

## theme and keys

`theme:` sets the TUI palette: a shared `colors:` map of names to `#rrggbb`, per-page role styles
and background gradients under `pages:`, and `colors-basic:` for 8- and 16-color terminals. Edit it
live on the Theme screen or with `configsys theme`; see docs/theming.md.

`keys:` rebinds TUI keys by action: `keys: { <key scope>: { <action>: <key or [ keys ]> } }`, where
the key scope (unrelated to the install `scope:` setting) is `global`, `screens` (the number keys
that switch screens) or a screen name (`components`, `profiles`, `plugins`, `glue`, `dotfiles`,
`config`, `theme`). A key is a character (case matters), a named key (`enter`, `tab`, `esc`,
`space`, arrows, `pgup`, `pgdn`, `home`, `end`, `del`, `shift-tab`, `f1` to `f12`) or `ctrl-<x>`.
The on-screen hints follow your bindings, and `configsys keys` prints the effective map. The
subsections below are the full reference.

Both are cosmetic, so every layer may contribute them; they merge per key, and your top config has
the last word.

### Where `keys:` goes and how it merges

The `keys:` section of the repo's `config.hu` is the complete default map: configsys has no other
built-in bindings. Any layer may add a `keys:` section: an ordinary plugin, your primary plugin, a
file you `include:`, and your top config. They merge lowest-first (repo `config.hu` < plugins <
primary plugin < your top config, with an included file just below the file that includes it), per
key scope and per action:

- A layer overrides only the actions it names; every other action keeps its binding from below.
- The value replaces the lower one whole; it is not appended to. `down: J` leaves `down` on `J`
  alone (no `j`, no Down arrow). To add a key, list the old ones too: `down: [ j  down  J ]`.
- An empty list unbinds the action: `quit: []`.
- Your rebind wins: giving an action a key that a lower layer gave another action in the same key
  scope takes the key from that action. The other action keeps its remaining keys, or is left
  unbound if that was its only one; `check` reports each such move (see "Conflicts and
  validation").

For example, in your top config or primary plugin:

```hu
keys: {
    global: {
        down: [ j  down  ctrl-n ]    // add emacs-style keys; keep j and the arrow
        up: [ k  up  ctrl-p ]
        quit: []                     // no confirm-quit key; quit-force (Q) still works
    }
    components: {
        method: p                    // was v
        refresh: ctrl-r              // was R
    }
    screens: { components: "0" }     // the screen chip bar shows the new key
}
```

### Key scopes and dispatch

- **`screens`**: one entry per screen, `<screen>: <key>`, which switches to that screen from
  anywhere. The names are `components`, `profiles`, `plugins`, `glue`, `dotfiles`, `config` and
  `theme` (keys `1` to `7`, in that order).
- **`global`**: the actions every screen shares (navigation, find, filter, help, quit).
- **One key scope per screen** (`components`, `profiles`, `plugins`, `glue`, `dotfiles`, `config`,
  `theme`): that screen's own actions, which work only there.

How the TUI resolves a key:

- The current screen's own key scope is consulted first, for every key, including the keys `global`
  gives `quit`, `quit-force`, `issues` and `help` and the `screens` keys. A key a screen binds goes
  to that screen: `components: { refresh: q }` makes `q` refresh on Components, and you quit from
  there with another key. `check` warns if a screen takes every `quit` and `quit-force` key, leaving
  no way out of it.
- `quit`, `quit-force`, `issues` and `help` may themselves be bound in a screen's key scope, and
  then work on that screen.
- A key the screen doesn't bind goes to `global` (`quit`, `quit-force`, `issues`, `help`), then to
  `screens`, then to the screen's `global` navigation actions. A screen key therefore shadows the
  same key's global action on that screen: Components binds `tab` to `expand-all`, so `switch-pane`
  (`tab` in `global`) doesn't apply there.
- A screen's key scope may also bind any other `global` action, which adds keys for it on that
  screen only: `profiles: { down: ctrl-n }` makes Ctrl-N move down on Profiles, while `j` and the
  Down arrow still work there through `global`.
- The where and issues overlays scroll with the navigation actions as the `components` key scope
  resolves them (so your `global` keys, unless you rebound them under `components`); the issues
  overlay's `r`, `f` and `s` (file a report, request or OS request) are fixed. Pop-up choosers keep
  fixed keys (`j`/`k` or the arrows to move, Enter to choose, Esc or `q` to cancel), and text prompts
  such as find and filter take what you type.

With the shipped bindings no screen binds those keys, so `q`, `Q`, `!`, `?` and `1` to `7` work the
same everywhere.

### Actions and default keys

The defaults below are the shipped `config.hu` bindings; where an action has several keys, each
one works.

**global** (every screen):

- `down` (`j`, `down`) and `up` (`k`, `up`): move the cursor.
- `left` (`h`, `left`) and `right` (`l`, `right`): collapse or expand a tree row, or scroll
  columns, depending on the pane.
- `top` (`g`) and `bottom` (`G`): jump to the first or last row.
- `page-down` (`pgdn`, `ctrl-j`) and `page-up` (`pgup`, `ctrl-k`): move a page, in every pane and
  overlay.
- `select` (`space`): select or mark the current row.
- `confirm` (`enter`, `kpenter`): activate, open or apply. Return and Ctrl-J are different keys.
- `switch-pane` (`tab`) and `switch-pane-back` (`shift-tab`): move focus between the panes of a
  two-pane screen.
- `find` (`/`): jump the cursor to a match.
- `filter` (`F`): a live substring filter that narrows the list.
- `issues` (`!`): open the issues overlay.
- `help` (`?`): this screen's help.
- `quit` (`q`): leave the TUI, after a confirmation.
- `quit-force` (`Q`): leave at once, without asking.

**screens**: `components` (`1`), `profiles` (`2`), `plugins` (`3`), `glue` (`4`), `dotfiles`
(`5`), `config` (`6`), `theme` (`7`).

**components**:

- `where` (`w`): explain the current component, as `configsys where` does.
- `lock` (`L`): lock or unlock the version of every selected row, or of the current row if none is
  selected.
- `expand-all` (`tab`): expand or collapse the whole tree.
- `select-all` (`a`): select every row in view.
- `clear` (`c`): unstage the current or selected rows (and drop them from the uninstall queue), then
  clear the selection and errors.
- `method` (`v`): pick an install method or provider; writes a pin.
- `op-install` (`i`): stage making the current row or selection current: install if missing, else
  upgrade.
- `op-upgrade` (`u`): stage an upgrade of the current row or selection (outdated only).
- `op-install-all` (`I`): stage making every tracked component current.
- `op-upgrade-all` (`U`): stage an upgrade of every outdated component.
- `op-remove` (`x`): stage a removal.
- `execute` (`X`): run the staged operations, after a confirmation.
- `refresh` (`R`): re-query version sources and the native package index.
- `mode` (`M`): cycle the view mode: to-do, tracked, installed+tracked.

**profiles**:

- `where` (`w`): explain the highlighted component, as `configsys where` does, or, with the profile
  list focused, where the current profile is defined.
- `track-all` (`T`): toggle tracking of the multi-select set, or of every component in the
  selected profile, on the target machines.
- `track-one` (`t`): toggle tracking of the highlighted component.
- `disp-seen` (`s`): toggle the highlighted component between new and seen.
- `disp-interesting` (`i`): toggle interesting on the highlighted component.
- `disp-seen-all` (`S`) and `disp-interesting-all` (`I`): mark the multi-select set, or the whole
  selected profile, seen or interesting.
- `select-all` (`a`): add every component in view to the multi-select set.
- `method` (`v`): pin the highlighted component's install method.
- `comp-machines` (`m`): choose which machines track just the highlighted component.
- `machine-target` (`M`): choose the target machines that `track-all` and `track-one` edit.
- `attr-filter` (`f`): filter the catalog by attrs.
- `toggle-install` (`O`): turn the install overlay on or off.
- `stage-uninstall` (`x`): stage the highlighted component in the uninstall queue.
- `mark-all-seen` (`E`): mark every new component seen, after a confirmation.
- `claim` (`C`): track every installed component, after a confirmation.
- `orphan-ignore` (`.`): add the highlighted component to `orphans-ignore:`, or remove it.

**plugins**:

- `add` (`a`): add a plugin.
- `remove` (`x`): remove the current plugin.
- `sync` (`s`) and `sync-all` (`S`): sync the current plugin, or all of them.
- `bless` (`b`): make the current plugin your primary plugin (syncing it first).
- `unbless` (`B`): clear the primary plugin.
- `update` (`u`) and `update-all` (`U`): update to the newest stable tag (else `main`/`master`) and
  re-sync.
- `trust` (`t`): trust or untrust the current plugin's code or recipes.
- `trust-all` (`T`): trust every untrusted or changed plugin.
- `set-ref` (`v`): pin a tag, branch or commit and re-sync.

**glue**:

- `activate` (`a`): activate the current snippet for its row's shell.
- `activate-group` (`A`): (re)activate every snippet in the cursor's shell group, refreshing
  changed ones.
- `deactivate` (`x`): deactivate the current snippet for its row's shell.

**dotfiles**:

- `manage` (`m`): manage the current config (capture it, then link it); `confirm` does the same.
- `manage-all` (`M`): manage every unmanaged config.
- `unmanage` (`u`): unmanage (unlink) the current config, after a confirmation.
- `unmanage-all` (`U`): unmanage every managed config, after a confirmation.
- `move-store` (`s`): move the current config between stores (local or your primary plugin).
- `move-store-all` (`S`): move every config to a store you choose.

**config** (`confirm` or `select` edits the current setting):

- `theme` (`t`): open the theme editor.
- `move` (`m`): move the current setting between your top config and your primary plugin.

**theme**:

- `page-1` to `page-7` (`f1` to `f7`): choose the sample page the editor previews (components,
  profiles, plugins, glue, dotfiles, config, theme).
- `new` (`n`): add a color to the map.
- `reset` (`r`, `x`): reset the current color, role or gradient end to its default (a color you
  added is removed).
- `edit-bg` (`B`): edit a role's background.
- `effect-bold` (`o`), `effect-underline` (`u`) and `effect-reverse` (`v`): toggle that effect on
  a role.
- `gradient-toggle` (`p`): toggle this page's background gradient.
- `copy-page` (`D`): copy this page's look onto another.
- `save` (`s`): export a theme pack, or promote the theme to your primary plugin.
- `load` (`L`): load a saved theme pack.

### Key names

- A single character is that key, case-sensitive: `g` and `G` are different keys. Quote
  punctuation and digits (`"/"`, `"?"`, `"1"`): Humon gives some characters a meaning, and a quoted
  key is always read literally.
- Named keys, in any case: `enter` (also `return`, `ret`, `cr`: the Return key), `kpenter` (also
  `kp-enter`: keypad Enter), `tab`, `shift-tab` (also `btab`), `esc` (also `escape`), `space` (also
  `spc`), `up`, `down`, `left`, `right`, `pgup` (also `pageup`), `pgdn` (also `pagedown`), `home`,
  `end`, `backspace` (also `bs`), `del` (also `delete`), `ins` (also `insert`), and `f1` to `f12`.
- `ctrl-<letter>` (also `c-<letter>` or `^<letter>`): a control key. Only letters are accepted.
  Return and Ctrl-J are different keys, but `ctrl-i` is the same key as `tab` and `ctrl-m` the same
  as `enter`.
- A list binds alternates: `down: [ j  down ]`. The first key is the one the hints show.

### Conflicts and validation

`configsys check` lints every layer's `keys:` section and prints a `warn` line, starting with the
file's name, for:

- an unknown key scope (`unknown key scope 'componets'`);
- an action its key scope doesn't have (`unknown action 'keys.components.lokc'`); a screen's key
  scope accepts its own actions plus the `global` ones, and `screens` accepts the screen names;
- a key name it can't parse (`keys.components.mode: unparseable key 'bogus-key'`);
- one key bound to two actions in the same key scope of the same file (`keys.profiles: 'z' bound to
  both 'track-one' and 'track-all'`); the TUI uses the first one listed;
- a key a higher layer takes from another action of a lower layer in the same key scope. Binding
  `components: { where: i }` in your config takes `i` from the shipped `op-install`, which is left
  unbound because `i` was its only key: `configsys.hu: keys.components.where: 'i' takes the key from
  'op-install' (config.hu) — 'op-install' is now unbound in keys.components`;
- a screen whose key scope takes every `quit` and `quit-force` key, so there is no way to quit from
  it;
- a key scope whose value isn't a map.

It doesn't report a screen key that shadows a `global` or `screens` key: that is the intended
override (see "Key scopes and dispatch").

None of these stop the TUI: an unknown key scope or action is ignored, an unparseable key drops out
of its list (the others still bind), and if the merged map has no `global` key scope at all (a
missing or broken repo `config.hu`), a minimal built-in map keeps `q`, `Q`, `!` and the screen keys
`1` to `7` working.

`configsys keys` prints the effective, merged map exactly as the TUI resolves it (with your rebinds
having taken their keys): each key scope (screens, global, then the screens in order: components,
profiles, plugins, glue, dotfiles, config, theme, then any other key scope a layer names), its
actions in alphabetical order, and each action's keys as the TUI draws them (`⏎` for Enter, arrows,
`^r` for Ctrl-R, `F1`), joined by ` / `. It doesn't validate: an unknown action or key scope prints
as given, and an action left with no key (unbound with `[]`, or whose only key a rebind took) is
absent. Run `configsys check` for the warnings.

### Help and hints

The TUI reads the same merged map it dispatches on, so what it shows matches what the keys do:

- Each screen's footer hints and the screen chip bar show an action's first key.
- The `?` overlay lists the live bindings: the `global` actions first (down, up, left, right, top,
  bottom, page-down, page-up, select, confirm, switch-pane, switch-pane-back, find, filter, issues,
  help, quit, quit-force), then the screen's own actions in
  alphabetical order, each with up to two keys joined by `/` and a short label. The Theme screen's
  `page-1` to `page-7` collapse to one row, "preview sample page". The overlay scrolls with your
  navigation keys and closes on Esc, `q`, or your `quit` or `help` key.

## Drivers

Each `via:` value names a driver:

- the OS package managers: `apt`, `dnf`, `pacman`, `aur`, `zypper`, `apk`, `xbps`, `brew`,
  `rpm-ostree`;
- the distribution drivers: `flatpak`, `snap`, `appImage`, `tarball` (also bare executables and
  `.zip` archives), `native-pkg-file` (an upstream release's `.deb`/`.rpm`/pacman package installed
  with the OS package tool; distinct from repo `native`, since it doesn't ride system updates),
  `source` (build from a git checkout or source archive with declared `build:` commands), `font`,
  and `script` (declared install/version/uninstall commands);
- the config drivers: `dotfiles` and `glue`;
- the language toolchains and their module or version installers: `cargo`, `pip`, `pipx`, `npm`,
  `gem`, `go-install`, `opam`, `luarocks`, `cabal`, `pyenv`, `sdkman`, `gcc`, `gcc-toolset`,
  `clang`;
- the post-install primitives: `service` (enable a systemd or runit service) and `group` (add you
  to a group).

Two `via:` values are special: `native` (this OS's package manager) and `parts` (a pure aggregator).
Plugins may add drivers.

## Retired keys

These still parse, but `check` warns about them:

- `configs:` is retired; the install set is `picks:`.
- `machines:` is retired; each `picks:` key is a machine.
- `orphans-adopt-target:` is retired; adopting an orphan picks it.

On a binding or a `drivers:` entry, `prefer:` became `standing: <integer>`, and `opt-in:` and
`candidate-only:` became `standing: never-auto`. The old names are not read, and `check` warns
about each one so a preference you meant doesn't silently do nothing. On a component they are an
error that names the replacement.

`last-refresh:` is not a config key: configsys keeps the last refresh time in its state directory,
and `check` reports the key as unrecognized.

## Environment

- `CONFIGSYS_CONFIG` (or `--config`): the top config's path.
- `CONFIGSYS_HOME` (or `--home`): the base for `~` paths and for the state directory
  (`<home>/.config/configsys`), to sandbox a run.
- `XDG_CONFIG_HOME`: the base of the state directory when `CONFIGSYS_HOME` isn't set.
- `CONFIGSYS_STATE_DIR`: the state directory itself (plugins, caches, the ledger, and by default
  your top config).
- `CONFIGSYS_USERSCOPE_DIR`, `CONFIGSYS_SYSTEMSCOPE_DIR`, `CONFIGSYS_APP_DIR`, `CONFIGSYS_SDK_DIR`,
  `CONFIGSYS_SRC_DIR`: override the matching `dirs:` key.
- `CONFIGSYS_OS`, `CONFIGSYS_OS_VERSION`, `CONFIGSYS_ARCH`: evaluate routes as this OS block,
  version and CPU instead of the detected ones (`--os` sets the block).
- `CONFIGSYS_FACET_<name>`: a facet's value, overriding detection and your `facets:`.
- `CONFIGSYS_EFFECTS`: overrides `effects:` (`--effects` sets it).
- `CONFIGSYS_NO_SPLASH`: no startup splash; `CONFIGSYS_SPLASH=always` shows it even on a fast
  start.
- `CONFIGSYS_GLUE_SHELLS`: which shells glue treats as installed.
- `CONFIGSYS_GITHUB_TOKEN` (or `GITHUB_TOKEN`): authenticates GitHub API calls.
- `CONFIGSYS_GIT_TOKEN`: lets `plugin sync` clone a private `github:`/`gitlab:` plugin.

## See also

**configsys(1)** for the command-line interface; the README for a narrative overview;
docs/routing-model.md, docs/plugins.md, docs/facets.md and docs/theming.md for the details.
