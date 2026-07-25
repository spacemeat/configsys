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
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
ROUTES = os.path.join(ROOT, 'routes.hu')
ALLOWLIST = os.path.join(ROOT, 'test', 'namesweep-allowlist.hu')

# A representative machine per manager. Resolution applies each component's when:/name: maps, so
# what we collect is the REAL per-distro package name — exactly what to check exists there.
MANAGERS = [
    ('apt', 'ubuntu', '24.04'),
    ('dnf', 'fedora', '42'),
    ('pacman', 'arch', '20260101'),
    ('zypper', 'opensuse', ''),
    ('apk', 'alpine', '3.20'),
]


# A native unit carrying any of these fields isn't a plain repo package — it wires a third-party
# repo (vscode/MS) or fetches a github .deb (fastfetch): the name only resolves after that setup,
# so a base-repo existence check would false-positive. These belong to other verifications.
_NON_REPO_FIELDS = frozenset({'deb-source', 'source-line', 'source-path', 'repo-url', 'repo-id',
                              'pubkey-url'})


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
                if rc.driver == mgr and not (_NON_REPO_FIELDS & rc.fields.keys()):
                    pkgs.setdefault(rc.name, set()).add(name)
        out[mgr] = {p: sorted(cs) for p, cs in pkgs.items()}
    return out


# -- container-side verifiers ---------------------------------------------
# (base image, shell that enables the repos configsys uses, refreshes once, then reads package
#  names on stdin and prints the ones that DON'T exist). Setup output is silenced so stdout is
#  exactly the missing names.
_VERIFIERS = {
    'apt': ('docker.io/library/ubuntu:24.04', r'''
        export DEBIAN_FRONTEND=noninteractive
        sed -i 's/^Components: main$/Components: main restricted universe multiverse/' \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        apt-get update -qq >/dev/null 2>&1
        while IFS= read -r p; do [ -z "$p" ] && continue
            apt-cache show "$p" >/dev/null 2>&1 || echo "$p"; done
    '''),
    'dnf': ('docker.io/library/fedora:41', r'''
        dnf -q -y install \
          "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
          "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm" \
          >/dev/null 2>&1 || true
        while IFS= read -r p; do [ -z "$p" ] && continue
            dnf -q info "$p" >/dev/null 2>&1 || echo "$p"; done
    '''),
    'pacman': ('docker.io/library/archlinux:latest', r'''
        pacman -Sy --noconfirm >/dev/null 2>&1
        while IFS= read -r p; do [ -z "$p" ] && continue
            (pacman -Si "$p" >/dev/null 2>&1 || pacman -Sg "$p" >/dev/null 2>&1) || echo "$p"; done
    '''),
    'zypper': ('docker.io/opensuse/tumbleweed:latest', r'''
        zypper -n --gpg-auto-import-keys ref >/dev/null 2>&1
        while IFS= read -r p; do [ -z "$p" ] && continue
            zypper -n se -x "$p" 2>/dev/null | grep -qE "\|[[:space:]]*$p[[:space:]]" || echo "$p"; done
    '''),
    'apk': ('docker.io/library/alpine:latest', r'''
        ver=$(cut -d. -f1,2 /etc/alpine-release)
        echo "https://dl-cdn.alpinelinux.org/alpine/v$ver/community" >> /etc/apk/repositories
        apk update >/dev/null 2>&1
        while IFS= read -r p; do [ -z "$p" ] && continue
            apk search -x "$p" 2>/dev/null | grep -q "^$p-[0-9]" || echo "$p"; done
    '''),
}


def _load_allowlist(path=ALLOWLIST):
    '''{manager: set(package)} of names this sweep is expected NOT to find (repo we don't enable
    in the check, brand-new package, ...). Each entry should carry a `//` reason in the file.'''
    if not os.path.exists(path):
        return {}
    from configsys.layers import materialize_string
    d = materialize_string(open(path, encoding='utf-8').read()) or {}
    return {mgr: set(v) for mgr, v in d.items() if isinstance(v, list)}


def _run_verifier(image, snippet, names, timeout=1200):
    proc = subprocess.run(['podman', 'run', '-i', '--rm', image, 'sh', '-c', snippet],
                          input='\n'.join(names) + '\n', capture_output=True, text=True,
                          timeout=timeout)
    missing = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return missing, proc.returncode


# The green gate: the families configsys is verified against. zypper/apk are opt-in (--only) —
# their native-name coverage is a known hardening backlog the sweep surfaces (see the design doc).
_DEFAULT_MANAGERS = ('apt', 'dnf', 'pacman')


def sweep(only=None):
    '''Verify every native package configsys maps to still exists in its target repos. Prints
    drift (renames/removals) and returns 1 if any survives the allowlist, else 0.'''
    if not shutil.which('podman'):
        print('namesweep: podman not found', file=sys.stderr)
        return 2
    data = extract()
    allow = _load_allowlist()
    targets = only or set(_DEFAULT_MANAGERS)
    drift, stale = {}, {}
    for mgr, (image, snippet) in _VERIFIERS.items():
        if mgr not in targets:
            continue
        names = sorted(data.get(mgr, {}))
        print(f'>> {mgr}: {len(names)} packages in {image}', file=sys.stderr)
        try:
            missing, rc = _run_verifier(image, snippet, names)
        except subprocess.TimeoutExpired:
            print(f'   {mgr}: verifier timed out — skipped', file=sys.stderr)
            continue
        allowed = allow.get(mgr, set())
        real = {p: data[mgr][p] for p in missing if p not in allowed}
        if real:
            drift[mgr] = real
        st = [p for p in allowed if p not in missing and p in data[mgr]]
        if st:
            stale[mgr] = st

    for mgr in sorted(drift):
        for p, comps in sorted(drift[mgr].items()):
            print(f'DRIFT  {mgr}: package "{p}" NOT FOUND  (component: {", ".join(comps)})')
    for mgr in sorted(stale):
        for p in sorted(stale[mgr]):
            print(f'note   {mgr}: allowlist entry "{p}" now exists — remove it from the allowlist')
    n = sum(len(v) for v in drift.values())
    if n:
        print(f'\nname sweep: {n} package(s) drifted — fix the route or allowlist them.')
        return 1
    print('\nname sweep: OK — every native package exists in its target repo.')
    return 0


def main():
    ap = argparse.ArgumentParser(description='extract native package names per manager')
    ap.add_argument('--manager', help='print just this manager\'s package names, one per line')
    ap.add_argument('--json', action='store_true', help='emit the full map as JSON')
    ap.add_argument('--sweep', action='store_true',
                    help='verify every name exists in its repos (podman); exit 1 on drift')
    ap.add_argument('--only', help='comma-separated managers to sweep (default: all)')
    args = ap.parse_args()
    if args.sweep:
        return sweep(only=set(args.only.split(',')) if args.only else None)
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
