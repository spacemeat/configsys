'''apt.py — the Debian/apt family.

Version state via dpkg-query + apt-cache policy; mutation via apt-get; version
lock via apt-mark hold/unhold. Mutating ops run under sudo and stream their output
(capture=False) so the user sees apt's progress and sudo can prompt.
'''

import shlex

from ..component import Family


class Apt(Family):
    name = 'apt'
    privileged = True

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f"dpkg-query -W -f='${{Version}}' {pkg}")
        if r.ok and r.stdout.strip():
            return r.stdout.strip()
        return None

    def get_latest(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f'apt-cache policy {pkg}')
        if not r.ok:
            return None
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith('Candidate:'):
                cand = line.split(':', 1)[1].strip()
                return None if cand in ('(none)', '') else cand
        return None

    def is_locked(self, rc):
        r = self.runner.run('apt-mark showhold')
        return bool(r.ok and rc.name in r.stdout.split())

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install -y {pkg}', sudo=True, capture=False)

    def uninstall(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get remove -y {pkg}', sudo=True, capture=False)

    def upgrade(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install --only-upgrade -y {pkg}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        pkg = shlex.quote(rc.name)
        ver = shlex.quote(version)
        return self.runner.run(
            f'apt-get install -y --allow-downgrades {pkg}={ver}',
            sudo=True, capture=False)

    def lock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-mark hold {pkg}', sudo=True)

    def unlock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-mark unhold {pkg}', sudo=True)
