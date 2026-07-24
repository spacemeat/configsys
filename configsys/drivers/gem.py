'''gem.py — the gem driver: Ruby gems via `gem install`.

Scope-honoring. The default `user` scope installs with `--user-install` (into the
per-user gem home, no sudo); `scope: system` installs into the system gem tree with
sudo. Ruby's GEM_PATH merges the user and system trees, so `gem list` is
scope-agnostic — only the install location differs. No native version lock, so lock
intent lives in the ledger.

The gem tool ships with Ruby, so this driver `requires: ruby`, satisfied by the
`ruby` toolchain component. get_latest is deferred to a `version:` spec.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

# `gem list -e <name>` prints e.g.  "rails (7.1.3, 7.0.8)"
_LIST_RE = re.compile(r'^(\S+)\s+\(([^,)]+)')


class Gem(Driver):
    name = 'gem'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    @staticmethod
    def _gem(rc):
        return rc.name  # route `name` field is the gem name

    def _user_flag(self, rc):
        # --user-install only applies to install; uninstall/update act over the gem path
        return '' if self._scope(rc) == 'system' else '--user-install '

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'gem list -e {shlex.quote(self._gem(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            m = _LIST_RE.match(line)
            if m and m.group(1) == self._gem(rc):
                return m.group(2).strip()
        return None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'gem install {self._user_flag(rc)}{shlex.quote(self._gem(rc))}',
            sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'gem uninstall -x {shlex.quote(self._gem(rc))}',
                               sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'gem update {shlex.quote(self._gem(rc))}',
                               sudo=self.sudo(rc), capture=False)

    def set_version(self, rc, version):
        return self.runner.run(
            f'gem install {self._user_flag(rc)}-v {shlex.quote(version)} '
            f'{shlex.quote(self._gem(rc))}', sudo=self.sudo(rc), capture=False)

    def lock(self, rc):
        return Result('(gem lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(gem unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.gem' if self._scope(rc) != 'system' else None
