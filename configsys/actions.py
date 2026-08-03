'''actions.py — the shared action layer.

Reusable read+write operations that BOTH the CLI subcommands and the TUI screens call, so the two
stay in lockstep (the TUI is a skin over these, never a parallel implementation). Each takes the app
`Context`, edits config surgically via the `plugins.set_*` writers, and `ctx.invalidate()`s the
cached config so the change takes effect on the next read. See docs/tui-screens-plan.md (F3).
'''

from . import plugins


def edit_target(ctx):
    '''(file, label) that profile / configs edits write to by default: the primary plugin's data
    file when a primary is blessed + synced (so edits travel to your other machines), else this
    machine's top config. The TUI/CLI can override the target explicitly.'''
    decls = plugins.declared(ctx.paths.user_config_file)
    prim = plugins.primary_name(decls)
    if prim:
        files = [f for f, role in plugins.layer_files(ctx.paths.plugins_dir, decls)
                 if role == 'primary']
        if files:
            return files[0], prim
    return str(ctx.paths.user_config_file), 'top config'


def set_profile_membership(ctx, profile, comp, action, *, target=None):
    '''Add or remove `comp` in `profile` (`action` = 'add'|'remove'), writing the term-algebra edit
    (via Config.plan_membership_edit) to `target` or the default edit target. Returns
    (changed, target_label); a no-op (already in the wanted state) returns (False, label).'''
    tfile, label = (target, target) if target else edit_target(ctx)
    new_terms = ctx.config.plan_membership_edit(profile, comp, action, tfile)
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
    tfile, label = (target, target) if target else edit_target(ctx)
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
    'scope':             ('scalar', 'Default install scope: user (~) or system (/opt, needs sudo).',
                          'configsys(1)'),
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
    return {key: {'kind': kind, 'value': values.get(key), 'desc': desc, 'man': man}
            for key, (kind, desc, man) in CONFIG_SETTINGS.items()}


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
