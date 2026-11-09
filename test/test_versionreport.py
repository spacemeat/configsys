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


# -- one slot per package (review-2026-11-2 subsystems-07) ----------------------------------------

def test_two_bindings_of_one_driver_with_different_names_keep_their_own_versions(tmp_path, monkeypatch):
    # p7zip on ubuntu 24.04: `via: native` p7zip-full (not rhel) and 7zip (ubuntu >= 22.04), both apt
    class PerPackage(_FakeDriver):
        name = 'apt'

        def get_latest(self, rc):
            return {'p7zip-full': '16.02+dfsg-8', '7zip': '23.01+dfsg-11'}[rc.name]

        def installed_index(self):
            return None                           # per-unit get_version: the probe-cache slot under test

        def get_version(self, rc):
            return {'p7zip-full': None, '7zip': '23.01+dfsg-11'}[rc.name]

    _mock_drivers(monkeypatch, {'apt': PerPackage()})
    ctx = _ctx(tmp_path)
    for _ in range(2):                            # the second report reads the cache back
        rep = versionreport.report(ctx, 'p7zip', now=1000)
        apt = {m.package: m for m in rep.methods if m.driver == 'apt'}
        assert apt['p7zip-full'].latest == '16.02+dfsg-8' and apt['7zip'].latest == '23.01+dfsg-11'
        assert apt['p7zip-full'].installed is None and apt['7zip'].installed == '23.01+dfsg-11'
    cache = versionreport._LatestCache.load(ctx.paths)
    assert {'apt\\p7zip\\p7zip-full', 'apt\\p7zip\\7zip'} <= set(cache.records)


def test_bindings_naming_the_same_package_fold_into_one_row(tmp_path, monkeypatch):
    two = ('{ components: { dupy: { install: [ { via: native  name: dupy }'
           '  { via: native  when: "ubuntu"  name: dupy } ] } } }')
    pf = tmp_path / 'dup.hu'
    pf.write_text(two, encoding='utf-8')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[(str(pf), 'plugin')])
    ctx = _Ctx(r, Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'HOME': str(tmp_path)}))
    _mock_drivers(monkeypatch, {'apt': _FakeDriver(latest='1.0')})
    rep = versionreport.report(ctx, 'dupy', now=1000)
    assert [(m.driver, m.package) for m in rep.methods] == [('apt', 'dupy')]
    assert rep.methods[0].is_default


def test_reports_memo_asks_once_and_never_raises(monkeypatch):
    calls = []

    def fake(ctx, name, **k):
        calls.append(name)
        if name == 'bad':
            raise versionreport.ResolveError('unknown component "bad"')
        return name.upper()
    monkeypatch.setattr(versionreport, 'report', fake)
    rep = versionreport.Reports(object())
    assert rep('go') == 'GO' and rep('go') == 'GO' and rep('bad') is None and rep('bad') is None
    assert calls == ['go', 'bad']
    assert versionreport.max_version(['1.2', 'v1.10', None]) == 'v1.10'
