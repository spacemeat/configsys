'''P2b — the import gate. A trusted code plugin's `code:` module is imported and its exported
DRIVERS registered before resolution; untrusted / incompatible / broken code plugins are
skipped (their `via:` stays unknown and the component degrades). Trust binds to a CONTENT hash
(plugin_identity), so it is per-content and transport-independent — no git required.'''

import shutil
import subprocess

import pytest

from configsys import plugins

DRIVER_PY = '''from configsys.plugins import Driver

class Apk(Driver):
    name = 'apk'
    privileged = True

    def install(self, rc):
        return self.runner.run(f'apk add {rc.name}', sudo=self.sudo(rc))

DRIVERS = [Apk]
'''


@pytest.fixture(autouse=True)
def _restore_registry():
    '''Registering a plugin driver mutates the process-global registry; snapshot + restore so
    no registration leaks into other tests.'''
    from configsys.drivers import _REGISTRY
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


def _plugin(pdir, manifest, files):
    '''Materialize a plugin dir — no VCS, since trust is now content-based.'''
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text(manifest)
    for name, text in files.items():
        (pdir / name).write_text(text)
    return pdir


# -- load_code gating (unit, via an injected register) --------------------

def test_load_code_gates_on_content_trust(tmp_path):
    pdir = _plugin(tmp_path / 'plugins' / 'apk-plug',
                   '{ name: apk-plug  requires-abi: 1  code: driver.py }',
                   {'driver.py': DRIVER_PY})
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'github:x/apk-plug'}]
    reg = []

    # untrusted -> not loaded, and the reason is reported
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, decls, reg.append)
    assert loaded == [] and reg == []
    assert skipped and 'untrusted' in skipped[0][1]

    # trust the exact content -> loaded + registered
    plugins.set_trust(tf, 'apk-plug', plugins.plugin_identity(pdir))
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, decls, reg.append)
    assert skipped == []
    assert loaded == [('apk-plug', ['apk'])]
    assert len(reg) == 1 and reg[0].name == 'apk'

    # editing ANY file changes the content identity -> trust no longer applies (re-approve)
    (pdir / 'driver.py').write_text(DRIVER_PY + '\n# edited\n')
    reg.clear()
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, decls, reg.append)
    assert loaded == [] and reg == []
    assert 'untrusted' in dict(skipped)['apk-plug']


def test_non_git_plugin_can_be_trusted(tmp_path):
    # the headline of the content-hash identity: a plugin materialized WITHOUT git (as a
    # tarball / OCI transport would) still has an identity and can be trusted
    pdir = _plugin(tmp_path / 'plugins' / 'tarplug',
                   '{ name: tarplug  requires-abi: 1  code: driver.py }',
                   {'driver.py': DRIVER_PY})
    assert not (pdir / '.git').exists()
    ident = plugins.plugin_identity(pdir)
    assert ident and ident.startswith('sha256:')
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'tarball:pkg/tarplug'}]        # dir_name -> tarplug

    reg = []
    plugins.load_code(tmp_path / 'plugins', tf, decls, reg.append)
    assert reg == []                                   # untrusted
    plugins.set_trust(tf, 'tarplug', ident)
    plugins.load_code(tmp_path / 'plugins', tf, decls, reg.append)
    assert [c.name for c in reg] == ['apk']            # trusted despite no git


def test_importing_code_does_not_invalidate_trust(tmp_path):
    # importing the module may write __pycache__/*.pyc next to it; the identity must EXCLUDE
    # those, or the plugin's own load would flip it to 'changed' on the very next run
    pdir = _plugin(tmp_path / 'plugins' / 'p',
                   '{ name: p  requires-abi: 1  code: driver.py }', {'driver.py': DRIVER_PY})
    tf = tmp_path / 'trust.hu'
    before = plugins.plugin_identity(pdir)
    plugins.set_trust(tf, 'p', before)

    reg = []
    plugins.load_code(tmp_path / 'plugins', tf, [{'source': 'github:x/p'}], reg.append)
    assert reg and reg[0].name == 'apk'                # imported (may emit bytecode)
    assert plugins.plugin_identity(pdir) == before     # identity unchanged


def test_load_code_skips_incompatible_and_broken(tmp_path):
    root = tmp_path / 'plugins'
    _plugin(root / 'old', '{ name: old  requires-abi: 99  code: driver.py }',
            {'driver.py': DRIVER_PY})
    _plugin(root / 'broken', '{ name: broken  requires-abi: 1  code: driver.py }',
            {'driver.py': 'raise RuntimeError("boom")\n'})
    _plugin(root / 'nodrv', '{ name: nodrv  requires-abi: 1  code: driver.py }',
            {'driver.py': '# defines no DRIVERS export\n'})
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'old', 'whatever')           # trusted, but ABI gate comes first
    plugins.set_trust(tf, 'broken', plugins.plugin_identity(root / 'broken'))
    plugins.set_trust(tf, 'nodrv', plugins.plugin_identity(root / 'nodrv'))
    decls = [{'source': 'github:x/old'}, {'source': 'github:x/broken'}, {'source': 'github:x/nodrv'}]
    reg = []
    loaded, skipped = plugins.load_code(root, tf, decls, reg.append)
    assert loaded == [] and reg == []
    reasons = dict(skipped)
    assert 'incompatible' in reasons['old']
    assert 'failed to load' in reasons['broken']
    assert 'failed to load' in reasons['nodrv']        # no DRIVERS export


def test_data_only_plugin_is_not_a_code_candidate(tmp_path):
    root = tmp_path / 'plugins'
    _plugin(root / 'data', '{ name: data  requires-abi: 1  data: [ routes.hu ] }',
            {'routes.hu': '{ components: { d: { install: [ { via: native } ] } } }'})
    loaded, skipped = plugins.load_code(root, tmp_path / 'trust.hu',
                                        [{'source': 'github:x/data'}], (lambda c: None))
    assert loaded == [] and skipped == []              # data-only: nothing to gate, no warning


# -- end-to-end: trust flips `via: apk` from unknown to resolvable (needs git: add clones) --

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_trusted_driver_makes_via_resolve_end_to_end(tmp_path, capsys):
    from configsys.app import main
    src = _plugin(tmp_path / 'src',
                  '{ name: apkp  requires-abi: 1  code: driver.py  data: [ routes.hu ] }',
                  {'driver.py': DRIVER_PY,
                   'routes.hu': '{ os: { alpine: { using: linux  native: apk } }'
                                '  components: { apk-tool: { install: [ { via: apk } ] } } }'})
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'alpine']
    main(home + ['plugin', 'add', str(src)])
    capsys.readouterr()

    # untrusted: the code warning appears (its via: apk is not registered)
    main(home + ['check'])
    assert 'untrusted code' in capsys.readouterr().out

    # trust it -> next run registers apk, the warning is gone
    main(home + ['plugin', 'trust', 'apkp'])
    capsys.readouterr()
    main(home + ['check'])
    assert 'untrusted code' not in capsys.readouterr().out
