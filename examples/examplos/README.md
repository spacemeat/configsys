# ExamplOS — the reference configsys plugin

A complete, working **code plugin** for a distro that does not exist. **ExamplOS** is a made-up
Linux distribution whose made-up package manager is **`toybox`**. Everything here is real
configsys — a real OS block, a real driver, real trust — but the OS is fictional on purpose:

- it **can't rot** (there's no upstream `toybox` repo to rename packages out from under it), so
  this example stays green forever as a teaching artifact;
- **nobody mistakes it for something to install** — real OS plugins (configsys-proxmox, and
  configsys-void as a worked Void example) live in their own repos, precisely because they're real
  and useful.

Copy this directory to start your own plugin. If you want the guided tour, read
**[WALKTHROUGH.md](WALKTHROUGH.md)** — it builds this plugin up from an empty file, one idea at a
time.

## The files

| File | Role |
| --- | --- |
| `plugin.hu` | manifest — `name`, `requires-abi`, `provides`, `data:` (routing layers), `code:` (the module) |
| `routes.hu` | data — the `examplos` OS block, a `via: toybox` component, and a `component-names:` map |
| `driver.py` | code — the `Toybox(Driver)` subclass + `DRIVERS = [Toybox]` export |
| `WALKTHROUGH.md` | the narrated build, stage by stage |
| `README.md` | this page |

## What it demonstrates

- **A new OS in one block.** `os: { examplos: { using: linux  native: toybox } }` makes every
  existing repo component that routes `via: native` install on ExamplOS through toybox — no
  per-component work.
- **A new driver.** `driver.py` subclasses `Driver` from the frozen ABI surface and implements the
  op set (`get_version`/`install`/`upgrade`/`lock`/…) with `toybox` commands. Query ops need no
  root; mutations run under sudo.
- **Correct package names, without redefining components.** ExamplOS calls ripgrep `rg` and
  doesn't package `nmap`; `component-names:` patches those onto the core components (a rename, and
  a `{}` drop) without owning the whole definition. See §10a of [docs/routing-model.md](../../docs/routing-model.md).
- **The trust gate.** Because `plugin.hu` has a `code:` key, the plugin runs with your privileges
  during installs — so its driver stays unloaded, and its own `via: toybox` binding is held back,
  until you approve its exact contents.

## Try it

`plugin add` clones its source, so give the example a git repository of its own first (it lives
inside the configsys repo, which isn't a plugin) — WALKTHROUGH.md does the same. Run these from
your configsys checkout; `git archive` copies just the files git tracks:

```console
$ mkdir /tmp/examplos && git archive HEAD:examples/examplos | tar -x -C /tmp/examplos
$ git -C /tmp/examplos init -q && git -C /tmp/examplos add -A \
      && git -C /tmp/examplos commit -qm examplos
$ ./configsys.sh --os examplos plugin add /tmp/examplos --local   # a local path, this machine only
$ ./configsys.sh --os examplos plugin list
  examplos               /tmp/examplos
                         ok  [ships code — untrusted; run: configsys plugin trust examplos]
                         provides: components, os, drivers, component-names

# its code — the toybox driver — won't load until you approve this content
$ ./configsys.sh --os examplos plugin trust examplos

# now the toybox driver is loaded: repo components install via toybox on ExamplOS,
# and so does the plugin's own toychest
$ ./configsys.sh --os examplos where btop        # -> toybox\btop  pkg btop
$ ./configsys.sh --os examplos where ripgrep     # -> toybox\ripgrep  pkg rg  (component-names)
$ ./configsys.sh --os examplos where toychest    # -> toybox\toychest  pkg toychest
```

`--os examplos` forces the (otherwise undetectable) fictional OS. Until you trust the plugin, its
data still loads: `btop` and `ripgrep` already resolve to `toybox\btop` and `toybox\ripgrep`
(package `rg`), because their `via: native` bindings come from configsys's own routes and the
`component-names` patch is plain data. But the toybox driver isn't loaded, so those units read
`untrusted` in `inspect`, and `where toychest` reports an error that names `plugin trust` — never a
crash.
