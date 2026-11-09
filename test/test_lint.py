'''pyflakes stays quiet over tools/ and test/ (review-2026-11-2 tests-tools-20): unused imports, dead
locals and a fixture imported from another test module hide real mistakes in the noise.'''

import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_pyflakes_is_clean_over_tools_and_tests():
    api = pytest.importorskip('pyflakes.api')
    from pyflakes.reporter import Reporter
    out, err = io.StringIO(), io.StringIO()
    n = api.checkRecursive([str(ROOT / 'tools'), str(ROOT / 'test')], Reporter(out, err))
    assert n == 0, out.getvalue() + err.getvalue()
