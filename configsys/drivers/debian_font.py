'''debian_font.py — the debian-font driver: install downloadable font archives.

The freedesktop way of installing fonts: download a .zip of font files, extract the
.ttf/.otf into a fonts directory, and refresh the font cache with fc-cache. Version
is discovered like other download drivers ($VERSION substituted into the url).
Each component gets its own dir (configsys-<comp>) so uninstall is clean.

User-space by default (~/.local/share/fonts); `scope: system` installs into
/usr/local/share/fonts with sudo. !depends on fontconfig (fc-cache) + unzip.
'''

import shlex
from pathlib import Path

from ..driver import Driver
from ..runner import Result

MARKER_PREFIX = '.configsys-'


class DebianFont(Driver):
    name = 'debian-font'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _home(self):
        return self.paths.home if self.paths is not None else Path.home()

    def _font_base(self, rc):
        if self.scope(rc) == 'system':
            return Path('/usr/local/share/fonts')
        env = self.paths.env if self.paths is not None else {}
        xdg = env.get('XDG_DATA_HOME')
        base = Path(xdg) if xdg else self._home() / '.local/share'
        return base / 'fonts'

    def _font_dir(self, rc):
        return self._font_base(rc) / f'configsys-{rc.comp}'

    def _marker(self, rc):
        return self._font_dir(rc) / f'{MARKER_PREFIX}{rc.comp}.version'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        try:
            return self._marker(rc).read_text(encoding='utf-8').strip() or None
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            return Result('(debian-font: no url in route)', 1)

        d = self._font_dir(rc)
        dq, uq = shlex.quote(str(d)), shlex.quote(url)
        mq, vq = shlex.quote(str(self._marker(rc))), shlex.quote(version)

        script = '\n'.join([
            'set -e',
            'tmp=$(mktemp -d)',
            f'curl -fSL {uq} -o "$tmp/font.zip"',
            f'rm -rf {dq} && mkdir -p {dq}',
            # `*.[to]tf` matches .ttf and .otf in one glob (so a missing type isn't
            # an unzip "nothing matched" error)
            f'unzip -o -j "$tmp/font.zip" "*.[to]tf" -d {dq}',
            f'printf %s {vq} > {mq}',
            'rm -rf "$tmp"',
            f'fc-cache -f {dq} >/dev/null 2>&1 || true',
        ])
        return self.runner.run(script, sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        return self.install(rc)  # dir is recreated; marker refreshed

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        d = self._font_dir(rc)
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

    def lock(self, rc):
        return Result('(debian-font lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(debian-font unlock recorded in ledger)', 0)
