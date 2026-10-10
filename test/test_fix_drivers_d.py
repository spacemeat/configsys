'''Regression tests for the driver/glue fix batch D:

1. set-version honesty — `Driver.targets_version` (False where set_version can only reinstall the
   routed version or there is no version at all).
2. apk orphan scan — `Apk.installed_index` (`apk list --installed`, `apk info -v` fallback) and
   `Apk.explicit_keys` (/etc/apk/world).
3. the shell-writes guard never reverts configsys's OWN rc marker blocks (the zsh glue loader that
   `install shell-glue` writes inside the guard's window).
4. conf.d load order: 00-configsys -> 50-<component> -> 90-<user> -> 99-user, with migration of
   pre-band (unprefixed) links configsys owns, and uninstall of both.
5. staged glue is machine-local state; `activate` turns it into ordinary user glue (user.d, correct
   per-shell extension, the user band), and the old capture-root layout migrates.
'''

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from configsys import shellguard
from configsys.componentObj import ResolvedComponent
from configsys.driver import Driver
from configsys.drivers import get_driver
from configsys.drivers.apk import Apk, _parse_world
from configsys.drivers.glue import Glue, component_link_stem, user_link_name
from configsys.paths import Paths
from configsys.runner import Result, Runner


def paths_for(tmp_path, shells='bash'):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                      'CONFIGSYS_GLUE_SHELLS': shells})


def glue_unit(comp, glue):
    return ResolvedComponent(key=f'glue\\{comp}', driver='glue', comp=comp, fields={'glue': glue})


def loader_unit():
    return ResolvedComponent(key='glue\\shell-glue', driver='glue', comp='shell-glue',
                             fields={'loader': 'all'})


def ship(p, shell, name, text):
    d = p.glue_dir / 'shell' / shell
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


# -- 1. targets_version ------------------------------------------------------------------------

FIXED_VERSION = ('tarball', 'appImage', 'font', 'native-pkg-file', 'glue', 'service', 'group',
                 'gcc', 'clang', 'gcc-toolset', 'aur', 'rpm-ostree')
TARGETS = ('apt', 'dnf', 'zypper', 'xbps', 'brew', 'flatpak', 'snap', 'cargo', 'npm', 'gem', 'pip',
           'opam', 'luarocks', 'cabal', 'go-install', 'pyenv', 'sdkman', 'source', 'script')


def test_base_driver_targets_version_by_default():
    assert Driver.targets_version is True


@pytest.mark.parametrize('name', FIXED_VERSION)
def test_fixed_version_drivers_declare_targets_version_false(name):
    drv = get_driver(name, Runner(pretend=True))
    assert drv is not None, name
    assert drv.targets_version is False


@pytest.mark.parametrize('name', TARGETS)
def test_version_capable_drivers_keep_targets_version(name):
    drv = get_driver(name, Runner(pretend=True))
    assert drv is not None, name
    assert drv.targets_version is True


# -- 2. apk orphan scan -------------------------------------------------------------------------

class FakeRunner:
    pretend = False

    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, **_kw):
        self.calls.append(cmd)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(cmd, code, stdout=out)
        return Result(cmd, 0, stdout='')


# captured from an alpine:3.20 container
APK_LIST_INSTALLED = '''\
WARNING: opening from cache https://dl-cdn.alpinelinux.org/alpine/v3.20/main: No such file or directory
alpine-baselayout-3.6.5-r0 x86_64 {alpine-baselayout} (GPL-2.0-only) [installed]
busybox-1.36.1-r29 x86_64 {busybox} (GPL-2.0-only) [installed]
ca-certificates-bundle-20240705-r0 x86_64 {ca-certificates} (MPL-2.0 AND MIT) [installed]
curl-8.11.1-r0 x86_64 {curl} (curl) [installed]
libcurl-8.11.1-r0 x86_64 {curl} (curl) [installed]
py3-setuptools-70.3.0-r0 noarch {py3-setuptools} (MIT) [installed]
'''
APK_INFO_V = '''\
alpine-baselayout-3.6.5-r0
busybox-1.36.1-r29
curl-8.11.1-r0
'''
APK_WORLD = '''\
alpine-base
curl>=8
py3-setuptools@edge
htop=3.3.0-r0
!nano
'''


def test_apk_installed_index_parses_apk_list_installed():
    d = Apk(FakeRunner([('apk list --installed', 0, APK_LIST_INSTALLED)]))
    idx = d.installed_index()
    assert idx['busybox'] == '1.36.1-r29'
    assert idx['ca-certificates-bundle'] == '20240705-r0'
    assert idx['py3-setuptools'] == '70.3.0-r0'
    assert idx['libcurl'] == '8.11.1-r0' and idx['curl'] == '8.11.1-r0'
    assert not any(k.startswith('WARNING') for k in idx)


def test_apk_installed_index_falls_back_to_apk_info_v():
    r = FakeRunner([('apk list --installed', 1, ''), ('apk info -v', 0, APK_INFO_V)])
    assert Apk(r).installed_index() == {'alpine-baselayout': '3.6.5-r0', 'busybox': '1.36.1-r29',
                                        'curl': '8.11.1-r0'}


def test_apk_installed_index_none_on_failure_never_empty():
    r = FakeRunner([('apk list --installed', 1, ''), ('apk info -v', 1, '')])
    assert Apk(r).installed_index() is None


def test_apk_explicit_keys_reads_world(tmp_path, monkeypatch):
    world = tmp_path / 'world'
    world.write_text(APK_WORLD)
    monkeypatch.setattr(Apk, 'WORLD', str(world))
    assert Apk(FakeRunner()).explicit_keys() == {'alpine-base', 'curl', 'py3-setuptools', 'htop'}
    monkeypatch.setattr(Apk, 'WORLD', str(tmp_path / 'absent'))
    assert Apk(FakeRunner()).explicit_keys() is None
    assert _parse_world('a b\n!c\nd~1.2\n') == {'a', 'b', 'd'}


def test_apk_batched_get_version_answers_from_index():
    r = FakeRunner([('apk list --installed', 0, APK_LIST_INSTALLED)])
    d = Apk(r)
    d._batch = d.batch_index([])
    n = len(r.calls)
    rc = ResolvedComponent(key='apk\\curl', driver='apk', comp='curl', fields={})
    assert d.get_version(rc) == '8.11.1-r0'
    absent = ResolvedComponent(key='apk\\htop', driver='apk', comp='htop', fields={})
    assert d.get_version(absent) is None
    assert len(r.calls) == n


def test_orphan_scan_enumerates_apk(monkeypatch, tmp_path):
    # the orphan scan's per-driver enumeration sees apk's packages + its explicit set
    world = tmp_path / 'world'
    world.write_text('curl\n')
    monkeypatch.setattr(Apk, 'WORLD', str(world))
    d = Apk(FakeRunner([('apk list --installed', 0, APK_LIST_INSTALLED)]))
    idx, expl = d.installed_index(), d.explicit_keys()
    assert 'curl' in idx and expl == {'curl'} and 'libcurl' not in expl


# -- 3. the guard never reverts configsys's own rc blocks ---------------------------------------

def _run_plan_with_guard(p, plan, runner):
    from configsys.actions import run_plan
    from configsys.ledger import Ledger
    ctx = SimpleNamespace(runner=runner, paths=p,
                          config=SimpleNamespace(guard_shell_writes=lambda comp: True))
    lines = []
    run_plan(ctx, plan, ledger=Ledger(), on_line=lines.append)
    return lines


def test_guard_keeps_the_zsh_glue_loader_that_install_shell_glue_writes(tmp_path):
    # repro: CONFIGSYS_GLUE_SHELLS=zsh configsys install shell-glue -> "guarded: reverted 6 line(s)"
    # and the loader staged as shell-glue zsh glue. The loader block is configsys's own.
    p = paths_for(tmp_path, shells='zsh')
    p.home.mkdir(parents=True)
    (p.home / '.zshrc').write_text('export EXISTING=1\n')
    lines = _run_plan_with_guard(p, [('install', 'glue\\shell-glue', loader_unit())],
                                 Runner(pretend=False))
    zshrc = (p.home / '.zshrc').read_text()
    assert zshrc.startswith('export EXISTING=1\n')
    assert '# >>> configsys glue >>>' in zshrc and '# <<< configsys glue <<<' in zshrc
    assert not any('guarded' in ln for ln in lines), lines
    assert shellguard.list_staged(p) == []
    assert Glue(Runner(pretend=False), p).get_version(loader_unit()) == 'linked'


def test_guard_reverts_installer_lines_but_keeps_a_configsys_block(tmp_path):
    home = tmp_path
    rc = home / '.zshrc'
    rc.write_text('A=1\n# >>> configsys glue >>>\nold\n# <<< configsys glue <<<\nB=2\n')
    snap = shellguard.snapshot(home)
    # one op both refreshes configsys's block in place AND an installer appends a line
    rc.write_text('A=1\n# >>> configsys glue >>>\nnew\n# <<< configsys glue <<<\nB=2\nexport NVM=1\n')
    captured = shellguard.revert_and_capture(home, snap)
    assert rc.read_text() == 'A=1\n# >>> configsys glue >>>\nnew\n# <<< configsys glue <<<\nB=2\n'
    assert 'export NVM=1' in captured['zsh'] and 'new' not in captured['zsh']


def test_guard_new_configsys_block_plus_installer_lines(tmp_path):
    home = tmp_path
    rc = home / '.zshrc'
    rc.write_text('A=1\n')
    snap = shellguard.snapshot(home)
    rc.write_text('A=1\nexport SDK=1\n# >>> configsys glue >>>\nx\n# <<< configsys glue <<<\n')
    captured = shellguard.revert_and_capture(home, snap)
    assert rc.read_text() == 'A=1\n# >>> configsys glue >>>\nx\n# <<< configsys glue <<<\n'
    assert captured['zsh'].count('export SDK=1') == 1 and '>>> configsys' not in captured['zsh']


def test_guard_only_a_configsys_block_on_a_created_file_is_kept(tmp_path):
    home = tmp_path
    snap = shellguard.snapshot(home)
    (home / '.zshrc').write_text('# >>> configsys glue >>>\nx\n# <<< configsys glue <<<\n')
    assert shellguard.revert_and_capture(home, snap) == {}
    assert (home / '.zshrc').exists()


def test_guard_unterminated_marker_is_not_exempt(tmp_path):
    home = tmp_path
    (home / '.zshrc').write_text('A=1\n')
    snap = shellguard.snapshot(home)
    (home / '.zshrc').write_text('A=1\n# >>> configsys glue >>>\nevil\n')
    captured = shellguard.revert_and_capture(home, snap)
    assert (home / '.zshrc').read_text() == 'A=1\n' and 'evil' in captured['zsh']


# -- 4. conf.d load order + migration -----------------------------------------------------------

def test_link_name_bands():
    assert component_link_stem('bat') == '50-bat'
    assert component_link_stem('00-configsys') == '00-configsys'
    assert user_link_name('foo.sh') == '90-foo.sh'
    assert user_link_name('99-user.zsh') == '99-user.zsh'
    assert user_link_name('10-early.sh') == '10-early.sh'      # a deliberate user prefix is kept


def test_confd_order_prelude_components_user(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', '00-configsys.sh', '# prelude\n')
    ship(p, 'bash', 'bat.sh', '# bat\n')
    ship(p, 'bash', 'zoxide.sh', '# zoxide\n')
    (p.glue_dir / 'bash_aliases').write_text('# loader\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    assert g.install(loader_unit()).ok                          # scaffolds 99-user
    path, _ = g.new_user_snippet('aliases', 'bash')             # `glue add aliases`
    g.deploy_user_glue('bash')
    for comp, glue in (('configsys-glue', '00-configsys'), ('bat-glue', 'bat'),
                       ('zoxide-glue', 'zoxide')):
        assert g.install(glue_unit(comp, glue)).ok
    confd = p.home / '.config' / 'bash' / 'conf.d'
    names = sorted(n.name for n in confd.iterdir())
    assert names == ['00-configsys.sh', '50-bat.sh', '50-zoxide.sh', '90-aliases.sh', '99-user.sh']
    assert g.user_glue_link('bash', path.name) == confd / '90-aliases.sh'
    # the bash loader's own glob order (C collation and the user's locale agree on digit bands)
    out = subprocess.run(['bash', '-c', f'cd {confd} && printf "%s\\n" *.sh'],
                         capture_output=True, text=True).stdout.split()
    assert out == names


def test_gestalt_block_orders_prelude_components_user(tmp_path):
    p = paths_for(tmp_path, shells='elvish')
    ship(p, 'elvish', '00-configsys.elv', 'fn cf { }\n')
    ship(p, 'elvish', 'bat.elv', 'fn bat { }\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    assert g.install(loader_unit()).ok
    path, _ = g.new_user_snippet('mine', 'elvish')
    path.write_text('fn mine { }\n')
    g.deploy_user_glue('elvish')
    assert g.install(glue_unit('configsys-glue', '00-configsys')).ok
    assert g.install(glue_unit('bat-glue', 'bat')).ok
    block = (p.home / '.config' / 'elvish' / 'rc.elv').read_text()
    order = [block.index(f'# >> {n}') for n in
             ('00-configsys.elv', '50-bat.elv', '90-mine.elv', '99-user.elv')]
    assert order == sorted(order)


def _legacy_deploy(p, shell, glue, ext, text):
    '''Lay down a pre-band deployment: store mirror <store>/<shell>/conf.d/<glue>.<ext> and an
    unprefixed conf.d link to it.'''
    mirror = p.user_glue_dir / shell / 'conf.d' / f'{glue}.{ext}'
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(text)
    confd = p.home / '.config' / shell / 'conf.d'
    confd.mkdir(parents=True, exist_ok=True)
    (confd / f'{glue}.{ext}').symlink_to(mirror)
    return confd / f'{glue}.{ext}', mirror


def test_install_migrates_a_legacy_unprefixed_link(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', 'bat.sh', '# bat\n')
    legacy, old_mirror = _legacy_deploy(p, 'bash', 'bat', 'sh', '# bat\n')
    g = Glue(Runner(pretend=False), p)
    rc = glue_unit('bat-glue', 'bat')
    assert g.install(rc).ok
    new = p.home / '.config' / 'bash' / 'conf.d' / '50-bat.sh'
    assert not legacy.exists() and not legacy.is_symlink()
    assert new.is_symlink() and new.read_text() == '# bat\n'
    assert not old_mirror.exists()
    assert (p.user_glue_dir / 'bash' / 'conf.d' / '50-bat.sh').is_file()
    assert g.get_version(rc) == 'linked'


def test_status_migrates_a_legacy_link_and_keeps_it_active(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', 'bat.sh', '# bat\n')
    legacy, _ = _legacy_deploy(p, 'bash', 'bat', 'sh', '# bat\n')
    rc = glue_unit('bat-glue', 'bat')
    # a dry run reports it active without writing anything
    assert Glue(Runner(pretend=True), p).get_version(rc) == 'linked'
    assert legacy.is_symlink()
    g = Glue(Runner(pretend=False), p)
    states = g.spec_states(rc)                                 # status view migrates
    assert [s[2] for s in states] == ['linked']
    assert not legacy.is_symlink()
    assert (p.home / '.config' / 'bash' / 'conf.d' / '50-bat.sh').is_symlink()


def test_migration_never_touches_foreign_files_or_links(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', 'bat.sh', '# bat\n')
    ship(p, 'bash', 'fd.sh', '# fd\n')
    confd = p.home / '.config' / 'bash' / 'conf.d'
    confd.mkdir(parents=True)
    (confd / 'bat.sh').write_text('# my own real file\n')      # a real file — not ours
    elsewhere = tmp_path / 'elsewhere.sh'
    elsewhere.write_text('# another tool\n')
    (confd / 'fd.sh').symlink_to(elsewhere)                    # a link outside our roots
    g = Glue(Runner(pretend=False), p)
    assert g.install(glue_unit('bat-glue', 'bat')).ok
    assert g.install(glue_unit('fd-glue', 'fd')).ok
    assert (confd / 'bat.sh').read_text() == '# my own real file\n'
    assert os.path.realpath(confd / 'fd.sh') == os.path.realpath(elsewhere)
    assert (confd / '50-bat.sh').is_symlink() and (confd / '50-fd.sh').is_symlink()
    g.uninstall(glue_unit('fd-glue', 'fd'))
    assert (confd / 'fd.sh').is_symlink()                      # still not ours to remove


def test_uninstall_removes_banded_and_legacy_links(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', 'bat.sh', '# bat\n')
    g = Glue(Runner(pretend=False), p)
    rc = glue_unit('bat-glue', 'bat')
    assert g.install(rc).ok
    confd = p.home / '.config' / 'bash' / 'conf.d'
    # a stray pre-band link of ours appears (e.g. restored from a backup)
    (confd / 'bat.sh').symlink_to(p.glue_dir / 'shell' / 'bash' / 'bat.sh')
    assert g.uninstall(rc).ok
    assert not (confd / '50-bat.sh').is_symlink() and not (confd / 'bat.sh').is_symlink()


def test_user_glue_legacy_unprefixed_link_is_migrated(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    path, _ = g.new_user_snippet('mine', 'bash')
    confd = p.home / '.config' / 'bash' / 'conf.d'
    confd.mkdir(parents=True)
    (confd / 'mine.sh').symlink_to(path)                       # the pre-band user link
    g.deploy_user_glue('bash')
    assert not (confd / 'mine.sh').is_symlink()
    assert os.path.realpath(confd / '90-mine.sh') == os.path.realpath(path)


def test_override_follows_the_banded_name(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    ship(p, 'bash', 'bat.sh', '# shipped\n')
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    rc = glue_unit('bat-glue', 'bat')
    assert g.install(rc).ok
    forks = g.override(rc, local=True)
    forks[0][0].write_text('# mine\n')
    assert g.install(rc).ok
    link = p.home / '.config' / 'bash' / 'conf.d' / '50-bat.sh'
    assert link.read_text() == '# mine\n'
    ship(p, 'bash', 'bat.sh', '# shipped v2\n')
    assert [d[0] for d in g.override_drift(rc)] == ['bash']


# -- 5. staged glue: machine-local, activates as user glue, migrates ----------------------------

def test_staging_is_machine_local_even_with_a_primary_plugin(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    prim = tmp_path / 'primary'
    p.primary_dotfiles_dir = prim / 'dotfiles'
    p.primary_glue_dir = prim / 'glue'
    p.home.mkdir(parents=True)
    (p.home / '.bashrc').write_text('A=1\n')
    snap = shellguard.snapshot(p.home)
    (p.home / '.bashrc').write_text('A=1\nexport SDKMAN_DIR=x\n')
    msg = shellguard.finish(p, 'sdkman', snap)
    assert 'guarded: reverted 1 line(s)' in msg
    staged = shellguard.staged_for(p, 'sdkman')
    assert [s for s, _ in staged] == ['bash']
    assert staged[0][1] == p.state_dir / 'staged-glue' / 'bash' / 'sdkman.sh'
    assert not prim.exists()                                   # nothing in the plugin tree


def test_zsh_activation_uses_zsh_extension_and_actually_loads(tmp_path):
    p = paths_for(tmp_path, shells='zsh')
    p.home.mkdir(parents=True)
    shellguard.stage(p, 'nvm', {'zsh': '# from ~/.zshrc (captured by configsys — x)\n'
                                       'export CS_ACTIVATED=yes\n'})
    done = shellguard.activate(p, 'nvm', Runner(pretend=False))
    link = p.home / '.config' / 'zsh' / 'conf.d' / '90-nvm.zsh'
    assert done == [('zsh', link)]
    assert os.path.realpath(link) == os.path.realpath(
        p.user_glue_dir / 'shell' / 'zsh' / 'user.d' / 'nvm.zsh')
    assert '# >>> configsys glue >>>' in (p.home / '.zshrc').read_text()   # loader hooked up
    if shutil.which('zsh') is None:
        pytest.skip('zsh not installed')
    out = subprocess.run(['zsh', '-i', '-c', 'print -r -- "v=$CS_ACTIVATED"'],
                         env={'HOME': str(p.home), 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                              'TERM': 'dumb'},
                         capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert 'v=yes' in out.stdout


def test_activation_shows_as_user_glue_and_goes_to_primary(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    p.primary_glue_dir = tmp_path / 'primary' / 'glue'
    p.home.mkdir(parents=True)
    shellguard.stage(p, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n'})
    shellguard.activate(p, 'sdkman', Runner(pretend=False))
    snippet = p.primary_glue_dir / 'shell' / 'bash' / 'user.d' / 'sdkman.sh'
    assert snippet.is_file()                                   # same destination as `glue add`
    rows = Glue(Runner(pretend=False), p).user_glue_entries()
    assert ('bash', snippet, p.home / '.config' / 'bash' / 'conf.d' / '90-sdkman.sh',
            'linked') in rows
    assert shellguard.list_staged(p) == []


def test_reactivation_appends_and_never_clobbers_user_edits(tmp_path):
    p = paths_for(tmp_path, shells='bash')
    p.home.mkdir(parents=True)
    shellguard.stage(p, 'sdkman', {'bash': 'export ONE=1\n'})
    shellguard.activate(p, 'sdkman', Runner(pretend=False), local=True)
    snippet = p.user_glue_dir / 'shell' / 'bash' / 'user.d' / 'sdkman.sh'
    snippet.write_text(snippet.read_text() + 'alias mine=1\n')     # the user edits it
    shellguard.stage(p, 'sdkman', {'bash': 'export TWO=2\n'})
    shellguard.activate(p, 'sdkman', Runner(pretend=False), local=True)
    text = snippet.read_text()
    assert 'export ONE=1' in text and 'alias mine=1' in text and 'export TWO=2' in text


def test_migrates_old_layout_staged_and_activated_blocks(tmp_path):
    p = paths_for(tmp_path, shells='bash,zsh')
    p.home.mkdir(parents=True)
    cap = p.user_dotfiles_dir
    hdr = '# from ~/.bashrc (captured by configsys — installer wanted to write this)\n'
    # old staged
    (cap / 'staged-glue').mkdir(parents=True)
    (cap / 'staged-glue' / 'nvm.bash.sh').write_text(hdr + 'export NVM_DIR=x\n')
    (cap / 'staged-glue' / 'nvm.zsh.sh').write_text(hdr + 'export NVM_Z=x\n')
    # old activated (bash link worked; zsh link never loaded)
    for shell, comp in (('bash', 'sdkman'), ('zsh', 'rustup')):
        f = cap / 'shell' / shell / f'{comp}.sh'
        f.parent.mkdir(parents=True)
        f.write_text(hdr + f'export {comp.upper()}=1\n')
        confd = p.home / '.config' / shell / 'conf.d'
        confd.mkdir(parents=True, exist_ok=True)
        (confd / f'{comp}.sh').symlink_to(f)
    # a non-guard file under the old shell/ dir (e.g. hand-made) is not ours to move
    (cap / 'shell' / 'bash' / 'handmade.sh').write_text('echo mine\n')

    notes = shellguard.migrate_legacy(p, Runner(pretend=False))
    assert len(notes) == 4, notes
    # staged moved to state, ext per shell
    assert sorted((c, s) for c, s, _ in shellguard.list_staged(p)) == [('nvm', 'bash'), ('nvm', 'zsh')]
    assert (p.state_dir / 'staged-glue' / 'zsh' / 'nvm.zsh').read_text().endswith('export NVM_Z=x\n')
    assert not (cap / 'staged-glue').exists()
    # activated converted to user glue, old links + files gone
    confd_b = p.home / '.config' / 'bash' / 'conf.d'
    confd_z = p.home / '.config' / 'zsh' / 'conf.d'
    assert not (confd_b / 'sdkman.sh').is_symlink() and not (confd_z / 'rustup.sh').is_symlink()
    assert 'export SDKMAN=1' in (confd_b / '90-sdkman.sh').read_text()
    assert 'export RUSTUP=1' in (confd_z / '90-rustup.zsh').read_text()
    assert not (cap / 'shell' / 'bash' / 'sdkman.sh').exists()
    assert (cap / 'shell' / 'bash' / 'handmade.sh').read_text() == 'echo mine\n'
    assert shellguard.migrate_legacy(p, Runner(pretend=False)) == []    # one-time: idempotent
