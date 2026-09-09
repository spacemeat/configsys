'''config.py — the per-machine selection + profile definitions, over the layer stack.

Reads from the shared layer engine (layers.py): the repo config.hu is the base, an included
file sits below the file that includes it, and the user ~/.config/configsys/configsys.hu wins. `configs` (which
profiles apply) and `scope` are machine SETTINGS — from the repo/user files, not includes.
`profiles:` are DEFINITIONS — merged per name across all layers (so an included project file
can contribute a profile). `pins:` likewise (repo/user). Values flatten to leaf names.
'''

import os

from . import layers
from .errors import ConfigError

# Layer roles that may set MACHINE settings (configs / scope / pins), lowest
# precedence first: the repo baseline, then a top-config-designated `primary` plugin (your
# portable personal defaults), then this machine's top user config (which overrides). Ordinary
# `plugin`/`include` layers are excluded — a shared plugin can't seize machine control
# unless the local top config explicitly grants it `primary`.
_MACHINE_ROLES = ('repo', 'primary', 'machine', 'user')


def _leaves(v):
    '''Flatten a profile / configs value to its leaf scalar names (lists + nested dicts).'''
    if isinstance(v, list):
        return [leaf for x in v for leaf in _leaves(x)]
    if isinstance(v, dict):
        return [leaf for x in v.values() for leaf in _leaves(x)]
    return [] if v is None else [v]


def _machine_entry(layer_list, name):
    '''The selected machine's `{configs?, profiles?}` entry from `machines:`, highest-precedence
    layer wins (among machine-setting roles). None if unknown.'''
    entry = None
    for layer in layer_list:
        if layer.role in _MACHINE_ROLES:
            m = layer.data.get('machines')
            if isinstance(m, dict) and isinstance(m.get(name), dict):
                entry = (m[name], layer.path)
    return entry


def _selected_machine(layer_list):
    v = layers.merge_scalar(layer_list, 'machine', _MACHINE_ROLES)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _inject_machine_layer(layer_list, override=None):
    '''If a `machine:` is selected (or `override` names one) and defined in `machines:`, splice that
    machine's `profiles:`/`configs:` in as its OWN layer — a `machine`-role rung that overlays the
    shared primary/plugin/repo profiles by name (so `^self`/`+self` and provenance flow) yet sits BELOW
    the local top config (which still overrides). A machine is a composing layer, not a container:
    shared profiles live at the primary's top level and a machine inherits/derives/amends them.
    `override` is the working-target selector (`--machine`). Unknown/absent selection -> no-op.'''
    sel = (override.strip() if isinstance(override, str) and override.strip()
           else _selected_machine(layer_list))
    if not sel:
        return layer_list
    got = _machine_entry(layer_list, sel)
    if got is None:
        return layer_list                    # selected machine not defined; surfaced by check
    entry, src = got
    data = {}
    if isinstance(entry.get('profiles'), dict):
        data['profiles'] = entry['profiles']
    if entry.get('configs') is not None:
        data['configs'] = entry['configs']
    mlayer = layers.Layer(src, 'machine', data)
    mlayer.machine = sel                     # the machine name this rung carries (writer + provenance)
    # insert just below the TOP user config (the last `user` layer) so the box's own file still wins
    at = max((i for i, l in enumerate(layer_list) if l.role == 'user'), default=len(layer_list))
    return layer_list[:at] + [mlayer] + layer_list[at:]


def _split_term(term):
    '''A profile-list entry -> (op, name). `+foo` includes profile foo (opt-out: its members join,
    live); `^foo` DERIVES from foo (opt-in: foo's members become an offered MENU, contributing NO
    members of their own — you pick from them with bare names); `~foo` removes/declines; a bare name
    adds a component. `^` collides with humon's heredoc syntax, so a derive term is authored quoted
    (`"^foo"`) — the quotes are gone by the time it reaches here, leaving the literal `^foo`.'''
    t = str(term)
    if t[:1] == '+':
        return '+', t[1:]
    if t[:1] == '^':
        return '^', t[1:]
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
    def load(cls, paths, plugin_files=(), machine=None):
        roots = [(paths.config_file, 'repo')]
        roots += [p if isinstance(p, (tuple, list)) else (p, 'plugin')   # (path, role)
                  for p in plugin_files]
        roots.append((paths.user_config_file, 'user'))
        layer_list, warns = layers.expand_tolerant(roots, {'plugin', 'primary'})
        # `machine` overrides the box's own `machine:` selection (the working-target selector).
        layer_list = _inject_machine_layer(layer_list, override=machine)
        cfg = cls(layer_list)
        cfg.load_warnings = warns     # a malformed primary/plugin layer skipped, not fatal
        return cfg

    def ignored_section_warnings(self):
        '''Sections a layer set that its role forbids (silently dropped) — e.g. `configs:` from a
        non-primary plugin. Surfaced via diagnostics.'''
        return layers.ignored_section_warnings(self._layers)

    @property
    def active_profiles(self):
        '''The active profile set: `configs:`, a machine setting read from repo < a designated
        `primary` plugin < the top user config (see _MACHINE_ROLES) — so your personal plugin can
        set the default active set, and this machine's top config overrides it. Deduped, in order.'''
        seen, out = set(), []
        for name in _leaves(layers.merge_scalar(self._layers, 'configs', _MACHINE_ROLES)):
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def default_scope(self):
        v = layers.merge_scalar(self._layers, 'scope', _MACHINE_ROLES)
        return v if isinstance(v, str) else None

    def machine_setting_source(self, key):
        '''(label, is_override) for machine setting `key`: the basename of the highest-precedence
        layer (among those allowed to set machine settings) that sets it, and whether that layer is
        one of YOURS rather than the repo baseline. None if only the built-in default applies. This
        is what lets the Config screen say "built-in default" vs "your override (set in <file>)".'''
        for layer in reversed(self._layers):
            if (layer.role in _MACHINE_ROLES and key in layer.data
                    and layer.data.get(key) not in (None, '')):
                return (os.path.basename(layer.path), layer.role != 'repo')
        return None

    def install_dirs(self):
        '''The install-layout dirs from the `dirs:` section (keys user/system/app/sdk/src), merged
        repo < primary < user — a machine setting. Paths applies the CONFIGSYS_*_DIR env overrides
        ON TOP (env wins). Only the install-layout dirs live here; bootstrap paths stay env-only.'''
        return layers.merge_dict_section(self._layers, 'dirs', _MACHINE_ROLES)

    def dir_source(self, key):
        '''The basename of the highest of YOUR layers (primary/user, not the repo baseline) that
        sets `dirs.<key>`, or None (built-in default / env). For the Config screen's attribution.'''
        for layer in reversed(self._layers):
            d = layer.data.get('dirs')
            if (layer.role in _MACHINE_ROLES and layer.role != 'repo'
                    and isinstance(d, dict) and d.get(key) not in (None, '')):
                return os.path.basename(layer.path)
        return None

    def disabled_drivers(self):
        '''Driver/via names DISABLED on this machine (a machine setting; repo < primary < user). A
        disabled driver's bindings don't match here, like a false `when:` — so a `suggests:` targeting
        a component that ONLY installs via it is silently skipped (e.g. `disabled-drivers: [ dotfiles ]`
        when you manage your own dotfiles), while a hard `requires:`/explicit want on such a component
        errors honestly. Generalizes to "no snaps here" etc.'''
        return _leaves(layers.merge_scalar(self._layers, 'disabled-drivers', _MACHINE_ROLES))

    def orphans_ignore(self):
        '''Name-or-glob patterns whose matching orphans stay quiet in `configsys orphans` (a machine
        setting; repo < primary < user). Acknowledged one-offs on THIS box don't nag; a glob matches
        an orphan's component name OR its installed key.'''
        return _leaves(layers.merge_scalar(self._layers, 'orphans-ignore', _MACHINE_ROLES))

    def orphans_adopt_target(self):
        '''The profile the TUI's orphan "stage" (`s`) action parks components into for later triage
        (a machine setting; repo < primary < user). Defaults to `orphans-lurking` — a staging profile
        you move names out of into the real base profiles.'''
        v = layers.merge_scalar(self._layers, 'orphans-adopt-target', _MACHINE_ROLES)
        return v if isinstance(v, str) and v else 'orphans-lurking'

    def pins(self):
        '''The effective pin map, merged PER KEY across repo < primary < user (see
        merge_scalar_map): a machine's top config overrides a primary plugin's pins key-by-key
        rather than replacing the whole block, so portable pins survive a single local override.'''
        return layers.merge_scalar_map(self._layers, 'pins', _MACHINE_ROLES)

    def locations(self):
        '''The effective per-component install-location map (component -> absolute path), merged
        PER KEY across repo < primary < user like pins(). A machine setting: "this component's
        install lives HERE, find/manage it there" — an absolute, scope-bypassing override that
        path-based drivers (source builds, appImage, tarball, font) honor over their computed dir.
        Distinct from the per-CATEGORY `dirs:` layout (which applies to every component of a class).'''
        return layers.merge_scalar_map(self._layers, 'locations', _MACHINE_ROLES)

    def theme(self):
        '''The merged TUI `theme:` overrides. Unlike the other machine settings, `theme` is purely
        cosmetic, so it is contributed by EVERY layer (a theme-only plugin can ship a look; a
        primary plugin can link one) and merged per key across the full stack repo < plugins <
        primary < top-config — later wins, so your own config always has the last
        word. Returns {colors: {name: #rrggbb}, pages: {page: {<role>: style, gradient: {...}}},
        splash}, deep-merged per map-color, per page, per role/gradient-key. Parsed by
        tui.theme.resolve_theme; the old `elements`/`palette` schema is ignored (a check warning).'''
        colors, pages, colors_basic = {}, {}, {}
        splash = None                              # startup-fill effect: last layer to speak wins
        for layer in self._layers:                 # low -> high precedence; no role restriction
            t = layer.data.get('theme')
            if not isinstance(t, dict):
                continue
            if isinstance(t.get('colors'), dict):
                colors.update(t['colors'])         # the shared name -> #rrggbb map
            if isinstance(t.get('colors-basic'), dict):
                colors_basic.update(t['colors-basic'])   # the 8/16-color slot override map
            if isinstance(t.get('pages'), dict):
                for page, spec in t['pages'].items():
                    if not isinstance(spec, dict):
                        continue
                    dst = pages.setdefault(page, {})
                    for k, v in spec.items():      # roles (dict styles) + the reserved `gradient`
                        if k == 'gradient':
                            if isinstance(v, dict) and isinstance(dst.get('gradient'), dict):
                                dst['gradient'].update(v)
                            elif isinstance(v, dict):
                                dst['gradient'] = dict(v)
                            else:
                                dst['gradient'] = v          # false/true
                        elif isinstance(v, dict):
                            r = dst.get(k)
                            if isinstance(r, dict):
                                r.update(v)
                            else:
                                dst[k] = dict(v)
                        else:
                            dst[k] = v
            if 'splash' in t:
                splash = t['splash']
        return {'colors': colors, 'colors-basic': colors_basic, 'pages': pages, 'splash': splash}

    def keys(self):
        '''The merged TUI `keys:` bindings — like `theme`, contributed by EVERY layer and merged
        per scope, per action across the full stack repo < plugins < primary < top-config (later
        wins per action). Returns {scope: {action: key-or-[keys]}}, consumed by tui.keyspec.Keymap.
        A primary plugin's configsys.hu (or your top config) can carry a `keys:` block right beside
        its profiles/components; a layer overrides just the actions it names.'''
        out = {}
        for layer in self._layers:                 # low -> high precedence
            k = layer.data.get('keys')
            if not isinstance(k, dict):
                continue
            for scope, actions in k.items():
                if not isinstance(actions, dict):
                    continue
                dst = out.setdefault(scope, {})
                for action, spec in actions.items():
                    dst[action] = spec                 # per-action override (whole value replaced)
        return out

    def driver_preference(self):
        '''The global driver-preference order (a machine setting; whole-list replace across
        repo < primary < user), or None to use the built-in default. An OS block in routes may
        still override it per-context (see resolve._effective_preference).'''
        v = layers.merge_scalar(self._layers, 'driver-preference', _MACHINE_ROLES)
        return _leaves(v) or None

    def auto_tighten(self):
        '''Opt-in (default off): when true, resolution AUTO-SELECTS a floor-satisfying install
        method for a provider whose default method can't meet a version floor — the gentoo-ish
        "just meet the floor" convenience, instead of only advising. A machine setting
        (repo < primary < user). Replacement of an ALREADY-INSTALLED provider stays explicit even
        under this (flooradvise.tighten_pins skips those — they remain advisories).'''
        v = layers.merge_scalar(self._layers, 'auto-tighten', _MACHINE_ROLES)
        return str(v).strip().lower() in ('true', 'yes', 'on', '1') if v is not None else False

    def block_installer_shell_writes(self):
        '''Default ON (block): wrap each component install so an installer can't scribble in your
        shell rc files (~/.bashrc, ~/.zshrc, …). configsys owns shell integration (the glue layer),
        so a write there is a surprise — snapshot/revert it and stage the removed block as a glue
        candidate you review. `installer-shell-writes: allow` turns the guard off globally; the
        per-component escape is `installer-shell-writes-allow: [ <comp> ]`. Machine setting
        (repo < primary < user).'''
        v = layers.merge_scalar(self._layers, 'installer-shell-writes', _MACHINE_ROLES)
        return str(v).strip().lower() not in ('allow', 'false', 'no', 'off', '0') if v is not None else True

    def shell_writes_allowlist(self):
        '''Components exempt from the shell-writes guard — allowed to edit rc files (their write is
        wanted). A machine setting list (repo < primary < user).'''
        return _leaves(layers.merge_scalar(self._layers, 'installer-shell-writes-allow', _MACHINE_ROLES))

    def guard_shell_writes(self, component):
        '''Whether to snapshot/revert this component's install: the guard is on AND the component
        isn't on the allow-list.'''
        return self.block_installer_shell_writes() and component not in self.shell_writes_allowlist()

    def detect_coexisting(self):
        '''Default ON: after inspect, detect installs of a component via its OTHER (non-managed)
        methods and surface them as "also present (unmanaged)" — so an existing machine's real state
        is visible. `detect-coexisting: false` skips the pass (the per-method sweep stays available
        via `configsys versions`). A machine setting (repo < primary < user).'''
        v = layers.merge_scalar(self._layers, 'detect-coexisting', _MACHINE_ROLES)
        return str(v).strip().lower() not in ('false', 'no', 'off', '0') if v is not None else True

    def adopt_installed(self):
        '''Default ON: the detection tier — bias resolution toward what's ALREADY installed, so an
        installed non-default method/provider is preferred over the blind default (you're never
        pushed to reinstall via a different route, or toward a fresh provider when a valid one is on
        disk). Precedence stays: explicit pin > detected-installed > default. `adopt-installed: false`
        turns it off (resolution ignores installed state, as before). Machine setting (repo<primary<user).'''
        v = layers.merge_scalar(self._layers, 'adopt-installed', _MACHINE_ROLES)
        return str(v).strip().lower() not in ('false', 'no', 'off', '0') if v is not None else True

    def refresh_before_execute(self):
        '''Refresh the OS package index ONCE before an execute batch — so upgrades see current
        candidates, and a broken vendor source is caught up front instead of failing per-package (a
        stale index silently upgrades to an old candidate; a per-package `apt-get update` lets one
        bad repo cascade into unrelated packages). 'auto' (default): refresh when the batch has a
        native install/upgrade. 'always'/'never' force it. Machine setting (repo<primary<user).'''
        v = layers.merge_scalar(self._layers, 'refresh-before-execute', _MACHINE_ROLES)
        v = str(v).strip().lower() if v is not None else 'auto'
        return v if v in ('auto', 'always', 'never') else 'auto'

    def install_overlay_default(self):
        '''Whether TUI::Profiles opens with the install-state overlay ON (installed underlined, orphans
        coloured, ignored orphans dimmed) — `O` toggles it either way. `install-overlay: false` starts
        it off. On by default. Machine setting (repo<primary<user).'''
        v = layers.merge_scalar(self._layers, 'install-overlay', _MACHINE_ROLES)
        return str(v).strip().lower() not in ('false', 'no', 'off', '0') if v is not None else True

    def splash(self):
        '''The chosen startup splash: a registered provider NAME, a disable token (false/off/no),
        or None when unset (use the built-in default). A machine setting (repo < primary < user).
        Selection only; whether a named provider is actually registered is resolved at TUI start.'''
        v = layers.merge_scalar(self._layers, 'splash', _MACHINE_ROLES)
        if v is False:
            return 'false'                       # a bare humon bool -> a disable token
        if v is True:
            return 'true'
        return v.strip() if isinstance(v, str) and v.strip() else None

    def effects(self):
        '''TUI motion level: 'full' | 'reduced' | 'none', or None when unset (the TUI then auto-picks
        reduced over SSH, else full). A machine setting (repo < primary < user).'''
        v = layers.merge_scalar(self._layers, 'effects', _MACHINE_ROLES)
        v = v.strip().lower() if isinstance(v, str) and v.strip() else None
        return v if v in ('full', 'reduced', 'none') else None

    def selected_machine(self):
        '''The active/target machine name: the spliced `machine`-role layer's name if one is present
        (honors a `--machine` override), else the `machine:` setting, else None.'''
        for layer in self._layers:
            if layer.role == 'machine':
                return getattr(layer, 'machine', None) or _selected_machine(self._layers)
        return _selected_machine(self._layers)

    def machine_layer_index(self):
        '''Index of the injected `machine`-role layer (the edit target for a machine-scoped profile
        write), or None. Distinguishes it from the primary layer they share a path.'''
        return next((i for i, l in enumerate(self._layers) if l.role == 'machine'), None)

    def machines(self):
        '''All defined machine names -> their `{configs?, profiles?}` entry, highest-precedence layer
        winning per name (among machine-setting roles). For listing / the working-target selector.'''
        out = {}
        for layer in self._layers:
            if layer.role in _MACHINE_ROLES:
                m = layer.data.get('machines')
                if isinstance(m, dict):
                    for name, entry in m.items():
                        if isinstance(entry, dict):
                            out[name] = entry
        return out

    def profile_edit_mode(self):
        '''How a membership edit resolves the FIRST amend of a profile defined only in a lower
        (non-editable) layer: 'track' (`+self` — repo/plugin changes apply, future additions install),
        'pin' (`^self` — you pick; upstream changes are OFFERED as NEW, never applied), or 'ask'
        (default — the TUI interposes the pin-or-track modal). A machine setting (repo<primary<user).'''
        v = layers.merge_scalar(self._layers, 'profile-edit-mode', _MACHINE_ROLES)
        v = v.strip().lower() if isinstance(v, str) and v.strip() else None
        return v if v in ('track', 'pin', 'ask') else 'ask'

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
                f'(add it under `profiles:` in config.hu, ~/.config/configsys/configsys.hu, or an included file)')
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

    UNINSTALL_PROFILE = '!uninstall'

    def uninstall_queue(self):
        '''Component names staged for uninstall — the members of the reserved `!uninstall` profile, a
        machine-local pending-removal queue (`x` in the TUI adds here; TUI::Components executes or
        clears them). `!`-prefixed profiles are reserved and never resolve for install (they're never
        active), so this stays inert until a remove op reads it. Empty/undefined -> empty set.'''
        try:
            return set(self.profile_own_components(self.UNINSTALL_PROFILE))
        except ConfigError:
            return set()

    def profiles_containing(self, name):
        '''Profiles that contain `name`, split into `(direct, indirect)`. DIRECT = the profile declares
        it as its own (a bare term or a `+self` amendment). INDIRECT = the profile only pulls it in
        through a `+other` cross-profile include (it belongs to the other profile there, but its members
        still land in this profile). Both sorted; a profile that fails to expand is skipped, never fatal.
        For the Profiles screen's "in profiles: …" detail.'''
        direct, indirect = [], []
        for p in self.profile_names():
            if p.startswith('!'):                        # reserved (e.g. !uninstall) isn't real membership
                continue
            try:
                own = self.profile_own_components(p)
            except ConfigError:
                continue
            if name in own:
                direct.append(p)
                continue
            try:
                if name in self.profile_components(p):
                    indirect.append(p)
            except ConfigError:
                pass
        return direct, indirect

    def profile_removed(self, profile):
        '''Components a `~term` drops anywhere in `profile`'s chain — for the profile editor's `~`
        marker (a component explicitly removed, so it isn't a member even if an include brought it).
        A `~subprofile` term contributes ALL of that subprofile's expanded members.'''
        out = set()
        for idx, _val, _src in self._chain.get(profile, ()):
            for term in self._own_terms(profile, idx):
                op, ref = _split_term(term)
                if op != '~':
                    continue
                sub = self._chain.get(ref)
                if sub and ref != profile:                 # ~subprofile -> all its members
                    try:
                        out.update(self._expand(ref, sub[-1][0], sub[-1][1], ()))
                    except ConfigError:
                        pass
                else:                                      # ~component
                    out.add(ref)
        return out

    def profile_removed_closure(self, profile):
        '''Like profile_removed, but across `profile`'s NET-ACTIVE include closure: a component a `~`
        drops in `profile` itself OR in any subprofile it net-includes (so a `~` buried inside an
        included meta-profile still counts — the transitive-exclusion case). Walks active_subprofiles
        (which already honors `~`), so a subprofile that's itself `~`'d out doesn't leak its own
        internal `~`s back in. Used to tell a transitively-excluded orphan from a merely-lurking one.'''
        out = set(self.profile_removed(profile))
        for sub in self.active_subprofiles(profile):
            try:
                out |= set(self.profile_removed(sub))
            except ConfigError:
                pass
        return out

    def profile_excludes(self, profile):
        '''Profiles that `profile` drops via a `~subprofile` term across the layer stack (the mirror
        of profile_includes). For the Profiles editor's excluded-include markers + `check`.'''
        out = set()
        for _i, terms, _s in self._chain.get(profile, ()):
            for t in _leaves(terms):
                if isinstance(t, str) and t[:1] == '~' and t[1:] in self._chain and t[1:] != profile:
                    out.add(t[1:])
        return out

    def profile_removal_terms(self, profile):
        '''Every `~ref` name a profile declares across its chain (raw, unclassified) — lets `check`
        flag a removal that matches neither a defined profile nor a known component (likely a typo,
        since such a `~` silently removes nothing).'''
        out = []
        for _i, terms, _s in self._chain.get(profile, ()):
            for t in _leaves(terms):
                if isinstance(t, str) and t[:1] == '~' and t[1:]:
                    out.append(t[1:])
        return out

    # -- derive (`^`) : the opt-in dual of `+include` — menu + NEW ------------------------------
    # A `^q` term offers q's members as a MENU without contributing members; your bare names are the
    # PICKS from that menu, `~name` a DECLINE, and a menu item that is neither is NEW (offered, never
    # installed). menu(^p) = members(p) — what p IS (recursive: a plain profile's full expansion, a
    # derived profile's picks). NEW = menu − members − declines. All derivable from the .hu text.

    def profile_derive_terms(self, profile):
        '''Every `^ref` name a profile declares across its chain (raw) — its derive-menu references.
        For `check` (undefined/subsumed/paired-with-include) and the TUI menu view.'''
        out = []
        for _i, terms, _s in self._chain.get(profile, ()):
            for t in _leaves(terms):
                if isinstance(t, str) and t[:1] == '^' and t[1:]:
                    out.append(t[1:])
        return out

    def is_derived(self, profile):
        '''True if `profile` has any `^derive` term (its catalog is a ballot over an offered menu).'''
        return bool(self.profile_derive_terms(profile))

    def profile_relation(self, profile):
        '''How the TOP (highest-precedence) definition of `profile` relates to any lower-layer
        definition of the SAME name — the provenance the pane badge / `where -p` show:
          'pinned'   — a `^self` (`^<profile>`) term: your layer PINS the lower def as a menu.
          'tracked'  — a `+self` (`+<profile>`) term: your layer AMENDS the live lower def.
          'shadowed' — a redefinition with neither self-ref while a lower def exists (it hides it).
          'base'     — a single definition (the lowest / your own fresh profile).'''
        chain = self._chain.get(profile)
        if not chain:
            return 'base'
        _idx, val, _src = chain[-1]
        terms = [t for t in _leaves(val) if isinstance(t, str)]
        if any(_split_term(t) == ('^', profile) for t in terms):
            return 'pinned'
        if any(_split_term(t) == ('+', profile) for t in terms):
            return 'tracked'
        return 'shadowed' if len(chain) > 1 else 'base'

    def profile_layer_defs(self, profile):
        '''Per-layer definitions of `profile`, LOW→HIGH precedence: a list of
        {role, source, terms} — the raw (unexpanded) term list each layer declares. Drives the
        `where -p` provenance report. Empty for an unknown profile.'''
        out = []
        for i, val, src in self._chain.get(profile, ()):
            role = self._layers[i].role if 0 <= i < len(self._layers) else '?'
            out.append({'role': role, 'source': str(src),
                        'terms': [str(t) for t in _leaves(val)]})
        return out

    def profile_amends_lower(self, profile, target_file, layer_idx=None):
        '''True if a membership edit to `profile` written to `target_file` would be the FIRST amend of
        a definition that lives only in a LOWER layer (typically non-editable) — i.e. the writer must
        synthesize a self-reference (`+self` track / `^self` pin). This is the moment the pin-or-track
        modal fires. False once the profile already has a definition in the target layer. `layer_idx`
        addresses the edit layer directly (a machine rung shares its path with the primary).'''
        tidx = layer_idx if layer_idx is not None else self.layer_index(target_file)
        if tidx is None:
            return False
        chain = self._chain.get(profile, ())
        in_target = any(i == tidx for i, _v, _s in chain)
        defined_below = any(i < tidx for i, _v, _s in chain)
        return (not in_target) and defined_below

    def _menu_structural(self, profile):
        '''STRUCTURAL menu: over the TOP def's `^q` terms, offer q's DIRECT CHILDREN — its `+sub`
        includes (and any `^`) as sub-profile UNITS, and its bare components — NOT the flattened member
        set. Returns (subprofiles, components). `^self` (`^ownname`) uses the next-lower def (mirrors
        `+self`). Recursion is emergent: deriving a sub-unit (`^sub`) offers ITS children in turn. A
        leaf `^p` (no sub-profiles) still menus its components, so leaf derives are unchanged. Raises
        ConfigError on an undefined `^ref` / a `^self` with no lower layer.'''
        chain = self._chain.get(profile)
        subs, comps = set(), set()
        if not chain:
            return subs, comps
        idx, val, _src = chain[-1]
        for term in _leaves(val):
            op, ref = _split_term(term)
            if op != '^':
                continue
            if ref == profile:                             # ^self -> the next-lower def's structure
                lower = [e for e in chain if e[0] < idx]
                if not lower:
                    raise ConfigError(f'profile "{profile}": `^{profile}` has no lower-layer '
                                      f'definition to derive from')
                layout = self._layout(profile, lower[-1][0], lower[-1][1], ())
            else:
                sub = self._chain.get(ref)
                if not sub:
                    raise ConfigError(f'profile "{profile}": `^{ref}` derives from an undefined '
                                      f'profile "{ref}"')
                layout = self._layout(ref, sub[-1][0], sub[-1][1], ())
            for kind, r in layout:
                if kind == 'include':                      # a `+sub` -> a sub-profile UNIT
                    subs.add(r)
                elif kind == 'component':
                    comps.add(r)
                # 'derive'/'exclude' in the SOURCE are its own curation, not offered here (so
                # deriving a derived profile still NARROWS to its structure — picks + includes)
        return subs, comps

    def _compute_menu(self, profile):
        '''The menu as a flat NAME set (sub-profile units ∪ direct components) — for check_derives and
        the flat-name `profile_menu`. Raises like _menu_structural.'''
        subs, comps = self._menu_structural(profile)
        return subs | comps

    def check_derives(self, profile):
        '''Raise ConfigError if any `^derive` term is undefined / has no lower layer — for `check`.'''
        self._compute_menu(profile)

    def profile_menu(self, profile):
        '''The MENU a derived profile offers, as a flat set of NAMES (sub-profile units + components),
        or the empty set for a plain (`^`-free) / broken profile. Use `profile_menu_items` to tell a
        sub-profile unit from a component.'''
        try:
            return self._compute_menu(profile)
        except ConfigError:
            return set()

    def profile_menu_items(self, profile):
        '''The structural menu split by kind: {'subprofiles': set, 'components': set}. Empty on a plain
        or broken profile. Drives the hierarchical ballot (a sub-unit drills in; a component is a pick).'''
        try:
            subs, comps = self._menu_structural(profile)
        except ConfigError:
            subs, comps = set(), set()
        return {'subprofiles': subs, 'components': comps}

    def profile_new(self, profile):
        '''Unballoted menu items — offered by a `^derive` but not yet acted on. For a sub-profile UNIT:
        NEW unless MENTIONED (`+sub`/`^sub`/`~sub`). For a direct COMPONENT: NEW unless a member
        (picked) or `~`-declined. So a brand-new sub-profile upstream shows as NEW (a unit), and a new
        direct component shows as NEW — each attributed to the level it appears at. Empty for a plain
        profile. `~subprofile` declines stay "open" (a growing declined sub is not resurfaced).'''
        subs, comps = (lambda d: (d['subprofiles'], d['components']))(self.profile_menu_items(profile))
        if not subs and not comps:
            return set()
        try:
            members = set(self.profile_components(profile))
        except ConfigError:
            members = set()
        removed = self.profile_removed(profile)
        mentioned = (set(self.profile_includes(profile)) | set(self.profile_derive_terms(profile))
                     | set(self.profile_excludes(profile)))
        new_subs = subs - mentioned                        # a sub-unit not yet +/^/~ engaged
        new_comps = comps - members - removed              # a direct component not picked/declined
        return new_subs | new_comps

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
            elif op == '^':                                # derive: MENU-only, contributes NO members
                continue                                   # (see profile_menu / profile_new)
            elif op == '~':                                # remove: a subprofile's members, or one component
                if ref in self._chain and ref != name:     # a defined profile -> subtract its whole member set
                    sidx, sval, _ = self._chain[ref][-1]    # (order-sensitive, like ~component: a later add re-adds)
                    drop = set(self._expand(ref, sidx, sval, stack))
                    out = [c for c in out if c not in drop]
                elif ref in out:                           # a component
                    out.remove(ref)
            elif ref not in out:                           # add a component
                out.append(ref)
        return out

    def active_subprofiles(self, profile):
        '''The set of subprofile NAMES a profile net-includes (a `+sub` not overridden by a later
        `~sub`), transitively — the profile-level mirror of profile_components. Drives the Profiles
        tree's active/excluded state and the subprofile membership toggle. Undefined/broken -> empty.'''
        chain = self._chain.get(profile)
        if not chain:
            return set()
        idx, val, _src = chain[-1]
        try:
            return self._active_subs(profile, idx, val, ())
        except ConfigError:
            return set()

    def _active_subs(self, name, idx, val, stack):
        '''Fold a profile definition to the set of subprofile names it net-includes (order-sensitive,
        like _expand but tracking profile membership, not components). `+ref` adds ref + ref's own
        active subs; `~ref` (a defined profile) drops ref AND its subtree (its members are pruned
        wholesale, matching _expand's set subtraction); `+self` amends the layer below.'''
        key = (name, idx)
        if key in stack:
            return set()                                 # cycle -> contributes nothing here
        stack = stack + (key,)
        on = set()
        for term in _leaves(val):
            op, ref = _split_term(term)
            if op == '+':
                if ref == name:                          # +self -> inherit the layer below
                    lower = [e for e in self._chain.get(name, ()) if e[0] < idx]
                    if lower:
                        on |= self._active_subs(name, lower[-1][0], lower[-1][1], stack)
                elif ref in self._chain:                 # include a profile: it + its active subs
                    on.add(ref)
                    sidx, sval, _ = self._chain[ref][-1]
                    on |= self._active_subs(ref, sidx, sval, stack)
            elif op == '~' and ref in self._chain and ref != name:
                on.discard(ref)                          # exclude the subprofile + its whole subtree
                sidx, sval, _ = self._chain[ref][-1]
                on -= self._active_subs(ref, sidx, sval, stack)
        return on

    def reachable_subprofiles(self, profile):
        '''Every subprofile reachable from `profile` via `+`-includes (transitively, IGNORING `~`
        exclusions) — the universe a `~sub` could actually prune. For check's orphan-`~` warning
        (a `~sub` for a profile that isn't even included removes nothing).'''
        seen, stack = set(), [profile]
        while stack:
            p = stack.pop()
            try:
                for inc in self.profile_includes(p):
                    if inc not in seen:
                        seen.add(inc)
                        stack.append(inc)
            except ConfigError:
                pass
        return seen

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

    def profile_children(self, profile):
        '''A profile's DIRECT children as `{subprofiles, components}` — its `+sub` includes as
        sub-profiles + its own bare components (its structural layout). For DRILLING INTO a
        sub-profile in the hierarchical ballot (contrast profile_menu_items, which is over a derived
        profile's `^q` terms). Empty for an unknown/broken profile.'''
        try:
            layout = self.profile_layout(profile)
        except ConfigError:
            return {'subprofiles': set(), 'components': set()}
        return {'subprofiles': {r for k, r in layout if k == 'include'},
                'components': {r for k, r in layout if k == 'component'}}

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
            elif op == '^':                                # ^derive -> a MENU reference (like include,
                if ('derive', ref) not in out:             # but opt-in; contributes no members here)
                    out.append(('derive', ref))
            elif op == '~':                                # ~ excludes a subprofile (a removed-include
                if ref in self._chain and ref != name:     # marker), or drops an OWN component
                    if ('exclude', ref) not in out:
                        out.append(('exclude', ref))
                elif ('component', ref) in out:            # (a ~component can't reach into an unexpanded include)
                    out.remove(('component', ref))
            elif ('component', ref) not in out:
                out.append(('component', ref))
        return out

    def profile_names(self):
        '''Every DEFINED profile name across the layer stack, sorted (excludes the synthetic
        `all`). For listing/editing profiles in the CLI and the TUI Profiles screen.'''
        return sorted(self._chain)

    def profile_source(self, profile):
        '''The file a selected profile's definition came from (provenance), or None. With
        in-place amendment this is the top (amending) layer's file.'''
        chain = self._chain.get(profile)
        return chain[-1][2] if chain else None

    # -- profile EDITING (term-algebra writer support; see plan_membership_edit) --------------

    def layer_index(self, path):
        '''Index of the loaded layer whose file is `path`, or None. Lets a writer address one
        layer of the merged stack (the edit target) by its file.'''
        for i, layer in enumerate(self._layers):
            if str(layer.path) == str(path):
                return i
        return None

    def _own_terms(self, profile, idx):
        '''The LITERAL term list `profile` declares in the layer at `idx` (raw, that file's own
        definition — `+self`/`+other`/`~`/bare, unexpanded), or [] if that layer doesn't define it.'''
        for i, val, _src in self._chain.get(profile, ()):
            if i == idx:
                return list(_leaves(val))
        return []

    def _members_safe(self, profile):
        '''Effective members, treating an UNDEFINED profile as empty (so `add` may create it) but
        letting a DEFINED-but-broken profile (bad include / cycle / `+self` with nothing below)
        RAISE — so an edit surfaces the error instead of silently no-oping on the remove path.'''
        if profile != self.ALL_PROFILE and profile not in self._chain:
            return []
        return self.profile_components(profile)

    def plan_membership_edit(self, profile, comp, action, target_file, synth='track', layer_idx=None):
        '''Compute the new raw term list for `profile` in `target_file` so `comp` reaches `action`'s
        state, honoring the term algebra. `action`: `'add'` (a member) / `'remove'` (a non-member) of
        the EFFECTIVE set; plus the derived-profile ballot pair `'decline'` (write an explicit `~comp`
        — an intentional NO on a menu offering) and `'clear'` (drop an OWNED pick or `~`-decline, so a
        menu item returns to unballoted/NEW). Pure: returns the new term list to write, or None for a
        no-op (already in the wanted state, and the target layer need not define the profile).
        `target_file` is the edit layer (usually the highest-precedence one — your primary or top
        config); reuses `_expand` to decide whether a component still arrives via `+self`/`+other`
        after dropping a bare term.

        `synth` picks how the FIRST amend of a profile defined only in a LOWER layer is materialized
        (add/remove only): `'track'` (default, the historical behavior) amends the live lower def via
        `+self`; `'pin'` writes a `^self` derivation seeded with the current effective members as picks
        (so behavior is identical today and upstream growth is later OFFERED as NEW, never applied).
        `layer_idx` addresses the edit layer directly (for a machine-role rung that shares a path with
        the primary — `layer_index` can't disambiguate); default resolves `target_file` by path.'''
        tidx = layer_idx if layer_idx is not None else self.layer_index(target_file)
        if tidx is None:
            raise ConfigError(f'{target_file} is not a loaded config layer')
        chain = self._chain.get(profile, ())
        own = self._own_terms(profile, tidx)
        in_target = any(i == tidx for i, _v, _s in chain)
        defined_below = any(i < tidx for i, _v, _s in chain)
        neg = '~' + comp
        selfinc = '+' + profile          # `+self` is spelled as the profile's OWN name (super/amend)
        pinself = '^' + profile          # `^self` pins the lower def as a menu (seed picks below)
        synthesizing = (not in_target) and defined_below and synth == 'pin'

        def expand(terms):
            return self._expand(profile, tidx, list(terms), ())

        if action == 'add':
            if comp in self._members_safe(profile) and neg not in own:
                return None                                  # already a member; nothing to write
            if synthesizing:                                 # PIN: snapshot members as picks, then add
                return [pinself] + list(self._members_safe(profile)) + [comp]
            base = [t for t in own if t != neg]              # drop a ~comp that was suppressing it
            if not in_target and defined_below:
                base = [selfinc] + base                       # inherit the lower def, then amend (track)
            if comp not in expand(base):
                base = base + [comp]
            return base

        if action == 'decline':
            # ballot DECLINE (a derived profile): write an explicit `~comp` (and drop any bare pick)
            # so a menu offering reads as an intentional NO, not merely un-picked (NEW).
            if not in_target:
                if comp in self.profile_removed(profile):
                    return None                              # already declined in a lower layer
                return [selfinc, neg] if defined_below else [neg]
            base = [t for t in own if t not in (comp, neg)] + [neg]
            return None if base == own else base

        if action == 'clear':
            # ballot CLEAR (a derived profile): drop a bare pick AND a `~` decline OWNED here, so the
            # menu item returns to unballoted (NEW / offered). Only clears terms in the target layer.
            if not in_target:
                return None
            base = [t for t in own if t not in (comp, neg)]
            return None if base == own else base

        # remove
        if comp not in self._members_safe(profile):
            return None                                      # already absent
        if synthesizing:                                     # PIN: snapshot members minus comp, decline it
            return [pinself] + [c for c in self._members_safe(profile) if c != comp] + [neg]
        if not in_target:
            return [selfinc, neg] if defined_below else [neg]  # member only from below -> negate here (track)
        without = [t for t in own if t != comp]              # drop a bare own term if present
        if comp in expand(without):                          # still arrives via +self/+other include
            return without if neg in without else without + [neg]
        return without

    def plan_include_edit(self, profile, other, add, target_file):
        '''New raw term list for `profile` in `target_file` so it INCLUDES (`add=True`) or drops the
        include of `other` (a `+other` term = pull in another profile's members). Pure; None for a
        no-op. Removing only drops an include OWNED in the target layer.'''
        tidx = self.layer_index(target_file)
        if tidx is None:
            raise ConfigError(f'{target_file} is not a loaded config layer')
        chain = self._chain.get(profile, ())
        own = self._own_terms(profile, tidx)
        in_target = any(i == tidx for i, _v, _s in chain)
        defined_below = any(i < tidx for i, _v, _s in chain)
        term = '+' + other
        selfinc = '+' + profile
        if add:
            if term in own:
                return None
            base = list(own)
            if not in_target and defined_below:
                base = [selfinc] + base                       # amend the lower def instead of shadowing
            return base + [term]
        if term not in own:
            return None                                       # not an include we own here
        return [t for t in own if t != term]

    def plan_subprofile_edit(self, profile, sub, member, target_file):
        '''New raw term list for `profile` in `target_file` so subprofile `sub` becomes a MEMBER
        (`member=True` -> a `+sub` include) or a NON-member (`member=False` -> a `~sub` exclusion) of
        `profile`'s effective subprofile set, honoring the term algebra. Pure; None for a no-op. This
        is the membership-toggle behind the Profiles tree: include a struck subprofile, or exclude an
        active one, writing `+sub`/`~sub` (or dropping the opposing own term) as needed. Mirrors
        plan_membership_edit, but the member test is profile-level (active_subprofiles).'''
        if sub == profile:
            raise ConfigError("a profile can't include or exclude itself")
        tidx = self.layer_index(target_file)
        if tidx is None:
            raise ConfigError(f'{target_file} is not a loaded config layer')
        chain = self._chain.get(profile, ())
        own = self._own_terms(profile, tidx)
        in_target = any(i == tidx for i, _v, _s in chain)
        defined_below = any(i < tidx for i, _v, _s in chain)
        plus, neg = '+' + sub, '~' + sub
        selfinc = '+' + profile

        def active(terms):
            return sub in self._active_subs(profile, tidx, list(terms), ())

        is_member = sub in self.active_subprofiles(profile)

        if member:
            if is_member and neg not in own:
                return None                              # already a member; nothing to write
            base = [t for t in own if t != neg]          # drop a ~sub that was suppressing it
            if not in_target and defined_below:
                base = [selfinc] + base                  # amend the lower def instead of shadowing
            if not active(base):
                base = base + [plus]                     # still not a member -> add the include
            return base

        # exclude
        if not is_member:
            return None                                  # already not a member
        if not in_target:
            return [selfinc, neg] if defined_below else [neg]   # member only from below -> negate here
        without = [t for t in own if t != plus]          # drop an own +sub first
        if not active(without):                          # dropping our own +sub alone excludes it
            return without
        return without if neg in without else without + [neg]

    def subprofile_state(self, profile, sub):
        '''How `profile` currently engages sub-profile `sub` in its OWN terms (across its chain):
        'derive' (`^sub`), 'whole' (`+sub`), 'exclude' (`~sub`), or 'new' (unmentioned/offered). The
        hierarchical ballot's per-sub state.'''
        if sub in set(self.profile_derive_terms(profile)):
            return 'derive'
        if sub in self.profile_includes(profile):
            return 'whole'
        if sub in self.profile_excludes(profile):
            return 'exclude'
        return 'new'

    def plan_subprofile_state_edit(self, profile, sub, state, target_file, layer_idx=None):
        '''New raw term list so sub-profile `sub` reaches `state` in `profile`: 'derive' (`^sub`),
        'whole' (`+sub`), 'exclude' (`~sub`), or 'new' (no term — unengaged/offered). Drops any
        existing `^sub`/`+sub`/`~sub` first. Pure; None for a no-op. `layer_idx` addresses a machine
        rung directly (shared path). The hierarchical ballot's sub-profile writer.'''
        if sub == profile:
            raise ConfigError("a profile can't engage itself")
        tidx = layer_idx if layer_idx is not None else self.layer_index(target_file)
        if tidx is None:
            raise ConfigError(f'{target_file} is not a loaded config layer')
        chain = self._chain.get(profile, ())
        own = self._own_terms(profile, tidx)
        in_target = any(i == tidx for i, _v, _s in chain)
        defined_below = any(i < tidx for i, _v, _s in chain)
        term = {'derive': '^' + sub, 'whole': '+' + sub, 'exclude': '~' + sub, 'new': None}[state]
        drop = {'^' + sub, '+' + sub, '~' + sub}
        base = [t for t in own if str(t) not in drop]
        if not in_target and defined_below and (term is not None or base != list(own)):
            base = ['+' + profile] + base                # amend the lower def (track) rather than shadow
        if term is not None:
            base = base + [term]
        return None if (in_target and base == list(own)) else base

    def profile_includes(self, profile):
        '''Profiles that `profile` pulls in via `+other` terms across the layer stack (excludes the
        `+self` amend term).'''
        out = set()
        for _i, terms, _s in self._chain.get(profile, ()):
            for t in terms:
                if isinstance(t, str) and t.startswith('+') and t[1:] and t[1:] != profile:
                    out.add(t[1:])
        return out

    def requested(self):
        '''Ordered {component_name: [profiles that requested it]} across active profiles.'''
        out = {}
        for prof in self.active_profiles:
            for name in self.profile_components(prof):
                out.setdefault(name, [])
                if prof not in out[name]:
                    out[name].append(prof)
        return out
