'''Work the CLI used to do twice or one at a time (review-2026-11-2 app-cli-19/20/21): `check`
route-checks each component once, `location --all` resolves once, a forced `--os` is vetted
against the os: sections alone, and `refresh` queries its version sources concurrently.'''

import argparse
import threading
import time
from types import SimpleNamespace

from configsys import routecheck, routes
from configsys.app import Context, build_parser, main
from configsys.cli import check, refresh, where


def _ctx(tmp_path, *extra):
    return Context(build_parser().parse_args(
        ['--home', str(tmp_path), '--os', 'pop', '--pretend', *extra, 'inspect']))


# -- app-cli-19 --------------------------------------------------------------

def test_check_route_checks_each_component_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(routes, '_VALIDATED', set())          # a cold process: nothing memoized
    calls = []
    real = routecheck.check_component
    monkeypatch.setattr(routecheck, 'check_component', lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    main(['--home', str(tmp_path), '--os', 'pop', '--pretend', 'check'])
    capsys.readouterr()
    assert calls and len(calls) == len(set(calls))            # once per component (it was twice)


def test_check_rows_match_the_tolerant_path(tmp_path, monkeypatch):
    (tmp_path / '.config' / 'configsys').mkdir(parents=True)
    (tmp_path / '.config' / 'configsys' / 'configsys.hu').write_text(
        '{ picks: { this-machine: [ btop  nosuchtool ] }  pins: { fzf: nosuchvia } }')
    fast = check.check_report(_ctx(tmp_path))
    monkeypatch.setattr(check, '_validated_routes', lambda _c: None)
    slow = check.check_report(_ctx(tmp_path))
    assert fast == slow and any('nosuchtool' in t for _l, t in fast[0])


# -- app-cli-20 --------------------------------------------------------------

def test_location_lines_resolves_once_with_an_unroutable_pick(tmp_path, monkeypatch):
    (tmp_path / '.config' / 'configsys').mkdir(parents=True)
    (tmp_path / '.config' / 'configsys' / 'configsys.hu').write_text(
        '{ picks: { this-machine: [ btop  nosuchtool ] } }')
    ctx = _ctx(tmp_path)
    seen = []
    r = ctx.routes
    real_res, real_names = r.resolve_resilient, r.resolve_names
    monkeypatch.setattr(r, 'resolve_resilient', lambda *a, **k: seen.append('resilient') or real_res(*a, **k))
    monkeypatch.setattr(r, 'resolve_names', lambda *a, **k: seen.append('names') or real_names(*a, **k))
    where._location_lines(ctx)
    assert seen == ['resilient']


def test_check_os_vets_a_forced_block_without_building_the_resolver(tmp_path):
    import pytest
    from configsys.errors import ConfigsysError
    ok = Context(argparse.Namespace(pretend=True, os='pop', home=str(tmp_path), config=None))
    ok.check_os(light=True)
    assert ok._routes is None                                 # no catalog load + route check for it
    bad = Context(argparse.Namespace(pretend=True, os='bogus', home=str(tmp_path), config=None))
    with pytest.raises(ConfigsysError, match='no OS block named "bogus"'):
        bad.check_os(light=True)


def test_show_with_a_forced_os_builds_no_resolver(tmp_path, monkeypatch, capsys):
    built = []
    real = Context._new_resolver
    monkeypatch.setattr(Context, '_new_resolver', lambda self, b: built.append(b) or real(self, b))
    assert main(['--home', str(tmp_path), '--os', 'pop', 'show', 'routes', '--path']) == 0
    assert built == [] and 'routes.hu' in capsys.readouterr().out
    assert main(['--home', str(tmp_path), '--os', 'bogus', 'show', 'routes', '--path']) == 1


def test_os_blocks_merges_the_os_sections(tmp_path):
    from configsys.paths import Paths
    p = Paths({})
    user = tmp_path / 'u.hu'
    user.write_text('{ os: { myos: { using: ubuntu } } }')
    blocks = routes.os_blocks(p.routes_file, user)
    assert 'myos' in blocks and 'pop_os!' in blocks


# -- app-cli-21 --------------------------------------------------------------

def test_refresh_queries_version_sources_concurrently(monkeypatch, capsys):
    threads = set()

    def slow_discover(spec, _paths, refresh=False, offline=False):
        threads.add(threading.get_ident())
        time.sleep(0.2)
        return f'1.{spec["github"][-1]}'
    monkeypatch.setattr('configsys.versions.discover', slow_discover)

    class Drv:
        def version_spec(self, rc):
            return {'github': f'own/r{rc.comp[-1]}'}
    monkeypatch.setattr(refresh, 'get_driver', lambda *a, **k: Drv())
    units = {f'tarball\\t{i}': SimpleNamespace(comp=f't{i}', driver='tarball', fields={}) for i in range(5)}
    ctx = SimpleNamespace(
        load_pipeline=lambda: (None, [], units, None, {}), paths=None, config=None,
        runner=SimpleNamespace(pretend=True),
        routes=SimpleNamespace(cascade=SimpleNamespace(native=lambda _b: None)),
        os_info=SimpleNamespace(block='x'))
    t0 = time.monotonic()
    refresh.cmd_refresh(ctx)
    assert time.monotonic() - t0 < 0.8 and len(threads) > 1       # serially it was 1 s
    out = [ln.split()[0] for ln in capsys.readouterr().out.splitlines() if ln.startswith('  github:')]
    assert out == sorted(out) and len(out) == 5
