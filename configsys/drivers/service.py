'''service.py — the service driver: enable a system service under the machine's init.

A component `{ via: service  unit: <name> }` enables (and starts, unless `start: false`) a system
service on install, and disables + stops it on uninstall. "Installed" = the service is enabled.
These are system services, so mutations run as root (the runner's escalator). Each init system is
one `Init` class; the driver builds ONE shell command that asks each init in turn whether it is the
machine's (`present`, first match wins — systemd, then runit, then dinit) and runs that init's op:

  * Systemd — `systemctl enable [--now] <unit>`; enabled = `systemctl is-enabled`.
  * Runit (Void Linux) — a service is a directory /etc/sv/<name>; enabling it is a symlink into
    /var/service (runsvdir then starts it), a `down` file keeps it from auto-starting (`start:
    false`), disabling is `sv down` + removing the link.
  * Dinit (Chimera Linux) — a service is a file in /etc/dinit.d or /usr/lib/dinit.d; enabled = a
    link in the boot service's waits-for.d (/etc/dinit.d/boot.d — or the distro's own defaults in
    /usr/lib/dinit.d/boot.d), made by `dinitctl enable` (which also starts it) and removed by
    `dinitctl disable` (which also stops it). With no running dinit (a chroot, a container) the
    link is made `--offline` and the service starts at the next boot; `start: false` always links
    offline, so nothing starts.

Runit and dinit name services their own way (mariadb's runit service is `mysqld`, Docker's dinit
service is `dockerd`), so a binding may say `runit: <name>` / `dinit: <name>` or a list of them
(libvirt needs several daemons); a name may be a glob for a versioned service (`postgresql[0-9]*`
-> postgresql18) — the highest match wins. Default: the unit minus a `.service` suffix. A
systemd-only `.socket` unit has no counterpart on either and declines there.

Elsewhere (WSL, some containers, OpenRC) install prints a note and no-ops rather than failing.

Post-install as composition: a package that needs its daemon running lists a `{ via: service }`
component alongside itself (ordered with `requires:` so the package installs first).
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_SAFE = re.compile(r'^[A-Za-z0-9_.@*?\[\]-]+$')
# a systemd unit name (its `\x2d` escapes included); `..` is refused separately (drivers-lang-25)
_UNIT = re.compile(r'^[A-Za-z0-9:_.@\\-]+$')


def _safe_name(n):
    '''A runit/dinit service name: the charset above, at least one letter/digit (a bare `*` would
    enable every service there is), and no `..`.'''
    return bool(_SAFE.match(n)) and any(c.isalnum() for c in n) and '..' not in n


def _note(msg):
    '''`printf` of a fixed message to stderr — the message one quoted token, never shell text.'''
    return f"printf '%s\\n' {shlex.quote(msg)} >&2"


def unit_name(rc):
    '''The binding's systemd unit (default: the component's name), validated.'''
    u = str(rc.fields.get('unit') or rc.comp)
    if not _UNIT.match(u) or '..' in u:
        raise ValueError(f'service {rc.comp}: unsafe unit name {u!r}')
    return u


class Init:
    '''One init system. `present` is a shell test that holds where this init runs the machine; the
    op methods return the shell for one op on a binding (validated before any command is built —
    an unsafe name raises ValueError).'''
    name = ''
    present = ''

    def enabled(self, rc):
        '''Exits 0 iff the binding's service(s) are enabled.'''
        raise NotImplementedError

    def enable(self, rc, start):
        raise NotImplementedError

    def disable(self, rc):
        raise NotImplementedError

    def where(self, rc):
        '''The `location` fragment for this init, or None when it has no counterpart.'''
        raise NotImplementedError


class Systemd(Init):
    name = 'systemd'
    present = 'command -v systemctl >/dev/null 2>&1'

    def enabled(self, rc):
        return f'systemctl is-enabled --quiet {shlex.quote(unit_name(rc))}'

    def enable(self, rc, start):
        return 'systemctl enable ' + ('--now ' if start else '') + shlex.quote(unit_name(rc))

    def disable(self, rc):
        return f'systemctl disable --now {shlex.quote(unit_name(rc))}'

    def where(self, rc):
        return f'systemd unit: {unit_name(rc)}'


class DirInit(Init):
    '''An init whose services are entries in a directory (runit, dinit): the binding names them in
    its own field (`runit:` / `dinit:`), and each op is a shell loop over the resolved names.'''
    field = ''
    dirs = ()          # where a service's definition lives, searched in order (the last match wins)
    test = '-e'        # what a definition is (`-d` a directory)

    def names(self, rc):
        '''This init's service name(s) for the binding, or [] when it has none (a .socket unit).'''
        names = rc.fields.get(self.field)
        if names is None:
            u = unit_name(rc)
            if u.endswith('.socket'):
                return []
            names = [u[:-len('.service')] if u.endswith('.service') else u]
        names = [names] if isinstance(names, str) else [str(n) for n in names]
        bad = [n for n in names if not _safe_name(n)]
        if bad:
            raise ValueError(f'service {rc.comp}: unsafe {self.name} name(s) {bad}')
        return names

    def _loop(self, rc, per_service, missing):
        '''A subshell looping over the binding's services: `per_service` runs with $s = the resolved
        name; `missing` runs (and the loop stops) for a name with no definition. The name patterns
        are deliberately unquoted so a glob expands; they were validated to a safe charset.'''
        found = ' '.join(f'{d}/$1' for d in self.dirs)
        resolve = (f'_rs() {{ r=; for f in {found}; do [ {self.test} "$f" ] && r=$f; done; '
                   f'[ -n "$r" ] && basename "$r"; }}; ')
        names = ' '.join(self.names(rc))
        return f'( {resolve}for n in {names}; do s=$(_rs "$n") || {{ {missing}; }}; {per_service}; done )'

    def _missing(self):
        return f'echo "configsys: no {self.name} service $n (is its package installed?)" >&2; exit 1'

    def enabled(self, rc):
        if not self.names(rc):
            return 'exit 1'
        return self._loop(rc, self._is_enabled, 'exit 1')

    def enable(self, rc, start):
        if not self.names(rc):
            return (_note(f'configsys: {unit_name(rc)} is a systemd-only unit; {self.name} has no '
                          f'counterpart') + '; exit 1')
        return self._loop(rc, self._enable(start), self._missing())

    def disable(self, rc):
        if not self.names(rc):
            return ':'
        return self._loop(rc, self._disable, 'continue')

    def where(self, rc):
        names = self.names(rc)
        return f'{self.name}: {self.dirs[0]}/{", ".join(names)}' if names else None


class Runit(DirInit):
    name = 'runit'
    field = 'runit'
    present = '[ -d /var/service ]'
    dirs = ('/etc/sv',)
    test = '-d'
    _is_enabled = '[ -e "/var/service/$s" ] || exit 1'
    _disable = 'sv down "$s" 2>/dev/null; rm -f "/var/service/$s"'

    def _enable(self, start):
        down = '' if start else 'touch "/etc/sv/$s/down"; '
        return f'{down}ln -sfn "/etc/sv/$s" "/var/service/$s"'


class Dinit(DirInit):
    name = 'dinit'
    field = 'dinit'
    present = 'command -v dinitctl >/dev/null 2>&1 && [ -d /etc/dinit.d ]'
    dirs = ('/etc/dinit.d', '/usr/lib/dinit.d')
    test = '-f'
    _linked = '[ -e "/etc/dinit.d/boot.d/$s" ]'          # enabled by the admin (what we add/remove)
    _running = '[ -S /run/dinitctl ]'                     # the system dinit's control socket
    _is_enabled = f'{{ {_linked} || [ -e "/usr/lib/dinit.d/boot.d/$s" ]; }} || exit 1'
    _disable = (f'if {_linked}; then if {_running}; then dinitctl disable "$s"; '
                f'else dinitctl --offline disable "$s"; fi; fi')

    def where(self, rc):
        names = self.names(rc)
        return f'dinit service: {", ".join(names)}' if names else None   # in either service dir

    def _enable(self, start):
        # `dinitctl enable` refuses a service already enabled, so link only when it isn't
        offline = f'{self._linked} || dinitctl --offline enable "$s"'
        if not start:
            return offline
        later = 'echo "configsys: dinit isn\'t running; $s starts at the next boot" >&2'
        return (f'if {self._running}; then if {self._linked}; then dinitctl start "$s"; '
                f'else dinitctl enable "$s"; fi; else {offline}; {later}; fi')


INITS = (Systemd(), Runit(), Dinit())


class Service(Driver):
    name = 'service'
    targets_version = False   # a service enablement has no version
    privileged = True
    default_scope = 'system'   # system units (fixed)

    @staticmethod
    def _dispatch(op, otherwise=None):
        '''`if <init1 present>; then <op(init1)>; elif …; [else <otherwise>;] fi`.'''
        branches = '; '.join(f'{"if" if i == 0 else "elif"} {init.present}; then {op(init)}'
                             for i, init in enumerate(INITS))
        return branches + (f'; else {otherwise}' if otherwise else '') + '; fi'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        try:
            cmd = self._dispatch(lambda init: init.enabled(rc), 'exit 1')
        except ValueError:
            return None
        return 'enabled' if self.runner.run(cmd).ok else None

    def get_latest(self, rc):
        return 'enabled'   # the target state

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        start = rc.fields.get('start') is not False
        try:
            inits = ', '.join(i.name for i in INITS[:-1]) + f' or {INITS[-1].name}'
            cmd = self._dispatch(lambda init: init.enable(rc, start),
                                 _note(f'configsys: no {inits} here; skipped {unit_name(rc)}'))
        except ValueError as e:                      # an unsafe unit/service name: no command built
            return Result.fail(str(e))
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        try:
            cmd = self._dispatch(lambda init: init.disable(rc))
        except ValueError as e:
            return Result.fail(str(e))
        return self.runner.run(cmd, sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)   # idempotent re-enable

    def set_version(self, rc, version):
        return self.install(rc)

    def location(self, rc):
        return ' / '.join(w for w in (init.where(rc) for init in INITS) if w)
