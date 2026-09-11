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
    '''Where a membership edit is EFFECTIVE **and writable**: the profile's highest-precedence
    definition layer when that layer is one we may edit — this machine's top config or the primary
    plugin (editing a lower layer would be shadowed by that definition) — else the portable default
    (primary-if-set, then top config). NEVER the repo baseline or a data plugin: when a profile is
    defined only in a non-editable lower layer (e.g. the shipped `dev` in the repo's config.hu), the
    term-algebra writer AMENDS it from the editable layer via `+self`, so the template stays
    untouched. Mirrors remove_profile's `editable` set.'''
    src = ctx.config.profile_source(profile)
    editable = {str(ctx.paths.user_config_file), str(edit_target(ctx)[0])}
    if src is not None and str(src) in editable:
        return str(src), _dir_label(ctx, src)
    return edit_target(ctx)


def _configs_target(ctx):
    '''Where a `configs:` edit is EFFECTIVE: the top config if it already has a `configs:` (it
    shadows lower layers whole-list), else the portable default.'''
    if plugins.read_configs(ctx.paths.user_config_file):
        return str(ctx.paths.user_config_file), 'top config'
    return edit_target(ctx)


def _membership_effect_ok(cfg, profile, comp, action):
    '''Did the write achieve `action`'s intended post-state? `add`/`remove` toggle membership.'''
    mem = comp in cfg._members_safe(profile)
    return {'add': mem, 'remove': not mem}[action]


def set_profile_membership(ctx, profile, comp, action, *, target=None, machine=None):
    '''Write the term-algebra edit so `comp` becomes a member (`action='add'`) or a non-member
    (`'remove'`) of `profile`, via Config.plan_membership_edit, to `target` or the effective target.
    `machine` scopes the edit into a `machines:[<machine>].profiles` namespace (that machine's rung
    must be loaded — pass `--machine`). Returns (changed, label); a no-op returns (False, label); a
    shadowed target -> (False, warning).'''
    if machine is not None:
        return _set_machine_membership(ctx, machine, profile, comp, action)
    tfile, label = (target, target) if target else _profile_target(ctx, profile)
    new_terms = ctx.config.plan_membership_edit(profile, comp, action, tfile)
    if new_terms is None:
        return False, label
    profs = plugins.read_profiles(tfile)
    profs[profile] = new_terms
    plugins.set_profiles(tfile, profs)
    ctx.invalidate()
    if not _membership_effect_ok(ctx.config, profile, comp, action):    # shadowed -> no effect
        return False, f'{label}: "{profile}" is overridden by a higher-precedence layer (no effect)'
    return True, label


def _set_machine_membership(ctx, machine, profile, comp, action):
    '''Machine-scoped membership write: the edit lands in `machines:[machine].profiles.<profile>` in
    the file that defines that machine, planned against the injected machine-role rung. The machine's
    layer MUST be loaded (run with `--machine <machine>`, or be on that box). Returns (changed, label).'''
    if ctx.config.selected_machine() != machine or ctx.config.machine_layer_index() is None:
        return False, (f'machine "{machine}" is not the loaded target — re-run with `--machine {machine}`'
                       f' (or define it in `machines:` first)')
    tidx = ctx.config.machine_layer_index()
    tfile = str(ctx.config._layers[tidx].path)           # the file holding machines:[machine]
    new_terms = ctx.config.plan_membership_edit(profile, comp, action, tfile, layer_idx=tidx)
    if new_terms is None:
        return False, f'machine {machine}'
    machines = plugins.read_machines(tfile)
    entry = machines.setdefault(machine, {})
    entry.setdefault('profiles', {})[profile] = new_terms
    plugins.set_machines(tfile, machines)
    ctx.invalidate()
    if not _membership_effect_ok(ctx.config, profile, comp, action):
        return False, f'machine {machine}: "{profile}" is overridden by a higher-precedence layer (no effect)'
    return True, f'machine {machine}'


UNINSTALL_PROFILE = '!uninstall'


def stage_uninstall(ctx, comp, *, on=True):
    '''Stage (`on`) or unstage (`on=False`) `comp` in the reserved `!uninstall` queue — a
    machine-local (top-config) pending-removal list. Returns (changed, label). The TUI `x` calls
    this; the real uninstall runs later from TUI::Components (execute) — or `clear_uninstall` cancels.'''
    tfile = str(ctx.paths.user_config_file)          # machine-local, like pins — never a plugin
    return set_profile_membership(ctx, UNINSTALL_PROFILE, comp, 'add' if on else 'remove', target=tfile)


def stage_adopt(ctx, comp):
    '''Park `comp` into the configured `orphans-adopt-target` staging profile (the TUI `s` action) —
    a non-active review profile the user later triages into real base profiles. Returns (changed,
    label). Written machine-local (top config), like `!uninstall`/pins: orphan triage is per-machine
    state, so it must NOT land in the primary plugin (which travels to every machine) — and a
    same-layer edit stays a plain list edit, so removing an entry later is a clean delete, never a
    `+self ~name` amend leaving residual exclusions.'''
    tfile = str(ctx.paths.user_config_file)
    return set_profile_membership(ctx, ctx.config.orphans_adopt_target(), comp, 'add', target=tfile)


def set_disposition(ctx, comp, state):
    '''Set component `comp`'s disposition — 'seen' | 'interesting', or clear it (state None/'new') —
    in the LOCAL dispositions store (this box's triage, like !uninstall). Returns (changed, label).'''
    tfile = str(ctx.paths.user_config_file)
    disp = plugins.read_dispositions(tfile)
    want = None if state in (None, 'new') else state
    if disp.get(comp) == want:
        return False, 'no change'
    if want is None:
        disp.pop(comp, None)
    else:
        disp[comp] = want
    plugins.set_dispositions(tfile, disp)
    ctx.invalidate()
    return True, 'top config'


def set_included(ctx, comp, machines, on):
    '''v3 matrix A/D: mark `comp` Included (`on=True`) or not, on EACH machine in `machines` (plural =
    fan-out). Writes the local per-machine `picks:` store (this box). Returns (changed_count, label).'''
    tfile = str(ctx.paths.user_config_file)          # machine-local, like pins/dispositions
    picks = plugins.read_picks(tfile)
    changed = 0
    for m in machines:
        cur = list(picks.get(m, []))
        has = comp in cur
        if on and not has:
            cur.append(comp)
            changed += 1
        elif not on and has:
            cur = [c for c in cur if c != comp]
            changed += 1
        picks[m] = cur
    if changed:
        plugins.set_picks(tfile, picks)
        ctx.invalidate()
    return changed, 'picks'


def set_included_clear_machine(ctx, machine):
    '''Drop a machine's entire `picks:` entry (when the machine is removed). Returns (changed, label).'''
    tfile = str(ctx.paths.user_config_file)
    picks = plugins.read_picks(tfile)
    if machine not in picks:
        return False, 'picks'
    picks.pop(machine, None)
    plugins.set_picks(tfile, picks)
    ctx.invalidate()
    return True, 'picks'


def migrate_picks(ctx):
    '''v3 migration: seed the current machine's `picks:` from today's active-profile membership, so
    switching to the matrix workflow (empty `configs:`) preserves the install set. Idempotent —
    already-picked components are skipped. Returns (added_count, machine).'''
    machine = ctx.config.current_machine()
    members = sorted(n for n, srcs in ctx.config.requested().items()
                     if any(s != 'picks' for s in srcs))     # active-profile members (not picks-only)
    tfile = str(ctx.paths.user_config_file)
    picks = plugins.read_picks(tfile)
    cur = picks.get(machine, [])
    added = [m for m in members if m not in cur]
    if not added:
        return 0, machine
    picks[machine] = list(cur) + added
    plugins.set_picks(tfile, picks)
    ctx.invalidate()
    return len(added), machine


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
    '''Empty the `!uninstall` queue (cancel every pending removal). Returns how many were cleared.'''
    n = len(ctx.config.uninstall_queue())
    tfile = str(ctx.paths.user_config_file)
    profs = plugins.read_profiles(tfile)
    if UNINSTALL_PROFILE in profs:
        del profs[UNINSTALL_PROFILE]
        plugins.set_profiles(tfile, profs)
        ctx.invalidate()
    return n


def add_profile(ctx, name):
    '''Create a new, empty profile in the portable edit target (primary-if-set, else top config).
    Returns (changed, label); a bad/duplicate name returns (False, reason).'''
    name = (name or '').strip()
    if not name:
        return False, 'a profile name is required'
    if name == 'all':
        return False, '"all" is reserved'
    if name.startswith('!'):
        return False, '"!"-prefixed profile names are reserved (system profiles like !uninstall)'
    # A same-name copy of a SYSTEM (repo/plugin) profile is allowed — it becomes an editable user
    # profile that shadows the browse original (the disposition model's clone). Refuse only when an
    # EDITABLE profile of that name already exists (you can't have two of your own).
    src = ctx.config.profile_source(name)
    editable = {str(ctx.paths.user_config_file), str(edit_target(ctx)[0])}
    if src is not None and str(src) in editable:
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


def clone_profile(ctx, name, *, target=None):
    '''Deep-clone SYSTEM profile `name` (repo/plugin) into an editable user-layer copy you can curate
    (the disposition model's core move). The clone keeps the SAME NAME, so — since `_expand` only
    inherits a lower layer on an explicit `+self` — the copy SHADOWS the system definition rather than
    amending it: any component the system later adds to the profile surfaces as NEW instead of leaking
    into your clone ("the profile is the lockfile"). Structure is preserved, not flattened: each
    `+other` include is cloned as its OWN same-name unit (recursively) and kept as a `+other` ref, so
    the hierarchy travels intact; leaf components are materialized. Writes to the portable edit target
    (primary-if-set, else top config), or `target`. Returns (changed, label/reason).'''
    cfg = ctx.config
    if name not in cfg.profile_names():
        return False, f'"{name}" is not defined'
    if name == cfg.ALL_PROFILE or name.startswith('!'):
        return False, f'"{name}" is reserved and cannot be cloned'
    tfile, label = (target, _dir_label(ctx, target)) if target else edit_target(ctx)
    editable = {str(ctx.paths.user_config_file), str(edit_target(ctx)[0])}
    src = cfg.profile_source(name)
    if src is not None and str(src) in editable:
        return False, f'"{name}" is already an editable user profile here (nothing to clone)'

    # BFS the include-closure; clone every SYSTEM profile reached, skip ones already user-editable
    # (their +ref resolves to the existing copy) and reserved names.
    order, seen, stack = [], set(), [name]
    while stack:
        q = stack.pop(0)
        if q in seen or q not in cfg.profile_names():
            continue
        seen.add(q)
        qsrc = cfg.profile_source(q)
        if q != name and (qsrc is None or str(qsrc) in editable):
            continue                                     # already-editable include: leave it, use as-is
        order.append(q)
        for inc in sorted(cfg.profile_includes(q)):
            if inc not in seen and not inc.startswith('!') and inc != cfg.ALL_PROFILE:
                stack.append(inc)

    profs = plugins.read_profiles(tfile)
    for q in order:
        incs = sorted(i for i in cfg.profile_includes(q) if not i.startswith('!') and i != cfg.ALL_PROFILE)
        own = sorted(cfg.profile_own_components(q))      # materialized leaves (post-`+self`, no amend term)
        profs[q] = [f'+{i}' for i in incs] + own         # includes as refs, leaves inline; no `+self` = shadow
    plugins.set_profiles(tfile, profs)
    ctx.invalidate()
    extra = f' (+{len(order) - 1} included)' if len(order) > 1 else ''
    return True, f'{label}{extra}'


def clone_profile_into(ctx, name, into=None):
    '''Clone system profile `name` (via clone_profile) and — the delta placement step — emplace it as
    a `+member` of the user profile `into`, so a cloned sub-profile keeps its cross-cutting structure
    under a profile you own. `into=None` clones it standalone (top-level). The clone lands in the same
    editable layer as `into` (so the `+name` reference resolves), else the portable edit target.
    Returns (changed, label/reason).'''
    if into is not None:
        if into not in ctx.config.profile_names():
            return False, f'no profile "{into}" to emplace the clone into'
        src = ctx.config.profile_source(into)
        editable = {str(ctx.paths.user_config_file), str(edit_target(ctx)[0])}
        if src is None or str(src) not in editable:
            return False, f'"{into}" is not an editable user profile (clone or create it first)'
        target = str(src)
    else:
        target = None
    changed, label = clone_profile(ctx, name, target=target)
    if not changed:
        return changed, label
    if into is not None:
        inc_changed, _l = set_profile_include(ctx, into, name, True)   # attach +name to the parent
        if inc_changed:
            label = f'{label}, +{name} in "{into}"'
    return True, label


def add_machine(ctx, name):
    '''Create a new, empty machine entry in `machines:` (portable edit target — primary if set). A
    machine is a composing layer: its `profiles:` overlay the shared ones by name. Returns
    (changed, label); a bad/duplicate name returns (False, reason).'''
    name = (name or '').strip()
    if not name:
        return False, 'a machine name is required'
    if name in ctx.config.machines():
        return False, f'machine "{name}" already exists'
    tfile, label = edit_target(ctx)
    machines = plugins.read_machines(tfile)
    machines[name] = {}
    plugins.set_machines(tfile, machines)
    ctx.invalidate()
    return True, label


def remove_machine(ctx, name):
    '''Delete a machine entry from the portable edit target. Returns (changed, label/reason).'''
    tfile, label = edit_target(ctx)
    machines = plugins.read_machines(tfile)
    if name not in machines:
        return False, f'machine "{name}" is not defined in {label}'
    del machines[name]
    plugins.set_machines(tfile, machines)
    ctx.invalidate()
    return True, label


def rename_machine(ctx, old, new):
    '''Rename a machine: move its `machines:` entry AND its `picks:` set to `new`, and re-point the
    `machine:` selection if it named `old`. Returns (changed, reason).'''
    new = (new or '').strip()
    if not new:
        return False, 'a new name is required'
    if new == old:
        return False, 'same name'
    if new in ctx.config.machines():
        return False, f'machine "{new}" already exists'
    tfile, _label = edit_target(ctx)
    machines = plugins.read_machines(tfile)
    if old in machines:
        machines[new] = machines.pop(old)
        plugins.set_machines(tfile, machines)
    # carry the (local) picks entry across
    ptile = str(ctx.paths.user_config_file)
    picks = plugins.read_picks(ptile)
    if old in picks:
        picks[new] = picks.pop(old)
        plugins.set_picks(ptile, picks)
    ctx.invalidate()
    if ctx.config.selected_machine() == old:               # re-point this box's selection
        set_config_setting(ctx, 'machine', [new])
    return True, new


def set_machine_active(ctx, name):
    '''Set THIS box's `machine:` selection (local top config, machine-nature) — an empty name clears
    it. Returns (changed, label).'''
    return set_config_setting(ctx, 'machine', [name] if name else [])


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


def set_subprofile_membership(ctx, profile, sub, member, *, target=None):
    '''Include (`member=True`) or exclude (`member=False`) subprofile `sub` in `profile` via the term
    algebra — writes a `+sub`/`~sub` term (or drops the opposing own term) as needed. The Profiles
    tree's membership toggle. Returns (changed, label); a no-op or invalid returns (False, reason).'''
    if sub == profile:
        return False, "a profile can't include or exclude itself"
    if sub not in ctx.config.profile_names():
        return False, f'no profile "{sub}"'
    tfile, label = (target, target) if target else _profile_target(ctx, profile)
    new_terms = ctx.config.plan_subprofile_edit(profile, sub, member, tfile)
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
    'adopt-installed':   ('bool',   'Prefer an already-installed method/provider over the default '
                                    '(detection tier). On by default.', 'configsys(1)'),
    'refresh-before-execute': ('scalar', 'Refresh the OS package index once before running staged '
                                    "ops: 'auto' (default, when the batch has a native install/"
                                    "upgrade), 'always', or 'never'.", 'configsys(1)'),
    'install-overlay':   ('bool',   'Open TUI::Profiles with the install-state overlay on (installed '
                                    'underlined, orphans coloured). On by default; O toggles it.',
                          'configsys(1)'),
    'splash':            ('scalar', 'Startup wait-screen animation: a splash provider name, '
                                    "'random' to pick one at random each run, off to disable, or "
                                    'unset for the built-in default.',
                          'configsys(1)'),
    'effects':           ('scalar', 'TUI motion: full (gradient + splash), reduced (no gradient, '
                                    'calmer splash), or none (no gradient or splash). Unset '
                                    'auto-picks reduced over SSH, else full. --effects overrides.',
                          'configsys(1)'),
    'orphans-ignore':    ('list',   'Name-or-glob patterns whose matching orphans stay quiet in '
                                    '`configsys orphans` (matches a component name OR installed key).',
                          'configsys(1)'),
    'orphans-adopt-target': ('scalar', 'Profile the TUI orphan "stage" (s) action parks components '
                                       'into for later triage (default: orphans-lurking).',
                          'configsys(1)'),
    'machine': ('scalar', 'This box\'s machine name — selects a `machines:` entry from your primary '
                          '(its profiles/configs overlay the shared ones). Unset = shared + local only.',
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
    'adopt-installed':   'uniform',
    'refresh-before-execute': 'uniform',      # a behavior preference (override per-machine with `m`)
    'install-overlay':   'uniform',           # a UI preference
    'splash':            'uniform',
    'effects':           'machine',           # about THIS terminal/transport (SSH), not shared config
    'orphans-ignore':    'machine',           # acknowledged one-offs on THIS box, not shared config
    'orphans-adopt-target': 'uniform',        # a workflow preference — the same staging profile name
    'machine':           'machine',           # which machine THIS box is — inherently per-box (local)
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
        'adopt-installed':   cfg.adopt_installed(),
        'orphans-ignore':    cfg.orphans_ignore(),
        'orphans-adopt-target': cfg.orphans_adopt_target(),
        'splash':            cfg.splash(),
        'machine':           cfg.selected_machine(),
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
    import shutil
    ctx.ensure_user_config()
    # a local-path source is saved ABSOLUTE (resolved from the CWD now), so the decl doesn't silently
    # point elsewhere when configsys is later run from another directory. Remote sources pass through.
    source = plugins.abs_local_source(source)
    # collision: another declared plugin lands in the same synced dir (same name) from a different
    # source. They'd clobber each other, so require an explicit --replace.
    new_dn = plugins.dir_name(source)
    clashes = [d for d in plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
               if plugins.dir_name(d['source']) == new_dn and d['source'] != source]
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
    if retargeting and pdir.exists() and not ctx.runner.pretend:
        if backup.exists():
            shutil.rmtree(backup)
        pdir.rename(backup)                              # clear the dir so the new source clones clean
        moved = True

    results = plugin_sync(ctx, [{'source': source, 'ref': ref}])
    if not results or 'failed' in results[0][1].lower():
        if moved:                                        # restore the old synced dir; decls untouched
            if pdir.exists():
                shutil.rmtree(pdir)
            backup.rename(pdir)
        return False, f'could not sync {source} — nothing changed {plugins.source_hint(source)}', results
    if moved and backup.exists():                        # new source synced OK -> discard the backup
        shutil.rmtree(backup)

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


def plugin_remove(ctx, ident, *, keep_dir=False):
    '''Undeclare a plugin (wherever it's declared) + delete its synced dir. `keep_dir` drops only the
    declaration and leaves the synced dir — used by a retarget, where the new source has just re-synced
    into that same dir (dir_name is shared). Returns (ok, message).'''
    import shutil
    cfg_file, cur, target = _locate_decl(ctx, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}'
    plugins.set_declared(cfg_file, [d for d in cur if d is not target])
    pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
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
    cfg_file, cur, target = _locate_decl(ctx, ident)
    if target is None:
        return False, f'no declared plugin matches {ident!r}', []
    latest_note = ''
    if latest:
        if ref:
            return False, 'pass either --ref or --latest, not both', []
        ref, kind = plugins.latest_ref(ctx.runner, target['source'])
        if ref is None:
            return False, (f'could not resolve --latest for {target["source"]} — no version tags '
                           f'and no main/master branch (unreachable or private?)'), []
        latest_note = f' (latest {kind})'
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
    msg = (f're-pinned {target["source"]} @{ref}{latest_note}{where}' if ref
           else f're-synced {target["source"]}')
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


def plugin_trust_all(ctx):
    '''Trust EVERY code plugin currently untrusted or changed (the bulk `T` / `plugin trust --all`).
    Returns (n_trusted, note). Unsynced code plugins are counted in the note but skipped (nothing
    on disk to hash yet).'''
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    rows = plugins.status(ctx.paths.plugins_dir, eff, trust_file=ctx.paths.plugin_trust_file)
    pending = [r for r in rows if r['code_state'] in ('untrusted', 'changed')]
    unsynced = [r for r in rows if r['code_state'] == 'unsynced']
    n = 0
    for r in pending:
        ok, _note = plugin_trust(ctx, r['name'])
        n += 1 if ok else 0
    if not pending:
        return 0, ('no untrusted code plugins'
                   + (' (some ship code but are unsynced — sync first)' if unsynced else ''))
    tail = f'; {len(unsynced)} unsynced skipped' if unsynced else ''
    return n, f'trusted {n} code plugin(s){tail}'


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
