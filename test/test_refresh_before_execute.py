'''refresh-before-execute: the OS index is refreshed ONCE before a batch (per the setting), so
upgrades see current candidates and a broken vendor source is caught up front, not per-package.'''

from types import SimpleNamespace

import configsys.app as app
from configsys.runner import Result


def _mkctx(mode, pm='apt'):
    calls = []

    class R:
        def run(self, cmd, *, sudo=False, capture=True, **kw):
            calls.append(cmd)
            return Result(cmd, 0)
    ctx = SimpleNamespace(
        config=SimpleNamespace(refresh_before_execute=lambda: mode),
        routes=SimpleNamespace(cascade=SimpleNamespace(native=lambda b: pm)),
        os_info=SimpleNamespace(block='pop'),
        runner=R())
    return ctx, calls


def _plan(*ops):   # ops: (op, driver)
    return [(op, f'{drv}\\x', SimpleNamespace(driver=drv, name='x')) for op, drv in ops]


def test_auto_refreshes_for_a_native_upgrade():
    ctx, calls = _mkctx('auto')
    app.maybe_refresh_before_plan(ctx, _plan(('upgrade', 'apt')))
    assert any('apt-get update' in c for c in calls)


def test_auto_skips_when_no_native_op():
    ctx, calls = _mkctx('auto')
    app.maybe_refresh_before_plan(ctx, _plan(('install', 'tarball'), ('remove', 'apt')))
    assert calls == []                      # tarball install + apt REMOVE -> nothing to refresh for


def test_never_never_refreshes():
    ctx, calls = _mkctx('never')
    app.maybe_refresh_before_plan(ctx, _plan(('upgrade', 'apt')))
    assert calls == []


def test_always_refreshes_even_without_a_native_op():
    ctx, calls = _mkctx('always')
    app.maybe_refresh_before_plan(ctx, _plan(('remove', 'tarball')))
    assert any('apt-get update' in c for c in calls)


def test_pacman_is_skipped_no_safe_index_refresh():
    ctx, calls = _mkctx('always', pm='pacman')
    app.maybe_refresh_before_plan(ctx, _plan(('upgrade', 'pacman')))
    assert calls == []                      # pacman has no safe index-only refresh
