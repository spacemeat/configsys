# configsys — Implementation Plan: Milestone 1 (apt vertical slice)

Goal: prove the entire pipeline end-to-end on **one family (apt)** before adding breadth.
Derived from `docs/PLAN.md`. Each step lists what it produces and how it's verified.

## Target repo layout (M1)

```
bootstrap.sh                  # minimal bash: verify python3>=3.10, .venv, humon; exec app
config.hu                     # rewritten: dev = flat list of routes-resolvable names
routes.hu                     # brace bug fixed
configsys/
  __init__.py
  __main__.py                 # `python -m configsys` entry -> app.main()
  app.py                      # orchestration: load -> resolve -> inspect -> TUI
  paths.py                    # env-overridable path resolution (HOME, config, ledger, ...)
  runner.py                   # shellCmd chokepoint + global --pretend dry-run
  osdetect.py                 # /etc/os-release ID -> routes block name; env override
  troveio.py                  # humon load (from_file/from_string) + hand-emit writer
  config.py                   # load config.hu + ~/configsys.hu overlay -> selected names
  routes.py                   # RouteResolver: cascade walk + ref grammar + deps + dedup
  component.py                # base Component/family op interface (incl lock/unlock)
  componentObj.py             # ResolvedComponent dataclass (name, family, vars, deps)
  installState.py             # live inspect + ledger reconcile -> per-component state
  ledger.py                   # read/write ~/.config/configsys/state.hu (lock intent, mgmt)
  families/
    __init__.py               # registry: family-name -> class
    apt.py                    # Apt family (full op set)
  tui/
    __init__.py
    theme.py                  # 24-bit RGB palette + SGR helpers
    screen.py                 # curses init/teardown, truecolor setup
    menu.py                   # component list, VIM keymap, single-key actions
test/
  conftest.py
  fixtures/{routes,config,configsys,state}*.hu
  test_osdetect.py test_config_overlay.py test_routes_cascade.py
  test_resolver.py test_ledger.py test_apt_family.py
  Containerfile                # ubuntu:22.04 + non-root test user + passwordless sudo
  run-in-podman.sh             # build throwaway image, copy repo, run integration script
  integration_apt.sh           # scripted app run: inspect -> install -> upgrade -> lock -> remove
```

## Data model (dataclasses)

- `ResolvedComponent`: `name`, `family` (e.g. "apt"), `vars: dict[str,str]` (from route dict /
  `$VAR` substitution), `route_fields: dict` (name, urls, paths…), `deps: list[str]` (names),
  `source_addr` (routes.hu node address, for error messages).
- `ComponentState`: `component`, `present: bool`, `installed_version: str|None`,
  `latest_version: str|None`, `locked: bool`, `lock_source: {"native","ledger",None}`,
  `managed_by_configsys: bool`, `error: str|None`.
- `MarkedOp`: enum `{INSTALL, UPGRADE, REMOVE, SET_VERSION, LOCK, UNLOCK}` staged in the TUI.

## Build order (each step is independently verifiable)

### Step 0 — Fixes that unblock everything
- **routes.hu brace bug**: re-nest `firefox`/`chrome`/`arduino` inside the `debian` block
  (remove the premature `}` after `neovim-config`).
- **config.hu rewrite**: `dev` becomes a flat list of names that resolve *today*, e.g.
  `dev: [ vulkan-dev, neovim, firefox, chrome, arduino, btop, fzf, ripgrep, xclip, cargo,
  build-essential, mononoki-nerd ]`. Toolchain names (gcc/clang/pyke/python12/mesa) stay
  parked (see PLAN.md) with a `// TODO` note.
- Verify: both files parse via `.venv/bin/python -c "import humon; humon.from_file(...)"`.

### Step 1 — Foundations (host-side, pure, pytest)
1. `paths.py` — resolves all paths from env with defaults: `CONFIGSYS_HOME`(→`$HOME`),
   config file (`~/configsys.hu`), repo config/routes, ledger dir
   (`$XDG_CONFIG_HOME/configsys` → `~/.config/configsys`), appImage dir, font dir.
2. `runner.py` — `shellCmd(cmd, *, pretend, capture, tui_active, sudo)`; when `pretend`,
   log+return a synthetic `CompletedProcess(returncode=0)`. Absorbs `utilities.py`'s
   `terminal_released`. Single chokepoint for all subprocess calls.
3. `troveio.py` — `load(path) -> Trove` (wraps `humon.from_file`, catches `DeserializeError`
   into a friendly error); `emit_hu(pyobj) -> str` small writer that serializes dict/list/str
   to Humon text (for ledger writes, since troves are read-only).
4. `osdetect.py` — parse `/etc/os-release`; map `ID` (`pop`→`pop_os!`, `ubuntu`→`ubuntu`, …)
   to routes block name; `CONFIGSYS_OS` env override.
- Verify: `test_osdetect.py` (fixture os-release strings → block name),
  round-trip test for `emit_hu` → `humon.from_string` → equal.

### Step 2 — Config + routes engines (host-side, pure, pytest)
5. `config.py` — load `config.hu` (definitions) + `~/configsys.hu` (selector+overrides),
   overlay, resolve `configs: [...]` → the union of named components for active profiles.
6. `routes.py` — `RouteResolver(routes_trove, os_block)`:
   - `_cascade()` — build the ordered OS lookup chain by following `!using`.
   - `resolve(name)` — find the node for `name` in the cascade (first block that has it),
     honoring `*` wildcard (`*: apt\*`); interpret the value:
     - `family\component` ref → bind family + look up family node (dict → vars, incl `$VAR`
       substitution and family-level defaults like `$FONTDIR`).
     - list → each entry resolved independently, all become parts/deps of this component.
     - dict with `package: fam\comp` → indirect binding.
   - Recursively resolve deps; detect cycles; collect into a deduped `dict[name,
     ResolvedComponent]`.
   - Unresolvable name → `ConfigError` with the offending name + OS (surfaced, not crash).
- Verify: `test_config_overlay.py`, `test_routes_cascade.py` (pop_os!→ubuntu→debian inherits
  `*: apt\*`), `test_resolver.py` (neovim → [appImage\neovim, neovim-config] → [ripgrep,
  dotfiles\neovim] → ripgrep→apt; dedup; unresolvable name error; `$FONT*` var substitution).

### Step 3 — Family interface + Apt (host-side units + podman integration)
7. `component.py` — base op interface: `getVersion, install, uninstall, upgrade, setVersion,
   lockVersion, unlockVersion`, each taking a `ResolvedComponent` + `runner`. Add the two
   lock ops the current base lacks.
8. `families/apt.py` — rewrite the broken file against the interface, using `runner.shellCmd`:
   - `getVersion` → `dpkg-query -W -f='${Version}' NAME` (returncode/parse).
   - `getLatest` → `apt-cache policy NAME` (Candidate).
   - `install/upgrade/uninstall/setVersion` → sudo apt-get … (setVersion with
     `--allow-downgrades NAME=VER`).
   - `lockVersion/unlockVersion` → `apt-mark hold/unhold`; lock intent also mirrored to ledger.
   - `isLocked` → parse `apt-mark showhold`.
9. `families/__init__.py` — registry mapping `"apt"` → `Apt` (extensible later).
- Verify: `test_apt_family.py` with mocked runner asserts exact command strings for each op
  (incl. sudo + pretend). Integration via podman in Step 5.

### Step 4 — Install state + ledger (host-side units)
10. `ledger.py` — read/write `state.hu` (per-component: `locked`, `managed`, `pinned_version`);
    writes via `troveio.emit_hu`. Missing file → empty ledger.
11. `installState.py` — `inspect(resolved: dict) -> dict[name, ComponentState]`: for each
    component, dispatch to its family for `getVersion`/`getLatest`/`isLocked`, union native +
    ledger lock state, flag configsys-managed items. `--pretend`-aware (read-only ops still run).
- Verify: `test_ledger.py` (round-trip, lock intent persists); inspect test with mocked
  family returns → correct `ComponentState`s.

### Step 5 — Podman integration harness
12. `test/Containerfile` — `ubuntu:22.04`, create non-root `tester` with passwordless sudo,
    install `python3`+`python3-venv`, copy repo.
13. `run-in-podman.sh` — build a throwaway image, run `integration_apt.sh` as `tester`:
    bootstrap → resolve `dev` → inspect (nothing installed) → install a small real pkg
    (`btop`/`fzf`/`xclip` from routes.hu) → verify present+version → lock → verify hold →
    upgrade (no-op) → unlock → remove → verify gone. Exit non-zero on any mismatch.
- Verify: `bash test/run-in-podman.sh` green; host untouched (all in container).

### Step 6 — Bootstrap + entry
14. `bootstrap.sh` — verify `python3 -c 'import sys; assert sys.version_info>=(3,10)'`
    (or install hint), ensure `.venv` (`python3 -m venv .venv`), ensure humon
    (`.venv/bin/pip show humon || pip install humon`), then
    `exec .venv/bin/python -m configsys "$@"`. Idempotent; `--pretend` passthrough.
15. `__main__.py` / `app.py` — arg parse (`--pretend`, `--os`, `--home`, profile override),
    first-run generation of `~/configsys.hu` from repo template, then load→resolve→inspect→TUI.
- Verify: `bash bootstrap.sh --pretend` on host runs read-only to the TUI without mutating
  anything.

### Step 7 — Curses TUI
16. `tui/theme.py` — 24-bit RGB palette; `fg(r,g,b)/bg(...)` SGR helpers; state colors
    (installed=green, outdated=yellow, missing=grey, locked=blue, marked=inverse).
17. `tui/screen.py` — curses init/teardown, raw mode, alt-screen, truecolor; integrates with
    `terminal_released` when shelling to sudo/apt mid-session.
18. `tui/menu.py` — component list grouped by family; VIM nav (`j/k/g/G`, `/` filter);
    single-key marks (`i`nstall, `u`pgrade, `x`remove, `L`ock, `l`unlock, space=toggle,
    `A`ll-in-view); `Enter`/`X`ecute applies staged `MarkedOp`s with a confirm summary
    ("no surprises"); `q`uit.
- Verify: manual run in podman (interactive) + a scripted non-interactive `--pretend` path
  that prints the planned ops for assertion.

## Milestone 1 status: COMPLETE (2026-07-13)

All steps landed and committed (Step 0–7 + Step 5b prerequisites). 83 host-side
pytest cases pass; the podman apt lifecycle and the repo-component prerequisite
cycle both PASS in-container with the host untouched.

## Acceptance criteria for Milestone 1
- `bash test/run-in-podman.sh` performs a real apt install→lock→unlock→remove cycle of a
  routes.hu component inside ubuntu:22.04 and exits 0, host untouched.
- Host-side `pytest` green for osdetect, config overlay, cascade, resolver, ledger, apt-family.
- `bash bootstrap.sh --pretend` on the host reaches the TUI and mutates nothing.
- Resolving `dev` on pop_os! yields the expected deduped component set with apt bindings via
  the `*` wildcard inherited from debian, and reports a clear error for any unroutable name.

## Deferred to later milestones (per PLAN.md Parked)
Flatpak/appImage/font/dotfiles families; qemu/kvm VM harness; conflict-resolution UX;
toolchain routes; non-Debian OS families.
