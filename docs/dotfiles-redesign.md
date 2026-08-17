# Dotfiles redesign — two kinds, user-owned links, managed-even-when-empty

Status: **DESIGN AGREED, not built.** Captures the decisions from the design discussion so
implementation can follow without re-litigating. Supersedes the ad-hoc parts of the current
`drivers/dotfiles.py` model (search-path + symlink-to-whatever-root).

## Why

Two genuinely different things wear the "dotfiles" hat, and conflating them causes the bugs:

- **glue** — shell-integration snippets configsys SHIPS (PATH/alias/env/completions/init that make an
  installed tool usable): `btop.sh`, `yazi.sh`, `rust.sh`, … Content is configsys's, lives in the
  repo, and is *kind of part of an app/SDK's installation on this machine*.
- **config** — an app's own user config (`nvim`, `git`, `alacritty`): the USER's, not shipped by
  configsys, and portable across machines.

### The five requirements (verbatim intent)
1. The user must **never lose config data** — first and foremost.
2. The user must **not have to hunt** for that data if it moves.
3. The user is **in control** of when/where data moves/links (local store vs primary plugin).
4. Links **only ever reference** the machine-local store or the **primary plugin's** `dotfiles/` —
   **never the repo** or any plugin the user doesn't own.
5. We can **signify management even when the content isn't there yet** (app installed but hasn't
   written its config; personal config not captured) — and can confidently mark the `-dotfiles`
   component **installed**. (Today an unpopulated `-dotfiles` can't be "installed".)

### The bugs today (that this fixes)
- **Repo links (#4).** With no local store and no user copy, the content search-path falls to the
  repo and links `~/.bash.d/btop.sh → <repo>/dotfiles/bash.d/btop.sh`. ~15 such links exist now.
- **Unpopulated ≠ installed (#5).** No content anywhere → no symlink → `get_version` None →
  "not installed", so we can't say we're managing that location.
- **Orphans.** `cargo.sh`, `python.sh`, `go.sh`, `android.sh` are real (non-symlink) files in
  `~/.bash.d` from older/manual setups — unmanaged cruft to reconcile, never to silently delete.

---

## The design

**The clean seam:** glue lives under `shell/<shell>/`, config under `<component>.cfs/`, and the two
never touch. Glue is per-machine + shell-shaped; config is portable + shell-agnostic.

### Glue (shell integration snippets)

- **Store (machine-local):** `~/.config/configsys/dotfiles/shell/<shell>/<name>.<ext>` — **copies** of
  the repo's glue, per shell. Local store, **not** the primary plugin: glue is how *this box's* tool
  got wired up, it refreshes with configsys, and it stays out of the user's portable git.
- **Copy ALL shells' variants, always.** Switching shells later never re-materializes anything — the
  store is a complete, shell-agnostic picture. (Files are tiny.)
- **Activate per *installed* shell, not `$SHELL`.** `$SHELL` is the login shell only (doesn't change
  on `exec fish`, ignores bash-for-scripts + fish-interactive). Activation = drop a symlink into each
  present shell's include dir; "present" = the shell binary is on PATH. Install a new shell later →
  next `refresh` activates its glue.
- **Hookup is per-shell:**
  - **fish** — native: it auto-sources `~/.config/fish/conf.d/*.fish`. Symlink there, no rc edit.
  - **bash / zsh** — no native drop-in; configsys owns one rc line (`.bashrc` / `.zshrc`) sourcing a
    loader dir it manages. `bash-dotfiles` generalizes into per-shell loader components
    (`zsh-dotfiles`, …); a glue component `requires:` the loader(s) for the shell(s) it activates.
  - **nushell** — structured config, not `source *.sh`; punt, but the layout must not preclude it.
- **Active loader dirs are uniform: `~/.config/<shell>/conf.d/`** (mirrors fish's real dir), for
  bash/zsh/fish/nushell. Collision-checked: only fish reads a `conf.d` (its native, auto-sourced
  one — we use it as intended); bash has no XDG home so `~/.config/bash/` is ours to invent; zsh has
  no `conf.d` convention (`~/.config/zsh/` may be a user's `ZDOTDIR`, which is benign — our `conf.d/`
  just co-locates next to their `.zshrc`); nushell's `~/.config/nushell/conf.d/` is free. TWO caveats
  the uniform NAME doesn't erase: (1) only fish AUTO-sources — bash/zsh still need the configsys rc
  line (the per-shell loader component); (2) fish's `conf.d` is COMMUNAL (user + other tools drop
  there) so our files must be namespaced by component, whereas the bash/zsh dirs are configsys-only.
- **Convention over per-shell specs.** A glue component declares a glue **name** (`btop`), NOT a spec
  per shell. The driver materializes/activates whatever `shell/<shell>/<name>.*` variants exist.
  Today only `shell/bash/btop.sh` exists → bash-only, unchanged. Add `shell/fish/btop.fish` to the
  repo and fish users get it on `refresh` with **zero edits to the component**. (Keeps ~60 glue
  components from each carrying a per-shell block.)
- **Link chain (satisfies #4):** `~/.config/fish/conf.d/btop.fish` (or the bash/zsh loader dir) →
  `~/.config/configsys/dotfiles/shell/<shell>/btop.<ext>` (a COPY). Never the repo.
- **Refresh:** re-copy repo→store for **un-edited** copies (hash-tracked); a copy the user edited is
  now theirs — leave it. (Glue is "part of the app install", so it tracks configsys, but the user can
  fork any snippet by editing the store copy.)
- **Opt-out:** **hobble the `-dotfiles` component** (durable — survives refresh). This is the
  documented gesture (removing a loader symlink is not durable; refresh would re-add). Opting out of
  the glue = opting out of the component.
- **"Installed" (glue):** the store copy exists AND it's activated (symlinked) for each installed
  shell. Glue is *never* empty (content always ships), so there is no managed-but-empty glue state.

### Config (the app's own user config)

- **Store (portable):** the **primary plugin's** `dotfiles/<component>.cfs/` when one is configured
  (rides the user's git), else the machine-local store. User picks per capture (#3).
- **`.cfs` dir = the management marker.** Its existence means "configsys manages this component's
  config." Created on install **even when no content exists yet** — that IS the #5 signal.
- **A tiny manifest inside it** (`<component>.cfs/managed.hu`) records the **dst mapping(s)**
  (`nvim → $XDG_CONFIG_HOME/nvim`). Two reasons: (a) git doesn't track empty dirs, so the
  managed-but-empty state would evaporate on commit/clone without a file in it; (b) startup can read
  it to know where the config goes *before* any content exists — this powers the warn (#2 / #5).
  It's one boring co-located file per component — nothing like a central registry to desync/fat-finger.
- **Multi-spec components** (`config:` + `aliases:`, …): key each spec's content by its `src` name
  inside `.cfs`; the manifest lists all their dsts.
- **Links (satisfies #4):** `dst → <component>.cfs/<src>` (user-owned). Never the repo.
- **"Installed" (config):** `.cfs` exists → **managed → installed**; content present + `dst` is our
  symlink to it → **linked**.

---

## State machine (the "all states" ask)

### config, per spec
| store `.cfs`/content | dst on system | state | action / guarantee |
|---|---|---|---|
| none | — | `unmanaged` | not installed |
| `.cfs` exists, no content | absent | `managed` (installed) | register only; no link |
| `.cfs` exists, no content | **real user file** | `managed` (installed) | **never clobber (#1)**; startup **warns** "capture your existing config" |
| `.cfs` has content | absent / our link | `adopted` | link `dst → .cfs/src` |
| `.cfs` has content | our symlink to it | `linked` | active |
| `.cfs` has content | **real un-adopted file** | `conflict` | refuse; back up to `*.pre-configsys` on `--force` |

### glue, per component
| state | meaning |
|---|---|
| `not-installed` | `-dotfiles` not installed |
| `installed` | store copy materialized + symlinked into every installed shell's include dir |
| `opted-out` | component hobbled → no copy, no link (durable) |

**Link invariant (#4), enforced everywhere:** a link's realpath resolves into the local store or the
primary plugin's `dotfiles/` — assert it; a link into the repo or a non-primary plugin is a bug the
driver refuses to create and `dotfiles status` / startup flags.

---

## Startup checks (#2, #5)

Cheap pass over the managed set (glue store + `.cfs` manifests), warn (never act) on:
- a `.cfs` whose `dst` holds a **real unmanaged file** → "you have `<app>` config that should be
  captured — `configsys dotfiles capture <app>`."
- a `.cfs` **with content** whose `dst` **isn't linked** → "run `configsys dotfiles link <app>`."
- a glue store copy that isn't activated for a present shell → offer to activate.
- the link-invariant check: any managed link pointing into the repo / non-primary plugin → flag.

---

## Naming decisions
- **Store glue dir:** `dotfiles/shell/<shell>/` (shell-neutral parent, per-shell subdir).
- **Active loader dirs:** **uniform `~/.config/<shell>/conf.d/`** for all four (bash/zsh/fish/nushell)
  — mirrors fish's native dir, discoverable, no collisions (see the glue section for the check). This
  replaces the old `~/.bash.d`; the rename rides the migration.
- **Config marker:** `<component>.cfs/` + `managed.hu` manifest.

---

## Migration (one-shot `configsys dotfiles migrate`, run with eyes open — never a surprise on install)
- Materialize each currently repo-linked glue snippet into the store, move `~/.bash.d` → the new
  loader dir, and **re-point the links at the store** (kills the ~15 repo links).
- Install the per-shell rc hookup for each installed shell.
- **Flag** the orphan plain files (`cargo.sh`, `python.sh`, `go.sh`, `android.sh`, …) — report, do NOT
  delete (they may be the user's); let the user decide.
- Leave `*.pre-configsys` backups untouched.

---

## Code touch-points (drivers/dotfiles.py + friends)
- **Split resolution by kind.** Glue: shell-keyed store, materialized-from-repo (copy, hash-tracked).
  Config: `.cfs`/manifest under the capture root. Retire "link to whatever content-root wins."
- **`install`:** glue → copy all shell variants to store + symlink into every present shell's include
  dir (creating the rc hookup via the loader component); config → create `.cfs` + manifest (even
  empty), link when content exists, refuse-to-clobber unchanged (#1).
- **`get_version`:** glue = copy+activation present; config = `.cfs` exists (managed) else linked.
- **New per-shell loader components** (`zsh-dotfiles`, `fish-dotfiles`) — fish is a no-op drop-in.
- **Shell-detection** helper: shell binary on PATH.
- **Startup check** hook (warn-only) + the link-invariant assertion.
- **`dotfiles migrate`** command.
- **Glue components become convention-driven** (declare a name, not per-shell src/dst specs) — the
  binding shape changes; regen golden accordingly.

## Phasing (proposed)
1. **#4 fix + rename + migrate** — the active bug: shell-keyed store, materialize+relink, move to
   `~/.config/bashrc.d`, `dotfiles migrate`. (Bash-only; convention layout in place.)
2. **#5 `.cfs` + manifest + managed state** — config marker, `get_version` "managed", startup warn.
3. **Multi-shell** — `zsh-dotfiles`/`fish-dotfiles` loaders, per-installed-shell activation, first
   non-bash glue variants. (Convention already supports it; this just adds the loaders + variants.)

## Open (small) questions
- Manifest format/name (`managed.hu` vs `.cfs`-as-file) and whether it also records the `src→content`
  layout for multi-spec.
- `refresh` UX when a glue store copy is user-edited (silent-skip vs note).
- Whether `dotfiles migrate` also offers to `capture` unmanaged config it finds at known `.cfs` dsts.
