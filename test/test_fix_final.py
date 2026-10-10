'''Regression tests for the last three audit findings (2026-10-10): per-field os/drivers merging,
the `where` providers line, and the kde_linux advisory's Homebrew route.'''
from types import SimpleNamespace

from configsys import layers
from configsys.app import main


def _layer(role, data):
    return SimpleNamespace(role=role, data=data, path=f'/{role}.hu')


def test_driver_override_keeps_unrestated_fields():
    # a top-config `drivers: { snap: { standing: never-auto } }` must not drop snap's shipped requires
    ls = [_layer('repo', {'drivers': {'snap': {'requires': ['snapd-socket'], 'when': 'ubuntu'}}}),
          _layer('user', {'drivers': {'snap': {'standing': 'never-auto'}}})]
    got = layers.merge_dict_section(ls, 'drivers', layers.ALL_ROLES)
    assert got['snap'] == {'requires': ['snapd-socket'], 'when': 'ubuntu', 'standing': 'never-auto'}


def test_restated_field_replaces_whole_and_new_names_add():
    ls = [_layer('repo', {'os': {'foo': {'using': 'linux', 'provides': ['a', 'b']}}}),
          _layer('plugin', {'os': {'foo': {'provides': ['c']}, 'bar': {'using': 'foo'}}})]
    got = layers.merge_dict_section(ls, 'os', layers.ALL_ROLES)
    assert got['foo'] == {'using': 'linux', 'provides': ['c']}
    assert got['bar'] == {'using': 'foo'}


def test_where_providers_line_skips_the_only_provider(tmp_path, capsys):
    main(['--home', str(tmp_path), '--os', 'pop_os!', 'where', 'cmake'])
    out = capsys.readouterr().out
    assert 'only provider here' not in out


def test_kde_linux_routes_pipx_through_homebrew():
    from configsys.routes import Resolver
    u = Resolver('routes.hu', 'kde_linux', '202610071200', 'x86_64').resolve_names(['pipx'])
    assert 'brew\\pipx' in u and 'script\\homebrew' in u
