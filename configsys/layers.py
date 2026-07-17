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
_SETTING_SECTIONS = ('configs', 'scope', 'pins')
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
    includer), deduped (diamonds appear once), and cycle-checked. Missing roots are skipped.'''
    stack, done, order = [], set(), []
    for path, role in roots:
        if path is not None and os.path.exists(path):
            _visit(path, role, stack, done, order)
    return order


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


def repo_section(layers, section):
    '''A repo-only section (os / mechanisms) from the repo layers; last non-empty wins.'''
    val = {}
    for layer in layers:
        if layer.role == 'repo' and layer.data.get(section):
            val = layer.data[section]
    return val


def include_warnings(layers):
    '''Sections an included file set that are ignored (includes are definitions-only).'''
    warns = []
    for layer in layers:
        if layer.role != 'include':
            continue
        for sec in _SETTING_SECTIONS + _REPO_SECTIONS:
            if sec in layer.data:
                warns.append(f'{layer.path}: `{sec}:` in an included file is ignored '
                             f'(includes are definitions-only)')
    return warns
