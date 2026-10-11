#!/usr/bin/env python3
'''compaudit — the mechanical half of the `/update-component` audit (see
.claude/skills/update-component/SKILL.md).

It enumerates the components DEFINED in a scope (base routes.hu, or one plugin's data files),
groups each with its companions (`<name>-dotfiles` / `-glue` / `-service` / `-group`), runs cheap
deterministic upstream probes, and writes batch files the skill hands to audit subagents. The
judgment work — license/telemetry drift, new install methods, config-path moves — is the
subagents'; this tool gathers the facts they start from, so forty agents don't each hammer the
GitHub API.

Probes (cached under $XDG_CACHE_HOME/configsys/compaudit, default TTL 1 day):
  github   — repo renamed (redirect / full_name) or gone; latest release tag; whether each
             binding's `asset:` glob still matches an asset of that release. With a token
             (CONFIGSYS_GITHUB_TOKEN / GITHUB_TOKEN, else `gh auth token` if gh is logged in)
             also archived / license / last push.
  flathub  — app-id published; end-of-life (renamed via eol/rebase, or an eol message).
  aur      — package exists; orphaned; flagged out-of-date.
  brew     — formula exists (else an alias / old name of which formula); deprecated; disabled;
             keg-only on Linux (not on PATH — house rule: no brew binding); macOS-only. One fetch of the
             full formulae.brew.sh index serves every brew binding (the per-formula API 404s on
             aliases).
  crates / pypi / npm — package exists; npm deprecation.

Usage:
  python3 tools/compaudit.py list  <scope>
  python3 tools/compaudit.py scan  <scope> [names...] [--full | --due-days N] [--batch-size N]
                                   [--out DIR] [--no-probe] [--ttl HOURS]
  python3 tools/compaudit.py record <scope> <names...>    # mark units deep-audited (ledger)
  python3 tools/compaudit.py token                        # preflight: is a GitHub token available?

<scope> is `base` (this repo's routes.hu) or a plugin: a name (`configsys-blender`) or a path.
A plugin name resolves to its DEV CHECKOUT — $CONFIGSYS_PLUGIN_SRC/<name>, else a sibling of this
repo (../<name>) — falling back to the synced clone in ~/.config/configsys/plugins/<name> (read-only
for editing purposes: `plugin sync` overwrites it).
'''

import argparse
import concurrent.futures
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
ROUTES = ROOT / 'routes.hu'

COMPANION_SUFFIXES = ('-dotfiles', '-glue', '-service', '-group')
ARCHES = ('x86_64', 'aarch64')
UA = 'configsys-compaudit (+https://github.com/spacemeat/configsys)'


# -- scope ------------------------------------------------------------------

def _cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'configsys' / 'compaudit'


def resolve_scope(scope):
    '''-> (label, root_dir, [layer files], is_plugin). `base` = this repo's routes.hu.'''
    if scope in ('base', '*', ''):
        return 'base', ROOT, [str(ROUTES)], False
    from configsys import plugins
    p = Path(scope).expanduser()
    if not p.is_dir():
        cands = []
        if os.environ.get('CONFIGSYS_PLUGIN_SRC'):
            cands.append(Path(os.environ['CONFIGSYS_PLUGIN_SRC']) / scope)
        cands += [ROOT.parent / scope,
                  Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
                  / 'configsys' / 'plugins' / scope]
        p = next((c for c in cands if (c / 'plugin.hu').is_file()), None)
        if p is None:
            sys.exit(f'compaudit: no plugin named {scope!r} (looked in: {", ".join(map(str, cands))})')
    files = plugins._data_files(p, plugins.read_manifest(p))
    return p.name, p.resolve(), files, True


def load_scope(scope):
    '''-> (label, root, {unit: record}). A unit is a parent component plus its companions; a
    companion whose parent isn't in scope stands alone.'''
    from configsys import layers
    label, root, files, is_plugin = resolve_scope(scope)
    roots = [(str(ROUTES), 'repo')] + ([(f, 'plugin') for f in files] if is_plugin else [])
    layer_list, _warn = layers.expand_tolerant(roots, {'plugin', 'primary'})
    chains = layers.collect_named(layer_list, 'components')
    scope_files = {os.path.normpath(f) for f in files}
    in_scope = sorted(n for n, chain in chains.items()
                      if any(os.path.normpath(src) in scope_files for _i, _v, src in chain))

    def parent_of(name):
        for suf in COMPANION_SUFFIXES:
            if name.endswith(suf) and name[:-len(suf)] in chains:
                return name[:-len(suf)]
        return None

    units = {}
    for name in in_scope:
        par = parent_of(name)
        key = par if par in in_scope else name
        units.setdefault(key, []).append(name)
    out = {}
    for key, names in sorted(units.items()):
        names.sort(key=lambda n: (n != key, n))
        comps = {n: _component_record(n, chains[n], scope_files, root) for n in names}
        out[key] = {'unit': key, 'scope': label, 'components': comps,
                    'probes': _probe_targets(comps), 'def_hash': _hash(comps)}
    return label, root, out


def _component_record(name, chain, scope_files, root):
    layers_ = []
    for _i, val, src in chain:
        layers_.append({'source': os.path.relpath(src, ROOT.parent),
                        'in_scope': os.path.normpath(src) in scope_files,
                        'line': _find_line(src, name),
                        'spec': val})
    rec = {'name': name, 'layers': layers_}
    glue = _glue_presence(chain, root)
    if glue:
        rec['glue_files'] = glue
    return rec


_LINE_CACHE = {}


def _find_line(path, name):
    if path not in _LINE_CACHE:
        try:
            _LINE_CACHE[path] = Path(path).read_text(encoding='utf-8').splitlines()
        except OSError:
            _LINE_CACHE[path] = []
    pat = re.compile(r'^\s*' + re.escape(name) + r'\s*:')
    return next((i + 1 for i, line in enumerate(_LINE_CACHE[path]) if pat.match(line)), None)


def _glue_presence(chain, root):
    '''{glue_name: [shell variant files found]} for every `glue: X` a binding declares — empty list
    = the glue is referenced but ships no variant (a broken companion).'''
    names = set()
    for _i, val, _src in chain:
        for b in _bindings(val):
            for v in [b.get('glue')] + [x.get('glue') for x in b.values() if isinstance(x, dict)]:
                if isinstance(v, str):
                    names.add(v)
    found = {}
    for g in sorted(names):
        hits = set()
        for base in {root, ROOT}:
            for f in (base / 'glue' / 'shell').glob(f'*/{g}.*'):
                hits.add(os.path.relpath(f, base))
        found[g] = sorted(hits)
    return found


def _bindings(spec):
    if not isinstance(spec, dict):
        return []
    return [b for b in (spec.get('install') or []) if isinstance(b, dict)]


def _hash(comps):
    blob = json.dumps({n: [l['spec'] for l in c['layers'] if l['in_scope']] for n, c in comps.items()},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# -- probe targets ----------------------------------------------------------

_GH_URL = re.compile(r'https?://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?(?:/|$|")')


def _probe_targets(comps):
    '''Upstream identifiers worth checking, from the IN-SCOPE layers' bindings.'''
    t = {'github': {}, 'flatpak': [], 'aur': [], 'brew': [], 'crates': [], 'pypi': [], 'npm': [],
         'static': []}
    for name, c in comps.items():
        for layer in c['layers']:
            if not layer['in_scope']:
                continue
            for b in _bindings(layer['spec']):
                via = b.get('via')
                ver = b.get('version') if isinstance(b.get('version'), dict) else {}
                repos = set()
                if isinstance(ver.get('github'), str):
                    repos.add(ver['github'])
                for k in ('repo', 'url'):
                    m = _GH_URL.search(str(b.get(k) or '') + '"')
                    if m:
                        repos.add(m.group(1))
                for r in repos:
                    ent = t['github'].setdefault(r, {'components': [], 'assets': []})
                    if name not in ent['components']:
                        ent['components'].append(name)
                    for glob in _asset_globs(b, ver):
                        ent['assets'].append({'component': name, 'via': via, 'when': b.get('when'),
                                              'glob': glob})
                arch = _arch_unguarded(name, b, ver)
                if arch:
                    t['static'].append(arch)
                pkg = b.get('name') if isinstance(b.get('name'), str) else None
                if via == 'flatpak' and b.get('app'):
                    t['flatpak'].append(b['app'])
                elif via == 'aur':
                    t['aur'].append(pkg or name)
                elif via == 'brew' or (via == 'native' and isinstance(b.get('name'), dict)
                                       and b['name'].get('brew')):
                    formula = _brew_formula(b, name)
                    if formula:
                        t['brew'].append(formula)
                elif via == 'cargo':
                    t['crates'].append(ver.get('crates') or pkg or name)
                elif via in ('pip', 'pipx'):
                    t['pypi'].append(ver.get('pypi') or pkg or name)
                elif via == 'npm':
                    t['npm'].append(pkg or name)
    for k in ('flatpak', 'aur', 'brew', 'crates', 'pypi', 'npm'):
        t[k] = sorted(set(t[k]))
    return {k: v for k, v in t.items() if v}


def _brew_formula(b, name):
    '''The formula a brew binding installs: a scalar `name:`, else its `brew:` (or `default:`) key,
    else the component name. `{}` in a name map means "no package there".'''
    n = b.get('name')
    if isinstance(n, dict):
        n = n.get('brew', n.get('default', name))
    return n if isinstance(n, str) and n else (None if n is not None else name)


_X86_TOKEN = re.compile(r'(x86[_-]64|amd64|linux64|\bx64\b|-x64[.-]|[-_]64bit\b)', re.I)


def _arch_unguarded(name, b, ver):
    '''A static finding when a binary-download binding hard-codes an x86-64 artifact (no $ARCH, no
    arch-keyed map) yet its `when:` doesn't gate `cpu:` — on aarch64 it would fetch an x86 binary.'''
    if b.get('via') not in ('tarball', 'appImage', 'native-pkg-file', 'script'):
        return None
    if 'cpu:' in str(b.get('when') or '') or isinstance(b.get('cpu-names'), dict):
        return None                                    # cpu-gated (when:) or arch-declared (cpu-names:)
    lits = [x for x in (ver.get('asset'), b.get('url'), b.get('asset')) if isinstance(x, str)]
    hit = next((x for x in lits if '$ARCH' not in x and _X86_TOKEN.search(x)), None)
    if not hit:
        return None
    return _fd('drift', 'arch-unguarded',
               f'{name} via:{b.get("via")} downloads an x86-64-only artifact ({hit!r}) but `when:` has no '
               f'arch gate — on aarch64 it would install an x86 binary. Use `$ARCH` + `cpu-names:` '
               f'({{ x86_64: <token> }} alone if upstream ships no arm64 build)', binding=_bkey({'via': b.get('via'), 'when': b.get('when')}))


def _asset_globs(b, ver):
    '''Every concrete asset glob a binding may download (arch- and format-keyed maps flattened,
    $ARCH expanded for each arch we ship).'''
    raw = []
    if isinstance(ver.get('asset'), str):
        raw.append(ver['asset'])
    a = b.get('asset')
    if isinstance(a, str):
        raw.append(a)
    elif isinstance(a, dict):
        for v in a.values():
            if isinstance(v, str):
                raw.append(v)
            elif isinstance(v, dict):
                raw += [x for x in v.values() if isinstance(x, str)]
    names = b.get('cpu-names') if isinstance(b.get('cpu-names'), dict) else None
    arches = list(names) if names else ARCHES          # cpu-names keys = the cpus upstream ships
    out = []
    for g in raw:
        if '$ARCH' in g:
            out += sorted({g.replace('$ARCH', str((names or {}).get(a, a))) for a in arches})
        else:
            out.append(g)
    return out


# -- probes -----------------------------------------------------------------

TOKEN_REMINDER = (
    'NO GITHUB TOKEN — github probes are degraded (renames/gone repos/releases/assets still work;\n'
    'archived-repo and license-change facts are SKIPPED). Fix once, it persists:\n'
    '    gh auth login        (in Claude Code: `! gh auth login`)\n'
    'compaudit then reads the token from `gh auth token` automatically — no export needed.\n'
    '(Or export CONFIGSYS_GITHUB_TOKEN / GITHUB_TOKEN.)')


def github_token():
    '''(token, source): $CONFIGSYS_GITHUB_TOKEN, $GITHUB_TOKEN, else `gh auth token` when the gh CLI
    is logged in (so a one-time `gh auth login` is all the setup there is). (None, None) if none.'''
    for var in ('CONFIGSYS_GITHUB_TOKEN', 'GITHUB_TOKEN'):
        if os.environ.get(var):
            return os.environ[var], f'${var}'
    import shutil
    import subprocess
    if shutil.which('gh'):
        try:
            r = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), 'gh auth token'
        except (OSError, subprocess.SubprocessError):
            pass
    return None, None


class Fetcher:
    '''Cached GETs with per-host concurrency limits. Returns (status, final_url, body|None).'''
    LIMITS = {'crates.io': 1, 'api.github.com': 4, 'github.com': 4}

    def __init__(self, ttl_hours=24, offline=False):
        self.dir = _cache_root() / 'http'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_hours * 3600
        self.offline = offline
        self.token, self.token_source = github_token()
        self._sems = {}
        self._lock = threading.Lock()

    def _sem(self, host):
        with self._lock:
            return self._sems.setdefault(host, threading.Semaphore(self.LIMITS.get(host, 4)))

    def get(self, url, follow=True):
        key = hashlib.sha256(f'{follow}:{url}'.encode()).hexdigest()
        cf = self.dir / f'{key}.json'
        if cf.exists() and (self.offline or time.time() - cf.stat().st_mtime < self.ttl):
            d = json.loads(cf.read_text())
            return d['status'], d['final'], d['body']
        if self.offline:
            return None, url, None
        host = urllib.parse.urlparse(url).hostname
        headers = {'User-Agent': UA}
        if self.token and host == 'api.github.com':
            headers['Authorization'] = f'Bearer {self.token}'
        with self._sem(host):
            status, final, body = self._fetch(url, headers, follow)
            if host == 'crates.io':
                time.sleep(1)                       # crates.io crawler policy: 1 req/s
        if status is not None and (status < 500 and status != 429 and status != 403):
            cf.write_text(json.dumps({'status': status, 'final': final, 'body': body}))
        return status, final, body

    @staticmethod
    def _fetch(url, headers, follow):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as r:
                return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            loc = e.headers.get('Location') if 300 <= e.code < 400 else None
            return e.code, loc or url, None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            return None, url, f'network error: {e}'



def probe_github(f, repo, assets):
    facts, findings = {'repo': repo}, []
    if f.token:
        st, _u, body = f.get(f'https://api.github.com/repos/{repo}')
        if st == 404:
            return facts, [_fd('broken', 'repo-gone', f'github repo {repo} not found (404)')]
        if st == 200 and body:
            d = json.loads(body)
            facts.update(full_name=d.get('full_name'), archived=d.get('archived'),
                         license=(d.get('license') or {}).get('spdx_id'), pushed_at=d.get('pushed_at'))
            if d.get('full_name', repo).lower() != repo.lower():
                findings.append(_fd('drift', 'repo-renamed', f'{repo} is now {d["full_name"]}',
                                    proposed=f'github: {d["full_name"]}'))
            if d.get('archived'):
                findings.append(_fd('drift', 'repo-archived', f'{repo} is archived (read-only upstream)'))
    else:
        st, loc, _b = f.get(f'https://github.com/{repo}', follow=False)
        if st == 404:
            return facts, [_fd('broken', 'repo-gone', f'github repo {repo} not found (404)')]
        if st in (301, 302) and loc:
            m = re.match(r'https://github\.com/([\w.-]+/[\w.-]+)', loc)
            if m and m.group(1).lower() != repo.lower():
                facts['full_name'] = m.group(1)
                findings.append(_fd('drift', 'repo-renamed', f'{repo} redirects to {m.group(1)}',
                                    proposed=f'github: {m.group(1)}'))
    target = facts.get('full_name') or repo
    st, loc, _b = f.get(f'https://github.com/{target}/releases/latest', follow=False)
    tag = None
    if st in (301, 302) and loc and '/releases/tag/' in loc:
        tag = urllib.parse.unquote(loc.rsplit('/releases/tag/', 1)[1])
    facts['latest_tag'] = tag
    if not assets:
        return facts, findings
    # Mirror versions._github_asset_url_live: the driver tries `latest`, then walks recent releases
    # (prereleases included) for one that carries the asset; matching is case-insensitive.
    latest = _release_assets(f, target, tag) if tag else []
    facts['latest_assets'] = latest
    pending = [a for a in assets if not _glob_hit(a['glob'], latest)]
    if pending:
        st, _u, html = f.get(f'https://github.com/{target}/releases')
        tags = []
        for t in re.findall(r'/releases/tag/([^"?#]+)"', html or ''):
            t = urllib.parse.unquote(t)
            if t != tag and t not in tags:
                tags.append(t)
        found = {}
        for t in tags[:10]:
            names = _release_assets(f, target, t)
            for a in pending:
                if a['glob'] not in found and _glob_hit(a['glob'], names):
                    found[a['glob']] = t
            if len(found) == len({a['glob'] for a in pending}):
                break
        for a in pending:
            where = found.get(a['glob'])
            if where and not tag:
                findings.append(_fd('note', 'prerelease-only',
                                    f'{a["component"]} via:{a["via"]}: {target} publishes no stable release; '
                                    f'{a["glob"]!r} resolves from prerelease {where} (rolling/nightly version)',
                                    binding=_bkey(a)))
            elif where:
                findings.append(_fd('drift', 'asset-not-in-latest',
                                    f'{a["component"]} via:{a["via"]}: latest release {tag} lacks {a["glob"]!r}; '
                                    f'the driver falls back to older release {where}', binding=_bkey(a)))
            else:
                findings.append(_fd('broken', 'asset-glob-miss',
                                    f'{a["component"]} via:{a["via"]} asset glob {a["glob"]!r} matches no asset in '
                                    f'{target}\'s recent releases' + (f' (latest {tag})' if tag else ' (no releases)'),
                                    binding=_bkey(a)))
    return facts, findings


def _release_assets(f, repo, tag):
    _st, _u, html = f.get(f'https://github.com/{repo}/releases/expanded_assets/{urllib.parse.quote(tag)}')
    return sorted({urllib.parse.unquote(n) for n in re.findall(r'/releases/download/[^"/]+/([^"?#]+)"', html or '')})


def _glob_hit(glob, names):
    '''Case-insensitive, like versions._match_release (upstreams flip Linux/linux).'''
    g = glob.lower()
    return any(fnmatch.fnmatch(n.lower(), g) for n in names)


def rebase_old_to_new(eol_rebase):
    '''Flathub's /eol/rebase is {NEW_id: [old ids it replaced]} — invert it to {old: new}.'''
    out = {}
    for new, olds in (eol_rebase or {}).items():
        for old in (olds if isinstance(olds, list) else [olds]):
            out[old] = new
    return out


def probe_flatpak(f, app, renamed_to, eol_msg):
    '''`renamed_to` = rebase_old_to_new(/eol/rebase).'''
    findings = []
    if app in renamed_to:
        new = renamed_to[app]
        findings.append(_fd('drift', 'flatpak-renamed', f'flatpak {app} is end-of-life, rebased to {new}',
                            proposed=f'app: {new}'))
    elif app in eol_msg:
        findings.append(_fd('broken', 'flatpak-eol', f'flatpak {app} is end-of-life: {eol_msg[app][:200]}'))
    st, _u, _b = f.get(f'https://flathub.org/api/v2/appstream/{app}')
    if st == 404 and not findings:
        findings.append(_fd('broken', 'flatpak-missing', f'flatpak {app} is not published on Flathub'))
    return {'app': app, 'published': st == 200}, findings


def probe_aur(f, pkgs):
    out = {}
    for i in range(0, len(pkgs), 100):
        chunk = pkgs[i:i + 100]
        q = '&'.join('arg[]=' + urllib.parse.quote(p) for p in chunk)
        st, _u, body = f.get(f'https://aur.archlinux.org/rpc/v5/info?{q}')
        res = {r['Name']: r for r in (json.loads(body).get('results', []) if st == 200 and body else [])}
        for p in chunk:
            r = res.get(p)
            fs = []
            if st == 200 and r is None:
                # the AUR deletes a package when it's promoted to Arch's official repos — then the
                # fix is `via: native`, not a new AUR name
                ast, _u, ab = f.get('https://archlinux.org/packages/search/json/?name=' + urllib.parse.quote(p))
                hits = json.loads(ab).get('results', []) if ast == 200 and ab else []
                if hits:
                    fs.append(_fd('broken', 'aur-promoted',
                                  f'AUR package {p} is gone — it is now in Arch [{hits[0]["repo"]}] '
                                  f'({hits[0]["pkgver"]})', proposed=f'{{ via: native  when: "arch" }} (pacman name {p})'))
                else:
                    fs.append(_fd('broken', 'aur-missing', f'AUR package {p} does not exist (not in Arch\'s '
                                  f'official repos either — renamed or dropped?)'))
            elif r:
                if not r.get('Maintainer'):
                    fs.append(_fd('drift', 'aur-orphaned', f'AUR package {p} is orphaned'))
                if r.get('OutOfDate'):
                    fs.append(_fd('note', 'aur-out-of-date', f'AUR package {p} is flagged out-of-date'))
            out[p] = ({'version': r.get('Version') if r else None}, fs)
    return out


def probe_brew(f, formulae):
    '''{formula: (facts, findings)} from ONE fetch of the full Homebrew formula index.'''
    st, _u, body = f.get('https://formulae.brew.sh/api/formula.json')
    if st != 200 or not body:
        return {}
    index, alias = {}, {}
    for d in json.loads(body):
        index[d['name']] = d
        for a in d.get('aliases') or []:
            alias.setdefault(a, ('alias', d['name']))
        for o in d.get('oldnames') or []:
            alias.setdefault(o, ('old name', d['name']))
    out = {}
    for p in formulae:
        d, fs = index.get(p), []
        if d is None:
            kind, real = alias.get(p, (None, None))
            if kind == 'old name':
                fs.append(_fd('drift', 'brew-renamed', f'brew formula {p} was renamed to {real}',
                              proposed=f'name: {real}'))
            elif kind == 'alias':
                # works today, but an alias can be repointed (openssl -> openssl@3 -> openssl@4)
                fs.append(_fd('note', 'brew-alias', f'brew formula {p} is an alias of {real}',
                              proposed=f'name: "{real}"'))
            else:
                fs.append(_fd('broken', 'brew-missing', f'brew formula {p} does not exist'))
            d = index.get(real) if real else None
        if d:
            if d.get('disabled'):
                fs.append(_fd('broken', 'brew-disabled', f'brew formula {d["name"]} is disabled: '
                              f'{d.get("disable_reason") or "no reason given"}'))
            elif d.get('deprecated'):
                fs.append(_fd('drift', 'brew-deprecated', f'brew formula {d["name"]} is deprecated: '
                              f'{d.get("deprecation_reason") or "no reason given"}'))
            # Homebrew ignores the macOS keg reasons on Linux (KegOnlyReason#applicable?)
            reason = (d.get('keg_only_reason') or {}).get('reason')
            if d.get('keg_only') and reason not in (':provided_by_macos', ':shadowed_by_macos'):
                fs.append(_fd('drift', 'brew-keg-only', f'brew formula {d["name"]} is keg-only on Linux '
                              f'({reason}: not linked onto PATH) — house rule: no brew binding for it'))
            files = ((d.get('bottle') or {}).get('stable') or {}).get('files') or {}
            macos = any((r.get('name') if isinstance(r, dict) else r) == 'macos'
                        for r in d.get('requirements') or [])
            if macos and not any(k.endswith('_linux') for k in files):
                fs.append(_fd('broken', 'brew-macos-only', f'brew formula {d["name"]} is macOS-only'))
        out[p] = ({'formula': p, 'latest': ((d or {}).get('versions') or {}).get('stable')}, fs)
    return out


def probe_registry(f, kind, pkg):
    url = {'crates': f'https://crates.io/api/v1/crates/{pkg}',
           'pypi': f'https://pypi.org/pypi/{pkg}/json',
           'npm': f'https://registry.npmjs.org/{urllib.parse.quote(pkg, safe="@")}'}[kind]
    st, _u, body = f.get(url)
    if st == 404:
        return {'pkg': pkg}, [_fd('broken', f'{kind}-missing', f'{kind} package {pkg} does not exist')]
    facts, fs = {'pkg': pkg}, []
    if st == 200 and body:
        d = json.loads(body)
        if kind == 'crates':
            facts['latest'] = (d.get('crate') or {}).get('max_stable_version')
            facts['repository'] = (d.get('crate') or {}).get('repository')
        elif kind == 'pypi':
            facts['latest'] = (d.get('info') or {}).get('version')
        elif kind == 'npm':
            latest = (d.get('dist-tags') or {}).get('latest')
            facts['latest'] = latest
            dep = ((d.get('versions') or {}).get(latest) or {}).get('deprecated')
            if dep:
                fs.append(_fd('drift', 'npm-deprecated', f'npm {pkg}@{latest} is deprecated: {dep[:200]}'))
    return facts, fs


def _fd(severity, category, summary, proposed=None, binding=None):
    d = {'severity': severity, 'category': category, 'summary': summary}
    if proposed:
        d['proposed'] = proposed
    if binding:
        d['binding'] = binding
    return d


def _bkey(a):
    return f'via:{a["via"]}' + (f' when:"{a["when"]}"' if a.get('when') else '')


def run_probes(units, fetcher):
    '''Attach `probe_facts` + `probe_findings` to each unit in place.'''
    _st, _u, b1 = fetcher.get('https://flathub.org/api/v2/eol/rebase')
    _st, _u, b2 = fetcher.get('https://flathub.org/api/v2/eol/message')
    eol_rebase = rebase_old_to_new(json.loads(b1) if b1 else {})
    eol_msg = json.loads(b2) if b2 else {}
    aur_all = sorted({p for u in units.values() for p in u['probes'].get('aur', [])})
    aur = probe_aur(fetcher, aur_all) if aur_all else {}
    brew_all = sorted({p for u in units.values() for p in u['probes'].get('brew', [])})
    brew = probe_brew(fetcher, brew_all) if brew_all else {}

    def one(u):
        facts, finds = {}, list(u['probes'].get('static', []))
        for repo, ent in u['probes'].get('github', {}).items():
            fa, fi = probe_github(fetcher, repo, ent['assets'])
            facts.setdefault('github', []).append(fa)
            finds += fi
        for app in u['probes'].get('flatpak', []):
            fa, fi = probe_flatpak(fetcher, app, eol_rebase, eol_msg)
            facts.setdefault('flatpak', []).append(fa)
            finds += fi
        for p in u['probes'].get('aur', []):
            fa, fi = aur.get(p, ({}, []))
            facts.setdefault('aur', []).append({'pkg': p, **fa})
            finds += fi
        for p in u['probes'].get('brew', []):
            fa, fi = brew.get(p, ({'formula': p}, []))
            facts.setdefault('brew', []).append(fa)
            finds += fi
        for kind in ('crates', 'pypi', 'npm'):
            for p in u['probes'].get(kind, []):
                fa, fi = probe_registry(fetcher, kind, p)
                facts.setdefault(kind, []).append(fa)
                finds += fi
        u['probe_facts'], u['probe_findings'] = facts, finds

    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        list(ex.map(one, units.values()))


# -- ledger -----------------------------------------------------------------

def _ledger_path():
    return _cache_root() / 'ledger.json'


def _ledger():
    try:
        return json.loads(_ledger_path().read_text())
    except (OSError, ValueError):
        return {}


def due(units, label, days):
    '''Units needing a DEEP audit: never audited, definition changed since, older than `days`, or
    a probe flagged something.'''
    led = _ledger().get(label, {})
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    for key, u in units.items():
        e = led.get(key)
        reason = ('never audited' if not e else
                  'definition changed' if e.get('def_hash') != u['def_hash'] else
                  'probe findings' if u.get('probe_findings') else
                  f'last audited {e["date"]}' if e.get('date', '') < cutoff else None)
        if reason:
            u['due_reason'] = reason
            out.append(key)
    return out


def record(label, units, names):
    led = _ledger()
    sect = led.setdefault(label, {})
    today = datetime.date.today().isoformat()
    for n in names:
        if n in units:
            sect[n] = {'date': today, 'def_hash': units[n]['def_hash']}
    _ledger_path().parent.mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(led, indent=1, sort_keys=True))
    return [n for n in names if n not in units]


# -- CLI --------------------------------------------------------------------

def _select(units, names):
    if not names:
        return units
    pick = {}
    for n in names:
        key = next((k for k, u in units.items() if n == k or n in u['components']), None)
        if key is None:
            sys.exit(f'compaudit: {n!r} is not defined in this scope')
        pick[key] = units[key]
    return pick


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('list')
    p.add_argument('scope')
    p = sub.add_parser('scan')
    p.add_argument('scope')
    p.add_argument('names', nargs='*')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--full', action='store_true', help='deep-audit every unit (ignore the ledger)')
    g.add_argument('--due-days', type=int, default=30, help='re-audit units older than N days (default 30)')
    p.add_argument('--batch-size', type=int, default=20)
    p.add_argument('--out', default=None, help='output dir (default: a fresh dir under the cache)')
    p.add_argument('--no-probe', action='store_true')
    p.add_argument('--offline', action='store_true', help='probe from cache only')
    p.add_argument('--ttl', type=float, default=24, help='probe cache TTL in hours (default 24)')
    sub.add_parser('token', help='report whether a GitHub token is available (preflight)')
    p = sub.add_parser('record')
    p.add_argument('scope')
    p.add_argument('names', nargs='+')
    a = ap.parse_args(argv)

    if a.cmd == 'token':
        tok, src = github_token()
        print(f'github token: available (from {src})' if tok else TOKEN_REMINDER)
        return 0 if tok else 1
    label, root, units = load_scope(a.scope)
    if a.cmd == 'list':
        for k, u in units.items():
            extra = [n for n in u['components'] if n != k]
            print(k + (f'  (+ {", ".join(extra)})' if extra else ''))
        return 0
    if a.cmd == 'record':
        missing = record(label, units, a.names)
        print(f'recorded {len(a.names) - len(missing)} unit(s) for {label}'
              + (f'; unknown: {", ".join(missing)}' if missing else ''))
        return 0

    units = _select(units, a.names)
    if not a.no_probe:
        f = Fetcher(a.ttl, a.offline)
        if not f.token and not a.offline:
            print('\n'.join('compaudit: ' + line for line in TOKEN_REMINDER.split('\n')) + '\n',
                  file=sys.stderr)
        run_probes(units, f)
    # explicitly-named units are always deep-audited; `*` consults the ledger
    keys = list(units) if (a.full or a.names) else due(units, label, a.due_days)
    out = Path(a.out) if a.out else _cache_root() / 'runs' / f'{label}-{datetime.datetime.now():%Y%m%d-%H%M%S}'
    out.mkdir(parents=True, exist_ok=True)
    batches = [keys[i:i + a.batch_size] for i in range(0, len(keys), a.batch_size)]
    for i, b in enumerate(batches, 1):
        (out / f'batch-{i:02d}.json').write_text(json.dumps(
            {'scope': label, 'scope_root': str(root), 'units': [units[k] for k in b]},
            indent=1, default=str))
    summary = {
        'scope': label, 'scope_root': str(root), 'units_total': len(units),
        'github_token': None if a.no_probe else (f.token_source or 'none'),
        'units_due': len(keys), 'batches': len(batches),
        'skipped_recent': sorted(set(units) - set(keys)),
        'probe_findings': {k: u['probe_findings'] for k, u in units.items() if u.get('probe_findings')},
        'due_reasons': {k: units[k].get('due_reason', 'requested') for k in keys},
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    nf = sum(len(v) for v in summary['probe_findings'].values())
    print(f'{label}: {len(units)} unit(s), {nf} probe finding(s) across '
          f'{len(summary["probe_findings"])} unit(s); {len(keys)} due for deep audit '
          f'in {len(batches)} batch(es) -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
