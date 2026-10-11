# System Updates

> **Status: REFERENCE** — the whole-machine update lane (configsys/sysupdates.py, the `Driver`
> update hooks, `configsys updates` / `upgrade --system`, the TUI System Updates group); maintained.

configsys installs and upgrades a machine's **picks**. Everything else the OS reports upgradable —
base packages, dependencies, flatpak runtimes, snaps — is the **System Updates** lane, so configsys
can be the machine's one updater without modeling the base system as components.

## The reframe: ask the manager, run the manager

configsys does **not** model base-vs-dependency (docs/principles.md, "What we deliberately do NOT
model"). The lane asks each package manager "what is upgradable?" (`Driver.upgradable_index`) and
applies it with that manager's own bulk upgrade (`Driver.upgrade_all`). Nothing is authored per
(distro × version), so a dist-upgrade changes nothing in configsys.

Invariants:

- **Not components.** A System Updates row is the manager's own report: no binding, no
  `provides:`, no pin, no version lock. It never enters resolution or `actions.run_plan`.
- **Within-release only.** `upgrade_all` is each manager's routine upgrade. configsys never runs
  `do-release-upgrade`, `dnf system-upgrade` or any other release jump.
- **Bulk only.** The unit of application is a whole manager, never a package subset. Distro
  managers ship fixes as complete sets; a partial upgrade is the unsafe case (on Arch it breaks
  the system). A per-package targeted upgrade was considered and declined.
- **Held stays held.** A package the manager holds (apt-mark hold, flatpak mask, snap hold, dnf
  versionlock, zypper lock, brew pin, xbps hold) is marked `[held]` and left alone by the
  manager's own bulk command.
- **Never bricks.** Any query failure drops that manager (or the dedup set) silently; the lane
  degrades to "less listed", never to a wrong list.

## Driver hooks

All live on `Driver` (configsys/driver.py) with no-op defaults, so path/build/language drivers
take no part. They are part of the frozen plugin ABI (the "System Updates" and "orphan scan" hook
groups in the driver.py docstring; docs/plugins.md §7), so a code-plugin manager can join the lane
by overriding them. test/test_driver_inventory.py requires every OS block's `native:` manager to
implement `installed_index`, `upgradable_index`, `upgrade_all` and `explicit_keys`.

| hook | returns | default |
| --- | --- | --- |
| `upgradable_index()` | `{key: (installed, candidate)}`, same key space as `installed_index()` | `None` |
| `held_keys()` | set of held keys | `None` (no hold notion) |
| `classify_index(keys)` | `{key: tier}` over `UPDATE_TIERS` | `tier_by_name` per key |
| `update_dedup_key(key)` | the identity compared against the component index | `key` |
| `upgrade_all()` | runner `Result` of the bulk command | `None` |
| `explicit_keys()` | the user-installed set (shared with docs/orphans.md) | `None` (all explicit) |

`upgradable_index` reads the **already-synced** native index; it never refreshes on its own.
`None` means "absent or failed"; `{}` means "up to date". Both drop the manager.

### Refresh styles

Who refreshes depends on the manager's declared refresh style (every native manager is in exactly
one map, test_driver_inventory):

- `app._NATIVE_REFRESH` (apt, dnf, zypper, apk, xbps, brew) — an index-only refresh, safe before
  any install. `app.refresh_native_index` runs it (sudo, except brew) before `upgrade --system`,
  before a TUI bulk apply, and before an ops batch per `refresh-before-execute`; `configsys
  refresh` runs it too.
- `app._FULL_UPGRADE_REFRESH` (pacman) — an index-only `pacman -Sy` would leave a partial-sync
  state that breaks the next `pacman -S`, so the only safe refresh is `pacman -Syu` itself.
  `refresh_native_index` returns `(False, True)` and does nothing; `configsys refresh` asks before
  running the full upgrade. So the pacman lister can't rely on the real sync DB being current —
  see the Coverage notes for how it lists anyway.

## Coverage

`sysupdates.machine_managers` consults this OS's native manager (`routes.cascade.native(block)`)
plus the app managers `_APP_MANAGERS = ('flatpak', 'snap')`. No availability probe: an absent
manager's query fails and it is dropped.

| manager | upgradable | held | bulk (`upgrade_all`) | tiers |
| --- | --- | --- | --- | --- |
| apt | `apt list --upgradable` | `apt-mark showhold` | `apt-get upgrade --with-new-pkgs -y` (sudo, noninteractive env) | Priority |
| dnf | `dnf -q check-update` (exit 100 = updates) | `dnf versionlock list` | `dnf upgrade -y` (sudo) | name |
| pacman | `checkupdates` (exit 2 = none), else `pacman -Qu` (exit 1 = none) | — | `pacman -Syu --noconfirm` (sudo) | name |
| zypper | `zypper --non-interactive -q list-updates` (`LC_ALL=C`) | `zypper locks` (`LC_ALL=C`) | `zypper --non-interactive update` (sudo) | name |
| apk | `apk list --upgradable` | — | `apk upgrade` (sudo) | name |
| xbps | `xbps-install -un` (`update` rows only) | `xbps-query -H` | `xbps-install -Suy` (sudo) | name |
| brew | `brew outdated --formula --verbose` (Homebrew absent → exit 127 → `None`, dropped) | `brew list --pinned` | `brew upgrade` (never sudo) | name |
| flatpak | `flatpak remote-ls --updates`, both scopes | `flatpak mask`, both scopes | `flatpak update -y` | runtime/app |
| snap | `snap refresh --list` | `held` in `snap list` Notes | `snap refresh` (sudo) | name |

Notes on the choices:

- **apt** `--with-new-pkgs` installs newly needed packages (a new kernel ABI) but never removes
  anything, so it matches `apt list --upgradable` without a dist-upgrade's surprise removals.
  apt hides held packages from its upgradable list, so they don't appear as rows at all.
- **pacman / apk / xbps** are rolling: the only safe bulk is a full system upgrade (`pacman -Syu`
  and `xbps-install -Suy` sync as they go; `apk upgrade` runs after the up-front `apk update`), and
  pacman/apk have no per-package hold (`holds_version = False`).
- **pacman lists through `checkupdates`.** Nothing safe refreshes pacman's real sync DB short of
  the full upgrade (Refresh styles, under Driver hooks), so `Pacman.upgradable_index` runs
  pacman-contrib's `checkupdates`, which syncs a temporary DB copy (no root, the real DB untouched)
  and lists what a `pacman -Syu` would bring now. Without pacman-contrib (exit 127) or when it fails,
  it falls back to `pacman -Qu` against the last full sync and says so through the driver's
  `upgradable_advisory()`: `sysupdates.gather(ctx, notes_out)` collects it even when the list is
  empty, `updates` / `upgrade --system` print it under the list, and the TUI adds it to the `!` page
  when its scan lands. The advisory names the `pacman-contrib` component (Arch-only, never pulled in
  automatically).
- **flatpak** keys rows by normalized full ref (`id/arch/branch`, `Flatpak._norm_ref`), so a
  runtime installed at two branches stays two rows, each against its own installed version.
  `update_dedup_key` maps a ref back to the app id for dedup. Detection is commit-based: an
  update is a new commit, often under the same version string (see `Flatpak.outdated_signal`).
- **rpm-ostree is omitted.** On atomic systems the OS block's `native:` is brew (+ flatpak), and
  rpm-ostree is image-based: an upgrade stages a new deployment, not per-package upgradables.
  Forcing it into a per-package list would mislead. Its driver has no `upgradable_index`.

## Tiers

`UPDATE_TIERS = ('kernel', 'core', 'standard', 'apps')` (driver.py) is a fixed, universal set,
ordered most fundamental first, so grouping reads the same on every OS. Each driver maps its own
notion in through `classify_index`; a manager without one falls back to `tier_by_name`:
kernel by name (`linux-image*`/`linux-headers*`/`linux-modules*`/…, `kernel*`, `vmlinuz`), core
for libc (`libc*`, `glibc`, `musl`), else apps.

- **apt** (`Apt.classify_index`, reusing `origin_index` = one `dpkg-query`): kernel by name first;
  Priority `required`/`important` → core, `standard` → standard, otherwise a libc-named package →
  core, else (`optional`/`extra`/unknown) → apps.
- **flatpak**: an id containing `.Platform` or `.Sdk` (platforms, SDKs, GL, codecs, VAAPI) → core;
  everything else → apps.
- Every other manager: the name heuristic. Only apt has a real `standard` tier.

## Dedup against components

The lane lists **upgradable − known**. `sysupdates.managed_keys` is the key set of
`orphans.build_reverse_index` (docs/orphans.md): every `(driver, package_key)` that **any**
component could install here, across all its candidate bindings, per-driver `name:` maps, `packages:`
sets and native-backed cross-indexing (clang/gcc/aur/native-pkg-file under the native manager).
`gather` drops a row when `(manager, update_dedup_key(key))` is in it.

Why method-complete, not picks-only: a component cfs knows (picked, or an orphan you could adopt)
belongs in the component world, with its own row and actions; the lane is the genuinely unmanaged
tail. Since the lane only sees installed packages, covering not-installed keys is harmless. The
two overlap harmlessly (docs/principles.md): the bulk command still patches excluded packages.

## Explicit vs auto-pulled

`UpdateRow.explicit` is membership (of the key or its `update_dedup_key`) in the manager's
`explicit_keys()` (apt-mark showmanual, dnf `--userinstalled`, pacman `-Qe`, zypper's `rpm -qa`
minus libzypp's `/var/lib/zypp/AutoInstalled` and `gpg-pubkey`, apk's `/etc/apk/world`, brew
`leaves --installed-on-request`, xbps `-m`) — every native manager answers, so dimming works on
every supported OS. A manager with no notion (`None`: flatpak, snap) or a failed query reads every
row as explicit. The TUI dims auto-pulled rows in the
standard/apps tiers only; kernel/core are never dimmed. This is emphasis only — everything is
still listed and still upgraded.

## Gathering (`sysupdates.gather`)

`{manager: [UpdateRow]}`. Per manager: `upgradable_index` → `held_keys` → `classify_index` →
`explicit_keys`; rows sorted by key, dedup-filtered; a manager with no remaining rows is omitted.
`UpdateRow` carries `manager, key, installed, candidate, held, tier, explicit`.

## CLI (configsys/app.py)

- **`configsys updates`** (`cmd_updates`) — read-only. Per manager (sorted), sub-grouped by tier
  (`_TIER_LABEL`: kernel / core (base system) / standard / apps & tools), one
  `key  installed -> candidate  [held]` line each (`_print_updates_groups`). With nothing pending it
  suggests `configsys refresh`, since the list is only as fresh as the index.
- **`configsys upgrade --system [--yes]`** (`cmd_upgrade_system`) — takes no names. Refreshes the
  native index first via `refresh_native_index` (non-fatal: on failure it warns and proceeds on the
  cached index; a no-op on pacman, see Refresh styles), gathers,
  previews the same grouped list, confirms (`--yes` skips; a non-TTY without `--yes` exits 1),
  then runs `upgrade_all` for each manager **that has at least one listed row**, then prints the
  reboot advisory (`reboot-advice`; the native manager's `rebootcheck._REBOOT_CHECKS` entry — brew is in
  `_NO_REBOOT_CHECK`, user-space). Exit status is the
  first failing manager's return code (1 when the confirm is declined).

## TUI (Components screen)

- **Background scan.** The TUI run loop calls `sysupdates.start_scan` at startup: `gather` on a
  daemon thread, cached on `ctx._sysupd_groups` (the manager queries take seconds, so startup never
  waits). The loop polls (`scan_busy` / `take_dirty`) and folds the result in with
  `menu._fold_system_updates`, which rebuilds only the tree from the states already held — no
  reload.
- **Invalidate supersedes an in-flight scan.** `sysupdates.invalidate` bumps a scan generation
  (`ctx._sysupd_gen`) and clears the cache under `sysupdates._SCAN_LOCK`; a scan thread stores its
  result under the same lock only if its generation is still current, so a scan started before an
  upgrade or refresh can never land its stale list afterwards. `start_scan` starts a fresh scan
  whenever the running one belongs to an older generation, and `scan_busy` ignores a superseded
  thread still finishing.
- **Rescans.** `R` (refresh) and every executed `X` drop the scan before the Components reload — so
  the rebuilt tree doesn't re-inject stale rows, and the header shows the spinner — and start a new
  background scan after it (`screens/components.py` `_rescan_system_updates`). Staged System Updates
  marks go with the dropped rows; after `R` the note says how many to re-stage once the rescan lands.
- **Header chip.** A spinner + `checking system updates…` while the scan runs (or after an apply
  invalidated it); `⟳ N system updates`
  (`cached_total`) once it lands, hidden at zero.
- **The group.** `sysupdates.tree_injection` adds one synthetic `System Updates` group (a sibling of
  `(other)`, present in every view mode) with one child per non-empty tier, each holding its package
  rows. Rows are display-only `ComponentState`s (`_synthetic_state`): key `sysupd\<manager>\<key>`,
  field `system_update`, always outdated, `locked` = held, full version strings (not
  `clean_version`'d — the change is often only the Debian revision).
- **Bulk action.** With the cursor anywhere in the subtree, `i`/`u`/`I`/`U` stage **every** System
  Updates row (`MenuState.stage_system_updates`, all managers); `x`, select, `v`, `w` and `L` only
  explain "apply in bulk". Outside the subtree, `stage`/`stage_all` skip these rows. Clearing is
  all-or-nothing too: `c` on any System Updates row unstages every one (`MenuState.unstage` →
  `unstage_system_updates`), because execute upgrades a whole manager whenever any of its rows is
  staged — a partial unstage would leave badges that misstate what `X` does.
- **Apply.** `X` → `menu._confirm_and_execute` partitions the synthetic rows out of the per-unit plan
  (they never reach `expand_plan`/`run_plan`), shows one `sys-update` preview line per manager set,
  and after the single confirm runs `sysupdates.apply_bulk` **first** (`refresh_native_index`,
  `upgrade_all` per staged manager, then `invalidate` + `start_scan`), then the per-component ops
  against the fresh base. Base-first means cleaner dependency resolution everywhere and no Arch
  partial-upgrade (`pacman -S <new>` on an un-`-Syu`'d system).

## Declined: a release-upgrade advisory

A "new release available" advisory was declined, not deferred. Only Ubuntu/Pop have a reliable
native probe (`do-release-upgrade -c`, `pop-upgrade release check`); Fedora, openSUSE Leap, Alpine
stable and EL do not, and detecting there would need a cfs-maintained "latest release per distro"
table — the authored base data this design rejects. A partial advisory is worse than none: a
distro-hopper calibrates on seeing it and is then silently unwarned where it's absent
(docs/principles.md, "uniform coverage, or not ship"). Revisit only if every supported non-rolling
distro gains a native probe.

## Related

- [docs/orphans.md](orphans.md) — the reverse index and `explicit_keys` this lane shares.
- [docs/principles.md](principles.md) — no surprises, uniform coverage, base-vs-dep not modeled.
- [docs/config-format.md](config-format.md) — `reboot-advice`, `refresh-before-execute`.
- [docs/stranded-installs.md](stranded-installs.md) — the component-side counterpart for installs
  whose route changed.
