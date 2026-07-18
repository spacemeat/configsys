'''P2b (2/2) — the import gate. A trusted code plugin's `code:` module is imported and its
exported DRIVERS registered before resolution; untrusted / incompatible / broken code plugins
are skipped (their `via:` stays unknown and the component degrades). Trust is per-commit.'''

import os
import shutil
import subprocess

import pytest

from configsys import plugins
from configsys.runner import Runner

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


def _git_plugin(pdir, manifest, files):
    '''Create a plugin dir that is its own git repo (init in place). Returns its HEAD sha.'''
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text(manifest)
    for name, text in files.items():
        (pdir / name).write_text(text)
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'init']):
        subprocess.run(['git', *cmd], cwd=pdir, check=True)
    return subprocess.run(['git', '-C', str(pdir), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()


pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


# -- load_code gating (unit, via an injected register) --------------------

def test_load_code_gates_on_per_commit_trust(tmp_path):
    pdir = tmp_path / 'plugins' / 'apk-plug'
    head = _git_plugin(pdir, '{ name: apk-plug  requires-abi: 1  code: driver.py }',
                       {'driver.py': DRIVER_PY})
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'github:x/apk-plug', 'ref': None}]     # dir_name -> 'apk-plug'
    reg = []

    # untrusted -> not loaded, and the reason is reported
    loaded, skipped = plugins.load_code(Runner(pretend=False), tmp_path / 'plugins', tf, decls,
                                        reg.append)
    assert loaded == [] and reg == []
    assert skipped and 'untrusted' in skipped[0][1]

    # trust the exact commit -> loaded + registered
    plugins.set_trust(tf, 'apk-plug', head)
    loaded, skipped = plugins.load_code(Runner(pretend=False), tmp_path / 'plugins', tf, decls,
                                        reg.append)
    assert skipped == []
    assert loaded == [('apk-plug', ['apk'])]
    assert len(reg) == 1 and reg[0].name == 'apk'

    # a moved commit invalidates the trust (trust is bound to the approved sha)
    subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'moved'], cwd=pdir, check=True)
    reg.clear()
    loaded, skipped = plugins.load_code(Runner(pretend=False), tmp_path / 'plugins', tf, decls,
                                        reg.append)
    assert loaded == [] and reg == []
    assert 'untrusted' in dict(skipped)['apk-plug']            # code changed -> re-approve


def test_load_code_skips_incompatible_and_broken(tmp_path):
    pdir = tmp_path / 'plugins'
    _git_plugin(pdir / 'old', '{ name: old  requires-abi: 99  code: driver.py }',
                {'driver.py': DRIVER_PY})
    h2 = _git_plugin(pdir / 'broken', '{ name: broken  requires-abi: 1  code: driver.py }',
                     {'driver.py': 'raise RuntimeError("boom")\n'})
    h3 = _git_plugin(pdir / 'nodrv', '{ name: nodrv  requires-abi: 1  code: driver.py }',
                     {'driver.py': '# defines no DRIVERS export\n'})
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'old', 'whatever')       # trusted, but ABI gate comes first
    plugins.set_trust(tf, 'broken', h2)
    plugins.set_trust(tf, 'nodrv', h3)
    decls = [{'source': 'github:x/old'}, {'source': 'github:x/broken'}, {'source': 'github:x/nodrv'}]
    reg = []
    loaded, skipped = plugins.load_code(Runner(pretend=False), pdir, tf, decls, reg.append)
    assert loaded == [] and reg == []
    reasons = dict(skipped)
    assert 'incompatible' in reasons['old']
    assert 'failed to load' in reasons['broken']
    assert 'failed to load' in reasons['nodrv']                # no DRIVERS export


def test_data_only_plugin_is_not_a_code_candidate(tmp_path):
    pdir = tmp_path / 'plugins'
    _git_plugin(pdir / 'data', '{ name: data  requires-abi: 1  data: [ routes.hu ] }',
                {'routes.hu': '{ components: { d: { install: [ { via: native } ] } } }'})
    loaded, skipped = plugins.load_code(Runner(pretend=False), pdir, tmp_path / 'trust.hu',
                                        [{'source': 'github:x/data'}], (lambda c: None))
    assert loaded == [] and skipped == []          # data-only: nothing to gate, no warning


# -- end-to-end: trust flips `via: apk` from unknown to resolvable ---------

def test_trusted_driver_makes_via_resolve_end_to_end(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    _git_plugin(src, '{ name: apkp  requires-abi: 1  code: driver.py  data: [ routes.hu ] }',
                {'driver.py': DRIVER_PY,
                 'routes.hu': '{ os: { alpine: { using: linux  native: apk } }'
                              '  components: { apk-tool: { install: [ { via: apk } ] } } }'})
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
