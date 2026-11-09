'''shells.py — one row per shell configsys wires glue into (review-2026-11-2 D4).

Everything the glue driver, the shell-writes guard and the TUI know about a shell comes from its
ShellSpec, so adding a shell is one row here (plus its loader code when its `mode` is new):

  name          the shell id (`glue` variants live at glue/shell/<name>/, CONFIGSYS_GLUE_SHELLS uses it)
  ext           a snippet's file extension
  confd         the conf.d dir its loader sources (<config>/<shell>/conf.d — `~/.config` for bash and
                zsh, whose dir is configsys's own choice; `$XDG_CONFIG_HOME` for the shells that read
                their own config there: fish, nushell, elvish)
  rc            the rc file a loader block goes in, or None when the shell sources conf.d natively
  mode          'native' (sources conf.d itself — fish), 'rc-block' (a marker block in the rc that
                sources the dir — bash, zsh) or 'inline' (the block INLINES every snippet — elvish and
                nushell can't source a dir into the interactive scope; drivers/glue.py explains)
  component     the component that installs the shell (managed-install detection)
  guarded       rc files an installer may scribble in — the shell-writes guard snapshots them
  guarded_dirs  dirs the shell sources every file of, where installers drop their own file

A path is `~/…`, `$XDG_CONFIG_HOME/…` (default <home>/.config) or relative to the home; `expand`
makes one absolute.
'''

from collections import namedtuple
from pathlib import Path

ShellSpec = namedtuple('ShellSpec', 'name ext confd rc mode component guarded guarded_dirs')

_XDG = '$XDG_CONFIG_HOME'

SHELLS = {s.name: s for s in (
    ShellSpec('bash', 'sh', '~/.config/bash/conf.d', '~/.bashrc', 'rc-block', 'bash',
              ('.bashrc', '.bash_profile', '.bash_login', '.profile'), ()),
    ShellSpec('zsh', 'zsh', '~/.config/zsh/conf.d', '~/.zshrc', 'rc-block', 'zsh',
              ('.zshrc', '.zprofile', '.zshenv', '.zlogin'), ()),
    ShellSpec('fish', 'fish', f'{_XDG}/fish/conf.d', None, 'native', 'fish',
              (f'{_XDG}/fish/config.fish',), (f'{_XDG}/fish/conf.d',)),
    ShellSpec('nu', 'nu', f'{_XDG}/nushell/conf.d', f'{_XDG}/nushell/config.nu', 'inline', 'nushell',
              (f'{_XDG}/nushell/config.nu', f'{_XDG}/nushell/env.nu'), ()),
    ShellSpec('elvish', 'elv', f'{_XDG}/elvish/conf.d', f'{_XDG}/elvish/rc.elv', 'inline', 'elvish',
              (f'{_XDG}/elvish/rc.elv',), ()),
)}


def expand(path, home, env=None):
    '''A ShellSpec path made absolute against `home`: `$XDG_CONFIG_HOME/…` (from `env`, default
    <home>/.config), `~/…`, or home-relative.'''
    home = Path(home)
    if path == _XDG or path.startswith(_XDG + '/'):
        base = (env or {}).get('XDG_CONFIG_HOME') or str(home / '.config')
        return Path(base) / path[len(_XDG) + 1:] if path != _XDG else Path(base)
    if path == '~':
        return home
    if path.startswith('~/'):
        return home / path[2:]
    return home / path
