'''Regression tests (follow-ups): dotfiles staged/activate/discard on the paths-based shellguard API,
glue add's 90-<name> link, user glue in `dotfiles status`, `configsys keys` rebind-wins, and the
actions-level --pretend refusal the TUI relies on.'''

import pytest

from configsys import actions
from configsys.app import Context, build_parser, main


@pytest.fixture
def zsh_only(monkeypatch):
    monkeypatch.setenv('CONFIGSYS_GLUE_SHELLS', 'zsh')
    monkeypatch.setenv('EDITOR', 'true')            # glue add opens $EDITOR — make it a no-op


def _cs(home, *argv):
    return main(['--home', str(home), '--os', 'pop', *argv])


def _stage(home, comp, body='export FOO=1\n'):
    d = home / '.config' / 'configsys' / 'staged-glue' / 'zsh'
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{comp}.zsh').write_text(body)
    return d / f'{comp}.zsh'


# -- 1: staged / activate / discard / glue add / status ---------------------------------------------

def test_dotfiles_staged_lists_from_the_state_dir(tmp_path, capsys, zsh_only):
    _stage(tmp_path, 'foo')
    assert _cs(tmp_path, 'dotfiles', 'staged') == 0
    out = capsys.readouterr().out
    assert 'foo [zsh]' in out and 'staged-glue' in out and 'export FOO=1' in out
    # the canonical spelling of the verbs (`dotfiles activate|discard` stays an alias)
    assert '`configsys glue activate <component>`' in out
    assert '`configsys glue discard <component>`' in out and 'dotfiles activate' not in out


def test_shell_guard_note_names_the_glue_verbs(tmp_path, monkeypatch):
    from configsys import shellguard
    from configsys.paths import Paths
    paths = Paths({'HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    monkeypatch.setattr(shellguard, 'revert_and_capture', lambda home, snap: {'zsh': 'export X=1\n'})
    note = shellguard.finish(paths, 'foo', {'snap': True})
    assert '`configsys glue staged`' in note and '`configsys glue activate foo`' in note


def test_glue_summary_counts_every_bucket_incl_changed():
    from configsys.cli.dotfiles import _glue_summary
    assert _glue_summary({'active': 2, 'changed': 1, 'available': 3, 'inactive': 1}) == \
        '2 active, 1 changed, 3 available, 1 inactive'


def test_dotfiles_activate_makes_user_glue_and_unstages(tmp_path, capsys, zsh_only):
    staged = _stage(tmp_path, 'foo')
    assert _cs(tmp_path, 'dotfiles', 'activate', 'foo', '--local') == 0
    out = capsys.readouterr().out
    assert 'foo: activated as zsh user glue ->' in out and '90-foo.zsh' in out
    link = tmp_path / '.config' / 'zsh' / 'conf.d' / '90-foo.zsh'
    assert link.is_symlink() and 'export FOO=1' in link.read_text()
    assert not staged.exists()
    assert _cs(tmp_path, 'dotfiles', 'activate', 'foo') == 1          # nothing left to activate
    assert 'nothing staged to activate' in capsys.readouterr().out
    # user glue is visible in `dotfiles status` (no surprises)
    _cs(tmp_path, 'dotfiles', 'status')
    out = capsys.readouterr().out
    assert 'user glue' in out and '90-foo.zsh' in out and 'linked' in out


def test_pretend_activate_and_discard_write_nothing(tmp_path, capsys, zsh_only):
    staged = _stage(tmp_path, 'foo')
    assert _cs(tmp_path, '--pretend', 'dotfiles', 'activate', 'foo') == 0
    assert _cs(tmp_path, '--pretend', 'dotfiles', 'discard', 'foo') == 0
    out = capsys.readouterr().out
    assert '[pretend] would activate foo' in out and '[pretend] would discard 1' in out
    assert staged.exists()
    assert not (tmp_path / '.config' / 'zsh').exists()


def test_dotfiles_discard_drops_the_candidate(tmp_path, capsys, zsh_only):
    staged = _stage(tmp_path, 'bar')
    assert _cs(tmp_path, 'dotfiles', 'discard', 'bar') == 0
    assert not staged.exists()
    assert _cs(tmp_path, 'dotfiles', 'discard', 'bar') == 1
    out = capsys.readouterr().out
    assert 'discarded 1' in out and 'nothing staged' in out


def test_glue_add_prints_the_user_band_link(tmp_path, capsys, zsh_only):
    assert _cs(tmp_path, 'glue', 'add', 'aliases', '--shell', 'zsh', '--local') == 0
    out = capsys.readouterr().out
    assert '90-aliases.zsh' in out


# -- 3: keys rebind-wins ----------------------------------------------------------------------------

def test_keys_shows_rebind_wins(tmp_path, capsys):
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{\n    keys: { screens: { glue: "1" } }\n}\n')
    assert _cs(tmp_path, 'keys') == 0
    out = capsys.readouterr().out
    screens = out.split('[screens]', 1)[1].split('\n  [', 1)[0]
    lines = {ln.split()[0]: ln.split()[1:] for ln in screens.strip().splitlines()}
    assert lines['glue'] == ['1', 'configsys.hu']           # the key, and the layer it came from
    assert 'components' not in lines          # its "1" was taken by the user's rebind


def test_keys_separates_rebinds_from_other_warnings(tmp_path, capsys):
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{\n    keys: { screens: { glue: "1" }  global: { nosuchaction: x } }\n}\n')
    assert _cs(tmp_path, 'keys') == 0
    out = capsys.readouterr().out
    rebinds = out.split('rebinds across layers:', 1)[1].split('\n\n', 1)[0]
    assert "'1'" in rebinds and 'nosuchaction' not in rebinds
    other = out.split('other key warnings', 1)[1]
    assert 'nosuchaction' in other


def test_keys_dedupes_glyphs_and_names_the_real_config(tmp_path, capsys):
    alt = tmp_path / 'elsewhere.hu'
    alt.write_text('{ }\n')
    assert _cs(tmp_path, '--config', str(alt), 'keys') == 0
    out = capsys.readouterr().out
    assert '⏎ / ⏎' not in out                  # enter + keypad enter read the same: shown once
    assert str(alt) in out.splitlines()[0] or 'elsewhere.hu' in out.splitlines()[0]
    assert '~/.config/configsys/configsys.hu' not in out


# -- 4: actions refuse to write under --pretend (what the TUI calls) ----------------------------------

def _pretend_ctx(home):
    return Context(build_parser().parse_args(['--home', str(home), '--os', 'pop', '--pretend',
                                              'inspect']))


def test_pretend_actions_refuse_to_write(tmp_path):
    ctx = _pretend_ctx(tmp_path)
    nsv = actions.PRETEND_NOT_SAVED
    assert actions.set_included(ctx, 'ripgrep', ['this-machine'], True) == (0, nsv)
    assert actions.set_config_setting(ctx, 'effects', ['none']) == (False, nsv)
    assert actions.set_disposition(ctx, 'ripgrep', 'seen') == (False, nsv)
    assert actions.add_machine(ctx, 'laptop') == (False, nsv)
    assert actions.rename_machine(ctx, 'this-machine', 'x') == (False, nsv)
    assert actions.stage_uninstall(ctx, 'ripgrep') == (False, nsv)
    assert actions.set_theme_value(ctx, 'colors.accent', '#ffffff') == (False, nsv)
    assert actions.ignore_orphan(ctx, 'foo*') == (False, nsv)
    assert actions.mark_all_seen(ctx, ['ripgrep']) == 0
    assert actions.move_picks_to_primary(ctx) == (0, nsv)
    _pdir, _existed = actions.save_theme_plugin(ctx, 'mytheme')
    files = [p for p in tmp_path.rglob('*') if p.is_file()]
    assert files == []


def test_real_run_actions_still_write(tmp_path):
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    ctx.ensure_user_config()
    n, _label = actions.set_included(ctx, 'ripgrep', ['this-machine'], True)
    assert n == 1
    assert 'ripgrep' in ctx.paths.user_config_file.read_text()


def test_ensure_user_config_pretend_writes_nothing(tmp_path):
    ctx = _pretend_ctx(tmp_path)
    ctx.ensure_user_config()
    assert not ctx.paths.user_config_file.exists()
    assert ctx.config.picks() == {} or isinstance(ctx.config.picks(), dict)   # loads fine without it
