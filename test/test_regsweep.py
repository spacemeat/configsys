'''tools/regsweep.py — the registry-existence sweep, against a fake fetcher (no network): identity
confirmation by upstream repo, the probable / rejected buckets, and its HTTP layer being compaudit's
cached Fetcher with a project-URL User-Agent (review-2026-11-2 tests-tools-16, -21).'''

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import regsweep  # noqa: E402


class FakeFetcher:
    '''url -> (status, final_url, body); unknown urls 404. Records every url asked for.'''
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def get(self, url, follow=True):
        self.urls.append(url)
        return self.routes.get(url, (404, url, None))


def _json(url, doc):
    return url, (200, url, json.dumps(doc))


@pytest.fixture
def fetch(monkeypatch):
    def install(routes):
        f = FakeFetcher(dict(routes))
        monkeypatch.setattr(regsweep, '_FETCHER', f)
        return f
    return install


def test_the_user_agent_names_the_project_not_a_person():
    assert '@' not in regsweep.UA
    assert 'github.com/spacemeat/configsys' in regsweep.UA


def test_probes_go_through_the_fetcher(fetch):
    f = fetch([_json('https://crates.io/api/v1/crates/zoxide',
                     {'crate': {'repository': 'https://github.com/ajeetdsouza/zoxide'}}),
               _json('https://pypi.org/pypi/tldr/json',
                     {'info': {'project_urls': {'Source': 'https://github.com/tldr-pages/tldr-python-client'}}}),
               _json('https://registry.npmjs.org/@scope/tool',
                     {'repository': {'url': 'git+https://github.com/o/tool.git'}})])
    assert regsweep.crates_probe('zoxide') == (True, 'ajeetdsouza/zoxide')
    assert regsweep.pypi_probe('tldr') == (True, 'tldr-pages/tldr-python-client', True)
    assert regsweep.npm_probe('@scope/tool') == (True, 'o/tool')
    assert regsweep.crates_probe('nope') == (False, None)                # a 404
    assert f.urls[-1] == 'https://crates.io/api/v1/crates/nope'


def test_a_failed_fetch_or_bad_json_is_a_miss_not_a_crash(fetch):
    fetch({'https://crates.io/api/v1/crates/x': (None, 'https://crates.io/api/v1/crates/x', None),
           'https://crates.io/api/v1/crates/y': (200, 'https://crates.io/api/v1/crates/y', 'not json')})
    assert regsweep.crates_probe('x') == (False, None)
    assert regsweep.crates_probe('y') == (False, None)


def _comp(name, **kw):
    c = dict(name=name, attrs=[], vias=['tarball'], github=None, crates=None, pypi=None, names={}, desc='')
    c.update(kw)
    return c


def test_sweep_confirms_only_an_identity_match(fetch):
    fetch([_json('https://crates.io/api/v1/crates/zoxide',
                 {'crate': {'repository': 'https://github.com/ajeetdsouza/zoxide'}}),
           _json('https://crates.io/api/v1/crates/bat', {'crate': {'repository': 'https://github.com/someone/else'}})])
    rep = regsweep.sweep([_comp('zoxide', github='ajeetdsouza/zoxide'),
                          _comp('bat', github='sharkdp/bat'),
                          _comp('ghost', github='o/ghost')], only={'cargo'})
    assert [(r['comp'], r['via']) for r in rep['confirmed']] == [('zoxide', 'cargo')]
    assert [r['comp'] for r in rep['probable']] == ['bat']                # same name, other repo
    assert [r['comp'] for r in rep['rejected']] == ['ghost']              # no crate at all


def test_sweep_skips_a_method_the_component_already_has(fetch):
    f = fetch([])
    rep = regsweep.sweep([_comp('ripgrep', vias=['cargo'], github='burntsushi/ripgrep')], only={'cargo'})
    assert rep == {'confirmed': [], 'probable': [], 'rejected': []} and f.urls == []


def test_norm_repo_reads_forge_urls():
    assert regsweep.norm_repo('https://github.com/Owner/Repo.git') == 'owner/repo'
    assert regsweep.norm_repo('https://gitlab.com/a/b') == 'gitlab.com:a/b'
    assert regsweep.norm_repo('owner/repo') == 'owner/repo'
    assert regsweep.norm_repo('https://example.org/') is None
