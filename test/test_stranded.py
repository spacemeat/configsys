'''stranded.py — installs routes no longer offer here (switch), and picks with no method left
(unmet / dangling). Offline: a fake probe cache stands in for the drivers' installed state.'''

import os
from types import SimpleNamespace

import pytest

from configsys import stranded
from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.ledger import Ledger
from configsys.paths import Paths
from configsys.routes import Resolver
from configsys.runner import Runner

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')

PLUGIN = '''{ components: {
    lw:      { description: "x"  install: [ { via: native  when: "arch" }
                                            { via: flatpak  hub: flathub  app: org.lw.App } ] }
    renamed: { description: "x"  install: [ { via: aur  when: "arch"  name: renamed } ] }
    gatedapp: { description: "x"  install: [
        { via: flatpak  hub: flathub  app: org.gated.App }
        { via: appImage  cpu-names: { x86_64: x86_64 }  name: Gated  scope: user
          version: { github: a/gated  asset: "gated-$ARCH.AppImage" }  path: ~/apps/gated.appimage } ] }
    fponly:  { description: "x"  install: [ { via: flatpak  hub: flathub  app: org.fp.App } ] }
    fedonly: { description: "x"  install: [ { via: native  when: "fedora" } ] }
    asc:     { description: "x"  install: [ { via: native  when: "arch" } ] }
    go:      { description: "x"  install: [ { via: native  when: "arch" } ] }
    ghlike:  { description: "x"  install: [ { via: native }
                                            { via: native-pkg-file  when: "rhel"  version: { github: a/gh }  asset: { rpm: { x86_64: "gh_*.rpm" } } } ] }
    needsfp: { description: "x"  requires: fponly  install: [ { via: native  when: "arch" } ] }
} }'''


class FakeCache:
    '''{(driver, package_name): version} — what's "installed".'''
    def __init__(self, installed):
        self.installed = installed

    def version(self, drv, rc):
        return self.installed.get((rc.driver, rc.name))


@pytest.fixture
def plugin(tmp_path):
    p = tmp_path / 'stranded.hu'
    p.write_text(PLUGIN)
    return str(p)


def ctx_for(plugin, block='arch', version='20260101', cpu='x86_64', disabled=()):
    r = Resolver(ROUTES, block, version, cpu, plugin_files=[plugin], disabled=disabled)
    return SimpleNamespace(routes=r, runner=Runner(pretend=True), paths=None)


def receipt(ledger, key, name, via, **fields):
    ledger.set_receipt(ResolvedComponent(key=key, driver=key.split('\\')[0], comp=key.split('\\')[1],
                                         via=via, fields={'name': name, **fields}))


# -- receipts ---------------------------------------------------------------

def test_receipt_roundtrips_through_the_ledger_file(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    led = Ledger()
    receipt(led, 'appImage\\gatedapp', 'Gated', 'appImage', path='~/apps/gated.appimage',
            version={'github': 'a/gated', 'asset': 'gated-x86_64.AppImage'})
    led.set_lock('apt\\jq', True)
    led.save(paths)
    back = Ledger.load(paths)
    rec = back.receipt('appImage\\gatedapp')
    assert rec['via'] == 'appImage' and rec['name'] == 'Gated'
    assert rec['fields']['version']['asset'] == 'gated-x86_64.AppImage'
    assert back.is_locked('apt\\jq') and back.receipt('apt\\jq') is None
    assert list(back.receipts_for('gatedapp')) == ['appImage\\gatedapp']
    back.clear_receipt('appImage\\gatedapp')
    assert back.receipts_for('gatedapp') == {}


def test_config_drivers_get_no_receipt():
    led = Ledger()
    receipt(led, 'dotfiles\\x-dotfiles', 'x-dotfiles', 'dotfiles')
    assert led.receipts_for('x-dotfiles') == {}


def test_run_plan_writes_and_clears_receipts(monkeypatch):
    from configsys import actions
    from configsys.runner import Result

    class Drv:
        name = 'flatpak'
        privileged = False
        def sudo(self, rc): return False
        def install(self, rc): return Result('i', 0, '', '')
        def uninstall(self, rc): return Result('u', 0, '', '')
        def get_version(self, rc): return '1.0'

    monkeypatch.setattr('configsys.drivers.get_driver', lambda *a, **k: Drv())
    monkeypatch.setattr('configsys.shellguard.arm', lambda *a, **k: None)
    monkeypatch.setattr('configsys.shellguard.finish', lambda *a, **k: None)
    runner = SimpleNamespace(pretend=False, end_sudo=lambda: None)
    ctx = SimpleNamespace(runner=runner, paths=SimpleNamespace(state_dir=None), config=None)
    led = Ledger()
    led.save = lambda paths: None
    rc = ResolvedComponent(key='flatpak\\fp', driver='flatpak', comp='fp', via='flatpak',
                           fields={'name': 'org.fp.App', 'hub': 'flathub'})
    actions.run_plan(ctx, [('install', rc.key, rc)], ledger=led, on_line=lambda *_: None)
    assert led.receipt('flatpak\\fp')['fields'] == {'hub': 'flathub'}
    actions.run_plan(ctx, [('remove', rc.key, rc)], ledger=led, on_line=lambda *_: None)
    assert led.receipt('flatpak\\fp') is None


# -- find ------------------------------------------------------------------

def test_receipt_for_a_removed_binding_is_stranded(plugin):
    # lw was installed from the AUR as lw-bin; routes now only offer pacman + flatpak
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'aur\\lw', 'lw-bin', 'aur')
    found = stranded.find(ctx, 'lw', ledger=led, cache=FakeCache({('aur', 'lw-bin'): '2.0'}))
    assert [(s.key, s.rc.name, s.reason) for s in found] == [('aur\\lw', 'lw-bin', 'removed')]


def test_receipt_for_the_current_method_is_not_stranded(plugin):
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'pacman\\lw', 'lw', 'native')
    assert stranded.find(ctx, 'lw', ledger=led, cache=FakeCache({('pacman', 'lw'): '1'})) == []


def test_stale_receipt_with_nothing_on_disk_is_ignored(plugin):
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'aur\\lw', 'lw-bin', 'aur')
    assert stranded.find(ctx, 'lw', ledger=led, cache=FakeCache({})) == []


def test_same_key_but_renamed_package_is_removed(plugin):
    # the AUR binding still exists but now names `renamed`; the receipt's renamed-bin is stranded
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'aur\\renamed', 'renamed-bin', 'aur')
    found = stranded.find(ctx, 'renamed', ledger=led, cache=FakeCache({('aur', 'renamed-bin'): '1'}))
    assert [(s.rc.name, s.reason) for s in found] == [('renamed-bin', 'removed')]


def test_binding_gated_out_here_is_stranded(plugin):
    # the x86-only AppImage on an aarch64 machine — still in routes, no longer valid here
    ctx = ctx_for(plugin, cpu='aarch64')
    found = stranded.find(ctx, 'gatedapp', ledger=Ledger(),
                          cache=FakeCache({('appImage', 'Gated'): '3.1'}))
    assert [(s.key, s.reason) for s in found] == [('appImage\\gatedapp', 'gated')]
    # on x86_64 it IS a candidate -> nothing stranded
    assert stranded.find(ctx_for(plugin), 'gatedapp', ledger=Ledger(),
                         cache=FakeCache({('appImage', 'Gated'): '3.1'})) == []


def test_installed_via_a_disabled_driver_is_stranded(plugin):
    ctx = ctx_for(plugin, disabled=('flatpak',))
    found = stranded.find(ctx, 'lw', ledger=Ledger(), cache=FakeCache({('flatpak', 'org.lw.App'): '1'}))
    assert [(s.key, s.reason) for s in found] == [('flatpak\\lw', 'disabled')]


def test_aur_heuristic_variants_only(plugin):
    ctx, led = ctx_for(plugin), Ledger()
    found = stranded.find(ctx, 'lw', ledger=led, cache=FakeCache({}), foreign={'lw-bin': '2.0'})
    assert [(s.rc.name, s.reason) for s in found] == [('lw-bin', 'removed')]
    # `go` must not claim an unrelated `go-task-bin`
    assert stranded.find(ctx, 'go', ledger=led, cache=FakeCache({}), foreign={'go-task-bin': '3'}) == []
    # a receipt already explains the package -> no duplicate from the heuristic
    receipt(led, 'aur\\lw', 'lw-bin', 'aur')
    found = stranded.find(ctx, 'lw', ledger=led, cache=FakeCache({('aur', 'lw-bin'): '2.0'}),
                          foreign={'lw-bin': '2.0'})
    assert len(found) == 1


def test_same_name_promotion_is_not_stranded(plugin):
    # AUR asc -> [extra] asc: the current pacman binding names the same package; pacman -Syu heals it
    ctx = ctx_for(plugin)
    assert stranded.find(ctx, 'asc', ledger=Ledger(), cache=FakeCache({}), foreign={'asc': '1.1'}) == []


# -- classification + state ---------------------------------------------------

def test_classify_unmet_vs_dangling(plugin):
    on_arch = ctx_for(plugin, disabled=('flatpak',))
    assert stranded.classify_unroutable(on_arch, ['fponly', 'fedonly', 'lw']) == {
        'fponly': ('unmet', 'only installable via disabled driver(s): flatpak'),
        'fedonly': ('dangling', 'no install method on this OS any more'),
    }                                            # lw still has a method (pacman) -> not classified
    # its own method is fine, but its requires-closure needs the disabled driver -> unmet, not error
    assert stranded.classify_unroutable(on_arch, ['needsfp']) == {
        'needsfp': ('unmet', 'a dependency needs a disabled driver (flatpak)')}
    # with nothing disabled, a routable name is never classified
    assert stranded.classify_unroutable(ctx_for(plugin), ['needsfp', 'lw']) == {}


def test_status_precedence():
    rc = ResolvedComponent(key='pacman\\lw', driver='pacman', comp='lw')
    st = ComponentState(component=rc, supported=True, present=True, installed_version='1',
                        latest_version='2', locked=False, lock_source=None, managed=False, error=None)
    assert st.status == 'outdated'
    st.route_status = 'switch'
    assert st.status == 'switch'                 # routing state outranks version state
    st.error = 'boom'
    assert st.status == 'error'


def test_augment_marks_switch_and_feeds_the_swap_offer(plugin, monkeypatch):
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'aur\\lw', 'lw-bin', 'aur')
    monkeypatch.setattr(stranded, 'foreign_index', lambda *a, **k: None)
    rc = ResolvedComponent(key='pacman\\lw', driver='pacman', comp='lw', via='native',
                           requested_as={'lw'})
    st = ComponentState(component=rc, supported=True, present=False, installed_version=None,
                        latest_version='2', locked=False, lock_source=None, managed=False, error=None)
    states = {rc.key: st}
    stranded.augment(ctx, states, led, cache=FakeCache({('aur', 'lw-bin'): '2.0'}))
    assert st.status == 'switch' and st.also_present == (('aur', 'lw-bin', '2.0'),)
    # a reload after the swap ran: nothing stranded any more -> the verdict is dropped, not kept
    stranded.augment(ctx, states, led, cache=FakeCache({}))
    assert st.route_status is None and st.also_present == () and st.status == 'missing'


def test_unroutable_rows_carry_the_stranded_install(plugin, monkeypatch):
    ctx, led = ctx_for(plugin), Ledger()
    receipt(led, 'dnf\\fedonly', 'fedonly', 'native')   # say it came over from a Fedora box config
    monkeypatch.setattr(stranded, 'foreign_index', lambda *a, **k: None)
    rows = stranded.unroutable_states(ctx, {'fedonly': ('dangling', 'no install method on this OS any more'),
                                            'fponly': ('unmet', 'only via flatpak')},
                                      led, cache=FakeCache({('dnf', 'fedonly'): '5'}))
    fed = rows['dnf\\fedonly']
    assert fed.present and fed.status == 'dangling' and fed.component.requested_as == {'fedonly'}
    fp = rows['—\\fponly']
    assert not fp.present and fp.status == 'unmet'
    texts = [t for _l, _t, t in stranded.diagnostics(rows)]
    assert any('still installed via native (fedonly 5); left in place' in t for t in texts)


def test_superseded_installs_includes_stranded(plugin, monkeypatch, tmp_path):
    from configsys import installState
    ctx = ctx_for(plugin)
    ctx.paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    old = ResolvedComponent(key='aur\\lw', driver='aur', comp='lw', via='aur', fields={'name': 'lw-bin'})
    monkeypatch.setattr(stranded, 'find', lambda *a, **k: [stranded.Stranded(old, old.key, '2.0', 'removed')])
    monkeypatch.setattr(stranded, 'foreign_index', lambda *a, **k: None)
    target = ResolvedComponent(key='pacman\\lw', driver='pacman', comp='lw', via='native')
    got = installState.superseded_installs(ctx, target)
    assert ('aur\\lw', '2.0') in [(rc.key, v) for rc, v in got]


def test_same_package_in_the_os_database_is_not_stranded(plugin):
    # gh's EL-only native-pkg-file binding, gated out on Ubuntu, probes dpkg for `gh` — and finds the
    # apt-installed gh. Same package, same database: that's the current install, not a stranded one.
    ctx = ctx_for(plugin, block='ubuntu', version='24.04')
    installed = FakeCache({('apt', 'ghlike'): '2.4', ('native-pkg-file', 'ghlike'): '2.4'})
    assert stranded.find(ctx, 'ghlike', ledger=Ledger(), cache=installed) == []
    led = Ledger()                               # ...and the same holds for a receipt of the .rpm/.deb
    receipt(led, 'native-pkg-file\\ghlike', 'ghlike', 'native-pkg-file')
    assert stranded.find(ctx, 'ghlike', ledger=led, cache=installed) == []


def test_tui_staging_rules_for_route_statuses():
    from configsys.tui.menu import OPS
    rc = ResolvedComponent(key='apt\\btop', driver='apt', comp='btop')

    def st(present, route_status):
        return ComponentState(component=rc, supported=True, present=present, installed_version='1' if present else None,
                              latest_version='1', locked=False, lock_source=None, managed=False, error=None,
                              route_status=route_status)
    install, remove = OPS['install'][2], OPS['remove'][2]
    assert install(st(False, None)) and not install(st(True, None))   # unchanged: install = absent
    assert install(st(True, 'switch'))           # installed + stranded: `i` stages the swap
    assert not install(st(False, 'dangling')) and not install(st(False, 'unmet'))   # no method
    assert remove(st(True, 'dangling'))          # a dangling row's stranded install is removable
