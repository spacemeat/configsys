# Review: dotfiles + glue drivers, shellguard, shipped content

Scope: `configsys/drivers/glue.py`, `configsys/drivers/dotfiles.py`, `configsys/shellguard.py`,
`glue/` + `dotfiles/` content roots, tests `test_glue_driver.py` / `test_dotfiles.py` /
`test_shellguard.py` / `test_coexistence.py`. Read-only; every claim below was verified by reading
(and, for the `re.sub` bug, by running the real shipped snippet through the exact expression).

Terminology used here, per docs/dotfiles-glue-split-plan.md: **dotfiles** = an app's own config
under `<comp>.cfs/` + `manifest.hu` (`via: dotfiles`, `dotfiles/` roots); **glue** = shell
snippets in `~/.config/<shell>/conf.d/` (`via: glue`, `glue/` roots); **inline/gestalt shells** =
elvish + nu, whose rc marker block inlines the concatenated conf.d.

## Themes

1. **The split is done in the drivers but NOT in shellguard, the CLI, or the docs.** `shellguard`
   stages and activates "glue" into the *dotfiles* capture root using the pre-split
   `dotfiles/shell/<shell>/` layout the glue driver no longer reads, always with a `.sh` extension
   (so zsh/fish/elvish/nu activations are never loaded), and the whole feature hangs off
   `configsys dotfiles staged|activate|discard`. `dotfiles status` still prints glue rows;
   `actions.dotfiles_units` returns both drivers with a "Phase 2 will split" comment; the redesign
   doc still says "not built" and names `dotfiles/shell/` as the glue store. This is the single
   largest source of conflation.
2. **Requirement #1 ("never lose config") has holes on the glue side.** Glue `install` does
   `ln -sfn` over whatever sits at `conf.d/<name>.<ext>` with no refusal/backup (fish's conf.d is
   communal by the design doc's own admission); `_link_bash_aliases` silently replaces a foreign
   `~/.bash_aliases` symlink and overwrites an existing `.pre-configsys` backup; and **`--pretend`
   is not honoured** for any Python-side filesystem mutation (rc-file rewrites, store
   materialisation, the `~/.bash_aliases` rename, `.cfs` stamping), only for the bash `ln` step.
3. **Two 100-line copies of the same "linked content" driver.** `_home/_env/_expand/_defining_root/
   _content_roots/_store_path/_materialize_to/_resolve`, the `ln -sfn` script builder incl. the
   ELOOP-coincidence skip, `uninstall`, `get_version`'s realpath loop, `location`, and the
   lock/unlock stubs are duplicated between `glue.py` and `dotfiles.py` (~140 lines, ~20% of each
   file); shellguard re-implements a third copy of "make executable + symlink into conf.d" and a
   third `_SHELL_CONFD` map. The `absorb-into` semantics exist twice (shell script in dotfiles,
   Python in glue). A `LinkedContentDriver` base + a per-shell `ShellSpec` table would collapse
   most of the branchy `if shell == 'bash'` / `in _INLINE_SHELLS` / `_SHELL_RC.get(...)` logic.
4. **Inline-shell block regeneration is fragile and expensive.** The marker block is spliced with
   `re.sub(pattern, block, ...)` where `block` is user/plugin content: backslash sequences are
   interpreted as replacement escapes (verified: `\t` in the shipped `00-configsys.{elv,nu}` is
   mangled into a real tab; a `\1` or `\d` anywhere would raise `re.error` and abort the op). The
   block, plus every `#!cs-eval` subprocess, is regenerated on every single (de)activation, so the
   TUI's `A` (activate-group) is O(N²) in snippets and spawns each generator command N times.
5. **Performance parity gap: bash/zsh/fish never got the location cache.** 49 of 77 bash snippets
   and 98 zsh+fish snippets still spawn `configsys location <x>` (a full Python start, ~250 ms
   each per the code's own comments) on every interactive shell start; only elvish/nu read
   `glue-locations.tsv` via `cs-loc`. Separately, `_installed_shells()` (5× `shutil.which` + a cache
   file read + up to 20 globs) is recomputed for every spec of every unit on every
   `get_version`/`spec_states` call.
6. **Test coverage is decent on happy paths, thin on the safety edges.** Nothing exercises:
   pretend-mode side effects, a real file pre-existing at a glue conf.d target, backslashes in an
   inline block, `#!cs-eval` on elvish, shellguard activation for zsh/inline shells, `capture`
   through symlinks, backup-over-backup, CRLF rc files, malformed `manifest.hu`.
   `test_coexistence.py` is about `installState` coexistence and does not touch this scope at all.

---

## Findings

### [HIGH] security/data-loss — glue `install` clobbers a real file at the conf.d target
- `configsys/drivers/glue.py:636-640` — the generated script is `if [ -e src ]; then mkdir -p …;
  ln -sfn src tgt; …` with no check on `tgt`. `-f` replaces a regular file silently.
- Why: fish's `~/.config/fish/conf.d/` is communal (docs/dotfiles-redesign.md:64-66 says so
  explicitly); a user who hand-wrote `~/.config/fish/conf.d/fzf.fish` loses it the moment
  `fzf-glue` is activated (TUI `a`/`A`, or transitively via `suggests:` on a normal install). The
  dotfiles driver refuses/backs up in the same situation (`dotfiles.py:586-600, 632`); glue has no
  equivalent, and `uninstall` (`glue.py:678`) can restore nothing.
- Recommend: mirror the dotfiles pre-flight — if `tgt` exists and is not a symlink, either refuse
  (advisory Result, like dotfiles) or `mv` it to `<tgt>.pre-configsys` and restore on uninstall.
  Add a test with a pre-existing real file at the fish conf.d path.

### [HIGH] correctness/no-surprises — `--pretend` does not cover Python-side filesystem mutations
- `glue.py:622` (`_materialize_to` copies into the store), `glue.py:647-648` → `_ensure_shell_loader`
  (`glue.py:427-428` rewrites `~/.zshrc` / `rc.elv` / `config.nu`; `glue.py:445-456`
  unlinks/renames the user's real `~/.bash_aliases`), `glue.py:682-683` (uninstall regenerates the
  inline block), `dotfiles.py:568` (`_ensure_marker` writes `.cfs/manifest.hu` + `.gitignore`),
  `dotfiles.py:604-606` (`_materialize`), `dotfiles.py:452-496` (`relocate`), `dotfiles.py:406-450`
  (`capture` — the CLI guards it at `app.py:3320`, the TUI `manage` path at `menu.py:5558` does not).
- Why: only `self.runner.run(...)` respects `Runner.pretend`; every direct `Path`/`shutil`/`os` call
  runs for real. No driver in `configsys/drivers/` checks `runner.pretend` (grep confirms), and
  neither op loop (`app.py:678-705`, `menu.py:540-560`) guards it. A `configsys --pretend install
  shell-glue` edits `~/.zshrc` and moves `~/.bash_aliases`.
- Recommend: route all mutations through one Python-side "fs op" helper on the shared base driver
  that no-ops (and echoes) under `runner.pretend`; add a pretend test asserting `$HOME` is untouched
  after `install`/`uninstall` of a loader + a snippet + a config unit.

### [HIGH] correctness — inline-shell rc block spliced with `re.sub` using content as the replacement string
- `glue.py:422-423` — `re.sub(re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?', block, existing, flags=re.DOTALL)`.
- Why: `block` (`_inline_block`, `glue.py:348-376`) is raw snippet text and `#!cs-eval` stdout. Python
  processes backslash escapes in a string replacement: `\t`/`\n` become real characters, `\1`
  becomes a group reference, `\d` raises `re.error: bad escape`. Verified against the shipped
  `glue/shell/elvish/00-configsys.elv` and `glue/shell/nu/00-configsys.nu` — both are mangled today
  (currently only inside comments and elvish's `str:split "\n"`/`"\t"`, so it happens to still run).
  The first activation uses concatenation (`glue.py:425-426`) so the bug only appears from the second
  (de)activation on — which is every real use. `_remove_shell_loader` (`glue.py:486-487`) is safe
  because its replacement is the literal `'\n'`.
- Recommend: `re.sub(..., lambda m: block, ...)` (or slice on `str.find` of the markers, which is
  also clearer). Add a test whose snippet contains `\1` and `\d`.

### [HIGH] conflation/correctness — shellguard stages+activates "glue" into the DOTFILES root, old layout, always `.sh`
- `shellguard.py:94-97` (`_capture_root` → `primary_dotfiles_dir`/`user_dotfiles_dir`),
  `shellguard.py:189-201` (`activate` writes `<dotfiles-root>/shell/<shell>/<component>.sh` and links
  `conf.d/<component>.sh`), `shellguard.py:175-178` (its own `_confd` map), `app.py:628-631`
  (`_shell_glue_root`), `app.py:3141-3197` (`dotfiles staged|activate|discard`).
- Why, three concrete breakages: (1) the glue driver's roots are `user_glue_dir`/`primary_glue_dir`/
  `<layer>/glue` (`glue.py:226-237`); `dotfiles/shell/…` is never read, so an activated staged block
  is invisible to `spec_states`, the Glue TUI, drift detection, and `disabled-drivers`. (2) The zsh
  loader sources `{confd}/*.zsh` (`glue.py:86-87`) and the inline loaders filter on `.{ext}`
  (`glue.py:361`), so a zsh-routed block activated as `<comp>.sh` is **never loaded** — only bash
  works. (3) With a primary plugin configured, staged blocks (installer boilerplate, possibly with
  absolute paths/tokens) land in `<plugin>/dotfiles/staged-glue/`, i.e. get git-committed into the
  user's portable config, contradicting the design that glue is machine-local and stays out of git
  (docs/dotfiles-redesign.md:44-47).
- Recommend: stage under `paths.user_glue_dir/staged/`, activate through `Glue._materialize_to` +
  `_glue_store` with `_SHELL_EXT[shell]`, and move the CLI to `configsys glue staged|activate|discard`
  (keep `dotfiles …` as deprecated aliases for one release). Tests: activate a zsh block and assert
  the zsh rc-sourced glob would match it.

### [HIGH] performance — bash/zsh/fish snippets spawn `configsys location` per snippet per shell start
- `glue/shell/bash/*.sh` (49 files, e.g. `go.sh`, `nushell.sh`, `elvish.sh`), `glue/shell/zsh/*.zsh`
  + `glue/shell/fish/*.fish` (98 files): `_x=$(configsys location x 2>/dev/null)` unconditionally.
- Why: the nu/elvish substrates (`glue/shell/nu/00-configsys.nu:22-46`, `elvish/00-configsys.elv:22-48`)
  read `glue-locations.tsv` once (~1 ms) precisely because each `configsys location` is a full
  Python start (~250 ms, per the comments there). A bash user with 20 activated tarball/appImage
  snippets pays ~5 s per interactive shell. The cache and its invalidation (`app.py:1718-1737`)
  already exist; only the POSIX/fish substrates lack a `cs-loc`.
- Recommend: add `cs-loc` to `00-configsys.sh`/`.zsh`/`.fish` (read the TSV into an assoc array /
  fish list, same 1h freshness rule) and sweep the 147 snippets to `$(cs-loc x)`. Low risk: same
  data source.

### [MED] security — `#!cs-eval` executes any command from any file in `~/.config/<shell>/conf.d/` inside the configsys process
- `glue.py:77, 348-395` — `_inline_block` iterates every `conf.d/*.{ext}` (not only our symlinks),
  and `_run_eval` runs the directive via `runner.run(cmd, capture=True)` → `bash -c`
  (`runner.py:432`) with configsys's environment. `_eval_directive` (`glue.py:378-386`) matches the
  directive on **any** line, not just a shebang-like first line.
- Why: no privilege escalation versus the shell later sourcing the same dir, but the timing and
  context differ: it runs at TUI keypress inside a batch that may have just pre-authenticated sudo
  (`runner` keeps the ticket warm for a batch — see memory/sudo notes), it runs for *every* other
  snippet's (de)activation (a generator fires when you toggle an unrelated snippet), and the command
  text is echoed verbatim into `config.nu`/`rc.elv` (`glue.py:371`). A stray or third-party file
  dropped into the (nominally configsys-only) dir becomes code configsys itself executes.
- Recommend: honour the directive only when the file is our symlink whose realpath is under
  `user_glue_dir`/`primary_glue_dir`; require it as the first line; run with `sudo -k`-equivalent
  isolation (or at least an env without `SUDO_ASKPASS`/warm ticket assumptions); document the
  trust model in the module docstring. Add an elvish `#!cs-eval` test (only nu is tested).

### [MED] security — `capture` follows symlinks when copying into a (possibly git-pushed) store
- `dotfiles.py:443` `shutil.copytree(tgt, dest, ignore=_ignore)` (default `symlinks=False`) and
  `dotfiles.py:445` `shutil.copy2` on a symlinked file; `relocate` likewise (`dotfiles.py:475-477`).
- Why: `~/.config/<app>/` commonly contains symlinks (stow, `-> ~/.ssh/…`, `-> ~/secrets`). The
  secret-glob suggestion (`dotfiles.py:62-63`, `.ssh`) matches basenames only, so a link named
  `keys -> ~/.ssh` is dereferenced and its contents copied into `<plugin>/dotfiles/<comp>.cfs/`,
  which the CLI then offers to commit. Contradicts docs/dotfiles-redesign.md:102-112 ("secrets
  never sync").
- Recommend: `symlinks=True` (preserve links) and skip links resolving outside `tgt`; report them in
  the capture preview. Test: capture a dir with a symlink to an outside file, assert it is not copied.

### [MED] data-loss — backups are silently overwritten
- `dotfiles.py:629, 632` — `mv t t.pre-configsys` replaces an existing backup (a second `--force`
  install after the user restored a real file). If `t` is a *directory* and the backup dir exists,
  `mv` nests it inside (`t.pre-configsys/<name>`), and `uninstall` (`dotfiles.py:660`) then restores
  the *older* backup. `glue.py:450` `dst.rename(dst.with_name(dst.name + BACKUP_SUFFIX))` —
  `Path.rename` replaces an existing backup unconditionally. docs/dotfiles-capture-plan.md:12-14
  names exactly this hazard as a motivation, and it is still present.
- Recommend: never overwrite a backup — suffix with a timestamp/counter when the target exists, or
  refuse with an advisory. One shared `_backup(path)` helper on the base driver.

### [MED] data-loss — `_link_bash_aliases` discards a foreign `~/.bash_aliases` symlink without record
- `glue.py:445-446` — `if dst.is_symlink(): dst.unlink()` regardless of where it points (a stow/
  chezmoi-managed link is common). `_remove_bash_aliases` (`glue.py:458-469`) can only restore an
  absorbed file or a `.pre-configsys` backup, so uninstall leaves the user with no `~/.bash_aliases`.
- Recommend: treat a symlink not pointing at our store/source as a real file (absorb its *target
  content* or back the link up via `os.readlink` into a sidecar) — same "ours" test the dotfiles
  driver already has at `dotfiles.py:586-587`.

### [MED] security — shipped bash loader exports `PYTHONPATH=.`
- `glue/bash_aliases:1-5` — `export PYTHONPATH=.:$PYTHONPATH` / `export PYTHONPATH=.` for every
  interactive bash (this file is linked as `~/.bash_aliases` by `shell-glue`).
- Why: puts the current working directory on every Python invocation's import path — running any
  Python tool inside an untrusted checkout imports that checkout's `os.py`/`site.py`-shaped modules.
  Also unrelated to loading conf.d (the "purify the bash loader" item in
  docs/dotfiles-glue-split-plan.md:133-137 is still open) and only bash gets it (zsh/fish don't).
- Recommend: drop it from the loader (move to an opt-in `python-dev-glue` snippet if wanted).

### [MED] performance — `_installed_shells()` recomputed per spec, per unit, per call
- `glue.py:119-173` — `_glue_variants` (`glue.py:185`) calls `_installed_shells()` for every glue
  name; `_specs` is invoked by `get_version`, `spec_states`, `install`, `uninstall`, `location`; each
  call does 5× `shutil.which` (PATH scan), reads `glue-locations.tsv`, and runs up to 4 globs per
  shell in `_shell_binary_in`. `GlueScreen.reload` (`menu.py:4830-4834`) and startup inspection do
  this for ~70 glue units.
- Recommend: memoise per driver instance (one `_installed_shells` per `Glue` object, invalidated by
  `CONFIGSYS_GLUE_SHELLS` change); `get_driver` already hands one instance per screen.

### [MED] performance — inline block + generator commands regenerated N times per group action
- `glue.py:647-648, 682-683` — every `install`/`uninstall` of a snippet calls
  `_ensure_shell_loader(shell)` → `_inline_block` → reads all conf.d files and runs every
  `#!cs-eval` command (`zoxide init nushell`, `atuin init nu`, …). `menu.py:5678-5680`
  (`activate-group`) loops `install` per snippet, so a 70-snippet nu group performs 70 block
  rebuilds and 140 subprocess spawns. `install` also reads each snippet's bytes three times
  (`glue.py:616-618`, `_materialize_to` refresh, then `_drifted` on the next `spec_states`).
- Recommend: batch — let `install(rc, only_shells, *, regenerate=True)` skip the rebuild and have
  the group action call `_ensure_shell_loader` once at the end; cache generator output per command
  within one op batch.

### [MED] conflation/naming — glue still lives under the `dotfiles` CLI/action surface
- `app.py:3213-3286` `cmd_dotfiles_status` prints a "glue — shell integration" section; docstring
  says "every via:dotfiles target". `actions.py:956-964` `dotfiles_units` returns both drivers with
  the comment "(Phase 2 splits these into separate glue/dotfiles pages)" — Phase 2 is DONE
  (docs/dotfiles-glue-split-plan.md:160-176), the comment is stale. `GlueScreen.reload`
  (`menu.py:4827`) calls `actions.dotfiles_units`. `shellguard.py:132` and `app.py:3169-3170` tell
  the user to run `configsys dotfiles activate` for glue. There is no `configsys glue` command at all
  (`app.py` grep). `config.hu:17` documents `disabled-drivers: [ dotfiles ]` only, while
  `actions.py:342` says "dotfiles/glue".
- Recommend: `actions.glue_units` + `dotfiles_units` (config-only); `configsys glue status|activate|
  deactivate [--shell] |staged|discard`; keep `dotfiles status` config-only. Mention `glue` in the
  `disabled-drivers` doc string.

### [MED] comment-vs-code drift — docs and headers still describe the pre-split world
- `docs/dotfiles-redesign.md:3` "DESIGN AGREED, not built" while phases 1a-3 are marked DONE;
  `:44, :73, :158` glue store is `dotfiles/shell/<shell>/` (now `glue/<shell>/conf.d/`, see
  `paths.py:104-108`, `glue.py:285-296`); `:80-82` opt-out = "hobble the `-dotfiles` component"
  (glue components are `-glue`); `:189, :233-239` `zsh-glue`/`fish-glue` (collapsed into `shell-glue`).
- `dotfiles.py:9-12` header: "Install symlinks dst -> src (edits flow back to the repo…). An existing
  non-symlink dst is backed up" — links never target the repo (#4) and the default is now *refuse*
  (`dotfiles.py:588-600`).
- `paths.py:15` references `dotfiles/bash.d/00-configsys.sh`; `configsys/drivers/source.py:162`
  "hasn't sourced bash.d"; `shellguard.py:176` "mirroring the dotfiles driver's `_SHELL_CONFD`" (it
  is the glue driver's); `glue.py:414` `# fish / nu: dir is the whole job` — nu is in `_SHELL_RC`
  and inline now, only fish takes this branch; `glue.py:88-90` an "Elvish: [nomatch-ok] …" comment
  inside `_RC_SOURCE` with no elvish entry (orphaned by the gestalt switch);
  `docs/shell-writes-switch.md:31` still says staged glue goes to `<store>/shell/<shell>/`.
- Recommend: one docs pass; add a "Status" line to dotfiles-redesign.md pointing at the split plan.

### [MED] test gaps
- No test for: pretend-mode no-write (both drivers); real file at a glue conf.d target;
  backslashes/`\1` in an inline block; `#!cs-eval` on elvish; `_remove_shell_loader`/`_ensure_shell_loader`
  when the rc is a managed symlink (`glue.py:417-418` returns False — `get_version` for `shell-glue`
  is then permanently None on a machine with a captured `.zshrc`, see next finding); shellguard
  `activate` for zsh/fish/elvish/nu; capture following symlinks; backup-over-backup;
  `_read_manifest` on a malformed/partial `manifest.hu` (`dotfiles.py:164-182` indexes
  `node['src']` without guarding a non-map node → AttributeError surfaces as a TUI "error:" note);
  glue `location()`; `_managed_shells` with a `~`-prefixed cache path.
- `test/test_dotfiles.py:27-48, 465-535` still test glue-shaped content (`bash.d/btop.sh`,
  `absorb-into` into `~/.bash.d/`) through the dotfiles driver; `paths_for` there sets
  `CONFIGSYS_GLUE_SHELLS`, which the dotfiles driver no longer reads. These pass but pin legacy
  behaviour rather than the current contract. (Plugin caveat: `~/src/configsys-user/configsys.hu`
  still matches `absorb-into|bash.d/|src: shell/` and ships `dotfiles/bash.d` + `dotfiles/bash_aliases`,
  so the `bash.d/` fallback in `glue.py:191-192` and the `_config_specs` filter in
  `dotfiles.py:203-208` are NOT dead — keep them until that plugin is migrated, then delete both.)
- `test/test_coexistence.py` is unrelated to this scope (installState coexistence).

### [MED] feature gap — a shell-glue loader on a machine with a captured `~/.zshrc` is never "installed"
- `glue.py:417-418` `_ensure_shell_loader` returns False for a symlinked rc (by design: a captured
  rc owns its source line), but `_loader_ok` (`glue.py:498-500`) then reports `loader-off` forever
  and `get_version(shell-glue)` is None → the Components page shows `shell-glue` as pending install
  on every run, and `install` "succeeds" (`glue.py:603`) without changing anything. Same for a
  glue snippet whose only installed shells ship no variant: `get_version` → None (`glue.py:538-539`)
  while `install` returns an advisory ok (`glue.py:608`) — perpetual to-do.
- Recommend: for a symlinked rc, check whether the *target* already contains the marker or a
  `conf.d` source line and report `loader-on`/`delegated`; for no-variant snippets return a
  distinct `n/a` state that the ledger/TUI treats as satisfied.

### [MED] refactor — extract a `LinkedContentDriver` base + a `ShellSpec` table
- Duplicated verbatim or near-verbatim: `_home`/`_env` (`glue.py:211-215` = `dotfiles.py:86-90`),
  `_expand` + `_VAR` (`glue.py:35, 298-317` = `dotfiles.py:31, 285-304`), `_defining_root`
  (`217-224` = `92-100`), `_content_roots` (`226-237` = `102-116`), `_store_path` (`250-253` =
  `242-247`), `_materialize_to` (`255-283` ⊃ `266-283`), `_resolve` (`239-248` ≈ `130-146`), the
  `set -e`/`if [ -e ]`/`mkdir -p`/`ln -sfn`/`else echo` script + ELOOP realpath skip
  (`glue.py:627-641` = `dotfiles.py:607-636`), `uninstall`'s `if [ -L ]; rm -f` (`678` = `654`),
  `get_version`'s realpath loop (`540-546` = `508-513`), `location` (`690-691` = `664-665`),
  `lock/unlock/is_locked/get_latest` stubs, `BACKUP_SUFFIX`. Roughly 140 lines each side.
- Per-shell knowledge is spread over five parallel dicts/tuples (`_SHELL_EXT`, `_SHELL_CONFD`,
  `_GLUE_SHELLS`, `_SHELL_COMPONENT`, `_SHELL_RC`, `_INLINE_SHELLS`, `_RC_SOURCE`) plus
  `if shell == 'bash'` special cases in `_glue_variants`, `_ensure_shell_loader`,
  `_remove_shell_loader`, `_loader_ok`, and shellguard's own `_confd` map and `GUARDED`. Adding a
  shell (the `add-shell.md` playbook) touches ~8 places.
- Recommend: `configsys/drivers/_linked.py` with `LinkedContentDriver(Driver)` parameterised by
  `kind` ('dotfiles'|'glue') → `paths.user_<kind>_dir`, `primary_<kind>_dir`, `<kind>_dir`; Python
  `os.symlink`-based link/unlink with an explicit backup policy (fixes pretend + backup findings in
  one place). A frozen `ShellSpec(name, ext, confd, rc, mode∈{native,rc-source,inline,bash-aliases},
  component, guarded_rcs)` table consumed by glue, shellguard, and the TUI grouping.

### [LOW] security — `_expand` leaves unknown `$VAR` literal, yielding a CWD-relative path
- `glue.py:310`, `dotfiles.py:297` — `env.get(var, m.group(0))`; a `dst: $FOO/x` with `FOO` unset
  becomes `Path('$FOO/x')`, relative to the process CWD, so `mkdir -p`/`ln` land wherever configsys
  was launched. Same for any `dst` without `~`/`/`.
- Recommend: refuse (advisory) a dst that is not absolute after expansion.

### [LOW] correctness — shellguard round-trips rc files as text, not bytes
- `shellguard.py:29-35, 79` — `read_text()`/`write_text()`: universal-newline translation means a
  CRLF `.bashrc` is rewritten LF (docstring promises "exactly their prior bytes"); a non-UTF-8 rc
  raises `UnicodeDecodeError` (not `OSError`) out of `snapshot` → `arm` → the install aborts before
  it starts. `revert_and_capture` also clobbers any edit the *user* made to the rc during a long
  install (documented nowhere).
- Recommend: `read_bytes`/`write_bytes`, decode only for the diff; mention the concurrent-edit
  window in the module docstring.

### [LOW] feature gap — guard covers only bash/zsh rc files; inline shells' rcs are unguarded
- `shellguard.py:23-24` — `GUARDED` lacks `~/.config/fish/config.fish`, `rc.elv`, `config.nu`. An
  installer (`atuin`, `zoxide` docs) writing `config.fish`/`config.nu` bypasses the switch, and the
  glue-owned marker block in `config.nu` could be edited around/inside by an installer.
- Recommend: extend `GUARDED` from the `ShellSpec` table (and stage with the right extension).

### [LOW] CLI/TUI parity
- TUI Glue has per-shell `activate`/`deactivate`/`activate-group` (`keyspec.py:168`,
  `menu.py:5657-5685`); CLI `install X-glue` activates all shells with no `--shell` scoping and
  there is no CLI deactivate-per-shell. Staged glue is CLI-only (docs/shell-writes-switch.md:9 says
  the TUI surfacing is "not yet added"; no `staged` on the Glue page). Drift (`drifted`/"changed") is
  only pulled by re-`install`; `configsys refresh` does not re-materialise glue and `upgrade` never
  fires because `get_latest` is None (`glue.py:579`). No per-shell opt-out except the
  `CONFIGSYS_GLUE_SHELLS` env (`glue.py:127-129`), which the docs call a test hook.
- Recommend: `configsys glue …` command family; a `glue-shells:` machine setting; have `refresh`
  re-materialise drifted store copies (or surface a count).

### [LOW] dead code / stragglers
- `dotfiles.py:224-227` `_excludes_for` — no callers anywhere (`capture` reads the manifest inline).
- `glue.py:88-90` orphaned elvish comment in `_RC_SOURCE` (see drift).
- `glue.py:623` re-implements `_shell_of` (`glue.py:588-590`) inline three lines below its use.
- `dotfiles.py:616, 648` `import shlex` inside function bodies (module already imports `re`, `os`).
- `test/test_dotfiles.py:19-24` `CONFIGSYS_GLUE_SHELLS` in the dotfiles fixture — unused by that driver.
- `docs/dotfiles-capture-plan.md:154-155` "Only functional plumbing still ships in `dotfiles/`
  (the `bash.d/*.sh` loaders + `bash_aliases` + `gdbinit`)" — today `dotfiles/` holds only `gdbinit`;
  the loaders moved to `glue/`.

### [LOW] naming
- Three "store path" notions in `glue.py` with overlapping names: `_store_path(src)` (`<store>/<src>`,
  only used for `bash_aliases`), `_glue_store(dst)` (`<store>/<shell>/conf.d/<x>`, the real mirror),
  and `_deployed(dst, src, rc)`. The glue store thus mixes two layouts under one dir
  (`<store>/bash_aliases` beside `<store>/bash/conf.d/`).
- `spec_states` returns a 7-positional tuple consumed by index in three places (`app.py:3228`,
  `menu.py:4796, 4834`) — a `NamedTuple` would make the ABI legible.
- `GLUE_STATE_LABEL` maps raw→display but `'empty'` and `'drifted'→'changed'` leak the raw
  vocabulary into `_GLUE_ORDER` (`app.py:3116`) and `_DF_STATE_ELEM` lookups.
- `shellguard._STAGE_DIR = 'staged-glue'` under a *dotfiles* root; `_capture_root` there vs
  `DotFiles._capture_root` — same name, one is glue's.

### [LOW] ABI/interface break candidates (for whoever does the refactor)
- Public-ish surfaces to preserve: `Glue.install/uninstall(rc, only_shells=None)`
  (`menu.py:5659-5680`); `spec_states` 7-tuple + `kind` column; `capture_plan` 4-tuple and the
  `hasattr(drv, 'capture_plan')` duck-check (`app.py:3226`); `GLUE_STATE_LABEL`, `CONFIG_STATES`,
  `config_display_state`; `CONFIGSYS_GLUE_SHELLS`; `Result(advisory=…)`; shellguard's
  `<component>.<shell>.sh` filename parsing (`shellguard.py:156-168`) and `arm/finish` signatures used
  by both op loops; `paths.user_glue_dir/primary_glue_dir/glue_locations_file` read by the shipped
  nu/elvish substrates (`glue-locations.tsv` name and `\t` format are a shell-facing contract).
- Changing `_STAGE_DIR` location or the staged extension is a data migration for anyone with
  staged blocks.

### [NIT] `#!cs-eval` directive matched anywhere in the file
- `glue.py:378-386` — any line that `strip()`s to `#!cs-eval …` fires, including inside a heredoc or
  a prose comment. `glue/shell/nu/fzf.nu:3-4` narrowly avoids it. Require line 1 (or line 1 after
  comments) and document it in the module docstring.

### [NIT] nu bridge quoting
- `glue/shell/nu/vulkan-sdk.nu:6` splices `$vk` (from the TSV cache) into a bash string with `"`
  quoting; a path containing `"` breaks the command. Values come from configsys itself, so low
  risk; prefer passing the dir via an env var to `cs-bash-env`.

### [NIT] hard-coded `cf` alias
- `glue/shell/bash/00-configsys.sh:18`, `zsh/00-configsys.zsh`, `fish/00-configsys.fish:20`:
  `alias cf="~/src/configsys/configsys.sh"` ignores `CONFIGSYS_LAUNCHER`/`CONFIGSYS_SRC_DIR` that the
  `configsys` function right above honours; elvish/nu define `cf` through `configsys`. Make it
  `alias cf=configsys`.

### [NIT] `_inline_block` / `_rc_has_block` use default-encoding `read_text()`
- `glue.py:364, 399, 420, 483` — a non-UTF-8 byte in any conf.d file or rc raises
  `UnicodeDecodeError` through `install`; `_inline_block` catches only `OSError`.
