from pathlib import Path

from configsys.paths import Paths


def test_defaults_from_home():
    p = Paths(env={'HOME': '/home/alice'})
    assert p.home == Path('/home/alice')
    assert p.state_dir == Path('/home/alice/.config/configsys')
    assert p.user_config_file == Path('/home/alice/.config/configsys/configsys.hu')
    assert p.legacy_user_config_file == Path('/home/alice/configsys.hu')
    assert p.ledger_file == Path('/home/alice/.config/configsys/state.hu')


def test_configsys_home_overrides_home_and_sandboxes_state():
    p = Paths(env={'HOME': '/home/alice', 'CONFIGSYS_HOME': '/tmp/sandbox'})
    assert p.home == Path('/tmp/sandbox')
    assert p.state_dir == Path('/tmp/sandbox/.config/configsys')
    assert p.user_config_file == Path('/tmp/sandbox/.config/configsys/configsys.hu')


def test_configsys_home_wins_over_xdg():
    # a sandbox home must contain everything, even when XDG_CONFIG_HOME is set in the env
    p = Paths(env={'HOME': '/home/alice', 'XDG_CONFIG_HOME': '/xdg', 'CONFIGSYS_HOME': '/tmp/sb'})
    assert p.state_dir == Path('/tmp/sb/.config/configsys')


def test_xdg_config_home_respected():
    p = Paths(env={'HOME': '/home/alice', 'XDG_CONFIG_HOME': '/xdg'})
    assert p.state_dir == Path('/xdg/configsys')
    assert p.user_config_file == Path('/xdg/configsys/configsys.hu')


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


def test_data_root_is_the_source_tree_when_cloned():
    # a normal checkout: routes.hu sits at the repo root beside the package -> that wins, so the
    # from-source workflow is unchanged (no CONFIGSYS_REPO needed).
    p = Paths(env={'HOME': '/home/x'})
    assert (p.repo / 'routes.hu').exists()
    assert p.routes_file.exists() and p.config_file.exists()


def test_data_root_falls_back_to_package_data_when_installed(tmp_path):
    # A pip/pipx install has NO repo-root routes.hu; the build ships the data as package data under
    # configsys/data/. Simulate that layout in a fully isolated interpreter (the in-process package
    # would always find the real source tree first), and confirm _locate_data_root picks the
    # package-data dir. This is the branch that makes `pip install configsys-cli` actually work.
    import os
    import shutil
    import subprocess
    import sys

    src_pkg = Path(__file__).resolve().parent.parent / 'configsys'
    site = tmp_path / 'site'
    pkg = site / 'configsys'
    shutil.copytree(src_pkg, pkg, ignore=shutil.ignore_patterns('__pycache__'))
    (pkg / 'data').mkdir()
    (pkg / 'data' / 'routes.hu').write_text('{ os: {} }')
    (pkg / 'data' / 'config.hu').write_text('{ configs: [] }')
    # deliberately NO routes.hu at the site root -> the source-tree probe must miss

    probe = (
        'from configsys.paths import Paths\n'
        'p = Paths(env={"HOME": "/home/x"})\n'
        'print(p.repo)\n'
    )
    env = {**os.environ, 'PYTHONPATH': str(site)}
    env.pop('CONFIGSYS_REPO', None)
    r = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True,
                       env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(pkg / 'data')
