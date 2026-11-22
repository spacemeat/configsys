'''tools/chimeranames.py — the generator of routes.hu's `component-names: { chimera-apk: … }` block:
its rename rules (accepted only when the name is in Chimera's index), the dev-library pass, the
human review (rename / reject first), the iterate-until-stable loop, and the marked region it owns.'''

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import chimeranames as cn  # noqa: E402

from configsys.routes import Resolver  # noqa: E402

OS = ('os: { linux: { provides: python3 }  alpine: { using: linux  native: apk }  '
      'chimera: { using: linux  native: chimera-apk } }  '
      'drivers: { tarball: { requires: curl } }')


def _gen(tmp_path, monkeypatch, comps, index, review=({}, {})):
    routes = tmp_path / 'routes.hu'
    routes.write_text('{ ' + OS + '  components: { ' + comps + ' }\n'
                      f'    {cn.BEGIN}\n    {cn.END}\n}}\n')
    monkeypatch.setattr(cn, 'ROUTES', str(routes))
    return cn.generate(set(index), review)


def test_parse_index_reads_names_off_apk_search():
    assert cn.parse_index('bat-0.26.1-r0\npython-devel-3.14.6-r2\n7zip-26.03-r0\nnoise\n') == \
        {'bat', 'python-devel', '7zip'}


def test_candidates_are_in_the_documented_order():
    class B:
        details = {'name': {'apk': 'py3-foo-dev', 'xbps': 'foo-devel', 'pacman': 'python-foo'}}
    assert [n for n, _ in cn.candidates('libfoo-dev', 'foo', B())] == [
        'libfoo-devel', 'foo', 'py3-foo-dev', 'py3-foo-devel', 'python-foo-dev', 'foo-devel', 'python-foo']


def test_rules_only_accept_names_chimera_has_and_unknowns_become_empty(tmp_path, monkeypatch):
    comps = ('pip: { install: [ { via: native  name: { apk: py3-pip  default: python3-pip } } ] }'
             '  hdr: { attrs: [ lib ]  install: [ { via: native  name: { apk: hdr-dev } } ] }'
             '  same: { install: [ { via: native } ] }'
             '  gone: { install: [ { via: native } ] }')
    entries, notes = _gen(tmp_path, monkeypatch, comps, {'python-pip', 'hdr', 'hdr-devel', 'same'})
    assert entries == {'pip': 'python-pip', 'hdr': 'hdr-devel', 'gone': None}   # `same` exists as-is
    assert 'py3- -> python-' in notes['pip'] and 'dev package' in notes['hdr']


def test_review_renames_and_rejects_come_first(tmp_path, monkeypatch):
    comps = ('fuse: { install: [ { via: native } ] }  dig: { install: [ { via: native  name: { pacman: bind  default: bind-utils } } ] }')
    review = ({'fuse': 'Chimera has fuse 3 only'}, {'dig': 'bind-progs'})
    entries, _ = _gen(tmp_path, monkeypatch, comps, {'fuse', 'bind', 'bind-progs'}, review)
    assert entries == {'fuse': None, 'dig': 'bind-progs'}             # not `bind` (Arch's name)
    with pytest.raises(SystemExit):                                    # a stale reviewed rename is loud
        _gen(tmp_path, monkeypatch, comps, {'fuse', 'bind'}, review)


def test_an_empty_entry_is_iterated_until_stable(tmp_path, monkeypatch):
    # round 1: `tool` resolves to its (more specific) tarball, and `curl` isn't packaged -> `{}`.
    # That closes the tarball driver (its curl requirement), so round 2 sees tool's NATIVE unit —
    # a name nobody checked yet
    comps = ('tool: { install: [ { via: tarball  when: "chimera"  url: "https://x/t.tgz"  installDir: /opt/t }'
             '                   { via: native  name: { default: tool-pkg } } ] }'
             '  curl: { install: [ { via: native  name: { default: curl-gone } } ] }')
    entries, _ = _gen(tmp_path, monkeypatch, comps, {'tool'})
    assert entries == {'curl': None, 'tool': 'tool'}


def test_render_and_splice_own_only_the_marked_region():
    block = cn.render({'b': None, 'a': 'x'}, {'a': 'was y', 'b': 'gone'})
    lines = block.splitlines()
    assert lines[0].strip() == cn.BEGIN and lines[-1].strip() == cn.END
    assert [ln.split()[0] for ln in lines[3:5]] == ['a:', 'b:']        # sorted, one per line
    text = f'before\n    {cn.BEGIN}\n    old\n    {cn.END}\nafter\n'
    assert cn.splice(text, block) == 'before\n' + block + 'after\n'


def test_the_routes_block_names_only_real_components_and_the_review_is_current():
    r = Resolver(os.path.join(ROOT, 'routes.hu'), 'chimera', None, 'x86_64')
    names = r.overrides.get('chimera-apk') or {}
    assert names and set(names) <= set(r.components)
    reject, rename = cn.load_review()
    assert set(reject) | set(rename) <= set(r.components)
    assert all(names.get(c) == p for c, p in rename.items() if c in names)
    assert all(names.get(c) == {} for c in reject if c in names)
