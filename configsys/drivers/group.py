'''group.py — the group driver: add the current user to a system group.

A component `{ via: group  name: <group> }` runs `usermod -aG <group> <you>` on install and
`gpasswd -d <you> <group>` on uninstall. "Installed" = you are a member — checked against the
group DB (so it reads true immediately), though a re-login is needed for it to take effect in
the running session (install says so). The group must already exist, so order this after the
package that creates it with `requires:`.

Runs under sudo; `${SUDO_USER:-$USER}` targets the real user, not root.
'''

import shlex

from ..driver import Driver
from ..runner import Result

_USER = '"${SUDO_USER:-$USER}"'   # the invoking user even under sudo


class Group(Driver):
    name = 'group'
    privileged = True
    default_scope = 'system'

    @staticmethod
    def _group(rc):
        return rc.name   # fields['name'] (normalized by the resolver), else the component name

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        g = shlex.quote(self._group(rc))
        # the current user's groups from the DB (reflects usermod without a re-login)
        r = self.runner.run(f'id -nG "$(id -un)" | tr " " "\\n" | grep -qx {g}')
        return 'member' if r.ok else None

    def get_latest(self, rc):
        return 'member'

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        g = shlex.quote(self._group(rc))
        cmd = (f'usermod -aG {g} {_USER} && '
               f'echo "configsys: added to group {self._group(rc)} — log out/in to take effect" >&2')
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        g = shlex.quote(self._group(rc))
        return self.runner.run(f'gpasswd -d {_USER} {g}', sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)

    def set_version(self, rc, version):
        return self.install(rc)

    def lock(self, rc):
        return Result('(group lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(group unlock recorded in ledger)', 0)

    def location(self, rc):
        return f'group: {self._group(rc)}'
