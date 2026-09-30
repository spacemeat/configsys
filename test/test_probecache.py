'''probecache: the detection passes' shared "what's installed" probes, kept across a TUI reload and
invalidated only by what the executed ops touched (a reload after a pin change used to re-probe the
whole machine: ~4s of the ~6s reload).'''

import types

from configsys.probecache import ProbeCache


class Drv:
    def __init__(self, name, index=None):
        self.name, self.index, self.enums, self.gets = name, index, 0, 0

    def installed_index(self):
        self.enums += 1
        return self.index

    def index_key(self, rc):
        return rc.comp

    def get_version(self, rc):
        self.gets += 1
        return '1.0'


def rc(key):
    return types.SimpleNamespace(key=key, comp=key.partition('\\')[2])


def test_enumerates_and_probes_once():
    pc, apt, tb = ProbeCache(), Drv('apt', {'htop': '3.0'}), Drv('tarball', None)
    assert pc.version(apt, rc('apt\\htop')) == '3.0' and pc.version(apt, rc('apt\\nope')) is None
    assert pc.version(tb, rc('tarball\\zig')) == '1.0' and pc.version(tb, rc('tarball\\zig')) == '1.0'
    assert apt.enums == 1 and tb.gets == 1                       # cached, not re-run


def test_invalidate_drops_only_what_the_ops_touched():
    pc, apt, flat, tb = ProbeCache(), Drv('apt', {}), Drv('flatpak', {}), Drv('tarball', None)
    for d in (apt, flat):
        pc.installed_index(d)
    pc.version(tb, rc('tarball\\zig'))
    pc.version(tb, rc('tarball\\lazygit'))
    pc.invalidate({'apt\\htop', 'tarball\\zig'})
    pc.installed_index(apt), pc.installed_index(flat)
    pc.version(tb, rc('tarball\\zig')), pc.version(tb, rc('tarball\\lazygit'))
    assert apt.enums == 2 and flat.enums == 1                    # apt re-enumerated, flatpak kept
    assert tb.gets == 3                                          # only zig re-probed; lazygit kept
    pc.invalidate(set())                                         # nothing ran (a pin change) -> nothing dropped
    pc.installed_index(apt)
    assert apt.enums == 2


def test_system_updates_bulk_key_invalidates_that_manager():
    pc, apt = ProbeCache(), Drv('apt', {})
    pc.installed_index(apt)
    pc.invalidate({'system-updates\\apt'})                       # a bulk `apt upgrade` ran
    pc.installed_index(apt)
    assert apt.enums == 2
