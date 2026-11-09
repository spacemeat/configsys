#!/usr/bin/env python3
'''reviewaudit — the mechanical half of the `/review-code` skill (see
.claude/skills/review-code/SKILL.md).

A full code review splits the tree into AREAS, one reviewer each. The split lives in
.claude/skills/review-code/areas.hu; this tool keeps it honest and answers the questions the skill
asks before it fans out, so no agent has to re-derive them:

Subcommands:
  areas     [--json]               every area: title, owned files (resolved), line count, context,
                                   focus, inherited earlier review files
  coverage  [--json]               tracked files under `track:` that no non-cross area owns, globs that
                                   match nothing, context paths that don't exist (exit 1 if any),
                                   plus files several areas own (listed, not an error)
  since     REF [--json]           the areas whose owned files changed between REF and HEAD (cross
                                   areas always run)
  prior     [--before DIR] [--json]
                                   the latest earlier review (docs/review-*/): its directory, baseline
                                   commit, and for each area the earlier review files it inherits

Globs: `*` stays inside one path segment, `**` crosses segments.
'''

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AREAS_FILE = ROOT / '.claude' / 'skills' / 'review-code' / 'areas.hu'
REVIEW_GLOB = 'review-*'


def _as_list(value):
    return [] if value is None else ([value] if isinstance(value, str) else list(value))


def load_map(path=AREAS_FILE):
    '''The area map as plain python: {'track': [...], 'areas': {key: {...}}}.'''
    from configsys import layers
    data = layers.materialize_string(Path(path).read_text(encoding='utf-8')) or {}
    areas = data.get('areas') or {}
    for spec in areas.values():
        for field in ('files', 'context', 'focus', 'was'):
            spec[field] = _as_list(spec.get(field))
        spec['cross'] = str(spec.get('cross', 'false')).lower() == 'true'
    return {'track': _as_list(data.get('track')), 'areas': areas}


def glob_regex(glob):
    '''A repo-relative glob as a compiled regex: `**` crosses `/`, `*` and `?` don't.'''
    out, i = [], 0
    while i < len(glob):
        if glob.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif glob.startswith('**', i):
            out.append('.*')
            i += 2
        elif glob[i] == '*':
            out.append('[^/]*')
            i += 1
        elif glob[i] == '?':
            out.append('[^/]')
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile(''.join(out) + r'\Z')


def tracked_files(root=ROOT):
    '''Every file git tracks, repo-relative.'''
    out = subprocess.run(['git', '-C', str(root), 'ls-files'], capture_output=True, text=True,
                         check=True).stdout
    return [line for line in out.splitlines() if line]


def matching(globs, files):
    regexes = [glob_regex(g) for g in globs]
    return [f for f in files if any(r.match(f) for r in regexes)]


def line_count(path):
    '''Lines of a reviewable file; data dumps (`.json`, e.g. the routing golden) count as 0.'''
    if str(path).endswith('.json'):
        return 0
    try:
        with open(path, 'rb') as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def resolve_areas(amap, files, root=ROOT):
    '''{key: spec + resolved `owned` file list + `lines`}.'''
    out = {}
    for key, spec in amap['areas'].items():
        owned = [] if spec['cross'] else matching(spec['files'], files)
        out[key] = dict(spec, owned=owned, lines=sum(line_count(root / f) for f in owned))
    return out


def coverage(amap, files, root=ROOT):
    '''Gaps in the map: unowned tracked files, owned-by-several files, dead globs, missing context.'''
    tracked = matching(amap['track'], files)
    owners = {}
    dead_globs, missing_context = [], []
    for key, spec in amap['areas'].items():
        for glob in spec['files']:
            hits = matching([glob], files)
            if not hits:
                dead_globs.append({'area': key, 'glob': glob})
            if not spec['cross']:
                for f in hits:
                    owners.setdefault(f, []).append(key)
        for ctx in spec['context']:
            if not matching([ctx], files) and not (root / ctx).exists():
                missing_context.append({'area': key, 'path': ctx})
    return {
        'unowned': sorted(f for f in tracked if f not in owners),
        'shared': {f: keys for f, keys in sorted(owners.items()) if len(keys) > 1},
        'dead_globs': dead_globs,
        'missing_context': missing_context,
    }


def changed_since(ref, root=ROOT):
    out = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', f'{ref}..HEAD'],
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def areas_since(amap, ref, root=ROOT):
    '''{key: [changed owned files]} for areas touched since REF; cross areas always listed.'''
    changed = changed_since(ref, root)
    out = {}
    for key, spec in amap['areas'].items():
        if spec['cross']:
            out[key] = ['(cross-cutting: always reviewed)']
            continue
        hits = matching(spec['files'], changed)
        if hits:
            out[key] = hits
    return out


_BASELINE = re.compile(r'Baseline:\s*`?([0-9a-f]{7,40})')
_SNAPSHOT = re.compile(r'`([0-9a-f]{7,40})`')


def baseline_of(readme):
    '''The commit a review was taken against: its `Baseline: <hash>` line, else (older reviews)
    the first backticked hash in its opening lines.'''
    try:
        text = Path(readme).read_text(encoding='utf-8')
    except OSError:
        return None
    m = _BASELINE.search(text)
    if m:
        return m.group(1)
    m = _SNAPSHOT.search('\n'.join(text.splitlines()[:20]))
    return m.group(1) if m else None


def prior_review(amap, before=None, root=ROOT):
    '''The latest docs/review-*/ (sorted by name, i.e. by date), excluding BEFORE and anything
    newer, with each area's inherited files from it.'''
    reviews = sorted(p for p in (root / 'docs').glob(REVIEW_GLOB) if p.is_dir())
    if before:
        cutoff = Path(before).resolve().name
        reviews = [p for p in reviews if p.name < cutoff]
    if not reviews:
        return None
    review = reviews[-1]
    inherits = {}
    for key, spec in amap['areas'].items():
        names = [key] + [w for w in spec['was'] if w != key]
        found = [str((review / f'{n}.md').relative_to(root)) for n in names
                 if (review / f'{n}.md').exists()]
        inherits[key] = found
    readme = review / 'README.md'
    return {
        'dir': str(review.relative_to(root)),
        'readme': str(readme.relative_to(root)) if readme.exists() else None,
        'baseline': baseline_of(readme),
        'inherits': inherits,
    }


def _print_areas(resolved):
    for key, spec in resolved.items():
        kind = 'cross-cutting' if spec['cross'] else f"{len(spec['owned'])} files, {spec['lines']} lines"
        effort = f", effort {spec['effort']}" if spec.get('effort') else ''
        print(f"{key:14} {spec.get('title', '')}  ({kind}{effort})")


def main(argv=None):
    parser = argparse.ArgumentParser(prog='reviewaudit', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('areas', help='every area with its owned files and line count')
    p.add_argument('--json', action='store_true', help='print as JSON')
    p = sub.add_parser('coverage', help='gaps in the area map (exit 1 if any)')
    p.add_argument('--json', action='store_true', help='print as JSON')
    p = sub.add_parser('since', help='the areas whose owned files changed between REF and HEAD')
    p.add_argument('ref', help='the git ref to diff from')
    p.add_argument('--json', action='store_true', help='print as JSON')
    p = sub.add_parser('prior', help='the latest earlier review and what each area inherits from it')
    p.add_argument('--before', help='a review dir: look only at reviews older than it')
    p.add_argument('--json', action='store_true', help='print as JSON')
    args = parser.parse_args(argv)

    amap = load_map()
    files = tracked_files()

    if args.cmd == 'areas':
        resolved = resolve_areas(amap, files)
        if args.json:
            print(json.dumps(resolved, indent=2))
        else:
            _print_areas(resolved)
        return 0

    if args.cmd == 'coverage':
        gaps = coverage(amap, files)
        bad = gaps['unowned'] or gaps['dead_globs'] or gaps['missing_context']
        if args.json:
            print(json.dumps(gaps, indent=2))
        else:
            for f in gaps['unowned']:
                print(f'unowned          {f}')
            for f, keys in gaps['shared'].items():
                print(f"shared           {f}  ({', '.join(keys)})")
            for d in gaps['dead_globs']:
                print(f"dead glob        {d['area']}: {d['glob']}")
            for d in gaps['missing_context']:
                print(f"missing context  {d['area']}: {d['path']}")
            if not bad:
                print(f"coverage OK — {len(matching(amap['track'], files))} tracked files, "
                      f"{len(amap['areas'])} areas")
        return 1 if bad else 0

    if args.cmd == 'since':
        hits = areas_since(amap, args.ref)
        if args.json:
            print(json.dumps(hits, indent=2))
        else:
            for key, changed in hits.items():
                print(f'{key:14} {len(changed)} changed' if not changed[0].startswith('(')
                      else f'{key:14} {changed[0]}')
        return 0

    if args.cmd == 'prior':
        info = prior_review(amap, args.before)
        if args.json:
            print(json.dumps(info, indent=2))
        elif info is None:
            print('no earlier review under docs/review-*/')
        else:
            print(f"{info['dir']}  baseline {info['baseline'] or 'unknown'}")
            for key, found in info['inherits'].items():
                print(f"  {key:14} {', '.join(found) or '(nothing to inherit)'}")
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
