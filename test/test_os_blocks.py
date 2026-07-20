'''The OS blocks added when Alpine folded into base and the cheap-descendant + openSUSE set
landed: native-driver resolution down the cascade, and — the subtle part — version *scale*
inheritance (which derivatives borrow a parent's numbering vs. own their own).'''

import os

import pytest

from configsys import routes
from configsys.predicate import parse
from configsys.resolve import ResolveError
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


@pytest.fixture(scope='module')
def cascade():
    c, _components, _m = routes.load(ROUTES)
    return c


def holds(cascade, expr, block, version=None, cpu='x86_64'):
    return parse(expr).eval(cascade.context(block, version, cpu))


# -- native driver resolves down each new lineage -------------------------

def test_native_driver_per_family(cascade):
    assert cascade.native('alpine') == 'apk'
    assert cascade.native('opensuse_leap') == 'zypper'
    assert cascade.native('opensuse_tumbleweed') == 'zypper'
    assert cascade.native('rocky') == 'dnf'          # inherited from rhel -> redhat
    assert cascade.native('almalinux') == 'dnf'
    assert cascade.native('centos') == 'dnf'
    assert cascade.native('manjaro') == 'pacman'     # inherited from arch
    assert cascade.native('endeavouros') == 'pacman'
    assert cascade.native('linuxmint') == 'apt'      # inherited from ubuntu -> debian
    assert cascade.native('lmde') == 'apt'


def test_lineage_membership(cascade):
    assert 'rhel' in cascade.lineage('rocky') and 'linux' in cascade.lineage('rocky')
    assert 'arch' in cascade.lineage('manjaro')
    assert 'opensuse' in cascade.lineage('opensuse_tumbleweed')


# -- scale inheritance: who borrows a parent's numbering, who owns their own

def test_rhel_rebuilds_borrow_rhel_scale(cascade):
    # Rocky 9.3 IS EL9 — it shares rhel's numbering, so a versioned rhel atom matches it.
    assert holds(cascade, 'rhel >= 9', 'rocky', '9.3')
    assert holds(cascade, 'rhel >= 9', 'almalinux', '9.4')
    assert not holds(cascade, 'rhel >= 10', 'rocky', '9.3')
    assert holds(cascade, 'rocky', 'rocky', '9.3')        # bare identity still matches


def test_mint_owns_its_own_scale(cascade):
    # Mint 21 = Ubuntu 22.04 (DIFFERENT digits). A versioned `ubuntu` atom must NOT misfire on
    # Mint just because 21 < 23.04 — Mint is its own scale-root, so the scale guard rejects it.
    assert not holds(cascade, 'ubuntu < 23.04', 'linuxmint', '21')
    assert not holds(cascade, 'debian < 12', 'lmde', '6')
    assert holds(cascade, 'ubuntu', 'linuxmint', '21')    # bare ubuntu still matches (routes)
    assert holds(cascade, 'linuxmint < 22', 'linuxmint', '21')   # its own scale targets it


def test_pop_still_borrows_ubuntu_scale(cascade):
    # the counter-case that justifies the split: Pop shares Ubuntu's exact numbers.
    assert holds(cascade, 'ubuntu < 23.04', 'pop_os!', '22.04')


def test_opensuse_leap_versioned_tumbleweed_rolling(cascade):
    # Leap is a scale-root (15.x); Tumbleweed is rolling — versioned atoms never match it,
    # but bare membership does.
    assert holds(cascade, 'opensuse_leap >= 15', 'opensuse_leap', '15.6')
    assert not holds(cascade, 'opensuse_leap >= 16', 'opensuse_leap', '15.6')
    assert not holds(cascade, 'opensuse_leap >= 15', 'opensuse_tumbleweed', '20260101')
    assert holds(cascade, 'opensuse', 'opensuse_tumbleweed')     # bare membership
    assert holds(cascade, 'opensuse_tumbleweed', 'opensuse_tumbleweed')


# -- glibc capability: the musl gate + the gcompat opt-in escape hatch ------

def test_glibc_provided_by_glibc_families_not_alpine(cascade):
    for glibc_os in ('ubuntu', 'fedora', 'arch', 'opensuse_leap', 'rocky', 'linuxmint'):
        assert 'glibc' in cascade.provides(glibc_os), glibc_os
    assert 'glibc' not in cascade.provides('alpine')


def test_appimage_routes_on_glibc_declines_on_alpine():
    # neovim (an appImage, requires glibc via the driver) resolves on ubuntu (glibc env-provided,
    # no extra unit) but declines on Alpine by default — a clean diagnostic, not a broken install.
    ubu = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['neovim'])
    assert 'appImage\\neovim' in ubu
    with pytest.raises(ResolveError) as e:
        Resolver(ROUTES, 'alpine').resolve_names(['neovim'])
    assert 'glibc' in str(e.value) and 'gcompat' in str(e.value)   # error names the opt-in


def test_gcompat_opt_in_enables_glibc_binaries_on_alpine():
    # provider-pin the shim -> the glibc appImage routes AND gcompat is pulled.
    pinned = Resolver(ROUTES, 'alpine', pins={'glibc': 'gcompat'}).resolve_names(['neovim'])
    assert 'appImage\\neovim' in pinned and 'apk\\gcompat' in pinned
    # ...but gcompat is NEVER auto-pulled without opting in
    with pytest.raises(ResolveError):
        Resolver(ROUTES, 'alpine').resolve_names(['android-studio'])
