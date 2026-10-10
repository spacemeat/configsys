'''apk.py — the Alpine Linux driver.

Installs native Alpine packages via `apk`. Alpine is rolling: its repos carry one current
version per branch, so — like pacman — there is no native per-package hold and no way to keep
an old version. configsys therefore DECLINES lock/set-version here (holds_version=False)
instead of recording an intent an `apk upgrade` would ignore.

Query ops (`apk list`) need no root; mutations run under sudo. This driver started life as a
code plugin of the same shape as examples/examplos (the reference template) and was folded
into base once Alpine graduated to a first-class OS.
'''

import re
import shlex
from pathlib import Path

from ..runner import Result
from ._native import NativePkgManager

# an apk atom is "<name>-<version>[-r<rev>]"; the name may contain hyphens, so anchor the version at
# the first segment that begins with a digit (greedy name eats the rest).
_APK_ATOM = re.compile(r'^(.*)-(\d[^\s-]*(?:-r\d+)?)$')


def _version_from_apk_list(lines, name):
    '''`apk list` prints one line per package: "<name>-<version> <arch> {origin} (license)
    [flags]". Return the version off the line for exactly `name`. Guard: the char right after
    "<name>-" must be a digit, so a query for `gcc` is not satisfied by `gcc-doc-...`.'''
    prefix = name + '-'
    for line in lines:
        if line.startswith(prefix):
            rest = line[len(prefix):]
            if rest[:1].isdigit():
                return rest.split()[0]          # e.g. "1.4.7-r0"
    return None


# A /etc/apk/world line is a dependency atom: "<name>[@tag][<op><version>]" (ops = < > = ~ and
# combos like >= ~= ><), or a "!<name>" conflict. The bare package name is everything before the
# first tag/constraint character.
_WORLD_NAME = re.compile(r'^([^\s<>=~@!]+)')


def _parse_installed(lines):
    '''{name: version} from `apk list --installed` ("<name>-<ver> <arch> {origin} (lic) [installed]")
    or `apk info -v` ("<name>-<ver>") lines. The atom is split at the first digit-led segment.'''
    idx = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith('WARNING') or s.startswith('ERROR'):
            continue
        m = _APK_ATOM.match(s.split()[0])
        if m:
            idx.setdefault(m.group(1), m.group(2) or 'installed')
    return idx


def _parse_world(text):
    '''The package names in /etc/apk/world (what the user asked apk for — `apk add` records it;
    dependencies never appear there). Conflicts ("!name") aren't installs, so they're skipped.'''
    out = set()
    for tok in text.split():                    # world is whitespace-separated (usually one per line)
        if tok.startswith('!'):
            continue
        m = _WORLD_NAME.match(tok)
        if m:
            out.add(m.group(1))
    return out


class Apk(NativePkgManager):
    name = 'apk'
    holds_version = False          # rolling: no per-package hold; a branch carries one current version
    INSTALL = 'apk add {pkgs}'
    REMOVE = 'apk del {pkgs}'
    UPGRADE = 'apk add --upgrade {pkgs}'
    WORLD = '/etc/apk/world'       # the explicit set: every `apk add`ed atom (docs/orphans.md)

    # -- read (no root needed) -------------------------------------------

    def installed_index(self):
        '''ONE `apk list --installed` -> {name: version} for every installed package — the orphan
        scan's native enumeration and the inspection prepass (docs/orphans.md). Falls back to
        `apk info -v` (apk-tools < 2.12 has no `list`). None when both fail — never {}.'''
        r = self.runner.run('apk list --installed')
        if r.ok and r.stdout.strip():
            return _parse_installed(r.stdout.splitlines())
        r = self.runner.run('apk info -v')
        if not r.ok:
            return None
        return _parse_installed(r.stdout.splitlines())

    def explicit_keys(self):
        '''The packages the user asked for: the names in /etc/apk/world (apk records every
        `apk add` there; pulled-in dependencies never appear). None when it can't be read.'''
        try:
            return _parse_world(Path(self.WORLD).read_text())
        except (OSError, UnicodeDecodeError):
            return None

    def get_version(self, rc):
        '''Installed version, or None if the package isn't installed.'''
        ver, hit = self.batched_version(rc)        # answer from the one `apk list --installed`
        if hit:
            return ver
        name = self._probe_name(rc)
        r = self.runner.run(f'apk list --installed {shlex.quote(name)}')
        return _version_from_apk_list(r.stdout.splitlines(), name) if r.ok else None

    def get_latest(self, rc):
        '''Version available in the configured repos (Alpine carries one current version per
        branch, so the first match is the candidate).'''
        name = self._probe_name(rc)
        r = self.runner.run(f'apk list {shlex.quote(name)}')
        return _version_from_apk_list(r.stdout.splitlines(), name) if r.ok else None

    def upgradable_index(self):
        # `apk list --upgradable` -> "<name>-<newver> <arch> {repo} (lic) [upgradable from: <name>-<old>]".
        r = self.runner.run('apk list --upgradable')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            s = line.strip()
            if not s:
                continue
            m = _APK_ATOM.match(s.split()[0])
            if not m:
                continue
            name, newver = m.group(1), m.group(2)
            oldver = None
            if 'upgradable from:' in s:
                frm = s.split('upgradable from:', 1)[1].strip().rstrip(']').strip()
                mo = _APK_ATOM.match(frm)
                oldver = mo.group(2) if mo else None
            idx.setdefault(name, (oldver, newver))
        return idx

    def upgrade_all(self):
        return self.runner.run('apk upgrade', sudo=True, capture=False)

    # (no held_keys: Alpine is rolling — apk has no per-package hold. holds_version=False.)

    # -- mutate (under sudo) — install/uninstall/upgrade come from NativePkgManager templates ------

    def set_version(self, rc, version):
        # Alpine is rolling: a branch carries one CURRENT version per package (older builds aren't in
        # the repos), and there's no hold — so `apk add pkg=<old>` would fail to resolve and even a
        # resolvable pin wouldn't survive the next `apk upgrade`. Decline honestly.
        return Result('', 1, advisory=True, stderr=(
            f'apk can\'t pin {rc.comp} to {version}: Alpine is rolling — apk carries one current '
            f'version per branch, with no per-package hold. Use `configsys upgrade {rc.comp}`.'))

    def lock(self, rc):
        return Result('', 1, advisory=True, stderr=(
            f'apk won\'t lock {rc.comp}: Alpine is rolling — apk has no per-package hold and '
            f'`apk upgrade` moves everything together, so a hold can\'t be honored. Nothing was locked.'))

    def unlock(self, rc):
        return Result(f'({rc.comp}: apk has no lock to release)', 0)
