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

    def installed_index(self):
        # ONE call lists every installed app (either installation) -> {app-id: version}.
        r = self.runner.run('flatpak list --app --columns=application,version')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            cols = line.split('\t') if '\t' in line else line.split()
            if cols and cols[0].strip():
                idx[cols[0].strip()] = (cols[1].strip() if len(cols) > 1 else '') or 'installed'
        return idx

    def index_key(self, rc):
        return self._appid(rc)

    def batch_index(self, rcs):
        '''Pre-fetch the inspect probes for these units in a FIXED few calls instead of ~4 per app.
        remote-info is ~2s/app; `flatpak remote-ls <hub>` lists a whole remote (all of flathub =
        3453 apps in ~2s), so ONE remote-ls per distinct hub replaces every per-app remote-info for
        that hub. Plus one `flatpak list` (installed app -> version+scope) and one `flatpak mask` per
        installation (mask ignores its arg). None only if nothing probes -> per-unit fallback.'''
        installed = {}                                 # app -> (version, scope)
        r = self.runner.run('flatpak list --app --columns=application,version,installation')
        if r.ok:
            for line in r.stdout.splitlines():
                cols = line.split('\t') if '\t' in line else line.split()
                if cols and cols[0].strip():
                    ver = (cols[1].strip() if len(cols) > 1 else '') or 'installed'
                    inst = cols[2].strip() if len(cols) > 2 else ''
                    installed[cols[0].strip()] = (ver, inst if inst in ('user', 'system') else 'user')
        masked = set()                                 # locked (masked) app ids, either installation
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak mask {flag}')
            if r.ok:
                masked.update(x.strip() for x in r.stdout.split() if x.strip())
        candidate = {}                                 # hub -> {app: version}
        for hub in sorted({rc.fields.get('hub') for rc in rcs if rc.fields.get('hub')}):
            hubq = shlex.quote(hub)
            for flag in ('--system', '--user'):        # the version is scope-independent; first hit wins
                r = self.runner.run(f'flatpak remote-ls {flag} {hubq} --app --columns=application,version')
                if r.ok:
                    m = {}
                    for line in r.stdout.splitlines():
                        cols = line.split('\t') if '\t' in line else line.split()
                        if cols and cols[0].strip():
                            m[cols[0].strip()] = (cols[1].strip() if len(cols) > 1 else '') or None
                    candidate[hub] = m
                    break
        return {'installed': installed, 'masked': masked, 'candidate': candidate}

    def get_version(self, rc):
        if self._batch is not None:                    # batched: from the one `flatpak list`
            v = self._batch['installed'].get(self._appid(rc))
            return v[0] if v else None
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
        if self._batch is not None:                    # batched: version + which installation
            v = self._batch['installed'].get(self._appid(rc))
            return v if v else (None, None)
        # which installation actually has it — so the menu shows the real scope, not the target
        app = shlex.quote(self._appid(rc))
        for scope, flag in (('user', '--user'), ('system', '--system')):
            r = self.runner.run(f'flatpak info {flag} {app}')
            if r.ok:
                return (self._parse_field(r.stdout, 'Version')
                        or self._parse_field(r.stdout, 'Commit') or 'installed', scope)
        return (None, None)

    def get_latest(self, rc):
        hub = rc.fields.get('hub')
        if not hub:
            return None
        if self._batch is not None:                    # batched: from the one remote-ls per hub
            return (self._batch['candidate'].get(hub) or {}).get(self._appid(rc)) or None
        # The remote's available version, from `flatpak remote-info` — read from flatpak's LOCAL
        # appstream metadata (refreshed on `flatpak update`/`flatpak remote-ls`), NOT a live network
        # fetch. The remote can exist in BOTH the user and system installations, which makes a bare
        # `remote-info` ambiguous (it prompts) — so disambiguate with a scope flag; either resolves
        # the same remote metadata. Version only (a bare commit hash isn't version-comparable).
        app, hubq = shlex.quote(self._appid(rc)), shlex.quote(hub)
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak remote-info {flag} {hubq} {app}')
            if r.ok:
                return self._parse_field(r.stdout, 'Version') or None
        return None

    def is_locked(self, rc):
        appid = self._appid(rc)
        if self._batch is not None:                    # batched: membership in the mask set
            return appid in self._batch['masked']
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
