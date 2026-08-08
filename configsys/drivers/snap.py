'''snap.py — the snap driver (Ubuntu + descendants).

Installs snaps from the Snap Store via snapd. System-owned (snapd runs as root), so the mutating
ops sudo; reads don't. Route fields: `name` (the snap name), optional `classic: true` (classic
confinement — some snaps, e.g. code/slack, need it), optional `channel:` (default the store's
default, usually latest/stable). Snap bindings are gated to `ubuntu` in the routes (snapd ships on
Ubuntu and its descendants; other distros can install snapd but that's a deliberate opt-in, not
assumed here).

get_version parses `snap list <name>`; get_latest reads the channel line from `snap info <name>`
(local store metadata, refreshed by snapd — no live fetch). Version lock uses `snap refresh --hold`.
'''

import shlex

from ..driver import Driver


class Snap(Driver):
    name = 'snap'
    privileged = True          # snapd is root-owned; install/remove/refresh need sudo
    default_scope = 'system'
    honors_scope = False

    @staticmethod
    def _snap(rc):
        return rc.name          # route `name` field is the snap name

    def _extra(self, rc):
        '''install flags derived from the binding: --classic and/or --channel=.'''
        flags = []
        if str(rc.fields.get('classic', '')).lower() in ('true', '1', 'yes', 'on'):
            flags.append('--classic')
        ch = rc.fields.get('channel')
        if ch:
            flags.append(f'--channel={shlex.quote(str(ch))}')
        return ' '.join(flags)

    # -- read (no sudo) ---------------------------------------------------

    def get_version(self, rc):
        # `snap list <name>` -> header + one row: Name Version Rev Tracking Publisher Notes
        r = self.runner.run(f'snap list {shlex.quote(self._snap(rc))}')
        if not r.ok:
            return None
        rows = [ln for ln in r.stdout.splitlines() if ln.strip()]
        if len(rows) < 2:
            return None
        cols = rows[1].split()
        return cols[1] if len(cols) > 1 else 'installed'

    def get_latest(self, rc):
        # `snap info <name>` lists a `channels:` block: `latest/stable: 1.2.3 2026-01-01 (rev) size`.
        ch = str(rc.fields.get('channel') or 'latest/stable')
        if '/' not in ch:
            ch = f'latest/{ch}'
        r = self.runner.run(f'snap info {shlex.quote(self._snap(rc))}')
        if not r.ok:
            return None
        want = f'{ch}:'
        for line in r.stdout.splitlines():
            s = line.strip()
            if s.startswith(want):
                rest = s[len(want):].split()
                return rest[0] if rest and rest[0] != '--' else None
        return None

    def is_locked(self, rc):
        # a held snap shows `held` in `snap list`'s Notes column. Best-effort.
        r = self.runner.run(f'snap list {shlex.quote(self._snap(rc))}')
        if not r.ok:
            return False
        return any(self._snap(rc) in ln and 'held' in ln for ln in r.stdout.splitlines())

    # -- mutate (sudo) ----------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'snap install {self._extra(rc)} {shlex.quote(self._snap(rc))}'.replace('  ', ' '),
            sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'snap remove {shlex.quote(self._snap(rc))}', sudo=True, capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'snap refresh {shlex.quote(self._snap(rc))}', sudo=True, capture=False)

    def set_version(self, rc, version):
        # snap pins by channel (or revision via --revision); treat `version` as a channel.
        return self.runner.run(
            f'snap refresh --channel={shlex.quote(str(version))} {shlex.quote(self._snap(rc))}',
            sudo=True, capture=False)

    def lock(self, rc):
        return self.runner.run(f'snap refresh --hold {shlex.quote(self._snap(rc))}', sudo=True)

    def unlock(self, rc):
        return self.runner.run(f'snap refresh --unhold {shlex.quote(self._snap(rc))}', sudo=True)

    def location(self, rc):
        return f'/snap/{self._snap(rc)}  (snapd)'
