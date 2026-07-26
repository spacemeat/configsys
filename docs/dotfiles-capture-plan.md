# Dotfiles: capture / adopt + clobber-proof linking — plan

## Problem

Dotfiles content lives in a `dotfiles/` dir next to the `.hu` that *defines* the component, so a
repo-shipped dotfiles component ships a **template**. Installing it displaces your real config with
that template (it backs the original up to `<dst>.pre-configsys`, but a second install can clobber
that backup, and the disruption is silent). The tree already flinches from this: `neovim-dotfiles`
ships its `config:` line **commented out** with a "I would never clobber your config" warning — the
model can't safely ship a dotfile that has a live on-system counterpart, so it punts.

Two things are missing: (1) a way to **adopt** your existing on-system dotfiles into your own
content store so the symlink points at *your* content, and (2) making the link **refuse** to run
over anything you haven't adopted.

## Locked decisions

1. **Content search-path (consumption).** The dotfiles driver resolves a component's `src` against
   an ordered set of content roots, first hit wins:
   1. `~/.config/configsys/dotfiles/<src>` — machine-local
   2. `<primary-plugin>/dotfiles/<src>` — git-tracked, portable
   3. `<defining-layer>/dotfiles/<src>` — the repo/plugin template (today's only root)

   Capture just *fills* a root; components are **never redefined**. The no-plugin fallback is just
   "root #2 is absent," so it needs no layer/discovery machinery.
2. **Refuse until adopted (linking).** `install` will not symlink over a real, non-symlink `dst`
   whose resolved `src` is still the **template** (root #3) — it errors and points you at `capture`.
   `--force` restores the old back-up-and-replace. Clobbering becomes a deliberate act.
3. **Plugin if present, else local (storage).** `capture` writes to the primary plugin's
   `dotfiles/` when a primary plugin is declared+synced, else `~/.config/configsys/dotfiles/`. Read
   precedence is always local > plugin > template, so a machine-local file can still override.

## The `capture` command

`configsys dotfiles capture [<component>...]` — default target is **every `via: dotfiles`
component in the active profiles**; optional names filter it.

For each link spec `{src, dst}` (from the driver's existing `_specs`):

| on-system `dst` | action |
| --- | --- |
| a real file/dir, **not** yet in a user root | **copy** `dst` → `<store>/<src>` (recursive for dirs) |
| already our symlink into a content root | skip — already managed |
| doesn't exist | skip — nothing to adopt (noted) |
| already present in `<store>/<src>` | skip unless `--force` — don't clobber committed config |

`<store>` = primary-plugin `dotfiles/` (decision 3) else `~/.config/configsys/dotfiles/`.

**Safety properties:**
- **Never writes to the system side** — it only *reads* `dst` and writes into the store. It cannot
  harm an on-system dotfile, by construction (the opposite direction from install).
- **Preview + confirm** (like `report`/`request`): prints the table of what will be copied where,
  and to which store, then asks before writing. `--dry-run` prints and stops; `--yes` skips the
  prompt for scripting.
- **Refuses to overwrite** existing store content without `--force` — the "hard to overwrite"
  applies to your *committed* config too, not just on-system files.

Result of the round-trip: after `capture` then `install`, `~/.config/nvim` → `<store>/neovim`,
which holds *your* adopted config; it's in git (if the store is your plugin); editing it flows back
to git per the existing sync design. `neovim-dotfiles` can then **un-comment its `config:` line** —
capture is exactly what makes shipping it safe.

## Clobber-proof linking

In `DotFiles.install`, a Python-side pre-flight before the `ln` script:

```
for (src, tgt) in pairs:
    if tgt exists and is not a symlink:
        if resolved src root is a USER root (local/plugin):   # adopted
            back up tgt -> tgt.pre-configsys, then link       # safe: link points at your content
        elif force:
            back up tgt -> tgt.pre-configsys, then link       # old behavior, opt-in
        else:
            return error: "<tgt> exists and isn't managed by configsys —
                           run `configsys dotfiles capture` to adopt it, or --force"
```

So: `dst` absent → link freely; `dst` adopted → link (with backup); `dst` real + only a template
exists → **refuse**. `--force` (a new flag on `install`, threaded to the dotfiles link step) always
does the backup-and-replace.

## Implementation sketch

- **`configsys/paths.py`** — add `user_dotfiles_dir` (`state_dir / 'dotfiles'`). The app computes
  the ordered overlay roots `[user_dotfiles_dir] + ([<primary>/dotfiles] if primary synced else [])`
  and stashes them (e.g. `paths.dotfiles_overlay_roots`); the driver reads them via `getattr`
  (default `[]`, so existing hand-built rc/tests are unaffected).
- **`configsys/drivers/dotfiles.py`**
  - `_resolve_src(src, rc)`: walk `overlay_roots + [defining_root]`, return the first existing
    (else the defining path, for a clean "source missing" error). `_pairs` uses it — so
    `get_version`/`location`/`uninstall` all follow the same precedence automatically.
  - `install`: the pre-flight above; honor a `force` flag; keep the `absorb-into` path.
- **`configsys/app.py`**
  - `dotfiles` subcommand group; `cmd_dotfiles_capture` (resolve active dotfiles units → specs →
    preview → confirm → copy → report). A `dotfiles status` view (managed / adopted / unmanaged /
    template-only) is a cheap, high-value companion — proposed, see below.
  - `install --force` → thread to the dotfiles link step.

## Open / defaults (overridable proposals)

- **Command surface**: ship `capture` + a read-only `dotfiles status` (shows each active dotfile's
  state: linked, adopted-not-linked, real-unmanaged, template-only, absent). `status` is where the
  paranoia pays off — you see what's at risk before touching anything.
- **Secrets**: capturing into a plugin that you later `git push` can commit private material (keys,
  tokens). Default: capture prints the full destination list in the preview and, when the store is
  a plugin, prints a one-line "this will be committed if you push <plugin>" caveat. (A skip-list /
  `.gitignore` seeding is a possible follow-up, not v1.)
- **Primary declared but not synced**: `capture` errors ("sync your primary plugin first") rather
  than silently falling back to local — no surprises about *where* your config landed.
- **Copy fidelity**: preserve mode bits; copy dirs recursively as-is (no VCS-junk filtering in v1).
- **`absorb-into` components** (e.g. `bash-dotfiles` → `~/.bash_aliases`): capture copies the
  on-system `dst` like any other; the absorb dance stays an install-time concern.
- **Ledger**: capture is a content operation; it records nothing in the state ledger.

## Test plan

- `_resolve_src` precedence: local > plugin > template; falls back to template path when absent.
- `capture`: copies a real dst into the store; skips already-managed symlinks; skips absent dst;
  refuses to overwrite existing store content without `--force`; **never** modifies the system side
  (assert `dst` unchanged after capture).
- `install` refusal: real unmanaged dst + template-only src → error, dst untouched; after `capture`,
  same install links (with `.pre-configsys` backup); `--force` links without capture.
- Fallback: no primary plugin → store is `~/.config/configsys/dotfiles/`.

## Phasing

1. **DONE** — content search-path (`_resolve` over local → primary-plugin → defining-layer),
   `Paths.user_dotfiles_dir` + app-wired `primary_dotfiles_dir`, and — per the "no templates"
   clarification — install now **skips an unpopulated spec** (declared src/dst, no content
   anywhere) gracefully instead of erroring. Plus `dotfiles status` (linked / adopted / unmanaged
   / template / empty). Behavior-preserving where content exists; existing tests green.
2. **DONE** — `dotfiles capture [names] [--force] [--dry-run] [--yes]`: copies each active
   dotfile's real on-system `dst` into the store (plugin if synced, else local); preview + confirm
   (with a "committed if you push" caveat for a plugin store); skips already-linked / absent /
   already-in-store (force to overwrite). **Read-only on the system side** — only reads `dst`,
   only writes the store. `status` now also shows the MANAGED SRC location (where your copy is, or
   `→` where capture will put it).
3. **DONE** — `install` refuses to symlink over a real, un-adopted `dst` whose src is still a
   template (adopted content links freely; an `absorb-into` spec keeps its own safe relocation;
   an unpopulated spec is already a no-op). The refusal prints an actionable message ("adopt with
   `dotfiles capture`, or --force"). `install`/`upgrade --force` restore backup-and-replace.
4. **DONE** — un-commented `neovim-dotfiles`'s `config:` (now safe) and deleted the shipped
   `dotfiles/neovim` (a real personal nvim config), `dotfiles/htop`, `dotfiles/containers`
   templates. configsys now ships zero personal config: neovim/htop/podman dotfiles declare
   src+dst but no content, so they're `empty`/`unmanaged` until you `capture`. Golden regen
   (neovim-dotfiles gained the config spec). Refusal is presented as advisory guidance, not a
   `report`.

Only functional plumbing still ships in `dotfiles/` (the `bash.d/*.sh` loaders + `bash_aliases`
+ `gdbinit`) — configsys's own machinery, not anyone's personal config.
