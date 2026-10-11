'''Regression tests for fix batch D follow-ups:

1. sysupdates scan generations — an invalidate() while a scan is in flight supersedes it: start_scan
   starts a fresh scan, and the stale scan's result is discarded when it lands.
2. purified shared shell loaders — no personal PYTHONPATH/`x` in glue/bash_aliases; every shell's
   00-configsys prelude ships `cfs` (not `cf`), with no hard-coded clone path, resolving the launcher
   from $CONFIGSYS_LAUNCHER / the `<state>/launcher` record the glue driver writes.
'''

import os
import shutil
import subprocess
import threading
import time
import types
from pathlib import Path

import pytest

from configsys import sysupdates
from configsys.componentObj import ResolvedComponent
from configsys.drivers.glue import Glue
from configsys.paths import Paths
from configsys.runner import Runner

REPO = Path(__file__).resolve().parent.parent
GLUE = REPO / 'glue'
PRELUDES = {'bash': GLUE / 'shell/bash/00-configsys.sh', 'zsh': GLUE / 'shell/zsh/00-configsys.zsh',
            'fish': GLUE / 'shell/fish/00-configsys.fish',
            'elvish': GLUE / 'shell/elvish/00-configsys.elv', 'nu': GLUE / 'shell/nu/00-configsys.nu'}


# -- 1. sysupdates generations ------------------------------------------------------------------

def _wait(pred, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_invalidate_supersedes_an_in_flight_scan(monkeypatch):
    release_old = threading.Event()
    calls = []

    def fake_gather(ctx, notes_out=None):
        n = len(calls)
        calls.append(n)
        if n == 0:
            release_old.wait(5)                     # the OLD scan is slow
            return {'apt': ['stale']}
        return {'apt': ['fresh']}

    monkeypatch.setattr(sysupdates, 'gather', fake_gather)
    ctx = types.SimpleNamespace()
    sysupdates.start_scan(ctx)
    assert _wait(lambda: calls == [0])
    assert sysupdates.scan_busy(ctx)

    sysupdates.invalidate(ctx)                       # `R` after an upgrade/refresh
    assert not sysupdates.scan_busy(ctx)             # the superseded scan doesn't count
    sysupdates.start_scan(ctx)                       # must start a FRESH scan, not return early
    assert _wait(lambda: getattr(ctx, '_sysupd_groups', None) == {'apt': ['fresh']})
    assert sysupdates.take_dirty(ctx)

    old = [t for t in threading.enumerate() if t is not ctx._sysupd_thread and t.daemon]
    release_old.set()                                # the stale scan now finishes…
    for t in old:
        t.join(2)
    assert ctx._sysupd_groups == {'apt': ['fresh']}  # …and its result is dropped
    assert not sysupdates.take_dirty(ctx)
    assert calls == [0, 1]


def test_start_scan_still_dedups_within_a_generation(monkeypatch):
    gate = threading.Event()
    calls = []

    def fake_gather(ctx, notes_out=None):
        calls.append(1)
        gate.wait(5)
        return {}

    monkeypatch.setattr(sysupdates, 'gather', fake_gather)
    ctx = types.SimpleNamespace()
    sysupdates.start_scan(ctx)
    sysupdates.start_scan(ctx)                       # same generation, in flight -> no-op
    gate.set()
    ctx._sysupd_thread.join(2)
    assert calls == [1] and ctx._sysupd_groups == {}


# -- 2. purified loaders + cfs in every prelude -------------------------------------------------

def test_bash_aliases_has_no_personal_content():
    text = (GLUE / 'bash_aliases').read_text()
    assert 'PYTHONPATH' not in text
    assert 'xdg-open' not in text and 'alias x=' not in text
    assert 'conf.d/*.sh' in text                     # still the loader


@pytest.mark.parametrize('shell', sorted(PRELUDES))
def test_every_prelude_ships_cfs_and_no_hardcoded_clone(shell):
    text = PRELUDES[shell].read_text()
    defs = {'bash': 'alias cfs=configsys', 'zsh': 'alias cfs=configsys',
            'fish': 'function cfs --wraps configsys', 'elvish': 'fn cfs {|@a| configsys $@a }',
            'nu': 'def --wrapped cfs [...args] { configsys ...$args }'}
    assert defs[shell] in text
    for old in ('alias cf=', 'fn cf ', 'def --wrapped cf ', 'function cf '):
        assert old not in text
    assert '~/src' not in text and 'HOME/src' not in text and '/src/configsys' not in text
    assert 'CONFIGSYS_LAUNCHER' in text and 'launcher' in text   # env override + the state record


def _sandbox(tmp_path):
    home = tmp_path / 'home'
    state = home / '.config' / 'configsys'
    state.mkdir(parents=True)
    fake = tmp_path / 'clone' / 'configsys.sh'
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\necho "LAUNCHED $*"\n')
    fake.chmod(0o755)
    (state / 'launcher').write_text(f'{fake}\n')
    env = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'TERM': 'dumb'}
    return home, env


SHELL_RUN = {
    'bash': lambda f: ['bash', '-c', f'shopt -s expand_aliases\n. {f}\ncfs hello world'],
    # zsh parses a whole -c string before running it, so the alias is used via eval (as at a prompt)
    'zsh': lambda f: ['zsh', '-c', f'. {f}\neval "cfs hello world"'],
    'fish': lambda f: ['fish', '--no-config', '-c', f'source {f}; cfs hello world'],
    # elvish's eval isolates namespaces, so (like the gestalt rc block) the prelude is inlined
    'elvish': lambda f: ['elvish', '-norc', '-c', f'{Path(f).read_text()}\ncfs hello world'],
}


@pytest.mark.parametrize('shell', sorted(SHELL_RUN))
def test_cfs_runs_the_recorded_launcher(tmp_path, shell):
    exe = shutil.which(shell) or (shutil.which('elvish', path=os.path.expanduser('~/apps/elvish'))
                                  if shell == 'elvish' else None)
    if exe is None:
        pytest.skip(f'{shell} not installed')
    _home, env = _sandbox(tmp_path)
    cmd = SHELL_RUN[shell](PRELUDES[shell])
    cmd[0] = exe
    out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30,
                         stdin=subprocess.DEVNULL)
    assert 'LAUNCHED hello world' in out.stdout, (out.stdout, out.stderr)


def test_glue_hookup_records_the_launcher(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'configsys.sh').write_text('#!/bin/sh\n')
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(repo),
                   'CONFIGSYS_GLUE_SHELLS': 'fish'})
    p.home.mkdir(parents=True)
    g = Glue(Runner(pretend=False), p)
    rc = ResolvedComponent(key='glue\\shell-glue', driver='glue', comp='shell-glue',
                           fields={'loader': 'all'})
    assert g.install(rc).ok
    assert (p.state_dir / 'launcher').read_text() == f'{(repo / "configsys.sh").resolve()}\n'


def test_pretend_hookup_records_nothing(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'configsys.sh').write_text('#!/bin/sh\n')
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(repo),
                   'CONFIGSYS_GLUE_SHELLS': 'fish'})
    g = Glue(Runner(pretend=True), p)
    g.install(ResolvedComponent(key='glue\\shell-glue', driver='glue', comp='shell-glue',
                                fields={'loader': 'all'}))
    assert not (p.state_dir / 'launcher').exists()


# -- 3. listing staged glue is read-only (safe under --pretend) ---------------------------------

def test_list_staged_does_not_migrate_unless_asked(tmp_path):
    from configsys import shellguard
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo')})
    old = p.user_dotfiles_dir / 'staged-glue' / 'nvm.bash.sh'
    old.parent.mkdir(parents=True)
    old.write_text('export NVM_DIR=x\n')
    shellguard.stage(p, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n'})

    rows = shellguard.list_staged(p)                       # default: pure listing
    assert ('nvm', 'bash', old) in rows                    # the old-layout block, listed in place
    assert ('sdkman', 'bash', p.state_dir / 'staged-glue' / 'bash' / 'sdkman.sh') in rows
    assert old.is_file()                                   # nothing moved
    assert not (p.state_dir / 'staged-glue' / 'bash' / 'nvm.sh').exists()
    assert shellguard.staged_for(p, 'nvm') == [('bash', old)] and old.is_file()

    rows = shellguard.list_staged(p, migrate=True)         # explicit: moves it into state
    assert not old.exists()
    assert ('nvm', 'bash', p.state_dir / 'staged-glue' / 'bash' / 'nvm.sh') in rows


def test_discard_migrates_then_drops_an_old_layout_block(tmp_path):
    from configsys import shellguard
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo')})
    old = p.user_dotfiles_dir / 'staged-glue' / 'nvm.bash.sh'
    old.parent.mkdir(parents=True)
    old.write_text('x\n')
    assert shellguard.discard(p, 'nvm') == 1
    assert shellguard.list_staged(p) == []
