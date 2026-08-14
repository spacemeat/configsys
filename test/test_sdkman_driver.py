'''The SDKMAN! driver — the JVM-ecosystem module driver (scala/groovy/sbt/leiningen via `sdk`).
Every op sources the init script (sdk is a bash function) and runs non-interactively.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.sdkman import Sdkman
from configsys.runner import Result


def rc(name='scala', **fields):
    return ResolvedComponent(key=f'sdkman\\{name}', driver='sdkman', comp=name,
                             fields={**fields})


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        self.calls.append(cmd)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(cmd, code, stdout=out)
        return Result(cmd, 0, stdout='')


def _drv(responses=None):
    fr = FakeRunner(responses)
    return get_driver('sdkman', fr), fr


def test_registry_resolves_sdkman():
    assert isinstance(get_driver('sdkman', FakeRunner()), Sdkman)


def test_install_sources_init_and_is_non_interactive():
    d, fr = _drv()
    d.install(rc('scala'))
    cmd = fr.calls[-1]
    assert 'sdkman-init.sh' in cmd            # sources the init script (sdk is a shell function)
    assert 'sdkman_auto_answer=true' in cmd   # non-interactive
    assert 'sdk install scala' in cmd


def test_install_pins_a_version_when_given():
    d, fr = _drv()
    d.install(rc('scala', version='3.8.4'))
    assert 'sdk install scala 3.8.4' in fr.calls[-1]


def test_get_version_parses_sdk_current():
    d, _ = _drv([('current', 0, 'Using scala version 3.8.4\n')])
    assert d.get_version(rc('scala')) == '3.8.4'
    d2, _ = _drv([('current', 0, 'Not using any version of scala\n')])   # no digit -> None
    assert d2.get_version(rc('scala')) is None


def test_uninstall_needs_a_version():
    # unknown version -> no-op, never a bare `sdk uninstall`
    d, fr = _drv([('current', 0, 'Not using any version of scala\n')])
    d.uninstall(rc('scala'))
    assert not any('sdk uninstall' in c for c in fr.calls)
    # known version -> uninstalls exactly it
    d2, fr2 = _drv([('current', 0, 'Using scala version 3.8.4\n')])
    d2.uninstall(rc('scala'))
    assert 'sdk uninstall scala 3.8.4' in fr2.calls[-1]


def test_set_version_installs_then_defaults():
    d, fr = _drv()
    d.set_version(rc('groovy'), '5.0.8')
    cmd = fr.calls[-1]
    assert 'sdk install groovy 5.0.8' in cmd and 'sdk default groovy 5.0.8' in cmd


def test_location_points_at_the_current_symlink():
    d, _ = _drv()
    assert d.location(rc('sbt')) == '~/.sdkman/candidates/sbt/current'
