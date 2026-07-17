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

        uc = self.env.get('CONFIGSYS_CONFIG')
        self.user_config_file = Path(uc) if uc else self.home / 'configsys.hu'

        sd = self.env.get('CONFIGSYS_STATE_DIR')
        if sd:
            self.state_dir = Path(sd)
        else:
            xdg = self.env.get('XDG_CONFIG_HOME')
            base = Path(xdg) if xdg else self.home / '.config'
            self.state_dir = base / 'configsys'
        self.ledger_file = self.state_dir / 'state.hu'
        self.versions_file = self.state_dir / 'versions.hu'   # discovered-version cache

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
