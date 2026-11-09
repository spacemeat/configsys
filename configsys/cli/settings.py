'''cli/settings.py — `config`, `theme`, `keys`, `show`, `manpages`.

Split out of app.py (review-2026-11-2 D2).
'''

import sys
from .common import _pretend_edit


_MANPAGES = (('configsys.1', 'man1'), ('configsys.hu.5', 'man5'))


def _manpage_targets(ctx, prefix):
    '''(shipped-source, install-destination) for each page under <prefix>/share/man.'''
    from pathlib import Path
    src_dir = ctx.paths.repo / 'man'
    base = Path(prefix).expanduser() / 'share' / 'man'
    return [(src_dir / f, base / sec / f) for f, sec in _MANPAGES]


def cmd_manpages(ctx, args):
    '''Install the man pages into a man directory, or check they're present + current. configsys
    runs from source, so there's no package to hook — this ships the checked-in pages on demand.'''
    import shutil
    from pathlib import Path

    action = getattr(args, 'manpages_command', None) or 'status'
    prefix = getattr(args, 'prefix', None) or str(ctx.paths.home / '.local')
    targets = _manpage_targets(ctx, prefix)

    for src, _dst in targets:
        if not src.exists():
            print(f'configsys: shipped man page missing: {src}\n'
                  '  regenerate with `python3 tools/gen_manpages.py`.')
            return 1

    if action == 'install':
        for src, dst in targets:
            if ctx.runner.pretend:
                print(f'[pretend] install {dst}')
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            print(f'installed {dst}')
        if not ctx.runner.pretend:
            base = Path(prefix).expanduser() / 'share' / 'man'
            print(f'configsys: man pages installed under {base}.\n'
                  '  try `man configsys` and `man 5 configsys.hu` '
                  '(ensure that man dir is on your MANPATH).')
        return 0

    # status — the presence + up-to-date check
    missing = stale = 0
    for src, dst in targets:
        if not dst.exists():
            missing += 1
            print(f'  not installed  {dst}')
        elif dst.read_bytes() != src.read_bytes():
            stale += 1
            print(f'  out of date    {dst}')
        else:
            print(f'  up to date     {dst}')
    if missing or stale:
        print(f'configsys: {missing} missing, {stale} out of date — '
              'run `configsys manpages install`.')
        return 1
    print('configsys: man pages installed and current.')
    return 0


_SHOW_TARGETS = ('routes', 'config')


def _show_file(ctx, what):
    '''(path, kind) for a base data file. kind describes it for messages.'''
    return {'routes': (ctx.paths.routes_file, 'routes.hu'),
            'config': (ctx.paths.config_file, 'config.hu template')}[what]


def cmd_keys(ctx, args):
    '''Print the effective TUI keybindings — the `keys:` section merged across every layer (repo <
    plugins < primary < your config). For a humon-only user (no TUI editor) to see what's active.'''
    from ..tui.keyspec import Keymap, config_keys, key_name, lint_keys
    owners = {}
    km = Keymap(config_keys(ctx.config, owners_out=owners))   # rebind-wins, as the TUI resolves it
    print('TUI keybindings — merged repo < plugins < primary < your config '
          '(edit the `keys:` section in ~/.config/configsys/configsys.hu or your primary plugin):')
    order = ['screens', 'global', 'components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config',
             'theme']                                         # screen order (keys 1-7)
    by_scope = {}
    for scope, action, codes in km.bindings():
        by_scope.setdefault(scope, {})[action] = codes
    for scope in order + [s for s in by_scope if s not in order]:
        actions = by_scope.get(scope)
        if not actions:
            continue
        print(f'\n  [{scope}]')
        for action in sorted(actions):
            keys = ' / '.join(key_name(c) for c in actions[action])
            src = (owners.get(scope) or {}).get(action) or 'built-in'
            print(f'    {action:18} {keys:16} {src}')
    steals = lint_keys(ctx.config.key_layers()) if hasattr(ctx.config, 'key_layers') else []
    if steals:                                         # what a higher layer took from a lower one
        print('\n  rebinds across layers:')
        for line in steals:
            print(f'    {line}')
    return 0


def cmd_show(ctx, args):
    '''Print a shipped base data file — routes.hu or the config.hu template — or, with --path,
    just its on-disk location. Handy once configsys is installed (pip/pipx) rather than cloned:
    the files then live in package data, so `configsys show routes --path` says where, and
    `configsys show routes` prints the file you can no longer `cat` from a checkout.'''
    what = getattr(args, 'what', None)
    if not what:
        print('configsys: name what to show — ' + ' | '.join(_SHOW_TARGETS))
        for name in _SHOW_TARGETS:
            path, _kind = _show_file(ctx, name)
            print(f'  {"" if path.exists() else "?"} {name:8} {path}')
        return 1
    path, kind = _show_file(ctx, what)
    if not path.exists():
        print(f'configsys: base {kind} not found at {path}', file=sys.stderr)
        return 1
    if getattr(args, 'path', False):
        print(path)
        return 0
    try:
        sys.stdout.write(path.read_text())
        sys.stdout.flush()
    except BrokenPipeError:
        # a downstream pager/`head` closed the pipe — normal; silence the interpreter's final
        # flush (which would re-raise) by pointing stdout at the void, then exit clean.
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


def _fmt_setting_value(kind, val):
    if kind in ('list', 'map'):                   # a map's value arrives as `key=value` tokens
        return ' '.join(val) if val else '(unset — built-in default)'
    if kind == 'bool':
        return 'true' if val else 'false'
    return str(val) if val not in (None, '') else '(unset)'


def cmd_config(ctx, args):
    '''View or edit machine settings (scope / driver-preference / auto-tighten).
    A skin over configsys.actions — the same functions the TUI Config screen will call.'''
    from .. import actions
    sub = getattr(args, 'config_command', None) or 'show'
    settings = actions.config_settings(ctx)

    if sub == 'show':
        w = max(18, max((len(k) for k in settings), default=0))
        for key, info in settings.items():
            src = info.get('source')
            if isinstance(src, str) and src.startswith('env '):
                loc = src + ' overrides config'
            elif info.get('home') in ('local', 'primary'):
                loc = {'local': 'local (top config)',
                       'primary': f'primary: {info.get("home_label")}'}[info['home']]
            else:                                 # at default -> name where an edit would land
                loc = f'built-in default → edits: {info.get("target")}'
            print(f'  {key:{w}} {_fmt_setting_value(info["kind"], info["value"])}  ({loc})')
            print(f'  {"":{w}} {info["desc"]}  (see {info["man"]})')
        print('\n  uniform settings default to your primary plugin; machine settings to this box.'
              '\n  edit: configsys config set <key> <value>   (--local = this machine only)'
              '\n  move: configsys config move <key>          (local <-> primary)')
        return 0

    if sub == 'move':
        if args.key not in actions.CONFIG_SETTINGS:
            print(f'configsys: unknown setting {args.key!r}', file=sys.stderr)
            return 1
        if ctx.runner.pretend:
            where, _who = actions._setting_home(ctx, args.key)
            if where is None:
                print(f'configsys: {args.key} is at its default — set a value before moving it',
                      file=sys.stderr)
                return 1
            dst = ('top config' if where == 'primary'
                   else actions._primary_target_label(ctx)[1] or '(no primary plugin)')
            _pretend_edit(ctx, f'move {args.key} → {dst}')
            return 0
        ctx.ensure_user_config()
        ok, msg = actions.move_config_setting(ctx, args.key)
        print(f'configsys: {msg}', file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if sub == 'get':
        if args.key not in settings:
            print(f'configsys: unknown setting {args.key!r}', file=sys.stderr)
            return 1
        print(_fmt_setting_value(settings[args.key]['kind'], settings[args.key]['value']))
        return 0

    # set / unset
    if args.key not in actions.CONFIG_SETTINGS:
        print(f'configsys: unknown setting {args.key!r} '
              f'(known: {", ".join(actions.CONFIG_SETTINGS)})', file=sys.stderr)
        return 1
    values = [] if sub == 'unset' else args.value
    if values and actions.CONFIG_SETTINGS[args.key][0] == 'map':
        try:
            actions._parse_map_tokens(values)
        except ValueError as e:
            print(f'configsys: {args.key}: {e}', file=sys.stderr)
            return 1
    if ctx.runner.pretend:
        label = ('top config' if getattr(args, 'local', False)
                 else actions._setting_target(ctx, args.key)[1])
        _pretend_edit(ctx, f'clear {args.key}  (in {label})' if sub == 'unset'
                      else f'set {args.key} = {" ".join(values)}  (in {label})')
        return 0
    ctx.ensure_user_config()
    target = str(ctx.paths.user_config_file) if getattr(args, 'local', False) else None
    try:
        _changed, label = actions.set_config_setting(ctx, args.key, values, target=target)
    except ValueError as e:                          # a fixed-choice setting given another value
        print(f'configsys: {e}', file=sys.stderr)
        return 1
    if sub == 'unset':
        print(f'configsys: cleared {args.key}  (in {label})')
    else:
        print(f'configsys: set {args.key} = {" ".join(args.value)}  (in {label})')
        if args.key == 'splash':                 # warn now if the value can't resolve to one splash
            from .. import plugins
            decls = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
            hint = plugins.splash_value_hint(' '.join(args.value), ctx.paths.plugins_dir, decls)
            if hint:
                print(f'configsys: note — {hint}', file=sys.stderr)
    return 0


def _print_theme(ov, indent=2):
    for k, v in ov.items():
        if isinstance(v, dict):
            print(' ' * indent + f'{k}:')
            _print_theme(v, indent + 2)
        else:
            print(' ' * indent + f'{k}: {v}')


def cmd_theme(ctx, args):
    '''View or edit the TUI theme, and save/load theme plugins. A skin over configsys.actions —
    the same functions the TUI theme editor (Config screen) will call.'''
    from .. import actions
    sub = getattr(args, 'theme_command', None) or 'show'

    if sub == 'show':
        ov = actions.theme_overrides(ctx)
        if ov:
            _print_theme(ov)
        else:
            print('configsys: no theme overrides (using built-in defaults)')
        return 0
    if sub == 'list':
        names = actions.theme_plugins(ctx)
        print('\n'.join(f'  {n}' for n in names) if names
              else 'configsys: no theme plugins saved (create one: configsys theme save <name>)')
        return 0

    if ctx.runner.pretend:
        label = ('top config' if getattr(args, 'local', False)
                 else actions.theme_target(ctx, getattr(args, 'key', None))[1])
        if sub == 'set':
            _pretend_edit(ctx, f'set {args.key} = {args.value}  (in {label})')
        elif sub == 'unset':
            _pretend_edit(ctx, f'clear {args.key}  (in {label})')
        elif sub == 'save':
            pdir = ctx.paths.plugins_dir / args.name
            if pdir.exists() and not args.force:
                print(f'configsys: theme plugin {args.name!r} already exists at {pdir} — '
                      f'use --force to overwrite', file=sys.stderr)
                return 1
            _pretend_edit(ctx, f'save the current theme -> {pdir}')
        elif sub == 'load':
            if args.name not in actions.theme_plugins(ctx):
                print(f'configsys: no theme plugin {args.name!r} (see `configsys theme list`)',
                      file=sys.stderr)
                return 1
            _pretend_edit(ctx, f'apply theme {args.name}  (in {label})')
        return 0
    ctx.ensure_user_config()
    target = str(ctx.paths.user_config_file) if getattr(args, 'local', False) else None

    if sub in ('set', 'unset'):
        val = None if sub == 'unset' else args.value
        try:
            _changed, label = actions.set_theme_value(ctx, args.key, val, target=target)
        except ValueError as e:
            print(f'configsys: {e}', file=sys.stderr)
            return 1
        verb = 'cleared' if val is None else f'set {args.key} = {args.value}'
        print(f'configsys: {"cleared " + args.key if val is None else verb}  (in {label})')
        return 0
    if sub == 'save':
        pdir, existed = actions.save_theme_plugin(ctx, args.name, force=args.force)
        if existed and not args.force:
            print(f'configsys: theme plugin {args.name!r} already exists at {pdir} — '
                  f'use --force to overwrite', file=sys.stderr)
            return 1
        print(f'configsys: saved current theme -> {pdir}\n'
              f'  to share: cd {pdir}; git init + push, then bless/declare it as a plugin')
        return 0
    if sub == 'load':
        _changed, label = actions.load_theme(ctx, args.name, target=target,
                                             reset=getattr(args, 'reset', False))
        if label is None:
            print(f'configsys: no theme plugin {args.name!r} (see `configsys theme list`)',
                  file=sys.stderr)
            return 1
        print(f'configsys: applied theme {args.name}  (in {label}) — '
              f'retune with `configsys theme set`')
        return 0
    return 0
