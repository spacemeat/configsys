'''_native.py — NativePkgManager: the shared skeleton for an OS package-manager driver.

apt / dnf / zypper / pacman / apk are the same nine ops with different verbs. Their install /
uninstall / upgrade differ only in the command word, so those come from class-level TEMPLATES here
(`{pkgs}` = the quoted package argument(s)), run under sudo, with an `ensure_prereqs` hook a driver
overrides to set up vendor repos/keys first. Everything version- or lock-specific — get_version,
get_latest, installed_index, is_locked, lock/unlock, set_version — stays on each driver, because the
query/lock mechanisms genuinely differ (rpm vs pacman -Q vs apk list; apt-mark hold vs dnf
versionlock vs the ledger). The installed_index-based `batch_index` (one enumeration instead of a
probe per unit) is inherited from Driver.
'''

import shlex

from ..driver import Driver


class NativePkgManager(Driver):
    privileged = True
    default_scope = 'system'          # OS packages are system-wide (a fixed scope)
    honors_scope = False

    # Command templates — a subclass sets these. `{pkgs}` is filled from `_pkgs(rc)`.
    ENV = ''                          # optional command prefix (apt: DEBIAN_FRONTEND=… NEEDRESTART_MODE=a)
    INSTALL = None                    # e.g. 'apt-get install -y {pkgs}'
    REMOVE = None
    UPGRADE = None

    @staticmethod
    def _pkg_list(rc):
        '''The package NAMES a binding installs. A `packages: [a, b, ...]` binding installs the whole
        set (the house convention for a native component that needs several packages — a python3.12
        interpreter + venv + dev, GL + GLU dev, a library's build deps); otherwise `rc.name` (which
        may itself be a whitespace-separated set). Every package-name op (install/remove/upgrade/
        lock) acts on the whole set; DETECTION reads one package — see `_probe_name`.'''
        pkgs = rc.fields.get('packages')
        return ([str(p) for p in pkgs] if isinstance(pkgs, list) else
                [str(pkgs)] if pkgs else rc.name.split())

    @classmethod
    def _pkgs(cls, rc):
        '''`_pkg_list` joined + quoted, for the command line.'''
        return ' '.join(shlex.quote(p) for p in cls._pkg_list(rc))

    @staticmethod
    def _probe_name(rc):
        '''The ONE package to read install-state / version from: the binding's `installed-name:` when
        set (a metapackage a system commonly has without — Debian's LibreOffice), else the first of a
        `packages:` set (the unit's own name — `python-build-deps` — is not a package), else `name`.'''
        pkgs = rc.fields.get('packages')
        first = (pkgs[0] if isinstance(pkgs, list) and pkgs else pkgs) if pkgs else None
        return rc.fields.get('installed-name') or (str(first) if first else rc.name)

    def index_key(self, rc):
        return self._probe_name(rc)

    def ensure_prereqs(self, rc):
        '''Vendor repos / signing keys / plugins to set up before an install (apt PPAs + `deb` sources,
        dnf `.repo` files + versionlock). Return None to proceed, or a failed Result to abort the op
        cleanly (a repo that didn't verify). Default: nothing to do.'''
        return None

    def _native_cmd(self, template, rc):
        prefix = f'{self.ENV} ' if self.ENV else ''
        return f'{prefix}{template.format(pkgs=self._pkgs(rc))}'

    def install(self, rc):
        pre = self.ensure_prereqs(rc)
        if pre is not None:              # a vendor repo failed to verify -> abort cleanly
            return pre
        return self.runner.run(self._native_cmd(self.INSTALL, rc), sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(self._native_cmd(self.REMOVE, rc), sudo=True, capture=False)

    def upgrade(self, rc):
        pre = self.ensure_prereqs(rc)
        if pre is not None:
            return pre
        return self.runner.run(self._native_cmd(self.UPGRADE, rc), sudo=True, capture=False)
