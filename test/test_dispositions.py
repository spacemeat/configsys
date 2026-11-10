'''Phase 2 of the disposition model (docs/done/profiles-disposition-plan.md): the `dispositions:` side-store
(seen/interesting), the NEW = undispositioned rule, and the `configsys disp` CLI. include/exclude live
in the profiles themselves; NEW is the unstored default.'''

import io
from contextlib import redirect_stdout

from configsys import actions, layers, plugins
from configsys.config import Config


def _cfg(*specs):
    '''(role, text) low->high, with a universe provider so profile membership resolves.'''
    ll = [layers.Layer(f'{r}.hu', r, layers.materialize_string(t)) for r, t in specs]
    c = Config(ll)
    c._universe_provider = lambda: {'htop', 'bat', 'fd', 'fzf', 'ripgrep', 'eza'}
    return c


# -- writer round-trip ----------------------------------------------------

def test_dispositions_writer_roundtrip_and_clear(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ // keep\n  configs: [ dev ] }\n', encoding='utf-8')
    plugins.set_dispositions(str(f), {'fd': 'interesting', 'ripgrep': 'seen'})
    assert plugins.read_dispositions(str(f)) == {'fd': 'interesting', 'ripgrep': 'seen'}
    assert '// keep' in f.read_text() and 'configs: [ dev ]' in f.read_text()   # comment + sibling survive
    plugins.set_dispositions(str(f), {})                                         # empty -> node removed
    assert plugins.read_dispositions(str(f)) == {}


# -- Config accessors + NEW ----------------------------------------------

def test_disposition_merge_and_is_new():
    c = _cfg(('repo', '{ profiles: { finders: [ fd  fzf  ripgrep ] } }'),
             ('user', '{ profiles: { mine: [ htop  bat ] }  dispositions: { ripgrep: seen  eza: interesting } }'))
    assert c.disposition('ripgrep') == 'seen' and c.disposition('eza') == 'interesting'
    assert c.disposition('fd') is None
    # NEW = not marked seen/interesting and picked on NO machine: a profile — even one you
    # authored — is only a browse lens, so its members stay NEW until you look at them
    assert c.is_new('fd') and c.is_new('fzf')                 # in a system profile only -> NEW
    assert c.is_new('htop') and c.is_new('bat')               # in your own profile `mine` -> still NEW
    assert not c.is_new('ripgrep') and not c.is_new('eza')    # dispositioned


def test_picked_on_any_machine_is_not_new():
    # a pick in ANY column of the matrix (merged repo < primary < user) takes a component out of
    # NEW — not only this box's
    c = _cfg(('primary', '{ picks: { laptop: [ fd ]  desk: [ fzf ] } }'),
             ('user', '{ machine: desk  picks: { desk: [ bat ]  this-machine: [ htop ] } }'))
    assert c.picked_components() == {'fd', 'bat', 'htop'}     # the user's desk list replaced fzf's
    assert not c.is_new('fd') and not c.is_new('bat') and not c.is_new('htop')
    assert c.is_new('fzf') and c.is_new('ripgrep')
    assert c.picked_on('fd') == ['laptop'] and c.picked_on('fzf') == []


def test_dispositions_layered_local_overrides_lower():
    # a plugin/primary may ship a default disposition; the local top config overrides per key
    c = _cfg(('primary', '{ profiles: {}  dispositions: { fd: seen } }'),
             ('user', '{ dispositions: { fd: interesting } }'))
    assert c.disposition('fd') == 'interesting'               # local wins key-by-key


def test_uninstall_is_not_new():
    c = _cfg(('repo', '{ profiles: { finders: [ fd ] } }'),
             ('user', '{ uninstall: [ fd ] }'))
    assert not c.is_new('fd')                                 # staged for uninstall -> dispositioned


# -- actions + CLI --------------------------------------------------------

def _ctx(tmp_path, body='{ picks: { laptop: [ htop ] }  profiles: { mine: [ htop  bat ] } }'):
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(body)
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def test_set_disposition_roundtrip(tmp_path):
    ctx = _ctx(tmp_path)
    changed, label = actions.set_disposition(ctx, 'fd', 'interesting')
    assert changed and label == 'top config'
    assert ctx.config.disposition('fd') == 'interesting'
    assert actions.set_disposition(ctx, 'fd', 'interesting')[0] is False    # no-op
    changed, _ = actions.set_disposition(ctx, 'fd', 'new')                  # clear
    assert changed and ctx.config.disposition('fd') is None
    assert plugins.read_dispositions(str(ctx.paths.user_config_file)) == {}  # node cleaned up


def test_mark_all_seen_lands_where_set_disposition_does(tmp_path, monkeypatch):
    # dispositions moved into the primary (`config move`): a mass-acknowledge must add to that block,
    # like set_disposition — not start a second one in the top config that splits the triage
    ctx = _ctx(tmp_path, '{ }')
    pfile = tmp_path / 'mine.hu'
    pfile.write_text('{ dispositions: { fd: interesting } }\n')
    monkeypatch.setattr(actions, '_primary_data_file', lambda c: (str(pfile), 'primary mine'))
    assert actions.set_disposition(ctx, 'bat', 'seen') == (True, 'primary mine')
    assert actions.mark_all_seen(ctx, ['fd', 'htop']) == 1
    assert plugins.read_dispositions(str(pfile)) == {'fd': 'interesting', 'bat': 'seen', 'htop': 'seen'}
    assert plugins.read_dispositions(str(ctx.paths.user_config_file)) == {}


def test_disp_cli_get_set_list(tmp_path):
    from configsys.app import build_parser, cmd_disp
    ctx = _ctx(tmp_path)

    def run(argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_disp(ctx, build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop'] + argv))
        return buf.getvalue()

    assert 'htop: picked on laptop' in run(['disp', 'get', 'htop'])   # tracked by a machine
    assert 'bat: new' in run(['disp', 'get', 'bat'])           # only in a profile -> still new
    assert 'fd: new' in run(['disp', 'get', 'fd'])
    run(['disp', 'set', 'fd', 'interesting'])
    assert 'fd: marked interesting' in run(['disp', 'get', 'fd'])
    run(['disp', 'set', 'fd', 'seen'])
    assert 'fd: marked seen' in run(['disp', 'get', 'fd'])
    run(['disp', 'set', 'fd', 'interesting'])
    out = run(['disp', 'list'])
    assert 'interesting (1): fd' in out and 'NEW (undispositioned):' in out
    newout = run(['disp', 'list', '--new'])
    assert '  ? fd\n' not in newout and '  ? fzf\n' in newout   # fd dispositioned; fzf still NEW
