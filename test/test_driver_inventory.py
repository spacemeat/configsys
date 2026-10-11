'''Every built-in driver is consciously placed — the enforcement half of the /add-driver skill
(.claude/skills/add-driver/SKILL.md). Adding, renaming or removing a driver fails here until each
touchpoint is updated; each failure names the skill section that says how. The skill is the
checklist, this file is the alarm — and TOUCHPOINTS below also fails when a code symbol the skill
points at is renamed, so the playbook can't silently rot.'''

import importlib
import re
from pathlib import Path

import pytest

from configsys.driver import Driver
from configsys.drivers import BUILTIN_DRIVERS, _REGISTRY
from configsys.resolve import DEFAULT_DRIVER_PREFERENCE

ROOT = Path(__file__).resolve().parent.parent
SKILL = '.claude/skills/add-driver/SKILL.md'


def _see(section):
    return f'— see {SKILL} §{section}'


# The family of every built-in driver — the grouping README, docs/config-format.md and CLAUDE.md use.
FAMILIES = {
    'system':       {'apt', 'dnf', 'pacman', 'zypper', 'apk', 'xbps', 'brew', 'aur', 'rpm-ostree'},
    'distribution': {'flatpak', 'snap', 'appImage', 'tarball', 'native-pkg-file', 'source', 'font',
                     'script'},
    'config':       {'dotfiles', 'glue'},
    'module':       {'cargo', 'pip', 'pipx', 'npm', 'gem', 'opam', 'luarocks', 'cabal', 'go-install',
                     'pyenv', 'sdkman'},
    'toolchain':    {'gcc', 'gcc-toolset', 'clang'},
    'primitive':    {'service', 'group'},
}

# Drivers deliberately NOT in DEFAULT_DRIVER_PREFERENCE: when several of these are valid for one
# component they tie, and the author settles it with a per-binding `standing:` rank (never a `when:`,
# which states validity only; routing-model §8a).
UNRANKED = {
    'rpm-ostree': 'atomic layering, a reboot-gated last resort — bindings carry standing: never-auto',
    'font': 'the only method for a font component; never competes',
    'dotfiles': 'a config companion, never an install method of the tool itself',
    'glue': 'a shell-glue companion, never an install method of the tool itself',
    'cargo': 'module installer: below every ranked method, author-ordered among peers',
    'pip': 'module installer', 'pipx': 'module installer', 'npm': 'module installer',
    'gem': 'module installer', 'opam': 'module installer', 'luarocks': 'module installer',
    'cabal': 'module installer', 'go-install': 'module installer', 'sdkman': 'module installer',
    'pyenv': 'a version-scoped interpreter provider, chosen by version selection',
    'gcc': 'versioned toolchain slot, chosen by version selection',
    'gcc-toolset': 'versioned toolchain slot (EL)', 'clang': 'versioned toolchain slot',
    'service': 'post-install primitive (a -service companion)',
    'group': 'post-install primitive (a -group companion)',
}

# Hooks a native manager should implement but one doesn't yet — a known, accepted gap (each degrades
# to the hook's default). Remove an entry when the hook lands; never add one to dodge the test.
KNOWN_GAPS = {}
# (e.g. ('zypper', 'explicit_keys'): 'why it can't be done yet' — the last one closed 2026-10-10)

# Code symbols the skill tells you to visit. Each must still exist AND be named in the skill.
TOUCHPOINTS = [
    ('configsys.drivers', 'BUILTIN_DRIVERS'),
    ('configsys.drivers', 'register_driver'),
    ('configsys.drivers._native', 'NativePkgManager'),
    ('configsys.driver', 'UPDATE_TIERS'),
    ('configsys.resolve', 'DEFAULT_DRIVER_PREFERENCE'),
    ('configsys.resolve', 'gated_context'),
    ('configsys.resolve', '_package'),
    ('configsys.routes', '_VIA_ATTR'),
    ('configsys.routecheck', 'validate'),
    ('configsys.actions', 'targets_version'),
    ('configsys.actions', '_INTERNAL_SUDO_DRIVERS'),
    ('configsys.actions', '_NO_POST_CHECK'),
    ('configsys.ledger', '_NO_RECEIPT'),
    ('configsys.stranded', '_SKIP_VIAS'),
    ('configsys.orphans', 'USER_FACING'),
    ('configsys.sysupdates', '_APP_MANAGERS'),
    ('configsys.rebootcheck', '_REBOOT_CHECKS'),
    ('configsys.rebootcheck', '_NO_REBOOT_CHECK'),
    ('tools.namesweep', 'MANAGERS'),
    ('tools.namesweep', 'UNSWEPT'),
    ('configsys.app', '_NATIVE_REFRESH'),
    ('configsys.app', '_FULL_UPGRADE_REFRESH'),
    ('configsys.app', '_INDEX_SRC_DIRS'),
    ('configsys.installState', 'InstallState'),
    ('configsys.versions', '_BUILTIN_KINDS'),
    ('configsys.plugins', '_scan_executable_data'),
    ('configsys.tui.menu', '_DRIVER_ABBR'),
]


def _word(name, text):
    '''`name` as a whole driver name — so `gcc` doesn't match inside `gcc-toolset`.'''
    return re.search(rf'(?<![\w-]){re.escape(name)}(?![\w-])', text) is not None


def _between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def _read(rel):
    return (ROOT / rel).read_text()


@pytest.fixture(scope='module')
def native_managers():
    from configsys.routes import Resolver
    r = Resolver(str(ROOT / 'routes.hu'), 'pop_os!', '22.04', 'x86_64')
    return {b['native'] for b in r.cascade.blocks.values() if isinstance(b, dict) and b.get('native')}


# -- classification ---------------------------------------------------------------------------------

def test_every_builtin_driver_has_exactly_one_family():
    named = [d for fam in FAMILIES.values() for d in fam]
    assert len(named) == len(set(named)), 'a driver is in two families'
    assert set(named) == set(BUILTIN_DRIVERS), (
        f'unclassified: {sorted(set(BUILTIN_DRIVERS) - set(named))}; gone: '
        f'{sorted(set(named) - set(BUILTIN_DRIVERS))} {_see("1")}')


def test_every_driver_is_ranked_or_deliberately_unranked(native_managers):
    ranked = set(DEFAULT_DRIVER_PREFERENCE) - {'native'}
    assert ranked <= set(BUILTIN_DRIVERS), f'preference names no driver: {ranked - set(BUILTIN_DRIVERS)}'
    assert not ranked & set(UNRANKED), f'both ranked and UNRANKED: {ranked & set(UNRANKED)}'
    loose = set(BUILTIN_DRIVERS) - ranked - native_managers - set(UNRANKED)
    assert not loose, f'neither in DEFAULT_DRIVER_PREFERENCE nor UNRANKED: {sorted(loose)} {_see("3")}'
    assert not set(UNRANKED) - set(BUILTIN_DRIVERS)


def test_every_ranked_driver_has_a_tui_abbreviation():
    from configsys.tui.menu import _DRIVER_ABBR
    missing = [d for d in DEFAULT_DRIVER_PREFERENCE if d not in _DRIVER_ABBR]
    assert not missing, f'_DRIVER_ABBR lacks {missing} {_see("3")}'
    assert len(set(_DRIVER_ABBR.values())) == len(_DRIVER_ABBR), 'duplicate abbreviation'


def test_routes_drivers_block_names_only_registered_drivers():
    from configsys.routes import Resolver
    r = Resolver(str(ROOT / 'routes.hu'), 'pop_os!', '22.04', 'x86_64')
    assert set(r.drivers) <= set(BUILTIN_DRIVERS), sorted(set(r.drivers) - set(BUILTIN_DRIVERS))


# -- native package managers ------------------------------------------------------------------------

def test_known_gaps_are_still_gaps():
    fixed = [k for k in KNOWN_GAPS if getattr(_REGISTRY[k[0]], k[1]) is not getattr(Driver, k[1])]
    assert not fixed, f'implemented now — remove from KNOWN_GAPS: {fixed}'


def test_native_managers_are_wired_everywhere_a_manager_must_be(native_managers):
    from configsys import app, rebootcheck
    import tools.namesweep as namesweep
    assert native_managers <= FAMILIES['system']
    swept = {m for m, _b, _v in namesweep.MANAGERS}
    for pm in sorted(native_managers):
        cls = _REGISTRY[pm]
        for hook in ('installed_index', 'upgradable_index', 'upgrade_all', 'explicit_keys'):
            assert getattr(cls, hook) is not getattr(Driver, hook) or (pm, hook) in KNOWN_GAPS, \
                f'{pm} lacks {hook} {_see("4")}'
        styles = [m for m in ('_NATIVE_REFRESH', '_FULL_UPGRADE_REFRESH') if pm in getattr(app, m)]
        assert len(styles) == 1, f'{pm} must declare exactly one refresh style, has {styles} {_see("4")}'
        reboot = [m for m in ('_REBOOT_CHECKS', '_NO_REBOOT_CHECK') if pm in getattr(rebootcheck, m)]
        assert len(reboot) == 1, f'{pm} must declare exactly one reboot entry, has {reboot} {_see("4")}'
        sweep = [m for m, names in (('MANAGERS', swept), ('UNSWEPT', namesweep.UNSWEPT)) if pm in names]
        assert len(sweep) == 1, f'{pm} must be in exactly one of namesweep {sweep or "MANAGERS/UNSWEPT"} {_see("4")}'
        if pm in swept:
            assert pm in namesweep._CHECK and pm in namesweep._VERIFIERS, \
                f'{pm} is swept but has no namesweep _CHECK/_VERIFIERS container {_see("4")}'
            ver = next(v for m, _b, v in namesweep.MANAGERS if m == pm)
            assert not ver or '{ver}' in namesweep._VERIFIERS[pm][0], \
                f'{pm}: names resolve for {ver} — tag its verifier image with {{ver}} {_see("4")}'


# -- docs and skills enumerate every driver ---------------------------------------------------------

def _all_named(text, where):
    missing = sorted(d for d in BUILTIN_DRIVERS if not _word(d, text))
    assert not missing, f'{where} does not name {missing} {_see("6")}'


def test_readme_concepts_names_every_driver_and_the_count():
    # README's hand-written Concepts bullet (the generated Glossary entry enumerates nothing)
    entry = _between(_read('README.md'), '**Driver**', '**Unit**')
    _all_named(entry, 'README Concepts "Driver" bullet (edit README.md)')
    m = re.search(r'ships (\d+)', entry)
    assert m and int(m.group(1)) == len(BUILTIN_DRIVERS), \
        f'README says "ships {m and m.group(1)}", the registry has {len(BUILTIN_DRIVERS)} {_see("6")}'


def test_claude_md_names_every_driver():
    _all_named(_between(_read('CLAUDE.md'), 'Drivers are defined in code', '(playbook: `/add-driver`'),
               'CLAUDE.md driver paragraph')


def test_config_format_names_every_driver():
    _all_named(_between(_read('docs/config-format.md'), 'the OS package managers:', 'Plugins may add drivers'),
               'docs/config-format.md driver list')


def test_add_component_catalog_names_every_driver():
    _all_named(_between(_read('.claude/skills/add-component/SKILL.md'), '## Driver catalog', '## `version:`'),
               'add-component Driver catalog')


def test_scope_honoring_list_matches_the_code():
    line = _between(_read('docs/config-format.md'), '**`scope:`** `user` or `system`', 'ignore it')
    documented = {d for d in BUILTIN_DRIVERS if _word(d, line.split('Other drivers')[0])}
    honoring = {n for n, c in _REGISTRY.items() if c.honors_scope}
    assert documented == honoring, f'docs/config-format.md scope list vs honors_scope {_see("2")}'


def test_targets_version_list_in_claude_md_matches_the_code():
    seg = _between(_read('CLAUDE.md'), 'targets_version = False` (', '`actions.targets_version`')
    documented = {d for d in BUILTIN_DRIVERS if _word(d, seg)}
    refused = {n for n, c in _REGISTRY.items() if not c.targets_version}
    assert documented == refused, \
        f'CLAUDE.md set-version list: missing {sorted(refused - documented)}, extra {sorted(documented - refused)} {_see("2")}'


def test_orphan_scan_list_matches_installed_index_overrides():
    seg = _between(_read('docs/orphans.md'), 'Today that means', 'wherever present')
    documented = {d for d in BUILTIN_DRIVERS if _word(d, seg)}
    enumerating = {n for n, c in _REGISTRY.items() if c.installed_index is not Driver.installed_index}
    assert documented == enumerating, \
        f'docs/orphans.md scanned drivers: missing {sorted(enumerating - documented)}, extra {sorted(documented - enumerating)} {_see("2")}'


# -- tests and skill freshness ----------------------------------------------------------------------

def test_every_driver_has_a_test():
    texts = [p.read_text() for p in (ROOT / 'test').glob('test_*.py') if p.name != Path(__file__).name]
    untested = []
    for name, cls in _REGISTRY.items():
        if name not in BUILTIN_DRIVERS:
            continue
        mod = cls.__module__.rsplit('.', 1)[-1]
        pat = re.compile(rf"configsys\.drivers\.{mod}\b|configsys\.drivers import [^\n]*\b{cls.__name__}\b"
                         rf"|get_driver\(\s*['\"]{re.escape(name)}['\"]")
        if not any(pat.search(t) for t in texts):
            untested.append(name)
    assert not untested, f'no test exercises {untested} {_see("5")}'


@pytest.mark.parametrize('module,symbol', TOUCHPOINTS)
def test_skill_touchpoints_exist_and_are_named(module, symbol):
    assert hasattr(importlib.import_module(module), symbol), \
        f'{module}.{symbol} is gone — update {SKILL} and TOUCHPOINTS'
    assert symbol in _read(SKILL), f'{SKILL} does not mention {symbol}'
