'''gem.py — the gem driver: Ruby gems via `gem install`.

Scope-honoring. The default `user` scope installs with `--user-install` (into the
per-user gem home, no sudo); `scope: system` installs into the system gem tree with
sudo. Ruby's GEM_PATH merges the user and system trees, so `gem list` is
scope-agnostic; the tree a gem actually lives in is read once (a `ruby -e` over
Gem::Specification) so a user-scope gem on a `scope: system` machine isn't reported as
the wrong scope — when that read fails the scope is unknown, never a false mismatch. No
native version lock, so lock intent lives in the ledger. set-version installs the version
and then removes the others (gem keeps versions side by side and runs the newest).

The gem tool ships with Ruby, so this driver `requires: ruby`, satisfied by the
`ruby` toolchain component. get_latest is deferred to a `version:` spec.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

# `gem list -e <name>` prints e.g.  "rails (7.1.3, 7.0.8)"
_LIST_RE = re.compile(r'^(\S+)\s+\(([^,)]+)')
_GEM_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*')


class Gem(Driver):
    name = 'gem'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    @staticmethod
    def _gem(rc):
        return rc.name  # route `name` field is the gem name

    def _user_flag(self, rc):
        # install AND update take --[no-]user-install; uninstall acts over the whole gem path
        return '' if self._scope(rc) == 'system' else '--user-install '

    _SCOPES_RB = ('u = Gem.user_dir; Gem::Specification.each { |s| next if s.default_gem?; '
                  'puts [s.name, s.base_dir == u ? "user" : "system"].join("\\t") }')

    def _scope_index(self):
        '''{gem: {'user'|'system', ...}} — where each installed gem actually lives — or None.'''
        if isinstance(self.batch, dict) and 'scopes' in self.batch:
            return self.batch['scopes']
        if getattr(self, '_scopes', None) is None:
            r = self.runner.run(f"ruby -e {shlex.quote(self._SCOPES_RB)}")
            scopes = None
            if r.ok and r.stdout.strip():
                scopes = {}
                for line in r.stdout.splitlines():
                    name, _, scope = line.partition('\t')
                    if name and scope in ('user', 'system'):
                        scopes.setdefault(name, set()).add(scope)
            self._scopes = scopes
        return self._scopes

    def batch_index(self, rcs):
        b = super().batch_index(rcs)
        if b is not None:
            b['scopes'] = self._scope_index()
        return b

    def get_installed(self, rc):
        v = self.get_version(rc)
        if v is None:
            return (None, None)
        where = (self._scope_index() or {}).get(self._gem(rc)) or set()
        want = self._scope(rc)
        return (v, want if (want in where or not where) else sorted(where)[0])

    # -- read -------------------------------------------------------------

    @staticmethod
    def _real_version(ver):
        '''The managed version from a `gem list` version group, or None for a default-only gem. A
        "default gem" (bundler, rdoc, …) ships INSIDE Ruby (rubygems-integration), not as a chosen
        `gem install` — it can't be uninstalled or version-managed independently, so it's not a
        managed install and reads as absent. `gem list` marks a default-only gem as "(default: X)";
        a real install lists its version FIRST ("(2.6.1, default: 2.2.22)").'''
        return None if ver.startswith('default:') else ver

    def installed_index(self):
        '''{gem: version} from ONE `gem list` — the base batch_index enumerates once instead of a
        `gem list -e` call per gem during inspect. Default-only gems are omitted (they read as
        absent, exactly as get_version reports them).'''
        r = self.runner.run('gem list')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            m = _LIST_RE.match(line)
            if m:
                ver = self._real_version(m.group(2).strip())
                if ver is not None:
                    idx[m.group(1)] = ver
        return idx

    def get_version(self, rc):
        ver, hit = self.batched_version(rc)          # answer from the one `gem list` when batched
        if hit:
            return ver
        r = self.runner.run(f'gem list -e {shlex.quote(self._gem(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            m = _LIST_RE.match(line)
            if m and m.group(1) == self._gem(rc):
                return self._real_version(m.group(2).strip())
        return None

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'gem install {self._user_flag(rc)}{shlex.quote(self._gem(rc))}',
            sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        # -a: every installed version — with two, gem stops to ask "Select gem to uninstall"
        r = self.runner.run(f'gem uninstall -x -a {shlex.quote(self._gem(rc))}',
                            sudo=self.sudo(rc), capture=False)
        # "default gems" (bundler, etc.) ship WITH Ruby and CANNOT be removed by `gem uninstall` —
        # it exits non-zero with "cannot be uninstalled because it is a default gem". That's not a
        # broken op to report: the message already streamed, so treat it as a benign no-op (advisory)
        # instead of a failure that would nag for a bug report.
        if not r.ok and 'default gem' in r.output.lower():
            return Result(r.cmd, 0, stdout=(r.output or f'{self._gem(rc)}: default gem, kept'),
                          advisory=True)
        return r

    def upgrade(self, rc):
        return self.runner.run(f'gem update {self._user_flag(rc)}{shlex.quote(self._gem(rc))}',
                               sudo=self.sudo(rc), capture=False)

    def set_version(self, rc, version):
        # gem keeps versions side by side and the binstub runs the NEWEST — so install the target,
        # then remove every other version (B14): what set-version says is what runs
        name = self._gem(rc)
        if not _GEM_NAME.fullmatch(name):                  # it is spliced into a sed pattern below
            return Result.fail(f'{rc.comp}: {name!r} is not a gem name')
        g, v = shlex.quote(name), shlex.quote(version)
        others = (f"gem list -e {g} | sed -n 's/^{name.replace('.', '[.]')} (\\(.*\\))$/\\1/p' | "
                  f"tr ',' '\\n' | sed 's/^ *//' | grep -v '^default:' | grep -v -x -F {v}")
        sudo = 'sudo ' if self.sudo(rc) else ''
        return self.runner.run(
            f'gem install {self._user_flag(rc)}-v {v} {g} && '
            f'for o in $({others}); do {sudo}gem uninstall -x -v "$o" {g} || exit 1; done',
            sudo=self.sudo(rc), capture=False)

    def location(self, rc):
        return '~/.gem' if self._scope(rc) != 'system' else None
