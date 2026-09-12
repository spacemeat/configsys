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


def test_requested_includes_picks(tmp_path):
    # phase B: the current machine's picks feed requested() (the install set), additively with configs
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text('{ configs: [] }')          # no active profiles -> picks-only
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    assert 'btop' not in ctx.config.requested()
    actions.set_included(ctx, 'btop', [ctx.config.current_machine()], True)
    assert ctx.config.requested().get('btop') == ['picks']


def test_rename_machine_carries_picks(tmp_path):
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(
        '{\n  machine: ts-desktop\n  machines: { ts-desktop: {} }\n'
        '  picks: { ts-desktop: [ btop  fd ] }\n}\n')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    ok, new = actions.rename_machine(ctx, 'ts-desktop', 'ts-laptop')
    assert ok and new == 'ts-laptop'
    assert 'ts-laptop' in ctx.config.machines() and 'ts-desktop' not in ctx.config.machines()
    assert ctx.config.included('ts-laptop') == {'btop', 'fd'}          # picks carried over
    assert ctx.config.current_machine() == 'ts-laptop'                 # selection re-pointed
    assert actions.rename_machine(ctx, 'ts-laptop', 'ts-laptop')[0] is False   # same name -> no-op


def test_requested_signature_tracks_picks_and_machine(tmp_path):
    # the TUI rebuilds Components when frozenset(requested()) changes — verify it moves on a pick edit
    # AND on a current-machine switch (the two triggers the user asked to honor).
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(
        '{\n  configs: []\n  machine: alpha\n  machines: { alpha: {}  beta: {} }\n'
        '  picks: { alpha: [ btop ]  beta: [ fzf ] }\n}\n')

    def ctx():
        return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))

    c = ctx()
    sig = frozenset(c.config.requested())
    assert 'btop' in sig and 'fzf' not in sig                 # alpha's set drives it
    actions.set_included(c, 'fd', ['alpha'], True)            # a local-machine pick change
    assert frozenset(c.config.requested()) != sig            # -> Components must rebuild
    c = ctx()
    actions.set_machine_active(c, 'beta')                     # the local machine ITSELF changes
    c = ctx()
    beta_sig = frozenset(c.config.requested())
    assert 'fzf' in beta_sig and 'btop' not in beta_sig      # -> different install set, rebuild


def test_rename_materializes_synthetic_current(tmp_path):
    # renaming the un-named default 'this-machine' materializes it into machines: and re-points the
    # machine: selection (the sync bug fix) — nothing was in machines: before.
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text('{\n  configs: []\n}\n')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    assert ctx.config.current_machine() == 'this-machine' and ctx.config.machines() == {}
    actions.set_included(ctx, 'btop', ['this-machine'], True)
    ok, new = actions.rename_machine(ctx, 'this-machine', 'desktop')
    assert ok and new == 'desktop'
    assert 'desktop' in ctx.config.machines()                 # materialized
    assert ctx.config.current_machine() == 'desktop'          # selection re-pointed
    assert ctx.config.included('desktop') == {'btop'}         # picks carried


def test_migrate_picks_from_active_profiles(tmp_path):
    import io
    from contextlib import redirect_stdout
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text('{ configs: [ finders ] }')     # a real repo profile
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    n, machine = actions.migrate_picks(ctx)
    assert n >= 3 and machine == 'this-machine'                     # finders' members seeded
    assert {'fd', 'fzf', 'ripgrep'} <= ctx.config.included()
    assert actions.migrate_picks(ctx)[0] == 0                       # idempotent


def test_set_included_fans_out_across_machines(tmp_path):
    ctx = _ctx(tmp_path)
    n, label = actions.set_included(ctx, 'btop', ['ts-desktop', 'ts-laptop'], True)
    assert n == 2 and label == 'picks'
    assert ctx.config.included('ts-desktop') == {'btop'} and ctx.config.included('ts-laptop') == {'btop'}
    # a re-add is a no-op on the machine that already has it; drop removes only where present
    n2, _ = actions.set_included(ctx, 'btop', ['ts-desktop'], False)
    assert n2 == 1
    assert ctx.config.included('ts-desktop') == set() and ctx.config.included('ts-laptop') == {'btop'}
