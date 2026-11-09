from types import SimpleNamespace

from configsys import app
from configsys.cli import refresh
from configsys.runner import Result

JLIST = '/etc/apt/sources.list.d/jenkins.list'
CODELIST = '/etc/apt/sources.list.d/code.list'


def _ctx(owned, runner=None):
    '''owned: {component: source-path}. Builds routes.components so _owned_index_sources maps
    each source-path back to its component.'''
    comps = {}
    for comp, path in owned.items():
        comps[comp] = SimpleNamespace(bindings=[SimpleNamespace(details={'source-path': path})])
    return SimpleNamespace(routes=SimpleNamespace(components=comps), runner=runner)


def test_orphan_detection_component_not_wanted():
    ctx = _ctx({'jenkins': JLIST, 'vscode': CODELIST})
    disk = [JLIST, CODELIST]
    # vscode is wanted, jenkins is not -> only jenkins's source is an orphan
    orphans = app._orphaned_managed_sources(ctx, wanted={'vscode'}, disk_files=disk)
    assert orphans == [(JLIST, 'jenkins')]


def test_foreign_file_never_an_orphan():
    ctx = _ctx({'jenkins': JLIST})
    disk = [JLIST, '/etc/apt/sources.list.d/some-random.list']   # the random one isn't in any route
    orphans = app._orphaned_managed_sources(ctx, wanted=set(), disk_files=disk)
    assert orphans == [(JLIST, 'jenkins')]                        # foreign file excluded


def test_all_wanted_no_orphans():
    ctx = _ctx({'jenkins': JLIST})
    assert app._orphaned_managed_sources(ctx, wanted={'jenkins'}, disk_files=[JLIST]) == []


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True):
        self.calls.append(cmd)
        return Result(cmd, 0)


def test_reconcile_prompts_and_removes(monkeypatch):
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted=set(),
                                       ask=lambda p: True, lister=lambda: [JLIST])
    assert n == 1
    assert any(c == f'sudo rm -f {JLIST}' for c in r.calls)


def test_reconcile_declined_removes_nothing():
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted=set(),
                                       ask=lambda p: False, lister=lambda: [JLIST])
    assert n == 0 and not r.calls


def test_reconcile_noop_when_component_wanted():
    r = _Runner()
    ctx = _ctx({'jenkins': JLIST}, r)
    n = app._reconcile_managed_sources(ctx, 'apt', wanted={'jenkins'},
                                       ask=lambda p: True, lister=lambda: [JLIST])
    assert n == 0 and not r.calls


def test_reconcile_under_pretend_asks_nothing(capsys):
    # A14 / app-cli-03: a dry run can't remove anything, so it never prompts
    import types
    from configsys import app
    ctx = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=True),
                                paths=types.SimpleNamespace(home=__import__('pathlib').Path.home()))
    orig = refresh._orphaned_managed_sources
    refresh._orphaned_managed_sources = lambda c, w, files: [('/etc/apt/sources.list.d/x.list', 'x')]
    try:
        n = app._reconcile_managed_sources(ctx, 'apt', set(), ask=lambda p: (_ for _ in ()).throw(AssertionError(p)),
                                           lister=lambda: ['/etc/apt/sources.list.d/x.list'])
    finally:
        refresh._orphaned_managed_sources = orig
    assert n == 0 and 'would offer to remove' in capsys.readouterr().out


def test_an_installed_or_receipted_owner_is_never_stale(tmp_path, monkeypatch):
    import types
    from configsys import app
    from configsys.componentObj import ResolvedComponent
    from configsys.ledger import Ledger
    from configsys.paths import Paths
    paths = Paths(env={'HOME': str(tmp_path)})
    led = Ledger()
    led.set_receipt(ResolvedComponent(key='apt\\gum', driver='apt', comp='gum', fields={'name': 'gum'}))
    led.save(paths)
    monkeypatch.setattr(refresh, '_owned_index_sources', lambda c: {'/etc/apt/x.list': 'gum', '/etc/apt/y.list': 'slack'})
    slack = ResolvedComponent(key='apt\\slack', driver='apt', comp='slack', fields={'name': 'slack-desktop'})
    ctx = types.SimpleNamespace(paths=paths, runner=None,
                                routes=types.SimpleNamespace(resolve_resilient=lambda n, **k: ({'apt\\slack': slack}, {})))
    monkeypatch.setattr(refresh, 'get_driver', lambda *a, **k: types.SimpleNamespace(get_version=lambda rc: '4.0'))
    assert app._installed_owners(ctx) == {'gum', 'slack'}
