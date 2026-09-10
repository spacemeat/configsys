'''Phase 2 of the disposition model (docs/profiles-disposition-plan.md): the `dispositions:` side-store
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
    # NEW = undispositioned: not in a user profile, not seen/interesting, not uninstall
    assert c.is_new('fd') and c.is_new('fzf')                 # in a system profile only -> NEW
    assert not c.is_new('htop') and not c.is_new('bat')       # in the user profile `mine` -> included
    assert not c.is_new('ripgrep') and not c.is_new('eza')    # dispositioned
    assert c.user_layer_components() == {'htop', 'bat'}       # only your profile's members count


def test_dispositions_layered_local_overrides_lower():
    # a plugin/primary may ship a default disposition; the local top config overrides per key
    c = _cfg(('primary', '{ profiles: {}  dispositions: { fd: seen } }'),
             ('user', '{ dispositions: { fd: interesting } }'))
    assert c.disposition('fd') == 'interesting'               # local wins key-by-key


def test_uninstall_is_not_new():
    c = _cfg(('repo', '{ profiles: { finders: [ fd ] } }'),
             ('user', '{ profiles: { "!uninstall": [ fd ] } }'))
    assert not c.is_new('fd')                                 # staged for uninstall -> dispositioned


# -- actions + CLI --------------------------------------------------------

def _ctx(tmp_path, body='{ configs: [ mine ]  profiles: { mine: [ htop  bat ] } }'):
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


def test_disp_cli_get_set_list(tmp_path):
    from configsys.app import build_parser, cmd_disp
    ctx = _ctx(tmp_path)

    def run(argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_disp(ctx, build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop'] + argv))
        return buf.getvalue()

    assert 'include' in run(['disp', 'get', 'htop'])           # member of `mine`
    assert 'fd: new' in run(['disp', 'get', 'fd'])
    run(['disp', 'set', 'fd', 'interesting'])
    assert 'fd: interesting' in run(['disp', 'get', 'fd'])
    out = run(['disp', 'list'])
    assert 'interesting (1): fd' in out and 'NEW (undispositioned):' in out
    newout = run(['disp', 'list', '--new'])
    assert '  ? fd\n' not in newout and '  ? fzf\n' in newout   # fd dispositioned; fzf still NEW
