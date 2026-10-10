# Orphans

> **Status: REFERENCE** — managed-orphans discovery (configsys/orphans.py, `configsys orphans`,
> the `orphans-ignore:` setting, the TUI Profiles install overlay and `uninstall:` queue); maintained.

An **orphan** is something installed on this box that this machine's picks don't account for, but
that configsys could manage: a known component installed outside the picks, or a recipe-less app
from a user-facing manager. Discovery lists them so the user can **track** (pick) them, **remove**
them, or **ignore** them. It is the complement of the detection tier: detection asks "what installed
method should I adopt for a component I'm resolving?"; the orphan scan asks "what's installed that
nothing here resolves to?".

Out of scope: arbitrary files, and anything no enumerable driver can list.

## Two orthogonal fields

An `Orphan` (dataclass: `driver, key, version, component, kind, ignored, tier`) has a **kind** and
an **ignored** status. They are kept separate: an ignored orphan keeps its kind.

**Kind** — `KINDS = ('lurking', 'forgotten', 'foreign')`, a priority ladder (index 0 = most
actionable; when one key maps to several components the lowest-ranked kind wins):

| kind | has a recipe | in a browse profile | meaning |
| --- | --- | --- | --- |
| `lurking` | yes | yes (`Config.profiles_containing`, direct or indirect) | a known component someone curated, not picked here |
| `forgotten` | yes | no | a known component no profile mentions |
| `foreign` | no | — | no component maps to the installed key |

A component in this machine's picks (`Config.requested()`) is never an orphan (`_classify_known`
returns `None`), even when the installed copy came via a different method than the resolved one —
that case belongs to detection, the "also present" line and docs/stranded-installs.md.

**Ignored** — set when any `orphans-ignore` glob (`fnmatch`) matches the orphan's component name OR
its installed key (`_is_ignored`). Ignored orphans are filtered from default output, not dropped.

**Tier** — `Driver.origin_index()`'s OS-origin class for the key (only apt implements it: Debian
Priority; an arch-qualified key falls back to its bare name). `BASE_TIERS = ('required',
'important', 'standard')` marks "the distro ships this".

## The reverse index (`build_reverse_index`)

`{(driver, package_key): [component, …]}` for this machine's context. For every component, every
**candidate** binding (`resolve.candidate_bindings` — all valid ones, not just the default) becomes
a unit (`unit_for_binding`); each unit contributes its `_unit_keys` (`Driver.index_key`, plus
`installed-name` and every `packages:` entry), and a `native_backed` driver (clang, gcc, aur,
native-pkg-file) contributes the same keys again under this OS's native manager, because that's
where enumeration finds them (dpkg lists `clang-18`, not the `clang` driver). Per-driver `name:`
maps apply through unit construction, so `p7zip-full` and `7zip` both map back to one component.
Fidelity matters: a missed name map turns a known package into a foreign (and usually invisible)
one. The same index is the System Updates dedup set (docs/system-updates.md).

## The scan (`scan_orphans`)

Inputs: the active resolved set (`units`, from `routes.resolve_resilient(cfg.requested())`, so one
bad pick is an error, not a brick), plus optional fill-through caches for `installed_index`,
`explicit_keys` and `origin_index`. Cost: one batched enumeration per driver plus set math — no
network, no per-item subprocess.

1. **Active slots** — the `_index_pairs` of every active unit, including native-backed
   cross-slots, so an active clang-18 never resurfaces as an apt orphan.
2. **Drivers scanned** — those of the active units ∪ every driver in the reverse index ∪
   `USER_FACING`; each whose `installed_index()` is non-empty. Today that means apt, dnf, pacman,
   zypper, apk, xbps, brew, flatpak, snap, pip, pipx, npm, cargo, gem, go-install, luarocks, opam,
   wherever present (apk enumerates with one `apk list --installed`, falling back to `apk info -v`
   on apk-tools without `list`). tarball, appImage, script and source have no batch enumeration and
   are not scanned.
3. **Per installed key**, in order: skip if an active slot; skip if `explicit_keys()` is a set and
   the key isn't in it (auto-installed dependency) unless `include_auto`; if the reverse index maps
   it, classify (`lurking`/`forgotten`, or skip when every match is picked); else `foreign` only on
   a `USER_FACING = ('flatpak', 'snap')` driver, or on any driver under `include_foreign_native`;
   otherwise drop it. A foreign orphan in a base tier is dropped unless `include_system`.
4. Sorted by kind rank, driver, component-or-key.

Why the filters: native managers and language installers carry hundreds of dependency packages,
so for them only the **known** intersection is listed by default; flatpak/snap installs are
deliberate user apps and few, so their recipe-less installs are shown. `explicit_keys` (apt-mark
showmanual, dnf `--userinstalled`, pacman `-Qe`, apk's `/etc/apk/world` (every `apk add`ed atom,
`!conflict` entries skipped), brew leaves, xbps `-m`, pip `INSTALLER=pip` +
`--not-required`, npm minus node-bundled) keeps the thousands of packages nobody chose out; a
driver returning `None` (zypper, flatpak, snap, pipx, …) counts every key as chosen. Base-tier
foreign packages are hidden but the tier rides on every orphan, so a user can still opt to manage
even systemd.

## `orphans-ignore:`

A list of name-or-glob patterns (`Config.orphans_ignore`, merged repo < primary < top config).
Its setting nature is **machine** (`actions.SETTING_NATURE`): acknowledged one-offs on this box
land in the top config, not in shared config. `actions.ignore_orphan` appends (idempotent);
`actions.unignore_orphan` removes only a literal entry (a glob must be edited by hand). See
docs/config-format.md.

## CLI: `configsys orphans` (`app.cmd_orphans`)

Report (default): resolves the picks, scans with `include_system=True`, then filters itself.

| flag | effect |
| --- | --- |
| `--driver D` | only that driver's orphans |
| `--foreign` | also recipe-less keys from native/language managers (noisy) |
| `--include-auto` | keep auto-installed dependency packages |
| `--system` | keep base-tier (required/important/standard) foreign orphans |
| `--all` | keep ignored orphans (marked `[ignored]`) |
| `--json` | the filtered list as JSON (`vars(Orphan)`); same filters as the report — base-tier foreign orphans are hidden unless `--system`, ignored ones unless `--all` |

Output groups by driver: `key  version  → component  (kind)`, or `(foreign — no cf recipe ·
<tier>)`. The footer counts known / foreign / ignored and says what's hidden and how to show it.

Action verbs (each returns before any scan):

- `--adopt NAME [--machine M …]` — `actions.stage_adopt`: picks the component on the target
  machines (default: this box's machine) through `actions.set_included`, so it lands wherever that
  machine's picks live (primary plugin by default), and marks it seen. Requires a component name; a
  foreign key has no recipe to adopt.
- `--remove NAME [--yes]` — confirms, then the ordinary remove op (`_dispatch_op(…, 'remove')`)
  through the component's driver. Foreign keys are declined: remove those with the package manager.
- `--ignore PATTERN …` — appends the new patterns to `orphans-ignore`.

Adopting does not install or change anything on disk: the component is already installed, and
picking it makes the next inspect see it as a managed install.

## TUI

**Profiles install overlay (`O`, `toggle-install`).** On by default (`install-overlay:`, nature
uniform). `ProfilesState.overlay()` paints installed underlines immediately from the startup
inspection's enumeration (`orphans.installed_overlay`, no new subprocess), then runs the full
`orphans.install_overlay` (enumeration in parallel + `scan_orphans`) on a daemon thread and folds it
in; a generation counter drops stale results. Non-enumerable drivers are probed per visible row
(`ensure_probes`). Enumeration caches survive membership edits and are dropped only by
`invalidate_overlay` after an execute.

What's drawn: the component name is underlined when installed; the `inst'd` column shows `●`
installed and picked here, `⊙` installed but **not** picked (in the `orphan_lurking` role colour),
`◐` partial, `○` absent, `⊘` no method on this OS, `⮾` queued for uninstall. A browse profile's
`⊙N` badge counts its installed-but-unpicked members. `⊙` reads raw installed state, so it is wider
than the orphan scan (no explicit-keys filter, no per-kind colour). An ignored `⊙` (its name matches
an `orphans-ignore` glob, or the overlay scan marked it `ignored` by name or package key) is drawn in
the dim `info_dim` role instead of `orphan_lurking`, so `.` visibly takes effect at once.

**Keys on the catalog** (configurable in `keys:`, see config.hu):

- `t` / `T` track — picks the component(s): the TUI way to adopt an orphan.
- `C` claim — `ProfilesState.installed_scan` (full catalog, including non-enumerable bindings and
  complete `parts` aggregates), confirm, then picks every installed component on the target
  machines and marks them seen. Adopts a whole existing system at once.
- `x` stage-uninstall — `actions.stage_uninstall`: appends to the top config's `uninstall:` queue.
  Idempotent; it never uninstalls in place (Profiles edits config, not the system).
- `.` orphan-ignore — toggles the cursor component's name in `orphans-ignore`.

**The `uninstall:` queue → Components.** Machine-local, always in the top config (never a plugin).
`Config` exposes it as the reserved `!uninstall` lens (the `!` profile namespace is reserved;
`check` warns on a hand-defined `!…` profile). On Components, `_with_uninstall_node` fresh-probes
queued components (orphans live outside the active set) and adds a `!uninstall` node listing the
present ones; `_seed_uninstall` pre-stages `remove` for them. `X` executes; a successful remove
drains the entry; `c` unstages and drops it from the queue. A queued component that is still picked
is a contradiction `check` surfaces rather than auto-fixes (the next sync would reinstall it).
Components' own `x` stages a session remove op only; it does not write the queue.

## Related

- [docs/system-updates.md](system-updates.md) — reuses the reverse index as its dedup set.
- [docs/stranded-installs.md](stranded-installs.md) — installs of picked components whose route
  changed (switch / unmet / dangling); orphans cover the unpicked side.
- [docs/config-format.md](config-format.md) — `picks:`, `uninstall:`, `orphans-ignore`,
  `install-overlay`.
- [docs/principles.md](principles.md) — no surprises; profiles are browse lenses, picks the install set.
