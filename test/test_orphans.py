'''Managed-orphans scan: classify installed software no active profile accounts for into
excluded / lurking / forgotten / foreign (see docs/managed-orphans-plan.md). The classification is
unit-tested against a hand-built Config; the full scan is exercised against a real routes context
with a fabricated installed-index cache (so it's deterministic — no real subprocess enumeration).'''

import pytest

from configsys import layers, orphans as O
from configsys.config import Config
from configsys.app import Context, build_parser


# ---- pure classification -------------------------------------------------------------------------

REPO = '''{
    configs: [ dev ]
    profiles: {
        base:  [ htop  bat ]
        dev:   [ +base  ~bat ]
        media: [ ncdu ]
    }
}'''


def _cfg(text=REPO):
    return Config([layers.Layer('config.hu', 'repo', layers.materialize_string(text))])


def _inputs(cfg):
    requested = set(cfg.requested())
    active = list(cfg.active_profiles)
    removed = set()
    for p in active:
        removed |= set(cfg.profile_removed(p))
    return requested, active, removed


def test_requested_component_is_not_an_orphan():
    cfg = _cfg()
    req, act, rem = _inputs(cfg)
    # htop is pulled by the active dev profile (via +base) -> managed, not an orphan
    assert O._classify_known(cfg, 'htop', req, act, rem) is None


def test_excluded_when_actively_tilde_removed():
    cfg = _cfg()
    req, act, rem = _inputs(cfg)
    # bat is in dev's closure but dev `~bat`s it -> the loudest kind
    assert O._classify_known(cfg, 'bat', req, act, rem) == 'excluded'


def test_lurking_when_in_an_inactive_profile():
    cfg = _cfg()
    req, act, rem = _inputs(cfg)
    # ncdu lives in `media`, which isn't active
    assert O._classify_known(cfg, 'ncdu', req, act, rem) == 'lurking'


def test_forgotten_when_in_no_profile_at_all():
    cfg = _cfg()
    req, act, rem = _inputs(cfg)
    assert O._classify_known(cfg, 'nowhere-tool', req, act, rem) == 'forgotten'


def test_removed_closure_catches_transitive_exclusion():
    # ripgrep is `~`'d out one level down (inside ext-langs, which with-sub includes) — the direct
    # profile_removed misses it; the closure catches it.
    cfg = _cfg('''{
        configs: [ with-sub ]
        profiles: {
            base-langs: [ htop  ripgrep ]
            ext-langs:  [ +base-langs  ~ripgrep ]
            with-sub:   [ +ext-langs  ncdu ]
        }
    }''')
    assert cfg.profile_removed('with-sub') == set()               # direct: nothing
    assert cfg.profile_removed_closure('with-sub') == {'ripgrep'}  # closure: caught


def test_removed_closure_does_not_leak_a_tilded_out_subprofiles_internal_removals():
    # P excludes B wholesale; B's OWN internal `~x` must NOT count as excluded-from-P (B isn't in P).
    cfg = _cfg('''{
        configs: [ p ]
        profiles: {
            leaf: [ x  y ]
            b:    [ +leaf  ~x ]
            a:    [ +b  z ]
            p:    [ +a  ~b ]
        }
    }''')
    closure = cfg.profile_removed_closure('p')
    assert 'x' not in closure          # x's only tie to P was via B, which P prunes -> not excluded
    assert 'y' in closure              # ~b drops b's net members ({y}), which IS an exclusion by P


def test_transitive_exclusion_classifies_as_excluded(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text('''{
      configs: [ with-sub ]
      profiles: {
        base-langs: [ htop  ripgrep ]
        ext-langs:  [ +base-langs  ~ripgrep ]
        with-sub:   [ +ext-langs  ncdu ]
      }
    }''')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    units, rindex, cache, explicit, origins = _scan(ctx)
    cache['apt'] = {_aptkey(rindex, 'ripgrep'): '14.1.0', _aptkey(rindex, 'ncdu'): '1.16'}
    found = {o.component: o for o in O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)}
    assert found['ripgrep'].kind == 'excluded'     # was 'lurking' before the closure fix
    assert 'ncdu' not in found                       # a net member of the active profile


def test_excluded_outranks_lurking():
    # a component both `~`'d out of the active profile AND sitting in an inactive one -> excluded wins
    cfg = _cfg('''{
        configs: [ dev ]
        profiles: {
            base:  [ htop  bat ]
            dev:   [ +base  ~bat ]
            shelf: [ bat ]
        }
    }''')
    req, act, rem = _inputs(cfg)
    assert O._classify_known(cfg, 'bat', req, act, rem) == 'excluded'


# ---- ignore + summary helpers --------------------------------------------------------------------

def test_is_ignored_matches_component_or_key():
    globs = ['bat', 'com.example.*']
    assert O._is_ignored(globs, 'bat', 'bat')                 # by component name
    assert O._is_ignored(globs, '', 'com.example.Thing')      # by key (foreign, no component)
    assert not O._is_ignored(globs, 'htop', 'htop')


def test_scanned_summary_counts_by_axis():
    orphans = [
        O.Orphan('apt', 'bat', '1', 'bat', 'excluded'),
        O.Orphan('apt', 'ncdu', '1', 'ncdu', 'lurking'),
        O.Orphan('flatpak', 'com.x.Y', '1', '', 'foreign'),
        O.Orphan('apt', 'q', '1', 'q', 'forgotten', ignored=True),
    ]
    assert O.scanned_summary(orphans) == (2, 1, 1)            # known, foreign, ignored


# ---- full scan against a real routes context, deterministic cache --------------------------------

USER_CFG = '''{
  configs: [ dev ]
  profiles: {
    base:  [ htop  bat ]
    dev:   [ +base  ~bat ]
    media: [ ncdu ]
  }
}'''


def _ctx(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text(USER_CFG)
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def _scan(ctx, apt=None, flatpak=None):
    '''Scan inputs with caches that FULLY cover every driver the scan would touch — installed-index
    all None ("nothing installed / not enumerable") except fabricated ones, and explicit_keys all
    None ("no manual/auto distinction, list all") and origins all {} ("no tier info") so neither the
    manual filter nor the priority lookup runs a real subprocess.
    Returns (units, rindex, cache, explicit, origins); tests override the pieces they care about.'''
    units, _ = ctx.routes.resolve_resilient(list(ctx.config.requested()))
    rindex = O.build_reverse_index(ctx)
    scan_drivers = ({rc.driver for rc in units.values()}
                    | {dn for (dn, _k) in rindex} | set(O.USER_FACING))
    cache = {dn: None for dn in scan_drivers}
    explicit = {dn: None for dn in scan_drivers}
    origins = {dn: {} for dn in scan_drivers}      # {} = no tier info -> deterministic, no dpkg-query
    if apt is not None:
        cache['apt'] = apt
    if flatpak is not None:
        cache['flatpak'] = flatpak
    return units, rindex, cache, explicit, origins


def _aptkey(rindex, comp):
    return next(k for (dn, k), cs in rindex.items() if dn == 'apt' and comp in cs)


def test_scan_classifies_real_components(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx)
    kb, kh, kn = (_aptkey(rindex, c) for c in ('bat', 'htop', 'ncdu'))
    cache['apt'] = {kb: '0.24', kh: '3.0.6', kn: '1.16', 'libdep-noise': '1.0'}
    found = {o.component: o for o in O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)}
    assert found['bat'].kind == 'excluded'
    assert found['ncdu'].kind == 'lurking'
    assert 'htop' not in found                        # active profile wants it -> not an orphan
    assert found['bat'].version == '0.24'


def test_native_foreign_dropped_by_default_shown_with_flag(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx)
    cache['apt'] = {'libdep-noise': '1.0'}            # matches no recipe, native manager
    default = O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)
    assert not any(o.key == 'libdep-noise' for o in default)
    opted = O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins, include_foreign_native=True)
    got = next(o for o in opted if o.key == 'libdep-noise')
    assert got.kind == 'foreign' and got.component == ''


def test_foreign_flatpak_listed_by_default(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx, flatpak={'com.example.Unknown': '1.0'})
    found = O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)
    got = next(o for o in found if o.key == 'com.example.Unknown')
    assert got.kind == 'foreign' and got.driver == 'flatpak'


def test_explicit_filter_hides_auto_installed_packages(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx)
    kb, kn = _aptkey(rindex, 'bat'), _aptkey(rindex, 'ncdu')
    cache['apt'] = {kb: '0.24', kn: '1.16', 'libdep': '1.0'}
    # only bat was user-installed; ncdu + libdep came in as dependencies
    explicit['apt'] = {kb}

    default = {o.component or o.key: o for o in
               O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)}
    assert 'bat' in default                          # a chosen package -> kept
    assert 'ncdu' not in default                     # an auto-installed dep -> hidden

    everything = {o.component or o.key: o for o in
                  O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins, include_auto=True)}
    assert {'bat', 'ncdu'} <= set(everything)        # --include-auto brings the dep back


def test_driver_without_manual_distinction_lists_all(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx)
    cache['apt'] = {_aptkey(rindex, 'ncdu'): '1.16'}
    # explicit is all-None here -> "no manual/auto notion", nothing is filtered
    found = O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins)
    assert any(o.component == 'ncdu' for o in found)


def test_foreign_tier_tagged_and_base_hidden_by_default(tmp_path):
    ctx = _ctx(tmp_path)
    units, rindex, cache, explicit, origins = _scan(ctx)
    # four recipe-less apt packages spanning the priority tiers
    cache['apt'] = {'myapp': '1', 'bash': '5', 'apt': '2', 'cron': '3'}
    origins['apt'] = {'myapp': 'optional', 'bash': 'required', 'apt': 'important', 'cron': 'standard'}

    default = {o.key: o for o in O.scan_orphans(
        ctx, units, cache=cache, explicit=explicit, origins=origins, include_foreign_native=True)}
    assert set(default) == {'myapp'}                 # only the optional one survives the base filter
    assert default['myapp'].tier == 'optional'       # tier rides along on the orphan

    full = {o.key: o for o in O.scan_orphans(
        ctx, units, cache=cache, explicit=explicit, origins=origins,
        include_foreign_native=True, include_system=True)}
    assert set(full) == {'myapp', 'bash', 'apt', 'cron'}         # --system reveals the base tiers
    assert full['bash'].tier == 'required' and full['cron'].tier == 'standard'


def test_apt_origin_index_parse():
    from configsys.drivers.apt import Apt

    class _R:
        ok = True
        stdout = 'bash required\nmyapp optional\napt important\n'

    class _Runner:
        def run(self, *a, **k):
            return _R()
    assert Apt(_Runner(), None).origin_index() == {
        'bash': 'required', 'myapp': 'optional', 'apt': 'important'}


def test_index_pairs_cross_indexes_native_backed_under_manager():
    from types import SimpleNamespace

    class _Drv:
        def __init__(self, nb): self.native_backed = nb
        def index_key(self, rc): return rc.name

    # a clang-N unit: its package lands in apt's DB, so it occupies BOTH slots
    rc = SimpleNamespace(driver='clang', fields={'packages': ['clang-18']}, name='clang-18')
    assert O._index_pairs(rc, _Drv(True), 'apt') == {('clang', 'clang-18'), ('apt', 'clang-18')}
    # a plain driver (cargo) occupies only its own slot
    rc2 = SimpleNamespace(driver='cargo', fields={}, name='ripgrep')
    assert O._index_pairs(rc2, _Drv(False), 'apt') == {('cargo', 'ripgrep')}


def test_reverse_index_recognizes_native_backed_and_alt_names():
    import os
    from types import SimpleNamespace
    from configsys.routes import Resolver
    from configsys.runner import Runner

    routes = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
    r = Resolver(routes, 'pop_os!', '22.04', 'x86_64')   # a versioned context (7zip gate needs it)
    ctx = SimpleNamespace(routes=r, runner=Runner(pretend=True), paths=None)
    ri = O.build_reverse_index(ctx)
    # clang installs clang-18 into apt -> recognized under (apt, clang-18)
    assert ri.get(('apt', 'clang-18')) == ['clang-18']
    # both the modern `7zip` name AND the legacy `p7zip-full` map to the one component
    assert ri.get(('apt', '7zip')) == ['p7zip']
    assert ri.get(('apt', 'p7zip-full')) == ['p7zip']
    # rust: `installed-name: cargo` makes the split-out cargo package recognized (rust-all is a meta)
    assert ri.get(('apt', 'cargo')) == ['rust']
    # krita: a real native binding (was flatpak-only off Alpine) -> the apt package is recognized
    assert ri.get(('apt', 'krita')) == ['krita']


def test_apt_explicit_keys_parse():
    from configsys.drivers.apt import Apt

    class _R:
        ok = True
        stdout = 'htop\nbat\n\n  ripgrep  \n'

    class _Runner:
        def run(self, *a, **k):
            return _R()
    assert Apt(_Runner(), None).explicit_keys() == {'htop', 'bat', 'ripgrep'}


IGNORE_CFG = '''{
  configs: [ dev ]
  orphans-ignore: [ bat ]
  profiles: { base: [ htop  bat ]  dev: [ +base  ~bat ]  media: [ ncdu ] }
}'''


def test_ignore_glob_stamps_without_dropping(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text(IGNORE_CFG)
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    assert ctx.config.orphans_ignore() == ['bat']     # the machine-setting reader picks it up

    units, rindex, cache, explicit, origins = _scan(ctx)
    cache['apt'] = {_aptkey(rindex, 'bat'): '0.24'}
    bat = next(o for o in O.scan_orphans(ctx, units, cache=cache, explicit=explicit, origins=origins) if o.component == 'bat')
    assert bat.ignored is True and bat.kind == 'excluded'   # kept in the list, just flagged
