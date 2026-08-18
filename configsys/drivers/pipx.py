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

    def _run(self, tail):
        '''Run `pipx <tail>` (streamed); if pipx aborts because its DEFAULT uv backend is unusable —
        a resident uv too old for this pipx (its `--backend pip` fallback is what fixes the whole
        pipx cluster failing at once) — transparently retry with `--backend pip` inserted after the
        subcommand, so the install still succeeds. pipx prints the literal hint "run with `--backend
        pip`" only on that abort, so it's a precise, pipx-version-agnostic trigger.'''
        res = self.runner.run(f'{_PIPX} {tail}', capture=False)
        if res.ok or '--backend pip' not in res.output:
            return res
        sub, _, rest = tail.partition(' ')
        return self.runner.run(f'{_PIPX} {sub} --backend pip {rest}', capture=False)

    def install(self, rc):
        return self._run(f'install {self._py_flag(rc)}{shlex.quote(self._dist(rc))}')

    def uninstall(self, rc):
        return self.runner.run(f'{_PIPX} uninstall {shlex.quote(self._dist(rc))}',
                               capture=False)

    def upgrade(self, rc):
        return self._run(f'upgrade {shlex.quote(self._dist(rc))}')

    def set_version(self, rc, version):
        spec = f'{self._dist(rc)}=={version}'
        # --force overwrites an existing venv (e.g. a downgrade, or a prior pip install)
        return self._run(f'install --force {self._py_flag(rc)}{shlex.quote(spec)}')

    def lock(self, rc):
        return Result('(pipx lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pipx unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin'
