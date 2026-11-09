'''`--pretend` is a full dry run for the plugin verbs too: trust / untrust / trust --all / update /
lock / unlock / init / diff / add print what they would do and leave every file exactly as it was.'''

import shutil
import subprocess

import pytest

from configsys import plugins
from configsys.app import main

pytestmark = [pytest.mark.real_runner, pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob('*')) if '.git' not in p.parts}


def _codeplug(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: codeplug  requires-abi: 1  code: driver.py }')
    (src / 'driver.py').write_text('# a driver\n')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'A'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    (src / 'driver.py').write_text('# v2\n')
    subprocess.run(['git', 'commit', '-qam', 'B'], cwd=src, check=True)
    subprocess.run(['git', 'tag', 'v2'], cwd=src, check=True)
    return src


def test_plugin_verbs_write_nothing_under_pretend(tmp_path, capsys):
    src = _codeplug(tmp_path)
    home = ['--home', str(tmp_path), '--os', 'pop']
    assert main(home + ['plugin', 'add', str(src), '--ref', 'v1']) == 0
    state = tmp_path / '.config' / 'configsys'
    (state / 'glue-locations.tsv').write_text('x\t/opt/x\n')
    before = _snapshot(state)
    dry = home + ['--pretend']

    main(dry + ['plugin', 'trust', 'codeplug'])
    assert 'would trust codeplug' in capsys.readouterr().out
    main(dry + ['plugin', 'trust', '--all'])
    assert 'would trust 1 plugin' in capsys.readouterr().out
    main(dry + ['plugin', 'update', 'codeplug', '--ref', 'v2'])
    assert 'would re-pin' in capsys.readouterr().out
    main(dry + ['plugin', 'lock', 'codeplug'])
    main(dry + ['plugin', 'diff', 'codeplug', '--to', 'v2'])
    main(dry + ['plugin', 'add', 'github:nobody/configsys-nothing'])
    main(dry + ['plugin', 'init', 'configsys-me'])
    assert '--pretend — nothing written' in capsys.readouterr().out
    main(dry + ['location', '--all'])
    assert _snapshot(state) == before

    # and untrust, once there is a trust to revoke
    assert main(home + ['plugin', 'trust', 'codeplug']) == 0
    before = _snapshot(state)
    main(dry + ['plugin', 'untrust', 'codeplug'])
    assert 'would untrust codeplug' in capsys.readouterr().out
    assert _snapshot(state) == before
    assert 'src' in plugins.read_trust(state / 'plugin-trust.hu')
