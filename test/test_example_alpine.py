'''The examples/configsys-alpine reference plugin — proof that P2a (the frozen ABI) and P2b
(trusted code loading) compose into a real, working code plugin. Exercises the apk driver's
command construction directly, then the whole add -> trust -> resolve path through the CLI.'''

import shutil
import subprocess
from pathlib import Path

import pytest

from configsys import plugins
from configsys.componentObj import ResolvedComponent
from configsys.runner import Result, Runner

EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'configsys-alpine'


@pytest.fixture(autouse=True)
def _restore_registry():
    from configsys.drivers import _REGISTRY
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


def _apk_cls():
    '''The Apk class, loaded exactly as the trusted loader would (via its DRIVERS export).'''
    return plugins._import_drivers(EXAMPLE, plugins.read_manifest(EXAMPLE))[0]


def _rc(name='doas'):
    return ResolvedComponent(key=f'apk\\{name}', driver='apk', comp=name, fields={'name': name})


# -- the apk driver in isolation ------------------------------------------

def test_manifest_and_export_shape():
    m = plugins.read_manifest(EXAMPLE)
    assert m['name'] == 'alpine' and int(m['requires-abi']) == 1
    assert m['code'] == 'driver.py'
    Apk = _apk_cls()
    assert Apk.name == 'apk' and Apk.privileged and Apk.default_scope == 'system'


def test_apk_mutating_commands():
    r = Runner(pretend=True)
    d = _apk_cls()(r)
    d.install(_rc()); d.uninstall(_rc()); d.upgrade(_rc()); d.set_version(_rc(), '1.2-r0')
    assert r.calls == ['sudo apk add doas', 'sudo apk del doas',
                       'sudo apk add --upgrade doas', 'sudo apk add doas=1.2-r0']
    assert d.is_locked(_rc()) is False
    assert d.lock(_rc()).ok and d.unlock(_rc()).ok         # no-op Results, still ok
    assert d.scope(_rc()) == 'system'                      # fixed system scope


def test_apk_get_version_parsing():
    Apk = _apk_cls()

    class Fake:
        def __init__(self, out): self.out = out
        def run(self, cmd, **kw): return Result(cmd, 0, stdout=self.out)

    assert Apk(Fake('doas-6.8.2-r0 x86_64 {doas} (ISC) [installed]\n')).get_version(_rc()) \
        == '6.8.2-r0'
    # a superstring package must NOT satisfy the query (digit-after-name guard)
    assert Apk(Fake('doas-doc-6.8.2-r0 x86_64 {doas} (ISC) [installed]\n')).get_version(_rc()) \
        is None
    assert Apk(Fake('')).get_version(_rc()) is None         # not installed


# -- the whole plugin, dogfooded through the CLI --------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_example_plugin_add_trust_resolve(tmp_path, capsys):
    from configsys.app import main
    plug = tmp_path / 'configsys-alpine'
    shutil.copytree(EXAMPLE, plug)
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'v0.1.0']):
        subprocess.run(['git', *cmd], cwd=plug, check=True)
    home = ['--home', str(tmp_path), '--os', 'alpine']

    main(home + ['plugin', 'add', str(plug)])
    capsys.readouterr()

    # untrusted: a single "trust the plugin" nudge — no redundant unknown-driver error,
    # because the manifest's provides.drivers marks `apk` as pending-trust, not a typo.
    main(home + ['check'])
    out = capsys.readouterr().out
    assert 'untrusted code' in out
    assert 'is not a known driver' not in out     # suppressed (pending trust, not unknown)
    assert '0 error(s)' in out                     # a nudge, not a blocker

    # approve the commit -> apk registers, the unknown-driver error clears
    main(home + ['plugin', 'trust', 'alpine'])
    capsys.readouterr()
    main(home + ['check'])
    assert "via:'apk' is not a known driver" not in capsys.readouterr().out

    # `via: apk` now resolves...
    main(home + ['where', 'doas'])
    assert 'via apk' in capsys.readouterr().out
    # ...and the one os block makes a repo `via: native` component install via apk on Alpine
    main(home + ['where', 'btop'])
    assert 'apk\\btop' in capsys.readouterr().out
