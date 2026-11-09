'''go_install.py — the go-install driver: Go tools via `go install <pkg>@<ver>`.

User-space (binaries land in GOBIN, default ~/go/bin), no sudo. Go keeps no registry
of installed tools, so version state is read back from the binary itself with
`go version -m <bin>` (the embedded module version); uninstall is just removing the
binary. No native lock, so lock intent lives in the ledger.

The route `name` is the module PATH (e.g. github.com/x/y/cmd/z); the installed
binary is its last path segment. A `version:` spec pins it; otherwise @latest. The
go tool is the driver `requires: go`, satisfied by the `go` toolchain component.

`checkout: true` (binding field): build from a git CHECKOUT of the module instead of
`go install <pkg>@<ver>`. `go install pkg@version` refuses a module whose go.mod carries
`replace` directives ("must not contain directives that would cause it to be interpreted
differently than if it were the main module"); built inside its own checkout the module
IS the main module, so they apply. The version is still the proxy's (@latest, or the
`version:` spec): a pseudo-version checks out its commit, a release its `v` tag. Go
(>= 1.24) stamps the main module's version from VCS, so the binary reports the same
pseudo-version the proxy does and get_version / get_latest compare as usual. `name:`
must be the module root (the main package at its top); `repo:` overrides the clone URL
(default https://<name>). Needs git — give the binding `requires: git`.
'''

import re
import shlex

from ..runner import Result
from ._module import ModuleDriver

_GOBIN = '~/go/bin'
# Prefer a configsys-managed Go toolchain (the `go` tarball installs under $CONFIGSYS_SDK_DIR/go) over
# a system `go`. The non-interactive runner shell doesn't source the PATH glue, so a bare `go install`
# would run an old /usr/bin/go and choke on a modern module's go.mod ("invalid go version '1.25.0'").
# If no tarball go is installed, the dir simply doesn't exist and PATH falls through to the system go.
# The READS (`go version -m`) need it too: with go ONLY from the tarball (a go>=X floor's advice), a
# bare `go` isn't found and every go-installed tool read "not installed".
_GO_PATH = '${CONFIGSYS_SDK_DIR:-$HOME/sdks}/go/bin'

# a Go pseudo-version's trailing `<yyyymmddhhmmss>-<12-hex commit>` (v0.0.0-20261020010606-2c8d24d94015)
_PSEUDO_RE = re.compile(r'\d{14}-([0-9a-f]{12})$')


class GoInstall(ModuleDriver):
    name = 'go-install'
    TOOL = f'PATH="{_GO_PATH}:$PATH" go'
    LIST_CMD = '{tool} version -m ' + _GOBIN
    BIN_DIR = _GOBIN

    @staticmethod
    def module(rc):
        # the module path, sans any @version the user wrote — also the index key: installed_index is
        # keyed by each binary's embedded install `path`
        return rc.name.split('@', 1)[0]

    _path = module

    def _bin(self, rc):
        return self._path(rc).rsplit('/', 1)[-1]  # installed binary = last path segment

    def _at(self, rc, version=None):
        v = version or self.resolve_version(rc) or 'latest'
        return f'{self._path(rc)}@{v}'

    # -- read -------------------------------------------------------------

    def parse_list(self, stdout):
        '''{module-path: version} from ONE `go version -m <GOBIN>` over every installed binary — the
        base batch_index enumerates once instead of a `go version -m <bin>` call per tool during
        inspect. Go keeps no registry, so this reads each binary's embedded module info: a block
        headed by "<bin>: goX.Y" carries `\tpath\t<pkg>` (the install path = index_key) and
        `\tmod\t<module>\t<version>`.'''
        idx = {}
        path = None
        for line in stdout.splitlines():
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
        ver, hit = self.batched_version(rc)          # answer from the one `go version -m` when batched
        if hit:
            return ver
        r = self.runner.run(f'{self.TOOL} version -m {_GOBIN}/{shlex.quote(self._bin(rc))}')
        if not r.ok or not r.stdout:
            return None
        # a `mod\t<module>\t<version>` line carries the module's version
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'mod':
                return parts[2].lstrip('v')
        return None

    def get_latest(self, rc):
        '''What `go install …@latest` would install: an explicit `version:` spec wins, else the Go
        module proxy's @latest for this package's module (cached like any discovered version).'''
        if self._disco_spec(rc):
            return self.resolve_version(rc)
        from .. import versions
        return versions.discover({'goproxy': self._path(rc)}, self.paths, offline=self._offline())

    def _fresh_latest(self, rc):
        '''@latest asked of the proxy NOW (not the cached discovery) — what `go install …@latest`
        would fetch, so a checkout upgrade never rebuilds a stale cached version.'''
        if self._disco_spec(rc):
            return self.resolve_version(rc, refresh=not self._offline())
        from .. import versions
        return versions.discover({'goproxy': self._path(rc)}, self.paths,
                                 refresh=not self._offline(), offline=self._offline())

    # -- mutate -----------------------------------------------------------

    def _go_install(self, spec):
        # run `go install` with a configsys-managed go (if any) ahead of the system one on PATH
        return self.runner.run(f'{self.TOOL} install {shlex.quote(spec)}',
                               capture=False)

    @staticmethod
    def _checkout(rc):
        '''`checkout:` as a boolean — route values arrive as strings ('true'), so `checkout: false` must
        not read as set.'''
        v = rc.fields.get('checkout')
        return v is True or str(v).strip().lower() in ('true', 'yes', 'on', '1')

    def _checkout_install(self, rc, version):
        '''`checkout: true`: clone the module, check out `version` (a pseudo-version's commit, else
        the `v` tag), and `go install .` inside it — see the module docstring. The clone lives in a
        mktemp dir, removed afterwards whatever the outcome.'''
        if not version:
            return Result.fail(f'{rc.comp}: no version to build — the Go module proxy lookup for '
                               f'{self._path(rc)}@latest failed (offline?)')
        version = str(version)
        m = _PSEUDO_RE.search(version)
        ref = m.group(1) if m else ('v' + version.lstrip('v'))
        repo = rc.fields.get('repo') or f'https://{self._path(rc)}'
        cmd = (f'tmp=$(mktemp -d) || exit 1; '
               f'git clone --quiet --filter=blob:none {shlex.quote(repo)} "$tmp/src" && '
               f'git -C "$tmp/src" checkout --quiet {shlex.quote(ref)} && '
               f'( cd "$tmp/src" && PATH="{_GO_PATH}:$PATH" go install . ); '
               f'rc=$?; rm -rf "$tmp"; exit $rc')
        return self.runner.run(cmd, capture=False)

    def install(self, rc):
        if self._checkout(rc):
            return self._checkout_install(rc, self._fresh_latest(rc))
        return self._go_install(self._at(rc))

    def uninstall(self, rc):
        return self.runner.run(f'rm -f {_GOBIN}/{shlex.quote(self._bin(rc))}', capture=False)

    def upgrade(self, rc):
        if self._checkout(rc):
            return self._checkout_install(rc, self._fresh_latest(rc))
        return self._go_install(f'{self._path(rc)}@latest')

    def set_version(self, rc, version):
        if self._checkout(rc):
            return self._checkout_install(rc, version)
        return self._go_install(self._at(rc, version))
