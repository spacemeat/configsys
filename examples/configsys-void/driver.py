'''xbps.py — the Void Linux driver (an example configsys code plugin).

Installs native Void packages via the `xbps-*` tools. Void is a rolling distro, but unlike
Alpine it has a native package *hold* (`xbps-pkgdb -m hold`), so this driver implements a real
lock/unlock — a slightly richer template than a hold-less manager.

This file is the whole "code" half of a configsys plugin: subclass Driver, implement the op
set with real commands, and export `DRIVERS` so the trusted loader registers it. Query ops
need no root; mutations run under sudo. Copy this as a starting point for another package
manager (zypper and apk graduated into base configsys this way).

Everything it needs comes from the frozen ABI surface:
    from configsys.plugins import Driver, Result
'''

import shlex

from configsys.plugins import Driver, Result


def _version_from_pkgver(stdout, name):
    '''`xbps-query -p pkgver <name>` prints "<name>-<version>_<revision>" (e.g.
    "vim-9.0.1_1"). Return the "<version>_<revision>" tail for exactly `name`, guarding that
    the char after "<name>-" is a digit (so `gcc` is not satisfied by `gcc-fortran-...`).'''
    prefix = name + '-'
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix) and line[len(prefix):len(prefix) + 1].isdigit():
            return line[len(prefix):]
    return None


class Xbps(Driver):
    name = 'xbps'
    privileged = True
    default_scope = 'system'        # xbps packages are system-wide (a fixed scope)

    # -- read (no root needed) -------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'xbps-query -p pkgver {shlex.quote(rc.name)}')
        return _version_from_pkgver(r.stdout, rc.name) if r.ok else None

    def get_latest(self, rc):
        # -R queries the remote repos (the candidate version).
        r = self.runner.run(f'xbps-query -R -p pkgver {shlex.quote(rc.name)}')
        return _version_from_pkgver(r.stdout, rc.name) if r.ok else None

    def is_locked(self, rc):
        # the `hold` property prints "yes" when the package is held back from upgrades.
        r = self.runner.run(f'xbps-query -p hold {shlex.quote(rc.name)}')
        return bool(r.ok and r.stdout.strip() == 'yes')

    # -- mutate (under sudo) ---------------------------------------------

    def install(self, rc):
        return self.runner.run(f'xbps-install -Sy {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'xbps-remove -y {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'xbps-install -Suy {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        # best-effort exact edition (only resolvable while it's still in a configured repo).
        spec = f'{rc.name}-{version}'
        return self.runner.run(f'xbps-install -y {shlex.quote(spec)}',
                               sudo=True, capture=False)

    def lock(self, rc):
        return self.runner.run(f'xbps-pkgdb -m hold {shlex.quote(rc.name)}', sudo=True)

    def unlock(self, rc):
        return self.runner.run(f'xbps-pkgdb -m unhold {shlex.quote(rc.name)}', sudo=True)


# The registration export the trusted loader reads (docs/plugins.md §7a).
DRIVERS = [Xbps]
