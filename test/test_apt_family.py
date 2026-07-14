import pytest

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.apt import Apt
from configsys.runner import Result, Runner


def rc(name='btop'):
    return ResolvedComponent(key=f'apt\\{name}', family='apt', comp=name,
                             fields={'name': name})


class FakeRunner:
    '''Records commands and returns canned Results matched by substring.'''

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


# -- command construction (via pretend Runner) ---------------------------

def test_registry_resolves_apt_and_rejects_others():
    assert isinstance(get_family('apt', Runner(pretend=True)), Apt)
    assert get_family('flatpak', Runner(pretend=True)) is None
    assert is_supported('apt') and not is_supported('flatpak')


def test_install_command():
    r = Runner(pretend=True)
    Apt(r).install(rc())
    assert r.calls == ['sudo apt-get install -y btop']


def test_uninstall_command():
    r = Runner(pretend=True)
    Apt(r).uninstall(rc())
    assert r.calls == ['sudo apt-get remove -y btop']


def test_upgrade_command():
    r = Runner(pretend=True)
    Apt(r).upgrade(rc())
    assert r.calls == ['sudo apt-get install --only-upgrade -y btop']


def test_set_version_command():
    r = Runner(pretend=True)
    Apt(r).set_version(rc(), '1.2.3-1')
    assert r.calls == ['sudo apt-get install -y --allow-downgrades btop=1.2.3-1']


def test_lock_unlock_commands():
    r = Runner(pretend=True)
    Apt(r).lock(rc())
    Apt(r).unlock(rc())
    assert r.calls == ['sudo apt-mark hold btop', 'sudo apt-mark unhold btop']


def test_uses_family_name_field_not_comp():
    # e.g. vulkan-dev -> apt\vulkan-sdk: the apt package is the `name` field.
    comp = ResolvedComponent(key='apt\\vulkan-sdk', family='apt', comp='vulkan-sdk',
                             fields={'name': 'vulkan-sdk'})
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls == ['sudo apt-get install -y vulkan-sdk']


# -- output parsing (via FakeRunner) -------------------------------------

def test_get_version_installed():
    fr = FakeRunner([('dpkg-query', 0, '1.2.13-1\n')])
    assert Apt(fr).get_version(rc()) == '1.2.13-1'


def test_get_version_not_installed():
    fr = FakeRunner([('dpkg-query', 1, '')])
    assert Apt(fr).get_version(rc()) is None


def test_get_latest_candidate():
    policy = ('btop:\n  Installed: (none)\n  Candidate: 1.2.13-1\n'
              '  Version table:\n     1.2.13-1 500\n')
    fr = FakeRunner([('apt-cache policy', 0, policy)])
    assert Apt(fr).get_latest(rc()) == '1.2.13-1'


def test_get_latest_none():
    policy = 'btop:\n  Installed: (none)\n  Candidate: (none)\n'
    fr = FakeRunner([('apt-cache policy', 0, policy)])
    assert Apt(fr).get_latest(rc()) is None


def test_is_locked_true_and_false():
    held = FakeRunner([('apt-mark showhold', 0, 'btop\nripgrep\n')])
    assert Apt(held).is_locked(rc('btop')) is True
    assert Apt(held).is_locked(rc('fzf')) is False
