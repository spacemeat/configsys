'''review-2026-11-2 C2: a Profiles triage edit (picks, dispositions, the uninstall queue) drops
only the Config — the Resolver, and every cache keyed on it, survives — while a routing edit (a
pin) still rebuilds it.'''

from configsys import actions
from configsys.app import Context, build_parser


def _ctx(tmp_path):
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def test_triage_edits_keep_the_resolver(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.ensure_user_config()
    routes = ctx.routes
    actions.set_disposition(ctx, 'btop', 'seen')
    actions.set_included(ctx, 'btop', [ctx.config.current_machine()], True)
    actions.stage_uninstall(ctx, 'htop')
    assert ctx.routes is routes                              # not rebuilt (~0.5 s each)
    assert 'btop' in ctx.config.requested()                  # but the config IS re-read


def test_a_pin_still_rebuilds_the_resolver(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.ensure_user_config()
    routes = ctx.routes
    ctx.invalidate()
    assert ctx.routes is not routes
