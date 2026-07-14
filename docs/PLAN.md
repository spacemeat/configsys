# configsys — Plan & Decisions

Living source of truth for design decisions. Updated as we grill/build.
Last grill: 2026-07-13.

## Locked (decided + rationale)

1. **Minimal bash bootstrap → python handoff.** `bootstrap.sh` verifies python3 ≥ 3.10,
   ensures `.venv` exists, ensures `humon` is installed, then execs the python app. Only
   python3 + humon are guaranteed before python takes over. *(On this machine all three
   already exist — bootstrap is idempotent verification, not first-time install.)*

2. **Config sync boundary: repo-shared definitions, per-machine selector.**
   Profile *definitions* live in the repo's `config.hu` (git-synced, shared across machines).
   `~/configsys.hu` is generated from a repo template on first run and holds only this
   machine's `configs: [ ... ]` selection plus optional local overrides. Loader reads both
   troves and overlays: `config.hu` = source of truth, `~/configsys.hu` = thin selector.

3. **Install-state truth: live query + small ledger.**
   Every run inspects the real system (`dpkg-query`, `flatpak list`, appImage dir, font dir)
   for presence/version. A small local ledger stores only what the OS can't: version-lock
   *intent* and configsys-managed appImage/font bookkeeping. `InstallState.inspect()` is a
   live reconcile, not a manifest read. Lock state = union of native (`apt-mark hold`) + ledger.

4. **TUI: stdlib `curses` + 24-bit RGB.** No pip deps beyond humon; bootstrap stays minimal.
   Hand-managed truecolor SGR, VIM-style keymap dispatch, single-key actions. `utilities.py`'s
   terminal-release stays relevant for shelling out (e.g. sudo/apt) mid-TUI.

5. **Profile model: flat list of component names.**
   A profile is a flat list, e.g. `dev: [ vulkan-dev, neovim, firefox, ... ]`. The resolver
   resolves each name through `routes.hu` (recursive deps + family binding), then unions +
   dedups into the working set. No grouping layer. A name with no route on the current OS is
   a surfaced config error ("no route for `pyke` on pop_os!"). The TUI organizes the view by
   an intrinsic axis (profile → family), not user-authored groups.

6. **`routes.hu` owns ALL install/dependency/family semantics.** The profile only *names*
   what's wanted. Routing (family binding via `family\component`, `*` wildcard, `!using`
   OS cascade, list-as-multipart, dict-as-vars) lives entirely in routes.hu.

7. **Testing sandbox: rootless podman + host-side pytest; VM later.**
   - Pure logic (resolver, cascade walk, ref-grammar, dedup, config overlay, ledger) is tested
     host-side with **pytest** using fixture `.hu` files and a mocked command runner — no
     sandbox, instant.
   - Destructive apt integration runs inside **rootless podman `ubuntu:22.04` (jammy)** —
     disposable, host-root-safe, matches the host codename, and exercises the ubuntu→debian
     `!using` cascade.
   - A **qemu/kvm VM** (HW virt available) is reserved for later flatpak/appImage FUSE/dbus
     fidelity — not built for the apt slice.
   - **Testability is a design constraint, not an afterthought:** (a) every `$HOME`-derived
     path is env-overridable so a run can target a scratch dir; (b) a global `--pretend`
     dry-run mode where the single `shellCmd` chokepoint prints commands instead of executing;
     (c) an OS-detection override env var so the cascade is testable off-distro.

8. **OS detection maps os-release → routes block.** Read `/etc/os-release` `ID` (+ `ID_LIKE`),
   map to the routes.hu block name (`ID=pop` → `pop_os!`), then walk `!using` upward. The
   detected OS is overridable via env for testing.

9. **System prerequisites are encoded in routes.hu and executed by the family.**
   If a component needs system-level setup to install — an apt archive component enabled
   (`universe`), a third-party signing key + source list added (lunarg vulkan) — that setup
   is declared as fields on the component's route and performed (idempotently) by the family
   *before* install. The tool never assumes a prerequisite is already satisfied. apt schema:
   - `repo-component: universe` (value or list) → `add-apt-repository -y <c>` then update
   - `pubkey-url` + `pubkey-path` → download signing key to the path
   - `source-url` + `source-path` → download the .list to sources.list.d, then update
   Prereqs run only when not already present (file existence / cheap checks) to avoid
   needless `apt-get update`s. This is why `vulkan-sdk` carries lunarg key/source fields.

## Parked (deferred on purpose + why)

- **Toolchain routes** — `gcc`, `clang`, `pyke`, `python12`, `mesa` in the current
  `config.hu` have no `routes.hu` entries yet. Park route authoring for these; the initial
  `dev` profile uses only names that resolve today.
- **Non-Debian families** — `routes.hu` only has the `debian → ubuntu → pop_os!` cascade and
  apt/flatpak/appImage/font/dotfiles families. `dnf`/`pacman`/`AUR`/macOS parked until the
  apt slice is proven.
- **Overlap/conflict UX detail** — set-union dedups overlapping components for free; the
  "family conflict, user must resolve" notification flow is parked until multi-family is live.

## Open / defaults (proposed — user can veto)

- **D1 — First milestone = apt vertical slice.** Prove the whole pipe on one family:
  bootstrap → load config+routes → resolve `dev` → live-inspect via `dpkg-query` → curses
  view of per-component state → single-key install/upgrade/remove/lock/unlock via the Apt
  family. Add flatpak/appImage/font/dotfiles families only after the slice works end-to-end.
- **D2 — Entry point.** `python -m configsys` via `configsys/__main__.py`; `bootstrap.sh` at
  repo root is the human entry.
- **D3 — Ledger.** `~/.config/configsys/state.hu`, humon format. Because troves are read-only,
  writes hand-emit humon text (small writer helper) rather than mutating nodes.
- **D4 — Family engine.** One class per family (Apt, Flatpak, AppImage, Dotfiles, Font)
  implementing the full op set: `getVersion, install, uninstall, upgrade, setVersion,
  lockVersion, unlockVersion`. Extend `component.py`'s base to include lock/unlock (currently
  missing).
- **D5 — Dotfiles = symlink.** Symlink `repo/dotfiles/<component>` → target path (resolved via
  the component's env-var paths). Edits flow back to the git repo. Copy mode overridable later.
- **D6 — Privilege.** Native/system ops (apt) run via `sudo` inside the `terminal_released`
  context so sudo can prompt cleanly. User-scoped families (flatpak `--user`, appImage, fonts,
  dotfiles) run without sudo.
- **D7 — humon API fix.** Existing Python uses the stale `Trove.fromFile` API. Rewrite to
  `humon.from_file(...)` / `.root` / node navigation per the installed 0.1.0 binding.
- **D8 — Land bug fixes early.** (a) `routes.hu` brace bug — `firefox`/`chrome`/`arduino`
  currently dangle outside the `debian` block; (b) `apt.py` syntax error (stray `:`) +
  ctor/interface mismatch + unset `self.version`; (c) `componentObj.py` stub (`findBestFit`
  missing `self`, ignores trove); (d) rewrite `config.hu` `dev` to a flat list of
  routes-resolvable names.
- **D9 — Resolver ref grammar.** Implement parsing of `family\component`, `*` wildcard,
  `!using` cascade walk, list-as-multipart, dict-as-vars (`$VAR` substitution, used by fonts).

## Open-questions backlog (future rounds)

- Exact ledger schema (per-component records: lock intent, installed-by-configsys flag,
  managed path, pinned version).
- Conflict-resolution UX when two components bind the same family target differently.
- Dotfiles path/env-var convention per component (how neovim's config path is declared).
- Version-lock semantics for families with no native hold (appImage, font).
- macOS / non-apt family command sets.
