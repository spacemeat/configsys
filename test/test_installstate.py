from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState, InstallState
from configsys.ledger import Ledger
from configsys.runner import Result


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


def apt_unit(name='btop'):
    return ResolvedComponent(key=f'apt\\{name}', driver='apt', comp=name,
                             fields={'name': name})


def unsupported_unit():
    # `nosuchvia` is not implemented -> exercises graceful degradation (all real routed
    # drivers are now supported, so use a synthetic unregistered one)
    return ResolvedComponent(key='nosuchvia\\foo', driver='nosuchvia', comp='foo',
                             fields={'name': 'foo'})


def test_installed_up_to_date():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.2.13-1'),
        ('apt-cache policy', 0, '  Candidate: 1.2.13-1\n'),
        ('apt-mark showhold', 0, ''),
    ])
    st = InstallState(fr).inspect_one(apt_unit())
    assert st.supported and st.present
    assert st.installed_version == '1.2.13-1'
    assert st.latest_version == '1.2.13-1'
    assert not st.outdated
    assert st.status == 'installed'


def test_outdated():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 2.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    st = InstallState(fr).inspect_one(apt_unit())
    assert st.outdated and st.status == 'outdated'


def _state(installed, latest):
    from configsys.componentObj import ResolvedComponent
    return ComponentState(
        component=ResolvedComponent(key='apt\\x', driver='apt', comp='x'),
        supported=True, present=True, installed_version=installed, latest_version=latest,
        locked=False, lock_source=None, managed=True, error=None)


def test_outdated_normalizes_across_schemes():
    # regression (yazi): an apt version `26.5.6-1` and a github tag `v26.5.6` are the SAME upstream
    # version — the Debian revision + `v` prefix must not read as outdated.
    assert _state('26.5.6-1', 'v26.5.6').outdated is False
    assert _state('26.5.6-1', 'v26.5.6').status == 'installed'
    assert _state('2:1.18~0ubuntu2', '1.18').outdated is False       # epoch + suffix
    # a genuinely newer upstream version still reads outdated
    assert _state('26.5.6-1', 'v26.5.7').outdated is True
    # unparseable -> conservative string diff (unchanged behavior)
    assert _state('nightly', 'stable').outdated is True
    assert _state('nightly', 'nightly').outdated is False


def test_clean_version_for_display():
    from configsys.osversion import clean_version
    assert clean_version('26.5.6-1') == '26.5.6'          # Debian revision dropped
    assert clean_version('v26.5.6') == '26.5.6'           # leading v dropped
    assert clean_version('2:1.18~0ubuntu2') == '1.18'     # epoch + packaging suffix dropped
    assert clean_version('1.2.3-rc1') == '1.2.3-rc1'      # pre-release kept (not a numeric revision)
    assert clean_version('nightly') == 'nightly'          # non-numeric -> unchanged
    assert clean_version(None) is None


def test_missing():
    fr = FakeRunner([
        ('dpkg-query', 1, ''),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    st = InstallState(fr).inspect_one(apt_unit())
    assert not st.present and st.status == 'missing'


def test_native_lock():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, 'btop\n'),
    ])
    st = InstallState(fr).inspect_one(apt_unit())
    assert st.locked and st.lock_source == 'native' and st.status == 'locked'


def test_ledger_lock_only():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    led = Ledger()
    led.set_lock('apt\\btop', True)
    st = InstallState(fr, led).inspect_one(apt_unit())
    assert st.locked and st.lock_source == 'ledger'


def test_both_lock_sources():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, 'btop\n'),
    ])
    led = Ledger()
    led.set_lock('apt\\btop', True)
    st = InstallState(fr, led).inspect_one(apt_unit())
    assert st.lock_source == 'both'


def test_unsupported_family_degrades():
    fr = FakeRunner()
    led = Ledger()
    led.set_managed('nosuchvia\\foo', True)
    st = InstallState(fr, led).inspect_one(unsupported_unit())
    assert not st.supported
    assert st.status == 'unsupported'
    assert st.managed is True
    assert 'nosuchvia' in st.error
    # a degraded inspection must not have shelled out
    assert fr.calls == []


def test_inspect_many():
    # inspect() runs the batch prepass, so apt is probed via `dpkg-query -W` (Package Version rows),
    # one `apt-cache policy` (column-0 `name:` blocks), and `apt-mark showhold` — not per-unit.
    fr = FakeRunner([
        ('dpkg-query', 0, 'btop 1.0.0\n'),
        ('apt-cache policy', 0, 'btop:\n  Installed: 1.0.0\n  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    units = {'apt\\btop': apt_unit('btop'), 'nosuchvia\\foo': unsupported_unit()}
    states = InstallState(fr).inspect(units)
    assert states['apt\\btop'].status == 'installed'
    assert states['nosuchvia\\foo'].status == 'unsupported'


def test_inspect_batches_apt_probes_across_units():
    # THE optimization: N apt units cost a FIXED few spawns (one dpkg-query -W, one apt-cache policy,
    # one apt-mark showhold), not 3 per unit. Regression guard for the startup-perf Phase A work.
    fr = FakeRunner([
        ('dpkg-query', 0, 'btop 1.0.0\nfd 2.0.0\n'),                    # one index, all packages
        ('apt-cache policy', 0, 'btop:\n  Candidate: 1.1.0\n'
                                'fd:\n  Candidate: 2.0.0\n'),           # one policy, all packages
        ('apt-mark showhold', 0, 'fd\n'),                              # one hold list
    ])
    units = {'apt\\btop': apt_unit('btop'), 'apt\\fd': apt_unit('fd')}
    states = InstallState(fr).inspect(units)
    assert states['apt\\btop'].status == 'outdated'                   # 1.0.0 < candidate 1.1.0
    assert states['apt\\fd'].status == 'locked' and states['apt\\fd'].locked      # held -> locked
    # exactly one of each batched probe, regardless of unit count (no per-package dpkg/policy/hold)
    assert sum('dpkg-query -W' in c for c in fr.calls) == 1
    assert sum('apt-cache policy' in c for c in fr.calls) == 1
    assert sum('apt-mark showhold' in c for c in fr.calls) == 1


def test_untrusted_driver_reads_as_untrusted_not_unsupported():
    # a component whose driver comes from a not-yet-trusted code plugin: the driver isn't
    # registered, but pending_vias tells us WHY -> status 'untrusted' with a trust hint.
    rc = ResolvedComponent(key='kicad-build\\kicad', driver='kicad-build', comp='kicad',
                           fields={'name': 'kicad'})
    st = InstallState(FakeRunner(), pending_vias={'kicad-build'}).inspect_one(rc)
    assert st.status == 'untrusted' and st.untrusted
    assert 'trust' in st.error

    # the same missing driver, but NOT a pending plugin via -> plain unsupported
    st2 = InstallState(FakeRunner()).inspect_one(rc)
    assert st2.status == 'unsupported' and not st2.untrusted


def test_untrusted_version_cells_show_question_not_dash():
    # display: an untrusted unit shows '?' (unknown), NOT '—' which would read as "not installed"
    from configsys.installState import ComponentState
    from configsys.tui.menu import Node, UNIT

    def node(untrusted):
        rc = ResolvedComponent(key='kicad-build\\kicad', driver='kicad-build', comp='kicad',
                               fields={'name': 'kicad'})
        st = ComponentState(component=rc, supported=False, present=False, installed_version=None,
                            latest_version=None, locked=False, lock_source=None, managed=False,
                            error='trust it', untrusted=untrusted)
        return Node(UNIT, 'u', 'kicad', 1, [st])

    n = node(True)
    assert n.installed_str() == '?' and n.latest_str() == '?'
    u = node(False)                       # unsupported (unknown driver, not a pending plugin)
    assert u.installed_str() == '—' and u.latest_str() == ''
