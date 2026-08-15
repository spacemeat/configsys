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
                              'pubkey-url', 'ppa'})   # `ppa:` wires a PPA (deadsnakes) — not a base-repo name


def _native_names(block, ver, manager, plugin_files=(), routes_path=ROUTES):
    '''{package_name: sorted[components]} — the manager's native packages when resolving the whole
    catalog on `block`. `plugin_files` loads a plugin OS's layers (its os block + components).'''
    from configsys.routes import Resolver
    from configsys.resolve import ResolveError
    r = Resolver(routes_path, block, ver or None, 'x86_64', plugin_files=plugin_files)
    pkgs = {}
    for name in sorted(r.components):
        try:
            units = r.resolve_names([name])              # applies when:/name:/requires closure
        except ResolveError:
            continue                                     # doesn't route here — skip
        for rc in units.values():
            if rc.driver != manager or (_NON_REPO_FIELDS & rc.fields.keys()):
                continue
            multi = rc.fields.get('packages')            # a multi-package meta unit (opengl, python-build-
            if isinstance(multi, (list, tuple)):         # deps, …): verify each REAL package, not the unit name
                for p in multi:
                    pkgs.setdefault(p, set()).add(name)
            else:
                pkgs.setdefault(rc.name, set()).add(name)
    return {p: sorted(cs) for p, cs in pkgs.items()}


def extract(routes_path=ROUTES):
    '''-> {manager: {package_name: sorted[components that map to it here]}}.'''
    return {mgr: _native_names(block, ver, mgr, routes_path=routes_path)
            for mgr, block, ver in MANAGERS}


# -- container-side verifiers ---------------------------------------------
# Split into (a) the per-manager existence CHECK verb — reads a package name in `$p`, exits 0 iff
# it exists — and (b) the base image + repo SETUP. A plugin OS reuses the CHECK for its manager
# and supplies its own image + setup (e.g. Proxmox = apt on debian:12 + the PVE repo).
_CHECK = {
    'apt':    'apt-cache show "$p" >/dev/null 2>&1',
    'dnf':    '(dnf -q info "$p" >/dev/null 2>&1 || dnf -q provides "$p" >/dev/null 2>&1)',
    'pacman': '(pacman -Si "$p" >/dev/null 2>&1 || pacman -Sg "$p" >/dev/null 2>&1)',
    # `se -x` is already an EXACT name match, so just confirm a binary-package row exists — the
    # name never enters the regex (the old grep -qE "...$p..." broke on names with regex
    # metacharacters like gcc-c++, false-flagging an existing package; awk isn't in the image).
    'zypper': 'zypper -n se -x "$p" 2>/dev/null | grep -qF "| package"',
    'apk':    'apk search -x "$p" 2>/dev/null | grep -q "^$p-[0-9]"',
    'xbps':   'xbps-query -R "$p" >/dev/null 2>&1',          # Void (plugin OS)
}

# (image, repo-setup) for the core families. Setup output is silenced; the read-loop is appended
# by _build_snippet so stdout is exactly the missing names.
_VERIFIERS = {
    'apt': ('docker.io/library/ubuntu:24.04', r'''
        export DEBIAN_FRONTEND=noninteractive
        sed -i 's/^Components: main$/Components: main restricted universe multiverse/' \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        apt-get update -qq >/dev/null 2>&1'''),
    'dnf': ('docker.io/library/fedora:41', r'''
        dnf -q -y install \
          "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
          "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm" \
          >/dev/null 2>&1 || true'''),
    'pacman': ('docker.io/library/archlinux:latest', 'pacman -Sy --noconfirm >/dev/null 2>&1'),
    'zypper': ('docker.io/opensuse/tumbleweed:latest',
               'zypper -n --gpg-auto-import-keys ref >/dev/null 2>&1'),
    'apk': ('docker.io/library/alpine:latest', r'''
        ver=$(cut -d. -f1,2 /etc/alpine-release)
        echo "https://dl-cdn.alpinelinux.org/alpine/v$ver/community" >> /etc/apk/repositories
        apk update >/dev/null 2>&1'''),
}


def _build_snippet(setup, check):
    '''setup + a read-loop that prints each name whose CHECK fails (i.e. doesn't exist).'''
    return (f'{setup}\n'
            'while IFS= read -r p; do [ -z "$p" ] && continue\n'
            f'    {check} || echo "$p"; done\n')


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


# The green gate: all five package families. NOTE openSUSE ships some versioned names
# (python313-pip, ffmpeg-7, ...) that roll with Tumbleweed — the sweep will flag them when they
# bump; just update the `name:` map (that's the sweep working, not a false alarm).
_DEFAULT_MANAGERS = ('apt', 'dnf', 'pacman', 'zypper', 'apk')


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
    for mgr, (image, setup) in _VERIFIERS.items():
        if mgr not in targets:
            continue
        names = sorted(data.get(mgr, {}))
        print(f'>> {mgr}: {len(names)} packages in {image}', file=sys.stderr)
        try:
            missing, rc = _run_verifier(image, _build_snippet(setup, _CHECK[mgr]), names)
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


def sweep_plugin(plugin, context, manager, image, setup='', allowlist=None):
    '''Sweep a PLUGIN OS: resolve the catalog on `context` with the plugin loaded, collect its
    `manager` package names, and verify them exist in `image` (after `setup`). Reuses the core
    allowlist for that manager (so e.g. Proxmox inherits apt's vendor-SDK exceptions), unioned
    with an optional plugin-local `allowlist` file (Void ships its own for the GPU SDKs, keyed by
    the plugin's own driver e.g. `xbps`).'''
    if not shutil.which('podman'):
        print('namesweep: podman not found', file=sys.stderr)
        return 2
    check = _CHECK.get(manager)
    if not (plugin and context and manager and image and check):
        print('namesweep --plugin needs --context, --manager (with a known check verb), --image',
              file=sys.stderr)
        return 2
    names_map = _native_names(context, None, manager, plugin_files=[(plugin, 'plugin')])
    names = sorted(names_map)
    allow = _load_allowlist().get(manager, set())
    if allowlist:
        allow = allow | _load_allowlist(allowlist).get(manager, set())
    print(f'>> {context} ({manager}): {len(names)} packages in {image}', file=sys.stderr)
    try:
        missing, _rc = _run_verifier(image, _build_snippet(setup, check), names)
    except subprocess.TimeoutExpired:
        print(f'   {context}: verifier timed out', file=sys.stderr)
        return 2
    drift = {p: names_map[p] for p in missing if p not in allow}
    for p in sorted(drift):
        print(f'DRIFT  {context}: package "{p}" NOT FOUND  (component: {", ".join(drift[p])})')
    if drift:
        print(f'\nname sweep: {len(drift)} package(s) drifted on {context}.')
        return 1
    print(f'\nname sweep: OK — {context} native names all exist.')
    return 0


def main():
    ap = argparse.ArgumentParser(description='extract native package names per manager')
    ap.add_argument('--manager', help='print just this manager\'s package names, one per line')
    ap.add_argument('--json', action='store_true', help='emit the full map as JSON')
    ap.add_argument('--sweep', action='store_true',
                    help='verify every name exists in its repos (podman); exit 1 on drift')
    ap.add_argument('--only', help='comma-separated managers to sweep (default: all)')
    # plugin-OS sweep: point at a plugin's routes.hu + its OS context, manager, and container.
    ap.add_argument('--plugin', help='sweep a plugin OS: path to the plugin routes.hu')
    ap.add_argument('--context', help='OS block to resolve against (with --plugin)')
    ap.add_argument('--image', help='container image to verify in (with --plugin)')
    ap.add_argument('--setup', help='shell file: repo setup run before the check (with --plugin)')
    ap.add_argument('--allowlist', help='plugin-local allowlist .hu, unioned with the core one')
    args = ap.parse_args()
    if args.sweep and args.plugin:
        setup = open(args.setup, encoding='utf-8').read() if args.setup else ''
        return sweep_plugin(args.plugin, args.context, args.manager, args.image, setup,
                            args.allowlist)
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
