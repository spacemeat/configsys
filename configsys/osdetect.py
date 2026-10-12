'''osdetect.py — determine which routes.hu OS block applies to this machine.

Reads /etc/os-release ID (and ID_LIKE as fallback context) and maps it to the
routes block name. The names differ in one important case: os-release reports
`ID=pop` for Pop!_OS, while the routes block is named `pop_os!`. VERSION_ID
(e.g. "22.04", "12") is also read; it feeds the `when:` version atoms during
resolution (see predicate / the routes Resolver).

Fedora Atomic / uBlue (Silverblue, Kinoite, Bazzite, Bluefin, Aurora …) report
ID=fedora but are a distinct environment; they fold into the `fedora_atomic` block
via VARIANT_ID or the ostree-booted marker (see _is_fedora_atomic).

CONFIGSYS_OS (and the `--os` flag that sets it) overrides detection entirely and bypasses the
atomic remap: `BLOCK` or `BLOCK:VERSION` (`alpine:3.24`); CONFIGSYS_OS_VERSION supplies the version
when the value names none. Detection knows nothing of routes.hu, so `settle` checks the block against
the loaded `os:` blocks once they are: a forced unknown block is an error (with near names), and a
detected distro with no block of its own routes as the first ID_LIKE entry that has one.
'''

import difflib
import os

from .errors import ConfigsysError
from .osversion import parse_version


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
    # Legacy Raspbian (Bullseye-, ID=raspbian) is the same distro as Raspberry Pi OS, renamed.
    # Bookworm+ reports ID=debian and is caught by the `pios` block's /etc/rpi-issue detect marker.
    'raspbian': 'pios',
    # KDE Linux reports ID=kde-linux; the when: DSL has no `-`
    'kde-linux': 'kde_linux',
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
    def __init__(self, id, id_like, block, version=None, forced=False):
        self.id = id
        self.id_like = list(id_like)
        self.block = block
        self.version = version or None      # VERSION_ID string, e.g. "22.04"
        self.forced = forced                # chosen by CONFIGSYS_OS / --os, not detected

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


def split_forced(value):
    '''A forced OS value -> (block-or-id, version-or-None): "alpine:3.24" -> ("alpine", "3.24"),
    "fedora" -> ("fedora", None). The `:` can't be part of a block name (the `when:` DSL has no `:`
    in an OS atom).'''
    name, sep, version = str(value).strip().partition(':')
    return name.strip(), (version.strip() or None) if sep else None


def settle(info, blocks):
    '''Make `info.block` name one of the loaded os: `blocks`, once routes are loaded (plugins add
    blocks, so this can't run at detection). Returns a one-line note when it had to fall back, else
    None; raises ConfigsysError when there is nothing to route as.
    - forced (--os / CONFIGSYS_OS) and unknown -> error naming the closest block names: a typo must
      never silently route as something else.
    - detected and unknown (a distro with no block of its own) -> the first ID_LIKE entry that has a
      block. Its VERSION_ID is on the distro's own scale, not the parent's, so the version is dropped
      (version conditions read false) rather than compared against the wrong numbering.'''
    if info.block in blocks:
        return None
    if info.forced:
        raise ConfigsysError(unknown_block_message(info.block, blocks))
    for like in info.id_like:
        block = block_for_id(like)
        if block in blocks:
            note = (f'this OS (ID={info.id}) has no os: block of its own; routing it as {block} '
                    f'(from ID_LIKE), without a version. `configsys request-os` asks for it to be added.')
            info.block, info.version = block, None
            return note
    raise ConfigsysError(
        f'this OS (ID={info.id or "unknown"}) has no os: block in routes.hu and no ID_LIKE relative '
        f'that does. Route it as a close relative with `--os <block>` (or CONFIGSYS_OS), and '
        f'`configsys request-os` asks for it to be added.')


def unknown_block_message(name, blocks):
    '''"no OS block named X" plus the closest block names.'''
    close = difflib.get_close_matches(name, sorted(blocks), n=3, cutoff=0.6)
    hint = f' Did you mean {", ".join(close)}?' if close else ''
    return (f'no OS block named "{name}" (--os / CONFIGSYS_OS).{hint} Name a block from routes.hu\'s '
            f'os: section, optionally with a version: BLOCK or BLOCK:VERSION (e.g. fedora, alpine:3.24).')


def refine(block, cascade, env=None, exists=os.path.exists):
    '''Refine a detected block using os blocks' `detect:` markers. A derivative distro that does
    NOT rebrand /etc/os-release (Proxmox VE reports ID=debian) declares
    `detect: { id: <base>  marker: <path> }` (marker may be a list). When the detected block is
    that base (or a descendant of it) and every marker exists on disk, we route to the more-
    specific block. This is the data-driven generalization of the built-in Fedora-Atomic
    ostree-marker detection — so a plugin can add a detectable OS with no code. A forced
    CONFIGSYS_OS is never second-guessed.'''
    env = os.environ if env is None else env
    if env.get('CONFIGSYS_OS'):
        return block
    for name, blk in cascade.blocks.items():
        det = (blk or {}).get('detect')
        if not isinstance(det, dict):
            continue
        base = det.get('id') or det.get('base')
        markers = det.get('marker') or det.get('markers') or []
        markers = [markers] if isinstance(markers, str) else list(markers)
        if base and not cascade.is_descendant(block, base):
            continue
        if markers and all(exists(str(m)) for m in markers):
            return name
    return block


def detect(env=None, os_release_path='/etc/os-release',
           ostree_marker='/run/ostree-booted') -> OsInfo:
    env = os.environ if env is None else env

    forced = env.get('CONFIGSYS_OS')
    forced_version = env.get('CONFIGSYS_OS_VERSION')
    if forced:
        name, version = split_forced(forced)
        version = version or forced_version
        if version is not None and parse_version(version) is None:
            raise ConfigsysError(f'"{forced}" (--os / CONFIGSYS_OS): "{version}" is not a version '
                                 f'number (expected BLOCK or BLOCK:VERSION, e.g. alpine:3.24)')
        return OsInfo(id=name, id_like=[], block=block_for_id(name), version=version, forced=True)

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
