'''pipx.py — the pipx driver: PyPI CLIs in isolated venvs via pipx.

User-space (pipx puts app binaries on ~/.local/bin, each in its own venv). Version
state comes from `pipx list --json`; no native version lock, so lock intent lives
in the ledger. The `pipx` tool itself is the driver `!depends` — and it is the
version-sensitive part: modern OSs route it to apt, older ones bootstrap it with
`pip install --user pipx` (the pip driver). See routes.hu.

get_latest resolves from pypi.org only when the route carries a
`version: { pypi: <dist> }` spec (cached).
'''

import json
import shlex

from ..driver import Driver
from ..runner import Result

# Invoke via the module, not the bare `pipx` script: right after a pip --user
# bootstrap the script isn't on PATH in the non-interactive runner shell, but the
# module is importable (works the same whether pipx came from apt or pip).
_PIPX = 'python3 -m pipx'

# pipx prefers a `uv` backend to build its venvs when uv is on PATH, but a uv older than pipx needs
# makes it ABORT. `_UV_MIN` is that floor for the current pipx line — below it we pick pipx's
# always-present pip backend UP FRONT (same pipx method + venv, just a different internal installer),
# with a note, rather than letting pipx discover the mismatch by failing. Bump if pipx raises it.
_UV_MIN = '0.9.17'


class Pipx(Driver):
    name = 'pipx'
    privileged = False

    @staticmethod
    def _dist(rc):
        return rc.name  # route `name` field is the PyPI distribution (== the command)

    # -- read -------------------------------------------------------------

    def installed_index(self):
        '''ONE `pipx list --json` -> {dist: version}. Feeds BOTH the inspect batch and the
        coexistence detector, so N pipx units cost one call, not one per unit. None on failure.'''
        r = self.runner.run(f'{_PIPX} list --json')
        if not r.ok or not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        idx = {}
        for dist, venv in (data.get('venvs') or {}).items():
            ver = ((venv.get('metadata') or {}).get('main_package') or {}).get('package_version')
            if ver:
                idx[dist] = ver
        return idx

    def batch_index(self, rcs):
        return self.installed_index() or {}

    def get_version(self, rc):
        idx = self._batch if self._batch is not None else self.installed_index()
        return idx.get(self._dist(rc)) if idx else None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    @staticmethod
    def _py_flag(rc):
        # interpreter-pin: `python: python3.12` builds the app's venv with that interpreter (pipx finds
        # it on PATH). Default: pipx's own default python. Only the venv-creating ops take it.
        py = rc.fields.get('python')
        return f'--python {shlex.quote(str(py))} ' if py else ''

    def _backend(self):
        '''pipx's venv backend, chosen UP FRONT and cached per driver instance: `--backend pip ` (with
        a one-line note) when a uv is on PATH but older than `_UV_MIN`; otherwise `''` (pipx's default
        — uv when it's present and new enough, pip when uv is absent). Read-only; same pipx method +
        venv either way. Cached so a batch probes uv (and notes) once, not per component.'''
        cached = getattr(self, '_backend_flag', None)
        if cached is not None:
            return cached
        from ..versionsweep import _pv, meets
        flag = ''
        r = self.runner.run('uv --version')                    # captured probe; fails if uv absent
        if r.ok and r.stdout:
            parts = r.stdout.split()
            ver = parts[1] if len(parts) > 1 else ''
            if _pv(ver) is not None and not meets(ver, f'>={_UV_MIN}'):
                self.runner.echo(f'pipx: using its pip backend (installed uv {ver} < {_UV_MIN} '
                                 f'needed for pipx’s uv backend)')
                flag = '--backend pip '
        self._backend_flag = flag
        return flag

    def install(self, rc):
        return self.runner.run(
            f'{_PIPX} install {self._backend()}{self._py_flag(rc)}{shlex.quote(self._dist(rc))}',
            capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'{_PIPX} uninstall {shlex.quote(self._dist(rc))}',
                               capture=False)

    def upgrade(self, rc):
        py = self._py_flag(rc)
        if py:
            # a pinned interpreter can't be applied by `pipx upgrade` (reuses the venv's python), and
            # `pipx install --force` IGNORES --python — `pipx reinstall` is the ONE that rebuilds the
            # venv with a new interpreter. It re-resolves the (unpinned) spec, so it also picks up the
            # latest — an interpreter-aware upgrade. e.g. mitmproxy 12 needs py>=3.12; a py3.10 venv
            # silently caps upgrades at 11.x.
            return self.runner.run(
                f'{_PIPX} reinstall {self._backend()}{py}{shlex.quote(self._dist(rc))}',
                capture=False)
        return self.runner.run(f'{_PIPX} upgrade {shlex.quote(self._dist(rc))}', capture=False)

    def set_version(self, rc, version):
        spec = f'{self._dist(rc)}=={version}'
        # --force overwrites an existing venv (e.g. a downgrade, or a prior pip install)
        return self.runner.run(
            f'{_PIPX} install {self._backend()}--force {self._py_flag(rc)}{shlex.quote(spec)}',
            capture=False)

    def lock(self, rc):
        return Result('(pipx lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pipx unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin'
