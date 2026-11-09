#!/usr/bin/env python3
'''osaudit — the mechanical half of the `/update-os` skill (see .claude/skills/update-os/SKILL.md).

configsys routes per OS RELEASE (`when: "fedora >= 43"`, `not (fedora >= 44)`, `fedora = 42`). The
release registry — `releases:` on the os block that owns a version line (routes.hu; docs/routing-
model.md §6) — says which releases exist and which are live. This tool checks everything else
against it, so a new release gets a systematic pass and the live older ones stay verified:

Subcommands:
  releases [LINE…] [--today D]   the registry per line + staleness (an EOL date passed while the
                                 status isn't eol; a prerelease past its release date; a versioned
                                 line with no registry; a live release with no image to sweep)
  delta LINE OLD NEW             offline: how every component's resolution differs between two
                                 releases of a line — lost / gained / changed (method or package)
  pinned [LINE…] [--all]         bindings whose `when:` bounds the line's version, with the
                                 registered releases each covers: an upper bound or an exact release
                                 that stops short of the newest live release is where a new release
                                 falls into a gap (or a deliberate retirement — read its comment)
  repos LINE RELEASE             network: probe every release-dependent source for that release —
                                 dnf/zypper `repo-url` + `pubkey-url` with $releasever, apt
                                 `source-line` with $CODENAME (or a literal codename: flagged), PPAs
  sweep LINE [RELEASE…]          podman: the native-name sweep per release (default: every live
                                 release with an image), plus what is missing on one release and
                                 present on another — the retirements to gate — and ARRIVALS: a
                                 package now in the release's repos for a component that doesn't
                                 route natively there (a gated-out native binding whose name now
                                 exists; or, lower confidence, the component's own name)
  fixtures                       the golden contexts, namesweep's releases and the Containerfile
                                 defaults, against the registry's newest live releases
  facts LINE RELEASE [--image I] podman: read a release's facts from its own image (VERSION_ID,
                                 codename, glibc, the repo's python3 / gcc, the package-manager
                                 version), compare them with the registry, print a ready entry
  snapshot LINE [RELEASE…] --out F   every component's resolution on each release (default: live)
  compare F                      what changed since a snapshot, per release — the guard that an edit
                                 for a new release left the older releases resolving as before

Every subcommand takes --json. Core routes.hu only (a plugin OS line: tools/namesweep.py --plugin).
'''

import argparse
import concurrent.futures
import datetime
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
ROUTES = str(ROOT / 'routes.hu')
CPU = 'x86_64'

LIVE = ('released', 'prerelease')

# Container-side repo setup per version LINE, run before namesweep's existence check for the line's
# manager. Kept in code, not in the registry: the registry is data any layer could carry, and a
# setup is a command. A line missing here can't be swept until it gets one.
_SETUPS = {
    'fedora': r'''
        dnf -q -y install \
          "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
          "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm" \
          >/dev/null 2>&1 || true''',
    'rhel': r'''
        dnf -q -y install epel-release dnf-plugins-core >/dev/null 2>&1 || true
        dnf config-manager --set-enabled crb >/dev/null 2>&1 \
          || dnf config-manager --set-enabled powertools >/dev/null 2>&1 || true
        dnf -q -y install \
          "https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm" \
          "https://mirrors.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-$(rpm -E %rhel).noarch.rpm" \
          >/dev/null 2>&1 || true''',
    'amzn': '',
    'ubuntu': r'''
        export DEBIAN_FRONTEND=noninteractive
        sed -i 's/^Components: main$/Components: main restricted universe multiverse/' \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        sed -i 's/ main restricted$/ main restricted universe multiverse/' /etc/apt/sources.list 2>/dev/null || true
        apt-get update -qq >/dev/null 2>&1''',
    'debian': r'''
        export DEBIAN_FRONTEND=noninteractive
        sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' \
            /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
        sed -i 's/ main$/ main contrib non-free/' /etc/apt/sources.list 2>/dev/null || true
        apt-get update -qq >/dev/null 2>&1''',
    'alpine': r'''
        ver=$(cut -d. -f1,2 /etc/alpine-release)
        echo "https://dl-cdn.alpinelinux.org/alpine/v$ver/community" >> /etc/apk/repositories
        apk update >/dev/null 2>&1''',
    'opensuse_leap': 'zypper -n --gpg-auto-import-keys ref >/dev/null 2>&1',
}


# A faster existence check than namesweep's per-name query for the managers that can list their
# whole catalog once: the setup dumps every available name to a file, the check greps it and falls
# back to the manager's own (slower) query only for a miss — virtual names, provides, groups.
_FAST_INDEX = {
    # names AND every provided capability (a miss used to cost `dnf info` + `dnf provides`, ~5 s
    # each on EL 8's modular metadata — the EL 8 sweep timed out); the slow query stays as a fallback
    'dnf': ("{ dnf -q repoquery --qf '%{name}\\n' 2>/dev/null; "
            "dnf -q repoquery --qf '%{provides}\\n' 2>/dev/null | cut -d' ' -f1; } "
            "| sort -u > /tmp/osaudit-names",
            'grep -qxF "$p" /tmp/osaudit-names'),
    'apt': ('apt-cache pkgnames 2>/dev/null | sort -u > /tmp/osaudit-names',
            'grep -qxF "$p" /tmp/osaudit-names'),
}


def _check_for(manager):
    import namesweep
    slow = namesweep._CHECK[manager]
    if manager in _FAST_INDEX:
        return _FAST_INDEX[manager][1] + ' || ' + slow
    return slow


def _setup_for(line, manager):
    setup = _SETUPS[line]
    if manager in _FAST_INDEX:
        setup = f'{setup}\n        {_FAST_INDEX[manager][0]}'
    return setup


# -- the registry -------------------------------------------------------------------------------

def load():
    from configsys import routes
    cascade, components, _mechs, _co = routes.load(ROUTES)
    return cascade, components


def _vkey(version):
    from configsys.osversion import parse_version
    return parse_version(version) or ()


def lines(cascade):
    '''{line block: {VERSION_ID: release spec}} for every block that owns a version line — every
    scale-root, plus any block that declares `releases:` with no scale-root above it.'''
    out = {}
    for block in sorted(cascade.blocks):
        if cascade.version_line(block) == block:
            out[block] = dict(sorted(cascade.releases(block).items(), key=lambda kv: _vkey(kv[0])))
    return out


def live(table):
    return [v for v, r in table.items() if (r or {}).get('status') in LIVE]


def newest_live(table, include_prerelease=False):
    statuses = LIVE if include_prerelease else ('released',)
    vs = [v for v, r in table.items() if (r or {}).get('status') in statuses]
    return max(vs, key=_vkey) if vs else None


def staleness(cascade, today, components=None):
    '''[finding] — registry entries the calendar has overtaken, and lines/releases that can't be
    swept. With `components`, also every block a `when:` compares versions on that owns no line
    (alpine before it declares `releases:`).'''
    out = []
    compared = None                     # the lines some `when:` compares versions on (with components)
    if components:
        unlined, compared = set(), set()
        for comp in components.values():
            for binding in comp.bindings:
                for atom in _versioned_atoms(binding.pred):
                    if atom.name in cascade.blocks and cascade.version_line(atom.name) is None:
                        unlined.add(atom.name)
                    elif atom.name in cascade.blocks:
                        compared.add(cascade.version_line(atom.name))
        for block in sorted(unlined):
            out.append({'line': block, 'kind': 'no-registry',
                        'message': f'{block}: `when:` compares its versions, but it has no '
                                   '`releases:` registry'})
    import namesweep
    for line, table in lines(cascade).items():
        sweepable = cascade.native(line) in namesweep._CHECK    # brew lines are compaudit's
        if not table and compared is not None and line not in compared:
            # a scale-root kept only so no parent's versioned atom misreads its VERSION_ID (kde_linux's
            # build stamp, pikaos on Debian sid): no gate reads its versions, so no registry to keep
            out.append({'line': line, 'kind': 'unversioned',
                        'message': f'{line}: no `when:` compares its versions — no registry needed'})
            continue
        if not table:
            out.append({'line': line, 'kind': 'no-registry',
                        'message': f'{line}: a versioned line with no `releases:` registry'})
            continue
        for version, rel in table.items():
            status = rel.get('status')
            eol = rel.get('eol')
            released = rel.get('released')
            if status != 'eol' and eol and str(eol) < today:
                out.append({'line': line, 'release': version, 'kind': 'eol-passed',
                            'message': f'{line} {version}: EOL {eol} has passed — mark it `status: eol`'})
            if status == 'prerelease' and released and str(released) <= today:
                out.append({'line': line, 'release': version, 'kind': 'prerelease-past-ga',
                            'message': f'{line} {version}: still `prerelease` after its release date '
                                       f'{released} — recheck at GA and mark it released'})
            if status in LIVE and not rel.get('image') and sweepable:
                out.append({'line': line, 'release': version, 'kind': 'no-image',
                            'message': f'{line} {version}: live but no `image:` — the sweeps skip it'})
    return out


# -- delta: resolution between two releases -----------------------------------------------------

def _resolve_all(block, version):
    from configsys.resolve import ResolveError
    from configsys.routes import Resolver
    r = Resolver(ROUTES, block, version, CPU)
    out = {}
    for name in sorted(r.components):
        try:
            units = r.resolve_names([name])
        except ResolveError:
            continue
        out[name] = {k: (rc.driver, rc.name, rc.fields.get('packages'), _digest(rc.fields))
                     for k, rc in units.items()}
    return out


def _digest(fields):
    '''A short stable digest of a unit's fields, so a changed repo URL or key shows up in a
    compare even when the package name doesn't move.'''
    import hashlib
    text = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _brief(units, other=None):
    '''driver:name [packages] per unit; `~fields` marks a unit whose fields differ from the same
    unit in `other` (the side it is being compared with).'''
    parts = []
    for key, unit in sorted(units.items()):
        driver, name, packages = unit[0], unit[1], unit[2]
        pk = f" [{' '.join(packages)}]" if isinstance(packages, (list, tuple)) else ''
        mark = ''
        if other and key in other and other[key][:3] == unit[:3] and other[key] != unit:
            mark = ' ~fields'
        parts.append(f'{driver}:{name}{pk}{mark}')
    return ', '.join(parts)


def _own(units, name):
    '''The units that are `name` itself (key `driver\\name`), not what it pulls in.'''
    return {k: v for k, v in units.items() if k.split('\\', 1)[-1] == name}


def diff_resolved(a, b):
    '''{lost, gained, changed, follows} between two {component: units} maps: per component, how
    its OWN unit differs; a component that differs only through what it requires is folded into
    `follows` under the dependency that changed, so one retired jdk doesn't read as 25 changes.'''
    lost = {n: _brief(a[n]) for n in sorted(set(a) - set(b))}
    gained = {n: _brief(b[n]) for n in sorted(set(b) - set(a))}
    changed, follows = {}, {}
    for n in sorted(set(a) & set(b)):
        if a[n] == b[n]:
            continue
        own_a, own_b = _own(a[n], n), _own(b[n], n)
        if own_a != own_b:
            changed[n] = {'old': _brief(own_a, own_b), 'new': _brief(own_b, own_a)}
            continue
        moved = sorted({k.split('\\', 1)[-1] for k in set(a[n]) ^ set(b[n])} |
                       {k.split('\\', 1)[-1] for k in set(a[n]) & set(b[n]) if a[n][k] != b[n][k]})
        for dep in moved:
            follows.setdefault(dep, []).append(n)
    return {'lost': lost, 'gained': gained, 'changed': changed, 'follows': follows}


def delta(block, old, new):
    return dict({'line': block, 'old': old, 'new': new},
                **diff_resolved(_resolve_all(block, old), _resolve_all(block, new)))


def snapshot(cascade, line, releases_wanted=None):
    table = cascade.releases(line)
    targets = releases_wanted or live(table)
    return {'line': line, 'releases': {v: {n: {k: list(u) for k, u in units.items()}
                                           for n, units in _resolve_all(line, v).items()}
                                       for v in targets}}


def compare(snap):
    def tup(units):
        return {k: (u[0], u[1], tuple(u[2]) if isinstance(u[2], list) else u[2],
                    u[3] if len(u) > 3 else None)
                for k, u in units.items()}
    out = {}
    for version, before in snap['releases'].items():
        old = {n: tup(units) for n, units in before.items()}
        now = {n: tup({k: list(u) for k, u in units.items()})
               for n, units in _resolve_all(snap['line'], version).items()}
        if any(u[3] is None for units in old.values() for u in units.values()):
            # a snapshot from before fields were recorded: compare names and packages only
            now = {n: {k: u[:3] + (None,) for k, u in units.items()} for n, units in now.items()}
        out[version] = diff_resolved(old, now)
    return {'line': snap['line'], 'releases': out}


# -- pinned: version-bounded bindings -----------------------------------------------------------

def _versioned_atoms(pred):
    from configsys import predicate
    out = []

    def walk(p):
        if isinstance(p, predicate.Os):
            if p.op is not None:
                out.append(p)
        elif isinstance(p, predicate.Not):
            walk(p.term)
        elif isinstance(p, (predicate.And, predicate.Or)):
            for t in p.terms:
                walk(t)
    if pred is not None:
        walk(pred)
    return out


def pinned(cascade, components, only_lines=None, show_all=False):
    '''[finding] for each binding whose `when:` carries a versioned atom on a registered line.'''
    registry = lines(cascade)
    out = []
    for comp_name, comp in sorted(components.items()):
        for index, binding in enumerate(comp.bindings):
            atoms = _versioned_atoms(binding.pred)
            by_line = {}
            for atom in atoms:
                if atom.name in cascade.blocks:
                    line = cascade.version_line(atom.name)
                    if line in registry and (not only_lines or line in only_lines):
                        by_line.setdefault(line, []).append(atom)
            for line, line_atoms in sorted(by_line.items()):
                table = registry[line]
                if not table:
                    continue
                covered = [v for v in table
                           if binding.pred.eval(cascade.context(line, v, CPU))]
                live_vs = live(table)
                newest = newest_live(table, include_prerelease=True)
                exact = any(a.op == '=' for a in line_atoms)
                upper = any(a.op in ('<', '<=', '=') for a in line_atoms) or \
                    (bool(covered) and newest not in covered)
                if not covered or not any(v in live_vs for v in covered):
                    kind = 'no-live-release'
                elif newest not in covered and upper:
                    kind = 'stops-short'
                elif exact:
                    kind = 'exact'
                else:
                    kind = 'from'
                if kind == 'from' and not show_all:
                    continue
                out.append({'component': comp_name, 'binding': index, 'via': binding.via,
                            'when': binding.when, 'line': line, 'kind': kind, 'exact': exact,
                            'covers': covered, 'newest': newest, 'source': comp.source})
    out.extend(_exact_gaps(out, registry))
    return out


def _exact_gaps(findings, registry):
    '''A component pinned per release (`fedora = 41`, `fedora = 42` …) with no binding for the
    newest live release while the one before it had one — the release-pin gap.'''
    gaps = []
    per = {}
    for f in findings:
        if f.get('exact'):
            per.setdefault((f['component'], f['line']), set()).update(f['covers'])
    for (comp, line), covered in sorted(per.items()):
        table = registry[line]
        ordered = sorted(live(table), key=_vkey)
        if len(ordered) < 2:
            continue
        newest, previous = ordered[-1], ordered[-2]
        # pinned for the release before the newest but not the newest — or pinned only for releases
        # that have all gone EOL, so no live release gets one
        if newest not in covered and (previous in covered or not set(covered) & set(ordered)):
            gaps.append({'component': comp, 'line': line, 'kind': 'release-pin-gap',
                         'covers': sorted(covered, key=_vkey), 'newest': newest,
                         'when': None, 'via': None, 'binding': None, 'source': None})
    return gaps


# -- repos: release-dependent sources -----------------------------------------------------------

_DEB_LINE = re.compile(r'^\s*deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?(\S+)\s+(\S+)')


def _codenames(table):
    return {str(r.get('codename')) for r in table.values() if r.get('codename')}


def _release_sources(cascade, components, line, release):
    '''[(component, kind, url, note)] for every source of a binding valid on LINE RELEASE whose
    URL depends on the release.'''
    table = cascade.releases(line)
    rel = table.get(release) or {}
    codename = rel.get('codename')
    major = str(release).split('.')[0]
    releasever = major if line == 'rhel' else str(release)
    others = _codenames(table) - {str(codename)}
    ctx = cascade.context(line, release, CPU)
    out = []
    for comp_name, comp in sorted(components.items()):
        for binding in comp.bindings:
            if binding.pred is not None and not binding.pred.eval(ctx):
                continue
            d = binding.details
            for key in ('repo-url', 'pubkey-url'):
                url = d.get(key)
                if isinstance(url, str) and '$releasever' in url:
                    url = url.replace('$releasever', releasever).replace('$basearch', CPU)
                    if key == 'repo-url':
                        url = url.rstrip('/') + '/repodata/repomd.xml'
                    out.append((comp_name, key, url, None))
            line_text = d.get('source-line')
            if isinstance(line_text, str):
                literal = sorted(c for c in others if re.search(rf'\b{re.escape(c)}\b', line_text))
                if literal:
                    out.append((comp_name, 'literal-codename', None,
                                f"source-line names {', '.join(literal)} literally — on {line} "
                                f'{release} ({codename}) that is another release'))
                if '$CODENAME' in line_text and codename:
                    m = _DEB_LINE.match(line_text.replace('$CODENAME', str(codename)))
                    if m and not m.group(2).endswith('/') and m.group(2) != '*':
                        out.append((comp_name, 'source-line',
                                    f'{m.group(1).rstrip("/")}/dists/{m.group(2)}/Release', None))
            ppa = d.get('ppa')
            if isinstance(ppa, str) and '/' in ppa and codename:
                owner, name = ppa.split('/', 1)
                out.append((comp_name, 'ppa', f'https://ppa.launchpadcontent.net/{owner}/{name}/'
                            f'ubuntu/dists/{codename}/Release', None))
    return out


def _probe(url, timeout=20):
    req = urllib.request.Request(url, method='GET', headers={'User-Agent': 'configsys-osaudit'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:   # noqa: BLE001 — a probe reports, never raises
        return None, f'{type(e).__name__}: {e}'


def repos(cascade, components, line, release):
    sources = _release_sources(cascade, components, line, release)
    probes = [s for s in sources if s[2]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: _probe(s[2]), probes))
    out = []
    for (comp, kind, url, _n), (status, err) in zip(probes, results):
        out.append({'component': comp, 'kind': kind, 'url': url, 'status': status, 'error': err,
                    'ok': status == 200})
    for comp, kind, _url, note in sources:
        if note:
            out.append({'component': comp, 'kind': kind, 'url': None, 'status': None,
                        'error': note, 'ok': False})
    return out


# -- sweep: native names per release ------------------------------------------------------------

def sweep(cascade, line, releases_wanted=None):
    import namesweep
    table = cascade.releases(line)
    manager = cascade.native(line)
    if manager not in namesweep._CHECK:
        return {'error': f'{line}: native manager {manager!r} has no container check '
                         f'({namesweep.UNSWEPT.get(manager, "not sweepable")})'}
    if line not in _SETUPS:
        return {'error': f'{line}: no repo setup in osaudit._SETUPS — add one to sweep this line'}
    if not shutil.which('podman'):
        return {'error': 'podman not found'}
    targets = releases_wanted or [v for v in live(table) if table[v].get('image')]
    allow = namesweep._load_allowlist().get(manager, set())
    per_release, names_by_release = {}, {}
    for version in targets:
        image = (table.get(version) or {}).get('image')
        if not image:
            per_release[version] = {'error': 'no image in the registry'}
            continue
        names = release_names(line, version, manager)
        names_by_release[version] = names
        candidates = arrival_candidates(line, version, manager)
        query = sorted(set(names) | set(candidates))
        print(f'>> {line} {version}: {len(names)} {manager} packages + {len(candidates)} arrival '
              f'candidates in {image}', file=sys.stderr)
        try:
            missing, _rc = namesweep._run_verifier(
                image, namesweep._build_snippet(_setup_for(line, manager), _check_for(manager)), query)
        except subprocess.TimeoutExpired:
            per_release[version] = {'error': 'verifier timed out'}
            continue
        absent = set(missing)
        # a name-only guess must be an exact package name: the slow fallback (`dnf provides`,
        # `apt-cache show`) also matches files and virtual names (`clang-18` -> /usr/bin/clang-18)
        guesses = sorted(p for p, c in candidates.items()
                         if c['confidence'] == 'name-only' and p not in absent)
        if guesses and manager in _FAST_INDEX:
            exact_check = _FAST_INDEX[manager][1]
            not_exact, _rc = namesweep._run_verifier(
                image, namesweep._build_snippet(_setup_for(line, manager), exact_check), guesses)
            absent |= set(not_exact)
        per_release[version] = {
            'image': image, 'checked': len(names),
            'missing': {p: names[p] for p in missing if p in names and p not in allow},
            'allowlisted': sorted(p for p in missing if p in names and p in allow),
            'arrivals': {p: c for p, c in sorted(candidates.items()) if p not in absent},
        }
    # a name missing on one swept release and present on another is a release boundary to gate
    boundaries = {}
    swept = [v for v in targets if 'missing' in per_release.get(v, {})]
    for version in swept:
        for pkg, comps in per_release[version]['missing'].items():
            present = [v for v in swept if v != version and pkg in names_by_release[v]
                       and pkg not in per_release[v]['missing']]
            if present:
                boundaries.setdefault(pkg, {'components': comps, 'missing_on': [],
                                            'present_on': sorted(present, key=_vkey)})
                boundaries[pkg]['missing_on'].append(version)
    return {'line': line, 'manager': manager, 'releases': per_release, 'boundaries': boundaries}


# vias that install no distro-packageable software of their own (companions, bundles)
_NOT_PACKAGES = frozenset({'dotfiles', 'glue', 'service', 'group', 'parts'})


# drivers that install a binding's `packages:` through the OS package manager (parallel toolchains)
_NATIVE_BACKED = ('gcc', 'clang', 'gcc-toolset')


def _vendor_sourced(rc):
    from configsys.drivers import get_driver
    from configsys.runner import Runner
    if rc.fields.get('ppa') or rc.fields.get('apt-source'):
        return True
    drv = get_driver(rc.driver, Runner(pretend=True), None)
    return bool(getattr(drv, 'default_source', None))


def release_names(line, version, manager):
    '''{package: [components]} to check on one release: namesweep's native names, plus the
    `packages:` of units whose driver installs through the native manager (gcc / clang /
    gcc-toolset) — namesweep keys on the manager's own driver, so it never sees those.'''
    import namesweep
    from configsys.resolve import ResolveError
    from configsys.routes import Resolver
    names = {p: list(c) for p, c in namesweep._native_names(line, version, manager).items()}
    r = Resolver(ROUTES, line, version, CPU)
    for comp in sorted(r.components):
        try:
            units = r.resolve_names([comp])
        except ResolveError:
            continue
        for rc in units.values():
            if rc.driver in _NATIVE_BACKED:
                # a toolchain the driver installs from a VENDOR apt source when the distro lacks it
                # (a `ppa:` — ubuntu-toolchain-r — or clang's apt.llvm.org default) isn't a base-repo
                # name: its absence here is the expected case, not a gap
                if manager == 'apt' and _vendor_sourced(rc):
                    continue
                for pkg in rc.fields.get('packages') or []:
                    if comp not in names.setdefault(pkg, []):
                        names[pkg].append(comp)
    return names


def arrival_candidates(line, version, manager):
    '''{package: {components, confidence, when}} — names to look for in a release's repos for
    components that do NOT route natively there: a native (or `via: <manager>`) binding whose
    `when:` excludes this release by a version bound on this line ("release-gated"), or that names
    a package for this manager but is gated off this family ("named") — high confidence, the name
    is the binding's own — or
    — for a component that doesn't route here at all and has no native binding — the component's
    own name ("name-only", low confidence: the package may be something else entirely) — for
    one installed by a fallback (cargo, tarball, flatpak, …) or not routable here at all.'''
    import namesweep
    from configsys.resolve import ResolveError, _package
    from configsys.routes import Resolver
    r = Resolver(ROUTES, line, version, CPU)
    ctx = r.cascade.context(line, version, CPU)
    out = {}
    for name, comp in sorted(r.components.items()):
        try:
            units = r.resolve_names([name])
        except ResolveError:
            units = None
        if units and any(k == f'{manager}\\{name}' for k in units):
            continue                                          # already native here
        native = [b for b in comp.bindings if b.via in ('native', manager)
                  and not (namesweep._NON_REPO_FIELDS & set(b.details))]
        for b in native:
            if b.pred is not None and b.pred.eval(ctx):
                continue                                      # valid here, lost for another reason
            on_line = any(a.name in r.cascade.blocks and r.cascade.version_line(a.name) == line
                          for a in _versioned_atoms(b.pred))
            named = isinstance(b.details.get('name'), dict) and manager in b.details['name']
            if not (on_line or named):
                continue                  # gated to another family: its name isn't this manager's
            pkg = _package(b, manager, comp)
            if isinstance(pkg, str) and pkg:
                entry = out.setdefault(pkg, {'components': [],
                                             'confidence': 'release-gated' if on_line else 'named',
                                             'when': b.when})
                entry['components'].append(name)
        if not native and any(b.via not in _NOT_PACKAGES for b in comp.bindings):
            entry = out.setdefault(name, {'components': [], 'confidence': 'name-only',
                                          'when': None})
            entry['components'].append(name)
    return out


# -- facts: read a release from its own image ---------------------------------------------------

_FACTS_COMMON = r'''
. /etc/os-release 2>/dev/null
echo "version_id=$VERSION_ID"
echo "codename=${UBUNTU_CODENAME:-$VERSION_CODENAME}"
echo "glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null | cut -d' ' -f2)"
'''
_FACTS = {
    'dnf': r'''
echo "manager=$( (dnf --version 2>/dev/null || true) | head -1)"
for p in python3 gcc; do echo "$p=$(dnf -q info "$p" 2>/dev/null | sed -n 's/^Version *: *//p' | head -1)"; done''',
    'apt': r'''
export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null 2>&1
echo "manager=$(apt --version 2>/dev/null | head -1)"
for p in python3 gcc; do echo "$p=$(apt-cache policy "$p" 2>/dev/null | sed -n 's/ *Candidate: *//p' | sed 's/^[0-9]*://')"; done''',
    'apk': r'''
apk update >/dev/null 2>&1
echo "manager=$(apk --version 2>/dev/null | head -1)"
for p in python3 gcc; do echo "$p=$(apk search -x "$p" 2>/dev/null | head -1 | sed "s/^$p-//")"; done''',
    'zypper': r'''
zypper -n --gpg-auto-import-keys ref >/dev/null 2>&1
echo "manager=$(zypper --version 2>/dev/null | head -1)"
for p in python3 gcc; do echo "$p=$(zypper -n info "$p" 2>/dev/null | sed -n 's/^Version *: *//p' | head -1)"; done''',
}


def _leading(version, parts):
    m = re.match(r'(\d+(?:\.\d+){0,%d})' % (parts - 1), str(version or ''))
    return m.group(1) if m else None


def parse_facts(text):
    '''The facts snippet's key=value lines -> registry-shaped fields (python3 as major.minor,
    gcc as its major, glibc as printed).'''
    raw = {}
    for line in text.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            raw[k.strip()] = v.strip()
    out = {k: raw[k] for k in ('version_id', 'codename', 'glibc', 'manager') if raw.get(k)}
    if _leading(raw.get('python3'), 2):
        out['python3'] = _leading(raw.get('python3'), 2)
    if _leading(raw.get('gcc'), 1):
        out['gcc'] = _leading(raw.get('gcc'), 1)
    return out


def facts(cascade, line, release, image=None):
    manager = cascade.native(line)
    rel = cascade.releases(line).get(release) or {}
    image = image or rel.get('image')
    if manager not in _FACTS:
        return {'error': f'{line}: no facts snippet for manager {manager!r}'}
    if not image:
        return {'error': f'{line} {release}: no image — pass --image'}
    if not shutil.which('podman'):
        return {'error': 'podman not found'}
    proc = subprocess.run(['podman', 'run', '--rm', '-i', image, 'sh', '-s'],
                          input=_FACTS_COMMON + _FACTS[manager], capture_output=True, text=True,
                          timeout=900)
    found = parse_facts(proc.stdout)
    mismatches = []
    if found.get('version_id') and found['version_id'] != str(release) and \
            not found['version_id'].startswith(str(release) + '.'):
        mismatches.append(f"the image reports VERSION_ID {found['version_id']}, not {release}")
    for key in ('codename', 'glibc', 'python3', 'gcc', 'manager'):
        if key in rel and key in found and str(rel[key]) != found[key]:
            mismatches.append(f'{key}: registry {rel[key]!r}, image {found[key]!r}')
    entry = {'status': rel.get('status', 'prerelease'), 'image': image}
    entry.update({k: v for k, v in found.items() if k != 'version_id'})
    for key in ('released', 'eol', 'note'):
        if key in rel:
            entry[key] = rel[key]
    return {'line': line, 'release': release, 'image': image, 'found': found,
            'mismatches': mismatches, 'entry': _humon_entry(release, entry),
            'stderr': proc.stderr[-2000:] if proc.returncode else ''}


def _humon_entry(release, entry):
    order = ('status', 'released', 'eol', 'codename', 'image', 'glibc', 'python3', 'gcc', 'manager',
             'note')

    def val(v):
        v = str(v)
        return v if re.fullmatch(r'[\w.\-]+', v) and not v.startswith('-') else json.dumps(v)
    body = '  '.join(f'{k}: {val(entry[k])}' for k in order if entry.get(k))
    return f'{release}: {{ {body} }}'


# -- fixtures: tests and containers against the registry ----------------------------------------

def fixtures(cascade):
    import namesweep
    registry = lines(cascade)
    out = []
    golden = (ROOT / 'test' / 'test_golden.py').read_text(encoding='utf-8')
    block = golden[golden.index('CONTEXTS'):golden.index(']', golden.index('CONTEXTS')) + 1]
    contexts = re.findall(r"\('([^']+)',\s*(?:'([^']*)'|None)\)", block)
    in_golden = {}
    for name, version in contexts:
        line = cascade.version_line(name)
        if line and version:
            in_golden.setdefault(line, set()).add(version)
    for line, versions in sorted(in_golden.items()):
        table = registry.get(line) or {}
        newest = newest_live(table)
        for v in sorted(versions, key=_vkey):
            if table and v not in table and not any(v.startswith(k + '.') for k in table):
                out.append({'fixture': 'test/test_golden.py CONTEXTS', 'line': line,
                            'message': f'{line} {v} is not in the registry'})
        if newest and newest not in versions and not any(v.startswith(newest + '.') for v in versions):
            out.append({'fixture': 'test/test_golden.py CONTEXTS', 'line': line,
                        'message': f'{line}: newest released {newest} has no golden context '
                                   f"(has {', '.join(sorted(versions, key=_vkey))})"})
    for manager, block_name, version in namesweep.MANAGERS:
        line = cascade.version_line(block_name)
        newest = newest_live(registry.get(line) or {}) if line else None
        if newest and version and version != newest:
            out.append({'fixture': 'tools/namesweep.py MANAGERS', 'line': line,
                        'message': f'{manager} sweeps {block_name} {version}; newest released is '
                                   f'{newest} (osaudit sweep covers every live release)'})
    for path in sorted((ROOT / 'test').glob('Containerfile*')):
        text = path.read_text(encoding='utf-8')
        for m in re.finditer(r'^(?:ARG\s+(\w+)=(\S+)|FROM\s+(\S+))', text, re.M):
            ref = m.group(2) or m.group(3)
            out.append({'fixture': str(path.relative_to(ROOT)), 'line': None,
                        'message': f"base: {m.group(1) + '=' if m.group(1) else 'FROM '}{ref}",
                        'info': True})
    return out


# -- CLI ----------------------------------------------------------------------------------------

def _emit(data, as_json, render):
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=False))
    else:
        render(data)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='osaudit', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('releases')
    p.add_argument('lines', nargs='*')
    p.add_argument('--today', default=datetime.date.today().isoformat())
    p = sub.add_parser('delta')
    p.add_argument('line')
    p.add_argument('old')
    p.add_argument('new')
    p = sub.add_parser('pinned')
    p.add_argument('lines', nargs='*')
    p.add_argument('--all', action='store_true', help='also list plain lower bounds (`>= N`)')
    p = sub.add_parser('repos')
    p.add_argument('line')
    p.add_argument('release')
    p = sub.add_parser('sweep')
    p.add_argument('line')
    p.add_argument('releases', nargs='*')
    sub.add_parser('fixtures')
    p = sub.add_parser('facts')
    p.add_argument('line')
    p.add_argument('release')
    p.add_argument('--image', help='an image to read instead of the registry entry\'s')
    p = sub.add_parser('snapshot')
    p.add_argument('line')
    p.add_argument('releases', nargs='*')
    p.add_argument('--out', required=True)
    p = sub.add_parser('compare')
    p.add_argument('snapshot')
    for sp in sub.choices.values():
        sp.add_argument('--json', action='store_true')
        sp.add_argument('--routes', help='a routes.hu to read instead of the repo\'s (e.g. a '
                        'snapshot of HEAD: `git show HEAD:routes.hu > F`)')
    args = parser.parse_args(argv)
    if args.routes:
        global ROUTES
        ROUTES = str(Path(args.routes).resolve())

    cascade, components = load()

    if args.cmd == 'releases':
        registry = {k: v for k, v in lines(cascade).items() if not args.lines or k in args.lines}
        stale = [f for f in staleness(cascade, args.today, components)
                 if not args.lines or f['line'] in args.lines]

        def render(_d):
            for line, table in registry.items():
                print(f'{line}:' + ('' if table else '  (no registry)'))
                for version, rel in table.items():
                    facts = '  '.join(f'{k}={rel[k]}' for k in rel if k != 'status')
                    print(f"  {version:8} {rel.get('status', '?'):10} {facts}")
            imageless = {}                       # one line per line: a derivative has no images at all
            for f in stale:
                if f['kind'] == 'no-image':
                    imageless.setdefault(f['line'], []).append(f['release'])
                    continue
                print(f"{'·' if f['kind'] == 'unversioned' else '!'} {f['message']}")
            for line, rels in imageless.items():
                print(f"! {line} {', '.join(rels)}: live but no `image:` — the sweeps skip "
                      + ('them' if len(rels) > 1 else 'it'))
        _emit({'lines': registry, 'stale': stale}, args.json, render)
        return 0

    if args.cmd == 'delta':
        data = delta(args.line, args.old, args.new)

        def render(d):
            print(f"{d['line']} {d['old']} -> {d['new']}: {len(d['lost'])} lost, "
                  f"{len(d['gained'])} gained, {len(d['changed'])} changed, "
                  f"{sum(len(v) for v in d['follows'].values())} following a dependency")
            for n, units in d['lost'].items():
                print(f'  lost     {n}: {units}')
            for n, units in d['gained'].items():
                print(f'  gained   {n}: {units}')
            for n, ch in d['changed'].items():
                print(f"  changed  {n}: {ch['old'] or '(nothing of its own)'}  ->  "
                      f"{ch['new'] or '(nothing of its own)'}")
            for dep, comps in sorted(d['follows'].items()):
                print(f"  follows  {dep}: {len(comps)} component(s) change only through it "
                      f"({', '.join(comps[:6])}{' …' if len(comps) > 6 else ''})")
        _emit(data, args.json, render)
        return 0

    if args.cmd == 'pinned':
        data = pinned(cascade, components, set(args.lines) or None, args.all)

        def render(d):
            for f in d:
                covers = ', '.join(f['covers']) or 'none'
                where = f" via:{f['via']} when:\"{f['when']}\"" if f['when'] else ''
                print(f"{f['kind']:16} {f['line']:10} {f['component']}{where}  covers {covers}"
                      f"  (newest {f['newest']})")
        _emit(data, args.json, render)
        return 0

    if args.cmd == 'repos':
        data = repos(cascade, components, args.line, args.release)

        def render(d):
            for f in d:
                state = 'ok ' if f['ok'] else 'BAD'
                detail = f['url'] or ''
                extra = f" ({f['status'] or f['error']})" if not f['ok'] else ''
                print(f"{state} {f['kind']:16} {f['component']}: {detail}{extra}")
            bad = sum(1 for f in d if not f['ok'])
            print(f'\n{len(d)} release-dependent sources, {bad} not OK')
        _emit(data, args.json, render)
        return 1 if any(not f['ok'] for f in data) else 0

    if args.cmd == 'sweep':
        data = sweep(cascade, args.line, args.releases or None)

        def render(d):
            if 'error' in d:
                print(d['error'])
                return
            for version, res in d['releases'].items():
                if 'error' in res:
                    print(f'{version}: {res["error"]}')
                    continue
                print(f"{version}: {res['checked']} checked in {res['image']}, "
                      f"{len(res['missing'])} missing")
                for pkg, comps in sorted(res['missing'].items()):
                    print(f"  missing  {pkg}  ({', '.join(comps)})")
                for pkg, a in res.get('arrivals', {}).items():
                    when = f" (binding when: \"{a['when']}\")" if a['when'] else ''
                    print(f"  arrival  {pkg}  {a['confidence']}: {', '.join(a['components'])}{when}")
            for pkg, b in sorted(d['boundaries'].items()):
                print(f"boundary {pkg}: missing on {', '.join(b['missing_on'])}, present on "
                      f"{', '.join(b['present_on'])}  ({', '.join(b['components'])})")
        _emit(data, args.json, render)
        if 'error' in data:
            return 2
        return 1 if any(r.get('missing') for r in data['releases'].values()) else 0

    if args.cmd == 'facts':
        data = facts(cascade, args.line, args.release, args.image)

        def render(d):
            if 'error' in d:
                print(d['error'])
                return
            for k, v in d['found'].items():
                print(f'  {k:10} {v}')
            for m in d['mismatches']:
                print(f'! {m}')
            print(f"\nregistry entry for {d['line']}:\n    {d['entry']}")
            if d['stderr']:
                print(f"\n(podman stderr)\n{d['stderr']}")
        _emit(data, args.json, render)
        return 2 if 'error' in data else (1 if data['mismatches'] else 0)

    if args.cmd == 'snapshot':
        data = snapshot(cascade, args.line, args.releases or None)
        Path(args.out).write_text(json.dumps(data), encoding='utf-8')
        print(f"snapshot: {args.line} {', '.join(data['releases'])} -> {args.out}")
        return 0

    if args.cmd == 'compare':
        data = compare(json.loads(Path(args.snapshot).read_text(encoding='utf-8')))

        def render(d):
            for version, diff in d['releases'].items():
                n = len(diff['lost']) + len(diff['gained']) + len(diff['changed'])
                print(f"{d['line']} {version}: {'unchanged' if not n else f'{n} changed'}")
                for k in ('lost', 'gained'):
                    for name, units in diff[k].items():
                        print(f'  {k:8} {name}: {units}')
                for name, ch in diff['changed'].items():
                    print(f"  changed  {name}: {ch['old']}  ->  {ch['new']}")
        _emit(data, args.json, render)
        return 1 if any(d['lost'] or d['gained'] or d['changed']
                        for d in data['releases'].values()) else 0

    if args.cmd == 'fixtures':
        data = fixtures(cascade)

        def render(d):
            for f in d:
                print(f"{'info' if f.get('info') else 'stale'}  {f['fixture']}: {f['message']}")
        _emit(data, args.json, render)
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
