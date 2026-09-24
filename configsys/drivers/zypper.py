'''zypper.py — the openSUSE / SUSE driver.

openSUSE is RPM-based, so installed-version state comes from `rpm -q` (exactly as the dnf
driver does); everything else goes through `zypper`. It serves both products off one driver:
Leap (versioned) and Tumbleweed (rolling) share zypper — the difference is a routes.hu scale
concern, not a driver one. zypper supports `name OP version` specifiers (`=`, `<`, `>=`, ...),
so set-version is exact, and `addlock`/`removelock` give a real native version hold (unlike
Alpine's rolling apk). Query ops need no root; mutations run `--non-interactive` under sudo
and stream output so the user sees progress.

Command construction is unit-tested (pretend mode); end-to-end validation on a live openSUSE
box is deferred — there is no testbed yet (like macOS/brew).
'''

import shlex

from ._native import NativePkgManager


def _version_from_info(stdout):
    '''`zypper info <pkg>` prints an aligned block; the candidate version is the line
    "Version        : 1.2.3-4.1". Return the value, or None if absent.'''
    for line in stdout.splitlines():
        label, sep, val = line.partition(':')
        if sep and label.strip().lower() == 'version':
            return val.strip() or None
    return None


class Zypper(NativePkgManager):
    name = 'zypper'
    INSTALL = 'zypper --non-interactive install {pkgs}'
    REMOVE = 'zypper --non-interactive remove {pkgs}'
    UPGRADE = 'zypper --non-interactive update {pkgs}'

    # -- read (no root needed) -------------------------------------------

    def installed_index(self):
        # ONE rpm query lists everything installed -> {name: version}; the read ops batch off it.
        r = self.runner.run("rpm -qa --qf '%{NAME} %{VERSION}\\n'")
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            name, _, ver = line.partition(' ')
            if name:
                idx[name] = ver.strip() or 'installed'
        return idx

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)          # answer from the one rpm -qa when batched
        if hit:
            return ver
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f"rpm -q --qf '%{{VERSION}}\\n' {pkg}")
        if r.ok and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
        return None

    def get_latest(self, rc):
        # `zypper info` prints "Version : <candidate>". zypper LOCALIZES its field labels, so
        # force LC_ALL=C — otherwise the "Version" label changes under a non-English locale and
        # the parse silently returns None. (--terse doesn't affect `info`, so it's dropped.)
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f'LC_ALL=C zypper --no-refresh info {pkg}')
        return _version_from_info(r.stdout) if r.ok else None

    def is_locked(self, rc):
        # `zypper locks` prints a table "# | Name | Type | Repository"; a hold on this package
        # is a row whose Name column equals rc.name. LC_ALL=C keeps the columns stable and
        # locale-independent (the header/labels are localized otherwise).
        r = self.runner.run('LC_ALL=C zypper locks')
        if not r.ok:
            return False
        for line in r.stdout.splitlines():
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 2 and cols[1] == rc.name:
                return True
        return False

    def upgradable_index(self):
        # `zypper list-updates` prints "S | Repo | Name | Current | Available | Arch"; data rows begin
        # with a status letter (v). LC_ALL=C keeps the columns/labels stable under any locale.
        r = self.runner.run('LC_ALL=C zypper --non-interactive -q list-updates')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 5 and cols[0] in ('v', 'i') and cols[2] and cols[2] != 'Name':
                idx.setdefault(cols[2], (cols[3] or None, cols[4] or None))
        return idx

    def held_keys(self):
        # `zypper locks` — the Name column (index 1) of each lock row (LC_ALL=C for stable columns).
        r = self.runner.run('LC_ALL=C zypper locks')
        if not r.ok:
            return None
        held = set()
        for line in r.stdout.splitlines():
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 2 and cols[1] and cols[1] != 'Name':
                held.add(cols[1])
        return held

    def upgrade_all(self):
        return self.runner.run('zypper --non-interactive update', sudo=True, capture=False)

    # -- mutate (under sudo, non-interactive) ----------------------------

    # install/uninstall/upgrade come from the NativePkgManager templates above.

    def set_version(self, rc, version):
        # zypper honors `name=version`; --oldpackage permits a downgrade to that exact edition.
        spec = shlex.quote(f'{rc.name}={version}')
        return self.runner.run(f'zypper --non-interactive install --oldpackage {spec}',
                               sudo=True, capture=False)

    def lock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'zypper --non-interactive addlock {pkg}', sudo=True)

    def unlock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'zypper --non-interactive removelock {pkg}', sudo=True)
