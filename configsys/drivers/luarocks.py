'''luarocks.py — the luarocks driver: Lua rocks via `luarocks install`.

Scope-honoring. The default `user` scope installs with `--local` (into the per-user
tree ~/.luarocks, no sudo); `scope: system` installs into the system rock tree with
sudo. Installed state comes from `luarocks list --porcelain` (tab-separated
name/version/status/path). No native version lock, so lock intent lives in the ledger.

The luarocks tool is the driver `requires: luarocks`, satisfied by the `luarocks`
component (which pulls lua). Command syntax confirmed against luarocks 3.8.0.
'''

import shlex

from ..driver import Driver
from ..runner import Result


class LuaRocks(Driver):
    name = 'luarocks'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    @staticmethod
    def _rock(rc):
        return rc.name

    def _local_flag(self, rc):
        # --local applies to install/remove; only user scope uses it
        return '' if self._scope(rc) == 'system' else '--local '

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'luarocks list --porcelain {shlex.quote(self._rock(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0] == self._rock(rc):
                return parts[1]
        return None

    def get_installed(self, rc):
        return self._installed_across_scopes(rc)

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'luarocks install {self._local_flag(rc)}{shlex.quote(self._rock(rc))}',
                               sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'luarocks remove {self._local_flag(rc)}{shlex.quote(self._rock(rc))}',
                               sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        # install of an already-present rock upgrades it to the latest
        return self.install(rc)

    def set_version(self, rc, version):
        return self.runner.run(
            f'luarocks install {self._local_flag(rc)}{shlex.quote(self._rock(rc))} '
            f'{shlex.quote(version)}', sudo=self.sudo(rc), capture=False)

    def lock(self, rc):
        return Result('(luarocks lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(luarocks unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.luarocks' if self._scope(rc) != 'system' else None
