'''flatpak.py — the \\flatpak family (user scope).

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

from ..component import Family

# Well-known hub remotes -> their .flatpakrepo URL (routes may override via `hub-url`).
HUB_REPOS = {
    'flathub': 'https://dl.flathub.org/repo/flathub.flatpakrepo',
    'flathub-beta': 'https://dl.flathub.org/beta-repo/flathub-beta.flatpakrepo',
}


class Flatpak(Family):
    name = 'flatpak'
    privileged = False

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _appid(rc):
        return rc.name  # route `name` field is the flatpak app id

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
            f'flatpak remote-add --user --if-not-exists {shlex.quote(hub)} '
            f'{shlex.quote(url)}', capture=False)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        app = shlex.quote(self._appid(rc))
        r = self.runner.run(f'flatpak info --user {app}')
        if not r.ok:
            return None
        return (self._parse_field(r.stdout, 'Version')
                or self._parse_field(r.stdout, 'Commit')
                or 'installed')

    def get_latest(self, rc):
        # Deferred: no cheap local "latest" for flatpak; avoid a network call per
        # inspect. `flatpak update` resolves latest at upgrade time.
        return None

    def is_locked(self, rc):
        r = self.runner.run('flatpak mask --user')
        if not r.ok:
            return False
        appid = self._appid(rc)
        return any(appid in line for line in r.stdout.splitlines())

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        self.ensure_remote(rc)
        hub = shlex.quote(rc.fields.get('hub', ''))
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak install --user -y {hub} {app}', capture=False)

    def uninstall(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak uninstall --user -y {app}', capture=False)

    def upgrade(self, rc):
        self.ensure_remote(rc)
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak update --user -y {app}', capture=False)

    def set_version(self, rc, version):
        # flatpak pins by commit; treat `version` as a commit id.
        app = shlex.quote(self._appid(rc))
        commit = shlex.quote(version)
        return self.runner.run(
            f'flatpak update --user -y --commit={commit} {app}', capture=False)

    def lock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask --user {app}')

    def unlock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask --user --remove {app}')
