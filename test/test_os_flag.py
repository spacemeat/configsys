'''`--os BLOCK[:VERSION]` / CONFIGSYS_OS: the version suffix, the flag replacing the env pair, a
clean error for an unknown block or a non-numeric version (never a traceback or a silent stand-in),
the ID_LIKE fallback for a detected distro with no block, and `where` naming the version conditions
a versionless block reads false.'''
import pytest

from configsys import osdetect
from configsys.app import Context, build_parser, main, where_report
from configsys.errors import ConfigsysError


def test_split_forced():
    assert osdetect.split_forced('alpine:3.24') == ('alpine', '3.24')
    assert osdetect.split_forced('fedora') == ('fedora', None)
    assert osdetect.split_forced('pop_os!:22.04') == ('pop_os!', '22.04')
    assert osdetect.split_forced('arch:') == ('arch', None)


def test_forced_version_suffix_and_env_fallback():
    info = osdetect.detect(env={'CONFIGSYS_OS': 'alpine:3.24'})
    assert (info.block, info.version, info.forced) == ('alpine', '3.24', True)
    info = osdetect.detect(env={'CONFIGSYS_OS': 'alpine', 'CONFIGSYS_OS_VERSION': '3.23'})
    assert info.version == '3.23'
    info = osdetect.detect(env={'CONFIGSYS_OS': 'alpine:3.24', 'CONFIGSYS_OS_VERSION': '3.23'})
    assert info.version == '3.24'                       # the value's own version wins
    assert osdetect.detect(env={'CONFIGSYS_OS': 'pop:22.04'}).block == 'pop_os!'


def test_forced_non_numeric_version_is_an_error():
    with pytest.raises(ConfigsysError, match='not a version number'):
        osdetect.detect(env={'CONFIGSYS_OS': 'alpine:latest'})


def test_settle_forced_unknown_block_errors_with_close_names():
    info = osdetect.OsInfo('debain', [], 'debain', forced=True)
    with pytest.raises(ConfigsysError, match='Did you mean debian'):
        osdetect.settle(info, {'debian': {}, 'arch': {}})


def test_settle_detected_unknown_falls_back_to_id_like_without_version():
    info = osdetect.OsInfo('frobos', ['ubuntu', 'debian'], 'frobos', '7')
    note = osdetect.settle(info, {'ubuntu': {}, 'debian': {}})
    assert (info.block, info.version) == ('ubuntu', None)
    assert 'frobos' in note and 'request-os' in note


def test_settle_detected_unknown_with_no_relative_errors():
    info = osdetect.OsInfo('frobos', ['nothing'], 'frobos', '7')
    with pytest.raises(ConfigsysError, match='request-os'):
        osdetect.settle(info, {'ubuntu': {}})


def test_settle_known_block_is_untouched():
    info = osdetect.OsInfo('arch', [], 'arch', forced=True)
    assert osdetect.settle(info, {'arch': {}}) is None and info.block == 'arch'


def test_cli_unknown_block_is_a_clean_error(tmp_path, capsys):
    assert main(['--home', str(tmp_path), '--os', 'debain', 'check']) == 1
    err = capsys.readouterr().err
    assert 'no OS block named "debain"' in err and 'Did you mean debian' in err


def test_cli_bad_version_is_a_clean_error(tmp_path, capsys):
    assert main(['--home', str(tmp_path), '--os', 'alpine:latest', 'check']) == 1
    assert 'not a version number' in capsys.readouterr().err


def _ctx(tmp_path, *argv, env=None, monkeypatch=None):
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return Context(build_parser().parse_args(['--home', str(tmp_path), *argv, 'inspect']))


def test_cli_version_suffix_reaches_the_resolver(tmp_path):
    ctx = _ctx(tmp_path, '--os', 'alpine:3.24')
    assert (ctx.routes.block, ctx.routes.version) == ('alpine', '3.24')


def test_cli_flag_replaces_the_env_version(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, '--os', 'fedora', env={'CONFIGSYS_OS_VERSION': '24.04'},
               monkeypatch=monkeypatch)
    assert ctx.routes.version is None                   # 24.04 was meant for some other OS


def test_where_names_version_conditions_a_versionless_block_reads_false(tmp_path):
    bare = '\n'.join(where_report(_ctx(tmp_path, '--os', 'alpine'), 'mangowm'))
    assert 'no OS version set' in bare and 'alpine >= 3.24' in bare and '--os alpine:VERSION' in bare
    versioned = '\n'.join(where_report(_ctx(tmp_path, '--os', 'alpine:3.24'), 'mangowm'))
    assert 'no OS version set' not in versioned and 'apk\\mangowm' in versioned


def test_resolution_refuses_an_unknown_block_cleanly(tmp_path):
    # a long-lived Context (the TUI) may force a block a plugin will add later, so the Context loads;
    # resolving against the block before it exists is a clean error, never an IndexError
    import argparse
    ctx = Context(argparse.Namespace(pretend=True, os='bogus', home=str(tmp_path), config=None))
    assert 'git' in ctx.routes.components
    with pytest.raises(ConfigsysError, match='no OS block named "bogus"'):
        ctx.routes.resolve_names(['git'])
    with pytest.raises(ConfigsysError, match='no OS block named "bogus"'):
        ctx.check_os()


def test_plugin_commands_run_with_a_block_not_yet_loaded(tmp_path, capsys):
    # `plugin …` may be what brings a forced block (`--os myos plugin add …`), so it isn't refused
    assert main(['--home', str(tmp_path), '--os', 'bogus', 'plugin', 'list']) in (0, 1)
    assert 'no OS block' not in capsys.readouterr().err
