'''drivers — registry of install-medium implementations.

Ships apt, tarball, flatpak, appImage, dotfiles, and debian-font — the full set.
An unregistered driver name still returns None here so InstallState degrades
gracefully instead of crashing.
'''

from .appImage import AppImage
from .apt import Apt
from .aur import Aur
from .cargo import Cargo
from .clang import Clang
from .debian_font import DebianFont
from .dnf import Dnf
from .dotfiles import DotFiles
from .flatpak import Flatpak
from .gcc import Gcc
from .gcc_toolset import GccToolset
from .pacman import Pacman
from .pip import Pip
from .pipx import Pipx
from .tarball import Tarball

_REGISTRY = {
    Apt.name: Apt,
    Dnf.name: Dnf,
    Pacman.name: Pacman,
    Aur.name: Aur,
    Tarball.name: Tarball,
    Flatpak.name: Flatpak,
    AppImage.name: AppImage,
    DotFiles.name: DotFiles,
    DebianFont.name: DebianFont,
    Cargo.name: Cargo,
    Gcc.name: Gcc,
    GccToolset.name: GccToolset,
    Clang.name: Clang,
    Pip.name: Pip,
    Pipx.name: Pipx,
}


def get_driver(name, runner, paths=None):
    '''Instantiate the driver for `name` bound to `runner`/`paths`, or None.'''
    cls = _REGISTRY.get(name)
    return cls(runner, paths) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def supported_names():
    return set(_REGISTRY)
