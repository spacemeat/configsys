'''Shared pytest fixtures and path setup.

Ensures the repo root is importable (so `import configsys...` works without an
installed package) and provides a fixtures directory helper.
'''

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


@pytest.fixture
def fixtures_dir():
    return FIXTURES
