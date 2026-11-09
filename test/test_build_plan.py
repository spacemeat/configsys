'''review-2026-11-2 D3 + B1: ONE plan builder for the CLI and the TUI (actions.build_plan) — the same
swaps, auto-tighten and advisories, and both install only MISSING dependencies (--with-deps re-runs
the tree, --no-deps skips it); after_run drains the uninstall queue for both.'''

import types

import pytest

from configsys import actions, installState
from configsys.componentObj import ResolvedComponent


def _rc(key, deps=()):
    drv, comp = key.split('\\')
    return ResolvedComponent(key=key, driver=drv, comp=comp, fields={'name': comp}, deps=set(deps))


@pytest.fixture
def units(monkeypatch):
    monkeypatch.setattr(installState, 'plan_with_swaps', lambda ctx, steps, u: (steps, u))
    return {'brew\\scala': _rc('brew\\scala', ['script\\homebrew']),
            'script\\homebrew': _rc('script\\homebrew', ['apt\\curl']),
            'apt\\curl': _rc('apt\\curl')}


CTX = types.SimpleNamespace(config=types.SimpleNamespace(auto_tighten=lambda: False),
                            runner=types.SimpleNamespace(pretend=True), paths=None)


def _keys(plan):
    return [(op, k) for op, k, _rc in plan]


def _present(*keys):
    return {k: types.SimpleNamespace(present=True) for k in keys}


def test_present_dependencies_are_skipped_by_default(units, monkeypatch):
    monkeypatch.setattr(actions, '_dependency_states', lambda ctx, plan, u: _present('script\\homebrew', 'apt\\curl'))
    plan, _u, _a = actions.build_plan(CTX, [('install', 'brew\\scala', units['brew\\scala'])], units)
    assert _keys(plan) == [('install', 'brew\\scala')]      # never re-runs the Homebrew installer


def test_missing_dependencies_are_installed_first(units, monkeypatch):
    monkeypatch.setattr(actions, '_dependency_states', lambda ctx, plan, u: _present('apt\\curl'))
    plan, _u, _a = actions.build_plan(CTX, [('upgrade', 'brew\\scala', units['brew\\scala'])], units)
    assert _keys(plan) == [('install', 'script\\homebrew'), ('upgrade', 'brew\\scala')]


def test_with_deps_reruns_the_tree_and_no_deps_skips_it(units, monkeypatch):
    monkeypatch.setattr(actions, '_dependency_states', lambda ctx, plan, u: pytest.fail('not probed'))
    step = [('install', 'brew\\scala', units['brew\\scala'])]
    plan, _u, _a = actions.build_plan(CTX, step, units, with_deps=True)
    assert _keys(plan) == [('install', 'apt\\curl'), ('install', 'script\\homebrew'),
                           ('install', 'brew\\scala')]
    plan, _u, _a = actions.build_plan(CTX, step, units, no_deps=True)
    assert _keys(plan) == [('install', 'brew\\scala')]


def test_the_tui_passes_its_own_states(units, monkeypatch):
    monkeypatch.setattr(actions, '_dependency_states', lambda ctx, plan, u: pytest.fail('not probed'))
    plan, _u, _a = actions.build_plan(CTX, [('install', 'brew\\scala', units['brew\\scala'])], units,
                                      states=_present('script\\homebrew', 'apt\\curl'))
    assert _keys(plan) == [('install', 'brew\\scala')]


def test_after_run_drains_the_uninstall_queue_for_both_surfaces(units, monkeypatch):
    drained = []
    monkeypatch.setattr(actions, 'stage_uninstall', lambda ctx, comp, on: drained.append((comp, on)))
    outcomes = [actions.OpOutcome('remove', 'apt\\curl', 'curl', True),
                actions.OpOutcome('remove', 'brew\\scala', 'scala', False)]
    actions.after_run(CTX, outcomes, units)
    assert drained == [('curl', False)]
