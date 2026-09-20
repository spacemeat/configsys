'''Glue driver (`via: glue`) — the shell-integration half split out of the dotfiles driver.

Mirrors the glue/loader coverage that used to live under the dotfiles driver: snippet deploy to the
store conf.d mirror, per-shell loaders, the `loader: all` shell-glue substrate, and get_version.'''

import os

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.glue import Glue
from configsys.paths import Paths
from configsys.runner import Runner


def paths_for(tmp_path, shells='bash'):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                      'CONFIGSYS_GLUE_SHELLS': shells})


def _glue_unit(comp='btop-glue', glue='btop'):
    return ResolvedComponent(key=f'glue\\{comp}', driver='glue', comp=comp, fields={'glue': glue})


def _loader_unit(loader='all'):
    return ResolvedComponent(key='glue\\shell-glue', driver='glue', comp='shell-glue',
                             fields={'loader': loader})


def test_glue_registered_under_via_glue(tmp_path):
    drv = get_driver('glue', Runner(pretend=True), paths_for(tmp_path))
    assert isinstance(drv, Glue)


def test_snippet_materializes_to_store_confd_mirror_executable(tmp_path):
    # a glue snippet deploys to <store>/<shell>/conf.d/<name>.<ext> (the store mirrors the deployed
    # ~/.config/<shell>/conf.d/ layout), made a+x; the link points at the store copy, never the repo.
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('# btop glue\n')   # repo-authored, -x
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    assert g.get_version(rc) is None
    assert g.install(rc).ok
    link = p.home / '.config' / 'bash' / 'conf.d' / 'btop.sh'
    store = p.user_glue_dir / 'bash' / 'conf.d' / 'btop.sh'
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(store)
    assert store.read_text() == '# btop glue\n'
    assert os.access(store, os.X_OK)                                  # executable
    assert os.path.realpath(link) != os.path.realpath(p.glue_dir / 'shell' / 'bash' / 'btop.sh')
    assert g.get_version(rc) == 'linked'
    # uninstall removes only our symlink
    assert g.uninstall(rc).ok
    assert not link.exists()
    assert g.get_version(rc) is None


def test_activate_refreshes_a_stale_store_copy_from_source(tmp_path):
    # the store is a deploy CACHE — when the authoritative source changes, a re-activate must
    # re-materialize over the stale cached copy (glue is shipped content).
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    auth = p.glue_dir / 'shell' / 'bash' / 'btop.sh'
    auth.write_text('# v1\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    assert g.install(rc).ok
    store = p.user_glue_dir / 'bash' / 'conf.d' / 'btop.sh'
    assert store.read_text() == '# v1\n'
    auth.write_text('# v2 updated\n')                    # source changes upstream
    res = g.install(rc)
    assert res.ok and store.read_text() == '# v2 updated\n'   # stale cache refreshed
    assert 'refreshed from source' in res.output


def test_activate_ensures_the_shell_loader(tmp_path):
    # a direct activate bypasses the snippet's `requires: shell-glue`, so the snippet driver wires
    # the shell loader itself — else the linked conf.d file would never be sourced.
    p = paths_for(tmp_path, shells='zsh')
    (p.glue_dir / 'shell' / 'zsh').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'zsh' / 'btop.zsh').write_text('# glue\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    assert g.install(_glue_unit()).ok
    assert '# >>> configsys glue >>>' in (p.home / '.zshrc').read_text()   # zsh loader wired


def test_zsh_loader_adds_idempotent_rc_block_and_uninstall_removes_it(tmp_path):
    p = paths_for(tmp_path, shells='zsh')
    p.home.mkdir(parents=True)
    (p.home / '.zshrc').write_text('# my zshrc\nexport FOO=1\n')      # a pre-existing rc
    g = Glue(Runner(pretend=False), paths=p)
    rc = ResolvedComponent(key='glue\\zsh-glue', driver='glue', comp='zsh-glue',
                           fields={'loader': 'zsh'})
    assert g.get_version(rc) is None
    assert g.install(rc).ok
    confd = p.home / '.config' / 'zsh' / 'conf.d'
    zshrc = (p.home / '.zshrc').read_text()
    assert confd.is_dir()
    assert '# >>> configsys glue >>>' in zshrc
    assert 'my zshrc' in zshrc and 'export FOO=1' in zshrc            # user content preserved
    assert g.get_version(rc) == 'linked'
    g.install(rc)                                                     # idempotent — no second block
    assert (p.home / '.zshrc').read_text().count('# >>> configsys glue >>>') == 1
    g.uninstall(rc)
    after = (p.home / '.zshrc').read_text()
    assert '# >>> configsys glue >>>' not in after
    assert 'export FOO=1' in after                                   # user content still intact
    assert confd.is_dir()                                            # dir left alone
    assert g.get_version(rc) is None


def test_elvish_gestalt_loader_inlines_snippets_into_rc(tmp_path):
    # elvish's per-file `eval` isolates namespaces, so shell-glue uses the GESTALT loader: the rc.elv
    # marker block INLINES the concatenated conf.d snippet contents (so `fn`/`var` land in the
    # interactive namespace), regenerated on (de)activation. Snippets still deploy to conf.d as links.
    p = paths_for(tmp_path, shells='elvish')
    (p.glue_dir / 'shell' / 'elvish').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'elvish' / '00-configsys.elv').write_text('fn cf {|@a| put configsys }\n')
    (p.glue_dir / 'shell' / 'elvish' / 'bat.elv').write_text('fn bat {|@a| batcat $@a }\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc_elv = p.home / '.config' / 'elvish' / 'rc.elv'

    # activate the substrate snippet first, then bat -> the rc block inlines BOTH, in sorted order
    assert g.install(_glue_unit(comp='configsys-glue', glue='00-configsys')).ok
    assert g.install(_glue_unit(comp='bat-glue', glue='bat')).ok
    block = rc_elv.read_text()
    assert '# >>> configsys glue >>>' in block
    assert 'fn cf {|@a| put configsys }' in block                    # inlined, not sourced
    assert 'fn bat {|@a| batcat $@a }' in block
    assert '[nomatch-ok]' not in block and 'eval (slurp' not in block  # NOT the old source-loop
    assert block.index('# >> 00-configsys.elv') < block.index('# >> bat.elv')   # 00- first
    # links still deploy to conf.d
    link = p.home / '.config' / 'elvish' / 'conf.d' / 'bat.elv'
    assert link.is_symlink()

    # deactivating bat regenerates the block WITHOUT bat, keeps the substrate
    assert g.uninstall(_glue_unit(comp='bat-glue', glue='bat')).ok
    block2 = rc_elv.read_text()
    assert 'fn bat {|@a| batcat $@a }' not in block2 and 'fn cf {|@a| put configsys }' in block2

    # the loader-all substrate removal drops the whole block
    loader = _loader_unit('all')
    assert g.get_version(loader) == 'linked'
    assert g.uninstall(loader).ok
    assert '# >>> configsys glue >>>' not in rc_elv.read_text()
    assert g.get_version(loader) is None


def test_spec_states_flags_a_changed_source_as_drifted(tmp_path):
    # after a snippet is active, editing the SHIPPED source marks it 'drifted' (active but stale) — so
    # the Glue TUI shows it changed and the user knows to re-activate (the store copy holds the OLD
    # content until then). Re-activating refreshes the store -> back to 'linked'.
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    auth = p.glue_dir / 'shell' / 'bash' / 'btop.sh'
    auth.write_text('# v1\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    assert g.install(rc).ok
    assert [s[2] for s in g.spec_states(rc)] == ['linked']       # active + fresh
    auth.write_text('# v2 changed\n')                            # shipped source changes upstream
    assert [s[2] for s in g.spec_states(rc)] == ['drifted']      # store copy now stale -> flagged
    assert g.install(rc).ok                                      # re-activate re-materializes the store
    assert [s[2] for s in g.spec_states(rc)] == ['linked']       # fresh again


def test_installed_shells_counts_managed_tarball_shell_off_path(tmp_path):
    # a shell configsys MANAGES (binary in its install dir, per the glue-locations cache) is detected
    # even when it's not on the current PATH — so a tarball shell shows in the Glue TUI immediately,
    # without opening a fresh shell to get it on PATH first.
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                   'PATH': str(tmp_path / 'no-such-bin')})     # nothing on PATH; NO GLUE_SHELLS override
    # a managed nushell tarball: <dir>/nu-<ver>-.../nu (versioned subdir), executable
    nudir = tmp_path / 'apps' / 'nushell'
    nubin = nudir / 'nu-0.115.1-x86_64-unknown-linux-gnu' / 'nu'
    nubin.parent.mkdir(parents=True)
    nubin.write_text('#!/bin/sh\n')
    os.chmod(nubin, 0o755)
    p.glue_locations_file.parent.mkdir(parents=True, exist_ok=True)
    p.glue_locations_file.write_text(f'nushell\t{nudir}\nelvish\t{tmp_path}/absent\n', encoding='utf-8')

    shells = Glue(Runner(pretend=True), paths=p)._installed_shells()
    assert 'nu' in shells                    # managed tarball with the binary present -> detected off PATH
    assert 'elvish' not in shells            # cache lists it but its dir/binary is absent -> not detected


def test_nushell_gestalt_loader_inlines_snippets_into_config(tmp_path):
    # nushell can't dynamically source a dir (it parses the whole program first, so `source` needs a
    # parse-time-constant path — no conf.d loop possible), so like elvish it uses the GESTALT loader:
    # config.nu's marker block INLINES the concatenated conf.d snippets, regenerated on (de)activation.
    p = paths_for(tmp_path, shells='nu')
    (p.glue_dir / 'shell' / 'nu').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'nu' / '00-configsys.nu').write_text('def cf [...a] { configsys ...$a }\n')
    (p.glue_dir / 'shell' / 'nu' / 'fd.nu').write_text('def --wrapped fd [...r] { ^fdfind ...$r }\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    config_nu = p.home / '.config' / 'nushell' / 'config.nu'

    # activate the substrate first, then fd -> the block inlines BOTH, in sorted order
    assert g.install(_glue_unit(comp='configsys-glue', glue='00-configsys')).ok
    assert g.install(_glue_unit(comp='fd-glue', glue='fd')).ok
    block = config_nu.read_text()
    assert '# >>> configsys glue >>>' in block
    assert 'def cf [...a] { configsys ...$a }' in block               # inlined, not sourced
    assert 'def --wrapped fd [...r] { ^fdfind ...$r }' in block
    assert 'source ' not in block                                    # nu can't source-loop a dir
    assert block.index('# >> 00-configsys.nu') < block.index('# >> fd.nu')   # 00- first
    link = p.home / '.config' / 'nushell' / 'conf.d' / 'fd.nu'
    assert link.is_symlink()

    # deactivating fd regenerates the block WITHOUT fd, keeps the substrate
    assert g.uninstall(_glue_unit(comp='fd-glue', glue='fd')).ok
    block2 = config_nu.read_text()
    assert 'fd [...r]' not in block2 and 'def cf [...a]' in block2

    # removing the loader-all substrate drops the whole block
    loader = _loader_unit('all')
    assert g.get_version(loader) == 'linked'
    assert g.uninstall(loader).ok
    assert '# >>> configsys glue >>>' not in config_nu.read_text()
    assert g.get_version(loader) is None


def test_nushell_gestalt_cs_eval_inlines_generated_output(tmp_path):
    # a `#!cs-eval <cmd>` snippet is a GENERATOR: the inline loader runs the command and inlines its
    # STDOUT (an init-eval tool's shell code), not the directive — the bridge for zoxide/atuin on
    # nushell, which has no runtime eval. A failing command (tool absent/too old) inlines NOTHING and
    # never breaks the block.
    p = paths_for(tmp_path, shells='nu')
    (p.glue_dir / 'shell' / 'nu').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'nu' / 'zoxide.nu').write_text(
        "# zoxide init\n#!cs-eval echo 'def z [] { 42 }'\n")
    (p.glue_dir / 'shell' / 'nu' / 'nope.nu').write_text("# absent tool\n#!cs-eval false\n")
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    config_nu = p.home / '.config' / 'nushell' / 'config.nu'

    assert g.install(_glue_unit(comp='zoxide-glue', glue='zoxide')).ok
    assert g.install(_glue_unit(comp='nope-glue', glue='nope')).ok
    block = config_nu.read_text()
    assert 'def z [] { 42 }' in block                     # the command's OUTPUT is inlined
    assert '#!cs-eval' not in block                       # the directive line itself is not inlined
    assert '(generated: echo' in block                    # header notes it was generated (names the cmd)
    assert 'nope.nu' not in block                         # the failing command inlined nothing


def test_shell_glue_loader_all_hooks_every_installed_shell(tmp_path):
    # the shell-glue substrate: `loader: all` wires conf.d loading for EVERY installed shell.
    p = paths_for(tmp_path, shells='bash,zsh,fish')
    p.glue_dir.mkdir(parents=True)
    (p.glue_dir / 'bash_aliases').write_text('# source conf.d\n')   # bash's loader file
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _loader_unit('all')
    assert g.get_version(rc) is None
    assert g.install(rc).ok
    assert (p.home / '.config' / 'bash' / 'conf.d').is_dir()
    assert (p.home / '.bash_aliases').is_symlink()                    # bash rides ~/.bash_aliases
    assert (p.home / '.config' / 'fish' / 'conf.d').is_dir()          # fish auto-sources natively
    assert '# >>> configsys glue >>>' in (p.home / '.zshrc').read_text()   # zsh needs the rc block
    assert g.get_version(rc) == 'linked'
    g.uninstall(rc)
    assert '# >>> configsys glue >>>' not in (p.home / '.zshrc').read_text()
    assert not (p.home / '.bash_aliases').is_symlink()               # bash link removed
    assert g.get_version(rc) is None                                 # loaders gone


def test_shell_glue_bash_absorbs_preexisting_bash_aliases(tmp_path):
    # a pre-existing real ~/.bash_aliases is MOVED into conf.d (kept running), then ~/.bash_aliases
    # becomes our link; uninstall restores the user's original file.
    p = paths_for(tmp_path, shells='bash')
    p.glue_dir.mkdir(parents=True)
    (p.glue_dir / 'bash_aliases').write_text('# source conf.d\n')
    p.home.mkdir(parents=True)
    (p.home / '.bash_aliases').write_text('alias mine="echo hi"\n')   # the user's own aliases
    g = Glue(Runner(pretend=False), paths=p)
    rc = _loader_unit('all')
    assert g.install(rc).ok
    link = p.home / '.bash_aliases'
    absorbed = p.home / '.config' / 'bash' / 'conf.d' / 'pre-configsys-aliases.sh'
    assert link.is_symlink()
    assert absorbed.read_text() == 'alias mine="echo hi"\n'          # user aliases preserved in conf.d
    assert os.access(absorbed, os.X_OK)
    g.uninstall(rc)
    assert not link.is_symlink() and link.read_text() == 'alias mine="echo hi"\n'   # restored


def test_snippet_activates_only_installed_shells(tmp_path):
    # a snippet deploys to conf.d for each INSTALLED shell that ships a variant (CONFIGSYS_GLUE_SHELLS
    # pins the set); a shell that isn't "installed" gets nothing.
    p = paths_for(tmp_path, shells='bash,fish')
    for sh, ext in (('bash', 'sh'), ('fish', 'fish'), ('zsh', 'zsh')):
        (p.glue_dir / 'shell' / sh).mkdir(parents=True)
        (p.glue_dir / 'shell' / sh / f'btop.{ext}').write_text('# glue\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    assert g.install(_glue_unit()).ok
    assert (p.home / '.config' / 'bash' / 'conf.d' / 'btop.sh').is_symlink()
    assert (p.home / '.config' / 'fish' / 'conf.d' / 'btop.fish').is_symlink()
    assert not (p.home / '.config' / 'zsh' / 'conf.d' / 'btop.zsh').exists()   # zsh not installed


def test_install_only_shells_scopes_activation_to_one_shell(tmp_path):
    # the TUI Glue group action passes only_shells so activating a snippet in ONE shell group doesn't
    # light up the component's other shells (the A-activates-everything bug). Each per-shell row is
    # independently activatable; only_shells=None (the CLI path) still does all shells.
    p = paths_for(tmp_path, shells='bash,zsh,fish')
    for sh, ext in (('bash', 'sh'), ('zsh', 'zsh'), ('fish', 'fish')):
        (p.glue_dir / 'shell' / sh).mkdir(parents=True)
        (p.glue_dir / 'shell' / sh / f'btop.{ext}').write_text('# glue\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    bash = p.home / '.config' / 'bash' / 'conf.d' / 'btop.sh'
    zsh = p.home / '.config' / 'zsh' / 'conf.d' / 'btop.zsh'
    fish = p.home / '.config' / 'fish' / 'conf.d' / 'btop.fish'

    g.install(rc, only_shells=['bash'])                      # activate ONLY bash
    assert bash.is_symlink() and not zsh.exists() and not fish.exists()
    g.install(rc, only_shells=['zsh'])                       # add zsh; fish still untouched
    assert bash.is_symlink() and zsh.is_symlink() and not fish.exists()
    g.uninstall(rc, only_shells=['bash'])                    # deactivate ONLY bash
    assert not bash.exists() and zsh.is_symlink()


def test_confd_symlinked_to_store_makes_no_self_loop(tmp_path):
    # if ~/.config/<shell>/conf.d is itself a symlink to the store's conf.d dir, the store file IS the
    # deployed file — a naive `ln -sfn store/x conf.d/x` would resolve to a self-link (ELOOP). Install
    # must detect the realpath coincidence and skip the link, leaving a real file.
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('# glue\n')
    store_confd = p.user_glue_dir / 'bash' / 'conf.d'
    store_confd.mkdir(parents=True)
    confd = p.home / '.config' / 'bash' / 'conf.d'
    confd.parent.mkdir(parents=True)
    confd.symlink_to(store_confd)                          # the dir is a symlink to the store
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    assert g.install(rc).ok
    store_file = store_confd / 'btop.sh'
    assert store_file.is_file() and not store_file.is_symlink()
    assert g.get_version(rc) == 'linked'
    assert g.install(rc).ok                                # idempotent — no crash, no re-created loop


def test_spec_states_reports_glue_kind(tmp_path):
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('# btop glue\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    states = g.spec_states(rc)
    assert states and all(row[6] == 'glue' for row in states)        # kind column is always 'glue'


# -- B6: safety (pretend no-write, literal rc-block regen, communal conf.d backup) ---------------

def test_pretend_install_touches_no_files(tmp_path):
    # --pretend must not materialize the store, rewrite rc files, or stamp loaders (only the symlink
    # step went through the runner before; the FS ops ran for real).
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('# btop glue\n')
    drv = Glue(Runner(pretend=True), p)
    drv.install(_glue_unit())
    store = p.glue_store_dir / 'bash' / 'conf.d' / 'btop.sh' if hasattr(p, 'glue_store_dir') else None
    # nothing was written into the store conf.d mirror
    mirror = list((p.state_dir).rglob('conf.d/*.sh')) if p.state_dir.exists() else []
    assert mirror == []
    assert not (p.home / '.bash_aliases').exists()          # loader link not created under pretend


def test_rc_block_with_backslashes_is_written_literally(tmp_path):
    # regeneration used re.sub with the block as the REPLACEMENT string, so a `\1`/`\t` in an inlined
    # snippet was reinterpreted (mangled) or raised. It must be written byte-for-byte.
    import types
    from configsys.drivers import glue as glue_mod
    from configsys.drivers.glue import _RC_BEGIN, _RC_END
    p = paths_for(tmp_path, shells='nu')                     # an inline (gestalt) shell
    drv = Glue(Runner(pretend=False), p)
    rc_path = drv._expand(glue_mod._SHELL_RC['nu'])          # the rc file the loader actually rewrites
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(f'echo hi\n{_RC_BEGIN}\nold\n{_RC_END}\n')
    tricky = f'{_RC_BEGIN}\nlet x = "a\\1b\tc"\n{_RC_END}\n'
    drv._rc_block = types.MethodType(lambda self, shell: tricky, drv)   # force a backslashy block
    assert drv._ensure_shell_loader('nu') is True
    assert 'a\\1b\tc' in rc_path.read_text()                 # literal, not a backref/tab expansion


def test_install_backs_up_a_real_file_in_a_communal_confd(tmp_path):
    # H1: a conf.d dir can be communal (fish); a pre-existing REAL file at the target is backed up to
    # <name>.pre-configsys, not clobbered. Assert the generated shell does the guarded mv.
    p = paths_for(tmp_path, shells='fish')
    (p.glue_dir / 'shell' / 'fish').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'fish' / 'btop.fish').write_text('# btop\n')
    r = Runner(pretend=True)
    Glue(r, p).install(_glue_unit())
    joined = '\n'.join(r.calls)
    assert '.pre-configsys' in joined and 'mv -n' in joined and '! -L' in joined
