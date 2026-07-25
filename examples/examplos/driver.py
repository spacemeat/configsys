'''driver.py — the `toybox` driver for ExamplOS (a fictional distro, the reference code plugin).

ExamplOS isn't a real operating system — it exists so this example can't rot against a real
distro's package renames, and so nobody tries to install it. `toybox` is its equally-fictional
package manager. The point isn't the commands; it's the SHAPE: subclass Driver, implement the op
set, export DRIVERS, and the trusted loader registers it. Copy this to wrap a real manager.

The op set the base class expects (all optional — implement what your manager supports):
    read  (no root): get_version, get_latest, is_locked
    write (sudo):    install, uninstall, upgrade, set_version, lock, unlock

Everything comes from the frozen ABI surface — import nothing else from configsys:
    from configsys.plugins import Driver, Result
'''

from configsys.plugins import Driver, Result   # noqa: F401 (Result re-exported for plugin authors)


def _version_of(stdout, name):
    '''`toybox show <pkg>` prints one "<name> <version>" line per matching package. Return the
    version for EXACTLY `name` — an exact field match, so `widget-extras` never answers a query
    for `widget` (the classic trap: a substring/prefix package satisfying the wrong lookup).'''
    for line in stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == name:
            return fields[1]
    return None


class Toybox(Driver):
    name = 'toybox'
    privileged = True               # writes go through sudo
    default_scope = 'system'        # toybox packages are system-wide (a fixed scope)

    # -- read (no root needed) -------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'toybox show {rc.name}')
        return _version_of(r.stdout, rc.name) if r.ok else None

    def get_latest(self, rc):
        r = self.runner.run(f'toybox show --remote {rc.name}')   # --remote = candidate in the repo
        return _version_of(r.stdout, rc.name) if r.ok else None

    def is_locked(self, rc):
        # `toybox status <pkg>` prints "pinned" when the package is held at its version.
        r = self.runner.run(f'toybox status {rc.name}')
        return bool(r.ok and r.stdout.strip() == 'pinned')

    # -- mutate (under sudo) ---------------------------------------------

    def install(self, rc):
        return self.runner.run(f'toybox add {rc.name}', sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'toybox rm {rc.name}', sudo=True, capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'toybox up {rc.name}', sudo=True, capture=False)

    def set_version(self, rc, version):
        return self.runner.run(f'toybox add {rc.name}@{version}', sudo=True, capture=False)

    def lock(self, rc):
        return self.runner.run(f'toybox pin {rc.name}', sudo=True)

    def unlock(self, rc):
        return self.runner.run(f'toybox unpin {rc.name}', sudo=True)


# The registration export the trusted loader reads (docs/plugins.md §7a): a list of Driver
# subclasses. List every class your plugin ships; here there's just the one.
DRIVERS = [Toybox]
