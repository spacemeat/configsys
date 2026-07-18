'''pip.py — the pip driver: PyPI console-script CLIs via `pip install --user`.

User-space (installs to ~/.local/bin, no sudo), the Python analog of the cargo
driver. Version state comes from `pip show`; there's no native version lock, so
lock intent lives in the ledger. `python3 -m pip` is used (not bare `pip`/`pip3`)
to avoid PATH ambiguity; python3-pip is the driver `!depends`.

get_latest resolves from pypi.org only when the route carries a
`version: { pypi: <dist> }` spec (cached); otherwise no "latest" is reported.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_VERSION_RE = re.compile(r'^Version:\s*(.+)$', re.MULTILINE)

_PIP = 'python3 -m pip'


class Pip(Driver):
    name = 'pip'
    privileged = False

    @staticmethod
    def _dist(rc):
        return rc.name  # route `name` field is the PyPI distribution (== the command)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'{_PIP} show {shlex.quote(self._dist(rc))}')
        if not r.ok or not r.stdout:
            return None
        m = _VERSION_RE.search(r.stdout)
        return m.group(1).strip() if m else None

    def get_latest(self, rc):
        # a `version: { pypi: <dist> }` route discovers the latest from pypi.org
        # (cached); dists without a spec report no "latest".
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'{_PIP} install --user {shlex.quote(self._dist(rc))}', capture=False)

    def uninstall(self, rc):
        return self.runner.run(
            f'{_PIP} uninstall -y {shlex.quote(self._dist(rc))}', capture=False)

    def upgrade(self, rc):
        return self.runner.run(
            f'{_PIP} install --user --upgrade {shlex.quote(self._dist(rc))}',
            capture=False)

    def set_version(self, rc, version):
        spec = f'{self._dist(rc)}=={version}'
        return self.runner.run(f'{_PIP} install --user {shlex.quote(spec)}',
                               capture=False)

    def lock(self, rc):
        return Result('(pip lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pip unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin'
