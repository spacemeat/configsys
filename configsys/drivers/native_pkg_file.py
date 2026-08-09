'''native_pkg_file.py — install an upstream release's native package FILE.

For a component whose upstream ships an official OS package (a `.deb` / `.rpm` / Arch
`.pkg.tar.zst`) on its GitHub releases, rather than — or newer than — the distro repos. It
downloads the release asset for this arch and installs it with the machine's OWN package tool
(apt/dpkg, dnf/rpm, pacman), so the file is registered in the OS package database (dependency
resolution, clean uninstall) — but it does NOT ride the repo's `apt upgrade` / security-update
flow. That makes it a deliberate OPT-IN alternative to `via: native` (which stays the default,
being the repo-managed good citizen), for "I want upstream's faster-moving build."

One via, dispatched by the machine's package format (like `via: native` dispatches to the OS's
package MANAGER). Version discovery reuses the base Driver's github/url machinery: declare a
normal `version: { github: owner/repo }` plus an `asset:` map. The `asset:` map may be
arch-keyed (`{ x86_64: foo.deb  aarch64: foo-arm64.deb }`) for a single-format component, or
format-then-arch-keyed (`{ deb: { x86_64: ... }  rpm: { x86_64: ... } }`) to carry more than one
package format in one binding — the driver picks the layer matching this machine's format.
'''

import shlex
import shutil

from ..driver import Driver
from ..runner import Result


class NativePkgFile(Driver):
    name = 'native-pkg-file'
    privileged = True
    default_scope = 'system'   # a native package is system-wide, like apt/dnf

    # -- package-format dispatch -----------------------------------------
    # Detected in-process (shutil.which, not the runner) so it's real even under --pretend, and
    # side-effect free. A machine has exactly one native format; probe in priority order.

    _FORMATS = (('deb', ('dpkg', 'apt-get')),
                ('rpm', ('rpm', 'dnf')),
                ('pacman', ('pacman',)))

    def _format(self):
        for fmt, tools in self._FORMATS:
            if any(shutil.which(t) for t in tools):
                return fmt
        return None

    def _asset_name(self, rc):
        '''This machine's release-asset filename: an arch-keyed map picks by arch; a
        format-then-arch map picks this format's layer first.'''
        asset = rc.fields.get('asset')
        if isinstance(asset, dict):
            fmt = self._format()
            if fmt and isinstance(asset.get(fmt), dict):
                return asset[fmt].get(self.arch())
            return asset.get(self.arch())
        return asset

    def _disco_spec(self, rc):
        '''Merge the machine's selected `asset` into the github `version:` spec, so the base
        Driver's resolve_version / download_url match the right release asset (mirrors how the
        appImage/tarball drivers carry an asset glob).'''
        spec = rc.fields.get('version')
        if isinstance(spec, dict):
            spec = dict(spec)
            asset = self._asset_name(rc)
            if asset:
                spec['asset'] = asset
            return spec
        return super()._disco_spec(rc)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        '''The installed version, queried from the OS package DB by name (the file registered
        there on install). Format-appropriate; first line only (a multiarch .deb prints one row
        per arch).'''
        fmt, pkg = self._format(), shlex.quote(rc.name)
        if fmt == 'deb':
            r = self.runner.run(f"dpkg-query -W -f='${{Version}}\\n' {pkg}")
        elif fmt == 'rpm':
            r = self.runner.run(f"rpm -q --qf '%{{VERSION}}\\n' {pkg}")
        elif fmt == 'pacman':
            r = self.runner.run(f'pacman -Q {pkg}')   # "name version"
        else:
            return None
        if not (r.ok and r.stdout.strip()):
            return None
        line = r.stdout.strip().splitlines()[0].strip()
        return line.split()[-1] if fmt == 'pacman' else line

    def get_latest(self, rc):
        # not in a repo — "latest" is the upstream release the package file comes from
        return self.resolve_version(rc)

    def is_locked(self, rc):
        # only apt/dpkg offers a hold we can honor; other formats aren't lockable here
        if self._format() == 'deb':
            r = self.runner.run('apt-mark showhold')
            return bool(r.ok and rc.name in r.stdout.split())
        return False

    # -- mutate -----------------------------------------------------------

    def _install_cmd(self, fmt, tmp_q):
        '''Install the downloaded package file with the OS tool, letting it resolve deps.'''
        if fmt == 'deb':
            return f'apt-get install -y {tmp_q}'
        if fmt == 'rpm':
            return f'dnf install -y {tmp_q}'
        if fmt == 'pacman':
            return f'pacman -U --noconfirm {tmp_q}'
        return None

    def install(self, rc):
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            return Result(f'(native-pkg-file: no release asset resolved for {rc.comp})', 1)
        fmt = self._format()
        inst = self._install_cmd(fmt, '$PKG')
        if inst is None:
            return Result('(native-pkg-file: no supported native package tool on this system)', 1)
        # the file MUST keep the format's real extension: `apt-get install <file>` recognizes a
        # local package only by a `.deb` suffix (a bare `.pkg` -> "E: Unsupported file … given on
        # commandline"), and dnf/rpm likewise want `.rpm`.
        ext = {'deb': 'deb', 'rpm': 'rpm', 'pacman': 'pkg.tar.zst'}.get(fmt, 'pkg')
        tmp = shlex.quote(f'/tmp/configsys-{rc.comp}.{ext}')
        cmd = (f'PKG={tmp}; curl -fSL {shlex.quote(url)} -o $PKG && '
               f'{inst} && rm -f $PKG')
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        fmt, pkg = self._format(), shlex.quote(rc.name)
        if fmt == 'deb':
            cmd = f'apt-get remove -y {pkg}'
        elif fmt == 'rpm':
            cmd = f'dnf remove -y {pkg}'
        elif fmt == 'pacman':
            cmd = f'pacman -R --noconfirm {pkg}'
        else:
            return Result('(native-pkg-file: no supported native package tool on this system)', 1)
        return self.runner.run(cmd, sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)                 # re-fetch + reinstall the latest release package

    def set_version(self, rc, version):
        return self.install(rc)                 # the release package tracks the discovered version

    def lock(self, rc):
        if self._format() == 'deb':
            return self.runner.run(f'apt-mark hold {shlex.quote(rc.name)}', sudo=True)
        return Result('(native-pkg-file: version lock only supported for .deb here)', 0)

    def unlock(self, rc):
        if self._format() == 'deb':
            return self.runner.run(f'apt-mark unhold {shlex.quote(rc.name)}', sudo=True)
        return Result('(native-pkg-file: version lock only supported for .deb here)', 0)
