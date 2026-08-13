'''pyenv.py — the pyenv driver: a Python version compiled from source, user-scope.

pyenv builds CPython under ~/.pyenv/versions/<X.Y.Z> and never touches the system python. A
`via: pyenv` binding's `version:` field is the minor LINE (e.g. "3.11"); pyenv resolves it to the
latest patch and compiles it. The pyenv tool itself + the C build deps are the driver `requires:`
(pyenv, python-build-deps). No native version lock — lock intent lives in the ledger. Installs stream
(a source compile). Runs pyenv by its explicit path, since the driver acts before any shell `pyenv init`.
'''

import shlex
from pathlib import Path

from ..driver import Driver
from ..runner import Result


class Pyenv(Driver):
    name = 'pyenv'
    privileged = False

    def _pyenv(self):
        home = self.paths.home if self.paths is not None else Path.home()
        root = home / '.pyenv'
        return f'PYENV_ROOT={shlex.quote(str(root))} {shlex.quote(str(root / "bin" / "pyenv"))}'

    @staticmethod
    def _line(rc):
        return str(rc.fields.get('version') or rc.comp)   # the minor line, e.g. "3.11"

    def _installed(self):
        r = self.runner.run(f'{self._pyenv()} versions --bare --skip-aliases')
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.ok else []

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # the newest installed patch whose X.Y matches the requested line (3.11 -> 3.11.9)
        line = self._line(rc)
        matches = sorted(v for v in self._installed() if v == line or v.startswith(line + '.'))
        return matches[-1] if matches else None

    def get_latest(self, rc):
        # pyenv's latest KNOWN patch for the line (local version DB; may lag until `pyenv update`)
        r = self.runner.run(f'{self._pyenv()} latest --known {shlex.quote(self._line(rc))}')
        return r.stdout.strip() if (r.ok and r.stdout.strip()) else None

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        # `pyenv install 3.11` resolves to the latest 3.11.x and compiles it; -s skips if present
        return self.runner.run(f'{self._pyenv()} install -s {shlex.quote(self._line(rc))}',
                               capture=False)

    def uninstall(self, rc):
        v = self.get_version(rc)
        if not v:
            return Result(f'(pyenv: {self._line(rc)} not installed)', 0)
        return self.runner.run(f'{self._pyenv()} uninstall -f {shlex.quote(v)}', capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # (re)installs the latest patch for the line

    def set_version(self, rc, version):
        return self.runner.run(f'{self._pyenv()} install -s {shlex.quote(version)}', capture=False)

    def lock(self, rc):
        return Result('(pyenv lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pyenv unlock recorded in ledger)', 0)

    def location(self, rc):
        return f'~/.pyenv/versions/{self._line(rc)}.*'
