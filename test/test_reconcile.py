'''Step-4 reconcile: `configsys reconcile` (triage OFFERED/NEW items across active derived profiles)
+ the plugin-sync member-delta report. See docs/profiles-derive-plan.md.'''

import io
from contextlib import redirect_stdout

from configsys.app import (Context, active_closure, active_snapshot, build_parser,
                           print_sync_delta, reconcile_data, reconcile_report)


def _ctx(tmp_path, body):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(body)
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


BODY = ('{ configs: [ mine ]  profiles: { '
        'ai: [ htop  bat  fd ]  '
        'mine: [ "^ai"  htop  ~fd ] } }')


def test_reconcile_data_groups_new_and_declined(tmp_path):
    d = reconcile_data(_ctx(tmp_path, BODY))
    assert d['groups'] == [{'profile': 'mine', 'relation': 'base', 'new': ['bat']}]   # fd declined
    assert d['declined'] == [{'profile': 'mine', 'items': ['fd']}]


def test_reconcile_data_only_active_closure(tmp_path):
    # a derived profile that is NOT active (nor +included by an active one) is not triaged
    body = ('{ configs: [ live ]  profiles: { '
            'ai: [ htop  bat ]  live: [ htop ]  idle: [ "^ai" ] } }')
    d = reconcile_data(_ctx(tmp_path, body))
    assert d['groups'] == []                                # idle isn't active -> not reconciled


def test_reconcile_data_follows_includes(tmp_path):
    # an active profile that +includes a derived subprofile surfaces the sub's NEW items
    body = ('{ configs: [ top ]  profiles: { '
            'ai: [ htop  bat ]  sub: [ "^ai"  htop ]  top: [ +sub ] } }')
    d = reconcile_data(_ctx(tmp_path, body))
    assert d['groups'] == [{'profile': 'sub', 'relation': 'base', 'new': ['bat']}]


def test_reconcile_report_text(tmp_path):
    txt = '\n'.join(reconcile_report(_ctx(tmp_path, BODY)))
    assert '1 offered (NEW) item(s)' in txt and '? bat' in txt
    assert 'auto-declined: 1' in txt and '~ mine: fd' in txt
    assert 'configsys profile add' in txt and 'configsys profile decline' in txt


def test_reconcile_report_empty(tmp_path):
    txt = '\n'.join(reconcile_report(_ctx(tmp_path, '{ configs: [ x ]  profiles: { x: [ htop ] } }')))
    assert 'Nothing to reconcile' in txt


def test_active_closure_transitive(tmp_path):
    ctx = _ctx(tmp_path, '{ configs: [ a ]  profiles: { a: [ +b ]  b: [ +c ]  c: [ htop ]  z: [ bat ] } }')
    clos = active_closure(ctx.config)
    assert {'a', 'b', 'c'} <= clos and 'z' not in clos


# -- sync-delta report (before/after an active-set change) -----------------

def test_active_snapshot_and_sync_delta(tmp_path):
    # simulate a "sync" that grows a TRACKED profile's members: snapshot, mutate config, report.
    from configsys import plugins
    ctx = _ctx(tmp_path, '{ configs: [ dev ]  profiles: { dev: [ htop ] } }')
    before = active_snapshot(ctx.config)
    assert 'htop' in before[0]
    profs = plugins.read_profiles(str(ctx.paths.user_config_file))
    profs['dev'] = ['htop', 'bat']                          # "upstream" grew the tracked profile
    plugins.set_profiles(str(ctx.paths.user_config_file), profs)
    ctx.invalidate()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_sync_delta(before, ctx.config)
    out = buf.getvalue()
    assert 'active set changed' in out and '+ bat' in out


def test_sync_delta_reports_new_offerings_for_pins(tmp_path):
    # a PINNED profile whose menu grows shows an offered-count gain, not a member delta
    from configsys import plugins
    ctx = _ctx(tmp_path, '{ configs: [ dev ]  profiles: { base: [ htop  bat ]  dev: [ "^base"  htop ] } }')
    before = active_snapshot(ctx.config)                    # bat already offered (1)
    profs = plugins.read_profiles(str(ctx.paths.user_config_file))
    profs['base'] = ['htop', 'bat', 'fd']                   # base (the menu) grew
    plugins.set_profiles(str(ctx.paths.user_config_file), profs)
    ctx.invalidate()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_sync_delta(before, ctx.config)
    out = buf.getvalue()
    assert 'new offering(s) in pinned profiles' in out
    assert 'active set changed' not in out                  # dev's members (picks) didn't move
