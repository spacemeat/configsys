'''The examples/configsys-void reference plugin — proof that P2a (the frozen ABI) and P2b
(trusted code loading) compose into a real, working code plugin. Exercises the xbps driver's
command construction directly, then the whole add -> trust -> resolve path through the CLI.'''

import shutil
import subprocess
from pathlib import Path

import pytest

from configsys import plugins
from configsys.componentObj import ResolvedComponent
from configsys.runner import Result, Runner

EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'configsys-void'


@pytest.fixture(autouse=True)
def _restore_registry():
    from configsys.drivers import _REGISTRY
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


def _xbps_cls():
    '''The Xbps class, loaded exactly as the trusted loader would (via its DRIVERS export).'''
    return plugins._import_drivers(EXAMPLE, plugins.read_manifest(EXAMPLE))[0]


def _rc(name='xtools'):
    return ResolvedComponent(key=f'xbps\\{name}', driver='xbps', comp=name, fields={'name': name})


# -- the xbps driver in isolation -----------------------------------------

def test_manifest_and_export_shape():
    m = plugins.read_manifest(EXAMPLE)
    assert m['name'] == 'void' and int(m['requires-abi']) == 1
    assert m['code'] == 'driver.py'
    Xbps = _xbps_cls()
    assert Xbps.name == 'xbps' and Xbps.privileged and Xbps.default_scope == 'system'


def test_xbps_mutating_commands():
    r = Runner(pretend=True)
    d = _xbps_cls()(r)
    d.install(_rc()); d.uninstall(_rc()); d.upgrade(_rc()); d.set_version(_rc(), '1.2_1')
    d.lock(_rc()); d.unlock(_rc())
    assert r.calls == ['sudo xbps-install -Sy xtools', 'sudo xbps-remove -y xtools',
                       'sudo xbps-install -Suy xtools', 'sudo xbps-install -y xtools-1.2_1',
                       'sudo xbps-pkgdb -m hold xtools', 'sudo xbps-pkgdb -m unhold xtools']
    assert d.scope(_rc()) == 'system'                      # fixed system scope


def test_xbps_get_version_parsing():
    Xbps = _xbps_cls()

    class Fake:
        def __init__(self, out): self.out = out
        def run(self, cmd, **kw): return Result(cmd, 0, stdout=self.out)

    assert Xbps(Fake('vim-9.0.1_1\n')).get_version(_rc('vim')) == '9.0.1_1'
    # a superstring package must NOT satisfy the query (digit-after-name guard)
    assert Xbps(Fake('vim-tools-9.0.1_1\n')).get_version(_rc('vim')) is None
    assert Xbps(Fake('')).get_version(_rc('vim')) is None    # not installed


def test_xbps_hold_state():
    Xbps = _xbps_cls()

    class Fake:
        def __init__(self, out): self.out = out
        def run(self, cmd, **kw): return Result(cmd, 0, stdout=self.out)

    assert Xbps(Fake('yes\n')).is_locked(_rc()) is True
    assert Xbps(Fake('')).is_locked(_rc()) is False


# -- the whole plugin, dogfooded through the CLI --------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_example_plugin_add_trust_resolve(tmp_path, capsys):
    from configsys.app import main
    plug = tmp_path / 'configsys-void'
    shutil.copytree(EXAMPLE, plug)
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'v0.1.0']):
        subprocess.run(['git', *cmd], cwd=plug, check=True)
    home = ['--home', str(tmp_path), '--os', 'void']

    main(home + ['plugin', 'add', str(plug)])
    capsys.readouterr()

    # untrusted: a single "trust the plugin" nudge — no redundant unknown-driver error,
    # because the manifest's provides.drivers marks `xbps` as pending-trust, not a typo.
    main(home + ['check'])
    out = capsys.readouterr().out
    assert 'untrusted code' in out
    assert 'is not a known driver' not in out     # suppressed (pending trust, not unknown)
    assert '0 error(s)' in out                     # a nudge, not a blocker

    # approve the commit -> xbps registers, the unknown-driver error clears
    main(home + ['plugin', 'trust', 'void'])
    capsys.readouterr()
    main(home + ['check'])
    assert "via:'xbps' is not a known driver" not in capsys.readouterr().out

    # `via: xbps` now resolves...
    main(home + ['where', 'xtools'])
    assert 'via xbps' in capsys.readouterr().out
    # ...and the one os block makes a repo `via: native` component install via xbps on Void
    main(home + ['where', 'btop'])
    assert 'xbps\\btop' in capsys.readouterr().out
