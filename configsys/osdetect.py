'''osdetect.py — determine which routes.hu OS block applies to this machine.

Reads /etc/os-release ID (and ID_LIKE as fallback context) and maps it to the
routes block name. The names differ in one important case: os-release reports
`ID=pop` for Pop!_OS, while the routes block is named `pop_os!`. VERSION_ID
(e.g. "22.04", "12") is also read; it feeds the `when:` version atoms during
resolution (see predicate / the routes Resolver).

Fedora Atomic / uBlue (Silverblue, Kinoite, Bazzite, Bluefin, Aurora …) report
ID=fedora but are a distinct environment; they fold into the `fedora_atomic` block
via VARIANT_ID or the ostree-booted marker (see _is_fedora_atomic).

CONFIGSYS_OS overrides detection entirely (and bypasses the atomic remap);
CONFIGSYS_OS_VERSION overrides the version (both used by tests and to force a
cascade without being on that distro).
'''

import os


# os-release ID -> routes.hu block name, only where they *differ*. Distros that now have
# their own routes block (rocky/almalinux/centos -> rhel, manjaro -> arch, all via `using`)
# need no entry — block_for_id returns the ID unchanged and the cascade does the inheriting.
# Aliases remain only where the block name can't equal the ID: `!` in pop_os!, and openSUSE's
# hyphens (the `when:` DSL has no `-`, so the blocks use `_`). SteamOS (Holo) has no block of
# its own, so it still borrows arch.
_ALIASES = {
    'pop': 'pop_os!',
    'steamos': 'arch',
    'opensuse-leap': 'opensuse_leap',
    'opensuse-tumbleweed': 'opensuse_tumbleweed',
}

# Fedora Atomic desktops report ID=fedora with the variant in VARIANT_ID. uBlue images
# (Bazzite/Bluefin/Aurora) are built on these and often keep an atomic VARIANT_ID — but some
# report VARIANT_ID=fedora, so VARIANT_ID alone can't be trusted for them (ublue-os/bazzite#1249).
# The robust signal is the ostree-booted marker every rpm-ostree system has. All of these route
# identically (brew CLI / flatpak apps / rpm-ostree layering), so they fold into ONE block.
_FEDORA_ATOMIC_VARIANTS = {
    'silverblue', 'kinoite', 'sericea', 'onyx', 'sway-atomic', 'budgie-atomic',
    'cosmic-atomic', 'xfce-atomic', 'lxqt-atomic',
}
_ATOMIC_BLOCK = 'fedora_atomic'

# Blocks that are immutable/atomic ENVIRONMENTS (brew CLI / flatpak apps / rpm-ostree layering).
# Grows as more land (e.g. an openSUSE MicroOS block). Used to advise the user that atomic
# routing is new + not hardware-validated (see app.Context.diagnostics).
ATOMIC_BLOCKS = frozenset({_ATOMIC_BLOCK})


def is_atomic(block):
    '''True if `block` is one of the immutable/atomic OS environments.'''
    return block in ATOMIC_BLOCKS


def _is_fedora_atomic(id, id_like, variant, ostree_marker):
    '''True on Fedora Atomic / uBlue (immutable ostree). Fedora-family + either an atomic
    VARIANT_ID or a booted ostree deployment. --os forcing bypasses this entirely.'''
    if id != 'fedora' and 'fedora' not in id_like:
        return False
    if variant in _FEDORA_ATOMIC_VARIANTS:
        return True
    return bool(ostree_marker) and os.path.exists(ostree_marker)


class OsInfo:
    def __init__(self, id, id_like, block, version=None):
        self.id = id
        self.id_like = list(id_like)
        self.block = block
        self.version = version or None      # VERSION_ID string, e.g. "22.04"

    def __repr__(self):
        return (f'OsInfo(id={self.id!r}, id_like={self.id_like}, '
                f'block={self.block!r}, version={self.version!r})')


def _parse_os_release(path):
    data = {}
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                data[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return data


def block_for_id(id):
    return _ALIASES.get(id, id)


def detect(env=None, os_release_path='/etc/os-release',
           ostree_marker='/run/ostree-booted') -> OsInfo:
    env = os.environ if env is None else env

    forced = env.get('CONFIGSYS_OS')
    forced_version = env.get('CONFIGSYS_OS_VERSION')
    if forced:
        return OsInfo(id=forced, id_like=[], block=block_for_id(forced),
                      version=forced_version)

    data = _parse_os_release(os_release_path)
    id = data.get('ID', '').strip()
    id_like = data.get('ID_LIKE', '').split()
    version = forced_version or data.get('VERSION_ID', '').strip()
    variant = data.get('VARIANT_ID', '').strip()

    # An atomic Fedora reports ID=fedora but is a different ENVIRONMENT (read-only ostree root,
    # brew CLI / flatpak / rpm-ostree). Fold every variant into the fedora_atomic block; keep
    # the real ID/VERSION for display and `when:` version atoms.
    if _is_fedora_atomic(id, id_like, variant, ostree_marker):
        block = _ATOMIC_BLOCK
    else:
        block = block_for_id(id)
    return OsInfo(id=id, id_like=id_like, block=block, version=version)
