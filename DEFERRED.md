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

## 1. Snap bindings — DECISION NEEDED (driver is ready)
A snap binding must be gated `when: ubuntu` for validity. But that makes it **more specific** than
the broader `native`/`flatpak` bindings, so the resolver's "most-specific `when:` wins before
driver-preference" rule makes **snap the Ubuntu DEFAULT**, not just an option. e.g. `vscode` would
flip from the Microsoft apt repo to the `code` snap. Given your ambivalence about snaps, this is a
call for you:

- **(A)** Accept snap-as-Ubuntu-default for components that have a good snap (add the bindings).
- **(B)** Only add snap where you actually want it to win on Ubuntu (curated, deliberate).
- **(C)** Ship the driver only; users add snap bindings per-machine / via a pin.

Candidate bindings I had queued (all famous snaps; add `classic: true` only where noted):
```
vscode      { via: snap  when: "ubuntu"  name: code  classic: true }   // MS official (classic)
slack       { via: snap  when: "ubuntu"  name: slack }
discord     { via: snap  when: "ubuntu"  name: discord }
postman     { via: snap  when: "ubuntu"  name: postman }
obs-studio  { via: snap  when: "ubuntu"  name: obs-studio }
blender     { via: snap  when: "ubuntu"  name: blender }
```
A fuller sweep (node, gh, kubectl, helm, chromium, spotify [not yet a component], …) waits on the
same decision + name verification.

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
