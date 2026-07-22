# Immutable / atomic distro support — design (scoping doc, not yet built)

Status: **proposed**. Triggered by the Bazzite request. Bazzite is not one distro but the
visible tip of a *class* — atomic/image-based systems with a read-only root where packages are
not installed the traditional way. This doc scopes support for that class. Nothing here is built
yet; it exists to lock the load-bearing decisions before code.

## The landscape

| Family | Layering tool | Underlying PM | App path | CLI path | Version line |
|---|---|---|---|---|---|
| **Fedora Atomic** (Silverblue, Kinoite, Sericea) + **uBlue** (Bazzite, Bluefin, Aurora) | `rpm-ostree` (→ bootc) | dnf/rpm | **Flatpak** | **Homebrew** / distrobox | tracks Fedora N |
| openSUSE **MicroOS / Aeon / Kalpa** | `transactional-update` | zypper | Flatpak | distrobox | tumbleweed-ish |
| **Vanilla OS** | ABRoot + `apx` | apt (in containers) | Flatpak | apx/distrobox | own |
| **NixOS** | declarative `configuration.nix` | nix | — | nix | own |

**Scope decision:** target the **rpm-ostree family first** (that's Bazzite + the biggest cluster,
and uBlue has clear, consistent guidance). openSUSE MicroOS is a close cousin (snapshot + reboot
over zypper) — a second driver on the same pattern, later. **Vanilla OS (apx)** and **NixOS**
(declarative, not imperative-install) are different enough to stay out; NixOS in particular does
not fit configsys's imperative install-driven model at all.

## The core problem: `native:` assumes a mutable package manager

On an atomic box there are *three* install paths with a strong preference order that uBlue itself
publishes:

1. **Flatpak** for GUI apps (Flathub is pre-configured).
2. **Homebrew (`brew`)** for CLI tools (shipped and blessed on Bluefin/Bazzite/Aurora).
3. **`rpm-ostree` layering** only as a last resort — kernel modules, hardware enablement,
   system integration. Layering is reboot-gated and bloats every future deployment, so you avoid
   it for anything available as a flatpak or brew formula.

So the wrong move is `native: rpm-ostree` (routes *everything* through layering). The right move
is to model atomic as a **distinct environment** whose `native` is **brew**, with flatpak for
apps (components already carry those bindings) and rpm-ostree as an *explicit, rare* `via:`.

## The key insight — no new resolver semantics needed

The tempting-but-heavy path is a "driver-preference policy" (let the OS declare
`prefer: [flatpak, brew, rpm-ostree]` and have the resolver disambiguate by it). That would
change resolution from "most-specific `when:` wins" to a preference tiebreak — a real semantic
change, and it doesn't even help the common case (a CLI tool with a *single* `via: native`
binding still has nothing to prefer *between*).

Instead: **make atomic its own OS environment, and existing binding selection just works.**

- Atomic blocks hang off **`glibc_linux`** (a clean glibc environment), **not** `fedora`. So the
  dnf-specific bindings guarded `when: fedora` / `when: rhel` (EPEL, RPM Fusion, `repo-component`,
  `enable-repo`) simply **don't match** — which is correct, because brew doesn't need any of them.
- They declare **`native: brew`**. Every existing plain `via: native` CLI component (btop,
  ripgrep, tcpdump, nmap, jq, socat, …) resolves to `brew install <name>` unchanged — brew's
  formula set covers essentially all of them.
- **Flatpak** app bindings (browsers, GUI clients, discord/slack, gimp/krita/…) are already
  unconditional or Flathub-based → unchanged.
- A new **`rpm-ostree`** driver serves *explicit* `via: rpm-ostree` bindings (guarded to atomic)
  for the genuine layering cases.

Because atomic is outside the redhat subtree, `ffmpeg`'s `when: redhat requires: rpmfusion`
binding won't fire on Bazzite; it falls to the generic `via: native` → `brew install ffmpeg`
(fully-featured, no RPM Fusion needed). That's the model working *with* the grain.

## What gets built

### 1. `brew` driver (Homebrew) — high value, reusable beyond atomic
Full op set maps cleanly, and this **also unblocks macOS** (currently parked) since Homebrew is
the same tool there:

| op | command |
|---|---|
| get_version | `brew list --versions <f>` |
| get_latest | `brew info --json=v2 <f>` → `versions.stable` |
| is_locked | `brew list --pinned` contains `<f>` |
| install | `brew install <f>` |
| uninstall | `brew uninstall <f>` |
| upgrade | `brew upgrade <f>` |
| set_version | brew is latest-only; pin-after-install (document the limitation) |
| lock / unlock | `brew pin` / `brew unpin` |
| location | `brew --prefix <f>` |

`privileged = False`, `default_scope = user` (brew is per-prefix, no sudo). Name maps key on
`brew:` where a formula name differs.

### 2. `rpm-ostree` driver — explicit layering only
| op | command |
|---|---|
| get_version | `rpm -q <pkg>` (merged view is queryable read-only) |
| get_installed | layered set from `rpm-ostree status --json` (`deployments[0].packages`) |
| get_latest | **image-managed** — no live repo metadata on ostree; report "managed by image" / unknown rather than fake a value |
| install | `rpm-ostree install -y <pkg>` — **stages for next boot** (rpm-ostree's own always-correct default); a binding may set `apply-live: true` to also apply to the running deployment now |
| uninstall | `rpm-ostree uninstall <pkg>` |
| upgrade | per-package upgrade isn't a thing; layered pkgs move with `rpm-ostree upgrade` (whole system) — treat as no-op/whole-system |
| lock/unlock | n/a (image-pinned) |

`privileged = True`. **Reboot messaging is first-class**: install must tell the user it's staged
and how to activate (`systemctl reboot`, or the `--apply-live` we ran).

### 3. OS blocks — DONE (one block, not per-image)
Research (ublue-os/bazzite#1249) killed the per-image plan: Silverblue/Kinoite report
`ID=fedora` + `VARIANT_ID=silverblue|kinoite`, and the uBlue images (Bazzite/Bluefin/Aurora)
report `ID=fedora` with `VARIANT_ID` = *fedora or kinoite* — they do **not** cleanly
self-identify, and their routing is identical anyway. So there is **one** block:
```hu
fedora_atomic: { using: glibc_linux  native: brew  provides: flatpak  scale-root: true }
```
`provides: flatpak` (pre-installed → an app's flatpak dep is env-satisfied, not `brew install
flatpak`). `scale-root` so it owns its Fedora-tracking VERSION_ID without inheriting fedora's dnf
version line. osdetect folds every variant in: `ID=fedora` (or fedora in ID_LIKE) **and** either
an atomic `VARIANT_ID` **or** the `/run/ostree-booted` marker (the robust catch-all for uBlue
images whose VARIANT_ID is just `fedora`). `--os` forcing bypasses the remap. Verified:
`btop→brew\btop`, `chrome→flatpak\chrome` (no brew\flatpak), `ffmpeg→brew\ffmpeg` (no RPM Fusion),
plain `fedora` unchanged. Finer per-image identity (bazzite vs bluefin, via PRETTY_NAME/package
probe) is deferred — nothing routes on it yet.

## Open decisions (need a call before building)

- **D1 — env vs inherit-fedora.** Recommended: atomic hangs off `glibc_linux` with `native: brew`
  (clean; dnf-specific bindings correctly don't apply). Alternative: `using: fedora` and fight the
  RPM Fusion/EPEL clashes. **Rec: glibc_linux + brew.**
- **D2 — macOS scope.** The `brew` driver is 90% of macOS support. Build brew now with Linux+macOS
  in mind (even if we don't add a `macos` OS block yet)? **Rec: yes — design it cross-platform.**
- **D3 — component audit.** A few components have *only* an apt/dnf-specific route with no generic
  fallback (e.g. `vscode` = Microsoft apt repo; brew Linux has no casks). Those need an explicit
  atomic binding (flatpak `com.visualstudio.code`, or `via: rpm-ostree`). Need a sweep to list them.
- **D4 — `get_latest` on rpm-ostree.** Honest "image-managed/unknown" vs. trying to query dnf
  metadata offline. **Rec: honest unknown** (no surprises beats a fabricated version).
- **D5 — `--apply-live` default.** *Resolved during step 2:* **stage-for-next-boot is the default**
  (rpm-ostree's own always-correct behavior), with **`apply-live: true` as an opt-in binding field**.
  This is more honest than "attempt live, fall back to reboot": the cases rpm-ostree layering is
  *for* (kernel modules, hardware) are exactly where `--apply-live` is unsafe, and a fallback that
  guesses whether it applied risks mis-messaging. Opt-in keeps live-apply to the userspace packages
  where it's actually safe.

## Rollout sketch

1. `brew` driver + tests (mocked runner), registered. *Independently shippable* — usable on any
   Linux with Homebrew, and the macOS foundation.
2. `rpm-ostree` driver + tests (reboot/apply-live messaging, image-managed latest).
3. `glibc_atomic` + the Fedora Atomic / uBlue blocks; osdetect IDs verified against real images.
4. Component audit (D3): add atomic bindings where a component has no brew/flatpak path.
5. Container validation where possible (a Bazzite/Silverblue image in podman for read-only
   query paths; layering/reboot can only be smoke-tested).

Related: [[routing-model.md]] (binding selection this leans on), the `native:`-per-OS mechanism,
and the parked macOS/brew note.
