'''reportgen.py — assemble an install-failure report the user can file upstream.

The whole point is *no hidden telemetry*: this only ever builds a payload and hands it to
the caller to show + approve. It never sends anything itself. A failed op persists a small
record (save_failure) so `configsys report <component>` can reassemble the context later,
even in a fresh run.

Before display the payload is scrubbed: the home directory collapses to `~`, and known
secrets (token/key/secret/password-shaped values, and the literal values of any such env
vars) are masked — so what the user reviews is what could be sent, already clean.
'''

import platform
import re
import subprocess
import time

from . import osdetect, plugins
from .troveio import emit_hu, load

REPORTS_REPO = 'spacemeat/configsys-issues'
_MARKER = '<!-- configsys-report v1 -->'          # reserved for later auto-labeling

# token/secret shapes to redact even when they don't sit behind a label
_SECRET_PATTERNS = [
    re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),           # GitHub PAT / OAuth / server tokens
    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'),         # Slack
    re.compile(r'AKIA[0-9A-Z]{16}'),                     # AWS access key id
]
# label=value / label: value forms -> keep the label, mask the value
_LABELED = re.compile(
    r'(?i)\b(token|api[_-]?key|secret|password|passwd|bearer|authorization)\b(\s*[=:]\s*)(\S+)')
_SECRET_ENV = re.compile(r'(?i)token|secret|password|passwd|api[_-]?key|\bkey\b')


# -- persistence ----------------------------------------------------------

def save_failure(paths, record):
    '''Persist the most recent op failure (best-effort — never raise into the op path).'''
    try:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        paths.failure_file.write_text(emit_hu(record), encoding='utf-8')
    except Exception:                                     # noqa: BLE001
        pass


def load_failure(paths):
    '''The saved failure record as a plain dict, or None if absent/unreadable.'''
    p = paths.failure_file
    if not p.exists() or not p.read_text(encoding='utf-8-sig').strip():
        return None
    try:
        trove = load(p)                                   # keep alive during the walk
        root = trove.root
        out = {}
        for i in range(root.num_children):
            ch = root[i]
            out[ch.key] = ch.value
        return out
    except Exception:                                     # noqa: BLE001
        return None


def failure_from_result(unit_key, driver, op, res):
    '''Build a persistable record from a failed driver Result.'''
    return {
        'component': unit_key.split('\\', 1)[-1],
        'unit': unit_key,
        'driver': driver,
        'op': op,
        'command': res.cmd or '',
        'exit': res.returncode,
        'output': res.output,                             # captured tail or stdout/stderr
        'at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }


# -- scrubbing ------------------------------------------------------------

def secret_values(env):
    '''Literal values of env vars whose NAME looks secret — masked wherever they appear.'''
    return sorted((v for k, v in (env or {}).items()
                   if v and len(v) >= 4 and _SECRET_ENV.search(k)), key=len, reverse=True)


def scrub(text, home=None, secrets=()):
    if not text:
        return text
    for val in secrets:                                   # exact known-secret values first
        text = text.replace(val, '***')
    if home:
        text = text.replace(str(home), '~')
    for pat in _SECRET_PATTERNS:
        text = pat.sub('***', text)
    text = _LABELED.sub(lambda m: f'{m.group(1)}{m.group(2)}***', text)
    return text


# -- collection -----------------------------------------------------------

def _git_rev(repo):
    try:
        out = subprocess.run(['git', '-C', str(repo), 'describe', '--tags', '--always', '--dirty'],
                             capture_output=True, text=True, timeout=5)
        rev = out.stdout.strip()
        if rev:
            return rev
        head = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=5)
        return head.stdout.strip() or 'unknown'
    except Exception:                                     # noqa: BLE001
        return 'unknown'


def _os_pretty():
    try:
        for line in open('/etc/os-release', encoding='utf-8'):
            if line.startswith('PRETTY_NAME='):
                return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return ''


def _route(ctx, name):
    '''Compact resolution of one component on this machine: winning binding + resolved units,
    or an error string. Mirrors what `configsys where` explains, without the printing.'''
    from .resolve import select_binding, ResolveError
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None:
        return {'error': f'unknown component "{name}"'}
    out = {'source': _layer_label(comp.source, ctx.paths)}
    if comp.bindings:
        cx = r.cascade.context(r.block, r.version, r.cpu)
        try:
            b = select_binding(comp, r.cascade, cx, r.pins)
            out['binding'] = {'via': b.via, 'when': b.when or 'always'}
        except ResolveError:
            out['binding'] = None
    try:
        units = r.resolve_names([name])
        out['units'] = sorted(units)
    except ResolveError as e:
        out['error'] = str(e)
    return out


def _layer_label(source, paths):
    if source in (str(paths.routes_file), paths.routes_file):
        return 'routes.hu'
    s, home = str(source), str(paths.home)
    return '~' + s[len(home):] if home and s.startswith(home) else s


def collect(ctx, component=None, failure=None):
    '''Assemble the (unscrubbed) report payload. `failure` is a saved/just-happened record;
    `component` overrides which component the route section explains.'''
    name = component or (failure or {}).get('component')
    payload = {
        'component': name,
        'os': {
            'block': ctx.os_info.block,
            'id': ctx.os_info.id,
            'version': ctx.os_info.version or '',
            'pretty': _os_pretty(),
            'atomic': osdetect.is_atomic(ctx.os_info.block),
        },
        'platform': {
            'kernel': platform.platform(),
            'arch': platform.machine(),
            'python': platform.python_version(),
        },
        'configsys': {'revision': _git_rev(ctx.paths.repo), 'abi': plugins.ABI_VERSION},
        'profiles': list(ctx.config.active_profiles),
        'pins': dict(ctx.config.pins() or {}),
        'route': _route(ctx, name) if name else None,
        'failure': failure or None,
    }
    return payload


# -- rendering ------------------------------------------------------------

def _fence(text):
    return f'```\n{text.rstrip()}\n```'


def render(payload, *, home=None, secrets=()):
    '''Render the payload to the scrubbed Markdown issue body the user reviews.'''
    def sc(t):
        return scrub(t, home, secrets)

    os_ = payload['os']
    pl = payload['platform']
    cs = payload['configsys']
    L = []
    L.append(f"**Component:** `{payload['component'] or '(unspecified)'}`")
    L.append('')
    L.append('### Environment')
    osline = os_['pretty'] or f"{os_['id']} {os_['version']}".strip()
    atomic = '  _(atomic/immutable)_' if os_['atomic'] else ''
    L.append(f"- **OS:** {sc(osline)} — routing block `{os_['block']}`"
             f"{(' ' + os_['version']) if os_['version'] else ''}{atomic}")
    L.append(f"- **Platform:** {sc(pl['kernel'])} · {pl['arch']} · Python {pl['python']}")
    L.append(f"- **configsys:** `{cs['revision']}` (plugin ABI {cs['abi']})")
    if payload['profiles']:
        L.append(f"- **Active profiles:** {', '.join(payload['profiles'])}")
    if payload['pins']:
        pins = ', '.join(f'{k}→{v}' for k, v in sorted(payload['pins'].items()))
        L.append(f"- **Pins:** {pins}")

    route = payload.get('route')
    if route:
        L.append('')
        L.append('### Resolved route')
        if route.get('error'):
            L.append(f"- **error:** {sc(route['error'])}")
        else:
            L.append(f"- **defined in:** {route.get('source', '?')}")
            b = route.get('binding')
            if b:
                L.append(f"- **winning binding:** via `{b['via']}`  when: `{b['when']}`")
            elif 'binding' in route:
                L.append('- **winning binding:** (none matches here)')
            if route.get('units'):
                L.append('- **resolves to:** ' + ', '.join(f'`{u}`' for u in route['units']))

    fail = payload.get('failure')
    if fail:
        L.append('')
        L.append('### Failure')
        L.append(f"- **op:** {fail.get('op')}  ·  **unit:** `{fail.get('unit')}`  "
                 f"·  **driver:** `{fail.get('driver')}`  ·  **exit:** {fail.get('exit')}"
                 f"{('  ·  ' + fail['at']) if fail.get('at') else ''}")
        if fail.get('command'):
            L.append('')
            L.append('**Command**')
            L.append(_fence(sc(str(fail['command']))))
        out = str(fail.get('output') or '').strip()
        L.append('')
        L.append('**Driver output**')
        if out:
            L.append(_fence(sc(out)))
        else:
            L.append('_(streamed to the terminal and not captured — paste the relevant '
                     'lines here before submitting)_')

    L.append('')
    L.append('---')
    L.append('_Filed with `configsys report`. Reviewed and approved by the reporter._')
    L.append('')
    L.append(_MARKER)
    return '\n'.join(L)


def title(payload):
    os_ = payload['os']
    ver = f" {os_['version']}" if os_['version'] else ''
    return f"[report] {payload['component'] or 'component'} on {os_['block']}{ver}"
