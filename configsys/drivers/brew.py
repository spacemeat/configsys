'''brew.py — the Homebrew driver: formulae via `brew`.

Entirely user-space (no sudo): modern Homebrew installs into a user-owned prefix
(/opt/homebrew on Apple Silicon, /home/linuxbrew/.linuxbrew on Linux, /usr/local on
Intel macOS) and every op runs as the invoking user. This is the blessed CLI path on
atomic/immutable distros (Bazzite/Bluefin/Aurora ship brew pre-configured) — see
docs/immutable-distros.md — and the same tool on macOS, so this driver is also the
foundation for eventual macOS support.

Version state: `brew list --versions` (installed) and `brew info --json` (latest
available from the tap). Native version lock is real: `brew pin`/`unpin`. Bootstrapping
brew itself is a separate concern (a `homebrew` prereq component / env-provided on
atomic), not this driver's job — this driver assumes `brew` is on PATH and degrades to
"not installed" when it isn't.

Formulae only for now; macOS GUI *casks* (`brew install --cask`) are a future `cask:`
field — the op structure below is already cask-ready.
'''

import json
import shlex

from ..driver import Driver
from ..runner import Result


class Brew(Driver):
    name = 'brew'
    privileged = False
    default_scope = 'user'   # brew's prefix is user-owned; ops never sudo

    @staticmethod
    def _formula(rc):
        return rc.name  # route `name` field is the formula (name-map key: `brew`)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        f = self._formula(rc)
        r = self.runner.run(f'brew list --versions {shlex.quote(f)}')
        if not r.ok or not r.stdout.strip():
            return None
        # "<formula> <ver> [<ver>...]" — a keg may have several; the last is newest.
        for line in r.stdout.splitlines():
            toks = line.split()
            if len(toks) >= 2 and toks[0] == f:
                return toks[-1]
        return None

    def get_latest(self, rc):
        # the tap's stable version (offline once `brew update` has run); no spec needed.
        r = self.runner.run(
            f'brew info --json=v2 --formula {shlex.quote(self._formula(rc))}')
        if not r.ok or not r.stdout.strip():
            return None
        try:
            data = json.loads(r.stdout)
            return (data['formulae'][0]['versions']['stable']) or None
        except (ValueError, KeyError, IndexError, TypeError):
            return None

    def is_locked(self, rc):
        r = self.runner.run('brew list --pinned')
        if not r.ok:
            return False
        return self._formula(rc) in r.stdout.split()

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'brew install {shlex.quote(self._formula(rc))}',
                               capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'brew uninstall {shlex.quote(self._formula(rc))}',
                               capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'brew upgrade {shlex.quote(self._formula(rc))}',
                               capture=False)

    def set_version(self, rc, version):
        # brew is latest-oriented: an exact old version is only reachable when the tap
        # ships a versioned formula (e.g. python@3.11). Best-effort install of that
        # variant; brew reports clearly if `<formula>@<version>` doesn't exist.
        spec = f'{self._formula(rc)}@{version}'
        return self.runner.run(f'brew install {shlex.quote(spec)}', capture=False)

    def lock(self, rc):
        return self.runner.run(f'brew pin {shlex.quote(self._formula(rc))}',
                               capture=False)

    def unlock(self, rc):
        return self.runner.run(f'brew unpin {shlex.quote(self._formula(rc))}',
                               capture=False)

    def location(self, rc):
        r = self.runner.run(f'brew --prefix {shlex.quote(self._formula(rc))}')
        if r.ok and r.stdout.strip():
            return r.stdout.strip()
        return '(homebrew)'
