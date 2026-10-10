'''service.py — the service driver: enable a system service under the machine's init.

A component `{ via: service  unit: <name> }` enables (and starts, unless `start: false`) a system
service on install, and disables + stops it on uninstall. "Installed" = the service is enabled.
These are system services, so mutations run under sudo. Two inits are supported:

  * systemd — `systemctl enable [--now] <unit>`; enabled = `systemctl is-enabled`.
  * runit (Void Linux) — a service is a directory /etc/sv/<name>; enabling it is a symlink into
    /var/service (runsvdir then starts it), a `down` file keeps it from auto-starting (`start:
    false`), disabling is `sv down` + removing the link. runit names often differ from systemd's
    (mariadb's is `mysqld`), so a binding may say `runit: <name>` or a list of them (libvirt
    needs libvirtd + virtlockd + virtlogd); a name may be a glob for a versioned service dir
    (`postgresql[0-9]*` -> postgresql18) — the highest match wins. Default: the unit minus a
    `.service` suffix. A systemd-only `.socket` unit has no runit counterpart and declines there.

Elsewhere (WSL, some containers) install prints a note and no-ops rather than failing.

Post-install as composition: a package that needs its daemon running lists a `{ via: service }`
component alongside itself (ordered with `requires:` so the package installs first).
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_HAS_SYSTEMD = 'command -v systemctl >/dev/null 2>&1'
_HAS_RUNIT = '[ -d /var/service ]'
# the LAST match of /etc/sv/<pattern> (sorted -> the highest versioned dir), or fail. The pattern is
# deliberately unquoted so a glob expands; names are validated to a safe charset first.
_RS = '_rs() { for d in /etc/sv/$1; do :; done; [ -d "$d" ] && basename "$d"; }; '
_SAFE = re.compile(r'^[A-Za-z0-9_.@*?\[\]-]+$')


class Service(Driver):
    name = 'service'
    targets_version = False   # a service enablement has no version
    privileged = True
    default_scope = 'system'   # system units (fixed)

    @staticmethod
    def _unit(rc):
        return rc.fields.get('unit') or rc.comp

    def _runit(self, rc):
        '''The runit service name(s) for this binding, or [] when it has none (a .socket unit).'''
        names = rc.fields.get('runit')
        if names is None:
            u = self._unit(rc)
            if u.endswith('.socket'):
                return []
            names = [u[:-len('.service')] if u.endswith('.service') else u]
        names = [names] if isinstance(names, str) else [str(n) for n in names]
        bad = [n for n in names if not _SAFE.match(n)]
        if bad:
            raise ValueError(f'service {rc.comp}: unsafe runit name(s) {bad}')
        return names

    def _runit_script(self, rc, per_service, missing):
        '''A shell loop over the binding's runit services: `per_service` runs with $s = the resolved
        service name; `missing` runs (and the loop stops) for a name with no /etc/sv dir.'''
        names = ' '.join(self._runit(rc))
        return f'{_RS}for n in {names}; do s=$(_rs "$n") || {{ {missing}; }}; {per_service}; done'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        u = shlex.quote(self._unit(rc))
        runit = (self._runit_script(rc, '[ -e "/var/service/$s" ] || exit 1', 'exit 1')
                 if self._runit(rc) else 'exit 1')
        r = self.runner.run(f'if {_HAS_SYSTEMD}; then systemctl is-enabled --quiet {u}; '
                            f'elif {_HAS_RUNIT}; then ( {runit} ); else exit 1; fi')
        return 'enabled' if r.ok else None

    def get_latest(self, rc):
        return 'enabled'   # the target state

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        u = shlex.quote(self._unit(rc))
        enable = 'systemctl enable ' + ('' if rc.fields.get('start') is False else '--now ') + u
        if self._runit(rc):
            down = 'touch "/etc/sv/$s/down"; ' if rc.fields.get('start') is False else ''
            runit = self._runit_script(
                rc, f'{down}ln -sfn "/etc/sv/$s" "/var/service/$s"',
                'echo "configsys: no runit service /etc/sv/$n (is its package installed?)" >&2; exit 1')
        else:
            runit = (f'echo "configsys: {self._unit(rc)} is a systemd-only unit; runit has no '
                     f'counterpart" >&2; exit 1')
        cmd = (f'if {_HAS_SYSTEMD}; then {enable}; '
               f'elif {_HAS_RUNIT}; then ( {runit} ); '
               f'else echo "configsys: no systemd or runit here; skipped {self._unit(rc)}" >&2; fi')
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        u = shlex.quote(self._unit(rc))
        runit = (self._runit_script(rc, 'sv down "$s" 2>/dev/null; rm -f "/var/service/$s"', 'continue')
                 if self._runit(rc) else ':')
        return self.runner.run(f'if {_HAS_SYSTEMD}; then systemctl disable --now {u}; '
                               f'elif {_HAS_RUNIT}; then ( {runit} ); fi',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # idempotent re-enable

    def set_version(self, rc, version):
        return self.install(rc)

    def location(self, rc):
        runit = self._runit(rc)
        where = f'systemd unit: {self._unit(rc)}'
        return where + (f' / runit: /etc/sv/{", ".join(runit)}' if runit else '')
