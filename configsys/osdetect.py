'''osdetect.py — determine which routes.hu OS block applies to this machine.

Reads /etc/os-release ID (and ID_LIKE as fallback context) and maps it to the
routes block name. The names differ in one important case: os-release reports
`ID=pop` for Pop!_OS, while the routes block is named `pop_os!`. VERSION_ID
(e.g. "22.04", "12") is also read; it feeds the `when:` version atoms during
resolution (see predicate / the routes Resolver).

CONFIGSYS_OS overrides detection entirely; CONFIGSYS_OS_VERSION overrides the
version (both used by tests and to force a cascade without being on that distro).
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


def detect(env=None, os_release_path='/etc/os-release') -> OsInfo:
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
    return OsInfo(id=id, id_like=id_like, block=block_for_id(id), version=version)
