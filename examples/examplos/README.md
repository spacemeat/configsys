# ExamplOS — the reference configsys plugin

A complete, working **code plugin** for a distro that does not exist. **ExamplOS** is a made-up
Linux distribution whose made-up package manager is **`toybox`**. Everything here is real
configsys — a real OS block, a real driver, real trust — but the OS is fictional on purpose:

- it **can't rot** (there's no upstream `toybox` repo to rename packages out from under it), so
  this example stays green forever as a teaching artifact;
- **nobody mistakes it for something to install** — real OS plugins (Void, Proxmox) live in their
  own repos, precisely because they're real and useful.

Copy this directory to start your own plugin. If you want the guided tour, read
**[WALKTHROUGH.md](WALKTHROUGH.md)** — it builds this plugin up from an empty file, one idea at a
time.

## The four files

| File | Role |
| --- | --- |
| `plugin.hu` | manifest — `name`, `requires-abi`, `provides`, `data:` (routing layers), `code:` (the module) |
| `routes.hu` | data — the `examplos` OS block, a `via: toybox` component, and a `component-names:` map |
| `driver.py` | code — the `Toybox(Driver)` subclass + `DRIVERS = [Toybox]` export |
| `WALKTHROUGH.md` | the narrated build, stage by stage |

## What it demonstrates

- **A new OS in one block.** `os: { examplos: { using: linux  native: toybox } }` makes every
  existing repo component that routes `via: native` install on ExamplOS through toybox — no
  per-component work.
- **A new driver.** `driver.py` subclasses `Driver` from the frozen ABI surface and implements the
  op set (`get_version`/`install`/`upgrade`/`lock`/…) with `toybox` commands. Query ops need no
  root; mutations run under sudo.
- **Correct package names, without redefining components.** ExamplOS calls ripgrep `rg` and
  doesn't package `nmap`; `component-names:` patches those onto the core components (a rename, and
  a `{}` drop) without owning the whole definition. See §10a of `docs/routing-model.md`.
- **The trust gate.** Because `plugin.hu` has a `code:` key, the plugin runs with your privileges
  during installs — so it stays inert until you approve its exact contents.

## Try it

```console
$ ./configsys.sh --os examplos plugin add examples/examplos     # a local path is fine
$ ./configsys.sh --os examplos plugin list
  examplos   examples/examplos
             ok  [ships code — untrusted; run: configsys plugin trust examplos]

# its code — the toybox driver — won't load until you approve this content
$ ./configsys.sh --os examplos plugin trust examplos

# now `via: toybox` resolves; a repo component installs via toybox on ExamplOS
$ ./configsys.sh --os examplos where btop        # -> toybox\btop  pkg btop
$ ./configsys.sh --os examplos where ripgrep     # -> toybox\ripgrep  pkg rg  (component-names)
```

`--os examplos` forces the (otherwise undetectable) fictional OS. Until trusted, the data still
loads — you'll see the `examplos` block and `toychest` — but `via: toybox` is an unknown driver
and the component degrades to a reported error, never a crash.
