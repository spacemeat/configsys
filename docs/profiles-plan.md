# Profiles pass — design + rationale (APPLIED)

**Status: applied to `config.hu`.** This is the reasoning behind the profiles now in `config.hu`;
that file is the source of truth (§6's block is not maintained here — see `config.hu`). The design
fills out the ~90 previously-orphaned components (defined in `routes.hu`, in no profile, not pulled
as a dep) and makes profiles composable. All §8 judgment calls were resolved (see §8).

## 1. Principles

1. **Two tiers.** *Leaf bundles* are small, single-purpose, composable, and carry no `+user`
   (e.g. `net-tools`, `cloud`, `k8s`). *Role profiles* compose leaves + a few role-specific
   names (e.g. `backend = +user +containers +k8s +cloud +db-clients +db-servers …`). This kills
   the duplication that's already creeping in (the browser list, the networking list) and lets a
   user cherry-pick a leaf into their own profile.
2. **Bundle only cohesive sets** — things you plausibly want *all* of (`analysis` = the whole
   debug kit; `net-tools` = the whole capture/probe/monitor set). **Never bundle pick-one
   categories**: editors, shells, desktop environments, individual languages, GPU vendor SDKs,
   hypervisors. Those stay **menu-only** — defined and discoverable, installed on demand
   (`configsys install helix`) or added to a personal profile, but never force-installed by a
   role. (§5 lists them, with why.)
3. **No surprises in the default set.** `configs:` stays conservative; the heavy/niche new
   profiles (`virt`, `ai`, `devops`, `desktop-apps`) are opt-in per machine, exactly like
   `artist`/`audio`/`backend` are today.
4. **Every orphan gets an explicit verdict** — a profile, a leaf, or "menu-only (reason)". §7 is
   the full disposition table; no component is left merely forgotten.

## 2. Leaf bundles (new — composable, no `+user`)

| Leaf | Members | Purpose |
|---|---|---|
| `terminal` | bash-dotfiles, configsys-dotfiles, git, fastfetch, fzf, ripgrep, xclip, htop, btop, tmux, lazygit, mononoki-nerd | the CLI baseline, extracted from today's `user` (+ `tmux`, `btop`, `lazygit`, and the orphaned `configsys-dotfiles`, which is literally the tool's own shell hook) |
| `net-tools` | iproute2, wireshark, wireshark-group, tshark, tcpdump, nmap, mtr, traceroute, iperf3, socat, ethtool, whois, netcat, dig, iftop, nethogs, nload, vnstat | today's `networking` minus `+user` |
| `cloud` | awscli, gcloud, azure-cli, opentofu, grpcurl | cloud CLIs + IaC |
| `containers` | docker, docker-group, lazydocker | local container stack (podman is the menu-only alternative) |
| `k8s` | kubectl, helm, k9s, k3s | Kubernetes client + a light local cluster |
| `db-clients` | pgcli, mycli, dbeaver, sqlitebrowser, lazysql | database front-ends |
| `db-servers` | postgresql-service, mariadb-service, redis-service | local DB servers (as systemd services) |
| `jvm` | jdk, kotlin, maven, gradle | the JVM toolchain (sdkman is the menu-only alternative bootstrap) |
| `latex` | texlive | LaTeX (texlive-full is the menu-only heavier alternative) |

`analysis`, `codecs`, `vulkan-dev`, `vulkan-runtime`, `docker`, `compression` are **already**
`parts` bundles in `routes.hu` — leaves in spirit; profiles just reference them.

## 3. Role profiles — revised (fill-outs in **bold**)

- **user** = `+terminal`, firefox, chrome, neovim  *(everyday desktop base = terminal + 2 browsers + default editor)*
- **dev** = `+user`, build-essential, rust, gcc-13/14/15, clang-18/19/20, gdb, **analysis**, **cmake**, **ninja**, **meson**, **just**, vscode
- **web-dev** = `+user`, node, typescript, prettier, pnpm, yarn, sass, brave, opera, vivaldi, edge, httpie, jq, yq, mitmproxy, xh, websocat, postman, insomnia, bruno  *(dropped firefox/chrome — already in `+user`)*
- **backend** = `+user`, **`+containers`**, **`+k8s`**, **`+cloud`**, **`+db-clients`**, **`+db-servers`**, protobuf, **ansible**  *(refactored from the flat list into leaves)*
- **electronics** = `+dev`, arduino, kicad, **gnuradio**
- **graphics** = `+user`, vulkan-dev, blender  *(unchanged)*
- **gaming** = `+user`, vulkan-runtime, steam  *(unchanged)*
- **artist** = `+user`, blender, krita, gimp, inkscape, darktable, freecad, openscad, godot, scribus, digikam, obs-studio  *(unchanged; consider `codecs`)*
- **audio** = `+user`, pipewire, ardour, lmms, tenacity, musescore, hydrogen, carla, sonic-pi, supercollider, qjackctl  *(unchanged; consider `codecs`)*
- **science** = `+user`, **`+latex`**, julia, r, octave, jupyterlab, gnuplot, paraview, miniforge
- **math** = `+user`, **`+latex`**, julia, r, octave, maxima, wxmaxima, pari, gap, gnuplot, sagemath  *(texlive → `+latex`)*
- **networking** = `+user`, **`+net-tools`**  *(now just composition)*

## 4. Role profiles — new

- **ai** = `+terminal`, claude-code, codex, llm, aider, ollama  *(AI-assisted dev CLIs; `+terminal` not `+user` so it's usable headless)*
- **virt** = `+user`, qemu, libvirt, libvirt-service, virt-manager  *(a KVM/libvirt host; virtualbox is the menu-only alternative)*
- **devops** = `+terminal`, `+containers`, `+k8s`, `+cloud`, ansible, opentofu  *(infra focus, lighter than `backend`; **overlaps backend** — see §8)*
- **desktop-apps** *(opt-in)* = `+user`, libreoffice, vlc, discord, slack  *(daily-driver desktop extras)*

## 5. Deliberately menu-only (defined, discoverable, in no profile — by design)

These are **pick-one / hardware-specific / personal**; force-installing a set would be wrong.
They remain fully usable via `configsys install <name>` or by adding to a personal profile.

- **Desktop environments** (all 10: gnome, kde, xfce, lxqt, mate, sway, cinnamon, budgie,
  hyprland, cosmic) — pick-one, and each is a large system change.
- **Shells** (zsh, fish, nushell) — personal; `tmux` is the one shared-baseline pick (→ `terminal`).
- **Alt editors/IDEs** (emacs, helix, zed, android-studio, jetbrains-toolbox) — `neovim`/`vscode`
  are the defaults in `user`/`dev`; the rest are a matter of taste.
- **Individual languages + their ecosystem demos** (go, ruby, ocaml, lua, haskell, erlang, elixir,
  nim, zig, odin, sbcl; and opam/dune, cabal/hlint, bundler, luarocks/dkjson, goimports,
  quicklisp, sdkman) — install the language you need. Several (`dkjson`, `dune`, `hlint`) are
  demonstrator "sample module" components anyway.
- **GPU/accelerator SDKs** (cuda-toolkit, rocm-hip, intel-oneapi-basekit) — match your hardware;
  each needs a vendor repo the user wires up.
- **Alternatives to a chosen default** (podman ↔ containers, virtualbox ↔ virt, salt/puppet ↔
  ansible, sdkman ↔ jvm, texlive-full ↔ texlive, bazelisk, conan, vcpkg).
- **Niche/heavy one-offs** (unityhub, perf, heaptrack, unrar, yay, gcompat, doas — the last two
  Alpine-only opt-ins).

## 6. Profiles block (historical snapshot — live version is `config.hu`)

> The block below is the original proposal. The applied version in `config.hu` additionally has
> `curl` in `terminal`, `codecs` in `user`, and the six `*-dev` per-language leaves (§8). Treat
> `config.hu` as authoritative.

```hu
    profiles: {
        // ---- leaf bundles (composable; no +user) --------------------------------
        terminal: [
            bash-dotfiles  configsys-dotfiles  git
            fastfetch  fzf  ripgrep  xclip
            htop  btop  tmux  lazygit
            mononoki-nerd
        ]
        net-tools: [
            iproute2
            wireshark  wireshark-group  tshark  tcpdump  nmap        // capture & probe
            mtr  traceroute  iperf3  socat  ethtool  whois  netcat  dig
            iftop  nethogs  nload  vnstat                            // live monitors
        ]
        cloud:       [ awscli  gcloud  azure-cli  opentofu  grpcurl ]
        containers:  [ docker  docker-group  lazydocker ]           // podman = menu-only alt
        k8s:         [ kubectl  helm  k9s  k3s ]
        db-clients:  [ pgcli  mycli  dbeaver  sqlitebrowser  lazysql ]
        db-servers:  [ postgresql-service  mariadb-service  redis-service ]
        jvm:         [ jdk  kotlin  maven  gradle ]                  // sdkman = menu-only alt
        latex:       [ texlive ]                                     // texlive-full = heavier alt

        // ---- role profiles ------------------------------------------------------
        user: [
            +terminal
            firefox  chrome
            neovim
        ]
        gaming: [ +user  vulkan-runtime  steam ]
        dev: [
            +user
            build-essential  rust
            gcc-13  gcc-14  gcc-15  clang-18  clang-19  clang-20
            gdb  analysis                                           // analysis = valgrind/cppcheck/lldb/strace/ltrace/clang-tidy
            cmake  ninja  meson  just
            vscode
        ]
        web-dev: [
            +user
            node  typescript  prettier  pnpm  yarn  sass            // node toolchain + front-end
            brave  opera  vivaldi  edge                             // extra browsers (firefox/chrome via +user)
            httpie  jq  yq  mitmproxy  xh  websocat                 // HTTP/API CLI
            postman  insomnia  bruno                                // GUI API clients
        ]
        backend: [
            +user  +containers  +k8s  +cloud  +db-clients  +db-servers
            protobuf  ansible
        ]
        electronics: [ +dev  arduino  kicad  gnuradio ]
        graphics:    [ +user  vulkan-dev  blender ]
        artist: [
            +user  blender  krita  gimp  inkscape  darktable
            freecad  openscad  godot  scribus  digikam  obs-studio
        ]
        audio: [
            +user  pipewire  ardour  lmms  tenacity  musescore
            hydrogen  carla  sonic-pi  supercollider  qjackctl
        ]
        science: [ +user  +latex  julia  r  octave  jupyterlab  gnuplot  paraview  miniforge ]
        math:    [ +user  +latex  julia  r  octave  maxima  wxmaxima  pari  gap  gnuplot  sagemath ]
        networking: [ +user  +net-tools ]

        // ---- new role profiles (opt-in; not in the default configs:) -------------
        ai:   [ +terminal  claude-code  codex  llm  aider  ollama ]
        virt: [ +user  qemu  libvirt  libvirt-service  virt-manager ]   // virtualbox = menu-only alt
        devops: [ +terminal  +containers  +k8s  +cloud  ansible  opentofu ]
        desktop-apps: [ +user  libreoffice  vlc  discord  slack ]
    }
```

`configs:` (the machine default) can stay `[ user, gaming, dev, electronics, graphics ]`, or you
could trim it — the new leaves/roles are all opt-in and don't change the default set.

## 7. Orphan disposition — every currently-orphaned component

| Orphan(s) | Verdict |
|---|---|
| tmux, btop, lazygit, configsys-dotfiles | → `terminal` |
| iproute2 *(was top-of-file, functionally networking)* | → `net-tools` |
| jdk, kotlin, maven, gradle | → `jvm` |
| cmake, ninja, meson, just | → `dev` |
| analysis (bundle), heaptrack?, perf? | `analysis` → `dev`; heaptrack/perf → menu-only (niche) |
| kubectl, helm, k9s, k3s | → `k8s` |
| docker-group, lazydocker | → `containers` |
| qemu, libvirt, libvirt-service, virt-manager | → `virt` |
| lazysql | → `db-clients` |
| awscli/gcloud/azure-cli already in backend → `cloud` leaf | (refactor) |
| claude-code, codex, llm, aider, ollama | → `ai` |
| ansible | → `backend` + `devops` |
| gnuradio | → `electronics` |
| libreoffice, vlc, discord, slack | → `desktop-apps` |
| texlive *(from math)*, science/math | → `latex` leaf |
| zsh, fish, nushell | menu-only (pick your shell) |
| emacs, helix, zed, android-studio, jetbrains-toolbox | menu-only (pick your editor) |
| go+goimports, ruby+bundler, haskell+cabal+hlint, ocaml+opam+dune, lua+luarocks, sbcl+quicklisp | → per-language leaves `go-dev`/`ruby-dev`/`haskell-dev`/`ocaml-dev`/`lua-dev`/`lisp-dev` |
| erlang, elixir, nim, zig, odin | menu-only (bare language, no ecosystem to bundle) |
| dkjson, sdkman | menu-only (sample rock / jvm alt bootstrap) |
| bazelisk, conan, vcpkg | menu-only (specialized C/C++/build) |
| salt, puppet | menu-only (ansible alternatives) |
| podman, virtualbox | menu-only (alternatives to containers/virt picks) |
| cuda-toolkit, rocm-hip, intel-oneapi-basekit | menu-only (hardware/vendor) |
| gnome, kde, xfce, lxqt, mate, sway, cinnamon, budgie, hyprland, cosmic | menu-only (pick-one DE) |
| codecs | → `user` (base); compression / codecs-restricted stay menu bundles |
| unrar, unityhub, texlive-full, yay, doas, gcompat | menu-only (one-offs / platform / opt-in) |

## 8. Judgment calls — resolved

1. **`backend` vs `devops` overlap** → **(a)**: keep both. `backend` = app + data platform,
   `devops` = infra only (no DB servers/clients).
2. **`btop` *and* `htop` in `terminal`** → **keep both**. Some prefer one, some the other.
3. **Naming `git` (and `curl`) in `terminal`** → **name both**. Useful to list for version
   upgrading, even though they're also pulled as driver deps.
4. **`codecs`** → **in `user`** (the base), so every profile inherits the free codec set. Verified
   `codecs` resolves on all five base OSes (ubuntu/fedora/arch/opensuse/alpine).
5. **Per-language dev leaves** → **yes, added**: `go-dev`, `ruby-dev`, `haskell-dev`, `ocaml-dev`,
   `lua-dev`, `lisp-dev` (each = the language + its ecosystem tooling). Bare languages with no
   extra tooling (erlang, elixir, nim, zig, odin) stay install-by-name. Named `<lang>-dev` to
   avoid colliding with the same-named component (e.g. the `haskell` component).
6. **Default `configs:`** → **left as-is** (the user will tune it). All new profiles are opt-in.

## 9. Input for the `routes.hu` spatial-grouping pass

You mentioned grouping similar-function components spatially in `routes.hu`. From the inventory,
these clusters are currently **split across distant regions** — the highest-value regroupings:

- **Browsers split:** `firefox` sits alone in the top "trivial natives" block (~line 104); the
  rest (`chrome, brave, opera, vivaldi, edge`) is ~250 lines later (356–360).
- **Terminal utils split:** `ripgrep, fzf, xclip, btop` are in the top natives block (126–139);
  `htop` is far later (426); they read as one section.
- **Editors in four places:** `neovim` (940), `emacs/helix/zed` (720–739), `vscode` (1073),
  `android-studio/jetbrains-toolbox` (662–674) — no single editors section.
- **Build tooling split:** `make` (1043) is far from `cmake/ninja/meson/just/bazelisk` (824–841).
- **Fundamentals late:** `curl`, `git` — basic and used as driver deps — are near the bottom
  (1036–1037).
- **`iproute2`** (108) is orphaned from the networking cluster (362+); **`libfuse2`** (182) sits
  amid language toolchains rather than with core/bootstrap utilities.

Already well-grouped: networking, web/HTTP, desktop environments, science/math, media/creative,
vulkan, codecs, versioned gcc/clang. (Dotfiles are deliberately co-located with their parent
component rather than in one section — consistent, so not a regrouping target.)
