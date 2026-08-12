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


def _norm(name):
    # PEP 503: distribution names are case-insensitive and treat runs of -_. as equivalent.
    return re.sub(r'[-_.]+', '-', name.strip().lower())


class Pip(Driver):
    name = 'pip'
    privileged = False

    @staticmethod
    def _dist(rc):
        return rc.name  # route `name` field is the PyPI distribution (== the command)

    # -- read -------------------------------------------------------------

    def installed_index(self):
        '''ONE `pip list --format=json` -> {normalized-dist: version}, PEP-503-normalized so lookups
        match regardless of case / -_. spelling. Feeds BOTH the inspect batch and the coexistence
        detector (N pip units -> one call). None on failure.'''
        import json
        r = self.runner.run(f'{_PIP} list --format=json')
        if not r.ok or not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        return {_norm(e['name']): e['version'] for e in data
                if isinstance(e, dict) and e.get('name') and e.get('version')}

    def index_key(self, rc):
        return _norm(self._dist(rc))                  # match installed_index's normalized keys

    def batch_index(self, rcs):
        return self.installed_index() or {}

    def get_version(self, rc):
        idx = self._batch if self._batch is not None else self.installed_index()
        return idx.get(_norm(self._dist(rc))) if idx else None

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
