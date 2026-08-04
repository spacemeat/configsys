'''actions.py — the shared action layer.

Reusable read+write operations that BOTH the CLI subcommands and the TUI screens call, so the two
stay in lockstep (the TUI is a skin over these, never a parallel implementation). Each takes the app
`Context`, edits config surgically via the `plugins.set_*` writers, and `ctx.invalidate()`s the
cached config so the change takes effect on the next read. See docs/tui-screens-plan.md (F3).
'''

from pathlib import Path

from . import plugins


def edit_target(ctx):
    '''(file, label) for a PORTABLE edit: the primary plugin's data file when a primary is blessed +
    synced (so edits travel to your other machines), else this machine's top config. NOTE: the
    primary layer sits BELOW the top config, so an edit here is only effective when a higher layer
    doesn't shadow it — profile/config edits use the effective-target helpers below instead.'''
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    if prim:
        files = [f for f, role in plugins.layer_files(ctx.paths.plugins_dir, decls)
                 if role == 'primary']
        if files:
            return files[0], prim
    return str(ctx.paths.user_config_file), 'top config'


def _dir_label(ctx, f):
    return 'top config' if str(f) == str(ctx.paths.user_config_file) else Path(f).parent.name


def _profile_target(ctx, profile):
    '''Where a membership edit is EFFECTIVE: the profile's highest-precedence definition layer if
    it's already defined (editing a lower layer would be shadowed by that definition), else the
    portable default (primary-if-set) for a brand-new profile.'''
    src = ctx.config.profile_source(profile)
    if src is not None:
        return str(src), _dir_label(ctx, src)
    return edit_target(ctx)


def _configs_target(ctx):
    '''Where a `configs:` edit is EFFECTIVE: the top config if it already has a `configs:` (it
    shadows lower layers whole-list), else the portable default.'''
    if plugins.read_configs(ctx.paths.user_config_file):
        return str(ctx.paths.user_config_file), 'top config'
    return edit_target(ctx)


def set_profile_membership(ctx, profile, comp, action, *, target=None):
    '''Add or remove `comp` in `profile` (`action` = 'add'|'remove'), writing the term-algebra edit
    (via Config.plan_membership_edit) to `target` or the effective target. Returns (changed, label);
    a no-op returns (False, label); a shadowed target that took no effect returns (False, warning).'''
    tfile, label = (target, target) if target else _profile_target(ctx, profile)
    new_terms = ctx.config.plan_membership_edit(profile, comp, action, tfile)
    if new_terms is None:
        return False, label
    profs = plugins.read_profiles(tfile)
    profs[profile] = new_terms
    plugins.set_profiles(tfile, profs)
    ctx.invalidate()
    if (comp in ctx.config._members_safe(profile)) != (action == 'add'):   # shadowed -> no effect
        return False, f'{label}: "{profile}" is overridden by a higher-precedence layer (no effect)'
    return True, label


def set_profile_active(ctx, profile, on, *, target=None):
    '''Activate (`on=True`) or deactivate `profile` in the active `configs:` set. Returns
    (changed, target_label).'''
    tfile, label = (target, target) if target else _configs_target(ctx)
    names = plugins.read_configs(tfile)
    present = profile in names
    if on and not present:
        names = names + [profile]
    elif not on and present:
        names = [n for n in names if n != profile]
    else:
        return False, label
    plugins.set_configs(tfile, names)
    ctx.invalidate()
    return True, label


# -- machine settings (`configsys config` + the TUI Config screen) --------------------------------
# key -> (kind, one-line descriptor, man page). The single source of truth the CLI and the TUI
# Config screen both read, so both describe each setting identically (docs/tui-screens-plan.md C1).
CONFIG_SETTINGS = {
    'scope':             ('scalar', 'Default install scope: user (~, the default when unset) or '
                                    'system (/opt, needs sudo).', 'configsys(1)'),
    'driver-preference': ('list',   'Order ties between equally-valid install methods break in.',
                          'configsys(1)'),
    'auto-tighten':      ('bool',   'Auto-pick a floor-satisfying install method instead of only '
                                    'advising.', 'configsys(1)'),
    'ignore-profiles':   ('list',   'Discovered project profiles to NOT auto-activate.',
                          'configsys(1)'),
}


def config_settings(ctx):
    '''{key: {kind, value, desc, man}} — the effective machine settings for display (CLI
    `config show` and the TUI Config screen). Read-only.'''
    cfg = ctx.config
    values = {
        'scope':             cfg.default_scope(),
        'driver-preference': cfg.driver_preference(),
        'auto-tighten':      cfg.auto_tighten(),
        'ignore-profiles':   cfg.ignore_profiles(),
    }
    out = {}
    for key, (kind, desc, man) in CONFIG_SETTINGS.items():
        src = cfg.machine_setting_source(key)             # (file, is_override) or None
        out[key] = {'kind': kind, 'value': values.get(key), 'desc': desc, 'man': man,
                    'source': src[0] if src and src[1] else None}
    return out


def _to_bool(s):
    return str(s).strip().lower() in ('true', 'yes', 'on', '1')


def set_config_setting(ctx, key, values, *, target=None):
    '''Set machine setting `key` from `values` (tokens, parsed per the setting's kind); an empty
    `values` clears it. Returns (changed, target_label). Raises KeyError for an unknown key.'''
    kind = CONFIG_SETTINGS[key][0]
    tfile, label = (target, target) if target else edit_target(ctx)
    if not values:                                        # clear
        (plugins.set_list_section if kind == 'list' else plugins.set_scalar_section)(
            tfile, key, [] if kind == 'list' else None)
    elif kind == 'list':
        plugins.set_list_section(tfile, key, list(values))
    elif kind == 'bool':
        token = 'true' if _to_bool(values[0]) else 'false'
        plugins.set_section(tfile, key, lambda indent: f'{key}: {token}')   # bare humon bool
    else:                                                 # scalar
        plugins.set_scalar_section(tfile, key, values[0])
    ctx.invalidate()
    return True, label


# -- theme (`configsys theme` + the TUI theme editor) ---------------------------------------------
# The theme lives in the `theme:` section (colors / elements.<el>.<attr> / gradient); saving a theme
# writes a theme-only PLUGIN (portable/shareable), per docs/tui-screens-plan.md (T1).

_THEME_BOOL_ATTRS = ('bold', 'underline', 'reverse')


def set_theme_value(ctx, dotted_key, value, *, target=None):
    '''Set one theme value by dotted path (`colors.accent`, `elements.profile.fg`, `gradient.from`);
    `value=None` removes it. bold/underline/reverse coerce to a bool. Returns (changed, label).'''
    tfile, label = (target, target) if target else edit_target(ctx)
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
        node[leaf] = _to_bool(value) if leaf in _THEME_BOOL_ATTRS else value
    plugins.set_theme(tfile, theme)
    ctx.invalidate()
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
    if existed and not force:
        return pdir, existed
    from .tui import theme as _theme
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / 'plugin.hu').write_text(
        f'{{\n    name: {name}\n    requires-abi: {plugins.ABI_VERSION}\n'
        f'    data: [ theme.hu ]\n}}\n', encoding='utf-8')
    block = plugins._emit_kv('theme', _theme.full_snapshot(ctx.config.theme()), 4)   # full, not diff
    (pdir / 'theme.hu').write_text('{\n' + block + '\n}\n', encoding='utf-8')
    (pdir / 'dotfiles').mkdir(exist_ok=True)
    return pdir, existed


def load_theme(ctx, name, *, target=None):
    '''Apply a saved theme plugin's `theme:` to the edit target (replacing your theme overrides, so
    the template becomes your look — retune on top after). Returns (changed, label|None).'''
    theme = _plugin_theme(Path(ctx.paths.plugins_dir) / name)
    if not theme:
        return False, None
    tfile, label = (target, target) if target else edit_target(ctx)
    plugins.set_theme(tfile, theme)
    ctx.invalidate()
    return True, label


def _primary_data_file(ctx):
    '''The primary plugin's highest-precedence synced data file (where a theme/pin can be written so
    it travels with the primary), plus the primary's name — or (None, None) if no primary is blessed
    and synced. Mirrors the edit_target / _pin_promote idiom.'''
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    if not prim:
        return None, None
    files = [f for f, role in plugins.layer_files(ctx.paths.plugins_dir, decls) if role == 'primary']
    return (files[0], prim) if files else (None, None)


def primary_theme_target(ctx):
    '''The primary plugin's name if one is blessed AND synced (so a theme can be written into it),
    else None — used to offer/hide the "save into primary plugin" destination.'''
    return _primary_data_file(ctx)[1]


def save_theme_to_primary(ctx):
    '''PROMOTE the current look into the PRIMARY plugin as a COMPLETE theme (full snapshot, not just
    diffs) and MOVE it there — clearing any theme in the top config so the primary's now-absolute
    theme isn't shadowed. This is deliberately absolute: a full theme in the primary overrides any
    theme plugin (the caller confirms first). Returns (ok, label): the primary name, or a reason.'''
    from .tui import theme as _theme
    target, prim = _primary_data_file(ctx)
    if not target:
        return False, 'no primary plugin blessed/synced to promote into'
    plugins.set_theme(target, _theme.full_snapshot(ctx.config.theme()))
    if str(target) != str(ctx.paths.user_config_file) and plugins.read_theme(ctx.paths.user_config_file):
        plugins.set_theme(str(ctx.paths.user_config_file), {})   # move, not copy — drop the local one
    ctx.invalidate()
    return True, prim


# -- plugins (`configsys plugin` + the TUI Plugins screen) ----------------------------------------
# Orchestration extracted from cmd_plugin so the CLI and the TUI Plugins screen share one path
# (docs/tui-screens-plan.md, F3 slice 4). Each returns structured results (ok/message/sync-actions);
# the caller prints (CLI) or shows a note (TUI).

def _locate_decl(ctx, ident):
    '''(config_file, decls, target) for the declared plugin `ident` — the top config, or a synced
    plugin's transitive `plugins:` (e.g. your primary). (None, None, None) if not found.'''
    pdir = ctx.paths.plugins_dir
    top = plugins.declared(ctx.paths.user_config_file)
    t = plugins.find_decl(top, pdir, ident)
    if t is not None:
        return ctx.paths.user_config_file, top, t
    if Path(pdir).exists():
        for sub in sorted(p for p in Path(pdir).iterdir() if p.is_dir()):
            decls = [d for d in (plugins._decl(e) for e in
                                 (plugins.read_manifest(sub).get('plugins') or [])) if d]
            t = plugins.find_decl(decls, pdir, ident)
            if t is not None:
                return sub / 'plugin.hu', decls, t
    return None, None, None


def plugin_sync(ctx, decls):
    '''Sync each declared plugin to its ref (transitive fixpoint). Returns [(name, action)].'''
    ctx.ensure_plugin_code()     # register transports from already-trusted plugins before sync
    return plugins.sync(ctx.runner, ctx.paths.plugins_dir, decls)


def plugin_add(ctx, source, ref=None, *, local=False, pin=False):
    '''Sync-FIRST add: a source that can't be cloned declares nothing. Lands in the primary's
    transitive `plugins:` (portable) when a primary is set, else this machine's top config (or with
    `local=True`). `pin` records the synced content sha256. Returns (ok, message, sync_results).'''
    ctx.ensure_user_config()
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
    results = plugin_sync(ctx, [{'source': source, 'ref': ref}])
    if not results or 'failed' in results[0][1].lower():
        return False, f'could not sync {source} — nothing added {plugins.source_hint(source)}', results
    target, existing = plugins.upsert_decl(cur, source, ref)
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
        msg = (f'{verb} {source}{at} in the primary plugin ({primary}) — commit + push + re-tag '
               f'{primary} and bump its ref to propagate (works locally now)')
    else:
        msg = f'{verb} {source}{at}' + (' (this machine only)' if primary else '')
    return True, lead + msg + pin_msg, results


def plugin_remove(ctx, ident):
    '''Undeclare a plugin (wherever it's declared) + delete its synced dir. Returns (ok, message).'''
    import shutil
    cfg_file, cur, target = _locate_decl(ctx, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    plugins.set_declared(cfg_file, [d for d in cur if d is not target])
    pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
    if pdir.exists() and not ctx.runner.pretend:
        shutil.rmtree(pdir)
    ctx.invalidate()
    where = ('' if str(cfg_file) == str(ctx.paths.user_config_file)
             else f' from {Path(cfg_file).parent.name}')
    return True, f'removed {target["source"]}{where}'


def plugin_update(ctx, ident, ref=None, *, pin=False):
    '''Re-pin a declared plugin's ref (if given) and re-sync it; `pin` re-records its sha256.
    Returns (ok, message, results).'''
    cfg_file, cur, target = _locate_decl(ctx, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}', []
    if ref:
        target['ref'] = ref
        plugins.set_declared(cfg_file, cur)
    results = plugin_sync(ctx, [target])
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
    msg = (f're-pinned {target["source"]} @{ref}{where}' if ref else f're-synced {target["source"]}')
    return True, msg + warn, results


def plugin_bless(ctx, ident):
    '''Make `ident` the sole `primary` plugin. Syncs it FIRST (+ its transitive plugins); only on a
    good sync does it declare + mark primary (clearing any other). Returns (ok, message, results).'''
    ctx.ensure_user_config()
    decls = plugins.declared(ctx.paths.user_config_file)
    existing = plugins.find_decl(decls, ctx.paths.plugins_dir, ident)
    source = existing['source'] if existing else ident
    ref = existing.get('ref') if existing else None
    results = plugin_sync(ctx, [{'source': source, 'ref': ref}])
    if not results or 'failed' in results[0][1].lower():
        return False, f"could not find/sync '{ident}' — nothing changed", results
    if existing is None:
        existing = {'source': source, 'ref': ref}
        decls.append(existing)
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


# -- dotfiles (`configsys dotfiles` + the TUI Dotfiles screen) ------------------------------------

def dotfiles_units(ctx):
    '''(driver, [ResolvedComponent]) — the via:dotfiles units in the active profiles. Resolution
    only (no install-state query), cheap + side-effect-free. Shared by the CLI + the TUI screen.'''
    from .drivers import get_driver
    units, _errs = ctx.routes.resolve_resilient(list(ctx.config.requested()))
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    return df, [units[k] for k in sorted(units) if units[k].driver == 'dotfiles']
