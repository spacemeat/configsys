'''families — registry of install-medium implementations.

Ships apt, tarball, flatpak, and appImage. Unregistered families (dotfiles/
debian-font) return None here so InstallState can degrade gracefully ("unsupported
family, not yet implemented") instead of crashing.
'''

from .appImage import AppImage
from .apt import Apt
from .flatpak import Flatpak
from .tarball import Tarball

_REGISTRY = {
    Apt.name: Apt,
    Tarball.name: Tarball,
    Flatpak.name: Flatpak,
    AppImage.name: AppImage,
}


def get_family(name, runner, paths=None):
    '''Instantiate the family for `name` bound to `runner`/`paths`, or None.'''
    cls = _REGISTRY.get(name)
    return cls(runner, paths) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def supported_names():
    return set(_REGISTRY)
