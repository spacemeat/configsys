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

    def explicit_keys(self):
        '''Cross-distro: keep only the dists PIP ITSELF installed (INSTALLER=pip), dropping the
        OS-packaged Python modules that `pip list` also enumerates — apt `python3-*`, dnf/pacman/
        zypper/apk equivalents all land in the interpreter's site and would otherwise flood the
        orphan scan. pip records `INSTALLER=pip` in each dist it installs; no distro package manager
        writes that, so it's the same "the user chose it" signal apt-mark gives for native packages.
        Read from `pip list -v`'s Installer column (present since pip ~19). Names PEP-503-normalized
        to match installed_index. None on failure / no Installer column -> no filtering (list all).'''
        r = self.runner.run(f'{_PIP} list -v')
        if not r.ok or not r.stdout:
            return None
        lines = r.stdout.splitlines()
        hdr = next((i for i, ln in enumerate(lines) if 'Installer' in ln and 'Package' in ln), None)
        if hdr is None or hdr + 2 > len(lines):
            return None                               # no Installer column (ancient pip) -> don't filter
        col = lines[hdr].index('Installer')           # columns are padded to a fixed width: same start
        out = set()                                   #   index in the header and every data row
        for ln in lines[hdr + 2:]:                    # skip the header and its `---` separator row
            if not ln.strip():
                continue
            installer = ln[col:].strip() if len(ln) > col else ''
            if installer == 'pip':
                out.add(_norm(ln.split(' ', 1)[0]))
        return out

    def batch_index(self, rcs):
        return self.installed_index() or {}

    @staticmethod
    def _pip(rc):
        # interpreter-pin: `python: python3.12` on the binding installs into THAT python's user site;
        # default is the system python3. `python3.X -m pip` (not bare pip) keeps the interpreter explicit.
        return f'{shlex.quote(str(rc.fields.get("python") or "python3"))} -m pip'

    def get_version(self, rc):
        if rc.fields.get('python'):
            # a pinned interpreter's user site — probe IT (the batch enumerates the default python only)
            r = self.runner.run(f'{self._pip(rc)} show {shlex.quote(self._dist(rc))}')
            if not r.ok or not r.stdout:
                return None
            m = _VERSION_RE.search(r.stdout)
            return m.group(1).strip() if m else None
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
            f'{self._pip(rc)} install --user {shlex.quote(self._dist(rc))}', capture=False)

    def uninstall(self, rc):
        return self.runner.run(
            f'{self._pip(rc)} uninstall -y {shlex.quote(self._dist(rc))}', capture=False)

    def upgrade(self, rc):
        return self.runner.run(
            f'{self._pip(rc)} install --user --upgrade {shlex.quote(self._dist(rc))}',
            capture=False)

    def set_version(self, rc, version):
        spec = f'{self._dist(rc)}=={version}'
        return self.runner.run(f'{self._pip(rc)} install --user {shlex.quote(spec)}',
                               capture=False)

    def lock(self, rc):
        return Result('(pip lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pip unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin'
