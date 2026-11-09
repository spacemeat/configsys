'''cli/matrix.py — the component × machine matrix verbs — `picks`, `machine`, `profile`, `disp`, `orphans`,
`pin`.

Split out of app.py (review-2026-11-2 D2).
'''

import sys
from ..errors import ConfigError
from .common import _install_scope_label, _pretend_edit, _warn_unknown_component, ask
from .ops import _dispatch_op, _expand_profile_args_detail
from .where import _layer_label


def cmd_disp(ctx, args):
    '''Component dispositions (v2 triage): seen / interesting / new. include/exclude are profile
    membership; NEW is the undispositioned default. Local (per-machine) side-store.'''
    from .. import actions
    cfg = ctx.config
    sub = getattr(args, 'disp_command', None) or 'list'
    universe = set(ctx.routes.components)

    if sub == 'list':
        new = sorted(c for c in universe if cfg.is_new(c))
        if getattr(args, 'new', False):
            for c in new:
                print(f'  ? {c}')
            print(f'\n{len(new)} NEW (undispositioned) component(s)')
            return 0
        disp = cfg.dispositions()
        inter = sorted(c for c, s in disp.items() if s == 'interesting')
        seen = sorted(c for c, s in disp.items() if s == 'seen')
        if inter:
            print(f'interesting ({len(inter)}): {", ".join(inter)}')
        if seen:
            print(f'seen ({len(seen)}): {", ".join(seen)}')
        if not inter and not seen:
            print('no dispositions set')
        print(f'NEW (undispositioned): {len(new)}   (list them: configsys disp list --new)')
        return 0

    if sub == 'get':
        c = args.name
        if c in cfg.user_layer_components():
            state = 'include (in one of your profiles)'
        elif c in cfg.uninstall_queue():
            state = 'uninstall (!uninstall)'
        else:
            state = cfg.disposition(c) or 'new'
        print(f'{c}: {state}')
        return 0

    if sub == 'set':
        _warn_unknown_component(args.name, universe)
        if ctx.runner.pretend:
            from .. import plugins
            _f, label = actions._nature_target(ctx, 'dispositions',
                                               lambda f: bool(plugins.read_dispositions(f)))
            _pretend_edit(ctx, f'set {args.name} → {args.state}  (in {label})')
            return 0
        ctx.ensure_user_config()
        changed, label = actions.set_disposition(ctx, args.name, args.state)
        print(f'configsys: {args.name} → {args.state}  (in {label})' if changed
              else f'configsys: no change — {args.name} is already {args.state}')
        return 0
    return 0


def cmd_picks(ctx, args):
    '''The matrix Included set: the components a machine installs. A skin over
    actions.set_included — the same the TUI Profiles (matrix) screen calls.'''
    from .. import actions
    cfg = ctx.config
    sub = getattr(args, 'picks_command', None) or 'list'

    if sub == 'list':
        m = getattr(args, 'machine', None) or cfg.current_machine()
        comps = sorted(cfg.included(m))
        print(f'picks for {m} ({len(comps)}):')
        for c in comps:
            print(f'  + {c}')
        if not comps:
            print('  (none — pick components in the TUI, or `configsys picks add <name>`)')
        return 0

    machines = getattr(args, 'machines', None) or [cfg.current_machine()]
    comps = [getattr(args, 'component', None)]
    if sub in ('add', 'rm') and comps[0].startswith('profile:'):
        # a `profile:<name>` picks (or unpicks) each member, as on the ops; it is never stored as a
        # pick itself, and an unknown profile writes nothing
        got = _expand_profile_args_detail(ctx, comps)
        if got is None:
            return 1
        comps = got[0]
    if ctx.runner.pretend:
        if sub == 'to-primary':
            from .. import plugins
            _pf, prim = actions._primary_target_label(ctx)
            local = plugins.read_picks(ctx.paths.user_config_file)
            n = sum(len(v) for v in local.values())
            _pretend_edit(ctx, f'move {n} local pick(s) into "{prim}"' if prim and n
                          else 'do nothing — ' + ('no primary plugin' if not prim
                                                  else 'no local picks to move'))
        elif sub in ('add', 'rm'):
            labels = sorted({actions._picks_target(ctx, m)[1] for m in machines})
            _pretend_edit(ctx, f'{"pick" if sub == "add" else "unpick"} {", ".join(comps)} on '
                               f'{", ".join(machines)}  (in {" + ".join(labels)})')
        return 0

    ctx.ensure_user_config()

    if sub == 'to-primary':
        n, label = actions.move_picks_to_primary(ctx)
        if label == 'no primary':
            print('configsys: no primary plugin — picks already live in your top config '
                  '(bless a primary with `configsys plugin bless` to make them portable)')
        elif n:
            print(f'configsys: moved {n} pick(s) into "{label}" — they now travel to your other machines')
        else:
            print(f'configsys: nothing to move — no local picks (they already live in "{label}")')
        return 0

    if sub in ('add', 'rm'):
        verb = 'picked' if sub == 'add' else 'unpicked'
        for comp in comps:
            if sub == 'add':
                _warn_unknown_component(comp, set(ctx.routes.components))
            n, label = actions.set_included(ctx, comp, machines, sub == 'add')  # invalidates glue cache
            print(f'configsys: {comp} {verb} on {", ".join(machines)}  (in {label})' if n
                  else f'configsys: no change — {comp} already {verb} there')
        if not comps:
            print(f'configsys: no change — {args.component} has no members')
        return 0
    return 0


def cmd_orphans(ctx, args):
    '''List installed software this machine doesn't track, grouped by driver, each tagged with its
    kind (lurking / forgotten / foreign) — or act on one: --adopt (track it), --remove (uninstall
    it), --ignore (quiet it), --unignore (list it again). The bare listing is read-only.'''
    from .. import orphans as orphans_mod, actions
    cfg = ctx.config

    # -- action verbs (adopt / remove / ignore / unignore) — each returns early; no scan needed --
    if args.ignore:
        new = [p for p in dict.fromkeys(args.ignore) if p not in cfg.orphans_ignore()]
        if new:
            ctx.ensure_user_config()                     # (a no-op under --pretend)
        n, label = actions.ignore_orphan(ctx, args.ignore)        # the TUI `.` action's writer
        if label == actions.PRETEND_NOT_SAVED:
            _pretend_edit(ctx, f'ignore {", ".join(new)}  →  orphans-ignore in '
                               f'{actions._setting_target(ctx, "orphans-ignore")[1]}')
        elif n:
            print(f'ignoring {", ".join(new)}  →  orphans-ignore in {label}')
        else:
            print(f'already ignored: {", ".join(args.ignore)}')
        return 0
    if getattr(args, 'unignore', None):
        rc = 0
        for pat in dict.fromkeys(args.unignore):
            changed, label = actions.unignore_orphan(ctx, pat)    # the TUI `.` toggle's other half
            if label == actions.PRETEND_NOT_SAVED:
                _pretend_edit(ctx, f'un-ignore {pat}  →  orphans-ignore in '
                                   f'{actions._setting_target(ctx, "orphans-ignore")[1]}')
            elif changed:
                print(f'un-ignored {pat}  (orphans-ignore in {label})')
            else:
                print(f'configsys: {pat}: {label}', file=sys.stderr)
                rc = 1
        return rc
    if args.adopt:
        if args.adopt not in ctx.routes.components:
            print(f'configsys: unknown component "{args.adopt}" — --adopt takes a known orphan '
                  f'(a component); a foreign orphan has no recipe to adopt')
            return 1
        machines = getattr(args, 'machines', None) or [ctx.config.current_machine()]
        if ctx.runner.pretend:
            labels = sorted({actions._picks_target(ctx, m)[1] for m in machines})
            _pretend_edit(ctx, f'adopt (track) {args.adopt} on {", ".join(machines)}  '
                               f'(in {" + ".join(labels)})')
            return 0
        n, label = actions.stage_adopt(ctx, args.adopt, machines)
        print(f'adopted (tracked) {args.adopt} on {", ".join(machines)}  (in {label})' if n
              else f'no change — {args.adopt} already tracked on {", ".join(machines)}')
        return 0
    if args.remove:
        if args.remove not in ctx.routes.components:
            print(f'configsys: "{args.remove}" is not a cf component (a foreign orphan) — remove it '
                  f'with your package manager')
            return 1
        # --pretend goes straight into the dry-run remove (it shows what would run), like _confirm_plan
        go = ask(f'Uninstall {args.remove}? [y/N] ', yes=args.yes or ctx.runner.pretend,
                 refuse_note=f'configsys: not a terminal — re-run with --yes to uninstall {args.remove}.')
        if not go:
            if go is False:
                print('aborted')
            return 0 if go is False else 1
        return _dispatch_op(ctx, [args.remove], 'remove')

    try:
        requested = list(cfg.requested())
    except ConfigError as e:
        print(f'configsys: {e}')
        return 1
    units, _errs = ctx.routes.resolve_resilient(requested)
    found = orphans_mod.scan_orphans(ctx, units, include_foreign_native=args.foreign,
                                     include_auto=args.include_auto, include_system=True)
    if args.driver:
        found = [o for o in found if o.driver == args.driver]
    # hide OS-base foreign (required/important/standard) unless `--system` — in the listing AND in
    # --json (the filter runs first). The tier rides on every orphan, so `--system` surfaces them
    # (tier included in the JSON); a user can still choose to manage systemd.
    base_hidden = 0
    if not args.system:
        kept = []
        for o in found:
            if o.kind == 'foreign' and o.tier in orphans_mod.BASE_TIERS:
                base_hidden += 1
            else:
                kept.append(o)
        found = kept
    visible = [o for o in found if args.all or not o.ignored]

    if args.json:
        import json
        print(json.dumps([vars(o) for o in visible], indent=2))
        return 0

    active = _install_scope_label(cfg)
    known, foreign, ignored = orphans_mod.scanned_summary(visible)
    if not visible:
        extra = []
        if ignored:
            extra.append(f'{ignored} ignored — `--all`')
        if base_hidden:
            extra.append(f'{base_hidden} OS-base foreign — `--system`')
        tail = f' ({"; ".join(extra)})' if extra else ''
        print(f'\nNo orphans: everything installed is tracked on this machine ({active}).{tail}')
        return 0

    print(f'\nInstalled, not tracked on this machine ({active}):\n')
    kw = max(len(o.key) for o in visible)
    vw = max(len(o.version) for o in visible)
    cw = max((len(o.component) for o in visible if o.kind != 'foreign'), default=0)
    last_driver = None
    for o in visible:
        col = o.driver if o.driver != last_driver else ''
        last_driver = o.driver
        head = f'  {col:<10} {o.key:<{kw}}  {o.version:<{vw}}'
        if o.kind == 'foreign':
            note = f'(foreign — no cf recipe · {o.tier or "?"})'
        else:
            note = f'→ {o.component:<{cw}}  ({o.kind})'
        flag = '  [ignored]' if o.ignored else ''
        print(f'{head}  {note}{flag}')

    scope = 'all installed' if args.include_auto else 'explicitly-installed only'
    print(f'\n{known} known · {foreign} foreign'
          + (f' · {ignored} ignored' if ignored else '')
          + f'   ·   {scope}   ·   `configsys orphans --json` for scripting')
    if not args.include_auto:
        print('(auto-installed dependency packages hidden — `--include-auto` to show them)')
    if base_hidden:
        print(f'({base_hidden} OS-base foreign package{"s" if base_hidden != 1 else ""} hidden '
              '[required/important/standard] — `--system` to show them)')
    print('scanned: batch-enumerable managers where present (apt/dnf/pacman/zypper/apk/xbps/brew, '
          'flatpak, snap, pip/pipx/npm/cargo/gem/go-install/luarocks/opam); not scanned: '
          'tarball/appImage/script/source installs (no batch enumeration) or arbitrary files.')
    return 0


def _validate_pin(ctx, name, value):
    from .. import actions
    return actions.validate_pin(ctx, name, value)


def _pin_list(ctx):
    pins = ctx.config.pins()
    if not pins:
        print('configsys: no pins set')
        return 0
    src = ctx.config.pin_sources()
    _ROLE = {'user': 'local', 'primary': 'primary plugin (portable)', 'repo': 'repo'}
    print('pins (effective):')
    for name in sorted(pins):
        print(f'  {name:24} -> {pins[name]:18} [{_ROLE.get(src.get(name), src.get(name, "?"))}]')
    return 0


def _pin_set(ctx, name, value):
    from .. import actions
    ok, label, note = actions.set_pin(ctx, name, value)
    if not ok:
        print(f'configsys: {note}', file=sys.stderr)
        return 1
    if label == actions.PRETEND_NOT_SAVED:
        print(f'configsys: [pretend] would pin {name} -> {value} in your top config')
        return 0
    print(f'configsys: pinned {name} -> {value} (local, in {label})')
    if note:
        print(f'  note: {note}')
    _swap_headsup(ctx, name, value)
    return 0


def _swap_headsup(ctx, name, value):
    '''If `name` is currently installed via a method OTHER than the just-pinned `value`, say so — the
    next install/upgrade queues a remove-then-reinstall (method-switch swap), no surprise at execute.'''
    try:
        ctx.invalidate()                 # re-read config so the new pin drives resolution
        from ..installState import superseded_installs
        units, roots = ctx.routes.resolve_with_roots([name])
        for key in roots:
            for old_rc, ver in superseded_installs(ctx, units[key]):
                print(f'  note: {name} is still installed via {old_rc.via} ({ver}); '
                      f'`configsys install {name}` will remove that and reinstall via {value}.')
    except Exception:                    # noqa: BLE001 — a heads-up must never fail the pin
        pass


def _pin_unset(ctx, name):
    from .. import actions
    changed, label = actions.unset_pin(ctx, name)
    if label == actions.PRETEND_NOT_SAVED:
        print(f'configsys: [pretend] would unpin {name}')
        return 0
    if not changed:
        print(f'configsys: {name} is {label}', file=sys.stderr)
        return 1
    print(f'configsys: unpinned {name} (in your {label})')
    return 0


def _pin_promote(ctx, name):
    '''Move a top-config pin up into the primary plugin, so it travels to other machines.'''
    from .. import actions
    ok, msg = actions.promote_pin(ctx, name)
    print(f'configsys: {msg}', file=None if ok else sys.stderr)
    if ok and not ctx.runner.pretend:
        print('  it travels to your other machines with the primary (`configsys plugin push`)')
    return 0 if ok else 1


def cmd_pin(ctx, args):
    sub = getattr(args, 'pin_command', None) or 'list'
    if sub == 'list':
        return _pin_list(ctx)
    if sub == 'set':
        return _pin_set(ctx, args.component, args.via)
    if sub == 'unset':
        return _pin_unset(ctx, args.component)
    if sub == 'promote':
        return _pin_promote(ctx, args.component)
    return _pin_list(ctx)


def cmd_machine(ctx, args):
    '''View or edit machines — the columns of the matrix, i.e. the keys of `picks:`.'''
    from .. import actions
    cfg = ctx.config
    sub = getattr(args, 'machine_command', None) or 'list'

    if sub == 'list':
        names = cfg.machine_names()
        here = cfg.selected_machine()
        if not names:
            print('configsys: no machines defined (create one: `configsys machine add <name>`)')
            if here:
                print(f'  note: `machine: {here}` is selected but undefined')
            return 0
        picks = cfg.picks()
        for name in names:
            mark = '*' if name == here else ' '
            print(f' {mark} {name}   tracked: {len(picks.get(name, []))}')
        print('\n  * = this box (`machine:`). Curate another with `--machine <name>`; edit with '
              '`configsys machine add|rm|use`.')
        return 0

    if sub == 'show':
        if args.name not in cfg.machine_names():
            print(f'configsys: machine "{args.name}" is not defined', file=sys.stderr)
            return 1
        print(f'machine {args.name}' + ('   [this box]' if args.name == cfg.selected_machine() else ''))
        tracked = sorted(cfg.picks().get(args.name, []))
        print(f'  tracked ({len(tracked)}): {", ".join(tracked) if tracked else "(none)"}')
        return 0

    if ctx.runner.pretend:
        if sub == 'add':
            name = (args.name or '').strip()
            if name in cfg.machine_names():
                print(f'configsys: machine "{name}" already exists')
                return 1
            _pretend_edit(ctx, f'create machine "{name}"  (in {actions._picks_target(ctx, name)[1]})')
        elif sub == 'rm':
            if args.name not in cfg.machine_names():
                print(f'configsys: machine "{args.name}" is not defined')
                return 1
            force = getattr(args, 'force', False)
            this_box = args.name == (cfg.configured_machine() or 'this-machine')
            if this_box and not force:
                print(f'configsys: machine "{args.name}" is this box; `configsys machine use <other>` '
                      'first (or --force, which also clears `machine:`)', file=sys.stderr)
                return 1
            _pretend_edit(ctx, f'remove machine "{args.name}" (its picks column)'
                          + (' and clear `machine:`' if this_box and cfg.configured_machine() else ''))
        elif sub == 'use':
            label = actions._setting_target(ctx, 'machine')[1]
            _pretend_edit(ctx, f'make this box machine "{args.name}"  (in {label})' if args.name
                          else f'clear the machine selection  (in {label})')
        return 0
    ctx.ensure_user_config()
    if sub == 'add':
        changed, label = actions.add_machine(ctx, args.name)
        print(f'configsys: machine "{args.name}" created (in {label})' if changed
              else f'configsys: {label}')
        return 0 if changed else 1
    if sub == 'rm':
        changed, label = actions.remove_machine(ctx, args.name, force=getattr(args, 'force', False))
        print(f'configsys: {label}', file=sys.stdout if changed else sys.stderr)
        return 0 if changed else 1
    if sub == 'use':
        changed, label = actions.set_machine_active(ctx, args.name)
        if args.name:
            print(f'configsys: this box is now machine "{args.name}"  (in {label})' if changed
                  else f'configsys: already machine "{args.name}"')
        else:
            print(f'configsys: machine selection cleared  (in {label})' if changed
                  else 'configsys: no machine was selected')
        return 0
    return 0


def cmd_profile(ctx, args):
    '''Browse the shipped profile catalog (read-only). Profiles are BROWSE lenses over the
    repo/plugin catalog — the matrix model installs from `picks:` (see `configsys picks`), so there
    is no profile authoring or active set to edit here.'''
    sub = getattr(args, 'profile_command', None) or 'list'

    cfg = ctx.config
    if sub == 'list':
        names = cfg.profile_names()
        if not names:
            print('configsys: no profiles defined')
            return 0
        for name in names:
            try:
                members = cfg.profile_components(name)
                body = ', '.join(members) if members else '(empty)'
            except ConfigError as e:
                body = f'(error: {e})'
            print(f'  {name}\n      {body}')
        print('\n  Profiles are read-only browse lenses. Track components with '
              '`configsys picks add <component> [--machine <name>]`.')
        return 0

    if sub == 'show':
        if args.profile not in cfg.profile_names():
            print(f'configsys: profile {args.profile!r} is not defined', file=sys.stderr)
            return 1
        src = cfg.profile_source(args.profile)
        print(f'profile {args.profile}   [browse lens]')
        print(f'  defined in  {_layer_label(src, ctx.paths) if src else "?"}')
        try:
            for kind, ref in cfg.profile_layout(args.profile):
                print(f'    {"+include " if kind == "include" else "component"}  {ref}')
            members = cfg.profile_components(args.profile)
            print(f'  expands to ({len(members)}): {", ".join(members) if members else "(empty)"}')
        except ConfigError as e:
            print(f'  error: {e}', file=sys.stderr)
            return 1
        return 0
    return 0
