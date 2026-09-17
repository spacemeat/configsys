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


def test_elvish_loader_writes_rc_marker_block_and_snippet_activates(tmp_path):
    # elvish is onboarded as a glue shell: no native conf.d auto-source, so shell-glue writes ONE
    # marker block into ~/.config/elvish/rc.elv sourcing conf.d/*.elv (empty-glob-safe), and a
    # snippet deploys to <store>/elvish/conf.d/<name>.elv and links into ~/.config/elvish/conf.d/.
    p = paths_for(tmp_path, shells='elvish')
    (p.glue_dir / 'shell' / 'elvish').mkdir(parents=True)
    (p.glue_dir / 'shell' / 'elvish' / '00-configsys.elv').write_text('# elvish glue\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), paths=p)

    loader = _loader_unit('all')                                     # loader: all -> every installed shell (elvish)
    assert g.install(loader).ok
    rc_elv = p.home / '.config' / 'elvish' / 'rc.elv'
    assert '# >>> configsys glue >>>' in rc_elv.read_text()
    assert '[nomatch-ok]' in rc_elv.read_text()                      # empty-glob-safe source line
    assert g.get_version(loader) == 'linked'

    snip = _glue_unit(comp='configsys-glue', glue='00-configsys')    # a snippet on elvish
    assert g.install(snip).ok
    link = p.home / '.config' / 'elvish' / 'conf.d' / '00-configsys.elv'
    store = p.user_glue_dir / 'elvish' / 'conf.d' / '00-configsys.elv'
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(store)
    assert g.get_version(snip) == 'linked'

    assert g.uninstall(loader).ok                                    # drop the rc block, leave conf.d + content
    assert '# >>> configsys glue >>>' not in rc_elv.read_text()
    assert g.get_version(loader) is None


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
