'''actions.py — the shared action layer.

Reusable read+write operations that BOTH the CLI subcommands and the TUI screens call, so the two
stay in lockstep (the TUI is a skin over these, never a parallel implementation). Each takes the app
`Context`, edits config surgically via the `plugins.set_*` writers, and `ctx.invalidate()`s the
cached config so the change takes effect on the next read. See docs/done/tui-screens-plan.md (F3).
'''

import os
import re
from pathlib import Path

from . import layers, plugins, primarygit


# --pretend is a true dry run for the TUI too: every config-editing action below refuses to write
# under ctx.runner.pretend and returns this as its label/message (a `(False, PRETEND_NOT_SAVED)` for
# the (changed, label) writers, 0 for the counters) so a surface can show it instead of a change.
PRETEND_NOT_SAVED = '[pretend] not saved'


def _pretend(ctx):
    '''True when this run is --pretend (so an edit must not be written).'''
    return bool(getattr(getattr(ctx, 'runner', None), 'pretend', False))


def invalidate_location_cache(ctx):
    '''Drop the glue-locations cache after an edit that changes WHERE a component installs (a method
    pin, a pick added/removed) so the next shell startup recomputes it. Lives here (not app.py) and
    is called from inside the shared writers, so neither the CLI nor the TUI can forget it.'''
    if getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return                                           # a dry run changed nothing to recompute
    f = getattr(getattr(ctx, 'paths', None), 'glue_locations_file', None)
    if f is None:
        return
    try:
        f.unlink()
    except (FileNotFoundError, OSError):
        pass


# -- the shared op-execution loop (CLI + TUI run the SAME plan the SAME way) -----------------------

class OpOutcome:
    '''One executed plan step, for the surfaces to render (the TUI summary, a report).'''
    def __init__(self, op, key, name, ok, detail='', installed_with_warning=False, advisory=False,
                 undetected=False):
        self.op = op
        self.key = key
        self.name = name
        self.ok = ok                                 # True also for installed-with-a-warning
        self.detail = detail
        self.installed_with_warning = installed_with_warning
        self.advisory = advisory                     # a "needs your input" outcome, not a bug
        self.undetected = undetected                 # ran ok, but configsys can't see it afterwards


class RunResult:
    '''What `run_plan` produced: outcomes (per step, for the TUI), failure records (for `report`),
    n_fatal (hard failures, excluding installed-with-warnings), an rc_code (for the CLI exit), and
    whether the batch was interrupted (^C).'''
    def __init__(self, outcomes, failures, n_fatal, rc_code, interrupted):
        self.outcomes = outcomes
        self.failures = failures
        self.n_fatal = n_fatal
        self.rc_code = rc_code
        self.interrupted = interrupted


_ERROR_LINE = re.compile(r'^\s*(?:error|fatal|e|err)\b\s*[:!]|\berror:', re.IGNORECASE)


def failure_excerpt(text, limit=240):
    '''The line(s) of a failed command's output that say WHY, for one-line summaries. The last line is
    often a trailer — pip's "hint: See PEP 668 …", the tail of a wrapped go message ("… it to be
    interpreted differently than if it were the main module.") — so: the LAST error-looking line
    (`error:` / `E:` / `fatal:` / `ERROR …`), else the trailing paragraph (the last line plus the
    indented continuation lines and the header line they hang from), whitespace-collapsed and
    truncated to `limit`.'''
    lines = [ln.rstrip() for ln in (text or '').splitlines() if ln.strip()]
    if not lines:
        return ''
    hits = [i for i, ln in enumerate(lines) if _ERROR_LINE.search(ln)]
    if hits:
        i = hits[-1]
        block = [lines[i]]
        for ln in lines[i + 1:]:                     # its own indented continuation lines only
            if not ln[:1].isspace():
                break
            block.append(ln)
    else:
        i = len(lines) - 1
        while i > 0 and lines[i][:1].isspace():
            i -= 1                                   # back to the line the indented tail hangs from
        block = lines[i:]
    out = ' '.join(' '.join(block).split())
    return out if len(out) <= limit else out[:limit - 1] + '…'


def fail_detail(res):
    '''A concise failure reason for a driver Result: exit code + the line(s) of output that say why
    (failure_excerpt), plus the failure taxonomy tag when known. The full output is still persisted
    for `configsys report`.'''
    if res is None:
        return 'no result'
    why = failure_excerpt(res.stderr or res.captured or res.stdout or '')
    base = f'exit {res.returncode}: {why}' if why else f'exit {res.returncode}'
    cat, rem = res.classified()
    if cat:
        base += f'  [{cat}]' + (f' — {rem}' if rem else '')
    return base


_UNPROBED = object()


def installed_despite_failure(drv, rc, op, version, before=_UNPROBED):
    '''After a non-zero install/upgrade, is the target unit ACTUALLY present now? apt exits non-zero
    when a Recommends / sub-package / post-install step fails though the wanted package installed
    (e.g. sysdig-dkms's kernel module). Returns the installed version, or None. For an upgrade/
    set-version, "present" isn't enough — it must have reached the target version. For an install,
    `before` (the version probed before the step) separates a failed REINSTALL / rebuild — the OLD
    install still there, unchanged — from a fresh install that landed (B17 / actions-06).'''
    if op not in ('install', 'upgrade', 'set-version'):
        return None
    try:
        got = drv.get_version(rc)
    except Exception:                                # noqa: BLE001
        return None
    if not got:
        return None
    if op == 'install':
        if before is not _UNPROBED and before is not None and str(before) == str(got):
            return None                              # it was already there and nothing changed
        return got
    try:
        target = version or drv.get_latest(rc)
    except Exception:                                # noqa: BLE001
        target = None
    return got if (target and str(got) == str(target)) else None


# Built-in drivers that don't run as root themselves but routinely sudo INSIDE their commands: a
# script's declared install-cmd (`curl … | sudo bash`), a source recipe's `sudo make install`,
# makepkg (aur). Code-plugin drivers are treated the same (blender/kicad builds sudo internally).
_INTERNAL_SUDO_DRIVERS = frozenset({'script', 'source', 'aur'})


def _may_need_root(drv, rc):
    '''Could this op need sudo? Its driver is privileged or runs this unit with sudo (system scope),
    or it's a driver known to sudo inside its commands, or a plugin driver (unknown -> assume yes).
    Decides whether a batch authenticates up front; a false positive only costs one early prompt.'''
    if drv is None:
        return False
    try:
        if drv.privileged or drv.sudo(rc):
            return True
    except Exception:                                # noqa: BLE001
        return True
    return (getattr(drv, 'name', None) in _INTERNAL_SUDO_DRIVERS
            or not type(drv).__module__.startswith('configsys.'))


# drivers whose "not present" after a good install is legitimate: config with nothing captured yet
_NO_POST_CHECK = frozenset({'dotfiles', 'glue'})


def detected_after(drv, rc):
    '''After a successful install/upgrade, can the driver see the unit? True when it reports a version,
    or when it can't be judged (config drivers, a probe that raises) — only a definite "absent" is
    False.'''
    if getattr(drv, 'name', None) in _NO_POST_CHECK:
        return True
    try:
        return drv.get_version(rc) is not None
    except Exception:                                # noqa: BLE001 — unknowable is not "undetected"
        return True


def targets_version(drv):
    '''Can `drv.set_version(rc, v)` actually install version `v`? Read from the driver's
    `targets_version` class attribute (Driver base default True; False = "installs the routed version
    only" — its set_version would silently reinstall whatever the route resolves and report ok, e.g.
    tarball/appImage/font/native-pkg-file/dotfiles/glue/service/group).'''
    return drv is not None and bool(getattr(drv, 'targets_version', True))


def no_version_target_message(via, comp):
    '''The one wording for "this method can't set a version" (CLI preflight + the op loop).'''
    return (f'{via} installs the routed version only — pin a method that supports versions '
            f'(`configsys versions {comp}`)')


def pretend_unresolved_download(drv, rc):
    '''Under --pretend, is this failed op just a download whose version/asset isn't in the offline
    cache? --pretend never touches the network, so a discovery-spec binding (`version: { github: … }`)
    with nothing cached has no URL to show — that is not a failure of the route, only of the dry run.
    True when the binding carries a discovery spec and the driver can't build a download URL offline.'''
    spec = (rc.fields or {}).get('version')
    if not isinstance(spec, dict) or not hasattr(drv, 'download_target'):
        return False
    try:
        _ver, url = drv.download_target(rc)
    except Exception:                                # noqa: BLE001 — unknowable offline = unresolved
        return True
    return not url


_PLAN_OPS = ('install', 'upgrade', 'set-version', 'remove')


def resolve_targets(ctx, names):
    """(units, root keys) for a CLI op on `names`, resolved the way inspect and the TUI resolve them:
    your pins, then the opt-in auto-tighten floor pins, then the detection tier's soft pins
    (`adopt-installed:`) — so `upgrade X` acts on the install X actually has, never on the default
    method next to it (review-2026-11-2 B1). Under --pretend detection is skipped (probes read empty),
    exactly as the inspect pipeline does."""
    routes = ctx.routes
    units, roots = routes.resolve_with_roots(names)
    tighten, detected = {}, {}
    cfg = getattr(ctx, 'config', None)
    if cfg is not None and cfg.auto_tighten():
        from . import flooradvise
        tighten = flooradvise.tighten_pins(ctx, list(units.values())) or {}
    if cfg is not None and cfg.adopt_installed() and not getattr(ctx.runner, 'pretend', False):
        from . import detection
        detected = detection.detect_pins(ctx, units) or {}
    if tighten or detected:
        units, roots = routes.resolve_with_roots(names, extra_pins=(tighten or None),
                                                 soft_pins=(detected or None))
    return units, roots


def _dependency_states(ctx, plan, units):
    """{key: ComponentState} for the dependency units a plan's install-ish steps would fold in —
    probed now, so `expand_plan` installs only the MISSING ones (the TUI passes its own states)."""
    from .installState import InstallState
    from .ledger import Ledger
    named = {key for _op, key, _rc in plan}
    deps, stack = {}, [key for op, key, _rc in plan if op in ('install', 'upgrade', 'set-version')]
    while stack:
        rc = units.get(stack.pop())
        for dep in (getattr(rc, 'deps', ()) or ()) if rc is not None else ():
            if dep in units and dep not in deps and dep not in named:
                deps[dep] = units[dep]
                stack.append(dep)
    if not deps:
        return {}
    try:
        return InstallState(ctx.runner, Ledger.load(ctx.paths), ctx.paths).inspect(deps)
    except Exception:                                  # noqa: BLE001 — can't tell: treat as missing
        return {}


def build_plan(ctx, steps, units, *, states=None, no_deps=False, with_deps=False):
    """The ONE plan builder the CLI and the TUI share (review-2026-11-2 D3): `steps` = the requested
    `[(op, key, rc)]` (the CLI's named roots, or the TUI's staged units). Returns `(plan, units,
    advisories)`:
    - `no_deps`: only the named units (`--no-deps`; the method-switch swap still applies — never a
      double install — and every remove runs first);
    - otherwise: opt-in auto-tighten upgrades of a resident provider below a consumer's floor, the
      method-switch swap (`plan_with_swaps`), and `expand_plan`, which folds in only the MISSING
      dependencies (`states` — the TUI's, else probed here; `with_deps` re-runs the whole tree);
    - `advisories`: version-floor heads-ups (flooradvise) for an install-ish plan, to show BEFORE the
      confirm. Both surfaces print/show them the same way."""
    from .installState import plan_with_swaps
    from .planning import expand_plan
    steps = list(steps)
    installish = any(op in ('install', 'upgrade', 'set-version') for op, _k, _r in steps)
    if no_deps:
        if any(op in _PLAN_OPS for op, _k, _r in steps):
            steps, units = plan_with_swaps(ctx, steps, units)
        plan = [s for s in steps if s[0] == 'remove'] + [s for s in steps if s[0] != 'remove']
    else:
        cfg = getattr(ctx, 'config', None)
        if installish and cfg is not None and cfg.auto_tighten():
            from . import flooradvise
            have = {key for _op, key, _rc in steps}
            for pkey, prc in flooradvise.resident_upgrades_probed(ctx, units).items():
                if pkey not in have:
                    steps.append(('upgrade', pkey, prc))
        if any(op in _PLAN_OPS for op, _k, _r in steps):
            steps, units = plan_with_swaps(ctx, steps, units)
        if states is None and not with_deps:
            states = _dependency_states(ctx, steps, units)
        plan = expand_plan(steps, units, None if with_deps else states)
    advisories = []
    if installish:
        try:
            from . import flooradvise
            advisories = [a['text'] for a in flooradvise.advise(ctx, list(units.values()))]
        except Exception:                              # noqa: BLE001 — an advisory never blocks the op
            advisories = []
    return plan, units, advisories


def after_run(ctx, outcomes, units):
    """The post-run step both surfaces share: a component you just removed leaves the `uninstall:`
    queue (it used to drain only from the TUI)."""
    for o in outcomes:
        rc = units.get(o.key)
        if o.op == 'remove' and o.ok and rc is not None:
            try:
                stage_uninstall(ctx, rc.comp, on=False)
            except Exception:                          # noqa: BLE001 — draining never fails the run
                pass


def _layer_may_run(ctx, drv, rc):
    '''False when `rc`'s binding comes from an untrusted plugin layer AND carries commands / root
    writes / downloads (trustgate.unit_needs_trust) — the run-time twin of the resolution gate.'''
    from . import trustgate
    if not getattr(rc, 'source', '') or getattr(ctx, 'paths', None) is None:
        return True
    try:
        trusted = drv.command_trusted(rc)
    except Exception:                                  # noqa: BLE001
        trusted = True
    return trusted or trustgate.unit_needs_trust(rc) is None


def _unit_locked(drv, rc, key, ledger):
    '''True if `key` is version-locked: in the ledger (every driver without a native hold), or by
    the manager's own hold (apt-mark, dnf versionlock, brew pin…). Best-effort: a probe error reads
    as unlocked.'''
    if ledger is not None and ledger.is_locked(key):
        return True
    try:
        return bool(drv.is_locked(rc))
    except Exception:                                  # noqa: BLE001
        return False


def run_plan(ctx, plan, *, ledger=None, version=None, on_line=print):
    '''Execute an ordered `[(op, key, rc)]` plan — the ONE op-execution loop the CLI and TUI share.
    Per step it dispatches the op (install/remove/upgrade/lock/unlock/set-version), runs the
    shell-writes guard (snapshot rc files, revert+stage after), records ledger lock state, and
    classifies the result: an `advisory` result ("needs your input", e.g. dotfiles refusing to
    clobber) is explained not reported; a hard failure that nonetheless left the package present
    (apt's failed-Recommends case) is downgraded to installed-with-a-warning. Ctrl-C aborts the whole
    batch. If any op may need root, sudo is authenticated ONCE up front (begin_sudo) and kept warm
for the whole batch, every streamed op reusing it — so a long run can go unattended after the first
prompt; the keep-alive is released and the ledger saved at the end. Progress
    prints via `on_line`. Returns a RunResult. Presentation of the reboot advisory and the report
    offer stays with each surface.'''
    from . import reportgen, shellguard
    from .drivers import get_driver
    versions = version if isinstance(version, dict) else None   # per-unit (a TUI batch) or one for all
    outcomes, failures, n_fatal, rc_code, interrupted = [], [], 0, 0, False
    pretend = bool(getattr(ctx.runner, 'pretend', False))   # --pretend: print, never record anything
    begin = getattr(ctx.runner, 'begin_sudo', None)
    if begin and any(_may_need_root(get_driver(rc.driver, ctx.runner, ctx.paths), rc) for _, _, rc in plan):
        begin(on_line)                   # the ONE prompt, up front — then the run can go unattended
    try:
        swapped_locks = set()            # comps whose locked install a swap removed: the new one is held too
        for cur_op, key, rc in plan:
            if versions is not None:
                version = versions.get(key)
            drv = get_driver(rc.driver, ctx.runner, ctx.paths)
            if drv is None and rc.driver == '—':        # a dangling/unmet placeholder row (stranded.py)
                on_line(f'skip {key}: {rc.comp} has no install method on this machine')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, 'no install method here'))
                continue
            if drv is None:
                on_line(f'skip {key}: driver "{rc.driver}" not yet supported')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, 'unsupported driver'))
                continue
            if cur_op == 'set-version' and not targets_version(drv):
                # tarball/appImage/font/... set_version would just reinstall the ROUTED version and say
                # "ok" — a lie about what got installed. Refuse up front, naming the fix.
                msg = no_version_target_message(rc.via or rc.driver, rc.comp)
                on_line(f'set-version {key}: FAILED — {msg}')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, msg))
                rc_code = rc_code or 1
                n_fatal += 1
                continue
            if cur_op != 'remove' and not _layer_may_run(ctx, drv, rc):
                # defense in depth for the resolution gate (trustgate): a step whose binding came from an
                # untrusted plugin and carries commands / root writes / downloads never runs (an install
                # receipt replayed later, a hand-built plan). Removing what's installed stays possible.
                res = drv.untrusted_command_result(rc)
                on_line(f'{cur_op} {key}: refused — {res.output}')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, 'untrusted plugin', advisory=True))
                rc_code = rc_code or 1
                continue
            locked = (cur_op in ('upgrade', 'set-version', 'remove')
                      and _unit_locked(drv, rc, key, ledger))
            if cur_op == 'upgrade' and locked:
                # a lock is a promise (the ledger carries it for every driver without a native hold):
                # never upgrade through it — and a native hold would just fail confusingly (B2)
                on_line(f'upgrade {key}: locked — {rc.comp} stays at its held version '
                        f'(`configsys unlock {rc.comp}` first)')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, 'locked', advisory=True))
                rc_code = rc_code or 1                   # an explicit upgrade of a locked unit is refused
                continue
            on_line(f'{cur_op} {key} (pkg: {rc.name}) ...')
            try:
                rc_snap = (None if pretend else  # nothing runs in a dry run, so nothing to guard or revert
                           shellguard.arm(ctx.paths, getattr(ctx, 'config', None), rc.comp, cur_op,
                                          rc.driver))
            except Exception as e:               # noqa: BLE001 — the guard must never abort the batch
                on_line(f'  (shell-writes guard skipped for {key}: {e})')
                rc_snap = None
            res = None
            before = _UNPROBED
            if cur_op == 'install' and not pretend:  # a reinstall/rebuild that fails leaves the OLD
                try:                                 # install present — it must not read as success
                    before = drv.get_version(rc)
                except Exception:                    # noqa: BLE001
                    before = _UNPROBED
            try:
                try:
                    if cur_op == 'install':
                        res = drv.install(rc)
                        if res.ok and rc.comp in swapped_locks:   # a lock follows the component across a swap
                            if drv.lock(rc).ok and ledger is not None and not pretend \
                                    and getattr(drv, 'holds_version', True):
                                ledger.set_lock(key, True)
                    elif cur_op == 'remove':
                        if locked:                               # a native hold would refuse the removal
                            drv.unlock(rc)
                        res = drv.uninstall(rc)
                        if res.ok and locked:                    # removing it ends its lock
                            swapped_locks.add(rc.comp)
                            if ledger is not None and not pretend:
                                ledger.set_lock(key, False)
                    elif cur_op == 'upgrade':
                        res = drv.upgrade(rc)
                    elif cur_op == 'set-version':
                        # retarget-then-hold: a locked unit is released, moved, and held at the new version
                        if locked:
                            drv.unlock(rc)
                        res = drv.set_version(rc, version)
                        if locked:
                            drv.lock(rc)
                    elif cur_op == 'lock':
                        res = drv.lock(rc)
                        if (res.ok and ledger is not None and not pretend
                                and getattr(drv, 'holds_version', True)):
                            ledger.set_lock(key, True)   # never record a hold a rolling manager can't keep
                    elif cur_op == 'unlock':
                        res = drv.unlock(rc)
                        if res.ok and ledger is not None and not pretend:
                            ledger.set_lock(key, False)
                finally:
                    # revert + stage even on failure/abort — a half-finished installer may have written
                    _guard_msg = shellguard.finish(ctx.paths, rc.comp, rc_snap)
                    if _guard_msg:
                        on_line(f'  -> {_guard_msg}')
            except KeyboardInterrupt:                    # Ctrl-C aborts the WHOLE batch, not just this op
                on_line(f'\n  ^C — aborted; {key} may be partially applied. Skipping the rest of the batch.')
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, 'interrupted (^C)'))
                rc_code, interrupted = 130, True
                break
            except Exception as e:                   # noqa: BLE001 — a driver bug fails THIS op (B10),
                from .runner import Result           # never the batch, the ledger save or the sudo release
                res = Result(f'{cur_op} {rc.comp}', 1,
                             stderr=f'configsys error in the {rc.driver} driver: {type(e).__name__}: {e}')
            if res is None:                              # unknown op (should not happen for a built plan)
                on_line(f'  -> unknown op {cur_op}')
                rc_code = rc_code or 2
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, f'unknown op {cur_op}'))
                continue
            if not res.ok and pretend and cur_op in ('install', 'upgrade') \
                    and pretend_unresolved_download(drv, rc):
                # a dry run is offline: with nothing cached there's no version/asset to name. Show a
                # placeholder for the step instead of a fake failure (and a report offer).
                on_line(f'[pretend] {rc.via or rc.driver}: download + {cur_op} {rc.comp} @ <latest release> '
                        '(not in the offline version cache — a real run resolves it; '
                        '`configsys refresh` caches versions for --pretend)')
                on_line('  -> ok (pretend)')
                outcomes.append(OpOutcome(cur_op, key, rc.name, True, 'pretend: version unresolved offline'))
            elif not res.ok and getattr(res, 'advisory', False):
                on_line('  -> needs your input:')
                for line in (res.output or 'action required').splitlines():
                    on_line(f'    {line}')
                rc_code = rc_code or res.returncode or 1
                outcomes.append(OpOutcome(cur_op, key, rc.name, False, fail_detail(res), advisory=True))
            elif not res.ok:
                got = installed_despite_failure(drv, rc, cur_op, version, before)
                rec = reportgen.failure_from_result(key, rc.driver, cur_op, res)
                if got:
                    rec['installed'] = 'true'
                    on_line(f'  -> installed WITH A WARNING (exit {res.returncode}) — a recommended '
                            'package or post-install step failed; the package itself is present.')
                    outcomes.append(OpOutcome(cur_op, key, rc.name, True, fail_detail(res),
                                              installed_with_warning=True))
                else:
                    rc_code = res.returncode or 1
                    n_fatal += 1
                    on_line(f'  -> FAILED (exit {res.returncode})')
                    outcomes.append(OpOutcome(cur_op, key, rc.name, False, fail_detail(res)))
                for line in (res.output or res.cmd or '').strip().splitlines():
                    on_line(f'     {line}')              # show WHY here, not only in last-failure.hu
                failures.append(rec)
            elif cur_op in ('install', 'upgrade') and not pretend and not detected_after(drv, rc):
                # the op succeeded, but the component still reads "not installed" — a DETECTION bug (a
                # renamed package, a binary off PATH, an empty version marker). Say so NOW, not when the
                # user later wonders why it's listed missing.
                on_line(f'  -> ok, but NOT DETECTED afterwards — {rc.comp} will read "not installed" '
                        f'(a detection bug in its route/driver; `configsys report {rc.comp}`)')
                outcomes.append(OpOutcome(cur_op, key, rc.name, True, 'installed but not detected',
                                          undetected=True))
            else:
                on_line('  -> ok')
                outcomes.append(OpOutcome(cur_op, key, rc.name, True))
            # install RECEIPT (stranded.py): remember what configsys installed so the install stays
            # findable + removable after routes stop offering that method; forget it on removal.
            if (ledger is not None and not pretend
                    and outcomes and outcomes[-1].key == key and outcomes[-1].ok):
                if cur_op in ('install', 'upgrade', 'set-version'):
                    ledger.set_receipt(rc)
                elif cur_op == 'remove':
                    ledger.clear_receipt(key)
    finally:
        # whatever happened above — a driver bug, Ctrl-C, a failed write — the keep-alive is
        # released and what DID run is recorded (B10): a lock or receipt is never lost to a crash
        ctx.runner.end_sudo()      # release the batch's sudo keep-alive (one prompt covered the run)
        if ledger is not None and not pretend:      # a dry run records nothing (no locks, no receipts)
            ledger.save(ctx.paths)
        if not pretend:            # the unresolved-failures record (! page, `report`): this run's in, fixed ones out
            reportgen.record_run(ctx.paths, failures, [o.key for o in outcomes])
    return RunResult(outcomes, failures, n_fatal, rc_code, interrupted)


def fix_scope(ctx, rc, current):
    """Reinstall `rc` at the scope your config declares (it is installed at `current`) — the ONE
    reconcile step `configsys fix-scope` and the TUI `v` picker's "fix scope" row share. Returns
    (ok, message). Never edits the config."""
    from .drivers import get_driver
    drv = get_driver(rc.driver, ctx.runner, ctx.paths)
    if drv is None or not drv.honors_scope:
        return False, f'{rc.comp}: its install method has one fixed scope'
    target = drv.scope(rc)
    if current == target:
        return False, f'{rc.comp} is already installed at {target} scope'
    res = drv.reconcile_scope(rc, current, target)
    if res.ok:
        return True, f'{rc.comp}: moved from {current} to {target} scope'
    out = (res.output or res.cmd or '').strip().splitlines()
    return False, f'{rc.comp}: fix-scope failed (exit {res.returncode})' + (f': {out[-1]}' if out else '')


def unset_pin(ctx, name):
    """Drop the `pins:` entry for `name` — from your top config, else from the primary plugin that
    carries it — so the routes' default applies again. The ONE unpin writer the CLI (`pin unset`) and
    the TUI method picker ("auto — unpin") share. Returns (changed, label): label names where it was
    removed, why nothing changed, or PRETEND_NOT_SAVED."""
    top = ctx.paths.user_config_file
    local = plugins.read_pins(top) if Path(str(top)).exists() else {}
    pfile, prim = _primary_data_file(ctx)
    ppins = plugins.read_pins(pfile) if pfile else {}
    if name not in local and name not in ppins:
        return False, 'not pinned in your top config or primary plugin'
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    if name in local:
        del local[name]
        plugins.set_pins(top, local)
        where = 'top config'
    else:
        del ppins[name]
        plugins.set_pins(pfile, ppins)
        where = f'primary plugin {prim}'
    invalidate_location_cache(ctx)                # the method reverts -> where it installs may too
    _invalidate_for(ctx, 'pins')
    return True, where


def edit_target(ctx, *, create=False):
    '''(file, label) for a PORTABLE edit: the primary plugin's data file when a primary is blessed +
    synced (so edits travel to your other machines), else this machine's top config. NOTE: the
    primary layer sits BELOW the top config, so an edit here is only effective when a higher layer
    doesn't shadow it — profile/config edits use the effective-target helpers below instead.
    `create` (write paths) gives a primary with no data file yet an empty one (_primary_data_file);
    without it, display callers see the label a write would land under.'''
    pfile, prim = (_writable_primary_file(ctx) if create else _primary_target_label(ctx))
    if pfile:
        return pfile, prim
    return str(ctx.paths.user_config_file), 'top config'


def _nature_target(ctx, key, lives_in, *, create=False):
    '''(file, label) where an edit to `key` should land — the ONE policy scalars, picks, and
    dispositions all share, driven by SETTING_NATURE (declared config, not incidental file content).
    `lives_in(file) -> bool` says whether the edit's slice already exists in that file. Preference:
    the writable layer it already lives in (the local top config shadows the primary, so editing a
    lower layer would be ineffective), else the nature DEFAULT — the primary plugin for a 'uniform'
    key when one is blessed+synced (portable), else this box's top config (a 'machine' key, or no
    primary). `create` (write paths only) lets a primary with no data file yet get an empty one;
    without it a display caller still sees the label an edit WOULD land under.'''
    local = str(ctx.paths.user_config_file)
    if key in layers.TOP_CONFIG_ONLY:                  # read only from the top config: edited there
        return local, 'top config'
    pfile, pname = _primary_data_file(ctx)
    if lives_in(local):
        return local, 'top config'
    if pfile and lives_in(pfile):
        return pfile, pname
    if SETTING_NATURE.get(key) == 'uniform':
        if not pfile:
            pfile, pname = (_writable_primary_file(ctx) if create
                            else _primary_target_label(ctx))
        if pfile:
            return pfile, pname
    return local, 'top config'


UNINSTALL_PROFILE = '!uninstall'


# the settings the Resolver (or the paths it lays installs out with) reads — an edit to one rebuilds
# it; every other setting needs only the Config re-read (C3 / app-cli-10)
_ROUTING_SETTINGS = frozenset({'driver-preference', 'disabled-drivers', 'pins', 'dirs', 'locations',
                               'facets'})


# settings that move WHERE something installs (or which method / machine column applies): after
# one, the shells' glue-locations cache (trusted for an hour by the preludes) is stale (B17 /
# actions-10 — `config set dirs.app`, `scope`, `machine use`, … used to keep the old paths)
_LAYOUT_SETTINGS = _ROUTING_SETTINGS | {'scope', 'machine', 'picks'}


def _invalidate_for(ctx, key):
    top = str(key).split('.', 1)[0]
    if top in _LAYOUT_SETTINGS:
        invalidate_location_cache(ctx)
    if top in _ROUTING_SETTINGS:
        ctx.invalidate()
    else:
        _invalidate_config(ctx)


def _invalidate_config(ctx):
    '''Config-only invalidation (Context.invalidate_config) where the context has it.'''
    getattr(ctx, 'invalidate_config', ctx.invalidate)()


def stage_uninstall(ctx, comp, *, on=True):
    '''Stage (`on`) or unstage (`on=False`) `comp` in the top-level `uninstall:` queue — a
    machine-local (top-config) pending-removal list. Returns (changed, label). The TUI `x` calls
    this; the real uninstall runs later from TUI::Components (execute) — or `clear_uninstall` cancels.'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    tfile = str(ctx.paths.user_config_file)          # machine-local, like pins — never a plugin
    cur = plugins.read_list_section(tfile, 'uninstall')
    if on and comp not in cur:
        cur.append(comp)
    elif not on and comp in cur:
        cur.remove(comp)
    else:
        return False, ('already staged' if on else 'not staged')
    plugins.set_list_section(tfile, 'uninstall', cur)
    _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return True, Path(tfile).name


def stage_adopt(ctx, comp, machines=None):
    '''Adopt an orphan = start managing it: TRACK it (add to `picks:`) on `machines` (default: this
    box's current machine). The matrix equivalent of the old "park it in a staging profile" — an
    installed-but-untracked thing becomes a pick, and thus part of the install set. Tracking marks it
    seen. Returns (changed_count, label).'''
    machines = machines or [ctx.config.current_machine()]
    n, label = set_included(ctx, comp, machines, True)
    if n:
        mark_all_seen(ctx, [comp])
    return n, label


def set_disposition(ctx, comp, state):
    '''Set component `comp`'s disposition — 'seen' | 'interesting', or clear it (state None/'new').
    dispositions are `machine`-nature (SETTING_NATURE) -> the LOCAL top config by default (this box's
    triage), but honor an existing home if you've moved them. Returns (changed, label).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    tfile, label = _nature_target(ctx, 'dispositions', lambda f: bool(plugins.read_dispositions(f)))
    disp = plugins.read_dispositions(tfile)
    want = None if state in (None, 'new') else state
    if disp.get(comp) == want:
        return False, 'no change'
    if want is None:
        disp.pop(comp, None)
    else:
        disp[comp] = want
    plugins.set_dispositions(tfile, disp)
    _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return True, label


def _picks_target(ctx, machine, *, create=False):
    '''(file, label) for a picks edit on `machine`. picks are `uniform` (SETTING_NATURE) -> the
    portable primary plugin by default; a per-machine local list still overrides (shadow-guard).'''
    return _nature_target(ctx, 'picks', lambda f: machine in plugins.read_picks(f), create=create)


def set_included(ctx, comp, machines, on):
    '''v3 matrix A/D: mark `comp` Included (`on=True`) or not, on EACH machine in `machines` (plural =
    fan-out). Each machine's picks write to its PORTABLE target — the primary plugin by default, else
    this box's top config, and always the top config when it already overrides that machine (see
    _picks_target). Returns (changed_count, label naming where it landed).'''
    if _pretend(ctx):
        return 0, PRETEND_NOT_SAVED
    by_target = {}                                   # (file, label) -> [machines] (usually one target)
    for m in machines:
        by_target.setdefault(_picks_target(ctx, m, create=True), []).append(m)
    changed, labels = 0, set()
    for (tfile, label), ms in by_target.items():
        picks = plugins.read_picks(tfile)
        touched = False
        for m in ms:
            cur = list(picks.get(m, []))
            has = comp in cur
            if on and not has:
                cur.append(comp)
                changed += 1
                touched = True
            elif not on and has:
                cur = [c for c in cur if c != comp]
                changed += 1
                touched = True
            picks[m] = cur
        if touched:
            plugins.set_picks(tfile, picks)
            labels.add(label)
    if changed:
        invalidate_location_cache(ctx)               # the install set changed -> recompute glue locs
        _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return changed, ' + '.join(sorted(labels)) if labels else 'picks'


def set_included_clear_machine(ctx, machine):
    '''Drop a machine's entire `picks:` entry (when the machine is removed) — from BOTH the local top
    config and the primary plugin, since its picks may live in either. Returns (changed, label).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    changed = False
    pfile, _pn = _primary_data_file(ctx)
    files = {str(ctx.paths.user_config_file)} | ({str(pfile)} if pfile else set())
    for tfile in files:
        picks = plugins.read_picks(tfile)
        if machine in picks:
            picks.pop(machine, None)
            plugins.set_picks(tfile, picks)
            changed = True
    if changed:
        invalidate_location_cache(ctx)
        _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return changed, 'picks'


def move_picks_to_primary(ctx):
    '''Consolidate this box's LOCAL `picks:` into the primary plugin, so they travel to your other
    machines. Writes the current EFFECTIVE picks (the merged, local-wins view) to the primary and
    clears the local `picks:` node. No-op when there's no blessed+synced primary, or no local picks.
    Returns (moved_component_count, label). Dispositions are deliberately left local.'''
    if _pretend(ctx):
        return 0, PRETEND_NOT_SAVED
    prim_file, label = _writable_primary_file(ctx)
    if not prim_file:                                # no blessed+synced primary -> nowhere portable
        return 0, 'no primary'
    local_file = str(ctx.paths.user_config_file)
    local = plugins.read_picks(local_file)
    if not local:
        return 0, label
    effective = ctx.config.picks()                   # merged truth (a local list already wins per machine)
    plugins.set_picks(prim_file, effective)          # primary now carries the full effective set
    plugins.set_picks(local_file, {})                # ...and drop the local shadow
    _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return sum(len(v) for v in local.values()), label


def mark_all_seen(ctx, names):
    '''Mark every UNDISPOSITIONED (NEW) component in `names` as `seen`, in ONE write — leaving any
    existing seen/interesting flag alone (SEEN never clobbers a flag). Returns the count newly seen.
    Used by the `E` mass-acknowledge and by Include (tracked implies seen).'''
    if _pretend(ctx):
        return 0
    tfile = str(ctx.paths.user_config_file)
    disp = plugins.read_dispositions(tfile)
    added = 0
    for n in names:
        if n not in disp:                            # undispositioned -> seen; seen/interesting kept
            disp[n] = 'seen'
            added += 1
    if added:
        plugins.set_dispositions(tfile, disp)
        _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return added


def ignore_orphan(ctx, pattern):
    '''Append `pattern` (a name or glob) to the `orphans-ignore` list (idempotent). Returns
    (changed, label). The TUI `.` action + the `configsys orphans --ignore` verb share this intent.'''
    cur = list(ctx.config.orphans_ignore())
    if pattern in cur:
        return False, 'already ignored'
    return set_config_setting(ctx, 'orphans-ignore', cur + [pattern])


def unignore_orphan(ctx, pattern):
    '''Remove the LITERAL `pattern` from orphans-ignore (the un-ignore half of the `.` toggle). A
    glob-ignored orphan whose exact name isn't listed can't be un-ignored here (edit the glob).
    Returns (changed, label).'''
    cur = list(ctx.config.orphans_ignore())
    if pattern not in cur:
        return False, 'not literally ignored (glob?)'
    cur.remove(pattern)
    return set_config_setting(ctx, 'orphans-ignore', cur)


def clear_uninstall(ctx):
    '''Empty the `uninstall:` queue (cancel every pending removal). Returns how many were cleared.'''
    if _pretend(ctx):
        return 0
    n = len(ctx.config.uninstall_queue())
    if n:
        plugins.set_list_section(str(ctx.paths.user_config_file), 'uninstall', [])
        _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return n


def add_machine(ctx, name):
    '''Register a new machine as an empty column — an empty `picks:` entry (picks: IS the machine
    registry). Written to the portable pick target (primary if blessed, see _picks_target). Returns
    (changed, label); a bad/duplicate name returns (False, reason).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    name = (name or '').strip()
    if not name:
        return False, 'a machine name is required'
    if name in ctx.config.machine_names():
        return False, f'machine "{name}" already exists'
    tfile, label = _picks_target(ctx, name, create=True)
    picks = plugins.read_picks(tfile)
    picks[name] = picks.get(name, [])                      # an empty column
    plugins.set_picks(tfile, picks)
    _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    return True, label


def remove_machine(ctx, name):
    '''Delete a machine — drop its `picks:` entry from both layers. Returns (changed, label/reason).'''
    if name not in ctx.config.machine_names():
        return False, f'machine "{name}" is not defined'
    return set_included_clear_machine(ctx, name)


def rename_machine(ctx, old, new):
    '''Rename a machine: move its `picks:` entry (in whichever layer holds it) to `new`, and re-point
    the `machine:` selection if it named `old`. Returns (changed, reason).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    new = (new or '').strip()
    if not new:
        return False, 'a new name is required'
    if new == old:
        return False, 'same name'
    if new in ctx.config.machine_names():
        return False, f'machine "{new}" already exists'
    was_current = old == ctx.config.current_machine()
    if old not in ctx.config.machine_names() and not was_current:
        return False, f'no machine "{old}"'
    pfile, _pn = _primary_data_file(ctx)
    files = {str(ctx.paths.user_config_file)} | ({str(pfile)} if pfile else set())
    moved = False
    for f in files:
        picks = plugins.read_picks(f)
        if old in picks:
            picks[new] = picks.pop(old)
            plugins.set_picks(f, picks)
            moved = True
    if not moved:                                          # synthetic 'this-machine' with no picks yet
        tfile, _l = _picks_target(ctx, new, create=True)
        picks = plugins.read_picks(tfile)
        picks[new] = []
        plugins.set_picks(tfile, picks)
    _invalidate_config(ctx)   # the Resolver never reads these sections (C2)
    if was_current or ctx.config.selected_machine() == old:   # re-point this box's selection
        set_config_setting(ctx, 'machine', [new])
    return True, new


def set_machine_active(ctx, name):
    '''Set THIS box's `machine:` selection (local top config, machine-nature) — an empty name clears
    it. Returns (changed, label).'''
    return set_config_setting(ctx, 'machine', [name] if name else [])



# -- machine settings (`configsys config` + the TUI Config screen) --------------------------------
# key -> (kind, one-line descriptor, man page). The single source of truth the CLI and the TUI
# Config screen both read, so both describe each setting identically (docs/done/tui-screens-plan.md C1).
CONFIG_SETTINGS = {
    'scope':             ('scalar', 'Default install scope: user (~, the default when unset) or '
                                    'system (/opt, needs sudo).', 'configsys.hu(5)'),
    'driver-preference': ('list',   'Order ties between equally-valid install methods break in '
                                    '(unlisted drivers follow, in the default order).',
                          'configsys.hu(5)'),
    'disabled-drivers':  ('list',   'Install methods (via names) to turn OFF on this machine — their '
                                    'bindings stop matching, like a false when:, so a soft suggests is '
                                    'skipped (a hard requires errors). Use it to opt a mechanism out: '
                                    'dotfiles / glue to manage your own shell config, or e.g. snap.',
                          'configsys.hu(5)'),
    'auto-tighten':      ('bool',   'Auto-pick a floor-satisfying install method instead of only '
                                    'advising.', 'configsys.hu(5)'),
    'adopt-installed':   ('bool',   'Prefer an already-installed method/provider over the default '
                                    '(detection tier). On by default.', 'configsys.hu(5)'),
    'refresh-before-execute': ('scalar', 'Refresh the OS package index once before running staged '
                                    "ops: 'auto' (default, when the batch has a native install/"
                                    "upgrade), 'always', or 'never'.", 'configsys.hu(5)'),
    'install-overlay':   ('bool',   'Open TUI::Profiles with the install-state overlay on (installed '
                                    'underlined, installed-but-unpicked ⊙ coloured). On by default; O toggles it.',
                          'configsys.hu(5)'),
    'reboot-advice':     ('bool',   'After an op (and as a TUI chip), advise when a reboot is needed / '
                                    'services want a restart, via each distro\'s native check. On by '
                                    'default.', 'configsys.hu(5)'),
    'primary-push':      ('scalar', "When your primary plugin is pushed to its remote: 'ask' (default; "
                                    'offered when you quit the TUI with changes not pushed), '
                                    "'auto' (after each command that changes it, and when you quit "
                                    "the TUI), 'auto-on-quit' (only when you quit the TUI, Q "
                                    "included), or 'manual' (only `plugin push` / P).",
                          'configsys.hu(5)'),
    'primary-verify':    ('scalar', "Check your primary's incoming commits: 'signed' — sync and push "
                                    'take in commits from its remote only when each has a good '
                                    "signature from a key you trust; 'off' (default). Read only from "
                                    'your top config.', 'configsys.hu(5)'),
    'primary-trust':     ('scalar', "Whether your primary plugin's commands, glue, dotfiles and keys "
                                    "run without `plugin trust`: 'identity' (default — it is yours, "
                                    "whatever syncs in is trusted), 'content' (re-trust after every "
                                    "sync that changes it, like any plugin), 'signed' (trusted while "
                                    "its newest commit carries a good signature, else by content). "
                                    'Read only from your top config.', 'configsys.hu(5)'),
    'splash':            ('scalar', 'Startup wait-screen animation: a splash provider name, '
                                    "'random' to pick one at random each run, off to disable, or "
                                    'unset for the built-in default.',
                          'configsys.hu(5)'),
    'effects':           ('scalar', 'TUI motion: full (gradient + splash), reduced (no gradient, '
                                    'calmer splash), or none (no gradient or splash). Unset '
                                    'auto-picks reduced over SSH, else full. --effects overrides.',
                          'configsys.hu(5)'),
    'orphans-ignore':    ('list',   'Name-or-glob patterns whose matching orphans stay quiet in '
                                    '`configsys orphans` (matches a component name OR installed key).',
                          'configsys.hu(5)'),
    'machine': ('scalar', 'This box\'s machine name — which `picks:` column is "this machine". Unset '
                          'defaults to `this-machine`.',
                'configsys.hu(5)'),
    'detect-coexisting': ('bool',   'After inspect, also detect installs of a component via its OTHER '
                                    '(unmanaged) methods and show them as "also present". On by '
                                    'default.', 'configsys.hu(5)'),
    'installer-shell-writes': ('scalar', "Shell-rc guard: 'block' (default) snapshots your rc files "
                                    'around each install and reverts what an installer writes there '
                                    "(staged as glue for review); 'allow' turns the guard off.",
                               'configsys.hu(5)'),
    'installer-shell-writes-allow': ('list', 'Components exempt from the shell-rc guard — their '
                                    'installer may edit your rc files.', 'configsys.hu(5)'),
    'locations':         ('map',    'Per-component install-location overrides, <component>=<absolute '
                                    'path> tokens: find/manage that install HERE (scope-bypassing; '
                                    'path-based drivers honor it).', 'configsys.hu(5)'),
    # install-layout dirs (the `dirs:` section) — default < config < env (CONFIGSYS_*_DIR)
    'dirs.user':         ('dir',    'Base dir for user-scope installs (default ~). '
                                    'env CONFIGSYS_USERSCOPE_DIR wins.', 'configsys.hu(5)'),
    'dirs.system':       ('dir',    'Base dir for system-scope installs (default /opt). '
                                    'env CONFIGSYS_SYSTEMSCOPE_DIR wins.', 'configsys.hu(5)'),
    'dirs.app':          ('dir',    'Category dir for self-contained apps ($CONFIGSYS_APP_DIR, '
                                    'default apps).', 'configsys.hu(5)'),
    'dirs.sdk':          ('dir',    'Category dir for SDKs/libraries ($CONFIGSYS_SDK_DIR, '
                                    'default sdks).', 'configsys.hu(5)'),
    'dirs.src':          ('dir',    'Category dir for source trees ($CONFIGSYS_SRC_DIR, '
                                    'default src).', 'configsys.hu(5)'),
}

# Per-setting NATURE decides where a fresh edit lands by default: 'uniform' settings are the same
# on every machine, so they default to your primary plugin (portable); 'machine' settings are a
# truth about THIS box (scope, home/system layout), so they default to the top config (local). A
# per-setting `m` move overrides either way — see _setting_target / move_config_setting.
SETTING_NATURE = {
    'scope':             'machine',
    'driver-preference': 'uniform',
    'disabled-drivers':  'machine',           # "on THIS box I manage my own dotfiles/glue" (local; `m` to travel)
    'auto-tighten':      'uniform',
    'adopt-installed':   'uniform',
    'refresh-before-execute': 'uniform',      # a behavior preference (override per-machine with `m`)
    'install-overlay':   'uniform',           # a UI preference
    'reboot-advice':     'uniform',           # a behavior preference (override per-machine with `m`)
    'primary-push':      'uniform',           # it travels in the primary it governs
    'primary-verify':    'machine',           # top config only: the primary must not switch it off
    'primary-trust':     'machine',           # top config only: the primary must not grant itself trust
    'splash':            'uniform',
    'effects':           'machine',           # about THIS terminal/transport (SSH), not shared config
    'orphans-ignore':    'machine',           # acknowledged one-offs on THIS box, not shared config
    'machine':           'machine',           # which machine THIS box is — inherently per-box (local)
    'detect-coexisting': 'uniform',           # a behavior preference
    'installer-shell-writes': 'uniform',      # a safety posture you want on every box
    'installer-shell-writes-allow': 'uniform',
    'locations':         'machine',           # install paths are a truth about THIS box's disk
    'dirs.user':         'machine',
    'dirs.system':       'machine',
    'dirs.app':          'uniform',
    'dirs.sdk':          'uniform',
    'dirs.src':          'uniform',
    # the matrix sections (not scalar settings — routed via _nature_target, not `config` edits):
    'picks':             'uniform',           # the install set is meant to travel between machines
    'dispositions':      'machine',           # NEW/interesting triage is per-box, stays local
}


# key -> getter(config) for the EFFECTIVE value `config show` / the TUI display. Every non-`dir`
# setting in CONFIG_SETTINGS must appear here (config_settings indexes it, and a test pins the key
# sets equal) so a new setting can't silently show "(unset)". `dir` settings resolve via Paths.
_SETTING_GETTERS = {
    'scope':                  lambda c: c.default_scope(),
    'driver-preference':      lambda c: c.driver_preference(),
    'disabled-drivers':       lambda c: c.disabled_drivers(),
    'auto-tighten':           lambda c: c.auto_tighten(),
    'adopt-installed':        lambda c: c.adopt_installed(),
    'refresh-before-execute': lambda c: c.refresh_before_execute(),
    'install-overlay':        lambda c: c.install_overlay_default(),
    'reboot-advice':          lambda c: c.reboot_advice(),
    'primary-push':           lambda c: c.primary_push(),
    'primary-verify':         lambda c: c.primary_verify(),
    'primary-trust':          lambda c: c.primary_trust(),
    'splash':                 lambda c: c.splash(),
    'effects':                lambda c: c.effects(),
    'orphans-ignore':         lambda c: c.orphans_ignore(),
    'machine':                lambda c: c.selected_machine(),
    'detect-coexisting':      lambda c: c.detect_coexisting(),
    'installer-shell-writes': lambda c: 'block' if c.block_installer_shell_writes() else 'allow',
    'installer-shell-writes-allow': lambda c: c.shell_writes_allowlist(),
    'locations':              lambda c: _map_tokens(c.locations()),
}


def _map_tokens(mapping):
    '''A `map` setting's value as `key=value` tokens (what `config get` prints and `config set`
    takes; also what the TUI's generic list editor round-trips).'''
    return [f'{k}={v}' for k, v in sorted((mapping or {}).items())]


def location_problem(path):
    '''Why a `locations:` value is unusable, or None: it must be absolute or `~`-rooted (`~` is
    configsys's home, so --home stays a sandbox) — a relative path would land wherever configsys
    happened to run (config-layers-07). `..` parts are normalized away when it is used.'''
    s = str(path).strip()
    if not (s.startswith('/') or s == '~' or s.startswith('~/')):
        return f'{s!r} must be an absolute path or start with ~/'
    return None


def _parse_map_tokens(tokens):
    '''`component=path` tokens -> {component: path}, each path absolute or `~`-rooted. Raises
    ValueError on a token without `=` or a relative path.'''
    out = {}
    for t in tokens:
        k, sep, v = str(t).partition('=')
        if not sep or not k.strip() or not v.strip():
            raise ValueError(f'expected <component>=<path>, got {t!r}')
        why = location_problem(v)
        if why:
            raise ValueError(f'{k.strip()}: {why}')
        out[k.strip()] = os.path.normpath(v.strip()) if not v.strip().startswith('~') else v.strip()
    return out


def _read_map_section(config_file, key):
    '''The flat scalar map of a top-level `<key>: { … }` in ONE .hu file, or {}.'''
    from . import layers
    p = Path(config_file)
    if not p.exists():
        return {}
    data = layers.materialize_string(p.read_text(encoding='utf-8'))
    m = data.get(key) if isinstance(data, dict) else None
    return ({k: v for k, v in m.items() if not isinstance(v, (dict, list))}
            if isinstance(m, dict) else {})


def _set_map_section(config_file, key, mapping):
    '''Rewrite a top-level map `<key>: { k: v … }` in place, or remove the node when empty.'''
    from .troveio import _scalar
    if not mapping:
        plugins.remove_sections(config_file, [key])
        return
    plugins.set_section(config_file, key, lambda indent: '\n'.join(
        [f'{key}: {{']                               # set_section places the first line itself
        + [f'{" " * (indent + 4)}{_scalar(k)}: {_scalar(v)}' for k, v in mapping.items()]
        + [' ' * indent + '}']))


def _read_setting(config_file, key):
    '''The value of machine setting `key` in ONE .hu file (kind-aware), or None if absent.'''
    kind = CONFIG_SETTINGS[key][0]
    if kind == 'dir':
        return plugins.read_dirs(config_file).get(key.split('.', 1)[1])
    if kind == 'map':
        return _read_map_section(config_file, key) or None
    if kind == 'list':
        return plugins.read_list_section(config_file, key) or None
    return plugins.read_scalar_section(config_file, key)      # scalar + bool


def _setting_tokens(value, kind):
    '''A value read from a file back into the token list set_config_setting expects.'''
    if value is None:
        return []
    if kind == 'list':
        return list(value)
    if kind == 'map':
        return _map_tokens(value)
    if kind == 'bool':
        return ['true' if layers.parse_bool(value, False) else 'false']
    return [str(value)]                                       # scalar + dir


def _setting_home(ctx, key):
    '''(where, label) for machine setting `key`: whether it currently lives in this machine's top
    config ('local'), the primary plugin ('primary'), or neither (None = built-in/repo default).
    The top config shadows the primary, so it's checked first.'''
    local = str(ctx.paths.user_config_file)
    if _read_setting(local, key) is not None:
        return 'local', 'top config'
    pfile, pname = _primary_data_file(ctx)
    if pfile and _read_setting(pfile, key) is not None:
        return 'primary', pname
    return None, None


def _setting_target(ctx, key, *, create=False):
    '''(file, label) where an edit to machine setting `key` is EFFECTIVE: the writable layer it
    already lives in (editing a lower one would be shadowed), else its nature default — the primary
    plugin for a 'uniform' setting when one is blessed+synced, this machine's top config for a
    'machine' setting (or when no primary exists). Delegates to the shared _nature_target.'''
    return _nature_target(ctx, key, lambda f: _read_setting(f, key) is not None, create=create)


def config_settings(ctx):
    '''{key: {kind, value, desc, man}} — the effective machine settings for display (CLI
    `config show` and the TUI Config screen). Read-only.'''
    from .paths import CONFIG_DIR_KEYS
    cfg = ctx.config
    # derived from the registry: a setting without a getter is a KeyError here, never a silent "(unset)"
    values = {key: _SETTING_GETTERS[key](cfg)
              for key, (kind, _d, _m) in CONFIG_SETTINGS.items() if kind != 'dir'}
    cfg_dirs = cfg.install_dirs()
    env_map = getattr(ctx.paths, 'env', {}) or {}
    ucf = getattr(ctx.paths, 'user_config_file', None)    # absent in some test fakes -> skip homing
    out = {}
    for key, (kind, desc, man) in CONFIG_SETTINGS.items():
        if kind == 'dir':
            sub = key.split('.', 1)[1]                    # user/system/app/sdk/src
            env, default = CONFIG_DIR_KEYS[sub]
            envval = env_map.get(env)
            out[key] = {'kind': kind, 'value': envval or cfg_dirs.get(sub) or default,
                        'desc': desc, 'man': man,
                        'source': f'env ${env}' if envval else cfg.dir_source(sub)}
        else:
            src = cfg.machine_setting_source(key)         # (file, is_override) or None
            out[key] = {'kind': kind, 'value': values.get(key), 'desc': desc, 'man': man,
                        'source': src[0] if src and src[1] else None}
        out[key]['nature'] = SETTING_NATURE.get(key, 'uniform')
        if ucf:
            where, home_label = _setting_home(ctx, key)
            out[key]['home'] = where                      # 'local' | 'primary' | None (default)
            out[key]['home_label'] = home_label
            out[key]['target'] = _setting_target(ctx, key)[1]   # where an edit would land
    return out




def set_config_setting(ctx, key, values, *, target=None):
    '''Set machine setting `key` from `values` (tokens, parsed per the setting's kind); an empty
    `values` clears it. Returns (changed, target_label). Raises KeyError for an unknown key.'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    kind = CONFIG_SETTINGS[key][0]
    tfile, label = (target, target) if target else _setting_target(ctx, key, create=True)
    if kind == 'bool' and values and not layers.is_bool_token(values[0]):
        raise ValueError(f'{key} takes true or false (not {values[0]!r})')
    if (key in ('dirs.user', 'dirs.system') and values
            and not values[0].startswith(('/', '~'))):  # (app/sdk/src are relative to the base)
        raise ValueError(f'{key} takes an absolute path or one starting with ~ (not {values[0]!r}) '
                         '— a relative base would follow whatever directory configsys runs from')
    if kind == 'dir':                                     # nested `dirs.<sub>`: edit the dirs map
        sub = key.split('.', 1)[1]
        dirs = plugins.read_dirs(tfile)
        if values:
            dirs[sub] = values[0]
        else:
            dirs.pop(sub, None)
        plugins.set_dirs(tfile, dirs)
        _invalidate_for(ctx, key)
        return True, label
    if kind == 'map':                                     # `k=v` tokens replace the whole map
        _set_map_section(tfile, key, _parse_map_tokens(values) if values else {})
        if key == 'locations':
            invalidate_location_cache(ctx)                # WHERE things install just changed
        _invalidate_for(ctx, key)
        return True, label
    if not values:                                        # clear
        (plugins.set_list_section if kind == 'list' else plugins.set_scalar_section)(
            tfile, key, [] if kind == 'list' else None)
    elif kind == 'list':
        plugins.set_list_section(tfile, key, list(values))
    elif kind == 'bool':
        token = 'true' if layers.parse_bool(values[0], False) else 'false'
        plugins.set_section(tfile, key, lambda indent: f'{key}: {token}')   # bare humon bool
    else:                                                 # scalar
        choices = layers.SETTING_CHOICES.get(key)
        if choices and values[0].strip().lower() not in choices:
            raise ValueError(f'{key} takes one of {", ".join(choices)} (not {values[0]!r})')
        plugins.set_scalar_section(tfile, key, values[0].strip().lower() if choices else values[0])
    _invalidate_for(ctx, key)
    return True, label


def move_config_setting(ctx, key):
    '''Move machine setting `key` between this machine's top config and the primary plugin, carrying
    its effective value and clearing the source. The direction is inferred from where it lives now
    (local->primary, or primary->local); a setting at its built-in default has nothing to move.
    Returns (ok, message).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    if key in layers.TOP_CONFIG_ONLY:
        return False, f'{key} is read only from your top config, so it stays there'
    where, _who = _setting_home(ctx, key)
    if where is None:
        return False, f'{key} is at its default — set a value before moving it'
    kind = CONFIG_SETTINGS[key][0]
    local = str(ctx.paths.user_config_file)
    pfile, pname = _writable_primary_file(ctx) if where == 'local' else _primary_data_file(ctx)
    if where == 'local':
        if not pfile:
            return False, 'no primary plugin blessed + synced to move into'
        src, dst, dst_label = local, pfile, pname
    else:                                                 # primary -> local
        src, dst, dst_label = pfile, local, 'top config'
    tokens = _setting_tokens(_read_setting(src, key), kind)
    set_config_setting(ctx, key, tokens, target=dst)      # write the value at the destination
    set_config_setting(ctx, key, [], target=src)          # clear it from the source
    _invalidate_for(ctx, key)
    return True, f'{key} → {dst_label}'


# -- theme (`configsys theme` + the TUI theme editor) ---------------------------------------------
# The theme lives in the `theme:` section (colors / elements.<el>.<attr> / gradient); saving a theme
# writes a theme-only PLUGIN (portable/shareable), per docs/done/tui-screens-plan.md (T1).

_THEME_BOOL_ATTRS = ('bold', 'underline', 'reverse')


def theme_target(ctx, dotted_key=None, *, create=False):
    '''(file, label) for a theme edit of `dotted_key`: your top config when it ALREADY sets that key
    (it shadows the primary — an edit below it would change nothing you see; B17 / actions-12), else
    the portable edit_target (the primary when blessed, else the top config).'''
    local = str(ctx.paths.user_config_file)
    if dotted_key and Path(local).exists():
        node = plugins.read_theme(local)
        for part in dotted_key.split('.'):
            if not isinstance(node, dict) or part not in node:
                break
            node = node[part]
        else:
            return local, 'top config'
    return edit_target(ctx, create=create)


def set_theme_value(ctx, dotted_key, value, *, target=None):
    '''Set one theme value by dotted path (`colors.accent`, `elements.profile.fg`, `gradient.from`);
    `value=None` removes it. bold/underline/reverse coerce to a bool. Returns (changed, label).'''
    if value is not None:                              # refuse what the TUI would ignore (G6)
        from .tui.theme import theme_problems
        probe = {}
        node = probe
        parts = dotted_key.split('.')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        bad = theme_problems(probe, colors=None)
        if bad:
            raise ValueError(f'theme {bad[0][0]}: {bad[0][1]}')
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    tfile, label = (target, target) if target else theme_target(ctx, dotted_key, create=True)
    theme = plugins.read_theme(tfile)
    parts = dotted_key.split('.')
    node = theme
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    leaf = parts[-1]
    if value is None:
        node.pop(leaf, None)
    else:
        node[leaf] = layers.parse_bool(value, False) if leaf in _THEME_BOOL_ATTRS else value
    plugins.set_theme(tfile, theme)
    _invalidate_config(ctx)   # cosmetic: never routing (C3)
    return True, label


def theme_overrides(ctx):
    '''The MERGED theme overrides in effect (colors map / per-page roles + gradient / splash,
    empties dropped) — for display and for snapshotting into a theme plugin. A per-page
    `gradient: {enabled: false}` round-trips as `gradient: false`, and the splash choice is
    preserved, so save/load is faithful.'''
    t = ctx.config.theme()
    out = {}
    if t.get('colors'):
        out['colors'] = t['colors']
    pages = {}
    for page, spec in (t.get('pages') or {}).items():
        p = {}
        for k, v in spec.items():                     # roles (dict) + the reserved `gradient`
            if k == 'gradient':
                grad = dict(v) if isinstance(v, dict) else {}
                if v in (False, 'false', 'no', 'off') or grad.get('enabled') in (False, 'false', 'no', 'off'):
                    p['gradient'] = False             # explicit disable survives the round-trip
                else:
                    g = {gk: gv for gk, gv in grad.items() if gk != 'enabled'}
                    if g:
                        p['gradient'] = g
            elif v:
                p[k] = v
        if p:
            pages[page] = p
    if pages:
        out['pages'] = pages
    if t.get('splash') is not None:
        out['splash'] = t['splash']
    return out


def _plugin_theme(pdir):
    '''The merged `theme:` from a plugin dir's data .hu files, or {}.'''
    theme = {}
    for f in sorted(Path(pdir).glob('*.hu')):
        if f.name == 'plugin.hu':
            continue
        for k, v in plugins.read_theme(str(f)).items():
            if isinstance(v, dict):
                theme.setdefault(k, {}).update(v)
            else:
                theme[k] = v
    return theme


def theme_plugins(ctx):
    '''Names of on-disk plugins that carry a `theme:` block (the saved/available themes).'''
    pdir = Path(ctx.paths.plugins_dir)
    if not pdir.exists():
        return []
    return sorted(d.name for d in pdir.iterdir() if d.is_dir() and _plugin_theme(d))


def save_theme_plugin(ctx, name, *, force=False):
    '''Snapshot the current effective theme overrides into a theme-only plugin `name` under the
    plugins dir (data-only: plugin.hu + theme.hu). Returns (path, existed); refuses to overwrite an
    existing plugin unless `force` (the caller warns first).'''
    pdir = Path(ctx.paths.plugins_dir) / name
    existed = pdir.exists()
    if (existed and not force) or _pretend(ctx):     # --pretend: nothing written (caller checks _pretend)
        return pdir, existed
    from .tui import theme as _theme
    primarygit.will_write(pdir)                      # `force` over the primary itself is a write to it
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / 'plugin.hu').write_text(
        f'{{\n    name: {name}\n    requires-abi: {plugins.ABI_VERSION}\n'
        f'    data: [ theme.hu ]\n}}\n', encoding='utf-8')
    block = plugins._emit_kv('theme', _theme.full_snapshot(ctx.config.theme()), 4)   # full, not diff
    (pdir / 'theme.hu').write_text('{\n' + block + '\n}\n', encoding='utf-8')
    (pdir / 'dotfiles').mkdir(exist_ok=True)
    return pdir, existed


def _overlay_theme(base, top):
    '''`top` laid over `base`, per key all the way down (your override of one role keeps the pack's
    others).'''
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (base or {}).items()}
    for k, v in (top or {}).items():
        out[k] = _overlay_theme(out.get(k), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_theme(ctx, name, *, target=None, reset=False):
    '''Apply a saved theme plugin's `theme:` to the edit target. By default the pack goes UNDER your
    own theme overrides (they stay on top — decision 18); `reset=True` replaces them with the pack
    (the TUI asks first). Returns (changed, label|None).'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    theme = _plugin_theme(Path(ctx.paths.plugins_dir) / name)
    if not theme:
        return False, None
    tfile, label = (target, target) if target else edit_target(ctx, create=True)
    if not reset:
        theme = _overlay_theme(theme, plugins.read_theme(tfile))
    plugins.set_theme(tfile, theme)
    ctx.invalidate()
    return True, label


def copy_page_theme(ctx, src, dst):
    '''Copy one page's theme overrides (its role styles + gradient) onto another page, in the edit
    target. Returns (ok, label|reason). Nothing to copy if the source page has no overrides.'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    tfile, label = theme_target(ctx, f'pages.{dst}', create=True)
    theme = plugins.read_theme(tfile)
    pages = theme.setdefault('pages', {})
    merged = (ctx.config.theme().get('pages') or {}) if getattr(ctx, 'config', None) else {}
    srcov = merged.get(src) or pages.get(src)      # the page as you SEE it, whichever layer set it
    if not isinstance(srcov, dict) or not srcov:
        return False, f'{src} has no overrides to copy'
    pages[dst] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in srcov.items()}
    plugins.set_theme(tfile, theme)
    ctx.invalidate()
    return True, label


def _primary_data_file(ctx):
    '''The primary plugin's highest-precedence synced data file (where a theme/pin can be written so
    it travels with the primary), plus the primary's name — or (None, None) if no primary is blessed
    and synced. Mirrors the edit_target / _pin_promote idiom. Read-only; writers use
    _writable_primary_file.'''
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    if not prim:
        return None, None
    files = [f for f, role in plugins.layer_files(ctx.paths.plugins_dir, decls) if role == 'primary']
    return (files[0], prim) if files else (None, None)


def _writable_primary_file(ctx):
    '''_primary_data_file for a WRITE: a primary can legitimately have NO data file yet (`plugin
    init` on a config with no components/profiles scaffolds only the manifest), which would leave it
    unable to hold picks, pins or settings — so an empty `<name>.hu` is created on demand when that's
    safe (see _creatable_primary_file). Never under --pretend.'''
    pfile, prim = _primary_data_file(ctx)
    if pfile or getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return pfile, prim
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    new = _creatable_primary_file(ctx, decls, prim) if prim else None
    if new is None:
        return None, None
    primarygit.will_write(new)
    new.write_text('{\n}\n', encoding='utf-8')
    ctx.invalidate()
    return str(new), prim


def _creatable_primary_file(ctx, decls, prim):
    '''The path an empty primary data file can be created at, or None when that's not safe/possible:
    the primary must be synced, ABI-compatible, with no explicit manifest `data:` list (a new file
    would then be ignored — data files come from the `*.hu` glob otherwise) and no `sha256:` pin
    (a new file would change its content hash and quarantine it).'''
    decl = next((d for d in decls if d.get('primary')), None)
    if decl is None or decl.get('sha256'):
        return None
    pdir = Path(ctx.paths.plugins_dir) / plugins.dir_name(decl['source'])
    if not (pdir / 'plugin.hu').exists():
        return None
    manifest = plugins.read_manifest(pdir)
    if manifest.get('data') or not plugins._abi_ok(manifest):
        return None
    target = pdir / f'{pdir.name}.hu'
    return None if target.exists() else target


def _primary_target_label(ctx):
    '''(file_or_would_be_path, name) for DISPLAY: the primary's data file, else the path one would
    be created at on the first write — so "edits → <primary>" reads true before the file exists.
    Never creates anything.'''
    pfile, pname = _primary_data_file(ctx)
    if pfile:
        return pfile, pname
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    if prim:
        new = _creatable_primary_file(ctx, decls, prim)
        if new is not None:
            return str(new), prim
    return None, None


def primary_theme_target(ctx):
    '''The primary plugin's name if one is blessed AND synced (so a theme can be written into it),
    else None — used to offer/hide the "save into primary plugin" destination.'''
    return _primary_target_label(ctx)[1]


def save_theme_to_primary(ctx):
    '''PROMOTE the current look into the PRIMARY plugin as a COMPLETE theme (full snapshot, not just
    diffs) and MOVE it there — clearing any theme in the top config so the primary's now-absolute
    theme isn't shadowed. This is deliberately absolute: a full theme in the primary overrides any
    theme plugin (the caller confirms first). Returns (ok, label): the primary name, or a reason.'''
    if _pretend(ctx):
        return False, PRETEND_NOT_SAVED
    from .tui import theme as _theme
    target, prim = _writable_primary_file(ctx)
    if not target:
        return False, 'no primary plugin blessed/synced to promote into'
    plugins.set_theme(target, _theme.full_snapshot(ctx.config.theme()))
    if str(target) != str(ctx.paths.user_config_file) and plugins.read_theme(ctx.paths.user_config_file):
        plugins.set_theme(str(ctx.paths.user_config_file), {})   # move, not copy — drop the local one
    ctx.invalidate()
    return True, prim


# -- plugins (`configsys plugin` + the TUI Plugins screen) ----------------------------------------
# Orchestration extracted from cmd_plugin so the CLI and the TUI Plugins screen share one path
# (docs/done/tui-screens-plan.md, F3 slice 4). Each returns structured results (ok/message/sync-actions);
# the caller prints (CLI) or shows a note (TUI).

class DeclaredElsewhere(Exception):
    '''`ident` is declared by a plugin configsys doesn't own — editing that clone's manifest would
    dirty it (trust -> changed, a sha256 pin -> quarantined) and it can't be pushed.'''


def _locate_decl(ctx, ident):
    '''(config_file, decls, target) for the declared plugin `ident` — the top config, or the PRIMARY
    plugin's manifest `plugins:` (yours, and pushable). A plugin only some other plugin declares
    raises DeclaredElsewhere naming that plugin (B17 / actions-09: its checkout is not yours to
    edit). (None, None, None) if not found.'''
    pdir = ctx.paths.plugins_dir
    top = plugins.declared(ctx.paths.user_config_file)
    t = plugins.find_decl(top, pdir, ident)
    if t is not None:
        return ctx.paths.user_config_file, top, t
    prim = plugins.primary_name(top)
    if Path(pdir).exists():
        for sub in sorted(p for p in Path(pdir).iterdir() if p.is_dir()):
            decls = [d for d in (plugins._decl(e) for e in
                                 (plugins.read_manifest(sub).get('plugins') or [])) if d]
            t = plugins.find_decl(decls, pdir, ident)
            if t is None:
                continue
            if prim is not None and sub.name == prim:
                return sub / 'plugin.hu', decls, t
            raise DeclaredElsewhere(
                f'{ident} is declared by the plugin {sub.name}, not by you — remove or lock '
                f'{sub.name}, or list {ident} in your own config to override it')
    return None, None, None


def _verify_primary(ctx):
    try:
        return ctx.config.primary_verify() == 'signed'
    except Exception:                                  # noqa: BLE001 — no config yet: off
        return False


def plugin_sync(ctx, decls):
    '''Sync each declared plugin to its ref (transitive fixpoint). Returns [(name, action)].'''
    ctx.ensure_plugin_code()     # register transports from already-trusted plugins before sync
    results = plugins.sync(ctx.runner, ctx.paths.plugins_dir, decls,
                           locked=_locks(ctx), verify_primary=_verify_primary(ctx))
    ctx.invalidate()             # new data files / drivers are now on disk — rebuild so they surface
    invalidate_location_cache(ctx)   # a synced plugin can MOVE installs (e.g. a build `dir:`): the
    # shell glue must not keep pointing at the old place for the cache's hour
    return results


def plugin_add(ctx, source, ref=None, *, local=False, pin=False, replace=False):
    '''Sync-FIRST add: a source that can't be cloned declares nothing. Lands in the primary's
    transitive `plugins:` (portable) when a primary is set, else this machine's top config (or with
    `local=True`). `pin` records the synced content sha256. If a plugin of the same NAME is already
    declared from a DIFFERENT source, refuse unless `replace=True` (then drop the old one first — the
    easy way to swap an in-development local copy for its published version). Returns (ok, message,
    sync_results).'''
    import shutil
    pretend = bool(getattr(ctx.runner, 'pretend', False))
    if not pretend:
        ctx.ensure_user_config()
    # a local-path source is saved ABSOLUTE (resolved from the CWD now), so the decl doesn't silently
    # point elsewhere when configsys is later run from another directory. Remote sources pass through.
    source = plugins.abs_local_source(source)
    # collision: another declared plugin lands in the same synced dir (same name) from a different
    # source. They'd clobber each other, so require an explicit --replace.
    new_dn = plugins.dir_name(source)
    clashes = [d for d in plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
               if plugins.dir_name(d['source']) == new_dn and d['source'] != source]
    if new_dn in _locks(ctx):
        return False, f"'{new_dn}' is locked on this machine — unlock it first (configsys plugin unlock {new_dn})", []
    if clashes and not replace:
        others = ', '.join(sorted({d['source'] for d in clashes}))
        return (False, f"a plugin named '{new_dn}' is already declared from {others}; "
                       f"re-run with --replace to swap it for {source}", [])

    # A retarget REUSES the synced dir (a clash shares dir_name), and the git transport only clones a
    # fresh source into an EMPTY dir — so move the old dir aside, then sync. Crucially, DON'T drop the
    # old declaration until the new source actually syncs: a failed retarget must never leave you with
    # the old plugin gone and nothing added (the bug this guards against).
    retargeting = bool(clashes and replace)
    pdir = ctx.paths.plugins_dir / new_dn
    backup = pdir.with_name(pdir.name + '.configsys-retarget-bak')
    moved = False
    # work in the old clone that exists nowhere else (unpushed commits, edits, authored in place) is
    # never deleted by a swap: that copy is KEPT, renamed `<name>.replaced-<stamp>` (A3)
    kept_lost = primarygit.local_work(pdir, clashes[0]['source']) if retargeting else []
    was_primary = retargeting and any(d.get('primary') for d in clashes)
    if retargeting and pdir.exists() and not ctx.runner.pretend:
        if backup.exists():
            if primarygit.local_work(backup):
                import time as _time
                backup.rename(backup.with_name(f'{pdir.name}.replaced-{_time.strftime("%Y%m%d-%H%M%S")}-old'))
            else:
                shutil.rmtree(backup)
        pdir.rename(backup)                              # clear the dir so the new source clones clean
        moved = True

    results = plugin_sync(ctx, [{'source': source, 'ref': ref}])
    if not results or not plugins.sync_succeeded(results[0][1]):
        if moved:                                        # restore the old synced dir; decls untouched
            if pdir.exists():
                shutil.rmtree(pdir)
            backup.rename(pdir)
        return False, f'could not sync {source} — nothing changed {plugins.source_hint(source)}', results
    kept_note = ''
    if moved and backup.exists():                        # new source synced OK -> discard the backup
        if kept_lost:                                    # ...unless it holds work found nowhere else
            import time as _time
            keep = pdir.with_name(f'{pdir.name}.replaced-{_time.strftime("%Y%m%d-%H%M%S")}')
            backup.rename(keep)
            kept_note = (f'\nkept the old copy at {keep} — it held ' + '; '.join(kept_lost))
        else:
            shutil.rmtree(backup)

    if pretend:                                      # a dry run declares nothing (no config writes)
        decls = plugins.declared(ctx.paths.user_config_file)
        primary = plugins.primary_name(decls)
        where = (f'the primary plugin ({primary})' if primary and not local
                 else 'your top config' + (' (this machine only)' if primary else ''))
        swap = (f', replacing {", ".join(sorted({d["source"] for d in clashes}))}'
                if retargeting else '')
        return True, (f'[pretend] would declare {source}' + (f' @{ref}' if ref else '')
                      + f' in {where}{swap}' + (' with a sha256 pin' if pin else '')), results

    # sync confirmed: NOW drop the old clashing decl(s) — keep_dir, since the synced dir is the new
    # content, not the old one to delete.
    if retargeting:
        for old in {d['source'] for d in clashes}:
            plugin_remove(ctx, old, keep_dir=True)

    decls = plugins.declared(ctx.paths.user_config_file)
    primary = plugins.primary_name(decls)
    primary_dir = ctx.paths.plugins_dir / primary if primary else None
    to_primary = (primary is not None and not local and primary_dir is not None
                  and (primary_dir / 'plugin.hu').exists())
    lead = ''
    if to_primary:
        cfg_file = primary_dir / 'plugin.hu'
        if plugins.ensure_branch(ctx.runner, primary_dir) is None and not ctx.runner.pretend:
            lead = (f'note — {primary} is in a detached HEAD with no branch to author on; '
                    f'commit by hand or pin it to a branch (ref: main)\n')
        cur = [d for d in (plugins._decl(e) for e in
                           (plugins.read_manifest(primary_dir).get('plugins') or [])) if d]
    else:
        cfg_file, cur = ctx.paths.user_config_file, decls
    target, existing = plugins.upsert_decl(cur, source, ref)
    if was_primary:                                  # a swap keeps the primary designation (A3)
        for d in cur:
            d.pop('primary', None)
        target['primary'] = True
    plugins.set_declared(cfg_file, cur)
    pin_msg = ''
    if pin:                                          # trust-on-first-use content pin
        pdir = ctx.paths.plugins_dir / plugins.dir_name(source)
        h = plugins.plugin_identity(pdir)
        if h:
            target['sha256'] = h
            plugins.set_declared(cfg_file, cur)
            disp = plugins.read_manifest(pdir).get('name', plugins.dir_name(source))
            pin_msg = f'\npinned {disp} @ {h.split(":")[-1][:12]} (sha256)'
    ctx.invalidate()
    verb, at = ('re-pinned' if existing else 'added'), (f' @{ref}' if ref else '')
    if to_primary:
        msg = (f'{verb} {source}{at} in your primary plugin ({primary}) — `configsys plugin push` '
               f'shares it with your other machines')
    else:
        msg = f'{verb} {source}{at}' + (' (this machine only)' if primary else '')
    return True, lead + msg + pin_msg + kept_note, results


def plugin_remove(ctx, ident, *, keep_dir=False, force=False):
    '''Undeclare a plugin (wherever it's declared) + delete its synced dir. `keep_dir` drops only the
    declaration and leaves the synced dir — used by a retarget, where the new source has just re-synced
    into that same dir (dir_name is shared). A clone holding work that exists nowhere else (uncommitted
    edits, unpushed commits, stashes, no remote, authored in place — `primarygit.local_work`) is
    refused, naming what would be lost, unless `force` (review-2026-11-2 A3). Returns (ok, message).'''
    import shutil
    try:
        cfg_file, cur, target = _locate_decl(ctx, ident)
    except DeclaredElsewhere as e:
        return False, str(e)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
    # defense in depth: dir_name already guarantees a contained segment, but never rmtree a path
    # that resolves outside the plugins dir (a symlinked plugins_dir, or a future dir_name change).
    if pdir.exists() and pdir.resolve().parent != ctx.paths.plugins_dir.resolve():
        return False, f'refusing to remove {pdir} — outside the plugins dir'
    if not keep_dir and not force:
        lost = primarygit.local_work(pdir, target['source'])
        if lost:
            name = plugins.dir_name(target['source'])
            hint = ('push it first (configsys plugin push)' if target.get('primary')
                    else 'commit and push it from that directory first')
            return False, (f'not removing {name}: deleting {pdir} would lose ' + '; '.join(lost)
                           + f' — {hint}, or re-run with --force to delete it anyway')
    if getattr(ctx.runner, 'pretend', False):
        return True, (f'[pretend] would remove {target["source"]}'
                      + ('' if keep_dir else ' and delete its synced dir'))
    plugins.set_declared(cfg_file, [d for d in cur if d is not target])
    if pdir.exists() and not ctx.runner.pretend and not keep_dir:
        shutil.rmtree(pdir)
    ctx.invalidate()
    where = ('' if str(cfg_file) == str(ctx.paths.user_config_file)
             else f' from {Path(cfg_file).parent.name}')
    return True, f'removed {target["source"]}{where}'


def plugin_update(ctx, ident, ref=None, *, pin=False, latest=False):
    '''Re-pin a declared plugin's ref (if given) and re-sync it; `pin` re-records its sha256.
    `latest` resolves the ref from the REMOTE — the newest stable version tag, else main/master
    (see plugins.latest_ref) — and is mutually exclusive with an explicit `ref`. Returns
    (ok, message, results).'''
    try:
        cfg_file, cur, target = _locate_decl(ctx, ident)
    except DeclaredElsewhere as e:
        return False, str(e), []
    if target is None:
        return False, f'no declared plugin matches {ident!r}', []
    locked = _locked_note(ctx, target, 'update')
    if locked:
        return False, locked, []
    latest_note = ''
    pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
    if latest and ref:
        return False, 'pass either --ref or --latest, not both', []
    if latest and target.get('primary') and plugins.follows_branch(ctx.runner, pdir, target.get('ref')):
        # a primary follows its branch and is never re-pinned to a version tag: just re-sync it
        latest = False
        latest_note = ' (your primary follows its branch)'
    if latest:
        ref, kind = plugins.latest_ref(ctx.runner, target['source'])
        if ref is None:
            return False, (f'could not resolve --latest for {target["source"]} — no version tags '
                           f'and no main/master branch (unreachable or private?)'), []
        latest_note = f' (latest {kind})'
    pretend = bool(getattr(ctx.runner, 'pretend', False))
    if pretend:                                          # a dry run: show the sync, edit nothing
        results = plugin_sync(ctx, [{**target, 'ref': ref or target.get('ref')}])
        return True, (f'[pretend] would re-pin {target["source"]} @{ref}{latest_note}' if ref
                      else f'[pretend] would re-sync {target["source"]}'), results
    # sync FIRST at the new ref; the declaration changes only once the clone is there (B17 /
    # actions-08 — a bad --ref used to be written, and every later sync failed)
    results = plugin_sync(ctx, [{**target, 'ref': ref or target.get('ref')}])
    outcome = results[0][1] if results else 'failed'
    if not plugins.sync_succeeded(outcome, moved=bool(ref)):
        why = plugins.sync_note(plugins.dir_name(target['source']), outcome, ctx.paths.plugins_dir,
                                primary=bool(target.get('primary')))
        return False, (why or f'could not sync {target["source"]}'
                       + (f' @{ref}' if ref else '') + f' ({outcome})') + ' — nothing changed', results
    if ref:
        target['ref'] = ref
        plugins.set_declared(cfg_file, cur)
    warn = ''
    if pin:
        h = plugins.plugin_identity(ctx.paths.plugins_dir / plugins.dir_name(target['source']))
        if h:
            target['sha256'] = h
            plugins.set_declared(cfg_file, cur)
    elif target.get('sha256') and not plugins.checksum_ok(ctx.paths.plugins_dir, target):
        warn = (f' — warning: {plugins.dir_name(target["source"])} no longer matches its pinned '
                f'sha256; quarantined until you re-pin (update --pin) or drop it')
    ctx.invalidate()
    where = '' if str(cfg_file) == str(ctx.paths.user_config_file) else f' in {Path(cfg_file).parent.name}'
    msg = (f're-pinned {target["source"]} @{ref}{latest_note}{where}' if ref
           else f're-synced {target["source"]}{latest_note}')
    return True, msg + warn, results


def plugin_update_all(ctx, *, latest=True, pin=False):
    '''Update EVERY declared plugin (top + transitive) — the bulk counterpart to a single
    `plugin update`, mirroring `plugin sync`'s get-'em-all reach. With `latest` (the default), each
    is re-pinned to its newest remote version tag, else main/master (see plugins.latest_ref); a
    locally-authored plugin (edited in place, never fetched) is skipped. Returns [(source, ok, msg)]
    in declared order, deduped by source.'''
    decls = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    out, seen = [], set()
    for d in decls:
        src = d['source']
        if src in seen:
            continue
        seen.add(src)
        dest = ctx.paths.plugins_dir / plugins.dir_name(src)
        if latest and plugins.is_local_authored(src, dest):
            out.append((src, True, 'local — skipped (authored in place)'))
            continue
        if plugins.dir_name(src) in _locks(ctx):
            out.append((src, True, f'{plugins.dir_name(src)}: locked — skipped'))
            continue
        ok, msg, _results = plugin_update(ctx, src, pin=pin, latest=latest)
        out.append((src, ok, msg))
    return out


def plugin_bless(ctx, ident):
    '''Make `ident` the sole `primary` plugin. Syncs it FIRST (+ its transitive plugins); only on a
    good sync does it declare + mark primary (clearing any other). Returns (ok, message, results).'''
    ctx.ensure_user_config()
    decls = plugins.declared(ctx.paths.user_config_file)
    existing = plugins.find_decl(decls, ctx.paths.plugins_dir, ident)
    source = existing['source'] if existing else ident
    ref = existing.get('ref') if existing else None
    locked = _locked_note(ctx, {'source': source}, 'bless')
    if locked:
        return False, locked, []
    results = plugin_sync(ctx, [{'source': source, 'ref': ref, 'primary': True}])   # on its branch
    if not results or not plugins.sync_succeeded(results[0][1]):
        why = plugins.sync_note(plugins.dir_name(source), results[0][1], ctx.paths.plugins_dir,
                                primary=True) if results else None
        return False, (why or f"could not find/sync '{ident}'") + ' — nothing changed', results
    if existing is None:
        existing = {'source': source, 'ref': ref}
        decls.append(existing)
    if not existing.get('ref'):                      # a primary follows a branch: record which one
        branch = plugins.default_branch(ctx.runner, ctx.paths.plugins_dir / plugins.dir_name(source))
        if branch:
            existing['ref'] = branch
    for d in decls:
        d.pop('primary', None)                       # exactly one primary
    existing['primary'] = True
    if ctx.runner.pretend:
        return True, f'[pretend] would bless {plugins.dir_name(source)} as primary', results
    plugins.set_declared(ctx.paths.user_config_file, decls)
    ctx.invalidate()
    return True, f'blessed {plugins.dir_name(source)} as primary (its machine settings now apply)', results


def plugin_unbless(ctx):
    '''Clear the primary designation. Returns (ok, message).'''
    decls = plugins.declared(ctx.paths.user_config_file)
    if not any(d.get('primary') for d in decls):
        return False, 'no primary plugin set'
    if ctx.runner.pretend:
        return True, '[pretend] would clear the primary designation'
    for d in decls:
        d.pop('primary', None)
    plugins.set_declared(ctx.paths.user_config_file, decls)
    ctx.invalidate()
    return True, 'cleared the primary designation'


def plugin_trust(ctx, ident):
    '''Approve a code plugin's CURRENT content to run during installs (trust-on-content-hash).
    Returns (ok, note). Mirrors `configsys plugin trust`.'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    key = plugins.dir_name(target['source'])
    pdir = Path(ctx.paths.plugins_dir) / key
    locked = _locked_note(ctx, target, 'trust')
    if locked:
        return False, locked
    if not pdir.exists():
        return False, f'{key} is not synced — sync it first'
    manifest = plugins.read_manifest(pdir)
    disp = manifest.get('name', key)
    has_code = bool(manifest.get('code'))
    has_recipes = plugins.ships_executable_data(pdir)
    if not has_code and not has_recipes:
        return False, f'{disp} ships no code or executable recipes — nothing to trust'
    identity = plugins.plugin_identity(pdir)
    if identity is None:
        return False, f'could not read {disp}’s contents'
    if _pretend(ctx):
        return False, f'[pretend] would trust {disp} @ {identity.split(":")[-1][:12]} — not saved'
    plugins.set_trust(ctx.paths.plugin_trust_file, key, identity)
    ctx.invalidate()
    what = 'its code' if has_code else 'its recipes'
    if has_code and has_recipes:
        what = 'its code + recipes'
    return True, f'trusted {disp} @ {identity.split(":")[-1][:12]} — {what} will run'


def plugin_trust_all(ctx):
    '''Trust EVERY plugin currently untrusted or changed — code OR command-carrying recipes (the bulk
    `T` / `plugin trust --all`). Returns (n_trusted, note); the note's first line is a summary (what
    the TUI shows), followed by one `verb name` line per plugin. Unsynced trustable plugins are
    counted in the note but skipped (nothing on disk to hash yet).'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    rows = plugins.status(ctx.paths.plugins_dir, eff, trust_file=ctx.paths.plugin_trust_file,
                          lock_file=getattr(ctx.paths, 'plugin_lock_file', None))
    held = [r for r in rows if r['locked'] and r['code_state'] in ('untrusted', 'changed')]
    pending = [r for r in rows if not r['locked'] and r['code_state'] in ('untrusted', 'changed')]
    unsynced = [r for r in rows if r['code_state'] == 'unsynced']
    n, detail = 0, []
    if pending and _pretend(ctx):
        return 0, '\n'.join([f'[pretend] would trust {len(pending)} plugin(s) — not saved']
                             + [f'  {r["name"]}' for r in pending])
    for r in pending:
        ok, _note = plugin_trust(ctx, r['name'])
        if ok:
            n += 1
            detail.append(f'  {"re-approved" if r["code_state"] == "changed" else "trusted":11} {r["name"]}')
    if not pending:
        return 0, ('no untrusted plugins'
                   + (' (some ship code/recipes but are unsynced — sync first)' if unsynced else '')
                   + (f' ({len(held)} locked left untrusted)' if held else ''))
    tail = (f'; {len(unsynced)} unsynced skipped' if unsynced else '') + (
        f'; {len(held)} locked skipped' if held else '')
    return n, '\n'.join([f'trusted {n} plugin(s){tail}'] + detail)


def plugin_untrust(ctx, ident):
    '''Revoke a code plugin's trust. Returns (ok, note). Mirrors `configsys plugin untrust`.'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    key = plugins.dir_name(target['source']) if target else ident
    pdir = Path(ctx.paths.plugins_dir) / key
    disp = plugins.read_manifest(pdir).get('name', key) if pdir.exists() else key
    if key not in plugins.read_trust(ctx.paths.plugin_trust_file):
        return False, f'{disp} was not trusted'
    if _pretend(ctx):
        return False, f'[pretend] would untrust {disp} — not saved'
    plugins.remove_trust(ctx.paths.plugin_trust_file, key)
    ctx.invalidate()
    return True, f'untrusted {disp}'


def _locks(ctx):
    return plugins.read_locks(getattr(ctx.paths, 'plugin_lock_file', None))


def _locked_note(ctx, decl, verb):
    '''The refusal for `verb` on a locked plugin, or None when it isn't locked.'''
    key = plugins.dir_name(decl['source'])
    when = _locks(ctx).get(key)
    if when is None:
        return None
    return f'{key} is locked (since {when}) — no {verb}; unlock it first (configsys plugin unlock {key})'


def plugin_lock(ctx, ident):
    '''Lock a declared plugin on this machine: sync leaves it as it is, update / bless / trust
    refuse it, and what is already on disk keeps loading. Returns (ok, note).'''
    import datetime
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    key = plugins.dir_name(target['source'])
    if key in _locks(ctx):
        return False, f'{key} is already locked'
    if getattr(ctx.runner, 'pretend', False):
        return False, PRETEND_NOT_SAVED
    plugins.set_lock(ctx.paths.plugin_lock_file, key, datetime.date.today().isoformat())
    synced = (Path(ctx.paths.plugins_dir) / key).exists()
    return True, (f'locked {key} — no sync, update or trust until you unlock it'
                  + ('; its synced copy still loads (remove it to stop that)' if synced else ''))


def plugin_unlock(ctx, ident):
    '''Lift a plugin's lock. Returns (ok, note).'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    key = plugins.dir_name(target['source']) if target else ident
    if key not in _locks(ctx):
        return False, f'{key} is not locked'
    if getattr(ctx.runner, 'pretend', False):
        return False, PRETEND_NOT_SAVED
    plugins.remove_lock(ctx.paths.plugin_lock_file, key)
    return True, f'unlocked {key}'


def plugin_review_plan(row, remote):
    '''What the review diff compares for a plugin status `row`, given its resolved remote-ref
    (`remote`: a ref string, or None). Returns (kind, base, target, what):
      kind 'synced'   — the on-disk copy (HEAD) -> remote-ref: what an update would pull in;
      kind 'review'   — two refs of the remote, fetched into the review cache (unsynced): the
                        declared ref -> remote-ref, or, with base None, the whole content at
                        target — what a sync would download (no ref, or the ref is already newest);
      kind None       — nothing to compare (`what` says why).'''
    ref = row.get('ref')
    if row.get('synced'):
        if not remote:
            return None, None, None, 'no upstream ref to compare against'
        return 'synced', 'HEAD', remote, 'what an update would change'
    if ref and remote and ref != remote:
        return 'review', ref, remote, 'not synced — what the newer remote changes'
    target = ref or remote
    if not target:
        return None, None, None, 'no ref to review (remote unreachable?)'
    return 'review', None, target, 'not synced — everything a sync would download'


def plugin_review(ctx, decl, row, remote):
    '''Run the review diff plugin_review_plan picks. Returns (files, note, plan).'''
    plan = plugin_review_plan(row, remote)
    kind, base, target, what = plan
    if kind is None:
        return [], what, plan
    if kind == 'synced':
        files, err = plugins.diff_against_ref(ctx.runner, ctx.paths.plugins_dir, decl, target)
        return files, err or ('' if files else 'up to date — nothing to pull in'), plan
    files, err = plugins.review_diff(ctx.runner, ctx.paths.plugin_review_dir, decl, base, target)
    return files, err or ('' if files else f'{base} and {target} are identical'), plan


# -- dotfiles (`configsys dotfiles` + the TUI Dotfiles screen) ------------------------------------

def dotfiles_units(ctx):
    '''(driver, [ResolvedComponent]) — the via:dotfiles units in the active profiles. Resolution
    only (no install-state query), cheap + side-effect-free. Shared by the CLI + the TUI screen.'''
    from .drivers import get_driver
    held = getattr(ctx, 'pipeline_units', None)
    if held and held[0] == id(ctx.routes) and held[1] == id(ctx.config):
        units = held[2]                    # the pipeline's resolution (its detected + floor pins)
    else:                                  # no pipeline ran (`dotfiles status`): resolve now
        units, _errs = ctx.routes.resolve_resilient(list(ctx.config.requested()))
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    # both the config (dotfiles) and glue (glue) units — the screen dispatches per-unit to the
    # right driver. (Phase 2 splits these into separate glue/dotfiles pages.)
    return df, [units[k] for k in sorted(units) if units[k].driver in ('dotfiles', 'glue')]
