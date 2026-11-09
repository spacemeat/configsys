'''review-2026-11-2 tests-tools-06 — the package-name sweeps never read an outage as "OK".'''

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import namesweep  # noqa: E402


def _fake_podman(monkeypatch, stdout, rc=0, stderr=''):
    monkeypatch.setattr(namesweep.subprocess, 'run',
                        lambda *a, **k: SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc))


def test_a_check_that_never_ran_raises(monkeypatch):
    _fake_podman(monkeypatch, '', 125, 'Error: initializing source docker://x: manifest unknown')
    with pytest.raises(namesweep.VerifierFailed, match='manifest unknown'):
        namesweep._run_verifier('x', namesweep._build_snippet('', 'true'), ['a', 'b'])


def test_a_completed_check_reports_only_the_missing(monkeypatch):
    _fake_podman(monkeypatch, f'b\n{namesweep.DONE}\n')
    missing, _rc = namesweep._run_verifier('x', namesweep._build_snippet('', 'true'), ['a', 'b'])
    assert missing == ['b']


def test_the_snippet_ends_with_the_sentinel():
    assert namesweep._build_snippet('setup', 'check').rstrip().endswith(f'echo {namesweep.DONE}')


def test_sweep_exits_nonzero_when_a_manager_was_not_checked(monkeypatch, capsys):
    monkeypatch.setattr(namesweep.shutil, 'which', lambda _x: '/usr/bin/podman')
    monkeypatch.setattr(namesweep, 'extract', lambda **_k: {'apk': {'curl': ['curl']}})
    monkeypatch.setattr(namesweep, '_load_allowlist', lambda *a: {'apk': {'rocm-hip'}})
    _fake_podman(monkeypatch, '', 125, 'manifest unknown')
    assert namesweep.sweep(only={'apk'}) == 2
    out = capsys.readouterr()
    assert 'NOT CHECKED' in out.out and 'now exists' not in out.out    # no bogus allowlist advice


def test_drift_alongside_an_unchecked_manager_still_names_it(monkeypatch, capsys):
    # drift (exit 1) used to return before the NOT CHECKED summary, so a manager with no verdict was
    # only an stderr line above — the summary now says both; the exit stays 1 (drift outranks)
    monkeypatch.setattr(namesweep.shutil, 'which', lambda _x: '/usr/bin/podman')
    monkeypatch.setattr(namesweep, 'extract', lambda **_k: {'apk': {'curl': ['curl']}, 'apt': {'jq': ['jq']}})
    monkeypatch.setattr(namesweep, '_load_allowlist', lambda *a: {})

    def run(argv, **_k):
        if 'alpine' in ' '.join(argv):
            return SimpleNamespace(stdout=f'curl\n{namesweep.DONE}\n', stderr='', returncode=0)
        return SimpleNamespace(stdout='', stderr='manifest unknown', returncode=125)
    monkeypatch.setattr(namesweep.subprocess, 'run', run)
    assert namesweep.sweep(only={'apk', 'apt'}) == 1
    out = capsys.readouterr().out
    assert 'DRIFT  apk: package "curl"' in out and '1 package(s) drifted' in out
    assert 'NOT CHECKED — apt' in out


def test_sweep_rejects_an_unknown_manager(monkeypatch, capsys):
    monkeypatch.setattr(namesweep.shutil, 'which', lambda _x: '/usr/bin/podman')
    assert namesweep.sweep(only={'fedora'}) == 2                       # a block, not a manager
    assert 'unknown manager' in capsys.readouterr().err


def test_sweep_resolves_only_the_managers_it_sweeps(monkeypatch):
    # tests-tools-22: `--only apk` resolves the catalog once (for apk), not for every manager
    seen = []
    monkeypatch.setattr(namesweep.shutil, 'which', lambda _x: '/usr/bin/podman')
    monkeypatch.setattr(namesweep, '_native_names',
                        lambda block, ver, mgr, **_k: seen.append(mgr) or {'curl': ['curl']})
    monkeypatch.setattr(namesweep, '_load_allowlist', lambda *a: {})
    _fake_podman(monkeypatch, f'{namesweep.DONE}\n')
    assert namesweep.sweep(only={'apk'}) == 0
    assert seen == ['apk']
