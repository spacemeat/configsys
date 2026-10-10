# Docs-audit bug batch + decisions (2026-10)

> **Status: DONE** — finished 2026-10-10 (bug batch 2a577c0; Homebrew sweep in the following commit; driver-gate follow-ups after). Lives on in: docs/routing-model.md, docs/config-format.md, docs/shell-glue.md, docs/plugins.md, docs/tui-architecture.md

The first full `/update-docs` run (d958cf9, 2026-10-09) reported ~60 places where the code, not the
doc, was wrong. The user asked for every one to be fixed, with regression tests, and for the open
questions to be grilled. This records the decisions so later work doesn't re-litigate them.

## Locked (decided + rationale)

**Model**
- **Uniform layer rule.** Every layer — repo, plugins, primary, top config, and files any of them
  include — may *define* components, profiles, os blocks and drivers. Only the top config and the
  primary may *set* machine settings; an include or ordinary plugin that tries gets a `check`
  warning. User-authored `profiles:` are un-retired as browse categories (they never install;
  `requested()` stays = picks). *Why:* the user wants top levels, plugins and repo to work the same;
  one sentence now explains every layer.
- **Top-config `os:`/`drivers:` are honored** (machine-local tweaks), not ignored.
- **A user pin always wins**, including over `auto-tighten`; when a pin misses a version floor, a
  `!` warning says so and names the fix. *Why:* no surprises, user keeps control.
- **Component-level integer `standing:` ranks providers** (symmetric with binding standing).
- **Detected installs are soft:** a detected pin that fails a version constraint is dropped, never
  an error.
- **Routing-overhaul phase-3 follow-ons retired** (`choices:`, driver-preference → via standing,
  `when:`-scoped standing): each is redundant with an existing mechanism. Phase 5 → DEFERRED.md.

**Homebrew**
- A `homebrew` component; the brew driver requires it.
- **brew is an ordinary method**, ranked just before tarball in the default driver-preference. To
  keep it off musl without making each brew binding *more specific* than an ungated native one (the
  research showed a `when: glibc_linux` gate would have flipped ~110 apt defaults to brew on
  Ubuntu), a new **driver-wide validity gate** `drivers: { brew: { when: "glibc_linux" } }` was
  added: validity-only, no specificity. Brew never replaces a native default; it now wins over
  tarball/sdkman/pipx/cargo/npm/script for ~50–80 components per glibc distro and fills a few gaps.
  Existing installs keep their method (adopt-installed).
- **No brew routes for libraries** (a brew lib lives in brew's prefix, invisible to system builds),
  keg-only formulae (not on PATH), or homebrew's own prerequisites (curl, git — a cycle on
  native-less OSes).

- **Driver gates (follow-ups, same day).** First an explicit AppImage `when:` gate (9e9fc68); then,
  after discussion, it was replaced by the general rule **a driver is valid only where its own
  `requires:` can be met** (the derived gate, `resolve.gated_context`). *Why:* hand-written gates
  duplicate what the routes already know (the AppImage gate had to copy libfuse2's coverage, a snap
  gate would copy snapd's) and go stale; the derived rule fixes snap (not offered where snapd has no
  method), AppImage (musl, atomic, kde_linux), pyenv and any future case with nothing to maintain,
  and makes gcompat a one-step opt-in (`pins: { glibc: gcompat }` — gates read HARD pins only, so an
  opt-in stays explicit). Explicit `when:` gates remain only for facts that aren't requirements:
  brew (glibc; Homebrew refuses musl even with gcompat) and aur (Arch; Void has base-devel too).
  Native managers get no gate: `via: native` already resolves to the OS block's manager, and every
  explicit manager binding was audited as correctly gated.
- **aur ranks right after native** in `DEFAULT_DRIVER_PREFERENCE`. *Why:* the `when: "arch"` on ~60
  aur bindings was a preference hiding in a validity clause (it won 50 Arch defaults by
  specificity). With the rank + the aur gate those clauses were dropped; aur keeps `when: "arch"`
  only where a competitor valid on Arch has a narrower `when:` (13 ArtCraft apps, dbx, tmog,
  wl-screenrec, signal-cli). Net default change: signal-cli on x86_64 Arch, brew → aur.
- **`driver-preference` is a fallback chain:** OS-block lists, then the setting, then the built-in
  default, each adding only the drivers the earlier ones don't name. *Why:* the user's primary
  plugin carried a copy of the old default without brew; once brew became an ordinary method it
  tied last with sdkman/pipx/cargo/opam/go-install/cabal and 11 picks errored. A list still fully
  decides every driver it names; only drivers named in no list tie.
- **Optional driver hooks frozen** into the plugin ABI (no ABI bump — a new promise about existing
  members): the batching, orphan-scan, System Updates and version-signal hooks, `holds_version`,
  `native_backed`, and the helpers `arch_token`, `location_override`, `command_trusted`,
  `untrusted_command_result`. The batch members a batching driver needs were promoted from
  `_batch` / `_batched_version` to `batch` / `batched_version`.

**Glue**
- **conf.d bands:** 00-configsys, 50-<component glue>, 90-<user glue>, 99-user. *Why:* the loader
  already assumed NN- prefixes; component glue was unprefixed and sorted after the user's snippets.
- **Staged installer lines live in machine state; `dotfiles activate` makes them ordinary user
  glue** (correct per-shell extension, visible and drift-checked).
- **Shared loaders carry nothing personal.** The personal PYTHONPATH/`x` alias, citybanner, ps1,
  geg and the shipped gdbinit template moved to the user's `~/cfs-todo/`. The prelude alias is
  `cfs` (was `cf`) and finds the real launcher instead of a hard-coded clone path.

**CLI / TUI**
- `install --picks` / `upgrade --picks` sync this machine's picks non-interactively (plan + confirm
  unless `--yes`).
- `install profile:X` skips members with no route here (notice), never asks.
- Screens may rebind any key, including q ! ? and the screen numbers.
- New settings in the registry: `locations` (machine), `detect-coexisting`,
  `installer-shell-writes`, `installer-shell-writes-allow` (uniform).
- `--pretend` is a true dry run everywhere (CLI, TUI edits, user-config generation).

**Plans**
- method-broadening (sweeps) and source-plugin (spin-outs) stay in docs/todo/; dotfiles-glue-split
  finished (phase 3 = the personal-file move + loader purification).
- configsys-bigdata fixed (glue layout; trust) and listed in Known plugins with configsys-versions
  and configsys-user.

## Defaults chosen by the integrator (user may veto)
- README clone URL shows the public `https://github.com/spacemeat/configsys`.
- The versionreport cache may still be written under `--pretend` (a cache, not state).
- Profile-install of a profile's members does not offer to pick them.
- `CONFIGSYS_PM` / `CONFIGSYS_GLUE_SHELLS` stay documented in configsys(1) as forcing/testing hooks.

## Parked
- Podman name-existence sweep for the new brew formula names.
