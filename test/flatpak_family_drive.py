'''Drive the Flatpak family against a synthetic component, for integration tests.

Lets the shell harness exercise real flatpak ops without adding a throwaway app to
the production routes. Usage:

    python test/flatpak_family_drive.py <op> <appid> [hub]

ops: install | uninstall | upgrade | lock | unlock | version | locked
Exits with the op's return code; `version`/`locked` print a line and exit 0.
'''

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configsys.componentObj import ResolvedComponent  # noqa: E402
from configsys.families.flatpak import Flatpak  # noqa: E402
from configsys.runner import Runner  # noqa: E402


def main():
    op, appid = sys.argv[1], sys.argv[2]
    hub = sys.argv[3] if len(sys.argv) > 3 else 'flathub'
    rc = ResolvedComponent(key=f'flatpak\\{appid}', family='flatpak', comp=appid,
                           fields={'hub': hub, 'name': appid})
    fam = Flatpak(Runner(pretend=False))

    if op == 'version':
        print(fam.get_version(rc) or '')
        return 0
    if op == 'locked':
        print('yes' if fam.is_locked(rc) else 'no')
        return 0

    dispatch = {
        'install': fam.install, 'uninstall': fam.uninstall,
        'upgrade': fam.upgrade, 'lock': fam.lock, 'unlock': fam.unlock,
    }
    if op not in dispatch:
        print(f'unknown op: {op}', file=sys.stderr)
        return 2
    return dispatch[op](rc).returncode


if __name__ == '__main__':
    sys.exit(main())
