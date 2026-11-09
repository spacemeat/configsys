'''configsys.sh (review-2026-11-2 B12): it finds the repo through a symlink, keeps YOUR working
directory for relative paths, and picks a new-enough python on EL 9 / Amazon Linux 2023 (python3 =
3.9 beside python3.1x). Stub pythons only — nothing is installed.'''

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.real_runner


def _stub(path, version, log):
    path.write_text(f'''#!/bin/sh
if [ "$1" = "-c" ]; then
  case "$2" in *version_info*) [ "{version}" != "3.9" ]; exit $?;; esac
  exit 0
fi
if [ "$1" = "-V" ]; then echo "Python {version}"; exit 0; fi
echo "$0 cwd=$(pwd) args=$*" >> {log}
exit 0
''')
    path.chmod(0o755)


def _tools(tmp_path):
    """A PATH holding only what the launcher needs before python (the host's own python3.1x must
    not be found)."""
    tools = tmp_path / 'tools'
    tools.mkdir()
    for name in ('readlink', 'dirname'):
        (tools / name).symlink_to(next(p for p in (f'/usr/bin/{name}', f'/bin/{name}') if os.path.exists(p)))
    return tools


def test_a_symlinked_launcher_uses_the_real_repo_and_a_new_enough_python(tmp_path):
    bindir, log = tmp_path / 'bin', tmp_path / 'log'
    bindir.mkdir()
    _stub(bindir / 'python3', '3.9', log)                  # EL 9's python3
    _stub(bindir / 'python3.12', '3.12', log)
    repo = tmp_path / 'repo'                               # a clone with no .venv yet
    repo.mkdir()
    (repo / 'configsys.sh').write_text((REPO / 'configsys.sh').read_text())
    (bindir / 'configsys').symlink_to(repo / 'configsys.sh')
    work = tmp_path / 'work'
    work.mkdir()
    env = {'HOME': str(tmp_path), 'PATH': f'{bindir}:{_tools(tmp_path)}'}
    # the venv fast path fails with the stub (it isn't the venv's python), so the launcher goes on
    # to create the venv with the chosen interpreter: that call names which python it picked
    subprocess.run(['/bin/bash', str(bindir / 'configsys'), '--help'], cwd=work, env=env,
                   capture_output=True, timeout=60)
    logged = log.read_text() if log.exists() else ''
    assert 'python3.12' in logged and f'cwd={repo}' in logged   # the real repo, not ~/…/bin
    assert '/python3 ' not in logged                            # never the 3.9 one


def test_no_new_enough_python_names_the_fix(tmp_path):
    bindir, log = tmp_path / 'bin', tmp_path / 'log'
    bindir.mkdir()
    _stub(bindir / 'python3', '3.9', log)
    r = subprocess.run(['/bin/bash', str(REPO / 'configsys.sh'), '--help'], cwd=tmp_path,
                       env={'HOME': str(tmp_path), 'PATH': f'{bindir}:{_tools(tmp_path)}'},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and 'PYTHON=' in r.stderr and '3.9' in r.stderr


def test_the_app_returns_to_the_invoking_directory(tmp_path):
    r = subprocess.run([str(REPO / '.venv' / 'bin' / 'python'), '-c',
                        'import os, configsys.__main__; print(os.getcwd())'],
                       cwd=REPO, env={**os.environ, 'CONFIGSYS_INVOKED_CWD': str(tmp_path)},
                       capture_output=True, text=True)
    assert r.stdout.strip() == str(tmp_path)
