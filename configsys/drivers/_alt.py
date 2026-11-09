'''_alt.py — shared base for versioned toolchains (gcc, clang) across apt and dnf; gcc-toolset
(gcc_toolset.py) reuses its dnf path.

Both distros ship the same versioned binaries at the same paths (/usr/bin/gcc-13,
/usr/bin/clang-18, ...), so version detection and location are identical. Only the
acquisition differs, which this base keys off the detected package manager:

  apt (Debian driver): install from a PPA / apt.llvm.org source, then register an
    update-alternatives group (master + slaves, priority = version) — /usr/bin/gcc
    is an alternatives slot there. Switch with `update-alternatives --config gcc`.

  dnf (Fedora driver): install the versioned compat packages (gcc13, clang18) from
    the main repo — no third-party repo, and NO update-alternatives (/usr/bin/gcc
    is a real file owned by the system gcc rpm; a slot there would clobber it). The
    versioned binary /usr/bin/gcc-13 is used directly (CC=gcc-13 or your alias).

configsys installs + registers only; picking the active version stays your job.
System-scoped (needs root). Component fields (packages differ per OS block):
  link      master tool / alternative name (default: comp minus the trailing -N)
  version   version number (default: the comp's trailing -N); also priority + suffix
  slaves    [g++, clang++, ...]  update-alternatives slaves (apt); default_slaves
  packages  packages to install ($VERSION expanded; default: link-N [+ slave-N]).
            Override per OS block: Debian [gcc-13, g++-13]; Fedora [gcc13, gcc13-c++]
  ppa       owner/name toolchain PPA to add first (apt only; Ubuntu only, and skipped
            when the distro already ships the package)
  apt-source { key, deb }  key url + deb line ($VERSION / $CODENAME expanded; apt only;
            added only when the distro doesn't carry the package, removed again if apt
            can't load it)
'''

import os
import re
import shlex
import shutil
from urllib.parse import urlsplit

from ..driver import Driver
from ..runner import Result

_VER_RE = re.compile(r'\d+\.\d+(?:\.\d+)?')


class AltDriver(Driver):
    targets_version = False   # the toolchain version is fixed by the package (gcc-13)
    privileged = True
    native_backed = True         # clang/gcc install into apt/dnf — packages land in the native index
    default_scope = 'system'
    default_slaves = ()          # subclasses (clang) may provide, routes may override
    default_source = None        # subclasses (clang) may provide the repo (key + deb)
    slaves_are_packages = True    # gcc: g++-N is its own package; clang: clang++ isn't

    @staticmethod
    def _link(rc):
        return rc.fields.get('link') or rc.comp.rsplit('-', 1)[0]

    @staticmethod
    def _ver(rc):
        return str(rc.fields.get('version') or rc.comp.rsplit('-', 1)[-1])

    def _slaves(self, rc):
        s = rc.fields.get('slaves')
        if s is None:
            return list(self.default_slaves)
        return list(s) if isinstance(s, list) else [s]

    def _packages(self, rc):
        v = self._ver(rc)
        pkgs = rc.fields.get('packages')
        if pkgs:
            pkgs = pkgs if isinstance(pkgs, list) else [pkgs]
            return [p.replace('$VERSION', v) for p in pkgs]
        out = [f'{self._link(rc)}-{v}']
        if self.slaves_are_packages:
            out += [f'{s}-{v}' for s in self._slaves(rc)]
        return out

    def _master_bin(self, rc):
        return f'/usr/bin/{self._link(rc)}-{self._ver(rc)}'

    def _latest_package(self, rc):
        '''The package whose candidate version IS the toolchain's version (get_latest).'''
        return self._packages(rc)[0]

    def _pm(self, rc=None):
        '''Package manager: CONFIGSYS_PM when set (tests, an unusual host), else the native manager
        the resolver settled for this machine (`rc.native`, stamped by Context.prepare_units — B14),
        else 'dnf' where present (Fedora/RHEL) and 'apt' otherwise.'''
        env = getattr(self.paths, 'env', None) if self.paths is not None else None
        forced = (env or os.environ).get('CONFIGSYS_PM')
        if forced in ('apt', 'dnf'):
            return forced
        native = getattr(rc, 'native', '') if rc is not None else ''
        if native in ('apt', 'dnf'):
            return native
        return 'dnf' if shutil.which('dnf') else 'apt'

    def _pm_install(self, pm, pkgs):
        return f'dnf install -y {pkgs}' if pm == 'dnf' else f'apt-get install -y {pkgs}'

    def _pm_remove(self, pm, pkgs):
        return f'dnf remove -y {pkgs}' if pm == 'dnf' else f'apt-get remove -y {pkgs}'

    def _pm_upgrade(self, pm, pkgs):
        return (f'dnf upgrade -y {pkgs}' if pm == 'dnf'
                else f'apt-get install --only-upgrade -y {pkgs}')

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(f'{shlex.quote(self._master_bin(rc))} --version')
        if not r.ok or not r.stdout:
            return None
        m = _VER_RE.search(r.stdout.splitlines()[0])
        return m.group(0) if m else self._ver(rc)

    def get_latest(self, rc):
        '''The package manager's candidate version for the versioned master package (gcc-13 / gcc13)
        — so a bugfix release WITHIN the pinned major (13.1.0 -> 13.2.0) shows as an available
        update. Extracted to bare X.Y[.Z] so it lines up with get_version's parse. None if the PM
        can't answer (e.g. --pretend, offline).'''
        master = self._latest_package(rc)                  # e.g. gcc-13 (apt) / gcc13 (dnf)
        if self._pm(rc) == 'apt':
            r = self.runner.run(f'apt-cache policy {shlex.quote(master)}')
            for line in (r.stdout or '').splitlines() if r.ok else ():
                line = line.strip()
                if line.startswith('Candidate:'):
                    cand = line.split(':', 1)[1].strip()
                    m = _VER_RE.search(cand)
                    return m.group(0) if (m and cand not in ('(none)', '')) else None
            return None
        r = self.runner.run(f'dnf --quiet list {shlex.quote(master)} 2>/dev/null')   # dnf
        for line in (r.stdout or '').splitlines() if r.ok else ():
            cols = line.split()
            if len(cols) >= 2 and cols[0].split('.')[0] == master:
                m = _VER_RE.search(cols[1])
                if m:
                    return m.group(0)
        return None

    # -- repo + alternatives ----------------------------------------------

    def _repo_lines(self, rc):
        # SECURITY: this whole script runs as root; every route/plugin field below is quoted so it
        # can't inject shell. The one deliberate expansion is $CODENAME (resolved in-shell), spliced
        # as a quoted "$CODENAME" into an otherwise-quoted deb line.
        ppa = rc.fields.get('ppa')
        if ppa:
            # a PPA only on Ubuntu (a Launchpad PPA on Debian 404s and poisons apt), and only when the
            # distro doesn't already ship the package (the toolchain *test* PPA would otherwise upgrade
            # libstdc++ system-wide for nothing) — B7 / drivers-lang-03
            pkg = shlex.quote(self._packages(rc)[0])
            return [
                'if ! grep -q "^UBUNTU_CODENAME=" /etc/os-release; then',
                f'  echo "configsys: {rc.comp}: the PPA ppa:{ppa} is Ubuntu-only — not adding it here" >&2; exit 1',
                'fi',
                f'if ! apt-cache madison {pkg} 2>/dev/null | grep -q .; then',
                f'  add-apt-repository -y {shlex.quote("ppa:" + ppa)}',
                '  apt-get update',
                'fi',
            ]
        src = rc.fields.get('apt-source') or self.default_source
        if isinstance(src, dict) and src.get('key') and src.get('deb'):
            v = self._ver(rc)
            key_path = src.get('key-path', f'/etc/apt/trusted.gpg.d/{self.name}.asc')
            list_path = src.get('list', f'/etc/apt/sources.list.d/{self.name}-{v}.list')
            deb = src['deb'].replace('$VERSION', v)   # $CODENAME resolved in-shell (spliced below)
            deb_q = '"$CODENAME"'.join(shlex.quote(p) for p in ('deb ' + deb).split('$CODENAME'))
            host = urlsplit(deb.split()[0]).netloc if deb.split() else ''
            pkg = shlex.quote(self._packages(rc)[0])
            listq = shlex.quote(list_path)
            # Only add the vendor repo when the DISTRO doesn't already carry the package. Ubuntu 24.04
            # ships clang-20 in noble-updates, and mixing apt.llvm.org's clang-20 with the distro's own
            # libllvm20 breaks — on Pop!_OS, which pins its repos above a vendor's, apt gives up with
            # "held broken packages". So when the distro has it: use the distro's, and drop OUR list
            # file if an earlier run left it (else apt keeps preferring the vendor's newer build).
            return [
                # the UBUNTU codename on a derivative (Mint's `wilma` is noble here) — what vendor
                # repos serve; the same lookup apt's source-line uses
                'CODENAME="$(. /etc/os-release; echo "${UBUNTU_CODENAME:-${DEBIAN_CODENAME:-$VERSION_CODENAME}}")"',
                f'if apt-cache madison {pkg} 2>/dev/null | grep -v -F {shlex.quote(host or "//")} | grep -q .; then',
                f'  if [ -f {listq} ]; then rm -f {listq}; apt-get update; fi',
                'else',
                f'  curl -fsSL {shlex.quote(src["key"])} | tee {shlex.quote(key_path)} >/dev/null',
                f'  echo {deb_q} | tee {listq} >/dev/null',
                # validate-then-commit: a source apt can't read (no suite for this codename, a dead
                # key) is taken back out at once, so it can never poison every later apt run
                f'  if ! apt-get update; then rm -f {listq}; apt-get update || true; '
                f'echo "configsys: {rc.comp}: the vendor repo failed to load and was removed again" >&2; '
                'exit 1; fi',
                'fi',
            ]
        return []

    def _alt_install(self, rc):
        v, link = self._ver(rc), self._link(rc)
        q = shlex.quote
        parts = [f'update-alternatives --install {q(f"/usr/bin/{link}")} {q(link)} '
                 f'{q(f"/usr/bin/{link}-{v}")} {q(v)}']
        for s in self._slaves(rc):
            parts.append(f'--slave {q(f"/usr/bin/{s}")} {q(s)} {q(f"/usr/bin/{s}-{v}")}')
        return ' '.join(parts)

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        from ..routecheck import vendor_path_problem
        why = vendor_path_problem(rc.fields)       # key/list paths stay in apt's dirs (A10)
        if why:
            return Result.fail(f'{rc.comp}: {why}')
        pm = self._pm(rc)
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        lines = ['set -e']
        if pm == 'apt':
            lines += self._repo_lines(rc)          # PPA / apt.llvm.org — apt only
        lines.append(self._pm_install(pm, pkgs))
        if pm == 'apt':
            lines.append(self._alt_install(rc))    # /usr/bin/gcc is an alternatives slot
        # on dnf the versioned binary is used directly; registering an alternative
        # would clobber /usr/bin/gcc (owned by the system gcc rpm).
        return self.runner.run('\n'.join(lines), sudo=True, capture=False)

    def upgrade(self, rc):
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        return self.runner.run(self._pm_upgrade(self._pm(rc), pkgs),
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        pm = self._pm(rc)
        pkgs = ' '.join(shlex.quote(p) for p in self._packages(rc))
        lines = ['set -e']
        if pm == 'apt':
            link = shlex.quote(self._link(rc))
            master = shlex.quote(self._master_bin(rc))
            lines.append(f'update-alternatives --remove {link} {master} || true')
        lines.append(self._pm_remove(pm, pkgs))
        return self.runner.run('\n'.join(lines), sudo=True, capture=False)

    def lock(self, rc):
        return Result(f'({self.name}: switch via update-alternatives, not configsys)', 0)

    def unlock(self, rc):
        return Result(f'({self.name}: switch via update-alternatives, not configsys)', 0)

    def location(self, rc):
        return self._master_bin(rc)
