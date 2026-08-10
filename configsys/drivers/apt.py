'''apt.py — the Debian/apt driver.

Version state via dpkg-query + apt-cache policy; mutation via apt-get; version
lock via apt-mark hold/unhold. Mutating ops run under sudo and stream their output
(capture=False) so the user sees apt's progress and sudo can prompt.
'''

import shlex

from ..driver import Driver


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

        # `debconf`: preseed install-time debconf answers so a NON-interactive install makes
        # the choice we want instead of the silent default (e.g. wireshark's non-root-capture
        # setuid, which apt otherwise declines). Each entry is a raw debconf-set-selections
        # line "<owner> <question> <type> <value>". Preseed always; and if the owning package
        # is ALREADY installed, dpkg-reconfigure it so the answer takes effect on this run too
        # — not only on a fresh install. (dnf/pacman don't read this field.)
        for line in self._as_list(f.get('debconf')):
            owner = (line.split(None, 1) or [''])[0]
            if not owner:
                continue
            lq, oq = shlex.quote(line), shlex.quote(owner)
            self.runner.run(
                f'echo {lq} | debconf-set-selections && '
                f'if dpkg-query -W -f=\'${{Status}}\' {oq} 2>/dev/null '
                f'| grep -q "install ok installed"; then '
                f'DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive {oq}; fi',
                sudo=True, capture=False)

    # -- read -------------------------------------------------------------

    def installed_index(self):
        # ONE call lists every installed package -> {name: version}; the coexistence detector does
        # membership lookups instead of a dpkg-query per component. \n-terminated (multiarch rows).
        r = self.runner.run("dpkg-query -W -f='${Package} ${Version}\\n'")
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            name, _, ver = line.partition(' ')
            if name:
                idx[name] = ver.strip() or 'installed'
        return idx

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

    # -- read: available version ------------------------------------------
    # (A tool that ships an upstream .deb rather than living in the apt repos is its own via:
    # native-pkg-file — see drivers/native_pkg_file.py. apt is just the distro repos.)

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
