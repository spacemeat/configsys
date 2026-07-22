'''drivers — registry of install-medium implementations.

Ships the native managers (apt, dnf, pacman, aur) plus tarball, flatpak,
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
from .cargo import Cargo
from .clang import Clang
from .font import Font
from .dnf import Dnf
from .dotfiles import DotFiles
from .flatpak import Flatpak
from .gcc import Gcc
from .gcc_toolset import GccToolset
from .group import Group
from .pacman import Pacman
from .pip import Pip
from .pipx import Pipx
from .rpm_ostree import RpmOstree
from .service import Service
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
    Flatpak.name: Flatpak,
    AppImage.name: AppImage,
    DotFiles.name: DotFiles,
    Font.name: Font,
    Cargo.name: Cargo,
    Gcc.name: Gcc,
    GccToolset.name: GccToolset,
    Clang.name: Clang,
    Pip.name: Pip,
    Pipx.name: Pipx,
    RpmOstree.name: RpmOstree,
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


def supported_names():
    return set(_REGISTRY)
