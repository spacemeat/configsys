'''review-2026-11-2 C1: the startup inspection asks each native manager ONCE for every unit's
candidate version and its held set (latest_index / held_keys in the batch), instead of a
repo-metadata-loading probe per unit — dnf went from 201 spawns for 100 units to a handful.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.installState import InstallState
from configsys.ledger import Ledger
from configsys.runner import Result


class _Rec:
    pretend, tui_active = False, False

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return Result(cmd, 0, stdout=self.answer(cmd))

    def end_sudo(self):
        pass


def _units(driver, n):
    return {f'{driver}\\p{i}': ResolvedComponent(key=f'{driver}\\p{i}', driver=driver, comp=f'p{i}',
                                                 fields={'name': f'p{i}'}) for i in range(n)}


def _dnf(cmd):
    if cmd.startswith('rpm -qa'):
        return ''.join(f'p{i} 1.0\n' for i in range(100))
    if 'repoquery' in cmd:
        return ''.join(f'p{i} 2.0\n' for i in range(100))
    if 'versionlock list' in cmd:
        return 'Package name: p3\n'
    return ''


def test_dnf_inspects_100_units_in_a_handful_of_spawns():
    r = _Rec(_dnf)
    states = InstallState(r, Ledger(), None).inspect(_units('dnf', 100))
    assert len(r.calls) <= 4, r.calls[:6]
    assert states['dnf\\p5'].installed_version == '1.0' and states['dnf\\p5'].latest_version == '2.0'
    assert states['dnf\\p3'].locked and not states['dnf\\p4'].locked


@pytest.mark.parametrize('driver,answer', [
    ('zypper', lambda c: ''.join(f'Name : p{i}\nVersion : 2.0\n\n' for i in range(20)) if 'info' in c else ''),
    ('pacman', lambda c: ''.join(f'Name : p{i}\nVersion : 2.0\n\n' for i in range(20)) if '-Si' in c else ''),
    ('apk', lambda c: ''.join(f'p{i}-2.0-r0 x86_64 {{p}} (MIT)\n' for i in range(20))
     if c.startswith('apk list ') and '--installed' not in c else ''),
])
def test_other_managers_batch_their_candidates(driver, answer):
    r = _Rec(answer)
    states = InstallState(r, Ledger(), None).inspect(_units(driver, 20))
    per_unit = [c for c in r.calls if ('info p' in c or '-Si p' in c or c.startswith('apk list p'))
                and c.count(' p') == 1]
    assert per_unit == [] and states[f'{driver}\\p7'].latest_version.startswith('2.0')
