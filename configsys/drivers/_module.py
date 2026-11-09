'''_module.py — the shared base for the language-ecosystem installers (review-2026-11-2 D5).

cargo, pip, pipx, npm, gem, opam, luarocks, cabal, go-install and sdkman all do the same thing: hand
a named MODULE (a crate, a PyPI dist, a gem, a rock, a candidate) to the ecosystem's own tool. What
differs is data, so a subclass states it as class attributes and overrides only what is bespoke
(pipx's backend/interpreter, cabal's index + exe, go's checkout build, gem's default gems, sdkman's
init):

  TOOL          the command every op runs: `cargo`, `python3 -m pipx`, or a `PATH="…:$PATH" go`
                prefix that puts a configsys-managed toolchain first. `tool(rc)` may vary it (pip's
                interpreter pin).
  CMDS          {op: template} for install / uninstall / upgrade / set_version. Placeholders:
                  {tool}   tool(rc)
                  {pkg}    the module name, shell-quoted
                  {ver}    the requested version, shell-quoted (set_version)
                  {spec}   VERSION_SPEC filled in and shell-quoted (`ripgrep@14.1`, `black==24.1`)
                  {scope}  the scope flag with a trailing space, or '' (see SCOPE_FLAGS)
                plus whatever `placeholders(op, rc)` adds (pipx: {backend}, {python}).
  VERSION_SPEC  how set_version spells module + version: '{pkg}@{ver}', '{pkg}=={ver}', '{pkg}.{ver}'.
  SCOPE_FLAGS   {scope: flag} — the flag that ops on a scope-honoring driver carry (gem's
                `--user-install`, luarocks' `--local`); npm computes its own (`--prefix ~/.local`).
  LIST_CMD      the ONE enumeration `installed_index` runs ({tool} expands), parsed by
                `parse_list(stdout)` -> {key: version}; keys match `index_key(rc)`.
  BIN_DIR       where the user-scope install lands, for `location` (system scope: None).

Every op runs with `capture=False` (the user watches the tool's output) and sudo only for a
scope-honoring driver's system scope. Lock state is the ledger's (the Driver defaults): none of these
ecosystems has a native hold.
'''

import shlex

from ..driver import Driver


class ModuleDriver(Driver):
    privileged = False
    TOOL = ''
    CMDS = {}
    VERSION_SPEC = '{pkg}'
    SCOPE_FLAGS = {}
    LIST_CMD = None
    BIN_DIR = None

    # -- identity + command building ----------------------------------------

    @staticmethod
    def module(rc):
        '''The module this unit installs — the route's `name` (== the component unless routed
        otherwise).'''
        return rc.name

    def index_key(self, rc):
        return self.module(rc)

    def tool(self, rc=None):
        return self.TOOL

    def scope_flag(self, rc):
        '''The scope flag ops carry, with a trailing space so it slots into a template, or ''.'''
        if not self.honors_scope:
            return ''
        flag = self.SCOPE_FLAGS.get(self._scope(rc), '')
        return f'{flag} ' if flag else ''

    def placeholders(self, op, rc):
        '''Extra template placeholders a subclass supplies for `op` (pipx: its backend and
        interpreter flags — computed only for the ops whose template names them).'''
        return {}

    def command(self, op, rc, version=None):
        '''The shell command for `op` on `rc`, from CMDS[op].'''
        mod = self.module(rc)
        ver = '' if version is None else str(version)
        spec = self.VERSION_SPEC.format(pkg=mod, ver=ver) if version is not None else mod
        return self.CMDS[op].format(tool=self.tool(rc), pkg=shlex.quote(mod), ver=shlex.quote(ver),
                                    spec=shlex.quote(spec), scope=self.scope_flag(rc),
                                    **self.placeholders(op, rc))

    def run_op(self, op, rc, version=None):
        return self.runner.run(self.command(op, rc, version),
                               sudo=self.honors_scope and self.sudo(rc), capture=False)

    # -- read -------------------------------------------------------------

    def parse_list(self, stdout):
        '''{key: version} from LIST_CMD's output. Subclasses with a LIST_CMD override.'''
        raise NotImplementedError

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        # only a driver with a LIST_CMD enumerates: callers read "overrides installed_index" as "can
        # list what it installed" (the orphan scan, the Profiles probe skip), so the listing is
        # installed per subclass, never inherited as a None-returning stub
        if cls.LIST_CMD is not None and 'installed_index' not in vars(cls):
            cls.installed_index = ModuleDriver._listed_index

    def _listed_index(self):
        r = self.runner.run(self.LIST_CMD.format(tool=self.tool()))
        if not r.ok:
            return None
        return self.parse_list(r.stdout or '')

    def get_version(self, rc):
        ver, hit = self.batched_version(rc)          # one enumeration for the whole batch
        if hit:
            return ver
        idx = self.installed_index()                  # unbatched: still one enumeration, per unit
        return idx.get(self.index_key(rc)) if idx is not None else None

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.run_op('install', rc)

    def uninstall(self, rc):
        return self.run_op('uninstall', rc)

    def upgrade(self, rc):
        return self.run_op('upgrade', rc)

    def set_version(self, rc, version):
        return self.run_op('set_version', rc, version)

    # -- presentation -----------------------------------------------------

    def location(self, rc):
        if self.honors_scope and self._scope(rc) == 'system':
            return None
        return self.BIN_DIR
