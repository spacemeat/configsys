'''config.py — the per-machine selection + profile definitions, over the layer stack.

Reads from the shared layer engine (layers.py): the repo config.hu is the base, an included
file sits below the file that includes it, and the user ~/configsys.hu wins. `configs` (which
profiles apply) and `scope` are machine SETTINGS — from the repo/user files, not includes.
`profiles:` are DEFINITIONS — merged per name across all layers (so an included project file
can contribute a profile). `pins:` likewise (repo/user). Values flatten to leaf names.
'''

from . import layers
from .errors import ConfigError


def _leaves(v):
    '''Flatten a profile / configs value to its leaf scalar names (lists + nested dicts).'''
    if isinstance(v, list):
        return [leaf for x in v for leaf in _leaves(x)]
    if isinstance(v, dict):
        return [leaf for x in v.values() for leaf in _leaves(x)]
    return [] if v is None else [v]


class Config:
    def __init__(self, layer_list):
        self._layers = layer_list
        self._profiles = layers.merge_named(layer_list, 'profiles')   # name -> (val, src, shadows)

    @classmethod
    def load(cls, paths, discovered=()):
        roots = [(paths.config_file, 'repo')]
        roots += [(d, 'discover') for d in discovered]
        roots.append((paths.user_config_file, 'user'))
        return cls(layers.expand_tolerant(roots, {'discover'})[0])

    @property
    def active_profiles(self):
        '''Explicit `configs:` (repo/user) UNION every profile a discovered project file
        defines (auto-activation), minus `ignore-profiles:`. Explicit first, then discovered.'''
        explicit = _leaves(layers.merge_scalar(self._layers, 'configs', ('repo', 'user')))
        ignore = set(_leaves(layers.merge_scalar(self._layers, 'ignore-profiles', ('repo', 'user'))))
        seen, out = set(), []
        for name in explicit + self._discovered_profiles():
            if name not in seen and name not in ignore:
                seen.add(name)
                out.append(name)
        return out

    def _discovered_profiles(self):
        '''Profile names from discovered (project) layers — auto-activated on discovery.'''
        out = []
        for layer in self._layers:
            if layer.role == 'discover' and isinstance(layer.data.get('profiles'), dict):
                out.extend(layer.data['profiles'])
        return out

    def default_scope(self):
        v = layers.merge_scalar(self._layers, 'scope', ('repo', 'user'))
        return v if isinstance(v, str) else None

    def pins(self):
        v = layers.merge_scalar(self._layers, 'pins', ('repo', 'user'))
        return {k: val for k, val in v.items()
                if not isinstance(val, (dict, list))} if isinstance(v, dict) else {}

    def profile_components(self, profile):
        entry = self._profiles.get(profile)
        if entry is None:
            raise ConfigError(
                f'profile "{profile}" is selected but not defined '
                f'(add it under `profiles:` in config.hu, ~/configsys.hu, or an included file)')
        return _leaves(entry[0])

    def profile_source(self, profile):
        '''The file a selected profile's definition came from (provenance), or None.'''
        entry = self._profiles.get(profile)
        return entry[1] if entry is not None else None

    def requested(self):
        '''Ordered {component_name: [profiles that requested it]} across active profiles.'''
        out = {}
        for prof in self.active_profiles:
            for name in self.profile_components(prof):
                out.setdefault(name, [])
                if prof not in out[name]:
                    out[name].append(prof)
        return out
