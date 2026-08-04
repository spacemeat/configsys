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

import hashlib
import os
import re
import shlex
from pathlib import Path

import humon

from . import layers, versions
from .driver import Driver
from .drivers import register_driver
from .errors import ConfigError
from .runner import Result
from .troveio import _scalar

register_version_source = versions.register_source   # re-export on the frozen surface

# Registration names owned by the core, for collision surfacing: a plugin registering one of
# these shadows a built-in. Version sources: github + the hardcoded discover kinds; transports:
# the schemes git / source_url already handle.
_BUILTIN_SOURCE_NAMES = frozenset(versions._BUILTIN_KINDS) | {'github'}
_RESERVED_SCHEMES = frozenset({'github', 'gitlab', 'git', 'https', 'http', 'file', 'ssh'})

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
# lock). The parallel hooks `register_version_source(name, fn)` (a new `version: { <name>: }`
# backend) and `register_transport(scheme, fn)` (a new `source:` sync scheme) let a plugin
# extend discovery and sync too — all three gated the same way (only trusted plugin code ever
# calls them). Everything re-exported here is ABI-stable within a given ABI_VERSION; the
# underscore members of Driver are internal and may change without a bump.
__all__ = [
    'Driver', 'register_driver', 'register_version_source', 'register_transport', 'Result',
    'ABI_VERSION', 'ABI_SUPPORTED',
    'declared', 'source_url', 'dir_name', 'read_manifest', 'layer_files', 'status', 'sync',
    'set_declared', 'set_section', 'read_pins', 'set_pins',
]


def _decl(entry, *, allow_primary=False):
    '''Normalize one plugins: entry -> {source, ref?, sha256?, primary?} or None.'''
    if not (isinstance(entry, dict) and entry.get('source')):
        return None
    d = {'source': entry['source'], 'ref': entry.get('ref')}
    if entry.get('sha256'):
        d['sha256'] = entry['sha256']               # only when pinned (keeps decls tidy)
    if allow_primary and entry.get('primary') in (True, 'true', 'yes'):
        d['primary'] = True                         # only the TOP config may grant primary
    return d


def declared(user_config_file):
    '''The `plugins:` list from the TOP user config -> [ {source, ref?, sha256?, primary?} ], or
    []. Read directly (before the layer stack), since plugins feed the stack. Only the top config
    may mark a plugin `primary: true` (grant it machine-settings authority — see the layer stack).'''
    raw = layers.read_setting(user_config_file, 'plugins')
    return [d for d in (_decl(e, allow_primary=True) for e in (raw or [])) if d]


def effective_declared(user_config_file, plugins_dir):
    '''The top-config plugin decls PLUS plugins transitively declared in each synced plugin's
    manifest `plugins:` — a fixpoint over what's on disk (breadth-first, deduped by plugin dir).
    A personal ("primary") plugin can thus bring its own plugins along, so a fresh machine
    bootstraps from a one-line top config. Transitive decls never carry `primary` (that grant is
    the top config's alone); an unsynced transitive plugin simply isn't discovered until the next
    sync populates its parent's manifest.'''
    out, seen = [], set()
    stack = list(declared(user_config_file))
    while stack:
        d = stack.pop(0)
        key = dir_name(d['source'])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        for sub in (read_manifest(plugins_dir / key).get('plugins') or []):
            nd = _decl(sub)                          # transitive: primary stripped
            if nd and dir_name(nd['source']) not in seen:
                stack.append(nd)
    return out


def primary_name(decls):
    '''The plugin dir the top config marks `primary`, or None. With more than one primary the
    first (declaration order) wins here — `check` reports the conflict as an error.'''
    prim = [dir_name(d['source']) for d in decls if d.get('primary')]
    return prim[0] if prim else None


def source_url(source):
    '''`github:owner/repo` / `gitlab:owner/repo` -> clone URL; anything else (full URL, ssh,
    file://, local path) passes through. So a private repo works by giving an ssh source
    (`git@host:owner/repo.git`) or a credential‑bearing URL, or by having git's own credential
    helper configured — configsys just shells out to git.'''
    if source.startswith('github:'):
        return f'https://github.com/{source[len("github:"):]}.git'
    if source.startswith('gitlab:'):
        return f'https://gitlab.com/{source[len("gitlab:"):]}.git'
    return source


def clone_url(source):
    '''The URL the git transport clones/fetches. Like source_url, but if CONFIGSYS_GIT_TOKEN is
    set it is embedded into a github:/gitlab: https URL so a private repo clones non-
    interactively (CI-friendly). NOTE: the token then persists in the synced repo's
    .git/config — acceptable for a personal config dir, but prefer ssh or a git credential
    helper if you'd rather not write it to disk. Other sources pass through untouched.'''
    url = source_url(source)
    token = os.environ.get('CONFIGSYS_GIT_TOKEN')
    if token and source.startswith(('github:', 'gitlab:')) and url.startswith('https://'):
        return 'https://' + token + '@' + url[len('https://'):]
    return url


def ssh_url(source):
    '''The SSH clone URL (`git@host:owner/repo.git`) for a `github:`/`gitlab:` shorthand, else None.
    A plugin clone FETCHES over https (so consuming a public plugin needs no keys), but PUSHING an
    authored plugin needs auth — and since GitHub/GitLab dropped password-over-https, an https push
    needs a token while most authors push via SSH keys. So we give the clone an ssh PUSH url and
    leave fetch on https. Only the shorthands convert; a full-URL / already-ssh source is left as-is.'''
    for scheme, host in (('github:', 'github.com'), ('gitlab:', 'gitlab.com')):
        if source.startswith(scheme):
            path = source[len(scheme):]
            return f'git@{host}:{path}' + ('' if path.endswith('.git') else '.git')
    return None


def _set_push_remote(runner, dest, source, *, only_if_unset=False):
    '''Point `origin`'s PUSH url at the ssh form (fetch untouched) so `git push` from an authored
    plugin uses the user's ssh keys. `only_if_unset` (re-sync of an existing clone) respects a push
    url the user set by hand — we set the default on first clone, then never clobber their choice.
    No-op for a non-shorthand source or a pretending runner. Best-effort.'''
    ssh = ssh_url(source)
    if not ssh:
        return
    dq = shlex.quote(str(dest))
    if only_if_unset:
        cur = runner.run(f'git -C {dq} config --get remote.origin.pushurl', capture=True)
        if cur is not None and cur.ok and cur.stdout.strip():
            return                               # user configured a push url — leave it alone
    runner.run(f'git -C {dq} remote set-url --push origin {shlex.quote(ssh)}', capture=True)


_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*:(?!//)')   # `github:`, `tarball:` — NOT `https://`


def dir_name(source):
    '''Plugin directory basename: strip a leading `scheme:` prefix (github:, gitlab:, or a
    plugin transport's scheme — but not a `scheme://` URL), then the last path segment minus
    any .git. So `github:a/b` -> b, `tarball:pkg/x` -> x, `https://h/r.git` -> r, `/a/b` -> b.'''
    tail = _SCHEME_RE.sub('', source, count=1)
    name = tail.rstrip('/').split('/')[-1]
    return name[:-4] if name.endswith('.git') else name


def read_manifest(plugin_dir):
    '''The plugin's plugin.hu as python (name/requires-abi/provides/data/code), or {}.'''
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
    '''(path, role) for each data file of each declared plugin that is synced, ABI-compatible,
    AND passes its declared checksum. role is `primary` for the top config's designated plugin (it
    may contribute machine settings), else `plugin` (definitions-only, plus os/drivers). Unsynced
    / incompatible / checksum-mismatched plugins are skipped. The `primary` plugin's files are
    ordered LAST — it is the authoritative personal layer, so its component/os overrides win over
    the (often transitively-declared) plugins it pulls in; precedence repo < plugins < primary <
    discovered < top-config.'''
    out = []
    for d in decls:
        pdir = plugins_dir / dir_name(d['source'])
        if not pdir.exists() or not checksum_ok(plugins_dir, d):
            continue
        manifest = read_manifest(pdir)
        if not _abi_ok(manifest):
            continue
        role = 'primary' if d.get('primary') else 'plugin'
        out.extend((f, role) for f in _data_files(pdir, manifest))
    out.sort(key=lambda pr: pr[1] == 'primary')   # stable: 'plugin' first, 'primary' last (wins)
    return out


def _norm_sha(s):
    '''Compare-normalize a content hash: drop an optional `sha256:` prefix, lowercase, strip.'''
    return (s or '').split(':', 1)[-1].strip().lower()


def checksum_ok(plugins_dir, decl):
    '''True if the plugin declares no `sha256` (nothing to verify) OR its synced content matches
    it. A declared checksum that does NOT match -> False: the plugin is quarantined (its data
    AND code are excluded). A pinned `ref` plus a content hash is belt-and-suspenders — it
    catches a moved tag, a compromised mirror, or a tampered synced tree.'''
    want = decl.get('sha256')
    if not want:
        return True
    got = plugin_identity(plugins_dir / dir_name(decl['source']))
    return got is not None and _norm_sha(got) == _norm_sha(want)


# -- code trust (P2b): a plugin that ships code runs with the user's privileges during
# installs, so its `code:` module is imported only when the user has approved the EXACT
# on-disk content. Approvals live in a machine-local trust store keyed by dir_name(source).

# Names/suffixes excluded from the content hash: VCS metadata and Python bytecode caches (the
# latter is written *by* importing the plugin, so hashing it would invalidate the plugin's own
# trust on the next run).
_HASH_SKIP_DIRS = {'.git', '__pycache__'}


def plugin_identity(plugin_dir):
    '''A content hash over the plugin's files — a transport-independent identity that trust
    binds to (P2c+): it replaces the old git-commit id, so a plugin fetched by any transport
    (git, tarball, OCI, …) can be trusted, and an edited working tree is caught (unlike a
    commit sha). sha256 over every file under plugin_dir — minus .git/ and __pycache__/ and
    *.pyc — in sorted path order (path bytes + NUL + content + NUL). "sha256:<hex>", or None
    if the dir is absent/has no files.'''
    root = Path(plugin_dir)
    if not root.is_dir():
        return None
    files = sorted(p for p in root.rglob('*')
                   if p.is_file() and p.suffix != '.pyc'
                   and not _HASH_SKIP_DIRS & set(p.relative_to(root).parts))
    if not files:
        return None
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(root).as_posix().encode('utf-8'))
        h.update(b'\0')
        h.update(p.read_bytes())
        h.update(b'\0')
    return 'sha256:' + h.hexdigest()


def read_trust(trust_file):
    '''The trust store { plugin_dir_name: approved_identity }, or {} (missing/corrupt =
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


def set_trust(trust_file, name, identity):
    trust = read_trust(trust_file)
    trust[name] = identity
    write_trust(trust_file, trust)


def remove_trust(trust_file, name):
    '''Drop `name` from the store. Returns True if it was present.'''
    trust = read_trust(trust_file)
    existed = name in trust
    trust.pop(name, None)
    write_trust(trust_file, trust)
    return existed


def is_trusted(trust_file, name, identity):
    '''True iff the store records EXACTLY this identity for this plugin. A None identity
    (unsynced / unknown) is never trusted.'''
    return identity is not None and read_trust(trust_file).get(name) == identity


def code_state(manifest, synced, approved, identity):
    '''Classify a plugin's code-trust state for display/gating:
    none (no code) | unsynced | trusted | untrusted (never approved) | changed (approved a
    different identity — the content moved, must re-approve).'''
    if not manifest.get('code'):
        return 'none'
    if not synced or identity is None:
        return 'unsynced'
    if approved == identity:
        return 'trusted'
    return 'untrusted' if approved is None else 'changed'


def status(plugins_dir, decls, *, trust_file=None):
    '''Per-declared-plugin status for `plugin list`: name, source, ref, synced, abi-ok,
    provides, has_code, and `checksum` ('ok'/'mismatch'/None). When `trust_file` is given, also
    resolves the on-disk content identity and its code-trust state.'''
    trust = read_trust(trust_file) if trust_file is not None else {}
    rows = []
    for d in decls:
        key = dir_name(d['source'])
        pdir = plugins_dir / key
        synced = pdir.exists()
        manifest = read_manifest(pdir) if synced else {}
        identity = plugin_identity(pdir) if (trust_file is not None and manifest.get('code')) else None
        checksum = None
        if synced and d.get('sha256'):
            checksum = 'ok' if checksum_ok(plugins_dir, d) else 'mismatch'
        rows.append({
            'name': manifest.get('name', key),
            'source': d['source'], 'ref': d.get('ref'), 'primary': bool(d.get('primary')),
            'local': is_local_authored(d['source'], pdir),   # authored in place, not pushed
            'synced': synced, 'abi_ok': (not synced) or _abi_ok(manifest),
            'requires_abi': manifest.get('requires-abi', ABI_VERSION),
            'provides': manifest.get('provides', {}),
            'has_code': bool(manifest.get('code')),
            'identity': identity,
            'checksum': checksum,
            'code_state': code_state(manifest, synced, trust.get(key), identity),
        })
    return rows


def _as_name_list(v):
    return v if isinstance(v, list) else ([v] if v else [])


def declared_conflicts(plugins_dir, decls):
    '''Names claimed by MORE THAN ONE plugin — an order-dependent collision the layer stack /
    registry resolves silently (last declared wins). Detected from manifests + data files only
    (no code is run), so it's usable by both `plugin list` and `check`:
      - `component` / `os` names in a plugin's data files,
      - `driver` names from a plugin's `provides.drivers` (and any `drivers:` config block).
    Only synced + ABI-compatible plugins count. Returns [(kind, name, [plugin_dir, ...])], sorted.'''
    owners = {}   # (kind, name) -> set(plugin_dir)
    for d in decls:
        key = dir_name(d['source'])
        pdir = plugins_dir / key
        if not pdir.exists():
            continue
        manifest = read_manifest(pdir)
        if not _abi_ok(manifest):
            continue
        for drv in _as_name_list((manifest.get('provides') or {}).get('drivers')):
            owners.setdefault(('driver', drv), set()).add(key)
        for f in _data_files(pdir, manifest):
            try:
                data = layers.materialize_string(Path(f).read_text(encoding='utf-8'))
            except Exception:                          # noqa: BLE001 — a bad data file is skipped
                continue
            if not isinstance(data, dict):
                continue
            for section, kind in (('components', 'component'), ('os', 'os'), ('drivers', 'driver')):
                sec = data.get(section)
                if isinstance(sec, dict):
                    for name in sec:
                        owners.setdefault((kind, name), set()).add(key)
    return sorted((kind, name, sorted(dirs))
                  for (kind, name), dirs in owners.items() if len(dirs) > 1)


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
        if d.get('sha256'):
            entry += f'  sha256: {_scalar(d["sha256"])}'
        if d.get('primary'):
            entry += '  primary: true'
        lines.append(inner + entry + ' }')
    lines.append(pad + ']')
    return '\n'.join(lines)


def set_section(user_config_file, section, emit):
    '''Rewrite one top-level `<section>:` node in a user config file in place, preserving every
    other line (comments and all): replace the existing node's exact source span, or — if there
    is none — insert before the root's closing brace. `emit(indent)` returns the full
    `<section>: ...` humon text at the given base indent. The single surgical write-back
    primitive shared by the plugin- and pins-config editors (span-locate via humon
    `node.source_text`, content via template emit — never a whole-file re-serialization, so
    comments and layout survive).'''
    path = Path(user_config_file)
    text = path.read_text(encoding='utf-8')
    trove = humon.from_string(text)                 # keep alive while reading source_text
    node = trove.root[section]
    if node is not None:
        old = node.source_text                      # '<section>: ...', starts at the key
        pos = text.find(old)
        line_start = text.rfind('\n', 0, pos) + 1
        indent = pos - line_start                   # whitespace before the key on its line
        text = text.replace(old, emit(indent), 1)
    else:
        idx = text.rstrip().rfind('}')              # before the root's closing brace
        text = text[:idx] + '    ' + emit(4) + '\n' + text[idx:]
    path.write_text(text, encoding='utf-8')


def set_declared(user_config_file, decls):
    '''Rewrite the `plugins:` list in the user config in place, preserving every other line.'''
    set_section(user_config_file, 'plugins', lambda indent: _emit_block(decls, indent))


def read_pins(config_file):
    '''The scalar pins map (name -> via / provider) from ONE .hu file's top-level `pins:`, or {}.
    For editing a single layer's own pins in place — config.pins() gives the MERGED view instead.'''
    p = Path(config_file)
    if not p.exists():
        return {}
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    pins = data.get('pins') if isinstance(data, dict) else None
    if not isinstance(pins, dict):
        return {}
    return {k: v for k, v in pins.items() if not isinstance(v, (dict, list))}


def _emit_pins(pins, indent):
    if not pins:
        return 'pins: {}'
    pad, inner = ' ' * indent, ' ' * (indent + 4)
    body = [f'{inner}{k}: {_scalar(v)}' for k, v in pins.items()]
    return '\n'.join(['pins: {'] + body + [pad + '}'])


def set_pins(config_file, pins):
    '''Rewrite the `pins:` node of a config/plugin .hu file in place (preserving comments and the
    rest), or remove the node entirely when `pins` is empty. The surgical write-back the pin CLI
    and the TUI method picker share (via set_section / remove_sections).'''
    if not pins:
        remove_sections(config_file, ['pins'])
        return
    set_section(config_file, 'pins', lambda indent: _emit_pins(pins, indent))


def _flat(v):
    '''Flatten a profile/configs value to a flat list of term strings.'''
    if isinstance(v, list):
        return [s for x in v for s in _flat(x)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _flat(x)]
    return [] if v is None else [str(v)]


def read_profiles(config_file):
    '''`{profile: [term, ...]}` from ONE .hu file's own top-level `profiles:` (raw term lists,
    unexpanded), or {}. For editing a single layer's profiles in place — Config.profile_components
    gives the MERGED/expanded view instead.'''
    p = Path(config_file)
    if not p.exists():
        return {}
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    profs = data.get('profiles') if isinstance(data, dict) else None
    if not isinstance(profs, dict):
        return {}
    return {name: _flat(val) for name, val in profs.items()}


def _emit_profiles(profiles, indent):
    pad, inner = ' ' * indent, ' ' * (indent + 4)
    if not profiles:
        return 'profiles: {}'
    lines = ['profiles: {']
    for name, terms in profiles.items():
        lines.append(f'{inner}{name}: [ {"  ".join(str(t) for t in terms)} ]' if terms
                     else f'{inner}{name}: []')
    return '\n'.join(lines + [pad + '}'])


def set_profiles(config_file, profiles):
    '''Rewrite the `profiles:` node of a config/plugin .hu in place (comments OUTSIDE it preserved;
    inline comments WITHIN the section are re-serialized away, like the pins writer), or remove it
    when empty. Values are raw term lists.'''
    if not profiles:
        remove_sections(config_file, ['profiles'])
        return
    set_section(config_file, 'profiles', lambda indent: _emit_profiles(profiles, indent))


def read_scalar_section(config_file, key):
    '''The scalar value of a top-level `<key>:` from ONE .hu file (not a list/dict), or None.'''
    p = Path(config_file)
    if not p.exists():
        return None
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    v = data.get(key) if isinstance(data, dict) else None
    return None if isinstance(v, (dict, list)) else v


def set_scalar_section(config_file, key, value):
    '''Set a top-level scalar `<key>: <value>` in place, or remove the node when `value` is None.'''
    if value is None:
        remove_sections(config_file, [key])
        return
    set_section(config_file, key, lambda indent: f'{key}: {_scalar(value)}')


def read_list_section(config_file, key):
    '''The flat name list of a top-level `<key>:` (scalar or list) from ONE .hu file, or [].'''
    p = Path(config_file)
    if not p.exists():
        return []
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    return _flat(data.get(key)) if isinstance(data, dict) else []


def set_list_section(config_file, key, items):
    '''Rewrite a top-level list `<key>: [ ... ]` in place, or remove the node when empty.'''
    if not items:
        remove_sections(config_file, [key])
        return
    set_section(config_file, key,
                lambda indent: f'{key}: [ {"  ".join(str(i) for i in items)} ]')


def read_configs(config_file):
    '''The active-profile name list from ONE .hu file's top-level `configs:` (scalar or list), or [].'''
    return read_list_section(config_file, 'configs')


def _emit_kv(key, value, indent):
    '''One `key: <value>` line (or block) at `indent`, recursing into nested dicts — for the `theme:`
    section (colors / elements.<el>.<attr> / gradient). Bools emit as bare humon true/false.'''
    pad = ' ' * indent
    if isinstance(value, dict):
        lines = [f'{pad}{key}: {{']
        for k, v in value.items():
            lines.append(_emit_kv(k, v, indent + 4))
        return '\n'.join(lines + [pad + '}'])
    if isinstance(value, bool):
        return f'{pad}{key}: {"true" if value else "false"}'
    if isinstance(value, list):
        return f'{pad}{key}: [ {"  ".join(_scalar(x) for x in value)} ]'
    return f'{pad}{key}: {_scalar(value)}'


def read_theme(config_file):
    '''The raw nested `theme:` override dict from ONE .hu file, or {}.'''
    p = Path(config_file)
    if not p.exists():
        return {}
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    t = data.get('theme') if isinstance(data, dict) else None
    return t if isinstance(t, dict) else {}


def set_theme(config_file, theme):
    '''Rewrite the nested `theme:` node in place (or remove it when empty).'''
    if not theme:
        remove_sections(config_file, ['theme'])
        return

    def emit(indent):
        pad = ' ' * indent
        body = [_emit_kv(k, v, indent + 4) for k, v in theme.items()]
        return '\n'.join(['theme: {'] + body + [pad + '}'])
    set_section(config_file, 'theme', emit)


def set_configs(config_file, names):
    '''Rewrite the `configs:` node in place (or remove it when empty).'''
    set_list_section(config_file, 'configs', names)


def config_sections_text(user_config_file, keys):
    '''{key: raw source_text} for the given top-level config keys that are PRESENT — the verbatim
    humon text (comments and all), for copying a user's `profiles:`/`components:` into a plugin.'''
    p = Path(user_config_file)
    if not p.exists():
        return {}
    trove = humon.from_string(p.read_text(encoding='utf-8'))   # keep alive while reading source_text
    out = {}
    for k in keys:
        node = trove.root[k]
        if node is not None:
            out[k] = node.source_text
    return out


def remove_sections(user_config_file, keys):
    '''Remove the given top-level section nodes from the user config, preserving everything else
    (comments and all) — the counterpart to set_declared, for cleaning up config that has moved
    into a plugin. Returns the keys actually removed. A comment sitting ABOVE a removed section is
    left in place (we only delete the node's own span), so it may be orphaned — cheap to tidy by
    hand, and safer than guessing which comments belonged to the section.'''
    path = Path(user_config_file)
    text = path.read_text(encoding='utf-8')
    trove = humon.from_string(text)                  # keep alive while reading source_text
    removed = []
    for k in keys:
        node = trove.root[k]
        if node is None:
            continue
        span = node.source_text                      # 'profiles: { ... }', starts at the key
        idx = text.find(span)
        if idx < 0:
            continue
        start = idx                                   # eat SAME-LINE leading whitespace only (so a
        while start > 0 and text[start - 1] in ' \t':  # single-line `{ a  profiles:… }` is safe)
            start -= 1
        end = idx + len(span)                         # then trailing spaces + one optional newline
        while end < len(text) and text[end] in ' \t':
            end += 1
        if end < len(text) and text[end] == '\n':
            end += 1
        text = text[:start] + text[end:]
        removed.append(k)
    path.write_text(text, encoding='utf-8')
    return removed


def scaffold_primary(plug_dir, name, transitive_decls=(), sections=None):
    '''Write a locally-authored primary plugin's files: a data-only `plugin.hu` (manifest) and,
    when `sections` ({key: text}) are given, a `<name>.hu` carrying them verbatim. `transitive_decls`
    become the manifest's `plugins:` list (their `primary` flag stripped — a transitive plugin is
    never itself primary). Creates an (empty) `dotfiles/` so it's the capture target.'''
    plug_dir = Path(plug_dir)
    plug_dir.mkdir(parents=True, exist_ok=True)
    trans = [{k: v for k, v in d.items() if k != 'primary'} for d in (transitive_decls or [])]
    lines = ['{', f'    name: {name}', f'    requires-abi: {ABI_VERSION}']
    if sections:
        lines.append(f'    data: [ {name}.hu ]')
    if trans:
        lines.append('    ' + _emit_block(trans, 4))
    lines.append('}')
    (plug_dir / 'plugin.hu').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if sections:
        body = '{\n' + ''.join(f'    {t}\n' for t in sections.values()) + '}\n'
        (plug_dir / f'{name}.hu').write_text(body, encoding='utf-8')
    (plug_dir / 'dotfiles').mkdir(exist_ok=True)


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


def _collect_reg_conflicts(out, kind, owners, builtins, builtin_note):
    '''Append conflict strings for a registration map {name: [plugin_keys]}: a name claimed by
    2+ plugins (last loaded wins), or a single plugin shadowing a built-in name.'''
    for name, keys in sorted(owners.items()):
        if len(keys) > 1:
            out.append(f"conflict: {kind} '{name}' registered by plugins "
                       f"{', '.join(keys)} (last loaded wins)")
        elif name in builtins:
            out.append(f"conflict: {kind} '{name}' from plugin {keys[0]} {builtin_note}")


def load_code(plugins_dir, trust_file, decls, register, conflicts=None):
    '''Import + register the drivers of each declared plugin that is synced, ABI-compatible,
    ships code, AND is trusted at its CURRENT on-disk content. `register` is register_driver
    (injected to keep this testable and cycle-free). Returns (loaded, skipped): loaded =
    [(dir_name, [driver_name, ...])]; skipped = [(dir_name, reason)] for a code plugin that
    ships code but was gated out (untrusted / changed / incompatible / broken). Never raises —
    a plugin that can't load is skipped, and its `via:` simply stays unknown (degrades).

    If `conflicts` (a list) is given, code-level REGISTRATION collisions are appended to it: two
    plugins registering the same version-source / transport (last loaded wins), or one shadowing
    a built-in. These are observable only by running the code, so they can't be found
    declaratively — driver-name conflicts, which can, are left to declared_conflicts.'''
    loaded, skipped = [], []
    src_owners, tr_owners = {}, {}       # registered name/scheme -> [plugin keys that added it]
    for d in decls:
        key = dir_name(d['source'])
        pdir = plugins_dir / key
        if not pdir.exists():
            continue
        manifest = read_manifest(pdir)
        if not manifest.get('code'):
            continue                                     # data-only: nothing to gate
        if not checksum_ok(plugins_dir, d):
            skipped.append((key, 'content does not match declared sha256 (quarantined)'))
            continue
        if not _abi_ok(manifest):
            skipped.append((key, f'incompatible (needs plugin ABI {manifest.get("requires-abi")})'))
            continue
        if not is_trusted(trust_file, key, plugin_identity(pdir)):
            skipped.append((key, 'untrusted code (run: configsys plugin trust <name>)'))
            continue
        try:
            before_src, before_tr = dict(versions._SOURCES), dict(_TRANSPORTS)
            drivers = _import_drivers(pdir, manifest)
            for cls in drivers:
                register(cls)
            for n, fn in versions._SOURCES.items():      # names this plugin (re)registered
                if before_src.get(n) is not fn:
                    src_owners.setdefault(n, []).append(key)
            for s, fn in _TRANSPORTS.items():
                if before_tr.get(s) is not fn:
                    tr_owners.setdefault(s, []).append(key)
            loaded.append((key, [getattr(c, 'name', '?') for c in drivers]))
        except Exception as e:                           # noqa: BLE001 — a broken module is skipped
            skipped.append((key, f'code failed to load — {e}'))
    if conflicts is not None:
        _collect_reg_conflicts(conflicts, 'version-source', src_owners, _BUILTIN_SOURCE_NAMES,
                               'shadows a built-in source (ignored — built-ins win)')
        _collect_reg_conflicts(conflicts, 'transport', tr_owners, _RESERVED_SCHEMES,
                               'overrides the built-in git handling for that scheme')
    return loaded, skipped


def _git_checkout(runner, dq, ref):
    '''Put the checkout at `ref` as it is on the remote now, so a re-sync advances.

    A BRANCH ref stays ON its local branch (ATTACHED HEAD) and fast-forwards to `origin/<ref>`. This
    keeps a plugin you author in place (your primary) on a real, pushable branch — so `plugin add` /
    `plugin init` edits + commits land on the branch, never on a detached HEAD whose commits git will
    eventually gc — and, being ff-only with no `--force`, a re-sync neither discards commits the
    branch is ahead by nor clobbers an in-progress uncommitted edit (it simply no-ops when it can't
    fast-forward). A TAG or commit ref DETACHES (it is immutable — you cannot be "on" it) with
    `--force` to overwrite drift; NO ref -> the remote's default branch (`origin/HEAD`), detached.
    Returns True unless the checkout itself failed (a pretended/absent run counts as ok).'''
    def _has(rev):
        r = runner.run(f'git -C {dq} rev-parse --verify --quiet {shlex.quote(rev)}', capture=True)
        return r is not None and r.ok and not r.pretended
    if ref and _has(f'origin/{ref}'):            # a BRANCH: stay attached, fast-forward
        rq = shlex.quote(ref)
        co = runner.run(f'git -C {dq} checkout --quiet {rq}', capture=True)   # DWIM creates+tracks
        if co is not None and not co.ok:         # older git / edge: create it tracking origin/<ref>
            co = runner.run(f'git -C {dq} checkout --quiet -B {rq} --track origin/{rq}', capture=True)
        runner.run(f'git -C {dq} merge --ff-only --quiet origin/{rq}', capture=True)   # no-op if ahead
        return co is None or co.ok
    target = ref if ref else ('origin/HEAD' if _has('origin/HEAD') else None)
    if target is None:
        return True                              # no ref and no known default branch: leave as-is
    co = runner.run(f'git -C {dq} checkout --quiet --force --detach {shlex.quote(target)}',
                    capture=False)
    return co is None or co.ok


def ensure_branch(runner, dest):
    '''Make sure `dest`'s HEAD is on a BRANCH (not detached), so an in-place edit + commit there lands
    on a real, pushable ref instead of a detached HEAD (whose commits git eventually gc's). No-op when
    already on a branch. When detached (a tag/commit sync left it so), reattach to the tracking/default
    branch — `origin/HEAD` (usually `main`). Returns the branch name, or None if it can't reattach
    (e.g. no origin/HEAD; the caller should then warn). Best-effort; safe under --pretend.'''
    dq = shlex.quote(str(dest))
    cur = runner.run(f'git -C {dq} symbolic-ref --short -q HEAD', capture=True)
    if cur is not None and cur.ok and cur.stdout.strip():
        return cur.stdout.strip()                # already on a branch
    head = runner.run(f'git -C {dq} rev-parse --abbrev-ref origin/HEAD', capture=True)
    branch = head.stdout.strip().split('/', 1)[-1] if (head is not None and head.ok) else ''
    if not branch or branch == 'HEAD':
        return None
    co = runner.run(f'git -C {dq} checkout --quiet {shlex.quote(branch)}', capture=True)
    return branch if (co is None or co.ok) else None


def _local_source_path(source):
    '''The filesystem path a LOCAL `source:` refers to (a plugin authored in place, not fetched
    from a remote), or None for a remote source (github:/gitlab:/a URL/ssh). Lets sync no-op a
    plugin whose source IS its own on-disk dir — the `plugin init` local-authoring model.'''
    if not source or '://' in source or source.startswith('git@'):
        return None
    head = source.split(':', 1)[0] if ':' in source else ''
    if head in ('github', 'gitlab'):
        return None
    return Path(source).expanduser()


def is_local_authored(source, dest):
    '''True when `source` is a local path equal to its own plugin dir `dest` — authored in place,
    nothing to clone/fetch (it IS the repo you later push).'''
    lp = _local_source_path(source)
    try:
        return lp is not None and lp.resolve() == Path(dest).resolve()
    except OSError:
        return False


def find_decl(decls, plugins_dir, ident):
    '''A declared plugin matching `ident` — its source, dir basename, or manifest name.'''
    for d in decls:
        dn = dir_name(d['source'])
        if ident in (d['source'], dn) or read_manifest(Path(plugins_dir) / dn).get('name') == ident:
            return d
    return None


def upsert_decl(decls, source, ref):
    '''Add `source` to a decls list, or re-pin its ref if already there. Returns (target, existed);
    target is a live element of `decls`.'''
    target = next((d for d in decls if d['source'] == source), None)
    if target is not None:
        target['ref'] = ref
        return target, True
    target = {'source': source, 'ref': ref}
    decls.append(target)
    return target, False


def source_hint(source):
    '''A nudge when a source can't be synced: the common `github.com:x/y` mistyping of the
    `github:x/y` shorthand, else how to reach a private repo.'''
    for prov in ('github', 'gitlab'):
        pfx = prov + '.com:'
        if source.startswith(pfx):
            return f'(did you mean {prov}:{source[len(pfx):]} ?)'
    return ('(private repo? use ssh git@host:owner/repo.git, a token via '
            'CONFIGSYS_GIT_TOKEN, or a configured git credential helper)')


def _noninteractive_git_env():
    '''Env for plugin git fetches so they NEVER block on a credential prompt: an unreachable,
    nonexistent, or private repo must fail fast (sync -> 'failed') instead of hanging the CLI/TUI
    on `Username for 'https://github.com':`. GIT_TERMINAL_PROMPT=0 kills git's own terminal prompt;
    GCM_INTERACTIVE=never stops git-credential-manager from popping one. A configured credential
    helper still answers non-interactively, so a properly set-up private repo (ssh, a token via
    CONFIGSYS_GIT_TOKEN, or a helper with stored creds) keeps working.'''
    return {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def _git_transport(runner, dest, source, ref):
    '''The built-in transport: clone/fetch a git repo to `dest`, then detach at `ref` as it is on
    the remote now (see _git_checkout). `fetch --force` so a re-pointed tag updates; a failed
    checkout is reported as 'failed', not silently 'updated'. A locally-authored plugin (source ==
    its own dir) is 'local' — untouched. Fetches run NON-INTERACTIVELY (never prompt for
    credentials — a bad/private source fails fast). Returns 'local'/'cloned'/'updated'/'failed'.'''
    if is_local_authored(source, dest):
        return 'local'
    dq = shlex.quote(str(dest))
    genv = _noninteractive_git_env()
    if dest.exists():
        runner.run(f'git -C {dq} fetch --force --tags --quiet', capture=False, env=genv)   # --force: re-pointed tags; non-fatal (offline -> checkout from local refs)
        _set_push_remote(runner, dest, source, only_if_unset=True)   # keep ssh push url, don't clobber a manual one
        return 'updated' if _git_checkout(runner, dq, ref) else 'failed'
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = runner.run(f'git clone --quiet {shlex.quote(clone_url(source))} {dq}', capture=False, env=genv)
    if r is not None and not r.ok:
        return 'failed'
    _set_push_remote(runner, dest, source)          # push via ssh keys; fetch stays https
    return 'cloned' if _git_checkout(runner, dq, ref) else 'failed'


# Registered sync transports (P2c): a plugin claims a `source:` scheme so `source:
# "<scheme>:..."` syncs via its fn instead of git. scheme -> fn(runner, dest, source, ref) ->
# action_str. Registration happens only from trusted plugin code (via load_code).
_TRANSPORTS = {}


def register_transport(scheme, fn):
    '''Register a sync transport for a `source:` scheme. `fn(runner, dest, source, ref) ->
    action` must materialize the plugin tree into `dest`. Re-exported as register_transport.
    Code trust binds to a CONTENT hash (plugin_identity), not a git commit, so a plugin fetched
    by any transport — git, tarball, OCI — can carry `code:` and be trusted the same way.'''
    if not scheme or not callable(fn):
        raise ValueError('register_transport(scheme, fn): scheme non-empty and fn callable')
    _TRANSPORTS[scheme] = fn
    return fn


def _transport_for(source):
    '''The transport for a source: a registered `<scheme>:` wins, else git (the default).'''
    scheme = source.split(':', 1)[0] if ':' in source else None
    return _TRANSPORTS.get(scheme, _git_transport)


def sync(runner, plugins_dir, decls):
    '''Sync each declared plugin to plugins_dir/<name> at its ref, via its transport (git by
    default; a registered transport claims a `<scheme>:` source). Returns [(name, action)].
    Transitive: after a plugin is synced, plugins named in ITS manifest `plugins:` are enqueued
    and synced too (fixpoint, deduped by dir) — so a primary/personal plugin pulls its own
    plugin set. Best-effort: a transport failure becomes a per-plugin 'failed' action, never an
    exception.'''
    results, seen = [], set()
    stack = list(decls)
    while stack:
        d = stack.pop(0)
        name = dir_name(d['source'])
        if name in seen:
            continue
        seen.add(name)
        try:
            action = _transport_for(d['source'])(runner, plugins_dir / name, d['source'],
                                                 d.get('ref'))
        except Exception as e:                       # noqa: BLE001 — isolate a bad transport
            action = f'failed ({e})'
        results.append((name, action))
        for sub in (read_manifest(plugins_dir / name).get('plugins') or []):
            nd = _decl(sub)
            if nd and dir_name(nd['source']) not in seen:
                stack.append(nd)
    return results
