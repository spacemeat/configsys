'''Field-parity harness: the equivalence harness proves the v2 dependency GRAPH matches
the old resolver, but only compares (mechanism, component, package) + closure keys — never
`rc.fields`. The families are entirely fields-driven, so this harness closes that gap: for
each ported unit it builds the old ResolvedComponent and the v2-adapted one and asserts the
install-relevant fields each family actually reads are equal. This is the flip gate.

A pure "install signature" per family (no runner / no network) captures what that family
would install; equal signatures => same install.
'''

import os

import humon
import pytest

from configsys.routes import RouteResolver
from configsys.families import get_family
from configsys.v2 import routes2
from configsys.v2.adapt import to_resolved_components
from configsys.v2.resolve import resolve

HERE = os.path.dirname(__file__)
ROUTES1 = os.path.join(HERE, '..', 'routes.hu')
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')


def _old_rc(name, block, ver):
    units = RouteResolver(humon.from_file(ROUTES1), block, ver).resolve_names([name])
    for rc in units.values():
        if rc.comp == name:
            return rc
    raise AssertionError(f'old: no primary unit for {name} @ {block}')


def _v2_rc(name, block, ver, cpu='x86_64'):
    cascade, comps, mechs = routes2.load(ROUTES2)
    units = resolve([name], cascade, comps, mechs, block, ver, cpu)
    rcs = to_resolved_components(units)
    for rc in rcs.values():
        if rc.comp == name:
            return rc
    raise AssertionError(f'v2: no primary unit for {name} @ {block}')


# -- per-family install signature (pure: reads fields only, no runner/network) ---

def _versionspec(rc):
    v = rc.fields.get('version')
    if isinstance(v, dict):
        return tuple(sorted((k, str(x)) for k, x in v.items()))
    return v


def _pm_for(block):
    if block in ('fedora', 'rhel'):
        return 'dnf'
    if block == 'arch':
        return 'pacman'
    return 'apt'


def _alt_sig(fam, rc, block):
    # dnf installs the compat packages directly — no update-alternatives, no PPA, so
    # slaves/ppa/apt-source are dead there (old inherits them from the shared family; v2
    # omits them). Only apt registers alternatives + a repo, so compare those on apt only.
    if _pm_for(block) == 'dnf':
        return ('alt-dnf', tuple(fam._packages(rc)))
    return ('alt-apt', fam._link(rc), fam._ver(rc), tuple(fam._slaves(rc)),
            tuple(fam._packages(rc)), rc.fields.get('ppa'),
            _hashable(rc.fields.get('apt-source')))


def _dotfiles_sig(fam, rc):
    return ('dotfiles', tuple(sorted(fam._specs(rc))))


def _aslist(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _apt_sig(rc):
    '''Canonical apt install intent, tolerant of the old vs v2 deb-mode field shapes
    (old: `deb:true` + `version:{github,asset-glob}`; v2: `deb-source` + cpu-keyed `asset`).
    Compares the resolved x86_64 .deb source, not the raw fields.'''
    f = rc.fields
    deb = bool(f.get('deb')) or ('deb-source' in f)
    repo = asset = None
    if deb:
        v = f.get('version')
        if isinstance(v, dict):
            repo, asset = v.get('github'), v.get('asset')
        ds = f.get('deb-source')
        if isinstance(ds, str) and ds.startswith('github:'):
            repo = ds.split(':', 1)[1]
        a = f.get('asset')
        if isinstance(a, dict):
            asset = a.get('x86_64')
        elif isinstance(a, str):
            asset = a
    return ('apt', rc.name, deb, repo, asset,
            tuple(sorted(_aslist(f.get('foreign-arch')))),
            tuple(sorted(_aslist(f.get('repo-component')))))


def _hashable(v):
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    return v


def _keyset_sig(rc, keys):
    return tuple((k, _hashable(rc.fields.get(k))) for k in keys)


# keys each family reads off rc.fields for its install ops (name compared separately via rc.name)
_FAMILY_KEYS = {
    'dnf':    (),
    'pacman': (),
    'aur':    (),
    'cargo':  (),
    'pip':    (),
    'pipx':   (),
    'flatpak': ('hub', 'hub-url'),
    'appImage': ('url', 'path', 'icon'),
    'tarball':  ('url', 'installDir'),
    'debian-font': ('url',),
}


def _signature(rc, block=None):
    fam = get_family(rc.family, runner=None, paths=None)
    assert fam is not None, f'no family for {rc.family}'
    if rc.family in ('gcc', 'clang'):
        return _alt_sig(fam, rc, block)
    if rc.family == 'dotfiles':
        return _dotfiles_sig(fam, rc)
    if rc.family == 'gcc-toolset':
        return ('gcc-toolset', str(rc.fields.get('version') or rc.comp.rsplit('-', 1)[-1]))
    if rc.family == 'apt':
        return _apt_sig(rc)
    keys = _FAMILY_KEYS.get(rc.family, ())
    return (rc.family, rc.name, _versionspec(rc), _keyset_sig(rc, keys))


# one representative primary-unit case per family / interesting shape
CASES = [
    ('btop', 'ubuntu', '24.04'),          # apt native
    ('btop', 'fedora', '41'),             # dnf native
    ('btop', 'arch', '20260101'),         # pacman native
    ('libfuse2', 'fedora', '41'),         # dnf name-map
    ('steam', 'pop_os!', '22.04'),        # apt foreign-arch
    ('chrome', 'ubuntu', '24.04'),        # flatpak (app -> name, hub)
    ('tree-sitter-cli', 'ubuntu', '24.04'),  # cargo
    ('mononoki-nerd', 'ubuntu', '24.04'),    # debian-font (url)
    ('neovim', 'ubuntu', '24.04'),        # appImage (url, path, version)
    ('arduino', 'ubuntu', '24.04'),       # appImage
    ('fastfetch', 'ubuntu', '24.04'),     # apt deb-mode
    ('vulkan-sdk', 'ubuntu', '24.04'),    # tarball (url, installDir, version)
    ('bashDotD', 'ubuntu', '24.04'),      # dotfiles (aliases spec)
    ('pipx', 'ubuntu', '24.04'),          # pipx native
    ('pipx', 'ubuntu', '22.04'),          # pip bootstrap
    ('apod', 'ubuntu', '24.04'),          # pipx (name = termapod)
    ('yay', 'arch', '20260101'),          # aur
    ('gcc-13', 'ubuntu', '24.04'),        # gcc alt (link/ver/slaves/packages/ppa)
    ('gcc-14', 'ubuntu', '24.04'),
    ('clang-18', 'ubuntu', '24.04'),      # clang alt
    ('clang-19', 'fedora', '41'),
    ('gcc-13', 'rhel', '9.8'),            # gcc-toolset
    # apt universe-natives on Ubuntu (repo-component parity)
    ('fzf', 'ubuntu', '24.04'), ('xclip', 'ubuntu', '24.04'), ('ripgrep', 'ubuntu', '24.04'),
    ('cargo', 'ubuntu', '24.04'), ('libfuse2', 'ubuntu', '24.04'), ('firefox', 'ubuntu', '24.04'),
    ('libxcb-cursor-dev', 'ubuntu', '24.04'),
    # same natives across the other package managers (name-maps, no universe)
    ('libfuse2', 'arch', '20260101'), ('cargo', 'arch', '20260101'),
    ('firefox', 'fedora', '41'), ('fzf', 'rhel', '9.8'),
    # more toolchain + fetch coverage
    ('gcc-15', 'ubuntu', '24.04'), ('clang-20', 'rhel', '9.8'), ('clang-19', 'fedora', '42'),
    ('gcc-14', 'rhel', '9.8'),
    ('fastfetch', 'fedora', '41'), ('fastfetch', 'arch', '20260101'),
    ('mononoki-nerd', 'fedora', '41'), ('neovim', 'arch', '20260101'),
    ('steam', 'ubuntu', '24.04'),         # flatpak path
    ('chrome', 'fedora', '41'),
]


@pytest.mark.parametrize('name,block,ver', CASES)
def test_field_parity(name, block, ver):
    old = _old_rc(name, block, ver)
    new = _v2_rc(name, block, ver)
    assert new.family == old.family, f'{name}: family {new.family} != {old.family}'
    assert _signature(new, block) == _signature(old, block), (
        f'{name} @ {block}: install signature differs\n'
        f'  old fields: {old.fields}\n  v2  fields: {new.fields}')
