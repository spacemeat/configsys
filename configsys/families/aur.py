'''aur.py — the Arch User Repository family.

Builds AUR packages from their PKGBUILD with makepkg — no helper (yay/paru) needed:
clone the package's AUR git repo and `makepkg -si`. makepkg refuses to run as root
and calls sudo itself for the final pacman install, so build/install run UNPRIVILEGED
(as the user); removal is a normal `pacman -R` (root).

makepkg does not fetch transitive *AUR* dependencies — declare them as configsys deps
and each is built in order (its official-repo deps makepkg pulls in itself). Installed
AUR packages land in the pacman db, so version state is `pacman -Q`; latest comes from
the AUR RPC via a `version: { aur: <pkgname> }` route spec. Needs base-devel + git.
'''

import shlex

from ..component import Family
from ..runner import Result

_AUR_GIT = 'https://aur.archlinux.org/{pkg}.git'
_BUILD_ROOT = '/tmp/configsys-aur'


class Aur(Family):
    name = 'aur'
    privileged = False   # makepkg must NOT run as root; it sudo's internally

    @staticmethod
    def _pkg(rc):
        return rc.name   # the AUR pkgname (e.g. yay-bin)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'pacman -Q {shlex.quote(self._pkg(rc))}')
        if not r.ok or not r.stdout.strip():
            return None
        parts = r.stdout.split()
        return parts[1] if len(parts) >= 2 else None

    def get_latest(self, rc):
        # a `version: { aur: <pkgname> }` route discovers the latest from the AUR RPC
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        pkg = self._pkg(rc)
        build = f'{_BUILD_ROOT}/{pkg}'
        url = _AUR_GIT.format(pkg=pkg)
        script = '\n'.join([
            'set -e',
            f'rm -rf {shlex.quote(build)}',
            f'mkdir -p {shlex.quote(build)}',
            f'git clone --depth 1 {shlex.quote(url)} {shlex.quote(build)}',
            f'cd {shlex.quote(build)}',
            'makepkg -si --noconfirm',
        ])
        return self.runner.run(script, capture=False)   # unprivileged; makepkg sudo's

    def uninstall(self, rc):
        # an installed AUR package is removed like any pacman package (needs root)
        return self.runner.run(f'pacman -R --noconfirm {shlex.quote(self._pkg(rc))}',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # rebuild from the current PKGBUILD

    def set_version(self, rc, version):
        return self.install(rc)   # AUR serves the current PKGBUILD only

    def lock(self, rc):
        return Result('(aur lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(aur unlock recorded in ledger)', 0)

    def location(self, rc):
        return None   # installed into the system via pacman, no single path
