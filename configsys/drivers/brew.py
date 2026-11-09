'''brew.py — the Homebrew driver: formulae via `brew`.

Entirely user-space (no sudo): modern Homebrew installs into a user-owned prefix
(/opt/homebrew on Apple Silicon, /home/linuxbrew/.linuxbrew on Linux, /usr/local on
Intel macOS) and every op runs as the invoking user. It is fedora_atomic's `native:` — the
blessed CLI path on atomic/immutable distros (Bazzite/Bluefin/Aurora ship brew pre-configured;
docs/done/immutable-distros.md) — and elsewhere on glibc Linux an ordinary `via: brew` method,
ranked just ahead of tarball (routes.hu `drivers: brew` gates it to glibc_linux). Only Linux is
modeled; the same tool on macOS makes this the natural base for macOS support.

Version state: `brew list --versions` (installed) and `brew info --json` (latest
available from the tap). Native version lock is real: `brew pin`/`unpin`. Bootstrapping
brew itself is a separate concern (a `homebrew` prereq component / env-provided on
atomic), not this driver's job. `brew` is found on PATH, else in Homebrew's standard Linux
prefixes (`brew_env`: a fresh install — the `homebrew` component earlier in the same batch, or an
uBlue image's — isn't on this process's PATH yet); with neither it degrades to "not installed".

Formulae only for now; macOS GUI *casks* (`brew install --cask`) are a future `cask:`
field — the op structure below is already cask-ready.
'''

import json
import os
import re
import shlex
import shutil

from ..driver import Driver

_NOT_FOUND = 127     # the shell's exit status for "command not found": Homebrew isn't installed
# where Homebrew's installer puts it on Linux (the shared prefix, then a per-user one); /opt/homebrew
# and /usr/local are macOS's, on PATH there
_PREFIXES = ('/home/linuxbrew/.linuxbrew', '~/.linuxbrew')


def brew_env():
    '''The env to run `brew` in: None (inherit) when `brew` is on PATH, else ours with the first
    installed prefix's bin/ APPENDED to PATH — so the command line stays `brew …` and nothing brew
    ships shadows a system tool. Looked up per call (never cached): Homebrew can arrive mid-batch.'''
    if shutil.which('brew'):
        return None
    for prefix in _PREFIXES:
        bindir = os.path.join(os.path.expanduser(prefix), 'bin')
        if os.access(os.path.join(bindir, 'brew'), os.X_OK):
            return {**os.environ, 'PATH': os.environ.get('PATH', '') + os.pathsep + bindir}
    return None


def brew_prefix():
    '''Homebrew's prefix WITHOUT running brew: $HOMEBREW_PREFIX (`brew shellenv` exports it), else the
    dir above the `brew` on PATH, else the first installed standard prefix; None with no brew at all.
    Looked up per call like brew_env (cheap — no subprocess): Homebrew can arrive mid-batch.'''
    env = os.environ.get('HOMEBREW_PREFIX')
    if env:
        return env
    found = shutil.which('brew')
    if found:
        return os.path.dirname(os.path.dirname(found))    # <prefix>/bin/brew (a link, not resolved)
    for prefix in _PREFIXES:
        p = os.path.expanduser(prefix)
        if os.access(os.path.join(p, 'bin', 'brew'), os.X_OK):
            return p
    return None


class Brew(Driver):
    name = 'brew'
    # a package BY NAME from a registry this system already trusts: an untrusted plugin's binding
    # of it is a candidate unless it sets one of these (trustgate, docs/plugins.md §6)
    trusted_registry = True
    command_fields = frozenset()
    privileged = False
    default_scope = 'user'   # brew's prefix is user-owned; ops never sudo

    @staticmethod
    def _formula(rc):
        return rc.name  # route `name` field is the formula (name-map key: `brew`)

    # -- read -------------------------------------------------------------

    def _listing(self):
        '''(installed {formula: newest-listed} | None, missing). ONE `brew list --versions` ->
        "<formula> <v1> [<v2>...]" per line. When Homebrew isn't installed at all (the shell's
        command-not-found, exit 127) that is a TRUE empty — nothing is installed via brew — so it
        returns ({}, True) rather than the None that means "couldn't tell".'''
        r = self.runner.run('brew list --versions', env=brew_env())
        if r.returncode == _NOT_FOUND:
            return {}, True
        if not r.ok:
            return None, False
        idx = {}
        for line in r.stdout.splitlines():
            cols = line.split()
            if cols:
                idx[cols[0]] = (cols[1] if len(cols) > 1 else '') or 'installed'
        return idx, False

    def installed_index(self):
        return self._listing()[0]

    def batch_index(self, rcs):
        # the default shape + `missing`: with no Homebrew, every per-unit read answers from here
        # instead of spawning a `brew` that doesn't exist (3 per unit — 100+ failed spawns at
        # startup for a machine whose picks default to brew before Homebrew is installed)
        idx, missing = self._listing()
        if idx is None:
            return None
        ctx = {'installed': idx, 'missing': missing}
        if not missing:
            names = sorted({self._formula(rc) for rc in rcs})
            cand = self.latest_index(names) if names else None
            if cand is not None:
                ctx['candidate'] = cand                # one `brew info` for every formula (C1)
            held = self.held_keys()
            if held is not None:
                ctx['held'] = set(held)
        return ctx

    def latest_index(self, names):
        '''{formula: stable version} from ONE `brew info --json=v2` (C1); None when brew refuses the
        batch (an unknown formula fails it) — each unit then asks on its own.'''
        r = self.runner.run('brew info --json=v2 --formula ' + ' '.join(shlex.quote(n) for n in names),
                            env=brew_env())
        if not r.ok or not r.stdout.strip():
            return None
        try:
            data = json.loads(r.stdout)
            return {f['name']: (f.get('versions') or {}).get('stable')
                    for f in data.get('formulae', []) if f.get('name')}
        except (ValueError, TypeError, AttributeError):
            return None

    def _missing(self):
        '''True when this inspection's batch found no Homebrew at all.'''
        return isinstance(self.batch, dict) and bool(self.batch.get('missing'))

    def index_key(self, rc):
        return self._formula(rc)

    def explicit_keys(self):
        '''`brew leaves --installed-on-request` — formulae the user asked for, not dependency-only.'''
        r = self.runner.run('brew leaves --installed-on-request', env=brew_env())
        if not r.ok:
            return None
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

    def get_version(self, rc):
        ver, hit = self.batched_version(rc)          # answer from the one brew list when batched
        if hit:
            return ver
        f = self._formula(rc)
        r = self.runner.run(f'brew list --versions {shlex.quote(f)}', env=brew_env())
        if not r.ok or not r.stdout.strip():
            return None
        # "<formula> <ver> [<ver>...]" — a keg may have several; the last is newest.
        for line in r.stdout.splitlines():
            toks = line.split()
            if len(toks) >= 2 and toks[0] == f:
                return toks[-1]
        return None

    def get_latest(self, rc):
        # the tap's stable version (offline once `brew update` has run); no spec needed. Unknown
        # until Homebrew itself is installed.
        if self._missing():
            return None
        ver, hit = self.batched_latest(rc)
        if hit:
            return ver
        r = self.runner.run(
            f'brew info --json=v2 --formula {shlex.quote(self._formula(rc))}', env=brew_env())
        if not r.ok or not r.stdout.strip():
            return None
        try:
            data = json.loads(r.stdout)
            return (data['formulae'][0]['versions']['stable']) or None
        except (ValueError, KeyError, IndexError, TypeError):
            return None

    def is_locked(self, rc):
        if self._missing():
            return False
        held, hit = self.batched_held(rc)
        if hit:
            return held
        r = self.runner.run('brew list --pinned', env=brew_env())
        if not r.ok:
            return False
        return self._formula(rc) in r.stdout.split()

    def upgradable_index(self):
        # `brew outdated --formula --verbose` -> "<formula> (<installed>[, ...]) [<!=] <candidate>".
        r = self.runner.run('brew outdated --formula --verbose', env=brew_env())
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            s = line.strip()
            if not s:
                continue
            m = re.match(r'^(\S+)\s+\(([^)]*)\)\s*[<!=]+\s*(\S+)', s)
            if m:
                idx.setdefault(m.group(1), (m.group(2).split(',')[0].strip() or None, m.group(3)))
            else:
                idx.setdefault(s.split()[0], (None, None))
        return idx

    def held_keys(self):
        r = self.runner.run('brew list --pinned', env=brew_env())
        if not r.ok:
            return None
        return {x.strip() for x in r.stdout.split() if x.strip()}

    def upgrade_all(self):
        return self.runner.run('brew upgrade', capture=False, env=brew_env())   # user-owned prefix; never sudo

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'brew install {shlex.quote(self._formula(rc))}',
                               capture=False, env=brew_env())

    def uninstall(self, rc):
        return self.runner.run(f'brew uninstall {shlex.quote(self._formula(rc))}',
                               capture=False, env=brew_env())

    def upgrade(self, rc):
        return self.runner.run(f'brew upgrade {shlex.quote(self._formula(rc))}',
                               capture=False, env=brew_env())

    def set_version(self, rc, version):
        # brew is latest-oriented: an exact old version is only reachable when the tap
        # ships a versioned formula (e.g. python@3.11). Best-effort install of that
        # variant; brew reports clearly if `<formula>@<version>` doesn't exist.
        spec = f'{self._formula(rc)}@{version}'
        return self.runner.run(f'brew install {shlex.quote(spec)}', capture=False, env=brew_env())

    def lock(self, rc):
        return self.runner.run(f'brew pin {shlex.quote(self._formula(rc))}',
                               capture=False, env=brew_env())

    def unlock(self, rc):
        return self.runner.run(f'brew unpin {shlex.quote(self._formula(rc))}',
                               capture=False, env=brew_env())

    def location(self, rc):
        # what `brew --prefix <formula>` answers — <prefix>/opt/<formula>, installed or not — without a
        # brew spawn per unit (the shell glue's cold `location --all` ran one each; app-cli-20)
        prefix = brew_prefix()
        if not prefix:
            return '(homebrew)'
        return os.path.join(prefix, 'opt', self._formula(rc).rsplit('/', 1)[-1])   # a tap's user/tap/f -> f
