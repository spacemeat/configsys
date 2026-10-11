'''The pyenv driver — a Python minor line (e.g. "3.11") compiled under ~/.pyenv, user-scope. Runs
pyenv by its explicit path (PYENV_ROOT under the configsys home), never a shell `pyenv init`.'''

from types import SimpleNamespace

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.pyenv import Pyenv
from configsys.runner import Result


def rc(name='python3.11', **fields):
    return ResolvedComponent(key=f'pyenv\\{name}', driver='pyenv', comp=name, fields=fields)


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


def _drv(tmp_path, responses=None):
    fr = FakeRunner(responses)
    return get_driver('pyenv', fr, SimpleNamespace(home=tmp_path)), fr


def test_registered_user_scope_and_explicit_path(tmp_path):
    d, fr = _drv(tmp_path)
    assert isinstance(d, Pyenv) and d.privileged is False and d.default_scope == 'user'
    d.install(rc(version='3.11'))
    assert fr.calls[-1].startswith(f'PYENV_ROOT={tmp_path}/.pyenv {tmp_path}/.pyenv/bin/pyenv ')
    assert fr.calls[-1].endswith('install -s 3.11')        # -s: skip when already present


def test_get_version_is_the_newest_installed_patch_of_the_line(tmp_path):
    d, _ = _drv(tmp_path, [('versions --bare', 0, '3.10.14\n3.11.2\n3.11.9\n3.110.1\n')])
    assert d.get_version(rc(version='3.11')) == '3.11.9'    # not 3.110.1: the line is X.Y exactly
    assert d.get_version(rc(version='3.12')) is None


def test_get_latest_reads_the_known_patch(tmp_path):
    d, _ = _drv(tmp_path, [('latest --known 3.11', 0, '3.11.10\n')])
    assert d.get_latest(rc(version='3.11')) == '3.11.10'
    d2, _ = _drv(tmp_path, [('latest --known', 1, '')])
    assert d2.get_latest(rc(version='3.11')) is None


def test_uninstall_removes_the_installed_patch_or_noops(tmp_path):
    d, fr = _drv(tmp_path, [('versions --bare', 0, '3.11.9\n')])
    d.uninstall(rc(version='3.11'))
    assert fr.calls[-1].endswith('uninstall -f 3.11.9')
    d2, fr2 = _drv(tmp_path, [('versions --bare', 0, '')])
    d2.uninstall(rc(version='3.11'))
    assert not any(' uninstall -f' in c for c in fr2.calls)


def test_upgrade_reinstalls_the_line_and_location_globs_it(tmp_path):
    d, fr = _drv(tmp_path)
    d.upgrade(rc(version='3.11'))
    assert fr.calls[-1].endswith('install -s 3.11')
    assert d.location(rc(version='3.11')) == '~/.pyenv/versions/3.11.*'
