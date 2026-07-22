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

def test_registry_resolves_apt_and_rejects_others():
    assert isinstance(get_driver('apt', Runner(pretend=True)), Apt)
    assert get_driver('snap', Runner(pretend=True)) is None   # not implemented
    assert is_supported('apt') and not is_supported('snap')


def test_install_command():
    r = Runner(pretend=True)
    Apt(r).install(rc())
    assert r.calls == ['sudo apt-get install -y btop']


def test_uninstall_command():
    r = Runner(pretend=True)
    Apt(r).uninstall(rc())
    assert r.calls == ['sudo apt-get remove -y btop']


def test_upgrade_command():
    r = Runner(pretend=True)
    Apt(r).upgrade(rc())
    assert r.calls == ['sudo apt-get install --only-upgrade -y btop']


def test_set_version_command():
    r = Runner(pretend=True)
    Apt(r).set_version(rc(), '1.2.3-1')
    assert r.calls == ['sudo apt-get install -y --allow-downgrades btop=1.2.3-1']


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
    assert r.calls == ['sudo apt-get install -y vulkan-sdk']


# -- output parsing (via FakeRunner) -------------------------------------

def test_get_version_installed():
    fr = FakeRunner([('dpkg-query', 0, '1.2.13-1\n')])
    assert Apt(fr).get_version(rc()) == '1.2.13-1'


def test_get_version_not_installed():
    fr = FakeRunner([('dpkg-query', 1, '')])
    assert Apt(fr).get_version(rc()) is None


def test_get_version_multiarch_takes_one_row():
    # a multiarch package (amd64 + i386, once i386 is enabled for Steam) prints one row
    # per instance; without this we'd concatenate them into a doubled, never-matching
    # version and the component would show as perpetually "outdated".
    fr = FakeRunner([('dpkg-query', 0, '1.3.280.0-1\n1.3.280.0-1\n')])
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
    assert len(units) == 1
    return next(iter(units.values()))


def test_repo_component_enabled_before_install():
    comp = ResolvedComponent(key='apt\\btop', driver='apt', comp='btop',
                             fields={'name': 'btop', 'repo-component': 'universe'})
    r = Runner(pretend=True)
    Apt(r).install(comp)
    assert r.calls == [
        'sudo add-apt-repository -y universe',
        'sudo apt-get install -y btop',
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
    assert r.calls[-1] == 'sudo apt-get install -y x'


def test_universe_route_carries_repo_component():
    # routes.hu declares btop needs universe (per "encode prereqs in routes.hu")
    unit = resolve_unit('btop')
    assert unit.fields.get('repo-component') == 'universe'
    r = Runner(pretend=True)
    Apt(r).install(unit)
    assert r.calls == [
        'sudo add-apt-repository -y universe',
        'sudo apt-get install -y btop',
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
    assert r.calls == [key_cmd, src_cmd, 'sudo apt-get install -y thing']


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
    assert r.calls[-1] == 'sudo apt-get install -y code'
    src_cmd = ("if [ ! -f /etc/apt/sources.list.d/vscode.list ]; then echo 'deb "
               '[signed-by=/usr/share/keyrings/packages.microsoft.asc] '
               "https://packages.microsoft.com/repos/code stable main' "
               '| sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null '
               '&& sudo apt-get update; fi')
    assert src_cmd in r.calls


def test_no_prereqs_when_none_declared():
    r = Runner(pretend=True)
    Apt(r).install(rc('build-essential'))  # main package, no repo-component
    assert r.calls == ['sudo apt-get install -y build-essential']


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
    assert r.calls == [preseed, 'sudo apt-get install -y wireshark']


def test_wireshark_route_carries_debconf_preseed():
    # the preseed rides on wireshark's single native binding; on apt it enables non-root
    # capture, on dnf/pacman the field is simply ignored (they set dumpcap's caps in-package).
    unit = resolve_unit('wireshark')   # pop_os! -> apt
    assert unit.fields.get('debconf') == \
        'wireshark-common wireshark-common/install-setuid boolean true'
