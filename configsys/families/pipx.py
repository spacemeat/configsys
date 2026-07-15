'''pipx.py — the \\pipx family: PyPI CLIs in isolated venvs via pipx.

User-space (pipx puts app binaries on ~/.local/bin, each in its own venv). Version
state comes from `pipx list --json`; no native version lock, so lock intent lives
in the ledger. The `pipx` tool itself is the family `!depends` — and it is the
version-sensitive part: modern OSs route it to apt, older ones bootstrap it with
`pip install --user pipx` (the \\pip family). See routes.hu.

get_latest resolves from pypi.org only when the route carries a
`version: { pypi: <dist> }` spec (cached).
'''

import json
import shlex

from ..component import Family
from ..runner import Result

# Invoke via the module, not the bare `pipx` script: right after a pip --user
# bootstrap the script isn't on PATH in the non-interactive runner shell, but the
# module is importable (works the same whether pipx came from apt or pip).
_PIPX = 'python3 -m pipx'


class Pipx(Family):
    name = 'pipx'
    privileged = False

    @staticmethod
    def _dist(rc):
        return rc.name  # route `name` field is the PyPI distribution (== the command)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'{_PIPX} list --json')
        if not r.ok or not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        venv = (data.get('venvs') or {}).get(self._dist(rc))
        if not venv:
            return None
        main = (venv.get('metadata') or {}).get('main_package') or {}
        return main.get('package_version')

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'{_PIPX} install {shlex.quote(self._dist(rc))}',
                               capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'{_PIPX} uninstall {shlex.quote(self._dist(rc))}',
                               capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'{_PIPX} upgrade {shlex.quote(self._dist(rc))}',
                               capture=False)

    def set_version(self, rc, version):
        spec = f'{self._dist(rc)}=={version}'
        # --force overwrites an existing venv (e.g. a downgrade, or a prior pip install)
        return self.runner.run(f'{_PIPX} install --force {shlex.quote(spec)}',
                               capture=False)

    def lock(self, rc):
        return Result('(pipx lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pipx unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin'
