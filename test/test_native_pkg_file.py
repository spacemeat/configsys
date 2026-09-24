'''native-pkg-file: the downloaded package file must keep the FORMAT's real extension, because
`apt-get install <file>` recognizes a local package only by a `.deb` suffix (a bare `.pkg` gives
"E: Unsupported file … given on commandline"); dnf/rpm likewise want `.rpm`.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers.native_pkg_file import NativePkgFile
from configsys.runner import Result


class Rec:
    def __init__(self):
        self.cmds = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        self.cmds.append(cmd)
        return Result(cmd, 0, stdout='')


def _drv(fmt):
    d = NativePkgFile.__new__(NativePkgFile)
    d.runner = Rec()
    d._format = lambda: fmt
    d.download_url = lambda rc, v: f'https://x/pkg.{fmt}'
    d.resolve_version = lambda rc: '1.0'
    return d


def _rc(comp='fastfetch'):
    return ResolvedComponent(key=f'native-pkg-file\\{comp}', driver='native-pkg-file',
                             comp=comp, fields={})


def test_deb_downloads_to_dot_deb():
    d = _drv('deb')
    d.install(_rc())
    cmd = d.runner.cmds[0]
    # downloaded into a private root-owned mktemp dir (no predictable /tmp name), keeping the .deb ext
    assert 'mktemp -d' in cmd and 'pkg.deb' in cmd
    assert '/tmp/configsys-' not in cmd                 # no predictable, symlink-attackable path
    assert 'apt-get install -y "$PKG"' in cmd


def test_rpm_downloads_to_dot_rpm():
    d = _drv('rpm')
    d.install(_rc())
    cmd = d.runner.cmds[0]
    assert 'mktemp -d' in cmd and 'pkg.rpm' in cmd
    assert '/tmp/configsys-' not in cmd
    assert 'dnf install -y "$PKG"' in cmd


def _asset_rc():
    return ResolvedComponent(
        key='native-pkg-file\\insomnia', driver='native-pkg-file', comp='insomnia',
        fields={'version': {'github': 'Kong/insomnia', 'tag-re': 'core@([0-9][0-9.]*)'},
                'asset': 'Insomnia.Core-*.deb'})


def test_download_url_resolves_asset_fresh_at_install(monkeypatch):
    '''Regression: the asset URL is cached with a lifetime independent of the (atom-fed) version, so a
    stale cached URL let get_latest report a new version while the download fetched the OLD release's
    file (insomnia: latest 13.3.0 but the cached .deb still 13.2.0). download_url must resolve the
    asset FRESH at install.'''
    from configsys import versions
    seen = {}

    def fake(spec, paths, *, refresh=False, offline=False, **k):
        seen['refresh'], seen['offline'] = refresh, offline
        return 'https://x/Insomnia.Core-13.3.0.deb'
    monkeypatch.setattr(versions, 'discover_asset_url', fake)

    d = NativePkgFile.__new__(NativePkgFile)
    d.paths = None
    d.runner = type('R', (), {'pretend': False})()      # a real (non-pretend) run
    url = d.download_url(_asset_rc(), '13.3.0')
    assert url.endswith('13.3.0.deb')
    assert seen['refresh'] is True and seen['offline'] is False     # fresh, live

    d.runner = type('R', (), {'pretend': True})()       # --pretend: cache-only, no network
    d.download_url(_asset_rc(), '13.3.0')
    assert seen['refresh'] is False and seen['offline'] is True
