'''families — registry of install-medium implementations.

M1 ships apt only. Unregistered families (flatpak/appImage/dotfiles/debian-font)
return None here so InstallState can degrade gracefully ("unsupported family, not
yet implemented") instead of crashing.
'''

from .apt import Apt

_REGISTRY = {
    Apt.name: Apt,
}


def get_family(name, runner):
    '''Instantiate the family for `name` bound to `runner`, or None if unregistered.'''
    cls = _REGISTRY.get(name)
    return cls(runner) if cls is not None else None


def is_supported(name):
    return name in _REGISTRY


def supported_names():
    return set(_REGISTRY)
