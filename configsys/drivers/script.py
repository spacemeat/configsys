'''script.py — the script driver: install a tool via its declared shell commands.

For tools shipped as an installer script (SDKMAN, rustup, nvm, the docker convenience
script, vendor `curl | bash` installers). The component DECLARES its lifecycle as data,
so the black box is explicit in the route rather than hidden in driver code:

  install-cmd     (required) shell command that installs the tool
  version-cmd     (optional) command whose output reports the installed version;
                  absent / failing / empty output  =>  "not installed"
  version-re      (optional) regex whose group 1 is the version inside version-cmd output
  uninstall-cmd   (optional) command that removes it. ABSENT is allowed — configsys does
                  NOT block the install; it just warns it can't cleanly remove the tool
                  later (surfaced up front by `configsys check`, and again at uninstall).
  upgrade-cmd     (optional) defaults to re-running install-cmd
  set-version-cmd (optional) command with $VERSION substituted; absent => pinning unsupported
  location        (optional) human-readable install path for display

Runs userland (no sudo — a script needing root bakes it into its own command). Commands
run through the runner's `bash -c`, so pipes and `source` work. NOTE: piping a remote
script to a shell is a trust decision; it lives in your own config — pin URLs/checksums in
the command as you see fit. No native version lock — lock intent lives in the ledger.
'''

import re

from ..driver import Driver
from ..runner import Result


class Script(Driver):
    name = 'script'
    privileged = False

    @staticmethod
    def _cmd(rc, key):
        return rc.fields.get(key)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        vc = self._cmd(rc, 'version-cmd')
        if not vc:
            return None                    # no way to tell; treated as unknown/not-installed
        r = self.runner.run(vc)
        out = (r.stdout or '').strip()
        if not r.ok or not out:
            return None
        rex = rc.fields.get('version-re')
        if rex:
            m = re.search(rex, out)
            return m.group(1) if m else None
        return out.splitlines()[0].strip()

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        cmd = self._cmd(rc, 'install-cmd')
        if not cmd:
            return Result('(script: no install-cmd in route)', 1)
        return self.runner.run(cmd, capture=False)

    def uninstall(self, rc):
        cmd = self._cmd(rc, 'uninstall-cmd')
        if cmd:
            return self.runner.run(cmd, capture=False)
        # warn, don't gatekeep: configsys can't clean up a script that declares no removal
        return Result(f'⚠ "{rc.comp}" declares no uninstall-cmd — left in place; '
                      f'remove it manually.', 0)

    def upgrade(self, rc):
        cmd = self._cmd(rc, 'upgrade-cmd') or self._cmd(rc, 'install-cmd')
        if not cmd:
            return Result('(script: no upgrade-cmd/install-cmd in route)', 1)
        return self.runner.run(cmd, capture=False)

    def set_version(self, rc, version):
        cmd = self._cmd(rc, 'set-version-cmd')
        if not cmd:
            return Result(f'⚠ "{rc.comp}" declares no set-version-cmd; version pinning '
                          f'is unsupported for this script.', 1)
        return self.runner.run(cmd.replace('$VERSION', version), capture=False)

    def lock(self, rc):
        return Result('(script lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(script unlock recorded in ledger)', 0)

    def location(self, rc):
        return rc.fields.get('location')
