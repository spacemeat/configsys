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
    return ResolvedComponent(key=f'apt\\{name}', family='apt', comp=name,
                             fields={'name': name})


def unsupported_unit():
    # appImage is not implemented yet -> exercises graceful degradation
    return ResolvedComponent(key='appImage\\neovim', family='appImage', comp='neovim',
                             fields={'name': 'neovim'})


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
    led.set_managed('appImage\\neovim', True)
    st = InstallState(fr, led).inspect_one(unsupported_unit())
    assert not st.supported
    assert st.status == 'unsupported'
    assert st.managed is True
    assert 'appImage' in st.error
    # a degraded inspection must not have shelled out
    assert fr.calls == []


def test_inspect_many():
    fr = FakeRunner([
        ('dpkg-query', 0, '1.0.0'),
        ('apt-cache policy', 0, '  Candidate: 1.0.0\n'),
        ('apt-mark showhold', 0, ''),
    ])
    units = {'apt\\btop': apt_unit('btop'), 'appImage\\neovim': unsupported_unit()}
    states = InstallState(fr).inspect(units)
    assert states['apt\\btop'].status == 'installed'
    assert states['appImage\\neovim'].status == 'unsupported'
