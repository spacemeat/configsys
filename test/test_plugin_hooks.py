'''P2c — extension hooks beyond drivers: register_version_source (new `version: { <name>: }`
backends) and register_transport (new `source:` sync schemes). Both are registered only from
trusted plugin code (via plugins.load_code), so they inherit the same trust + ABI gate.'''

import shutil
import subprocess

import pytest

from configsys import plugins, versions
from configsys.runner import Runner


@pytest.fixture(autouse=True)
def _restore_hooks():
    '''The hook registries are process-global; snapshot + restore so nothing leaks.'''
    vs, tr = dict(versions._SOURCES), dict(plugins._TRANSPORTS)
    yield
    versions._SOURCES.clear(); versions._SOURCES.update(vs)
    plugins._TRANSPORTS.clear(); plugins._TRANSPORTS.update(tr)


# -- version-source hook --------------------------------------------------

def test_register_version_source_dispatch():
    calls = []

    def src(spec, fetch):
        calls.append(spec)
        return spec['demo'] + '-resolved', None

    plugins.register_version_source('demo', src)              # the frozen-surface name
    assert versions.discover({'demo': '1.2'}) == '1.2-resolved'
    assert versions.source_key({'demo': '1.2'}) == 'demo:1.2'  # cached under a proper key
    assert calls == [{'demo': '1.2'}]


def test_builtin_sources_win_over_a_registered_name():
    plugins.register_version_source('static', lambda spec, fetch: ('HIJACKED', None))
    assert versions.discover({'static': '3.3'}) == '3.3'       # builtin static still wins


def test_register_source_validates():
    with pytest.raises(ValueError):
        versions.register_source('', lambda s, f: (None, None))
    with pytest.raises(ValueError):
        versions.register_source('x', None)


# -- transport hook -------------------------------------------------------

def test_register_transport_claims_a_scheme(tmp_path):
    seen = {}

    def copy_transport(runner, dest, source, ref):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'plugin.hu').write_text('{ name: t }')
        seen['args'] = (str(dest), source, ref)
        return 'copied'

    plugins.register_transport('demo', copy_transport)
    results = plugins.sync(Runner(pretend=True), tmp_path,
                           [{'source': 'demo:whatever', 'ref': 'v1'}])
    assert results == [('whatever', 'copied')]
    assert (tmp_path / 'whatever' / 'plugin.hu').exists()
    assert seen['args'][1] == 'demo:whatever' and seen['args'][2] == 'v1'


def test_unregistered_scheme_falls_back_to_git(tmp_path):
    r = Runner(pretend=True)
    plugins.sync(r, tmp_path, [{'source': 'github:a/b', 'ref': 'v1'}])
    assert any('git clone' in c for c in r.calls)             # default transport is git


def test_transport_failure_is_isolated(tmp_path):
    plugins.register_transport('boom', lambda *a: (_ for _ in ()).throw(RuntimeError('nope')))
    results = plugins.sync(Runner(pretend=True), tmp_path, [{'source': 'boom:x'}])
    assert results[0][0] == 'x' and 'failed' in results[0][1]  # isolated, not raised


def test_register_transport_validates():
    with pytest.raises(ValueError):
        plugins.register_transport('', lambda *a: None)
    with pytest.raises(ValueError):
        plugins.register_transport('x', None)


# -- the real path: a trusted plugin registers a source via its own code ---

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_trusted_plugin_registers_a_version_source(tmp_path):
    pdir = tmp_path / 'plugins' / 'srcplug'
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text('{ name: srcplug  requires-abi: 1  code: code.py }')
    (pdir / 'code.py').write_text(
        'from configsys.plugins import register_version_source\n'
        'register_version_source("demo", lambda spec, fetch: (spec["demo"] + "!", None))\n'
        'DRIVERS = []\n')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i']):
        subprocess.run(['git', *cmd], cwd=pdir, check=True)
    head = subprocess.run(['git', '-C', str(pdir), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'github:x/srcplug'}]

    # untrusted -> code not imported -> the source is never registered
    plugins.load_code(Runner(pretend=False), tmp_path / 'plugins', tf, decls, lambda c: None)
    assert versions.discover({'demo': '5'}) is None

    # trust the commit -> the module imports -> its register_version_source() ran
    plugins.set_trust(tf, 'srcplug', head)
    plugins.load_code(Runner(pretend=False), tmp_path / 'plugins', tf, decls, lambda c: None)
    assert versions.discover({'demo': '5'}) == '5!'
