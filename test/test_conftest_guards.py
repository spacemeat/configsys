'''The hermetic harness itself (test/conftest.py): no sudo, no real runner, no network.'''

import socket
import urllib.request

import pytest


def test_the_network_is_off_by_default():
    with pytest.raises(OSError, match='network disabled'):
        socket.create_connection(('example.com', 443), timeout=1)
    with pytest.raises(OSError):
        urllib.request.urlopen('https://api.github.com/', timeout=1)


def test_loopback_still_works():
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    c = socket.create_connection(srv.getsockname(), timeout=1)
    c.close()
    srv.close()


def test_version_discovery_reads_offline_fast():
    import time
    from configsys import versions
    t = time.perf_counter()
    with pytest.raises(OSError):
        versions.http_fetch('https://github.com/x/y/releases.atom')
    assert time.perf_counter() - t < 1.0                 # no retry backoff under the harness
