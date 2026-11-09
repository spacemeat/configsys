'''Shared test doubles and builders (review-2026-11-2 tests-tools-15).

- `FakeRunner` — the recording stand-in for `configsys.runner.Runner`: canned `Result`s matched by
  substring, every command recorded in `calls`. Its `run` accepts every keyword the real
  `Runner.run` does (test_fakes.py checks the signatures against each other), so a new runner
  parameter can't silently break thirty copies again.
- `git(cwd, *args)` — run git in a test repo, stdout stripped.
- `primary_remote(tmp_path, files)` — a bare remote seeded with a primary plugin `prim`, blessed
  into a sandbox home (the `primary` fixture in conftest.py is built on it).

Import from a test module as `from fakes import FakeRunner` (test/ is on sys.path under pytest).
'''

import subprocess

from configsys.runner import Result


class FakeRunner:
    '''Records commands and returns canned Results: `responses` is [(needle, returncode, stdout)],
    the first needle found in the command wins; anything else succeeds with empty output. A
    `sudo=True` call is recorded as `sudo <cmd>` (the real runner's readable form).'''

    pretend = False

    def __init__(self, responses=None, default=(0, '')):
        self.responses = responses or []
        self.default = default
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None,
            presudo=False, timeout=None, **_future):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        code, out = self.default
        return Result(full, code, stdout=out)

    def echo(self, msg):
        pass                       # a driver's progress note; a no-op for the stub


def git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


PLUGIN_HU = '{ name: prim  requires-abi: 1  data: [ p.hu ] }\n'
# the primary's data file in the `primary` fixture: this machine's picks plus two other machines'
BASE_P = '{ picks: {\n    this-machine: [ btop ]\n    laptop: [ htop ]\n    desk: [ jq ]\n} }\n'


def primary_remote(tmp_path, files, *, seed='seed', home=None, os_arg='pop'):
    '''A bare remote `<tmp>/prim` whose first commit holds `plugin.hu` plus `files` ({relative path:
    text}), pushed from the clone `<tmp>/<seed>`, then blessed as the primary of the sandbox home
    (`<tmp>/home` unless given). -> (base argv, the synced clone, the bare remote, the seed clone).
    The git identity comes from conftest's `_hermetic`.'''
    from configsys.app import main
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    seed_dir = tmp_path / seed
    subprocess.run(['git', 'clone', '-q', str(bare), str(seed_dir)], check=True, capture_output=True)
    (seed_dir / 'plugin.hu').write_text(PLUGIN_HU)
    for rel, text in files.items():
        (seed_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed_dir / rel).write_text(text)
    git(seed_dir, 'add', '-A'); git(seed_dir, 'commit', '-qm', 'A'); git(seed_dir, 'push', '-q', 'origin', 'main')
    home = home or tmp_path / 'home'
    base = ['--home', str(home), '--os', os_arg, '-q']
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    return base, home / '.config' / 'configsys' / 'plugins' / 'prim', bare, seed_dir
