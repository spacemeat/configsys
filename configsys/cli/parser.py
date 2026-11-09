'''cli/parser.py — the argparse tree (`configsys … --help`), its epilog and `--version`.

This is also the source of the configsys(1) man page: tools/gen_manpages.py builds NAME from the
first sentence of the top-level description, DESCRIPTION from all of it, OPTIONS from the global
flags' help, COMMANDS from each command's `description=` (its `help=` when it has none) plus the
names of its subcommands, and EXAMPLES / ENVIRONMENT from the `examples:` and `environment:`
blocks of `_EPILOG`. So every command carries a one-line `help=` (the `--help` listing) and a
`description=` written for a newcomer (its own `--help` page and the man page); a command with
subcommands names them in its description, because the man page shows only their names. Keep the
first sentence of the top-level description free of other periods. Regenerate the page with
`python3 tools/gen_manpages.py` after editing (test/test_manpages.py fails on a stale one).

Split out of app.py (review-2026-11-2 D2); the handlers live in the sibling cli/ modules.
'''

import argparse
from pathlib import Path
from .settings import _SHOW_TARGETS


_EPILOG = '''\
examples:
  configsys                            open the interactive TUI (the default)
  configsys --machine laptop           open the TUI on the `laptop` machine's picks, to curate them
  configsys inspect                    install state of this machine's picks, plus any issues
  configsys search terminal            find components whose name or description says "terminal"
  configsys picks add ripgrep          track ripgrep: add it to this machine's picks
  configsys install --picks            install every pick of this machine that isn't installed yet
  configsys install rust ripgrep       install components now (dependencies pulled in and ordered)
  configsys install profile:finders    install every component in the `finders` profile
  configsys upgrade profile:finders btop
                                       upgrade a profile's components plus one more, to latest
  configsys updates                    list System Updates (pending updates outside configsys)
  configsys upgrade --system           preview, confirm, then run each package manager's bulk upgrade
  configsys where neovim               explain how a component resolves on this machine
  configsys location vulkan-sdk        print its absolute install dir (for shell snippets)
  configsys pin set steam flatpak      choose an install method (a local pin)
  configsys pin promote steam          make that pin portable via your primary plugin
  configsys glue add aliases           write your own shell startup snippet in $EDITOR
  configsys check                      lint your whole merged config
  configsys show routes                print the shipped routes.hu (--path prints its location)
  configsys --pretend install steam    dry run: print the commands instead of running them

environment:
  CONFIGSYS_OS                         route as this OS block[:version] instead of the detected OS
                                       (--os)
  CONFIGSYS_OS_VERSION                 use this OS version instead of the detected one
  CONFIGSYS_ARCH                       CPU arch for `$ARCH` and `cpu:` conditions (default: detected)
  CONFIGSYS_HOME                       stand-in for $HOME on every configsys path (--home also
                                       gives the commands it runs that HOME)
  CONFIGSYS_CONFIG                     your user config file (--config)
  CONFIGSYS_STATE_DIR                  holds your user config, the ledger, caches and synced plugins
                                       (default ~/.config/configsys, or $XDG_CONFIG_HOME/configsys
                                       when CONFIGSYS_HOME is unset)
  CONFIGSYS_REPO                       data root holding the shipped routes.hu and config.hu
  CONFIGSYS_USERSCOPE_DIR              base dir for user-scope installs (default ~)
  CONFIGSYS_SYSTEMSCOPE_DIR            base dir for system-scope installs (default /opt)
  CONFIGSYS_APP_DIR, CONFIGSYS_SDK_DIR, CONFIGSYS_SRC_DIR
                                       app / SDK / source-tree dirs under that base (default apps,
                                       sdks, src); these five override the `dirs:` setting
  CONFIGSYS_COLOR                      TUI color cap, same values as --color (NO_COLOR forces none;
                                       an explicit --color / --nocolor wins over both)
  CONFIGSYS_EFFECTS                    TUI motion: full, reduced or none (--effects)
  CONFIGSYS_SPLASH                     always = show the startup splash even on a fast load;
                                       linger = also hold it until a key (--splash-linger)
  CONFIGSYS_NO_SPLASH                  set to anything to turn the startup splash off
  CONFIGSYS_GLUE_SHELLS                comma-separated shells to set up glue for (default: the
                                       installed ones)
  CONFIGSYS_PM                         apt or dnf: the package manager the gcc, clang and
                                       gcc-toolset drivers use (default: this OS's)
  CONFIGSYS_GITHUB_TOKEN               GitHub API token: lifts the API rate limit for version checks
                                       (GITHUB_TOKEN also works)
  CONFIGSYS_GIT_TOKEN                  token for cloning private github: / gitlab: plugin repos
'''


def _version_string():
    '''`configsys <version> (<short commit>)` — the commit when it runs from a git clone (the usual
    clone-first install), for an issue someone files by hand (G6).'''
    from .. import __version__
    import subprocess
    try:
        sha = subprocess.run(['git', '-C', str(Path(__file__).resolve().parent.parent), 'rev-parse',
                              '--short', 'HEAD'], capture_output=True, text=True, timeout=5,
                             stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ''
    return f'configsys {__version__}' + (f' ({sha})' if sha else '')


class _VersionAction(argparse.Action):
    '''`--version`, worked out only when asked (the git lookup isn't paid on every command).'''
    def __call__(self, parser, namespace, values, option_string=None):
        print(_version_string())
        parser.exit()


def build_parser():
    p = argparse.ArgumentParser(
        prog='configsys',
        description="Install and manage the software on each of your machines from one config.\n"
                    "Each machine installs its own picks (the components listed for it in the "
                    "`picks:` section\nof your config) through this OS's package manager (apt, "
                    'dnf, pacman, zypper, apk, xbps) or\nthe AUR, Homebrew, flatpak, snap, '
                    'AppImages, tarballs, source builds, language toolchains\nand more. Profiles '
                    'are read-only lists to browse and pick from. With no command, the\n'
                    'interactive TUI opens. `configsys <command> --help` shows a command\'s '
                    'options; configsys.hu(5)\ndescribes the config file.',
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action=_VersionAction, nargs=0,
                   help='print the configsys version (and the git commit it runs from) and exit')
    p.add_argument('--pretend', action='store_true',
                   help='dry run: print the commands an operation would run instead of running them, '
                        'and change no file (no config edit, state, cache or plugin)')
    p.add_argument('--os', metavar='BLOCK[:VERSION]',
                   help='route as this OS block, and optionally release, instead of the detected OS '
                        '(e.g. ubuntu:24.04, fedora:44, arch); without a version, every versioned '
                        'condition (`ubuntu >= 24.04`) reads false, and an unknown block is an '
                        'error. Same as CONFIGSYS_OS')
    p.add_argument('--home', metavar='DIR',
                   help='sandbox: use DIR in place of $HOME for every path configsys reads or writes '
                        '(config, state, user-scope installs) and as HOME for the commands it runs, '
                        'ignoring any inherited CONFIGSYS_STATE_DIR, CONFIGSYS_CONFIG and XDG_* dirs. '
                        'System packages still install for real unless you add --pretend')
    p.add_argument('--machine', metavar='NAME',
                   help="work on machine NAME's picks for this run instead of this box's `machine:` "
                        'setting, to view or curate another machine from here. Nothing installs '
                        "another machine's picks here: `--picks` refuses and the TUI's Components "
                        'screen is read-only')
    p.add_argument('--config', metavar='FILE',
                   help='your user config file (default ~/.config/configsys/configsys.hu, created '
                        'from a template when first needed); same as CONFIGSYS_CONFIG')
    p.add_argument('--color', choices=['auto', '24bit', '256', '16', '8', 'none'], default=None,
                   help='cap the TUI color depth (default auto: detect it). Lower values only clamp '
                        'down, 24bit forces direct RGB even without COLORTERM, 16 uses the theme\'s '
                        '`colors-basic` ANSI set and 8 only the base eight. An explicit --color wins '
                        'over NO_COLOR (which otherwise forces none) and CONFIGSYS_COLOR (the same '
                        'values)')
    p.add_argument('--nocolor', '--no-color', dest='nocolor', action='store_true',
                   help='monochrome TUI, the same as --color none: no colors or gradient, and only the '
                        'plain built-in startup progress bar; reverse video and bold still mark the '
                        'cursor and headers')
    p.add_argument('--effects', choices=['full', 'reduced', 'none'], default=None,
                   help='TUI motion: full (background gradient + any splash), reduced (no gradient, a '
                        'calmer splash), none (no gradient, only the plain built-in progress bar). '
                        'Overrides the `effects:` setting; unset picks reduced over SSH, else full')
    p.add_argument('--probe', action='store_true',
                   help='print the TUI color mode and motion level this terminal gets, and why, then '
                        'exit (honors --color, --nocolor and --effects)')
    p.add_argument('--splash-linger', action='store_true',
                   help='always show the startup splash, even on a fast load, and keep it animating '
                        'until you press a key; same as CONFIGSYS_SPLASH=linger')
    p.add_argument('-v', '--verbose', action='count', default=0,
                   help='print load detail to stderr: -v adds the layer stack, route overrides and '
                        "per-unit state; -vv adds each component's winning binding and why (errors and "
                        'progress always show)')
    p.add_argument('-q', '--silent', action='store_true',
                   help='print nothing to the console while loading, not even errors (they still '
                        "appear on the TUI `!` page and in `inspect`'s issue list)")

    sub = p.add_subparsers(dest='command')
    sub.add_parser('inspect', help="show the install state of this machine's picks (status, installed "
                                   'and latest versions) and any issues',
                   description="Show the install state of this machine's picks without changing "
                               'anything. Each unit (a component bound to the driver that installs '
                               'it, `driver\\component`) gets its status (installed, outdated, missing, '
                               'locked, …), installed and latest versions, and any install of it '
                               'through another method ("also present"); then the issues the TUI\'s '
                               '`!` page lists. With --machine, the picks are that machine\'s.')

    # each op's description carries extra notes (rebuild semantics + the dependency flags, swaps,
    # picks, stranded removal, locks) — the generated man page shows each command's description.
    _rebuild_note = (' A named component already present is not skipped: a package manager re-runs (a '
                     'no-op when current), and a `via: source` component rebuilds from a clean checkout, '
                     'so re-running it picks up a recipe change even at the same version. Its '
                     'dependencies are installed only when missing (--with-deps re-runs them all; '
                     '--no-deps skips them). When the component is already installed through a method '
                     'other than its default, that install is the one acted on; when a pin now names a '
                     'different method, the old install is removed first, then the new one installs '
                     '(a swap). The OS package index is refreshed once first when the plan reads it '
                     '(the `refresh-before-execute` setting). --force lets a dotfiles install overwrite '
                     'an on-system file that was never captured (it is backed up to .pre-configsys '
                     'first), and lets a tarball, font or AppImage replace a directory or file '
                     'configsys did not install. A source component builds only in a checkout '
                     'configsys created, or one you adopted with `install --adopt`.')
    _op_notes = {
        'install': (_rebuild_note + ' Installing does not add a component to this machine\'s picks; '
                    '`configsys picks add` does that. --picks installs every pick of this box that '
                    'is not installed (with any names given), after showing the plan and asking '
                    '(--yes skips the question); picks with no install method here are skipped '
                    'with a notice.'),
        'upgrade': (_rebuild_note + ' Upgrading a locked component is refused until you `configsys '
                    'unlock` it. --picks upgrades every outdated pick of this box (with any names '
                    'given; locked picks are left alone), after showing the plan and asking (--yes '
                    'skips the question). --system upgrades the whole machine instead and takes no '
                    'names; see `configsys updates`.'),
        'remove': (' Glue that only the removed components needed goes with them; their dependencies '
                   'and dotfiles stay. Removing a locked component releases its hold, and a removed '
                   'component leaves this machine\'s uninstall queue. A component with no install '
                   'method left on this OS is still removed when a stranded install of it remains, '
                   'through the method that made it. Removing does not unpick a component; '
                   '`configsys picks rm` does that.'),
        'lock': (' The hold is the package manager\'s own where it has one (apt-mark hold, dnf '
                 'versionlock, …), else a record in configsys\' ledger; managers that cannot hold a '
                 'version, such as pacman and apk, decline. A locked component is skipped by '
                 '`upgrade --picks` and refused by `upgrade`; `set-version` moves it and holds it '
                 'again.'),
        'unlock': ' The component can then be upgraded again.',
    }
    for name, help_ in (('install', 'install components, with any dependencies they are missing'),
                        ('remove', 'uninstall components'),
                        ('upgrade', 'upgrade components to their latest version, or the whole system '
                                    'with --system'),
                        ('lock', 'hold components at their installed version'),
                        ('unlock', 'release the version hold on components')):
        desc = (f'{help_.capitalize()}. A name is a component; '
                'profile:<name> expands to that profile\'s components (members with no install '
                'method here are skipped with a notice, while a name you give yourself that '
                'cannot install here is an error).')
        desc += _op_notes.get(name, '')
        sp = sub.add_parser(name, help=help_, description=desc)
        # upgrade takes NO names with --system (the whole-machine lane), and install/upgrade take
        # none with --picks, so those allow zero (cmd_install/cmd_upgrade insist otherwise).
        sp.add_argument('names', nargs=('*' if name in ('install', 'upgrade') else '+'),
                        help='component names, and/or profile:<name> to expand a whole profile')
        if name in ('install', 'upgrade'):
            sp.add_argument('--force', action='store_true',
                            help='let a dotfiles install overwrite an on-system file that was never '
                                 'captured (backed up to .pre-configsys; `configsys dotfiles capture` '
                                 'first is usually better), a tarball/font/AppImage replace a dir or '
                                 'file configsys didn\'t install, and a source build discard local '
                                 'changes in a checkout configsys made')
            if name == 'install':
                sp.add_argument('--adopt', action='store_true',
                                help='let a source component build in an existing checkout configsys '
                                     "didn't create (fetch + checkout only: your files are never "
                                     'cleaned, and remove never deletes it)')
            deps = sp.add_mutually_exclusive_group()     # opposite asks: neither may silently win
            deps.add_argument('--no-deps', action='store_true',
                              help='act on only the named components, without installing their '
                                   'missing dependencies. A source component always rebuilds, so '
                                   'this rebuilds just it (e.g. to pick up a recipe change)')
            deps.add_argument('--with-deps', action='store_true',
                              help='also re-run every dependency, present or not (by default '
                                   'only missing dependencies are installed)')
            sp.add_argument('--picks', action='store_true',
                            help=("also act on every pick of this box that is not installed: show "
                                  'the plan and ask first (on this box only, so not with --machine '
                                  'naming another machine)') if name == 'install' else
                                 ('also act on every outdated pick of this box (locked ones are left '
                                  'alone): show the plan and ask first (on this box only, so not with '
                                  '--machine naming another machine)'))
        if name == 'install':
            sp.add_argument('--yes', action='store_true',
                            help='with --picks: skip the confirmation prompt (without it, a run that '
                                 'is not on a terminal stops)')
        if name == 'upgrade':
            sp.add_argument('--system', action='store_true',
                            help='upgrade the whole system: refresh the package index, preview the '
                                 'System Updates list, confirm, then run each package manager\'s own '
                                 "bulk upgrade (this OS's manager, flatpak, snap), which also updates "
                                 'anything else it manages; held packages stay held. Within-release '
                                 'only; see `configsys updates`')
            sp.add_argument('--yes', action='store_true',
                            help='with --system or --picks: skip the confirmation prompt (without it, '
                                 'a run that is not on a terminal stops)')

    fs = sub.add_parser('fix-scope', help='move installs whose scope (user / system) differs from the '
                                          'configured scope, so they match the config (the config is '
                                          'not changed)',
                        description='Find installs whose actual scope differs from the scope your '
                                    'config declares for them (the `scope` setting, or a binding\'s '
                                    'own `scope:`) — user (under your home) or system (/opt, with '
                                    'sudo) — list each move, and after you confirm, reinstall each at '
                                    'the declared scope and remove the old one. Your config is never '
                                    'changed. Only drivers that can install either way are '
                                    'considered.')
    fs.add_argument('names', nargs='*', help='component names (default: every mismatched install)')
    fs.add_argument('-y', '--yes', action='store_true',
                    help='skip the confirmation prompt (without it, a run that is not on a terminal '
                         'stops)')

    sv = sub.add_parser('set-version', help='install a specific version of a component, where its '
                                            'install method can target one',
                        description='Install a specific version of a component through its install '
                                    'method here, and its missing dependencies. Refused up front when '
                                    'that method installs only the version its route names (tarball, '
                                    'AppImage, font, native-pkg-file, aur, rpm-ostree, the gcc / '
                                    'clang alternatives, gcc-toolset, glue, dotfiles, service, group); '
                                    '`configsys versions <name>` shows what each method offers. A '
                                    'locked component is released, moved and held again at the new '
                                    'version.')
    sv.add_argument('name', help='component name')
    sv.add_argument('version', help='version to install (for flatpak, a commit id)')

    p_machine = sub.add_parser('machine', help='list, add, remove or switch machines (the columns '
                                               'of `picks:`)',
                               description='Manage machines: each machine is a column of the '
                                           '`picks:` matrix (the components it installs), and the '
                                           '`machine:` setting says which one this box is (default '
                                           '`this-machine`). Subcommands: list (the default), show, '
                                           'add, rm, use.')
    mpsub = p_machine.add_subparsers(dest='machine_command')
    mpsub.add_parser('list', help='list machines and how many components each tracks, marking which '
                                  'one this box is (default)',
                     description='List every machine (every key of `picks:`) with how many components '
                                 'it tracks; * marks the one this box is.')
    mps = mpsub.add_parser('show', help="show one machine's picks",
                           description="Show one machine's picks, and whether it is this box.")
    mps.add_argument('name', help='machine name')
    for _n, _h, _d in (('add', 'add a machine (a new, empty picks column)',
                        'Add a machine: a new, empty column in `picks:`, kept in your primary plugin '
                        'when you have one, else in your top config.'),
                       ('rm', 'remove a machine and its picks (from your top config and your primary '
                              'plugin)',
                        'Remove a machine and its picks from both your top config and your primary '
                        'plugin. The machine this box is set to is refused unless --force.')):
        _sp = mpsub.add_parser(_n, help=_h, description=_d)
        _sp.add_argument('name', help='machine name')
        if _n == 'rm':
            _sp.add_argument('--force', action='store_true',
                             help='remove the machine this box is set to as well (also clears '
                                  '`machine:`)')
    mpu = mpsub.add_parser('use', help="set which machine this box is (the `machine:` setting); no "
                                       'name clears it',
                           description='Set which machine this box is: the `machine:` setting, kept '
                                       'in your top config. With no name, clear it, so this box is '
                                       '`this-machine` again.')
    mpu.add_argument('name', nargs='?', help='machine name (omit to clear)')

    dp = sub.add_parser('disp', help='view or set dispositions: your seen / interesting triage marks on '
                                     'catalog components (they never install anything)',
                        description='View or set dispositions: your triage marks on catalog '
                                    'components — seen or interesting — so new ones stand out. '
                                    'Components you have not marked are NEW. Dispositions are kept '
                                    'per machine (your top config) and never install anything. '
                                    'Subcommands: list (the default), get, set.')
    dpsub = dp.add_subparsers(dest='disp_command')
    dpl = dpsub.add_parser('list', help='list your seen / interesting components and how many are NEW '
                                        '(not yet triaged) (default)',
                           description='List the components you marked interesting or seen, and how '
                                       'many are still NEW (not triaged).')
    dpl.add_argument('--new', action='store_true', help='list every NEW component instead')
    dpg = dpsub.add_parser('get', help="print a component's disposition",
                           description="Print a component's disposition: seen, interesting or new — "
                                       'or that one of your own profiles includes it, or that it is '
                                       'staged for removal.')
    dpg.add_argument('name', help='component name')
    dps = dpsub.add_parser('set', help="set a component's disposition (kept per machine)",
                           description="Set a component's disposition, in your top config (or "
                                       'wherever your dispositions already live). `new` clears it.')
    dps.add_argument('name', help='component name')
    dps.add_argument('state', choices=['seen', 'interesting', 'new'], help="'new' clears it")

    pk = sub.add_parser('picks', help="list or edit a machine's picks: the components it installs "
                                      '(also editable in the TUI Profiles screen)',
                        description="List or edit a machine's picks: the components that machine "
                                    'installs. Editing picks installs or removes nothing by itself '
                                    '(`configsys install --picks` installs the missing ones). Picks '
                                    'live in your primary plugin when you have one, so they travel '
                                    'to your other machines; else in your top config. Subcommands: '
                                    'list (the default), add, rm, to-primary.')
    pksub = pk.add_subparsers(dest='picks_command')
    pkl = pksub.add_parser('list', help="list a machine's picks (default)",
                           description="List a machine's picks (default: this box's, or the global "
                                       '--machine).')
    # SUPPRESS: unset here must not clobber the global --machine (same dest) with None
    pkl.add_argument('--machine', metavar='NAME', default=argparse.SUPPRESS,
                     help="which machine (default: this box's)")
    for _n, _h, _d in (('add', "track a component: add it to a machine's picks (kept in your primary "
                               'plugin when you have one)',
                        "Track a component: add it to a machine's picks — or every member of a "
                        'profile, with profile:<name>. It lands in your primary plugin when you have '
                        "one, unless that machine's picks already live in your top config. A name "
                        'no loaded layer defines is still written, with a warning.'),
                       ('rm', "untrack a component: remove it from a machine's picks (it is not "
                              'uninstalled)',
                        "Untrack a component (or every member of profile:<name>): remove it from a "
                        "machine's picks. It is not uninstalled; `configsys remove` does that.")):
        _sp = pksub.add_parser(_n, help=_h, description=_d)
        _sp.add_argument('component', help='component name, or profile:<name> for each of its members')
        _sp.add_argument('--machine', action='append', dest='machines', metavar='NAME',
                         help="target machine (repeat for several; default: this box's, or the "
                              'global --machine)')
    pksub.add_parser('to-primary', help="move this box's local picks into the primary plugin so they "
                                        'travel to your other machines (dispositions stay local)',
                     description="Move the picks in this box's top config into your primary plugin, "
                                 'so they travel to your other machines. Dispositions stay local.')

    srch = sub.add_parser('search', help='find components in the catalog by name, description or '
                                        'attrs (e.g. `search terminal`, `search --attr TUI git`)',
                          description='Search the catalog — every component the loaded layers define '
                                      '— by words, each of which must appear (ignoring case) in the '
                                      'name or description, and by attrs. A + marks the components '
                                      'picked on this machine. Exits 1 when nothing matches.')
    srch.add_argument('text', nargs='*', help='words that must each appear in the name or description')
    srch.add_argument('--attr', action='append', default=[], metavar='ATTR',
                      help='only components carrying this attr, e.g. TUI, GUI, FOSS (repeatable; '
                           'see docs/component-attrs.md)')
    srch.add_argument('--json', action='store_true', help='machine-readable output')
    wh = sub.add_parser('where', help='explain a component: the layer that defines it, each install '
                                      'method (marking the default, the alternatives you can pin, and '
                                      "any that can't be used here, with why), the rule that chose "
                                      'the default, and what it resolves to on this machine',
                        description='Explain how a component resolves on this machine: the layer '
                                    'that defines it, what it provides and requires, any pin, every '
                                    'binding (marking the default, the alternatives you can pin, and '
                                    'why each of the others is not a candidate here), the rule that '
                                    'chose the default, and the units it resolves to here. With -p, '
                                    'explain a profile instead.')
    wh.add_argument('name', help='component name (or a profile name with -p)')
    wh.add_argument('-p', '--profile', action='store_true',
                    help='treat NAME as a profile: show its definition in each layer, how the layers '
                         'relate, and its member / declined counts')

    lo = sub.add_parser('location', help="print a component's absolute install location as it "
                                         'resolves here (honoring scope, pins and `locations:`), for '
                                         'shell snippets',
                        description="Print a component's absolute install location as it resolves "
                                    'on this machine (honoring scope, pins and the `locations:` '
                                    'setting), for shell snippets such as `export '
                                    'VULKAN_SDK=$(configsys location vulkan-sdk)`. A component a '
                                    'package manager puts on the system PATH has no managed location: '
                                    'nothing is printed and it still exits 0. A component that does '
                                    'not resolve here exits 1.')
    lo.add_argument('name', nargs='?', help='component name')
    lo.add_argument('--all', action='store_true', dest='all',
                    help='print `<component>\\t<path>` for every picked component with a managed '
                         'install location, and refresh the cache the shell glue reads')

    ve = sub.add_parser('versions', help='show the version each install method would install for a '
                                         'component (native vs tarball/source/…), and which lag the '
                                         'newest',
                        description='For each install method of a component that works here, show '
                                    'the version it would install (the native package vs a tarball, '
                                    'a source build, …), which one is the default or pinned, what is '
                                    'installed, and which lag the newest. Answers come from a cache '
                                    '(--refresh re-queries). Read-only.')
    ve.add_argument('name', help='component name')
    ve.add_argument('--min', dest='min_version', metavar='VERSION',
                    help='mark which methods meet this minimum version (and how to pin one)')
    ve.add_argument('--refresh', action='store_true',
                    help='bypass the cache and re-query each method now')

    sub.add_parser('check', help='lint the merged config (repo, plugins, your config and its '
                                 'includes) without installing anything',
                   description='Lint the whole merged config — the shipped routes.hu and config.hu, '
                               'your plugins and primary plugin, your top config, and everything they '
                               'include — without installing or probing anything: unknown keys and '
                               'drivers, ambiguous bindings, settings a layer may not set, profiles '
                               'naming unknown components, key rebinds, theme mistakes and more. '
                               'Exits 1 when it finds an error (warnings alone exit 0).')

    pn = sub.add_parser('pin', help='view or change install-method / provider pins '
                                    '(local, or portable via a primary plugin)',
                        description='View or change pins. A binding-pin chooses the install method '
                                    'for a component (`pin set steam flatpak`); a provider-pin '
                                    'chooses which component satisfies a capability. A pin is a '
                                    'filter, not a hint: one that cannot be met here is an error. '
                                    'New pins go in your top config (this machine only); `pin '
                                    'promote` moves one into your primary plugin so it travels. '
                                    'Subcommands: list (the default), set, unset, promote.')
    pnsub = pn.add_subparsers(dest='pin_command')
    pnsub.add_parser('list', help='list the effective pins and where each came from (default)',
                     description='List the effective pins and the layer each came from (local, your '
                                 'primary plugin, or the repo).')
    ps = pnsub.add_parser('set', help='pin a component to an install method (or a capability to a '
                                      "provider component) in your top config; the next install "
                                      'swaps out an install made by another method',
                          description='Pin a component to an install method (a via the component '
                                      'has a binding for), or a capability to the component that '
                                      'should provide it, in your top config. When the component '
                                      'is installed through another method, the next install '
                                      'removes that one and installs through the pinned method (a '
                                      'swap).')
    ps.add_argument('component', help='component (or capability) name')
    ps.add_argument('via', help='a via/driver (binding-pin), or a provider component (provider-pin)')
    pnu = pnsub.add_parser('unset', help='remove a pin (from your top config, else your primary '
                                         'plugin)',
                           description='Remove a pin from your top config — or, when only your '
                                       'primary plugin has it, from there — so the default method '
                                       'applies again.')
    pnu.add_argument('component', help='component (or capability) name')
    pnp = pnsub.add_parser('promote', help='move a top-config pin into your primary plugin '
                                           '(portable to your other machines)',
                           description='Move a pin from your top config into your primary plugin, '
                                       'so it travels to your other machines.')
    pnp.add_argument('component', help='component (or capability) name')

    p_profile = sub.add_parser('profile', help='browse profiles: read-only component lists from the '
                                               'repo, your plugins and your own config (installs come '
                                               'from picks)',
                               description='Browse profiles: named, read-only lists of components '
                                           'from the repo, your plugins and your own config. A '
                                           'profile never installs anything — you pick from it (`'
                                           'configsys picks add`), or name profile:<name> on an '
                                           'install. Subcommands: list (the default), show.')
    prsub = p_profile.add_subparsers(dest='profile_command')
    prsub.add_parser('list', help='list every profile and its components (default)',
                     description='List every profile and the components it expands to.')
    prs = prsub.add_parser('show', help="show one profile's terms, where it is defined, and what it "
                                        'expands to',
                           description="Show one profile: the layer that defines it, its terms "
                                       '(components and +included profiles), and the components it '
                                       'expands to.')
    prs.add_argument('profile', help='profile name')

    cfp = sub.add_parser('config', help='view or edit machine settings (`config show` lists them all)',
                         description='View or edit machine settings (scope, driver-preference, '
                                     'splash, dirs.*, …). A uniform setting (the same on every '
                                     'machine) is written to your primary plugin when you have one; a '
                                     'machine-local one to your top config; a setting that already '
                                     'lives in one of them is edited there. Subcommands: show (the '
                                     'default), get, set, unset, move.')
    cfsub = cfp.add_subparsers(dest='config_command')
    cfsub.add_parser('show', help='list every setting `config set` can change: its value, where it is '
                                  'set, and what it does (default)',
                     description='List every setting `config set` can change: its value, where it is '
                                 'set (or where an edit would land), and what it does. Picks, pins, '
                                 'dispositions and the uninstall queue have their own commands.')
    cfg_get = cfsub.add_parser('get', help="print one setting's effective value",
                               description="Print one setting's effective value.")
    cfg_get.add_argument('key', help='setting name (see `config show`)')
    cfg_set = cfsub.add_parser('set', help='set a machine setting where it already lives, else in your '
                                           "primary plugin (uniform settings) or your top config "
                                           '(machine-local ones)',
                               description='Set a machine setting where it already lives, else in your '
                                           'primary plugin (uniform settings) or your top config '
                                           '(machine-local ones). A value outside the setting\'s '
                                           'choices is refused.')
    cfg_set.add_argument('key', help='setting name (see `config show`)')
    cfg_set.add_argument('value', nargs='+', help='the value (list settings take several tokens)')
    cfg_set.add_argument('--local', action='store_true',
                         help="write to this machine's top config, not the primary plugin")
    cfg_unset = cfsub.add_parser('unset', help='clear a machine setting where it is set',
                                 description='Clear a machine setting where it is set, so the built-in '
                                             'default applies — unless the other layer (top config or '
                                             'primary plugin) also sets it, which configsys then '
                                             'tells you.')
    cfg_unset.add_argument('key', help='setting name (see `config show`)')
    cfg_unset.add_argument('--local', action='store_true',
                           help="write to this machine's top config, not the primary plugin")
    cfg_move = cfsub.add_parser('move', help='move a setting between local (top config) and the '
                                             'primary plugin, carrying its value',
                                description='Move a setting between your top config (this machine '
                                            'only) and your primary plugin (every machine), carrying '
                                            'its value.')
    cfg_move.add_argument('key', help='setting name (see `config show`)')

    thp = sub.add_parser('theme', help='view or edit the TUI theme; save/load shareable themes',
                         description='View or edit the TUI theme: colors, per-page role styles and '
                                     'background gradients. Edits go to your primary plugin when you '
                                     'have one (else your top config), or with --local to your top '
                                     'config. A theme plugin is a saved, shareable theme. Subcommands: '
                                     'show (the default), list, set, unset, save, load.')
    thsub = thp.add_subparsers(dest='theme_command')
    thsub.add_parser('show', help='show the theme overrides currently in effect (default)',
                     description='Show the theme overrides in effect, merged across your layers.')
    thsub.add_parser('list', help='list the theme plugins on disk',
                     description='List the synced or saved plugins that carry a theme.')
    th_set = thsub.add_parser('set', help='set a theme value, e.g. theme set colors.accent "#c88cf0"',
                              description='Set one theme value by its dotted key, e.g. `configsys '
                                          'theme set colors.accent "#c88cf0"`. A key or value the TUI '
                                          'would ignore is refused.')
    th_set.add_argument('key', help='colors.<name> | colors-basic.<name> | '
                                    'pages.<page>.<role>.<fg|bg|bold|underline|reverse> | '
                                    'pages.<page>.gradient.<from|to|enabled>  '
                                    '(fg/bg = a color-map name or #rrggbb)')
    th_set.add_argument('value', help='a color (#rrggbb or a color-map name), or true / false for '
                                      'bold, underline, reverse and enabled')
    th_set.add_argument('--local', action='store_true',
                        help="write to this machine's top config, not the primary plugin")
    th_unset = thsub.add_parser('unset', help='remove a theme value',
                                description='Remove one theme value, so the layer below (or the '
                                            'built-in theme) shows through.')
    th_unset.add_argument('key', help='the dotted key, as for `theme set`')
    th_unset.add_argument('--local', action='store_true',
                          help="write to this machine's top config, not the primary plugin")
    th_save = thsub.add_parser('save', help='snapshot your theme into a shareable theme plugin',
                               description='Snapshot your current theme into a theme-only plugin in '
                                           'the plugins dir, to share as its own git repo.')
    th_save.add_argument('name', help='theme plugin name')
    th_save.add_argument('--force', action='store_true',
                         help='overwrite an existing theme plugin of that name')
    th_load = thsub.add_parser('load', help='apply a saved theme plugin under your own theme '
                                            'overrides (--reset replaces them)',
                               description='Apply a theme plugin: its theme goes under your own '
                                           'overrides, which stay on top (--reset replaces them '
                                           'with the pack).')
    th_load.add_argument('name', help='theme plugin name (see `theme list`)')
    th_load.add_argument('--reset', action='store_true',
                         help='replace your theme overrides with the pack instead of keeping them on top')
    th_load.add_argument('--local', action='store_true',
                         help="write to this machine's top config, not the primary plugin")

    pl = sub.add_parser('plugin', help='manage plugins: declare and sync them, bless or init your '
                                       'primary plugin, trust plugins that run code',
                        description='Manage plugins: git repos (or local dirs) that add components, '
                                    'OS blocks, profiles, drivers or splash screens. Declare and '
                                    'sync them (add, sync, update, remove, set-source), review a '
                                    'change before taking it (diff), trust the ones that run code or '
                                    'commands (trust, untrust), hold one where it is (lock, unlock), '
                                    'and manage your primary plugin — your personal layer that '
                                    'travels between machines (bless, unbless, init, push, log, '
                                    'undo). Subcommands: list (the default), sync, bless, unbless, '
                                    'add, remove, update, trust, untrust, lock, unlock, diff, push, '
                                    'log, undo, init, set-source.')
    plsub = pl.add_subparsers(dest='plugin_command')
    pll = plsub.add_parser('list', help='list declared plugins with their sync, ABI and trust status '
                                        '(default)',
                           description='List every declared plugin (including those other plugins '
                                       'declare) with its source and ref, sync, ABI, checksum, '
                                       'trust and lock status, what it provides, and, for your '
                                       'primary, how far it is ahead of or behind its remote.')
    pll.add_argument('--fetch', action='store_true',
                     help="fetch your primary's remote first, so it counts the changes your other "
                          'machines pushed (otherwise: as of the last fetch or sync)')
    plsub.add_parser('sync', help='clone or fetch every declared plugin at its `ref:`',
                     description='Clone or fetch every declared plugin (and the plugins they '
                                 'declare) at its `ref:`, then say how this machine\'s installable '
                                 'set changed. A locked plugin is left alone, and a copy with local '
                                 'changes is never overwritten.')
    pb = plsub.add_parser('bless', help='designate your primary personal-config plugin '
                                        '(register + sync it; its machine settings then apply)',
                          description='Make a plugin your primary plugin: sync it, declare it if it '
                                      'isn\'t yet, and mark it primary (clearing any other). Its '
                                      'machine settings then apply here. `bless none` clears it.')
    pb.add_argument('source', help='<provider>:<user>/<name> (or a declared plugin name), or '
                                   '"none" to clear')
    plsub.add_parser('unbless', help='clear the primary designation',
                     description='Clear the primary designation; the plugin stays declared as an '
                                 'ordinary plugin.')
    pa = plsub.add_parser('add', help='sync a plugin and declare it (nothing is declared if the sync '
                                      'fails)',
                          description='Sync a plugin, then declare it: in your primary plugin when you '
                                      'have one (so it travels), else in your top config. Nothing is '
                                      'declared if the sync fails.')
    pa.add_argument('source', help='github:owner/repo | gitlab:owner/repo | git URL | local path')
    pa.add_argument('--ref', help='use this tag / commit / branch (saved as the plugin\'s `ref:`)')
    pa.add_argument('--pin', action='store_true',
                    help='also record the synced content\'s sha256; content that later differs is '
                         'quarantined')
    pa.add_argument('--local', action='store_true',
                    help='add to this machine\'s top config even if a primary plugin is set, so it '
                         'applies only here, e.g. a project checkout (default: a new plugin rides the '
                         'primary, portable to all machines)')
    pa.add_argument('--replace', action='store_true',
                    help='if a plugin of the same name is already declared from another source, '
                         'drop that one and use this source instead (a copy holding unpushed or '
                         'uncommitted work is kept as <name>.replaced-<date>; a primary stays primary)')
    p_plugin_remove = plsub.add_parser('remove', help='undeclare a plugin and delete its synced copy '
                                                      '(refused while the copy holds unpushed or '
                                                      'uncommitted work)',
                                       description='Undeclare a plugin and delete its synced copy. '
                                                   'Refused while that copy holds work found nowhere '
                                                   'else — uncommitted edits, unpushed commits, '
                                                   'stashes, no remote — unless --force.')
    p_plugin_remove.add_argument('name', help='plugin name, source, or dir')
    p_plugin_remove.add_argument('--force', action='store_true',
                                 help='delete the synced copy even if it holds work found nowhere else')
    pu = plsub.add_parser('update',
                          help="re-sync a plugin, or all of them (--ref / --latest move its `ref:`)",
                          description='Re-sync one plugin, or every declared plugin. --ref or '
                                      '--latest moves its `ref:` first; the declaration changes only '
                                      'once the new ref syncs. Your primary plugin follows its '
                                      'branch, so --latest just re-syncs it. Locked plugins are '
                                      'refused (one) or skipped (all).')
    pu.add_argument('name', nargs='?',
                    help='plugin name, source, or dir; omit it to update every declared plugin')
    pu.add_argument('--all', action='store_true', dest='all',
                    help="update every declared plugin (the same as omitting the name)")
    pu.add_argument('--ref', help='move the plugin\'s `ref:` to this tag / commit / branch')
    pu.add_argument('--latest', action='store_true',
                    help="move `ref:` to the newest version tag on the remote (or main/master if it "
                         'has none)')
    pu.add_argument('--pin', action='store_true',
                    help='re-record the sha256 of the newly synced content')
    pt = plsub.add_parser('trust', help="approve a plugin's current content (its code and the data "
                                        'that runs commands) so it can run',
                          description="Approve a plugin's exact current content (pinned by hash) so "
                                      'configsys may run it: its code, and data that runs commands or '
                                      'writes outside a package manager — downloads, builds, '
                                      'scripts, glue, dotfiles, package-repo setup, facet probes, '
                                      'keybindings. Until then only its plain package names are used. '
                                      'Content that changes later needs trusting again. With no name '
                                      '(or --all), every plugin that needs it is listed with what '
                                      'it ships, and trusted once you say yes; off a terminal that '
                                      'takes --all --yes.')
    pt.add_argument('name', nargs='?', help='plugin name, source, or dir (omit, or use --all, to '
                                            'trust every plugin that needs it)')
    pt.add_argument('--all', action='store_true',
                    help='trust every plugin that is currently untrusted or changed since trusted '
                         '(lists them and asks first)')
    pt.add_argument('--yes', action='store_true',
                    help="with --all: trust them without asking (what a script needs)")
    p_plugin_untrust = plsub.add_parser('untrust', help="revoke a plugin's trust",
                                        description="Revoke a plugin's trust: its code and "
                                                    'command-carrying data stop running.')
    p_plugin_untrust.add_argument('name', help='plugin name, source, or dir')
    plk = plsub.add_parser('lock', help='hold a plugin where it is on this machine: sync leaves it '
                                        'alone and update, bless and trust refuse it (its synced copy '
                                        'still loads)',
                           description='Hold a plugin where it is on this machine: sync leaves it '
                                       'alone, and update, bless and trust refuse it until you '
                                       'unlock it. Its synced copy, if any, still loads.')
    plk.add_argument('name', help='plugin name, source, or dir')
    pulk = plsub.add_parser('unlock', help="lift a plugin's lock",
                            description="Lift a plugin's lock, so sync, update, bless and trust "
                                        'act on it again.')
    pulk.add_argument('name', help='plugin name, source, or dir')
    pdf = plsub.add_parser('diff', help='review what a plugin would change before you take it: a '
                                        'synced plugin against its newest remote ref; an unsynced one '
                                        'between its ref and the newest (or everything a sync would '
                                        'download), fetched into a cache that is never loaded',
                           description='Review what a plugin would change before you take it, as a '
                                       'diff: a synced plugin\'s copy against its newest remote ref; '
                                       'an unsynced one between its declared ref and the newest (or '
                                       'everything a sync would download), fetched into a cache that '
                                       'is never loaded or run.')
    pdf.add_argument('name', help='plugin name, source, or dir')
    pdf.add_argument('--to', metavar='REF',
                     help='compare against this ref instead of the newest version tag (or main/master)')
    ppu = plsub.add_parser('push', help='publish your primary plugin: combine what this machine '
                                        'committed with what your other machines pushed (asking about '
                                        'anything both changed), and push to its branch',
                           description='Publish your primary plugin. configsys commits each of its own '
                                       'edits there as you work; push combines those (and your hand '
                                       'edits, if you say so) with what your other machines pushed — '
                                       'asking about anything both changed, or stopping with your '
                                       'work intact — and pushes to its branch. The `primary-push` '
                                       'setting can make this automatic.')
    ppu.add_argument('--include-edits', action='store_true',
                     help='also commit and push edits you made by hand, without asking')
    ppu.add_argument('-y', '--yes', action='store_true',
                     help='push without listing the outgoing changes and asking first')
    plg = plsub.add_parser('log', help="your primary plugin's recent commits: what each changed, which "
                                       "configsys made, which aren't pushed yet",
                           description="List your primary plugin's recent commits, newest first: what "
                                       'each changed, which configsys made (*), and which are not '
                                       'pushed yet (↑).')
    plg.add_argument('-n', type=int, default=10, metavar='N', help='how many commits (default 10)')
    p_plugin_undo = plsub.add_parser('undo', help='take back the newest change configsys committed to '
                                                  'your primary (dropped if never pushed, else reverted)',
                                     description='Take back the newest change configsys committed to '
                                                 'your primary plugin: dropped if it was never pushed, '
                                                 'else reverted by a new commit (so undo twice is a '
                                                 'redo). Refused over your uncommitted edits to the '
                                                 'same files.')
    p_plugin_undo.add_argument('-y', '--yes', action='store_true',
                               help='undo without showing it and asking first')
    p_plugin_init = plsub.add_parser('init', help='create your primary plugin from local content '
                                                  "(captured dotfiles, your own glue, your config's "
                                                  'profiles and components), or merge that into your '
                                                  'existing primary',
                                     description='Create your primary plugin from what lives only on '
                                                 'this machine: your captured dotfiles and your own '
                                                 'glue are moved into it, your config\'s `profiles:` '
                                                 'and `components:` are moved there, and your other '
                                                 'plugins are declared in its manifest; it is then '
                                                 'git-initialized and blessed. With a primary already '
                                                 'blessed, move the dotfiles and glue into it '
                                                 'instead. Then set its source and push it to share '
                                                 'it.')
    p_plugin_init.add_argument('name', nargs='?', help='plugin name (default: configsys-<user>)')
    p_plugin_init.add_argument('--force', action='store_true',
                               help='overwrite dotfiles and glue already in the plugin')
    p_plugin_init.add_argument('--dry-run', action='store_true',
                               help='show the plan and exit; write nothing')
    pss = plsub.add_parser('set-source', help='swap a plugin\'s source (e.g. local path -> '
                                              'github:you/name after you push it)',
                           description='Change a declared plugin\'s source (e.g. a local path -> '
                                       'github:you/name once you have pushed it), keeping its ref '
                                       'and primary mark, and point its synced copy\'s git origin at '
                                       'the new source.')
    pss.add_argument('name', help='declared plugin name')
    pss.add_argument('source', help='new source: github:owner/repo | gitlab:owner/repo | git URL | '
                                    'local path')

    rp = sub.add_parser('report', help='assemble an install-failure report (OS + route + driver '
                                       'output) and file it upstream — you approve the full text first',
                        description='Assemble an install-failure report — this OS, the route and the '
                                    "driver's output, with secrets and your home path scrubbed — and "
                                    'file it in the configsys issue tracker (with `gh` when you have '
                                    'it, else as a prefilled link). You see the full text and approve '
                                    'it first; nothing is sent otherwise.')
    rp.add_argument('name', nargs='?', help='component to report (default: every saved failure a '
                                            'later run has not cleared)')
    rp.add_argument('--yes', action='store_true',
                    help='file without asking (the full text is still printed first)')
    rp.add_argument('--print', dest='print_only', action='store_true',
                    help='print the report and exit; never send')

    rq = sub.add_parser('request', help='ask upstream to support a component on more platforms — '
                                        'shows a coverage matrix of where it installs today; you '
                                        'approve before filing',
                        description='Ask upstream to support a component on more platforms: builds a '
                                    'coverage matrix of where it installs today and files it in the '
                                    'configsys issue tracker once you approve the full text.')
    rq.add_argument('name', help='component to request full support for')
    rq.add_argument('--yes', action='store_true',
                    help='file without asking (the full text is still printed first)')
    rq.add_argument('--print', dest='print_only', action='store_true',
                    help='print the request and exit; never send')

    rqo = sub.add_parser('request-os', help='suggest THIS OS for inclusion, or report that a system '
                                            'update broke it — captures os-release; you approve before filing',
                         description='Suggest this OS for inclusion, or report that a system update '
                                     'changed or broke it: captures /etc/os-release and how configsys '
                                     'maps it today (OS block and package manager), and files it in '
                                     'the configsys issue tracker once you approve the full text.')
    rqo.add_argument('--yes', action='store_true',
                     help='file without asking (the full text is still printed first)')
    rqo.add_argument('--print', dest='print_only', action='store_true',
                     help='print the OS request and exit; never send')

    orp = sub.add_parser('orphans', help="list installed software this machine's picks don't account "
                                         'for; adopt (track), remove or ignore it',
                         description="List installed software this machine's picks don't account "
                                     'for, grouped by driver: known orphans (a component describes '
                                     'them) and foreign ones (no component does). Then adopt one '
                                     '(--adopt: track it in picks), remove it (--remove), or quiet '
                                     'it (--ignore). By default only what you installed yourself is '
                                     'listed, OS-base packages are hidden, and foreign orphans come '
                                     'only from flatpak and snap.')
    orp.add_argument('--driver', help='only this driver (apt, flatpak, …)')
    orp.add_argument('--foreign', action='store_true',
                     help='also list packages no component describes from the other managers '
                          '(apt, pip, cargo, …; noisy, off by default)')
    orp.add_argument('--include-auto', action='store_true', dest='include_auto',
                     help='include auto-installed dependency packages (default: only ones you chose)')
    orp.add_argument('--system', action='store_true',
                     help='also list OS-base foreign packages (apt priority required/important/'
                          'standard; default hides them)')
    orp.add_argument('--all', action='store_true', help='include orphans silenced by orphans-ignore')
    orp.add_argument('--json', action='store_true', help='machine-readable output')
    orp.add_argument('--adopt', metavar='NAME',
                     help='adopt a known orphan (a component): track it in picks: on the target '
                          'machine(s) so it becomes managed')
    orp.add_argument('--machine', action='append', dest='machines', metavar='NAME',
                     help="machine to adopt onto (repeat for several; default: this box's)")
    orp.add_argument('--remove', metavar='NAME',
                     help='uninstall a known orphan (a component) through configsys (asks first '
                          'unless --yes)')
    orp.add_argument('--ignore', metavar='PATTERN', nargs='+',
                     help='silence orphans matching these name/key globs (adds to orphans-ignore)')
    orp.add_argument('--unignore', metavar='PATTERN', nargs='+',
                     help='list these again: remove each exact entry from orphans-ignore (a glob is '
                          'removed by naming the glob itself)')
    orp.add_argument('--yes', action='store_true', help='skip the confirmation for --remove')

    dfp = sub.add_parser('dotfiles', help='show and capture your dotfiles; review glue the '
                                          'shell-writes guard staged',
                         description='Dotfiles are your apps\' own config files, kept in your content '
                                     'store (your primary plugin, else ~/.config/configsys/dotfiles) '
                                     'and linked into place. Show their state (status), adopt the '
                                     'ones already on this machine (capture), and review the shell '
                                     'startup lines the shell-writes guard took back from an '
                                     'installer (staged, activate, discard — also under `configsys '
                                     'glue`). Subcommands: status (the default), capture, staged, '
                                     'activate, discard.')
    dfsub = dfp.add_subparsers(dest='dotfiles_command')
    dfsub.add_parser('status', help="show every dotfiles target for this machine's picks: config "
                                    '(managed / unmanaged / no config) and glue (active / changed / '
                                    'available / inactive) (default)',
                     description="Show every dotfiles target for this machine's picks: config "
                                 '(managed, unmanaged — needs a capture or a link — or no config), '
                                 'glue (active, changed, available, inactive), and your own user '
                                 'glue snippets.')
    cap = dfsub.add_parser('capture', help='adopt existing on-system dotfiles into your content '
                                           'store (read-only on the system side)',
                           description='Copy config files already on this machine into your content '
                                       'store, so configsys manages them from then on (a later '
                                       'install links your copy into place). It only reads the files '
                                       'on the system; it shows the plan and asks first.')
    cap.add_argument('names', nargs='*', help="limit to these components — `btop` or `btop-dotfiles` "
                                              "(default: every one in this machine's picks)")
    cap.add_argument('--force', action='store_true', help='overwrite content already in the store')
    cap.add_argument('--dry-run', action='store_true', help='show the plan and exit; write nothing')
    cap.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    dfsub.add_parser('staged', help='list inactive glue candidates the shell-writes guard captured '
                                    '(installers that tried to edit your rc files)',
                     description='List the shell startup lines an installer tried to add to your rc '
                                 'files, which the shell-writes guard took back and holds, inactive, '
                                 'on this machine.')
    act = dfsub.add_parser('activate', help='promote a staged glue candidate to your own user glue '
                                            '(a user.d snippet, linked into ~/.config/<shell>/conf.d/ '
                                            'as 90-<name>)',
                           description='Turn a staged glue candidate into your own user glue: a '
                                       'user.d snippet (in your primary plugin unless --local), '
                                       'linked into ~/.config/<shell>/conf.d/ as 90-<name>.')
    act.add_argument('names', nargs='+', help='component(s) whose staged glue to activate')
    act.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set "
                          '(default: the primary, so it travels to your other machines)')
    disc = dfsub.add_parser('discard', help='delete a staged glue candidate without activating it',
                            description='Delete a staged glue candidate without activating it.')
    disc.add_argument('names', nargs='+', help='component(s) whose staged glue to drop')

    glp = sub.add_parser('glue', help='add your own shell-startup snippets (aliases / env / functions), '
                                      "or override a component's shipped glue; kept in your primary "
                                      'plugin when you have one',
                         description='Glue is the small shipped shell snippets that wire tools into '
                                     'your shells, linked into each shell\'s ~/.config/<shell>/conf.d/. '
                                     'Write your own startup snippets (add), fork a component\'s '
                                     'shipped glue to edit it (override), and review the startup '
                                     'lines the shell-writes guard took back from an installer '
                                     '(staged, activate, discard). Yours are kept in your primary '
                                     'plugin when you have one (--local keeps them on this machine). '
                                     'Subcommands: add, override, staged, activate, discard.')
    glsub = glp.add_subparsers(dest='glue_command')
    gla = glsub.add_parser('add', help='create your own startup snippet and open it in $EDITOR '
                                       '(linked into ~/.config/<shell>/conf.d/, loads after component glue)',
                           description='Create your own shell startup snippet (or open an existing '
                                       'one) in $EDITOR, and link it into ~/.config/<shell>/conf.d/, '
                                       'where it loads after component glue. It loads on your next '
                                       'shell session.')
    gla.add_argument('name', help='snippet name (a .<ext> suffix is optional)')
    gla.add_argument('--shell', help='which shell (default: your $SHELL, else bash)')
    gla.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set "
                          '(default: the primary, so it travels to your other machines)')
    glo = glsub.add_parser('override', help="copy a component's shipped glue into your layer and edit "
                                            'it (yours then shadows the shipped one; `check` flags '
                                            'when the shipped one changes)',
                           description="Copy a component's shipped glue into your own layer, open it "
                                       'in $EDITOR, and relink it: your copy then replaces the '
                                       'shipped one, and `configsys check` tells you when the shipped '
                                       'one changes.')
    glo.add_argument('comp', help='component (tool or its -glue companion) whose glue to override')
    glo.add_argument('--shell', help='only this shell (default: every installed shell it ships)')
    glo.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set")
    # the shell-writes guard's staged blocks are glue — here too (`dotfiles staged|activate|discard`
    # stay as aliases; review-2026-11-2 G4)
    glsub.add_parser('staged', help='list inactive glue candidates the shell-writes guard captured',
                     description='List the shell startup lines an installer tried to add to your rc '
                                 'files, which the shell-writes guard took back and holds, inactive, '
                                 'on this machine.')
    gact = glsub.add_parser('activate', help='promote a staged candidate to your own user glue (90-<name>)',
                            description='Turn a staged glue candidate into your own user glue: a '
                                        'user.d snippet (in your primary plugin unless --local), '
                                        'linked into ~/.config/<shell>/conf.d/ as 90-<name>.')
    gact.add_argument('names', nargs='+', help='component(s) whose staged glue to activate')
    gact.add_argument('--local', action='store_true',
                      help="write to this machine's store even if a primary plugin is set")
    gdis = glsub.add_parser('discard', help='delete a staged glue candidate without activating it',
                            description='Delete a staged glue candidate without activating it.')
    gdis.add_argument('names', nargs='+', help='component(s) whose staged glue to drop')

    unp = sub.add_parser('uninstall', help="this machine's uninstall queue — removals staged (TUI "
                                          '`x`) to run when you execute in the TUI',
                         description="Manage this machine's uninstall queue: removals you staged "
                                     '(the TUI\'s `x`), kept in your top config until they run. They '
                                     'run when you execute in the TUI (`X`); `configsys remove <name>` '
                                     'removes one now and takes it off the queue, and `configsys '
                                     "remove 'profile:!uninstall'` removes them all. Subcommands: list "
                                     '(the default), add, rm, clear.')
    unsub = unp.add_subparsers(dest='uninstall_command')
    unsub.add_parser('list', help='show what is staged for removal (default)',
                     description='Show the components staged for removal.')
    for verb, what, desc in (('add', 'stage component(s) for removal',
                              'Stage components for removal; nothing is removed yet.'),
                             ('rm', 'unstage component(s)',
                              'Take components off the uninstall queue.')):
        u = unsub.add_parser(verb, help=what, description=desc)
        u.add_argument('names', nargs='+', help='component name(s)')
    unsub.add_parser('clear', help='unstage everything', description='Empty the uninstall queue.')

    p_manpages = sub.add_parser('manpages', help='install or check the man pages '
                                                 '(configsys(1) + configsys.hu(5))',
                                description='Install the configsys(1) and configsys.hu(5) man pages '
                                            'into a man directory, or check that the installed '
                                            'copies are present and current. Subcommands: status '
                                            '(the default), install.')
    p_manpages_sub = p_manpages.add_subparsers(dest='manpages_command')
    for mname, mhelp in (('install', 'copy the man pages into a man directory (default: '
                                     '~/.local/share/man)'),
                         ('status', 'report whether the installed pages are present and current '
                                    '(default)')):
        msp = p_manpages_sub.add_parser(mname, help=mhelp, description=mhelp[:1].upper() + mhelp[1:] + '.')
        msp.add_argument('--prefix', metavar='DIR',
                         help='man-dir prefix; pages go under <prefix>/share/man (default: ~/.local)')

    sub.add_parser('updates', help="list System Updates: pending updates from this OS's package "
                                   "manager, flatpak and snap for packages that aren't configsys "
                                   'components, grouped by tier; apply with `upgrade --system`',
                   description="List System Updates: everything this OS's package manager, flatpak "
                               'and snap report upgradable that is not one of your components, '
                               'grouped by manager and tier (kernel, core, standard, apps), with '
                               'held packages marked. Read-only: `configsys upgrade --system` '
                               'applies them. Run `configsys refresh` first if the package index '
                               'may be stale.')

    sub.add_parser('refresh', help="re-check upstream versions for this machine's picks and refresh the "
                                   "package index of this OS's package manager (sudo may prompt). On "
                                   'Arch, where only a full upgrade is safe, it asks before running '
                                   '`pacman -Syu` instead',
                   description="Re-check upstream versions for this machine's picks and their "
                               "dependencies, re-probe facets, and refresh this OS's package index "
                               '(apt-get update and the like; sudo may prompt). Fixed version pins '
                               'that name a `latest-check:` are compared against upstream (advice '
                               'only). If the index refresh fails, configsys explains why and can '
                               're-fetch a rotated signing key for a source it manages; it also '
                               'offers to remove sources it added for components you no longer use. '
                               'On Arch, where only a full upgrade is safe, it asks before running '
                               '`pacman -Syu` instead. Exits 1 when the index refresh fails.')
    sh = sub.add_parser('show', help='print the shipped routes.hu or config.hu, or its path',
                        description='Print a shipped base file — routes (routes.hu: the components '
                                    'and OS blocks) or config (config.hu: the shipped profiles and '
                                    'default keybindings) — or with --path just where it is. With '
                                    'no name, list them.')
    sh.add_argument('what', nargs='?', choices=list(_SHOW_TARGETS),
                    help='which base file to show (omit to list them)')
    sh.add_argument('--path', action='store_true',
                    help="print the file's resolved location instead of its contents")

    sub.add_parser('keys', help='show the effective TUI keybindings (the merged `keys:` section)',
                   description='Show the effective TUI keybindings — the `keys:` section merged '
                               'across every layer — with the layer each binding comes from, and any '
                               'key a higher layer took from a lower one.')
    sub.add_parser('tui', help='open the interactive TUI (the default; prints `inspect` output when '
                               'not on a terminal)',
                   description='Open the interactive TUI, the same as running configsys with no '
                               'command. When stdin or stdout is not a terminal, it prints '
                               '`configsys inspect` output instead.')
    return p
