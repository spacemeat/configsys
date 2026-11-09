'''luarocks.py — the luarocks driver: Lua rocks via `luarocks install`.

Scope-honoring. The default `user` scope installs with `--local` (into the per-user
tree ~/.luarocks, no sudo); `scope: system` installs into the system rock tree with
sudo. Installed state comes from `luarocks list --porcelain` (tab-separated
name/version/status/path). No native version lock, so lock intent lives in the ledger.

The luarocks tool is the driver `requires: luarocks`, satisfied by the `luarocks`
component (which pulls lua). Command syntax confirmed against luarocks 3.8.0.
'''

import shlex

from ._module import ModuleDriver


class LuaRocks(ModuleDriver):
    name = 'luarocks'
    default_scope = 'user'
    honors_scope = True
    TOOL = 'luarocks'
    # --local (the per-user tree) on install/remove in user scope; installing an already-present
    # rock upgrades it to the latest
    CMDS = {'install': '{tool} install {scope}{pkg}',
            'uninstall': '{tool} remove {scope}{pkg}',
            'upgrade': '{tool} install {scope}{pkg}',
            'set_version': '{tool} install {scope}{pkg} {ver}'}
    SCOPE_FLAGS = {'user': '--local'}
    BIN_DIR = '~/.luarocks'

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
        r = self.runner.run(f'luarocks list --porcelain {shlex.quote(self.module(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0] == self.module(rc):
                return parts[1]
        return None

    def get_installed(self, rc):
        # `luarocks list` spans both trees, so a per-scope re-probe can't tell them apart: read the
        # TREE each rock lives in (B14) — a user rock on a `scope: system` machine reads `user`
        if isinstance(self.batch, dict) and 'scopes' in self.batch:
            v = self.batch['installed'].get(self.index_key(rc))
            where = self.batch['scopes'].get(self.index_key(rc), set())
        else:
            rows = [row for row in (self._rows(self.module(rc)) or []) if row[0] == self.module(rc)]
            v = rows[0][1] if rows else None
            where = {self._tree_scope(tree) for _n, _v, tree in rows}
        if v is None:
            return (None, None)
        want = self._scope(rc)
        return (v, want if (want in where or not where) else sorted(where)[0])
