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
    assert f'git -C {src} checkout v1.2.3' in cmd
    assert 'git -C' in cmd and 'fetch --tags' in cmd
    assert f'( cd {src} && ./configure --prefix={prefix} && make && make install )' in cmd
    assert f'mkdir -p {src.parent} {prefix}' in cmd
    assert 'printf %s v1.2.3' in cmd                       # marker records the version/ref
    assert 'sudo' not in cmd                               # userland by default


def test_version_static_forms_the_tag(tmp_path):
    r = Runner(pretend=True)
    # a static version + tag-prefix -> checkout the v-prefixed tag, no network
    Source(r, paths=None).install(
        src_unit(tmp_path, version={'static': '2.0.0'}, **{'tag-prefix': 'v'}))
    assert 'checkout v2.0.0' in r.calls[0] and 'printf %s 2.0.0' in r.calls[0]


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
    assert f'( cd {src} && ./configure --prefix={prefix} && make install )' in cmd
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


def test_curated_base_source_bindings_resolve():
    # base routes.hu ships a few `via: source` alternatives; pinning one selects it and pulls the
    # declared build deps (cxx->cpp-toolchain, make, and the driver's git)
    import os
    ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
    units = set(Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64',
                         pins={'btop': 'source'}).resolve_names(['btop']))
    assert 'source\\btop' in units
    assert {'apt\\make', 'apt\\cpp-toolchain', 'apt\\git'} <= units   # build toolchain pulled
    # and without the pin, source is NOT the default (native wins by driver-preference)
    plain = set(Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64').resolve_names(['btop']))
    assert 'apt\\btop' in plain and 'source\\btop' not in plain


def test_source_component_resolves_and_pulls_git(tmp_path):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  drivers: { source: { requires: git } }  components: {'
                 '  git:    { install: [ { via: native } ] }'
                 '  mytool: { install: [ { via: source  repo: r  build: make } ] } } }')
    units = set(Resolver(str(p), 'debian', '12').resolve_names(['mytool']))
    assert 'source\\mytool' in units and 'apt\\git' in units     # driver `requires: git` pulled
