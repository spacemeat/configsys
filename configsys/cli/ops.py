'''cli/ops.py — the operation verbs — inspect, install, remove, upgrade, lock, unlock, set-version,
fix-scope, uninstall, updates / upgrade --system — and the plan confirm + failure reporting around them.

Split out of app.py (review-2026-11-2 D2).
'''

import argparse
import sys
from ..errors import ConfigsysError
from ..drivers import get_driver
from ..ledger import Ledger
from .common import _install_scope_label, _pretend_edit, ask, print_reboot_advisory
from .issues import cmd_report
from .refresh import maybe_refresh_before_plan, refresh_native_index


def cmd_inspect(ctx, args):
    _cfg, requested, units, _ledger, states = ctx.load_pipeline()
    print(f'OS: {ctx.os_info.block}   install set: {_install_scope_label(_cfg)}   '
          f'units: {len(units)}')
    print()
    print(f'{"UNIT":30} {"STATUS":12} {"INSTALLED":20} {"LATEST"}')
    print('-' * 78)
    for key in sorted(states):
        s = states[key]
        lock = ' [locked]' if s.locked else ''
        na = '?' if s.untrusted else '-'      # untrusted: unknown (can't read without the driver)
        print(f'{key:30} {s.status:12} '
              f'{str(s.installed_version or na):20} {s.latest_version or na}{lock}')
        from ..stranded import REASON_TEXT, stranded_reasons
        strand = stranded_reasons(s)
        for via, pkg, ver in s.also_present:   # coexisting installs via OTHER (unmanaged) methods
            if (via, pkg) in strand:           # routes don't offer it here: repin AWAY from it
                print(f'{"":30} also present: {via} {ver}  ({pkg}) — stranded '
                      f'({REASON_TEXT[strand[(via, pkg)]]}); `configsys install {s.component.comp}` '
                      f'swaps it out')
            else:
                print(f'{"":30} also present: {via} {ver}  ({pkg}) — `pin {s.component.comp} {via}` to manage')
        if s.recipe_behind:
            from ..installState import recipe_pin_text
            print(f'{"":30} [R] {recipe_pin_text(s.latest_version, s.upstream_version)}')
    # non-fatal skips/warnings that would otherwise go unseen (dropped layers, quarantined
    # plugins, unroutable components, ...) — the same set the TUI shows on its `!` page.
    diags = ctx.diagnostics(states)
    if diags:
        print(f'\n{len(diags)} issue(s):')
        for d in diags:
            mark = '✗' if d['level'] == 'error' else '⚠'
            print(f'  {mark} {d["tag"]:12} {d["text"]}')
    return 0


def _expand_profile_args_detail(ctx, names):
    '''Expand any `profile:<name>` token to that profile's components (order-preserving, deduped);
    bare tokens pass through as component names. The `profile:` prefix disambiguates from a
    component of the same name. Also says WHICH names came only from a `profile:` expansion (not
    named explicitly) — those may be skipped when they can't install here. Returns (names,
    from_profile), or None on a bad profile (after printing the error).'''
    out, seen, explicit, from_profile = [], set(), set(), set()

    def add(c, via_profile=False):
        (from_profile if via_profile else explicit).add(c)
        if c not in seen:
            seen.add(c)
            out.append(c)

    for tok in names:
        if tok.startswith('profile:'):
            pname = tok[len('profile:'):]
            if not pname:
                print('configsys: empty profile name (use `profile:<name>`)')
                return None
            try:
                members = ctx.config.profile_components(pname)
            except ConfigsysError as e:
                print(f'configsys: {e}')
                return None
            for c in members:
                add(c, via_profile=True)
        else:
            add(tok)
    return out, from_profile - explicit


def _skip_unroutable_profile_members(ctx, names, from_profile):
    '''Drop profile-expanded members that have no install route on this machine (no binding here, an
    unmet hard requirement) with ONE notice line, so `install profile:terminal` installs what it can
    instead of aborting on one Arch-only member. Explicitly named components are never skipped —
    they still error loudly.'''
    cand = [n for n in names if n in from_profile]
    if not cand:
        return names
    try:
        _units, errs = ctx.routes.resolve_resilient(cand)
    except Exception:                                # noqa: BLE001 — let the normal path report it
        return names
    bad = [n for n in cand if n in (errs or {})]
    if bad:
        print(f'configsys: skipped {len(bad)} not installable here: {", ".join(bad)}  '
              '(`configsys where <name>` says why)')
    return [n for n in names if n not in bad]


def _confirm_plan(ctx, plan, *, yes=False):
    '''Show a multi-op plan and ask before running it (the --picks runs). True = go. --yes skips
    the question; --pretend runs without asking (nothing happens anyway); a non-interactive run
    without --yes stops, like `upgrade --system`.'''
    print(f'\nplan ({len(plan)} op{"" if len(plan) == 1 else "s"}):')
    for op, key, _rc in plan:
        print(f'  {op:12} {key}')
    go = ask(f'\nRun these {len(plan)} op(s) now? [y/N] ', yes=yes or getattr(ctx.runner, 'pretend', False),
             refuse_note='\nconfigsys: re-run with --yes to apply this plan non-interactively.')
    if go is False:
        print('Aborted — nothing changed.')
    return bool(go)


def _dispatch_op(ctx, names, op, *, ledger=None, version=None, no_deps=False, confirm=False,
                 yes=False, with_deps=False):
    if ledger is None:
        ledger = Ledger.load(ctx.paths)      # every op writes it now: locks, and install receipts
    got = _expand_profile_args_detail(ctx, names)
    if got is None:
        return 1
    names, from_profile = got
    if op != 'remove':                       # a remove still looks for stranded installs (below)
        names = _skip_unroutable_profile_members(ctx, names, from_profile)
        if not names:
            print('configsys: nothing installable here in that selection')
            return 1
    stranded_removes = []
    if op == 'remove':
        # a component with no install method here any more (dangling/unmet) can't resolve — but
        # if it's still installed via a stranded method (receipt / AUR heuristic / gated binding),
        # removing THAT install is exactly what the user asked for
        from .. import probecache, stranded
        cache = probecache.of(ctx)                    # one `pacman -Qm` for the whole loop, not one per name
        routable, skipped = [], []
        for n in names:
            try:
                ctx.routes.resolve_names([n])
                routable.append(n)
            except Exception:                        # noqa: BLE001 — unroutable: look for a stranded install
                found = stranded.find(ctx, n, ledger=ledger, foreign=stranded.foreign_index(ctx, cache))
                if found:
                    stranded_removes += [('remove', s_.key, s_.rc) for s_ in found]
                elif n in from_profile:
                    skipped.append(n)                # a profile member with nothing here to remove
                else:
                    routable.append(n)               # let the normal path report it
        if skipped:
            print(f'configsys: skipped {len(skipped)} not installable here: {", ".join(skipped)}')
        names = routable
    from .. import actions
    if names:
        units, roots = actions.resolve_targets(ctx, names)    # honors adopted installs (B1)
    else:
        units, roots = {}, set()
    if not roots and not stranded_removes:
        print(f'configsys: nothing resolved for {names}')
        return 1
    ctx.prepare_units(units)
    if op == 'set-version':
        # no surprises: a method that can't target a version (tarball/appImage/font/...) would just
        # reinstall the routed one and report ok — refuse BEFORE anything (deps included) runs.
        from .. import actions
        for key in sorted(roots):
            rc = units[key]
            drv = get_driver(rc.driver, ctx.runner, ctx.paths)
            if drv is not None and not actions.targets_version(drv):
                print(f'configsys: set-version {rc.comp}: '
                      f'{actions.no_version_target_message(rc.via or rc.driver, rc.comp)}',
                      file=sys.stderr)
                return 1
    # Apply the requested op to the *named* units; expand_plan folds in dependency
    # installs (e.g. apt\flatpak before flatpak\firefox) and orders the whole thing.
    base_plan = [(op, key, units[key]) for key in sorted(roots)]
    for step in stranded_removes:
        base_plan.append(step)
        units[step[1]] = step[2]
    # ONE plan builder for both surfaces (actions.build_plan): --no-deps = only the named units (a
    # source component rebuilds just itself); else auto-tighten, the method-switch swap, and only the
    # MISSING dependencies folded in (--with-deps re-runs the whole tree). Floor heads-ups come back
    # to show BEFORE anything runs.
    plan, units, advisories = actions.build_plan(ctx, base_plan, units, no_deps=no_deps,
                                                 with_deps=with_deps)
    for text in advisories:
        print(f'configsys: heads-up — {text}', file=sys.stderr)
    if confirm and not _confirm_plan(ctx, plan, yes=yes):
        return 1
    maybe_refresh_before_plan(ctx, plan)     # refresh the OS index once up front (see the setting)
    result = actions.run_plan(ctx, plan, ledger=ledger, version=version)   # the shared op loop
    actions.after_run(ctx, result.outcomes, units)
    if result.failures:
        _offer_report(ctx, result.failures, fatal=result.n_fatal)
    if op in ('install', 'upgrade', 'set-version') and getattr(ctx, 'config', None) is not None \
            and ctx.config.reboot_advice():
        print_reboot_advisory(ctx)     # "reboot advised / N services need restart", per the native check
    return result.rc_code


def _failure_open(rec, states):
    '''Is a saved failure still unresolved, judged against the current install state? A later op on
    the unit drops its record (reportgen.record_run); this also hides one the system has since made
    moot by other means — the install that failed is present now, the upgrade is current, the remove
    is gone. With no states (nothing inspected) every record shows. A unit outside the inspected set
    (the pick was dropped) is hidden; a System Updates bulk failure always shows.'''
    unit = rec.get('unit') or ''
    if states is None or unit.startswith('system-updates\\'):
        return True
    st = states.get(unit)
    if st is None:
        return False
    op = rec.get('op')
    if op == 'install':
        return not st.present
    if op == 'upgrade':
        return not (st.present and not st.outdated)
    if op == 'remove':
        return st.present
    return True                                     # set-version / lock / unlock: until acted on again


def _failure_diagnostics(ctx, states):
    '''One ! line per unresolved op failure (reportgen.load_failures, minus the moot ones), naming the
    op, when, and why (actions.failure_excerpt), with the fix path. installed-with-a-warning records
    are skipped — the package is in; the run's summary already said so.'''
    from .. import reportgen
    from ..actions import failure_excerpt
    out = []
    for rec in reportgen.load_failures(ctx.paths):
        if rec.get('installed') == 'true' or not _failure_open(rec, states):
            continue
        unit = rec.get('unit') or rec.get('component') or '?'
        why = failure_excerpt(rec.get('output') or '')
        name = rec.get('component') or unit
        out.append(f"{unit}: {rec.get('op', 'op')} failed {rec.get('at', '')} (exit {rec.get('exit', '?')})"
                   + (f' — {why}' if why else '')
                   + f' — retry it, or file it: configsys report {name}')
    return out


def _offer_report(ctx, failures, fatal=None):
    '''The run's problems (real failures + installed-with-a-warning — run_plan has recorded them for
    `configsys report` and the ! page) — on a terminal, offer to file real failures now. `fatal` is
    how many are hard failures (None = treat all as fatal). Never fatal itself. A --pretend run
    records nothing: no last-failure.hu, no report offer — just a note of what would have failed.'''
    if not isinstance(failures, list):                    # tolerate a single record
        failures = [failures]
    if getattr(ctx.runner, 'pretend', False):
        names = [f['component'] for f in failures]
        print(f'\nconfigsys: [pretend] {", ".join(names)} would fail as shown above — nothing '
              'recorded (no report saved).')
        return
    fatal = len(failures) if fatal is None else fatal     # (run_plan already recorded them)
    if fatal == 0:                                        # only installed-with-warnings — note, don't push
        names = [f['component'] for f in failures]
        print(f'\nconfigsys: {", ".join(names)} installed with a warning — '
              '`configsys report` files the details.')
        return
    failures = [f for f in failures if not f.get('installed')]   # offer on the real failures
    names = [f['component'] for f in failures]
    n = len(failures)
    who = names[0] if n == 1 else f'{n} components ({", ".join(names)})'
    tail = names[0] if n == 1 else ''                     # `report` with no name files them all
    go = ask(f'\nfile a report of {"this" if n == 1 else "these"} {who} failure{"" if n == 1 else "s"}? [y/N] ',
             refuse_note=f'\nconfigsys: {who} failed — run `configsys report {tail}`'.rstrip()
             + ' to file a report.')
    if go is None:
        return
    if go:
        # no name -> report all saved failures; the saved list is what report reads
        nm = names[0] if n == 1 else None
        cmd_report(ctx, argparse.Namespace(name=nm, yes=False, print_only=False))
    else:
        hint = names[0] if n == 1 else '<name>` for one, or `configsys report'
        print(f'configsys: saved — `configsys report {hint}` files {"it" if n == 1 else "them"} later.')


def cmd_fix_scope(ctx, args):
    '''Reconcile installed units whose ACTUAL scope differs from their DECLARED scope — make the
    install match the config (never edits the config). No args = every mismatched active unit.
    Each step uninstalls at one scope and reinstalls at the other, so the moves are shown and
    confirmed first (app-cli-26) — --yes skips the question, a non-terminal without it stops.'''
    from .. import actions
    _cfg, _req, _units, ledger, states = ctx.load_pipeline()
    names = set(getattr(args, 'names', None) or [])
    plan, moves = [], []
    for key in sorted(states):
        st = states[key]
        rc = st.component
        if not st.present or not st.scope:
            continue
        if names and rc.comp not in names and key not in names:
            continue
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None or not drv.honors_scope or st.scope == drv.scope(rc):
            continue                                  # one fixed scope, or already where it's declared
        plan.append(('fix-scope', key, rc))
        moves.append(f'  {key}: installed at {st.scope} scope -> declared {drv.scope(rc)}')
    if not plan:
        print('configsys: no scope mismatches to fix')
        return 0
    print('configsys: scope moves (each uninstalls, then reinstalls at the declared scope):')
    print('\n'.join(moves))
    if not _confirm_plan(ctx, plan, yes=getattr(args, 'yes', False)):
        return 1
    # ONE run_plan batch (D3): the up-front sudo, the guard, ^C, every failure recorded for `report`
    result = actions.run_plan(ctx, plan, ledger=ledger)
    if result.failures:
        _offer_report(ctx, result.failures, result.n_fatal)
    return result.rc_code


def _picks_selection(ctx, op):
    '''For `install --picks` / `upgrade --picks`: (names, error_rc). The component names of THIS
    box's picks that need `op` — not installed (install) or outdated (upgrade) — from a full inspect.
    Picks with no install method here are skipped with the same one-line notice as a profile:
    expansion. Refuses (error_rc=1) when --machine names another machine: installs only ever happen
    on this box, so curating machine X's set from here must not install X's picks here.'''
    other = ctx.curating_machine()
    if other:
        print(f'configsys: --picks acts on THIS box ("{ctx.own_machine()}"), but --machine names '
              f'"{other}" — installs never happen for another machine here. Drop '
              '--machine (or run this on that machine).', file=sys.stderr)
        return None, 1
    _cfg, requested, _units, _ledger, states = ctx.load_pipeline()
    picked = list(requested)
    unroutable = sorted(set(ctx.resolve_errors or {}) | set(getattr(ctx, 'route_classes', None) or {}))
    unroutable = [n for n in unroutable if n in picked]
    if unroutable:
        print(f'configsys: skipped {len(unroutable)} not installable here: {", ".join(unroutable)}  '
              '(`configsys where <name>` says why)')
    want = 'missing' if op == 'install' else 'outdated'
    need = {s.component.comp for s in states.values() if s.status == want}
    return [n for n in picked if n in need], 0


def _merge_names(explicit, extra):
    out = list(explicit or [])
    out += [n for n in extra if n not in out]
    return out


def _ops_from_picks(ctx, args, op):
    '''The shared `--picks` front half of cmd_install / cmd_upgrade: (names, rc) where rc is not
    None when the command should stop now (refused, or nothing to do).'''
    sel, err = _picks_selection(ctx, op)
    if err:
        return None, err
    names = _merge_names(args.names, sel)
    if not names:
        print('configsys: nothing to do — every pick of this box is '
              + ('installed' if op == 'install' else 'up to date (locked picks are left alone)'))
        return None, 0
    return names, None


def cmd_install(ctx, args):
    ctx.paths.dotfiles_force = getattr(args, 'force', False)   # read by the dotfiles driver
    ctx.paths.install_force = getattr(args, 'force', False)    # a dir/file configsys didn't make (A6/A9)
    ctx.paths.source_adopt = getattr(args, 'adopt', False)     # build in your own checkout (A9)
    names, confirm = args.names, False
    if getattr(args, 'picks', False):
        names, rc = _ops_from_picks(ctx, args, 'install')
        if rc is not None:
            return rc
        confirm = True
    elif not names:
        print('configsys: `install` needs component name(s), or `--picks` for every uninstalled pick')
        return 1
    return _dispatch_op(ctx, names, 'install', no_deps=getattr(args, 'no_deps', False),
                        with_deps=getattr(args, 'with_deps', False),
                        confirm=confirm, yes=getattr(args, 'yes', False))


def cmd_remove(ctx, args):
    return _dispatch_op(ctx, args.names, 'remove')


def cmd_upgrade(ctx, args):
    if getattr(args, 'system', False):
        return cmd_upgrade_system(ctx, args)
    names, confirm = args.names, False
    if getattr(args, 'picks', False):
        names, rc = _ops_from_picks(ctx, args, 'upgrade')
        if rc is not None:
            return rc
        confirm = True
    elif not names:
        print('configsys: `upgrade` needs component name(s), `--picks` for every outdated pick, or '
              '`--system` to upgrade the whole system')
        return 1
    ctx.paths.dotfiles_force = getattr(args, 'force', False)
    ctx.paths.install_force = getattr(args, 'force', False)
    return _dispatch_op(ctx, names, 'upgrade', no_deps=getattr(args, 'no_deps', False),
                        with_deps=getattr(args, 'with_deps', False),
                        confirm=confirm, yes=getattr(args, 'yes', False))


_TIER_LABEL = {'kernel': 'kernel', 'core': 'core (base system)',
               'standard': 'standard', 'apps': 'apps & tools'}


def _print_updates_groups(groups):
    '''Shared rendering for `updates` and the `upgrade --system` preview: per-manager sections,
    sub-grouped by tier (kernel/core/standard/apps — most-fundamental first), a `installed ->
    candidate` line per package and a [held] marker. Returns the total row count.'''
    from ..driver import UPDATE_TIERS
    total = sum(len(v) for v in groups.values())
    for mgr in sorted(groups):
        rows = groups[mgr]
        held = sum(1 for r in rows if r.held)
        tail = f'  ({held} held, left as-is)' if held else ''
        print(f'{mgr}  ({len(rows)}){tail}:')
        for tier in UPDATE_TIERS:
            trows = [r for r in rows if r.tier == tier]
            if not trows:
                continue
            print(f'  {_TIER_LABEL[tier]}  ({len(trows)}):')
            for r in trows:
                frm = f'{r.installed} -> ' if r.installed else ''
                mark = '  [held]' if r.held else ''
                print(f'    {r.key:40} {frm}{r.candidate or "?"}{mark}')
        print()
    return total


def cmd_updates(ctx, args):
    '''List everything the machine's package managers report upgradable OUTSIDE the tracked picks —
    the System Updates lane. Read-only; `configsys upgrade --system` applies it.'''
    from .. import sysupdates
    notes = []
    groups = sysupdates.gather(ctx, notes)
    if not groups:
        print('configsys: no system updates — every package manager reports up to date.\n'
              '(Run `configsys refresh` first if the index may be stale.)')
        _print_update_notes(notes)
        return 0
    print('System updates — packages upgradable outside your picks '
          '(these are each manager\'s own report, not tracked components):\n')
    total = _print_updates_groups(groups)
    print(f'{total} package(s) across {len(groups)} manager(s). '
          'Apply with `configsys upgrade --system`.')
    _print_update_notes(notes)
    return 0


def _print_update_notes(notes):
    '''Each manager's upgradable_advisory (a list that may be incomplete), after the update list.'''
    for n in notes:
        print(f'  ⚠ {n}')


def cmd_upgrade_system(ctx, args):
    '''Apply the System Updates lane: run each manager's OWN bulk upgrade (apt upgrade / flatpak
    update / snap refresh) for everything upgradable outside your picks. Previews first, confirms,
    then ends with the reboot advisory. Held/masked packages are left held by the managers.'''
    from .. import sysupdates
    # Refresh the native index up front so candidates are current (non-fatal), same as an ops batch.
    print('Refreshing the package index…', flush=True)
    ran, ok = refresh_native_index(ctx)
    if ran and not ok:
        print('  ⚠ index refresh hit a problem — proceeding on the cached index '
              '(run `configsys refresh` to diagnose)')
    notes = []
    groups = sysupdates.gather(ctx, notes)
    if not groups:
        print('\nconfigsys: no system updates to apply — everything is up to date.')
        _print_update_notes(notes)
        return 0
    print()
    total = _print_updates_groups(groups)
    _print_update_notes(notes)
    print(f'{total} package(s) across {len(groups)} manager(s) will be upgraded via each '
          "manager's own bulk command.")
    go = ask('\nApply all system updates now? [y/N] ', yes=getattr(args, 'yes', False),
             refuse_note='\nconfigsys: re-run with --yes to apply system updates non-interactively.')
    if not go:
        if go is False:
            print('Aborted — nothing upgraded.')
        return 1
    # the SAME apply step the TUI runs (sysupdates.apply_bulk: the per-manager outcomes, the failure
    # record for the ! page and `configsys report`, ^C), inside one sudo session so the keep-alive a
    # sudo'd bulk command warms is released when it ends (B17 / app-cli-05 / actions-14)
    with ctx.runner.sudo_session():
        result = sysupdates.apply_bulk(ctx, sorted(groups), refresh=False,
                                       on_start=lambda m: print(f'\n── upgrading via {m} ──'))
    rc_code, failures = result.rc_code, result.failures
    if failures:
        _offer_report(ctx, failures)
    if getattr(ctx, 'config', None) is not None and ctx.config.reboot_advice():
        print_reboot_advisory(ctx)
    return rc_code


def cmd_lock(ctx, args):
    return _dispatch_op(ctx, args.names, 'lock', ledger=Ledger.load(ctx.paths))


def cmd_unlock(ctx, args):
    return _dispatch_op(ctx, args.names, 'unlock', ledger=Ledger.load(ctx.paths))


def cmd_set_version(ctx, args):
    return _dispatch_op(ctx, [args.name], 'set-version', version=args.version)


def cmd_tui(ctx, args):
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        print('configsys: not an interactive terminal; showing inspection instead.\n')
        return cmd_inspect(ctx, args)
    try:
        from ..tui import run as run_tui
    except ImportError:
        print('configsys: TUI not available; showing inspection instead.\n')
        return cmd_inspect(ctx, args)
    return run_tui(ctx)


def cmd_uninstall(ctx, args):
    '''The machine-local `uninstall:` queue (TUI `x`): list / add / rm / clear. A staged removal runs
    with the next execute (TUI `X`) or `configsys remove` (run_plan drains it).'''
    from .. import actions
    sub = getattr(args, 'uninstall_command', None) or 'list'
    queue = sorted(ctx.config.uninstall_queue())
    if sub == 'list':
        print('\n'.join(f'  - {c}' for c in queue) if queue else 'configsys: nothing staged for removal')
        return 0
    if sub == 'clear':
        if ctx.runner.pretend:
            _pretend_edit(ctx, f'unstage {len(queue)} removal(s)')
            return 0
        print(f'configsys: unstaged {actions.clear_uninstall(ctx)} removal(s)')
        return 0
    known = set(ctx.routes.components)
    rc = 0
    for name in args.names:
        if sub == 'add' and name not in known:
            print(f'configsys: {name!r} is not a known component', file=sys.stderr)
            rc = 1
            continue
        if ctx.runner.pretend:
            _pretend_edit(ctx, f'{"stage" if sub == "add" else "unstage"} {name} for removal')
            continue
        ctx.ensure_user_config()
        changed, _label = actions.stage_uninstall(ctx, name, on=(sub == 'add'))
        print(f'configsys: {name} {"staged for removal" if sub == "add" else "unstaged"}' if changed
              else f'configsys: no change — {name} already {"staged" if sub == "add" else "not staged"}')
    return rc
