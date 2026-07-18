'''apk.py — the Alpine Linux driver (an example configsys code plugin).

Installs native Alpine packages via `apk`. Alpine is rolling: its repos carry one current
version per branch, so — like pacman — there is no native per-package hold. Lock intent is
tracked by configsys's ledger, and set-version leans on apk's `<pkg>=<version>` constraint
(which only resolves while that version is still in a configured repo / the local cache).

This file is the whole "code" half of a configsys plugin: subclass Driver, implement the op
set with real apk commands, and export `DRIVERS` so the trusted loader registers it. Query
ops (`apk list`) need no root; mutations run under sudo. Copy this as a starting point for
another package manager (zypper, xbps, ...).

Everything it needs comes from the frozen ABI surface:
    from configsys.plugins import Driver, Result
'''

import shlex

from configsys.plugins import Driver, Result


def _version_from_apk_list(lines, name):
    '''`apk list` prints one line per package: "<name>-<version> <arch> {origin} (license)
    [flags]". Return the version off the line for exactly `name`. Guard: the char right after
    "<name>-" must be a digit, so a query for `gcc` is not satisfied by `gcc-doc-...`.'''
    prefix = name + '-'
    for line in lines:
        if line.startswith(prefix):
            rest = line[len(prefix):]
            if rest[:1].isdigit():
                return rest.split()[0]          # e.g. "1.4.7-r0"
    return None


class Apk(Driver):
    name = 'apk'
    privileged = True
    default_scope = 'system'        # apk packages are system-wide (a fixed scope)

    # -- read (no root needed) -------------------------------------------

    def get_version(self, rc):
        '''Installed version, or None if the package isn't installed.'''
        r = self.runner.run(f'apk list --installed {shlex.quote(rc.name)}')
        return _version_from_apk_list(r.stdout.splitlines(), rc.name) if r.ok else None

    def get_latest(self, rc):
        '''Version available in the configured repos (Alpine carries one current version per
        branch, so the first match is the candidate).'''
        r = self.runner.run(f'apk list {shlex.quote(rc.name)}')
        return _version_from_apk_list(r.stdout.splitlines(), rc.name) if r.ok else None

    def is_locked(self, rc):
        return False                # no native per-package hold on a rolling distro

    # -- mutate (under sudo) ---------------------------------------------

    def install(self, rc):
        return self.runner.run(f'apk add {shlex.quote(rc.name)}', sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'apk del {shlex.quote(rc.name)}', sudo=True, capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'apk add --upgrade {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        # apk pins with `<pkg>=<version>` — it must still be resolvable in a repo/cache.
        spec = f'{rc.name}={version}'
        return self.runner.run(f'apk add {shlex.quote(spec)}', sudo=True, capture=False)

    def lock(self, rc):
        return Result('apk has no native hold; lock intent is tracked by configsys', 0)

    def unlock(self, rc):
        return Result('apk unlock recorded by configsys', 0)


# The registration export the trusted loader reads (docs/plugins.md §7a).
DRIVERS = [Apk]
