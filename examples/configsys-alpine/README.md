# configsys-alpine — an example code plugin

A complete, working [configsys](../../README.md) **code plugin** that adds Alpine Linux
support: an `alpine` OS block, an `apk` driver, and a sample `via: apk` component. Use it as
a template for any package manager configsys doesn't ship (zypper, xbps, nix, …).

It's three files — the shape of every code plugin:

| File | Role |
| --- | --- |
| `plugin.hu` | manifest — name, `requires-abi`, `data:` (the routing layers), `code:` (the module) |
| `routes.hu` | data — the `alpine` OS block + `via: apk` components |
| `driver.py` | code — the `Apk(Driver)` subclass + `DRIVERS = [Apk]` export |

## What it demonstrates

- **A new OS in one block.** `os: { alpine: { using: linux  native: apk } }` makes every
  existing repo component that routes `via: native` install on Alpine — no per-component work.
- **A new driver.** `driver.py` subclasses `Driver` from the frozen ABI surface and implements
  the op set (`get_version`/`install`/`upgrade`/…) with real `apk` commands. Query ops need no
  root; mutations run under sudo. Rolling-distro realities (no native per-package hold) are
  handled the way `pacman` does.
- **The trust gate.** Because `plugin.hu` has a `code:` key, the plugin runs with your
  privileges during installs — so it stays inert until you approve its exact contents.

## Try it

```console
# point configsys at this plugin (publish it as its own git repo, or use a local path)
$ configsys plugin add github:you/configsys-alpine --ref v0.1.0
$ configsys plugin list
  alpine   github:you/configsys-alpine @v0.1.0
           ok  [ships code — untrusted; run: configsys plugin trust alpine]

# its code — the apk driver — won't load until you approve this content
$ configsys plugin trust alpine
configsys: trusted alpine @ <sha256> — its code will run during installs

# now `via: apk` resolves; on an Alpine box, `btop` (a repo component) installs via apk too
$ configsys where doas
```

Until trusted, the data still loads (you'll see the `alpine` OS block and `doas`), but
`via: apk` is an unknown driver and the component degrades to an error row — never a crash.

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
