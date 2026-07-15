'''gcc.py — the \\gcc family: versioned compilers via apt + update-alternatives.

Each component is a specific version (gcc-13, gcc-16, ...). Installing one adds the
toolchain PPA if named, installs the version's packages (gcc-13 + its slaves like
g++-13), and registers an update-alternatives group — `gcc` as master, `g++` (etc.)
as slaves, priority = the version number — so switching gcc carries g++ along.

configsys does NOT switch the active version; that's `update-alternatives --config`
(or your own alias). System-scoped (apt + alternatives need root). Route fields:
  link     the master tool / alternative name (gcc)
  version  the version number (also the priority and package suffix)
  slaves   [g++, cpp, ...]  registered as slaves of the master
  ppa      optional `owner/name` toolchain PPA to add first
'''

import re
import shlex

from ..component import Family
from ..runner import Result

_VER_RE = re.compile(r'\d+\.\d+(?:\.\d+)?')


class Gcc(Family):
    name = 'gcc'
    privileged = True
    default_scope = 'system'   # apt + update-alternatives are system-wide

    @staticmethod
    def _link(rc):
        return rc.fields.get('link') or rc.comp.rsplit('-', 1)[0]

    @staticmethod
    def _ver(rc):
        return str(rc.fields.get('version') or rc.comp.rsplit('-', 1)[-1])

    @staticmethod
    def _slaves(rc):
        s = rc.fields.get('slaves')
        return list(s) if isinstance(s, list) else ([s] if s else [])

    def _packages(self, rc):
        v = self._ver(rc)
        return [f'{self._link(rc)}-{v}'] + [f'{s}-{v}' for s in self._slaves(rc)]

    def _master_bin(self, rc):
        return f'/usr/bin/{self._link(rc)}-{self._ver(rc)}'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'{shlex.quote(self._master_bin(rc))} --version')
        if not r.ok or not r.stdout:
            return None
        m = _VER_RE.search(r.stdout.splitlines()[0])
        return m.group(0) if m else self._ver(rc)

    def get_latest(self, rc):
        return None  # the component is itself a pinned major version

    def is_locked(self, rc):
        return False  # configsys doesn't manage the active selection

    # -- mutate -----------------------------------------------------------

    def _alt_install(self, rc):
        v = self._ver(rc)
        link = self._link(rc)
        parts = [f'update-alternatives --install /usr/bin/{link} {link} '
                 f'/usr/bin/{link}-{v} {v}']
        for s in self._slaves(rc):
            parts.append(f'--slave /usr/bin/{s} {s} /usr/bin/{s}-{v}')
        return ' '.join(parts)

    def install(self, rc):
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        lines = ['set -e']
        ppa = rc.fields.get('ppa')
        if ppa:
            lines.append(f'add-apt-repository -y ppa:{shlex.quote(ppa)}')
            lines.append('apt-get update')
        lines.append(f'apt-get install -y {pkgs}')
        lines.append(self._alt_install(rc))
        return self.runner.run('\n'.join(lines), sudo=True, capture=False)

    def upgrade(self, rc):
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        return self.runner.run(f'apt-get install --only-upgrade -y {pkgs}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        return self.install(rc)  # the "version" is the component; (re)install it

    def uninstall(self, rc):
        link = shlex.quote(self._link(rc))
        master = shlex.quote(self._master_bin(rc))
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        lines = ['set -e',
                 f'update-alternatives --remove {link} {master} || true',
                 f'apt-get remove -y {pkgs}']
        return self.runner.run('\n'.join(lines), sudo=True, capture=False)

    def lock(self, rc):
        return Result('(gcc: switch via update-alternatives, not configsys)', 0)

    def unlock(self, rc):
        return Result('(gcc: switch via update-alternatives, not configsys)', 0)

    def location(self, rc):
        return self._master_bin(rc)
