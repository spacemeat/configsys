'''paths.py — single source of truth for every filesystem location configsys uses.

All paths derive from environment variables with sensible defaults so a test (or a
sandboxed run) can redirect everything at a scratch directory without touching the
real account. Nothing here reads or writes; it only computes locations.

Env overrides:
  CONFIGSYS_HOME       base for ~-relative paths            (default: $HOME)
  CONFIGSYS_REPO       data root holding config.hu/routes.hu (default: auto — see _locate_data_root)
  CONFIGSYS_CONFIG     per-machine selector file            (default: <home>/configsys.hu)
  CONFIGSYS_STATE_DIR  ledger directory                     (default: <config>/configsys)
  XDG_CONFIG_HOME      base for the default state dir        (default: <home>/.config)

Install-layout overrides (the "config for configsys" — also settable from the shipped
dotfiles/bash.d/00-configsys.sh so your shell and configsys agree). A driver install location is
<scope base>/<category>/<name>; each part is env-overridable with a sensible default:
  CONFIGSYS_USERSCOPE_DIR   base for user-scope installs         (default: ~ = configsys home)
  CONFIGSYS_SYSTEMSCOPE_DIR base for system-scope installs       (default: /opt)
  CONFIGSYS_APP_DIR         self-contained apps  ($CONFIGSYS_APP_DIR)  (default: apps)
  CONFIGSYS_SDK_DIR         SDKs and libraries   ($CONFIGSYS_SDK_DIR)  (default: sdks)
  CONFIGSYS_SRC_DIR         source trees         ($CONFIGSYS_SRC_DIR)  (default: src)
'''

import os
from pathlib import Path

# The install-layout category variables and their defaults. A driver install location is
# <scope base>/<category>/<name>; routes name the category via these $VARs (e.g.
# `installDir: $CONFIGSYS_APP_DIR/lazygit`) so one env override relocates the whole class.
_DIR_VARS = {
    'CONFIGSYS_APP_DIR': 'apps',
    'CONFIGSYS_SDK_DIR': 'sdks',
    'CONFIGSYS_SRC_DIR': 'src',
}


class Paths:
    def __init__(self, env=None):
        self.env = dict(os.environ) if env is None else dict(env)

        self.home = Path(
            self.env.get('CONFIGSYS_HOME') or self.env.get('HOME') or Path.home()
        )

        # Data root holds the shipped routes.hu / config.hu / dotfiles/ (and man/). It is
        # resolved from three sources in order (see _locate_data_root): an explicit
        # CONFIGSYS_REPO, the source tree (clone/dev), then the installed package's own data
        # (so a `pip install` with no clone still finds its files).
        self.repo = self._locate_data_root()

        self.routes_file = self.repo / 'routes.hu'
        self.config_file = self.repo / 'config.hu'
        self.dotfiles_dir = self.repo / 'dotfiles'   # content root for the dotfiles driver

        # state dir (holds the ledger, the version cache, AND the user config). XDG by
        # default; CONFIGSYS_HOME wins over XDG so `--home` fully sandboxes everything.
        sd = self.env.get('CONFIGSYS_STATE_DIR')
        if sd:
            self.state_dir = Path(sd)
        elif self.env.get('CONFIGSYS_HOME'):
            self.state_dir = self.home / '.config' / 'configsys'
        else:
            xdg = self.env.get('XDG_CONFIG_HOME')
            base = Path(xdg) if xdg else self.home / '.config'
            self.state_dir = base / 'configsys'

        # user config lives with state (XDG): ~/.config/configsys/configsys.hu. The old
        # ~/configsys.hu is migrated there on first run (Context._migrate_user_config).
        uc = self.env.get('CONFIGSYS_CONFIG')
        self.user_config_file = Path(uc) if uc else self.state_dir / 'configsys.hu'
        self.legacy_user_config_file = self.home / 'configsys.hu'
        self.ledger_file = self.state_dir / 'state.hu'
        self.failure_file = self.state_dir / 'last-failure.hu'   # last op failure, for `report`
        self.versions_file = self.state_dir / 'versions.hu'   # discovered-version cache
        self.method_versions_file = self.state_dir / 'method-versions.hu'  # per-method get_latest cache (native queries are slow)
        self.plugins_dir = self.state_dir / 'plugins'         # synced remote plugin repos
        self.plugin_trust_file = self.state_dir / 'plugin-trust.hu'   # {plugin: approved commit}

        # dotfiles content overlay: the machine-local store (always) that capture writes to when
        # there's no primary plugin, and that the driver reads FIRST — so your own content shadows
        # any shipped template. `primary_dotfiles_dir` is filled in by the app once the primary
        # plugin is known (Context.ensure_plugin_code); None otherwise.
        self.user_dotfiles_dir = self.state_dir / 'dotfiles'
        self.primary_dotfiles_dir = None

    def _locate_data_root(self) -> Path:
        '''Where routes.hu / config.hu / dotfiles/ live, resolved in precedence order:

        1. CONFIGSYS_REPO — explicit override (tests, sandboxes, a checkout used by an install).
        2. Source tree / clone — the repo root beside the package (``<repo>/configsys/paths.py``
           -> ``<repo>``), used when it actually holds ``routes.hu``. This wins for every clone
           and dev run, so nothing about the from-source workflow changes.
        3. Installed wheel — ``importlib.resources.files('configsys') / 'data'``, where the build
           ships the data files as package data. Only reached when the source-tree root has no
           ``routes.hu`` (i.e. a real ``pip install``), so it never shadows a checkout.

        Falls back to the source-tree guess if nothing matches, so a missing file surfaces as a
        clear ENOENT against a sensible path rather than a None.'''
        override = self.env.get('CONFIGSYS_REPO')
        if override:
            return Path(override)

        src_root = Path(__file__).resolve().parent.parent      # <repo>/configsys/paths.py -> <repo>
        if (src_root / 'routes.hu').exists():
            return src_root

        try:
            import importlib.resources as ir
            data = Path(str(ir.files('configsys'))) / 'data'
            if (data / 'routes.hu').exists():
                return data
        except (ModuleNotFoundError, TypeError, NotADirectoryError, ValueError):
            pass

        return src_root

    def expand(self, p) -> Path:
        '''Expand a route-supplied path against configsys HOME (not the OS home),
        so sandboxed runs stay contained: `~`/`~/x` and *bare relative* paths
        (e.g. `vulkan`) both resolve under HOME; absolute paths pass through. Env
        vars are NOT expanded here — route $VARs are substituted by the resolver.'''
        s = str(p)
        if s == '~':
            return self.home
        if s.startswith('~/'):
            return self.home / s[2:]
        path = Path(s)
        if path.is_absolute():
            return path
        return self.home / path            # bare relative -> home-relative

    def dir_var(self, name):
        '''The value of an install-layout category variable (CONFIGSYS_APP_DIR, ...), from the
        env or its default.'''
        return self.env.get(name, _DIR_VARS[name])

    def _subst_dir_vars(self, s):
        for name in _DIR_VARS:
            token = '$' + name
            if token in s:
                s = s.replace(token, self.dir_var(name))
        return s

    def scope_base(self, scope):
        '''The base dir a `scope` ('user'|'system') installs under — CONFIGSYS_USERSCOPE_DIR
        (default `~`, i.e. configsys HOME) or CONFIGSYS_SYSTEMSCOPE_DIR (default `/opt`).'''
        raw = (self.env.get('CONFIGSYS_SYSTEMSCOPE_DIR', '/opt') if scope == 'system'
               else self.env.get('CONFIGSYS_USERSCOPE_DIR', '~'))
        return self.expand(raw)

    def install_dir(self, raw, scope):
        '''Resolve a driver install location: substitute the $CONFIGSYS_*_DIR category vars (env
        or default), then an absolute / `~` path passes through, and a bare-relative one resolves
        under the scope base. Defaults reproduce the old behavior exactly (~/<raw> for user,
        /opt/<raw> for system), so unmigrated `apps/x` routes are unchanged.'''
        s = self._subst_dir_vars(str(raw))
        if s.startswith('~') or Path(s).is_absolute():
            return self.expand(s)
        return self.scope_base(scope) / s

    def __repr__(self):
        return (f'Paths(home={self.home}, repo={self.repo}, '
                f'user_config={self.user_config_file}, ledger={self.ledger_file})')
