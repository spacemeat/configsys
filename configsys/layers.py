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

from . import settings
from .errors import ConfigError

_DEFINITION_SECTIONS = ('components', 'profiles')
_REPO_SECTIONS = ('os', 'drivers')

# Every top-level MACHINE SETTING — a section Config reads only from the machine-role layers (repo /
# primary / user, config._MACHINE_ROLES). An include or an ordinary (non-primary) plugin that sets one
# is IGNORED, so these feed _FORBIDDEN_BY_ROLE (-> a `check` / `!` warning instead of a silent drop).
# Every one is a row of configsys/settings.py (the registry), so a newly registered setting is
# covered automatically. Cosmetic `theme:` / `keys:` are NOT machine settings — every layer may
# contribute them.
MACHINE_SETTING_SECTIONS = settings.SECTIONS          # (D1: derived from settings.SETTINGS)


# Scalar settings whose value is one of a fixed set — `config set` refuses anything else, `check` warns
# on one in a layer, and the TUI Config screen offers them as a list. (The accessors in config.py fall
# back to the default on an unknown value, so a bad one is never fatal — but it is never silent either.)
SETTING_CHOICES = settings.CHOICES                    # (D1: derived)

# On/off settings, and the ONE spelling of a bool every reader and `config set` accepts (B11). An
# unknown token (`ture`) is the setting's default — never the opposite of what you meant — and a
# `check` warning; `config set` refuses it. (actions.CONFIG_SETTINGS kind 'bool' == this set.)
BOOL_SETTINGS = settings.BOOLS                         # (D1: derived)
_TRUE = frozenset({'true', 'yes', 'on', '1'})
_FALSE = frozenset({'false', 'no', 'off', '0'})


def parse_bool(v, default):
    '''A setting value as a bool: true/yes/on/1, false/no/off/0 (any case), else `default`.'''
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower() if v is not None else ''
    return True if s in _TRUE else False if s in _FALSE else default


def is_bool_token(v):
    return isinstance(v, bool) or str(v).strip().lower() in _TRUE | _FALSE

# Settings read ONLY from this machine's top config: a value in your primary plugin (or anywhere
# else) is ignored, with a `check` warning. `primary-verify` guards what the primary may bring in, and
# `primary-trust` decides whether its commands run without a re-trust, so a commit pushed to the
# primary must not be able to change either.
TOP_CONFIG_ONLY = settings.TOP_ONLY                    # (D1: derived)


def setting_value_warnings(layers):
    '''Warnings for a fixed-choice setting (SETTING_CHOICES) set to a value it doesn't take.'''
    warns = []
    for layer in layers:
        if not isinstance(layer.data, dict):
            continue
        for key, choices in SETTING_CHOICES.items():
            v = layer.data.get(key)
            if v is not None and str(v).strip().lower() not in choices:
                warns.append(f'{layer.path}: `{key}: {v}` is not one of {", ".join(choices)} — '
                             f'configsys uses the default instead')
        for key in sorted(BOOL_SETTINGS & set(layer.data)):
            v = layer.data[key]
            if not is_bool_token(v):
                warns.append(f'{layer.path}: `{key}: {v}` is not true or false — configsys uses '
                             f'the default instead')
        for key in TOP_CONFIG_ONLY & set(layer.data):
            if layer.role != 'user':
                warns.append(f'{layer.path}: `{key}:` is read only from your top config '
                             f'(~/.config/configsys/configsys.hu), so it is ignored here')
        dirs = layer.data.get('dirs')
        for sub in ('user', 'system'):
            v = dirs.get(sub) if isinstance(dirs, dict) else None
            if v is not None and not _location_ok(v):
                warns.append(f'{layer.path}: `dirs: {{ {sub}: {v} }}` must be an absolute path or start '
                             f'with ~/ — a relative base follows whatever directory configsys runs from')
        locs = layer.data.get('locations')
        for comp, path in (locs.items() if isinstance(locs, dict) else ()):
            if not _location_ok(path):
                warns.append(f'{layer.path}: `locations: {comp}={path}` must be an absolute path or '
                             f'start with ~/ — ignored')
    return warns


def _location_ok(path):
    s = str(path).strip()
    return s.startswith('/') or s == '~' or s.startswith('~/')


def machine_setting_sections():
    '''Every machine-setting section (settings.SECTIONS — the registry, no lazy import of actions).'''
    return MACHINE_SETTING_SECTIONS


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


def duplicate_keys(node, prefix=''):
    '''Dotted paths of every key a map holds TWICE (humon keeps both; a read takes the last, a
    surgical edit the first — so a later `config set` "succeeds" and changes nothing: B17 /
    primary-04). [] for a clean tree.'''
    out = []
    if node is None:
        return out
    if node.kind == humon.NodeKind.DICT:
        seen = set()
        for i in range(node.num_children):
            ch = node[i]
            k = ch.key
            path = f'{prefix}.{k}' if prefix else str(k)
            if k in seen and path not in out:
                out.append(path)
            seen.add(k)
            out += [d for d in duplicate_keys(ch, path) if d not in out]
    elif node.kind == humon.NodeKind.LIST:
        for i in range(node.num_children):
            out += [d for d in duplicate_keys(node[i], f'{prefix}[{i}]') if d not in out]
    return out


def duplicate_keys_in_text(text):
    '''duplicate_keys for humon text (None when it doesn't parse).'''
    try:
        trove = humon.from_string(text)
    except Exception:                         # noqa: BLE001
        return None
    return duplicate_keys(trove.root)


def duplicate_key_warnings(layers, roles=('user', 'primary', 'plugin', 'include')):
    '''A warning per non-repo layer file holding a key twice (the repo's own files are held to that by
    a test, and re-parsing routes.hu here every load would cost). For `check` and the `!` page.'''
    out, seen = [], set()
    for lyr in layers:
        path = getattr(lyr, 'path', None)
        if getattr(lyr, 'role', None) not in roles or not path or path in seen:
            continue
        seen.add(path)
        try:
            from pathlib import Path
            dups = duplicate_keys_in_text(Path(path).read_text(encoding='utf-8-sig'))
        except OSError:
            continue
        if dups:
            out.append(f'{path}: `{", ".join(dups)}` set twice — configsys reads the LAST one but an '
                       f'edit changes the first; delete one')
    return out


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
        _trove, data = read_tree(path)        # keep the trove alive during the walk
        return data.get(key)
    except Exception:                         # noqa: BLE001 — a broken file just means "unset"
        return None


def read_tree(path):
    '''(trove, data) for one .hu file — THE layer parse chokepoint (B11). Reads UTF-8 text (a BOM
    tolerated) and parses from the string: humon's from_file sniffs the encoding and rejects any file
    under ~10 bytes (`{}`, which configsys itself writes) as BADENCODING. A blank file is `{}`.
    Keep the trove alive while walking nodes from it. Raises ConfigError with one wording.'''
    from pathlib import Path
    from . import troveio
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except UnicodeDecodeError as e:
        raise ConfigError(f'{path}: could not read (not valid UTF-8: {e})')
    except OSError as e:
        raise ConfigError(f'{path}: could not read ({e.strerror or e})')
    if not text.strip():
        return None, {}
    try:
        trove = troveio.load_string(text)
        data = materialize(trove.root) or {}
    except Exception as e:                    # noqa: BLE001 — humon parse failure
        raise ConfigError(f'{path}: could not read ({e})')
    if not isinstance(data, dict):
        raise ConfigError(f'{path}: could not read (a config file is a {{ … }} map, not a '
                          f'{type(data).__name__})')
    return trove, data


def as_list(v):
    '''`v` as a list: None -> [], a scalar -> [v] (the one spelling routes / resolve / routecheck share).'''
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


def _plugin_tree(path):
    '''The plugin checkout a plugin/primary data file lives in: its nearest ancestor holding a
    `plugin.hu` manifest (else the file's own dir).'''
    d = os.path.dirname(os.path.realpath(path))
    probe = d
    while True:
        if os.path.exists(os.path.join(probe, 'plugin.hu')):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return d
        probe = parent


def _inside(path, tree):
    rp = os.path.realpath(path)
    return rp == tree or rp.startswith(tree.rstrip(os.sep) + os.sep)


def _visit(path, role, stack, done, order, guard=None):
    '''Expand one file and its includes post-order. `guard` = (root realpaths, plugin tree or None,
    warnings): an `include:` of a ROOT layer (your top config, the primary's file, the repo's) is
    ignored with a warning — a lower layer including it would visit it first, as an `include`, and
    demote it below itself (2026-09 A5 / review-2026-11-2 A5) — and a plugin's includes must stay
    inside its own checkout.'''
    rp = os.path.realpath(path)
    if rp in stack:
        raise ConfigError('include cycle: ' + ' -> '.join(stack + [rp]))
    if rp in done:
        return                                # diamond: already merged, once is enough
    if not os.path.exists(path):
        raise ConfigError(f'include not found: {path}')
    _trove, data = read_tree(path)            # keep alive: nodes point into it during walk
    stack.append(rp)
    base = os.path.dirname(os.path.abspath(path))
    for inc in as_list(data.get('include')):
        target = _resolve(inc, base)
        if guard is not None:
            roots, tree, warnings = guard
            if os.path.realpath(target) in roots:
                warnings.append(f'{path}: `include: {inc}` ignored — it names a root config layer '
                                '(your top config, the primary, or the repo), which keeps its own place')
                continue
            if tree is not None and not _inside(target, tree):
                warnings.append(f'{path}: `include: {inc}` ignored — a plugin may only include files '
                                'inside its own checkout')
                continue
        _visit(target, 'include', stack, done, order, guard)
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
    root_paths = {os.path.realpath(p) for p, _r in roots if p is not None}
    for path, role in roots:
        if path is None or not os.path.exists(path):
            continue
        tree = _plugin_tree(path) if role in ('plugin', 'primary') else None
        try:
            _visit(path, role, stack, done, order, (root_paths, tree, warnings))
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
    `roles`. A later layer's entry overlays the lower one FIELD BY FIELD, so a top-config
    `drivers: { snap: { standing: never-auto } }` adds standing without dropping snap's shipped
    `requires:` (no surprises); a field it restates replaces that field whole. Lets a plugin add
    os blocks (derivative distros) while the rest stay from the repo.'''
    out = {}
    for layer in layers:
        if layer.role in roles and isinstance(layer.data.get(section), dict):
            for name, spec in layer.data[section].items():
                prev = out.get(name)
                out[name] = {**prev, **spec} if isinstance(prev, dict) and isinstance(spec, dict) else spec
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
