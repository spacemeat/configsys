'''System Updates lane (docs/system-update-coverage-plan.md, P0): each manager's upgradable_index /
held_keys / upgrade_all, and sysupdates.gather aggregating upgradable − managed picks across
apt + flatpak + snap. Fake runner returns canned manager output.'''

from configsys import sysupdates
from configsys.componentObj import ResolvedComponent
from configsys.driver import tier_by_name
from configsys.drivers.apt import Apt
from configsys.drivers.flatpak import Flatpak
from configsys.drivers.snap import Snap
from configsys.runner import Result


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


def test_gather_excludes_managed_picks_across_managers():
    # a picked apt package (vim) and a picked flatpak app (Chrome) drop out of the update lane —
    # they show in their own pick rows, not here. Chrome is excluded by app id despite the ref key.
    units = {
        'apt\\vim': ResolvedComponent(key='apt\\vim', driver='apt', comp='vim',
                                      fields={'name': 'vim'}),
        'flatpak\\chrome': ResolvedComponent(key='flatpak\\chrome', driver='flatpak', comp='chrome',
                                             fields={'name': 'com.google.Chrome', 'hub': 'flathub'}),
    }
    groups = sysupdates.gather(_Ctx(_full_runner(), units=units, requested=['vim', 'chrome']))
    assert {r.key for r in groups['apt']} == {'htop'}                       # vim excluded
    assert {r.key for r in groups['flatpak']} == {'org.freedesktop.Platform/x86_64/24.08'}  # chrome excluded
    assert {r.key for r in groups['snap']} == {'hello'}


def test_gather_omits_a_manager_with_nothing_upgradable():
    r = FakeRunner([('apt list --upgradable', 0, 'Listing...\n')])   # apt empty; flatpak/snap absent
    # flatpak/snap commands fall through to ok+empty -> upgradable_index returns {} (seen_ok) / {} -> omitted
    groups = sysupdates.gather(_Ctx(r))
    assert 'apt' not in groups
