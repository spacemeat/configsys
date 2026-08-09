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


def add_profile(ctx, name):
    '''Create a new, empty profile in the portable edit target (primary-if-set, else top config).
    Returns (changed, label); a bad/duplicate name returns (False, reason).'''
    name = (name or '').strip()
    if not name:
        return False, 'a profile name is required'
    if name == 'all':
        return False, '"all" is reserved'
    if name in ctx.config.profile_names():
        return False, f'"{name}" already exists'
    tfile, label = edit_target(ctx)
    profs = plugins.read_profiles(tfile)
    profs[name] = []                                 # a fresh profile with no members yet
    plugins.set_profiles(tfile, profs)
    ctx.invalidate()
    return True, label


def remove_profile(ctx, name):
    '''Delete a profile from the editable layer that defines it (top config or the primary plugin),
    first dropping it from the active `configs:` set. Refuses a profile defined only in a
    non-editable layer (the repo or a data plugin). Returns (changed, label/reason).'''
    src = ctx.config.profile_source(name)
    if src is None:
        return False, f'"{name}" is not defined'
    editable = {str(ctx.paths.user_config_file), str(edit_target(ctx)[0])}
    if str(src) not in editable:
        return False, f'cannot remove "{name}" (defined in {_dir_label(ctx, src)}, not editable here)'
    if name in set(ctx.config.active_profiles):      # drop the active reference first
        set_profile_active(ctx, name, False)
    profs = plugins.read_profiles(str(src))
    profs.pop(name, None)
    plugins.set_profiles(str(src), profs)
    ctx.invalidate()
    label = _dir_label(ctx, src)
    if name in ctx.config.profile_names():           # a lower layer still defines it
        return True, f'removed "{name}" from {label} (still defined by a lower layer)'
    return True, f'removed "{name}" (from {label})'


def set_profile_include(ctx, profile, other, add, *, target=None):
    '''Add (`add=True`) or remove a `+other` include term in `profile` — include another profile's
    members. Returns (changed, label); a no-op or invalid include returns (False, reason).'''
    if other == profile:
        return False, "a profile can't include itself"
    if other not in ctx.config.profile_names():
        return False, f'no profile "{other}"'
    tfile, label = (target, target) if target else _profile_target(ctx, profile)
    new_terms = ctx.config.plan_include_edit(profile, other, add, tfile)
    if new_terms is None:
        return False, label
    profs = plugins.read_profiles(tfile)
    profs[profile] = new_terms
    plugins.set_profiles(tfile, profs)
    ctx.invalidate()
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
    'splash':            ('scalar', 'Startup wait-screen animation: a splash provider name, '
                                    "'random' to pick one at random each run, off to disable, or "
                                    'unset for the built-in default.',
                          'configsys(1)'),
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
    'auto-tighten':      'uniform',
    'ignore-profiles':   'uniform',
    'splash':            'uniform',
    'dirs.user':         'machine',
    'dirs.system':       'machine',
    'dirs.app':          'uniform',
    'dirs.sdk':          'uniform',
    'dirs.src':          'uniform',
}


def _read_setting(config_file, key):
    '''The value of machine setting `key` in ONE .hu file (kind-aware), or None if absent.'''
    kind = CONFIG_SETTINGS[key][0]
    if kind == 'dir':
        return plugins.read_dirs(config_file).get(key.split('.', 1)[1])
    if kind == 'list':
        return plugins.read_list_section(config_file, key) or None
    return plugins.read_scalar_section(config_file, key)      # scalar + bool


def _setting_tokens(value, kind):
    '''A value read from a file back into the token list set_config_setting expects.'''
    if value is None:
        return []
    if kind == 'list':
        return list(value)
    if kind == 'bool':
        return ['true' if _to_bool(value) else 'false']
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


def _setting_target(ctx, key):
    '''(file, label) where an edit to machine setting `key` is EFFECTIVE: the writable layer it
    already lives in (editing a lower one would be shadowed), else its nature default — the primary
    plugin for a 'uniform' setting when one is blessed+synced, this machine's top config for a
    'machine' setting (or when no primary exists). The counterpart to _profile_target for scalars.'''
    where, _who = _setting_home(ctx, key)
    local = str(ctx.paths.user_config_file)
    if where == 'local':
        return local, 'top config'
    pfile, pname = _primary_data_file(ctx)
    if where == 'primary':
        return pfile, pname
    if SETTING_NATURE.get(key) == 'uniform' and pfile:       # unset -> nature default
        return pfile, pname
    return local, 'top config'


def config_settings(ctx):
    '''{key: {kind, value, desc, man}} — the effective machine settings for display (CLI
    `config show` and the TUI Config screen). Read-only.'''
    from .paths import CONFIG_DIR_KEYS
    cfg = ctx.config
    values = {
        'scope':             cfg.default_scope(),
        'driver-preference': cfg.driver_preference(),
        'auto-tighten':      cfg.auto_tighten(),
        'ignore-profiles':   cfg.ignore_profiles(),
        'splash':            cfg.splash(),
    }
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


def _to_bool(s):
    return str(s).strip().lower() in ('true', 'yes', 'on', '1')


def set_config_setting(ctx, key, values, *, target=None):
    '''Set machine setting `key` from `values` (tokens, parsed per the setting's kind); an empty
    `values` clears it. Returns (changed, target_label). Raises KeyError for an unknown key.'''
    kind = CONFIG_SETTINGS[key][0]
    tfile, label = (target, target) if target else _setting_target(ctx, key)
    if kind == 'dir':                                     # nested `dirs.<sub>`: edit the dirs map
        sub = key.split('.', 1)[1]
        dirs = plugins.read_dirs(tfile)
        if values:
            dirs[sub] = values[0]
        else:
            dirs.pop(sub, None)
        plugins.set_dirs(tfile, dirs)
        ctx.invalidate()
        return True, label
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


def move_config_setting(ctx, key):
    '''Move machine setting `key` between this machine's top config and the primary plugin, carrying
    its effective value and clearing the source. The direction is inferred from where it lives now
    (local->primary, or primary->local); a setting at its built-in default has nothing to move.
    Returns (ok, message).'''
    where, _who = _setting_home(ctx, key)
    if where is None:
        return False, f'{key} is at its default — set a value before moving it'
    kind = CONFIG_SETTINGS[key][0]
    local = str(ctx.paths.user_config_file)
    pfile, pname = _primary_data_file(ctx)
    if where == 'local':
        if not pfile:
            return False, 'no primary plugin blessed + synced to move into'
        src, dst, dst_label = local, pfile, pname
    else:                                                 # primary -> local
        src, dst, dst_label = pfile, local, 'top config'
    tokens = _setting_tokens(_read_setting(src, key), kind)
    set_config_setting(ctx, key, tokens, target=dst)      # write the value at the destination
    set_config_setting(ctx, key, [], target=src)          # clear it from the source
    ctx.invalidate()
    return True, f'{key} → {dst_label}'


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


def copy_page_theme(ctx, src, dst):
    '''Copy one page's theme overrides (its role styles + gradient) onto another page, in the edit
    target. Returns (ok, label|reason). Nothing to copy if the source page has no overrides.'''
    tfile, label = edit_target(ctx)
    theme = plugins.read_theme(tfile)
    pages = theme.setdefault('pages', {})
    srcov = pages.get(src)
    if not isinstance(srcov, dict) or not srcov:
        return False, f'{src} has no overrides to copy'
    pages[dst] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in srcov.items()}
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
    results = plugins.sync(ctx.runner, ctx.paths.plugins_dir, decls)
    ctx.invalidate()             # new data files / drivers are now on disk — rebuild so they surface
    return results


def plugin_add(ctx, source, ref=None, *, local=False, pin=False, replace=False):
    '''Sync-FIRST add: a source that can't be cloned declares nothing. Lands in the primary's
    transitive `plugins:` (portable) when a primary is set, else this machine's top config (or with
    `local=True`). `pin` records the synced content sha256. If a plugin of the same NAME is already
    declared from a DIFFERENT source, refuse unless `replace=True` (then drop the old one first — the
    easy way to swap an in-development local copy for its published version). Returns (ok, message,
    sync_results).'''
    ctx.ensure_user_config()
    # collision: another declared plugin lands in the same synced dir (same name) from a different
    # source. They'd clobber each other, so require an explicit --replace.
    new_dn = plugins.dir_name(source)
    clashes = [d for d in plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
               if plugins.dir_name(d['source']) == new_dn and d['source'] != source]
    if clashes and not replace:
        others = ', '.join(sorted({d['source'] for d in clashes}))
        return (False, f"a plugin named '{new_dn}' is already declared from {others}; "
                       f"re-run with --replace to swap it for {source}", [])
    if clashes and replace:
        for old in {d['source'] for d in clashes}:       # drop each old decl (wherever it's declared)
            plugin_remove(ctx, old)
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


def plugin_trust(ctx, ident):
    '''Approve a code plugin's CURRENT content to run during installs (trust-on-content-hash).
    Returns (ok, note). Mirrors `configsys plugin trust`.'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    key = plugins.dir_name(target['source'])
    pdir = Path(ctx.paths.plugins_dir) / key
    if not pdir.exists():
        return False, f'{key} is not synced — sync it first'
    manifest = plugins.read_manifest(pdir)
    disp = manifest.get('name', key)
    if not manifest.get('code'):
        return False, f'{disp} ships no code — nothing to trust'
    identity = plugins.plugin_identity(pdir)
    if identity is None:
        return False, f'could not read {disp}’s contents'
    plugins.set_trust(ctx.paths.plugin_trust_file, key, identity)
    ctx.invalidate()
    return True, f'trusted {disp} @ {identity.split(":")[-1][:12]} — its code will run'


def plugin_untrust(ctx, ident):
    '''Revoke a code plugin's trust. Returns (ok, note). Mirrors `configsys plugin untrust`.'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, ident)
    key = plugins.dir_name(target['source']) if target else ident
    pdir = Path(ctx.paths.plugins_dir) / key
    disp = plugins.read_manifest(pdir).get('name', key) if pdir.exists() else key
    if plugins.remove_trust(ctx.paths.plugin_trust_file, key):
        ctx.invalidate()
        return True, f'untrusted {disp}'
    return False, f'{disp} was not trusted'


# -- dotfiles (`configsys dotfiles` + the TUI Dotfiles screen) ------------------------------------

def dotfiles_units(ctx):
    '''(driver, [ResolvedComponent]) — the via:dotfiles units in the active profiles. Resolution
    only (no install-state query), cheap + side-effect-free. Shared by the CLI + the TUI screen.'''
    from .drivers import get_driver
    units, _errs = ctx.routes.resolve_resilient(list(ctx.config.requested()))
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    return df, [units[k] for k in sorted(units) if units[k].driver == 'dotfiles']
