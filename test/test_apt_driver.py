from pathlib import Path

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.apt import Apt
from configsys.routes import Resolver
from configsys.runner import Result, Runner
from configsys.troveio import load


def rc(name='btop'):
    return ResolvedComponent(key=f'apt\\{name}', driver='apt', comp=name,
                             fields={'name': name})


class FakeRunner:
    '''Records commands and returns canned Results matched by substring.'''

    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


# -- command construction (via pretend Runner) ---------------------------

def test_installed_index_keys_bare_and_arch_qualified():
    # A foreign-arch package (Steam's steam:i386) is reported by dpkg with ${Package} BARE
    # ('steam'), but a route may name it 'steam:i386'. The batched index must carry BOTH keys, or
    # the startup scan reports an installed multiarch package as "missing".
    # rows are `${db:Status-Status} ${Package} ${Architecture} ${Version}`; a `config-files` row is a
    # removed-but-not-purged package (conffiles remain) — it must NOT count as installed.
    dpkg_out = ('installed curl amd64 8.5.0-2\n'
                'installed steam i386 1:1.0.0.78\n'
                'installed steam-installer amd64 1:1.0.0.78\n'
                'installed libvulkan1 amd64 1.3.0\n'
                'installed libvulkan1 i386 1.3.0\n'
                'config-files nano amd64 7.2-1\n')
    apt = Apt(FakeRunner([("dpkg-query -W", 0, dpkg_out)]))
    idx = apt.installed_index()
    assert idx.get('steam') == '1:1.0.0.78'          # bare name (dpkg's ${Package})
    assert idx.get('steam:i386') == '1:1.0.0.78'     # arch-qualified — the route's name
    assert idx.get('curl') == '8.5.0-2' and idx.get('curl:amd64') == '8.5.0-2'
    assert idx.get('libvulkan1:i386') == '1.3.0'     # both multiarch instances addressable
    assert 'nano' not in idx and 'nano:amd64' not in idx   # removed (config-files) -> not installed


def test_installed_name_probes_a_different_package_than_install():
    # A metapackage (libreoffice) is commonly ABSENT while the suite is installed via its parts
    # (-core/-calc/...). `installed-name` probes libreoffice-core for state while `name` still
    # drives install/remove — so batched detection reports it installed, not missing.
    lo = ResolvedComponent(key='apt\\libreoffice', driver='apt', comp='libreoffice',
                           fields={'name': 'libreoffice', 'installed-name': 'libreoffice-core'})
    fr = FakeRunner([
        ('dpkg-query', 0, 'installed libreoffice-core amd64 1:7.3.7\ninstalled libreoffice-calc amd64 1:7.3.7\n'),  # NO bare `libreoffice`
        ('apt-cache policy', 0, 'libreoffice-core:\n  Installed: 1:7.3.7\n  Candidate: 1:7.3.7\n'),
        ('apt-mark showhold', 0, ''),
    ])
    apt = Apt(fr)
    apt._batch = apt.batch_index([lo])
    assert apt.get_version(lo) == '1:7.3.7'        # detected via libreoffice-core (meta is absent)
    assert apt.get_latest(lo) == '1:7.3.7'
    # mutation still targets the install name (the meta)
    Apt(Runner(pretend=True)).install(lo)          # would `apt-get install -y libreoffice` (name, not -core)


def test_registry_resolves_apt_and_rejects_others():
    assert isinstance(get_driver('apt', Runner(pretend=True)), Apt)
    assert get_driver('nosuchvia', Runner(pretend=True)) is None   # not implemented
    assert is_supported('apt') and not is_supported('nosuchvia')


def test_install_command():
    r = Runner(pretend=True)
    Apt(r).install(rc())
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y btop']


def test_uninstall_command():
    r = Runner(pretend=True)
    Apt(r).uninstall(rc())
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get remove -y btop']


def test_upgrade_command():
    r = Runner(pretend=True)
    Apt(r).upgrade(rc())
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install --only-upgrade -y btop']


def test_set_version_command():
    r = Runner(pretend=True)
    Apt(r).set_version(rc(), '1.2.3-1')
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y --allow-downgrades btop=1.2.3-1']


def test_lock_unlock_commands():
    r = Runner(pretend=True)
    Apt(r).lock(rc())
    Apt(r).unlock(rc())
    assert r.calls == ['sudo apt-mark hold btop', 'sudo apt-mark unhold btop']


def test_uses_family_name_field_not_comp():
    # e.g. vulkan-dev -> apt\vulkan-sdk: the apt package is the `name` field.
    comp = ResolvedComponent(key='apt\\vulkan-sdk', driver='apt', comp='vulkan-sdk',
                             fields={'name': 'vulkan-sdk'})
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y vulkan-sdk']


# -- output parsing (via FakeRunner) -------------------------------------

def test_get_version_installed():
    fr = FakeRunner([('dpkg-query', 0, 'installed 1.2.13-1\n')])
    assert Apt(fr).get_version(rc()) == '1.2.13-1'


def test_get_version_not_installed():
    fr = FakeRunner([('dpkg-query', 1, '')])
    assert Apt(fr).get_version(rc()) is None


def test_get_version_ignores_removed_config_files_state():
    # `apt-get remove` (not purge) leaves a `config-files` row that dpkg-query still answers with a
    # version — it must read as NOT installed, not as the stale removed version.
    fr = FakeRunner([('dpkg-query', 0, 'config-files 1.2.13-1\n')])
    assert Apt(fr).get_version(rc()) is None


def test_get_version_multiarch_takes_one_row():
    # a multiarch package (amd64 + i386, once i386 is enabled for Steam) prints one row
    # per instance; without this we'd concatenate them into a doubled, never-matching
    # version and the component would show as perpetually "outdated".
    fr = FakeRunner([('dpkg-query', 0, 'installed 1.3.280.0-1\ninstalled 1.3.280.0-1\n')])
    assert Apt(fr).get_version(rc()) == '1.3.280.0-1'


def test_get_latest_candidate():
    policy = ('btop:\n  Installed: (none)\n  Candidate: 1.2.13-1\n'
              '  Version table:\n     1.2.13-1 500\n')
    fr = FakeRunner([('apt-cache policy', 0, policy)])
    assert Apt(fr).get_latest(rc()) == '1.2.13-1'


def test_get_latest_none():
    policy = 'btop:\n  Installed: (none)\n  Candidate: (none)\n'
    fr = FakeRunner([('apt-cache policy', 0, policy)])
    assert Apt(fr).get_latest(rc()) is None


def test_is_locked_true_and_false():
    held = FakeRunner([('apt-mark showhold', 0, 'btop\nripgrep\n')])
    assert Apt(held).is_locked(rc('btop')) is True
    assert Apt(held).is_locked(rc('fzf')) is False


# -- prerequisites -------------------------------------------------------

def resolve_unit(name, os_block='pop_os!'):
    routes = Path(__file__).resolve().parent.parent / 'routes.hu'
    units = Resolver(routes, os_block).resolve_names([name])
    # the component may now softly `suggests:` a <name>-dotfiles companion (which itself
    # pulls bash-dotfiles); select the unit for the requested component itself.
    matches = [u for u in units.values() if u.comp == name]
    assert len(matches) == 1
    return matches[0]


def test_repo_component_enabled_before_install():
    comp = ResolvedComponent(key='apt\\btop', driver='apt', comp='btop',
                             fields={'name': 'btop', 'repo-component': 'universe'})
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls == [
        'sudo add-apt-repository -y universe',
        'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y btop',
    ]


def test_repo_component_list():
    comp = ResolvedComponent(key='apt\\x', driver='apt', comp='x',
                             fields={'name': 'x', 'repo-component': ['universe', 'multiverse']})
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls[:2] == [
        'sudo add-apt-repository -y universe',
        'sudo add-apt-repository -y multiverse',
    ]
    assert r.calls[-1] == 'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y x'


def test_universe_route_carries_repo_component():
    # routes.hu declares btop needs universe (per "encode prereqs in routes.hu")
    unit = resolve_unit('btop')
    assert unit.fields.get('repo-component') == 'universe'
    r = Runner(pretend=True)
    Apt(r).install(unit)
    assert r.calls == [
        'sudo add-apt-repository -y universe',
        'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y btop',
    ]


def test_apt_key_and_source_prereq_still_supported():
    # The apt third-party key/source mechanism is retained for other components,
    # even though vulkan-sdk itself moved to the tarball driver.
    comp = ResolvedComponent(key='apt\\thing', driver='apt', comp='thing', fields={
        'name': 'thing',
        'pubkey-url': 'https://ex.com/key.asc',
        'pubkey-path': '/etc/apt/trusted.gpg.d/ex.asc',
        'source-url': 'https://ex.com/ex.list',
        'source-path': '/etc/apt/sources.list.d/ex.list',
    })
    r = Runner(pretend=True)
    Apt(r).install(comp)
    key_cmd = ('[ -f /etc/apt/trusted.gpg.d/ex.asc ] || '
               'sudo curl -fsSL https://ex.com/key.asc -o /etc/apt/trusted.gpg.d/ex.asc')
    src_cmd = ('if [ ! -f /etc/apt/sources.list.d/ex.list ]; then '
               'sudo curl -fsSL https://ex.com/ex.list -o /etc/apt/sources.list.d/ex.list '
               '&& sudo apt-get update; fi')
    # the source write now goes through _commit_source (validate-then-commit): a `test -f`
    # existence probe precedes the write so a NEWLY-created broken source can be rolled back.
    assert r.calls == [key_cmd, 'test -f /etc/apt/sources.list.d/ex.list', src_cmd,
                       'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y thing']


def test_source_line_writes_inline_deb_repo():
    # vendor repos with no downloadable .list (e.g. Microsoft's vscode) echo a deb line.
    comp = ResolvedComponent(key='apt\\code', driver='apt', comp='vscode', fields={
        'name': 'code',
        'pubkey-url': 'https://packages.microsoft.com/keys/microsoft.asc',
        'pubkey-path': '/usr/share/keyrings/packages.microsoft.asc',
        'source-line': 'deb [signed-by=/usr/share/keyrings/packages.microsoft.asc] '
                       'https://packages.microsoft.com/repos/code stable main',
        'source-path': '/etc/apt/sources.list.d/vscode.list',
    })
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls[-1] == 'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y code'
    src_cmd = ("if [ ! -f /etc/apt/sources.list.d/vscode.list ]; then echo 'deb "
               '[signed-by=/usr/share/keyrings/packages.microsoft.asc] '
               "https://packages.microsoft.com/repos/code stable main' "
               '| sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null '
               '&& sudo apt-get update; fi')
    assert src_cmd in r.calls


class SeqRunner:
    '''Runner whose responses depend on prior calls — for the validate-then-commit flow, where the
    same `apt-get update` is issued more than once and must answer differently each time.'''

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, **kw):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        code, out = self.handler(cmd, self)
        return Result(full, code, stdout=out)

    def echo(self, msg):
        pass


def _vendor_comp():
    return ResolvedComponent(key='apt\\unityhub', driver='apt', comp='unityhub', fields={
        'name': 'unityhub',
        'source-line': 'deb [signed-by=/x.asc] https://hub.unity3d.com/linux/repos/deb stable main',
        'source-path': '/etc/apt/sources.list.d/unityhub.list'})


def test_commit_source_restores_when_a_preexisting_source_is_the_culprit():
    # apt-get update fails, but NOT because of our source (a pre-existing broken source elsewhere —
    # "E: The list of sources could not be read" names nothing). _commit_source re-checks with ours
    # disabled, sees it STILL fail, restores our valid source, and reports the pre-existing breakage.
    def handler(cmd, r):
        if cmd.startswith('test -f'):
            return 1, ''                                       # not existed -> we created it this run
        if 'rm -f' in cmd:
            return 0, ''
        if 'apt-get update' in cmd:
            return 100, 'E: The list of sources could not be read.'   # ALWAYS fails (unrelated)
        return 0, ''                                           # tee/write succeeds
    r = SeqRunner(handler)
    res = Apt(r).ensure_prereqs(_vendor_comp())
    assert res is not None and not res.ok
    assert 'pre-existing apt source' in res.output
    assert 'not on /etc/apt/sources.list.d/unityhub.list' in res.output
    assert 'source rolled back' not in res.output               # ours was NOT blamed
    # our source was RESTORED: a tee to the source path runs AFTER the rm
    seen_rm = restored = False
    for c in r.calls:
        if 'rm -f' in c:
            seen_rm = True
        elif seen_rm and 'tee /etc/apt/sources.list.d/unityhub.list' in c:
            restored = True
    assert restored


def test_commit_source_rolls_back_when_our_source_is_the_culprit():
    # apt-get update fails, and re-checking WITHOUT our source SUCCEEDS -> ours was the poison pill.
    state = {'removed': False}

    def handler(cmd, r):
        if cmd.startswith('test -f'):
            return 1, ''
        if 'rm -f' in cmd:
            state['removed'] = True
            return 0, ''
        if 'apt-get update' in cmd:
            return (0, '') if state['removed'] else (100, 'E: repository malformed (our repo)')
        return 0, ''
    r = SeqRunner(handler)
    res = Apt(r).ensure_prereqs(_vendor_comp())
    assert res is not None and not res.ok
    assert 'source rolled back' in res.output                   # ours WAS the culprit
    assert 'pre-existing' not in res.output
    # and it stayed removed — no tee to the source path after the rm
    seen_rm = False
    for c in r.calls:
        if 'rm -f' in c:
            seen_rm = True
        elif seen_rm:
            assert 'tee /etc/apt/sources.list.d/unityhub.list' not in c


def test_no_prereqs_when_none_declared():
    r = Runner(pretend=True)
    Apt(r).install(rc('build-essential'))  # main package, no repo-component
    assert r.calls == ['sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y build-essential']


def test_debconf_preseed_before_install():
    # wireshark's non-root-capture setuid: preseed the answer, then (only if already
    # installed) dpkg-reconfigure so it applies now too — before the apt-get install.
    comp = ResolvedComponent(key='apt\\wireshark', driver='apt', comp='wireshark', fields={
        'name': 'wireshark',
        'debconf': 'wireshark-common wireshark-common/install-setuid boolean true',
    })
    r = Runner(pretend=True)
    Apt(r).install(comp)
    preseed = (
        "sudo echo 'wireshark-common wireshark-common/install-setuid boolean true' "
        "| debconf-set-selections && "
        "if dpkg-query -W -f='${Status}' wireshark-common 2>/dev/null "
        '| grep -q "install ok installed"; then '
        'DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive wireshark-common; fi'
    )
    assert r.calls == [preseed, 'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y wireshark']


def test_wireshark_route_carries_debconf_preseed():
    # the preseed rides on wireshark's single native binding; on apt it enables non-root
    # capture, on dnf/pacman the field is simply ignored (they set dumpcap's caps in-package).
    unit = resolve_unit('wireshark')   # pop_os! -> apt
    assert unit.fields.get('debconf') == \
        'wireshark-common wireshark-common/install-setuid boolean true'


def test_packages_field_installs_the_whole_set():
    # a `packages:` binding installs every listed package (opengl -> GL + GLU dev), not the component
    # name; installed-name governs detection separately.
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\opengl', driver='apt', comp='opengl',
                           fields={'packages': ['libgl1-mesa-dev', 'libglu1-mesa-dev'],
                                   'installed-name': 'libgl1-mesa-dev'})
    Apt(r).install(rc)
    assert r.calls[-1] == ('sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a '
                           'apt-get install -y libgl1-mesa-dev libglu1-mesa-dev')


def test_ppa_is_added_before_install():
    # a `ppa:` binding (deadsnakes for python3.12) runs add-apt-repository ppa:... before installing.
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\python3.12', driver='apt', comp='python3.12',
                           fields={'packages': ['python3.12', 'python3.12-venv'],
                                   'ppa': 'deadsnakes/ppa', 'requires': 'software-properties-common'})
    Apt(r).install(rc)
    assert r.calls[0] == 'sudo add-apt-repository -y ppa:deadsnakes/ppa'
    assert r.calls[-1].endswith('apt-get install -y python3.12 python3.12-venv')
