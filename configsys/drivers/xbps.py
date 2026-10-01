'''xbps.py — the Void Linux driver.

Installs native Void packages via the `xbps-*` tools. Void is rolling, but unlike Alpine/Arch it
has a native per-package HOLD (`xbps-pkgdb -m hold`), so lock/unlock are real. Query ops need no
root; mutations run under sudo. Void ships two libc flavors (the `void` and `void_musl` os blocks);
xbps package names are libc-agnostic, so this one driver serves both.

Batched like apt: one `xbps-query -l` (installed) + one `xbps-query -Rs ""` (every repo package's
candidate version) answer the inspect prepass instead of a probe per unit. Also carries the orphan
(`explicit_keys`) and System Updates (`upgradable_index`/`held_keys`/`upgrade_all`) hooks.

This driver began as the configsys-void code plugin's (which remains as a worked example of an OS
plugin); core is now authoritative — a plugin `xbps` driver loaded on top SHADOWS this one.
'''

import re
import shlex

from ._native import NativePkgManager

# An xbps pkgver is "<name>-<version>_<revision>"; the name may contain hyphens (gcc-fortran), so
# anchor the version at the last "-" whose tail is "<digit>…_<rev>" (no interior hyphen).
_PKGVER = re.compile(r'^(.*)-(\d[^-]*_\d+)$')


def _version_from_pkgver(stdout, name):
    '''`xbps-query -p pkgver <name>` prints "<name>-<version>_<revision>" (e.g. "vim-9.0.1_1").
    Return the "<version>_<revision>" tail for exactly `name`, guarding that the char after
    "<name>-" is a digit (so `gcc` is not satisfied by `gcc-fortran-...`).'''
    prefix = name + '-'
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix) and line[len(prefix):len(prefix) + 1].isdigit():
            return line[len(prefix):]
    return None


def _split_pkgver(pkgver):
    '''(name, version_rev) from a bare pkgver, or (None, None) if it doesn't parse.'''
    m = _PKGVER.match(pkgver.strip())
    return (m.group(1), m.group(2)) if m else (None, None)


class Xbps(NativePkgManager):
    name = 'xbps'
    INSTALL = 'xbps-install -Sy {pkgs}'
    REMOVE = 'xbps-remove -y {pkgs}'
    UPGRADE = 'xbps-install -Suy {pkgs}'

    # -- read (no root needed) -------------------------------------------

    def installed_index(self):
        # ONE `xbps-query -l` lists every installed package ("ii <pkgver>  <desc>") -> {name: version}.
        r = self.runner.run('xbps-query -l')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:                         # "ii <pkgver> <description…>"
                name, ver = _split_pkgver(parts[1])
                if name:
                    idx.setdefault(name, ver or 'installed')
        return idx

    def batch_index(self, rcs):
        '''The installed index + every repo package's candidate (`xbps-query -Rs ""`: one row per
        package, "[-] <pkgver>  <desc>", first repo wins) + the held set — three calls in all.'''
        installed = self.installed_index()
        if installed is None:
            return None
        candidate = {}
        r = self.runner.run('xbps-query -Rs ""')
        if r.ok:
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith('['):
                    name, ver = _split_pkgver(parts[1])
                    if name:
                        candidate.setdefault(name, ver)
        return {'installed': installed, 'candidate': candidate, 'held': self.held_keys()}

    def explicit_keys(self):
        '''`xbps-query -m` — packages installed MANUALLY (not pulled as dependencies).'''
        r = self.runner.run('xbps-query -m')
        if not r.ok:
            return None
        out = set()
        for line in r.stdout.splitlines():
            name, _ = _split_pkgver(line)
            if name:
                out.add(name)
        return out

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)            # answer from the one xbps-query -l when batched
        if hit:
            return ver
        name = self._probe_name(rc)
        r = self.runner.run(f'xbps-query -p pkgver {shlex.quote(name)}')
        return _version_from_pkgver(r.stdout, name) if r.ok else None

    def get_latest(self, rc):
        if isinstance(self._batch, dict) and 'candidate' in self._batch:
            return self._batch['candidate'].get(self._probe_name(rc))
        name = self._probe_name(rc)
        r = self.runner.run(f'xbps-query -R -p pkgver {shlex.quote(name)}')   # -R: the repos
        return _version_from_pkgver(r.stdout, name) if r.ok else None

    def is_locked(self, rc):
        if isinstance(self._batch, dict) and isinstance(self._batch.get('held'), set):
            return self._probe_name(rc) in self._batch['held']
        # the `hold` property prints "yes" when the package is held back from upgrades.
        r = self.runner.run(f'xbps-query -p hold {shlex.quote(self._probe_name(rc))}')
        return bool(r.ok and r.stdout.strip() == 'yes')

    # -- System Updates lane (upgradable / held / bulk) ------------------

    def upgradable_index(self):
        '''{name: (installed, candidate)} from `xbps-install -un` — a dry-run upgrade against the
        CURRENT (already-synced) repo index, no root needed. Rows read "<pkgver> update <arch> …";
        keep the `update` actions (new-dependency `install` rows aren't upgrades).'''
        r = self.runner.run('xbps-install -un')
        if not r.ok:
            return None
        installed = self.installed_index() or {}
        idx = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[1] != 'update':
                continue
            name, cand = _split_pkgver(parts[0])
            if name:
                idx.setdefault(name, (installed.get(name), cand))
        return idx

    def held_keys(self):
        # `xbps-query -H` lists packages on hold (pkgvers).
        r = self.runner.run('xbps-query -H')
        if not r.ok:
            return None
        out = set()
        for line in r.stdout.splitlines():
            s = line.strip()
            if s:
                name, _ = _split_pkgver(s)
                out.add(name or s)
        return out

    def upgrade_all(self):
        # rolling: the safe bulk is a full sync + system upgrade (like pacman -Syu / apk upgrade).
        return self.runner.run('xbps-install -Suy', sudo=True, capture=False)

    # -- mutate (under sudo) — install/uninstall/upgrade come from NativePkgManager templates ------

    def set_version(self, rc, version):
        # best-effort exact edition (only resolvable while it's still in a configured repo).
        spec = f'{rc.name}-{version}'
        return self.runner.run(f'xbps-install -y {shlex.quote(spec)}', sudo=True, capture=False)

    def lock(self, rc):
        return self.runner.run(f'xbps-pkgdb -m hold {self._pkgs(rc)}', sudo=True)

    def unlock(self, rc):
        return self.runner.run(f'xbps-pkgdb -m unhold {self._pkgs(rc)}', sudo=True)
