from pathlib import Path

from configsys.paths import Paths


def test_defaults_from_home():
    p = Paths(env={'HOME': '/home/alice'})
    assert p.home == Path('/home/alice')
    assert p.user_config_file == Path('/home/alice/configsys.hu')
    assert p.state_dir == Path('/home/alice/.config/configsys')
    assert p.ledger_file == Path('/home/alice/.config/configsys/state.hu')


def test_configsys_home_overrides_home():
    p = Paths(env={'HOME': '/home/alice', 'CONFIGSYS_HOME': '/tmp/sandbox'})
    assert p.home == Path('/tmp/sandbox')
    assert p.user_config_file == Path('/tmp/sandbox/configsys.hu')


def test_xdg_config_home_respected():
    p = Paths(env={'HOME': '/home/alice', 'XDG_CONFIG_HOME': '/xdg'})
    assert p.state_dir == Path('/xdg/configsys')


def test_explicit_overrides():
    p = Paths(env={
        'HOME': '/home/alice',
        'CONFIGSYS_REPO': '/opt/configsys',
        'CONFIGSYS_CONFIG': '/custom/sel.hu',
        'CONFIGSYS_STATE_DIR': '/var/state',
    })
    assert p.repo == Path('/opt/configsys')
    assert p.routes_file == Path('/opt/configsys/routes.hu')
    assert p.config_file == Path('/opt/configsys/config.hu')
    assert p.user_config_file == Path('/custom/sel.hu')
    assert p.ledger_file == Path('/var/state/state.hu')


def test_expand_tilde_against_configsys_home():
    p = Paths(env={'CONFIGSYS_HOME': '/tmp/sandbox'})
    assert p.expand('~/apps/neovim') == Path('/tmp/sandbox/apps/neovim')
    assert p.expand('~') == Path('/tmp/sandbox')
    assert p.expand('/etc/apt/x') == Path('/etc/apt/x')


def test_expand_bare_relative_is_home_relative():
    p = Paths(env={'CONFIGSYS_HOME': '/tmp/sandbox'})
    assert p.expand('vulkan') == Path('/tmp/sandbox/vulkan')
    assert p.expand('apps/nvim.appimage') == Path('/tmp/sandbox/apps/nvim.appimage')
