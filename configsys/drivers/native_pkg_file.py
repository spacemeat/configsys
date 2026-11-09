'''native_pkg_file.py — install an upstream release's native package FILE.

For a component whose upstream ships an official OS package (a `.deb` / `.rpm` / Arch
`.pkg.tar.zst`) on its GitHub releases, rather than — or newer than — the distro repos. It
downloads the release asset for this arch and installs it with the machine's OWN package tool
(apt/dpkg, dnf or zypper/rpm, pacman), so the file is registered in the OS package database (dependency
resolution, clean uninstall) — but it does NOT ride the repo's `apt upgrade` / security-update
flow. That makes it a lower-preference alternative to `via: native` (the repo-managed good
citizen): driver-preference ranks it after native/aur/flatpak/snap, so it is the default only
where none of those is valid (a tool the repos don't carry), else a pinnable choice for "I want
upstream's faster-moving build."

One via, dispatched by the machine's package format (like `via: native` dispatches to the OS's
package MANAGER). Version discovery reuses the base Driver's github/url machinery: declare a
normal `version: { github: owner/repo }` plus an `asset:` map. The `asset:` map may be
arch-keyed (`{ x86_64: foo.deb  aarch64: foo-arm64.deb }`) for a single-format component, or
format-then-arch-keyed (`{ deb: { x86_64: ... }  rpm: { x86_64: ... } }`) to carry more than one
package format in one binding — the driver picks the layer matching this machine's format.
'''

import shlex
import shutil

from ..driver import Driver, _CURL_DOWNLOAD
from ..runner import Result
from .apt import _APT_ENV

# the resolved native manager -> the package format it installs (B14 / drivers-os-11)
_MANAGER_FORMAT = {'apt': 'deb', 'dnf': 'rpm', 'zypper': 'rpm', 'pacman': 'pacman'}


class NativePkgFile(Driver):
    name = 'native-pkg-file'
    targets_version = False   # the release package tracks the discovered version
    privileged = True
    native_backed = True       # the .deb/.rpm is registered in dpkg/rpm — enumerated by the native mgr
    default_scope = 'system'   # a native package is system-wide, like apt/dnf

    # -- package-format dispatch -----------------------------------------
    # The format follows the native manager the resolver settled for this machine (`rc.native`,
    # stamped by Context.prepare_units), so a Fedora box that happens to carry dpkg never installs a
    # .deb. Only a unit with no stamp (a hand-built one) falls back to probing the host in-process.

    _FORMATS = (('deb', ('dpkg', 'apt-get')),
                ('rpm', ('rpm', 'dnf')),
                ('pacman', ('pacman',)))

    def _manager(self, rc):
        return getattr(rc, 'native', '') or ''

    def _format(self, rc=None):
        mgr = self._manager(rc) if rc is not None else ''
        if mgr:
            return _MANAGER_FORMAT.get(mgr)      # a manager with no package-file format: none
        for fmt, tools in self._FORMATS:
            if any(shutil.which(t) for t in tools):
                return fmt
        return None

    def _rpm_tool(self, rc):
        return 'zypper' if self._manager(rc) == 'zypper' else 'dnf'

    def _asset_name(self, rc):
        '''This machine's release-asset filename: an arch-keyed map picks by arch; a
        format-then-arch map picks this format's layer first.'''
        asset = rc.fields.get('asset')
        if isinstance(asset, dict):
            fmt = self._format(rc)
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
        fmt, pkg = self._format(rc), shlex.quote(rc.name)
        if fmt == 'deb':
            # status-guarded like apt's probe: after a remove dpkg keeps the package in
            # `config-files` state and still prints its version (B14 / drivers-os-04)
            r = self.runner.run(f"dpkg-query -W -f='${{db:Status-Status}} ${{Version}}\\n' {pkg}")
            rows = [ln.split(None, 1) for ln in (r.stdout or '').splitlines() if r.ok]
            vers = [row[1].strip() for row in rows if len(row) == 2 and row[0] == 'installed']
            return vers[0] if vers else None
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

    def is_locked(self, rc):
        # only apt/dpkg offers a hold we can honor; other formats aren't lockable here
        if self._format(rc) == 'deb':
            r = self.runner.run('apt-mark showhold')
            return bool(r.ok and rc.name in r.stdout.split())
        return False

    # -- mutate -----------------------------------------------------------

    def _install_cmd(self, fmt, tmp_q, rc=None):
        '''Install the downloaded package file with the OS tool, letting it resolve deps.'''
        if fmt == 'deb':      # non-interactive: a vendor .deb's debconf / needrestart can't stall the batch
            return f'{_APT_ENV} apt-get install -y {tmp_q}'
        if fmt == 'rpm':
            if rc is not None and self._rpm_tool(rc) == 'zypper':
                return f'zypper --non-interactive install --allow-unsigned-rpm {tmp_q}'
            return f'dnf install -y {tmp_q}'
        if fmt == 'pacman':
            return f'pacman -U --noconfirm {tmp_q}'
        return None

    def install(self, rc):
        version, url = self.download_target(rc)          # the version of what's actually fetched
        if not url:
            return Result.fail(self.download_failure(rc, version))
        fmt = self._format(rc)
        inst = self._install_cmd(fmt, '"$PKG"', rc)
        if inst is None:
            return Result.fail(f'{rc.comp}: native-pkg-file found no supported native package tool on this system')
        # the file MUST keep the format's real extension: `apt-get install <file>` recognizes a
        # local package only by a `.deb` suffix (a bare `.pkg` -> "E: Unsupported file … given on
        # commandline"), and dnf/rpm likewise want `.rpm`.
        ext = {'deb': 'deb', 'rpm': 'rpm', 'pacman': 'pkg.tar.zst'}.get(fmt, 'pkg')
        # SECURITY: this runs as ROOT. A predictable /tmp name let a local user pre-symlink it so
        # root's `curl -o` clobbers an arbitrary file. Download into a private root-owned `mktemp -d`
        # dir (mode 700, unguessable — portable across GNU/busybox, unlike --suffix), and quote $PKG.
        check = self.verify_download(rc, '"$PKG"', fmt)    # a format-keyed sha256: map, deb/rpm first
        cmd = (f'D="$(mktemp -d)" && PKG="$D/pkg.{ext}" && '
               f'{_CURL_DOWNLOAD} {shlex.quote(url)} -o "$PKG"{check} && {inst} && rm -rf "$D"')
        return self.runner.run(cmd, sudo=True, capture=False)

    def uninstall(self, rc):
        fmt, pkg = self._format(rc), shlex.quote(rc.name)
        if fmt == 'deb':
            cmd = f'{_APT_ENV} apt-get remove -y {pkg}'
        elif fmt == 'rpm':
            cmd = (f'zypper --non-interactive remove {pkg}' if self._rpm_tool(rc) == 'zypper'
                   else f'dnf remove -y {pkg}')
        elif fmt == 'pacman':
            cmd = f'pacman -R --noconfirm {pkg}'
        else:
            return Result.fail(f'{rc.comp}: native-pkg-file found no supported native package tool on this system')
        return self.runner.run(cmd, sudo=True, capture=False)

    def upgrade(self, rc):
        return self.install(rc)                 # re-fetch + reinstall the latest release package

    def set_version(self, rc, version):
        return self.install(rc)                 # the release package tracks the discovered version

    def lock(self, rc):
        if self._format(rc) == 'deb':
            return self.runner.run(f'apt-mark hold {shlex.quote(rc.name)}', sudo=True)
        return Result('(native-pkg-file: version lock only supported for .deb here)', 0)

    def unlock(self, rc):
        if self._format(rc) == 'deb':
            return self.runner.run(f'apt-mark unhold {shlex.quote(rc.name)}', sudo=True)
        return Result('(native-pkg-file: version lock only supported for .deb here)', 0)
