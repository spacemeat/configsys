# configsys-proxmox

An example **configsys plugin** that makes **Proxmox VE** a first-class OS. It demonstrates two
things worth copying:

- adding a **detectable derivative distro** purely in data (no code), and
- a **pure-data plugin** — no driver, so no trust step (contrast `configsys-void`, which ships an
  `xbps` driver).

## What it does

Proxmox VE 8 is Debian 12 under the hood, so the `os:` block simply says `using: debian`. That
one line inherits the whole `debian` family — every component configsys already routes
`via: native` installs on a PVE host through apt, with zero per-component work.

The interesting part is **detection**. Proxmox does not rebrand `/etc/os-release` (it reports
`ID=debian`), so it can't be told apart by ID alone. The block declares a marker instead:

```hu
proxmox: { using: debian  detect: { id: debian  marker: /etc/pve } }
```

`/etc/pve` exists on every Proxmox host, so when configsys detects `debian` and sees that marker,
it routes to `proxmox`. This is the data-driven form of the ostree marker configsys uses
internally for Fedora Atomic — now available to any plugin. Override anytime with `--os proxmox`.

It also `provides: qemu` (PVE ships QEMU/KVM, so installing `qemu` is a no-op), adds a lean
`proxmox-admin` profile (admin CLI tooling — a hypervisor host is an appliance, not a
workstation), and one PVE-specific component, `proxmox-headers`.

## Using it

Declare and sync it in `~/.config/configsys/configsys.hu`:

```hu
plugins: [ { source: "github:you/configsys-proxmox"  ref: v0.1.0 } ]
configs:  [ proxmox-admin ]
```

```console
$ configsys plugin sync
$ configsys inspect                      # on a PVE host, OS shows `proxmox`
$ configsys install profile:proxmox-admin
```

Or point at a local checkout with `configsys plugin add <path>`.

## Why not the virtualization components?

Proxmox drives QEMU + LXC directly through its own stack — it does **not** use libvirt. So the
core `virt-manager`/`libvirt` components are not the PVE way; this plugin deliberately leaves them
alone and only marks `qemu` as already-provided.

## Pure data — no trust step

There is no `code:` in the manifest, so nothing here runs with your privileges beyond apt. That's
the whole plugin: an OS block, a detection marker, a profile, and a component.
