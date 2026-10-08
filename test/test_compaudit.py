'''tools/compaudit.py — the mechanical half of /update-component. Offline: probes run against a
fake fetcher, scope loading against the real routes.hu + a throwaway plugin dir.'''

import importlib.util
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('compaudit', HERE.parent / 'tools' / 'compaudit.py')
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


class FakeFetcher:
    '''url -> (status, final_url, body); unknown urls 404.'''
    def __init__(self, routes, token=None):
        self.routes, self.token = routes, token

    def get(self, url, follow=True):
        return self.routes.get(url, (404, url, None))


def test_asset_globs_flatten_arch_and_format_maps():
    b = {'asset': {'deb': {'x86_64': 'a_amd64.deb', 'aarch64': 'a_arm64.deb'}, 'rpm': {'x86_64': 'a.rpm'}}}
    assert sorted(ca._asset_globs(b, {})) == ['a.rpm', 'a_amd64.deb', 'a_arm64.deb']
    assert ca._asset_globs({}, {'asset': 'x-*-$ARCH.AppImage'}) == ['x-*-aarch64.AppImage', 'x-*-x86_64.AppImage']


def test_github_rename_via_redirect_and_asset_glob_miss():
    f = FakeFetcher({
        'https://github.com/old/tool': (301, 'https://github.com/new/tool', None),
        'https://github.com/new/tool/releases/latest': (302, 'https://github.com/new/tool/releases/tag/v2.0', None),
        'https://github.com/new/tool/releases/expanded_assets/v2.0':
            (200, '', '<a href="/new/tool/releases/download/v2.0/tool-2.0-linux-x86_64.tar.gz">'),
    })
    assets = [{'component': 'tool', 'via': 'tarball', 'when': None, 'glob': 'tool-*-linux-x86_64.tar.gz'},
              {'component': 'tool', 'via': 'appImage', 'when': 'not alpine', 'glob': 'tool-*.AppImage'}]
    facts, finds = ca.probe_github(f, 'old/tool', assets)
    cats = [x['category'] for x in finds]
    assert facts['full_name'] == 'new/tool' and facts['latest_tag'] == 'v2.0'
    assert cats == ['repo-renamed', 'asset-glob-miss']
    assert finds[0]['proposed'] == 'github: new/tool'
    assert 'tool-*.AppImage' in finds[1]['summary'] and finds[1]['binding'] == 'via:appImage when:"not alpine"'


def test_github_gone_and_no_release_at_all():
    _f, finds = ca.probe_github(FakeFetcher({}), 'ghost/repo', [])
    assert [x['category'] for x in finds] == ['repo-gone']
    f = FakeFetcher({'https://github.com/a/b': (200, 'https://github.com/a/b', '')})
    _f, finds = ca.probe_github(f, 'a/b', [{'component': 'b', 'via': 'tarball', 'when': None, 'glob': '*'}])
    assert [x['category'] for x in finds] == ['asset-glob-miss'] and '(no releases)' in finds[0]['summary']


REPO_OK = ('https://github.com/a/b', (200, 'https://github.com/a/b', ''))


def _rel(repo, tag, *names):
    html = ''.join(f'<a href="/{repo}/releases/download/{tag}/{n}">' for n in names)
    return f'https://github.com/{repo}/releases/expanded_assets/{tag}', (200, '', html)


def test_asset_match_is_case_insensitive_like_the_driver():
    f = FakeFetcher(dict([REPO_OK,
        ('https://github.com/a/b/releases/latest', (302, 'https://github.com/a/b/releases/tag/v1', None)),
        _rel('a/b', 'v1', 'tool_1_linux_x86_64.tar.gz')]))
    _f, finds = ca.probe_github(f, 'a/b', [{'component': 'b', 'via': 'tarball', 'when': None,
                                            'glob': 'tool_*_Linux_x86_64.tar.gz'}])
    assert finds == []


def test_prerelease_only_and_asset_only_in_older_release():
    page = '<a href="/a/b/releases/tag/nightly">'
    f = FakeFetcher(dict([REPO_OK, ('https://github.com/a/b/releases', (200, '', page)),
                          _rel('a/b', 'nightly', 'App-abc-x86_64.AppImage')]))
    asset = {'component': 'b', 'via': 'appImage', 'when': None, 'glob': 'App-*-x86_64.AppImage'}
    _f, finds = ca.probe_github(f, 'a/b', [asset])
    assert [x['category'] for x in finds] == ['prerelease-only']
    page = '<a href="/a/b/releases/tag/v2"><a href="/a/b/releases/tag/v1">'
    f = FakeFetcher(dict([REPO_OK, ('https://github.com/a/b/releases/latest', (302, 'https://github.com/a/b/releases/tag/v2', None)),
                          ('https://github.com/a/b/releases', (200, '', page)),
                          _rel('a/b', 'v2', 'other.zip'), _rel('a/b', 'v1', 'App-1-x86_64.AppImage')]))
    _f, finds = ca.probe_github(f, 'a/b', [asset])
    assert [x['category'] for x in finds] == ['asset-not-in-latest'] and 'v1' in finds[0]['summary']


def test_arch_unguarded_static_check():
    hard = {'via': 'tarball', 'version': {'github': 'a/b', 'asset': 'b_*_linux_x86_64.tar.gz'}}
    assert ca._arch_unguarded('b', hard, hard['version'])['category'] == 'arch-unguarded'
    gated = dict(hard, when='cpu: x86_64')
    assert ca._arch_unguarded('b', gated, gated['version']) is None
    templ = {'via': 'appImage', 'version': {'github': 'a/b', 'asset': 'b-$ARCH.AppImage'}}
    assert ca._arch_unguarded('b', templ, templ['version']) is None
    flat = {'via': 'flatpak', 'app': 'org.x86_64.App'}
    assert ca._arch_unguarded('b', flat, {}) is None


def test_github_token_mode_reads_archived_and_license():
    body = json.dumps({'full_name': 'a/b', 'archived': True, 'license': {'spdx_id': 'BUSL-1.1'}, 'pushed_at': 'x'})
    f = FakeFetcher({'https://api.github.com/repos/a/b': (200, '', body)}, token='t')
    facts, finds = ca.probe_github(f, 'a/b', [])
    assert facts['license'] == 'BUSL-1.1' and facts['archived'] is True
    assert [x['category'] for x in finds] == ['repo-archived']


def test_flatpak_eol_rebase_and_missing():
    f = FakeFetcher({'https://flathub.org/api/v2/appstream/org.ok.App': (200, '', '{}'),
                     'https://flathub.org/api/v2/appstream/org.new.App': (200, '', '{}')})
    assert ca.probe_flatpak(f, 'org.ok.App', {}, {})[1] == []
    renamed = ca.rebase_old_to_new({'org.new.App': ['org.old.App']})   # Flathub: {new: [olds]}
    assert ca.probe_flatpak(f, 'org.new.App', renamed, {})[1] == []      # the NEW id is fine
    _f, finds = ca.probe_flatpak(f, 'org.old.App', renamed, {})
    assert finds[0]['category'] == 'flatpak-renamed' and finds[0]['proposed'] == 'app: org.new.App'
    _f, finds = ca.probe_flatpak(f, 'org.gone.App', {}, {})
    assert finds[0]['category'] == 'flatpak-missing'


def test_aur_missing_orphaned_outofdate_promoted():
    body = json.dumps({'results': [{'Name': 'orph', 'Maintainer': None, 'OutOfDate': 1700000000, 'Version': '1'}]})
    url = 'https://aur.archlinux.org/rpc/v5/info?arg[]=orph&arg[]=gone&arg[]=promo'
    arch = 'https://archlinux.org/packages/search/json/?name='
    out = ca.probe_aur(FakeFetcher({url: (200, url, body),
                                    arch + 'gone': (200, '', json.dumps({'results': []})),
                                    arch + 'promo': (200, '', json.dumps({'results': [{'repo': 'extra', 'pkgver': '2'}]}))}),
                       ['orph', 'gone', 'promo'])
    assert [x['category'] for x in out['orph'][1]] == ['aur-orphaned', 'aur-out-of-date']
    assert [x['category'] for x in out['gone'][1]] == ['aur-missing']
    assert [x['category'] for x in out['promo'][1]] == ['aur-promoted'] and '[extra]' in out['promo'][1][0]['summary']


def test_base_scope_groups_companions_with_their_parent():
    _label, _root, units = ca.load_scope('base')
    assert 'ghostty-dotfiles' not in units and 'ghostty-glue' not in units
    g = units['ghostty']
    assert set(g['components']) >= {'ghostty', 'ghostty-dotfiles', 'ghostty-glue'}
    assert 'pkgforge-dev/ghostty-appimage' in g['probes']['github']
    glue = g['components']['ghostty-glue'].get('glue_files')
    assert glue and all(v for v in glue.values())      # every referenced glue ships a variant


def test_plugin_scope_is_only_what_the_plugin_defines(tmp_path):
    p = tmp_path / 'configsys-fake'
    p.mkdir()
    (p / 'plugin.hu').write_text('{ name: configsys-fake  requires-abi: 1  data: [ fake.hu ] }')
    (p / 'fake.hu').write_text('{ components: {\n'
                               '    ripgrep: { install: [ { via: aur  when: "arch"  name: ripgrep-git } ] }\n'
                               '    fakeapp: { description: "x"  install: [ { via: flatpak  hub: flathub  app: org.fake.App } ] }\n'
                               '} }')
    label, root, units = ca.load_scope(str(p))
    assert label == 'configsys-fake' and root == p.resolve()
    assert sorted(units) == ['fakeapp', 'ripgrep']
    rg = units['ripgrep']['components']['ripgrep']['layers']
    assert [l['in_scope'] for l in rg] == [False, True]   # base definition shown, plugin layer marked
    assert units['ripgrep']['probes'] == {'aur': ['ripgrep-git']}   # only IN-SCOPE bindings probed
    assert units['fakeapp']['probes'] == {'flatpak': ['org.fake.App']}


def test_ledger_due_logic(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    units = {'a': {'def_hash': 'h1'}, 'b': {'def_hash': 'h2'}, 'c': {'def_hash': 'h3', 'probe_findings': [1]}}
    assert ca.due(units, 'base', 30) == ['a', 'b', 'c']
    ca.record('base', units, ['a', 'b', 'c'])
    assert ca.due(units, 'base', 30) == ['c']               # probe findings always re-audit
    units['b']['def_hash'] = 'changed'
    assert ca.due(units, 'base', 30) == ['b', 'c']
    assert units['b']['due_reason'] == 'definition changed'
