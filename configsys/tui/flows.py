'''flows.py — the multi-step actions screens run — execute (confirm, run, report), the method/provider
pickers and pins, the primary push questions.

Split out of menu.py (review-2026-11-2 D2).
'''

from .. import primarygit, reportgen
from . import keyspec
from ..drivers import get_driver
from ..osversion import clean_version
from .screen import suspended
from ..actions import fail_detail as _fail_detail   # noqa: E402
from .modals import _input_box, _popup_choose
from .models import MenuState, _added_extras, _components_model, _describe, _is_system_update, _row_component
from .paint import _fit, _put


def _pretend_note(ctx, note, wrote):
    '''The status note after a config-EDITING key. Under --pretend every actions-level config writer
    refuses (returns actions.PRETEND_NOT_SAVED / 0 instead of writing), so a note built from the
    attempt ("x set", "no change", "3 tracked") would misreport it: say it wasn't saved, plus what it
    would have done when that's known. Unchanged when nothing was written or it isn't a dry run.'''
    if not wrote or not getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return note
    from ..actions import PRETEND_NOT_SAVED
    if note and '[pretend]' in note:                  # the writer's own message already says so
        return note
    return f'{PRETEND_NOT_SAVED} (--pretend)' + (f' — would: {note}' if note else '')


def execute_plan(ctx, plan, ledger, version=None, refresh=True):
    '''Run the plan through the SAME shared loop the CLI uses (actions.run_plan) — so the TUI gets
    set-version, the advisory "needs your input" outcome, verify-after-fail (installed-with-a-warning),
    and EVERY failure persisted for `configsys report`, not just the last one. Returns the OpOutcomes
    the summary/footer render.'''
    from ..cli.refresh import maybe_refresh_before_plan           # lazy: the cli imports the TUI
    from .. import actions
    if refresh:                                          # False: the caller refreshed for the batch
        maybe_refresh_before_plan(ctx, plan)
    result = actions.run_plan(ctx, plan, ledger=ledger, version=version)   # records its failures
    return result.outcomes


def _summary_note(outcomes):
    n_ok = sum(1 for o in outcomes if o.ok)
    n_adv = sum(1 for o in outcomes if getattr(o, 'advisory', False))
    n_bad = len(outcomes) - n_ok - n_adv
    parts = [f'{n_ok} ok']
    if n_bad:
        parts.append(f'{n_bad} failed')
    if n_adv:
        parts.append(f'{n_adv} need input')
    return ', '.join(parts)


def _with_uninstall_node(ctx, states, layouts, transitive):
    '''Fold the reserved `!uninstall` queue into the Components model: FRESH-inspect the queued
    components that aren't in the active set (orphans live outside it — and their install state must
    be current, not a reused cache, so a re-added leftover shows), then add a `!uninstall` node
    listing the PRESENT ones so their removals can be executed here. No-op when empty.'''
    try:
        q = list(ctx.config.uninstall_queue())
    except Exception:                               # noqa: BLE001
        return states, layouts, transitive
    if not q:
        return states, layouts, transitive
    have = {st.component.comp for st in states.values()}
    missing = [c for c in q if c not in have]
    if missing:
        try:
            states = {**states, **ctx.inspect_components(missing)}   # fresh probe (no reuse) — accuracy
        except Exception:                           # noqa: BLE001 — never let this brick the screen
            pass
    present = sorted(c for c in q
                     if any(st.component.comp == c and st.present for st in states.values()))
    if present:
        layouts = list(layouts) + [('!uninstall', present)]
        transitive = {**transitive, '!uninstall': present}
    return states, layouts, transitive


def _seed_uninstall(ms, ctx):
    '''Pre-stage a `remove` op for each PRESENT unit whose component is in the persisted `!uninstall`
    queue — so removals staged from TUI::Profiles (or a prior session) surface here and execute via
    the normal Components flow. Never overrides an already-staged op; failures are silent.'''
    try:
        q = ctx.config.uninstall_queue()
    except Exception:                               # noqa: BLE001
        return
    if not q:
        return
    for key, st in ms.states.items():
        if st.present and st.component.comp in q:
            ms.staged.setdefault(key, 'remove')


def _commit_primary_action(ctx, snap, screen, act, note):
    '''Commit what one TUI action changed in the primary (primarygit), as `<screen>: <action> — <note>`.
    Returns the notes to show (empty when it went through quietly or nothing changed).'''
    label = keyspec.Keymap.label(screen, act) if act else 'edit'
    return primarygit.commit(ctx, snap, f'{screen}: {label}' + (f' — {note}' if note else ''))


class _TuiPushUI(primarygit.PushUI):
    '''`primarygit.push`'s questions as popups over the current screen. git never prompts here (no
    terminal): an SSH key that needs a passphrase fails with a note saying how to fix it.'''

    def __init__(self, stdscr, pal):
        self.stdscr, self.pal = stdscr, pal

    def ask(self, q):
        '''A `primarygit.Question` as a popup: its title (with the first few listed items), its
        choices with their letters; Enter starts on the cautious answer, Esc gives it.'''
        # the same listing the CLI prints (Question.listing: the commits, then the FILES about to
        # leave — what shows a freshly captured dotfile holding a token; G5 / primary-15)
        body = q.listing() if q.kind in ('include-own', 'confirm-push') else []
        start = next((i for i, c in enumerate(q.choices) if c.answer == q.enter), 0)
        i = _popup_choose(self.stdscr, self.pal, q.title, [(c.label, c.key) for c in q.choices], start=start,
                          shortcuts={c.key: i for i, c in enumerate(q.choices)}, body=body)
        return q.choices[i].answer if i is not None else q.enter

    def edit(self, path):
        from ..cli.plugin import _edit_conflict
        from .screen import suspended
        with suspended(self.stdscr):
            _edit_conflict(path)

    def progress(self, text):
        h, w = self.stdscr.getmaxyx()
        _put(self.stdscr, h - 2, 0, _fit(f' {text}'.ljust(w), w), self.pal.style('status_line', h - 2, 0, h, w))
        self.stdscr.refresh()


class _TuiAutoPushUI(primarygit.PushUI):
    '''The no-questions push of `primary-push: auto` / `auto-on-quit` on quit: every question gets
    the cautious answer (your edits stay out, a conflict stops it unpushed) — only the progress line
    is painted.'''

    def __init__(self, stdscr, pal):
        self.stdscr, self.pal = stdscr, pal

    def progress(self, text):
        if self.stdscr is not None:
            _TuiPushUI.progress(self, text)


def _push_primary(stdscr, pal, ctx):
    '''Push the primary from the TUI (Plugins `P`, the quit prompt). Returns (ok, lines).'''
    try:
        return primarygit.push(ctx, _TuiPushUI(stdscr, pal))
    except Exception as e:                          # noqa: BLE001 — surface, don't crash
        return False, [f'push failed: {e}']


def _auto_push_primary(stdscr, pal, ctx):
    '''The push on quit under `auto` / `auto-on-quit`: nothing is asked. Returns (ok, lines).'''
    try:
        return primarygit.push(ctx, _TuiAutoPushUI(stdscr, pal))
    except Exception as e:                          # noqa: BLE001
        return False, [f'push failed: {e}']


def _quit_push(stdscr, pal, ctx, force=False):
    '''What quitting does about a primary with changes not pushed, per `primary-push`. Returns
    (quit?, notes to print after exit). ask: one prompt — push and quit / quit / keep working (the
    default, like the plain quit confirm). auto: push without asking. auto-on-quit: push without
    asking, quit-force included. manual: nothing. `force` (quit-force) otherwise never stops to push;
    it leaves a note instead. The rules are `primarygit.PUSH_POLICY`.'''
    try:
        st, mode = primarygit.state(ctx), primarygit.push_mode(ctx)
    except Exception:                               # noqa: BLE001
        st, mode = None, 'manual'
    ahead = st.ahead if st else 0
    then = primarygit.PUSH_POLICY[mode]['quit_force' if force else 'quit']
    if then is None or not ahead:
        return None, []
    later = (f'{st.name}: {primarygit.count_phrase(ahead)} not pushed — `configsys plugin push` shares '
             f'{primarygit.them_phrase(ahead)}.')
    if then == 'note':
        return True, [later]
    if then == 'push':
        ok, lines = _auto_push_primary(stdscr, pal, ctx)  # every line, the driver's notes too (primary-12)
        return True, (lines if ok else lines[:-1] + ['not pushed automatically — ' + (lines[-1] if lines else '')])
    c = _popup_choose(stdscr, pal, f'Quit? {primarygit.count_phrase(ahead)} to {st.name} not pushed yet.',
                      [('Push, then quit', 'p'), ('Quit, push later', 'q'), ('Keep working', 'n')],
                      start=2, shortcuts={'p': 0, 'q': 1, 'n': 2})
    if c == 0:
        _ok, lines = _push_primary(stdscr, pal, ctx)
        return True, lines
    if c == 1:
        return True, [later]
    return False, []


def _confirm_and_execute(stdscr, pal, ms, ctx, ledger):
    raw = ms.plan()
    # System Updates rows are a BULK mark, not per-unit ops: pull them out of the per-unit plan and
    # apply them via each manager's own bulk upgrade (upgrade_all), never through run_plan per-package.
    su_raw = [s for s in raw if _is_system_update(ms.states.get(s[1]))]
    raw = [s for s in raw if not _is_system_update(ms.states.get(s[1]))]
    su_managers = sorted({rc.driver for _op, _k, rc in su_raw})
    if not raw and not su_managers:
        return False, 'nothing staged', []
    units = {k: st.component for k, st in ms.states.items()
             if not _is_system_update(st)}                # synthetic units never reach expand/run_plan
    # the ONE plan builder the CLI uses too (actions.build_plan): auto-tighten, the method-switch
    # swap (remove-before-reinstall), only the missing dependencies (this screen's states), and the
    # version-floor heads-ups to show before you confirm
    from ..actions import build_plan
    plan, units, advisories = build_plan(ctx, raw, units, states=ms.states) if raw else ([], units, [])

    with suspended(stdscr):
        for text in advisories:
            print(f'heads-up — {text}')
        print('\nAbout to execute:')
        # System Updates run FIRST: bring the base current before installing new packages against it —
        # cleaner dependency resolution everywhere, and on Arch it avoids the partial-upgrade footgun
        # of `pacman -S <new>` on a not-yet-`-Syu`'d system.
        if su_managers:
            print(f'  {"sys-update":8} System Updates — bulk upgrade via {", ".join(su_managers)} '
                  f'({len(su_raw)} package(s))')
        for op, key, rc in plan:
            print(f'  {op:8} {key}  (pkg: {rc.name})')
        try:
            ans = input('\nProceed? [y/N] ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans != 'y':
            print('cancelled.')
            input('Press Enter to return...')
            return False, 'cancelled', []

        outcomes = []
        # ONE index refresh for the whole batch, before anything runs (see maybe_refresh_before_plan)
        from ..cli.refresh import maybe_refresh_before_plan, published_pending
        fresh = maybe_refresh_before_plan(ctx, plan, system=bool(su_managers))
        if su_managers:                                   # the whole-machine bulk upgrade(s) — first
            from .. import sysupdates
            from ..actions import OpOutcome
            bulk_failures, bulk_keys = [], []
            for mgr, res in sysupdates.apply_bulk(ctx, su_managers, refresh=False):
                ok = bool(res is not None and res.ok)
                bkey = f'system-updates\\{mgr}'
                outcomes.append(OpOutcome('upgrade', bkey, mgr, ok,
                                          '' if ok else (_fail_detail(res) if res is not None
                                                         else 'bulk upgrade failed')))
                bulk_keys.append(bkey)
                if res is not None and not ok:
                    bulk_failures.append(reportgen.failure_from_result(bkey, mgr, 'upgrade', res))
            if not getattr(ctx.runner, 'pretend', False):   # the ! page + `report` see it too
                reportgen.record_run(ctx.paths, bulk_failures, bulk_keys)
        if plan:                                          # then the per-component ops, against the fresh base
            outcomes += execute_plan(ctx, plan, ledger, refresh=False,
                                     version=(getattr(ms, 'plan_versions', dict)() or None))
        # drain the persisted !uninstall queue for components we just removed (shared with the CLI)
        from ..actions import after_run
        after_run(ctx, outcomes, units)
        n_ok = sum(1 for o in outcomes if o.ok)
        warned = [o for o in outcomes if getattr(o, 'installed_with_warning', False)]
        advisories = [o for o in outcomes if getattr(o, 'advisory', False)]
        undetected = [o for o in outcomes if getattr(o, 'undetected', False)]
        failed = [o for o in outcomes if not o.ok and not getattr(o, 'advisory', False)]
        print(f'\nSummary: {n_ok} ok, {len(failed)} failed'
              + (f', {len(advisories)} need input' if advisories else '')
              + (f', {len(warned)} with warnings' if warned else '')
              + (f', {len(undetected)} not detected after install' if undetected else ''))
        for o in failed:
            print(f'  FAILED  {o.op:8} {o.key}  (pkg: {o.name})  {o.detail}')
        for o in undetected:
            print(f'  NOT DETECTED  {o.op:8} {o.key}  (pkg: {o.name})  — ran ok, but reads '
                  f'"not installed": a detection bug in its route/driver')
        for o in advisories:
            print(f'  NEEDS INPUT  {o.op:8} {o.key}  {o.detail}')
        if failed or warned:                          # all failures are persisted now -> report works
            print('\n`configsys report` files the details of the above (they stay on the ! page '
                  'until fixed).')
        pending = published_pending(ctx, fresh)
        if pending:                                   # no surprises: say why they now read outdated
            shown = ', '.join(pending[:8]) + (f' +{len(pending) - 8} more' if len(pending) > 8 else '')
            print(f'\nPublished since you staged: the refresh found {len(pending)} newer package(s) '
                  f'this batch didn\'t include — {shown}. They now show as outdated; stage them to '
                  f'upgrade.')
        input('\nPress Enter to return...')
        return True, _summary_note(outcomes), outcomes


def _reload(ctx, old, dirty):
    '''Rebuild the menu after a pin change or an execute, requerying only `dirty` (+ any
    newly-appearing) units and REUSING the rest of the cached probe. Preserves cursor position,
    expansion, selection, and still-valid staged ops across the rebuild so the view stays put.
    Returns (ms, cfg, ledger, states, diags).'''
    cfg, _requested, _units, ledger, states = ctx.load_pipeline(reuse=old.states, dirty=dirty)
    mode = getattr(old, 'mode', 'to-do')
    base = states
    states, layouts, transitive = _components_model(ctx, cfg, states, mode)   # fresh overlay: disk changed
    ms = MenuState(states, layouts, transitive)
    ms.mode = mode
    ms.adopt_view(old, errors=False, descriptions=False)   # an execute's errors are re-derived
    ms._overlay_caches = {}                            # installed reality changed -> re-enumerate on next switch
    ms._extra_keys = _added_extras(base, states) if mode == 'installed+tracked' else set()
    _seed_uninstall(ms, ctx)                          # add any newly-queued removes (setdefault)
    ms._uninstall_q = set(ctx.config.uninstall_queue())   # snapshot -> refresh on switch if it changes
    ms.descriptions = _describe(ctx)             # cache once; never hit ctx.routes per frame
    ms._req_sig = frozenset(_requested)          # the install set this tree was built for (matrix picks)
    if hasattr(ctx, 'start_check_lints'):
        ctx.start_check_lints()                  # an edit may have changed what `check` says
    return ms, cfg, ledger, states, ctx.diagnostics(states)


def _apply_method_pin(ctx, name, via, already_pinned):
    '''Write a binding-pin name->via through actions.set_pin (the writer `configsys pin set` uses —
    validated the same way). Returns (changed, note, deferred).'''
    from .. import actions
    if already_pinned:
        return False, f'{name} already uses {via}', None
    ok, label, note = actions.set_pin(ctx, name, via)
    if not ok:
        return False, f'{name}: {note}', None
    if label == actions.PRETEND_NOT_SAVED:
        return False, f'[pretend] would pin {name} → {via}', None
    return True, f'pinned {name} → {via}' + (f' — {note}' if note else ''), \
        f'pinned {name} → {via} (local); `v` → "promote the pin" makes it portable via your primary.'


def _offer_method_swap(stdscr, pal, ms, ctx):
    '''After a method pin change, if the pinned component is STILL installed via another method, pop a
    modal offering to queue that old install's removal (a remove-before-reinstall swap). On "yes",
    stage an install of the new-method unit — the swap-remove itself is folded in at execute
    (plan_with_swaps). Returns a footer note, or None when there's nothing to swap.'''
    name = _row_component(ms.cur())
    if not name:
        return None
    tgt = next((k for k, st in ms.states.items()
                if st.component.comp == name and st.also_present), None)
    if tgt is None:
        return None                                  # not doubled up — nothing to switch away from
    st = ms.states[tgt]
    olds = ', '.join(f'{via} {ver}' for via, _pkg, ver in st.also_present)
    new_via = st.component.via
    idx = _popup_choose(
        stdscr, pal, f'{name} is still installed via {olds}',
        [(f'queue removal + reinstall via {new_via}', ''),
         ('keep both (do nothing)', '')],
        start=0, shortcuts={'y': 0, 'n': 1})
    if idx != 0:
        return None
    ms.staged[tgt] = 'install'                        # execute folds in the swap-remove of the old method
    return f'queued {name}: remove {olds} → reinstall via {new_via} (run with execute)'


def _pick_method(stdscr, pal, ms, ctx):
    '''Components-screen entry to the install-method picker: the current row's component.'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to choose its install method', None
    return _pick_method_name(stdscr, pal, ctx, name)


def _pick_method_name(stdscr, pal, ctx, name):
    '''Install-method picker for component `name`: an in-place popup of its candidate methods;
    choosing one writes a binding-pin. Returns (changed, note, deferred). No drop to the terminal;
    the promote hint is deferred to TUI exit.'''
    cands = ctx.routes.candidates(name)
    if len(cands) < 2:
        return False, f'{name}: only one install method available here', None
    # annotate each method with the version it would install (cached; the first open of a component
    # may briefly query native/discovery) + a "lags" flag vs the newest available, so the choice is
    # version-informed. Best-effort: a probe failure just omits versions.
    vers, tip = {}, None
    try:
        from .. import versionreport
        rep = versionreport.report(ctx, name)
        vers = {m.via: m for m in rep.methods}
        tip = rep.tip
    except Exception:  # noqa: BLE001 — never let a version probe block the picker
        pass
    # lay the labels out in columns — `via <name>` | version | (when) — so the versions line up
    # (the popup box auto-widens to the longest label). Compute the column widths first.
    rows = []
    for c in cands:
        mv = vers.get(c['via'])
        ver = clean_version(mv.latest if mv else None) or '—'   # normalized, like the columns
        tags = [t for t, on in (('auto-default', c.get('auto', c['default'])), ('pinned', c['pinned'])) if on]
        if mv and mv.lags_tip:
            tags.append('lags')
        rows.append((c['via'], ver, f"({c['when']})" if c['when'] else '', ' '.join(tags)))
    via_w = max(len(via) for via, _v, _w, _t in rows)
    ver_w = max(len(v) for _via, v, _w, _t in rows)
    options = [(f"via {via:<{via_w}}   {ver:<{ver_w}}   {when}".rstrip(), tags)
               for via, ver, when, tags in rows]
    pinned = next((c['via'] for c in cands if c['pinned']), None)
    from .. import plugins as _pl
    promotable = bool(pinned) and name in _pl.read_pins(ctx.paths.user_config_file) \
        and _pl.primary_name(_pl.declared(ctx.paths.user_config_file)) is not None
    if pinned:                       # "auto — unpin": drop the pin, follow the routes again (B16; §7.17)
        options.append(('auto — unpin (follow the routes\' default again)', ''))
    if promotable:                   # a local pin into the primary, so it travels (D3 / parity-04)
        options.append(('promote the pin into your primary (travels)', ''))
    title = f'install method — {name}' + (f'   (tip {clean_version(tip)})' if tip else '')
    start = next((i for i, c in enumerate(cands) if c['pinned'] or c['default']), 0)
    idx = _popup_choose(stdscr, pal, title, options, start)
    if idx is None:
        return False, 'method unchanged', None
    if pinned and idx == len(cands):
        from .. import actions
        changed, label = actions.unset_pin(ctx, name)
        return changed, (_pretend_note(ctx, f'{name}: unpinned — the default method applies again',
                                       True) if changed else f'{name}: {label}'), None
    if promotable and idx == len(cands) + 1:
        from .. import actions
        ok, msg = actions.promote_pin(ctx, name)
        return ok and not ctx.runner.pretend, msg, None
    chosen = cands[idx]
    if chosen.get('auto') and not chosen['pinned'] and not pinned:
        return False, f'{name}: already on the default method (no pin to write)', None
    return _apply_method_pin(ctx, name, chosen['via'], chosen['pinned'])


def _providers_of(routes, cap):
    '''Component names that declare `provides: cap` — a capability's candidate providers (the
    capability itself is not a component here, so it's not included).'''
    return sorted(n for n, c in routes.components.items()
                  if cap in getattr(c, 'provides', ()))


def _capability_choices(routes, name):
    '''Capabilities relevant to component `name` that have MORE THAN ONE provider — a real choice.
    Considers the caps it PROVIDES (so you repoint from a provider's row, e.g. stand on
    cuda-toolkit-12 to switch the `cuda-toolkit` capability to cuda-toolkit-11), the ones it REQUIRES
    at the component level, AND the requires declared on the binding that WINS here — so a variant
    whose SDK need rides its method (blender-optix's binding-level `cuda-toolkit`) still surfaces the
    provider choice from the component's own row. Returns [(cap, [providers])], deduped and sorted.'''
    comp = routes.components.get(name)
    if comp is None:
        return []
    caps = set(getattr(comp, 'provides', ())) | set(getattr(comp, 'requires', ()))
    try:                                                 # + the winning binding's requires (mirrors _edges_text)
        from ..resolve import ResolveError, cap_names
        won = routes.select(comp).binding
        caps.update(cap_names(won.details.get('requires')))
    except ResolveError:
        pass
    out = []
    for cap in sorted(caps):
        provs = _providers_of(routes, cap)
        if len(provs) >= 2:
            out.append((cap, provs))
    return out


def _apply_provider_pin(ctx, cap, provider, current):
    '''Write a provider-pin (capability `cap` -> component `provider`) through actions.set_pin —
    "whatever needs `cap`, use `provider`". Returns (changed, note, deferred).'''
    from .. import actions
    if provider == current:
        return False, f'{cap} already provided by {provider}', None
    ok, label, note = actions.set_pin(ctx, cap, provider)
    if not ok:
        return False, f'{cap}: {note}', None
    if label == actions.PRETEND_NOT_SAVED:
        return False, f'[pretend] would set provider {cap} → {provider}', None
    return True, f'{cap} now provided by {provider}', \
        f'set provider {cap} → {provider} (local); `configsys pin promote {cap}` makes it portable.'


def _pick_provider(stdscr, pal, ms, ctx):
    '''Components-screen entry: for the current row's component, choose which component PROVIDES a
    capability it's tied to (a provider-pin). The generic answer to "this capability has several
    providers — use that one instead" (e.g. the opt-in cuda-toolkit-11 vs default cuda-toolkit-12).
    Returns (changed, note, deferred).'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to choose a provider', None
    choices = _capability_choices(ctx.routes, name)
    if not choices:
        return False, f'{name}: no capability with alternative providers here', None
    if len(choices) == 1:
        cap, provs = choices[0]
    else:                                                # more than one cap -> pick which first
        cidx = _popup_choose(stdscr, pal, f'capability — {name}',
                             [(c, f'{len(p)} providers') for c, p in choices], 0)
        if cidx is None:
            return False, 'provider unchanged', None
        cap, provs = choices[cidx]
    return _pick_provider_cap(stdscr, pal, ctx, name, cap, provs)


def _pick_provider_cap(stdscr, pal, ctx, name, cap, provs):
    '''Provider picker for ONE already-chosen capability `cap` (providers `provs`), from `name`'s row.
    Writes a provider-pin cap->provider. Split out of `_pick_provider` so the unified chooser, which
    has already picked the capability axis, can jump straight here. Returns (changed, note, deferred).'''
    routes = ctx.routes
    pins = ctx.config.pins()
    pinned = pins.get(cap)
    default = next((p for p in provs if not getattr(routes.components[p], 'never_auto', False)), None)
    # the provider in effect now: an explicit pin, else this row (if it provides cap), else the default
    current = pinned or (name if cap in getattr(routes.components.get(name), 'provides', ()) else default)
    avail, options = {}, []
    for p in provs:
        here = bool(routes.candidates(p))
        avail[p] = here
        tags = []
        if p == pinned:
            tags.append('pinned')
        elif p == current:
            tags.append('current')
        if not getattr(routes.components[p], 'never_auto', False):
            tags.append('default')
        if not here:
            tags.append('n/a here')
        options.append((p, ' '.join(tags)))
    start = (provs.index(pinned) if pinned in provs
             else provs.index(current) if current in provs else 0)
    idx = _popup_choose(stdscr, pal, f'provider for {cap}', options, start)
    if idx is None:
        return False, 'provider unchanged', None
    chosen = provs[idx]
    if not avail.get(chosen, True):
        return False, f'{chosen} has no install method on this machine — not set', None
    return _apply_provider_pin(ctx, cap, chosen, current)


def _pick_choices(stdscr, pal, ms, ctx):
    '''The unified "change how this resolves" chooser for the current row's component — one key that
    folds the install-method picker (a binding-pin) and the provider picker (a provider-pin). Lists
    only the axes this component actually has a choice on; a single axis opens its picker directly,
    several first ask which to change. Returns (changed, note, deferred).'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to change how it resolves', None
    routes = ctx.routes
    axes = []                                            # (menu-label, kind, payload)
    if len(routes.candidates(name)) >= 2:
        axes.append((f'install method — {name}', 'method', None))
    for cap, provs in _capability_choices(routes, name):
        axes.append((f'provider for {cap}', 'provider', (cap, provs)))
    # what you can DO to its installed unit here (§7.17 — CLI parity: `install` re-runs, set-version,
    # fix-scope), staged like any op and run with X
    unit = next((k for k, st in (getattr(ms, 'states', None) or {}).items()
                 if st.component.comp == name and st.present and not _is_system_update(st)), None)
    if unit is not None:
        st = ms.states[unit]
        from ..actions import targets_version
        drv = get_driver(st.component.driver, ctx.runner, ctx.paths)
        axes.append((f'rebuild / reinstall {name} (X runs it)', 'rebuild', unit))
        if drv is not None and targets_version(drv):
            axes.append((f'pin {name} to a version…', 'set-version', unit))
        want = drv.scope(st.component) if drv is not None else None
        if st.scope and want and st.scope != want:
            axes.append((f'fix scope: move it from {st.scope} to {want}', 'fix-scope', unit))
    if not axes:
        return False, f'{name}: nothing to choose (one method, no multi-provider capability)', None
    if len(axes) == 1:
        _label, kind, payload = axes[0]                  # skip the menu when there's a single axis
    else:
        idx = _popup_choose(stdscr, pal, f'change — {name}', [(lbl, '') for lbl, _k, _p in axes], 0)
        if idx is None:
            return False, 'unchanged', None
        _label, kind, payload = axes[idx]
    if kind == 'method':
        return _pick_method_name(stdscr, pal, ctx, name)
    if kind == 'rebuild':
        ms.stage_unit(payload, 'install')
        ms._refresh()
        return False, f'staged a rebuild of {name} — X runs it (missing dependencies too)', None
    if kind == 'set-version':
        return _stage_set_version(stdscr, pal, ms, ctx, name, payload)
    if kind == 'fix-scope':
        return _fix_scope_row(stdscr, pal, ms, ctx, name, payload)
    cap, provs = payload
    return _pick_provider_cap(stdscr, pal, ctx, name, cap, provs)


def _stage_set_version(stdscr, pal, ms, ctx, name, key):
    '''Ask for a version (offering what the method can install, newest first) and stage a
    set-version of `key` at it.'''
    offers = []
    try:
        from .. import versionreport
        rep = versionreport.report(ctx, name)
        offers = [m.latest for m in rep.methods if getattr(m, 'latest', None)]
    except Exception:  # noqa: BLE001 — a probe failure just means no suggestions
        pass
    seed = clean_version(offers[0]) if offers else ''
    ver = _input_box(stdscr, pal, f'pin {name} to version', seed)
    if not ver or not ver.strip():
        return False, 'unchanged', None
    ms.stage_unit(key, 'set-version', ver.strip())
    ms._refresh()
    return False, f'staged {name} → {ver.strip()} (set-version; X runs it, a lock follows it)', None


def _fix_scope_row(stdscr, pal, ms, ctx, name, key):
    '''Reinstall `key` at the scope your config declares (`configsys fix-scope`), after a confirm.'''
    st = ms.states[key]
    if _popup_choose(stdscr, pal, f'move {name} from {st.scope} to the scope your config declares?',
                     [('cancel', ''), ('move it (reinstall there, then remove the old one)', '')], 0) != 1:
        return False, 'unchanged', None
    from .. import actions
    with suspended(stdscr):
        ok, msg = actions.fix_scope(ctx, st.component)
    return ok, _pretend_note(ctx, msg, ok), None
