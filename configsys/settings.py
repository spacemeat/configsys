'''settings.py — THE registry of machine settings (review-2026-11-2 D1 / config-layers-20).

One row per setting — its kind, nature, choices, where it may be set, what it moves, how it is read and
described — and every table that used to be hand-kept beside it is DERIVED from this: layers'
MACHINE_SETTING_SECTIONS / SETTING_CHOICES / TOP_CONFIG_ONLY / BOOL_SETTINGS, actions'
CONFIG_SETTINGS / SETTING_NATURE / the routing and layout sets and the display getters. A new setting
is one row here. A leaf module (no configsys imports), so layers no longer reaches up into actions.

Fields: `kind` bool | scalar | list | map | dir (a `dirs.<sub>` key) | section (a matrix / side-store
section, not edited by `config`); `nature` uniform (an edit lands in your primary when one is blessed)
| machine (this box's top config); `choices` the accepted values of a scalar; `top_only` read only
from the top config; `routing` the resolver reads it (an edit rebuilds it); `layout` it moves WHERE
something installs (an edit drops the shells' glue-locations cache); `getter` the Config method that
reads its effective value; `editable` whether `configsys config` / the Config screen edit it;
`machine_section` whether it is a machine-setting section (only the top config and the primary may
set one).
'''

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str
    nature: str
    choices: tuple = ()
    top_only: bool = False
    routing: bool = False
    layout: bool = False
    getter: str = None
    editable: bool = True
    machine_section: bool = True
    man: str = 'configsys.hu(5)'
    desc: str = ''


_ROWS = [
    Setting('scope', 'scalar', 'machine', choices=('user', 'system'), layout=True, getter='default_scope',
            desc='Default install scope: user (~, the default when unset) or system (/opt, needs sudo).'),
    Setting('driver-preference', 'list', 'uniform', routing=True, layout=True, getter='driver_preference',
            desc=('Order ties between equally-valid install methods break in (unlisted drivers follow, in'
                 ' the default order).')),
    Setting('disabled-drivers', 'list', 'machine', routing=True, layout=True, getter='disabled_drivers',
            desc=('Install methods (via names) to turn OFF on this machine — their bindings stop '
                 'matching, like a false when:, so a soft suggests is skipped (a hard requires errors). '
                 'Use it to opt a mechanism out: dotfiles / glue to manage your own shell config, or '
                 'e.g. snap.')),
    Setting('auto-tighten', 'bool', 'uniform', getter='auto_tighten',
            desc='Auto-pick a floor-satisfying install method instead of only advising.'),
    Setting('adopt-installed', 'bool', 'uniform', getter='adopt_installed',
            desc=('Prefer an already-installed method/provider over the default (detection tier). On by '
                 'default.')),
    Setting('refresh-before-execute', 'scalar', 'uniform', choices=('auto', 'always', 'never'), getter='refresh_before_execute',
            desc=("Refresh the OS package index once before running staged ops: 'auto' (default, when the"
                 " batch has a native install/upgrade), 'always', or 'never'.")),
    Setting('install-overlay', 'bool', 'uniform', getter='install_overlay_default',
            desc=('Open the TUI Profiles screen with the install-state overlay on (installed underlined, installed-'
                 'but-unpicked ⊙ coloured). On by default; O toggles it.')),
    Setting('reboot-advice', 'bool', 'uniform', getter='reboot_advice',
            desc=('After an op (and as a TUI chip), advise when a reboot is needed / services want a '
                 "restart, via each distro's native check. On by default.")),
    Setting('primary-push', 'scalar', 'uniform', choices=('ask', 'auto', 'auto-on-quit', 'manual'), getter='primary_push',
            desc=("When your primary plugin is pushed to its remote: 'ask' (default; offered when you "
                 "quit the TUI with changes not pushed), 'auto' (after each command that changes it, and"
                 " when you quit the TUI), 'auto-on-quit' (only when you quit the TUI, Q included), or "
                 "'manual' (only `plugin push` / P).")),
    Setting('primary-verify', 'scalar', 'machine', choices=('off', 'signed'), top_only=True, getter='primary_verify',
            desc=("Check your primary's incoming commits: 'signed' — sync and push take in commits from "
                 "its remote only when each has a good signature from a key you trust; 'off' (default). "
                 'Read only from your top config.')),
    Setting('primary-trust', 'scalar', 'machine', choices=('identity', 'content', 'signed'), top_only=True, getter='primary_trust',
            desc=("Whether your primary plugin's commands, glue, dotfiles and keys run without `plugin "
                 "trust`: 'identity' (default — it is yours, whatever syncs in is trusted), 'content' "
                 "(re-trust after every sync that changes it, like any plugin), 'signed' (trusted while "
                 'its newest commit carries a good signature, else by content). Read only from your top '
                 'config.')),
    Setting('splash', 'scalar', 'uniform', getter='splash',
            desc=("Startup wait-screen animation: a splash provider name, 'random' to pick one at random "
                 'each run, off to disable, or unset for the built-in default.')),
    Setting('effects', 'scalar', 'machine', choices=('full', 'reduced', 'none'), getter='effects',
            desc=('TUI motion: full (gradient + splash), reduced (no gradient, calmer splash), or none '
                 '(no gradient; only the plain progress bar). Unset auto-picks reduced over SSH, else full. --effects '
                 'overrides.')),
    Setting('orphans-ignore', 'list', 'machine', getter='orphans_ignore',
            desc=('Name-or-glob patterns whose matching orphans stay quiet in `configsys orphans` '
                 '(matches a component name OR installed key).')),
    Setting('machine', 'scalar', 'machine', layout=True, getter='selected_machine',
            desc=('This box\'s machine name — which `picks:` column is "this machine". Unset defaults to '
                 '`this-machine`.')),
    Setting('detect-coexisting', 'bool', 'uniform', getter='detect_coexisting',
            desc=('After inspect, also detect installs of a component via its OTHER (unmanaged) methods '
                 'and show them as "also present". On by default.')),
    Setting('installer-shell-writes', 'scalar', 'uniform', choices=('block', 'allow'), getter='block_installer_shell_writes',
            desc=("Shell-rc guard: 'block' (default) snapshots your rc files around each install and "
                 "reverts what an installer writes there (staged as glue for review); 'allow' turns the "
                 'guard off.')),
    Setting('installer-shell-writes-allow', 'list', 'uniform', getter='shell_writes_allowlist',
            desc='Components exempt from the shell-rc guard — their installer may edit your rc files.'),
    Setting('locations', 'map', 'machine', routing=True, layout=True, getter='locations',
            desc=('Per-component install-location overrides, <component>=<absolute path> tokens: '
                 'find/manage that install HERE (scope-bypassing; path-based drivers honor it).')),
    Setting('dirs.user', 'dir', 'machine', routing=True, layout=True,
            desc='Base dir for user-scope installs (default ~). env CONFIGSYS_USERSCOPE_DIR wins.'),
    Setting('dirs.system', 'dir', 'machine', routing=True, layout=True,
            desc='Base dir for system-scope installs (default /opt). env CONFIGSYS_SYSTEMSCOPE_DIR wins.'),
    Setting('dirs.app', 'dir', 'uniform', routing=True, layout=True,
            desc='Category dir for self-contained apps ($CONFIGSYS_APP_DIR, default apps).'),
    Setting('dirs.sdk', 'dir', 'uniform', routing=True, layout=True,
            desc='Category dir for SDKs/libraries ($CONFIGSYS_SDK_DIR, default sdks).'),
    Setting('dirs.src', 'dir', 'uniform', routing=True, layout=True,
            desc='Category dir for source trees ($CONFIGSYS_SRC_DIR, default src).'),
    Setting('picks', 'section', 'uniform', editable=False, layout=True, desc='the component × machine matrix: what each machine installs'),
    Setting('pins', 'section', 'uniform', editable=False, routing=True, layout=True, desc='binding- and provider-pins (`configsys pin`)'),
    Setting('dispositions', 'section', 'machine', editable=False, desc='seen / interesting triage of the catalog'),
    Setting('uninstall', 'section', 'machine', editable=False, desc='this box\'s staged removals (`configsys uninstall`)'),
    Setting('facets', 'section', 'machine', editable=False, routing=True, machine_section=False, desc='facet values (`gpu:`…) — any layer'),
]

SETTINGS = {s.key: s for s in _ROWS}

# -- the derived tables (what the rest of configsys reads) -----------------------------------------
EDITABLE = {k: s for k, s in SETTINGS.items() if s.editable}
SECTIONS = frozenset(k.split('.', 1)[0] for k, s in SETTINGS.items() if s.machine_section)
CHOICES = {k: s.choices for k, s in SETTINGS.items() if s.choices}
TOP_ONLY = frozenset(k for k, s in SETTINGS.items() if s.top_only)
BOOLS = frozenset(k for k, s in SETTINGS.items() if s.kind == 'bool')
NATURE = {k: s.nature for k, s in SETTINGS.items()}
ROUTING = frozenset(k.split('.', 1)[0] for k, s in SETTINGS.items() if s.routing)
LAYOUT = frozenset(k.split('.', 1)[0] for k, s in SETTINGS.items() if s.layout or s.routing)
