'''config.py — the per-machine selection + profile definitions, over the layer stack.

Reads from the shared layer engine (layers.py): the repo config.hu is the base, an included
file sits below the file that includes it, and the user ~/configsys.hu wins. `configs` (which
profiles apply) and `scope` are machine SETTINGS — from the repo/user files, not includes.
`profiles:` are DEFINITIONS — merged per name across all layers (so an included project file
can contribute a profile). `pins:` likewise (repo/user). Values flatten to leaf names.
'''

from . import layers
from .errors import ConfigError

# Layer roles that may set MACHINE settings (configs / scope / pins / ignore-profiles), lowest
# precedence first: the repo baseline, then a top-config-designated `primary` plugin (your
# portable personal defaults), then this machine's top user config (which overrides). Ordinary
# `plugin`/`discover`/`include` layers are excluded — a shared plugin can't seize machine control
# unless the local top config explicitly grants it `primary`.
_MACHINE_ROLES = ('repo', 'primary', 'user')


def _leaves(v):
    '''Flatten a profile / configs value to its leaf scalar names (lists + nested dicts).'''
    if isinstance(v, list):
        return [leaf for x in v for leaf in _leaves(x)]
    if isinstance(v, dict):
        return [leaf for x in v.values() for leaf in _leaves(x)]
    return [] if v is None else [v]


def _split_term(term):
    '''A profile-list entry -> (op, name). `+foo` includes profile foo; `~foo` removes
    component foo; a bare name adds a component. (`@` is humon's annotation sigil, so `+` marks
    an include.)'''
    t = str(term)
    if t[:1] == '+':
        return '+', t[1:]
    if t[:1] == '~':
        return '~', t[1:]
    return '', t


class Config:
    def __init__(self, layer_list):
        self._layers = layer_list
        self.load_warnings = []       # files SKIPPED while loading (set by load()); see diagnostics
        self._profiles = layers.merge_named(layer_list, 'profiles')   # name -> (val, src, shadows)
        # Per-name chain of same-named definitions across layers, ascending precedence:
        #   name -> [(layer_index, value, source_path), ...]
        # This preserves the shadowed (lower-layer) definitions that merge_named drops, so a
        # higher layer can amend a profile in place via a `+self` include (super semantics).
        self._chain = {}
        for i, layer in enumerate(layer_list):
            sec = layer.data.get('profiles')
            if isinstance(sec, dict):
                for name, val in sec.items():
                    self._chain.setdefault(name, []).append((i, val, layer.path))
        # `all` is a built-in synthetic profile = every defined component. The universe lives in
        # routes (not config), so it's supplied lazily by the app; None until then.
        self._universe_provider = None

    ALL_PROFILE = 'all'

    @classmethod
    def load(cls, paths, discovered=(), plugin_files=()):
        roots = [(paths.config_file, 'repo')]
        roots += [p if isinstance(p, (tuple, list)) else (p, 'plugin')   # (path, role)
                  for p in plugin_files]
        roots += [(d, 'discover') for d in discovered]
        roots.append((paths.user_config_file, 'user'))
        layer_list, warns = layers.expand_tolerant(roots, {'discover', 'plugin', 'primary'})
        cfg = cls(layer_list)
        cfg.load_warnings = warns     # a malformed primary/plugin/project file skipped, not fatal
        return cfg

    def ignored_section_warnings(self):
        '''Sections a layer set that its role forbids (silently dropped) — e.g. `configs:` from a
        non-primary plugin. Surfaced via diagnostics.'''
        return layers.ignored_section_warnings(self._layers)

    @property
    def active_profiles(self):
        '''Explicit `configs:` UNION every profile a discovered project file defines (auto-
        activation), minus `ignore-profiles:`. Explicit first, then discovered. `configs:` and
        `ignore-profiles:` are machine settings read from repo < a designated `primary` plugin <
        the top user config (see _MACHINE_ROLES) — so your personal plugin can set the default
        active set, and this machine's top config overrides it.'''
        explicit = _leaves(layers.merge_scalar(self._layers, 'configs', _MACHINE_ROLES))
        ignore = set(_leaves(layers.merge_scalar(self._layers, 'ignore-profiles', _MACHINE_ROLES)))
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
        v = layers.merge_scalar(self._layers, 'scope', _MACHINE_ROLES)
        return v if isinstance(v, str) else None

    def pins(self):
        '''The effective pin map, merged PER KEY across repo < primary < user (see
        merge_scalar_map): a machine's top config overrides a primary plugin's pins key-by-key
        rather than replacing the whole block, so portable pins survive a single local override.'''
        return layers.merge_scalar_map(self._layers, 'pins', _MACHINE_ROLES)

    def driver_preference(self):
        '''The global driver-preference order (a machine setting; whole-list replace across
        repo < primary < user), or None to use the built-in default. An OS block in routes may
        still override it per-context (see resolve._effective_preference).'''
        v = layers.merge_scalar(self._layers, 'driver-preference', _MACHINE_ROLES)
        return _leaves(v) or None

    def layer_pins(self, role):
        '''The raw scalar pins from the single layer of this role (repo/primary/user) — for
        editing that one layer's pins and for provenance, distinct from the merged pins().'''
        out = {}
        for layer in self._layers:
            if layer.role == role and isinstance(layer.data.get('pins'), dict):
                for k, v in layer.data['pins'].items():
                    if not isinstance(v, (dict, list)):
                        out[k] = v
        return out

    def pin_sources(self):
        '''{pin_name: role} — which machine-role set each EFFECTIVE pin (highest wins, matching
        pins()). For `configsys pin` provenance (local top config vs a portable primary plugin).'''
        src = {}
        for role in _MACHINE_ROLES:          # repo < primary < user; later overrides
            for k in self.layer_pins(role):
                src[k] = role
        return src

    def profile_components(self, profile):
        '''The ordered, deduped component list a profile expands to. A profile value is a list
        of terms, applied left-to-right: a bare `name` adds a component, `+name` splices in
        another profile's members (recursively), `~name` removes a component added so far. Order
        matters (a `~` after a `+` drops what the include brought in; a later add re-adds).

        `+self` (a profile including its own name) means "the same profile from the next layer
        down" — so a higher layer amends a profile in place (super semantics) instead of
        replacing it. A bare redefine with no `+self` still replaces wholesale. A genuine
        include cycle, an undefined include, or a `+self` with no lower layer to inherit raises
        ConfigError.'''
        if profile == self.ALL_PROFILE:                  # built-in: every defined component
            return self._all_components()
        chain = self._chain.get(profile)
        if not chain:
            raise ConfigError(
                f'profile "{profile}" is selected but not defined '
                f'(add it under `profiles:` in config.hu, ~/configsys.hu, or an included file)')
        idx, val, _src = chain[-1]                       # top (highest-precedence) definition
        return self._expand(profile, idx, val, ())

    def profile_own_components(self, profile):
        '''The components a profile declares AS ITS OWN — for menu attribution. Same as
        profile_components but `+other` (a cross-profile include) is NOT expanded: those
        components belong to the other profile. `+self` amendment IS followed (a profile's
        inherited-from-below members are still its own). So `sculpture-artist: [ +user, blender ]`
        owns just `blender`, while `user: [ +user, apod ]` owns the base `user` set plus apod.
        This keeps the menu from repeating a base profile's components under every includer.'''
        if profile == self.ALL_PROFILE:
            return self._all_components()
        chain = self._chain.get(profile)
        if not chain:
            raise ConfigError(f'profile "{profile}" is not defined')
        idx, val, _src = chain[-1]
        return self._expand(profile, idx, val, (), own_only=True)

    def _all_components(self):
        '''Every defined component name (the built-in `all` profile), or [] before the app has
        supplied the universe. Sorted for a stable menu order.'''
        return sorted(self._universe_provider() if self._universe_provider else [])

    def _expand(self, name, idx, val, stack, own_only=False):
        '''Expand one profile definition (name@idx) to its component list. `stack` holds the
        (name, layer_index) frames being expanded, so cycle detection distinguishes a self-
        inherit chain (same name, strictly-lower layer) from a real loop. `own_only` skips
        `+other` includes (see profile_own_components).'''
        key = (name, idx)
        if key in stack:
            raise ConfigError('profile include cycle: '
                              + ' -> '.join(f'{n}@{i}' for n, i in stack + (key,)))
        stack = stack + (key,)
        out = []
        for term in _leaves(val):
            op, ref = _split_term(term)
            if op == '+':                                  # include a profile
                if own_only and ref != name:               # +other belongs to the other profile
                    continue
                if ref == name:                            # +self -> inherit the layer below
                    lower = [e for e in self._chain.get(name, ()) if e[0] < idx]
                    if not lower:
                        raise ConfigError(
                            f'profile "{name}": `+{name}` has no lower-layer definition to '
                            f'inherit (nothing to amend)')
                    lidx, lval, _ = lower[-1]
                    members = self._expand(name, lidx, lval, stack, own_only)
                else:                                      # another profile's top definition
                    sub = self._chain.get(ref)
                    if not sub:
                        raise ConfigError(
                            f'profile "{name}": `+{ref}` includes an undefined profile "{ref}"')
                    sidx, sval, _ = sub[-1]
                    members = self._expand(ref, sidx, sval, stack)
                for c in members:
                    if c not in out:
                        out.append(c)
            elif op == '~':                                # remove a component
                if ref in out:
                    out.remove(ref)
            elif ref not in out:                           # add a component
                out.append(ref)
        return out

    def profile_layout(self, profile):
        '''The DIRECT structure of a profile, for the menu's include-as-link view: an ordered,
        deduped list of ('include', other) for each `+other` (KEPT as a reference, NOT expanded)
        and ('component', name) for each own component. `+self` amendment is followed (its
        inherited members merge in), and `~name` drops a component added so far. Contrast
        profile_components (fully transitive) and profile_own_components (drops all includes).'''
        if profile == self.ALL_PROFILE:
            return [('component', c) for c in self._all_components()]
        chain = self._chain.get(profile)
        if not chain:
            raise ConfigError(f'profile "{profile}" is not defined')
        idx, val, _src = chain[-1]
        return self._layout(profile, idx, val, ())

    def _layout(self, name, idx, val, stack):
        key = (name, idx)
        if key in stack:
            raise ConfigError('profile include cycle: '
                              + ' -> '.join(f'{n}@{i}' for n, i in stack + (key,)))
        stack = stack + (key,)
        out = []
        for term in _leaves(val):
            op, ref = _split_term(term)
            if op == '+':
                if ref == name:                            # +self -> merge the lower layer's layout
                    lower = [e for e in self._chain.get(name, ()) if e[0] < idx]
                    if not lower:
                        raise ConfigError(
                            f'profile "{name}": `+{name}` has no lower-layer definition to inherit')
                    lidx, lval, _ = lower[-1]
                    for item in self._layout(name, lidx, lval, stack):
                        if item not in out:
                            out.append(item)
                elif ('include', ref) not in out:          # +other -> a link reference
                    out.append(('include', ref))
            elif op == '~':                                # ~ drops an OWN component (can't reach
                if ('component', ref) in out:              # into an unexpanded include)
                    out.remove(('component', ref))
            elif ('component', ref) not in out:
                out.append(('component', ref))
        return out

    def profile_source(self, profile):
        '''The file a selected profile's definition came from (provenance), or None. With
        in-place amendment this is the top (amending) layer's file.'''
        chain = self._chain.get(profile)
        return chain[-1][2] if chain else None

    def requested(self):
        '''Ordered {component_name: [profiles that requested it]} across active profiles.'''
        out = {}
        for prof in self.active_profiles:
            for name in self.profile_components(prof):
                out.setdefault(name, [])
                if prof not in out[name]:
                    out[name].append(prof)
        return out
