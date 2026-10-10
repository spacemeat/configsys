'''Unit tests for the shell-writes guard (configsys/shellguard.py): snapshot -> install-scribble ->
revert-to-prior-bytes + stage the removed block as an inactive glue candidate for review.'''

import os
from pathlib import Path

from configsys import shellguard
from configsys.runner import Runner


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


def _paths(tmp_path):
    from configsys.paths import Paths
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'), 'CONFIGSYS_REPO': str(tmp_path / 'repo'),
                      'CONFIGSYS_GLUE_SHELLS': 'bash,zsh'})


def test_stage_writes_inactive_candidate_in_machine_local_state(tmp_path):
    p = _paths(tmp_path)
    staged = shellguard.stage(p, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n', 'zsh': 'Z=1\n'})
    root = p.state_dir / 'staged-glue'
    assert staged == [('bash', root / 'bash' / 'sdkman.sh'), ('zsh', root / 'zsh' / 'sdkman.zsh')]
    assert (root / 'bash' / 'sdkman.sh').read_text() == 'export SDKMAN_DIR=x\n'
    # nothing linked anywhere yet -> inactive; nothing under any dotfiles/plugin tree
    assert not (p.home / '.config' / 'bash' / 'conf.d').exists()
    assert not (p.user_dotfiles_dir / 'staged-glue').exists()


def test_list_and_staged_for(tmp_path):
    p = _paths(tmp_path)
    shellguard.stage(p, 'sdkman', {'bash': 'a\n', 'zsh': 'b\n'})
    shellguard.stage(p, 'nvm', {'bash': 'c\n'})
    allrows = shellguard.list_staged(p)
    assert ('sdkman', 'bash', p.state_dir / 'staged-glue' / 'bash' / 'sdkman.sh') in allrows
    assert sorted(s for s, _ in shellguard.staged_for(p, 'sdkman')) == ['bash', 'zsh']


def test_activate_becomes_user_glue_and_clears_stage(tmp_path):
    p = _paths(tmp_path)
    p.home.mkdir(parents=True)
    shellguard.stage(p, 'sdkman', {'bash': 'export SDKMAN_DIR=x\n'})
    done = shellguard.activate(p, 'sdkman', Runner(pretend=False))
    link = p.home / '.config' / 'bash' / 'conf.d' / '90-sdkman.sh'
    snippet = p.user_glue_dir / 'shell' / 'bash' / 'user.d' / 'sdkman.sh'
    assert done == [('bash', link)]
    assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(snippet)
    assert 'export SDKMAN_DIR=x' in snippet.read_text()
    assert os.stat(snippet).st_mode & 0o111                # executable so loaders source it
    assert shellguard.staged_for(p, 'sdkman') == []        # staged copy consumed


def test_discard_drops_without_activating(tmp_path):
    p = _paths(tmp_path)
    shellguard.stage(p, 'sdkman', {'bash': 'x\n'})
    assert shellguard.discard(p, 'sdkman') == 1
    assert shellguard.staged_for(p, 'sdkman') == []
    assert not (p.home / '.config' / 'bash' / 'conf.d').exists()


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
    staged = shellguard.staged_for(paths, 'sdkman')
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
    assert shellguard.staged_for(paths, 'nvm') == []
