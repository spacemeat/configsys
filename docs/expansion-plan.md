# Expansion plan — languages, tools, DEs, and `configsys request`

Status: **SHIPPED** — every track below landed (language toolchains + module drivers, editors/
shells, the DE catalog, and `configsys request`). Kept as the record of what was built and why.

Discovery + grill outcome (2026-07-24). Source of truth for the smart-commit sequence below.
Each **data** commit regenerates the golden gate (`CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m
pytest test/test_golden.py`, review the diff) and runs the full suite before landing.

## Locked decisions

- **"Component stories" = a request-a-component report.** New `configsys request <name>`, parallel
  to `configsys report`. Its payload is a **coverage matrix**: resolve the component against every
  modeled OS block, show *have (this platform)* vs *missing (dnf / pacman / brew / …)*. Reuses the
  reportgen scrub/approve/gh-or-browser plumbing; own marker `<!-- configsys-request v1 -->`, own
  `component-request` label + issue form + a branch in the reports-repo auto-label Action.
  - Honest scope: there is no macOS OS block today (brew is only `native` on `fedora_atomic` + a
    `name:`-map key), so the matrix spans the modeled Linux families, not a fictional macOS.
- **Language model = native-first toolchains + ecosystem module drivers.** The *toolchain*
  (rustc/go/node/jdk/…) installs so the language is usable directly — native package where
  available, tarball where not. On top, **module-installer drivers** let configsys install
  language modules/CLIs the way `tree-sitter-cli` rides `cargo` today.
- **Module drivers, full set now:** `npm` (Node globals), `gem` (Ruby), `opam` (OCaml),
  `luarocks` (Lua), `cabal` (Haskell), `go-install` (Go), `sdkman` (JVM). (`cargo`, `pipx` exist.)
  Each implements the standard op set; no native version-lock → lock intent in the ledger (like
  cargo/pipx).
- **Languages, full set:** named — rust (made explicit), ocaml, zig, go, node/typescript,
  java/kotlin, odin, lua — plus curated extras — haskell, ruby, elixir/erlang, julia, nim, deno,
  bun.
- **DEs = broad catalog + variant OS blocks.** DEs are capabilities; *ubuntu variants declare
  `provides:` so a DE component skips install where the OS already ships it. Add OS blocks
  kubuntu→kde, lubuntu→lxqt, xubuntu→xfce (and kfedora/... as cheap). DE components: cosmic,
  gnome, kde/plasma, xfce, lxqt, cinnamon, mate, budgie, sway, hyprland (native metapackages,
  per-distro `name:` maps).
- **Editors/shells:** JetBrains Toolbox (tarball, manages IDEA/CLion/etc.), tmux, zsh, plus fish +
  nushell (native everywhere).

## Smart-commit sequence

### Track A — languages & module drivers  (one cohesive commit per ecosystem)
- **A1  rust, explicit.** `rust` component (native `rustup`/`rust`; provides `rust` + `cargo`
  capabilities); rewire the `cargo` driver-dep onto it. Foundational — proves the native-first
  toolchain + `provides:`-a-capability pattern.
- **A2  node + npm.** `node` toolchain (native / tarball); `npm` driver (`npm install -g`);
  `typescript`, `prettier` sample globals; `deno`, `bun` toolchains.
- **A3  go + go-install.** `go` toolchain; `go-install` driver (`go install pkg@latest`).
- **A4  ruby + gem.** `ruby` toolchain; `gem` driver.
- **A5–A8  native toolchains (verified).** jdk (openjdk), ocaml, lua, haskell (ghc), elixir,
  erlang, nim — all real, directly-usable native packages. **Landed together.**
- **A9  zig + odin.** tarball toolchains (github release, tar.xz/tar.gz — tarball-driver OK).
- **Module drivers `opam` / `luarocks` / `cabal` — BUILT + container-validated.** The podman
  harness exists (I'd missed it): `test/Containerfile.*` + `run-*-in-podman.sh` +
  `integration_*.sh` run real installs per-distro, throwaway. CLIs confirmed against opam 2.1.5 /
  luarocks 3.8.0 / cabal-install 3.8.1 in a container. luarocks gets a full configsys round-trip
  (`integration_lang_modules.sh`); opam/cabal read-commands are validated there, mutating
  commands recon-verified (their backends — `opam init`, ghc — are too heavy to build every run).
  - **opam init handled:** uninitialized opam exits 50 on *every* command (even `--safe`). Fixed:
    `Opam.install` runs an idempotent `opam init --no-setup --yes && opam install …`, and
    get_version degrades to None (not a crash) when uninitialized — validated in-container.
- **`deno` / `bun` / `kotlin` — DONE.** Added a zip path to the tarball driver (unzip, detected
  from a `.zip` url or `archive: zip`). deno/bun use github's API-free `releases/latest/download`
  URL (robust when api.github.com is blocked) — validated end-to-end in a container
  (`test/integration_zip.sh`). kotlin keeps github asset discovery (versioned asset name); needs
  a JVM (`requires: jdk`) + unzip.
- **`julia` — DONE.** julialang S3 tarball, pinned latest stable (1.12.6, url verified 200);
  native on Arch/Homebrew.
- **`script` driver — DONE (generalizes sdkman).** Rather than a bespoke sdkman driver, a general
  `via: script` driver: a component declares `install-cmd` / `version-cmd` (+ `version-re`) /
  `uninstall-cmd` / `upgrade-cmd` / `set-version-cmd` / `location` as data, so any script-installed
  tool (sdkman, rustup, nvm, vendor `curl|bash`) is just a route. Policy: **warn, don't gatekeep** —
  a missing `uninstall-cmd` is allowed (can't cleanly remove), flagged by a `configsys check`
  warning + at uninstall, never blocked. Ships sdkman as the demonstrator; validated end-to-end in
  a container (`test/integration_script.sh`). Nothing left deferred.

### Track C — desktop environments  (DONE, all five families)
- Podman sweep of apt/dnf/pacman/zypper/apk + this Pop host for cosmic confirmed every
  metapackage name. Shipped: gnome/kde/xfce/lxqt/mate/sway (all five families); cinnamon/budgie
  (all but Alpine); hyprland (all but stock Ubuntu); cosmic (Pop `cosmic-session` verified
  on-host + fedora/arch/opensuse/alpine; stock Debian/Ubuntu decline). `when:`-gated away from
  atomic (brew-native) desktops.
- Arch package GROUPS (xfce4/lxqt/mate) are handled: the pacman driver's get_version/get_latest
  fall back to `-Qg`/`-Sg` with a `(group)` marker, and uninstall expands a group to its members.
  - `kotlin` — its clean cross-distro path is SDKMAN; lands with that driver (native on
    Arch/brew only otherwise; its release artifact is a `.zip`, which the tar-only tarball
    driver can't take).
  - `deno`, `bun` — ship `.zip`; need a zip-capable fetch path first.
  - `julia` — official binaries aren't github release assets (S3 URLs); needs a bespoke url/
    version story.

### Track B — editors & shells
- **B1  tmux + zsh + fish + nushell.** native everywhere.
- **B2  jetbrains-toolbox.** tarball app (unityhub/kicad pattern).

### Track C — desktop environments  (original scoping — since RESOLVED, see the DONE entry above)
This was the earlier "defer to a validated pass" scoping; the DE track was subsequently shipped
(sweep-verified above). Two findings from it still hold:
- **Finding: variant OS blocks can't work.** Kubuntu/Lubuntu/Xubuntu all ship `ID=ubuntu` in
  os-release — no distinct ID to detect, so a `kubuntu`/etc. block would never auto-activate.
  Dropped the variant-block model; "already-present DE" is handled naturally (metapackage install
  is a no-op when present; inspect reads it as installed).
- **DE metapackage names were the highest unverifiable-in-sandbox risk** (gnome-shell vs gnome vs
  @gnome-desktop; plasma-desktop vs plasma-meta vs @kde-desktop; COSMIC packaging in flux) — which
  is exactly why the shipped names were podman-sweep verified before landing.

### Track D — `configsys request`  (DONE)
- **D1  reportgen coverage matrix.** ✅ `coverage()` probes a representative machine per package
  manager (reusing the loaded layered components); `request_payload`/`render_request`/
  `request_title`; `<!-- configsys-request v1 -->` marker + `component-request` label.
- **D2  `request` command.** ✅ app.py `cmd_request`, argparse `request`, `_send_report`
  generalized (label/save-as), scrub/approve/gh-or-browser reuse. Tests in test_app +
  test_reportgen.
- **D3  reports-repo scaffolding.** ✅ `component-request.yml` issue form, auto-label Action
  extended to both markers, README updated. (In ~/src/configsys-issues — push separately.)

## Parked / notes
- No macOS block yet; if one lands, DE + toolchain matrices extend for free.
- luarocks/opam/sdkman/cabal all have real `list`/`upgrade` verbs → genuine version state (better
  than cargo/pipx's ledger-only lock, but keep lock in the ledger for uniformity).
- Profiles: consider a `languages` / `polyglot` profile once the toolchains land (not in scope
  until the data exists).
