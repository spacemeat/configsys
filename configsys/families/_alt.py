'''_alt.py — shared base for versioned toolchains (gcc, clang) across apt and dnf.

Both distros ship the same versioned binaries at the same paths (/usr/bin/gcc-13,
/usr/bin/clang-18, ...), so version detection and location are identical. Only the
acquisition differs, which this base keys off the detected package manager:

  apt (Debian family): install from a PPA / apt.llvm.org source, then register an
    update-alternatives group (master + slaves, priority = version) — /usr/bin/gcc
    is an alternatives slot there. Switch with `update-alternatives --config gcc`.

  dnf (Fedora family): install the versioned compat packages (gcc13, clang18) from
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
  ppa       owner/name toolchain PPA to add first (apt only)
  apt-source { key, deb }  key url + deb line ($VERSION / $CODENAME expanded; apt only)
'''

import os
import re
import shlex
import shutil

from ..component import Family
from ..runner import Result

_VER_RE = re.compile(r'\d+\.\d+(?:\.\d+)?')


class AltFamily(Family):
    privileged = True
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

    @staticmethod
    def _pm():
        '''Package manager: 'dnf' where present (Fedora/RHEL), else 'apt'. The runner
        is local, so the host's PM is the target's. CONFIGSYS_PM forces it (tests, or
        an unusual host).'''
        forced = os.environ.get('CONFIGSYS_PM')
        if forced in ('apt', 'dnf'):
            return forced
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
        return None  # the component is itself a pinned major version

    def is_locked(self, rc):
        return False  # configsys doesn't manage the active selection

    # -- repo + alternatives ----------------------------------------------

    def _repo_lines(self, rc):
        ppa = rc.fields.get('ppa')
        if ppa:
            return [f'add-apt-repository -y ppa:{ppa}', 'apt-get update']
        src = rc.fields.get('apt-source') or self.default_source
        if isinstance(src, dict) and src.get('key') and src.get('deb'):
            v = self._ver(rc)
            key_path = src.get('key-path', f'/etc/apt/trusted.gpg.d/{self.name}.asc')
            list_path = src.get('list', f'/etc/apt/sources.list.d/{self.name}-{v}.list')
            deb = src['deb'].replace('$VERSION', v)   # $CODENAME resolved in-shell
            return [
                'CODENAME="$(. /etc/os-release; echo "$VERSION_CODENAME")"',
                f'curl -fsSL {shlex.quote(src["key"])} | tee {shlex.quote(key_path)} >/dev/null',
                f'echo "deb {deb}" | tee {shlex.quote(list_path)} >/dev/null',
                'apt-get update',
            ]
        return []

    def _alt_install(self, rc):
        v, link = self._ver(rc), self._link(rc)
        parts = [f'update-alternatives --install /usr/bin/{link} {link} '
                 f'/usr/bin/{link}-{v} {v}']
        for s in self._slaves(rc):
            parts.append(f'--slave /usr/bin/{s} {s} /usr/bin/{s}-{v}')
        return ' '.join(parts)

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        pm = self._pm()
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
        return self.runner.run(self._pm_upgrade(self._pm(), pkgs),
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        pm = self._pm()
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
