'''gcc_toolset.py — versioned GCC via Red Hat Software Collections (EL / gcc-toolset).

RHEL-driver distros (RHEL, Rocky, AlmaLinux, CentOS Stream) ship versioned compilers
as `gcc-toolset-N` meta packages that install under /opt/rh/gcc-toolset-N — NOT on the
default PATH (the system gcc stays put). You activate a toolset for a shell with
`scl enable gcc-toolset-13 bash` or `source /opt/rh/gcc-toolset-13/enable`.

configsys installs the toolset and reports its real gcc version (read from the
toolset's own gcc binary, since the meta package's rpm version is just the collection
number). Activating a version stays your job, same as update-alternatives on Debian.
System-scoped (dnf + /opt).
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_VER_RE = re.compile(r'\d+\.\d+(?:\.\d+)?')


class GccToolset(Driver):
    name = 'gcc-toolset'
    privileged = True
    default_scope = 'system'

    @staticmethod
    def _ver(rc):
        return str(rc.fields.get('version') or rc.comp.rsplit('-', 1)[-1])

    def _pkg(self, rc):
        return f'gcc-toolset-{self._ver(rc)}'

    def _prefix(self, rc):
        return f'/opt/rh/gcc-toolset-{self._ver(rc)}'

    def _gcc_bin(self, rc):
        return f'{self._prefix(rc)}/root/usr/bin/gcc'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # the meta rpm version is the collection number (e.g. 13.0); the toolset's
        # own gcc binary reports the real version (13.3.1)
        r = self.runner.run(f'{shlex.quote(self._gcc_bin(rc))} --version')
        if not r.ok or not r.stdout:
            return None
        m = _VER_RE.search(r.stdout.splitlines()[0])
        return m.group(0) if m else None

    def get_latest(self, rc):
        return None  # the component is itself a pinned major version

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'dnf install -y {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'dnf remove -y {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'dnf upgrade -y {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        return self.install(rc)  # the toolset version is fixed by the package

    def lock(self, rc):
        return Result('(gcc-toolset: activate via scl, not configsys)', 0)

    def unlock(self, rc):
        return Result('(gcc-toolset: activate via scl, not configsys)', 0)

    def location(self, rc):
        return self._prefix(rc)
