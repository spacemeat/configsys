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


def test_set_included_fans_out_across_machines(tmp_path):
    ctx = _ctx(tmp_path)
    n, label = actions.set_included(ctx, 'btop', ['ts-desktop', 'ts-laptop'], True)
    assert n == 2 and label == 'top config'          # no primary blessed -> the portable target IS local
    assert ctx.config.included('ts-desktop') == {'btop'} and ctx.config.included('ts-laptop') == {'btop'}
    # a re-add is a no-op on the machine that already has it; drop removes only where present
    n2, _ = actions.set_included(ctx, 'btop', ['ts-desktop'], False)
    assert n2 == 1
    assert ctx.config.included('ts-desktop') == set() and ctx.config.included('ts-laptop') == {'btop'}


# -- portability: picks default to the primary plugin (dispositions stay local) --------------------

def _local_file(tmp_path):
    return tmp_path / '.config' / 'configsys' / 'configsys.hu'


def test_set_included_targets_primary_by_default(tmp_path, monkeypatch):
    # with a primary blessed, a fresh machine's picks land in the PRIMARY (portable), not local.
    ctx = _ctx(tmp_path)
    primary = tmp_path / 'primary.hu'
    primary.write_text('{ }\n')
    monkeypatch.setattr(actions, '_primary_data_file', lambda c: (str(primary), 'my-primary'))
    n, label = actions.set_included(ctx, 'btop', ['boxA'], True)
    assert n == 1 and label == 'my-primary'
    assert plugins.read_picks(str(primary)) == {'boxA': ['btop']}
    assert 'picks' not in _local_file(tmp_path).read_text()       # local untouched


def test_set_included_respects_a_local_override(tmp_path, monkeypatch):
    # a machine the LOCAL config already overrides keeps its edits local (a local list shadows primary
    # per machine), so the write stays effective — the layer stack is preserved.
    ctx = _ctx(tmp_path)
    plugins.set_picks(str(_local_file(tmp_path)), {'boxA': ['htop']})
    primary = tmp_path / 'primary.hu'
    primary.write_text('{ }\n')
    monkeypatch.setattr(actions, '_primary_data_file', lambda c: (str(primary), 'my-primary'))
    ctx.invalidate()
    n, label = actions.set_included(ctx, 'btop', ['boxA'], True)
    assert n == 1 and label == 'top config'                       # stayed local (the override lives there)
    assert plugins.read_picks(str(_local_file(tmp_path))) == {'boxA': ['htop', 'btop']}
    assert plugins.read_picks(str(primary)) == {}                 # primary untouched


def test_move_picks_to_primary(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    plugins.set_picks(str(_local_file(tmp_path)), {'a': ['btop', 'fd'], 'b': ['fish']})
    primary = tmp_path / 'primary.hu'
    primary.write_text('{ }\n')
    monkeypatch.setattr(actions, '_primary_data_file', lambda c: (str(primary), 'my-primary'))
    ctx.invalidate()
    n, label = actions.move_picks_to_primary(ctx)
    assert n == 3 and label == 'my-primary'
    assert plugins.read_picks(str(primary)) == {'a': ['btop', 'fd'], 'b': ['fish']}
    assert plugins.read_picks(str(_local_file(tmp_path))) == {}   # local shadow cleared


def test_move_picks_to_primary_noop_without_primary(tmp_path):
    # no primary blessed -> edit_target falls back to local, so there's nowhere portable to move to
    ctx = _ctx(tmp_path)
    plugins.set_picks(str(_local_file(tmp_path)), {'a': ['btop']})
    ctx.invalidate()
    assert actions.move_picks_to_primary(ctx) == (0, 'no primary')
    assert plugins.read_picks(str(_local_file(tmp_path))) == {'a': ['btop']}   # left in place


def test_clear_machine_clears_both_layers(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    primary = tmp_path / 'primary.hu'
    primary.write_text('{ }\n')
    plugins.set_picks(str(_local_file(tmp_path)), {'m': ['a']})
    plugins.set_picks(str(primary), {'m': ['b'], 'other': ['c']})
    monkeypatch.setattr(actions, '_primary_data_file', lambda c: (str(primary), 'my-primary'))
    ctx.invalidate()
    changed, _ = actions.set_included_clear_machine(ctx, 'm')
    assert changed
    assert 'm' not in plugins.read_picks(str(_local_file(tmp_path)))
    assert plugins.read_picks(str(primary)) == {'other': ['c']}   # m dropped, sibling kept
