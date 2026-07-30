'''tarball.py — the tarball driver: fetch a tarball and unpack it into a dir.

For software distributed as a downloadable archive (e.g. the Vulkan SDK). Entirely
user-space (no sudo): download the `url` to a temp file, extract into `installDir`,
and record the installed version in a marker file so inspection is stateless. The
declared version comes from the route ($SDKVERSION); "latest" is that declared
version. There is no native version lock — lock intent lives in the ledger.
'''

import shlex

from ..driver import Driver
from ..runner import Result

MARKER_PREFIX = '.configsys-'


class Tarball(Driver):
    name = 'tarball'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _install_dir(self, rc):
        # bare-relative installDir (e.g. `vulkan`) -> HOME (user) or /opt (system)
        return self.scoped_dir(rc.fields.get('installDir', ''), rc)

    def _marker(self, rc):
        return self._install_dir(rc) / f'{MARKER_PREFIX}{rc.comp}.version'

    @staticmethod
    def _extract_cmd(rc, url, tmp, dq):
        '''The unpack command. `.zip` archives (some github releases: deno, bun, kotlin)
        extract with `unzip`; everything else with `tar -xf` (which auto-detects gz/xz/bz2).
        A binding may force it with `archive: zip` when the url has no telltale extension.'''
        fmt = str(rc.fields.get('archive') or '').lower()
        if fmt == 'zip' or (not fmt and url.lower().split('?', 1)[0].endswith('.zip')):
            return f'unzip -o -q {tmp} -d {dq}'   # needs unzip → the binding `requires: unzip`
        return f'tar -xf {tmp} -C {dq}'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        try:
            v = self._marker(rc).read_text(encoding='utf-8').strip()
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return v or None

    def get_installed(self, rc):
        return self._installed_across_scopes(rc)   # ~/apps (user) or /opt (system)

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False  # no native lock; the ledger carries lock intent

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            spec = rc.fields.get('version')
            asset = spec.get('asset') if isinstance(spec, dict) else None
            if asset:
                reason = (f'no release asset matched `{asset}` for {rc.comp} '
                          f'{version or "(version unresolved)"} — check the asset name/arch/case '
                          f'for this platform, or run `configsys refresh`')
            elif not rc.fields.get('url'):
                reason = (f'{rc.comp}: binding has neither a `url:` template nor a matching '
                          f'`version:` asset to download')
            else:
                reason = f'{rc.comp}: could not build a download URL (version unresolved?)'
            return Result.fail(reason)
        d = self._install_dir(rc)

        dq = shlex.quote(str(d))
        uq = shlex.quote(url)
        marker = shlex.quote(str(self._marker(rc)))
        verq = shlex.quote(version)

        if str(rc.fields.get('archive') or '').lower() == 'none':
            # bare executable (bazelisk, kubectl, ...): no archive to unpack — download straight
            # to installDir/<binary> and make it executable. `binary:` overrides the file name.
            binpath = shlex.quote(str(d / (rc.fields.get('binary') or rc.comp)))
            cmd = (f'mkdir -p {dq} && '
                   f'curl -fSL {uq} -o {binpath} && chmod +x {binpath} && '
                   f'printf %s {verq} > {marker}')
        else:
            tmp = shlex.quote(str(d / f'{MARKER_PREFIX}download.archive'))
            cmd = (f'mkdir -p {dq} && '
                   f'curl -fSL {uq} -o {tmp} && '
                   f'{self._extract_cmd(rc, url, tmp, dq)} && '
                   f'rm -f {tmp} && '
                   f'printf %s {verq} > {marker}')
        return self.runner.run(cmd, sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        # tarball upgrade = clean reinstall of the declared version
        self.uninstall(rc)
        return self.install(rc)

    def set_version(self, rc, version):
        # The url is templated on the routed version, so retargeting to an
        # arbitrary version isn't possible here; (re)install the routed version.
        return self.install(rc)

    def uninstall(self, rc):
        d = self._install_dir(rc)
        marker = self._marker(rc)
        # only remove the dir when we actually manage it (our marker is present)
        cmd = (f'if [ -f {shlex.quote(str(marker))} ]; then '
               f'rm -rf {shlex.quote(str(d))}; fi')
        return self.runner.run(cmd, sudo=self.sudo(rc), capture=False)

    def location(self, rc):
        return self.display_path(self._install_dir(rc))

    def lock(self, rc):
        return Result('(tarball lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(tarball unlock recorded in ledger)', 0)
