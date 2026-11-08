# Review: Dotfiles, glue, the shell-writes guard, the bootstrap

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys.sh`, `configsys/drivers/dotfiles.py`, `configsys/drivers/glue.py`, `configsys/shellguard.py`,
`glue/bash_aliases`, and the shipped snippets under `glue/shell/{bash,zsh,fish,nu,elvish}/` (398 files —
swept by script in all five real shells, plus a representative sample of each read line by line).
Context: `docs/shell-glue.md`, `docs/done/dotfiles-redesign.md`, `docs/principles.md`, `docs/plugins.md` §6,
`actions.run_plan`, `actions.dotfiles_units`, `app.cmd_dotfiles_*` / `cmd_glue_*`, `primarygit.will_write`,
`paths.py`, `driver.command_trusted`, the TUI Glue/Dotfiles screens' handlers.
Tests read: `test_glue_driver.py`, `test_dotfiles.py`, `test_shellguard.py`, `test_pretend_sweep.py`,
`test_fix_cli_pretend.py`, `test_fix_cli_followups.py`, `test_fix_drivers_d.py`, `test_fix_drivers_d2.py`
(114 targeted tests pass at baseline).

Reproductions ran in scratch sandboxes under `$RUN/scratch/dotfiles-glue/` (scripts kept there:
`repro_*.py`, `inline_gen.py`, `time_*.py`); shells used: bash 5.1.16, zsh 5.8.1, fish 3.3.1, nushell 0.116.1,
elvish 0.21.0; distro skeleton files read from the locally cached podman images (`--network=none`).
One bootstrap reproduction (finding -10) reached the script's own `sudo apt-get install` line; sudo refused
without a terminal and nothing ran as root.

Verification (2026-11-08, checker): every HIGH and every MED-or-above safety/security finding was
re-checked (-01 to -06, -12, -14, -17, -19 to -22). Sandboxes are under `$RUN/scratch/verify-dotfiles-glue/`
(`$V`), and the scripts are in `$V/scripts/`. Python calls that delete things ran under an rmtree/unlink fence
(`guarded_main.py`, `v05_*.py`, `v22_*.py`) that refuses any path outside the sandbox. Only dotfiles and glue
ops ran for real, inside `--home` sandboxes; the bootstrap's sudo and apt-get were stubs; nothing was written
to git. Result: 13 checked, 13 confirmed, 1 severity change (-19 MED → LOW).

## Carried over from docs/review-2026-09/dotfiles-glue.md (and README D7)

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] glue install clobbers a real file at the conf.d target | open (partly fixed) | `328d25e` backs up the FIRST real file (`mv -n`), but when a backup exists `mv -n` no-ops (exit 0, coreutils 8.32) and `ln -sfn` then clobbers the file — re-reported as **dotfiles-glue-06** |
| [HIGH] `--pretend` skips Python-side writes | fixed | `328d25e` (glue), `2a577c0` (.cfs marker/store), `63ecefe` (full sweep); `test_pretend_sweep.py` covers capture/activate/discard/glue add/override |
| [HIGH] inline block spliced with `re.sub` content-as-replacement | fixed | `328d25e` (`lambda _m: block`, glue.py:828-829); `test_rc_block_with_backslashes_is_written_literally` |
| [HIGH] shellguard stages/activates into the dotfiles root, old layout, always `.sh` | fixed | `2a577c0`: `<state>/staged-glue/<shell>/<comp>.<ext>`, activate → `Glue.add_user_glue` (user.d, 90- band), `migrate_legacy` carries old blocks |
| [HIGH] bash/zsh/fish spawn `configsys location` per snippet | fixed | `f45a5d0` + `2a577c0` (`cs_loc` + `glue-locations.tsv` in every prelude); guard test `test_no_startup_snippet_spawns_configsys_per_component`. The replacement lookup is itself slow → **-15** |
| [MED] `#!cs-eval` honored in any conf.d file, any line | open | glue.py:759-785 unchanged → **-31** |
| [MED] `capture` follows symlinks into the store | open, raised to HIGH | dotfiles.py:465/467 unchanged; since then the primary write journal commits whatever lands there → **-04** |
| [MED] backups silently overwritten | dotfiles fixed, glue open | `2a577c0` `backup_cmd` numbered backups (`test_backup_cmd_never_overwrites_existing_backups`); glue's three backup sites still overwrite → **-06** |
| [MED] `_link_bash_aliases` discards a foreign symlink | open | glue.py:873-874 → **-29** |
| [MED] shipped bash loader exports `PYTHONPATH=.` | fixed | `2a577c0` (`test_bash_aliases_has_no_personal_content`) |
| [MED] `_installed_shells()` recomputed per spec | open, downgraded | measured 164 calls / ~165 ms per 82-unit sweep → **-24** (LOW) |
| [MED] inline block + generators rebuilt per snippet in a group action | open, downgraded | measured 1.09 s for an 80-snippet nu group → **-25** (LOW) |
| [MED] glue lives under the `dotfiles` CLI surface | partly fixed | `configsys glue add|override` exist; `dotfiles staged|activate|discard`, the `dotfiles status` glue table and shellguard's message remain → **-33** (the app.py/actions.py halves belong to the app-cli area) |
| [MED] comment drift (pre-split world) | partly fixed | `dotfiles-redesign.md` stamped DONE, paths.py/shellguard headers fixed; the owned-file drifts that remain → **-37** |
| [MED] test gaps | partly filled | pretend, backslash, communal-backup, zsh activation now tested; remaining gaps listed below |
| [MED] shell-glue never "installed" with a captured `~/.zshrc` | open | glue.py:820-821 + 1036-1039 → **-18** |
| [MED] refactor: `LinkedContentDriver` + `ShellSpec` (README D7) | open | → **-23** |
| [LOW] `_expand` leaves an unknown `$VAR` → CWD-relative path | open, worse | the launcher `cd`s into the repo (configsys.sh:7), so such a dst now lands INSIDE the repo; folded into **-05** |
| [LOW] shellguard round-trips text, not bytes | open, raised to MED | a non-UTF-8 rc now demonstrably aborts the whole batch → **-13** |
| [LOW] guard covers only bash/zsh rc files | open, raised to MED | principles.md "uniform coverage or not ship" → **-14** |
| [LOW] CLI/TUI parity | open | → **-33** |
| [LOW] dead code / stragglers | partly open | `_excludes_for`, orphaned `_RC_SOURCE` comment, inline `_shell_of` copies, function-level `import shlex` remain → **-38**; the `dotfiles-capture-plan.md` line is a done-doc (historical) → obsolete |
| [LOW] naming (three store notions, 7-tuple, label leak, `_STAGE_DIR`) | partly fixed | `_STAGE_DIR` now under the state dir (`2a577c0`); the rest folded into **-23** |
| [LOW] ABI candidates | informational | re-listed under "ABI / interface candidates" |
| [NIT] `#!cs-eval` matched on any line | open | merged into **-31** |
| [NIT] nu bridge quoting (`vulkan-sdk.nu`) | open | → **-40** |
| [NIT] hard-coded `cf` alias | fixed | `2a577c0` (`alias cfs=configsys`; `test_every_prelude_ships_cfs_and_no_hardcoded_clone`) |
| [NIT] default-encoding `read_text` | open | merged into **-13** |

## Cross-cutting themes

- **Linking is done by three hand-written shell/Python fragments, and only one of them got the safety rules.**
  The dotfiles driver's `backup_cmd` (numbered, never-overwrite) is the one place that honors the "never
  overwrite a user file" rule. Glue's conf.d link, `_link_bash_aliases`, `_deploy_user_glue`, and every
  *restore* path (dotfiles `uninstall`, `_remove_bash_aliases`) still overwrite, remove "our" symlink without
  checking it is ours, or restore a backup over a live file (-03, -06, -29). None of the copy/rmtree paths
  check that a route-supplied `src:` stays inside the store (-05). One pretend-aware Python primitive —
  `link(src, dst)` / `unlink_and_restore(dst)` with ownership and containment checks — would close the whole
  class (-23).
- **Writes go through symlinks the code never looks at.** The guard reverts *through* the link a dotfiles
  install just made (-01); `_remove_shell_loader` edits a captured rc in the primary through `~/.zshrc`
  while `_ensure_shell_loader` refuses to (-17); `capture` copies through links into a git-tracked tree (-04).
  Each needs an `lstat`/realpath decision at the point of writing.
- **The shell side is checked for parse errors but not for behavior.** All 398 snippets parse in their shells,
  and the bare-sandbox sweep raised nothing. The bugs are semantic: fish's `fish_add_path -a` doesn't append to
  PATH (-07); `setopt local_options` at top level leaks `null_glob` (-08); the bash loader assumes a Debian
  `.bashrc` (-02); fish's freshness test is always true (-26). A small per-shell behavior harness (source the
  prelude and a snippet in each real shell, assert on PATH/aliases/options) would have caught all four;
  `test_cs_loc_reads_the_cache` is the only test of that kind today, and it covers bash and zsh only.
- **Shell-start cost moved from spawning configsys into the lookup and the init hooks.** `cs_loc` is a
  linear scan plus a subshell per call (~100 ms per shell, -15), and the cached pyenv init still runs
  `pyenv rehash` on every start (~70–110 ms, -16). Each fix is small.
- **The bootstrap is written for the author's own setup.** It is invoked from the clone, on a
  Debian-family box with python ≥ 3.10, through the recorded launcher. A symlink onto PATH (-10), a relative
  CLI path (-09), EL9/AL2023's python 3.9 (-11), and a broken venv found during a hidden shell-start refresh
  (-12) each fail in a confusing way.

## Findings

### dotfiles-glue-01 [HIGH] safety — the shell-writes guard reverts THROUGH the symlink `zsh-dotfiles` just created, overwriting your captured zshrc (in the primary) and staging its lines as "installer writes"
`configsys/shellguard.py:130-163` (`revert_and_capture`) with `actions.run_plan` (arms the guard for every
`install`/`upgrade`, any driver) and `configsys/drivers/dotfiles.py:584-668` (`install`). Installing
`zsh-dotfiles` (shipped; `zsh` suggests it, so `install --picks` pulls it in on a new machine) replaces
`~/.zshrc` with a symlink to your captured zshrc. The guard compares the snapshot (the old file, or *absent*)
with what `~/.zshrc` reads *through the new link*. It treats your whole captured config as installer
lines and stages them. It then writes the snapshot back, `path.write_text(target)`, through the symlink into
the captured file. On a fresh box (no `~/.zshrc`), if the captured zshrc contains the configsys glue
block, `_restore_with_cs_blocks(None, now_blocks)` leaves only that block. Your portable zshrc is truncated to
five lines. With an existing `~/.zshrc`, the captured file is overwritten by this machine's old zshrc. The
capture root is the primary plugin when one is blessed, so the write lands in its git working tree,
unjournaled. The message then tells you to `dotfiles discard` the "installer's" block, which is your own
config. The user's real primary (`~/src/configsys-user/dotfiles/zsh-dotfiles.cfs/zshrc`) has exactly this
shape: it contains the configsys marker block.
**(reproduced)** `.venv/bin/python $RUN/scratch/dotfiles-glue/repro_guard_df.py …` →
`A-fresh-box: … guard says: guarded: reverted 3 line(s) zsh-dotfiles tried to add to your zsh rc … CAPTURED store file now: '# >>> configsys glue >>>\nsetopt …\n# <<< configsys glue <<<\n'`
and `B-existing-zshrc: … CAPTURED store file now: '# old machine zshrc\nexport EDITOR=vi\n# >>> configsys glue >>> …'`.
**Fix:** in `shellguard.arm`, return None for configsys's own config drivers (`rc.driver in ('dotfiles','glue')`
— pass the rc, not just the name). Also, in `revert_and_capture`, never write a file whose `lstat` identity
changed during the op (regular file or absent → symlink, or a new link target). Treat that as "not an
installer write" and leave it. Add a regression test that installs a dotfiles spec at `~/.zshrc` with the
guard armed. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays HIGH. Real CLI in `$V/c01a/home`: a captured `zsh-dotfiles.cfs/zshrc` (four of the user's lines plus the configsys marker block) and no `~/.zshrc`. `configsys --home $H install --no-deps zsh-dotfiles` printed `-> guarded: reverted 4 line(s) zsh-dotfiles tried to add to your zsh rc … Staged as inactive glue` and then `-> ok`. `~/.zshrc` is the new link. The captured file now holds only the 5-line block, and the user's 4 lines sit in `<state>/staged-glue/zsh/zsh-dotfiles.zsh` under `# from ~/.zshrc (captured by configsys — installer wanted to write this)`. Case B (`$V/c01b`, an existing `~/.zshrc`): the captured file now reads `# old machine zshrc` / `export EDITOR=vi`, the same as `.zshrc.pre-configsys`. Case C (`$V/c01c`, a captured zshrc without the block, fresh box): the guard deletes the new `~/.zshrc` link, so the install is silently undone, and it still prints `-> ok`. Nothing prevents it: `run_plan` arms the guard for every driver, `guard_shell_writes` checks only the allow-list (empty by default), shellguard.py never calls `will_write`, and no test arms the guard around a dotfiles install. One correction: the message points at `dotfiles staged` and `dotfiles activate`, not at `discard`. Why not CRITICAL: the user's lines survive in the staged block, and in git when the store is the primary. But when the store is local, running `dotfiles discard` on what reads as installer junk deletes the last copy.

### dotfiles-glue-02 [HIGH] correctness — the bash loader only works where `~/.bashrc` sources `~/.bash_aliases` (Debian-family); on Fedora/RHEL/Oracle/Arch/Void/Alpine no bash glue ever loads, while configsys reports it active
`configsys/drivers/glue.py:813-815, 859-884` (`_ensure_shell_loader` → `_link_bash_aliases`), `:926-927`
(`_loader_ok`: bash is "on" iff `~/.bash_aliases` is a symlink). The glue driver never checks that anything
sources `~/.bash_aliases`. Only Debian/Ubuntu's `/etc/skel/.bashrc` does. Fedora/EL use `~/.bashrc.d/`,
Arch's skel has no hook, and Void/Alpine ship no skel `.bashrc`. On those distros every bash snippet (PATH for
tarball tools, cargo, go, init hooks) is silently dead. The Glue screen and `get_version(shell-glue)` say
`active`/`linked`. The project's own sweep and podman harnesses never run an interactive bash. That breaks
"no surprises", and principles.md's uniform-coverage rule.
**(reproduced)** `podman run --rm --network=none <img> sh -c 'grep -l bash_aliases /etc/skel/.bashrc /etc/bash.bashrc /etc/bashrc …'`
→ `langs-noble: /etc/skel/.bashrc` · `fedora:44: (none)` · `arch: (none)` · `void: (no /etc/skel/.bashrc)` ·
`alpine:3.23: (no /etc/skel/.bashrc)`; `oraclelinux:9` skel uses `~/.bashrc.d`. Loader state verified by reading
`_loader_ok`.
**Fix:** treat bash like zsh. Keep one marker block in `~/.bashrc` that sources `~/.config/bash/conf.d/*.sh`
(guarded with `-r`), or keep `~/.bash_aliases` but have `_ensure_shell_loader` add the
`[ -f ~/.bash_aliases ] && . ~/.bash_aliases` marker block to `~/.bashrc` when no `bash_aliases`/`conf.d`
reference is found. Make `_loader_ok` verify the chain, not just the link. Update the bash row of
docs/shell-glue.md. **Effort:** M. **Tier:** B.

**Verified:** CONFIRMED (reproduced). Stays HIGH. I read the skeleton files from the cached images (`podman run --rm --network=none <img> …`). Only Debian 11's and Ubuntu noble's `/etc/skel/.bashrc` mention `bash_aliases`. Fedora 44, Oracle 9, Alma 10 and AL2023 source `~/.bashrc.d`, openSUSE's skel sources `~/.alias`, Arch's has no hook, and Void and Alpine ship no skel `.bashrc`. End to end: in a sandbox home holding Fedora 44's skel `.bashrc` (`$V/c02fed`), `CONFIGSYS_GLUE_SHELLS=bash configsys --home $H install --no-deps shell-glue` gives `-> ok` and `~/.bash_aliases -> ~/.config/configsys/glue/bash_aliases`. I then added `export CFS_TEST_LOADED=yes` to `conf.d/50-zz-test.sh`. `env -i HOME=$H … bash -i -c 'echo $CFS_TEST_LOADED'` prints nothing. The same steps on Debian 11's skel (`$V/c02deb`) print `yes`. Meanwhile the driver reports `get_version(shell-glue) = linked` and `spec_states = ['loader-on']` (shown as `active`). Nothing in glue.py, app.py, actions.py or `glue/bash_aliases` touches `~/.bashrc`. docs/shell-glue.md:24 calls this "the distro `~/.bash_aliases` convention" but doesn't say only Debian-family distros have it.

### dotfiles-glue-03 [HIGH] safety — `dotfiles` uninstall restores `.pre-configsys` OVER your live config when the link was replaced by a real file (and removes any symlink, ours or not)
`configsys/drivers/dotfiles.py:680-697` (`uninstall`):
`if [ -L t ]; then rm -f t; fi` then `if [ -e t.pre-configsys ]; then mv t.pre-configsys t; fi`. Many apps save
atomically (write a temp file, rename it over the target), which turns configsys's symlink into a regular file
holding your current edits. `configsys remove <x>-dotfiles` (or the TUI's unmanage/`x`) then `mv`s the
months-old backup over it; a plain `mv` overwrites. A directory target nests the backup inside it instead.
The comment "only remove our own symlink" is false: any symlink at dst is removed, including a stow or
chezmoi link that replaced ours. The absorb branch (`mv a t`) has the same flaw. The docstring promises
"restores the (first) backup", the oldest one, even when newer `.pre-configsys.N` exist.
**(reproduced)** `repro_df_uninstall.py` → `dst is now a regular file: True` · `uninstall: True` ·
`dst after uninstall = ORIGINAL machine-local` · `LIVE edits anywhere? False`.
**Fix:** restore only when `t` is absent *after* removing a symlink that resolves into one of our content
roots. If a real file is present, leave both it and the backup, and return an advisory naming both. Use
the same ownership test for the `rm`. Add a test: link, replace it with a regular file, uninstall, and assert the
regular file survives. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays HIGH. Real CLI in `$V/c03/home`: a captured `gdb-dotfiles.cfs/gdbinit` and a real `~/.gdbinit` (`ORIGINAL machine-local`). `install --no-deps gdb-dotfiles` backs the file up and links it. A `sed -i` edit then turns the link into a regular file holding `LIVE edits made after install`. That is an in-place save; GLib's `g_file_set_contents` also replaces a symlink this way. Next, `configsys --home $H remove gdb-dotfiles`. Its `--pretend` output shows `if [ -L … ]; then rm -f …; fi` followed by `if [ -e ….pre-configsys ]; then mv … …; fi`. The real run prints `-> ok`. Afterwards `~/.gdbinit` holds `ORIGINAL machine-local`, and `grep -rl 'LIVE edits'` over the sandbox finds nothing. `uninstall` checks neither for a real file nor for ownership. The two uninstall tests in test_dotfiles.py (`test_real_symlink_install_getversion_uninstall` and `test_existing_dir_is_backed_up_and_restored`) both uninstall while the link is still in place. The TUI `u` popup says "unlinks it; your content stays in your store" and then does the same thing.

### dotfiles-glue-04 [HIGH] security — `capture` follows symlinks (e.g. `keys -> ~/.ssh`) into the store; the secret scan doesn't descend into them, and with a primary the write journal commits the private key
`configsys/drivers/dotfiles.py:456-467` (`capture`: `shutil.copytree(tgt, dest, ignore=_ignore)` with the default
`symlinks=False`, `shutil.copy2`), `:399-418` (`_suggest_secrets`: `rglob` doesn't follow symlinked dirs, so
`id_*` is never suggested for a linked dir), `:444` (`primarygit.will_write(cfs)` records the whole tree, and
`commit()` runs `git add -A` on it). A config dir holding a link into `~/.ssh`, `~/.gnupg` or a secrets dir is
dereferenced into `<primary>/dotfiles/<comp>.cfs/`. It is committed as a configsys change (pushed at once under
`primary-push: auto`) and never git-ignored. A dangling link inside makes `copytree` raise `shutil.Error`
*after* copying everything else, so the partial tree is in the store without a manifest or `.gitignore`. The
recorded tree is committed anyway. docs/done/dotfiles-redesign.md promises "secrets never sync".
Single-file specs (`gradle.properties`, `.hgrc`, maven `settings.xml`, helm `repositories.yaml`, all shipped
`-dotfiles` components) get no secret scan at all, since `_suggest_secrets` returns `[]` for a non-dir.
**(reproduced)** `repro_capture_symlink.py` → `suggested excludes: []` · `capture raised: Error [(…/dangling …` ·
`store tree: ['myapp', 'myapp/keys', 'myapp/keys/id_ed25519', 'myapp/settings.toml']` ·
`manifest written: False`.
**Fix:** `copytree(..., symlinks=True)`, and drop or report links whose realpath leaves `tgt`. Show them in the
capture plan as `skip-link-outside`. Catch `shutil.Error` and roll back the partial copy. Scan file contents
(not just names) for `BEGIN .* PRIVATE KEY`, `password`, `token`, `secret` before writing into a primary, and
ask. Tests: an outside link, a dangling link, and a single-file spec containing `password=`. **Effort:** M.
**Tier:** A.

**Verified:** CONFIRMED (reproduced) for the store side. The commit leg is CONFIRMED (by reading), because this check made no git writes. Stays HIGH. Real CLI in `$V/c04/home`: `btop-dotfiles` picked, and `~/.config/btop/` holds `btop.conf` plus `keys -> ~/fake-ssh`, which contains a fake `id_ed25519` (mode 600). `configsys --home $H dotfiles capture btop-dotfiles --yes` lists only `~/.config/btop -> ~/.config/configsys/dotfiles/btop-dotfiles.cfs/btop`. Afterwards the store holds `btop/keys/id_ed25519` as a real file (mode 600), and `keys` is a real directory, not a link. The manifest says `exclude: []`, and there is no `.gitignore`. Python 3.10's `rglob` doesn't descend into the linked directory, so `id_*` is never suggested. With a dangling link added (`$V/c04c`), the command exits 1 with `shutil.Error: [('$H/.config/btop/zz-dangling', …, "[Errno 2] No such file or directory: …")]`. By then the key is already copied, and no manifest is written. The commit leg, by reading: `capture` calls `primarygit.will_write(<cfs>)` before it copies anything. `app.main` runs `primarygit.commit` in a `finally`, so the commit also happens after the `shutil.Error`. `PrimaryRepo.dirty()` lists files with `--untracked-files=all`, so `git add -A` stages every new file under the recorded `.cfs` that no `.gitignore` matches, and `_after_primary_commit` pushes it under `primary-push: auto`. Precondition: a link inside a captured config directory that points at secrets.

### dotfiles-glue-05 [HIGH] security — a route's `src:` is never validated: absolute or `..` paths make `capture --force` `rmtree()` any directory and the TUI "move" relocate move/delete directories outside the store (untrusted data plugins can author this)
`configsys/drivers/dotfiles.py:449-455` (`capture`: `dest = self._cfs_dir(rc) / src`, then
`shutil.rmtree(dest)`); `:487-512` (`relocate`: `newpath = target_cfs / src`, then `rmtree(newpath)`, a copy, and
`rmtree(srcpath)`); `:143-159` (`_resolve` accepts `root / '<comp>.cfs' / src` and the legacy `root / src`).
`Path(cfs) / '/home'` is `/home`, and `<store>/<comp>.cfs/../../..` walks out of the store. Neither routecheck
nor the driver rejects such a `src:`. `via: dotfiles` isn't trust-gated (`command_trusted` is consulted only by
script/source/glue), so any synced data plugin, or a typo in your own layer, can supply one. With
`src: "../../../.."`, `dotfiles capture --force` targets `rmtree(~)` when there is no primary. The CLI
prints the dest in the plan before asking. The TUI "move to primary / move all" (`relocate`, no `--force`)
moved `~/Documents` out of place and rmtree'd a pre-existing directory at the computed destination.
`dst:` has the related gap the 2026-09 review raised. An unexpanded `$VAR` or a bare relative dst is
CWD-relative, and the launcher `cd`s into the repo, so the link lands in the repo.
**(reproduced)** `repro_src_traversal.py` (absolute src, `capture(force=True)`) →
`victim dir still has precious.txt? False | victim is now file`; `repro_relocate.py` (`src: ../../../Documents`) →
`relocate (TUI "move to primary", no --force): [('config', …/prim/dotfiles/evil-dotfiles.cfs/../../../Documents)]` ·
`~/Documents still exists? False | <state>/plugins/Documents/state-precious still exists? False`.
**Fix:** at load (routecheck), reject a dotfiles `src:`/`absorb-into:` that is absolute or contains a `..` part,
and a `dst:` that isn't under HOME after expansion. In the driver, assert
`dest.resolve().is_relative_to(cfs.resolve())` (and the same for `newpath`/`srcpath` against their roots)
before any unlink, rmtree or copy. Expand `dst:` with `paths.expand` semantics (home-relative) and refuse an
unexpanded `$VAR`. Tests for each. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced), and worse than written: `--force` is not needed. Stays HIGH, at the edge of CRITICAL. Sandbox `$V/c05cap/home` has `btop-dotfiles` picked. An untrusted data-only plugin, staged on disk, changes the shipped binding to `config: { src: "../../../../victim" … }`. `plugin list` shows it as plain `ok` / `provides: components`, with no trust prompt. `where btop-dotfiles` reports `defined in ~/.config/configsys/plugins/evilplug/evil.hu (overrides routes.hu)`. `check` reports `0 error(s), 1 warning(s)`, and the warning is the python-floor note. `dotfiles capture btop-dotfiles --yes`, with no `--force`, printed `~/.config/btop -> ~/.config/configsys/dotfiles/btop-dotfiles.cfs/../../../../victim`. The fence then logged `[fence] rmtree $H/victim`: `precious.txt` is gone, and `victim/` now holds `btop.conf`. Why `--force` is not needed: on a first capture the `.cfs` directory doesn't exist yet. So at plan time `dest.exists()` is False, and the plan says `copy` instead of `skip-exists`. `dest.parent.mkdir(parents=True)` then creates `.cfs`, and `dest` resolves to the escaped path just before `shutil.rmtree(dest)` runs. With `src: "../../../.."` (`$V/c05home`, fence set so the home is outside it), the same capture called `rmtree` on `…/btop-dotfiles.cfs/../../../..`, which is the home directory. The fence refused it (`PermissionError: [fence] refused rmtree outside sandbox`), and nothing was deleted. The TUI is worse. `m`/Enter (`manage`) and `M` (`manage-all`) call `capture(force=False)` without showing a plan or asking. I drove the real `DotfilesScreen.handle` headlessly (`$V/scripts/v05_tui.py`; only the curses `suspended` was stubbed) and pressed `m` on that row. The fence logged `[fence] rmtree $H/victim`, and the TUI note read `managing btop-dotfiles`. Relocate leg: `$V/scripts/v05_relocate.py` makes the call behind TUI `s`/`S`, `relocate(rc, <primary dotfiles>)`, with `src: ../../../Documents`. The fence logged `[fence] rmtree …/plugins/Documents` and then `[fence] rmtree …/home/Documents`. `~/Documents` and the unrelated `state-precious` were gone, and `thesis.tex` had moved to `plugins/Documents/`. No shipped route uses an absolute or `..` src (I grepped routes.hu, config.hu and examples/), and routecheck has no dotfiles check. The `dst:` / unexpanded-`$VAR` leg is verified by reading only, because reproducing it would write into the repo. HIGH matches security-01's calibration: a hostile or broken plugin plus one explicit user action. Even so, `rm -rf ~` is one TUI keypress away, with no prompt.

### dotfiles-glue-06 [MED] safety — glue backs up a displaced real file only once: the second real file is clobbered by `ln -sfn`, `~/.bash_aliases` backups are overwritten, and uninstall restores over a live `~/.bash_aliases`
`configsys/drivers/glue.py:1080-1081` (`install`: `mv -n t bak; ln -sfn s t`. With `bak` present, `mv -n` skips
and exits 0, so `ln -sfn` removes `t`), `:875-878` (`_link_bash_aliases`: `dst.rename(...pre-configsys)`
overwrites an earlier backup), `:628-631` (`_deploy_user_glue`: same `Path.rename`, named
`<file>.pre-configsys`, not the link's name), `:886-897` (`_remove_bash_aliases`: `absorb.rename(dst)` over a
real `~/.bash_aliases`). The dotfiles driver already has the never-overwrite helper `backup_cmd`
(dotfiles.py:52-59). Glue doesn't use it. The fix commit (`328d25e`) claimed "never over an existing backup", but
the clobber just moved one line down.
**(reproduced)** `repro_glue_backup.py` → `after 2nd install: target is symlink = True | backups: ['50-btop.fish.pre-configsys'] | backup content = MY FIRST CUSTOM` ·
`SECOND CUSTOM survives anywhere? False` · `.bash_aliases.pre-configsys = THIRD aliases (SECOND lost?)` ·
`after shell-glue uninstall, ~/.bash_aliases = ORIGINAL aliases` (the user's FOURTH, real file, gone).
**Fix:** use `backup_cmd`, or the Python primitive from -23, at all four sites. On uninstall, restore only when
`~/.bash_aliases` is absent after removing *our* link. Tests: second-displacement and restore-over-real-file.
**Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays MED. Real CLI with `CONFIGSYS_GLUE_SHELLS=fish` in `$V/c06`. `install --no-deps btop-glue` backs up a real `conf.d/50-btop.fish` (`MY FIRST CUSTOM`). After `remove btop-glue`, a second real file (`MY SECOND CUSTOM`), and a reinstall, the link is back in place. The only backup is `50-btop.fish.pre-configsys`, which holds `MY FIRST CUSTOM`, and `SECOND CUSTOM` is nowhere in the sandbox. `~/.bash_aliases` (`$V/c06b`, `CONFIGSYS_GLUE_SHELLS=bash`): I ran `install --no-deps shell-glue` three times, each over a new real file. Afterwards `.pre-configsys` holds THIRD, and SECOND is gone. A FOURTH real file followed by `remove shell-glue` leaves `~/.bash_aliases` holding ORIGINAL, and FOURTH is gone. The first leg depends on coreutils. When `mv -n` skips an existing target, it exits 0 on 8.32 (this host and Debian 11), 9.10 (Fedora 44), 9.11 (Arch) and busybox (Alpine), and `ln -sfn` then clobbers the file. On 9.4 (Ubuntu 24.04 and Void) it exits 1, so `set -e` aborts the script and the reinstall fails instead: nothing is lost, but the activation breaks. The `_deploy_user_glue` rename is verified by reading.

### dotfiles-glue-07 [MED] correctness — fish's `fish_add_path -ga` does not append to PATH: Homebrew (and 13 other "append" snippets) are put AHEAD of /usr/bin in fish, unlike the other four shells
`glue/shell/fish/homebrew.fish:8` (and bun, dotnet, cabal, composer×2, coursier, go, kubectl, luarocks, nim, deno,
dart, ruby). Without `-P`, fish appends to `fish_user_paths`, and fish always puts `fish_user_paths` *before*
the inherited PATH. In fish, Homebrew's `bin`/`sbin` therefore shadow system tools (`python3`, `git`,
`openssl`…). That is the opposite of the stated intent in the snippet ("APPENDED to PATH (so a formula fills
gaps, never shadows a system tool)") and of commit `3d5bb6b` ("Homebrew's bin/sbin on PATH after the
system's"). bash/zsh/nu/elvish append correctly.
**(reproduced)** `env -i HOME=… PATH=$RT/bin:/usr/bin:/bin … fish $RT/run_fish.fish` →
`PATH=/home/linuxbrew/.linuxbrew/bin PATH=/home/linuxbrew/.linuxbrew/sbin PATH=…/rt/bin PATH=/usr/bin PATH=/bin`.
**Fix:** `fish_add_path -gaP …` (operate on `$PATH` directly) or `set -gxa PATH …` (guarded with
`contains`). Add a fish case to a per-shell PATH-order test. **Effort:** S. **Tier:** B.

### dotfiles-glue-08 [MED] correctness — the zsh loader block leaks `null_glob` into your interactive session
`configsys/drivers/glue.py:120-123` (`_RC_SOURCE['zsh']`: `setopt local_options null_glob` at the top level of
`~/.zshrc`). `local_options` only scopes inside a function, so `null_glob` stays on for the rest of
`.zshrc` and the whole session. `ls *.foo` with no match then lists the cwd instead of erroring, and `rm *.bak`
runs `rm` with no operands. It also differs from bash's loader, which guards each file with `-r`; zsh's loop
`source`s a dangling link and prints an error (-28).
**(reproduced)** `zsh -f -c "source $S/zt/zshrc; [[ -o null_glob ]] && echo 'null_glob LEAKED …'"` →
`hi` / `null_glob LEAKED into the session`.
**Fix:** use a per-pattern qualifier and no setopt:
`for _f in {confd}/*.zsh(N); do [[ -r $_f ]] && source "$_f"; done; unset _f`. (An anonymous-function wrapper
would also scope it, but would make snippets' `typeset`s function-local.) The migration is simple, since the
block is regenerated in place. **Effort:** S. **Tier:** B.

### dotfiles-glue-09 [MED] correctness — `configsys.sh` `cd`s into the repo, so every relative path on the command line resolves against the clone (`plugin add .` declares the configsys repo itself)
`configsys.sh:6-7` (`cd "$here"`), then `exec "$VPY" -m configsys "$@"` (configsys.sh:78). `plugins.abs_local_source`
says it resolves "from the CWD at add-time", but through the launcher (what the `configsys`/`cfs` shell
functions run) the CWD is always the repo. `--home ./sandbox`, `--config ./x.hu`, `plugin add ./dir`,
`plugin set-source ../x` and `manpages install --prefix ./p` all point into the clone.
**(reproduced)** `cd $S/myplug && configsys.sh --home $S/home --pretend plugin add . --local` →
`[pretend] git clone --quiet -- /home/schrock/src/configsys …/plugins/configsys` ·
`configsys: [pretend] would declare /home/schrock/src/configsys in your top config`.
**Fix:** before the `cd`, `export CONFIGSYS_INVOKED_CWD="$PWD"`, and have `configsys/__main__.py` `os.chdir()` back to
it first thing. With `-m`, `sys.path[0]` is already the repo, so imports are unaffected. Alternatively do
the setup in a subshell (`( cd "$here" && … )`) and exec with `PYTHONPATH="$here"`. **Effort:** S. **Tier:** B.

### dotfiles-glue-10 [MED] correctness — invoked through a symlink (`ln -s …/configsys.sh ~/.local/bin/configsys`), the launcher treats the symlink's directory as the repo: it tries to build `.venv` there (even `sudo apt-get install pythonX-venv`) and can't import the package
`configsys.sh:6` (`here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` doesn't resolve symlinks). The natural
way to put configsys on PATH sends the fast path to `~/.local/bin/.venv`, which is missing, so it falls into
the repair branch in the wrong directory. Even if that succeeds, `python -m configsys` runs with
CWD=`~/.local/bin` and can't find the package. All five preludes *prefer* a `configsys` found on PATH, so the
symlink also breaks the shell function (`cfs`).
**(reproduced)** with a logging fake python on PATH, `env -i … $S/symlaunch/bin/configsys --help` →
`configsys: python venv support missing — installing python-venv (sudo)...` and the fake python logged
`cwd=…/symlaunch/bin` (sudo then refused without a terminal; nothing ran as root).
**Fix:** `src="${BASH_SOURCE[0]}"; while [ -L "$src" ]; do …readlink…; done`, or `readlink -f` (GNU and
busybox both have it), before computing `here`. Add a test that runs the launcher through a symlink with a
stub python. **Effort:** S. **Tier:** B.

### dotfiles-glue-11 [MED] correctness — the bootstrap can't start on EL9 (Alma/Rocky/RHEL/Oracle 9) or Amazon Linux 2023, both live releases whose `python3` is 3.9, even when python3.11/3.12 is installed, and the message names no fix
`configsys.sh:9-19` checks only `${PYTHON:-python3}`. The repo's own release registry flags this
(`routes.hu:114`, `:125`: "python3 3.9 is below configsys's 3.10 floor: the bootstrap needs a python3.1N route").
EL9 ships `python3.11`/`python3.12` packages and AL2023 ships `python3.11`, but the script neither probes for
them nor says `PYTHON=` exists.
**(reproduced)** fake EL9 `python3` (3.9) plus a real interpreter as `python3.12` on PATH →
`configsys: python >= 3.10 required (found: Python 3.9.18).`
**Fix:** when `$PYTHON` is unset, try `python3.14 … python3.10 python3` and take the first ≥ 3.10. On failure,
print `PYTHON=/path/to/python3.1x` and the distro's install command (`dnf install python3.12`; the hint
table already exists at configsys.sh:64-71). **Effort:** S. **Tier:** B.

### dotfiles-glue-12 [MED] safety — a shell START can trigger the whole bootstrap repair (venv rebuild, pip compile, even `sudo apt-get`) with every explanatory line hidden, and two terminals race the same `venv --clear`
`glue/shell/{bash,zsh}/00-configsys.*:33-37`, `fish/00-configsys.fish:41-45`, `nu/00-configsys.nu:37-46`,
`elvish/00-configsys.elv:42-55` run `configsys location --all 2>/dev/null` on a cold or stale cache, through
the launcher. If the venv broke (a distro release upgrade replaces `/usr/bin/python3.X`), `configsys.sh:36-75`
rebuilds the venv, `pip install`s and *compiles* humon, or runs `sudo apt-get install -y pythonX.Y-venv`,
while opening a terminal. stderr is discarded, so the user sees a hung shell or a bare `[sudo] password`
prompt (sudo writes to the tty). There is no lock, so concurrent shells run `python -m venv --clear .venv` at
the same time. That breaks principles.md's no-surprises and "confirm before root" rules. Verified by reading.
**Fix:** have the preludes call the launcher with `CONFIGSYS_NO_BOOTSTRAP=1`. With it set, `configsys.sh`
exits non-zero instead of repairing when `_venv_ok` fails, and the prelude keeps the stale cache. Take an
`flock` on `$VENV.lock` around the repair. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced with stubs). Stays MED. `$V/c12` (`$C` below) holds a scratch copy of `configsys.sh` beside a dangling `.venv/bin/python` (as after a release upgrade), a fake `python3` whose `import ensurepip` fails, and fake `sudo`/`apt-get` that only log and exit 1. I then ran `env -i HOME=$C/home PATH=$C/bin:/usr/bin:/bin CONFIGSYS_LAUNCHER=$C/clone/configsys.sh bash -c 'source glue/shell/bash/00-configsys.sh'` with a cold cache, as any new shell would. The log shows `python3 -c import ensurepip` and then `SUDO apt-get install -y python3.10-venv`. The shell printed nothing: the `installing python3.10-venv (sudo)` line went to the prelude's `2>/dev/null`, and stdout is swallowed into `_CS_LOCS`. A real sudo would show only its bare `[sudo] password` prompt on the tty. A failed run never rewrites `glue-locations.tsv`, so every later shell tries again. All five preludes call `configsys location --all` the same way: bash, zsh, fish and elvish with `2>/dev/null`, and nu through `complete`. The `venv --clear` race is verified by reading: there is no lock.

### dotfiles-glue-13 [MED] correctness — shellguard reads rc files as text: a non-UTF-8 `~/.bashrc` makes `arm` raise outside `run_plan`'s try, aborting the batch before the ledger is saved; CRLF rc files are rewritten LF
`configsys/shellguard.py:50-56` (`_read` catches `OSError` but not `UnicodeDecodeError`), `:162`
(`write_text`), and `actions.py:237-238` (where `arm` is called, before the `try`). One Latin-1 comment in
`~/.bashrc` makes every guarded install raise. The exception escapes `run_plan`, which skips `end_sudo()`,
`ledger.save()` (receipts for earlier successful ops in the batch are lost) and `record_run`. The module
docstring promises "exactly their prior bytes", but a CRLF file comes back LF. The same default-encoding
`read_text()` in `glue.py:763, 798, 823, 913` (only `OSError` caught) can crash an inline regeneration.
**(reproduced)** `printf '# caf\xe9 …' > ~/.bashrc; shellguard.arm(...)` →
`arm raised: UnicodeDecodeError 'utf-8' codec can't decode byte 0xe9 …`; CRLF case →
`after revert bytes: b'alias a=b\nalias c=d\n'`.
**Fix:** snapshot and restore with `read_bytes`/`write_bytes`, and decode with `errors='surrogateescape'` only to
diff. Arm inside the `try` (or catch in `arm` and return None with a warning). **Effort:** S. **Tier:** B.

### dotfiles-glue-14 [MED] safety — the shell-writes guard covers 5 bash/zsh files only: `.zshenv`, `.bash_login`, fish's `config.fish`/`conf.d`, `config.nu`, `rc.elv` are unwatched (a safety feature with partial coverage)
`configsys/shellguard.py:35-36` (`GUARDED`). principles.md: "a safety/advisory feature must have uniform coverage,
or not ship". A zsh user is protected from `.zshrc` writes but not `.zshenv`, which rustup-family installers
use for zsh. Medium confidence that the shipped `elan-init.sh … -y` (routes.hu:1231, no `--no-modify-path`)
writes it. fish, nushell and elvish users get no guard at all. docs/shell-glue.md:191 states the gap but
doesn't flag it as a coverage hole. Verified by reading.
**Fix:** drive `GUARDED` from the per-shell table (-23). Add `.zshenv`, `.zlogin`, `.bash_login`,
`$XDG_CONFIG_HOME/fish/config.fish`, `rc.elv` and `config.nu` (exempting configsys's own marker block, as now).
For fish `conf.d/`, snapshot the directory listing and stage any new non-configsys file. **Effort:** M.
**Tier:** A.

**Verified:** CONFIRMED (by reading). Stays MED. `shellguard.GUARDED` is exactly `.bashrc`, `.bash_profile`, `.profile`, `.zshrc` and `.zprofile`. Nothing covers `.zshenv`, `.zlogin`, `.bash_login`, a `$ZDOTDIR` rc, fish, nushell or elvish. docs/shell-glue.md:190-191 says so ("Nothing else is watched …") without calling it a coverage hole. Caveat: no shipped installer was shown to hit the gap. rustup runs with `--no-modify-path`, and ghcup runs non-interactive. The cited `elan-init.sh -y` forks rustup's pre-1.23 PATH logic. If it still follows that logic, it writes `.profile`, `$ZDOTDIR/.zprofile` and an existing `.bash_profile`, not `.zshenv`. Those are guarded unless `ZDOTDIR` is set. I couldn't check that offline. So MED rests on principles.md's uniform-coverage rule for a safety feature, not on an observed write.

### dotfiles-glue-15 [MED] performance — `cs_loc` in bash/zsh/fish is a linear scan per call (plus a subshell fork per `$(cs_loc x)` in bash/zsh): ~100 ms per shell start with a realistic cache
`glue/shell/bash/00-configsys.sh:39-45`, `zsh/00-configsys.zsh:39-45`, `fish/00-configsys.fish:46-54`. 55 snippets
per shell call it. Each `_x=$(cs_loc x)` forks a subshell and re-reads the whole TSV through a here-string.
nu (record) and elvish (map) are O(1).
**(reproduced)** 48 lookups against a 60-line `glue-locations.tsv`: bash `93 ms`, zsh `110 ms`, fish `96 ms`
(a 150-line cache: bash 98, zsh 112). The same 48 lookups from a bash associative array took `2.4 ms`.
For comparison, the whole glue load measured ~0.2 s with a one-line cache.
**Fix:** in the bash/zsh preludes, load the TSV once into `declare -A _CS_LOC` / `typeset -gA _CS_LOC`, and make
`cs_loc` print `${_CS_LOC[$1]}`. Better, let snippets read `${_CS_LOC[go]}` directly (no fork). In fish, keep two
parallel lists and use `contains -i`. **Effort:** S. **Tier:** C.

### dotfiles-glue-16 [MED] performance — the cached `pyenv init -` still runs `command pyenv rehash` on every start (~70 ms bash, ~110 ms fish — the single most expensive snippet)
`glue/shell/bash/pyenv.sh:4`, `zsh/pyenv.zsh:4`, `fish/pyenv.fish:4`. `cs_cached` caches the *text* of
`pyenv init -`, which includes `command pyenv rehash` (and, for fish, sourcing pyenv's completions).
**(reproduced)** `pyenv init - bash` eval: `0.07 s`; `pyenv init - --no-rehash bash` eval: `0.00 s`. Removing
`pyenv.fish` drops a non-interactive `fish -c true` from `0.21 s` to `0.10 s`. Per-snippet timing (bash, warm):
`54 pyenv.sh 45 gnustep.sh 8 zoxide.sh …`.
**Fix:** `pyenv init - --no-rehash <shell>`. pyenv rehashes on `pyenv install` and pip installs itself, and the
cache key should change with the flag. Consider caching GNUstep's env (45 ms) the way the nu bridge does.
**Effort:** S. **Tier:** C.

### dotfiles-glue-17 [MED] safety — removing `shell-glue` strips the loader block from a captured `~/.zshrc` THROUGH its symlink (your portable zshrc in the primary, unjournaled), and installing can never put it back
`configsys/drivers/glue.py:899-918` (`_remove_shell_loader` has no `is_symlink` check, so `write_text` follows the
link) versus `:820-821` (`_ensure_shell_loader` refuses a symlinked rc). `configsys remove shell-glue` on one
machine edits the primary's `zsh-dotfiles.cfs/zshrc` without `primarygit.will_write`. Once you push or
commit it, every other machine's zsh stops sourcing conf.d, and their `shell-glue` install can't restore it.
**(reproduced)** a `~/.zshrc` linked to a primary-held zshrc that contains the block; `Glue.uninstall(shell-glue)` →
`primary zshrc still has the block? False | ~/.zshrc still a link: True`; re-install → block still absent.
**Fix:** make removal symmetric: never write through a symlinked rc, and instead advise that the block lives
in your captured zshrc. Or, if editing the captured file is wanted, do it in both directions under
`primarygit.will_write`, with consent. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays MED. Real CLI in `$V/c17` with `CONFIGSYS_GLUE_SHELLS=zsh`: a captured zshrc holding the block, with `~/.zshrc` linked to it by hand so -01 can't interfere. `remove shell-glue` prints `-> ok`. Afterwards the captured file no longer contains the block (`grep -c` gives 0), and `~/.zshrc` is still the link. `install --no-deps shell-glue` prints `-> ok`, but the block is still missing, and the file holds just the user's two lines. `_remove_shell_loader` has no symlink check and no `will_write`. `_ensure_shell_loader` returns False for a symlinked rc, and `install` ignores the return value. The plain `-> ok` on the reinstall also hides the problem: glue is in `actions._NO_POST_CHECK`, so nothing hints that every zsh snippet is now dead (see the note under -18).

### dotfiles-glue-18 [MED] correctness — with `~/.zshrc` linked to a captured rc that lacks the block, `install shell-glue` says "hooked up", nothing is hooked, and the op loop blames "a detection bug"
`configsys/drivers/glue.py:1036-1039` ignores `_ensure_shell_loader`'s `False`. `get_version` then returns None
forever (`_loader_ok`, glue.py:928-930), and `run_plan` prints "ok, but NOT DETECTED afterwards — a detection
bug in its route/driver". Every zsh snippet is silently inactive. (Carried from 2026-09.)
**(reproduced)** `Glue.install(shell-glue)` with a symlinked `~/.zshrc` → `install: True | glue: conf.d loader hooked up (zsh) | get_version -> None`, `spec_states: ['loader-off']`.
**Fix:** return an advisory `Result` naming the fix: add the conf.d block to your captured zshrc
(`configsys dotfiles …`), or offer to insert it through the link under the journal. Give `_loader_ok` a
distinct `delegated` state when the captured rc already sources conf.d some other way. **Effort:** S.
**Tier:** B.

**Checker note (incidental, not a verification of -18):** one sub-claim is wrong. `run_plan` never prints "NOT DETECTED afterwards — a detection bug" for glue: `actions._NO_POST_CHECK = frozenset({'dotfiles', 'glue'})` makes `detected_after` return True, and the shell-glue reinstall in -17's repro printed a plain `-> ok`. That silence is the real problem. The rest of -18 was not checked.

### dotfiles-glue-19 [LOW] security — every shell hookup chmods each `user.d` snippet to exactly 0755, widening a private 0600 snippet (API keys) to world-readable; the stated reason is false
`configsys/drivers/glue.py:614-617` (`_deploy_user_glue`: `if mode & 0o777 != 0o755: chmod(0o755)` "loaders
source only a+x files"), also `:332`, `:368`. The bash loader deliberately gates on `-r`, not `-x`
(`glue/bash_aliases:4-6`), and zsh's `source` and fish's conf.d ignore the x bit. People keep tokens in rc
snippets. `_deploy_user_glue` runs on every snippet (de)activation, and in the primary the mode change is
also journaled.
**(reproduced)** a `user.d/secrets.sh` at `0o600`, `deploy_user_glue('bash')` → `after deploy_user_glue: 0o755`.
**Fix:** don't chmod user content. At most add `u+x` (`mode | 0o100`) when a loader needs it; none of ours does.
Fix the comment. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Severity MED → LOW. In `$V/c19`, a user.d `secrets.sh` at mode 600 and then a plain `install --no-deps shell-glue` (`CONFIGSYS_GLUE_SHELLS=bash`) leave the snippet at `755`, linked as `90-secrets.sh`. No loader needs the x bit: bash_aliases gates on `-r`, and zsh `source`, fish conf.d and the inline shells ignore it. Why the severity changed: the wider mode only exposes the file when another local user can traverse the home. In the cached images, a fresh user's home (`useradd -m` / `adduser -D`) is 750 on Ubuntu noble and 700 on Fedora 44, Oracle 9, Arch, openSUSE and Void, so other users can't reach it. Debian 11 (755) and Alpine (2755) homes are traversable, and so are homes created before Ubuntu 21.04 (this host's is 750). git records only 644 or 755, so a push leaks nothing more. What remains is a needless chmod of user content and a false comment, with a narrow exposure: LOW.

### dotfiles-glue-20 [MED] safety — the nu/elvish inline block is written unvalidated and goes stale silently (user.d edits, a primary sync, a tool upgrade's `#!cs-eval` output); one bad snippet makes `config.nu` unparsable for every new shell
`configsys/drivers/glue.py:747-775, 822-834`. nushell parses the whole program before running (the module's own
comment, glue.py:100-102), so a syntax error in any inlined snippet, or in a generator's output from an
incompatible zoxide/atuin/nu pairing, disables the entire config.nu. That includes PATH and the user's own
lines. Nothing checks the block before writing it. That breaks principles.md's validate-before-commit rule:
"no half-applied state that wedges the next run". It is also a snapshot. Hand edits to a linked
`99-user.nu`, user.d changes pulled by `plugin sync`, or a tool upgrade never reach it until some unrelated
glue toggle. The Glue screen keeps showing those rows `linked`. bash/zsh/fish source the live file, and
`cs_cached` re-runs an init when the tool's binary changes; the inline shells have neither. All 80 nu and
71 elvish snippets do pass `nu-check` / `elvish -compileonly` today (checked), so this is a robustness gap,
not a current break. Verified by reading.
**Fix:** before writing, run `nu --no-config-file -c 'nu-check <tmp>'` / `elvish -compileonly <tmp>` when the
binary is present. If it fails, rebuild without the failing snippets (check per snippet) and warn. Record a
hash of the inlined inputs (snippet contents plus the generator tools' mtimes) in the block header, and have
`spec_states`/`get_version` report `changed` when it differs, so the Glue screen offers a refresh, as it does for
component drift. Refresh after `plugin sync` of a primary that ships user.d. **Effort:** M. **Tier:** A.

**Verified:** CONFIRMED (reproduced) for the validation half; the staleness half is documented design. Stays MED. Setup in `$V/c20` with nu 0.116.1: a `config.nu` holding one user line (`$env.USER_LINE = …`), which applies before configsys touches anything, and a user.d `mytypo.nu` missing its closing `}`. `CONFIGSYS_GLUE_SHELLS=nu configsys --home $H install --no-deps shell-glue` prints `-> ok`, and the block now inlines the snippet. Starting nu with that config gives `Error: nu::parser::unclosed_delimiter … config.nu:7:25` and exit 1, and the user's own line no longer applies. `nu-check` on the written file returns `false`, so a check before writing would have caught it. In bash, zsh and fish the same typo breaks only that one snippet. The snapshot behavior is documented in docs/shell-glue.md:27-31 ("regenerated on every glue (de)activation"). What remains of that half is that the Glue screen shows `linked`/`active` for content the block doesn't hold. Mitigation: nu prints the error at shell start, along with the snippet's `# >> 90-…` header.

### dotfiles-glue-21 [MED] security — `via: dotfiles` templates from an untrusted data plugin are not trust-gated, though one aimed at `~/.zshenv`, an autostart entry or `~/.local/bin` is as executable as glue
`configsys/drivers/dotfiles.py:584-668` (`install`; no `command_trusted` call). docs/plugins.md §6 draws the line at
"does configsys run something from it as a program", and puts glue on the code side because "it is sourced
at every shell start". A dotfiles template linked to `~/.zshenv` (absent on most boxes, so not refused as
"un-adopted") is sourced the same way. Bindings merge across layers and plugins can set `suggests:` on
existing components, so an untrusted plugin can attach one to something you already pick. The difference
from today's exposure is modest, because an untrusted plugin's download bindings can already deliver a binary
you will run (the security reviewer's security-02). This is consistency, not a new capability. Verified by
reading (`driver.py:180-189`, `plugins.py:447-456`).
**Fix:** gate `DotFiles.install`'s template tier on `command_trusted(rc)` when the template comes from a plugin
layer (a user's own captured content stays ungated). Extend `ships_executable_data` to count a `dotfiles/`
tree, so `plugin trust` can accept it. **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced). Stays MED. `$V/c21` has two untrusted plugins staged on disk. `dfplug` ships only a dotfiles template (`dotfiles/evil-dotfiles.cfs/zshenv`, `dst: ~/.zshenv`), and `glueplug` ships only a zsh glue snippet. `plugin list` shows `dfplug … ok`, but `glueplug … ok [ships recipes — untrusted; run: configsys plugin trust glueplug]`. `install --no-deps evil-glue` is refused with `refusing to run glue commands from the untrusted plugin 'glueplug'`. `install --no-deps evil-dotfiles` prints `-> ok` and links `~/.zshenv -> ~/.config/configsys/dotfiles/zshenv`. After that, `env -i HOME=$H PATH=/usr/bin:/bin zsh -c true` prints `PWNED: untrusted plugin code ran in every zsh`. The finding's own caveat still holds: download bindings already deliver binaries (security-02), so this is a consistency fix.

### dotfiles-glue-22 [MED] safety — "move to local (this box only)" deletes the config from your primary, so every other machine loses it on its next sync (their links dangle)
`configsys/drivers/dotfiles.py:494-519` (`relocate`: copy, then `shutil.rmtree(srcpath)` / `unlink`, journaled via
`will_write`). It is reached from the TUI Dotfiles `move-store`/`move-store-all`, whose chooser labels the target
"local (this box only)". Moving primary → local commits a deletion in the primary. After the sync, other
machines' `~/.config/<app>` links point at a removed `.cfs` path, and the app silently starts with no config
(or recreates defaults). Verified by reading.
**Fix:** for primary → local, copy and leave the primary alone (it "stops traveling" only if the user also
removes it), or confirm with "this removes <comp>'s config from your primary — your other machines lose it
on next sync". **Effort:** S. **Tier:** A.

**Verified:** CONFIRMED (reproduced in-process). Stays MED. `$V/scripts/v22_move_local.py` makes the call behind the TUI's `s`/`S` → "local (this box only)": `relocate(rc, user_dotfiles_dir)` on a primary-held `btop-dotfiles.cfs`. The primary tree goes from `['btop-dotfiles.cfs', …/btop/btop.conf, …/manifest.hu]` to `[]`. This box's link is moved to the local store. Another box's link to the same primary path no longer resolves (`resolves? False`). `relocate` calls `will_write` on both sides, so the deletion is journaled and committed. Worse than written: the single-row `s` asks for no confirmation at all; only `S` shows the chooser. The config is recoverable (`plugin undo`, git history, this box's local copy), hence MED.

### dotfiles-glue-23 [MED] refactor — a shared `LinkedContentDriver` plus a `ShellSpec` table (README D7)
glue.py and dotfiles.py share ~50 verbatim lines (`_home`, `_env`, `_expand` + `_VAR`, `repl`, `get_latest`,
`upgrade`, `set_version`; measured with an AST diff) and four more near-copies (`_content_roots`,
`_store_path`, `_materialize_to`, `_resolve`). The duplicated part that matters is behavior: the
link-with-backup shell fragment, the restore-on-uninstall fragment and the backup policy, which exist four
times with four different safety properties (-03, -05, -06, -17, -29). Per-shell knowledge is in eight places:
`_SHELL_EXT`, `_SHELL_CONFD`, `_GLUE_SHELLS`, `_SHELL_COMPONENT`, `_SHELL_RC`, `_INLINE_SHELLS`, `_RC_SOURCE`,
shellguard's `GUARDED` and `_old_confd`, plus `if shell == 'bash'` branches in five methods. `spec_states`
returns a positional 7-tuple unpacked in three places (app.py:4372, menu.py:4571, 4609).
**Fix:** `drivers/_linked.py` with one pretend-aware Python `link(src, dst, *, backup)` /
`unlink(dst, *, restore)` that checks ownership (realpath inside our content roots) and containment, and
writes numbered backups. Both drivers and `_link_bash_aliases` use it, and `os.symlink` replaces the bash
script. Add a frozen `ShellSpec(name, ext, confd, rc, mode ∈ {native, rc-block, inline, bash-aliases},
component, guarded_files)` consumed by glue, shellguard, and the TUI grouping, and a `SpecState` NamedTuple.
This removes the backup/restore/containment bug class and makes adding a shell a one-row change. **Effort:** L.
**Tier:** D.

### dotfiles-glue-24 [LOW] performance — `_installed_shells()` (5× `which`, a cache read, globs) is recomputed for every glue name on every call
`configsys/drivers/glue.py:156-170`, called from `_glue_variants` (`:222`) through `_specs` on each `get_version`,
`spec_states`, `install`, `location`. `get_driver` builds a fresh instance per call, so an instance memo helps
only partly. (Carried, downgraded from MED.)
**(reproduced)** `time_states.py`: 82 glue components × (`get_version` + `spec_states`) → `calls: 164 time 386 ms`,
with `_installed_shells` memoized → `221 ms`.
**Fix:** a module-level memo keyed on `(PATH, CONFIGSYS_GLUE_SHELLS, glue-locations mtime)` with a few
seconds' TTL. **Effort:** S. **Tier:** C.

### dotfiles-glue-25 [LOW] performance — TUI "activate group" regenerates the inline block and re-runs every generator once per snippet
`configsys/drivers/glue.py:1089-1090` (each `install` calls `_ensure_shell_loader`, which calls `_inline_block`),
driven by `tui/screens/glue.py:208-225`. (Carried, downgraded from MED.)
**(reproduced)** `time_group.py`: 80 nu snippets → `1.09s; calls={'inline': 80, 'eval': 76, …}`.
**Fix:** `install(rc, only_shells, *, hookup=True)`. The group action passes `hookup=False` and calls
`_ensure_shell_loader` once at the end. **Effort:** S. **Tier:** C.

### dotfiles-glue-26 [LOW] correctness — the fish prelude never refreshes a stale (>1 h) location cache
`glue/shell/fish/00-configsys.fish:41`: `test -n (find … -mmin -60 | string collect)`. When `find` prints
nothing, the substitution expands to *no* argument, and `test -n` with one argument is true. A stale cache
is read forever (only deletion by `invalidate_location_cache` refreshes it). The comment says otherwise, and
the other four shells behave as documented.
**(reproduced)** a 3-hour-old cache and a fake `configsys` printing `/NEW/path` → `bash: /NEW/path`,
`zsh: /NEW/path`, `fish: /old/path`, `nu: /NEW/path`; `fish -c 'test -n; echo $status'` → `0`.
**Fix:** `set -l fresh (find …); if test -f $_cs_cache; and set -q fresh[1]`. **Effort:** S. **Tier:** B.

### dotfiles-glue-27 [LOW] correctness — a plugin's bash snippet activated directly (TUI `a`) before `shell-glue` gets no loader, yet reports "activated"
`configsys/drivers/glue.py:865-871` (`_link_bash_aliases` resolves `bash_aliases` only through
`_content_roots(rc)`: the store, the primary, and the snippet's own defining layer). A plugin layer ships no
`bash_aliases`, so on a fresh box the TUI's direct activate (which bypasses `requires: shell-glue`, per the
comment at `:1086-1088`) links the snippet and nothing sources it.
**(reproduced)** → `install: True activated blender-glue` · `~/.bash_aliases exists: False | repo ships loader: True`.
**Fix:** resolve `bash_aliases` from `paths.glue_dir` (the repo owns the loader) as a final fallback.
**Effort:** S. **Tier:** B.

### dotfiles-glue-28 [LOW] correctness — a removed user.d snippet leaves a dangling `90-*` link forever; zsh then prints an error at every start
`configsys/drivers/glue.py:581-634` (`_deploy_user_glue` links what exists and never prunes). The TUI's own advice
for user glue ("delete or move {file} to stop it loading", `tui/screens/glue.py:193-194`) produces exactly this.
So does a primary sync from a machine where you deleted the snippet. bash's loader skips it (`-r`), but the zsh
block has no guard (-08).
**(reproduced)** after deleting `user.d/foo.zsh` and re-deploying → `conf.d: [('90-foo.zsh', False), ('99-user.zsh', True)]`;
zsh → `source:2: no such file or directory: …/conf.d/90-foo.zsh`.
**Fix:** in `_deploy_user_glue`, remove `90-`/`NN-` links that point into a user.d root but whose target no
longer exists (ownership via `_link_into_owned(user_d=True)`). **Effort:** S. **Tier:** B.

### dotfiles-glue-29 [LOW] safety — `_link_bash_aliases` silently discards a foreign `~/.bash_aliases` symlink (stow/chezmoi)
`configsys/drivers/glue.py:873-874` (`if dst.is_symlink(): dst.unlink()`, ours or not). This runs on *every* bash
snippet activation, not just `shell-glue`, and `_remove_bash_aliases` can't restore the link. (Carried.)
Verified by reading.
**Fix:** a symlink that doesn't resolve into our store is "a real file". Absorb what it points at, or record
the link target in a sidecar and restore it on removal. **Effort:** S. **Tier:** A.

### dotfiles-glue-30 [LOW] correctness — a hand-edited `manifest.hu` typo raises out of `install`/`capture` and aborts the whole batch
`configsys/drivers/dotfiles.py:177-195` (`_read_manifest`: `troveio.load` raises `ConfigError`; a list-shaped `specs:`
yields a `None` key that `_write_manifest` would then emit). It is reached from `install` → `_ensure_marker`,
which `run_plan` doesn't catch. The docs invite editing `exclude:` in this file.
**(reproduced)** `{ specs: { nvim: { src: x  dst: ` → `raised ConfigError …`; `{ specs: [ a b ] }` →
`{None: {'src': None, 'dst': '', 'exclude': []}}`.
**Fix:** catch it and return an advisory `Result` naming the file. Skip non-map spec nodes. **Effort:** S.
**Tier:** B.

### dotfiles-glue-31 [LOW] security — `#!cs-eval` is honored in any conf.d file and on any line; generators run inside configsys (during a batch's warm sudo window) with no timeout
`configsys/drivers/glue.py:758-785, 787-794`. `_inline_block` iterates every `*.nu`/`*.elv` in conf.d (ours or
not). `_eval_directive` matches any line, and `_run_eval` has no timeout, so a hung generator hangs the TUI.
The exposure is low: conf.d is a configsys-only directory, and whoever can write it can write config.nu.
(Carried, merging the 2026-09 MED and NIT.)
**Fix:** honor the directive only on line 1–3 of a file whose realpath is inside an owned glue root. Add a
timeout (`capture=True, timeout=10`). Document the trust model in the module docstring. **Effort:** S.
**Tier:** A.

### dotfiles-glue-32 [LOW] correctness — glue targets hard-code `~/.config` while fish/nushell/elvish read `$XDG_CONFIG_HOME`
`configsys/drivers/glue.py:51-53, 95-96` (`_SHELL_CONFD`, `_SHELL_RC`), `glue/bash_aliases:7-8`. With a custom
`XDG_CONFIG_HOME`, fish never auto-sources `~/.config/fish/conf.d`, and nu/elvish never read the rc that gets
the block. The dotfiles driver, the state dir and every prelude honor `XDG_CONFIG_HOME`. Verified by reading.
**Fix:** express the targets as `$XDG_CONFIG_HOME/<shell>/…` and expand them with the existing `_expand`
(which already defaults it). **Effort:** S. **Tier:** B.

### dotfiles-glue-33 [LOW] parity — glue's CLI and TUI each lack half the verbs, and staged glue lives under `dotfiles`
TUI: no review/activate/discard for staged blocks (shellguard's message, `shellguard.py:208-210`, points only at
`configsys dotfiles staged|activate`), no `glue add`, no `glue override`, no override-drift marker. CLI: no
per-shell activate/deactivate (the TUI has it via `only_shells`), no `glue status` (it's a table inside
`dotfiles status`), and no way to regenerate an inline block (-20). (Carried; the app/actions halves belong to
the app-cli area.) Verified by reading.
**Fix:** `configsys glue status|activate|deactivate [--shell S]|staged|discard`, keeping `dotfiles staged|activate|discard`
as aliases for a release. A "staged" group on the Glue screen. `a`/`o` keys on it for add/override.
**Effort:** M. **Tier:** G.

### dotfiles-glue-34 [LOW] performance — fish runs every conf.d snippet for non-interactive `fish -c`; interactive-only init isn't behind `status is-interactive`
fish sources conf.d for scripts too. zoxide/atuin/fzf init, kubectl completions and the aliases all run for
`vim :!cmd`, `tmux run-shell`, and tools that use `$SHELL -c` when fish is the login shell.
**(reproduced)** with all fish glue linked: `fish -c true` `0.21 s` vs `0.03 s` with none (`0.10 s` after removing
pyenv, -16).
**Fix:** `status is-interactive; or return` at the top of init/completion/keybinding/alias snippets (PATH/env ones
must still run). `apod.fish` already does this. **Effort:** S. **Tier:** C.

### dotfiles-glue-35 [LOW] safety — the bootstrap installs unpinned `humon`/`packaging`, and the user's `PYTHONPATH`/`PYTHONHOME` leak into the venv interpreter
`configsys.sh:61` (`pip install -q humon packaging`, so a fresh box gets whatever is newest: an API break or a
compromised release reaches only *new* machines) and `:34`/`:78` (`exec "$VPY" -m configsys`, so e.g. a ROS
`setup.bash`'s `PYTHONPATH` shadows the venv's `packaging`). `pyproject.toml` has only `humon>=0.1.0`.
Verified by reading.
**Fix:** pin compatible ranges (`'humon>=0.1,<0.2' 'packaging>=23'`) in one place that both files read. Exec with
`-E` (ignores `PYTHON*`, keeps `-m`'s CWD path). **Effort:** S. **Tier:** A.

### dotfiles-glue-36 [LOW] performance — the bootstrap's fast path starts two interpreters before the real one
`configsys.sh:16` (floor check with `$PY`) runs before `:33` (`_venv_ok` with `$VPY`) on every call. Once the
venv is healthy the floor check is redundant (`_venv_ok` can test `sys.version_info` in the same start).
**(reproduced)** floor check `0.03 s`, `_venv_ok` `0.02 s` per call. **Fix:** try `_venv_ok` (extended with the
version test) first, and run the floor check only on the repair path. **Effort:** S. **Tier:** C.

### dotfiles-glue-37 [LOW] comment-drift — owned comments that describe code that no longer exists
- `dotfiles.py:9-12`: "Install symlinks dst -> src (edits flow back to the repo…)" (links never target the repo;
  templates are refused by default) and "uninstall removes our symlink" (it removes any symlink, -03).
- `dotfiles.py:400`: `_suggest_secrets` "top level + one deep" (it is a full `rglob`, minus symlinked dirs).
- `dotfiles.py:690`: "only remove our own symlink" (any symlink).
- `glue.py:7`: "(and, later, its own TUI page)" (the Glue screen exists). `glue.py:48-49`: "Repo ships bash variants
  today" (all five shells ship). `glue.py:124-125`: an elvish comment inside `_RC_SOURCE`, which has no elvish
  entry. `glue.py:817`: "fish / nu: dir is the whole job" (only fish reaches it). `glue.py:617, 655`: "the loader
  sources only executable files" (false, -19). `glue.py:1079`: "-n never overwrites an existing backup" (true,
  but the next line clobbers, -06).
- `shellguard.py:7`: "REVERT the files to exactly their prior bytes" (text mode, -13).
- `glue/bash_aliases:2-3`: "00-configsys.sh runs first and exports the CONFIGSYS_*_DIR layout vars" (no prelude
  exports them; paths.py:16-17 repeats the claim).
- `glue/shell/fish/homebrew.fish:1` (and the fish `-ga` snippets): "APPENDED to PATH" (-07);
  `fish/00-configsys.fish:38-39`: "a cold/stale (>1h) cache spawns…" (stale never does, -26);
  `configsys.sh:27`: "this runs on EVERY `configsys` call (the shell glue calls it at startup)" (the glue now
  calls it only on a cold/stale cache).
Verified by reading each. **Fix:** one comment pass after the fixes above. **Effort:** S. **Tier:** E.

### dotfiles-glue-38 [LOW] dead-code — stragglers from the split and the band migration
`dotfiles.py:238-241` `_excludes_for` (no callers); `glue.py:228-229` the `bash.d/<glue>.sh` "legacy authoring
layout" fallback (no glue root ever had a `bash.d/`); `dotfiles.py:217-222` `_config_specs`' `bash.d/`/`shell/`
filter (no route uses those srcs any more); `glue.py:124-125` the orphaned elvish comment; `glue.py:450, 1060`
re-implement `_shell_of` inline; `dotfiles.py:648, 684` function-level `import shlex`; `test_dotfiles.py:19-24`
sets `CONFIGSYS_GLUE_SHELLS`, which the dotfiles driver never reads. Grep evidence is under "Dead code".
**Fix:** delete them (keep `absorb-into`: it is documented in config-format.md:740). **Effort:** S. **Tier:** D.

### dotfiles-glue-39 [LOW] security — a primary plugin's user.d snippets and its overrides of repo components' glue go live without the trust check docs/plugins.md promises for the primary
`configsys/drivers/glue.py:581-634` (`_deploy_user_glue` links every `<primary>/glue/shell/*/user.d/*` with no
`command_trusted`; the links point at the live git working tree, so a `plugin sync` changes what your next
shell sources) and `:1031` (`install` checks `command_trusted(rc)` against `rc.source`, the *repo* for a repo
component, even when the snippet resolved is a primary override). docs/plugins.md:230-231 says "Your primary
plugin follows the same rule: if it carries code or command-carrying data, trust it too", and
`ships_executable_data` counts `glue/` content. The code doesn't enforce it here. The brief's baseline
already accepts that a pusher to your primary runs code (any captured rc linked into the primary is the same
exposure), so this is a docs/code mismatch to settle, not a new hole. Verified by reading.
**Fix:** decide the model (Questions, 3). Either gate user.d and override resolution on
`command_source_trusted(paths, <primary file>)`, or say in plugins.md that the primary's glue and dotfiles are
trusted as you. **Effort:** S. **Tier:** E.

### dotfiles-glue-40 [NIT] parity — snippet-level cross-shell nits
- `nu/vulkan-sdk.nu:6` splices `$vk` into a bash string with `"` quoting (carried; the value comes from
  configsys's own cache). Pass it through the environment instead.
- nu/elvish `configsys` fallback prints "launcher not found" but succeeds; bash/zsh/fish `return 127`.
- `nu/neovim.nu` always defines `v`/`vi` (falling back to `nvim`, so it shadows system `vi`); the other shells
  define them only when the managed AppImage exists.
- `nu/00-configsys.nu:100` caches `cs-bash-env` deltas under the *state* dir (`nu-bash-env/<md5>.nuon`), never
  pruned; bash/zsh/fish `cs_cached` uses `~/.cache/configsys/glue-eval`. Its 1 h TTL also ignores tool upgrades.
- `bash/go.sh:5` / `zsh/go.zsh` append `$GOBIN` unconditionally (no existence or dedup check, so it piles up on
  re-source; measured +1 entry per re-source).
- Variant gaps: zsh lacks `atuin` and `lean` (bash/fish/nu ship them); elvish lacks 12 (no bash-env bridge like
  nu's `cs-bash-env`); nu lacks `gcloud` and `elvish` (putting elvish on PATH).
- Several bash snippets end on `[ … ] && …`, so they return 1 when the tool is absent (harmless, since the
  loader ignores it).
**Effort:** S. **Tier:** G.

## Test gaps
- **Guard vs configsys's own drivers:** no test arms the guard around a `via: dotfiles` install whose dst is a
  guarded rc (-01), or around a non-UTF-8 or CRLF rc (-13).
- **Restore safety:** dotfiles uninstall with a regular file at dst (-03); glue second-displacement, `bash_aliases`
  backup-over-backup, and `_remove_bash_aliases` over a live file (-06); a foreign `~/.bash_aliases` link (-29).
- **Containment:** absolute or `..` `src:` for capture/relocate; unexpanded `$VAR` dst (-05).
- **Capture:** an outside-pointing symlink, a dangling symlink, a single-file spec with a secret (-04).
- **Shell behavior (not just syntax):** a per-shell harness that sources the prelude and a snippet in the real shell
  and asserts PATH order, options and aliases (-07, -08, -26). `test_cs_loc_reads_the_cache` and
  `test_no_startup_snippet_spawns_configsys_per_component` cover bash and zsh only; extend both to fish, nu and
  elvish.
- **Loader truth:** bash loader on a `.bashrc` that doesn't source `~/.bash_aliases` (-02); shell-glue with a
  symlinked `~/.zshrc` (-17, -18); a plugin snippet's bash loader (-27); `#!cs-eval` on elvish (only nu is tested).
- **Bootstrap:** no test touches `configsys.sh` at all. A stub-python test harness could cover the floor probe
  (-11), symlink invocation (-10), CWD (-09) and `CONFIGSYS_NO_BOOTSTRAP` (-12).
- **Inline validity:** a test that composes the real shipped nu/elvish blocks and runs `nu-check` /
  `elvish -compileonly` (both pass today; this would keep it so).

## Dead code   (each entry: what you grepped to be sure)
- `DotFiles._excludes_for` (dotfiles.py:238): `grep -rn _excludes_for` over the repo, `~/src/configsys-*/`,
  `examples/` and tests finds only the definition; not in driver.py's FROZEN list.
- Glue's `bash.d/<glue>.sh` fallback (glue.py:228-229): `git log -- glue/bash.d` is empty, and
  `ls ~/src/configsys-*/glue/` shows only `shell/`. Nothing writes `<store>/bash.d`.
- `_config_specs`' `bash.d/`/`shell/` filter (dotfiles.py:217-222): `grep -rn 'src: *bash.d\|src: *shell/'` over
  routes.hu, `~/src/configsys-*/*.hu` and examples/ finds none (configsys-user has migrated; its leftover
  `dotfiles/bash.d/` files are referenced by no route).
- The orphaned elvish comment in `_RC_SOURCE` (glue.py:124-125): no `'elvish'` key exists.
- *Migration shims, not dead yet:* `shellguard.migrate_legacy`/`_migrate_staged`/`_legacy_staged`/`_old_confd`,
  `Glue._migrate_legacy_component`/`_legacy_linked`. These are live on any machine that still has the old
  layout; the user can decide when to retire them (Questions, 5).
- `DotFiles.warnings`' "link still points into the repo" check: the repo `dotfiles/` dir was removed in `2a577c0`,
  so it can only fire for dangling legacy links. Still useful on the user's machine; keep it.

## ABI / interface candidates
- `Glue.install(rc, only_shells=None)` / `uninstall(rc, only_shells=None)` extend the frozen `install(rc)` /
  `uninstall(rc)` signatures. Only the TUI uses the keyword. If -25's `hookup=False` lands, add both
  keywords to a documented glue-specific surface rather than to the base contract.
- `spec_states` → `[SpecState(name, target, state, src_root, src_rel, here, kind)]` (a NamedTuple keeps tuple
  unpacking working); `capture_plan` → `CapturePlanRow`.
- `glue-locations.tsv` (`<comp>\t<path>`), `<state>/launcher`, `<state>/staged-glue/<shell>/<comp>.<ext>`, the
  `# >>> configsys glue >>>` markers, `user.d/` and the `00/50/90/99` bands are shell-facing contracts read by the
  shipped preludes and by users' rc files. Changing any of them (-15 adds an assoc-array global next to `_CS_LOCS`)
  is a data and shell migration.
- `GLUE_STATE_LABEL`, `CONFIG_STATES`, `config_display_state`, `component_link_stem`, `user_link_name` are imported
  by app/TUI. Keep them as the presentation vocabulary if -23 moves code around.

## Questions for the user
1. Should the shell-writes guard skip configsys's own config drivers (`dotfiles`, `glue`) entirely (simplest fix
   for -01), or also refuse to write any guarded file whose link identity changed during the op?
2. For bash on non-Debian distros (-02), would you rather have a `~/.bashrc` marker block like zsh's (uniform,
   one more rc edit), or keep `~/.bash_aliases` and add a one-line `.bashrc` hook only where none exists?
3. Is the primary plugin trusted *by identity* (yours, so its glue and dotfiles go live on sync) or *by content*
   (re-trust after every sync, as plugins.md says)? This settles -39 and the security reviewer's lead #3.
4. Should "move to local" (-22) copy (the primary keeps it for other machines) or move (and warn)?
5. Can the legacy-layout migration shims (old staged-glue layout, pre-band links, `bash.d`) be retired? Has
   your own machine been migrated?
6. Dotfiles uninstall with several backups (`.pre-configsys`, `.1`, `.2`): restore the oldest (today), the
   newest, or none and just report them?

## Refuted on verification

None. All 13 findings in the verification scope were confirmed: -01 to -06, -12, -14, -17, -19, -20, -21 and -22. -14 was confirmed by reading; the others were reproduced. One severity changed: -19, MED → LOW. Two were worse than written: -05 needs no `--force` and is one TUI keypress, and -22's single-row `s` has no confirmation.
