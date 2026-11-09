# Trust gate at resolution (review-2026-11-2 A1)

> **Status: DONE** — finished 2026-11-08. Lives on in: docs/plugins.md §6, configsys/trustgate.py

## Why

The 2026-09 A1 fix made `script` / `source` / `glue` refuse their ops from an untrusted plugin, but
every other way a plugin layer could run, download, place or privilege something stayed open: apt
`ppa:` / `source-line:` / `pubkey-*` and dnf `repo-*` ran as root, `native-pkg-file` installed an
arbitrary `.deb`, tarballs and AppImages downloaded and placed plugin-chosen bytes (the AppImage was
even executed as root to extract an icon), dotfiles templates could land in `~/.zshenv`, a
`version: { url: }` was fetched at inspect time (with `file://` and the GitHub token), and install
receipts dropped the binding's source so a removed plugin's script still ran as trusted. The docs
promised all of this was refused until trust (review-2026-11-2 security-01/02/04/06/07, plugins-01/05,
drivers-os-01, drivers-lang-04/05, dotfiles-glue-21, actions-07, subsystems-04, config-layers-04).

## Decisions (the user, 2026-11-08)

- Gate **every** command / privileged-write / download binding from an untrusted layer — downloads
  are not "inert". Severity CRITICAL.
- The primary plugin's trust is a top-config setting, `primary-trust: identity | content | signed`,
  default `identity`.
- Keys stay rebindable, but a plugin's `keys:` count only once the plugin is trusted (A11).

## What was built

1. **One gate at resolution** (`configsys/trustgate.py`). `routes.load` records the untrusted plugin
   layer files on the cascade; every context carries them; `resolve._matching` drops a binding from
   such a file unless its driver is a `trusted_registry` (a package by name from distro repos,
   Flathub, the Snap Store, Homebrew core) and it sets none of the driver's `command_fields` and no
   `version: { url: }`. `where` and the "no binding here" error name the reason and the remedy.
   `trusted_registry` / `command_fields` are new frozen Driver attributes (default: needs trust).
2. **Defense in depth.** `run_plan` refuses a step whose binding is from an untrusted layer and needs
   trust (a replayed receipt, a hand-built plan). Receipts record their binding's source.
3. **Trustable.** `ships_executable_data` counts every gated binding, shipped `dotfiles/` / `glue/`
   trees and `keys:`, so `plugin trust` always accepts what the gate refuses.
4. **Primary trust** setting (`plugins.command_source_trusted` → `primary_trust_mode`, `_head_signed`).
5. **Keys** (`Config.key_layers`): an untrusted plugin's `keys:` are left out; `check` says so.
6. **Containment.** apt `pubkey-path` / `source-path` / `apt-source: key-path/list` must sit directly in
   apt's keyring / sources dirs and a dnf `repo-id` is a plain name (routecheck error + driver check);
   a plugin's `code:` / `data:` entry (or symlinked data file) that resolves outside its checkout is
   never loaded; the content hash is length-prefixed and hashes symlinks as links (F1 — an approval or pin
   recorded in the old format still matches the same content, `plugins.legacy_identity`); the AppImage icon extraction never runs under sudo and copies only a
   `.DirIcon` inside the extracted tree.
7. **Version fetches** are https-only (no `file://`, no plaintext), and the GitHub token goes only to
   `api.github.com` (it used to go to any URL containing that string).
8. **Asset checksums** (2026-09 A7): an optional `sha256:` on tarball / AppImage / font /
   native-pkg-file bindings (scalar, or a map by cpu / package format), verified right after the
   download (`Driver.expected_sha256` / `verify_download`, frozen).

Tests: `test/test_trust_gate.py` (the gate, the reasons, trust opening it, the primary modes, run_plan's
re-check, receipts, keys, identity, containment, vendor paths), `test_versions.py`, `test_tarball.py`,
`test_appimage.py`. A mutation check (gate disabled) fails 12 of the gate tests.
