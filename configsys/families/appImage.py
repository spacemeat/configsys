'''appImage.py — the \\appImage family: a single self-contained executable.

Software shipped as one .AppImage file. We download it to `path`, mark it
executable, record the installed version in a marker (stateless inspection), and
write a best-effort .desktop entry so it shows up in application menus. User-space
by default (no sudo); `scope: system` switches file ops to sudo for system paths.

Route fields: `url` (download, may be $VERSION-templated), `path` (target file),
optional `version`, `name` (menu label), `icon`.

Note: AppImages need FUSE to *run*, so the family !depends on libfuse2 — installed
first via the normal cascade. We never launch the app ourselves.
'''

import shlex
from pathlib import Path

from ..component import Family
from ..runner import Result

MARKER_PREFIX = '.configsys-'


class AppImage(Family):
    name = 'appImage'
    privileged = False
    default_scope = 'user'

    # -- locations --------------------------------------------------------

    def _home(self):
        return self.paths.home if self.paths is not None else Path.home()

    def _target(self, rc):
        # bare-relative path -> HOME (user) or /opt (system); ~/absolute pass through
        return self._scoped_dir(rc.fields.get('path', ''), rc)

    def _marker(self, rc):
        t = self._target(rc)
        return t.parent / f'{MARKER_PREFIX}{rc.comp}.version'

    def _desktop_file(self, rc):
        return self._home() / '.local/share/applications' / f'configsys-{rc.comp}.desktop'

    def _icon_file(self, rc):
        return self._home() / '.local/share/icons' / f'configsys-{rc.comp}.png'

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        if not self._target(rc).exists():
            return None
        try:
            return self._marker(rc).read_text(encoding='utf-8').strip() or 'installed'
        except (FileNotFoundError, NotADirectoryError, OSError):
            return 'installed'

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False  # no native lock; ledger carries intent

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        version = self.resolve_version(rc) or ''
        url = self.download_url(rc, version)
        if not url:
            return Result('(appImage: no url in route)', 1)
        t = self._target(rc)
        tq, dq = shlex.quote(str(t)), shlex.quote(str(t.parent))
        uq, mq, vq = shlex.quote(url), shlex.quote(str(self._marker(rc))), shlex.quote(version)

        cmd = (f'mkdir -p {dq} && curl -fSL {uq} -o {tq} && chmod +x {tq} && '
               f'printf %s {vq} > {mq}')
        res = self.runner.run(cmd, sudo=self._sudo(rc), capture=False)
        if res.ok:
            self._extract_icon(rc)
            self._write_desktop(rc)
        return res

    def _extract_icon(self, rc):
        '''Best-effort: pull the AppImage's embedded icon (.DirIcon) into the icon
        dir so the .desktop entry has a real icon. `--appimage-extract` self-extracts
        without needing FUSE; any failure is non-fatal.'''
        t = self._target(rc)
        icon = self._icon_file(rc)
        tq, iq, idq = shlex.quote(str(t)), shlex.quote(str(icon)), shlex.quote(str(icon.parent))
        self.runner.run(
            f'tmp=$(mktemp -d) && cd "$tmp" && '
            f'{tq} --appimage-extract .DirIcon >/dev/null 2>&1; '
            f'if [ -e squashfs-root/.DirIcon ]; then '
            f'mkdir -p {idq} && cp -Lf squashfs-root/.DirIcon {iq}; fi; '
            f'cd / && rm -rf "$tmp"',
            sudo=self._sudo(rc), capture=False)

    def _write_desktop(self, rc):
        '''Best-effort application-menu entry (user-space, own runner call so
        --pretend skips it and it isn't written on a failed install).'''
        t = self._target(rc)
        label = rc.fields.get('name') or rc.comp
        icon = str(self._icon_file(rc))   # extracted above (or a harmless missing path)
        df = self._desktop_file(rc)
        fmt = ('[Desktop Entry]\\nType=Application\\nName=%s\\nExec=%s\\n'
               'Icon=%s\\nTerminal=false\\nCategories=Utility;\\n')
        self.runner.run(
            f'mkdir -p {shlex.quote(str(df.parent))} && '
            f"printf '{fmt}' {shlex.quote(label)} {shlex.quote(str(t))} "
            f'{shlex.quote(icon)} > {shlex.quote(str(df))}',
            capture=False)

    def upgrade(self, rc):
        return self.install(rc)  # curl overwrites the file + refreshes marker/desktop

    def set_version(self, rc, version):
        return self.install(rc)  # url is version-templated; (re)install the routed one

    def uninstall(self, rc):
        t = self._target(rc)
        marker, df, icon = self._marker(rc), self._desktop_file(rc), self._icon_file(rc)
        # only remove when we manage it (our marker is present)
        cmd = (f'if [ -f {shlex.quote(str(marker))} ]; then '
               f'rm -f {shlex.quote(str(t))} {shlex.quote(str(marker))} '
               f'{shlex.quote(str(df))} {shlex.quote(str(icon))}; fi')
        return self.runner.run(cmd, sudo=self._sudo(rc), capture=False)

    def location(self, rc):
        return self._display_path(self._target(rc))

    def lock(self, rc):
        return Result('(appImage lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(appImage unlock recorded in ledger)', 0)
