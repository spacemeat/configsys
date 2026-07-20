'''flatpak.py — the flatpak driver (user scope).

Operates on flatpaks in the unprivileged `--user` installation (no sudo, and
sandbox-friendly: XDG_DATA_HOME redirects it). We only install/list/update/remove
and mask — never launch — so none of the bwrap/FUSE/dbus runtime machinery is
needed. Route fields: `hub` (remote name, e.g. flathub) and `name` (the app id).

Version lock uses `flatpak mask` (prevents updates). Adding the hub remote is a
prerequisite handled before install/upgrade, mirroring apt's repo-component.

Known limitation (deferred): get_latest returns None, so installed flatpaks show as
"installed" rather than "outdated" — `configsys upgrade <name>` still works and lets
flatpak resolve the latest itself.
'''

import shlex

from ..driver import Driver

# Well-known hub remotes -> their .flatpakrepo URL (routes may override via `hub-url`).
HUB_REPOS = {
    'flathub': 'https://dl.flathub.org/repo/flathub.flatpakrepo',
    'flathub-beta': 'https://dl.flathub.org/beta-repo/flathub-beta.flatpakrepo',
}


class Flatpak(Driver):
    name = 'flatpak'
    privileged = False

    # -- helpers ----------------------------------------------------------

    default_scope = 'user'
    honors_scope = True

    @staticmethod
    def _appid(rc):
        return rc.name  # route `name` field is the flatpak app id

    def _flag(self, rc):
        return '--user' if self.scope(rc) == 'user' else '--system'

    @staticmethod
    def _parse_field(text, field):
        prefix = f'{field}:'
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return None

    def ensure_remote(self, rc):
        hub = rc.fields.get('hub')
        if not hub:
            return
        url = rc.fields.get('hub-url') or HUB_REPOS.get(hub)
        if not url:
            # Unknown hub with no url; assume the remote is already configured.
            return
        self.runner.run(
            f'flatpak remote-add {self._flag(rc)} --if-not-exists {shlex.quote(hub)} '
            f'{shlex.quote(url)}', sudo=self.sudo(rc), capture=False)

    # -- read (scope-agnostic: detect it wherever it's installed; no sudo) -

    def get_version(self, rc):
        # no --user/--system flag: find the app in EITHER installation. (Otherwise a
        # system-installed app looks "missing" under the default user scope.)
        app = shlex.quote(self._appid(rc))
        r = self.runner.run(f'flatpak info {app}')
        if not r.ok:
            return None
        return (self._parse_field(r.stdout, 'Version')
                or self._parse_field(r.stdout, 'Commit')
                or 'installed')

    def get_installed(self, rc):
        # which installation actually has it — so the menu shows the real scope, not the target
        app = shlex.quote(self._appid(rc))
        for scope, flag in (('user', '--user'), ('system', '--system')):
            r = self.runner.run(f'flatpak info {flag} {app}')
            if r.ok:
                return (self._parse_field(r.stdout, 'Version')
                        or self._parse_field(r.stdout, 'Commit') or 'installed', scope)
        return (None, None)

    def get_latest(self, rc):
        # Deferred: no cheap local "latest" for flatpak; avoid a network call per
        # inspect. `flatpak update` resolves latest at upgrade time.
        return None

    def is_locked(self, rc):
        appid = self._appid(rc)
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak mask {flag}')
            if r.ok and any(appid in line for line in r.stdout.splitlines()):
                return True
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        self.ensure_remote(rc)
        hub = shlex.quote(rc.fields.get('hub', ''))
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak install {self._flag(rc)} -y {hub} {app}',
                               sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak uninstall {self._flag(rc)} -y {app}',
                               sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        self.ensure_remote(rc)
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak update {self._flag(rc)} -y {app}',
                               sudo=self.sudo(rc), capture=False)

    def set_version(self, rc, version):
        # flatpak pins by commit; treat `version` as a commit id.
        app = shlex.quote(self._appid(rc))
        commit = shlex.quote(version)
        return self.runner.run(
            f'flatpak update {self._flag(rc)} -y --commit={commit} {app}',
            sudo=self.sudo(rc), capture=False)

    def location(self, rc):
        root = '~/.local/share/flatpak' if self.scope(rc) == 'user' else '/var/lib/flatpak'
        return f'{root}  ({self._appid(rc)})'

    def lock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask {self._flag(rc)} {app}',
                               sudo=self.sudo(rc))

    def unlock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask {self._flag(rc)} --remove {app}',
                               sudo=self.sudo(rc))
