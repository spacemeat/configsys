'''cli/check.py — `configsys check` — the whole-config lint (`check_report` is shared with the TUI `!` page).

Split out of app.py (review-2026-11-2 D2).
'''

import os
import sys
from ..errors import ConfigsysError
from ..resolve import CONFIG_ERROR_KINDS, SPECIAL_VIAS
from ..drivers import get_driver
from .plugin import _fmt_conflict
from .where import _layer_label


def _issue_loc(issue, paths):
    if issue.component is None:
        return ''
    src = f' [{_layer_label(issue.source, paths)}]' if issue.source else ''
    return f"component '{issue.component}'{src}: "


def cmd_check(ctx, args):
    '''Lint the whole merged config (repo + plugins + primary + your top config, with includes)
    without installing.'''
    try:
        rows, n_components = check_report(ctx)
    except ConfigsysError as e:
        print(f'configsys: {e}')          # a parse/structural error before we can lint
        return 1
    if not rows:
        print(f'configsys: OK — {n_components} components, no issues')
        return 0
    for level, text in rows:
        print(f'  {"ERROR" if level == "error" else "warn "}   {text}')
    n_err = sum(1 for lv, _t in rows if lv == 'error')
    print(f'\nconfigsys: {n_err} error(s), {len(rows) - n_err} warning(s) '
          f'across {n_components} components')
    return 1 if n_err else 0


def _validated_routes(ctx):
    '''The Context's Resolver when its validated load is the same catalog check's tolerant load would
    build — it raised nothing and warned nothing, so no layer, component or facet was skipped and
    every component passed routecheck.check_component. None = take the tolerant path (app-cli-19).'''
    try:
        r = ctx.routes
    except ConfigsysError:
        return None                        # e.g. an ambiguity in your config: the tolerant load reports it
    return None if getattr(r, 'load_warnings', None) else r


def check_report(ctx):
    '''Every `check` finding as data -> ([(level, text)], n_components): errors first, then warnings,
    in the order `check` prints them. Shared by `configsys check` and the TUI `!` page, which runs
    it on a background thread (review-2026-11-2 G2). Raises ConfigsysError on a structural failure.'''
    from .. import layers, routes, routecheck
    ctx.ensure_plugin_code()          # register trusted plugin drivers so `via:` validates
    _route_w = []
    # the catalog: the Resolver's when it loaded cleanly (its load already route-checked each
    # component — don't load and check ~870 again), else a tolerant load that keeps what a validated
    # one would refuse, so an ambiguity is reported here as an issue instead of stopping check
    validated = _validated_routes(ctx)
    try:
        home = getattr(ctx.paths, 'home', None)
        if validated is not None:
            cascade, components, drivers = validated.cascade, validated.components, validated.drivers
        else:
            cascade, components, drivers, _never_auto_drivers = routes.load(
                ctx.paths.routes_file, ctx.paths.user_config_file,
                ctx.plugin_files, validate=False, warnings_out=_route_w, home=home)
        # the whole stack again, config.hu included (routes.load's has no config.hu); the files
        # routes.load read come from layers' parse cache, so this re-parses nothing
        roots = ([(ctx.paths.routes_file, 'repo'), (ctx.paths.config_file, 'repo')]
                 + list(ctx.plugin_files)                 # (path, role): 'primary' or 'plugin'
                 + [(ctx.paths.user_config_file, 'user')])
        layer_list, _layer_w = layers.expand_tolerant(roots, {'plugin', 'primary'}, home=home)
    except ConfigsysError:
        raise                              # a parse/structural error before we can lint

    issues = routecheck.validate(components, cascade, drivers,
                                 pending_vias=ctx.plugin_pending_vias,
                                 components_checked=validated is not None)
    include_warnings = (layers.ignored_section_warnings(layer_list)
                        + layers.unknown_section_warnings(layer_list)
                        + layers.setting_value_warnings(layer_list)
                        + layers.duplicate_key_warnings(layer_list))

    # the theme model is `colors:` (a shared map) + `pages.<page>.<role>`; a leftover
    # palette/elements block or a top-level gradient is ignored, so flag it rather than let a stale
    # theme silently do nothing.
    theme_warnings = []
    from ..tui.theme import theme_problems
    for lyr in layer_list:
        t = lyr.data.get('theme')
        for key, why in theme_problems(t):
            theme_warnings.append(f'{os.path.basename(lyr.path)}: theme {key}: {why} — ignored')
        if isinstance(t, dict):
            stale = [k for k in ('palette', 'elements', 'gradient') if k in t]
            if stale:
                theme_warnings.append(
                    f'{os.path.basename(lyr.path)}: theme uses the old {"/".join(stale)} schema '
                    f'(now colors: + pages.<page>.<role>) — ignored; see docs/theming.md')

    # profile references: a profile naming a component that doesn't exist, plus structural errors
    # from expansion (undefined `+include`, include cycle). Profiles are read-only BROWSE lenses, so
    # every one is linted: a lens naming a component that isn't defined is an authoring error.
    prof_issues = []
    prof_errors = []
    for prof in ctx.config.profile_names():
        try:
            for cname in ctx.config.profile_components(prof):
                if cname not in components:
                    prof_issues.append((prof, cname))
        except ConfigsysError as e:
            prof_errors.append(str(e))

    # a `~ref` that matches neither a defined profile nor a known component removes nothing — almost
    # always a typo (e.g. `~haskel-lang`). Warn, don't error: it's a no-op, not a hard failure.
    removal_warnings = []
    _prof_names = set(ctx.config.profile_names())
    for prof in ctx.config.profile_names():
        reach = None
        for ref in ctx.config.profile_removal_terms(prof):
            if ref in _prof_names:                       # a ~subprofile: warn if it isn't even included
                if reach is None:
                    reach = ctx.config.reachable_subprofiles(prof)
                if ref not in reach:
                    removal_warnings.append(f"profile '{prof}': `~{ref}` removes nothing "
                                            f"({prof} doesn't include the {ref} subprofile)")
            elif ref not in components:                  # neither profile nor component -> likely a typo
                removal_warnings.append(f"profile '{prof}': `~{ref}` removes nothing "
                                        f"(not a defined profile or known component)")

    # a `machine:` selection that names no column of the picks matrix installs nothing — almost
    # always a typo or an unsynced primary. Warn so it isn't a silent no-op.
    _sel_machine = ctx.config.selected_machine()
    if _sel_machine and _sel_machine not in ctx.config.machine_names():
        removal_warnings.append(f"machine '{_sel_machine}' is selected but has no column in `picks:` "
                                f"— this box's install set is empty (`configsys machine add` creates it)")

    # the `!` namespace is reserved for system workflow lenses (the synthetic !uninstall / !all
    # browse lenses). A hand-defined `!…` profile collides — warn (the UI blocks creating one).
    removal_warnings += [f"profile '{p}': the `!` namespace is reserved for system lenses (rename it)"
                         for p in ctx.config.profile_names() if p.startswith('!')]
    # a component staged for uninstall while still tracked/picked on this machine is a contradiction
    # (the next sync reinstalls it) — surface it, don't auto-fix.
    uninstall_conflicts = []
    _queue = ctx.config.uninstall_queue()
    if _queue:
        for c in sorted(_queue & set(ctx.config.requested())):
            uninstall_conflicts.append(f"'{c}' is staged for uninstall but still tracked/picked on "
                                       f"this machine — untrack it or unstage the uninstall")

    # pins: value must be a known driver (binding-pin) or a known component (provider-pin)
    from ..drivers import supported_names
    valid_via = SPECIAL_VIAS | supported_names()
    pin_issues = []
    for key, val in ctx.config.pins().items():
        if val in valid_via:
            if key not in components:
                pin_issues.append(f"pin '{key}: {val}': component '{key}' does not exist")
        elif val not in components:
            pin_issues.append(f"pin '{key}: {val}': '{val}' is neither a known driver "
                              f'(binding-pin) nor a component (provider-pin)')

    # provider-pin vs version constraint: a pin whose provided version fails a constraint some
    # component requires on that cap can never resolve for that consumer — flag it here rather than
    # let it surface only at install/inspect time. (helper is unit-tested in routecheck.)
    pin_conflict_warnings = routecheck.pin_constraint_conflicts(ctx.config.pins(), components, valid_via)

    # python floor: configsys runs on the system python3 (the .venv inherits its version) and needs
    # >= 3.10 (configsys.sh). Warn when it's AT that minimum, so you upgrade before a dependency — or
    # configsys itself — needs newer. (The system python is what the bootstrap requires; installing a
    # python3.X component doesn't change the interpreter configsys runs on.)
    py_floor_warnings = []
    _py = sys.version_info[:2]
    if _py <= (3, 10):
        py_floor_warnings.append(
            f"Python {_py[0]}.{_py[1]} is configsys's minimum (3.10) — upgrade the system python "
            f"before it ages out (a python3.X component installs a NEWER interpreter alongside, but "
            f"doesn't replace the one configsys runs on).")

    # D8: a derivative release the registry doesn't know gets no base, so gates written against its
    # base line (`ubuntu >= 24.04`) don't reach it — say which release to register (/update-os)
    try:
        _cas, _blk, _ver = ctx.routes.cascade, ctx.routes.block, ctx.routes.version
        _sroot = next((n for n in _cas.lineage(_blk) if n in _cas.scale_roots), None)
        if _sroot in _cas.release_bases and _ver and not _cas.bases_of(_blk, _ver):
            py_floor_warnings.append(
                f'{_sroot} {_ver} is not in the release registry — gates written for its base '
                f'(e.g. `ubuntu >= 24.04`) do not reach it until it is (routes.hu `releases:`, /update-os)')
    except Exception:                                  # noqa: BLE001 — an advisory never breaks check
        pass

    from .. import plugins as _plugins
    _top = _plugins.declared(ctx.paths.user_config_file)
    _decls = _plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    # exactly one plugin may be `primary` (only the top config grants it)
    _primaries = [_plugins.dir_name(d['source']) for d in _top if d.get('primary')]
    if len(_primaries) > 1:
        prof_errors.append(f'multiple primary plugins declared: {", ".join(_primaries)} '
                           f'(only one may be primary)')
    conflict_warnings = [_fmt_conflict(*c) for c in
                         _plugins.declared_conflicts(ctx.paths.plugins_dir, _decls)]
    conflict_warnings += [f'plugin {_src}: `primary: {_val}` is not a yes/no value — read as not '
                          f'primary (use true or false)'
                          for _src, _val in _plugins.bad_primary_values(ctx.paths.user_config_file)]
    conflict_warnings += ctx.plugin_code_conflicts    # code-only (version-source/transport)
    conflict_warnings += [_plugins.fmt_shadow(*s) for s in
                          _plugins.shadowed_builtins(ctx.paths.plugins_dir, _decls)]
    conflict_warnings += [f"plugin {_plugins.dir_name(d['source'])}: `{e}` points outside the "
                          f"plugin's checkout — not loaded (it isn't covered by trust)"
                          for d in _decls
                          for e in _plugins.uncontained_entries(
                              ctx.paths.plugins_dir / _plugins.dir_name(d['source']),
                              _plugins.read_manifest(ctx.paths.plugins_dir / _plugins.dir_name(d['source'])))
                          if (ctx.paths.plugins_dir / _plugins.dir_name(d['source'])).is_dir()]
    conflict_warnings += [f"plugin {_plugins.dir_name(d['source'])}: content does not match "
                          f"declared sha256 — quarantined"
                          for d in _decls
                          if d.get('sha256') and not _plugins.checksum_ok(ctx.paths.plugins_dir, d)]

    # TUI keybindings: an unknown action/scope (typo), an unparseable key name, or a self-conflict
    # (one key on two actions in a scope) in any layer's `keys:` section.
    from ..tui.keyspec import lint_keys
    _ignored = {os.path.normpath(x.path) for x in ctx.config.untrusted_key_layers()}
    key_warnings = lint_keys([x for x in layer_list if os.path.normpath(x.path) not in _ignored])
    key_warnings += [f'{os.path.basename(p)}: `keys:` ignored until its plugin is trusted '
                     f'(configsys plugin trust)' for p in sorted(_ignored)]

    # manual version pins the LAST `refresh` found behind upstream (from a `latest-check:` source).
    # Read-only from the stamp — never hits the network here; empty until you run `configsys refresh`.
    from .. import refreshstate
    stale_pin_warnings = [f'{c}: version pin {p[0]} is behind upstream {p[1]} — bump it '
                          f'(routes.hu / the plugin)'
                          for c, p in sorted(refreshstate.read_stale_pins(ctx.paths).items())
                          if isinstance(p, (list, tuple)) and len(p) == 2]

    # pre-band conf.d links of ours (from before the load-order bands): no longer migrated (§7.16) —
    # the banded link loads the same snippet, so the old one double-loads it until you delete it
    try:
        for _lk, _tg in get_driver('glue', ctx.runner, ctx.paths).legacy_links():
            removal_warnings.append(f'{_lk}: a pre-band glue link (from an older configsys) — the '
                                    f'banded 50-/90- link loads it now; delete this one')
    except Exception:                                    # noqa: BLE001 — a lint never breaks check
        pass

    # glue-override drift (docs/done/glue-customization-plan.md P2): a user override whose SHIPPED source
    # has since changed. Advisory — the override stays authoritative. Re-running `glue override`
    # never overwrites an existing fork (Glue.override): it only records the new shipped hash, so
    # it is the "I've reviewed it" acknowledgement, not a refresh.
    glue_drift_warnings = []
    try:
        gdrv = get_driver('glue', ctx.runner, ctx.paths)
        _ov_comps = set()
        for _root in gdrv.user_glue_roots():
            _ov_comps.update(k.split('|', 1)[0] for k in gdrv.load_overrides(_root))
        for _comp in sorted(_ov_comps):
            _units, _e = ctx.routes.resolve_resilient([_comp])
            _rc = next((r for r in _units.values() if r.driver == 'glue' and r.comp == _comp), None)
            if _rc is None:
                continue
            for _shell, _old, _new in gdrv.override_drift(_rc):
                glue_drift_warnings.append(
                    f"glue override for '{_comp}' ({_shell}) was forked from an older shipped "
                    f'version — merge what you want from the new one into your copy, then '
                    f'`configsys glue override {_comp}` marks it current (it never overwrites yours)')
    except Exception:                                    # noqa: BLE001 — drift lint must never break check
        pass

    # RESOLVE this machine's picks (no disk probe) so `check` surfaces resolve-TIME CONFIG
    # inconsistencies the static lint sees only as latent — a pin that can't satisfy a versioned
    # `requires:` for a PICKED consumer (e.g. a `cuda-toolkit` pin blocking `cudnn-9`), or an ambiguity needing a pin.
    # This is the class the TUI `!` page / `inspect` flag as errors but that `check` used to downgrade
    # to a warning (or miss). We KEEP only pin/ambiguity errors (things the config author controls),
    # NOT pure OS-availability ("no binding for X in this context") — a config that lists a component
    # unavailable on THIS OS is still a clean config. Unknown-component members are already reported
    # by prof_issues, so they're excluded too.
    # every column of the picks matrix, and the dispositions / uninstall side-stores, against the
    # merged catalog (B11): an unknown pick on THIS machine is an error (it installs nothing); on
    # another machine a warning (that box may load a plugin defining it)
    pick_errors, pick_warnings = [], []
    _this = ctx.config.current_machine()
    for _m, _names in sorted(ctx.config.picks().items()):
        for _n in _names:
            if _n not in components:
                if _m == _this:
                    pick_errors.append(f"picks: '{_n}' (this machine, {_m}) is not a known component")
                else:
                    pick_warnings.append(f"picks: '{_n}' (machine {_m}) is not a component here "
                                         f'(fine if that machine loads a plugin defining it)')
    for _store, _names in (('dispositions', ctx.config.dispositions()),
                           ('uninstall', ctx.config.uninstall_queue())):
        _stale = sorted(n for n in _names if n not in components)   # harmless bookkeeping: one line
        if _stale:
            _shown = ', '.join(_stale[:6]) + (f', … (+{len(_stale) - 6})' if len(_stale) > 6 else '')
            pick_warnings.append(f'{_store}: {len(_stale)} name(s) not in the catalog here: {_shown}')

    resolve_errors = []
    _known_bad = {c for _p, c in prof_issues} | {
        n for n in ctx.config.picks().get(_this, []) if n not in components}
    try:
        # the errors that are the config's to fix (a pin, a preference, a rank), by the kind the
        # resolver raised — not by message text, which a cap or gate reason can echo (routing-28)
        _out = {}
        _u, _rerrs = ctx.routes.resolve_resilient(list(ctx.config.requested()), out=_out)
        _kinds = _out.get('error_kinds') or {}
        resolve_errors = [f'{n}: {_rerrs[n]}' for n in sorted(_rerrs)
                          if n not in _known_bad and _kinds.get(n) in CONFIG_ERROR_KINDS]
    except ConfigsysError:
        pass                                        # a structural failure already surfaced above

    # a layer (your primary, a plugin) or component the loaders had to SKIP — unreadable, malformed —
    # is an error here exactly as on the `!` page (B11): its picks and settings are silently gone
    skipped_errors = []
    for w in _layer_w + _route_w:
        msg = w[len('skipped '):] if w.startswith('skipped ') else w
        if msg not in skipped_errors:
            skipped_errors.append(msg)

    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if not i.is_error]
    code_warnings = ctx.plugin_code_warnings
    rows = ([('error', f'skipped {m}') for m in skipped_errors]
            + [('error', f'{_issue_loc(i, ctx.paths)}{i.message}') for i in errors]
            + [('error', m) for m in pick_errors + prof_errors]
            + [('error', f"profile '{prof}': unknown component '{cname}'") for prof, cname in prof_issues]
            + [('error', m) for m in pin_issues + resolve_errors]
            + [('warn', f'{_issue_loc(i, ctx.paths)}{i.message}') for i in warnings]
            + [('warn', m) for m in (include_warnings + code_warnings + conflict_warnings
                                     + theme_warnings + pin_conflict_warnings + py_floor_warnings
                                     + stale_pin_warnings + key_warnings + removal_warnings
                                     + uninstall_conflicts + glue_drift_warnings + pick_warnings)])
    return rows, len(components)
