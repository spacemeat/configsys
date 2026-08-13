'''drivers — registry of install-medium implementations.

Ships the native managers (apt, dnf, pacman, aur) plus tarball, native-pkg-file
(install an upstream release's .deb/.rpm/pkg with the OS package tool), flatpak,
appImage, dotfiles, font, cargo, brew, pip, pipx, rpm-ostree, the
gcc/clang/gcc-toolset toolchains, and the post-install primitives service
(systemd) and group (usermod). An unregistered driver name still returns None
here so InstallState degrades gracefully instead of crashing.
'''

from .appImage import AppImage
from .apk import Apk
from .apt import Apt
from .aur import Aur
from .brew import Brew
from .cabal import Cabal
from .cargo import Cargo
from .clang import Clang
from .font import Font
from .dnf import Dnf
from .dotfiles import DotFiles
from .flatpak import Flatpak
from .snap import Snap
from .gcc import Gcc
from .gem import Gem
from .gcc_toolset import GccToolset
from .go_install import GoInstall
from .group import Group
from .luarocks import LuaRocks
from .native_pkg_file import NativePkgFile
from .npm import Npm
from .opam import Opam
from .pacman import Pacman
from .pip import Pip
from .pipx import Pipx
from .pyenv import Pyenv
from .rpm_ostree import RpmOstree
from .script import Script
from .service import Service
from .source import Source
from .tarball import Tarball
from .zypper import Zypper

_REGISTRY = {
    Apt.name: Apt,
    Dnf.name: Dnf,
    Pacman.name: Pacman,
    Apk.name: Apk,
    Zypper.name: Zypper,
    Aur.name: Aur,
    Brew.name: Brew,
    Tarball.name: Tarball,
    NativePkgFile.name: NativePkgFile,
    Flatpak.name: Flatpak,
    Snap.name: Snap,
    AppImage.name: AppImage,
    DotFiles.name: DotFiles,
    Font.name: Font,
    Cargo.name: Cargo,
    Npm.name: Npm,
    GoInstall.name: GoInstall,
    Gem.name: Gem,
    Opam.name: Opam,
    LuaRocks.name: LuaRocks,
    Cabal.name: Cabal,
    Gcc.name: Gcc,
    GccToolset.name: GccToolset,
    Clang.name: Clang,
    Pip.name: Pip,
    Pipx.name: Pipx,
    Pyenv.name: Pyenv,
    RpmOstree.name: RpmOstree,
    Script.name: Script,
    Source.name: Source,
    Service.name: Service,
    Group.name: Group,
}


def register_driver(cls):
    '''Register a Driver subclass under its `name`, so `via: <name>` resolves to it.
    Built-in drivers are registered above; plugins call this (via the frozen surface in
    configsys.plugins) to add their own. Returns the class (usable as a decorator).'''
    if not getattr(cls, 'name', None):
        raise ValueError(f'{cls!r} has no `name` — a Driver must set a class-level name')
    _REGISTRY[cls.name] = cls
    return cls


def get_driver(name, runner, paths=None):
    '''Instantiate the driver for `name` bound to `runner`/`paths`, or None.'''
    cls = _REGISTRY.get(name)
    return cls(runner, paths) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def scope_meta(name):
    '''(honors_scope, default_scope) for a driver — lets the UI tell a deliberate NON-DEFAULT
    scope CHOICE (a scope-honoring driver installed at a non-default scope) from a FIXED scope
    (apt is always system, cargo always user), so only the former is worth highlighting. Unknown
    driver -> (False, 'user').'''
    cls = _REGISTRY.get(name)
    if cls is None:
        return (False, 'user')
    return (bool(cls.honors_scope), cls.default_scope)


def supported_names():
    return set(_REGISTRY)
