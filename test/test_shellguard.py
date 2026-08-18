'''Unit tests for the shell-writes guard (configsys/shellguard.py): snapshot -> install-scribble ->
revert-to-prior-bytes + stage the removed block as an inactive glue candidate for review.'''

import os
from pathlib import Path

from configsys import shellguard


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_snapshot_reads_present_and_absent(tmp_path):
    _write(tmp_path / '.bashrc', 'export A=1\n')
    snap = shellguard.snapshot(tmp_path)
    assert snap[str(tmp_path / '.bashrc')] == 'export A=1\n'
    assert snap[str(tmp_path / '.zshrc')] is None          # absent -> None


def test_revert_removes_appended_lines(tmp_path):
    rc = tmp_path / '.bashrc'
    _write(rc, 'export A=1\n')
    snap = shellguard.snapshot(tmp_path)
    # simulate an installer appending its block
    rc.write_text('export A=1\n# sdkman\nexport SDKMAN_DIR="$HOME/.sdkman"\nsource "$SDKMAN_DIR/bin"\n')
    captured = shellguard.revert_and_capture(tmp_path, snap)
    assert rc.read_text() == 'export A=1\n'                # reverted to exact prior bytes
    assert 'bash' in captured
    assert 'SDKMAN_DIR' in captured['bash'] and 'source' in captured['bash']


def test_revert_deletes_file_the_install_created(tmp_path):
    # no .zshrc before; installer creates one -> revert removes it entirely
    snap = shellguard.snapshot(tmp_path)
    (tmp_path / '.zshrc').write_text('# nvm\nexport NVM_DIR=~/.nvm\n')
    captured = shellguard.revert_and_capture(tmp_path, snap)
    assert not (tmp_path / '.zshrc').exists()
    assert 'NVM_DIR' in captured['zsh']


def test_unchanged_file_is_not_captured(tmp_path):
    _write(tmp_path / '.bashrc', 'export A=1\n')
    snap = shellguard.snapshot(tmp_path)
    captured = shellguard.revert_and_capture(tmp_path, snap)   # nothing touched it
    assert captured == {}


def test_routes_bash_and_zsh_separately(tmp_path):
    _write(tmp_path / '.bashrc', '')
    _write(tmp_path / '.zshrc', '')
    snap = shellguard.snapshot(tmp_path)
    (tmp_path / '.bashrc').write_text('BASH_ONLY=1\n')
    (tmp_path / '.zshrc').write_text('ZSH_ONLY=1\n')
    captured = shellguard.revert_and_capture(tmp_path, snap)
    assert 'BASH_ONLY' in captured['bash'] and 'BASH_ONLY' not in captured.get('zsh', '')
    assert 'ZSH_ONLY' in captured['zsh'] and 'ZSH_ONLY' not in captured.get('bash', '')


def test_stage_writes_inactive_candidate(tmp_path):
    root = tmp_path / 'store'
    staged = shellguard.stage(root, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n'})
    assert staged == [('bash', root / 'staged-glue' / 'sdkman.bash.sh')]
    assert (root / 'staged-glue' / 'sdkman.bash.sh').read_text() == 'export SDKMAN_DIR=x\n'
    # nothing linked anywhere yet -> inactive
    assert not (tmp_path / '.config' / 'bash' / 'conf.d').exists()


def test_list_and_staged_for(tmp_path):
    root = tmp_path / 'store'
    shellguard.stage(root, 'sdkman', {'bash': 'a\n', 'zsh': 'b\n'})
    shellguard.stage(root, 'nvm', {'bash': 'c\n'})
    allrows = shellguard.list_staged(root)
    assert ('sdkman', 'bash', root / 'staged-glue' / 'sdkman.bash.sh') in allrows
    assert sorted(s for s, _ in shellguard.staged_for(root, 'sdkman')) == ['bash', 'zsh']


def test_activate_links_into_confd_and_clears_stage(tmp_path):
    home = tmp_path
    root = tmp_path / 'store'
    shellguard.stage(root, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n'})
    done = shellguard.activate(root, 'sdkman', home)
    link = home / '.config' / 'bash' / 'conf.d' / 'sdkman.sh'
    author = root / 'shell' / 'bash' / 'sdkman.sh'
    assert done == [('bash', link)]
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(author)
    assert author.read_text() == 'export SDKMAN_DIR=x\n'
    assert os.stat(author).st_mode & 0o111                 # executable so loaders source it
    assert shellguard.staged_for(root, 'sdkman') == []     # staged copy consumed


def test_discard_drops_without_activating(tmp_path):
    root = tmp_path / 'store'
    shellguard.stage(root, 'sdkman', {'bash': 'x\n'})
    assert shellguard.discard(root, 'sdkman') == 1
    assert shellguard.staged_for(root, 'sdkman') == []
    assert not (tmp_path / '.config' / 'bash' / 'conf.d').exists()


# -- integration: the guard fires through the TUI execute_plan path -------

def test_execute_plan_reverts_and_stages(tmp_path, capsys):
    from types import SimpleNamespace
    from configsys.componentObj import ResolvedComponent
    from configsys.ledger import Ledger
    from configsys.paths import Paths
    from configsys.runner import Result
    from configsys.tui.menu import execute_plan

    home = tmp_path
    (home / '.bashrc').write_text('export EXISTING=1\n')

    class ScribblingRunner:
        pretend = False
        tui_active = False

        def __init__(self):
            self.calls = []

        def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
            self.calls.append(cmd)
            if 'install' in cmd and 'sdkman' in cmd:            # emulate an rc-scribbling installer
                (home / '.bashrc').write_text('export EXISTING=1\nexport SDKMAN_DIR="$HOME/.sdkman"\n')
            return Result(cmd, 0)

        def end_sudo(self):
            pass

    paths = Paths(env={'HOME': str(home), 'CONFIGSYS_STATE_DIR': str(home / 's')})
    cfg = SimpleNamespace(guard_shell_writes=lambda comp: True)     # guard armed
    ctx = SimpleNamespace(runner=ScribblingRunner(), paths=paths, config=cfg)
    rc = ResolvedComponent(key='apt\\sdkman', driver='apt', comp='sdkman', fields={'name': 'sdkman'})

    outcomes = execute_plan(ctx, [('install', 'apt\\sdkman', rc)], Ledger())

    assert outcomes[0].ok                                          # install itself succeeded
    assert (home / '.bashrc').read_text() == 'export EXISTING=1\n'  # scribble reverted
    staged = shellguard.staged_for(paths.user_dotfiles_dir, 'sdkman')
    assert [s for s, _ in staged] == ['bash']
    assert 'SDKMAN_DIR' in staged[0][1].read_text()
    assert 'guarded: reverted' in capsys.readouterr().out


def test_execute_plan_allowlisted_component_writes_through(tmp_path):
    from types import SimpleNamespace
    from configsys.componentObj import ResolvedComponent
    from configsys.ledger import Ledger
    from configsys.paths import Paths
    from configsys.runner import Result
    from configsys.tui.menu import execute_plan

    home = tmp_path
    (home / '.bashrc').write_text('export EXISTING=1\n')

    class R:
        pretend = False
        tui_active = False
        def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
            (home / '.bashrc').write_text('export EXISTING=1\nWROTE=1\n')
            return Result(cmd, 0)
        def end_sudo(self): pass

    paths = Paths(env={'HOME': str(home), 'CONFIGSYS_STATE_DIR': str(home / 's')})
    cfg = SimpleNamespace(guard_shell_writes=lambda comp: False)    # allow-listed -> not guarded
    ctx = SimpleNamespace(runner=R(), paths=paths, config=cfg)
    rc = ResolvedComponent(key='apt\\nvm', driver='apt', comp='nvm', fields={'name': 'nvm'})

    execute_plan(ctx, [('install', 'apt\\nvm', rc)], Ledger())
    assert (home / '.bashrc').read_text() == 'export EXISTING=1\nWROTE=1\n'   # left in place
    assert shellguard.staged_for(paths.user_dotfiles_dir, 'nvm') == []
