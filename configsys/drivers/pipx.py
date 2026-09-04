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
import re
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

    @staticmethod
    def _norm(dist):
        '''PEP 503 normalized project name: lowercase, runs of -_. collapsed to one -. pipx keys its
        `list` venvs by this (e.g. route `Faker` -> venv `faker`), so presence lookups must match on
        the normalized form, not the raw route name.'''
        return re.sub(r'[-_.]+', '-', str(dist)).strip().lower()

    # -- read -------------------------------------------------------------

    def installed_index(self):
        '''ONE `pipx list --json` -> {dist: version}. Feeds BOTH the inspect batch and the
        coexistence detector, so N pipx units cost one call, not one per unit. None on failure.
        As a side effect it caches each venv's interpreter (for python-aware get_latest).'''
        r = self.runner.run(f'{_PIPX} list --json')
        if not r.ok or not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        idx, pys = {}, {}
        for dist, venv in (data.get('venvs') or {}).items():
            meta = venv.get('metadata') or {}
            ver = (meta.get('main_package') or {}).get('package_version')
            if ver:
                idx[dist] = ver
            pv = meta.get('python_version')                # e.g. "Python 3.10.12"
            if pv:
                pys[self._norm(dist)] = pv
        self._pyver_cache = pys
        return idx

    def batch_index(self, rcs):
        return self.installed_index() or {}

    def batch_installed_index(self, batch):
        return batch if isinstance(batch, dict) else None   # the batch IS the installed index

    def get_version(self, rc):
        idx = self._batch if self._batch is not None else self.installed_index()
        if not idx:
            return None
        want = self._dist(rc)
        if want in idx:                                    # exact hit (already-normalized route name)
            return idx[want]
        want = self._norm(want)                            # else match PEP 503-normalized (Faker->faker)
        return next((v for d, v in idx.items() if self._norm(d) == want), None)

    def _venv_pythons(self):
        '''{norm_dist: "Python X.Y.Z"} — the interpreter each installed venv runs. Populated as a
        side effect of the batch's installed_index; parsed on demand for a single-component call.'''
        if getattr(self, '_pyver_cache', None) is None:
            self.installed_index()
            if getattr(self, '_pyver_cache', None) is None:
                self._pyver_cache = {}                     # probe failed -> don't retry per component
        return self._pyver_cache

    def _target_python(self, rc):
        '''The interpreter get_latest should judge requires_python against. A `python:` route pin is
        the INTENT — scope to it even when the current venv is on an older interpreter, so a pin that
        would reach a newer release reads as an available upgrade (the `pipx reinstall --python` path
        then rebuilds the venv and applies it). No pin -> the installed venv's python (reality — a
        release that dropped it is unreachable). Neither -> None (absolute latest; a fresh unpinned
        install uses pipx's default interpreter).'''
        pin = rc.fields.get('python')
        m = re.search(r'(\d+\.\d+)', str(pin)) if pin else None
        if m:
            return m.group(1)                              # "python3.12" / "/usr/bin/python3.13" -> "3.12"
        pv = self._venv_pythons().get(self._norm(self._dist(rc)))
        m = re.search(r'(\d+\.\d+(?:\.\d+)?)', pv) if pv else None
        return m.group(1) if m else None                  # "Python 3.10.12" -> "3.10.12"

    def get_latest(self, rc):
        v = self.resolve_version(rc)                       # an explicit `version:` spec wins if present
        if v is not None:
            return v
        # otherwise the pipx `name` IS a PyPI distribution -> query PyPI. Scope it to the venv's
        # interpreter so we report the newest release pipx could actually UPGRADE to (a package can
        # publish a newer version that drops old pythons — pywal16 3.8.15 needs >=3.11 but a 3.10 venv
        # caps at 3.8.10; reporting 3.8.15 there would read outdated with no way to move).
        from .. import versions
        spec = {'pypi': self._dist(rc)}
        py = self._target_python(rc)
        if py:
            spec['python'] = py
        return versions.discover(spec, self.paths, offline=self._offline())

    def _suggest_pin(self, requires_python):
        '''The lowest `python3.NN` we ship a component for that satisfies `requires_python`
        (e.g. ">=3.11" -> "python3.11"), so the advisory can name a concrete, installable pin.'''
        from packaging.specifiers import SpecifierSet, InvalidSpecifier
        try:
            spec = SpecifierSet(requires_python)
        except (InvalidSpecifier, TypeError):
            return None
        return next((f'python3.{n}' for n in (11, 12, 13) if f'3.{n}.0' in spec), None)

    def version_advisory(self, rc):
        '''`configsys versions` heads-up: ONE line when this venv's python CAPS the installable
        version below PyPI's absolute latest — naming the gating python and the pin that lifts it.
        None when uncapped or unknowable. Interactive-only (does its own PyPI read; never the inspect
        hot path). This is the "soft max-ceiling" surfacing — not a hard floor.'''
        if self.resolve_version(rc) is not None:    # an explicit version: spec -> not python-scoped
            return None
        py = self._target_python(rc)
        if not py:
            return None
        from .. import versions
        try:
            data = json.loads(versions.http_fetch(versions.PYPI_LATEST.format(dist=self._dist(rc))))
        except Exception:                           # noqa: BLE001 — advisory must never break the report
            return None
        absolute = (data.get('info') or {}).get('version')
        scoped = versions._pypi_latest_for_python(data, py)
        if not absolute or not scoped or absolute == scoped:
            return None                             # uncapped (the pinned/venv python reaches latest)
        files = (data.get('releases') or {}).get(absolute) or []
        need = files[0].get('requires_python') if files else None
        pin = self._suggest_pin(need) if need else None
        need_txt = f'python {need}' if need else 'a newer python'
        tail = f' — pin `python: {pin}`' if pin else ''
        return f'python {py} caps this at {scoped}; {absolute} needs {need_txt}{tail}'

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
