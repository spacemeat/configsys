'''Phase A of the v3 matrix model (docs/profiles-matrix-plan.md): the per-machine `picks:` store —
each machine's Included component set. Writer round-trip, Config accessors, and the plural fan-out
`set_included` action.'''

from configsys import actions, layers, plugins
from configsys.config import Config


def _cfg(*specs):
    ll = [layers.Layer(f'{r}.hu', r, layers.materialize_string(t)) for r, t in specs]
    return Config(ll)


def test_picks_writer_roundtrip_and_clear(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ // keep\n  configs: [ dev ] }\n', encoding='utf-8')
    plugins.set_picks(str(f), {'ts-desktop': ['btop', 'neovim'], 'ts-laptop': ['fish']})
    assert plugins.read_picks(str(f)) == {'ts-desktop': ['btop', 'neovim'], 'ts-laptop': ['fish']}
    assert '// keep' in f.read_text() and 'configs: [ dev ]' in f.read_text()   # comment + sibling survive
    plugins.set_picks(str(f), {'ts-desktop': []})                              # empty machine dropped
    assert plugins.read_picks(str(f)) == {}                                    # -> whole node removed
    assert 'picks' not in f.read_text()


def test_config_picks_included_and_current_machine():
    c = _cfg(('user', '{ machine: ts-desktop  picks: { ts-desktop: [ btop  fd ]  ts-laptop: [ fish ] } }'))
    assert c.current_machine() == 'ts-desktop'                 # from the `machine:` setting
    assert c.included() == {'btop', 'fd'}                      # current machine's set
    assert c.included('ts-laptop') == {'fish'}
    assert c.picks() == {'ts-desktop': ['btop', 'fd'], 'ts-laptop': ['fish']}


def test_current_machine_defaults_without_selection():
    c = _cfg(('user', '{ picks: { this-machine: [ htop ] } }'))
    assert c.current_machine() == 'this-machine'               # no `machine:` -> the default key
    assert c.included() == {'htop'}


def test_picks_layer_replace_per_machine():
    # a later machine-role layer replaces a machine's list (local top config wins)
    c = _cfg(('primary', '{ picks: { m1: [ a  b ] } }'),
             ('user', '{ picks: { m1: [ a  c ] } }'))
    assert c.included('m1') == {'a', 'c'}


def _ctx(tmp_path):
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text('{ machine: [ ts-desktop ] }')
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def test_set_included_fans_out_across_machines(tmp_path):
    ctx = _ctx(tmp_path)
    n, label = actions.set_included(ctx, 'btop', ['ts-desktop', 'ts-laptop'], True)
    assert n == 2 and label == 'picks'
    assert ctx.config.included('ts-desktop') == {'btop'} and ctx.config.included('ts-laptop') == {'btop'}
    # a re-add is a no-op on the machine that already has it; drop removes only where present
    n2, _ = actions.set_included(ctx, 'btop', ['ts-desktop'], False)
    assert n2 == 1
    assert ctx.config.included('ts-desktop') == set() and ctx.config.included('ts-laptop') == {'btop'}
