'''The source driver (Phase 4): a declarative build-from-source medium — clone a git repo at a
resolved ref, run the route's `build:` steps in the tree with $PREFIX/$SRC/$VERSION/$ARCH
substituted, and record the built version in a marker file. Command construction is checked under
the pretend runner (which records r.calls); resolution wiring pulls the driver's `git` require.'''

import shutil
import subprocess

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.source import Source
from configsys.resolve import ResolveError
from configsys.paths import Paths
from configsys.runner import Runner
from configsys.routes import Resolver


def src_unit(tmp_path, comp='mytool', **fields):
    f = {'repo': 'https://example.com/x/mytool.git',
         'build': './configure --prefix=$PREFIX && make && make install',
         'installDir': str(tmp_path / 'src'), 'prefix': str(tmp_path / 'prefix')}
    f.update(fields)
    return ResolvedComponent(key=f'source\\{comp}', driver='source', comp=comp, fields=f)


def test_registry_has_source():
    fam = get_driver('source', Runner(pretend=True))
    assert isinstance(fam, Source) and is_supported('source')
    assert not fam.privileged and fam.honors_scope


def test_install_command_construction(tmp_path):
    r = Runner(pretend=True)
    src, prefix = tmp_path / 'src', tmp_path / 'prefix'
    Source(r, paths=None).install(src_unit(tmp_path, ref='v1.2.3'))
    cmd = r.calls[0]
    assert f'git clone https://example.com/x/mytool.git {src}' in cmd
    assert f'git -C {src} checkout -f v1.2.3' in cmd
    assert 'git -C' in cmd and 'fetch --tags' in cmd
    # after checkout, scrub the tree pristine so a reused checkout's stale build/ (cached
    # CMakeCache etc.) can't survive — preserving only our version marker
    assert f"git -C {src} clean -xfd -e '.configsys-*'" in cmd   # every own marker survives the clean
    assert (f'( cd {src} && export PATH="$HOME/.cargo/bin:$HOME/sdks/go/bin:$HOME/go/bin:$PATH" && '
            f'./configure --prefix={prefix} && make && make install )') in cmd
    assert f'mkdir -p {src.parent} && mkdir -p {prefix}' in cmd
    assert 'printf %s v1.2.3' in cmd                       # marker records the version/ref
    assert 'sudo' not in cmd                               # userland by default


def test_build_gets_toolchain_bin_dirs_on_path(tmp_path):
    # the build must find a NON-native toolchain a recipe requires (rustup cargo in ~/.cargo/bin),
    # since it runs in a fresh non-interactive shell — so those dirs are prepended to PATH.
    r = Runner(pretend=True)
    Source(r, paths=None).install(src_unit(tmp_path, ref='v1', build='cargo build --release'))
    assert 'export PATH="$HOME/.cargo/bin:$HOME/sdks/go/bin:$HOME/go/bin:$PATH" && cargo build --release' in r.calls[0]


def test_build_path_adds_extra_dirs(tmp_path):
    r = Runner(pretend=True)
    rc = src_unit(tmp_path, ref='v1', build='make', **{'build-path': '$PREFIX/toolchain/bin'})
    Source(r, paths=None).install(rc)
    prefix = tmp_path / 'prefix'
    assert f'export PATH="$HOME/.cargo/bin:$HOME/sdks/go/bin:$HOME/go/bin:{prefix}/toolchain/bin:$PATH"' in r.calls[0]


def test_version_static_forms_the_tag(tmp_path):
    r = Runner(pretend=True)
    # a static version + tag-prefix -> checkout the v-prefixed tag, no network
    Source(r, paths=None).install(
        src_unit(tmp_path, version={'static': '2.0.0'}, **{'tag-prefix': 'v'}))
    assert 'checkout -f v2.0.0' in r.calls[0] and 'printf %s 2.0.0' in r.calls[0]


def test_build_accepts_a_list_of_steps(tmp_path):
    r = Runner(pretend=True)
    Source(r, paths=None).install(
        src_unit(tmp_path, ref='main', build=['cmake -B build -DCMAKE_INSTALL_PREFIX=$PREFIX',
                                              'cmake --build build', 'cmake --install build']))
    cmd = r.calls[0]
    assert 'cmake -B build' in cmd and 'cmake --build build && cmake --install build' in cmd


def test_no_acquisition_or_build_is_a_clean_preflight_failure(tmp_path):
    r = Runner(pretend=True)
    # no repo AND no url/version -> nothing to acquire
    res = Source(r, paths=None).install(src_unit(tmp_path, repo=None))
    assert not res.ok and 'neither a `repo:`' in res.stderr and not r.calls
    # no build step
    res2 = Source(r, paths=None).install(src_unit(tmp_path, ref='v1', build=None))
    assert not res2.ok and 'no `build:`' in res2.stderr


def test_install_from_source_archive(tmp_path):
    # archive acquisition (no repo): download + extract + build — the missing 2x2 cell
    r = Runner(pretend=True)
    src, prefix = tmp_path / 'src', tmp_path / 'prefix'
    rc = src_unit(tmp_path, repo=None, url='https://ftp.gnu.org/gnu/foo/foo-1.2.3.tar.gz',
                  build='./configure --prefix=$PREFIX && make install')
    Source(r, paths=None).install(rc)
    cmd = r.calls[0]
    assert 'curl -fSL' in cmd and 'foo-1.2.3.tar.gz' in cmd
    assert 'tar -xf' in cmd and '--strip-components=1' in cmd   # strip the foo-1.2.3/ wrapper
    assert (f'( cd {src} && export PATH="$HOME/.cargo/bin:$HOME/sdks/go/bin:$HOME/go/bin:$PATH" && '
            f'./configure --prefix={prefix} && make install )') in cmd
    assert 'git clone' not in cmd                               # archive path, not git


def test_archive_strip_can_be_disabled(tmp_path):
    r = Runner(pretend=True)
    Source(r, paths=None).install(
        src_unit(tmp_path, repo=None, url='https://x/foo.tar.gz', build='make', strip=0))
    assert '--strip-components' not in r.calls[0]


def test_get_version_reads_marker(tmp_path):
    src = tmp_path / 'src'
    src.mkdir(parents=True)
    (src / '.configsys-mytool.version').write_text('1.2.3')
    assert Source(Runner(pretend=True), paths=None).get_version(src_unit(tmp_path)) == '1.2.3'
    # absent marker -> not installed
    assert Source(Runner(pretend=True), paths=None).get_version(
        src_unit(tmp_path, comp='other')) is None


def test_uninstall_without_cmd_warns(tmp_path):
    r = Runner(pretend=True)
    res = Source(r, paths=None).uninstall(src_unit(tmp_path))
    assert 'rm -rf' in r.calls[0] and 'configsys-mytool.version' in r.calls[0]   # marker-guarded
    assert res.ok and 'may remain' in res.cmd                                    # advisory warning


def test_uninstall_runs_declared_cmd(tmp_path):
    r = Runner(pretend=True)
    Source(r, paths=None).uninstall(src_unit(tmp_path, **{'uninstall-cmd': 'make uninstall'}))
    assert 'make uninstall' in r.calls[0] and 'rm -rf' in r.calls[0]


OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
@pytest.mark.real_runner
def test_real_build_clones_checks_out_and_installs(tmp_path):
    # a local git repo with a trivial Makefile that "installs" into $PREFIX, tagged v1.0.0
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'Makefile').write_text(
        'install:\n\tmkdir -p $(PREFIX)/bin\n'
        '\tprintf %s hi > $(PREFIX)/bin/mytool\n')
    env = {**__import__('os').environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    for args in (['init', '-q'], ['add', '-A'], ['commit', '-qm', 'x'], ['tag', 'v1.0.0']):
        subprocess.run(['git', *args], cwd=repo, env=env, check=True)

    prefix = tmp_path / 'prefix'
    rc = src_unit(tmp_path, repo=str(repo), version={'static': '1.0.0'},
                  build='make install PREFIX=$PREFIX', prefix=str(prefix), **{'tag-prefix': 'v'})
    fam = Source(Runner(pretend=False), paths=None)
    res = fam.install(rc)
    assert res.ok, res.output
    assert (prefix / 'bin' / 'mytool').read_text() == 'hi'         # built + installed to prefix
    assert fam.get_version(rc) == '1.0.0'                          # marker recorded


def test_no_source_bindings_in_core():
    # source-building lives in the configsys-source PLUGIN now, not base routes.hu (the fold). No
    # core component carries a `via: source` binding — a regression guard against re-adding one.
    import os
    from configsys.routes import load
    ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
    _cascade, components, _drivers, _co = load(ROUTES)
    with_source = sorted(n for n, c in components.items()
                         if any(b.via == 'source' for b in c.bindings))
    assert with_source == [], f'core should ship no source bindings (moved to the plugin): {with_source}'
    # btop resolves to native (its former source binding is gone); pinning source now declines
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64')
    assert 'apt\\btop' in set(r.resolve_names(['btop']))
    with pytest.raises(ResolveError):
        Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64',
                 pins={'btop': 'source'}).resolve_names(['btop'])


def test_source_component_resolves_and_pulls_git(tmp_path):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  drivers: { source: { requires: git } }  components: {'
                 '  git:    { install: [ { via: native } ] }'
                 '  mytool: { install: [ { via: source  repo: r  build: make } ] } } }')
    units = set(Resolver(str(p), 'debian', '12').resolve_names(['mytool']))
    assert 'source\\mytool' in units and 'apt\\git' in units     # driver `requires: git` pulled


def test_resolve_version_rejects_shell_metacharacters(tmp_path):
    # a discovered tag name is network input; a metachar-laden one must read as undiscoverable
    # (None) rather than reach a build shell. Covered at the Driver chokepoint for every driver.
    from configsys.componentObj import ResolvedComponent
    from configsys.drivers.source import Source
    from configsys.runner import Runner
    drv = Source(Runner(pretend=True))
    for bad in ('1.0;reboot', '1.0$(id)', '`whoami`', '1 2'):
        rc = ResolvedComponent(key='source\\x', driver='source', comp='x',
                               fields={'version': bad, 'repo': 'https://h/r', 'build': 'make'})
        assert drv.resolve_version(rc) is None
    for good in ('1.2.3', 'v2024.2.1.11', '1:2.3+build~rc1'):
        rc = ResolvedComponent(key='source\\x', driver='source', comp='x',
                               fields={'version': good, 'repo': 'https://h/r', 'build': 'make'})
        assert drv.resolve_version(rc) == good


# -- review-2026-11-2 A9: a checkout configsys didn't create is never cleaned or deleted -----------

def _git(cwd, *a):
    import subprocess
    subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)


def _upstream(tmp_path):
    up = tmp_path / 'upstream'
    up.mkdir()
    _git(up, 'init', '-q', '-b', 'main')
    (up / 'config.def.h').write_text('default\n')
    (up / '.gitignore').write_text('build/\n')
    _git(up, 'add', '-A')
    _git(up, 'commit', '-qm', 'init')
    _git(up, 'tag', 'v1')
    return up


def _src_setup(tmp_path, adopt=False, force=False):
    from configsys.drivers.source import Source
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    paths.source_adopt, paths.install_force = adopt, force
    rc = ResolvedComponent(key='source\\dwm', driver='source', comp='dwm',
                           fields={'repo': str(_upstream(tmp_path) if not (tmp_path / 'upstream').exists()
                                               else tmp_path / 'upstream'),
                                   'version': {'static': '1'}, 'tag-prefix': 'v', 'build': 'true'})
    return Source(Runner(), paths=paths), rc, tmp_path / 'home' / 'src' / 'dwm'


@pytest.mark.real_runner
def test_your_own_checkout_is_refused_then_adopted_never_cleaned_or_deleted(tmp_path):
    drv, rc, src = _src_setup(tmp_path)
    src.parent.mkdir(parents=True)
    _git(src.parent, 'clone', '-q', str(tmp_path / 'upstream'), 'dwm')
    (src / 'config.h').write_text('my config\n')                 # untracked, yours
    (src / 'config.def.h').write_text('my edit\n')               # a tracked edit
    res = drv.install(rc)
    assert not res.ok and (src / 'config.h').exists()            # refused, nothing touched
    drv, rc, src = _src_setup(tmp_path, adopt=True)
    (src / 'config.def.h').write_text('default\n')               # (a plain checkout won't overwrite edits)
    assert drv.install(rc).ok
    assert (src / 'config.h').read_text() == 'my config\n'       # adopted: no clean
    drv.uninstall(rc)
    assert (src / 'config.h').exists() and (src / '.git').exists()   # adopted: never deleted


@pytest.mark.real_runner
def test_a_configsys_clone_with_local_changes_needs_force_and_clean_ones_are_removed(tmp_path):
    drv, rc, src = _src_setup(tmp_path)
    assert drv.install(rc).ok and (src / '.configsys-dwm.cloned').exists()
    (src / 'config.h').write_text('edited after install\n')
    res = drv.install(rc)
    assert not res.ok and (src / 'config.h').exists()            # local changes: refused
    drv.uninstall(rc)
    assert src.exists()                                           # ...and not deleted either
    drv, rc, src = _src_setup(tmp_path, force=True)
    assert drv.install(rc).ok and not (src / 'config.h').exists()   # --force discards them
    drv.uninstall(rc)
    assert not src.exists()                                       # ours and clean: removed


def _head_setup(tmp_path, **fields):
    from configsys.drivers.source import Source
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    paths.source_adopt = paths.install_force = False
    up = tmp_path / 'upstream'
    if not up.exists():
        _upstream(tmp_path)
    f = {'repo': str(up), 'build': 'true'}
    f.update(fields)
    rc = ResolvedComponent(key='source\\dwm', driver='source', comp='dwm', fields=f)
    return Source(Runner(), paths=paths), rc, tmp_path / 'home' / 'src' / 'dwm'


def _tip(d):
    return subprocess.run(['git', '-C', str(d), 'rev-parse', 'HEAD'], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.mark.real_runner
@pytest.mark.parametrize('fields', [{}, {'ref': 'main'}])
def test_a_branch_recipe_upgrade_builds_the_new_upstream_commit(tmp_path, fields):
    # B14 / drivers-lang-07: HEAD / a branch follows origin, not the stale local branch
    drv, rc, src = _head_setup(tmp_path, **fields)
    assert drv.install(rc).ok
    up = tmp_path / 'upstream'
    (up / 'config.def.h').write_text('newer\n')
    _git(up, 'commit', '-qam', 'upstream moves')
    assert drv.upgrade(rc).ok, 'upgrade failed'
    assert _tip(src) == _tip(up)
    assert (src / 'config.def.h').read_text() == 'newer\n'


@pytest.mark.real_runner
def test_a_changed_repo_repoints_a_configsys_made_tree(tmp_path):
    drv, rc, src = _head_setup(tmp_path)
    assert drv.install(rc).ok
    fork = tmp_path / 'fork'
    subprocess.run(['git', 'clone', '-q', str(tmp_path / 'upstream'), str(fork)], check=True)
    (fork / 'config.def.h').write_text('forked\n')
    _git(fork, 'commit', '-qam', 'fork')
    rc.fields['repo'] = str(fork)
    assert drv.upgrade(rc).ok
    assert (src / 'config.def.h').read_text() == 'forked\n'


@pytest.mark.real_runner
def test_an_archive_rebuild_starts_from_a_fresh_tree(tmp_path):
    # B14 / drivers-lang-09: a stale file from the previous extract (or a CMakeCache) doesn't survive
    import tarfile
    from configsys.drivers.source import Source
    work = tmp_path / 'pkg' / 'tool-1'
    work.mkdir(parents=True)
    (work / 'Makefile').write_text('all:\n\ttrue\n')
    arc = tmp_path / 'tool-1.tar.gz'
    with tarfile.open(arc, 'w:gz') as tf:
        tf.add(work, arcname='tool-1')
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    paths.source_adopt = paths.install_force = False
    rc = ResolvedComponent(key='source\\tool', driver='source', comp='tool',
                           fields={'url': f'file://{arc}', 'version': {'static': '1'}, 'build': 'true'})
    drv = Source(Runner(), paths=paths)
    assert drv.install(rc).ok, 'first build failed'
    src = tmp_path / 'home' / 'src' / 'tool'
    (src / 'CMakeCache.txt').write_text('stale\n')
    assert drv.install(rc).ok, 'rebuild failed'
    assert not (src / 'CMakeCache.txt').exists() and (src / 'Makefile').exists()
    assert (src / '.configsys-tool.cloned').exists() and drv.get_version(rc) == '1'


def test_system_scope_keeps_the_tree_in_user_space_and_needs_sudo_in_the_recipe(tmp_path):
    # B14 / drivers-lang-08
    from configsys.drivers.source import Source
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    r = Runner(pretend=True)
    drv = Source(r, paths=paths)
    rc = ResolvedComponent(key='source\\dwm', driver='source', comp='dwm',
                           fields={'repo': 'https://x/dwm', 'build': 'make install', 'scope': 'system'})
    res = drv.install(rc)
    assert not res.ok and '$SUDO' in res.output and r.calls == []
    assert str(drv._src_dir(rc)).startswith(str(tmp_path / 'home'))
    rc.fields['build'] = 'make && $SUDO make PREFIX=$PREFIX install'
    drv.install(rc)
    assert 'sudo make PREFIX=/usr/local install' in r.calls[-1]
    assert 'sudo mkdir -p /usr/local' in r.calls[-1]
