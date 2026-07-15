'''families — registry of install-medium implementations.

Ships apt, tarball, flatpak, appImage, dotfiles, and debian-font — the full set.
An unregistered family name still returns None here so InstallState degrades
gracefully instead of crashing.
'''

from .appImage import AppImage
from .apt import Apt
from .cargo import Cargo
from .clang import Clang
from .debian_font import DebianFont
from .dotfiles import DotFiles
from .flatpak import Flatpak
from .gcc import Gcc
from .pip import Pip
from .tarball import Tarball

_REGISTRY = {
    Apt.name: Apt,
    Tarball.name: Tarball,
    Flatpak.name: Flatpak,
    AppImage.name: AppImage,
    DotFiles.name: DotFiles,
    DebianFont.name: DebianFont,
    Cargo.name: Cargo,
    Gcc.name: Gcc,
    Clang.name: Clang,
    Pip.name: Pip,
}


def get_family(name, runner, paths=None):
    '''Instantiate the family for `name` bound to `runner`/`paths`, or None.'''
    cls = _REGISTRY.get(name)
    return cls(runner, paths) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def supported_names():
    return set(_REGISTRY)
