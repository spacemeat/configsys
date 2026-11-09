'''The matrix CLI's edges (review-2026-11-2 actions-20 / -21 / -28): `machine rm` of this box,
`picks add profile:<name>`, and `orphans --ignore/--unignore` through the shared actions.'''

import pytest

from configsys import plugins
from configsys.app import main


def _cs(home, *argv):
    return main(['--home', str(home), '--os', 'pop', '-q', *argv])


def _cfg_file(home):
    return home / '.config' / 'configsys' / 'configsys.hu'


# -- actions-20: `machine rm` of the machine this box is set to ------------------------------------

def test_machine_rm_refuses_this_box_and_keeps_its_picks(tmp_path, capsys):
    assert _cs(tmp_path, 'machine', 'add', 'laptop') == 0
    assert _cs(tmp_path, 'machine', 'use', 'laptop') == 0
    assert _cs(tmp_path, 'picks', 'add', 'btop') == 0
    capsys.readouterr()
    assert _cs(tmp_path, 'machine', 'rm', 'laptop') == 1
    assert 'is this box' in capsys.readouterr().err
    assert plugins.read_picks(str(_cfg_file(tmp_path))) == {'laptop': ['btop']}
    assert plugins.read_list_section(str(_cfg_file(tmp_path)), 'machine') == ['laptop']


def test_machine_rm_force_clears_the_selection(tmp_path, capsys):
    for argv in (['machine', 'add', 'laptop'], ['machine', 'use', 'laptop'], ['picks', 'add', 'btop']):
        assert _cs(tmp_path, *argv) == 0
    capsys.readouterr()
    assert _cs(tmp_path, 'machine', 'rm', 'laptop', '--force') == 0
    assert 'removed machine laptop (1 pick)' in capsys.readouterr().out
    assert plugins.read_picks(str(_cfg_file(tmp_path))) == {}
    assert plugins.read_list_section(str(_cfg_file(tmp_path)), 'machine') == []


def test_machine_rm_of_another_machine_names_it(tmp_path, capsys):
    for argv in (['machine', 'add', 'desk'], ['machine', 'add', 'laptop'], ['machine', 'use', 'desk']):
        assert _cs(tmp_path, *argv) == 0
    capsys.readouterr()
    assert _cs(tmp_path, 'machine', 'rm', 'laptop') == 0
    assert 'removed machine laptop (0 picks)' in capsys.readouterr().out
    assert list(plugins.read_picks(str(_cfg_file(tmp_path)))) == ['desk']


# -- actions-21: `picks add profile:<name>` --------------------------------------------------------

def test_picks_add_profile_picks_each_member(tmp_path, capsys):
    assert _cs(tmp_path, 'picks', 'add', 'profile:compression-tools') == 0
    picks = plugins.read_picks(str(_cfg_file(tmp_path)))['this-machine']
    assert {'zstd', 'lz4', 'p7zip', 'zip', 'unzip'} <= set(picks)
    assert not any(p.startswith('profile:') for p in picks)
    assert _cs(tmp_path, 'picks', 'rm', 'profile:compression-tools') == 0
    assert plugins.read_picks(str(_cfg_file(tmp_path)))['this-machine'] == []


def test_picks_add_unknown_profile_writes_nothing(tmp_path, capsys):
    assert _cs(tmp_path, 'picks', 'add', 'profile:nope') == 1
    assert not _cfg_file(tmp_path).exists() or plugins.read_picks(str(_cfg_file(tmp_path))) == {}


def test_set_included_refuses_a_profile_token(tmp_path):
    from configsys import actions
    with pytest.raises(ValueError):
        actions.set_included(object(), 'profile:x', ['m'], True)


# -- actions-28: `orphans --ignore` / `--unignore` through the shared actions ----------------------

def _ignored(home):
    return plugins.read_list_section(str(_cfg_file(home)), 'orphans-ignore')


def test_orphans_ignore_then_unignore(tmp_path, capsys):
    assert _cs(tmp_path, 'orphans', '--ignore', 'a', 'b') == 0
    assert _ignored(tmp_path) == ['a', 'b']
    assert _cs(tmp_path, 'orphans', '--ignore', 'b') == 0           # already there: no change
    assert 'already ignored: b' in capsys.readouterr().out
    assert _cs(tmp_path, 'orphans', '--unignore', 'a') == 0
    assert _ignored(tmp_path) == ['b']
    assert _cs(tmp_path, 'orphans', '--unignore', 'zz') == 1         # not listed: said, nonzero
    assert 'not literally ignored' in capsys.readouterr().err


def test_orphans_unignore_under_pretend_writes_nothing(tmp_path, capsys):
    assert _cs(tmp_path, 'orphans', '--ignore', 'a') == 0
    before = _cfg_file(tmp_path).read_text()
    capsys.readouterr()
    assert _cs(tmp_path, '--pretend', 'orphans', '--unignore', 'a') == 0
    assert '[pretend] would un-ignore a' in capsys.readouterr().out
    assert _cfg_file(tmp_path).read_text() == before


def test_ignore_orphan_takes_a_list_in_one_write(tmp_path, monkeypatch):
    from configsys import actions
    from configsys.app import Context, build_parser
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', '-q', 'inspect']))
    ctx.ensure_user_config()
    writes = []
    real = actions.set_config_setting
    monkeypatch.setattr(actions, 'set_config_setting', lambda c, k, v, **kw: writes.append(v) or real(c, k, v, **kw))
    assert actions.ignore_orphan(ctx, ['a', 'b', 'a'])[0] == 2
    assert writes == [['a', 'b']]
    assert actions.ignore_orphan(ctx, 'a') == (0, 'already ignored')
