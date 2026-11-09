'''parity.py — the CLI ⇄ TUI parity table (review-2026-11-2 D9 / parity-11).

Every CLI verb (`build_parser()`'s subcommands, two levels) and every TUI screen action
(`tui.keyspec.KNOWN_ACTIONS`, outside the navigation `global` scope) is CLASSIFIED here: where its
counterpart lives, or why it has none. `test/test_parity.py` walks both vocabularies and fails on an
unclassified entry — so a new verb or key can't ship without a parity decision (the way
test_driver_inventory, test_pretend_sweep `VERBS` and test_primary_journal `WRITES` hold their own
inventories).

Values: `('<screen>', '<action>')` — the TUI counterpart (for TUI_ACTIONS: the CLI verb string);
`'cli-only: <why>'` / `'tui-only: <why>'` — deliberately on one surface; `'tui-gap: <finding>'` — a
known gap still open.
'''

CLI_VERBS = {
    'inspect': ('components', '(the tree itself)'),
    'install': ('components', 'op-install'),
    'remove': ('components', 'op-remove'),
    'upgrade': ('components', 'op-upgrade'),
    'lock': ('components', 'lock'),
    'unlock': ('components', 'lock'),
    'fix-scope': ('components', 'method'),                 # the `v` picker's "fix scope" row
    'set-version': ('components', 'method'),               # the `v` picker's "pin to a version" row
    'machine list': ('profiles', 'machine-target'),
    'machine show': ('profiles', 'comp-machines'),
    'machine add': ('profiles', 'machine-target'),
    'machine rm': ('profiles', 'machine-target'),
    'machine use': ('profiles', 'machine-target'),
    'disp list': ('profiles', 'disp-interesting'),
    'disp get': ('profiles', 'disp-interesting'),
    'disp set': ('profiles', 'disp-interesting'),
    'picks list': ('profiles', 'track-one'),
    'picks add': ('profiles', 'track-one'),
    'picks rm': ('profiles', 'track-one'),
    'picks to-primary': ('plugins', 'picks-to-primary'),
    'search': ('global', 'find'),                       # `/` find (+ `f` attr filter on Profiles)
    'where': ('components', 'where'),
    'location': ('components', 'where'),
    'versions': ('components', 'method'),                  # the picker lists each method's version
    'check': ('global', 'issues'),                         # its lints reach `!` (G2)
    'pin list': ('components', 'method'),
    'pin set': ('components', 'method'),
    'pin unset': ('components', 'method'),                 # "auto — unpin"
    'pin promote': ('components', 'method'),              # the picker's "promote the pin" row
    'profile list': ('profiles', '(the profile tree)'),
    'profile show': ('profiles', '(the profile tree)'),
    'config show': ('config', '(the settings list)'),
    'config get': ('config', '(the settings list)'),
    'config set': ('global', 'confirm'),                # Enter on a Config row
    'config unset': ('global', 'confirm'),
    'config move': ('config', 'move'),
    'theme show': ('theme', '(the editor)'),
    'theme list': ('theme', 'load'),
    'theme set': ('theme', 'edit-bg'),
    'theme unset': ('theme', 'reset'),
    'theme save': ('theme', 'save'),
    'theme load': ('theme', 'load'),
    'plugin list': ('plugins', '(the plugin table)'),
    'plugin sync': ('plugins', 'sync'),
    'plugin bless': ('plugins', 'bless'),
    'plugin unbless': ('plugins', 'unbless'),
    'plugin add': ('plugins', 'add'),
    'plugin remove': ('plugins', 'remove'),
    'plugin update': ('plugins', 'update'),
    'plugin trust': ('plugins', 'trust'),
    'plugin untrust': ('plugins', 'trust'),
    'plugin lock': ('plugins', 'lock'),
    'plugin unlock': ('plugins', 'lock'),
    'plugin diff': ('plugins', '(the diff pane)'),
    'plugin push': ('plugins', 'push'),
    'plugin log': ('plugins', 'history'),
    'plugin undo': ('plugins', 'history'),
    'plugin init': ('plugins', 'init-primary'),
    'plugin set-source': ('plugins', 'set-source'),
    'report': ('issues', 'report'),                       # the `!` page files the same body
    'request': ('issues', 'request'),
    'request-os': ('issues', 'suggest-os'),
    'orphans': ('profiles', 'orphan-ignore'),
    'dotfiles status': ('dotfiles', '(the dotfiles table)'),
    'dotfiles capture': ('dotfiles', 'manage'),
    'dotfiles staged': ('glue', 'staged'),
    'dotfiles activate': ('glue', 'staged'),
    'dotfiles discard': ('glue', 'staged'),
    'glue add': ('glue', 'new-snippet'),
    'glue override': ('glue', 'override'),
    'glue staged': ('glue', 'staged'),
    'glue activate': ('glue', 'staged'),
    'glue discard': ('glue', 'staged'),
    'uninstall list': ('profiles', 'stage-uninstall'),
    'uninstall add': ('profiles', 'stage-uninstall'),
    'uninstall rm': ('profiles', 'stage-uninstall'),
    'uninstall clear': ('components', 'clear'),
    'manpages install': 'cli-only: installs man pages for the shell, not a TUI concern',
    'manpages status': 'cli-only: man pages are for the shell',
    'updates': ('components', '(the System Updates group)'),
    'refresh': ('components', 'refresh'),
    'show': 'cli-only: prints a shipped data file (routes.hu / config.hu) for a pip/pipx install',
    'keys': 'tui-only-view: the `?` page lists every binding',
    'tui': ('global', '(the TUI)'),
}

TUI_ACTIONS = {
    ('components', 'clear'): 'uninstall clear',
    ('components', 'execute'): 'install',
    ('components', 'expand-all'): 'tui-only: tree view',
    ('components', 'lock'): 'lock',
    ('components', 'method'): 'pin set',
    ('components', 'mode'): 'tui-only: tree view mode',
    ('components', 'op-install'): 'install',
    ('components', 'op-install-all'): 'install',        # install --picks
    ('components', 'op-remove'): 'remove',
    ('components', 'op-upgrade'): 'upgrade',
    ('components', 'op-upgrade-all'): 'upgrade',        # upgrade --picks
    ('components', 'refresh'): 'refresh',
    ('components', 'select-all'): 'tui-only: selection',
    ('components', 'where'): 'where',
    ('config', 'move'): 'config move',
    ('issues', 'report'): 'report',
    ('issues', 'request'): 'request',
    ('issues', 'suggest-os'): 'request-os',
    ('config', 'theme'): 'tui-only: switches to the Theme screen',
    ('dotfiles', 'manage'): 'dotfiles capture',
    ('dotfiles', 'manage-all'): 'dotfiles capture',
    ('dotfiles', 'move-store'): 'tui-gap: dotfiles-glue (a CLI `dotfiles move` verb)',
    ('dotfiles', 'move-store-all'): 'tui-gap: dotfiles-glue (a CLI `dotfiles move` verb)',
    ('dotfiles', 'unmanage'): 'remove',                 # remove <comp>-dotfiles
    ('dotfiles', 'unmanage-all'): 'remove',
    ('glue', 'activate'): 'install',                    # install <comp>-glue
    ('glue', 'activate-group'): 'install',
    ('glue', 'deactivate'): 'remove',
    ('glue', 'new-snippet'): 'glue add',
    ('glue', 'override'): 'glue override',
    ('glue', 'staged'): 'glue staged',
    ('plugins', 'add'): 'plugin add',
    ('plugins', 'bless'): 'plugin bless',
    ('plugins', 'history'): 'plugin log',
    ('plugins', 'init-primary'): 'plugin init',
    ('plugins', 'lock'): 'plugin lock',
    ('plugins', 'picks-to-primary'): 'picks to-primary',
    ('plugins', 'push'): 'plugin push',
    ('plugins', 'remove'): 'plugin remove',
    ('plugins', 'set-ref'): 'plugin update',            # update --ref
    ('plugins', 'set-source'): 'plugin set-source',
    ('plugins', 'sync'): 'plugin sync',
    ('plugins', 'sync-all'): 'plugin sync',
    ('plugins', 'trust'): 'plugin trust',
    ('plugins', 'trust-all'): 'plugin trust',           # trust --all
    ('plugins', 'unbless'): 'plugin unbless',
    ('plugins', 'update'): 'plugin update',
    ('plugins', 'update-all'): 'plugin update',
    ('profiles', 'attr-filter'): 'search',              # search --attr
    ('profiles', 'claim'): 'picks add',
    ('profiles', 'comp-machines'): 'machine show',
    ('profiles', 'disp-interesting'): 'disp set',
    ('profiles', 'disp-interesting-all'): 'disp set',
    ('profiles', 'disp-seen'): 'disp set',
    ('profiles', 'disp-seen-all'): 'disp set',
    ('profiles', 'machine-target'): 'machine use',
    ('profiles', 'mark-all-seen'): 'disp set',
    ('profiles', 'method'): 'pin set',
    ('profiles', 'orphan-ignore'): 'orphans',           # orphans --ignore / --unignore
    ('profiles', 'select-all'): 'tui-only: selection',
    ('profiles', 'stage-uninstall'): 'uninstall add',
    ('profiles', 'toggle-install'): 'tui-only: the install-state overlay',
    ('profiles', 'track-all'): 'picks add',
    ('profiles', 'track-one'): 'picks add',
    ('profiles', 'where'): 'where',
    ('theme', 'copy-page'): 'tui-only: interactive theme editing (CLI: theme set per key)',
    ('theme', 'edit-bg'): 'theme set',
    ('theme', 'effect-bold'): 'theme set',
    ('theme', 'effect-reverse'): 'theme set',
    ('theme', 'effect-underline'): 'theme set',
    ('theme', 'gradient-toggle'): 'theme set',
    ('theme', 'load'): 'theme load',
    ('theme', 'new'): 'theme save',
    ('theme', 'reset'): 'theme unset',
    ('theme', 'save'): 'theme save',
}
for _n in range(1, 8):
    TUI_ACTIONS[('theme', f'page-{_n}')] = 'tui-only: theme editor page switch'
