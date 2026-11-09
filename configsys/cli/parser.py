'''cli/parser.py — the argparse tree (`configsys … --help`, the man page source), its epilog and `--version`.

Split out of app.py (review-2026-11-2 D2).
'''

import argparse
from pathlib import Path
from .settings import _SHOW_TARGETS


_EPILOG = '''\
examples:
  configsys                            open the interactive TUI (the default)
  configsys --machine laptop           open the TUI on the `laptop` machine's picks, to curate them
  configsys inspect                    install state of this machine's picks, plus any issues
  configsys picks add ripgrep          track ripgrep: add it to this machine's picks
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
  configsys show routes                print the shipped routes.hu (--path prints its location)
  configsys --pretend install steam    dry run: print the commands instead of running them

environment:
  CONFIGSYS_OS, CONFIGSYS_OS_VERSION   use this OS block[:version] / version instead of the detected one (--os)
  CONFIGSYS_ARCH                       CPU arch for `$ARCH` and `cpu:` conditions (default: detected)
  CONFIGSYS_HOME                       stand-in for $HOME on every configsys path (--home)
  CONFIGSYS_CONFIG                     your user config file (--config)
  CONFIGSYS_STATE_DIR                  holds your user config, the ledger, caches and synced plugins
                                       (default $XDG_CONFIG_HOME/configsys, else ~/.config/configsys)
  CONFIGSYS_REPO                       data root holding the shipped routes.hu and config.hu
  CONFIGSYS_USERSCOPE_DIR              base dir for user-scope installs (default ~)
  CONFIGSYS_SYSTEMSCOPE_DIR            base dir for system-scope installs (default /opt)
  CONFIGSYS_APP_DIR, CONFIGSYS_SDK_DIR, CONFIGSYS_SRC_DIR
                                       app / SDK / source-tree dirs under that base (default apps,
                                       sdks, src); these five override the `dirs:` setting
  CONFIGSYS_COLOR                      TUI color cap, same values as --color (NO_COLOR forces none)
  CONFIGSYS_EFFECTS                    TUI motion: full, reduced or none (--effects)
  CONFIGSYS_SPLASH                     always = show the startup splash even on a fast load;
                                       linger = also hold it until a key (--splash-linger)
  CONFIGSYS_NO_SPLASH                  set to anything to turn the startup splash off
  CONFIGSYS_GLUE_SHELLS                comma-separated shells to set up glue for (default: detected)
  CONFIGSYS_PM                         apt or dnf: the package manager the gcc / clang drivers use
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
                    "Each machine installs its own picks (the `picks:` section of your config) through "
                    "this OS's\npackage manager (apt, dnf, pacman, zypper, apk, xbps) or the AUR, "
                    'Homebrew, flatpak, snap,\nAppImages, tarballs, source builds, language toolchains '
                    'and more. Profiles are read-only lists\nto browse and pick from. With no command, '
                    'the interactive TUI opens.',
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action=_VersionAction, nargs=0,
                   help='print the configsys version (and the git commit it runs from) and exit')
    p.add_argument('--pretend', action='store_true',
                   help='dry run: print the commands an operation would run instead of running them')
    p.add_argument('--os', metavar='BLOCK[:VERSION]',
                   help='use this OS block, and optionally release, instead of the detected one (e.g. '
                        'pop_os!:22.04, fedora:44, arch); without a version, version conditions read '
                        'false. Same as CONFIGSYS_OS')
    p.add_argument('--home', metavar='DIR',
                   help='use DIR in place of $HOME for every path configsys reads or writes (config, '
                        'state, user-scope installs), for sandboxed runs; same as CONFIGSYS_HOME')
    p.add_argument('--machine', metavar='NAME',
                   help="work on machine NAME's picks for this run instead of this box's `machine:` "
                        '(to view or curate another machine from here); installs still happen on '
                        'this box')
    p.add_argument('--config', metavar='FILE',
                   help='your user config file (default ~/.config/configsys/configsys.hu); same as '
                        'CONFIGSYS_CONFIG')
    p.add_argument('--color', choices=['auto', '24bit', '256', '16', '8', 'none'], default=None,
                   help='cap the TUI color depth (default auto: detect it). Lower values only clamp '
                        'down, 24bit forces direct RGB even without COLORTERM, 16 uses the theme\'s '
                        '`colors-basic` ANSI set and 8 only the base eight; CONFIGSYS_COLOR sets the '
                        'same, and NO_COLOR forces none')
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
                                   'and latest versions) and any issues')

    # each op's description carries extra notes (rebuild semantics + --no-deps, picks, stranded
    # removal, holds) — surfaced in the generated man page, which uses each command's description.
    _rebuild_note = (' A named component already present is not skipped: a package manager re-runs (a '
                     'no-op when current), and a `via: source` component rebuilds from a clean checkout, '
                     'so re-running install picks up a recipe change even at the same version. Its '
                     'dependencies are installed only when missing (--with-deps re-runs them all; '
                     '--no-deps skips them). An install configsys adopted through another method is '
                     'the one acted on. A locked component is not upgraded until you unlock it. '
                     '--force lets a dotfiles install overwrite an on-system file that was never '
                     'captured (it is backed up to .pre-configsys first), and lets a tarball, font or '
                     'AppImage replace a directory or file configsys did not install. A source '
                     'component builds only in a checkout configsys created, or one you --adopt.')
    _op_notes = {
        'install': (_rebuild_note + ' Installing does not add a component to this machine\'s picks; '
                    '`configsys picks add` does that. --picks installs every pick of this box that '
                    'is not installed (with any names given), after showing the plan and asking '
                    '(--yes skips the question); picks with no install method here are skipped '
                    'with a notice.'),
        'upgrade': (_rebuild_note + ' --picks upgrades every outdated pick of this box (with any '
                    'names given), after showing the plan and asking (--yes skips the question). '
                    '--system upgrades the whole machine instead and takes no names; see '
                    '`configsys updates`.'),
        'remove': (' Glue that only the removed components needed goes with them; their dependencies '
                   'stay. A component with no install method left on this OS is still removed when a '
                   'stranded install of it remains, through the method that made it. Removing does '
                   'not unpick a component; `configsys picks rm` does that.'),
        'lock': (' The hold is the package manager\'s own where it has one (apt-mark hold, dnf '
                 'versionlock, …), else a record in configsys\' ledger; managers that cannot hold a '
                 'version, such as pacman and apk, decline.'),
    }
    for name, help_ in (('install', 'install components'),
                        ('remove', 'uninstall components'),
                        ('upgrade', 'upgrade components to their latest version, or the whole system '
                                    'with --system'),
                        ('lock', 'hold components at their installed version'),
                        ('unlock', 'release the version hold on components')):
        desc = (f'{help_.capitalize()}. A name is a component; '
                'profile:<name> expands to that profile\'s components.')
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
            sp.add_argument('--no-deps', action='store_true',
                            help='act on only the named components, without installing their '
                                 'missing dependencies. A source component always rebuilds, so this '
                                 'rebuilds just it (e.g. to pick up a recipe change)')
            sp.add_argument('--with-deps', action='store_true',
                            help='also re-run every dependency, present or not (by default only '
                                 'missing dependencies are installed)')
            sp.add_argument('--picks', action='store_true',
                            help=("also act on every pick of this box that is not installed: show "
                                  'the plan and ask first (on this box only, so not with --machine '
                                  'naming another machine)') if name == 'install' else
                                 ('also act on every outdated pick of this box: show the plan and ask '
                                  'first (on this box only, so not with --machine naming another '
                                  'machine)'))
        if name == 'install':
            sp.add_argument('--yes', action='store_true',
                            help='with --picks: skip the confirmation prompt')
        if name == 'upgrade':
            sp.add_argument('--system', action='store_true',
                            help='upgrade the whole system: preview the System Updates list, confirm, '
                                 "then run each package manager's own bulk upgrade (this OS's manager, "
                                 'flatpak, snap), which also updates anything else it manages; held '
                                 'packages stay held. Within-release only; see `configsys updates`')
            sp.add_argument('--yes', action='store_true',
                            help='with --system or --picks: skip the confirmation prompt')

    fs = sub.add_parser('fix-scope', help='move installs whose scope (user / system) differs from the '
                                          'configured scope, so they match the config (the config is '
                                          'not changed)')
    fs.add_argument('names', nargs='*', help='component names (default: every mismatched install)')

    sv = sub.add_parser('set-version', help='install a specific version of a component, where its '
                                            'install method can target one')
    sv.add_argument('name', help='component name')
    sv.add_argument('version', help='version to install (for flatpak, a commit id)')

    mp = sub.add_parser('machine', help='list, add, remove or switch machines (the columns of '
                                        '`picks:`)')
    mpsub = mp.add_subparsers(dest='machine_command')
    mpsub.add_parser('list', help='list machines and how many components each tracks, marking which '
                                  'one this box is (default)')
    mps = mpsub.add_parser('show', help="show one machine's picks")
    mps.add_argument('name', help='machine name')
    for _n, _h in (('add', 'add a machine (a new, empty picks column)'),
                   ('rm', 'remove a machine and its picks (from your top config and your primary '
                          'plugin)')):
        _sp = mpsub.add_parser(_n, help=_h)
        _sp.add_argument('name', help='machine name')
    mpu = mpsub.add_parser('use', help="set which machine this box is (the `machine:` setting); no "
                                       'name clears it')
    mpu.add_argument('name', nargs='?', help='machine name (omit to clear)')

    dp = sub.add_parser('disp', help='view or set dispositions: your seen / interesting triage marks on '
                                     'catalog components (they never install anything)')
    dpsub = dp.add_subparsers(dest='disp_command')
    dpl = dpsub.add_parser('list', help='list your seen / interesting components and how many are NEW '
                                        '(not yet triaged) (default)')
    dpl.add_argument('--new', action='store_true', help='list every NEW component instead')
    dpg = dpsub.add_parser('get', help="print a component's disposition")
    dpg.add_argument('name', help='component name')
    dps = dpsub.add_parser('set', help="set a component's disposition (kept per machine)")
    dps.add_argument('name', help='component name')
    dps.add_argument('state', choices=['seen', 'interesting', 'new'], help="'new' clears it")

    pk = sub.add_parser('picks', help="list or edit a machine's picks: the components it installs "
                                      '(also editable in the TUI Profiles screen)')
    pksub = pk.add_subparsers(dest='picks_command')
    pkl = pksub.add_parser('list', help="list a machine's picks (default)")
    # SUPPRESS: unset here must not clobber the global --machine (same dest) with None
    pkl.add_argument('--machine', metavar='NAME', default=argparse.SUPPRESS,
                     help="which machine (default: this box's)")
    for _n, _h in (('add', "track a component: add it to a machine's picks (kept in your primary "
                           'plugin when you have one)'),
                   ('rm', "untrack a component: remove it from a machine's picks (it is not "
                          'uninstalled)')):
        _sp = pksub.add_parser(_n, help=_h)
        _sp.add_argument('component', help='component name')
        _sp.add_argument('--machine', action='append', dest='machines', metavar='NAME',
                         help="target machine (repeat for several; default: this box's)")
    pksub.add_parser('to-primary', help="move this box's local picks into the primary plugin so they "
                                        'travel to your other machines (dispositions stay local)')

    srch = sub.add_parser('search', help='find components in the catalog by name, description or '
                                        'attrs (e.g. `search terminal`, `search --attr TUI git`)')
    srch.add_argument('text', nargs='*', help='words that must each appear in the name or description')
    srch.add_argument('--attr', action='append', default=[], metavar='ATTR',
                      help='only components carrying this attr (repeatable; see docs/component-attrs.md)')
    srch.add_argument('--json', action='store_true', help='machine-readable output')
    wh = sub.add_parser('where', help='explain a component: the layer that defines it, each install '
                                      'method (marking the default, the alternatives you can pin, and '
                                      "any whose driver can't work here, with why), the rule that chose "
                                      'the default, and what it resolves to on this machine')
    wh.add_argument('name', help='component name (or a profile name with -p)')
    wh.add_argument('-p', '--profile', action='store_true',
                    help='treat NAME as a profile: show its definition in each layer, how the layers '
                         'relate, and its member / declined counts')

    lo = sub.add_parser('location', help="print a component's absolute install location as it "
                                         'resolves here (honoring scope, pins and `locations:`), for '
                                         'shell snippets')
    lo.add_argument('name', nargs='?', help='component name')
    lo.add_argument('--all', action='store_true', dest='all',
                    help='print `<component>\\t<path>` for every picked component with a managed '
                         'install location, and refresh the cache the shell glue reads')

    ve = sub.add_parser('versions', help='show the version each install method would install for a '
                                         'component (native vs tarball/source/…), and which lag the '
                                         'newest')
    ve.add_argument('name', help='component name')
    ve.add_argument('--min', dest='min_version', metavar='VERSION',
                    help='mark which methods meet this minimum version (and how to pin one)')
    ve.add_argument('--refresh', action='store_true',
                    help='bypass the cache and re-query each method now')

    sub.add_parser('check', help='lint the merged config (repo, plugins, your config and its '
                                 'includes) without installing anything')

    pn = sub.add_parser('pin', help='view or change install-method / provider pins '
                                    '(local, or portable via a primary plugin)')
    pnsub = pn.add_subparsers(dest='pin_command')
    pnsub.add_parser('list', help='list the effective pins and where each came from (default)')
    ps = pnsub.add_parser('set', help='pin a component to an install method (or a capability to a '
                                      "provider component) in your top config; the next install "
                                      'swaps out an install made by another method')
    ps.add_argument('component', help='component (or capability) name')
    ps.add_argument('via', help='a via/driver (binding-pin), or a provider component (provider-pin)')
    pnu = pnsub.add_parser('unset', help='remove a pin from your top config')
    pnu.add_argument('component', help='component (or capability) name')
    pnp = pnsub.add_parser('promote', help='move a top-config pin into your primary plugin '
                                           '(portable to your other machines)')
    pnp.add_argument('component', help='component (or capability) name')

    pr = sub.add_parser('profile', help='browse profiles: read-only component lists from the repo, '
                                        'your plugins and your own config (installs come from picks)')
    prsub = pr.add_subparsers(dest='profile_command')
    prsub.add_parser('list', help='list every profile and its components (default)')
    prs = prsub.add_parser('show', help="show one profile's terms, where it is defined, and what it "
                                        'expands to')
    prs.add_argument('profile', help='profile name')

    cfp = sub.add_parser('config', help='view or edit machine settings (`config show` lists them all)')
    cfsub = cfp.add_subparsers(dest='config_command')
    cfsub.add_parser('show', help='list every machine setting: its value, where it is set, and what it '
                                  'does (default)')
    cfg_get = cfsub.add_parser('get', help="print one setting's effective value")
    cfg_get.add_argument('key', help='setting name (see `config show`)')
    cfg_set = cfsub.add_parser('set', help='set a machine setting where it already lives, else in your '
                                           "primary plugin (uniform settings) or your top config "
                                           '(machine-local ones)')
    cfg_set.add_argument('key', help='setting name (see `config show`)')
    cfg_set.add_argument('value', nargs='+', help='the value (list settings take several tokens)')
    cfg_set.add_argument('--local', action='store_true',
                         help="write to this machine's top config, not the primary plugin")
    cfg_unset = cfsub.add_parser('unset', help='clear a machine setting where it is set')
    cfg_unset.add_argument('key', help='setting name (see `config show`)')
    cfg_unset.add_argument('--local', action='store_true',
                           help="write to this machine's top config, not the primary plugin")
    cfg_move = cfsub.add_parser('move', help='move a setting between local (top config) and the '
                                             'primary plugin, carrying its value')
    cfg_move.add_argument('key', help='setting name (see `config show`)')

    thp = sub.add_parser('theme', help='view or edit the TUI theme; save/load shareable themes')
    thsub = thp.add_subparsers(dest='theme_command')
    thsub.add_parser('show', help='show the theme overrides currently in effect (default)')
    thsub.add_parser('list', help='list the theme plugins on disk')
    th_set = thsub.add_parser('set', help='set a theme value, e.g. theme set colors.accent "#c88cf0"')
    th_set.add_argument('key', help='colors.<name> | colors-basic.<name> | '
                                    'pages.<page>.<role>.<fg|bg|bold|underline|reverse> | '
                                    'pages.<page>.gradient.<from|to|enabled>  '
                                    '(fg/bg = a color-map name or #rrggbb)')
    th_set.add_argument('value', help='a color (#rrggbb or a color-map name), or true / false for '
                                      'bold, underline, reverse and enabled')
    th_set.add_argument('--local', action='store_true',
                        help="write to this machine's top config, not the primary plugin")
    th_unset = thsub.add_parser('unset', help='remove a theme value')
    th_unset.add_argument('key', help='the dotted key, as for `theme set`')
    th_unset.add_argument('--local', action='store_true',
                          help="write to this machine's top config, not the primary plugin")
    th_save = thsub.add_parser('save', help='snapshot your theme into a shareable theme plugin')
    th_save.add_argument('name', help='theme plugin name')
    th_save.add_argument('--force', action='store_true',
                         help='overwrite an existing theme plugin of that name')
    th_load = thsub.add_parser('load', help='apply a saved theme plugin under your own theme '
                                            'overrides (--reset replaces them)')
    th_load.add_argument('name', help='theme plugin name (see `theme list`)')
    th_load.add_argument('--reset', action='store_true',
                         help='replace your theme overrides with the pack instead of keeping them on top')
    th_load.add_argument('--local', action='store_true',
                         help="write to this machine's top config, not the primary plugin")

    pl = sub.add_parser('plugin', help='manage plugins: declare and sync them, bless or init your '
                                       'primary plugin, trust plugins that run code')
    plsub = pl.add_subparsers(dest='plugin_command')
    pll = plsub.add_parser('list', help='list declared plugins with their sync, ABI and trust status '
                                        '(default)')
    pll.add_argument('--fetch', action='store_true',
                     help="fetch your primary's remote first, so it counts the changes your other "
                          'machines pushed (otherwise: as of the last fetch or sync)')
    plsub.add_parser('sync', help='clone or fetch every declared plugin at its `ref:`')
    pb = plsub.add_parser('bless', help='designate your primary personal-config plugin '
                                        '(register + sync it; its machine settings then apply)')
    pb.add_argument('source', help='<provider>:<user>/<name> (or a declared plugin name), or '
                                   '"none" to clear')
    plsub.add_parser('unbless', help='clear the primary designation')
    pa = plsub.add_parser('add', help='sync a plugin and declare it (nothing is declared if the sync '
                                      'fails)')
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
    pr = plsub.add_parser('remove', help='undeclare a plugin and delete its synced copy (refused '
                                         'while the copy holds unpushed or uncommitted work)')
    pr.add_argument('name', help='plugin name, source, or dir')
    pr.add_argument('--force', action='store_true',
                    help='delete the synced copy even if it holds work found nowhere else')
    pu = plsub.add_parser('update',
                          help="re-sync a plugin, or all of them (--ref / --latest move its `ref:`)")
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
    pt = plsub.add_parser('trust', help="approve a plugin's current content (its code and command-"
                                        'carrying data: script / source / glue recipes) so it can run')
    pt.add_argument('name', nargs='?', help='plugin name, source, or dir (omit, or use --all, to '
                                            'trust every plugin that needs it)')
    pt.add_argument('--all', action='store_true',
                    help='trust every plugin that is currently untrusted or changed since trusted')
    pun = plsub.add_parser('untrust', help="revoke a plugin's trust")
    pun.add_argument('name', help='plugin name, source, or dir')
    plk = plsub.add_parser('lock', help='hold a plugin where it is on this machine: sync leaves it '
                                        'alone and update, bless and trust refuse it (its synced copy '
                                        'still loads)')
    plk.add_argument('name', help='plugin name, source, or dir')
    pulk = plsub.add_parser('unlock', help="lift a plugin's lock")
    pulk.add_argument('name', help='plugin name, source, or dir')
    pdf = plsub.add_parser('diff', help='review what a plugin would change before you take it: a '
                                        'synced plugin against its newest remote ref; an unsynced one '
                                        'between its ref and the newest (or everything a sync would '
                                        'download), fetched into a cache that is never loaded')
    pdf.add_argument('name', help='plugin name, source, or dir')
    pdf.add_argument('--to', metavar='REF',
                     help='compare against this ref instead of the newest version tag (or main/master)')
    ppu = plsub.add_parser('push', help='publish your primary plugin: commit, combine with what your '
                                        'other machines pushed (asking about any file both changed), '
                                        'and push to its branch')
    ppu.add_argument('--include-edits', action='store_true',
                     help='also commit and push edits you made by hand, without asking')
    ppu.add_argument('-y', '--yes', action='store_true',
                     help='push without listing the outgoing changes and asking first')
    plg = plsub.add_parser('log', help="your primary plugin's recent commits: what each changed, which "
                                       "configsys made, which aren't pushed yet")
    plg.add_argument('-n', type=int, default=10, metavar='N', help='how many commits (default 10)')
    pun = plsub.add_parser('undo', help='take back the newest change configsys committed to your '
                                        'primary (dropped if never pushed, else reverted)')
    pun.add_argument('-y', '--yes', action='store_true', help='undo without showing it and asking first')
    pin = plsub.add_parser('init', help='create your primary plugin from local content (captured '
                                        "dotfiles, your own glue, your config's component "
                                        'definitions), or merge that into your existing primary')
    pin.add_argument('name', nargs='?', help='plugin name (default: configsys-<user>)')
    pin.add_argument('--force', action='store_true',
                     help='overwrite dotfiles and glue already in the plugin')
    pin.add_argument('--dry-run', action='store_true', help='show the plan and exit; write nothing')
    pss = plsub.add_parser('set-source', help='swap a plugin\'s source (e.g. local path -> '
                                              'github:you/name after you push it)')
    pss.add_argument('name', help='declared plugin name')
    pss.add_argument('source', help='new source: github:owner/repo | git URL | local path')

    rp = sub.add_parser('report', help='assemble an install-failure report (OS + route + driver '
                                       'output) and file it upstream — you approve the full text first')
    rp.add_argument('name', nargs='?', help='component to report (default: every saved failure not '
                                            'yet fixed)')
    rp.add_argument('--yes', action='store_true',
                    help='file without asking (the full text is still printed first)')
    rp.add_argument('--print', dest='print_only', action='store_true',
                    help='print the report and exit; never send')

    rq = sub.add_parser('request', help='ask upstream to support a component on more platforms — '
                                        'shows a coverage matrix of where it installs today; you '
                                        'approve before filing')
    rq.add_argument('name', help='component to request full support for')
    rq.add_argument('--yes', action='store_true',
                    help='file without asking (the full text is still printed first)')
    rq.add_argument('--print', dest='print_only', action='store_true',
                    help='print the request and exit; never send')

    rqo = sub.add_parser('request-os', help='suggest THIS OS for inclusion, or report that a system '
                                            'update broke it — captures os-release; you approve before filing')
    rqo.add_argument('--yes', action='store_true',
                     help='file without asking (the full text is still printed first)')
    rqo.add_argument('--print', dest='print_only', action='store_true',
                     help='print the OS request and exit; never send')

    orp = sub.add_parser('orphans', help="list installed software this machine's picks don't account "
                                         'for; adopt (track), remove or ignore it')
    orp.add_argument('--driver', help='only this driver (apt, flatpak, …)')
    orp.add_argument('--foreign', action='store_true',
                     help='also list recipe-less packages from native managers (noisy; off by default)')
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
                     help='uninstall a known orphan via its driver (asks first unless --yes)')
    orp.add_argument('--ignore', metavar='PATTERN', nargs='+',
                     help='silence orphans matching these name/key globs (adds to orphans-ignore)')
    orp.add_argument('--yes', action='store_true', help='skip the confirmation for --remove')

    dfp = sub.add_parser('dotfiles', help='show and capture your dotfiles; review glue the '
                                          'shell-writes guard staged')
    dfsub = dfp.add_subparsers(dest='dotfiles_command')
    dfsub.add_parser('status', help="show every dotfiles target for this machine's picks: config "
                                    '(managed / unmanaged / no config) and glue (active / changed / '
                                    'available / inactive) (default)')
    cap = dfsub.add_parser('capture', help='adopt existing on-system dotfiles into your content '
                                           'store (read-only on the system side)')
    cap.add_argument('names', nargs='*', help="limit to these components — `btop` or `btop-dotfiles` "
                                              "(default: every one in this machine's picks)")
    cap.add_argument('--force', action='store_true', help='overwrite content already in the store')
    cap.add_argument('--dry-run', action='store_true', help='show the plan and exit; write nothing')
    cap.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    dfsub.add_parser('staged', help='list inactive glue candidates the shell-writes guard captured '
                                    '(installers that tried to edit your rc files)')
    act = dfsub.add_parser('activate', help='promote a staged glue candidate to your own user glue '
                                            '(a user.d snippet, linked into ~/.config/<shell>/conf.d/ '
                                            'as 90-<name>)')
    act.add_argument('names', nargs='+', help='component(s) whose staged glue to activate')
    act.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set "
                          '(default: the primary, so it travels to your other machines)')
    disc = dfsub.add_parser('discard', help='delete a staged glue candidate without activating it')
    disc.add_argument('names', nargs='+', help='component(s) whose staged glue to drop')

    glp = sub.add_parser('glue', help='add your own shell-startup snippets (aliases / env / functions), '
                                      "or override a component's shipped glue; kept in your primary "
                                      'plugin when you have one')
    glsub = glp.add_subparsers(dest='glue_command')
    gla = glsub.add_parser('add', help='create your own startup snippet and open it in $EDITOR '
                                       '(linked into ~/.config/<shell>/conf.d/, loads after component glue)')
    gla.add_argument('name', help='snippet name (a .<ext> suffix is optional)')
    gla.add_argument('--shell', help='which shell (default: your $SHELL, else bash)')
    gla.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set "
                          '(default: the primary, so it travels to your other machines)')
    glo = glsub.add_parser('override', help="copy a component's shipped glue into your layer and edit "
                                            'it (yours then shadows the shipped one; `check` flags '
                                            'when the shipped one changes)')
    glo.add_argument('comp', help='component (tool or its -glue companion) whose glue to override')
    glo.add_argument('--shell', help='only this shell (default: every installed shell it ships)')
    glo.add_argument('--local', action='store_true',
                     help="write to this machine's store even if a primary plugin is set")
    # the shell-writes guard's staged blocks are glue — here too (`dotfiles staged|activate|discard`
    # stay as aliases; review-2026-11-2 G4)
    glsub.add_parser('staged', help='list inactive glue candidates the shell-writes guard captured')
    gact = glsub.add_parser('activate', help='promote a staged candidate to your own user glue (90-<name>)')
    gact.add_argument('names', nargs='+', help='component(s) whose staged glue to activate')
    gact.add_argument('--local', action='store_true',
                      help="write to this machine's store even if a primary plugin is set")
    gdis = glsub.add_parser('discard', help='delete a staged glue candidate without activating it')
    gdis.add_argument('names', nargs='+', help='component(s) whose staged glue to drop')

    unp = sub.add_parser('uninstall', help="this machine's uninstall queue — removals staged (TUI "
                                          '`x`) to run with the next execute or `remove`')
    unsub = unp.add_subparsers(dest='uninstall_command')
    unsub.add_parser('list', help='show what is staged for removal (default)')
    for verb, what in (('add', 'stage component(s) for removal'), ('rm', 'unstage component(s)')):
        u = unsub.add_parser(verb, help=what)
        u.add_argument('names', nargs='+', help='component name(s)')
    unsub.add_parser('clear', help='unstage everything')

    mp = sub.add_parser('manpages', help='install or check the man pages '
                                         '(configsys(1) + configsys.hu(5))')
    mpsub = mp.add_subparsers(dest='manpages_command')
    for mname, mhelp in (('install', 'copy the man pages into a man directory (default: '
                                     '~/.local/share/man)'),
                         ('status', 'report whether the installed pages are present and current '
                                    '(default)')):
        msp = mpsub.add_parser(mname, help=mhelp)
        msp.add_argument('--prefix', metavar='DIR',
                         help='man-dir prefix; pages go under <prefix>/share/man (default: ~/.local)')

    sub.add_parser('updates', help="list System Updates: pending updates from this OS's package "
                                   "manager, flatpak and snap for packages that aren't configsys "
                                   'components, grouped by tier; apply with `upgrade --system`')

    sub.add_parser('refresh', help="re-check upstream versions for this machine's picks and refresh the "
                                   "package index of this OS's package manager (sudo may prompt). On "
                                   'Arch, where only a full upgrade is safe, it asks before running '
                                   '`pacman -Syu` instead')
    sh = sub.add_parser('show', help='print the shipped routes.hu or config.hu template, or its path')
    sh.add_argument('what', nargs='?', choices=list(_SHOW_TARGETS),
                    help='which base file to show (omit to list them)')
    sh.add_argument('--path', action='store_true',
                    help="print the file's resolved location instead of its contents")

    sub.add_parser('keys', help='show the effective TUI keybindings (the merged `keys:` section)')
    sub.add_parser('tui', help='open the interactive TUI (the default; prints `inspect` output when '
                               'not on a terminal)')
    return p
