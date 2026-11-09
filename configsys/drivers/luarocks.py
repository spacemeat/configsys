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

    def _rows(self, rock=None):
        '''[(rock, version, tree)] from `luarocks list --porcelain` (name/version/status/tree), or None.'''
        r = self.runner.run('luarocks list --porcelain' + (f' {shlex.quote(rock)}' if rock else ''))
        if not r.ok:
            return None
        rows = []
        for line in r.stdout.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0]:
                rows.append((parts[0], parts[1], parts[3] if len(parts) > 3 else ''))
        return rows

    def _tree_scope(self, tree):
        '''A rock tree's scope: the per-user ~/.luarocks (or anything under your home) is user.'''
        import os
        home = str(self.paths.home) if self.paths is not None else os.path.expanduser('~')
        return 'user' if tree and ('/.luarocks' in tree or tree.startswith(home.rstrip('/') + '/')) \
            else 'system'

    def installed_index(self):
        '''{rock: version} from ONE `luarocks list --porcelain` — the base batch_index enumerates
        once instead of a call per rock during inspect. The tree of each row is kept for scope.'''
        rows = self._rows()
        if rows is None:
            return None
        idx, self._scopes = {}, {}
        for name, ver, tree in rows:
            idx.setdefault(name, ver)                # first (newest) entry wins
            self._scopes.setdefault(name, set()).add(self._tree_scope(tree))
        return idx

    def batch_index(self, rcs):
        b = super().batch_index(rcs)
        if b is not None:
            b['scopes'] = getattr(self, '_scopes', {})
        return b

    def get_version(self, rc):
        ver, hit = self.batched_version(rc)          # answer from the one porcelain listing when batched
        if hit:
            return ver
        r = self.runner.run(f'luarocks list --porcelain {shlex.quote(self._rock(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0] == self._rock(rc):
                return parts[1]
        return None

    def get_installed(self, rc):
        # `luarocks list` spans both trees, so a per-scope re-probe can't tell them apart: read the
        # TREE each rock lives in (B14) — a user rock on a `scope: system` machine reads `user`
        if isinstance(self.batch, dict) and 'scopes' in self.batch:
            v = self.batch['installed'].get(self.index_key(rc))
            where = self.batch['scopes'].get(self.index_key(rc), set())
        else:
            rows = [row for row in (self._rows(self._rock(rc)) or []) if row[0] == self._rock(rc)]
            v = rows[0][1] if rows else None
            where = {self._tree_scope(tree) for _n, _v, tree in rows}
        if v is None:
            return (None, None)
        want = self._scope(rc)
        return (v, want if (want in where or not where) else sorted(where)[0])

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

    def location(self, rc):
        return '~/.luarocks' if self._scope(rc) != 'system' else None
