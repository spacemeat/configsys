'''font.py — the font driver: install downloadable font archives.

The freedesktop way of installing fonts: download a .zip of font files, extract the
.ttf/.otf into a fonts directory, and refresh the font cache with fc-cache. Version
is discovered like other download drivers ($VERSION substituted into the url).
Each component gets its own dir (configsys-<comp>) so uninstall is clean.

User-space by default (~/.local/share/fonts); `scope: system` installs into
/usr/local/share/fonts with sudo. !depends on fontconfig (fc-cache) + unzip.
'''

import shlex
from pathlib import Path

from ..driver import Driver, _CURL_DOWNLOAD
from ..runner import Result


class Font(Driver):
    name = 'font'
    targets_version = False   # the archive url is fixed by the route
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _font_base(self, rc):
        if self.scope(rc) == 'system':
            return Path('/usr/local/share/fonts')
        env = self.paths.env if self.paths is not None else {}
        xdg = env.get('XDG_DATA_HOME')
        base = Path(xdg) if xdg else self.home() / '.local/share'
        return base / 'fonts'

    def _font_dir(self, rc):
        return self.location_override(rc) or (self._font_base(rc) / f'configsys-{rc.comp}')

    def _marker(self, rc):
        return self.marker_path(self._font_dir(rc), rc)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        return self.read_marker(self._marker(rc))     # empty = present, version unrecorded

    def get_installed(self, rc):
        return self._installed_across_scopes(rc)   # ~/.local/share/fonts (user) or /usr/local (system)

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        version, url = self.download_target(rc)          # the version of what's actually fetched
        if not url:
            return Result.fail(self.download_failure(rc, version))

        d = self._font_dir(rc)
        why = self.replace_dir_refusal(d, self._marker(rc))   # never rm -rf a shared/unowned dir (A6)
        if why:
            return Result.fail(f'{rc.comp}: refusing to install fonts into {d} — {why}')
        dq, uq = shlex.quote(str(d)), shlex.quote(url)
        pq = shlex.quote(str(d.parent))
        mq, vq = shlex.quote(str(self._marker(rc))), shlex.quote(version)

        # TRANSACTIONAL (drivers-lang-27): download and unzip into the temp dir first, and replace the
        # installed dir only once that worked — a failed download/unzip leaves the old fonts in
        # place. The trap removes the temp dir on every exit, a failure included.
        script = '\n'.join([
            'set -e',
            'tmp=$(mktemp -d)',
            'trap \'rm -rf "$tmp"\' EXIT',
            f'{_CURL_DOWNLOAD} {uq} -o "$tmp/font.zip"{self.verify_download(rc, chr(34) + "$tmp/font.zip" + chr(34))}',
            'mkdir -p "$tmp/out"',
            # ONE glob for .ttf/.otf/.ttc/.otc in any case (.TTF too) — a second pattern that
            # matched nothing would be an unzip "filename not matched" error
            'unzip -o -j "$tmp/font.zip" \'*.[tToO][tT][fFcC]\' -d "$tmp/out"',
            f'rm -rf {dq} && mkdir -p {pq} && mv "$tmp/out" {dq}',
            f'printf %s {vq} > {mq}',
            f'fc-cache -f {dq} >/dev/null 2>&1 || true',
        ])
        return self.runner.run(script, sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        return self.install(rc)  # dir is recreated; marker refreshed

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        d = self._font_dir(rc)
        why = self.unsafe_dir_reason(d)
        if why:
            return Result.fail(f'{rc.comp}: refusing to remove {d} — {why}')
        marker = self._marker(rc)
        script = '\n'.join([
            f'if [ -f {shlex.quote(str(marker))} ]; then',
            f'  rm -rf {shlex.quote(str(d))}',
            '  fc-cache -f >/dev/null 2>&1 || true',
            'fi',
        ])
        return self.runner.run(script, sudo=self.sudo(rc), capture=False)

    def location(self, rc):
        return self.display_path(self._font_dir(rc))

