# Deferred sweep work (2026-08-08)

Batch task: add C++ libs; sweep flatpak / snap / tarball / native-pkg-file / appImage methods so
users get "full options and control." Done offline (no network to verify app IDs / snap names /
release asset URLs), so this file collects what still needs a networked pass. **Verify each item
before integrating** — the notes are transcribed from training knowledge.

## Already shipped (committed)
- **C++ libs** (`routes.hu`): `boost`, `abseil`, `qt` (Qt6), `gtk` (GTK4), `gtkmm` (native,
  debian/redhat/arch/alpine); `folly` (Fedora native + Arch AUR); `eastl` (Arch AUR).
- **Flatpak** (`routes.hu`): added to `emacs` (org.gnu.emacs), `octave` (org.octave.Octave),
  `zed` (dev.zed.Zed). Skipped `wireshark` (its comment bars flatpak — sandbox can't live-capture).
- **Snap driver** (`configsys/drivers/snap.py`): built + registered + unit-tested. **Bindings NOT
  added** — see the snap section below.

---

## 1. Snap bindings — RESOLVED (candidate-only driver flag + verified bindings shipped)
The "snap gated `when: ubuntu` becomes the Ubuntu default by specificity" problem is fixed by a
**driver-level `candidate-only` flag** (`drivers: { snap: { candidate-only: true } }`): a snap
binding is valid + listed in the picker + pinnable, but never the auto-default while any ordinary
method is valid (native/flatpak keep the Ubuntu default). A binding-pin still forces it; if snap is
the *only* method (chromium on Ubuntu) it wins. See docs/routing-model.md §8a. Overlaid repo→plugin→
primary, so your configsys-user primary can add `flatpak: { candidate-only: true }` the same way.

Shipped snap bindings (names verified on snapcraft.io): vscode (`code`, classic), slack, discord,
postman, obs-studio, blender (classic), node (classic), kubectl (classic), helm (classic), firefox,
chromium, and a new **spotify** component (Flathub `com.spotify.Client` + `spotify` snap). Golden
proved ZERO default flips from these (candidate-only). `gh` snap SKIPPED — it's community, not
official GitHub. Remaining snap candidates if wanted (all verified official/Canonical): a `code`-vs-
native question is moot now; could still add snaps for more apps, but they'd all be candidate-only.

## 2. Binary-release sweep (tarball / native-pkg-file / appImage) — VERIFY URLs/assets then add
From an offline research pass. `H` = confident about repo + asset shape; `M` = repo known, asset
pattern needs checking. Study the existing `via: tarball` / `via: native-pkg-file` / `via: appImage`
bindings in routes.hu for the exact field syntax (`version: { github: owner/repo  strip-v:  asset: }`,
`installDir`, `archive`, `binary`, `requires`, etc.).

### tarball (prebuilt binary from a GitHub release)
| comp | repo | conf | asset / notes |
| --- | --- | --- | --- |
| ripgrep | BurntSushi/ripgrep | H | `ripgrep-*-x86_64-unknown-linux-musl.tar.gz` (rg in a subdir, strip 1). native-only now. |
| fzf | junegunn/fzf | H | `fzf-*-linux_amd64.tar.gz`, strip-v; single `fzf`. native-only now. |
| btop | aristocratos/btop | H | `btop-x86_64-linux-musl.tbz` (bzip2 tar; `btop/bin/btop`). native-only now. |
| xh | ducaale/xh | H | `xh-v*-x86_64-unknown-linux-musl.tar.gz`; `xh`. cargo-only now. |
| ollama | ollama/ollama | H | `ollama-linux-amd64.tgz` (bin/ + lib/). native,script now. |
| tree-sitter-cli | tree-sitter/tree-sitter | H | `tree-sitter-linux-x64.gz` (gzipped single binary → rename `tree-sitter`). cargo-only now. |
| protobuf | protocolbuffers/protobuf | H | `protoc-*-linux-x86_64.zip`, strip-v; `bin/protoc` + `include/`. native-only now. |
| jq | jqlang/jq | H | asset `jq-linux-amd64` (raw binary, archive:none, binary:jq). Tags are `jq-*` not `v*` → strip `jq-`, not strip-v. |
| websocat | vi/websocat | M | raw binary `websocat.x86_64-unknown-linux-musl` (rename `websocat`); naming varies by release. cargo-only now. |
| zed | zed-industries/zed | M | `zed-linux-x86_64.tar.gz` (ships zed.app tree) — verify layout. has flatpak+script. |
| k3s | k3s-io/k3s | M | raw binary asset `k3s`, archive:none. has script now. |
| godot | godotengine/godot | M | `Godot_v*-stable_linux.x86_64.zip`; tag form `4.x-stable` needs custom version handling. flatpak-only now. |

### native-pkg-file (.deb/.rpm on a GitHub release)
| comp | repo | conf | asset |
| --- | --- | --- | --- |
| insomnia | Kong/insomnia | M | `Insomnia.Core-*.deb` / `.rpm` (also ships .AppImage). flatpak-only now. |
| dbeaver | dbeaver/dbeaver | M | `dbeaver-ce_*_amd64.deb` / `dbeaver-ce-*.x86_64.rpm`. flatpak-only now. |
| bruno | usebruno/bruno | M | `bruno_*_amd64_linux.deb` / `.rpm`. flatpak-only now. |

### appImage
| comp | repo/source | conf | asset |
| --- | --- | --- | --- |
| musescore | musescore/MuseScore | M | `MuseScore-Studio-*-x86_64.AppImage` (needs libfuse2). flatpak-only now. |
| freecad | FreeCAD/FreeCAD | M | `FreeCAD_*-Linux-x86_64-*.AppImage`. flatpak-only now. |
| openscad | openscad/openscad or files.openscad.org | M | `OpenSCAD-*-x86_64.AppImage` (stable assets may be on files.openscad.org, not GH). flatpak-only now. |

### deferred by the researcher (vendor-URL-only / capability generic / no GH assets)
node (nodejs.org/dist), jdk (Adoptium per-major repos + generic capability), maven (dlcdn.apache.org),
gradle (services.gradle.org), vscode .deb (vendor redirect), discord/slack/postman .deb (rolling
vendor URLs, no versioned tag), virtualbox (Oracle per-distro matrix), krita/inkscape/obs-studio
AppImages (KDE/GitLab/PPA, not upstream GH), awscli (installer zip + ./install), gcloud/helm (vendor
storage). Each needs a bespoke `url:` (not GH `version:` discovery) or is fine as-is.

## 3. Flatpak deferred (GUI apps, exact Flathub ID unconfirmed)
arduino (cc.arduino.IDE2?), ghostty (com.mitchellh.ghostty?), gnuradio (org.gnuradio.GNURadio?),
paraview (org.paraview.ParaView?), qjackctl (org.rncbc.qjackctl?), supercollider (?), virt-manager
(needs system libvirt; Flathub presence uncertain), wxmaxima (?). Confirm the reverse-DNS IDs on
Flathub, then add `{ via: flatpak  hub: flathub  app: <ID> }`.

## 4. C++ lib coverage gaps
- **boost/abseil/qt/gtk/gtkmm**: native names are gated to debian/redhat/arch/alpine. Add
  **openSUSE** names (its dev packages are split/renamed — e.g. `libqt6-qtbase-devel`,
  `libboost_headers-devel`) and **brew** (macOS/atomic: `boost`, `qt`, `gtk4`, …) once verified.
- **gtkmm** currently skips alpine (name unconfirmed — `gtkmm4-dev`?). **folly** on Debian/Ubuntu/
  Alpine/openSUSE and **eastl** everywhere but Arch have no repo package → a `via: source` recipe
  (github facebook/folly, electronicarts/EASTL) in configsys-source or a bespoke plugin.

## 5. Desktop environments / window managers
Added natively (commit): i3, qtile, xmonad, fvwm2. Still deferred:
- **pantheon** — elementary OS's desktop is hard to install cleanly outside elementary (no tidy
  metapackage on Debian/Fedora; Arch has it via AUR `pantheon-*`, elementary via its own repos).
  Needs a per-distro decision (AUR on Arch? a `pantheon-session`/`pantheon-shell` metapackage that
  actually exists?) before adding. Verify package names first.
- **fvwm2** naming: shipped gated to debian/arch (their `fvwm` is the 2.x line). Fedora/openSUSE/
  Alpine ship the 3.x line as `fvwm3` (or nothing) — add those with the right name if wanted.

## 6. Homebrew (brew) sweep — VERIFY formula/cask names then add to native `name:` maps
Brew is configsys's native package manager on **fedora_atomic** (and a future macOS block), so a
component's brew coverage is a `brew: <formula>` entry in its `via: native` `name:` map (see
rust/node/openjdk/r/dig for the shape). Casks (GUI apps) install with `--cask`. Proposals below were
researched offline — verify each formula/cask name exists before adding.

### What the sweep actually found (two structural facts changed the plan)
1. **formula == component name → already works, no edit.** On fedora_atomic a `via: native` binding
   with no name map installs the *component name*, which for ~66 of the researched formulae (git,
   curl, jq, ripgrep, go, htop, neovim, podman, helm, …) IS the brew formula. These resolve to
   `brew\<comp>` today wherever their native binding reaches fedora_atomic — nothing to add.
   Likewise `haskell` (`default: ghc`) and `cabal` (`default: cabal-install`) already install the
   right brew formula via their existing `default:` names.
2. **Linux Homebrew has no casks.** Every cask the researcher listed (firefox, vlc, gimp, krita,
   blender, vscode, kitty, ghostty, zed, steam, libreoffice, virtualbox, wireshark-GUI, paraview…)
   is **macOS-only**. They are inert on fedora_atomic (the only current brew OS). Revisit ALL casks
   only when/if a `macos`/`darwin` OS block is added — then they'd need a `cask: true` field + the
   brew driver learning `--cask`. Parked entirely until then.

### Integrated this pass (committed) — added a `{ via: native  when: "fedora_atomic" }` binding to
components that had a real brew formula but whose native binding **didn't reach fedora_atomic** (so
they declined there entirely — the nushell/yazi pattern): **erlang, nim, maxima, gap, supercollider,
opencv (`name: opencv`), texlive (`name: texlive`), mariadb (`name: mariadb`, not the distro
`-server` split).** All verified to resolve to `brew\<comp>` on fedora_atomic. (The golden gate
doesn't cover fedora_atomic, so these are resolve-verified, not golden-locked — see note below.)

### Deferred (verify a name/policy before adding)
- **redis** — its Linux binding installs `valkey` (dnf/pacman) post-relicense, `redis-server` (apt).
  Brew has both `redis` and `valkey` formulae. Pick the policy (match component identity `redis`, or
  stay consistent with the Linux `valkey` lean) then add a fedora_atomic binding.
- **kubectl** — resolves to `brew install kubectl` (a stable Homebrew alias for `kubernetes-cli`);
  works as-is, optionally pin `name: kubernetes-cli` for explicitness.
- Researcher's **DEFER** list (unconfirmed/removed/versioned formula names — verify before adding a
  fedora_atomic binding): `postgresql` (brew ships versioned `postgresql@16` etc., bare is deprecated
  — pick a version), `julia`/`odin` (formula-vs-cask/existence unsure), `p7zip`→`7-zip`/`sevenzip`
  (renamed), `unrar` (removed then re-added — confirm), `bun` (in the `oven-sh/bun` tap, not core),
  `clang-tidy`/`lldb`/`tshark` (ship *inside* `llvm`/`wireshark`, no standalone formula), `strace`
  (Linuxbrew-only), `virt-manager`/`qjackctl`/`traceroute` (formula existence unsure),
  `texlive-full`/`opencv-python` (brew's single `texlive`/`opencv` bundles them — no `-full`/`-python`).
- **M-confidence formulae the researcher flagged** (name likely right, double-check): valgrind, iftop,
  nethogs, nload, vnstat, mtr, netcat, wxmaxima. Most already resolve via `default:` where their
  native binding reaches fedora_atomic; only add a fedora_atomic binding if they currently decline.

### Suggested follow-up: add `('fedora_atomic', '41')` to the golden matrix (`test/test_golden.py`
`CONTEXTS`) so brew resolution is regression-locked like the other OSes. Deferred here because it's a
large one-time golden diff (301 components × a new context) and is a gate-policy call for you.
