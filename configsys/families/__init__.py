'''families — registry of install-medium implementations.

M1 ships apt and tarball. Unregistered families (flatpak/appImage/dotfiles/
debian-font) return None here so InstallState can degrade gracefully ("unsupported
family, not yet implemented") instead of crashing.
'''

from .apt import Apt
from .tarball import Tarball

_REGISTRY = {
    Apt.name: Apt,
    Tarball.name: Tarball,
}


def get_family(name, runner, paths=None):
    '''Instantiate the family for `name` bound to `runner`/`paths`, or None.'''
    cls = _REGISTRY.get(name)
    return cls(runner, paths) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def supported_names():
    return set(_REGISTRY)
