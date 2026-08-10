'''pacman.py — the Arch driver (Arch, Manjaro, SteamOS).

Native packages via pacman. Arch is a rolling release — there is one version (the
current repo version), so there's no per-package hold or arbitrary version pin: lock
intent lives in the ledger, and a real upgrade is system-wide (`pacman -Syu`).

Install uses the current sync db (deliberately no `-y`): keep it fresh with a full
`pacman -Syu` yourself, the Arch way — a bare `pacman -Sy <pkg>` partial upgrade is
the classic breakage. Query ops (-Q/-Si) need no root; mutations run under sudo.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_VER_RE = re.compile(r'^Version\s*:\s*(.+)$', re.MULTILINE)

# Some names (several desktop environments: xfce4, lxqt, mate) are package GROUPS, not single
# packages — they have no single version on a rolling distro. This marker stands in for both the
# installed and available "version" so a group reads as installed/up-to-date rather than missing.
_GROUP = '(group)'


class Pacman(Driver):
    name = 'pacman'
    privileged = True
    default_scope = 'system'   # pacman packages are system-wide (fixed)

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

    def get_version(self, rc):
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

    def is_locked(self, rc):
        return False   # no native per-package hold on a rolling distro

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'pacman -S --noconfirm {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        # `pacman -R` doesn't accept a group name — if this is a group, expand to its installed
        # members (`pacman -Qgq xfce4`); otherwise remove the package directly.
        n = shlex.quote(rc.name)
        cmd = (f'if pacman -Qq {n} >/dev/null 2>&1; then pacman -R --noconfirm {n}; '
               f'else pacman -R --noconfirm $(pacman -Qgq {n}); fi')
        return self.runner.run(cmd, sudo=True, capture=False)

    def upgrade(self, rc):
        # installs the current repo version; whole-system upgrades are `pacman -Syu`
        return self.runner.run(f'pacman -S --noconfirm {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        # the repos carry only the current version; pinning an arbitrary one needs the
        # Arch Linux Archive or a cached package — out of scope. Install the current.
        return self.install(rc)

    def lock(self, rc):
        return Result('(pacman is rolling; lock intent recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(pacman unlock recorded in ledger)', 0)
