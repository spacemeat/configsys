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
    assert '/tmp/configsys-fastfetch.deb' in d.runner.cmds[0]
    assert '.pkg' not in d.runner.cmds[0].replace('.pkg.tar', '')   # no bare `.pkg`
    assert 'apt-get install -y' in d.runner.cmds[0]


def test_rpm_downloads_to_dot_rpm():
    d = _drv('rpm')
    d.install(_rc())
    assert '/tmp/configsys-fastfetch.rpm' in d.runner.cmds[0]
    assert 'dnf install -y' in d.runner.cmds[0]
