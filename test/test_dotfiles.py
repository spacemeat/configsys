import os
from pathlib import Path

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.dotfiles import DotFiles
from configsys.paths import Paths
from configsys.routes import Resolver
from configsys.runner import Runner


def df_unit(specs=None, comp='neovim'):
    fields = specs if specs is not None else {
        'config': {'src': 'neovim', 'dst': '$XDG_CONFIG_HOME/nvim'}}
    return ResolvedComponent(key=f'dotfiles\\{comp}', driver='dotfiles', comp=comp,
                             fields=fields)


def paths_for(tmp_path):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo')})


def test_template_materializes_to_store_and_link_survives_repo_removal(tmp_path):
    # #4 payoff: a shipped template is copied into the machine-local store on install and the link
    # points THERE — so the link keeps working even if the repo moves or is deleted.
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'bash.d').mkdir(parents=True)
    (p.dotfiles_dir / 'bash.d' / 'btop.sh').write_text('# btop glue\n')
    p.home.mkdir(parents=True)
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit(specs={'src': 'bash.d/btop.sh', 'dst': '~/.bash.d/btop.sh'}, comp='btop')

    assert df.install(rc).ok
    link = p.home / '.bash.d' / 'btop.sh'
    store_copy = p.user_dotfiles_dir / 'bash.d' / 'btop.sh'
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(store_copy)
    assert store_copy.read_text() == '# btop glue\n'
    assert df.get_version(rc) == 'linked'

    # nuke the repo entirely — the link + get_version still hold (store-backed, repo-independent).
    import shutil as _sh
    _sh.rmtree(p.dotfiles_dir)
    assert link.is_symlink() and link.resolve().read_text() == '# btop glue\n'
    assert df.get_version(rc) == 'linked'


def test_dotfiles_migrate_repoints_repo_links_to_store(tmp_path, monkeypatch):
    # migrate re-points a link that references the repo at the machine-local store (idempotent apply
    # = re-install), leaving orphan plain files untouched.
    import types
    from configsys import app
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'bash.d').mkdir(parents=True)
    (p.dotfiles_dir / 'bash.d' / 'btop.sh').write_text('# glue\n')
    (p.home / '.bash.d').mkdir(parents=True)
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit(specs={'src': 'bash.d/btop.sh', 'dst': '~/.bash.d/btop.sh'}, comp='btop')

    link = p.home / '.bash.d' / 'btop.sh'            # OLD broken state: a link straight into the repo
    link.symlink_to(p.dotfiles_dir / 'bash.d' / 'btop.sh')
    (p.home / '.bash.d' / 'mine.sh').write_text('# my own orphan\n')   # a non-symlink orphan
    assert os.path.realpath(link).startswith(str(p.dotfiles_dir))

    monkeypatch.setattr(app, '_active_dotfiles', lambda c: (df, [rc]))
    ctx = types.SimpleNamespace(paths=p, os_info=types.SimpleNamespace(block='x'))
    assert app.cmd_dotfiles_migrate(ctx, types.SimpleNamespace(yes=True)) == 0

    store_copy = p.user_dotfiles_dir / 'bash.d' / 'btop.sh'
    assert os.path.realpath(link) == os.path.realpath(store_copy)          # now the store, not the repo
    assert not os.path.realpath(link).startswith(str(p.dotfiles_dir))
    assert (p.home / '.bash.d' / 'mine.sh').read_text() == '# my own orphan\n'   # orphan untouched


def test_dotfiles_migrate_moves_glue_link_from_bashd_to_confd(tmp_path, monkeypatch):
    # Phase 1b: a glue component now targets ~/.config/bash/conf.d/. migrate installs the conf.d link
    # (materialized from the store) and removes the now-superseded ~/.bash.d link.
    import types
    from configsys import app
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.dotfiles_dir / 'shell' / 'bash' / 'btop.sh').write_text('# glue\n')
    # pre-existing Phase-1a state: a managed store-link at the OLD ~/.bash.d location.
    store_old = p.user_dotfiles_dir / 'bash.d' / 'btop.sh'
    store_old.parent.mkdir(parents=True)
    store_old.write_text('# glue\n')
    (p.home / '.bash.d').mkdir(parents=True)
    old_link = p.home / '.bash.d' / 'btop.sh'
    old_link.symlink_to(store_old)

    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit(specs={'glue': 'btop'}, comp='btop-dotfiles')
    monkeypatch.setattr(app, '_active_dotfiles', lambda c: (df, [rc]))
    ctx = types.SimpleNamespace(paths=p, os_info=types.SimpleNamespace(block='x'))
    assert app.cmd_dotfiles_migrate(ctx, types.SimpleNamespace(yes=True)) == 0

    confd = p.home / '.config' / 'bash' / 'conf.d' / 'btop.sh'
    assert confd.is_symlink() and confd.resolve().read_text() == '# glue\n'
    assert not old_link.exists() and not old_link.is_symlink()             # old bash.d link removed


def test_dotfiles_migrate_removes_dead_repo_link(tmp_path, monkeypatch):
    # A ~/.bash.d symlink into the repo's now-gone bash.d/ is dead cruft (loader skips it) — migrate
    # clears it even though no active component references it.
    import types
    from configsys import app
    p = paths_for(tmp_path)
    p.dotfiles_dir.mkdir(parents=True)                                     # repo exists; bash.d/ does NOT
    (p.home / '.bash.d').mkdir(parents=True)
    dead = p.home / '.bash.d' / 'clang.sh'
    dead.symlink_to(p.dotfiles_dir / 'bash.d' / 'clang.sh')               # dangling into the repo
    assert dead.is_symlink() and not dead.exists()

    df = DotFiles(Runner(pretend=False), paths=p)
    monkeypatch.setattr(app, '_active_dotfiles', lambda c: (df, []))
    ctx = types.SimpleNamespace(paths=p, os_info=types.SimpleNamespace(block='x'))
    assert app.cmd_dotfiles_migrate(ctx, types.SimpleNamespace(yes=True)) == 0
    assert not dead.is_symlink()                                          # dead link cleared


# -- content root follows the layer that defined the component -------------

def test_src_anchors_at_the_defining_layers_dotfiles_dir(tmp_path):
    # a component defined in /somewhere/routes.hu sources from /somewhere/dotfiles/
    df = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path))
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'},
                           source=str(tmp_path / 'myplugin' / 'routes.hu'))
    src, _tgt, _ = df._pairs(rc)[0]
    # config content lives under the <component>.cfs/ marker dir next to the defining routes file
    assert src == tmp_path / 'myplugin' / 'dotfiles' / 'x.cfs' / 'foo.sh'


def test_src_falls_back_to_repo_without_a_source(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'})   # no source
    src, _tgt, _ = df._pairs(rc)[0]
    assert src == p.dotfiles_dir / 'x.cfs' / 'foo.sh'


def test_resolution_threads_the_defining_file_end_to_end(tmp_path):
    # a via:dotfiles component defined in its own routes file carries that file as rc.source,
    # so the driver anchors its content next to it — the configsys-user-as-a-plugin path
    routes = tmp_path / 'plug' / 'routes.hu'
    routes.parent.mkdir(parents=True)
    routes.write_text('{ os: { linux: {}  debian: { using: linux  native: apt } }'
                      '  components: { mycfg: { install: [ { via: dotfiles  src: m  dst: ~/m } ] } } }')
    rc = Resolver(str(routes), 'debian', '12').resolve_names(['mycfg'])['dotfiles\\mycfg']
    assert Path(rc.source) == routes                       # threaded from the defining file
    df = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path))
    src, _tgt, _ = df._pairs(rc)[0]
    assert src == routes.parent / 'dotfiles' / 'mycfg.cfs' / 'm'


def test_registry_has_dotfiles():
    assert isinstance(get_driver('dotfiles', Runner(pretend=True)), DotFiles)


def test_single_inline_spec():
    rc = ResolvedComponent(key='dotfiles\\arduino', driver='dotfiles', comp='arduino',
                           fields={'src': 'bash.d/arduino.sh', 'dst': '~/.bash.d/arduino.sh'})
    assert DotFiles(Runner(pretend=True))._specs(rc) == [
        ('arduino', 'bash.d/arduino.sh', '~/.bash.d/arduino.sh', None, 'config')]


def test_glue_expands_to_conf_d_per_shell(tmp_path):
    # `glue: btop` -> a spec per shell that has a snippet; bash today: src shell/bash/btop.sh,
    # dst ~/.config/bash/conf.d/btop.sh. The repo template is enough to light up bash.
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'shell' / 'bash').mkdir(parents=True)
    (p.dotfiles_dir / 'shell' / 'bash' / 'btop.sh').write_text('# glue\n')
    df = DotFiles(Runner(pretend=True), paths=p)
    rc = ResolvedComponent(key='dotfiles\\btop-dotfiles', driver='dotfiles', comp='btop-dotfiles',
                           fields={'glue': 'btop', 'requires': 'bash-dotfiles'})
    assert df._specs(rc) == [
        ('btop@bash', 'shell/bash/btop.sh', '~/.config/bash/conf.d/btop.sh', None, 'glue')]

    # a user copy at the pre-move bash.d/ path (e.g. an un-migrated plugin) still resolves + WINS.
    (p.user_dotfiles_dir / 'bash.d').mkdir(parents=True)
    (p.user_dotfiles_dir / 'bash.d' / 'btop.sh').write_text('# my btop\n')
    assert df._specs(rc)[0][1] == 'bash.d/btop.sh'          # user store (bash.d) beats repo shell/bash


def test_dst_env_expansion_defaults_xdg(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    src, tgt, _ = df._pairs(df_unit())[0]
    assert src == p.dotfiles_dir / 'neovim.cfs' / 'neovim'   # unpopulated config -> .cfs marker path
    assert tgt == p.home / '.config' / 'nvim'   # $XDG_CONFIG_HOME default


def test_install_command_has_symlink_and_backup(tmp_path):
    r = Runner(pretend=True)
    DotFiles(r, paths=paths_for(tmp_path)).install(df_unit())
    cmd = r.calls[0]
    assert 'ln -sfn' in cmd
    assert '.pre-configsys' in cmd          # backs up an existing non-symlink
    assert 'nvim' in cmd
    assert 'sudo' not in cmd                # user-space


def test_no_specs_is_an_error(tmp_path):
    res = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path)).install(df_unit(specs={}))
    assert not res.ok


def test_real_symlink_install_getversion_uninstall(tmp_path):
    p = paths_for(tmp_path)
    src_dir = p.dotfiles_dir / 'neovim'
    src_dir.mkdir(parents=True)
    (src_dir / 'init.lua').write_text('-- cfg')
    p.home.mkdir(parents=True)

    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    assert df.get_version(rc) is None

    assert df.install(rc).ok
    target = p.home / '.config' / 'nvim'
    store_copy = p.user_dotfiles_dir / 'neovim'                 # a shipped template materializes here
    assert target.is_symlink()
    # #4: the link points at the machine-local STORE copy, NEVER the repo template.
    assert os.path.realpath(target) == os.path.realpath(store_copy)
    assert os.path.realpath(target) != os.path.realpath(src_dir)
    assert store_copy.is_dir() and (store_copy / 'init.lua').read_text() == '-- cfg'
    assert df.get_version(rc) == 'linked'

    df.uninstall(rc)
    assert not target.exists()


def test_existing_dir_is_backed_up_and_restored(tmp_path):
    p = paths_for(tmp_path)
    src_dir = p.user_dotfiles_dir / 'neovim'      # ADOPTED content (a user store) -> link is safe
    src_dir.mkdir(parents=True)
    (src_dir / 'init.lua').write_text('new')

    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'old.txt').write_text('old')

    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()

    assert df.install(rc).ok
    assert target.is_symlink()
    backup = p.home / '.config' / 'nvim.pre-configsys'
    assert backup.is_dir() and (backup / 'old.txt').read_text() == 'old'

    df.uninstall(rc)
    assert target.is_dir() and not target.is_symlink()
    assert (target / 'old.txt').read_text() == 'old'   # original restored


def test_unpopulated_source_is_a_noop(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    # no content anywhere (no template shipped, nothing captured) -> a component may still DECLARE
    # src/dst; install skips it gracefully (never links a dangling path) and does NOT fail.
    res = DotFiles(Runner(pretend=False), paths=p).install(df_unit())
    assert res.ok                                          # graceful skip, not an error
    assert not (p.home / '.config' / 'nvim').exists()      # nothing linked


# -- content search-path: user store shadows the shipped template --------

def test_user_store_shadows_the_template(tmp_path):
    p = paths_for(tmp_path)
    # a template ships in the defining/repo dir; the user's local store also has content
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)
    (p.dotfiles_dir / 'neovim' / 'init.lua').write_text('-- template')
    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)
    (p.user_dotfiles_dir / 'neovim' / 'init.lua').write_text('-- mine')

    df = DotFiles(Runner(pretend=True), paths=p)
    src, _tgt, _ = df._pairs(df_unit())[0]
    assert src == p.user_dotfiles_dir / 'neovim'           # local store wins over the template


def test_primary_plugin_store_beats_template_but_not_local(tmp_path):
    p = paths_for(tmp_path)
    p.primary_dotfiles_dir = tmp_path / 'plug' / 'dotfiles'
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)         # template
    (p.primary_dotfiles_dir / 'neovim').mkdir(parents=True)  # plugin store
    df = DotFiles(Runner(pretend=True), paths=p)
    assert df._pairs(df_unit())[0][0] == p.primary_dotfiles_dir / 'neovim'   # plugin > template
    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)     # local store
    assert df._pairs(df_unit())[0][0] == p.user_dotfiles_dir / 'neovim'      # local > plugin


def test_spec_states(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    df = DotFiles(Runner(pretend=False), paths=p)

    # empty: no content anywhere, dst absent
    assert df.spec_states(df_unit())[0][2] == 'empty'

    # unmanaged: a real on-system dst, nothing captured
    (p.home / '.config' / 'nvim').mkdir(parents=True)
    assert df.spec_states(df_unit())[0][2] == 'unmanaged'

    # adopted: content now in the user store (dst still real, not linked)
    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)
    assert df.spec_states(df_unit())[0][2] == 'adopted'

    # linked: install it -> our symlink
    assert df.install(df_unit()).ok
    assert df.spec_states(df_unit())[0][2] == 'linked'


def test_spec_state_template(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)        # a shipped template, dst absent
    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.spec_states(df_unit())[0][2] == 'template'


# -- refuse-until-adopted: never clobber a real dotfile with a template ----

def test_install_refuses_template_over_real_dst(tmp_path):
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)          # a shipped TEMPLATE (repo root)
    (p.dotfiles_dir / 'neovim' / 'init.lua').write_text('template')
    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'mine.lua').write_text('mine')                 # the user's real, un-adopted config

    res = DotFiles(Runner(pretend=False), paths=p).install(df_unit())
    assert not res.ok and res.advisory                       # refused, but advisory (not a bug)
    assert 'capture' in res.output and '--force' in res.output   # actionable guidance
    assert not target.is_symlink()                           # untouched
    assert (target / 'mine.lua').read_text() == 'mine'
    assert not (p.home / '.config' / 'nvim.pre-configsys').exists()   # no backup made either


def test_install_force_overwrites_template(tmp_path):
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'neovim').mkdir(parents=True)
    (p.dotfiles_dir / 'neovim' / 'init.lua').write_text('template')
    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'mine.lua').write_text('mine')
    p.dotfiles_force = True                                  # what `install --force` sets

    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.install(df_unit()).ok
    assert target.is_symlink()                               # replaced
    backup = p.home / '.config' / 'nvim.pre-configsys'
    assert (backup / 'mine.lua').read_text() == 'mine'       # original preserved


def test_install_over_real_dst_ok_once_adopted(tmp_path):
    # the sanctioned path: capture (content in a user store) makes the link safe, no --force needed
    p = paths_for(tmp_path)
    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)     # adopted
    (p.user_dotfiles_dir / 'neovim' / 'init.lua').write_text('mine')
    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'mine.lua').write_text('mine')

    assert DotFiles(Runner(pretend=False), paths=p).install(df_unit()).ok
    assert target.is_symlink()


# -- capture: adopt on-system dotfiles into the store (phase 2) ------------

def test_capture_root_prefers_plugin_then_local(tmp_path):
    p = paths_for(tmp_path)
    assert DotFiles(Runner(pretend=True), paths=p)._capture_root() == p.user_dotfiles_dir
    p.primary_dotfiles_dir = tmp_path / 'plug' / 'dotfiles'
    assert DotFiles(Runner(pretend=True), paths=p)._capture_root() == p.primary_dotfiles_dir


def test_capture_plan_actions(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    df = DotFiles(Runner(pretend=True), paths=p)
    rc = df_unit()

    assert df.capture_plan(rc)[0][3] == 'skip-absent'          # nothing on-system

    (p.home / '.config' / 'nvim').mkdir(parents=True)          # a real on-system dir
    name, dst, dest, action = df.capture_plan(rc)[0]
    assert action == 'copy'
    assert dst == p.home / '.config' / 'nvim'
    assert dest == p.user_dotfiles_dir / 'neovim.cfs' / 'neovim'   # into the .cfs store marker

    (p.user_dotfiles_dir / 'neovim.cfs' / 'neovim').mkdir(parents=True)   # store already has it
    assert df.capture_plan(rc)[0][3] == 'skip-exists'
    assert df.capture_plan(rc, force=True)[0][3] == 'copy'    # --force overwrites


def test_capture_plan_skips_our_own_link(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)      # content in the store
    df = DotFiles(Runner(pretend=False), paths=p)
    df.install(df_unit())                                     # dst -> store symlink
    assert df.capture_plan(df_unit())[0][3] == 'skip-linked'


def test_cli_capture_copies_and_leaves_system_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv('CONFIGSYS_NO_DISCOVER', '1')
    from configsys.app import main
    home = tmp_path / 'home'
    (home / '.config' / 'configsys').mkdir(parents=True)
    (home / '.config' / 'configsys' / 'configsys.hu').write_text('{ configs: [ user ] }')
    real = home / '.config' / 'htop'
    real.mkdir(parents=True)
    (real / 'htoprc').write_text('mine')                     # htop-dotfiles rides in via `user`
    base = ['--home', str(home), '--os', 'pop', 'dotfiles', 'capture']

    assert main(base + ['--dry-run']) == 0                    # dry run writes nothing
    store = home / '.config' / 'configsys' / 'dotfiles' / 'htop-dotfiles.cfs' / 'htop'
    assert not store.exists()

    assert main(base + ['--yes']) == 0
    assert (store / 'htoprc').read_text() == 'mine'          # copied into the store
    assert (real / 'htoprc').read_text() == 'mine'           # system side UNTOUCHED (read-only)


# -- phase 2: .cfs marker, managed-when-empty, exclude globs, secret suggest ----

def test_config_install_creates_cfs_marker_even_without_content(tmp_path):
    # #5: installing a config -dotfiles with NO content anywhere still stamps the .cfs marker +
    # manifest, so the component reads as "managed" (installed) though nothing is linked yet.
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    assert df.get_version(rc) is None                         # nothing yet
    assert df.install(rc).ok                                  # graceful; marks managed
    cfs = p.user_dotfiles_dir / 'neovim.cfs'
    assert (cfs / 'manifest.hu').exists()
    assert df.get_version(rc) == 'managed'
    assert not (p.home / '.config' / 'nvim').exists()         # nothing linked / clobbered
    man = df._read_manifest(cfs / 'manifest.hu')
    assert man['config']['src'] == 'neovim'
    assert man['config']['dst'] == '$XDG_CONFIG_HOME/nvim'


def test_managed_config_over_real_file_keeps_it_and_warns(tmp_path):
    # marker + a real un-captured file at dst -> state 'managed', file untouched, startup warns.
    p = paths_for(tmp_path)
    nvim = p.home / '.config' / 'nvim'
    nvim.mkdir(parents=True)
    (nvim / 'init.lua').write_text('mine')
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    assert df.install(rc).ok
    assert df.spec_states(rc)[0][2] == 'managed'
    assert (nvim / 'init.lua').read_text() == 'mine'          # never clobbered
    assert not (nvim).is_symlink()
    assert any('capture' in t for _tag, t in df.warnings(rc))


def test_capture_excludes_secrets_and_writes_gitignore(tmp_path):
    p = paths_for(tmp_path)
    cfg = p.home / '.config' / 'nvim'
    cfg.mkdir(parents=True)
    (cfg / 'init.lua').write_text('cfg')
    (cfg / '.env').write_text('SECRET=1')                    # secret-shaped -> auto-excluded
    (cfg / 'id_rsa').write_text('KEY')
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    df.capture(rc)
    store = p.user_dotfiles_dir / 'neovim.cfs' / 'neovim'
    assert (store / 'init.lua').read_text() == 'cfg'
    assert not (store / '.env').exists() and not (store / 'id_rsa').exists()   # secrets kept out
    cfs = p.user_dotfiles_dir / 'neovim.cfs'
    gi = (cfs / '.gitignore').read_text()
    assert '.env' in gi and 'id_*' in gi
    assert '.env' in df._read_manifest(cfs / 'manifest.hu')['config']['exclude']
    assert (cfg / '.env').read_text() == 'SECRET=1'          # system side untouched


def test_capture_respects_a_preexisting_manifest_exclude(tmp_path):
    # a non-secret exclude the user put in the manifest is honored on capture (and no secret
    # auto-suggest, since the manifest already exists).
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    df._write_manifest(rc, {'config': {'src': 'neovim', 'dst': '$XDG_CONFIG_HOME/nvim',
                                       'exclude': ['big.log', 'cache/']}})
    cfg = p.home / '.config' / 'nvim'
    cfg.mkdir(parents=True)
    (cfg / 'init.lua').write_text('cfg')
    (cfg / 'big.log').write_text('noise')
    (cfg / 'cache').mkdir()
    (cfg / 'cache' / 'x').write_text('c')
    df.capture(rc)
    store = p.user_dotfiles_dir / 'neovim.cfs' / 'neovim'
    assert (store / 'init.lua').exists()
    assert not (store / 'big.log').exists() and not (store / 'cache').exists()


def test_capture_then_install_links_from_cfs(tmp_path):
    p = paths_for(tmp_path)
    cfg = p.home / '.config' / 'nvim'
    cfg.mkdir(parents=True)
    (cfg / 'init.lua').write_text('mine')
    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    df.capture(rc)                                           # -> store neovim.cfs/neovim
    assert df.install(rc).ok
    tgt = p.home / '.config' / 'nvim'
    store = p.user_dotfiles_dir / 'neovim.cfs' / 'neovim'
    assert tgt.is_symlink() and os.path.realpath(tgt) == os.path.realpath(store)
    assert df.get_version(rc) == 'linked'


def test_warns_on_link_that_still_points_into_repo(tmp_path):
    # a legacy link straight into the repo trips the #4 invariant warning (migrate fixes it).
    p = paths_for(tmp_path)
    (p.dotfiles_dir / 'neovim.cfs' / 'neovim').mkdir(parents=True)
    tgt = p.home / '.config' / 'nvim'
    tgt.parent.mkdir(parents=True)
    tgt.symlink_to(p.dotfiles_dir / 'neovim.cfs' / 'neovim')
    df = DotFiles(Runner(pretend=False), paths=p)
    assert any('migrate' in t for _tag, t in df.warnings(df_unit()))


# -- absorb-into: relocate a pre-existing file into the loader dir --------

ABSORB = '~/.bash.d/pre-configsys-aliases.sh'


def _bash_unit():
    return ResolvedComponent(
        key='dotfiles\\bash-dotfiles', driver='dotfiles', comp='bash-dotfiles',
        fields={'aliases': {'src': 'bash_aliases', 'dst': '~/.bash_aliases', 'absorb-into': ABSORB}})


def _seed_bash_src(p):
    p.dotfiles_dir.mkdir(parents=True, exist_ok=True)
    (p.dotfiles_dir / 'bash_aliases').write_text('# the new loader\n')
    p.home.mkdir(parents=True, exist_ok=True)


def test_absorb_moves_preexisting_aliases_into_bash_d(tmp_path):
    p = paths_for(tmp_path)
    _seed_bash_src(p)
    (p.home / '.bash_aliases').write_text('alias mine="echo hi"\n')     # the user's own file

    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.install(_bash_unit()).ok

    link = p.home / '.bash_aliases'
    assert link.is_symlink()
    # #4: links at the materialized STORE copy, not the repo template.
    assert os.path.realpath(link) == os.path.realpath(p.user_dotfiles_dir / 'bash_aliases')
    assert os.path.realpath(link) != os.path.realpath(p.dotfiles_dir / 'bash_aliases')
    absorbed = p.home / '.bash.d' / 'pre-configsys-aliases.sh'
    assert absorbed.is_file() and not absorbed.is_symlink()
    assert absorbed.read_text() == 'alias mine="echo hi"\n'            # aliases preserved
    assert os.access(absorbed, os.X_OK)                                # +x, so the loader sources it
    assert not (p.home / '.bash_aliases.pre-configsys').exists()       # moved, not backed up


def test_absorb_noop_when_no_preexisting_file(tmp_path):
    p = paths_for(tmp_path)
    _seed_bash_src(p)
    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.install(_bash_unit()).ok
    assert (p.home / '.bash_aliases').is_symlink()
    assert not (p.home / '.bash.d' / 'pre-configsys-aliases.sh').exists()   # nothing to absorb


def test_absorb_is_restored_on_uninstall(tmp_path):
    p = paths_for(tmp_path)
    _seed_bash_src(p)
    (p.home / '.bash_aliases').write_text('alias mine="echo hi"\n')
    df = DotFiles(Runner(pretend=False), paths=p)
    df.install(_bash_unit())

    df.uninstall(_bash_unit())
    restored = p.home / '.bash_aliases'
    assert restored.is_file() and not restored.is_symlink()
    assert restored.read_text() == 'alias mine="echo hi"\n'            # original put back
    assert not (p.home / '.bash.d' / 'pre-configsys-aliases.sh').exists()


def test_absorb_falls_back_to_backup_if_target_taken(tmp_path):
    p = paths_for(tmp_path)
    _seed_bash_src(p)
    (p.home / '.bash_aliases').write_text('mine\n')
    taken = p.home / '.bash.d' / 'pre-configsys-aliases.sh'            # already occupied
    taken.parent.mkdir(parents=True)
    taken.write_text('someone-elses\n')

    df = DotFiles(Runner(pretend=False), paths=p)
    assert df.install(_bash_unit()).ok
    assert (p.home / '.bash_aliases').is_symlink()
    assert taken.read_text() == 'someone-elses\n'                     # not clobbered
    assert (p.home / '.bash_aliases.pre-configsys').read_text() == 'mine\n'   # backed up instead
