'''Regression tests: picks --machine dest, config show coverage + the four added settings, plugin
set-source retargets the clone, a data-file-less primary still takes picks, set-version refuses on
version-less methods, profile ops skip unroutable members, keys order, epilog + advisory text.'''

import subprocess
import types

from configsys import actions, app
from configsys.app import build_parser, main
from configsys.componentObj import ResolvedComponent
from configsys.runner import Result, Runner


def _cs(home, *argv):
    return main(['--home', str(home), '--os', 'pop', *argv])


# -- 2 ---------------------------------------------------------------------------------------------

def test_picks_list_keeps_the_global_machine():
    p = build_parser()
    assert p.parse_args(['--machine', 'foo', 'picks', 'list']).machine == 'foo'
    assert p.parse_args(['picks', 'list', '--machine', 'bar']).machine == 'bar'
    assert p.parse_args(['picks', 'list']).machine is None


def test_picks_list_global_machine_selects_that_column(tmp_path, capsys):
    _cs(tmp_path, 'machine', 'add', 'laptop')
    _cs(tmp_path, 'picks', 'add', 'ripgrep', '--machine', 'laptop')
    capsys.readouterr()
    _cs(tmp_path, '--machine', 'laptop', 'picks', 'list')
    out = capsys.readouterr().out
    assert 'picks for laptop' in out and 'ripgrep' in out


# -- 3 + 4 -----------------------------------------------------------------------------------------

def test_every_setting_has_a_display_getter_and_a_nature():
    non_dir = {k for k, v in actions.CONFIG_SETTINGS.items() if v[0] != 'dir'}
    assert set(actions._SETTING_GETTERS) == non_dir
    assert set(actions.CONFIG_SETTINGS) <= set(actions.SETTING_NATURE)


def test_new_settings_registered_with_their_natures():
    for key, nature in (('locations', 'machine'), ('detect-coexisting', 'uniform'),
                        ('installer-shell-writes', 'uniform'),
                        ('installer-shell-writes-allow', 'uniform')):
        assert key in actions.CONFIG_SETTINGS
        assert actions.SETTING_NATURE[key] == nature


def test_config_show_reports_values_that_were_set(tmp_path, capsys):
    for argv in (['disabled-drivers', 'snap'], ['refresh-before-execute', 'never'],
                 ['install-overlay', 'false'], ['reboot-advice', 'false'], ['effects', 'reduced'],
                 ['detect-coexisting', 'false'], ['installer-shell-writes', 'allow'],
                 ['installer-shell-writes-allow', 'rustup'],
                 ['locations', 'ripgrep=/opt/rg', 'fd=/opt/fd']):
        assert _cs(tmp_path, 'config', 'set', *argv) == 0
    capsys.readouterr()
    _cs(tmp_path, 'config', 'show')
    rows = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()
            if line.startswith('  ') and line.split() and not line.startswith('   ')}
    assert 'snap' in rows['disabled-drivers']
    assert 'never' in rows['refresh-before-execute']
    assert 'false' in rows['install-overlay']
    assert 'false' in rows['reboot-advice']
    assert 'reduced' in rows['effects']
    assert 'false' in rows['detect-coexisting']
    assert 'allow' in rows['installer-shell-writes']
    assert 'rustup' in rows['installer-shell-writes-allow']
    assert 'fd=/opt/fd ripgrep=/opt/rg' in rows['locations']


def test_locations_set_get_unset_roundtrip(tmp_path, capsys):
    assert _cs(tmp_path, 'config', 'set', 'locations', 'ripgrep=/opt/rg') == 0
    capsys.readouterr()
    _cs(tmp_path, 'config', 'get', 'locations')
    assert capsys.readouterr().out.strip() == 'ripgrep=/opt/rg'
    assert _cs(tmp_path, 'config', 'set', 'locations', 'bogus') == 1      # needs comp=path
    assert _cs(tmp_path, 'config', 'unset', 'locations') == 0
    capsys.readouterr()
    _cs(tmp_path, 'config', 'get', 'locations')
    assert 'ripgrep' not in capsys.readouterr().out


# -- 5 ---------------------------------------------------------------------------------------------

def _git_repo(d, name):
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(f'{{\n    name: {name}\n    requires-abi: 1\n}}\n')
    g = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'init.defaultBranch=main']
    subprocess.run(g + ['init', '-q', str(d)], check=True)
    subprocess.run(g + ['-C', str(d), 'add', '.'], check=True)
    subprocess.run(g + ['-C', str(d), 'commit', '-qm', 'init'], check=True)


def test_set_source_retargets_the_synced_clone(tmp_path, capsys):
    a, b = tmp_path / 'a' / 'myplug', tmp_path / 'b' / 'myplug'
    _git_repo(a, 'myplug')
    _git_repo(b, 'myplug')
    home = tmp_path / 'home'
    assert _cs(home, 'plugin', 'add', str(a)) == 0
    clone = home / '.config' / 'configsys' / 'plugins' / 'myplug'
    url = lambda: subprocess.run(['git', '-C', str(clone), 'remote', 'get-url', 'origin'],  # noqa: E731
                                 capture_output=True, text=True).stdout.strip()
    assert url() == str(a)
    assert _cs(home, 'plugin', 'set-source', 'myplug', str(b)) == 0
    assert url() == str(b)


# -- 6 ---------------------------------------------------------------------------------------------

def test_primary_without_data_file_gets_one_on_first_edit(tmp_path, capsys):
    assert _cs(tmp_path, 'plugin', 'init', 'mine') == 0
    plug = tmp_path / '.config' / 'configsys' / 'plugins' / 'mine'
    assert not list(p for p in plug.glob('*.hu') if p.name != 'plugin.hu')   # the bug's precondition
    capsys.readouterr()
    assert _cs(tmp_path, 'picks', 'add', 'ripgrep') == 0
    assert '(in mine)' in capsys.readouterr().out
    assert 'ripgrep' in (plug / 'mine.hu').read_text()
    _cs(tmp_path, 'picks', 'list')
    assert 'ripgrep' in capsys.readouterr().out


# -- 7 ---------------------------------------------------------------------------------------------

class _NoVerDrv:
    name = 'tarball'
    privileged = False
    targets_version = False

    def sudo(self, rc):
        return False

    def set_version(self, rc, v):                     # the bug: reinstalls the routed version, "ok"
        raise AssertionError('set_version must not be called')


def test_run_plan_refuses_set_version_on_a_versionless_method(monkeypatch):
    import configsys.drivers as drivers_mod
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: _NoVerDrv())
    ctx = types.SimpleNamespace(runner=Runner(pretend=True), paths=None, config=None)
    rc = ResolvedComponent(key='tarball\\x', driver='tarball', comp='x', fields={})
    lines = []
    res = actions.run_plan(ctx, [('set-version', 'tarball\\x', rc)], version='1.2.3',
                           on_line=lines.append)
    assert res.rc_code == 1 and res.n_fatal == 1
    assert not res.outcomes[0].ok
    assert 'installs the routed version only' in '\n'.join(lines)
    assert 'configsys versions x' in '\n'.join(lines)


def test_targets_version_defaults_true():
    class D:
        pass
    assert actions.targets_version(D()) is True
    assert actions.targets_version(_NoVerDrv()) is False


def test_cli_set_version_on_dotfiles_fails_up_front(tmp_path, capsys):
    rc = _cs(tmp_path, '--pretend', 'set-version', 'lazygit-dotfiles', '1.2.3')
    err = capsys.readouterr().err
    assert rc == 1
    assert 'installs the routed version only' in err


# -- 8 ---------------------------------------------------------------------------------------------

def test_profile_install_skips_unroutable_members(tmp_path, capsys):
    rc = main(['--home', str(tmp_path), '--os', 'ubuntu', '--pretend', 'install', 'profile:terminal'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'not installable here' in out and 'ueberzugpp' in out
    assert 'no binding for ueberzugpp' not in out


def test_explicit_unroutable_component_still_errors(tmp_path, capsys):
    rc = main(['--home', str(tmp_path), '--os', 'ubuntu', '--pretend', 'install', 'ueberzugpp'])
    assert rc != 0


# -- 9, 10, 11, 12 ---------------------------------------------------------------------------------

def test_keys_print_in_screen_order(tmp_path, capsys):
    _cs(tmp_path, 'keys')
    out = capsys.readouterr().out
    order = [s for s in ('components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config', 'theme')
             if f'[{s}]' in out]
    assert order == sorted(order, key=lambda s: out.index(f'[{s}]'))
    assert '[glue]' in out


def test_orphans_docstring_no_longer_claims_read_only():
    assert 'phase-1' not in app.cmd_orphans.__doc__
    assert '--adopt' in app.cmd_orphans.__doc__


def test_epilog_token_env_text():
    e = app._EPILOG
    assert 'CONFIGSYS_GIT_TOKEN' in e and 'private github: / gitlab: plugin' in e
    assert 'rate limit for version checks' in e and 'GITHUB_TOKEN also works' in e


def test_os_advisories_tell_the_truth(tmp_path, capsys):
    main(['--home', str(tmp_path), '--os', 'chimera', '--pretend', 'inspect'])
    out = capsys.readouterr()
    text = out.out + out.err
    assert 'practically NOTHING installs here' in text
    assert 'musl tarballs, cargo' not in text
    main(['--home', str(tmp_path), '--os', 'kde_linux', '--pretend', 'inspect'])
    out = capsys.readouterr()
    text = (out.out + out.err).replace('\n', ' ')
    assert "pipx tools come through Homebrew" in text and '`via: pip` packages' in text
    assert 'cargo, pipx' not in text


# -- 15: install --picks / upgrade --picks ---------------------------------------------------------

def test_picks_flags_parse():
    p = build_parser()
    a = p.parse_args(['install', '--picks', '--yes'])
    assert a.picks and a.yes and a.names == []
    a = p.parse_args(['upgrade', '--picks', 'btop'])
    assert a.picks and not a.yes and a.names == ['btop']


def test_install_without_names_or_picks_errors(tmp_path, capsys):
    assert _cs(tmp_path, 'install') == 1
    assert '--picks' in capsys.readouterr().out


def test_picks_refuses_another_machine(tmp_path, capsys):
    rc = _cs(tmp_path, '--machine', 'elsewhere', 'install', '--picks')
    assert rc == 1
    assert 'THIS box' in capsys.readouterr().err


def test_pretend_install_picks_plans_picks_and_skips_unroutable(tmp_path, capsys):
    home = tmp_path
    for c in ('ripgrep', 'ueberzugpp'):
        main(['--home', str(home), '--os', 'ubuntu', 'picks', 'add', c])
    capsys.readouterr()
    rc = main(['--home', str(home), '--os', 'ubuntu', '--pretend', 'install', '--picks'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'skipped 1 not installable here: ueberzugpp' in out
    assert 'plan (' in out and 'apt\\ripgrep' in out


def test_picks_union_with_names_and_confirmation_gate(tmp_path, capsys, monkeypatch):
    seen = {}

    def fake_dispatch(ctx, names, op, **kw):
        seen.update(names=names, op=op, **kw)
        return 0
    monkeypatch.setattr(app, '_picks_selection', lambda ctx, op: (['ripgrep', 'btop'], 0))
    monkeypatch.setattr(app, '_dispatch_op', fake_dispatch)
    assert _cs(tmp_path, 'upgrade', '--picks', 'fd', 'btop') == 0
    assert seen['op'] == 'upgrade' and seen['names'] == ['fd', 'btop', 'ripgrep']
    assert seen['confirm'] is True and seen['yes'] is False
    monkeypatch.setattr(app, '_picks_selection', lambda ctx, op: ([], 0))
    capsys.readouterr()
    assert _cs(tmp_path, 'install', '--picks') == 0
    assert 'nothing to do' in capsys.readouterr().out


def test_confirm_plan_needs_yes_when_not_interactive(capsys, monkeypatch):
    ctx = types.SimpleNamespace(runner=Runner(pretend=False))
    plan = [('install', 'apt\\ripgrep', None)]
    monkeypatch.setattr('sys.stdin.isatty', lambda: False, raising=False)
    assert app._confirm_plan(ctx, plan) is False
    out = capsys.readouterr().out
    assert 'apt\\ripgrep' in out and '--yes' in out
    assert app._confirm_plan(ctx, plan, yes=True) is True
    assert app._confirm_plan(types.SimpleNamespace(runner=Runner(pretend=True)), plan) is True
