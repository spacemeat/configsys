'''tarball.py — the \\tarball family: fetch a tarball and unpack it into a dir.

For software distributed as a downloadable archive (e.g. the Vulkan SDK). Entirely
user-space (no sudo): download the `url` to a temp file, extract into `installDir`,
and record the installed version in a marker file so inspection is stateless. The
declared version comes from the route ($SDKVERSION); "latest" is that declared
version. There is no native version lock — lock intent lives in the ledger.
'''

import shlex

from ..component import Family
from ..runner import Result

MARKER_PREFIX = '.configsys-'


class Tarball(Family):
    name = 'tarball'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _install_dir(self, rc):
        # bare-relative installDir (e.g. `vulkan`) -> HOME (user) or /opt (system)
        return self._scoped_dir(rc.fields.get('installDir', ''), rc)

    def _marker(self, rc):
        return self._install_dir(rc) / f'{MARKER_PREFIX}{rc.comp}.version'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        try:
            v = self._marker(rc).read_text(encoding='utf-8').strip()
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return v or None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False  # no native lock; the ledger carries lock intent

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            return Result('(tarball: no url in route)', 1)
        d = self._install_dir(rc)

        dq = shlex.quote(str(d))
        uq = shlex.quote(url)
        tmp = shlex.quote(str(d / f'{MARKER_PREFIX}download.tar'))
        marker = shlex.quote(str(self._marker(rc)))
        verq = shlex.quote(version)

        cmd = (f'mkdir -p {dq} && '
               f'curl -fSL {uq} -o {tmp} && '
               f'tar -xf {tmp} -C {dq} && '
               f'rm -f {tmp} && '
               f'printf %s {verq} > {marker}')
        return self.runner.run(cmd, sudo=self._sudo(rc), capture=False)

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
        return self.runner.run(cmd, sudo=self._sudo(rc), capture=False)

    def location(self, rc):
        return self._display_path(self._install_dir(rc))

    def lock(self, rc):
        return Result('(tarball lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(tarball unlock recorded in ledger)', 0)
