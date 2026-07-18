'''layers.py — the config/routes layer stack: expand `include:` graphs and merge sources.

Every config/routes file is a LAYER contributing sections: os / mechanisms / components /
profiles / configs / scope / pins. A file may `include:` others (paths relative to the
including file resolve against ITS directory). Layers overlay lowest-precedence-first: the
repo (routes.hu + config.hu) is the base, an included file sits below the file that
includes it, and the top user file (~/configsys.hu) wins. Merge is by section and, within
components/profiles, by name (later wins).

Includes are DEFINITIONS-ONLY: an included file's components + profiles merge in, but its
machine settings (configs / scope / pins) and code-adjacent os / mechanisms are ignored
(collected as warnings). This is the shared substrate the plugin model will reuse — a
plugin is just another source in the stack.
'''

import os

import humon

from .errors import ConfigError

_DEFINITION_SECTIONS = ('components', 'profiles')
_SETTING_SECTIONS = ('configs', 'scope', 'pins', 'ignore-profiles', 'discover')
_REPO_SECTIONS = ('os', 'mechanisms')


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
        self.role = role          # 'repo' | 'user' | 'include'
        self.data = data          # {section: value}


def _resolve(inc, base_dir):
    inc = str(inc)
    if inc.startswith('~'):
        return os.path.expanduser(inc)
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


def expand_tolerant(roots, tolerant_roles=('discover',)):
    '''Like expand(), but a bad file (parse error / cycle / bad include) whose role is in
    `tolerant_roles` is SKIPPED with a warning instead of aborting — so a malformed project
    file you happened to `cd` into never takes down the rest. Returns (layers, warnings).
    A bad repo/user file still raises (your own config errors should be loud, not skipped).'''
    stack, done, order, warnings = [], set(), [], []
    for path, role in roots:
        if path is None or not os.path.exists(path):
            continue
        try:
            _visit(path, role, stack, done, order)
        except ConfigError as e:
            if role in tolerant_roles:
                warnings.append(f'skipped {path}: {e}')
                del stack[:]                  # a partial visit may have left the stack dirty
            else:
                raise
    return order, warnings


def _project_files(d):
    '''The project configsys files in dir `d`: `.configsys.hu` (base, first) then any
    `.configsys-*.hu` sorted. Empty if none.'''
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    base = os.path.join(d, '.configsys.hu')
    if os.path.isfile(base):
        out.append(base)
    out.extend(sorted(os.path.join(d, n) for n in names
                      if n.startswith('.configsys-') and n.endswith('.hu')
                      and os.path.isfile(os.path.join(d, n))))
    return out


def discover(start, home=None):
    '''Walk up from `start` to the nearest ancestor dir holding project configsys files
    (.configsys.hu / .configsys-*.hu) and return them (base first). Stops at `home`
    (exclusive — $HOME is user-config territory, not a project) and the filesystem root.'''
    d = os.path.abspath(start)
    home = os.path.abspath(home) if home else None
    while True:
        if home and os.path.normpath(d) == os.path.normpath(home):
            return []
        files = _project_files(d)
        if files:
            return files
        parent = os.path.dirname(d)
        if parent == d:
            return []
        d = parent


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


def merge_scalar(layers, section, roles):
    '''Last (highest-precedence) value for a single-valued section, among `roles` layers.'''
    val = None
    for layer in layers:
        if layer.role in roles and layer.data.get(section) is not None:
            val = layer.data[section]
    return val


def merge_dict_section(layers, section, roles):
    '''Union a dict section (os / mechanisms — {name: spec}) across layers whose role is in
    `roles`; a later layer's entry wins per name. Lets a plugin add os blocks (derivative
    distros) while the rest stay from the repo.'''
    out = {}
    for layer in layers:
        if layer.role in roles and isinstance(layer.data.get(section), dict):
            out.update(layer.data[section])
    return out


# what each non-repo/non-user role may NOT contribute (ignored -> a `check` warning)
_FORBIDDEN_BY_ROLE = {
    'include':  _SETTING_SECTIONS + _REPO_SECTIONS,   # definitions-only
    'discover': _SETTING_SECTIONS + _REPO_SECTIONS,   # definitions-only
    'plugin':   _SETTING_SECTIONS,                    # may add os/mechanisms, not machine settings
}


def ignored_section_warnings(layers):
    '''Sections a layer set that its role doesn't permit (silently ignored) — surfaced by check.'''
    warns = []
    for layer in layers:
        for sec in _FORBIDDEN_BY_ROLE.get(layer.role, ()):
            if sec in layer.data:
                warns.append(f'{layer.path}: `{sec}:` is ignored here (not permitted from a '
                             f'{layer.role} layer)')
    return warns
