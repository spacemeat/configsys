'''npm.py — the npm driver: global Node CLIs via `npm install -g`.

Scope-honoring (like tarball/flatpak). The default `user` scope installs into a
per-user prefix (~/.local, so binaries land on the standard ~/.local/bin PATH) with
no sudo; `scope: system` installs into node's own global prefix with sudo. Version
state comes from `npm ls -g --json`; there's no native version lock, so lock intent
lives in the ledger.

The npm tool itself is the driver `requires: npm`, satisfied by the `node` toolchain
component (which `provides: npm`). get_latest is deferred to a `version:` spec (no
network per inspect); `npm install` fetches the latest at install time.
'''

import json
import shlex
from pathlib import Path

from ..driver import Driver
from ..runner import Result


_NODE_BUNDLED = {'npm', 'corepack'}   # ship INSIDE the node package on every distro, not user-installed


class Npm(Driver):
    name = 'npm'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    def explicit_keys(self):
        '''The global packages the user actually installed — every global minus the ones bundled with
        node itself (npm, corepack), which appear in `npm ls -g` on every platform but nobody chose.
        None if nothing enumerates -> no filtering.'''
        idx = self.installed_index()
        if idx is None:
            return None
        return set(idx) - _NODE_BUNDLED

    @staticmethod
    def _pkg(rc):
        return rc.name  # route `name` field is the npm package (== the command)

    def _prefix_flag(self, rc):
        '''User scope pins a per-user prefix (sudo-free); system scope uses node's
        own global prefix. Returned with a trailing space so it slots into a command.'''
        if self._scope(rc) == 'system':
            return ''
        home = self.paths.home if self.paths is not None else Path.home()
        return f'--prefix {shlex.quote(str(home / ".local"))} '

    # -- read -------------------------------------------------------------

    def batch_index(self, rcs):
        '''ONE `npm ls -g … --json` per SCOPE prefix (each lists every package in that prefix),
        instead of that same call once per (package × scope) — get_installed probes user+system, so
        N packages was ~2N identical `npm ls` spawns. -> {scope: {pkg: version}}; the scope-probe
        then reads it via get_version. Empty scope maps on failure -> per-unit fallback still works.'''
        home = self.paths.home if self.paths is not None else Path.home()
        cmds = {'user': f'npm ls -g --prefix {shlex.quote(str(home / ".local"))} --depth=0 --json',
                'system': 'npm ls -g --depth=0 --json'}
        out = {}
        for scope, cmd in cmds.items():
            m = {}
            r = self.runner.run(cmd)
            if r.stdout:
                try:
                    for pkg, dep in (json.loads(r.stdout).get('dependencies') or {}).items():
                        if isinstance(dep, dict) and dep.get('version'):
                            m[pkg] = dep['version']
                except ValueError:
                    pass
            out[scope] = m
        return out

    def installed_index(self):
        '''Flat {pkg: version} across BOTH scope prefixes (union) — for the coexistence detector's
        membership test, so N npm units cost two `npm ls` calls, not one per unit. inspect uses the
        SCOPED batch_index instead (get_version needs the per-scope answer). None if nothing found.'''
        flat = {}
        for m in self.batch_index([]).values():
            flat.update(m)
        return flat or None

    def get_version(self, rc):
        if self._batch is not None:               # batched: the scope's pre-listed index
            return self._batch.get(self._scope(rc), {}).get(self._pkg(rc))
        # `npm ls -g` often exits non-zero (unmet peer deps, extraneous pkgs) while still
        # emitting valid JSON, so parse stdout rather than gating on returncode.
        r = self.runner.run(f'npm ls -g {self._prefix_flag(rc)}--depth=0 --json')
        if not r.stdout:
            return None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return None
        dep = (data.get('dependencies') or {}).get(self._pkg(rc))
        return dep.get('version') if dep else None

    def get_installed(self, rc):
        # a package may sit in either prefix; probe both so a scope mismatch never
        # reads as "missing" (mirrors the path-based scope-honoring drivers).
        return self._installed_across_scopes(rc)

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'npm install -g {self._prefix_flag(rc)}{shlex.quote(self._pkg(rc))}',
            sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        return self.runner.run(
            f'npm uninstall -g {self._prefix_flag(rc)}{shlex.quote(self._pkg(rc))}',
            sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        return self.runner.run(
            f'npm update -g {self._prefix_flag(rc)}{shlex.quote(self._pkg(rc))}',
            sudo=self.sudo(rc), capture=False)

    def set_version(self, rc, version):
        spec = f'{self._pkg(rc)}@{version}'
        return self.runner.run(
            f'npm install -g {self._prefix_flag(rc)}{shlex.quote(spec)}',
            sudo=self.sudo(rc), capture=False)

    def lock(self, rc):
        return Result('(npm lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(npm unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.local/bin' if self._scope(rc) != 'system' else None
