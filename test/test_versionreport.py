'''Unit tests for versionreport — per-install-method version visibility.

The comparison helpers are pure. The report assembly is exercised over the real routes.hu (btop =
native + source, a stable multi-method component) with DRIVERS MOCKED, so versions are deterministic
and no network/package-manager is touched.
'''

import os

from configsys import versionreport
from configsys.paths import Paths
from configsys.routes import Resolver

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')


# -- pure comparison helpers -------------------------------------------------

def test_pv_strips_leading_v_and_tolerates_debian_suffix():
    assert versionreport._pv('v1.4.7') == (1, 4, 7)
    assert versionreport._pv('1.2.3-2') == (1, 2, 3)      # Debian revision tolerated
    assert versionreport._pv('V2.0') == (2, 0)
    assert versionreport._pv(None) is None
    assert versionreport._pv('nightly') is None           # unparseable -> None (abstain)
    assert versionreport._pv('2:1.18~0ubuntu2') == (1, 18)  # Debian epoch stripped (not 2.18)


def test_ge_lt_abstain_on_unparseable():
    assert versionreport._ge('1.96.0', '1.96') is True
    assert versionreport._ge('1.75.0', '1.96') is False
    assert versionreport._ge('v1.4.7', '1.4') is True     # v-prefix normalized
    assert versionreport._ge('nightly', '1.0') is None    # abstain
    assert versionreport._lt('1.2.3-2', 'v1.4.7') is True
    assert versionreport._lt('nightly', '1.0') is False   # abstain -> not "lagging"


def test_max_version_ignores_unparseable():
    assert versionreport._max_version(['1.2.3-2', 'v1.4.7', 'nightly', None]) == 'v1.4.7'
    assert versionreport._max_version([None, 'garbage']) is None


# -- report assembly (drivers mocked) ----------------------------------------

class _FakeDriver:
    def __init__(self, latest=None, installed=None):
        self._latest, self._installed = latest, installed

    def get_latest(self, rc):
        return self._latest

    def get_version(self, rc):
        return self._installed


class _Ctx:
    def __init__(self, routes, paths):
        self.routes, self.runner, self.paths = routes, None, paths


# source-building lives in the configsys-source plugin now, not core — so add a btop source binding
# via a temp plugin layer (rather than coupling to the external repo) to exercise the multi-method
# report. btop then has native + source, as before the fold.
_BTOP_SRC = '{ components: { btop: { install: [ { via: source  repo: "https://x/btop"  requires: cxx  build: "make" } ] } } }'


def _ctx(tmp_path, **pins):
    pf = tmp_path / 'btop-src.hu'
    pf.write_text(_BTOP_SRC, encoding='utf-8')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', pins=pins or None,
                 plugin_files=[(str(pf), 'plugin')])
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'HOME': str(tmp_path)})
    return _Ctx(r, paths)


def _mock_drivers(monkeypatch, mapping):
    monkeypatch.setattr(versionreport, 'get_driver',
                        lambda name, runner, paths: mapping.get(name))


def test_report_marks_default_tip_lag_and_min(tmp_path, monkeypatch):
    # btop on ubuntu = native(apt) + source; apt is the default (native-first preference).
    _mock_drivers(monkeypatch, {
        'apt': _FakeDriver(latest='1.2.3-2', installed='1.2.3-2'),
        'source': _FakeDriver(latest='v1.4.7', installed=None),
    })
    rep = versionreport.report(_ctx(tmp_path), 'btop', min_version='1.4', now=1000)

    by_via = {m.via: m for m in rep.methods}
    assert set(by_via) >= {'native', 'source'}
    assert rep.tip == 'v1.4.7'                            # source is the newest available

    native = by_via['native']
    assert native.driver == 'apt' and native.is_default
    assert native.installed == '1.2.3-2'
    assert native.lags_tip is True                        # 1.2.3 < 1.4.7
    assert native.meets_min is False                      # 1.2.3 < 1.4
    assert rep.default_meets_min is False                 # the default can't meet the floor

    source = by_via['source']
    assert source.lags_tip is False and source.meets_min is True   # v1.4.7 >= 1.4


def test_report_shows_all_methods_even_when_pinned(tmp_path, monkeypatch):
    # a pin must NOT hide the alternatives — the whole point is to see what you could switch to.
    _mock_drivers(monkeypatch, {
        'apt': _FakeDriver(latest='1.2.3-2', installed='1.2.3-2'),
        'source': _FakeDriver(latest='v1.4.7'),
    })
    rep = versionreport.report(_ctx(tmp_path, btop='native'), 'btop', now=1000)
    by_via = {m.via: m for m in rep.methods}
    assert 'source' in by_via                             # alternative still listed
    assert by_via['native'].is_pinned is True
    assert by_via['source'].is_pinned is False


def test_latest_is_cached_between_calls(tmp_path, monkeypatch):
    calls = {'n': 0}

    class Counting(_FakeDriver):
        def get_latest(self, rc):
            calls['n'] += 1
            return '1.2.3-2'

    _mock_drivers(monkeypatch, {'apt': Counting(), 'source': _FakeDriver(latest='v1.4.7')})
    ctx = _ctx(tmp_path)
    versionreport.report(ctx, 'btop', now=1000)
    first = calls['n']
    versionreport.report(ctx, 'btop', now=1000)           # same now -> within TTL -> cache hit
    assert calls['n'] == first                            # apt get_latest not called again


def test_unknown_result_is_not_cached_and_self_heals(tmp_path, monkeypatch):
    # a method that returns None (unknown) must NOT poison the cache — once its driver learns to
    # report a version, the next read picks it up (no stale blank until the TTL).
    box = {'latest': None}

    class Learns(_FakeDriver):
        def get_latest(self, rc):
            return box['latest']

    _mock_drivers(monkeypatch, {'apt': Learns(), 'source': _FakeDriver(latest='v1.4.7')})
    ctx = _ctx(tmp_path)
    rep1 = versionreport.report(ctx, 'btop', now=1000)
    assert {m.via: m.latest for m in rep1.methods}['native'] is None
    box['latest'] = '1.5.0'                                # the driver now knows a version
    rep2 = versionreport.report(ctx, 'btop', now=1000)    # same now: a cached blank would block this
    assert {m.via: m.latest for m in rep2.methods}['native'] == '1.5.0'


def test_unknown_component_raises(tmp_path, monkeypatch):
    from configsys.resolve import ResolveError
    _mock_drivers(monkeypatch, {})
    import pytest
    with pytest.raises(ResolveError):
        versionreport.report(_ctx(tmp_path), 'no-such-component-xyz')
