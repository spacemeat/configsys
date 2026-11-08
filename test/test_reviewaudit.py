'''tools/reviewaudit.py — the /review-code area map: glob matching, coverage gaps, carry-over
lookup of the earlier review. (Whether the shipped map covers today's tree is the skill's Phase 0
check, not CI's: a new module shouldn't fail the suite.)'''

import importlib.util
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('reviewaudit', HERE.parent / 'tools' / 'reviewaudit.py')
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)


def test_glob_star_stays_in_one_segment_and_double_star_crosses():
    assert ra.glob_regex('configsys/*.py').match('configsys/app.py')
    assert not ra.glob_regex('configsys/*.py').match('configsys/tui/menu.py')
    assert ra.glob_regex('configsys/**/*.py').match('configsys/app.py')
    assert ra.glob_regex('configsys/**/*.py').match('configsys/tui/screens/base.py')
    assert ra.glob_regex('glue/**').match('glue/shell/fish/yazi.fish')
    assert not ra.glob_regex('configsys.sh').match('configsysXsh')


def _map(tmp_path, text):
    path = tmp_path / 'areas.hu'
    path.write_text(text, encoding='utf-8')
    return ra.load_map(path)


def test_coverage_reports_unowned_shared_dead_and_missing_context(tmp_path):
    amap = _map(tmp_path, '''{
        track: [ "pkg/*.py" ]
        areas: {
            one: { title: "One"  files: [ "pkg/a.py"  "pkg/gone.py" ]  context: [ "docs/nope.md" ] }
            two: { title: "Two"  files: [ "pkg/a.py" ] }
            sec: { title: "Sec"  cross: true  context: [ "pkg/b.py" ] }
        }
    }''')
    files = ['pkg/a.py', 'pkg/b.py', 'README.md']
    gaps = ra.coverage(amap, files, root=tmp_path)
    assert gaps['unowned'] == ['pkg/b.py']              # cross areas own nothing
    assert gaps['shared'] == {'pkg/a.py': ['one', 'two']}
    assert gaps['dead_globs'] == [{'area': 'one', 'glob': 'pkg/gone.py'}]
    assert gaps['missing_context'] == [{'area': 'one', 'path': 'docs/nope.md'}]


def test_scalar_fields_become_lists_and_cross_is_a_bool(tmp_path):
    amap = _map(tmp_path, '{ track: "x/*"  areas: { a: { files: "x/a"  cross: false } } }')
    spec = amap['areas']['a']
    assert amap['track'] == ['x/*']
    assert spec['files'] == ['x/a'] and spec['focus'] == [] and spec['cross'] is False


def test_prior_review_inherits_own_key_and_was_names(tmp_path):
    amap = _map(tmp_path, '''{ track: []  areas: {
        routing: { files: []  was: [ "routing-engine" ] }
        primary: { files: [] }
    } }''')
    old = tmp_path / 'docs' / 'review-2026-09'
    old.mkdir(parents=True)
    (old / 'README.md').write_text('# review\n\nsnapshot against HEAD ~`7c0c04d`/`fcafb84`\n')
    (old / 'routing-engine.md').write_text('x')
    new = tmp_path / 'docs' / 'review-2026-11'
    new.mkdir()
    (new / 'README.md').write_text('Baseline: `abc1234`\n')
    (new / 'primary.md').write_text('x')

    latest = ra.prior_review(amap, root=tmp_path)
    assert latest['dir'] == 'docs/review-2026-11' and latest['baseline'] == 'abc1234'
    assert latest['inherits']['primary'] == ['docs/review-2026-11/primary.md']

    earlier = ra.prior_review(amap, before=str(new), root=tmp_path)
    assert earlier['baseline'] == '7c0c04d'
    assert earlier['inherits'] == {'routing': ['docs/review-2026-09/routing-engine.md'],
                                   'primary': []}


def test_since_lists_changed_areas_and_always_the_cross_ones(tmp_path):
    def git(*args):
        subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', 'user.email=t@t',
                        *args], check=True, capture_output=True)
    git('init', '-q')
    (tmp_path / 'a.py').write_text('1\n')
    (tmp_path / 'b.py').write_text('1\n')
    git('add', '.')
    git('commit', '-qm', 'one')
    (tmp_path / 'a.py').write_text('2\n')
    git('commit', '-qam', 'two')
    amap = _map(tmp_path, '''{ track: [ "*.py" ]  areas: {
        a: { files: [ "a.py" ] }   b: { files: [ "b.py" ] }   s: { cross: true }
    } }''')
    hits = ra.areas_since(amap, 'HEAD~1', root=tmp_path)
    assert set(hits) == {'a', 's'} and hits['a'] == ['a.py']


def test_shipped_map_loads_and_every_area_is_well_formed():
    amap = ra.load_map()
    assert amap['track']
    for key, spec in amap['areas'].items():
        assert spec.get('title'), key
        assert spec['cross'] or spec['files'], key
        assert spec.get('effort', 'xhigh') in ('high', 'xhigh', 'max'), key
