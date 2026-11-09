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
    repo = tmp_path / 'repo'                               # no .venv: a healthy one is used first
    repo.mkdir()
    (repo / 'configsys.sh').write_text((REPO / 'configsys.sh').read_text())
    r = subprocess.run(['/bin/bash', str(repo / 'configsys.sh'), '--help'], cwd=tmp_path,
                       env={'HOME': str(tmp_path), 'PATH': f'{bindir}:{_tools(tmp_path)}'},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and 'PYTHON=' in r.stderr and '3.9' in r.stderr


def test_the_app_returns_to_the_invoking_directory(tmp_path):
    r = subprocess.run([str(REPO / '.venv' / 'bin' / 'python'), '-c',
                        'import os, configsys.__main__; print(os.getcwd())'],
                       cwd=REPO, env={**os.environ, 'CONFIGSYS_INVOKED_CWD': str(tmp_path)},
                       capture_output=True, text=True)
    assert r.stdout.strip() == str(tmp_path)


def test_a_shell_start_never_repairs_the_venv(tmp_path):
    # A15 / dotfiles-glue-12: the preludes call the launcher with CONFIGSYS_NO_BOOTSTRAP; a broken
    # venv then exits 75 (the prelude keeps its cache) — no venv rebuild, no hidden `sudo apt-get`
    import shutil
    repo = tmp_path / 'repo'
    repo.mkdir()
    shutil.copy(REPO / 'configsys.sh', repo / 'configsys.sh')
    r = subprocess.run(['bash', str(repo / 'configsys.sh'), 'location', '--all'],
                       env={**os.environ, 'CONFIGSYS_NO_BOOTSTRAP': '1'}, capture_output=True, text=True)
    assert r.returncode == 75
    assert not (repo / '.venv').exists()


def _venv_stub(repo, log, *, healthy):
    '''A repo `.venv/bin/python` that logs its argv: healthy = the fast-path probe passes; else the
    probe and the deps import fail (a fresh venv), while pip "works".'''
    vpy = repo / '.venv' / 'bin' / 'python'
    vpy.parent.mkdir(parents=True)
    vpy.write_text(f'''#!/bin/sh
echo "$*" >> {log}
case "$*" in
  *find_spec*) {'exit 0' if healthy else 'exit 1'};;
  *"import humon, packaging"*) exit 1;;
esac
exit 0
''')
    vpy.chmod(0o755)


def test_a_healthy_venv_starts_one_interpreter_with_E(tmp_path):
    # dotfiles-glue-36: the python floor search ran before the venv fast path (two extra starts);
    # dotfiles-glue-35: and the exec lacked -E, so a PYTHONPATH could shadow the venv's packages
    bindir, plog, vlog = tmp_path / 'bin', tmp_path / 'py.log', tmp_path / 'venv.log'
    bindir.mkdir()
    for v in ('3', '3.14', '3.13', '3.12', '3.11', '3.10'):
        _stub(bindir / f'python{v}', '3.12', plog)
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'configsys.sh').write_text((REPO / 'configsys.sh').read_text())
    _venv_stub(repo, vlog, healthy=True)
    r = subprocess.run(['/bin/bash', str(repo / 'configsys.sh'), 'inspect'], cwd=tmp_path,
                       env={'HOME': str(tmp_path), 'PATH': f'{bindir}:{_tools(tmp_path)}',
                            'PYTHONPATH': str(tmp_path / 'shadow')},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert not plog.exists()                                    # no candidate python was started
    calls = vlog.read_text().splitlines()
    assert len(calls) == 2 and calls[0].startswith('-E -c ') and calls[1] == '-E -m configsys inspect'


def test_the_bootstrap_installs_the_bounded_deps_from_pyproject(tmp_path):
    # dotfiles-glue-35: `pip install humon packaging` took whatever was newest; the bounds now live in
    # pyproject.toml's one `dependencies` line, which the launcher reads
    import re
    bindir, plog, vlog = tmp_path / 'bin', tmp_path / 'py.log', tmp_path / 'venv.log'
    bindir.mkdir()
    _stub(bindir / 'python3', '3.12', plog)
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'configsys.sh').write_text((REPO / 'configsys.sh').read_text())
    (repo / 'pyproject.toml').write_text((REPO / 'pyproject.toml').read_text())
    _venv_stub(repo, vlog, healthy=False)
    r = subprocess.run(['/bin/bash', str(repo / 'configsys.sh'), 'inspect'], cwd=tmp_path,
                       env={'HOME': str(tmp_path), 'PATH': f'{bindir}:{_tools(tmp_path)}',
                            '_CONFIGSYS_REPAIR_LOCKED': '1'},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    deps = re.search(r'^dependencies = \[(.*)\]$', (REPO / 'pyproject.toml').read_text(), re.M).group(1)
    want = re.findall(r'"([^"]*)"', deps)
    assert want and all(re.search(r'[<>=]=?\s*\d', d) for d in want)          # every dep is bounded
    assert f'-m pip install -q {" ".join(want)}' in vlog.read_text().splitlines()
    assert vlog.read_text().splitlines()[-1] == '-E -m configsys inspect'
