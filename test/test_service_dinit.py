'''The service driver under dinit (Chimera): a service file in /etc/dinit.d or /usr/lib/dinit.d,
enabled = a link in the boot service's waits-for.d (/etc/dinit.d/boot.d), the `dinit:` name
override, `start: false` -> an offline enable that starts nothing, and no running dinit (a chroot or
container) -> an offline enable that starts at the next boot. The generated shell was exercised in
the chimeralinux/chimera container (offline, and online against a `dinit --container`); these pin
its shape.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers.service import INITS, Dinit, Runit, Service, Systemd
from configsys.runner import Result


class R:
    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return Result(cmd, self.rc)


def rc(**f):
    return ResolvedComponent(key='service\\x', driver='service', comp='x', fields=f)


def _dinit_branch(cmd):
    return cmd[cmd.index(Dinit.present):]


def test_inits_are_asked_in_order_systemd_runit_dinit():
    assert [type(i) for i in INITS] == [Systemd, Runit, Dinit]
    r = R()
    Service(r).install(rc(unit='docker', dinit='dockerd'))
    cmd = r.calls[-1]
    assert (cmd.index(Systemd.present) < cmd.index(Runit.present) < cmd.index(Dinit.present)
            < cmd.index('no systemd, runit or dinit here'))


def test_dinit_names_default_override_and_socket():
    d = Dinit()
    assert d.names(rc(unit='nginx.service')) == ['nginx']
    assert d.names(rc(unit='docker', dinit='dockerd')) == ['dockerd']
    assert d.names(rc(unit='libvirtd', dinit=['virtqemud', 'virtlogd'])) == ['virtqemud', 'virtlogd']
    assert d.names(rc(unit='docker', runit='docker-runit')) == ['docker']   # runit: is runit's only
    assert d.names(rc(unit='cockpit.socket')) == []                          # systemd-only
    with pytest.raises(ValueError):
        d.names(rc(unit='x', dinit='a;rm -rf /'))


def test_dinit_install_enables_online_and_falls_back_offline():
    r = R()
    Service(r).install(rc(unit='docker', dinit='dockerd'))
    sh = _dinit_branch(r.calls[-1])
    assert 'for f in /etc/dinit.d/$1 /usr/lib/dinit.d/$1' in sh        # either service dir
    assert 'for n in dockerd' in sh
    assert 'if [ -S /run/dinitctl ]' in sh                              # a running dinit ...
    assert 'dinitctl enable "$s"' in sh                                 # ... links + starts
    assert 'dinitctl start "$s"' in sh                                  # already linked: start only
    assert '[ -e "/etc/dinit.d/boot.d/$s" ] || dinitctl --offline enable "$s"' in sh
    assert 'starts at the next boot' in sh


def test_dinit_start_false_only_links_offline():
    r = R()
    Service(r).install(rc(unit='postgresql', start=False))
    sh = _dinit_branch(r.calls[-1])
    assert '[ -e "/etc/dinit.d/boot.d/$s" ] || dinitctl --offline enable "$s"' in sh
    assert 'dinitctl enable "$s"' not in sh and 'dinitctl start' not in sh


def test_dinit_uninstall_removes_only_the_admins_link():
    r = R()
    Service(r).uninstall(rc(unit='docker', dinit='dockerd'))
    sh = _dinit_branch(r.calls[-1])
    assert 'if [ -e "/etc/dinit.d/boot.d/$s" ]; then' in sh   # never the distro's /usr/lib boot.d
    assert 'dinitctl disable "$s"' in sh and 'dinitctl --offline disable "$s"' in sh


def test_dinit_enabled_counts_the_distros_default_links():
    r = R(1)
    assert Service(r).get_version(rc(unit='dbus')) is None
    sh = _dinit_branch(r.calls[-1])
    assert '[ -e "/usr/lib/dinit.d/boot.d/$s" ]' in sh


def test_socket_unit_declines_under_dinit():
    r = R()
    Service(r).install(rc(unit='snapd.socket'))
    assert 'dinit has no counterpart' in _dinit_branch(r.calls[-1])


def test_unsafe_dinit_name_builds_no_command():
    r = R()
    res = Service(r).install(rc(unit='x.service', dinit='*'))
    assert not res.ok and 'unsafe dinit' in res.stderr and r.calls == []
    assert Service(r).get_version(rc(unit='x', dinit='a..b')) is None and r.calls == []


def test_location_names_each_init():
    assert Service(R()).location(rc(unit='docker', dinit='dockerd')) == (
        'systemd unit: docker / runit: /etc/sv/docker / dinit service: dockerd')
    assert Service(R()).location(rc(unit='cups.socket')) == 'systemd unit: cups.socket'
