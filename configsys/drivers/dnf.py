'''dnf.py — the Fedora/RHEL dnf driver (the rpm-world analog of apt).

Version state via `rpm -q` + `dnf repoquery`; mutation via `dnf`; version lock via
the versionlock plugin, which is installed on demand (unlike apt-mark, it isn't
built in). Verified against dnf5 on Fedora 41. Mutating ops run under sudo and
stream their output (capture=False) so the user sees progress and sudo can prompt.
'''

import shlex

from ..driver import Driver

# `dnf versionlock` lives in a plugin that isn't installed by default; lock/unlock
# ensure it first. This dnf4-named package also wires up the dnf5 subcommand.
_VERSIONLOCK_PLUGIN = 'python3-dnf-plugin-versionlock'


class Dnf(Driver):
    name = 'dnf'
    privileged = True
    default_scope = 'system'   # dnf packages are system-wide (fixed)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(f"rpm -q --qf '%{{VERSION}}\\n' {pkg}")
        # not-installed -> exit 1 with a "package X is not installed" message
        if r.ok and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
        return None

    def get_latest(self, rc):
        pkg = shlex.quote(rc.name)
        r = self.runner.run(
            f"dnf -q repoquery --queryformat '%{{version}}' --latest-limit=1 {pkg}")
        if not r.ok:
            return None
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        return lines[0] if lines else None

    def is_locked(self, rc):
        # degrades to False when the plugin isn't installed (list -> nonzero)
        r = self.runner.run('dnf versionlock list')
        if not r.ok:
            return False
        name = rc.name
        for line in r.stdout.splitlines():
            s = line.strip()
            if s.startswith('Package name:') and s.split(':', 1)[1].strip() == name:
                return True   # dnf5 format
            if s == name or s.startswith(name + '-'):
                return True   # dnf4 format fallback
        return False

    # -- prerequisites ----------------------------------------------------

    def ensure_prereqs(self, rc):
        '''Third-party dnf repo setup declared on the route: import the signing key
        (`pubkey-url`) and drop a .repo file (`repo-id`/`repo-name`/`repo-url`, gpgkey =
        pubkey-url). Idempotent — the .repo write is skipped when it already exists.

        A key URL templated with dnf repo vars (`$releasever`/`$basearch`, e.g. RPM Fusion's
        per-release key) can't be imported eagerly — `rpm --import` doesn't expand them. Such
        a key is left only in the .repo's `gpgkey=`, where dnf expands it and auto-imports on
        the first `-y` install. Literal keys are still imported up front.'''
        f = rc.fields
        key = f.get('pubkey-url')
        if key and '$' not in key:
            self.runner.run(f'rpm --import {shlex.quote(key)}', sudo=True, capture=False)
        repo_id, repo_url = f.get('repo-id'), f.get('repo-url')
        if repo_id and repo_url:
            name = f.get('repo-name', repo_id)
            content = (f'[{repo_id}]\nname={name}\nbaseurl={repo_url}\n'
                       f'enabled=1\ngpgcheck=1\ngpgkey={key}\n')
            path = shlex.quote(f'/etc/yum.repos.d/{repo_id}.repo')
            self.runner.run(
                f'[ -f {path} ] || printf %s {shlex.quote(content)} | sudo tee {path} >/dev/null',
                capture=False)

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        self.ensure_prereqs(rc)
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'dnf install -y {pkg}', sudo=True, capture=False)

    def uninstall(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'dnf remove -y {pkg}', sudo=True, capture=False)

    def upgrade(self, rc):
        self.ensure_prereqs(rc)
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'dnf upgrade -y {pkg}', sudo=True, capture=False)

    def set_version(self, rc, version):
        self.ensure_prereqs(rc)
        spec = shlex.quote(f'{rc.name}-{version}')
        # install covers same-or-upgrade; a lower target needs the downgrade verb
        return self.runner.run(f'dnf install -y {spec} || dnf downgrade -y {spec}',
                               sudo=True, capture=False)

    def _ensure_versionlock(self):
        self.runner.run(f'dnf install -y {_VERSIONLOCK_PLUGIN}',
                        sudo=True, capture=False)

    def lock(self, rc):
        self._ensure_versionlock()
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'dnf versionlock add {pkg}', sudo=True)

    def unlock(self, rc):
        self._ensure_versionlock()
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'dnf versionlock delete {pkg}', sudo=True)
