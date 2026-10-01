'''The service driver under runit (Void): /etc/sv/<name> linked into /var/service, the `runit:` name
override (string, list, or a glob for versioned service dirs), `start: false` -> a `down` file, and a
systemd-only .socket unit declining. The generated shell was exercised in a void-glibc container;
these pin its shape.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers.service import Service
from configsys.runner import Result


class R:
    def __init__(self):
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return Result(cmd, 0)


def rc(**f):
    return ResolvedComponent(key='service\\x', driver='service', comp='x', fields=f)


def test_runit_names_default_override_and_socket():
    d = Service(R())
    assert d._runit(rc(unit='nginx')) == ['nginx']
    assert d._runit(rc(unit='docker.service')) == ['docker']
    assert d._runit(rc(unit='mariadb', runit='mysqld')) == ['mysqld']
    assert d._runit(rc(unit='libvirtd', runit=['libvirtd', 'virtlogd'])) == ['libvirtd', 'virtlogd']
    assert d._runit(rc(unit='snapd.socket')) == []                    # systemd-only
    with pytest.raises(ValueError):
        d._runit(rc(unit='x', runit='a;rm -rf /'))                    # never reaches a shell


def test_install_prefers_systemd_then_links_runit_service():
    r = R()
    Service(r).install(rc(unit='postgresql', runit='postgresql[0-9]*', start=False))
    cmd = r.calls[-1]
    assert cmd.index('systemctl enable postgresql') < cmd.index('[ -d /var/service ]')
    assert 'for n in postgresql[0-9]*' in cmd                        # glob left to the shell
    assert 'touch "/etc/sv/$s/down"' in cmd                          # start: false
    assert 'ln -sfn "/etc/sv/$s" "/var/service/$s"' in cmd


def test_socket_unit_declines_under_runit():
    r = R()
    Service(r).install(rc(unit='snapd.socket'))
    assert 'systemd-only unit' in r.calls[-1]
