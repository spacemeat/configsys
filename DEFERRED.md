> **Status: REFERENCE** — the deferred-work list; reviewed 2026-10-09.

# Deferred work (method sweeps, 2026-08-08 onward)

Started as the 2026-08-08 batch: add C++ libs; sweep flatpak / snap / tarball / native-pkg-file /
appImage methods so users get "full options and control." That pass was offline, so this file
collected what needed a networked check. Later passes verified most of it against the live
flathub / snapcraft / GitHub / formulae.brew.sh APIs. The 2026-10-09 review checked every item
against routes.hu, the drivers, the tests and git history. Each item is now in one of three places:
**Still deferred** (below, facts refreshed), **Done since deferral**, or **Dropped**. **Verify any
upstream name before integrating** — names that haven't been verified came from training knowledge.

> **POLICY REVERSED 2026-08-10:** the original "minimize install options" stance is dropped
> (see Dropped). The goal is **full choice**: offer EVERY valid method per component. Native stays
> the default where the distro packages it, and the extras are candidates you can pin. The
> full-choice sweep is essentially DONE; its log is under Done since deferral.

---

## Still deferred

### Needs a real box
- **snapd setup UNVALIDATED on real Fedora/Arch.** The snap driver `requires: [snapd-socket,
  snapd-snap-link]` (enable `snapd.socket` via the `service` driver; the `/snap` →
  `/var/lib/snapd/snap` symlink via `script`). It is a no-op on Ubuntu but untested on Fedora/Arch,
  because snapd can't run cleanly in the container harness. Needs a VM.

### Parked until a macOS OS block exists
- **brew casks.** Linux Homebrew has no casks, so every GUI cask the researcher listed (firefox, vlc,
  gimp, krita, blender, vscode, kitty, ghostty, zed, steam, libreoffice, virtualbox, wireshark-GUI,
  paraview, …) is macOS-only. Today `brew` is the declared `native:` only on `fedora_atomic`; on
  every other glibc distro it is an ordinary `via: brew` method (ec59455), formulae too.
  `configsys/drivers/brew.py` is formulae-only; casks are a future `cask:` field (the driver's op
  structure is already cask-ready). Revisit ALL casks only when a `macos`/`darwin` OS block is added.

### Low-value method additions
- **openscad upstream binary.** It's now native (base repos + EPEL, de00d7d) with Flathub as the
  fallback, so it is no longer flatpak-only. Upstream's GitHub "latest" is the stale 2021.01, and
  current builds live on files.openscad.org, so GitHub `version:` discovery can't find them. The
  non-GitHub `version: { url: }` source kind now exists (kubectl's tarball uses it), so an AppImage
  binding is unblocked. It just isn't worth much now that native exists.
- **Vendor-URL-only methods the researcher set aside** (no GitHub release assets; each would need
  a bespoke `url:` or is fine as-is): node (nodejs.org/dist tarball; has native + snap today), jdk
  (Adoptium per-major repos + the generic capability; native today), maven/gradle (dlcdn.apache.org /
  services.gradle.org; both have native + `sdkman` today), postman (rolling .deb; flatpak + snap
  today), obs-studio AppImage (not upstream GitHub; flatpak + snap today), awscli/gcloud (vendor
  installers; both are `script` today). See Done for the ones that got covered another way.
- **Per-binding review of the `standing: 1` defaults** added when Flathub methods arrived (9a81e5b):
  android-studio (Google's tarball over the community flatpak), unityhub (Unity's vendor apt repo;
  the public AppImage was retired, 5253afe), mitmproxy (pipx from PyPI over the flatpak; pinned to
  python3.13 on debian, 1493dbc). Each `standing: 1` still holds. The open question is only whether
  each is still the right default.

### C++ lib coverage gaps
- **boost / abseil / qt / gtk / gtkmm** are gated to debian/redhat/arch/alpine/void (qt and gtkmm
  exclude amzn). Still missing:
  - **openSUSE** names. Its dev packages are split/renamed (e.g. `libqt6-qtbase-devel`,
    `libboost_headers-devel`), and none of the five carries a `zypper:` name yet.
  - **brew** (`boost`, `abseil`, `qt`, `gtk4`, `gtkmm4`). All five still decline on fedora_atomic.
    The names are verified: each is a homebrew/core formula with a Linux bottle, not keg-only
    (formulae.brew.sh index, 2026-10-10). Add `{ via: native  when: "fedora_atomic" }` bindings
    with those names — libraries get no `via: brew` binding elsewhere (the add-component rule).
  - **gtkmm on alpine** (name unconfirmed, possibly `gtkmm4-dev`).

### Desktop environments / window managers
- **pantheon** — elementary OS's desktop is hard to install cleanly outside elementary. Debian and
  Fedora have no tidy metapackage. Arch has the AUR `pantheon-*` packages, and elementary has its own
  repos. The `elementary` OS block (`using: ubuntu`, 5c99ccd) now exists as its natural home. Still
  needs a per-distro decision (AUR on Arch? a `pantheon-session`/`pantheon-shell` metapackage that
  actually exists?) and verified names before adding.
- **fvwm3** — `fvwm2` is now gated to `debian or void or void_musl` (name `fvwm`). Arch was dropped
  in 03fa9b2 because it ships only the 3.x line. Fedora/openSUSE/Alpine/Arch carry 3.x as `fvwm3`
  (or nothing). No `fvwm3` component exists. Add it as its own component if wanted.

### Homebrew (brew) on fedora_atomic — names still to verify
On fedora_atomic, brew is the `native:` manager. A component reaches it through a `brew: <formula>`
entry in its `via: native` `name:` map, a `{ via: native  when: "fedora_atomic" }` binding where the
native binding doesn't already reach fedora_atomic (see rust/node/openjdk/r/dig for the shape), or
the `{ via: brew  name: <formula> }` binding that CLI tools, toolchains and servers now carry on
every glibc distro (ec59455). A native binding with no `brew:`/`default:` name installs the
*component name* there. Watch out: a `default:` name meant for the Linux distros also lands on brew.
`tools/namesweep.py` doesn't check brew names; `tools/compaudit.py`'s brew probe (2df25e5) checks
every `via: brew` formula and every explicit `brew:` name against the formulae.brew.sh index, but
not a native binding's default-name resolution on fedora_atomic.
- **postgresql** — declines on fedora_atomic. Homebrew ships only versioned `postgresql@NN`
  formulae (the bare name is now an alias of `postgresql@18`), and they are keg-only, so the
  no-brew-binding-for-keg-only rule keeps it declined; a route there would need another method.
- **unrar** — declines on fedora_atomic, correctly: it is not in the homebrew/core index
  (formulae.brew.sh, 2026-10-10). Add a binding only if the formula returns.

### Nushell glue — more init-evals on demand
Every shipped elvish snippet now has a nu path (see Done). The personal snippets (citybanner, ps1,
geg) left the repo on 2026-10-10 (to the user's ~/cfs-todo/). More init-eval tools can be added with
one `#!cs-eval <cmd>` line each (e.g. `starship init nu`, if a starship component is added; none
exists today).

### Routing — variant-aware identity
- **Same-driver multi-version instances** (routing-overhaul phase 5): variant-aware unit identity so
  one driver can hold several versions of one component side by side. Only on a concrete case.
  (Moved from docs/done/routing-overhaul-plan.md, 2026-10-10.)

---

## Done since deferral

- **brew names on fedora_atomic** (from Still deferred) — RESOLVED 2026-10-10: tshark → the
  CLI-only `wireshark` formula and netcat → `netcat` (2a577c0); kubectl → `kubernetes-cli` (ec59455);
  lldb is its own formula (keg-only only on macOS) with a `{ via: brew  name: lldb }` binding
  (ec59455); iftop, nethogs, nload, vnstat and mtr are formulae with Linux bottles (formulae.brew.sh
  index, 2026-10-10).

- **`ProfileScreen._warm_cache` thread-safety** (from docs/done/d2-mvvm-findings.md) — FIXED
  2026-10-10 (2a577c0): `_resolve`'s cache read/mutate runs under a per-instance `_res_lock`, and
  `routes.candidates()` under the module-level `menu._ROUTES_LOCK`, so two profile views over one
  ctx can't race.

- **2026-08-08, d98f306 — C++ libs + 3 flatpaks.** `boost`, `abseil`, `qt` (Qt6), `gtk` (GTK4),
  `gtkmm` natively; `folly` (Fedora native + Arch AUR); `eastl` (Arch AUR). Flatpak for `emacs`
  (org.gnu.emacs), `octave` (org.octave.Octave), `zed` (dev.zed.Zed).
- **2026-08-08, b57c108 — snap driver** (`configsys/drivers/snap.py`). It started Ubuntu-only; see
  the snap entries below.
- **2026-08-08, b6cf9df — snap bindings + driver-wide `standing:`.** Originally the driver flag
  `candidate-only`. Since the routing overhaul (d284b7f / f199137 / 9d3b791, 2026-08-11) it is
  `drivers: { snap: { standing: never-auto } }`. A snap binding is valid, listed and pinnable, but
  never the automatic choice while another method is valid. A binding-pin still forces it, and where
  snap is the only method it wins. See docs/routing-model.md §8a. The `drivers:` block overlays
  every layer (repo → plugins → primary → top config), so a primary plugin can add
  `flatpak: { standing: never-auto }` the same way. Since da0a7ac (2026-10-10) the snap driver is
  also gated off wherever its own requires (snapd) have no method — openSUSE, Void (glibc and
  musl), Alpine, Chimera, fedora_atomic, kde_linux, Amazon Linux — so no snap method is offered
  there.
  - Bindings, names verified on snapcraft.io: vscode (`code`, classic), slack, discord, postman,
    obs-studio, blender (classic), node (classic), kubectl (classic), helm (classic), firefox,
    chromium, plus a new **spotify** component (Flathub `com.spotify.Client` + `spotify` snap).
  - Golden showed ZERO default flips. The `gh` snap was skipped (community, not official GitHub).
- **2026-08-08, 1c1a5d5 — binary-release sweep (14 components, every asset glob matched against a
  live release).**
  - tarball → ripgrep, fzf, btop, jq (raw), protobuf, xh, websocat (raw), ollama, zed, k3s.
  - native-pkg-file (.deb + .rpm in one binding) → dbeaver, bruno.
  - appImage → musescore, freecad.
  - Defaults:
    - xh/websocat flipped cargo → tarball (approved).
    - ollama flipped script → tarball (userland; configsys avoids `curl | sudo` scripts).
    - k3s keeps its get.k3s.io script via `standing: 1`, because the script sets up the systemd
      service.
    - dbeaver/bruno get the `when:`-gated .deb/.rpm by specificity on debian/redhat. flatpak stays
      the default elsewhere and is listed everywhere.
- **2026-08-08, a77177d — tree-sitter-cli.** Added the tarball `archive: gz` mode (gunzip a single
  compressed binary). cargo stays the default via `standing: 1`.
- **2026-08-08, 3ccf78c — insomnia + godot.** `discover_asset_url` scans recent releases (not just
  `releases/latest`), and a new `tag-re:` extracts a clean version (`core@13.1.0` → `13.1.0`,
  `4.7.1-stable` → `4.7.1`). insomnia = .deb/.rpm (default on debian/redhat); godot = tarball
  option (flatpak stays default).
- **2026-08-08, 5691a43 — Flathub IDs + brew fixes (networked pass).**
  - Flatpak added: arduino (cc.arduino.IDE2), paraview (org.paraview.ParaView), virt-manager
    (org.virt_manager.virt-manager), wxmaxima (io.github.wxmaxima_developers.wxMaxima).
  - Confirmed absent from Flathub: ghostty, gnuradio, qjackctl, supercollider. (ghostty has since
    gained native arch/void plus a community AppImage.)
  - Brew: traceroute gated `not fedora_atomic` (no formula); p7zip → `sevenzip` on fedora_atomic.
    Verified correct as-is on formulae.brew.sh: virt-manager, qjackctl, strace, valgrind, julia,
    odin, bun.
- **2026-08-08, 100ce60 — brew coverage pass.** Added a fedora_atomic binding where a real formula
  existed but the native binding didn't reach there: erlang, nim, maxima, gap, supercollider, opencv
  (`name: opencv`), texlive (`name: texlive`), mariadb (`name: mariadb`). Most other researched
  formulae equal the component name and already resolved (`haskell` → `ghc`, `cabal` →
  `cabal-install` via their `default:` names).
- **2026-08-08, 5c99ccd — redis + golden gate.** redis got a fedora_atomic binding with
  `name: redis`; the distro repos lean valkey post-relicense, but Homebrew keeps `redis`. Added
  `('fedora_atomic', '41')` (and `('elementary', '8')`) to `test/test_golden.py` `CONTEXTS`, so brew
  resolution is now regression-locked.
- **2026-08-10 — full-choice sweep** (after the policy reversal):
  - Flatpak made universal for firefox/libreoffice/vlc/blender/vscode + chromium (2b7777f).
  - Over-narrow binaries broadened: just (5105301), helix/kubectl (55d0b86).
  - Flathub-verified sweep of every no-flatpak component: android-studio/unityhub/mitmproxy got
    flatpaks (9a81e5b), keeping their official build as default. httpie was skipped (Flathub's is a
    different product).
  - wireshark Flatpak (52707ee) — it's the only GUI on atomic.
  - nushell musl tarball for Alpine (2bfce89).
  - Per-binding `standing: never-auto` (b96cb45, then named `candidate-only`), first used for
    discord's rolling .deb (56b664d).
  - Vendor-repo native: chrome (8209ba8), brave/opera/vivaldi/edge (ee78047), slack (6810ef5).
    Each wires the official apt + dnf repo (+ AUR / Arch extra). Native is the default there; flatpak
    is the default on openSUSE/atomic.
  - snapd/snapd-socket/snapd-snap-link + snaps offered on every distro, not just Ubuntu (589d8e2).
- **2026-08-10, configsys-source e89b63b + c3c8262 — `via: source` recipes** for EASTL and folly
  (with folly's C++ deps) in the configsys-source plugin. No bespoke plugin was needed. Core routes.hu
  keeps only folly's Fedora native/Arch AUR and eastl's Arch AUR bindings.
- **Researcher's vendor-URL list, covered another way:**
  - vscode .deb → Microsoft's vendor repo, native on debian/redhat (c6a8387, predates the list).
  - slack .deb → the packagecloud repo (6810ef5).
  - discord .deb → a `standing: never-auto` native-pkg-file (56b664d).
  - krita/inkscape AppImages → native bindings (inkscape in de00d7d).
  - virtualbox → native per distro.
  - helm → `script` + native/snap.
- **2026-09-18/19 — nushell glue complete.**
  - Full snippet batch (c119924).
  - The `#!cs-eval <cmd>` init-eval directive, shipping zoxide and atuin (bc04e99).
  - The `cs-bash-env` bridge in `glue/shell/nu/00-configsys.nu` (nushell's `bass`) for sdkman,
    vulkan-sdk, gnustep, miniforge, pyenv, opam, luarocks (106ec2f). A bash *function* the script
    defines (`sdk`/`conda`/`pyenv`) doesn't cross to nu, but the PATH/env it sets does.
  - fzf via native Reedline keybindings in `glue/shell/nu/fzf.nu` (Ctrl-R / Ctrl-T / Alt-C;
    honours `$FZF_CTRL_T_COMMAND` / `$FZF_ALT_C_COMMAND`) (0a6c746).

---

## Dropped

- **"Minimize install options" stance** — reversed 2026-08-10 in favour of full choice.
- **Judgment call on cargo → tarball default flips** (xh, websocat, tree-sitter-cli) — decided in
  1c1a5d5 / a77177d: xh and websocat flipped; tree-sitter-cli keeps cargo via `standing: 1`.
- **Snap-vs-native for `code`** — moot, because snap's driver-wide `standing: never-auto` keeps it
  from ever being the automatic choice.
- **brew for clang-tidy / texlive-full / opencv-python** — no standalone formula (they ship inside
  `llvm` / `texlive` / `opencv`). All three decline on fedora_atomic by design, and `clang` already
  maps `brew: llvm`.
- **brew for julia / odin / bun / p7zip / strace / virt-manager / qjackctl / traceroute** — resolved
  in 5691a43 (verified, renamed to `sevenzip`, or declined). Nothing left to add.

---

## Appendix: binary-release research notes (2026-08-08, historical)

The asset facts below are folded into the shipped bindings. They are kept for the repo and
binary-layout detail. Versions and tags are as of 2026-08-08. Field syntax: see existing
`via: tarball` / `via: native-pkg-file` / `via: appImage` bindings (`version: { github: owner/repo
strip-v:  asset: }`, `installDir`, `archive`, `binary`, `requires`).

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
- openscad — **GitHub "latest" is the old 2021.01 stable; current nightlies live at files.openscad.org, NOT GitHub** → needs a `url:`-based (non-GH) binding (still deferred, above)

The original offline H/M tables are below. The "X-only now" notes describe each component's methods
at the time, before the sweep.

### tarball (prebuilt binary from a GitHub release)
| comp | repo | conf | asset / notes |
| --- | --- | --- | --- |
| ripgrep | BurntSushi/ripgrep | H | `ripgrep-*-x86_64-unknown-linux-musl.tar.gz` (rg in a subdir, strip 1). native-only then. |
| fzf | junegunn/fzf | H | `fzf-*-linux_amd64.tar.gz`, strip-v; single `fzf`. native-only then. |
| btop | aristocratos/btop | H | `btop-x86_64-linux-musl.tbz` (bzip2 tar; `btop/bin/btop`). native-only then. |
| xh | ducaale/xh | H | `xh-v*-x86_64-unknown-linux-musl.tar.gz`; `xh`. cargo-only then. |
| ollama | ollama/ollama | H | `ollama-linux-amd64.tgz` (bin/ + lib/). native,script then. |
| tree-sitter-cli | tree-sitter/tree-sitter | H | `tree-sitter-linux-x64.gz` (gzipped single binary → rename `tree-sitter`). cargo-only then. |
| protobuf | protocolbuffers/protobuf | H | `protoc-*-linux-x86_64.zip`, strip-v; `bin/protoc` + `include/`. native-only then. |
| jq | jqlang/jq | H | asset `jq-linux-amd64` (raw binary, archive:none, binary:jq). Tags are `jq-*` not `v*` → strip `jq-`, not strip-v. |
| websocat | vi/websocat | M | raw binary `websocat.x86_64-unknown-linux-musl` (rename `websocat`); naming varies by release. cargo-only then. |
| zed | zed-industries/zed | M | `zed-linux-x86_64.tar.gz` (ships zed.app tree) — verify layout. had flatpak+script. |
| k3s | k3s-io/k3s | M | raw binary asset `k3s`, archive:none. had script. |
| godot | godotengine/godot | M | `Godot_v*-stable_linux.x86_64.zip`; tag form `4.x-stable` needs custom version handling. flatpak-only then. |

### native-pkg-file (.deb/.rpm on a GitHub release)
| comp | repo | conf | asset |
| --- | --- | --- | --- |
| insomnia | Kong/insomnia | M | `Insomnia.Core-*.deb` / `.rpm` (also ships .AppImage). flatpak-only then. |
| dbeaver | dbeaver/dbeaver | M | `dbeaver-ce_*_amd64.deb` / `dbeaver-ce-*.x86_64.rpm`. flatpak-only then. |
| bruno | usebruno/bruno | M | `bruno_*_amd64_linux.deb` / `.rpm`. flatpak-only then. |

### appImage
| comp | repo/source | conf | asset |
| --- | --- | --- | --- |
| musescore | musescore/MuseScore | M | `MuseScore-Studio-*-x86_64.AppImage` (needs libfuse2). flatpak-only then. |
| freecad | FreeCAD/FreeCAD | M | `FreeCAD_*-Linux-x86_64-*.AppImage`. flatpak-only then. |
| openscad | openscad/openscad or files.openscad.org | M | `OpenSCAD-*-x86_64.AppImage` (stable assets may be on files.openscad.org, not GH). flatpak-only then. |
