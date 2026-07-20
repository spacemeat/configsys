# configsys-void — an example code plugin

A complete, working [configsys](../../README.md) **code plugin** that adds Void Linux
support: a `void` OS block, an `xbps` driver, and a sample `via: xbps` component. Use it as
a template for any package manager configsys doesn't ship (nix, slackpkg, …). Alpine (`apk`)
and openSUSE (`zypper`) started as plugins shaped exactly like this and were later folded
into base — this example is the same pattern, kept as a live template.

It's three files — the shape of every code plugin:

| File | Role |
| --- | --- |
| `plugin.hu` | manifest — name, `requires-abi`, `data:` (the routing layers), `code:` (the module) |
| `routes.hu` | data — the `void` OS block + `via: xbps` components |
| `driver.py` | code — the `Xbps(Driver)` subclass + `DRIVERS = [Xbps]` export |

## What it demonstrates

- **A new OS in one block.** `os: { void: { using: linux  native: xbps } }` makes every
  existing repo component that routes `via: native` install on Void — no per-component work.
- **A new driver.** `driver.py` subclasses `Driver` from the frozen ABI surface and implements
  the op set (`get_version`/`install`/`upgrade`/…) with real `xbps-*` commands. Query ops need
  no root; mutations run under sudo. Void is rolling but has a native package hold, so this
  driver implements a real `lock`/`unlock` via `xbps-pkgdb -m hold`.
- **The trust gate.** Because `plugin.hu` has a `code:` key, the plugin runs with your
  privileges during installs — so it stays inert until you approve its exact contents.

## Try it

```console
# point configsys at this plugin (publish it as its own git repo, or use a local path)
$ configsys plugin add github:you/configsys-void --ref v0.1.0
$ configsys plugin list
  void   github:you/configsys-void @v0.1.0
         ok  [ships code — untrusted; run: configsys plugin trust void]

# its code — the xbps driver — won't load until you approve this content
$ configsys plugin trust void
configsys: trusted void @ <sha256> — its code will run during installs

# now `via: xbps` resolves; on a Void box, `btop` (a repo component) installs via xbps too
$ configsys where xtools
```

Until trusted, the data still loads (you'll see the `void` OS block and `xtools`), but
`via: xbps` is an unknown driver and the component degrades to an error row — never a crash.

## Writing your own

Copy this directory, then:

1. Rename in `plugin.hu` (`name`, `provides`) and keep `requires-abi: 1`.
2. In `driver.py`, set `name = '<your-driver>'`, implement the op set against your package
   manager, and list your classes in `DRIVERS = [ ... ]`. Import only from the frozen surface:
   `from configsys.plugins import Driver, Result`.
3. In `routes.hu`, add your `os:` block (if it's a new distro) and components with
   `{ via: <your-driver> ... }` bindings.

The contract your `Driver` codes against — class attributes, the ops to implement, and the
helpers you may call (`resolve_version`, `download_url`, `scoped_dir`, `sudo`, `scope`, …) — is
documented on the `Driver` base class (`configsys/driver.py`) and versioned by
`configsys.plugins.ABI_VERSION`.
