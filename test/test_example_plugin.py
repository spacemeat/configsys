'''examples/examplos — the reference code plugin. ExamplOS is a fictional distro (so it can't rot
against a real repo's renames), its `toybox` package manager equally fictional. Proof that P2a (the
frozen ABI) and P2b (trusted code loading) compose into a real, working code plugin, and that a
plugin's `component-names:` map patches core component names on its OS. Exercises the toybox driver's
command construction directly, then the whole add -> trust -> resolve path through the CLI.'''

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from configsys import plugins
from configsys.componentObj import ResolvedComponent
from configsys.routes import Resolver
from configsys.runner import Result, Runner

EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'examplos'
ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


@pytest.fixture(autouse=True)
def _restore_registry():
    from configsys.drivers import _REGISTRY
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


def _toybox_cls():
    '''The Toybox class, loaded exactly as the trusted loader would (via its DRIVERS export).'''
    return plugins._import_drivers(EXAMPLE, plugins.read_manifest(EXAMPLE))[0]


def _rc(name='toychest'):
    return ResolvedComponent(key=f'toybox\\{name}', driver='toybox', comp=name, fields={'name': name})


# -- the toybox driver in isolation ---------------------------------------

def test_manifest_and_export_shape():
    m = plugins.read_manifest(EXAMPLE)
    assert m['name'] == 'examplos' and int(m['requires-abi']) == 1
    assert m['code'] == 'driver.py'
    Toybox = _toybox_cls()
    assert Toybox.name == 'toybox' and Toybox.privileged and Toybox.default_scope == 'system'


def test_toybox_mutating_commands():
    r = Runner(pretend=True)
    d = _toybox_cls()(r)
    d.install(_rc()); d.uninstall(_rc()); d.upgrade(_rc()); d.set_version(_rc(), '1.2.0')
    d.lock(_rc()); d.unlock(_rc())
    assert r.calls == ['sudo toybox add toychest', 'sudo toybox rm toychest',
                       'sudo toybox up toychest', 'sudo toybox add toychest@1.2.0',
                       'sudo toybox pin toychest', 'sudo toybox unpin toychest']
    assert d.scope(_rc()) == 'system'                      # fixed system scope


def test_toybox_get_version_parsing():
    Toybox = _toybox_cls()

    class Fake:
        def __init__(self, out): self.out = out
        def run(self, cmd, **kw): return Result(cmd, 0, stdout=self.out)

    assert Toybox(Fake('widget 9.0.1\n')).get_version(_rc('widget')) == '9.0.1'
    # a superstring package must NOT satisfy the query (exact field match)
    assert Toybox(Fake('widget-extras 1.0.0\n')).get_version(_rc('widget')) is None
    assert Toybox(Fake('')).get_version(_rc('widget')) is None    # not installed


def test_toybox_pin_state():
    Toybox = _toybox_cls()

    class Fake:
        def __init__(self, out): self.out = out
        def run(self, cmd, **kw): return Result(cmd, 0, stdout=self.out)

    assert Toybox(Fake('pinned\n')).is_locked(_rc()) is True
    assert Toybox(Fake('unpinned\n')).is_locked(_rc()) is False


# -- the plugin's component-names map (no trust needed — resolution is data) -----

def test_examplos_component_names():
    r = Resolver(ROUTES, 'examplos', None, 'x86_64',
                 plugin_files=[(str(EXAMPLE / 'routes.hu'), 'plugin')])

    def pkg(comp):
        for v in r.resolve_names([comp]).values():
            if v.comp == comp:
                return v.name
        return None

    assert pkg('ripgrep') == 'rg'                          # renamed under toybox
    assert 'toybox\\btop' in r.resolve_names(['btop'])     # unpatched native comp still routes
    assert not r.resolve_names(['nmap'])                   # dropped ({}) -> not offered


# -- the whole plugin, dogfooded through the CLI --------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_example_plugin_add_trust_resolve(tmp_path, capsys):
    from configsys.app import main
    plug = tmp_path / 'examplos'
    shutil.copytree(EXAMPLE, plug)
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'v0.1.0']):
        subprocess.run(['git', *cmd], cwd=plug, check=True)
    home = ['--home', str(tmp_path), '--os', 'examplos']

    main(home + ['plugin', 'add', str(plug)])
    capsys.readouterr()

    # untrusted: a single "trust the plugin" nudge — no redundant unknown-driver error,
    # because the manifest's provides.drivers marks `toybox` as pending-trust, not a typo.
    main(home + ['check'])
    out = capsys.readouterr().out
    assert 'untrusted code' in out
    assert 'is not a known driver' not in out     # suppressed (pending trust, not unknown)
    assert '0 error(s)' in out                     # a nudge, not a blocker

    # approve the commit -> toybox registers, the unknown-driver error clears
    main(home + ['plugin', 'trust', 'examplos'])
    capsys.readouterr()
    main(home + ['check'])
    assert "via:'toybox' is not a known driver" not in capsys.readouterr().out

    # `via: toybox` now resolves...
    main(home + ['where', 'toychest'])
    assert 'via toybox' in capsys.readouterr().out
    # ...and the one os block makes a repo `via: native` component install via toybox on ExamplOS
    main(home + ['where', 'btop'])
    assert 'toybox\\btop' in capsys.readouterr().out
