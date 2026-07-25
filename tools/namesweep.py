#!/usr/bin/env python3
'''namesweep — extract the native package names configsys would install, per package manager.

This is the HOST-SIDE half of the name-existence sweep (see docs/name-sweep-test.md). It resolves
every component in a representative context per manager and collects the native package names each
maps to — the exact set a container-side verifier then checks for existence, catching renames/
removals (redis->valkey, Fedora dropping sagemath, ...) automatically.

Only NATIVE units are collected (apt/dnf/pacman/zypper/apk). Flatpak app-ids, pipx/npm/cargo dist
names, tarball URLs and script installers are a different verification and are skipped here.

Usage:
  python3 tools/namesweep.py                 # summary: package count per manager
  python3 tools/namesweep.py --manager apt   # one package name per line (feed to a container)
  python3 tools/namesweep.py --json          # full {manager: {pkg: [components]}} as JSON
'''

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
ROUTES = os.path.join(ROOT, 'routes.hu')

# A representative machine per manager. Resolution applies each component's when:/name: maps, so
# what we collect is the REAL per-distro package name — exactly what to check exists there.
MANAGERS = [
    ('apt', 'ubuntu', '24.04'),
    ('dnf', 'fedora', '42'),
    ('pacman', 'arch', '20260101'),
    ('zypper', 'opensuse', ''),
    ('apk', 'alpine', '3.20'),
]


def extract(routes_path=ROUTES):
    '''-> {manager: {package_name: sorted[components that map to it here]}}.'''
    from configsys.routes import Resolver
    from configsys.resolve import ResolveError
    out = {}
    for mgr, block, ver in MANAGERS:
        r = Resolver(routes_path, block, ver or None, 'x86_64')
        pkgs = {}
        for name in sorted(r.components):
            try:
                units = r.resolve_names([name])          # applies when:/name:/requires closure
            except ResolveError:
                continue                                 # doesn't route on this manager — skip
            for rc in units.values():
                if rc.driver == mgr:                     # a native unit on THIS manager
                    pkgs.setdefault(rc.name, set()).add(name)
        out[mgr] = {p: sorted(cs) for p, cs in pkgs.items()}
    return out


def main():
    ap = argparse.ArgumentParser(description='extract native package names per manager')
    ap.add_argument('--manager', help='print just this manager\'s package names, one per line')
    ap.add_argument('--json', action='store_true', help='emit the full map as JSON')
    args = ap.parse_args()
    data = extract()
    if args.manager:
        for pkg in sorted(data.get(args.manager, {})):
            print(pkg)
    elif args.json:
        print(json.dumps(data, indent=1, sort_keys=True))
    else:
        for mgr, _b, _v in MANAGERS:
            print(f'{mgr:8} {len(data.get(mgr, {})):4d} native packages to verify')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
