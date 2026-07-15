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
    default_scope = 'system'   # apt packages are system-wide (fixed)

    # -- prerequisites ----------------------------------------------------

    @staticmethod
    def _as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def ensure_prereqs(self, rc):
        '''System setup a component needs before it can install, declared on its
        route: archive components to enable (`repo-component`) and third-party
        signing key + source list (`pubkey-*`/`source-*`). Idempotent — a source
        is only fetched (and apt updated) when its file is missing.'''
        f = rc.fields

        for comp in self._as_list(f.get('repo-component')):
            c = shlex.quote(comp)
            # add-apt-repository is idempotent and refreshes apt lists itself.
            self.runner.run(f'add-apt-repository -y {c}', sudo=True, capture=False)

        key_url, key_path = f.get('pubkey-url'), f.get('pubkey-path')
        if key_url and key_path:
            kp, ku = shlex.quote(key_path), shlex.quote(key_url)
            self.runner.run(f'[ -f {kp} ] || sudo curl -fsSL {ku} -o {kp}',
                            capture=False)

        src_url, src_path = f.get('source-url'), f.get('source-path')
        if src_url and src_path:
            sp, su = shlex.quote(src_path), shlex.quote(src_url)
            self.runner.run(
                f'if [ ! -f {sp} ]; then sudo curl -fsSL {su} -o {sp} '
                f'&& sudo apt-get update; fi', capture=False)

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
        self.ensure_prereqs(rc)
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install -y {pkg}', sudo=True, capture=False)

    def uninstall(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get remove -y {pkg}', sudo=True, capture=False)

    def upgrade(self, rc):
        self.ensure_prereqs(rc)
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install --only-upgrade -y {pkg}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        self.ensure_prereqs(rc)
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
