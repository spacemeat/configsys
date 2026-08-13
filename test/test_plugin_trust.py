'''P2b — the code-plugin trust store + `plugin trust`/`untrust`. A plugin that ships code runs
with the user's privileges during installs, so its code is gated on per-commit approval. This
slice covers the store + commands + `plugin list` surfacing (the import gate itself is next).'''

import os
import shutil
import subprocess

import pytest

from configsys import plugins


# -- the trust store (pure data) ------------------------------------------

def test_trust_store_round_trip(tmp_path):
    tf = tmp_path / 'plugin-trust.hu'
    assert plugins.read_trust(tf) == {}                       # missing -> nothing trusted
    plugins.set_trust(tf, 'opensuse-support', 'abc123')
    plugins.set_trust(tf, 'alpine', 'def456')
    assert plugins.read_trust(tf) == {'opensuse-support': 'abc123', 'alpine': 'def456'}
    assert plugins.remove_trust(tf, 'alpine') is True
    assert plugins.remove_trust(tf, 'alpine') is False        # already gone
    assert plugins.read_trust(tf) == {'opensuse-support': 'abc123'}


def test_is_trusted_requires_exact_commit(tmp_path):
    tf = tmp_path / 'plugin-trust.hu'
    plugins.set_trust(tf, 'p', 'sha-1')
    assert plugins.is_trusted(tf, 'p', 'sha-1')
    assert not plugins.is_trusted(tf, 'p', 'sha-2')           # code moved -> not trusted
    assert not plugins.is_trusted(tf, 'other', 'sha-1')       # different plugin
    assert not plugins.is_trusted(tf, 'p', None)              # unsynced / unknown -> never


def test_corrupt_store_trusts_nothing(tmp_path):
    tf = tmp_path / 'plugin-trust.hu'
    tf.write_text('{ this is not valid humon ][')
    assert plugins.read_trust(tf) == {}                       # fail closed


def test_code_state_classification():
    cs = plugins.code_state
    assert cs({}, True, None, 'abc') == 'none'                # no code shipped
    assert cs({'code': 'd.py'}, False, None, None) == 'unsynced'
    assert cs({'code': 'd.py'}, True, None, None) == 'unsynced'   # synced but no commit read
    assert cs({'code': 'd.py'}, True, None, 'abc') == 'untrusted'  # never approved
    assert cs({'code': 'd.py'}, True, 'abc', 'abc') == 'trusted'
    assert cs({'code': 'd.py'}, True, 'old', 'abc') == 'changed'   # approved a different identity


# -- the CLI lifecycle over a real git plugin that ships code -------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_trust_untrust_cli_lifecycle(tmp_path, capsys):
    from configsys.app import main

    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text(
        '{ name: codeplug  requires-abi: 1  code: driver.py  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { ctool: { install: [ { via: native } ] } } }')
    (src / 'driver.py').write_text('# a would-be Driver subclass (not imported in this slice)\n')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'init'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']

    assert main(home + ['plugin', 'add', str(src), '--ref', 'v1']) == 0
    capsys.readouterr()

    # synced code plugin, not yet trusted -> list nudges to trust it
    assert main(home + ['plugin', 'list']) == 0
    assert 'untrusted' in capsys.readouterr().out

    # trust the current content
    assert main(home + ['plugin', 'trust', 'codeplug']) == 0
    assert 'trusted codeplug @' in capsys.readouterr().out
    trust_file = tmp_path / '.config' / 'configsys' / 'plugin-trust.hu'
    assert plugins.read_trust(trust_file).get('src', '').startswith('sha256:')   # content id

    assert main(home + ['plugin', 'list']) == 0
    assert 'code trusted' in capsys.readouterr().out

    # tampering with a file in the synced tree changes its identity -> trust no longer applies
    pdir = tmp_path / '.config' / 'configsys' / 'plugins' / 'src'
    (pdir / 'driver.py').write_text('# tampered\n')
    assert main(home + ['plugin', 'list']) == 0
    assert 'code changed since trust' in capsys.readouterr().out

    # revoke
    assert main(home + ['plugin', 'untrust', 'codeplug']) == 0
    assert 'untrusted codeplug' in capsys.readouterr().out
    assert 'src' not in plugins.read_trust(trust_file)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_trust_all_trusts_every_untrusted_code_plugin(tmp_path, capsys):
    from configsys.app import main

    def make_src(name, *, code):
        src = tmp_path / name
        src.mkdir()
        comp = name.replace('-', '') + 'tool'
        (src / 'plugin.hu').write_text('{ name: ' + name + '  requires-abi: 1  '
                                       + ('code: driver.py  ' if code else '')
                                       + 'data: [ routes.hu ] }')
        (src / 'routes.hu').write_text('{ components: { ' + comp + ': { install: [ { via: native } ] } } }')
        if code:
            (src / 'driver.py').write_text('# a would-be Driver subclass\n')
        for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                    ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
            subprocess.run(['git', *cmd], cwd=src, check=True)
        return src

    a, b, d = make_src('codeplug-a', code=True), make_src('codeplug-b', code=True), make_src('dataonly', code=False)
    home = ['--home', str(tmp_path), '--os', 'pop']
    for s in (a, b, d):
        assert main(home + ['plugin', 'add', str(s), '--ref', 'v1']) == 0
    capsys.readouterr()

    # trust --all: both code plugins trusted, the data-only one untouched
    assert main(home + ['plugin', 'trust', '--all']) == 0
    out = capsys.readouterr().out
    assert 'codeplug-a' in out and 'codeplug-b' in out and 'dataonly' not in out
    assert 'trusted 2 code plugin' in out
    trust_file = tmp_path / '.config' / 'configsys' / 'plugin-trust.hu'
    trust = plugins.read_trust(trust_file)
    assert plugins.dir_name(str(a)) in trust and plugins.dir_name(str(b)) in trust

    # idempotent: nothing left untrusted
    assert main(home + ['plugin', 'trust', '--all']) == 0
    assert 'no untrusted code plugins' in capsys.readouterr().out

    # a bare `plugin trust` (no name) behaves like --all — here it re-approves a changed plugin
    pdir = tmp_path / '.config' / 'configsys' / 'plugins' / plugins.dir_name(str(a))
    (pdir / 'driver.py').write_text('# tampered\n')
    assert main(home + ['plugin', 'list']) == 0
    assert 'code changed since trust' in capsys.readouterr().out
    assert main(home + ['plugin', 'trust']) == 0
    out2 = capsys.readouterr().out
    assert 're-approved' in out2 and 'codeplug-a' in out2


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_trust_a_dataonly_plugin_is_a_noop(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: dataonly  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { dtool: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']
    main(home + ['plugin', 'add', str(src), '--ref', 'v1'])
    capsys.readouterr()

    assert main(home + ['plugin', 'trust', 'dataonly']) == 0
    assert 'ships no code' in capsys.readouterr().out
    assert not (tmp_path / '.config' / 'configsys' / 'plugin-trust.hu').exists()


def test_trust_untrust_actions(tmp_path):
    # action-layer trust/untrust (what the TUI Plugins screen t/T keys call)
    import types
    from configsys import actions, layers
    from configsys.config import Config
    pdir = tmp_path / 'plugins'
    (pdir / 'codeplug').mkdir(parents=True)
    (pdir / 'codeplug' / 'plugin.hu').write_text(
        f'{{ name: codeplug  requires-abi: {plugins.ABI_VERSION}  code: driver.py }}\n', encoding='utf-8')
    (pdir / 'codeplug' / 'driver.py').write_text('# a driver\n', encoding='utf-8')
    (pdir / 'nocode').mkdir(parents=True)
    (pdir / 'nocode' / 'plugin.hu').write_text(
        f'{{ name: nocode  requires-abi: {plugins.ABI_VERSION}  data: [ d.hu ] }}\n', encoding='utf-8')
    (pdir / 'nocode' / 'd.hu').write_text('{ }\n', encoding='utf-8')
    user = tmp_path / 'user.hu'
    user.write_text('{ plugins: [ { source: codeplug }  { source: nocode } ] }\n', encoding='utf-8')
    tf = tmp_path / 'trust.hu'

    def load():
        return Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    ctx = types.SimpleNamespace(config=load(), paths=types.SimpleNamespace(
        user_config_file=str(user), plugins_dir=pdir, plugin_trust_file=str(tf)))
    ctx.invalidate = lambda: setattr(ctx, 'config', load())

    ok, note = actions.plugin_trust(ctx, 'codeplug')
    assert ok and 'trusted' in note
    ident = plugins.plugin_identity(pdir / 'codeplug')
    assert plugins.is_trusted(tf, 'codeplug', ident)
    ok2, _n = actions.plugin_untrust(ctx, 'codeplug')
    assert ok2 and not plugins.is_trusted(tf, 'codeplug', ident)
    # a data-only plugin has nothing to trust
    ok3, note3 = actions.plugin_trust(ctx, 'nocode')
    assert ok3 is False and 'no code' in note3
