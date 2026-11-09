'''pip.py — the pip driver: PyPI console-script CLIs via `pip install --user`.

User-space (installs to ~/.local/bin, no sudo), the Python analog of the cargo
driver. Version state comes from `pip list --user`: ONLY the user site counts, because
that is the only place this driver installs. A plain `pip list` also enumerates the
distro's own Python packages (apt's `pipx` package is the dist `pipx` in
/usr/lib/python3/dist-packages), which would read as a pip install of that component —
a false "also present" / stranded install that a method switch then tries to `pip
uninstall`. There's no native version lock, so lock intent lives in the ledger.
`python3 -m pip` is used (not bare `pip`/`pip3`) to avoid PATH ambiguity; the driver
`requires: python3-pip` (routes.hu `drivers:`).

PEP 668: on an externally-managed interpreter (Debian 12+, Ubuntu 23.04+, …) pip refuses
`uninstall` as well as `install`. Removing a dist from the USER site can't break the
distro's packages, so uninstall runs only when the dist is in the user site, with
PIP_BREAK_SYSTEM_PACKAGES=1 (an env var, so a pip too old to know the option ignores it).
Install/upgrade stay strict: putting user-site packages ahead of the distro's is exactly
what PEP 668 guards against, so they fail loudly there instead of overriding it.

get_latest resolves from pypi.org only when the route carries a
`version: { pypi: <dist> }` spec (cached); otherwise no "latest" is reported.
'''

import re
import shlex

from ..runner import Result
from ._module import ModuleDriver, pep503_name as _norm

_PIP = 'python3 -m pip'


class Pip(ModuleDriver):
    name = 'pip'
    TOOL = _PIP
    CMDS = {'install': '{tool} install --user {pkg}',
            'uninstall': 'PIP_BREAK_SYSTEM_PACKAGES=1 {tool} uninstall -y {pkg}',
            'upgrade': '{tool} install --user --upgrade {pkg}',
            'set_version': '{tool} install --user {spec}'}
    VERSION_SPEC = '{pkg}=={ver}'
    BIN_DIR = '~/.local/bin'

    # -- read -------------------------------------------------------------

    def installed_index(self):
        '''ONE `pip list --user --format=json` -> {normalized-dist: version}, PEP-503-normalized so lookups
        match regardless of case / -_. spelling. Feeds BOTH the inspect batch and the coexistence
        detector (N pip units -> one call). None on failure.'''
        return self._user_index(_PIP)

    def _user_index(self, pip):
        '''`<pip> list --user --format=json` -> {normalized-dist: version}: the user site only (see
        the module docstring — distro-packaged dists aren't pip installs). None on failure.'''
        import json
        r = self.runner.run(f'{pip} list --user --format=json')
        if not r.ok or not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        if not isinstance(data, list):
            return None
        return {_norm(e['name']): e['version'] for e in data
                if isinstance(e, dict) and e.get('name') and e.get('version')}

    def index_key(self, rc):
        return _norm(self.module(rc))                  # match installed_index's normalized keys

    def explicit_keys(self):
        '''Cross-distro: keep only the dists PIP ITSELF installed (INSTALLER=pip) in the user site,
        dropping anything another installer wrote there (the listing is `--user`, so the distro's
        own `python3-*` modules in the system site never appear; this guards the rest of the
        orphan scan the same way). pip records `INSTALLER=pip` in each dist it installs; no distro package manager
        writes that, so it's the same "the user chose it" signal apt-mark gives for native packages.
        `--not-required` further drops pip-pulled DEPENDENCIES (the pip analog of apt's manual-not-
        auto), leaving the top-level dists the user actually asked for. Read from `pip list -v`'s
        Installer column (present since pip ~19). Names PEP-503-normalized to match installed_index.
        None on failure / no Installer column -> no filtering (list all).'''
        r = self.runner.run(f'{_PIP} list --user --not-required -v')
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

    def batch_installed_index(self, batch):
        return batch if isinstance(batch, dict) else None   # the batch IS the installed index

    def tool(self, rc=None):
        return self._pip(rc) if rc is not None else _PIP

    @staticmethod
    def _pip(rc):
        # interpreter-pin: `python: python3.12` on the binding installs into THAT python's user site;
        # default is the system python3. `python3.X -m pip` (not bare pip) keeps the interpreter explicit.
        return f'{shlex.quote(str(rc.fields.get("python") or "python3"))} -m pip'

    def get_version(self, rc):
        if rc.fields.get('python'):
            # a pinned interpreter's user site — probe IT (the batch enumerates the default python only)
            idx = self._user_index(self._pip(rc))
            return idx.get(_norm(self.module(rc))) if idx else None
        idx = self.batch if self.batch is not None else self.installed_index()
        return idx.get(_norm(self.module(rc))) if idx else None

    def _disco_spec(self, rc):
        '''A `version: { pypi: <dist> }` spec scoped to the interpreter pip installs into (the
        `python:` pin, else the default python3), so "latest" is the newest release whose
        requires_python admits it — what `pip install --upgrade` can actually reach. pipx 1.18 needs
        Python >= 3.11: on a 3.10 system pip stops at 1.17.x, and the absolute latest read outdated
        forever ("Requirement already satisfied"). The pipx driver scopes the same way.'''
        spec = super()._disco_spec(rc)
        if isinstance(spec, dict) and spec.get('pypi') and not spec.get('python'):
            py = self._python_version(rc)
            if py:
                spec = {**spec, 'python': py}
        return spec

    def _python_version(self, rc):
        '''"3.10.12" for the interpreter `rc` installs into, probed once per interpreter per runner
        (each unit builds a fresh driver, so the cache lives on the runner); None when it can't be asked (a --pretend run, no such python).'''
        cache = self.runner.__dict__.setdefault('_pip_pyver', {})   # per runner: each unit gets a fresh driver (C4)
        interp = str(rc.fields.get('python') or 'python3')
        if interp not in cache:
            r = self.runner.run(f'{shlex.quote(interp)} -c '
                                '"import sys; print(\'%d.%d.%d\' % sys.version_info[:3])"')
            out = (r.stdout or '').strip() if r.ok else ''
            cache[interp] = out if re.fullmatch(r'\d+\.\d+\.\d+', out) else None
        return cache[interp]

    # -- mutate -----------------------------------------------------------

    def uninstall(self, rc):
        cmd = self.command('uninstall', rc)
        if not getattr(self.runner, 'pretend', False):
            idx = self._user_index(self._pip(rc))
            if idx is not None and _norm(self.module(rc)) not in idx:
                # nothing of ours to remove: a same-named dist elsewhere belongs to the distro (or a
                # venv), and `pip uninstall` would reach for it (PEP 668 refusal / "installed by debian")
                return Result(cmd, 0, stdout=f'{self.module(rc)}: not installed in the user site; nothing to remove')
        return self.runner.run(cmd, capture=False)
