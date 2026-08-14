'''The two-pane Plugins TUI's data layer: `declared_tree` (transitive hierarchy for the tree
view), `_parse_unified_diff`/`diff_against_ref` (the review-before-you-trust diff), and the bulk
`plugin_trust_all` action. Rendering itself is exercised by the TUI smoke test.'''

import shutil
import subprocess

import pytest

from configsys import plugins
from configsys.runner import Runner


def _plugin(plugins_dir, name, manifest, files=None):
    d = plugins_dir / name
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(manifest)
    for fname, text in (files or {}).items():
        (d / fname).write_text(text)
    return d


# -- declared_tree: transitive hierarchy + prefix flags -------------------

def test_declared_tree_nests_transitive_under_their_parent(tmp_path):
    pdir = tmp_path / 'plugins'
    # cfg (primary) declares two children; one child declares a grandchild
    _plugin(pdir, 'cfg', '{ name: cfg  requires-abi: 1  plugins: ['
                         ' { source: "github:x/blender" } { source: "github:x/kicad" } ] }')
    _plugin(pdir, 'blender', '{ name: blender  requires-abi: 1  plugins: ['
                             ' { source: "github:x/opencv" } ] }')
    _plugin(pdir, 'kicad', '{ name: kicad  requires-abi: 1 }')
    _plugin(pdir, 'opencv', '{ name: opencv  requires-abi: 1 }')
    top = tmp_path / 'configsys.hu'
    top.write_text('{ plugins: [ { source: "github:me/cfg"  primary: true } ] }')

    tree = plugins.declared_tree(str(top), pdir)
    got = [(plugins.dir_name(t['decl']['source']), t['depth']) for t in tree]
    # DFS pre-order: root, then its children, with the grandchild nested under blender
    assert got == [('cfg', 0), ('blender', 1), ('opencv', 2), ('kicad', 1)]
    # last-sibling flags: cfg is the only/last root; kicad is blender's last sibling; opencv last child
    flags = {plugins.dir_name(t['decl']['source']): t['last'] for t in tree}
    assert flags['cfg'] == [True]
    assert flags['blender'][-1] is False and flags['kicad'][-1] is True
    assert flags['opencv'] == [True, False, True]


def test_declared_tree_dedups_a_shared_child_to_one_row(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'cfg', '{ name: cfg  requires-abi: 1  plugins: ['
                         ' { source: "github:x/shared" } { source: "github:x/other" } ] }')
    _plugin(pdir, 'other', '{ name: other  requires-abi: 1  plugins: ['
                           ' { source: "github:x/shared" } ] }')      # also points at shared
    _plugin(pdir, 'shared', '{ name: shared  requires-abi: 1 }')
    top = tmp_path / 'configsys.hu'
    top.write_text('{ plugins: [ { source: "github:me/cfg"  primary: true } ] }')

    names = [plugins.dir_name(t['decl']['source']) for t in plugins.declared_tree(str(top), pdir)]
    assert names.count('shared') == 1                      # listed once, at first encounter
    assert set(names) == {'cfg', 'shared', 'other'}


# -- unified-diff parsing --------------------------------------------------

def test_parse_unified_diff_classifies_lines():
    text = ('diff --git a/routes.hu b/routes.hu\n'
            'index 111..222 100644\n'
            '--- a/routes.hu\n'
            '+++ b/routes.hu\n'
            '@@ -1,2 +1,2 @@\n'
            ' unchanged\n'
            '-old line\n'
            '+new line\n'
            'diff --git a/new.txt b/new.txt\n'
            'new file mode 100644\n'
            '@@ -0,0 +1 @@\n'
            '+hello\n')
    files = plugins._parse_unified_diff(text)
    assert [f['path'] for f in files] == ['routes.hu', 'new.txt']
    kinds = [k for k, _t in files[0]['lines']]
    assert kinds == ['meta', 'meta', 'meta', 'hunk', 'ctx', 'del', 'add']
    assert files[1]['lines'][-1] == ('add', '+hello')


def test_parse_unified_diff_empty_is_no_files():
    assert plugins._parse_unified_diff('') == []


# -- diff_against_ref: real git fetch + diff -------------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_diff_against_ref_shows_what_updating_would_change(tmp_path):
    def _git(cwd, *a):
        subprocess.run(['git', *a], cwd=cwd, check=True)

    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: sp  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('one\n')
    _git(src, 'init', '-q'); _git(src, 'config', 'user.email', 't@t')
    _git(src, 'config', 'user.name', 't'); _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'A')
    _git(src, 'tag', 'v1')

    pdir = tmp_path / 'plugins'
    decl = {'source': str(src), 'ref': 'v1'}
    plugins.sync(Runner(pretend=False), pdir, [decl])

    # up to date against v1 -> no changes
    files, err = plugins.diff_against_ref(Runner(pretend=False), pdir, decl, 'v1')
    assert err is None and files == []

    # advance the remote and diff v1 -> v2
    (src / 'routes.hu').write_text('two\n')
    _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'B'); _git(src, 'tag', 'v2')
    files, err = plugins.diff_against_ref(Runner(pretend=False), pdir, decl, 'v2')
    assert err is None and len(files) == 1 and files[0]['path'] == 'routes.hu'
    kinds = [k for k, _t in files[0]['lines']]
    assert 'del' in kinds and 'add' in kinds          # -one +two


def test_diff_against_ref_unsynced_reports_gracefully(tmp_path):
    files, err = plugins.diff_against_ref(Runner(pretend=False), tmp_path / 'plugins',
                                          {'source': 'github:x/none'}, 'v1')
    assert files == [] and 'not synced' in err
