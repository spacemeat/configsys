'''config.py — load profile definitions and the per-machine selection.

Two troves overlay, section by section:
  * repo config.hu  — shared, git-synced `profiles: { ... }` definitions (source of truth)
  * ~/configsys.hu  — this machine's `configs: [...]` selection + `scope:` + optional
                      `profiles:`/`components:`/`pins:` overrides

`configs` and `scope` are top-level machine settings (user file wins). Profiles live in a
`profiles:` section; a profile named in the user's section shadows the repo's same-named
one (per-name overlay). A profile is a flat list of component names; nested values are
tolerated and flattened to leaf names. (`components:`/`pins:` sections are consumed by the
resolver, not here.)
'''

import humon as h

from .errors import ConfigError
from .troveio import load

VALUE = h.NodeKind.VALUE
LIST = h.NodeKind.LIST


def _values(node):
    '''`configs` may be a single value or a list.'''
    if node.kind == VALUE:
        return [node.value]
    return _leaf_values(node)


def _leaf_values(node):
    '''All leaf scalar values under a node, in order (flattens any nesting).'''
    if node.kind == VALUE:
        return [node.value]
    out = []
    for i in range(node.num_children):
        out.extend(_leaf_values(node[i]))
    return out


class Config:
    def __init__(self, config_trove, user_trove=None):
        self.config_trove = config_trove      # keep alive
        self.user_trove = user_trove          # keep alive
        self._c = config_trove.root
        self._u = user_trove.root if user_trove is not None else None

    @classmethod
    def load(cls, paths):
        config_trove = load(paths.config_file)
        user_trove = None
        if paths.user_config_file.exists():
            user_trove = load(paths.user_config_file)
        return cls(config_trove, user_trove)

    def _get(self, key):
        '''Top-level node (configs / scope), user file overriding repo file.'''
        if self._u is not None:
            n = self._u[key]
            if n is not None:
                return n
        return self._c[key]

    def _profile_node(self, name):
        '''A profile from the `profiles:` section, user file overriding repo per profile
        name (so the user can shadow one profile without replacing the whole section).'''
        for root in (self._u, self._c):
            if root is None:
                continue
            section = root['profiles']
            if section is not None and section[name] is not None:
                return section[name]
        return None

    @property
    def active_profiles(self):
        node = self._get('configs')
        return _values(node) if node is not None else []

    def default_scope(self):
        '''Machine-wide install scope default (top-level `scope` in either file),
        or None to let each family use its own default.'''
        node = self._get('scope')
        return node.value if node is not None and node.kind == VALUE else None

    def profile_components(self, profile):
        node = self._profile_node(profile)
        if node is None:
            raise ConfigError(f'profile "{profile}" is selected but not defined '
                              f'(add it under `profiles:` in config.hu or ~/configsys.hu)')
        return _leaf_values(node)

    def requested(self):
        '''Ordered {component_name: [profiles that requested it]} across active profiles.'''
        out = {}
        for prof in self.active_profiles:
            for name in self.profile_components(prof):
                out.setdefault(name, [])
                if prof not in out[name]:
                    out[name].append(prof)
        return out
