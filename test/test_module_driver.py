'''The ModuleDriver base (review-2026-11-2 D5): every language-ecosystem installer's commands come from
its CMDS table — pinned here byte for byte, with the scope flag, sudo and location rules.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers._module import ModuleDriver
from configsys.runner import Runner


def unit(driver, name, **fields):
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name, fields={'name': name, **fields})


def ops(driver, name, **fields):
    r = Runner(pretend=True)
    d = get_driver(driver, r)
    rc = unit(driver, name, **fields)
    d.install(rc)
    d.uninstall(rc)
    d.upgrade(rc)
    d.set_version(rc, '1.2')
    return d, rc, r.calls


CARGO = 'PATH="$HOME/.cargo/bin:$PATH" cargo'


@pytest.mark.parametrize('driver,name,fields,want', [
    ('cargo', 'ripgrep', {}, [f'{CARGO} install ripgrep', f'{CARGO} uninstall ripgrep',
                              f'{CARGO} install --force ripgrep',
                              f'{CARGO} install --force --version 1.2 ripgrep']),
    ('opam', 'dune', {}, ['opam init --no-setup --yes && opam install -y dune', 'opam remove -y dune',
                          'opam upgrade -y dune', 'opam install -y dune.1.2']),
    ('luarocks', 'lpeg', {}, ['luarocks install --local lpeg', 'luarocks remove --local lpeg',
                              'luarocks install --local lpeg', 'luarocks install --local lpeg 1.2']),
    ('luarocks', 'lpeg', {'scope': 'system'}, ['sudo luarocks install lpeg', 'sudo luarocks remove lpeg',
                                               'sudo luarocks install lpeg', 'sudo luarocks install lpeg 1.2']),
    ('pip', 'black', {}, ['python3 -m pip install --user black',
                          'PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip uninstall -y black',
                          'python3 -m pip install --user --upgrade black',
                          'python3 -m pip install --user black==1.2']),
    ('pip', 'black', {'python': 'python3.12'}, ['python3.12 -m pip install --user black',
                                                'PIP_BREAK_SYSTEM_PACKAGES=1 python3.12 -m pip uninstall -y black',
                                                'python3.12 -m pip install --user --upgrade black',
                                                'python3.12 -m pip install --user black==1.2']),
    ('pipx', 'httpie', {}, ['python3 -m pipx install httpie', 'python3 -m pipx uninstall httpie',
                            'python3 -m pipx upgrade httpie', 'python3 -m pipx install --force httpie==1.2']),
])
def test_commands_are_the_table(driver, name, fields, want):
    d, _rc, calls = ops(driver, name, **fields)
    assert isinstance(d, ModuleDriver)
    assert [c for c in calls if 'uv --version' not in c] == want


def test_scope_flag_only_on_scope_honoring_drivers():
    r = Runner(pretend=True)
    gem, cargo = get_driver('gem', r), get_driver('cargo', r)
    assert gem.scope_flag(unit('gem', 'rake')) == '--user-install '
    assert gem.scope_flag(unit('gem', 'rake', scope='system')) == ''
    # cargo doesn't honor scope: a stray `scope: system` neither adds a flag nor sudo
    cargo.install(unit('cargo', 'fd-find', scope='system'))
    assert cargo.scope_flag(unit('cargo', 'x', scope='system')) == '' and not r.calls[-1].startswith('sudo')


def test_location_is_the_user_bin_dir_and_none_for_system_scope():
    r = Runner(pretend=True)
    assert get_driver('npm', r).location(unit('npm', 'x')) == '~/.local/bin'
    assert get_driver('npm', r).location(unit('npm', 'x', scope='system')) is None
    assert get_driver('cargo', r).location(unit('cargo', 'x')) == '~/.cargo/bin'
    assert get_driver('go-install', r).location(unit('go-install', 'golang.org/x/tools/gopls')) == '~/go/bin'


def test_index_key_is_the_module():
    r = Runner(pretend=True)
    assert get_driver('go-install', r).index_key(unit('go-install', 'github.com/a/b/cmd/c@v1')) == 'github.com/a/b/cmd/c'
    assert get_driver('pip', r).index_key(unit('pip', 'Foo_Bar')) == 'foo-bar'     # PEP 503
    assert get_driver('gem', r).index_key(unit('gem', 'rake')) == 'rake'


def test_parse_list_drives_installed_index():
    class R:
        def run(self, cmd, **kw):
            from configsys.runner import Result
            return Result(cmd, 0, stdout='ripgrep v14.1.0:\n    rg\nfd-find v10.2.0:\n    fd\n')
    assert get_driver('cargo', R()).installed_index() == {'ripgrep': '14.1.0', 'fd-find': '10.2.0'}


@pytest.mark.parametrize('driver', ['cargo', 'gem', 'opam'])
def test_listed_index_tool_not_installed_is_a_true_empty(driver):
    # the frozen rule (docs/plugins.md §7a): a manager that isn't installed at all (the shell's
    # command-not-found, exit 127) answers {} — nothing is installed via it — never the None that
    # means "couldn't tell" (which sends every unit to a per-unit probe of a tool that isn't there)
    def runner(code):
        class R:
            def run(self, cmd, **kw):
                from configsys.runner import Result
                return Result(cmd, code, stdout='')
        return R()
    assert get_driver(driver, runner(127)).installed_index() == {}
    assert get_driver(driver, runner(1)).installed_index() is None     # a real query failure
