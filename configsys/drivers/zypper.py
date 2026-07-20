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

from ..driver import Driver


def _version_from_info(stdout):
    '''`zypper info <pkg>` prints an aligned block; the candidate version is the line
    "Version        : 1.2.3-4.1". Return the value, or None if absent.'''
    for line in stdout.splitlines():
        label, sep, val = line.partition(':')
        if sep and label.strip().lower() == 'version':
            return val.strip() or None
    return None


class Zypper(Driver):
    name = 'zypper'
    privileged = True
    default_scope = 'system'   # zypper packages are system-wide (fixed)

    # -- read (no root needed) -------------------------------------------

    def get_version(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f"rpm -q --qf '%{{VERSION}}\\n' {pkg}")
        if r.ok and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
        return None

    def get_latest(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f'zypper --terse --no-refresh info {pkg}')
        return _version_from_info(r.stdout) if r.ok else None

    def is_locked(self, rc):
        # `zypper locks` prints a table "# | Name | Type | Repository"; a hold on this
        # package is a row whose Name column equals rc.name.
        r = self.runner.run('zypper --terse locks')
        if not r.ok:
            return False
        for line in r.stdout.splitlines():
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 2 and cols[1] == rc.name:
                return True
        return False

    # -- mutate (under sudo, non-interactive) ----------------------------

    def install(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'zypper --non-interactive install {pkg}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'zypper --non-interactive remove {pkg}',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'zypper --non-interactive update {pkg}',
                               sudo=True, capture=False)

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
