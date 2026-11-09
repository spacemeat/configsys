'''aur.py — the Arch User Repository driver.

Builds AUR packages from their PKGBUILD with makepkg — no helper (yay/paru) needed:
clone the package's AUR git repo and `makepkg -si`. makepkg refuses to run as root
and calls sudo itself for the final pacman install, so build/install run UNPRIVILEGED
(as the user); removal is a normal `pacman -R` (root).

makepkg does not fetch transitive *AUR* dependencies — declare them as configsys deps
and each is built in order (its official-repo deps makepkg pulls in itself). Installed
AUR packages land in the pacman db, so version state is `pacman -Q`; latest comes from
the AUR RPC via a `version: { aur: <pkgname> }` route spec. Needs base-devel + git.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_AUR_GIT = 'https://aur.archlinux.org/{pkg}.git'
# an AUR pkgname (the AUR's own rule): one path segment, so a build dir can't escape its root
_PKGNAME = re.compile(r'[a-z0-9@._+][a-z0-9@._+-]*')


class Aur(Driver):
    name = 'aur'
    targets_version = False   # the AUR serves only the current PKGBUILD
    privileged = False   # makepkg must NOT run as root; it sudo's internally
    native_backed = True   # makepkg installs the built package via pacman — it lands in `pacman -Q`

    @staticmethod
    def _pkg(rc):
        return rc.name   # the AUR pkgname (e.g. yay-bin)

    # -- read -------------------------------------------------------------

    def foreign_index(self):
        '''`pacman -Qm` — the FOREIGN packages (not from a sync repo: AUR builds, local pkgs) ->
        {name: version}, or None off Arch. stranded.py reads it for pre-receipt AUR installs.'''
        r = self.runner.run('pacman -Qm')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            cols = line.split()
            if cols:
                idx[cols[0]] = cols[1] if len(cols) > 1 else 'installed'
        return idx

    def get_version(self, rc):
        r = self.runner.run(f'pacman -Q {shlex.quote(self._pkg(rc))}')
        if not r.ok or not r.stdout.strip():
            return None
        parts = r.stdout.split()
        return parts[1] if len(parts) >= 2 else None

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        pkg = self._pkg(rc)
        if not _PKGNAME.fullmatch(pkg):
            return Result.fail(f'{rc.comp}: {pkg!r} is not an AUR package name')
        url = _AUR_GIT.format(pkg=pkg)
        # a PRIVATE per-build dir (mktemp -d: mode 700, unguessable) — the old fixed, shared
        # /tmp/configsys-aur could be pre-created or symlink-raced by another local user (A16) —
        # removed again however the build ends
        script = '\n'.join([
            'set -e',
            'B="$(mktemp -d "${TMPDIR:-/tmp}/configsys-aur.XXXXXX")"',
            'trap \'rm -rf "$B"\' EXIT',
            f'git clone --depth 1 {shlex.quote(url)} "$B/{pkg}"',
            f'cd "$B/{pkg}"',
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

    def location(self, rc):
        return None   # installed into the system via pacman, no single path
