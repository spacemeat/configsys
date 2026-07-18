'''apt.py — the Debian/apt driver.

Version state via dpkg-query + apt-cache policy; mutation via apt-get; version
lock via apt-mark hold/unhold. Mutating ops run under sudo and stream their output
(capture=False) so the user sees apt's progress and sudo can prompt.
'''

import shlex

from ..driver import Driver
from ..runner import Result


class Apt(Driver):
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
        route: extra CPU architectures to enable (`foreign-arch`, e.g. i386 for
        Steam), archive components (`repo-component`), and third-party signing key +
        source list (`pubkey-*`/`source-*`). Idempotent — each step is skipped when
        already satisfied.'''
        f = rc.fields

        for arch in self._as_list(f.get('foreign-arch')):
            a = shlex.quote(arch)
            # enable the multiarch once (idempotent), then refresh lists so its
            # packages become visible. `steam:i386` needs i386 on an amd64 host.
            self.runner.run(
                f'if ! dpkg --print-foreign-architectures | grep -qx {a}; then '
                f'dpkg --add-architecture {a} && apt-get update; fi',
                sudo=True, capture=False)

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

        # `source-line`: an inline `deb ...` line written to source-path (for vendor repos
        # like Microsoft's that ship no downloadable .list — you echo the line yourself).
        src_line = f.get('source-line')
        if src_line and src_path:
            sp, sl = shlex.quote(src_path), shlex.quote(src_line)
            self.runner.run(
                f'if [ ! -f {sp} ]; then echo {sl} | sudo tee {sp} >/dev/null '
                f'&& sudo apt-get update; fi', capture=False)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        pkg = shlex.quote(rc.name)
        # `\n`-terminate the format: a multiarch package (e.g. libvulkan1:amd64 + :i386,
        # once i386 is enabled for Steam) prints one row per installed instance. Without a
        # separator the two versions concatenate into a doubled string that never matches
        # the apt candidate -> perpetually "outdated". Take the first row (arches match).
        r = self.runner.run(f"dpkg-query -W -f='${{Version}}\\n' {pkg}")
        if r.ok and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
        return None

    # -- deb mode (a tool shipping an official .deb, not in the apt repos) -

    @staticmethod
    def _is_deb(rc):
        '''deb-mode: a `deb-source` (github:owner/repo) marks a tool that ships an
        official .deb rather than living in the apt repos.'''
        return 'deb-source' in rc.fields

    def _deb_spec(self, rc):
        '''The github version-discovery spec for the .deb: `deb-source` + the cpu-keyed
        `asset` (this arch's file). Returns None if not a github .deb.'''
        src = rc.fields.get('deb-source')
        if isinstance(src, str) and src.startswith('github:'):
            asset = rc.fields.get('asset')
            if isinstance(asset, dict):
                asset = asset.get(self._arch())
            return {'github': src.split(':', 1)[1], 'asset': asset}
        return None

    def _disco_spec(self, rc):
        # a deb builds its discovery spec from deb-source; otherwise the base version spec.
        return self._deb_spec(rc) or super()._disco_spec(rc)

    def get_latest(self, rc):
        # a deb-mode component isn't in the apt repos; its latest is the version
        # discovery spec (e.g. the github release the .deb comes from)
        if self._is_deb(rc):
            return self.resolve_version(rc)
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

    def _install_deb(self, rc):
        '''Install a .deb downloaded from a release (the version-spec `asset`, via the
        authoritative github URL), letting apt resolve its dependencies. For tools not
        in the apt repos but shipping an official .deb (e.g. fastfetch on Ubuntu).'''
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            return Result(f'(apt: no .deb url resolved for {rc.comp})', 1)
        tmp = f'/tmp/configsys-{rc.comp}.deb'
        cmd = (f'curl -fSL {shlex.quote(url)} -o {shlex.quote(tmp)} && '
               f'apt-get install -y {shlex.quote(tmp)} && rm -f {shlex.quote(tmp)}')
        return self.runner.run(cmd, sudo=True, capture=False)

    def install(self, rc):
        self.ensure_prereqs(rc)
        if self._is_deb(rc):
            return self._install_deb(rc)
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install -y {pkg}', sudo=True, capture=False)

    def uninstall(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get remove -y {pkg}', sudo=True, capture=False)

    def upgrade(self, rc):
        self.ensure_prereqs(rc)
        if self._is_deb(rc):
            return self._install_deb(rc)   # re-fetch the latest release .deb
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-get install --only-upgrade -y {pkg}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        self.ensure_prereqs(rc)
        if self._is_deb(rc):
            return self._install_deb(rc)   # the .deb tracks the discovered version
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
