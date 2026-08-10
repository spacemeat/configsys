# Deferred sweep work (2026-08-08)

> **POLICY REVERSED 2026-08-10:** the "minimize install options" stance below is dropped — the goal
> is now **full choice**: offer EVERY valid method per component (native stays the default where the
> distro packages it; extras are candidates you can pin). Network verification is now available
> (flathub/snapcraft/GitHub APIs), so adds are verified, not guessed. Progress this pass:
> - Atomic-gated flatpaks made universal: firefox/libreoffice/vlc/blender/vscode + chromium (2b7777f).
> - Over-narrow binaries broadened: just (5105301), helix/kubectl (55d0b86).
> - Flathub-verified sweep of all 251 no-flatpak components → added android-studio/unityhub/mitmproxy
>   (9a81e5b, official build kept default via prefer:). Flatpak catalog COMPLETE. wireshark corrected
>   (52707ee — it's the only GUI on atomic). Skipped: httpie (Flathub = a different product).
> - nushell musl tarball for Alpine (2bfce89). Coverage holes analyzed: mainstream complete, rest by-design.
> - NEW PRIMITIVE: per-binding `candidate-only: true` (b96cb45) — a validity-gated method offered
>   without beating a universal one by specificity. Used for discord's rolling .deb.
> - Vendor-repo native (all verified live): chrome (8209ba8), brave/opera/vivaldi/edge (ee78047),
>   slack (6810ef5) — each wires its official apt+dnf repo (+ AUR / Arch extra), native default there,
>   flatpak candidate + openSUSE/atomic default. discord's rolling .deb (56b664d) as a candidate-only.
> - snapd component + snaps offered on every distro (589d8e2): snapd/snapd-socket/snapd-snap-link,
>   snap driver `requires` them, the 12 snaps de-gated (candidate-only everywhere).
>
> **The full-choice sweep is essentially DONE.** Genuinely remaining (lower value / needs a real box):
> - snapd socket-enable + /snap symlink UNVALIDATED on real Fedora/Arch (needs a VM — snapd can't run
>   cleanly in the container harness).
> - brew casks (parked until a macOS OS block — mac-only); folly/eastl `source` recipes; openscad's
>   non-GitHub URL; per-binding review of the `prefer:` methods (android-studio/unityhub/mitmproxy).


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

## 2. Binary-release sweep — MOSTLY SHIPPED (globs live-validated against GitHub)
**INTEGRATED (14 components, every asset glob confirmed to match a current release asset):**
tarball → ripgrep, fzf, btop, jq (raw), protobuf, xh*, websocat* (raw), ollama†, zed, k3s (kept
script default via `prefer:` — the get.k3s.io script sets up the systemd service; tarball is the
bare-binary option); native-pkg-file (.deb+.rpm in one binding) → dbeaver, bruno; appImage →
musescore, freecad. (* xh/websocat default flipped cargo→tarball as you OK'd. † ollama default
flipped script→tarball — the tarball is userland, consistent with configsys avoiding curl|sudo
scripts. dbeaver/bruno default flatpak→native-pkg-file on debian/redhat: their `.deb`/`.rpm` binding
is `when:`-gated so it wins by specificity — a sensible native default for a DB GUI; flatpak stays
the default on arch/atomic and remains a listed option everywhere.)

**STILL DEFERRED (1, with the specific blocker):**
- ~~tree-sitter-cli~~ **DONE** — `archive: gz` mode on the tarball driver (gunzip a single compressed
  binary; distinct from `.tar.gz`). Offers it but KEEPS cargo default via `prefer: 1`.
- ~~insomnia, godot~~ **DONE** — `discover_asset_url` now scans recent releases (not just
  `releases/latest`) for one whose assets match the glob, so monorepo `core@` tags and RC-latest
  repos resolve; a new `tag-re:` extracts a clean version (`core@13.1.0`→`13.1.0`, `4.7.1-stable`→
  `4.7.1`). insomnia = .deb/.rpm (default on debian/redhat, flatpak elsewhere); godot = tarball
  option (flatpak stays default; the zip holds a single `Godot_v<ver>_linux.x86_64` exe).
- **openscad** — GitHub "latest" is the stale 2021.01; current nightlies live on files.openscad.org
  (not GitHub), so no GH `version:` discovery works. Needs a bespoke non-GH `url:`. Left flatpak-only.

--- original research notes (asset facts now folded into the shipped bindings) ---
**Asset names below were confirmed on the actual GitHub releases (2026-08-08 networked pass).**
Study existing `via: tarball` / `via: native-pkg-file` / `via: appImage` bindings for field syntax
(`version: { github: owner/repo  strip-v:  asset: }`, `installDir`, `archive`, `binary`, `requires`).

**ONE JUDGMENT CALL before authoring:** for components currently **cargo-only** (xh, tree-sitter-cli,
websocat), adding a tarball binding FLIPS their default cargo→tarball (cargo isn't in the driver-
preference list, so it's least-preferred; tarball outranks it). That's arguably better (prebuilt vs
build-from-source), but it IS a default change — decide whether to accept it or add `prefer:`/keep
cargo. native-only (ripgrep/fzf/btop/protobuf/jq/ollama) and flatpak-only (godot/insomnia/dbeaver/
bruno/musescore/freecad/openscad) components keep their current default; the binary method is just an
added option, so those are pure wins with no flip.

**Verified asset facts (corrections in bold — several drifted from the old offline guesses):**
- ripgrep BurntSushi/ripgrep — tag `15.2.0` (no v) — `ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz`, bin at `<name>/rg` (versioned subdir, strip 1)
- fzf junegunn/fzf — tag `v0.74.2` (**asset uses bare `0.74.2`**) — `fzf-0.74.2-linux_amd64.tar.gz`, single `fzf` at root
- btop aristocratos/btop — tag `v1.4.7` — **`btop-x86_64-unknown-linux-musl.tar.gz` (NOT the old `.tbz`; no version in name)**, `btop/bin/btop`
- xh ducaale/xh — tag `v0.26.2` — `xh-v0.26.2-x86_64-unknown-linux-musl.tar.gz`, `xh-v.../xh`
- ollama ollama/ollama — tag `v0.32.6` — **`ollama-linux-amd64.tar.zst` (CHANGED from `.tgz`; zstd)**, `bin/ollama`+`lib/ollama`
- tree-sitter tree-sitter/tree-sitter — tag `v0.26.12` — `tree-sitter-linux-x64.gz` (plain gzip single ELF; gunzip→rename)
- protobuf protocolbuffers/protobuf — tag `v35.1` (asset bare `35.1`) — `protoc-35.1-linux-x86_64.zip`, `bin/protoc`+`include/`
- jq jqlang/jq — tag **`jq-1.8.2` (strip `jq-`, not v)** — `jq-linux-amd64` raw ELF, archive:none, rename jq
- websocat vi/websocat — tag `v1.14.1` — `websocat.x86_64-unknown-linux-musl` raw, rename websocat
- zed zed-industries/zed — tag `v1.14.2` — `zed-linux-x86_64.tar.gz` → `zed.app/bin/zed` bundle
- k3s k3s-io/k3s — tag `v1.36.3+k3s1` (**URL-encode the `+` as `%2B`**) — raw `k3s`, archive:none
- godot godotengine/godot — tag `4.7.1-stable` (no v; **asset carries a v**) — `Godot_v4.7.1-stable_linux.x86_64.zip`, single exe
- insomnia Kong/insomnia — tag **`core@13.1.0` (parse version out of the monorepo tag)** — `Insomnia.Core-13.1.0.deb`/`.rpm`
- dbeaver dbeaver/dbeaver — tag `26.1.4` — `dbeaver-ce-26.1.4-linux-x86_64.deb`/`.rpm`
- bruno usebruno/bruno — tag `v4.0.0` — `bruno_4.0.0_amd64_linux.deb` / `bruno_4.0.0_x86_64_linux.rpm` (**deb=amd64, rpm=x86_64**)
- musescore musescore/MuseScore — tag `v4.7.4` — **`MuseScore-Studio-4.7.4.260706075-x86_64.AppImage` (build suffix NOT derivable from the tag — must SCRAPE the asset name, can't template)**
- freecad FreeCAD/FreeCAD — tag `1.1.3` — `FreeCAD_1.1.3-Linux-x86_64-py311.AppImage` (**`py311` token varies per release**)
- openscad — **GitHub "latest" is the old 2021.01 stable; current nightlies live at files.openscad.org, NOT GitHub** → needs a `url:`-based (non-GH) binding or leave flatpak-only

(Original H/M tables below retained for the repo/binary-layout notes.)

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

## 3. Flatpak — RESOLVED (networked pass)
**ADDED (IDs confirmed on flathub.org):** arduino (cc.arduino.IDE2), paraview (org.paraview.ParaView),
virt-manager (org.virt_manager.virt-manager), wxmaxima (io.github.wxmaxima_developers.wxMaxima).
**NOT on Flathub (confirmed 404) — leave as-is:** ghostty, gnuradio, qjackctl, supercollider (these
distribute via their own sites / community third-party Flatpaks, not the official Flathub remote).

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
