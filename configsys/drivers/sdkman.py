'''sdkman.py — the SDKMAN! driver: JVM-ecosystem SDKs via `sdk install <candidate>`.

The JVM analog of the npm/pipx/luarocks module drivers. User-scope only: SDKMAN lives under
~/.sdkman and `sdk` is a bash FUNCTION, so every op sources its init script first (in the runner's
`bash -c`). Installs are non-interactive via `sdkman_auto_answer=true`. The candidate name is the
route `name` (== the component, e.g. scala/groovy/sbt); an optional `version:` field pins it.

The SDKMAN tool itself is the driver `requires: sdkman`, satisfied by the `sdkman` component. Like
nvm/pyenv, an installed SDK is only on PATH once the user's shell sources SDKMAN (its per-candidate
`current` symlink) — configsys installs and version-tracks it; the shell wiring is the user's.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

# `sdk` is a shell function — source the init script every call. auto-answer keeps `sdk install`
# non-interactive; self-update off keeps it quiet and deterministic under automation.
_INIT = ('export sdkman_auto_answer=true sdkman_selfupdate_feature=false; '
         'source "$HOME/.sdkman/bin/sdkman-init.sh"')
# `sdk current <c>` -> "Using scala version 3.8.4" (a digit-led token after "version").
_CUR_RE = re.compile(r'version\s+([0-9][0-9A-Za-z.\-+]*)', re.I)


class Sdkman(Driver):
    name = 'sdkman'
    privileged = False           # user-scope (~/.sdkman); never sudo
    default_scope = 'user'

    @staticmethod
    def _cand(rc):
        return rc.name           # the SDKMAN candidate (== the component name unless routed otherwise)

    def _sdk(self, args, **kw):
        return self.runner.run(f'{_INIT} && sdk {args}', **kw)

    def _spec(self, rc):
        '''`<candidate>` or `<candidate> <version>` when a `version:` is pinned.'''
        c = shlex.quote(self._cand(rc))
        v = rc.fields.get('version')
        return f'{c} {shlex.quote(str(v))}' if v else c

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self._sdk(f'current {shlex.quote(self._cand(rc))}')
        if not r.ok or not r.stdout:
            return None
        m = _CUR_RE.search(r.stdout)       # "Not using any version of X" has no digit -> None
        return m.group(1) if m else None

    def get_latest(self, rc):
        return None                        # SDKMAN has no clean per-candidate "latest" query

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self._sdk(f'install {self._spec(rc)}', capture=False)

    def uninstall(self, rc):
        v = rc.fields.get('version') or self.get_version(rc)
        if not v:
            return Result(f'(sdkman: {self._cand(rc)} not installed)', 0)
        return self._sdk(f'uninstall {shlex.quote(self._cand(rc))} {shlex.quote(str(v))}',
                         capture=False)

    def upgrade(self, rc):
        return self._sdk(f'upgrade {shlex.quote(self._cand(rc))}', capture=False)

    def set_version(self, rc, version):
        c = shlex.quote(self._cand(rc))
        v = shlex.quote(str(version))
        return self._sdk(f'install {c} {v} && sdk default {c} {v}', capture=False)

    def lock(self, rc):
        return Result('(sdkman: pin a version with `version:`; no native lock)', 0)

    def unlock(self, rc):
        return Result('(sdkman: no native lock)', 0)

    def location(self, rc):
        return f'~/.sdkman/candidates/{self._cand(rc)}/current'
