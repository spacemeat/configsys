'''go_install.py — the go-install driver: Go tools via `go install <pkg>@<ver>`.

User-space (binaries land in GOBIN, default ~/go/bin), no sudo. Go keeps no registry
of installed tools, so version state is read back from the binary itself with
`go version -m <bin>` (the embedded module version); uninstall is just removing the
binary. No native lock, so lock intent lives in the ledger.

The route `name` is the module PATH (e.g. github.com/x/y/cmd/z); the installed
binary is its last path segment. A `version:` spec pins it; otherwise @latest. The
go tool is the driver `requires: go`, satisfied by the `go` toolchain component.
'''

import shlex

from ..driver import Driver
from ..runner import Result

_GOBIN = '~/go/bin'


class GoInstall(Driver):
    name = 'go-install'
    privileged = False

    @staticmethod
    def _path(rc):
        return rc.name.split('@', 1)[0]  # module path, sans any @version the user wrote

    def _bin(self, rc):
        return self._path(rc).rsplit('/', 1)[-1]  # installed binary = last path segment

    def _at(self, rc, version=None):
        v = version or self.resolve_version(rc) or 'latest'
        return f'{self._path(rc)}@{v}'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'go version -m {_GOBIN}/{shlex.quote(self._bin(rc))}')
        if not r.ok or not r.stdout:
            return None
        # a `mod\t<module>\t<version>` line carries the module's version
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'mod':
                return parts[2].lstrip('v')
        return None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'go install {shlex.quote(self._at(rc))}', capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'rm -f {_GOBIN}/{shlex.quote(self._bin(rc))}', capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'go install {shlex.quote(self._path(rc))}@latest', capture=False)

    def set_version(self, rc, version):
        return self.runner.run(f'go install {shlex.quote(self._at(rc, version))}', capture=False)

    def lock(self, rc):
        return Result('(go-install lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(go-install unlock recorded in ledger)', 0)

    def location(self, rc):
        return _GOBIN
