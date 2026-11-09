'''gcc_toolset.py — versioned GCC via Red Hat Software Collections (EL / gcc-toolset).

RHEL-family distros (RHEL, Rocky, AlmaLinux, CentOS Stream) ship versioned compilers
as `gcc-toolset-N` meta packages that install under /opt/rh/gcc-toolset-N — NOT on the
default PATH (the system gcc stays put). You activate a toolset for a shell with
`scl enable gcc-toolset-13 bash` or `source /opt/rh/gcc-toolset-13/enable` (EL 8/9), or on EL 10 —
which drops the SCL enable script — `source /usr/lib/gcc-toolset/15-env.source` (or run a command
through `gcc-toolset-15-env`).

configsys installs the toolset and reports its real gcc version (read from the
toolset's own gcc binary, since the meta package's rpm version is just the collection
number). Activating a version stays your job, same as update-alternatives on Debian.
System-scoped (dnf + /opt).

It is AltDriver's dnf path with a different package and binary (review-2026-11-2 D5 /
drivers-lang-18): one `gcc-toolset-N` package, its gcc under the toolset prefix, always dnf, never
an alternatives slot — and it inherits the dnf candidate lookup (asked of `gcc-toolset-N-gcc`, whose
rpm version is the compiler's), so a bugfix release within the toolset (13.2 → 13.3) shows as an
update.
'''

import shlex

from ..runner import Result
from ._alt import _VER_RE, AltDriver


class GccToolset(AltDriver):
    name = 'gcc-toolset'

    def _pkg(self, rc):
        return f'gcc-toolset-{self._ver(rc)}'

    def _packages(self, rc):
        return [self._pkg(rc)]

    def _latest_package(self, rc):
        # the meta package's rpm version is the collection number (13.0); its gcc subpackage
        # carries the real compiler version (13.3.1), the one get_version reads
        return f'{self._pkg(rc)}-gcc'

    def _prefix(self, rc):
        return f'/opt/rh/gcc-toolset-{self._ver(rc)}'

    def _gcc_bin(self, rc):
        return f'{self._prefix(rc)}/root/usr/bin/gcc'

    def _master_bin(self, rc):
        return self._gcc_bin(rc)

    def _pm(self, rc=None):
        return 'dnf'                       # EL only — the SCL packages are dnf's

    def index_key(self, rc):
        return self._pkg(rc)               # the dnf package it lands as (orphan scan, batch reads)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # the meta rpm version is the collection number (e.g. 13.0); the toolset's own gcc binary
        # reports the real version (13.3.1). None (not the collection number) when it isn't there.
        r = self.runner.run(f'{shlex.quote(self._gcc_bin(rc))} --version')
        if not r.ok or not r.stdout:
            return None
        m = _VER_RE.search(r.stdout.splitlines()[0])
        return m.group(0) if m else None

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'dnf install -y {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'dnf remove -y {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def lock(self, rc):
        return Result('(gcc-toolset: no version hold — the toolset version is fixed by its package)', 0)

    def unlock(self, rc):
        return Result('(gcc-toolset: no version hold — the toolset version is fixed by its package)', 0)

    def location(self, rc):
        return self._prefix(rc)
