'''System Updates lane (docs/done/system-update-coverage-plan.md, P0): each manager's upgradable_index /
held_keys / upgrade_all, and sysupdates.gather aggregating upgradable − managed picks across
apt + flatpak + snap. Fake runner returns canned manager output.'''

from configsys import sysupdates
from configsys.sysupdates import UpdateRow
from configsys.componentObj import ResolvedComponent
from configsys.driver import tier_by_name
from configsys.drivers.apt import Apt
from configsys.drivers.apk import Apk
from configsys.drivers.brew import Brew
from configsys.drivers.dnf import Dnf
from configsys.drivers.flatpak import Flatpak
from configsys.drivers.pacman import Pacman
from configsys.drivers.snap import Snap
from configsys.drivers.zypper import Zypper
from configsys.runner import Result
from configsys.tui import models as models_mod


class FakeRunner:
    '''Substring-matched canned responses, first match wins; unmatched -> ok + empty stdout.'''
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None, presudo=False):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


APT_UPGRADABLE = ('Listing...\n'
                  'vim/jammy-updates 2:8.2-1 amd64 [upgradable from: 2:8.1-1]\n'
                  'htop/jammy 3.2-1 amd64 [upgradable from: 3.0-1]\n')

FP_LIST = ('com.google.Chrome/x86_64/stable\t153-1\n'
           'org.freedesktop.Platform/x86_64/24.08\tfreedesktop-sdk-24.08.35\n')
FP_UPDATES = ('app/com.google.Chrome/x86_64/stable\t153-1\n'
              'runtime/org.freedesktop.Platform/x86_64/24.08\tfreedesktop-sdk-24.08.36\n')

SNAP_LIST = ('Name   Version  Rev  Publisher  Notes\n'
             'hello  2.10     36   canonical  -\n')
SNAP_REFRESH_LIST = ('Name   Version  Rev  Publisher  Notes\n'
                     'hello  2.11     38   canonical  -\n')


# -- apt ------------------------------------------------------------------

def test_apt_upgradable_index_parses_installed_and_candidate():
    r = FakeRunner([('apt list --upgradable', 0, APT_UPGRADABLE)])
    idx = Apt(r).upgradable_index()
    assert idx == {'vim': ('2:8.1-1', '2:8.2-1'), 'htop': ('3.0-1', '3.2-1')}


def test_apt_upgradable_index_none_on_failure():
    assert Apt(FakeRunner([('apt list --upgradable', 1, '')])).upgradable_index() is None


def test_tier_by_name_heuristic():
    assert tier_by_name('linux-image-generic') == 'kernel'
    assert tier_by_name('linux-headers-6.8') == 'kernel'
    assert tier_by_name('libc6') == 'core'
    assert tier_by_name('glibc') == 'core'
    assert tier_by_name('htop') == 'apps'
    assert tier_by_name('org.freedesktop.Platform/x86_64/24.08') == 'apps'  # id/arch/branch tolerated


APT_PRIORITY = ('linux-image-generic important\n'
                'libc6 required\n'
                'bash standard\n'
                'htop optional\n'
                'ripgrep extra\n')


def test_apt_classify_index_priority_and_kernel():
    r = FakeRunner([("dpkg-query -W -f='${Package} ${Priority}", 0, APT_PRIORITY)])
    tiers = Apt(r).classify_index(['linux-image-generic', 'libc6', 'bash', 'htop', 'ripgrep',
                                   'unheard-of'])
    assert tiers == {'linux-image-generic': 'kernel',  # kernel by name (beats its 'important' prio)
                     'libc6': 'core',                  # required
                     'bash': 'standard',               # standard
                     'htop': 'apps',                   # optional
                     'ripgrep': 'apps',                # extra
                     'unheard-of': 'apps'}             # not in the priority map -> name heuristic


def test_apt_held_keys_and_bulk_upgrade_shape():
    r = FakeRunner([('apt-mark showhold', 0, 'vim\nlibc6\n')])
    assert Apt(r).held_keys() == {'vim', 'libc6'}
    r2 = FakeRunner()
    Apt(r2).upgrade_all()
    assert r2.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a '
                        'apt-get upgrade --with-new-pkgs -y']


# -- flatpak --------------------------------------------------------------

def test_flatpak_upgradable_index_keys_by_ref_matching_installed():
    # remote-ls refs carry an app/runtime prefix; list refs don't — _norm_ref reconciles them so
    # each branch matches its OWN installed version (no bogus cross-branch downgrade).
    r = FakeRunner([('flatpak list', 0, FP_LIST),
                    ('remote-ls --user --updates', 0, FP_UPDATES)])  # --system falls through -> empty
    idx = Flatpak(r).upgradable_index()
    assert idx == {
        'com.google.Chrome/x86_64/stable': ('153-1', '153-1'),
        'org.freedesktop.Platform/x86_64/24.08': ('freedesktop-sdk-24.08.35',
                                                   'freedesktop-sdk-24.08.36'),
    }


def test_flatpak_update_dedup_key_extracts_app_id():
    d = Flatpak(FakeRunner())
    assert d.update_dedup_key('com.google.Chrome/x86_64/stable') == 'com.google.Chrome'
    assert d.update_dedup_key('org.freedesktop.Platform/x86_64/24.08') == 'org.freedesktop.Platform'


def test_flatpak_classify_index_runtime_vs_app():
    keys = ['org.freedesktop.Platform/x86_64/24.08',
            'org.freedesktop.Platform.GL.nvidia-580/x86_64/1.4',
            'org.freedesktop.Sdk/x86_64/25.08',
            'org.gnome.Platform/x86_64/50',
            'com.google.Chrome/x86_64/stable',
            'org.gnome.Calculator/x86_64/stable']
    tiers = Flatpak(FakeRunner()).classify_index(keys)
    assert tiers == {'org.freedesktop.Platform/x86_64/24.08': 'core',
                     'org.freedesktop.Platform.GL.nvidia-580/x86_64/1.4': 'core',
                     'org.freedesktop.Sdk/x86_64/25.08': 'core',
                     'org.gnome.Platform/x86_64/50': 'core',
                     'com.google.Chrome/x86_64/stable': 'apps',
                     'org.gnome.Calculator/x86_64/stable': 'apps'}


def test_flatpak_bulk_upgrade_shape():
    r = FakeRunner()
    Flatpak(r).upgrade_all()
    assert r.calls == ['flatpak update -y']


# -- snap -----------------------------------------------------------------

def test_snap_upgradable_index_pairs_available_with_installed():
    r = FakeRunner([('snap refresh --list', 0, SNAP_REFRESH_LIST), ('snap list', 0, SNAP_LIST)])
    assert Snap(r).upgradable_index() == {'hello': ('2.10', '2.11')}


def test_snap_upgradable_index_none_on_failure():
    assert Snap(FakeRunner([('snap refresh --list', 1, '')])).upgradable_index() is None


def test_snap_bulk_upgrade_shape():
    r = FakeRunner()
    Snap(r).upgrade_all()
    assert r.calls == ['sudo snap refresh']


# -- P3 managers: dnf / pacman / zypper / apk / brew ---------------------------

def test_dnf_upgradable_and_bulk():
    r = FakeRunner([('dnf -q check-update', 100,
                     '\nbash.x86_64  5.1.8-6.el9  baseos\nvim-minimal.x86_64  9.0-1.el9  appstream\n'),
                    ('rpm -qa', 0, 'bash 5.1.7\nvim-minimal 8.2\n')])
    assert Dnf(r).upgradable_index() == {'bash': ('5.1.7', '5.1.8-6.el9'),
                                         'vim-minimal': ('8.2', '9.0-1.el9')}
    # exit code other than 0/100 is a real failure -> None
    assert Dnf(FakeRunner([('dnf -q check-update', 1, '')])).upgradable_index() is None
    r2 = FakeRunner()
    Dnf(r2).upgrade_all()
    assert r2.calls == ['sudo dnf upgrade -y']


def test_pacman_upgradable_and_bulk():
    # no pacman-contrib (checkupdates -> 127): falls back to pacman -Qu on the last-synced DB
    r = FakeRunner([('checkupdates', 127, ''),
                    ('pacman -Qu', 0, 'linux 6.9.1-1 -> 6.9.2-1\nvim 9.1.0-1 -> 9.1.5-1\n')])
    assert Pacman(r).upgradable_index() == {'linux': ('6.9.1-1', '6.9.2-1'),
                                            'vim': ('9.1.0-1', '9.1.5-1')}
    # exit 1 with no output = nothing upgradable, NOT a failure
    assert Pacman(FakeRunner([('checkupdates', 127, ''), ('pacman -Qu', 1, '')])).upgradable_index() == {}
    r2 = FakeRunner()
    Pacman(r2).upgrade_all()
    assert r2.calls == ['sudo pacman -Syu --noconfirm']         # full upgrade — the only safe bulk


def test_zypper_upgradable_held_and_bulk():
    r = FakeRunner([('list-updates', 0,
                     'S | Repository | Name | Current Version | Available Version | Arch\n'
                     '--+--\nv | repo-oss | curl | 8.0.1-1 | 8.4.0-1 | x86_64\n')])
    assert Zypper(r).upgradable_index() == {'curl': ('8.0.1-1', '8.4.0-1')}
    held = FakeRunner([('zypper locks', 0, '# | Name | Type | Repository\n--+--\n1 | curl | package | (any)\n')])
    assert Zypper(held).held_keys() == {'curl'}
    r2 = FakeRunner()
    Zypper(r2).upgrade_all()
    assert r2.calls == ['sudo zypper --non-interactive update']


def test_apk_upgradable_and_bulk():
    r = FakeRunner([('apk list --upgradable', 0,
                     'busybox-1.36.1-r5 x86_64 {aports} (GPL) [upgradable from: busybox-1.36.1-r4]\n'
                     'musl-utils-1.2.4-r2 x86_64 {aports} (MIT) [upgradable from: musl-utils-1.2.4-r1]\n')])
    assert Apk(r).upgradable_index() == {'busybox': ('1.36.1-r4', '1.36.1-r5'),
                                         'musl-utils': ('1.2.4-r1', '1.2.4-r2')}   # hyphenated name preserved
    r2 = FakeRunner()
    Apk(r2).upgrade_all()
    assert r2.calls == ['sudo apk upgrade']


def test_brew_upgradable_held_and_bulk():
    r = FakeRunner([('brew outdated', 0, 'wget (1.21.3) < 1.21.4\ngit (2.42.0) < 2.43.0\n')])
    assert Brew(r).upgradable_index() == {'wget': ('1.21.3', '1.21.4'), 'git': ('2.42.0', '2.43.0')}
    assert Brew(FakeRunner([('brew list --pinned', 0, 'wget\nnode\n')])).held_keys() == {'wget', 'node'}
    r2 = FakeRunner()
    Brew(r2).upgrade_all()
    assert r2.calls == ['brew upgrade']                          # user-owned prefix; never sudo


def test_pacman_lists_live_via_checkupdates_and_says_when_it_cannot():
    d = Pacman(FakeRunner([('checkupdates', 0, 'vim 9.1.0-1 -> 9.1.5-1\n')]))
    assert d.upgradable_index() == {'vim': ('9.1.0-1', '9.1.5-1')}
    assert d.upgradable_advisory() is None                      # a live list: nothing to caveat
    d = Pacman(FakeRunner([('checkupdates', 2, '')]))           # checkupdates: exit 2 = none pending
    assert d.upgradable_index() == {} and d.upgradable_advisory() is None
    fr = FakeRunner([('checkupdates', 127, ''), ('pacman -Qu', 1, '')])
    d = Pacman(fr)
    assert d.upgradable_index() == {}
    assert 'pacman-contrib' in d.upgradable_advisory()          # stale list -> names the fix
    assert fr.calls == ['checkupdates', 'pacman -Qu']           # never touches the real sync DB
    d = Pacman(FakeRunner([('checkupdates', 1, ''), ('pacman -Qu', 1, '')]))
    d.upgradable_index()
    assert 'failed (exit 1)' in d.upgradable_advisory()


# -- gather (aggregation + managed-picks exclusion) -----------------------

class _Cascade:
    def native(self, block):
        return 'apt'


class _Routes:
    def __init__(self, units):
        self.cascade = _Cascade()
        self._units = units

    def resolve_resilient(self, names):
        return (self._units, {})


class _Config:
    def __init__(self, requested):
        self._requested = requested

    def requested(self):
        return self._requested


class _OS:
    block = 'pop_os!'


class _Ctx:
    def __init__(self, runner, units=None, requested=None):
        self.runner = runner
        self.paths = None
        self.routes = _Routes(units or {})
        self.config = _Config(requested or [])
        self.os_info = _OS()

    def prepare_units(self, units):
        pass


def _full_runner():
    return FakeRunner([('apt list --upgradable', 0, APT_UPGRADABLE),
                       ('apt-mark showhold', 0, 'vim\n'),           # vim is held
                       ("dpkg-query -W -f='${Package} ${Priority}", 0,
                        'vim important\nhtop optional\n'),          # vim -> core, htop -> apps
                       ('flatpak list', 0, FP_LIST),
                       ('remote-ls --user --updates', 0, FP_UPDATES),
                       ('snap refresh --list', 0, SNAP_REFRESH_LIST),
                       ('snap list', 0, SNAP_LIST)])


def test_gather_groups_all_managers_when_nothing_managed():
    groups = sysupdates.gather(_Ctx(_full_runner()))
    assert set(groups) == {'apt', 'flatpak', 'snap'}
    assert {r.key for r in groups['apt']} == {'vim', 'htop'}
    assert next(r for r in groups['apt'] if r.key == 'vim').held is True
    assert {r.key for r in groups['flatpak']} == {
        'com.google.Chrome/x86_64/stable', 'org.freedesktop.Platform/x86_64/24.08'}
    assert {r.key for r in groups['snap']} == {'hello'}
    # tiers: apt vim(important)->core, htop(optional)->apps; flatpak Platform->core, Chrome->apps
    tier = {r.key: r.tier for g in groups.values() for r in g}
    assert tier['vim'] == 'core' and tier['htop'] == 'apps'
    assert tier['org.freedesktop.Platform/x86_64/24.08'] == 'core'
    assert tier['com.google.Chrome/x86_64/stable'] == 'apps'
    assert tier['hello'] == 'apps'                    # snap: name heuristic (no tier notion)


def test_gather_excludes_managed_keys_across_managers(monkeypatch):
    # anything a component covers drops out of the update lane, keyed by (driver, package_key) — and
    # a flatpak app is matched by its app id even though the upgradable key is a full ref. (managed_keys
    # itself is built from the reverse index; here we stub it to test gather's exclusion in isolation.)
    monkeypatch.setattr(sysupdates, 'managed_keys',
                        lambda ctx: {('apt', 'vim'), ('flatpak', 'com.google.Chrome')})
    groups = sysupdates.gather(_Ctx(_full_runner()))
    assert {r.key for r in groups['apt']} == {'htop'}                       # vim excluded
    assert {r.key for r in groups['flatpak']} == {'org.freedesktop.Platform/x86_64/24.08'}  # chrome excluded
    assert {r.key for r in groups['snap']} == {'hello'}


def test_gather_collects_advisories_even_when_a_manager_lists_nothing():
    ctx = _Ctx(FakeRunner([('checkupdates', 127, ''), ('pacman -Qu', 1, '')]))
    ctx.routes.cascade.native = lambda block: 'pacman'
    notes = []
    groups = sysupdates.gather(ctx, notes)
    assert 'pacman' not in groups
    assert len(notes) == 1 and notes[0].startswith('pacman: ') and 'pacman-contrib' in notes[0]


def test_gather_omits_a_manager_with_nothing_upgradable():
    r = FakeRunner([('apt list --upgradable', 0, 'Listing...\n')])   # apt empty; flatpak/snap absent
    # flatpak/snap commands fall through to ok+empty -> upgradable_index returns {} (seen_ok) / {} -> omitted
    groups = sysupdates.gather(_Ctx(r))
    assert 'apt' not in groups


# -- TUI (P2): the synthetic Components-tree injection ------------------------

def _groups():
    return {'apt': [UpdateRow('apt', 'linux-image-generic', '7.0', '7.1', False, 'kernel'),
                    UpdateRow('apt', 'coreutils', '8.32-1', '8.32-2', False, 'core'),
                    UpdateRow('apt', 'htop', '3.0', '3.2', True, 'apps')],
            'flatpak': [UpdateRow('flatpak', 'org.gnome.Platform/x86_64/50', 'a', 'b', False, 'core')]}


def test_tree_injection_builds_group_and_tiers():
    states, layouts, transitive = sysupdates.tree_injection(_groups())
    assert len(states) == 4
    assert all(k.startswith('sysupd\\') for k in states)          # namespaced, no real-unit collision
    assert all(sysupdates.is_synthetic(s) for s in states.values())
    (name, items), = layouts                                      # one 'System Updates' group
    assert name == sysupdates.SYSTEM_UPDATES_GROUP
    # tiers present, in kernel/core/standard/apps order, standard omitted (empty)
    assert items == [('component', 'kernel'), ('component', 'core'), ('component', 'apps')]
    assert transitive[name] == ['kernel', 'core', 'apps']


def test_tree_injection_empty_when_no_updates():
    assert sysupdates.tree_injection({}) == ({}, [], {})


def test_auto_dep_rows_dim_only_in_standard_and_apps():
    from configsys.tui import menu
    from configsys.tui.screens.components import _su_dim
    groups = {'apt': [UpdateRow('apt', 'myapp', '1', '2', False, 'apps', True),      # user-chosen app
                      UpdateRow('apt', 'libdep', '1', '2', False, 'apps', False),    # auto dep, apps
                      UpdateRow('apt', 'coreutils', '1', '2', False, 'core', False), # auto dep, core
                      UpdateRow('apt', 'libc6', '1', '2', False, 'core', False),     # (2nd core -> group)
                      UpdateRow('apt', 'stddep', '1', '2', False, 'standard', False),
                      UpdateRow('apt', 'stdtool', '1', '2', False, 'standard', True)]}  # (2nd standard)
    states, layouts, transitive = sysupdates.tree_injection(groups)
    ms = menu.MenuState(states, layouts, transitive)
    for n in ms._all_nodes():
        if n.expandable:
            n.expanded = True
    ms._refresh()
    dim = {n.label: _su_dim(n) for n in ms.rows if n.kind == 'unit'}
    assert dim['myapp'] is False        # user-installed -> prominent
    assert dim['libdep'] is True        # auto dep in apps -> dimmed
    assert dim['stddep'] is True        # auto dep in standard -> dimmed
    assert dim['coreutils'] is False    # core is never dimmed (stays prominent)


def test_synthetic_rows_render_and_never_stage():
    from configsys.tui import menu
    from configsys.tui.screens.components import _cursor_in_sysupd
    states, layouts, transitive = sysupdates.tree_injection(_groups())
    ms = menu.MenuState(states, layouts, transitive)
    for n in ms._all_nodes():                                     # expand everything
        if n.expandable:
            n.expanded = True
    ms._refresh()
    labels = [n.label for n in ms.rows]
    assert 'System Updates' in labels and 'kernel' in labels and 'core' in labels
    # System Updates rows keep the FULL version (the change is in the revision clean_version strips)
    cu = next(n for n in ms.rows if n.label == 'coreutils')
    assert cu.installed_str() == '8.32-1' and cu.latest_str() == '8.32-2'
    # bulk-action: a NORMAL bulk stage_all must never stage a synthetic row
    assert ms.stage_all('upgrade') == 0 and not ms.staged
    # ...but the explicit System Updates mark stages every synthetic row at once (all-or-nothing)
    assert ms.stage_system_updates() == 4
    assert all(op == 'upgrade' for op in ms.staged.values()) and len(ms.staged) == 4
    # the cursor-in-subtree predicate fires for the group, a tier, and a leaf, not outside it
    su = next(i for i, n in enumerate(ms.rows) if n.label == 'System Updates')
    ms.cursor = su
    assert _cursor_in_sysupd(ms)
    ms.cursor = next(i for i, n in enumerate(ms.rows) if n.label == 'coreutils')
    assert _cursor_in_sysupd(ms)


def test_fold_rebuilds_the_tree_without_the_pipeline(monkeypatch):
    # the scan lands on the UI thread: folding it in must NOT re-run the load pipeline + diagnostics
    # (~6s — the freeze after the splash); only the tree is rebuilt from the states already held.
    # A rescan replaces the previous scan's synthetic rows rather than stacking them.
    import types
    from configsys.tui import menu

    def model(ctx, cfg, states, mode, caches=None):       # _components_model's System Updates fold
        su_states, su_layouts, su_transitive = sysupdates.tree_injection(ctx._sysupd_groups or {})
        return {**states, **su_states}, list(su_layouts), dict(su_transitive)
    monkeypatch.setattr(models_mod, '_components_model', model)
    ctx = types.SimpleNamespace(_sysupd_groups=_groups())    # no load_pipeline: calling it would fail
    ms = menu.MenuState({}, [], {})
    ms.descriptions = {}
    ms, states = menu._fold_system_updates(ctx, None, ms)
    assert sum(sysupdates.is_synthetic(s) for s in states.values()) == 4
    ctx._sysupd_groups = {'apt': _groups()['apt'][:1]}       # a later, smaller scan
    ms, states = menu._fold_system_updates(ctx, None, ms)
    assert sum(sysupdates.is_synthetic(s) for s in states.values()) == 1


# -- the ONE apply step both surfaces run (review-2026-11-2 actions-14 / subsystems-13 / actions-24 / -34)

class _BulkDriver:
    '''A manager whose upgrade_all answers `res` (a Result, None = no bulk command, or an exception
    class to raise); `warm` simulates a sudo'd bulk command warming the runner's credential.'''
    def __init__(self, name, res, runner=None, warm=False):
        self.name, self.res, self.runner, self.warm = name, res, runner, warm

    def upgrade_all(self):
        if self.warm:
            self.runner._ensure_sudo()
        if isinstance(self.res, type) and issubclass(self.res, BaseException):
            raise self.res()
        return self.res


def _bulk_ctx(tmp_path, runner):
    from configsys.paths import Paths
    import types
    return types.SimpleNamespace(
        runner=runner, config=None, routes=_Routes({}), os_info=_OS(),
        paths=Paths(env={'HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')}))


def _stub_managers(monkeypatch, answers, runner=None, warm=False):
    monkeypatch.setattr(sysupdates, 'get_driver', lambda name, r, p: (
        _BulkDriver(name, answers[name], runner, warm) if name in answers else None))


def _bulk_answers():
    return {'apt': Result('apt-get upgrade -y', 100, stderr='E: dpkg was interrupted'), 'snap': None}


def _cli_run(monkeypatch, ctx, groups):
    import types
    from configsys.cli import ops
    monkeypatch.setattr(ops, 'refresh_native_index', lambda c: (False, True))
    monkeypatch.setattr(sysupdates, 'gather', lambda c, notes=None: groups)
    monkeypatch.setattr(ops, '_offer_report', lambda c, f, fatal=None: None)
    return ops.cmd_upgrade_system(ctx, types.SimpleNamespace(yes=True))


def _tui_run(monkeypatch, ctx, managers, also=()):
    '''Drive the TUI execute flow with one System Updates row per manager staged, plus `also`
    component units (their per-unit plan is recorded in `ran`, never run).'''
    import builtins
    import contextlib
    import types
    from configsys.cli import refresh as cli_refresh
    from configsys.ledger import Ledger
    from configsys.tui import flows as flows_mod
    states = {}
    for m in managers:
        rc = ResolvedComponent(key=f'sysupd\\{m}\\pkg', driver=m, comp='pkg',
                               fields={'name': 'pkg', 'system_update': True})
        states[rc.key] = types.SimpleNamespace(component=rc, present=True)
    for name in also:
        rc = ResolvedComponent(key=f'apt\\{name}', driver='apt', comp=name, fields={'name': name})
        states[rc.key] = types.SimpleNamespace(component=rc, present=True)
    from configsys import actions
    monkeypatch.setattr(actions, 'build_plan', lambda c, raw, units, states=None: (raw, units, []))
    ms = types.SimpleNamespace(plan=lambda: [('upgrade', k, s.component) for k, s in states.items()],
                               states=states)
    monkeypatch.setattr(flows_mod, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: 'y')
    tty = types.SimpleNamespace(isatty=lambda: True)    # the TUI's own terminal (cli.common.ask checks it)
    monkeypatch.setattr('configsys.cli.common.sys', types.SimpleNamespace(stdin=tty, stdout=tty))
    monkeypatch.setattr(cli_refresh, 'maybe_refresh_before_plan', lambda c, plan, system=False: set())
    monkeypatch.setattr(cli_refresh, 'published_pending', lambda c, fresh: [])
    monkeypatch.setattr(sysupdates, 'gather', lambda c, notes=None: {})   # the pre-confirm recount
    ran = []
    monkeypatch.setattr(flows_mod, 'execute_plan', lambda *a, **k: ran.append(a) or [])
    _ok, _note, outcomes = flows_mod._confirm_and_execute(None, None, ms, ctx, Ledger())
    return outcomes, ran


def _records(ctx):
    from configsys import reportgen
    return sorted((f['unit'], f['exit']) for f in reportgen.load_failures(ctx.paths))


def test_apply_bulk_gives_both_surfaces_the_same_outcomes_and_records(monkeypatch, tmp_path, capsys):
    from configsys.runner import Runner
    _stub_managers(monkeypatch, _bulk_answers())
    res = sysupdates.apply_bulk(_bulk_ctx(tmp_path / 'direct', Runner()), ['apt', 'snap'], refresh=False)
    assert [(o.key, o.ok, o.advisory) for o in res.outcomes] == [
        ('system-updates\\apt', False, False), ('system-updates\\snap', False, True)]
    assert res.rc_code == 100 and res.n_fatal == 1 and not res.interrupted
    assert 'no bulk-upgrade command' in res.outcomes[1].detail

    cli_ctx = _bulk_ctx(tmp_path / 'cli', Runner())
    groups = {m: [UpdateRow(m, 'pkg', '1', '2', False)] for m in ('apt', 'snap')}
    assert _cli_run(monkeypatch, cli_ctx, groups) == 100
    out = capsys.readouterr().out
    assert 'apt upgrade FAILED (exit 100)' in out and '(snap has no bulk-upgrade command — skipped)' in out

    tui_ctx = _bulk_ctx(tmp_path / 'tui', Runner())
    outcomes, _ran = _tui_run(monkeypatch, tui_ctx, ['apt', 'snap'])
    assert [(o.key, o.ok, o.advisory, o.detail) for o in outcomes] == \
        [(o.key, o.ok, o.advisory, o.detail) for o in res.outcomes]
    assert _records(cli_ctx) == _records(tui_ctx) == [('system-updates\\apt', '100')]


def test_apply_bulk_records_nothing_under_pretend(monkeypatch, tmp_path):
    from configsys.runner import Runner
    _stub_managers(monkeypatch, _bulk_answers())
    ctx = _bulk_ctx(tmp_path, Runner(pretend=True))
    sysupdates.apply_bulk(ctx, ['apt'], refresh=False)
    assert not ctx.paths.failure_file.exists()


def test_apply_bulk_ctrl_c_stops_the_batch(monkeypatch, tmp_path):
    from configsys.runner import Runner
    _stub_managers(monkeypatch, {'apt': KeyboardInterrupt, 'snap': Result('snap refresh', 0)})
    ctx = _bulk_ctx(tmp_path, Runner())
    res = sysupdates.apply_bulk(ctx, ['apt', 'snap'], refresh=False, on_line=lambda m: None)
    assert res.interrupted and res.rc_code == 130
    assert [o.key for o in res.outcomes] == ['system-updates\\apt']        # snap never ran
    # …and the TUI doesn't go on to the component ops after a ^C'd bulk upgrade
    outcomes, ran = _tui_run(monkeypatch, _bulk_ctx(tmp_path / 't', Runner()), ['apt'], also=['btop'])
    assert ran == [] and [o.detail for o in outcomes] == ['interrupted (^C)']


def test_apply_bulk_starts_no_scan(monkeypatch, tmp_path):
    from configsys.runner import Runner
    _stub_managers(monkeypatch, {'apt': Result('apt-get upgrade -y', 0)})
    monkeypatch.setattr(sysupdates, 'start_scan', lambda c: (_ for _ in ()).throw(AssertionError('scan')))
    ctx = _bulk_ctx(tmp_path, Runner())
    ctx._sysupd_groups = {'apt': []}
    sysupdates.apply_bulk(ctx, ['apt'], refresh=False)
    assert ctx._sysupd_groups is None                     # invalidated — the caller rescans


def test_a_system_updates_only_apply_releases_the_sudo_keepalive(monkeypatch, tmp_path):
    import configsys.runner as runner_mod
    from configsys.runner import Runner

    class _Keepalive:
        def stop(self):
            pass
    monkeypatch.setattr(runner_mod, '_sudo_preauth', lambda: True)
    monkeypatch.setattr(runner_mod, '_SudoKeepalive', _Keepalive)
    r = Runner()
    _stub_managers(monkeypatch, {'apt': Result('apt-get upgrade -y', 0)}, runner=r, warm=True)
    outcomes, ran = _tui_run(monkeypatch, _bulk_ctx(tmp_path, r), ['apt'])
    assert [o.ok for o in outcomes] == [True] and ran == []        # no component plan: run_plan never ran
    assert r._keepalive is None and r._sudo_warm is False
    # the CLI's `upgrade --system` too
    _cli_run(monkeypatch, _bulk_ctx(tmp_path / 'c', r), {'apt': [UpdateRow('apt', 'pkg', '1', '2', False)]})
    assert r._keepalive is None and r._sudo_warm is False


def test_start_scan_is_a_no_op_under_pretend(monkeypatch):
    from configsys.runner import Runner
    r = Runner(pretend=True)
    ctx = _Ctx(r)
    ctx._sysupd_groups = None
    sysupdates.start_scan(ctx)
    assert r.calls == [] and ctx._sysupd_groups == {}
    assert getattr(ctx, '_sysupd_thread', None) is None


def test_a_scan_that_raises_leaves_a_note(monkeypatch):
    def boom(ctx, notes=None):
        raise RuntimeError('dpkg lock')
    monkeypatch.setattr(sysupdates, 'gather', boom)
    ctx = _Ctx(FakeRunner())
    ctx.runner.pretend = False
    sysupdates.start_scan(ctx)
    ctx._sysupd_thread.join(2)
    assert ctx._sysupd_groups == {} and ctx._sysupd_notes == ['system-updates: scan failed: dpkg lock']


def test_the_native_manager_failing_to_list_is_a_note():
    notes = []
    groups = sysupdates.gather(_Ctx(FakeRunner([('apt list --upgradable', 1, '')])), notes)
    assert 'apt' not in groups and 'apt: could not list upgradable packages' in notes
    # an absent app manager answering None is not a note
    assert not any(n.startswith(('flatpak', 'snap')) for n in notes)


def test_flatpak_rows_carry_their_installation():
    r = FakeRunner([('flatpak list', 0, FP_LIST),
                    ('remote-ls --user --updates', 0, 'app/com.google.Chrome/x86_64/stable\t153-1\n'),
                    ('remote-ls --system --updates', 0,
                     'runtime/org.freedesktop.Platform/x86_64/24.08\tfreedesktop-sdk-24.08.36\n')])
    rows = {row.key: row for row in sysupdates.gather(_Ctx(r))['flatpak']}
    assert rows['com.google.Chrome/x86_64/stable'].scope == 'user'
    assert rows['org.freedesktop.Platform/x86_64/24.08'].scope == 'system'
    st = sysupdates._synthetic_state(rows['org.freedesktop.Platform/x86_64/24.08'])
    assert st.scope == 'system'


def test_upgrade_system_refuses_component_names_and_picks(capsys):
    '''`--system` is the whole-system lane; names or --picks beside it are refused, never ignored.'''
    import argparse
    from configsys.cli import ops
    for extra in ({'names': ['ripgrep'], 'picks': False}, {'names': [], 'picks': True}):
        args = argparse.Namespace(system=True, yes=False, **extra)
        assert ops.cmd_upgrade(None, args) == 1
        assert '--system' in capsys.readouterr().out

