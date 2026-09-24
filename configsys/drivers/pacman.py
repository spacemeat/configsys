'''pacman.py — the Arch driver (Arch, Manjaro, SteamOS).

Native packages via pacman. Arch is a rolling release — there is one version (the
current repo version), and a real upgrade is system-wide (`pacman -Syu`). There is no
per-package hold and no arbitrary version pin, so configsys DECLINES lock/set-version
here (holds_version=False) rather than recording an intent a `pacman -Syu` would ignore —
holding one package back is an unsupported partial upgrade.

Install uses the current sync db (deliberately no `-y`): keep it fresh with a full
`pacman -Syu` yourself, the Arch way — a bare `pacman -Sy <pkg>` partial upgrade is
the classic breakage. Query ops (-Q/-Si) need no root; mutations run under sudo.
'''

import re
import shlex

from ..runner import Result
from ._native import NativePkgManager

_VER_RE = re.compile(r'^Version\s*:\s*(.+)$', re.MULTILINE)

# Some names (several desktop environments: xfce4, lxqt, mate) are package GROUPS, not single
# packages — they have no single version on a rolling distro. This marker stands in for both the
# installed and available "version" so a group reads as installed/up-to-date rather than missing.
_GROUP = '(group)'


class Pacman(NativePkgManager):
    name = 'pacman'
    holds_version = False          # rolling: no hold, and repos carry only the current version
    INSTALL = 'pacman -S --noconfirm {pkgs}'
    UPGRADE = 'pacman -S --noconfirm {pkgs}'      # -S already installs-or-upgrades to the current rev
    # REMOVE is custom (group-aware) — see uninstall below.

    # -- read -------------------------------------------------------------

    def installed_index(self):
        # ONE `pacman -Q` lists every installed package -> {name: version} (groups aren't listed;
        # a group component just falls back to per-method get_version, which handles -Qg).
        r = self.runner.run('pacman -Q')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            cols = line.split()
            if cols:
                idx[cols[0]] = (cols[1] if len(cols) > 1 else '') or 'installed'
        return idx

    def explicit_keys(self):
        '''`pacman -Qeq` — explicitly-installed packages (names only), not dependency-only ones.'''
        r = self.runner.run('pacman -Qeq')
        if not r.ok:
            return None
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)          # answer from the one pacman -Q index when batched
        if hit:
            if ver is not None:
                return ver
            # batched but not a package -> maybe an installed GROUP (groups aren't in the pkg index)
            g = self.runner.run(f'pacman -Qg {shlex.quote(rc.name)}')
            return _GROUP if g.ok and g.stdout.strip() else None
        # `pacman -Q btop` -> "btop 1.4.7-1"; nonzero + not-found message if absent
        r = self.runner.run(f'pacman -Q {shlex.quote(rc.name)}')
        if r.ok and r.stdout.strip():
            parts = r.stdout.split()
            return parts[1] if len(parts) >= 2 else None
        # not a single package — maybe an installed GROUP: `pacman -Qg xfce4` lists its members
        g = self.runner.run(f'pacman -Qg {shlex.quote(rc.name)}')
        return _GROUP if g.ok and g.stdout.strip() else None

    def get_latest(self, rc):
        r = self.runner.run(f'pacman -Si {shlex.quote(rc.name)}')
        if r.ok:
            m = _VER_RE.search(r.stdout)
            if m:
                return m.group(1).strip()
        # a group has no version; report the same marker so an installed group isn't "outdated"
        g = self.runner.run(f'pacman -Sg {shlex.quote(rc.name)}')
        return _GROUP if g.ok and g.stdout.strip() else None

    def upgradable_index(self):
        # `pacman -Qu` -> "name oldver -> newver" per out-of-date package (reads the synced DB).
        # Exit 1 with no output = nothing to upgrade (not a failure).
        r = self.runner.run('pacman -Qu')
        if not r.ok:
            return {} if r.returncode == 1 else None
        idx = {}
        for line in r.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4 and cols[2] == '->':
                idx.setdefault(cols[0], (cols[1], cols[3]))
            elif cols:
                idx.setdefault(cols[0], (None, cols[-1]))
        return idx

    def upgrade_all(self):
        # Arch has no safe partial upgrade: `pacman -Syu` (full system upgrade) is the ONLY correct
        # bulk — a targeted `-S` off a synced DB is a partial upgrade that breaks the system.
        return self.runner.run('pacman -Syu --noconfirm', sudo=True, capture=False)

    # (no held_keys: pacman has no per-package hold — holds_version=False.)

    # -- mutate -----------------------------------------------------------

    # install/upgrade come from the NativePkgManager templates (pacman -S installs-or-upgrades);
    # remove is custom because `pacman -R` can't take a GROUP name:
    def uninstall(self, rc):
        # if this is a group, expand to its installed members (`pacman -Qgq xfce4`); else remove direct
        n = shlex.quote(rc.name)
        cmd = (f'if pacman -Qq {n} >/dev/null 2>&1; then pacman -R --noconfirm {n}; '
               f'else pacman -R --noconfirm $(pacman -Qgq {n}); fi')
        return self.runner.run(cmd, sudo=True, capture=False)

    def set_version(self, rc, version):
        # Arch is rolling: the repos carry only the CURRENT version (older ones live in the Arch Linux
        # Archive / a local cache, not the repos), so there's no version to pin to. Decline honestly
        # instead of silently installing the current version under the guise of pinning `version`.
        return Result('', 1, advisory=True, stderr=(
            f'pacman can\'t pin {rc.comp} to {version}: Arch is rolling — its repos carry only the '
            f'current version. Use `configsys upgrade {rc.comp}` for the current one, or install an '
            f'old build from the Arch Linux Archive by hand.'))

    def lock(self, rc):
        # A lock can't be honored on Arch: `pacman -Syu` (the supported update path) upgrades every
        # package together, out of configsys's control, and holding one back is an unsupported partial
        # upgrade. So decline instead of recording an intent nothing will enforce.
        return Result('', 1, advisory=True, stderr=(
            f'pacman won\'t lock {rc.comp}: Arch is rolling — a `pacman -Syu` upgrades everything '
            f'together, so a per-package hold can\'t be honored (holding one back is an unsupported '
            f'partial upgrade). Nothing was locked.'))

    def unlock(self, rc):
        return Result(f'({rc.comp}: pacman has no lock to release)', 0)
