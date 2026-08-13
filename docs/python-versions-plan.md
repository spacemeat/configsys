# Python versions as components — design proposal

Status: BUILT (2026-08-12, commits ab3dd8d + f48080d). Originally a proposal; now shipped in base.
general, as components?" Decisions still open — see the end.

## Current state

- **configsys's own floor** lives in the bash bootstrap (`configsys.sh`): it needs a system
  `python3 >= 3.10`, makes the repo `.venv` from it, installs `humon`. It does NOT manage or install
  Python — it assumes the system provides one, and errors telling you to install it if not.
- **No `python3` / `python3.X` component exists.** `python3-pip` and `python3-pipx` are the *tooling*
  components; the `pip`/`pipx` drivers call bare `python3` (the system default). `opencv-python` is the
  `cv2` bindings, not an interpreter.
- **We already have the right engine.** The version-scoped providers built in the routing overhaul
  (`provides: {cap: N}` + `requires: {cap: ">=N"}`, multiple residents coexisting — the cuda-toolkit-11/
  12 pattern) is exactly what "several Python versions installed, pick the right one" needs.

## The two things you actually want

1. Install / upgrade a specific interpreter (3.11, 3.12, 3.13).
2. Have several coexist and "use the right one."

## Proposed model (data-only; reuses the existing engine)

- **One component per version**, each a version-scoped provider of a shared `python3` capability:
  - `python3.11` → `provides: {python3: 3.11}`, `python3.12` → `{python3: 3.12}`, etc.
  - A consumer that needs a floor writes `requires: {python3: ">=3.11"}` → the resolver selects a
    matching installed provider, or pulls one. Identical to how blender/opencv pick a cuda-toolkit.
- **They coexist for free.** On debian/fedora each installs a distinct `/usr/bin/python3.X` binary —
  distinct packages, so this is normal concurrent residency (version-scoped providers), no conflict.
- **Native bindings:**
  - debian/ubuntu: `via: native  packages: [python3.11, python3.11-venv, python3.11-dev]`. Ubuntu's
    NON-default versions come from the **deadsnakes PPA** — add it with the binding's `ppa:` field (the
    same mechanism `gcc-11` uses for `ubuntu-toolchain-r/test`). Debian has some in backports.
  - fedora/rhel: `python3.11`, `python3.12` are native packages.
- **The system default** is an environment capability: the OS block `provides: {python3: <detected>}`
  (probe `python3 -V`). So `requires: {python3: ">=X"}` is satisfied by the system when it's new
  enough, and only pulls a version-package when it isn't.

## "Use the right one" — the selection story (the subtle part)

Coexisting `python3.X` are separate binaries, so there's **no single "active" python to flip** — and
that's good, because the flip is the dangerous part:

- **Never repoint the system `python3` default** (`update-alternatives --config python3`). On debian/
  ubuntu, `apt` and a pile of distro tools hard-depend on the distro's python3; changing it breaks the
  system. configsys must never auto-do this. (A `python-is-python3` alias for bare `python` → `python3`
  is a separate, safe nicety, unrelated to picking a *version*.)
- **The safe, normal selectors** are per-consumer, not global: a tool built for 3.11 calls
  `python3.11`; a project makes a **venv from a specific `python3.X`** (`python3.12 -m venv .venv`).
  This is what "use the right one" means in practice on a distro.
- **pyenv is the user-scope manager** you half-remember: it installs interpreters under `~/.pyenv/
  versions/`, drops **shims** ahead of the system on PATH that intercept `python`/`python3`, and picks
  per-directory via a `.python-version` file (`pyenv local 3.12`) or globally (`pyenv global`). It
  never touches the system python, so it's safe. It could be a **second `via: pyenv` method** on the
  `python3.X` components (a small new driver) — giving safe user-scope multi-version + per-project
  selection. Bigger lift; optional.

## configsys's own 3.10 floor

The bootstrap owns it and should keep owning it — configsys can't install the interpreter it's *running
on* (chicken-and-egg). Modeling it as a component would be informational only. Worth adding: a
`configsys check` warning when the system python is below a recommended floor or nearing EOL, so you
get a heads-up before a dependency needs newer.

## Recommended phasing

- **P1 — data only, no new code:** add `python3.11/3.12/3.13` components (native; deadsnakes `ppa:` on
  ubuntu; `-venv`/`-dev` bundled), version-scoped `provides`; OS-env `provides: {python3: <detected>}`.
  Coexist via the existing version-scoping. Ship a `python3` capability so components can floor it.
- **P2 — optional, one new driver:** a `pyenv` via on the `python3.X` components for user-scope
  multi-version + per-project selection (shims, `.python-version`), for people who don't want system
  packages.
- **Small adjacent win:** let the `pip`/`pipx` drivers optionally target a specific `python3.X` (a
  component field / binding option), so a pipx app can pin its interpreter instead of riding the
  system default.
- **Hard rule:** never auto-repoint the system `python3` default.

## Open questions for you

1. **System packages (deadsnakes, coexisting `python3.X`) or pyenv (user-scope shims), or both** (native
   default + pyenv as an opt-in `via`)?
2. **Which versions** to ship as components — 3.11 / 3.12 / 3.13?
3. Should `configsys check` **warn** when the system python is aging / below a floor?
4. Do you want the **pip/pipx interpreter-pin** (target a specific `python3.X`), or is riding the system
   default fine for now?
