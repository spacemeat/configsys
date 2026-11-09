'''`--pretend` writes nothing, anywhere. A populated sandbox home, then every mutating CLI verb run
under --pretend, with the whole home tree (contents, mtimes, links) compared after each one. Plus the
TUI-only write paths the CLI can't reach (Dotfiles manage / move-store, glue writers, the method-
version cache, startup timing), and the guarantee that a dry-run `report --yes` files nothing.'''

import os
import shutil
import subprocess

import pytest

from configsys import actions
from configsys.app import main

pytestmark = [pytest.mark.real_runner, pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


def _snapshot(root):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for n in dirs + files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                out[rel] = ('link', os.readlink(p))
            elif os.path.isdir(p):
                out[rel] = ('dir',)
            else:
                st = os.stat(p)
                with open(p, 'rb') as f:
                    out[rel] = ('file', f.read(), st.st_mtime_ns, st.st_mode)
    return out


def _changes(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    for k in list(os.environ):
        if k.startswith(('CONFIGSYS_', 'XDG_')):
            monkeypatch.delenv(k)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr('builtins.input', lambda *a: 'y')
    src = tmp_path / 'srcplug'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: codeplug  requires-abi: 1  code: driver.py  data: [ r.hu ] }')
    (src / 'driver.py').write_text('DRIVERS = []\n')
    (src / 'r.hu').write_text('{ components: { ctool: { description: "x"  install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'A'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    (home / '.bashrc').write_text('# bashrc\n')
    (home / '.config' / 'btop').mkdir(parents=True)
    (home / '.config' / 'btop' / 'btop.conf').write_text('color_theme = "x"\n')
    base = ['--home', str(home), '--os', 'pop_os!:22.04', '-q']
    for args in (['picks', 'add', 'btop'], ['picks', 'add', 'fzf'], ['picks', 'add', 'bash'],
                 ['plugin', 'add', str(src), '--ref', 'v1', '--local'], ['plugin', 'trust', 'codeplug'],
                 ['machine', 'add', 'laptop'], ['pin', 'set', 'fzf', 'native'],
                 ['picks', 'add', 'syncthing'], ['pin', 'set', 'syncthing', 'tarball'],   # a github version source (A14)
                 ['dotfiles', 'capture', 'btop', '--yes'], ['glue', 'add', 'mine', '--shell', 'bash']):
        assert main(base + args) == 0, args
    state = home / '.config' / 'configsys'
    (state / 'staged-glue' / 'bash').mkdir(parents=True)
    (state / 'staged-glue' / 'bash' / 'rustup.sh').write_text('export PATH="$HOME/.cargo/bin:$PATH"\n')
    for name, text in (('glue-locations.tsv', 'btop\t/usr/bin/btop\n'),
                       ('method-versions.hu', '{ "apt\\\\btop": { version: "1.2.13"  fetched: "1.0" } }\n'),
                       ('stale-pins.json', '{"foo": ["1.0", "2.0"]}'), ('last-refresh', '1700000000'),
                       ('startup-timing.json', '{"load": 1.0}')):
        (state / name).write_text(text)
    return home, base + ['--pretend']


# Every verb that edits config, state, plugins, dotfiles or glue — each must leave the home untouched.
VERBS = [
    ['install', 'btop', '--yes'], ['install', '--picks', '--yes'], ['remove', 'btop'],
    ['upgrade', '--picks', '--yes'], ['upgrade', '--system', '--yes'], ['lock', 'btop'], ['unlock', 'btop'],
    ['fix-scope'], ['set-version', 'fzf', '0.40.0'],
    ['machine', 'add', 'desk'], ['machine', 'rm', 'laptop'], ['machine', 'use', 'laptop'],
    ['disp', 'set', 'btop', 'seen'], ['uninstall', 'add', 'btop'], ['uninstall', 'rm', 'btop'],
    ['uninstall', 'clear'], ['glue', 'discard', 'rustup'], ['picks', 'add', 'jq'], ['picks', 'rm', 'btop'], ['picks', 'to-primary'],
    ['location', '--all'], ['versions', 'btop'], ['versions', 'btop', '--refresh'],
    ['pin', 'set', 'btop', 'native'], ['pin', 'unset', 'fzf'], ['pin', 'promote', 'fzf'],
    ['config', 'set', 'splash', 'plain'], ['config', 'unset', 'splash'], ['config', 'move', 'splash'],
    ['theme', 'set', 'accent', '#ff0000'], ['theme', 'unset', 'accent'], ['theme', 'save', 'mytheme'],
    ['plugin', 'sync'], ['plugin', 'bless', 'codeplug'], ['plugin', 'unbless'], ['plugin', 'add', 'github:nobody/none'],
    ['plugin', 'remove', 'codeplug'], ['plugin', 'update'], ['plugin', 'update', 'codeplug', '--ref', 'v1', '--pin'],
    ['plugin', 'trust', '--all'], ['plugin', 'untrust', 'codeplug'], ['plugin', 'lock', 'codeplug'],
    ['plugin', 'diff', 'codeplug', '--to', 'v1'], ['plugin', 'init', 'configsys-me'],
    ['plugin', 'set-source', 'srcplug', 'github:me/codeplug'], ['plugin', 'push'], ['plugin', 'undo', '--yes'],
    ['report', 'btop', '--yes'], ['request', 'btop', '--yes'], ['request-os', '--yes'],
    ['orphans', '--ignore', 'nano'],
    ['dotfiles', 'capture', 'bash', '--yes'], ['dotfiles', 'capture', 'btop', '--force', '--yes'],
    ['dotfiles', 'activate', 'rustup'], ['dotfiles', 'discard', 'rustup'],
    ['glue', 'add', 'other', '--shell', 'bash'], ['glue', 'override', 'fzf', '--shell', 'bash'],
    ['manpages', 'install'], ['refresh'],
]


def test_every_mutating_verb_writes_nothing_under_pretend(sandbox, monkeypatch, capsys):
    home, dry = sandbox
    real_run = subprocess.run

    def no_gh(cmd, *a, **kw):                       # a dry run must never file anything upstream
        assert not (isinstance(cmd, list) and cmd and cmd[0] == 'gh'), 'gh called under --pretend'
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(subprocess, 'run', no_gh)
    monkeypatch.setattr(shutil, 'which', lambda n, *a, _w=shutil.which, **k: '/usr/bin/gh' if n == 'gh' else _w(n, *a, **k))
    wrote = {}
    before = _snapshot(home)
    for args in VERBS:
        main(dry + args)
        after = _snapshot(home)
        ch = _changes(before, after)
        if ch:
            wrote[' '.join(args)] = ch
        before = after
    capsys.readouterr()
    assert wrote == {}


# -- TUI-only write paths ------------------------------------------------------

def _pretend_ctx(home):
    from configsys.app import Context, build_parser
    args = build_parser().parse_args(['--home', str(home), '--os', 'pop_os!:22.04', '-q', '--pretend', 'inspect'])
    ctx = Context(args)
    ctx.runner.echo = lambda *a, **k: None
    return ctx


def test_tui_dotfiles_glue_and_caches_write_nothing_under_pretend(sandbox, capsys):
    from configsys import versionreport
    from configsys.drivers import get_driver
    home, _dry = sandbox
    ctx = _pretend_ctx(home)
    before = _snapshot(home)
    _drv, units = actions.dotfiles_units(ctx)
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    btop = next(u for u in units if u.comp == 'btop-dotfiles')
    assert df.capture(btop, force=True) == []                       # TUI Dotfiles `m` (manage)
    assert df.relocate(btop, home / 'elsewhere') == []              # TUI Dotfiles move-store
    glue = get_driver('glue', ctx.runner, ctx.paths)
    assert glue.add_user_glue('x', 'bash', 'echo hi') == (None, None)   # shellguard.activate's writer
    path, created = glue.new_user_snippet('y', 'bash')
    assert not created and not path.exists()
    versionreport.report(ctx, 'btop', refresh=True)                  # `versions`, the TUI where box
    capsys.readouterr()
    assert _changes(before, _snapshot(home)) == []
