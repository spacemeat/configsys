'''osdetect.py — determine which routes.hu OS block applies to this machine.

Reads /etc/os-release ID (and ID_LIKE as fallback context) and maps it to the
routes block name. The names differ in one important case: os-release reports
`ID=pop` for Pop!_OS, while the routes block is named `pop_os!`.

CONFIGSYS_OS overrides detection entirely (used by tests and to force a cascade
without being on that distro).
'''

import os


# os-release ID -> routes.hu block name, where they differ.
_ALIASES = {
    'pop': 'pop_os!',
}


class OsInfo:
    def __init__(self, id, id_like, block):
        self.id = id
        self.id_like = list(id_like)
        self.block = block

    def __repr__(self):
        return f'OsInfo(id={self.id!r}, id_like={self.id_like}, block={self.block!r})'


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
    if forced:
        return OsInfo(id=forced, id_like=[], block=block_for_id(forced))

    data = _parse_os_release(os_release_path)
    id = data.get('ID', '').strip()
    id_like = data.get('ID_LIKE', '').split()
    return OsInfo(id=id, id_like=id_like, block=block_for_id(id))
