'''shells.py — one row per shell configsys wires glue into (review-2026-11-2 D4).

Everything the glue driver, the shell-writes guard and the TUI know about a shell comes from its
ShellSpec, so adding a shell is one row here (plus its loader code when its `mode` is new):

  name          the shell id (`glue` variants live at glue/shell/<name>/, CONFIGSYS_GLUE_SHELLS uses it)
  ext           a snippet's file extension
  confd         the conf.d dir its loader sources (uniform ~/.config/<shell>/conf.d)
  rc            the rc file a loader block goes in, or None when the shell sources conf.d natively
  mode          'native' (sources conf.d itself — fish), 'rc-block' (a marker block in the rc that
                sources the dir — bash, zsh) or 'inline' (the block INLINES every snippet — elvish and
                nushell can't source a dir into the interactive scope; drivers/glue.py explains)
  component     the component that installs the shell (managed-install detection)
  guarded       rc files an installer may scribble in — the shell-writes guard snapshots them
  guarded_dirs  dirs the shell sources every file of, where installers drop their own file
'''

from collections import namedtuple

ShellSpec = namedtuple('ShellSpec', 'name ext confd rc mode component guarded guarded_dirs')

SHELLS = {s.name: s for s in (
    ShellSpec('bash', 'sh', '~/.config/bash/conf.d', '~/.bashrc', 'rc-block', 'bash',
              ('.bashrc', '.bash_profile', '.bash_login', '.profile'), ()),
    ShellSpec('zsh', 'zsh', '~/.config/zsh/conf.d', '~/.zshrc', 'rc-block', 'zsh',
              ('.zshrc', '.zprofile', '.zshenv', '.zlogin'), ()),
    ShellSpec('fish', 'fish', '~/.config/fish/conf.d', None, 'native', 'fish',
              ('.config/fish/config.fish',), ('.config/fish/conf.d',)),
    ShellSpec('nu', 'nu', '~/.config/nushell/conf.d', '~/.config/nushell/config.nu', 'inline', 'nushell',
              ('.config/nushell/config.nu', '.config/nushell/env.nu'), ()),
    ShellSpec('elvish', 'elv', '~/.config/elvish/conf.d', '~/.config/elvish/rc.elv', 'inline', 'elvish',
              ('.config/elvish/rc.elv',), ()),
)}
