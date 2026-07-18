'''plugins.py — the plugin subsystem (P1: data plugins + sync).

A plugin is a git repo synced to ~/.config/configsys/plugins/<name>/, contributing DATA
layers (os / components / profiles) to the stack — precedence repo < plugins < discovered <
user. The user declares plugins in their config; `configsys plugin sync` reconciles the
plugins dir to pinned refs. Loading uses whatever is already on disk (sync is separate), so a
declared-but-unsynced or incompatible plugin is simply absent — its components then surface as
resilient error rows, never a brick.

This module is also the FROZEN PLUGIN SURFACE: it re-exports `Driver` + `register_driver` and
owns `ABI_VERSION`/`ABI_SUPPORTED` (the manifest gates on it), so a code plugin imports
everything from one place. P2b/P2c will add trusted loading of those Driver subclasses + the
trust model, and further `register_*` hooks. See docs/plugins.md.
'''

import shlex
from pathlib import Path

import humon

from . import layers
from .driver import Driver
from .drivers import register_driver
from .errors import ConfigError
from .runner import Result
from .troveio import _scalar

# The plugin ABI version (Driver contract + data schema + registration + RC shape). One coarse
# integer (KISS). A manifest declares `requires-abi: N`; we load it iff N is in ABI_SUPPORTED.
ABI_VERSION = 1
ABI_SUPPORTED = frozenset({1})

# The FROZEN plugin surface. A code plugin imports exactly this — one line:
#   from configsys.plugins import Driver, register_driver
# `Driver` is the base class to subclass (see configsys/driver.py for the documented
# contract: class attrs, the op set to implement, and the public helpers a subclass may
# call). `register_driver(SubclassOfDriver)` binds it so `via: <name>` resolves; `Result` is
# the return type of the mutating ops (construct one for synthetic outcomes, e.g. a no-op
# lock). Everything re-exported here is ABI-stable within a given ABI_VERSION; the underscore
# members of Driver are internal and may change without a bump. New pluggable kinds
# (version-source, transport) will join this surface as further `register_*` hooks (§10).
__all__ = [
    'Driver', 'register_driver', 'Result', 'ABI_VERSION', 'ABI_SUPPORTED',
    'declared', 'source_url', 'dir_name', 'read_manifest', 'layer_files', 'status', 'sync',
    'set_declared',
]


def declared(user_config_file):
    '''The `plugins:` list from the user config -> [ {source, ref?} ], or []. Read directly
    (before the layer stack), since plugins feed the stack.'''
    raw = layers.read_setting(user_config_file, 'plugins')
    out = []
    for entry in (raw or []):
        if isinstance(entry, dict) and entry.get('source'):
            out.append({'source': entry['source'], 'ref': entry.get('ref')})
    return out


def source_url(source):
    '''`github:owner/repo` / `gitlab:owner/repo` -> clone URL; anything else (full URL, ssh,
    file://, local path) passes through.'''
    if source.startswith('github:'):
        return f'https://github.com/{source[len("github:"):]}.git'
    if source.startswith('gitlab:'):
        return f'https://gitlab.com/{source[len("gitlab:"):]}.git'
    return source


def dir_name(source):
    '''Plugin directory basename: the repo's last path segment, minus any .git.'''
    tail = source.split(':', 1)[-1] if source.startswith(('github:', 'gitlab:')) else source
    name = tail.rstrip('/').split('/')[-1]
    return name[:-4] if name.endswith('.git') else name


def read_manifest(plugin_dir):
    '''The plugin's plugin.hu as python (name/version/requires-abi/provides/data), or {}.'''
    p = plugin_dir / 'plugin.hu'
    if not p.exists():
        return {}
    try:
        return layers.materialize_string(p.read_text(encoding='utf-8'))
    except Exception:                              # noqa: BLE001 — a broken manifest -> {}
        return {}


def _abi_ok(manifest):
    try:                                           # humon scalars materialize as strings
        return int(manifest.get('requires-abi', ABI_VERSION)) in ABI_SUPPORTED
    except (TypeError, ValueError):
        return False


def _data_files(plugin_dir, manifest):
    '''The .hu data files a plugin contributes: its manifest `data:` list, or every *.hu but
    plugin.hu.'''
    listed = manifest.get('data')
    if listed:
        return [str(plugin_dir / f) for f in (listed if isinstance(listed, list) else [listed])]
    return sorted(str(p) for p in plugin_dir.glob('*.hu') if p.name != 'plugin.hu')


def layer_files(plugins_dir, decls):
    '''Data-file paths (in declaration order) for each declared plugin that is synced AND
    ABI-compatible — the `plugin`-role layers. Unsynced/incompatible plugins are skipped.'''
    out = []
    for d in decls:
        pdir = plugins_dir / dir_name(d['source'])
        if not pdir.exists():
            continue
        manifest = read_manifest(pdir)
        if not _abi_ok(manifest):
            continue
        out.extend(_data_files(pdir, manifest))
    return out


# -- code trust (P2b): a plugin that ships code runs with the user's privileges during
# installs, so its `code:` module is imported only when the user has approved the EXACT
# commit on disk. Approvals live in a machine-local trust store keyed by dir_name(source).

def plugin_commit(runner, plugin_dir):
    '''The synced plugin's current HEAD commit sha, or None (unsynced / not a git repo /
    --pretend). This is the identity a trust approval is bound to.'''
    if not Path(plugin_dir).exists():
        return None
    r = runner.run(f'git -C {shlex.quote(str(plugin_dir))} rev-parse HEAD')
    if r is None or not getattr(r, 'ok', False):
        return None
    return (r.stdout or '').strip() or None


def read_trust(trust_file):
    '''The trust store { plugin_dir_name: approved_commit_sha }, or {} (missing/corrupt =
    nothing trusted — fail closed).'''
    p = Path(trust_file)
    if not p.exists():
        return {}
    try:
        data = layers.materialize_string(p.read_text(encoding='utf-8'))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:                                  # noqa: BLE001 — corrupt store -> trust nothing
        return {}


def write_trust(trust_file, trust):
    '''Rewrite the trust store (machine-local, not user-authored — a plain full rewrite).'''
    p = Path(trust_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not trust:
        p.write_text('{ }\n', encoding='utf-8')
        return
    lines = ['{'] + [f'    {_scalar(k)}: {_scalar(trust[k])}' for k in sorted(trust)] + ['}']
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def set_trust(trust_file, name, commit):
    trust = read_trust(trust_file)
    trust[name] = commit
    write_trust(trust_file, trust)


def remove_trust(trust_file, name):
    '''Drop `name` from the store. Returns True if it was present.'''
    trust = read_trust(trust_file)
    existed = name in trust
    trust.pop(name, None)
    write_trust(trust_file, trust)
    return existed


def is_trusted(trust_file, name, commit):
    '''True iff the store records EXACTLY this commit for this plugin. A None commit
    (unsynced / unknown) is never trusted.'''
    return commit is not None and read_trust(trust_file).get(name) == commit


def code_state(manifest, synced, approved, commit):
    '''Classify a plugin's code-trust state for display/gating:
    none (no code) | unsynced | trusted | untrusted (never approved) | changed (approved a
    different commit — code moved, must re-approve).'''
    if not manifest.get('code'):
        return 'none'
    if not synced or commit is None:
        return 'unsynced'
    if approved == commit:
        return 'trusted'
    return 'untrusted' if approved is None else 'changed'


def status(plugins_dir, decls, *, runner=None, trust_file=None):
    '''Per-declared-plugin status for `plugin list`: name, source, ref, synced, abi-ok,
    provides, has_code. When `runner` and `trust_file` are given, also resolves the on-disk
    commit and its code-trust state (git is only run in that case).'''
    trust = read_trust(trust_file) if trust_file is not None else {}
    rows = []
    for d in decls:
        key = dir_name(d['source'])
        pdir = plugins_dir / key
        synced = pdir.exists()
        manifest = read_manifest(pdir) if synced else {}
        commit = plugin_commit(runner, pdir) if (runner is not None and manifest.get('code')) else None
        rows.append({
            'name': manifest.get('name', key),
            'source': d['source'], 'ref': d.get('ref'),
            'synced': synced, 'abi_ok': (not synced) or _abi_ok(manifest),
            'requires_abi': manifest.get('requires-abi', ABI_VERSION),
            'provides': manifest.get('provides', {}),
            'has_code': bool(manifest.get('code')),
            'commit': commit,
            'code_state': code_state(manifest, synced, trust.get(key), commit),
        })
    return rows


def _emit_block(decls, indent):
    '''`plugins: [...]` humon text at the given base indent (source values quoted as needed).'''
    pad, inner = ' ' * indent, ' ' * (indent + 4)
    if not decls:
        return 'plugins: []'
    lines = ['plugins: [']
    for d in decls:
        entry = f'{{ source: {_scalar(d["source"])}'
        if d.get('ref'):
            entry += f'  ref: {_scalar(d["ref"])}'
        lines.append(inner + entry + ' }')
    lines.append(pad + ']')
    return '\n'.join(lines)


def set_declared(user_config_file, decls):
    '''Rewrite the `plugins:` list in the user config in place, preserving every other line
    (comments and all): replace the existing `plugins:` node's exact source span, or — if
    there is none — insert a block before the root's closing brace.'''
    path = Path(user_config_file)
    text = path.read_text(encoding='utf-8')
    trove = humon.from_string(text)                 # keep alive while reading source_text
    node = trove.root['plugins']
    if node is not None:
        old = node.source_text                      # 'plugins: [ ... ]', starts at the key
        pos = text.find(old)
        line_start = text.rfind('\n', 0, pos) + 1
        indent = pos - line_start                   # whitespace before `plugins:` on its line
        text = text.replace(old, _emit_block(decls, indent), 1)
    else:
        idx = text.rstrip().rfind('}')              # before the root's closing brace
        text = text[:idx] + '    ' + _emit_block(decls, 4) + '\n' + text[idx:]
    path.write_text(text, encoding='utf-8')


def _import_drivers(pdir, manifest):
    '''Import the plugin's `code:` module from disk and return its `DRIVERS` list (the explicit
    registration export). This RUNS the module's top-level code — reached only for a plugin the
    user has trusted at this exact commit. Raises on a missing file / import error / bad export.'''
    import importlib.util
    import sys
    code_file = pdir / manifest['code']
    if not code_file.exists():
        raise FileNotFoundError(f'code: {manifest["code"]} not found')
    mod_name = f'configsys_plugin_{pdir.name}'
    spec = importlib.util.spec_from_file_location(mod_name, code_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module                       # so dataclasses / self-import resolve
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    exported = getattr(module, 'DRIVERS', None)
    if exported is None:
        raise AttributeError('module defines no DRIVERS = [ ... ] export')
    return list(exported)


def load_code(runner, plugins_dir, trust_file, decls, register):
    '''Import + register the drivers of each declared plugin that is synced, ABI-compatible,
    ships code, AND is trusted at its CURRENT on-disk commit. `register` is register_driver
    (injected to keep this testable and cycle-free). Returns (loaded, skipped): loaded =
    [(dir_name, [driver_name, ...])]; skipped = [(dir_name, reason)] for a code plugin that
    ships code but was gated out (untrusted / changed / incompatible / broken). Never raises —
    a plugin that can't load is skipped, and its `via:` simply stays unknown (degrades).'''
    loaded, skipped = [], []
    for d in decls:
        key = dir_name(d['source'])
        pdir = plugins_dir / key
        if not pdir.exists():
            continue
        manifest = read_manifest(pdir)
        if not manifest.get('code'):
            continue                                     # data-only: nothing to gate
        if not _abi_ok(manifest):
            skipped.append((key, f'incompatible (needs plugin ABI {manifest.get("requires-abi")})'))
            continue
        commit = plugin_commit(runner, pdir)
        if not is_trusted(trust_file, key, commit):
            skipped.append((key, 'untrusted code (run: configsys plugin trust <name>)'))
            continue
        try:
            drivers = _import_drivers(pdir, manifest)
            for cls in drivers:
                register(cls)
            loaded.append((key, [getattr(c, 'name', '?') for c in drivers]))
        except Exception as e:                           # noqa: BLE001 — a broken module is skipped
            skipped.append((key, f'code failed to load — {e}'))
    return loaded, skipped


def sync(runner, plugins_dir, decls):
    '''Clone/fetch each declared plugin to plugins_dir/<name> at its pinned ref (via git through
    the runner, so --pretend works). Returns [(name, action)]. Best-effort per plugin.'''
    results = []
    for d in decls:
        name = dir_name(d['source'])
        dest = plugins_dir / name
        url, ref = source_url(d['source']), d.get('ref')
        dq = shlex.quote(str(dest))
        if dest.exists():
            runner.run(f'git -C {dq} fetch --tags --quiet', capture=False)
            if ref:
                runner.run(f'git -C {dq} checkout --quiet {shlex.quote(ref)}', capture=False)
            results.append((name, 'updated'))
        else:
            plugins_dir.mkdir(parents=True, exist_ok=True)
            r = runner.run(f'git clone --quiet {shlex.quote(url)} {dq}', capture=False)
            if ref and (r is None or r.ok):
                runner.run(f'git -C {dq} checkout --quiet {shlex.quote(ref)}', capture=False)
            results.append((name, 'cloned' if (r is None or r.ok) else 'failed'))
    return results
