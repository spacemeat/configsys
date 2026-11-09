'''cli/refresh.py — `configsys refresh`, the native package-index refresh (also run before a batch per
`refresh-before-execute`), and index-failure diagnosis: broken sources, key rotation, rekey.

Split out of app.py (review-2026-11-2 D2).
'''

import os
import re
from pathlib import Path
from ..drivers import get_driver
from ..ledger import Ledger
from .common import print_reboot_advisory


def _owned_index_sources(ctx):
    '''{system source-file path -> owning component} for every route binding that writes a native
    package source (apt `source-path`, dnf `/etc/yum.repos.d/<repo-id>.repo`). Lets the refresh
    diagnosis say "this broken source is one configsys wrote, for component X" vs a foreign file.'''
    owned = {}
    try:
        comps = ctx.routes.components
    except Exception:
        return owned
    for name, comp in comps.items():
        for b in getattr(comp, 'bindings', []) or []:
            d = getattr(b, 'details', {}) or {}
            sp = d.get('source-path')
            if sp:
                owned[str(sp)] = name
            rid = d.get('repo-id')
            if rid:
                owned[f'/etc/yum.repos.d/{rid}.repo'] = name
    return owned


_INDEX_SRC_DIRS = {
    'apt': ('/etc/apt/sources.list.d', '/etc/apt/sources.list'),
    'dnf': ('/etc/yum.repos.d',),
    'zypper': ('/etc/zypp/repos.d',),
}


def _list_source_files(dirs, exists=os.path.exists, listdir=os.listdir):
    '''Every file under the given package-manager source dirs (a dir is enumerated, a bare file
    included as-is). Best-effort + injectable for tests.'''
    files = []
    for d in dirs:
        if not exists(d):
            continue
        if os.path.isdir(d):
            files += [os.path.join(d, n) for n in sorted(listdir(d))]
        else:
            files.append(d)
    return files


def _find_source_files(urls, dirs, exists=os.path.exists, listdir=os.listdir,
                       read=lambda p: Path(p).read_text(errors='replace')):
    '''{source-file -> the failing url it contains} by scanning the package-manager source dirs for
    any of `urls`. Best-effort + fully injectable for tests; unreadable files are skipped.'''
    found = {}
    for f in _list_source_files(dirs, exists, listdir):
        try:
            text = read(f)
        except Exception:
            continue
        for u in urls:
            if u in text:
                found[f] = u
                break
    return found


def diagnose_index_failure(output, pm, owned, *, finder=_find_source_files):
    '''Lines diagnosing a failed native index refresh (Theme 1, diagnose-only): the classified
    cause + remediation, and the source file(s) mentioning the failing repo url — each flagged as
    configsys-managed (naming the component) or foreign. `owned` is _owned_index_sources()'s map.
    Returns [] when nothing is recognised (caller then leaves the raw tool output to speak).'''
    from .. import failures
    lines = []
    cat, rem = failures.classify(output)
    if cat:
        lines.append(f'Likely cause: {cat}')
        if rem:
            lines.append(f'Fix: {rem}')
    # the repo urls apt/dnf named in the error — trim a trailing "binary/"/"Release"/quote noise
    urls = sorted({re.sub(r'[)\'">,]+$', '', u) for u in re.findall(r'https?://[^\s\'">]+', output)})
    culprits = finder(urls, _INDEX_SRC_DIRS.get(pm, ())) if urls else {}
    for f in sorted(culprits):
        comp = owned.get(f)
        if comp:
            lines.append(f'Source: {f}  — written by configsys for component `{comp}`')
        else:
            lines.append(f'Source: {f}  — NOT managed by configsys (a file you or another tool added)')
    if urls and not culprits:
        lines.append(f'Affected repo(s): {", ".join(urls[:3])} (source file not located under '
                     f'{", ".join(_INDEX_SRC_DIRS.get(pm, ())) or "the package sources"})')
    return lines


def _source_key_fields(ctx, component, src_path):
    '''(pubkey-url, pubkey-path) for the route binding of `component` that writes `src_path` (or the
    dnf `/etc/yum.repos.d/<repo-id>.repo`), else (None, None). Lets refresh re-fetch a rotated key.'''
    try:
        comp = ctx.routes.components.get(component)
    except Exception:
        comp = None
    for b in getattr(comp, 'bindings', []) or []:
        d = getattr(b, 'details', {}) or {}
        rid = d.get('repo-id')
        if str(d.get('source-path') or '') == src_path or (rid and f'/etc/yum.repos.d/{rid}.repo' == src_path):
            return d.get('pubkey-url'), d.get('pubkey-path')
    return None, None


def _rekey_candidates(ctx, output, pm, owned, *, finder=None):
    '''For a SIGNATURE-class index failure, the configsys-managed culprits we could re-key:
    [(source-file, component, key-url, key-path)]. Foreign sources and ones with no route key are
    excluded (never touched). Pure — the caller owns the prompt + fetch. `owned` = {file: component}.'''
    from .. import failures
    finder = finder or _find_source_files          # resolved at call time (test-injectable)
    if failures.classify(output)[0] != failures.SIGNATURE:
        return []
    urls = sorted({re.sub(r'[)\'">,]+$', '', u) for u in re.findall(r'https?://[^\s\'">]+', output)})
    out = []
    for f in sorted(finder(urls, _INDEX_SRC_DIRS.get(pm, ())) if urls else {}):
        comp = owned.get(f)
        if not comp:
            continue                                         # foreign -> never touch (plan default Q4)
        ku, kp = _source_key_fields(ctx, comp, f)
        if ku and kp:
            out.append((f, comp, ku, kp))
    return out


def _offer_rekey(ctx, pm, output, owned, native_cmd, *, ask=None):
    '''Rotation self-heal (plan Theme 2): on a SIGNATURE failure for a configsys-managed source with
    a route key url, PROMPT (plan default Q1) to re-fetch the key (overwriting the stale one) and
    retry the index refresh. Returns True iff a retry then succeeded. `ask(prompt)->bool` is
    injectable for tests; defaults to a y/N terminal prompt.'''
    import shlex
    if ask is None:
        def ask(prompt):
            try:
                return input(prompt).strip().lower() == 'y'
            except EOFError:
                return False
    for src, comp, key_url, key_path in _rekey_candidates(ctx, output, pm, owned):
        if not ask(f'\nRe-fetch the signing key for `{comp}` (rotated?) into {key_path} and retry? [y/N] '):
            continue
        ctx.runner.run(f'sudo curl -fsSL {shlex.quote(key_url)} -o {shlex.quote(key_path)}', capture=True)
        retry = ctx.runner.run(native_cmd, sudo=(pm != 'brew'), capture=True)
        if retry.ok:
            print(f'  re-keyed `{comp}` — the index refresh is clean now.')
            return True
        print(f'  still failing for `{comp}` after re-keying — the route key itself may be stale.')
    return False


def _orphaned_managed_sources(ctx, wanted, disk_files):
    '''[(source-file, component)] for configsys-managed sources on disk whose OWNING component is not
    in `wanted` (the resolved/active set) — a source left behind by a component you removed from your
    config (its stale .list/.repo still breaks the package manager). Pure. Foreign files (not in any
    route's source-path) are never included.'''
    owned = _owned_index_sources(ctx)                    # {path: component}, all routes
    return sorted((f, owned[f]) for f in disk_files if f in owned and owned[f] not in wanted)


def _installed_owners(ctx):
    '''Components a managed source may still serve though they aren't picked: everything configsys
    holds an install receipt for, and each source owner whose package reads installed here — `install
    X` never adds a pick, and pre-matrix installs aren't picked (A14 / app-cli-03).'''
    out = set()
    try:
        for key, rec in Ledger.load(ctx.paths).records.items():
            if rec.get('receipt'):
                out.add(key.split('\\', 1)[-1])
    except Exception:                                    # noqa: BLE001
        pass
    for comp in set(_owned_index_sources(ctx).values()) - out:
        try:
            units, _e = ctx.routes.resolve_resilient([comp])
            for rc in units.values():
                drv = get_driver(rc.driver, ctx.runner, ctx.paths)
                if rc.comp == comp and drv is not None and drv.get_version(rc):
                    out.add(comp)
                    break
        except Exception:                                # noqa: BLE001 — unknown: treat as in use
            out.add(comp)
    return out


def _reconcile_managed_sources(ctx, pm, wanted, *, ask=None, lister=None):
    '''Phase 3 reconciliation (advisory, component-scoped): offer (prompt, plan Q1) to remove
    configsys-managed apt/dnf sources whose owning component is no longer in the active config — the
    stale-source cleanup that closes the loop on "I removed the component but its broken source keeps
    breaking apt". Returns the number removed. Never touches a foreign source (plan Q4). `ask`/
    `lister` are injectable for tests.'''
    dirs = _INDEX_SRC_DIRS.get(pm, ())
    if not dirs:
        return 0
    lister = lister or (lambda: _list_source_files(dirs))
    orphans = _orphaned_managed_sources(ctx, wanted, lister())
    if not orphans:
        return 0
    if ask is None:
        def ask(prompt):
            try:
                return input(prompt).strip().lower() == 'y'
            except EOFError:
                return False
    import shlex
    removed = 0
    print('\n── stale managed package sources (their component is neither picked nor installed here) ──')
    home = getattr(getattr(ctx, 'paths', None), 'home', None)
    if home is not None and Path(home) != Path.home():
        print('  (these are the REAL system source dirs, whatever --home says)')
    if getattr(ctx.runner, 'pretend', False):                               # a dry run asks nothing it can't act on
        for f, comp in orphans:
            print(f'  [pretend] would offer to remove {f} (written for `{comp}`)')
        return 0
    for f, comp in orphans:
        if ask(f'  remove {f} — configsys wrote it for `{comp}`, which is neither picked nor installed '
               f'here? [y/N] '):
            ctx.runner.run(f'sudo rm -f {shlex.quote(f)}', capture=True)
            removed += 1
    return removed


# How each native manager refreshes its package index — every native manager is in exactly one map
# (test_driver_inventory). _NATIVE_REFRESH: an index-only refresh, safe before a single-package
# install, so it also runs automatically ahead of an execute batch. _FULL_UPGRADE_REFRESH: managers
# where an index-only sync is NOT safe — Arch's rolling model forbids partial upgrades, so a bare
# `pacman -Sy` leaves the DB newer than the system and the next `pacman -S` breaks it; the only safe
# refresh is the full system upgrade, which `configsys refresh` asks before running and nothing
# runs automatically. (Rolling alone doesn't decide it: Void and Tumbleweed sync safely.)
_NATIVE_REFRESH = {'apt': 'apt-get update', 'dnf': 'dnf -q makecache',
                   'zypper': 'zypper --non-interactive refresh', 'apk': 'apk update', 'xbps': 'xbps-install -S',
                   'brew': 'brew update'}


_FULL_UPGRADE_REFRESH = {'pacman': 'pacman -Syu --noconfirm'}


def refresh_native_index(ctx):
    '''Refresh the OS package index ONCE, resiliently (retry a transient stumble) and NON-fatally —
    a failure is reported by the caller, never blocks the batch. Returns (ran, ok): ran=False when
    there's nothing safe to do automatically (a _FULL_UPGRADE_REFRESH manager, or an unknown pm).
    Used before an execute batch so upgrades see current candidates and a broken vendor source is
    caught up front, not per-package.'''
    pm = ctx.routes.cascade.native(ctx.os_info.block)
    cmd = _NATIVE_REFRESH.get(pm)
    if not cmd:
        return False, True
    return True, _run_native_refresh(ctx, pm, cmd).ok


def _run_native_refresh(ctx, pm, cmd):
    '''Run the native index refresh `cmd` once, the ONE way (B17 / app-cli-06): sudo except for brew,
    Homebrew's own env (its prefix off PATH — drivers.brew.brew_env), a transient stumble retried,
    output captured for the failure diagnosis. -> the Result.'''
    from ..failures import retry_transient
    from ..drivers.brew import brew_env
    env = brew_env() if pm == 'brew' else None
    return retry_transient(lambda: ctx.runner.run(cmd, sudo=(pm != 'brew'), capture=True, env=env))


def _uses_native_index(rc, pm):
    '''True when installing/upgrading `rc` reads THIS OS's package index: a unit of the OS's own
    manager (brew elsewhere on glibc is its own user-space prefix — `brew install` updates itself),
    or a native-backed driver whose installs go through that manager (native-pkg-file's .deb/.rpm
    dependencies, clang/gcc from an added repo).'''
    if rc.driver == pm:
        return True
    drv = get_driver(rc.driver, None)
    return bool(getattr(drv, 'native_backed', False))


def maybe_refresh_before_plan(ctx, plan, *, system=False):
    '''Per the `refresh-before-execute` setting, refresh the OS package index ONCE before running
    `plan` — so upgrades see current candidates and a broken vendor source is caught up front instead
    of failing per-package. 'auto' (default) refreshes only when the plan installs/upgrades something
    that reads this OS's index (_uses_native_index); 'always'/'never' force it. `system` = the batch
    also runs a System Updates bulk upgrade, which always reads the index (refreshed whatever the
    setting). A manager with no index-only refresh (_FULL_UPGRADE_REFRESH) is never refreshed here;
    'always' says so. Non-fatal: a failed refresh proceeds on the cached index.

    ONE refresh per batch: a TUI batch running System Updates and then component ops refreshes here,
    up front, never again between the two — a second refresh after a long bulk upgrade picks up
    packages published meanwhile, which then read "newly outdated" after a run that never offered
    them. Returns the package names this refresh made upgradable that weren't before (staged against
    the older index — `published_pending` reports the ones the batch didn't cover); empty when it
    didn't refresh or can't tell.'''
    cfg = getattr(ctx, 'config', None)
    mode = cfg.refresh_before_execute() if hasattr(cfg, 'refresh_before_execute') else 'auto'
    if mode == 'never' and not system:
        return set()
    if getattr(ctx, 'routes', None) is None or getattr(ctx, 'os_info', None) is None:
        return set()                         # not enough context to refresh (e.g. a bare test stub)
    pm = ctx.routes.cascade.native(ctx.os_info.block)
    if mode == 'auto' and not system and not any(
            op in ('install', 'upgrade') and _uses_native_index(rc, pm) for op, _k, rc in plan):
        return set()
    if pm not in _NATIVE_REFRESH:
        if mode == 'always' and pm in _FULL_UPGRADE_REFRESH:
            print(f'\nNot refreshing the {pm} index before the batch: its only safe refresh is a full '
                  'upgrade (run `configsys refresh` for that).', flush=True)
        return set()
    before = _upgradable_names(ctx, pm)
    print('\nRefreshing the package index before the batch…', flush=True)
    ran, ok = refresh_native_index(ctx)
    if ran:
        print('  ✓ index refreshed' if ok else
              '  ⚠ index refresh hit a problem — proceeding on the cached index '
              '(run `configsys refresh` to diagnose)')
    after = _upgradable_names(ctx, pm) if ran and ok else None
    return (after - before) if before is not None and after is not None else set()


def _upgradable_names(ctx, pm):
    '''The native manager's upgradable package names from its CACHED index (Driver.upgradable_index —
    no network), or None when it can't say.'''
    drv = get_driver(pm, ctx.runner, getattr(ctx, "paths", None)) if pm else None
    try:
        idx = drv.upgradable_index() if drv is not None else None
    except Exception:                        # noqa: BLE001 — an advisory read, never fatal
        idx = None
    return set(idx) if isinstance(idx, dict) else None


def published_pending(ctx, fresh):
    '''Of `fresh` (maybe_refresh_before_plan's newly-upgradable names), the ones STILL upgradable
    after the batch — updates published after you staged, which the run didn't include. Sorted.'''
    if not fresh:
        return []
    pm = ctx.routes.cascade.native(ctx.os_info.block)
    now = _upgradable_names(ctx, pm)
    return sorted(fresh & now) if now is not None else []


def cmd_refresh(ctx, args):
    from ..routes import clear_facet_cache
    from ..versions import discover, source_key
    clear_facet_cache()                                # facets are probed afresh too (a new GPU / CUDA)
    ctx.invalidate()
    print('configsys refresh — re-querying version sources and the package index '
          '(this can take a moment; sudo may prompt)…', flush=True)
    _cfg, _req, units, _ledger, _states = ctx.load_pipeline()
    print('\nRefreshing discovered versions...')
    seen = {}
    for key in sorted(units):
        rc = units[key]
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        # use the driver's arch-substituted spec so the cache key matches what the driver looks up
        # at install time. GitHub versions come from the anonymous atom feed (no API rate limit);
        # asset urls warm lazily at install (one component -> a couple of API calls, never the limit).
        spec = drv.version_spec(rc)
        if not isinstance(spec, dict) or 'static' in spec:
            continue
        sk = source_key(spec)
        if sk in seen:
            continue
        seen[sk] = discover(spec, ctx.paths, refresh=True, offline=ctx.runner.pretend)   # A14: a dry run asks nothing
        print(f'  {sk:44} -> {seen[sk] or "(unknown)"}')
    if not seen:
        print('  (no discoverable versions among your tracked components)')
    elif any(v is None for v in seen.values()):
        print('\nSome version lookups failed (offline or a transient network error). '
              'Kept the last cached value for those; try `configsys refresh` again later.')

    # MANUAL (`static:`) version pins are skipped by the discovery loop above (no upstream query).
    # A component may add a `latest-check:` version-source naming where the CURRENT upstream version
    # lives (a github repo, or a `url:`+`regex:` page scrape); we fetch it and compare — ADVISORY
    # only, the pin stays authoritative and nothing auto-bumps, so you just learn WHEN to bump a pin
    # by hand. `check` re-surfaces this (from the stamp) without hitting the network. Deduped per comp.
    from .. import refreshstate
    from ..versions import discover as _discover_latest
    from ..osversion import parse_version as _pv
    stale, seen_lc = {}, set()
    for key in sorted(units):
        rc = units[key]
        lc = rc.fields.get('latest-check')
        if not isinstance(lc, dict) or rc.comp in seen_lc:
            continue
        seen_lc.add(rc.comp)
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        pinned = drv.resolve_version(rc) if drv is not None else None
        upstream = _discover_latest(lc, ctx.paths, refresh=True, offline=ctx.runner.pretend)
        pu, pp = _pv(upstream), _pv(pinned)
        if pu is not None and pp is not None and pu > pp:
            stale[rc.comp] = [str(pinned), str(upstream)]
    if stale:
        print('\nManual version pins behind upstream (bump the pin in routes.hu / the plugin):')
        for comp in sorted(stale):
            print(f'  {comp}: pinned {stale[comp][0]}  ->  {stale[comp][1]} available')
    if not ctx.runner.pretend:                    # a dry run checked nothing: keep the last stamp
        refreshstate.record_stale_pins(ctx.paths, stale)

    # refresh the native package index too — the SOURCE for `via: native` components, so their
    # get_latest / installs reflect the current candidates (apt in particular NEVER auto-updates
    # for a plain install). sudo runs as a subprocess (prompts in this terminal), not the whole app.
    pm = ctx.routes.cascade.native(ctx.os_info.block)
    native = _NATIVE_REFRESH.get(pm)
    ok = True
    if native:
        print(f'\nRefreshing the {pm} package index...')
        # capture (fast command) so a broken third-party source can be diagnosed instead of dumping
        # a raw NO_PUBKEY/not-signed error. Echo the output so the user still sees what ran. Retry a
        # TRANSIENT stumble (a network blip, or a concurrent apt run's "could not read sources") a few
        # times first — so a momentary hiccup self-heals instead of surfacing the whole failure flow.
        res = _run_native_refresh(ctx, pm, native)
        ok = res.ok
        if res.output:
            print(res.output)
        if not ok:
            owned = _owned_index_sources(ctx)
            diag = diagnose_index_failure(res.output, pm, owned)
            if diag:
                print('\n── the package index refresh failed ──')
                for line in diag:
                    print(f'  {line}')
                # P2: rotation self-heal — offer (prompt) to re-fetch a rotated key for a
                # configsys-managed source and retry. Foreign sources are never touched.
                if _offer_rekey(ctx, pm, res.output, owned, native):
                    ok = True
        # P3 reconciliation: offer to remove stale managed sources whose owning component is no
        # longer in your config. If an orphan like that was WHY the refresh failed, cleaning it up
        # fixes it — so re-run the index once after a removal.
        wanted = {units[k].comp for k in units} | _installed_owners(ctx)
        if _reconcile_managed_sources(ctx, pm, wanted) and not ok:
            print(f'\nRe-running the {pm} index refresh after cleanup...')
            res = _run_native_refresh(ctx, pm, native)
            ok = res.ok
            if res.output and not ok:
                print(res.output)
    elif pm in _FULL_UPGRADE_REFRESH:
        # No safe index-only refresh here (see _FULL_UPGRADE_REFRESH): on Arch a bare `pacman -Sy`
        # makes the next single-package install (`pacman -S`, exactly how this driver installs) a
        # partial upgrade -> breakage. Confirm first, then run the full upgrade to completion
        # (--noconfirm) so we never leave that partial-sync state.
        full = _FULL_UPGRADE_REFRESH[pm]
        print(f'\nOn {pm} a safe refresh is a FULL SYSTEM UPGRADE (`{full}`) — an index-only sync\n'
              'leaves a partial-sync state that breaks the next install, so configsys never does one.')
        try:
            go = input(f'Run `{full}` now (upgrades ALL installed packages)? [y/N] ').strip().lower() == 'y'
        except EOFError:
            go = False
        if go:
            ok = ctx.runner.run(full, sudo=True, capture=False).ok
        else:
            print(f'Skipped — {pm} DB left unchanged.')
            ok = False                                 # nothing refreshed -> don't stamp
    if ok and not ctx.runner.pretend:
        refreshstate.record(ctx.paths)                # stamp only a successful index refresh
    if getattr(ctx, 'config', None) is not None and ctx.config.reboot_advice():
        print_reboot_advisory(ctx)                    # a refresh can reveal a pending reboot too
    return 0
