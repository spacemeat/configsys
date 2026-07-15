'''pacman.py — the Arch family (Arch, Manjaro, SteamOS).

Native packages via pacman. Arch is a rolling release — there is one version (the
current repo version), so there's no per-package hold or arbitrary version pin: lock
intent lives in the ledger, and a real upgrade is system-wide (`pacman -Syu`).

Install uses the current sync db (deliberately no `-y`): keep it fresh with a full
`pacman -Syu` yourself, the Arch way — a bare `pacman -Sy <pkg>` partial upgrade is
the classic breakage. Query ops (-Q/-Si) need no root; mutations run under sudo.
'''

import re
import shlex

from ..component import Family
from ..runner import Result

_VER_RE = re.compile(r'^Version\s*:\s*(.+)$', re.MULTILINE)


class Pacman(Family):
    name = 'pacman'
    privileged = True
    default_scope = 'system'   # pacman packages are system-wide (fixed)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # `pacman -Q btop` -> "btop 1.4.7-1"; nonzero + not-found message if absent
        r = self.runner.run(f'pacman -Q {shlex.quote(rc.name)}')
        if not r.ok or not r.stdout.strip():
            return None
        parts = r.stdout.split()
        return parts[1] if len(parts) >= 2 else None

    def get_latest(self, rc):
        r = self.runner.run(f'pacman -Si {shlex.quote(rc.name)}')
        if not r.ok:
            return None
        m = _VER_RE.search(r.stdout)
        return m.group(1).strip() if m else None

    def is_locked(self, rc):
        return False   # no native per-package hold on a rolling distro

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'pacman -S --noconfirm {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'pacman -R --noconfirm {shlex.quote(rc.name)}',
                               sudo=True, capture=False)

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
