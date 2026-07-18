'''paths.py — single source of truth for every filesystem location configsys uses.

All paths derive from environment variables with sensible defaults so a test (or a
sandboxed run) can redirect everything at a scratch directory without touching the
real account. Nothing here reads or writes; it only computes locations.

Env overrides:
  CONFIGSYS_HOME       base for ~-relative paths            (default: $HOME)
  CONFIGSYS_REPO       repo root holding config.hu/routes.hu (default: package parent)
  CONFIGSYS_CONFIG     per-machine selector file            (default: <home>/configsys.hu)
  CONFIGSYS_STATE_DIR  ledger directory                     (default: <config>/configsys)
  XDG_CONFIG_HOME      base for the default state dir        (default: <home>/.config)
'''

import os
from pathlib import Path


class Paths:
    def __init__(self, env=None):
        self.env = dict(os.environ) if env is None else dict(env)

        self.home = Path(
            self.env.get('CONFIGSYS_HOME') or self.env.get('HOME') or Path.home()
        )

        repo = self.env.get('CONFIGSYS_REPO')
        # package lives at <repo>/configsys/paths.py -> repo is two parents up.
        self.repo = Path(repo) if repo else Path(__file__).resolve().parent.parent

        self.routes_file = self.repo / 'routes.hu'
        self.config_file = self.repo / 'config.hu'
        self.dotfiles_dir = self.repo / 'dotfiles'   # source tree for the dotfiles family

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
        self.versions_file = self.state_dir / 'versions.hu'   # discovered-version cache
        self.plugins_dir = self.state_dir / 'plugins'         # synced remote plugin repos

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

    def __repr__(self):
        return (f'Paths(home={self.home}, repo={self.repo}, '
                f'user_config={self.user_config_file}, ledger={self.ledger_file})')
