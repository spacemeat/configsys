'''layers.py — the config/routes layer stack: expand `include:` graphs and merge sources.

Every config/routes file is a LAYER contributing sections: definitions (os / drivers / components /
profiles / component-names / version-floors / facets) and machine settings (picks / scope / pins / …).
A file may `include:` others (paths relative to the including file resolve against ITS directory;
`~` against the configsys home). Layers overlay lowest-precedence-first: the repo (routes.hu +
config.hu) is the base, an included file sits below the file that includes it, and the top user file
(~/.config/configsys/configsys.hu) wins. Merge is by section and, within components/profiles, by
name (later wins).

THE UNIFORM LAYER RULE: every layer — repo, plugins, primary, the top config, and any file they
include — may DEFINE things (components, profiles, os blocks, drivers; facet probe specs still need
plugin trust). Only the top config and the primary plugin may SET machine settings
(MACHINE_SETTING_SECTIONS); an include or an ordinary plugin that sets one is ignored with a warning.
This is the shared substrate the plugin model reuses — a plugin is just another source in the stack.
'''

import os

import humon

from .errors import ConfigError

_DEFINITION_SECTIONS = ('components', 'profiles')
_REPO_SECTIONS = ('os', 'drivers')

# Every top-level MACHINE SETTING — a section Config reads only from the machine-role layers (repo /
# primary / user, config._MACHINE_ROLES). An include or an ordinary (non-primary) plugin that sets one
# is IGNORED, so these feed _FORBIDDEN_BY_ROLE (-> a `check` / `!` warning instead of a silent drop).
# The scalar/list settings the CLI + TUI Config screen edit are registered in actions.CONFIG_SETTINGS
# and unioned in by machine_setting_sections() (so a newly registered setting is covered
# automatically); this list adds the matrix/side-store sections and the settings not editable there.
# Cosmetic `theme:` / `keys:` are NOT machine settings — every layer may contribute them.
MACHINE_SETTING_SECTIONS = frozenset({
    'picks', 'machine', 'scope', 'pins', 'dispositions', 'uninstall', 'dirs', 'locations',
    'driver-preference', 'disabled-drivers', 'auto-tighten', 'adopt-installed', 'detect-coexisting',
    'installer-shell-writes', 'installer-shell-writes-allow', 'refresh-before-execute',
    'install-overlay', 'reboot-advice', 'splash', 'effects', 'orphans-ignore',
})


def machine_setting_sections():
    '''MACHINE_SETTING_SECTIONS ∪ the top-level keys of actions.CONFIG_SETTINGS (`dirs.user` -> `dirs`).
    actions is imported lazily (it imports this module's dependents), and a failed import just falls
    back to the static list.'''
    keys = set(MACHINE_SETTING_SECTIONS)
    try:
        from .actions import CONFIG_SETTINGS
        keys.update(k.split('.', 1)[0] for k in CONFIG_SETTINGS)
    except Exception:                         # noqa: BLE001 — the static list is complete on its own
        pass
    return frozenset(keys)


def materialize(node):
    '''humon node -> plain python (dict / list / scalar), or None for a missing node.'''
    if node is None:
        return None
    kind = node.kind
    if kind == humon.NodeKind.DICT:
        out = {}
        for i in range(node.num_children):
            ch = node[i]
            if ch.key:
                out[ch.key] = materialize(ch)
        return out
    if kind == humon.NodeKind.LIST:
        return [materialize(node[i]) for i in range(node.num_children)]
    return node.value


def materialize_string(text):
    '''Materialize a humon string to python (for tests / in-memory layers).'''
    trove = humon.from_string(text)           # keep alive during the walk
    return materialize(trove.root) or {}


def read_setting(path, key):
    '''Peek one top-level setting from a single file (no include expansion), or None. For
    settings that must be known before the layer stack is built (e.g. `discover:`).'''
    if path is None or not os.path.exists(str(path)):
        return None
    try:
        trove = humon.from_file(str(path))    # keep alive during the walk
        return (materialize(trove.root) or {}).get(key)
    except Exception:                         # noqa: BLE001 — a broken file just means "unset"
        return None


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


class Layer:
    '''One materialized source file: its path (provenance), role, and section data.'''

    def __init__(self, path, role, data):
        self.path = path          # source file path
        self.role = role          # 'repo' | 'user' | 'plugin' | 'primary' | 'include'
        self.data = data          # {section: value}


# The configsys home that a `~` in an `include:` path expands against — Paths.home (CONFIGSYS_HOME /
# --home), not the real $HOME, so a sandboxed run reads the sandbox's includes like every other path.
# Paths sets it when constructed (set_include_home); None falls back to $CONFIGSYS_HOME, then $HOME.
_INCLUDE_HOME = None


def set_include_home(home):
    '''Record the configsys home `~` include paths expand against (called by Paths).'''
    global _INCLUDE_HOME
    _INCLUDE_HOME = None if home is None else str(home)


def _expand_home(inc, home=None):
    home = home or _INCLUDE_HOME or os.environ.get('CONFIGSYS_HOME')
    if home and (inc == '~' or inc.startswith('~/')):
        return os.path.join(str(home), inc[2:]) if inc != '~' else str(home)
    return os.path.expanduser(inc)


def _resolve(inc, base_dir):
    inc = str(inc)
    if inc.startswith('~'):
        return _expand_home(inc)
    if os.path.isabs(inc):
        return inc
    return os.path.join(base_dir, inc)


def _visit(path, role, stack, done, order):
    rp = os.path.realpath(path)
    if rp in stack:
        raise ConfigError('include cycle: ' + ' -> '.join(stack + [rp]))
    if rp in done:
        return                                # diamond: already merged, once is enough
    if not os.path.exists(path):
        raise ConfigError(f'include not found: {path}')
    try:
        trove = humon.from_file(path)         # keep alive: nodes point into it during walk
        data = materialize(trove.root) or {}
    except ConfigError:
        raise
    except Exception as e:                    # noqa: BLE001 — humon parse/read failure
        raise ConfigError(f'{path}: could not read ({e})')
    stack.append(rp)
    base = os.path.dirname(os.path.abspath(path))
    for inc in _as_list(data.get('include')):
        _visit(_resolve(inc, base), 'include', stack, done, order)
    stack.pop()
    done.add(rp)
    order.append(Layer(os.path.normpath(path), role, data))


def expand(roots):
    '''roots: [(path, role)] lowest-precedence-first. Returns [Layer] with include graphs
    expanded post-order (an included file precedes — is lower precedence than — its
    includer), deduped (diamonds appear once), and cycle-checked. Missing roots are skipped.
    Strict: any bad file raises. See expand_tolerant to skip failures for some roles.'''
    return expand_tolerant(roots, tolerant_roles=())[0]


def expand_tolerant(roots, tolerant_roles=()):
    '''Like expand(), but a bad file (parse error / cycle / bad include) whose role is in
    `tolerant_roles` is SKIPPED with a warning instead of aborting — so a malformed plugin
    layer never takes down the rest. Returns (layers, warnings). A bad repo/user file still
    raises (your own config errors should be loud, not skipped).'''
    stack, done, order, warnings = [], set(), [], []
    for path, role in roots:
        if path is None or not os.path.exists(path):
            continue
        try:
            _visit(path, role, stack, done, order)
        except ConfigError as e:
            if role in tolerant_roles:
                msg = str(e)
                if msg.startswith(f'{path}: '):          # don't repeat the path the error carries
                    msg = msg[len(path) + 2:]
                warnings.append(f'skipped {path}: {msg}')
                del stack[:]                  # a partial visit may have left the stack dirty
            else:
                raise
    return order, warnings


def merge_named(layers, section, roles=None):
    '''Overlay a per-name section (components / profiles) across layers -> {name:
    (value, source_path, shadows)}. `shadows` is True when a lower layer also defined the
    name. `roles` (optional) restricts which layers contribute.'''
    out = {}
    for layer in layers:
        if roles is not None and layer.role not in roles:
            continue
        sec = layer.data.get(section)
        if isinstance(sec, dict):
            for name, val in sec.items():
                out[name] = (val, layer.path, name in out)
    return out


def collect_named(layers, section, roles=None):
    '''Per-name chain of definitions across layers, ASCENDING precedence ->
    {name: [(layer_index, value, source_path), ...]}. Unlike merge_named (which keeps only the
    top definition per name), this preserves EVERY layer's definition so components can be merged
    additively (union of bindings) instead of replaced wholesale.'''
    out = {}
    for i, layer in enumerate(layers):
        if roles is not None and layer.role not in roles:
            continue
        sec = layer.data.get(section)
        if isinstance(sec, dict):
            for name, val in sec.items():
                out.setdefault(name, []).append((i, val, layer.path))
    return out


def merge_name_overrides(layers, roles=None):
    '''Overlay the `component-names` section across layers -> {driver: {component: pkg-or-{}}}.
    A higher layer patches a LOWER layer's package name for a component under a given driver,
    WITHOUT redefining the component (the all-or-nothing `components:` override is too blunt for
    "docker is `docker` under xbps"). `{}` (or null) means that driver has no package for the
    component -> it's dropped there (mirrors the `{}` = remove convention). Driver-keyed, so it
    expresses cross-driver name facts (Void's xbps names), NOT same-driver splits like Ubuntu-vs-
    Debian perf (both apt) — those stay `when:` splits. Later layers win per (driver, component).'''
    out = {}
    for layer in layers:
        if roles is not None and layer.role not in roles:
            continue
        sec = layer.data.get('component-names')
        if isinstance(sec, dict):
            for driver, comp_map in sec.items():
                if isinstance(comp_map, dict):
                    out.setdefault(driver, {}).update(comp_map)
    return out


def merge_version_floors(layers, roles=None):
    '''Overlay the `version-floors` section across layers -> {component: {cap: constraint}}. The
    analog of component-names for VERSION constraints: a higher layer patches a (component,
    capability) floor WITHOUT redefining the component, so a `main`-keyed data plugin can supply
    auto-derived toolchain floors that fold into existing recipes. Later layers win per
    (component, cap).'''
    out = {}
    for layer in layers:
        if roles is not None and layer.role not in roles:
            continue
        sec = layer.data.get('version-floors')
        if isinstance(sec, dict):
            for comp, cap_map in sec.items():
                if isinstance(cap_map, dict):
                    out.setdefault(comp, {}).update(cap_map)
    return out


def merge_scalar(layers, section, roles):
    '''Last (highest-precedence) value for a single-valued section, among `roles` layers.'''
    val = None
    for layer in layers:
        if layer.role in roles and layer.data.get(section) is not None:
            val = layer.data[section]
    return val


def merge_scalar_map(layers, section, roles):
    '''Overlay a flat scalar map section (pins) across `roles` layers, MERGING per key (a later
    layer wins per key) — unlike merge_scalar's whole-block replace. Non-scalar values (dict/list)
    are dropped: pins are leaf name->name entries. This is what lets a machine's top config
    override a primary plugin's pins key-by-key instead of wiping the whole block.'''
    out = {}
    for layer in layers:
        if layer.role in roles and isinstance(layer.data.get(section), dict):
            for k, val in layer.data[section].items():
                if not isinstance(val, (dict, list)):
                    out[k] = val
    return out


def merge_dict_section(layers, section, roles):
    '''Union a dict section (os / drivers — {name: spec}) across layers whose role is in
    `roles`; a later layer's entry wins per name. Lets a plugin add os blocks (derivative
    distros) while the rest stay from the repo.'''
    out = {}
    for layer in layers:
        if layer.role in roles and isinstance(layer.data.get(section), dict):
            out.update(layer.data[section])
    return out


ALL_ROLES = ('repo', 'plugin', 'primary', 'include', 'user')


def dict_section_sources(layers, section, roles=ALL_ROLES):
    """{name: source_path} for a dict section (os / drivers) — the file whose entry WINS per name
    under merge_dict_section (provenance for `where` / `check`)."""
    out = {}
    for layer in layers:
        if layer.role in roles and isinstance(layer.data.get(section), dict):
            for name in layer.data[section]:
                out[name] = layer.path
    return out


# what each non-repo/non-user role may NOT contribute (ignored -> a `check` warning)
def _forbidden_by_role():
    '''What each non-repo/non-user role may NOT contribute. The retired `configs:` is not listed — it
    carries its own retired warning (unknown_section_warnings) everywhere.'''
    settings = tuple(sorted(machine_setting_sections()))
    # THE UNIFORM LAYER RULE: every layer may DEFINE (components / profiles / os / drivers / …); only
    # the top config and the primary plugin may SET machine settings. So an include (of any file) and
    # an ordinary plugin lose exactly the machine settings.
    return {
        'include': settings,                      # definitions only — like its includer's definitions
        'plugin':  settings,                      # definitions, not machine settings
        # 'primary' (the top config's designated personal plugin) has NO entry: it may contribute
        # everything a user config can — machine settings included — sitting just below the top
        # config in precedence. The grant lives in the top config, so it stays a per-machine choice.
    }


def ignored_section_warnings(layers):
    '''Sections a layer set that its role doesn't permit (silently ignored) — surfaced by check.'''
    forbidden = _forbidden_by_role()
    warns = []
    for layer in layers:
        if not isinstance(layer.data, dict):
            continue
        for sec in forbidden.get(layer.role, ()):
            if sec in layer.data:
                why = ('an included file only defines things' if layer.role == 'include' else
                       'only the top config or the primary plugin sets machine settings')
                warns.append(f'{layer.path}: `{sec}:` is ignored here (not permitted from a '
                             f'{layer.role} layer — {why})')
    return warns


# Every top-level key configsys understands in a config/data .hu LAYER (plugin *manifests* are read
# separately, so their keys aren't checked here). An unknown key is a typo or a retired construct.
_KNOWN_TOP_KEYS = frozenset({
    # definitions + structure
    'os', 'drivers', 'components', 'profiles', 'component-names', 'include', 'plugins', 'facets',
    'version-floors',
    # cosmetic (every layer)
    'theme', 'keys',
}) | MACHINE_SETTING_SECTIONS                    # machine settings / local state
# Understood historically, now dropped -> always warn.
_RETIRED_TOP_KEYS = {
    'configs': 'retired — the matrix model installs from picks:, not active profiles',
    'machines': 'retired — picks: is now the machine registry (each picks: key is a machine/column)',
    'orphans-adopt-target': 'retired — orphan adopt now tracks (picks) the component, not a staging profile',
}


def unknown_section_warnings(layers):
    '''Non-fatal warnings for top-level keys configsys no longer understands — a typo, or a RETIRED
    construct (`configs:`, `machines:`, `orphans-adopt-target:`). Definitions (`profiles:` / `os:` /
    `components:` …) are valid in EVERY layer (the uniform layer rule).'''
    warns = []
    known = _KNOWN_TOP_KEYS | machine_setting_sections()
    for layer in layers:
        if not isinstance(layer.data, dict):
            continue
        for key in layer.data:
            if key in _RETIRED_TOP_KEYS:
                warns.append(f'{layer.path}: `{key}:` {_RETIRED_TOP_KEYS[key]}')
            elif key not in known:
                warns.append(f'{layer.path}: unrecognized top-level key `{key}:` (typo, or retired?)')
    return warns
