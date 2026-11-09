'''pyproject.toml — the wheel's force-include and the sdist's include list name paths that exist,
and cover every repo-root data file Paths reads (review-2026-11-2 tests-tools-11: a stale
`dotfiles` entry broke the build and `glue/` was never shipped).'''

from pathlib import Path

import pytest

from configsys.paths import Paths

try:
    import tomllib
except ModuleNotFoundError:                     # python 3.10
    tomllib = pytest.importorskip('tomli')

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def hatch():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        return tomllib.load(f)['tool']['hatch']['build']['targets']


def test_every_force_include_source_exists(hatch):
    missing = [src for src in hatch['wheel']['force-include'] if not (ROOT / src).exists()]
    assert not missing, f'force-include sources not in the repo: {missing}'


def test_the_wheel_ships_every_repo_root_file_paths_reads(hatch, tmp_path):
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_REPO': str(ROOT)})
    shipped = hatch['wheel']['force-include']
    for path in (p.routes_file, p.config_file, p.glue_dir, ROOT / 'man'):
        rel = Path(path).relative_to(ROOT).as_posix()
        assert shipped.get(rel) == f'configsys/data/{rel}', f'{rel} is not in the wheel'


def test_the_sdist_is_self_checking(hatch):
    include = hatch['sdist']['include']
    assert not [i for i in include if not (ROOT / i).exists()]
    for needed in ('test', 'tools', 'examples', 'glue'):
        assert needed in include
