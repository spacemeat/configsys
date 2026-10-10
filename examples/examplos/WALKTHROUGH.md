# Building a configsys plugin, from an empty file

Let's teach configsys about an operating system it's never heard of.

Our OS is **ExamplOS**. It doesn't exist. Its package manager, **`toybox`**, doesn't exist either.
This is on purpose — a fictional distro can't rename a package out from under us mid-tutorial, so
we get to focus entirely on the *shape* of a plugin. Everything you write here is exactly what a
real plugin (Void, Proxmox, your homegrown distro) is made of; only the distro is pretend.

By the end you'll have three files. We'll write them in the order they actually earn their keep,
and at each stage you'll be able to *see the thing work* before adding the next piece. (Run the
`./configsys.sh` commands from your configsys checkout.)

---

## Stage 0 — what a plugin actually is

A configsys plugin is just **a directory that contributes to the routing stack**. At most it has:

- some **data** (`.hu` files) — an OS block, components, a name map;
- optionally some **code** (`.py`) — a driver, if your OS installs software in a way configsys
  doesn't already know;
- a **manifest** (`plugin.hu`) tying those together.

The magic word is *contributes*. Your plugin's data merges into the same layer stack as the
built-in `routes.hu`, so you're not reimplementing configsys — you're adding to it. Watch how
little that takes.

---

## Stage 1 — the OS block (one line does a shocking amount)

Make a directory for the plugin — say `~/configsys-examplos` — and in it a file `routes.hu` that
declares the OS:

```hu
{
    os: {
        examplos: { using: linux  native: toybox }
    }
}
```

That's the whole first stage. Two claims:

- **`using: linux`** — ExamplOS is a Linux. It *inherits the entire `linux` baseline*: every
  capability, every `when: "linux"` binding, the works. You are standing on top of everything
  configsys already knows about Linux.
- **`native: toybox`** — when a component says "install me the native way," the native way here is
  `toybox`.

That file is already a plugin — a data-only one. configsys fetches plugins with git, so make the
directory a repository and add it:

```console
$ cd ~/configsys-examplos && git init -q && git add -A && git commit -qm "OS block" && cd -
$ ./configsys.sh --os examplos plugin add ~/configsys-examplos --local
```

(`--local` keeps the plugin on this machine even if you have a primary plugin that travels to your
others.) From here on, after each change, commit it and run `./configsys.sh plugin sync` — the
sync picks up whatever you've committed.

Here's the part that surprises people. configsys already has hundreds of components that route
`via: native` — `btop`, `git`, `ripgrep`, `tmux`, on and on. Because of that one `native: toybox`,
**all of them now route through toybox on ExamplOS**, with zero per-component work:

```console
$ ./configsys.sh --os examplos where btop
  ...
  on examplos (x86_64):
    ...
    toybox\btop  pkg btop
```

Note we haven't written a single line of Python yet. Resolution is pure data — it picks *which*
driver and *what* package name, and doesn't care whether the driver's code exists. (We used
`--os examplos` because ExamplOS is fictional and won't be auto-detected. A real distro announces
itself in `/etc/os-release`; one that doesn't have its own ID there can name a `detect:` marker
file in its OS block — see the `pios` block in the shipped `routes.hu`.)

---

## Stage 2 — a component of your own

ExamplOS ships a little package-management helper called `toychest`. It's unique to this distro,
so we install it the *direct* way — naming the driver ourselves instead of going through `native`:

```hu
    components: {
        toychest: { install: [ { via: toybox  when: "examplos" } ] }
    }
```

Two habits worth forming:

- **`via: toybox`** is the direct form — use it for things unique to your distro. Everything from
  the base catalog can keep using `via: native`; you only reach for the direct form when *you*
  own the component.
- **`when: "examplos"`** guards the binding to your OS. A binding for `via: toybox` only makes
  sense where toybox exists, so we gate it.

Commit, sync, and ask configsys about it:

```console
$ ./configsys.sh --os examplos where toychest
  ...
  bindings
    - via toybox   when: examplos  <- default here
  on examplos (x86_64):
    toybox\toychest  pkg toychest
```

Everything so far is data. If `toybox` were a package manager configsys already shipped, **you'd
be done** — no code at all. It isn't, so we teach configsys how to drive it.

---

## Stage 3 — the driver (now we write code)

A driver is a Python class that knows how to run one package manager. Make `driver.py`:

```python
from configsys.plugins import Driver, Result

class Toybox(Driver):
    name = 'toybox'
    privileged = True               # writes go through sudo
    default_scope = 'system'        # toybox packages are system-wide

    def get_version(self, rc):                      # read ops need no root
        r = self.runner.run(f'toybox show {rc.name}')
        return _version_of(r.stdout, rc.name) if r.ok else None

    def install(self, rc):                          # write ops run under sudo
        return self.runner.run(f'toybox add {rc.name}', sudo=True, capture=False)

    # ... uninstall / upgrade / set_version / lock / unlock / get_latest / is_locked ...

DRIVERS = [Toybox]
```

The rules, and there are only a few:

- **Subclass `Driver`, import only from `configsys.plugins`.** That module is the *frozen ABI
  surface* — the one contract that's guaranteed stable across configsys versions. Import anything
  else and you're coding against internals that can move.
- **Implement the op set** you can support: read ops (`get_version`, `get_latest`, `is_locked`)
  and write ops (`install`, `uninstall`, `upgrade`, `set_version`, `lock`, `unlock`). Reads query
  and need no root; writes mutate and pass `sudo=True`.
- **Export `DRIVERS`** — a list of your classes. That's the hook the loader reads.

The commands themselves are the *only* part that's fictional. Swap `toybox add` for `apt-get
install`, `dnf install`, `pacman -S`, `nix-env -i`, whatever your real manager wants. The shape
doesn't change. (In fact, configsys's own Alpine, openSUSE and Void drivers began life as plugins
shaped exactly like this one, then graduated into the base tool.)

The full `driver.py` in this directory has a couple of nice touches worth a look — a parser that
refuses to let `widget-extras` answer a query for `widget`, and a real `lock`/`unlock` — but the
skeleton above is the whole idea.

---

## Stage 4 — the manifest (tie it together)

`plugin.hu` is the cover sheet configsys reads first:

```hu
{
    name: examplos
    requires-abi: 1                 // the ABI your code targets; the loader checks it
    provides: {
        os: examplos
        drivers: [ toybox ]         // "toybox is a real driver of mine, not a typo"
    }
    data: [ routes.hu ]             // the layers to merge
    code: driver.py                 // the module to load — its presence means "ships code"
}
```

`requires-abi` is your compatibility handshake: configsys loads the plugin only if it supports
that ABI. `provides.drivers` matters more than it looks — it's how `check` can tell a *pending*
driver (`toybox`, real but not yet trusted) apart from a genuine typo, so an untrusted plugin
*nudges* you instead of erroring.

---

## Stage 5 — trust (because code runs as you)

Here's the thing about `code:` — that driver runs **with your privileges** during an install. So
configsys refuses to run it until you've explicitly approved its exact contents. Commit the driver
and manifest, sync, and you'll see the plugin sitting there, inert:

```console
$ ./configsys.sh --os examplos plugin sync
$ ./configsys.sh --os examplos plugin list
  examplos               /home/you/configsys-examplos
                         ok  [ships code — untrusted; run: configsys plugin trust examplos]
```

The *data* still loads — the `examplos` OS block and `toychest` resolve exactly as before. But the
`toybox` driver isn't registered yet, so anything installed through it shows the `untrusted` status
(never a crash), and `check` nudges you to trust the plugin. Trust it and the code registers:

```console
$ ./configsys.sh --os examplos plugin trust examplos
configsys: trusted examplos @ bd14ddac0922 — its code will run
$ ./configsys.sh --os examplos plugin list
  examplos               /home/you/configsys-examplos
                         ok  [code trusted]
```

Trust binds to a **content hash**, not a version tag. Change one byte of `driver.py` and the trust
re-arms — you'll be asked to approve it again. That's the point: you're trusting *this exact code*,
not a name.

---

## Stage 6 — fixing the names that don't match

One loose end. Our `via: native` win from Stage 1 was almost free — but "almost." ExamplOS calls
ripgrep `rg`, and it doesn't package `nmap` at all. The generic default gets those wrong.

We could redefine the `ripgrep` and `nmap` components wholesale in our plugin, but that's a bad
trade: we'd be copying the base tool's definitions and they'd drift apart the moment the base
changes. What we actually want is to *patch a name*, not adopt a component. That's
`component-names`:

```hu
    component-names: {
        toybox: {
            ripgrep: rg        // ExamplOS ships it under its binary name
            nmap:    {}        // not packaged here -> just don't offer it
        }
    }
```

Keyed by **driver**. A string renames the package; `{}` (empty) means "toybox has no package for
this," so the component is quietly dropped on ExamplOS — not an error, just not offered there.
The base `ripgrep` and `nmap` components stay
untouched and keep updating; we've only leaned a correction against them for our driver.

```console
$ ./configsys.sh --os examplos where ripgrep
  ...
  on examplos (x86_64):
    toybox\ripgrep  pkg rg          # renamed, without touching the base ripgrep component

$ ./configsys.sh --os examplos where nmap
  ...
  on examplos (x86_64):
    nothing                          # {} -> dropped, not an error
```

How do you *know* which names are wrong? You don't guess — you run the name sweep against a real
container image and let it tell you. That's exactly how the real Void plugin's map was built
(`tools/namesweep.py --plugin`). ExamplOS has no image to check against, being imaginary, so its
tiny map is hand-written for illustration.

---

## That's the whole thing

Three files:

```
configsys-examplos/
├── plugin.hu    manifest
├── routes.hu    OS block + component + name map
└── driver.py    the toybox driver
```

(The copy in `examples/examplos/` adds a README and this walkthrough.)

To share it, push the repository somewhere and swap your own declaration over to the published
copy with `./configsys.sh plugin add github:you/configsys-examplos --replace`; others run
`./configsys.sh plugin add github:you/configsys-examplos`. (Trust re-arms if the content differs.)
If your driver turns out to be broadly useful, it can graduate into base configsys — which is
precisely the path Alpine, openSUSE and Void took.

Now go teach configsys about *your* OS. Swap the toybox commands for your real package manager,
point `using:` at the closest base family, and let the sweep keep your names honest.
