'''cli/dotfiles.py — `dotfiles …` and `glue …` (status, capture, staged/activate/discard, add, override).

Split out of app.py (review-2026-11-2 D2).
'''

import os
import sys
from pathlib import Path
from .. import shellguard
from ..drivers import get_driver
from ..errors import ConfigError
from .common import _install_scope_label, ask


_GLUE_ORDER = ['loader-on', 'linked', 'drifted', 'template', 'loader-off']   # glue states, active-first (drifted = active but shipped source changed)


def _dotfiles_diagnostics(ctx):
    '''[(tag, text)] warn-only hygiene over the active via:dotfiles units — un-captured managed
    config (#5) and any link still pointing into the repo (#4). Fully guarded: a dotfiles issue
    must never break the diagnostics pass.'''
    out = []
    try:
        from .. import actions
        _df, units = actions.dotfiles_units(ctx)     # resolution only: cheap, side-effect-free
        for rc in units:                         # glue.warnings is empty; config warns live on dotfiles
            out.extend(get_driver(rc.driver, ctx.runner, ctx.paths).warnings(rc))
    except Exception:
        pass
    return out


def cmd_dotfiles(ctx, args):
    cmd = getattr(args, 'dotfiles_command', None) or 'status'
    if cmd == 'capture':
        return cmd_dotfiles_capture(ctx, args)
    if cmd == 'staged':
        return cmd_dotfiles_staged(ctx, args)
    if cmd == 'activate':
        return cmd_dotfiles_activate(ctx, args)
    if cmd == 'discard':
        return cmd_dotfiles_discard(ctx, args)
    return cmd_dotfiles_status(ctx, args)


def _default_glue_shell(ctx):
    '''The shell `glue add` targets by default: the user's login shell ($SHELL) when it's a known
    glue shell, else bash.'''
    from ..drivers.glue import _GLUE_SHELLS
    sh = os.path.basename((ctx.env.get('SHELL') or '').strip())
    return sh if sh in _GLUE_SHELLS else 'bash'


def _open_in_editor(path):
    '''Open `path` in $VISUAL/$EDITOR on a terminal; otherwise just print where it is.'''
    import shlex as _shlex
    import subprocess
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    if editor and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            subprocess.run([*_shlex.split(editor), str(path)])
            return
        except Exception:                                # noqa: BLE001 — fall back to just naming it
            print('  (could not launch $EDITOR — edit it yourself)')
    print(f'  edit it: {path}')


def cmd_glue(ctx, args):
    cmd = getattr(args, 'glue_command', None)
    if cmd == 'add':
        return cmd_glue_add(ctx, args)
    if cmd == 'override':
        return cmd_glue_override(ctx, args)
    if cmd == 'staged':
        return cmd_dotfiles_staged(ctx, args)
    if cmd == 'activate':
        return cmd_dotfiles_activate(ctx, args)
    if cmd == 'discard':
        return cmd_dotfiles_discard(ctx, args)
    print('usage: configsys glue {add <name> | override <comp> | staged | activate <comp> | discard <comp>}')
    return 1


def _resolve_glue_unit(ctx, name):
    '''The glue unit (ResolvedComponent, driver=="glue", with snippet specs) for `name` — accepting
    the tool name (its suggested -glue companion) or the -glue component directly. None if none.'''
    drv = get_driver('glue', ctx.runner, ctx.paths)

    def glue_units(nm):
        try:
            units, _e = ctx.routes.resolve_resilient([nm])
        except Exception:                                # noqa: BLE001
            return []
        return [rc for rc in units.values() if rc.driver == 'glue' and drv.specs(rc)]

    for candidate in (name, f'{name}-glue'):
        units = glue_units(candidate)
        if not units:
            continue
        # prefer the unit whose comp is exactly the name or <name>-glue; else the first
        for rc in units:
            if rc.comp in (name, f'{name}-glue'):
                return rc
        return units[0]
    return None


def cmd_glue_override(ctx, args):
    '''Fork a component's shipped glue into the user's layer (primary if set, else local), open the
    copies in $EDITOR, and redeploy so they shadow the repo. Records the forked-from hash so `check`
    can flag when the shipped version later moves on.'''
    drv = get_driver('glue', ctx.runner, ctx.paths)
    rc = _resolve_glue_unit(ctx, args.comp)
    if rc is None:
        print(f'configsys: no glue found for {args.comp!r} (try the tool name or its -glue component)')
        return 1
    portable = (getattr(ctx.paths, 'primary_glue_dir', None) is not None) and not args.local
    if ctx.runner.pretend:
        print(f'[pretend] would fork {rc.comp} glue into the '
              f'{"primary plugin (portable)" if portable else "local store"} and redeploy')
        return 0
    forked = drv.override(rc, shell=args.shell, local=args.local)
    if not forked:
        print(f'configsys: {rc.comp} ships no glue snippet for '
              f'{args.shell or "your installed shells"} to override')
        return 1
    print(f'forked {rc.comp} glue into the {"primary plugin (portable)" if portable else "local store"}:')
    for path, shell in forked:
        print(f'  [{shell}] {path}')
    for path, _shell in forked:
        _open_in_editor(path)
    res = drv.install(rc)                                  # redeploy — the override wins by search path
    if res is not None and not res.ok:
        print(f'configsys: redeploy failed: {res.output or res.returncode}')
        return 1
    print(f'{rc.comp} now uses your override (edit the files above anytime; '
          f'`configsys check` flags if the shipped version later changes).')
    if not portable and not args.local:
        print('  (saved locally — `configsys plugin bless <source>` sets a primary so it travels.)')
    return 0


def cmd_glue_add(ctx, args):
    '''Create a user-owned startup snippet in the user-glue namespace (primary plugin if set, else the
    local store), open it in $EDITOR, and deploy it (linked into conf.d; inlined for gestalt shells).'''
    from ..drivers.glue import _GLUE_SHELLS
    drv = get_driver('glue', ctx.runner, ctx.paths)
    shell = args.shell or _default_glue_shell(ctx)
    if shell not in _GLUE_SHELLS:
        print(f'configsys: unknown shell {shell!r} — known: {", ".join(_GLUE_SHELLS)}')
        return 1
    dest = drv.dest_glue_root(local=args.local)
    if dest is None:
        print('configsys: no glue store to write to.')
        return 1
    portable = (getattr(ctx.paths, 'primary_glue_dir', None) is not None) and not args.local
    if ctx.runner.pretend:
        print(f'[pretend] would add {args.name} glue for {shell} under '
              f'{dest}/shell/{shell}/user.d/ ({"primary — portable" if portable else "local"})')
        return 0
    path, created = drv.new_user_snippet(args.name, shell, local=args.local)
    if path is None:
        print('configsys: could not create the snippet (bad shell or no store).')
        return 1
    print(f'{"created" if created else "opening existing"} {path.name} for {shell} '
          f'in the {"primary plugin (portable)" if portable else "local store"}')
    _open_in_editor(path)
    drv.deploy_user_glue(shell)                            # link into conf.d (+ refresh gestalt block)
    link = drv.user_glue_link(shell, path.name)
    print(f'linked into {drv.display_path(link) if link else path.name} — loads on your next '
          f'{shell} session.')
    if not portable and not args.local:
        print('  (saved locally — `configsys plugin bless <source>` sets a primary so your glue travels.)')
    return 0


def cmd_dotfiles_staged(ctx, args):
    '''List the glue candidates the shell-writes guard captured — each is an rc-file block an
    installer tried to write, held INACTIVE until you review and activate it.'''
    rows = shellguard.list_staged(ctx.paths)
    if not rows:
        print('no staged glue — nothing has tried to write your shell rc files.')
        return 0
    print(f'staged glue candidates (in {shellguard.stage_dir(ctx.paths)}):\n')
    for comp, shell, path in rows:
        body = path.read_text().strip().splitlines()
        print(f'  {comp} [{shell}]  ({len(body)} line(s))')
        for line in body:
            print(f'      {line}')
        print()
    print('activate: `configsys dotfiles activate <component>`   '
          'discard: `configsys dotfiles discard <component>`')
    return 0


def cmd_dotfiles_activate(ctx, args):
    '''Promote staged glue to your own USER glue: each block becomes a user.d snippet (primary plugin
    unless --local, else the local store — where `glue add` writes), linked into conf.d as
    90-<name>, and leaves staging.'''
    local = getattr(args, 'local', False)
    rc = 0
    for name in args.names:
        if ctx.runner.pretend:
            staged = shellguard.staged_for(ctx.paths, name)
            if not staged:
                print(f'{name}: nothing staged to activate.')
                rc = 1
                continue
            for shell, _path in staged:
                print(f'[pretend] would activate {name} as {shell} user glue'
                      f'{" (local)" if local else ""}')
            continue
        done = shellguard.activate(ctx.paths, name, ctx.runner, local=local)
        if not done:
            print(f'{name}: nothing staged to activate.')
            rc = 1
            continue
        for shell, link in done:
            print(f'{name}: activated as {shell} user glue -> {link}')
    return rc


def cmd_dotfiles_discard(ctx, args):
    rc = 0
    for name in args.names:
        if ctx.runner.pretend:
            n = len(shellguard.staged_for(ctx.paths, name))
            print(f'[pretend] would discard {n} staged candidate(s) for {name}' if n
                  else f'{name}: nothing staged.')
        else:
            n = shellguard.discard(ctx.paths, name)
            print(f'{name}: discarded {n} staged candidate(s)' if n else f'{name}: nothing staged.')
        rc = rc or (0 if n else 1)
    return rc


def _print_user_glue(drv, entries):
    '''The `user glue` table of `dotfiles status`: every user.d snippet (`glue add`, an activated
    staged block) per shell, whether its conf.d link is live, and where the snippet lives.'''
    if not entries:
        return
    disp = drv.display_path if drv is not None else str
    sw = max(len('SHELL'), *(len(e[0]) for e in entries))
    print('\n  user glue  (your own snippets: `configsys glue add`, activated staged blocks)')
    print(f'    {"STATE":8} {"SHELL":{sw}} LINK  ->  SNIPPET')
    for shell, snippet, link, state in entries:
        print(f'  {"!" if state != "linked" else " "} {state:8} {shell:{sw}} '
              f'{disp(link) if link else "-"}  ->  {disp(snippet)}')


def cmd_dotfiles_status(ctx, args):
    '''Show every via:dotfiles target for this machine's picks, split into the two state machines:
    CONFIG (content you own — a capture→link lifecycle) and GLUE (shipped shell integration — a
    ship→activate toggle: snippets + the per-shell conf.d loaders). Each row: state, target,
    component, and where its MANAGED content lives (or `→` where capture will put it). Content roots
    are labeled once up top so the SRC column stays short.'''
    from ..drivers.glue import GLUE_STATE_LABEL
    from ..drivers.dotfiles import config_display_state, CONFIG_STATES
    from ..drivers import get_driver
    from .. import actions
    df, units = actions.dotfiles_units(ctx)
    cfg, glue = [], []   # (state, target, component, src_root|None, src_rel, here)
    for rc in units:                             # dispatch per unit: config->dotfiles, glue->glue
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        cap = ({n: (action == 'copy') for n, _d, _de, action in drv.capture_plan(rc)}
               if hasattr(drv, 'capture_plan') else {})
        for st in drv.spec_states(rc):
            src_rel = st.src_rel if st.src_root is not None else ('rc hookup' if st.here else 'not hooked up')
            root = Path(st.src_root) if st.src_root is not None else None
            if st.kind == 'config':              # collapse to the 3 user-facing config states
                cfg.append((config_display_state(st.state, cap.get(st.name, False)), st.target, rc.comp,
                            root, src_rel, st.here))
            else:
                glue.append((st.state, st.target, rc.comp, root, src_rel, st.here))
    print(f'OS: {ctx.os_info.block}   install set: {_install_scope_label(ctx.config)}')
    gdrv = get_driver('glue', ctx.runner, ctx.paths)
    try:                                         # your own user.d snippets (`glue add`/activate) —
        user_glue = gdrv.user_glue_entries() if gdrv is not None else []   # visible, no surprises
    except Exception:                            # noqa: BLE001 — a status view never crashes on it
        user_glue = []
    if not cfg and not glue:
        print('\n(no dotfiles components in the install set)')
        _print_user_glue(gdrv, user_glue)
        return 0
    roots = {}                                   # distinct src roots -> label, listed once
    for r in cfg + glue:
        if isinstance(r[3], Path):
            roots.setdefault(r[3], ctx.paths.content_root_label(r[3]))
    print()
    for root, label in sorted(roots.items(), key=lambda kv: kv[1]):
        print(f'  {label:9} {df.display_path(root)}')

    def _section(title, rows, order, relabel, src_note):
        '''Print one group's table (columns sized to the group's content); return its
        underlying-state counts.'''
        if not rows:
            return {}
        rows = sorted(rows, key=lambda r: (order.index(r[0]) if r[0] in order else 99, str(r[1])))
        shown_of = lambda s: (relabel.get(s, s) if relabel else s)   # noqa: E731
        sw = max(len('STATE'), *(len(shown_of(r[0])) for r in rows))
        tw = max(len('TARGET'), *(len(str(r[1])) for r in rows))
        cw = max(len('COMPONENT'), *(len(r[2]) for r in rows))
        head = f'  {"":1} {"STATE":{sw}} {"TARGET":{tw}} {"COMPONENT":{cw}} SRC{src_note}'
        print(f'\n  {title}')
        print(head)
        print('  ' + '-' * (len(head) - 2))
        counts = {}
        for state, tgt, comp, src_root, src_rel, here in rows:
            counts[state] = counts.get(state, 0) + 1
            mark = '!' if state == 'unmanaged' else ' '
            src = (f'{"" if here else "→ "}{roots[src_root]}/{src_rel}'
                   if isinstance(src_root, Path) else src_rel)
            print(f'  {mark} {shown_of(state):{sw}} {str(tgt):{tw}} {comp:{cw}} {src}')
        return counts

    ccounts = _section('config  (content you own)', cfg, list(CONFIG_STATES), None,
                       '  (→ = on capture)')
    gcounts = _section('glue — shell integration  (shipped; never captured)', glue,
                       _GLUE_ORDER, GLUE_STATE_LABEL, '')
    _print_user_glue(gdrv, user_glue)
    gbuckets = {}
    for state, n in gcounts.items():
        lbl = GLUE_STATE_LABEL.get(state, state)
        gbuckets[lbl] = gbuckets.get(lbl, 0) + n
    csum = ', '.join(f'{ccounts[s]} {s}' for s in CONFIG_STATES if s in ccounts)
    gsum = ', '.join(f'{gbuckets[l]} {l}' for l in ('active', 'available', 'inactive') if l in gbuckets)
    parts = [p for p in (f'config: {csum}' if csum else '', f'glue: {gsum}' if gsum else '') if p]
    if parts:
        print('\n' + '   '.join(parts))
    if ccounts.get('unmanaged'):
        print('  ! unmanaged = needs action: capture (c) an on-system file, or link content '
              'that is ready — the SRC column says which.')
    return 0


def cmd_dotfiles_capture(ctx, args):
    '''Adopt existing on-system dotfiles into your content store (the primary plugin's dotfiles/,
    else ~/.config/configsys/dotfiles) so a later install links YOUR content, not a template.
    Read-only on the system side — it only copies FROM your dotfiles INTO the store; it never
    modifies or deletes an on-system file.'''
    from .. import actions
    df, units = actions.dotfiles_units(ctx)
    want = set(args.names or [])
    store = df.capture_root()
    units = [rc for rc in units if rc.driver == 'dotfiles']   # capture is config-only; glue is shipped
    if want:                                 # `btop` names its config companion `btop-dotfiles` too
        named = {n: [rc for rc in units if rc.comp in (n, f'{n}-dotfiles')] for n in sorted(want)}
        for n in (n for n, hit in named.items() if not hit):
            print(f'configsys: {n}: no config to capture — neither {n} nor {n}-dotfiles is a dotfiles '
                  f'component in this machine\'s picks (see `configsys dotfiles status`)')
        units = [rc for hit in named.values() for rc in hit]
        if not units:
            return 1
    is_plugin = (ctx.paths.primary_dotfiles_dir is not None
                 and Path(store) == Path(ctx.paths.primary_dotfiles_dir))
    plan, skips = [], []
    for rc in units:
        for _name, dst, dest, action in df.capture_plan(rc, force=args.force):
            (plan if action == 'copy' else skips).append((rc.comp, dst, dest, action))

    print(f'store: {df.display_path(store)}' + ('  (plugin)' if is_plugin else '  (local)'))
    if plan:
        print(f'\nwill capture {len(plan)} target(s):')
        for comp, dst, dest, _a in plan:
            print(f'  {df.display_path(dst):34} ->  {df.display_path(dest)}   [{comp}]')
    _SKIP_WHY = {'skip-linked': 'already managed', 'skip-absent': 'nothing on-system',
                 'skip-exists': 'already in store (--force to overwrite)'}
    for comp, dst, _dest, action in skips:
        print(f'  skip {df.display_path(dst):34} ({_SKIP_WHY.get(action, action)}) [{comp}]')
    if not plan:
        print('\nnothing to capture.')
        return 0
    if args.dry_run or ctx.runner.pretend:
        print('\n(dry run — nothing written)')
        return 0
    caveat = ' — committed if you push the plugin' if is_plugin else ''
    if not ask(f'\nCopy {len(plan)} target(s) into {df.display_path(store)}{caveat}? [y/N] ',
               yes=args.yes, refuse_note='\nconfigsys: not a terminal — re-run with --yes to capture.'):
        print('aborted.')
        return 1
    captured, failed = 0, 0
    for rc in units:
        try:
            captured += len(df.capture(rc, force=args.force))
        except (ConfigError, RuntimeError) as e:          # a hand-edited manifest.hu, a failed copy
            print(f'configsys: {rc.comp}: {e}', file=sys.stderr)
            failed += 1
    print(f'\ncaptured {captured} target(s) into {df.display_path(store)}.')
    return 1 if failed else 0
