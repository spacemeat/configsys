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
    def load(cls, paths):
        roots = [(paths.config_file, 'repo'), (paths.user_config_file, 'user')]
        return cls(layers.expand(roots))

    @property
    def active_profiles(self):
        return _leaves(layers.merge_scalar(self._layers, 'configs', ('repo', 'user')))

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
