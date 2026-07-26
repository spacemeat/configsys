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


# -- content root follows the layer that defined the component -------------

def test_src_anchors_at_the_defining_layers_dotfiles_dir(tmp_path):
    # a component defined in /somewhere/routes.hu sources from /somewhere/dotfiles/
    df = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path))
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'},
                           source=str(tmp_path / 'myplugin' / 'routes.hu'))
    src, _tgt, _ = df._pairs(rc)[0]
    assert src == tmp_path / 'myplugin' / 'dotfiles' / 'foo.sh'


def test_src_falls_back_to_repo_without_a_source(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'})   # no source
    src, _tgt, _ = df._pairs(rc)[0]
    assert src == p.dotfiles_dir / 'foo.sh'


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
    assert src == routes.parent / 'dotfiles' / 'm'


def test_registry_has_dotfiles():
    assert isinstance(get_driver('dotfiles', Runner(pretend=True)), DotFiles)


def test_single_inline_spec():
    rc = ResolvedComponent(key='dotfiles\\arduino', driver='dotfiles', comp='arduino',
                           fields={'src': 'bash.d/arduino.sh', 'dst': '~/.bash.d/arduino.sh'})
    assert DotFiles._specs(rc) == [('arduino', 'bash.d/arduino.sh', '~/.bash.d/arduino.sh', None)]


def test_dst_env_expansion_defaults_xdg(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    src, tgt, _ = df._pairs(df_unit())[0]
    assert src == p.dotfiles_dir / 'neovim'
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
    assert target.is_symlink()
    assert os.path.realpath(target) == os.path.realpath(src_dir)
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
    assert dest == p.user_dotfiles_dir / 'neovim'             # into the local store

    (p.user_dotfiles_dir / 'neovim').mkdir(parents=True)      # store already has it
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
    store = home / '.config' / 'configsys' / 'dotfiles' / 'htop'
    assert not store.exists()

    assert main(base + ['--yes']) == 0
    assert (store / 'htoprc').read_text() == 'mine'          # copied into the store
    assert (real / 'htoprc').read_text() == 'mine'           # system side UNTOUCHED (read-only)


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
    assert os.path.realpath(link) == os.path.realpath(p.dotfiles_dir / 'bash_aliases')
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
