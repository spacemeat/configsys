from configsys.componentObj import ResolvedComponent
from configsys.installState import InstallState
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
    # `snap` is not implemented -> exercises graceful degradation (all real routed
    # drivers are now supported, so use a synthetic unregistered one)
    return ResolvedComponent(key='snap\\foo', driver='snap', comp='foo',
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
    led.set_managed('snap\\foo', True)
    st = InstallState(fr, led).inspect_one(unsupported_unit())
    assert not st.supported
    assert st.status == 'unsupported'
    assert st.managed is True
    assert 'snap' in st.error
    # a degraded inspection must not have shelled out
    assert fr.calls == []


def test_inspect_many():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    units = {'apt\\btop': apt_unit('btop'), 'snap\\foo': unsupported_unit()}
    states = InstallState(fr).inspect(units)
    assert states['apt\\btop'].status == 'installed'
    assert states['snap\\foo'].status == 'unsupported'


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
