'''service.py — the service driver: manage a systemd unit.

A component `{ via: service  unit: <name> }` enables (and starts, unless `start: false`) a
systemd unit on install, and disables + stops it on uninstall. "Installed" = the unit is
enabled. These are system units, so mutations run under sudo. Where systemd is absent (WSL,
some containers) install prints a note and no-ops rather than failing — a soft degrade.

Post-install as composition: a package that needs its daemon running lists a `{ via: service }`
component alongside itself (ordered with `requires:` so the package installs first).
'''

import shlex

from ..driver import Driver
from ..runner import Result

_HAS_SYSTEMD = 'command -v systemctl >/dev/null 2>&1'


class Service(Driver):
    name = 'service'
    privileged = True
    default_scope = 'system'   # system units (fixed)

    @staticmethod
    def _unit(rc):
        return rc.fields.get('unit') or rc.comp

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        u = shlex.quote(self._unit(rc))
        r = self.runner.run(f'{_HAS_SYSTEMD} && systemctl is-enabled --quiet {u}')
        return 'enabled' if r.ok else None

    def get_latest(self, rc):
        return 'enabled'   # the target state

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        u = shlex.quote(self._unit(rc))
        enable = 'systemctl enable ' + ('' if rc.fields.get('start') is False else '--now ') + u
        cmd = (f'if {_HAS_SYSTEMD}; then {enable}; '
               f'else echo "configsys: no systemd here; skipped {self._unit(rc)}" >&2; fi')
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        u = shlex.quote(self._unit(rc))
        return self.runner.run(f'if {_HAS_SYSTEMD}; then systemctl disable --now {u}; fi',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # idempotent re-enable

    def set_version(self, rc, version):
        return self.install(rc)

    def lock(self, rc):
        return Result('(service lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(service unlock recorded in ledger)', 0)

    def location(self, rc):
        return f'systemd unit: {self._unit(rc)}'
