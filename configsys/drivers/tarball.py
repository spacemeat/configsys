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
        # bare-relative installDir (e.g. `vulkan`) -> HOME (user) or /opt (system); a config
        # `locations:` override (absolute) points straight at the install dir, scope-bypassing.
        return self.location_override(rc) or self.scoped_dir(rc.fields.get('installDir', ''), rc)

    def _marker(self, rc):
        return self._install_dir(rc) / f'{MARKER_PREFIX}{rc.comp}.version'

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

        # Build into a SIBLING staging dir, then atomically swap into place (rm old && mv stage) —
        # so a failed download/extract (or a failed upgrade) leaves the EXISTING install untouched
        # instead of a partial/bricked dir. See docs/driver-resilience-plan.md (P4 transactional).
        stage = str(d) + MARKER_PREFIX + 'stage'
        dq = shlex.quote(str(d))
        sq = shlex.quote(stage)
        uq = shlex.quote(url)
        marker = shlex.quote(f'{stage}/{self._marker(rc).name}')   # written INTO the stage
        verq = shlex.quote(version)

        archive = str(rc.fields.get('archive') or '').lower()
        if archive == 'none':
            # bare executable (bazelisk, kubectl, ...): no archive to unpack — download straight
            # to <stage>/<binary> and make it executable. `binary:` overrides the file name.
            binpath = shlex.quote(f'{stage}/{rc.fields.get("binary") or rc.comp}')
            build = f'curl -fSL {uq} -o {binpath} && chmod +x {binpath}'
        elif archive in ('gz', 'gzip'):
            # a SINGLE gzip-compressed binary (e.g. tree-sitter's `tree-sitter-linux-x64.gz`) — NOT
            # a `.tar.gz` (those are tar streams, handled by the tar branch below, which auto-detects
            # gzip/xz/bz2/zst). There is no archive to walk; gunzip the stream straight to
            # <stage>/<binary> and make it executable. `binary:` overrides the file name.
            binpath = shlex.quote(f'{stage}/{rc.fields.get("binary") or rc.comp}')
            tmp = shlex.quote(f'{stage}/.configsys-download.gz')
            build = (f'curl -fSL {uq} -o {tmp} && '
                     f'gunzip -c {tmp} > {binpath} && chmod +x {binpath} && rm -f {tmp}')
        else:
            # download + unpack via the shared acquire (same fragment the source driver builds on).
            # `strip:` drops N leading tar path components — e.g. the Go tarball's `go/` wrapper so
            # its bin/pkg/src land directly in installDir; default None = extract as-is (unchanged).
            build = self._fetch_and_extract(url, stage, rc.fields.get("archive"), rc.fields.get("strip"))
        cmd = (f'rm -rf {sq} && mkdir -p {sq} && {build} && printf %s {verq} > {marker} && '
               f'rm -rf {dq} && mv {sq} {dq}')
        return self.runner.run(cmd, sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        # tarball upgrade = reinstall the declared version. The install stages + atomically swaps,
        # so we do NOT uninstall first — a failed upgrade leaves the OLD version working, not a hole.
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
