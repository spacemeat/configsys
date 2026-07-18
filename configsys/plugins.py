'''plugins.py — the plugin subsystem (P1: data plugins + sync).

A plugin is a git repo synced to ~/.config/configsys/plugins/<name>/, contributing DATA
layers (os / components / profiles) to the stack — precedence repo < plugins < discovered <
user. The user declares plugins in their config; `configsys plugin sync` reconciles the
plugins dir to pinned refs. Loading uses whatever is already on disk (sync is separate), so a
declared-but-unsynced or incompatible plugin is simply absent — its components then surface as
resilient error rows, never a brick.

P2 will add code plugins (Python Family subclasses) + the trust model; this module also owns
the ABI version the manifest gates on. See docs/plugins.md.
'''

import shlex

from . import layers
from .errors import ConfigError

# The plugin ABI version (Family contract + data schema + registration + RC shape). One coarse
# integer (KISS). A manifest declares `requires-abi: N`; we load it iff N is in ABI_SUPPORTED.
ABI_VERSION = 1
ABI_SUPPORTED = frozenset({1})


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


def status(plugins_dir, decls):
    '''Per-declared-plugin status for `plugin list`: name, source, ref, synced, abi-ok, provides.'''
    rows = []
    for d in decls:
        pdir = plugins_dir / dir_name(d['source'])
        synced = pdir.exists()
        manifest = read_manifest(pdir) if synced else {}
        rows.append({
            'name': manifest.get('name', dir_name(d['source'])),
            'source': d['source'], 'ref': d.get('ref'),
            'synced': synced, 'abi_ok': (not synced) or _abi_ok(manifest),
            'requires_abi': manifest.get('requires-abi', ABI_VERSION),
            'provides': manifest.get('provides', {}),
            'has_code': bool(manifest.get('code')),      # P2: needs trust; inert in P1
        })
    return rows


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
