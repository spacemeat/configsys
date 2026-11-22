#!/usr/bin/env python3
'''chimeranames — generate routes.hu's `component-names: { chimera-apk: … }` block.

Chimera Linux installs with apk-tools but names its packages its own way, so its native driver is
`chimera-apk` (never Alpine's `apk:` names) and its names are patched onto the catalog by ONE
generated block in routes.hu, between the `BEGIN`/`END chimera-apk component-names` markers. The
block lists ONLY the components whose Chimera name differs from what their binding resolves to on
Chimera (its `default:` / the component name), plus `{}` for those Chimera doesn't package (that
method is then not a candidate — routing-model §10a).

How: resolve every component in the chimera context, the block's current entries ignored; collect
each chimera-apk unit's package name(s); check each against Chimera's package index (main + user,
read from the chimera image with podman, or `--index FILE`, a saved `apk search` dump). A DEV
library (a `lib` component whose Alpine name is `X-dev`, or a component named `…-dev`) that resolves
to a runtime name on Chimera gets Chimera's `X-devel` when it exists — Chimera always splits headers
out, so the as-is name is the wrong half. For a name missing from the index, try, in order,
accepting a candidate ONLY if it is in the index:
  1. the `-dev` -> `-devel` rule;
  2. `py3-X` -> `python-X`;
  3. the component's own name;
  4. the binding's Alpine (`apk:`) name, then rules 1-2 on it; then its Void (`xbps:`) and Arch
     (`pacman:`) names;
else `{}`. Then resolve again with the new entries and repeat until nothing changes: a `{}` can move
a component to another method whose requirements pull new chimera-apk units (curl for a tarball),
or close a driver whose tool lost its package. A `packages:` set can't be renamed by
component-names (the driver installs the set), so a miss there is `{}`.

Human review (identity — same software, not a name collision) lives in
tools/chimeranames-review.hu, applied first: `rename:` hand-verified Chimera names (where no rule
finds one, or a rule finds the wrong one); `reject:` components whose Chimera name — as-is or found
by a rule — is NOT their software (they become `{}`). Prefer `{}` to a doubtful rename.

Usage:
  python3 tools/chimeranames.py [--index FILE] [--save-index FILE]   # print the block + a report
  python3 tools/chimeranames.py --write [--index FILE]             # rewrite the block in routes.hu
  python3 tools/chimeranames.py --check [--index FILE]             # exit 1 if routes.hu's block is stale
'''

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
ROUTES = os.path.join(ROOT, 'routes.hu')
REVIEW = os.path.join(HERE, 'chimeranames-review.hu')
DRIVER = 'chimera-apk'
IMAGE = 'docker.io/chimeralinux/chimera:latest'
BEGIN = '// BEGIN chimera-apk component-names'
END = '// END chimera-apk component-names'

# an apk atom is "<name>-<version>[-r<rev>]" (drivers/apk.py's rule)
_ATOM = re.compile(r'^(.*)-(\d[^\s-]*(?:-r\d+)?)$')
_INDEX_SNIPPET = ('apk add --no-interactive chimera-repo-user >/dev/null 2>&1 && '
                  'apk update >/dev/null 2>&1 && apk search && echo __CFS_DONE__')


def parse_index(text):
    '''The package NAMES in an `apk search` dump (one "<name>-<version>" per line).'''
    out = set()
    for line in text.splitlines():
        m = _ATOM.match(line.strip())
        if m:
            out.add(m.group(1))
    return out


def fetch_index(image=IMAGE):
    '''Chimera's main + user package names, from a throwaway container.'''
    proc = subprocess.run(['podman', 'run', '--rm', image, 'sh', '-c', _INDEX_SNIPPET],
                          capture_output=True, text=True, timeout=900)
    if '__CFS_DONE__' not in proc.stdout:
        tail = (proc.stderr or '').strip().splitlines()[-1:] or [f'exit {proc.returncode}']
        raise SystemExit(f'chimeranames: reading the index from {image} failed — {tail[0]}')
    return proc.stdout


def load_review(path=REVIEW):
    '''(reject {comp: why}, rename {comp: pkg}) from the review file.'''
    if not os.path.exists(path):
        return {}, {}
    from configsys.layers import materialize_string
    d = materialize_string(open(path, encoding='utf-8').read()) or {}
    return dict(d.get('reject') or {}), {k: str(v) for k, v in (d.get('rename') or {}).items()}


def _dev_rule(p):
    return p[:-len('-dev')] + '-devel' if p.endswith('-dev') else None


def _py_rule(p):
    return 'python-' + p[len('py3-'):] if p.startswith('py3-') else None


def candidates(pkg, comp, binding):
    '''The rename candidates for a missing Chimera name, in the documented order: (name, rule).'''
    names = binding.details.get('name') if binding is not None else None
    names = names if isinstance(names, dict) else {}
    out = [(_dev_rule(pkg), '-dev -> -devel'), (_py_rule(pkg), 'py3- -> python-'),
           (comp, 'the component name')]
    alpine = names.get('apk')
    if alpine:
        alpine = str(alpine)
        out += [(alpine, "Alpine's name"), (_dev_rule(alpine), "Alpine's name, -dev -> -devel"),
                (_py_rule(alpine), "Alpine's name, py3- -> python-")]
    for drv, label in (('xbps', "Void's name"), ('pacman', "Arch's name")):
        if names.get(drv):
            out.append((str(names[drv]), label))
    seen, uniq = {pkg}, []
    for name, rule in out:
        if name and name not in seen:
            seen.add(name)
            uniq.append((name, rule))
    return uniq


def _resolver():
    from configsys.routes import Resolver
    r = Resolver(ROUTES, 'chimera', None, 'x86_64', command_trust=lambda _p: True)
    base = {k: v for k, v in r.overrides.items() if k != DRIVER}   # the generated block, ignored
    return r, base


def _chimera_units(r):
    '''{component: ResolvedComponent} for every chimera-apk unit in the catalog's closures.'''
    found = {}
    for name in sorted(r.components):
        units, _errors = r.resolve_resilient([name])
        for rc in units.values():
            if rc.driver == DRIVER:
                found.setdefault(rc.comp, rc)
    return found


def dev_package(pkg, comp, binding, index, attrs=()):
    """Chimera's `-devel` for a DEV library that resolves to a runtime name there — `cairo` for a
    `lib` component whose Alpine name is `cairo-dev` (or any component whose own name ends `-dev`):
    Chimera always splits headers into `-devel`, so the as-is name exists but is the wrong half.
    Only for a `lib` component (a CLI like gettext whose Alpine name happens to be a -dev keeps its
    tools package). -> (name, why) or None."""
    if pkg.endswith('-devel') or not ('lib' in attrs or comp.endswith('-dev')):
        return None
    names = binding.details.get('name') if binding is not None else None
    alpine = str(names.get('apk')) if isinstance(names, dict) and names.get('apk') else None
    for src, label in ((alpine, "Alpine's dev package"), (comp, 'a -dev component')):
        dev = _dev_rule(src) if src else None
        if dev and dev != pkg and dev in index:
            return dev, f'{label} {src} -> -devel'
    return None


def generate(index, review=None):
    """-> (entries {comp: pkg | None}, notes {comp: text}). None = `{}`. Per chimera-apk unit, in
    order: a reviewed `rename:`; a reviewed `reject:` (-> `{}`); a dev component resolving to a
    runtime name (dev_package); a name missing from the index -> the rename rules (candidates), else
    `{}`. Repeated until no new entry appears."""
    from configsys.resolve import binding_of
    reject, manual = review if review is not None else load_review()
    r, base = _resolver()
    entries, notes = {}, {}
    while True:
        r.overrides = {**base, DRIVER: {c: (p if p else {}) for c, p in entries.items()}}
        added = False
        for comp, rc in sorted(_chimera_units(r).items()):
            if comp in entries:
                continue
            raw = rc.fields.get('packages')
            is_set = isinstance(raw, list)
            pkgs = [str(p) for p in raw] if is_set else ([str(raw)] if raw else rc.name.split())
            is_set = is_set or len(pkgs) != 1
            missing = [p for p in pkgs if p not in index]
            binding = binding_of(r.components[comp], rc)
            if comp in manual and not is_set and manual[comp] != pkgs[0]:   # hand-verified (review file)
                if manual[comp] not in index:
                    raise SystemExit(f'chimeranames: review rename {comp} -> {manual[comp]} is not in '
                                     f"Chimera's index any more — re-review it")
                entries[comp], notes[comp] = manual[comp], f'was {pkgs[0]} (reviewed)'
            elif comp in reject:
                entries[comp], notes[comp] = None, f'was {" ".join(pkgs)}: rejected in review'
            elif not is_set and (dev := dev_package(pkgs[0], comp, binding, index,
                                                    r.components[comp].attrs)):
                entries[comp], notes[comp] = dev[0], f'was {pkgs[0]} ({dev[1]})'
            elif not missing:
                continue
            elif is_set:
                entries[comp], notes[comp] = None, f'not in Chimera: {" ".join(missing)} (a package set)'
            else:
                hit = next(((n, why) for n, why in candidates(pkgs[0], comp, binding) if n in index),
                           None)
                if hit is not None:
                    entries[comp], notes[comp] = hit[0], f'was {pkgs[0]} ({hit[1]})'
                else:
                    entries[comp], notes[comp] = None, f'{pkgs[0]}: not in Chimera'
            added = True
        if not added:
            return entries, notes


def _key(s):
    return s if re.fullmatch(r'[A-Za-z0-9_.+-]+', s) else '"' + s.replace('"', '\\"') + '"'


def render(entries, notes):
    '''The block's text (between the markers, markers included), indented for routes.hu.'''
    lines = [f'    {BEGIN}', '    component-names: {', f'        {DRIVER}: {{']
    width = max((len(_key(c)) for c in entries), default=0)
    for comp in sorted(entries):
        val = _key(entries[comp]) if entries[comp] else '{}'
        lines.append(f'            {_key(comp) + ":":<{width + 1}} {val:<24} // {notes.get(comp, "")}'.rstrip())
    lines += ['        }', '    }', f'    {END}']
    return '\n'.join(lines) + '\n'


def splice(text, block):
    '''routes.hu `text` with the marked region replaced by `block`.'''
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0:
        raise SystemExit(f'chimeranames: routes.hu has no "{BEGIN}" … "{END}" region')
    start = text.rfind('\n', 0, i) + 1
    end = text.index('\n', j) + 1
    return text[:start] + block + text[end:]


def main():
    ap = argparse.ArgumentParser(description="generate routes.hu's chimera-apk component-names block")
    ap.add_argument('--index', help='a saved `apk search` dump of Chimera main + user (skips podman)')
    ap.add_argument('--save-index', help='write the index dump read from the image here')
    ap.add_argument('--write', action='store_true', help='rewrite the marked block in routes.hu')
    ap.add_argument('--check', action='store_true', help='exit 1 if the block in routes.hu is stale')
    args = ap.parse_args()
    text = open(args.index, encoding='utf-8').read() if args.index else fetch_index()
    if args.save_index:
        with open(args.save_index, 'w', encoding='utf-8') as f:
            f.write(text)
    index = parse_index(text)
    entries, notes = generate(index)
    block = render(entries, notes)
    routes = open(ROUTES, encoding='utf-8').read()
    new = splice(routes, block)
    renamed = sum(1 for p in entries.values() if p)
    print(f'chimeranames: {len(index)} Chimera packages; {renamed} renamed, '
          f'{len(entries) - renamed} not packaged ({{}})', file=sys.stderr)
    if args.check:
        if new != routes:
            print('chimeranames: routes.hu is stale — run tools/chimeranames.py --write', file=sys.stderr)
            return 1
        return 0
    if args.write:
        if new != routes:
            with open(ROUTES, 'w', encoding='utf-8') as f:
                f.write(new)
        return 0
    sys.stdout.write(block)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
