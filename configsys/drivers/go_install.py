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
# Prefer a configsys-managed Go toolchain (the `go` tarball installs under $CONFIGSYS_SDK_DIR/go) over
# a system `go`. The non-interactive runner shell doesn't source the PATH glue, so a bare `go install`
# would run an old /usr/bin/go and choke on a modern module's go.mod ("invalid go version '1.25.0'").
# If no tarball go is installed, the dir simply doesn't exist and PATH falls through to the system go.
_GO_PATH = '${CONFIGSYS_SDK_DIR:-$HOME/sdks}/go/bin'


class GoInstall(Driver):
    name = 'go-install'
    privileged = False

    @staticmethod
    def _path(rc):
        return rc.name.split('@', 1)[0]  # module path, sans any @version the user wrote

    def _bin(self, rc):
        return self._path(rc).rsplit('/', 1)[-1]  # installed binary = last path segment

    def index_key(self, rc):
        # the installed_index is keyed by the binary's embedded install `path`, which is the module
        # path SANS any @version the route wrote — align the batch lookup to that, not raw rc.name.
        return self._path(rc)

    def _at(self, rc, version=None):
        v = version or self.resolve_version(rc) or 'latest'
        return f'{self._path(rc)}@{v}'

    # -- read -------------------------------------------------------------

    def installed_index(self):
        '''{module-path: version} from ONE `go version -m <GOBIN>` over every installed binary — the
        base batch_index enumerates once instead of a `go version -m <bin>` call per tool during
        inspect. Go keeps no registry, so this reads each binary's embedded module info: a block
        headed by "<bin>: goX.Y" carries `\tpath\t<pkg>` (the install path = the route `name`, the
        default index_key) and `\tmod\t<module>\t<version>`.'''
        r = self.runner.run(f'go version -m {_GOBIN}')
        if not r.ok:
            return None
        idx = {}
        path = None
        for line in r.stdout.splitlines():
            if line and line == line.lstrip():
                path = None                           # a new "<bin>: goX.Y" header — reset the block
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[0] == 'path':
                path = parts[1]
            elif len(parts) >= 3 and parts[0] == 'mod' and path is not None:
                idx[path] = parts[2].lstrip('v')      # key by the install path, matching index_key
        return idx

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)          # answer from the one `go version -m` when batched
        if hit:
            return ver
        r = self.runner.run(f'go version -m {_GOBIN}/{shlex.quote(self._bin(rc))}')
        if not r.ok or not r.stdout:
            return None
        # a `mod\t<module>\t<version>` line carries the module's version
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'mod':
                return parts[2].lstrip('v')
        return None

    # -- mutate -----------------------------------------------------------

    def _go_install(self, spec):
        # run `go install` with a configsys-managed go (if any) ahead of the system one on PATH
        return self.runner.run(f'PATH="{_GO_PATH}:$PATH" go install {shlex.quote(spec)}',
                               capture=False)

    def install(self, rc):
        return self._go_install(self._at(rc))

    def uninstall(self, rc):
        return self.runner.run(f'rm -f {_GOBIN}/{shlex.quote(self._bin(rc))}', capture=False)

    def upgrade(self, rc):
        return self._go_install(f'{self._path(rc)}@latest')

    def set_version(self, rc, version):
        return self._go_install(self._at(rc, version))

    def location(self, rc):
        return _GOBIN
