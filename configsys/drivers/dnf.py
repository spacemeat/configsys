'''dnf.py — the Fedora/RHEL dnf driver (the rpm-world analog of apt).

Version state via `rpm -q` + `dnf repoquery`; mutation via `dnf`; version lock via
the versionlock plugin, which is installed on demand (unlike apt-mark, it isn't
built in). Verified against dnf5 on Fedora 41. Mutating ops run under sudo and
stream their output (capture=False) so the user sees progress and sudo can prompt.
'''

import shlex

from ..failures import classify
from ..runner import Result
from ._native import NativePkgManager

# `dnf versionlock` lives in a plugin that isn't installed by default; lock/unlock
# ensure it first. This dnf4-named package also wires up the dnf5 subcommand.
_VERSIONLOCK_PLUGIN = 'python3-dnf-plugin-versionlock'


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class Dnf(NativePkgManager):
    name = 'dnf'
    INSTALL = 'dnf install -y {pkgs}'
    REMOVE = 'dnf remove -y {pkgs}'
    UPGRADE = 'dnf upgrade -y {pkgs}'

    # -- read -------------------------------------------------------------

    def installed_index(self):
        # ONE rpm query lists every installed package -> {name: version}.
        r = self.runner.run("rpm -qa --qf '%{NAME} %{VERSION}\\n'")
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            name, _, ver = line.partition(' ')
            if name:
                idx[name] = ver.strip() or 'installed'
        return idx

    def explicit_keys(self):
        '''`dnf repoquery --userinstalled` — packages the user requested, not dependency-pulled.'''
        r = self.runner.run("dnf repoquery --userinstalled --qf '%{name}\\n'")
        if not r.ok:
            return None
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)          # answer from the one rpm -qa when batched
        if hit:
            return ver
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

    def upgradable_index(self):
        # `dnf -q check-update` lists "name.arch  version  repo" and EXITS 100 when updates exist
        # (0 = none) — both are success. Name is arch-stripped; installed comes from rpm.
        r = self.runner.run('dnf -q check-update')
        if r.returncode not in (0, 100):
            return None
        installed = self.installed_index() or {}
        idx = {}
        for line in r.stdout.splitlines():
            cols = line.split()
            if len(cols) < 3 or '.' not in cols[0] or cols[0].startswith('Obsoleting'):
                continue                               # header / blank / obsoletes section
            name = cols[0].rsplit('.', 1)[0]           # strip .x86_64 / .noarch
            idx.setdefault(name, (installed.get(name), cols[1]))
        return idx

    def held_keys(self):
        # `dnf versionlock list` — dnf5 prints "Package name: <n>"; dnf4 prints name-version globs.
        r = self.runner.run('dnf versionlock list')
        if not r.ok:
            return None
        held = set()
        for line in r.stdout.splitlines():
            s = line.strip()
            if s.startswith('Package name:'):
                held.add(s.split(':', 1)[1].strip())
        return held

    def upgrade_all(self):
        return self.runner.run('dnf upgrade -y', sudo=True, capture=False)

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
        # enable-repo: turn on a distro repo that ships disabled — e.g. EL's CRB
        # (CodeReady Builder), which RPM Fusion's ffmpeg needs (ladspa/rubberband live
        # there). config-manager is in dnf-plugins-core; ensure it, then enable each.
        enable = _as_list(f.get('enable-repo'))
        if enable:
            self.runner.run('dnf install -y dnf-plugins-core', sudo=True, capture=False)
            for repo in enable:
                self.runner.run(f'dnf config-manager --set-enabled {shlex.quote(repo)}',
                                sudo=True, capture=False)
        repo_id, repo_url = f.get('repo-id'), f.get('repo-url')
        if repo_id and repo_url:
            name = f.get('repo-name', repo_id)
            # a newline in any value would inject extra INI keys (e.g. gpgcheck=0) — reject it.
            if any('\n' in str(v) for v in (repo_id, name, repo_url, key or '')):
                return Result.fail(f'{repo_id}: a repo field contains a newline')
            # with a key, verify against it; WITHOUT one, gpgcheck=0 (can't verify) — never the
            # literal `gpgkey=None` that made gpgcheck=1 fail every install from this repo.
            gpg = f'gpgcheck=1\ngpgkey={key}\n' if key else 'gpgcheck=0\n'
            content = f'[{repo_id}]\nname={name}\nbaseurl={repo_url}\nenabled=1\n{gpg}'
            return self._commit_repo(content, repo_id)

    def _commit_repo(self, content, repo_id):
        '''Write a third-party .repo (only if absent), then — for a NEWLY-created one — validate it
        by refreshing ONLY that repo. If the refresh fails (unreachable baseurl, bad repomd), roll
        the .repo back so it can't poison every later dnf op. Returns None on success, or a
        classified failing Result. (GPG-at-install verification is dnf's own, later — see docs/
        driver-resilience-plan.md P2/P4.)'''
        path = f'/etc/yum.repos.d/{repo_id}.repo'
        p = shlex.quote(path)
        rid = shlex.quote(repo_id)
        existed = self.runner.run(f'test -f {p}', capture=True).ok
        self.runner.run(
            f'[ -f {p} ] || printf %s {shlex.quote(content)} | sudo tee {p} >/dev/null', capture=True)
        if existed:
            return None                          # already present (worked before) — don't re-validate
        res = self.runner.run(f"dnf -q --disablerepo='*' --enablerepo={rid} makecache",
                              sudo=True, capture=True)
        if res.ok:
            return None
        self.runner.run(f'sudo rm -f {p}', capture=True)   # roll back OUR just-created repo
        cat, rem = classify(res.output)
        tail = res.output.splitlines()[-1].strip() if res.output else 'dnf makecache failed'
        return Result.fail(f'vendor repo setup for {repo_id} failed: {tail} (repo rolled back)',
                           category=cat, remediation=rem)

    # -- mutate -----------------------------------------------------------

    # install/uninstall/upgrade come from the NativePkgManager templates (install/upgrade run
    # ensure_prereqs first — see below). set_version is dnf-specific (install-or-downgrade).
    def set_version(self, rc, version):
        pre = self.ensure_prereqs(rc)
        if pre is not None:
            return pre
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
