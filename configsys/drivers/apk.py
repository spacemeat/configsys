'''apk.py — the Alpine Linux driver.

Installs native Alpine packages via `apk`. Alpine is rolling: its repos carry one current
version per branch, so — like pacman — there is no native per-package hold and no way to keep
an old version. configsys therefore DECLINES lock/set-version here (holds_version=False)
instead of recording an intent an `apk upgrade` would ignore.

Query ops (`apk list`) need no root; mutations run under sudo. This driver started life as a
code plugin of the same shape as examples/examplos (the reference template) and was folded
into base once Alpine graduated to a first-class OS.
'''

import shlex

from ..runner import Result
from ._native import NativePkgManager


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


class Apk(NativePkgManager):
    name = 'apk'
    holds_version = False          # rolling: no per-package hold; a branch carries one current version
    INSTALL = 'apk add {pkgs}'
    REMOVE = 'apk del {pkgs}'
    UPGRADE = 'apk add --upgrade {pkgs}'

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

    # -- mutate (under sudo) — install/uninstall/upgrade come from NativePkgManager templates ------

    def set_version(self, rc, version):
        # Alpine is rolling: a branch carries one CURRENT version per package (older builds aren't in
        # the repos), and there's no hold — so `apk add pkg=<old>` would fail to resolve and even a
        # resolvable pin wouldn't survive the next `apk upgrade`. Decline honestly.
        return Result('', 1, advisory=True, stderr=(
            f'apk can\'t pin {rc.comp} to {version}: Alpine is rolling — apk carries one current '
            f'version per branch, with no per-package hold. Use `configsys upgrade {rc.comp}`.'))

    def lock(self, rc):
        return Result('', 1, advisory=True, stderr=(
            f'apk won\'t lock {rc.comp}: Alpine is rolling — apk has no per-package hold and '
            f'`apk upgrade` moves everything together, so a hold can\'t be honored. Nothing was locked.'))

    def unlock(self, rc):
        return Result(f'({rc.comp}: apk has no lock to release)', 0)
