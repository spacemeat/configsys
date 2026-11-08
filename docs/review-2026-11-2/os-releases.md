# Review: OS releases (`/update-os *`, Phases 0–6, report only)

Baseline: `956208e` · 2026-11-08 · run by the orchestrator (no subagents)
Registry: every versioned line registered the same day (`956208e`). Tools: `osaudit releases / snapshot /
pinned / delta / sweep` (podman, every live release; EPEL + CRB enabled for EL), plus a new
derivative-vs-base comparison (each own-numbering derivative release resolved against the base release its
`note:` names). Driver lifecycle harnesses were **not run** (see §6).

## 1. Registry changes proposed

| # | change | evidence |
|---|---|---|
| R1 | **fedora 46** `{ status: prerelease  image: "docker.io/library/fedora:46"  glibc: 2.44.9000  python3: 3.15  gcc: 16  manager: "dnf5 version 5.4.6.0"  released: 2027-04-?? note: "expected" }` | `podman manifest inspect docker.io/library/fedora:46` exists (Rawhide carries the next number); `osaudit facts fedora 46` |
| R2 | none needed elsewhere: ubuntu 27.04, debian 14, alpine 3.25 have no image yet | `podman manifest inspect` → absent |

No `eol-passed` or `prerelease-past-ga` staleness (`osaudit releases`).

## 2. Broken on a live release (native names missing, no fallback checked yet)

Names a binding routes to on that release that the release's repos don't carry (`osaudit sweep`). Each needs
triage: a release-scoped gate on the native binding (`not (<line> >= N)`) plus a fallback that still routes,
or an honest "no method on N". Counts are distinct missing package names.

- **EL 10 — 64 missing** (EPEL 10 + CRB enabled). The biggest gap in the tree: EPEL 10 is still filling in.
  SDL2-devel, SFML-devel, VirtualBox, asciinema, asciiquarium, audacity, blender, budgie-desktop, cinnamon,
  cmatrix, cosmic-session, darktable, elixir, erlang, fossil, frotz, gap, gcc-gnat, gcc-objc, glances,
  glmark2, gnucobol, gnuradio, heaptrack, httpie, hyprland, i3, inkscape, jack-audio-connection-kit,
  java-17-openjdk-devel, jmtpfs, libcxx-devel, libcxxabi-devel, libreoffice, lxqt-session, mate-desktop,
  maxima, moby-engine, mpc, mpd, newsboat, nng-devel, opam, paraview, pari-gp, playerctl, python3.10,
  python3.11, qjackctl, qtile, rakudo, sbcl, scribus, supercollider, sway, texlive-scheme-full/medium, wine,
  winetricks, wxmaxima, xfce4-session, xmonad, xorg-x11-server-Xephyr, zoxide. GUI apps mostly have a flatpak
  fallback already — gating the native binding off EL 10 lets it win; toolchains/libs need a per-item look.
- **EL 9 — 38 missing**: SFML-devel, asciiquarium, budgie-desktop, cmatrix, cosmic-session, elixir, frotz,
  gap, glmark2, gtkmm4.0-devel, gum, hyprland, just, libcxx-devel, libcxxabi-devel, lxqt-session, maxima,
  moby-engine, mpc, newsboat, nng-devel, opam, pari-gp, pipx, python3.10, qjackctl, qtile, rocm-hip, sbcl,
  supercollider, sway, syncthing, texlive-scheme-full/medium, webkit2gtk4.1-devel, winetricks, wlroots-devel,
  wxmaxima. (Boundaries: gtkmm4.0-devel, gum, just, pipx arrive in EL 10 — move those gates.)
- **EL 8** — not swept: the sweep's name verifier timed out twice on the almalinux:8 image (a tooling finding: osaudit's verifier timeout is too short for EL 8's modular dnf metadata).
- **openSUSE Leap 16.0 — 27 missing**: bitwarden, bmon, carla, cbonsai, cmatrix, cosmic-session, darktable,
  dool, freecad, glfw-devel, gnuradio, hydrogen, hyprland, impala, lmms, maxima, nim, nmap, openscad,
  openshot-qt, rocm-hip, sbcl, sdl2-compat-devel, sqlitebrowser, steam, webkitgtk4-devel, wiremix. Leap 16
  dropped much of what Tumbleweed carries; the bindings say `opensuse` (both) — they need
  `opensuse_tumbleweed` or `not opensuse_leap`.
- **Amazon Linux 2023 — 27 missing**: SDL2_image-devel, SDL2_ttf-devel, asciinema, asio-devel, bmon,
  bridge-utils, cmake-gui, cmatrix, double-conversion-devel, fmt-devel, freealut-devel, frotz, glmark2,
  glog-devel, ioping, libmtp-devel, libvirt-client, mosh, newsboat, openal-soft-devel, python3-wxpython4,
  python3.10, radare2, sysbench, tor, ttyd, wlroots-devel. The `redhat` bindings reach amzn; most want
  `and not amzn`.
- **Debian 13 — 8**: clang-20, gcc-10, gcc-11, gcc-15, libwlroots-dev, openjdk-17-jdk,
  software-properties-common (gone in trixie — **the apt PPA path calls `add-apt-repository`**, check every
  `ppa:` binding reachable on debian), ttyd.
- **Debian 12 — 11**: clang-18, clang-20, gcc-10, gcc-13, gcc-14, gcc-15, kew, openjdk-21-jdk, openjdk-25-jdk,
  vkmark, wmenu (the parallel gcc/clang components route there by name without a release gate).
- **Ubuntu 26.04 / 26.10 — 4 each**: dotnet-sdk-8.0, gcc-10, jmtpfs, libwlroots-dev.
- **Ubuntu 24.04 — 1**: gcc-15. **Ubuntu 22.04 — 8**: clang-20, gcc-13, gcc-14, gcc-15, kew, libwxgtk3.2-dev,
  vkmark, wmenu.
- **Alpine 3.22 — 6 / 3.23 — 3 / 3.24 — 0**: cosmic-session, gnucobol, wlroots0.19-dev (both), impala,
  openjdk25, pastel (3.22) — boundaries say each arrives in 3.23/3.24: gate `alpine >= 3.24` etc.
- **Fedora 43–45 — 0.**

The parallel-toolchain pattern (gcc-NN / clang-NN / openjdk-NN routed by name on every release of a line)
accounts for a third of the Debian/Ubuntu misses: they want the release pins the Fedora run gave them.

## 3. Old-release and derivative corrections

**Derivatives drift from their base (new check).** Each own-numbering derivative release should resolve like
the base release it is built on. It doesn't wherever a gate names only `ubuntu`/`debian` versions — those
atoms don't reach a scale-root derivative, so Zorin/Mint/elementary/LMDE/MX fall into the *other* branch:

| derivative | vs base | components routed differently |
|---|---|---|
| zorin 17 · linuxmint 21.3 · elementary 7.1 | ubuntu 22.04 | gtkmm (gets **gtkmm-4.0** — not in 22.04), p7zip (`p7zip-full` vs `7zip`), pipx + 8 pipx apps (apt `pipx` vs pip), wl-screenrec (cargo, base declines) |
| zorin 18 · linuxmint 22.3 · elementary 8.1 | ubuntu 24.04 | eza (tarball vs apt), gping (brew vs apt), yazi (brew vs .deb), tuxedo (brew vs tarball), newsboat (apt vs brew), p7zip |
| lmde 7 · mx 25 | debian 13 | eza, gping, lazygit, tuxedo, yazi, p7zip |
| mx 23 | debian 12 | gtkmm, p7zip, wl-screenrec |

11 of the 42 versioned `ubuntu`/`debian` gates in routes.hu omit the derivative atoms (31 carry the long
`(elementary >= 7) or (linuxmint >= 21) …` list by hand). Per-gate fix: add the derivative atoms. **Systemic
fix (recommended, see README D-tier):** let a derivative's registry entry name its base (`base: "ubuntu
24.04"`) and have the predicate evaluate a versioned base atom through it — this is the os-releases plan's
phase 5 ("the engine reads the registry"), and it retires every hand-kept derivative list.

**Release-pinned bindings (`osaudit pinned`)** — `stops-short` items to confirm against the sweep:
- `gtkmm` native `(ubuntu < 24.04) or (debian < 13)` — fine on the bases, wrong on derivatives (above).
- `pipx` via pip `(ubuntu < 23.04) or (debian < 12) or amzn` — derivatives again.
- `gthumb` native `rhel < 10` — EL 10 gets flatpak; gthumb is not in EPEL 10 (sweep agrees).
- Fedora: `dotnet` `< 45`, `folly` `< 44`, `gcc-14` `[42,44)`, `jdk` `< 44`, `supercollider` `< 44` —
  retirements recorded by the F45 run; confirmed still gone (fedora sweep: 0 missing).
- `no-live-release`: clang-19 (=41), clang-20 (=42), gcc-13 (=41), jdk-17 (<42), hyprland (<43) — frozen, leave.

**Deltas worth a look:** `neovim` resolves to the AppImage on EL 10 and Leap 16 (its native binding is gated
off both; neovim is in neither repo per the sweep's arrivals — correct, but a flatpak/brew is a better
default than an AppImage on a server-ish EL); Debian 13 gains native eza/gping/lazygit/tuxedo-tarball/yazi
.deb as intended.

## 4. Gaps to fill (arrivals)

Exact-name arrivals — a component's own name now in that release's repos while it routes elsewhere there
(`osaudit sweep` arrivals; `name-only` ones need an identity check before a native binding):
- **every line**: ant, hlint, yq, tree-sitter-cli, obs-studio, musescore, mycli, pgcli, leiningen, puppet.
- **Fedora 43–45** (unchanged from the F45 run): azure-cli, conan, discord, godot, grpcurl, jupyterlab,
  nextcloud, olive, opentofu, pnpm, salt, scratch, typescript, vcpkg.
- **Ubuntu 26.04/26.10 + Debian 13**: awscli, jupyterlab, llm, pyenv, xh, durdraw, swift; 26.10 adds godot.
- **EL 9/10**: discord, opentofu, onednn-devel/miopen (EL 9/10), typescript, salt.
- **Leap 16**: clang-19, gcc-15, conan, opentofu, pnpm, pyenv, xh, yarn, nextcloud.
- **Alpine 3.22–3.24**: k3s, signal-cli, websocat, xh, prettier (3.23+), jupyterlab (3.23+), opentofu, pnpm.
- **Amazon Linux 2023**: gtkmm4.0-devel, libgit2-devel, libsecret-devel, protobuf-devel, glew-devel and a set
  of X11 `-devel` libs — the `not amzn` on several lib bindings can narrow.
Arrivals are `/update-component` input: they're where native routes can replace brew/pipx/tarball defaults.

## 5. Fixtures (`osaudit fixtures`)

- `test/test_golden.py` CONTEXTS: no context for ubuntu 26.10 (newest released), rhel 10, elementary 8.1 — add
  them (keep the older contexts as the old-release guard).
- `tools/namesweep.py` MANAGERS: apt still sweeps ubuntu 24.04 (newest released 26.10).
- Containerfiles: defaults unchanged (user's call).

## 6. Not run

- **Driver lifecycle** (podman install→lock→unlock→remove): apt 3.x is new on Ubuntu 25.04+/Debian 13, apk-tools
  3 on Alpine 3.23+, zypper on Leap 16, dnf 4.20 on EL 10 — each a manager change the skill says needs the
  harness (`BASE=ubuntu:26.04 bash test/run-in-podman.sh`, `bash test/run-zypper-in-podman.sh btop
  registry.opensuse.org/opensuse/leap:16.0`, `bash test/run-rhel-toolchain-in-podman.sh almalinux:10`; no
  harness for alpine/amzn). Skipped for time in this overnight run; recommended before declaring those
  releases supported.
- **Per-release repos/PPAs** (`osaudit repos`) for the newly registered releases — not probed (network).
  Note `software-properties-common` is gone on Debian 13: any `ppa:` binding reachable there will fail.
