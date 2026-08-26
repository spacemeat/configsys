'''The reserved `!uninstall` staged-removal queue (phase 4): `x` on the TUI stages a component here
(machine-local), TUI::Components executes or clears it. `!`-prefixed profiles are reserved — never
active, not counted as real membership, and rejected from user profile creation.'''

from configsys import layers, actions
from configsys.config import Config
from configsys.app import Context, build_parser


def _cfg(text):
    return Config([layers.Layer('config.hu', 'repo', layers.materialize_string(text))])


def _ctx(tmp_path, body='{ configs: [ dev ]  profiles: { dev: [ htop  bat ] } }'):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(body)
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def _reload(tmp_path):
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def test_stage_and_clear_roundtrip(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.config.uninstall_queue() == set()
    actions.stage_uninstall(ctx, 'bat')
    actions.stage_uninstall(_reload(tmp_path), 'ncdu')
    assert _reload(tmp_path).config.uninstall_queue() == {'bat', 'ncdu'}
    # unstage one
    actions.stage_uninstall(_reload(tmp_path), 'bat', on=False)
    assert _reload(tmp_path).config.uninstall_queue() == {'ncdu'}
    # clear the rest
    assert actions.clear_uninstall(_reload(tmp_path)) == 1
    assert _reload(tmp_path).config.uninstall_queue() == set()


def test_add_profile_rejects_reserved_bang_name(tmp_path):
    ctx = _ctx(tmp_path)
    changed, msg = actions.add_profile(ctx, '!uninstall')
    assert changed is False and 'reserved' in msg


def test_reserved_profile_not_counted_as_membership():
    # a component only in !uninstall is NOT "in a profile" (so the orphan scan reads it forgotten)
    cfg = _cfg('{ configs: [ dev ]  profiles: { dev: [ htop ]  "!uninstall": [ ncdu ] } }')
    direct, indirect = cfg.profiles_containing('ncdu')
    assert direct == [] and indirect == []
    assert cfg.uninstall_queue() == {'ncdu'}


def test_check_errors_on_active_reserved_profile(tmp_path, capsys):
    from configsys.app import cmd_check
    ctx = _ctx(tmp_path, '{ configs: [ dev, "!uninstall" ]  profiles: { dev: [ htop ]  "!uninstall": [ bat ] } }')
    rc = cmd_check(ctx, None)
    out = capsys.readouterr().out
    assert rc == 1 and 'reserved profile' in out and 'cannot be active' in out


def test_check_warns_on_staged_but_still_wanted(tmp_path, capsys):
    from configsys.app import cmd_check
    ctx = _ctx(tmp_path, '{ configs: [ dev ]  profiles: { dev: [ htop  bat ]  "!uninstall": [ bat ] } }')
    cmd_check(ctx, None)
    out = capsys.readouterr().out
    assert "'bat' is staged for uninstall" in out and "active profile 'dev'" in out
