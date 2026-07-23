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


# -- the 2026 descendant blocks (cachyos/garuda/nobara/kali/pikaos) ---------

def test_new_descendant_natives(cascade):
    assert cascade.native('cachyos') == 'pacman'   # arch
    assert cascade.native('garuda') == 'pacman'
    assert cascade.native('nobara') == 'dnf'       # fedora
    assert cascade.native('kali') == 'apt'         # debian
    assert cascade.native('pikaos') == 'apt'


def test_nobara_borrows_fedora_scale_kali_pikaos_own(cascade):
    # Nobara N == Fedora N -> a versioned fedora atom applies to it (no scale-root)
    assert holds(cascade, 'fedora >= 40', 'nobara', '40')
    # kali is rolling / pikaos owns date numbering -> a versioned debian atom must NOT bind them
    assert not holds(cascade, 'debian < 12', 'pikaos', '26')
    assert not holds(cascade, 'debian < 12', 'kali', '2026')


# -- Fedora Atomic / uBlue = a distinct environment (brew CLI, flatpak apps) --

def test_fedora_atomic_is_glibc_not_redhat(cascade):
    lin = cascade.lineage('fedora_atomic')
    assert 'glibc_linux' in lin and 'linux' in lin
    assert 'redhat' not in lin and 'fedora' not in lin   # dnf-only bindings must not apply
    assert cascade.native('fedora_atomic') == 'brew'
    assert 'flatpak' in cascade.provides('fedora_atomic')  # pre-installed -> env-satisfied


def test_fedora_atomic_routes_cli_to_brew_apps_to_flatpak():
    r = Resolver(ROUTES, 'fedora_atomic', '40')
    assert 'brew\\btop' in r.resolve_names(['btop'])          # native -> brew
    # chrome resolves to flatpak, and its flatpak dep is env-provided (no brew\flatpak unit)
    chrome = r.resolve_names(['chrome'])
    assert 'flatpak\\chrome' in chrome
    assert not any(k.startswith('brew\\flatpak') for k in chrome)
    # ffmpeg takes the generic binding -> brew, never RPM Fusion (outside the redhat subtree)
    ff = r.resolve_names(['ffmpeg'])
    assert 'brew\\ffmpeg' in ff
    assert not any('rpmfusion' in k for k in ff)


def test_fedora_atomic_audit_fixes():
    R = 'routes.hu'
    def unit(name):
        return list(Resolver(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'),
                             'fedora_atomic', '40').resolve_names([name]))
    # GUI apps -> flatpak (their brew names are mac-only casks that would fail on Linux)
    for app, key in [('firefox', 'flatpak\\firefox'), ('blender', 'flatpak\\blender'),
                     ('vlc', 'flatpak\\vlc'), ('kicad', 'flatpak\\kicad'),
                     ('libreoffice', 'flatpak\\libreoffice'), ('vscode', 'flatpak\\vscode')]:
        assert key in unit(app), (app, unit(app))
    # neovim -> brew (a real formula, cleaner than its fuse2-needing AppImage)
    assert 'brew\\neovim' in unit('neovim')
    # brew name-map keys: cargo is Homebrew's `rust`, dig is `bind`
    cargo = Resolver('routes.hu', 'fedora_atomic', '40').resolve_names(['cargo'])
    assert cargo['brew\\cargo'].name == 'rust'
    dig = Resolver('routes.hu', 'fedora_atomic', '40').resolve_names(['dig'])
    assert dig['brew\\dig'].name == 'bind'
