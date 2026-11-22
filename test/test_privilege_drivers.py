'''Drivers name root through the runner's escalator (privilege.py): a step a command string runs as
root reads `sudo …` under sudo, `doas …` under doas, and bare as root — through ONE helper
(`privilege.as_root`, the Driver's `as_root`), and a source recipe's `$SUDO` expands to the same.'''

import pytest

from configsys.drivers.apt import Apt, commit_source
from configsys.paths import Paths
from configsys.privilege import AlreadyRoot, Doas, Sudo
from configsys.componentObj import ResolvedComponent
from configsys.runner import Runner

from fakes import FakeRunner


def _rc(driver, comp, **fields):
    return ResolvedComponent(key=f'{driver}\\{comp}', driver=driver, comp=comp,
                             fields={'name': comp, **fields})


def test_the_driver_helper_reads_the_runners_escalator():
    from configsys.driver import Driver
    assert Driver(Runner(pretend=True, escalator=Sudo())).as_root == 'sudo'
    assert Driver(Runner(pretend=True, escalator=Doas())).as_root == 'doas'
    assert Driver(Runner(pretend=True, escalator=AlreadyRoot())).as_root == ''
    assert Driver(FakeRunner()).as_root == 'sudo'                  # a stand-in runner: as recorded


def test_fake_runner_records_its_escalators_form():
    fr = FakeRunner(escalator=Doas())
    fr.run('apk add x', sudo=True)
    assert fr.calls == ['doas apk add x']


def test_apt_vendor_key_and_source_under_doas():
    comp = _rc('apt', 'thing', **{'pubkey-url': 'https://ex.com/key.asc',
                                  'pubkey-path': '/etc/apt/trusted.gpg.d/ex.asc',
                                  'source-url': 'https://ex.com/ex.list',
                                  'source-path': '/etc/apt/sources.list.d/ex.list'})
    r = Runner(pretend=True, escalator=Doas())
    Apt(r).install(comp)
    assert r.calls == [
        '[ -f /etc/apt/trusted.gpg.d/ex.asc ] || '
        'doas curl -fsSL https://ex.com/key.asc -o /etc/apt/trusted.gpg.d/ex.asc',
        'test -f /etc/apt/sources.list.d/ex.list',
        'if [ ! -f /etc/apt/sources.list.d/ex.list ]; then '
        'doas curl -fsSL https://ex.com/ex.list -o /etc/apt/sources.list.d/ex.list '
        '&& doas apt-get update; fi',
        'doas DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y thing']


def test_apt_rollback_and_rekey_under_doas():
    # the validate-then-commit rollback (a new source broke apt-get update) escalates through doas
    fr = FakeRunner([('test -f', 1, ''), ('WRITE', 1, ''),
                     ('apt-get update', 100, 'E: NO_PUBKEY ABCDEF0123456789')],
                    escalator=Doas())
    fail = commit_source(fr, 'WRITE', '/etc/apt/sources.list.d/x.list',
                         'https://ex.com/k.asc', '/usr/share/keyrings/x.asc')
    assert fail is not None
    assert 'doas apt-get update' in fr.calls
    assert 'doas curl -fsSL https://ex.com/k.asc -o /usr/share/keyrings/x.asc' in fr.calls
    assert 'doas rm -f /etc/apt/sources.list.d/x.list' in fr.calls
    assert not [c for c in fr.calls if 'sudo' in c]


def test_dnf_repo_write_and_rollback_under_doas():
    from configsys.drivers.dnf import Dnf
    fr = FakeRunner([('test -f', 1, ''), ('makecache', 1, 'Curl error (6)')], escalator=Doas())
    assert Dnf(fr)._commit_repo('[x]\nname=x\n', 'x') is not None
    assert any(c.endswith('| doas tee /etc/yum.repos.d/x.repo >/dev/null') for c in fr.calls)
    assert 'doas rm -f /etc/yum.repos.d/x.repo' in fr.calls
    assert not [c for c in fr.calls if 'sudo' in c]


@pytest.mark.parametrize('esc, want', [(Sudo(), 'sudo make install'),
                                       (Doas(), 'doas make install'),
                                       (AlreadyRoot(), ' make install')])
def test_a_source_recipes_sudo_names_the_escalator(tmp_path, esc, want):
    from configsys.drivers.source import Source
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    r = Runner(pretend=True, escalator=esc)
    rc = _rc('source', 'dwm', repo='https://x/dwm', scope='system',
             build='make && $SUDO make install && echo "$SUDO_USER"')
    Source(r, paths=paths).install(rc)
    cmd = r.calls[-1]
    assert f'&& {want} &&' in cmd
    assert '"$SUDO_USER"' in cmd                     # a longer name that starts $SUDO is left alone
    word = esc.word
    assert (f'|| {word} mkdir -p /usr/local' if word else '||  mkdir -p /usr/local') in cmd


def test_a_user_scope_recipes_sudo_is_empty_under_any_escalator(tmp_path):
    from configsys.drivers.source import Source
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})
    r = Runner(pretend=True, escalator=Doas())
    Source(r, paths=paths).install(_rc('source', 'dwm', repo='https://x/dwm', build='$SUDO make install'))
    assert 'doas' not in r.calls[-1] and ' make install' in r.calls[-1]


def test_gem_system_set_version_runs_in_one_root_shell():
    # the whole command already runs as root (sudo=True): no inner escalation — under doas an inner
    # `doas` as root may not even be permitted
    from configsys.drivers.gem import Gem
    for esc in (Sudo(), Doas()):
        r = Runner(pretend=True, escalator=esc)
        Gem(r).set_version(_rc('gem', 'rubocop', scope='system'), '1.50.0')
        cmd = r.calls[-1]
        assert cmd.startswith(f'{esc.word} gem install ')
        assert 'do gem uninstall -x -v "$o" rubocop' in cmd and cmd.count(esc.word) == 1


def test_group_targets_the_invoking_user_under_each_escalator():
    from configsys.drivers.group import Group
    for esc, user in ((Sudo(), '"${SUDO_USER:-$USER}"'), (Doas(), '"${DOAS_USER:-$USER}"'),
                      (AlreadyRoot(), '"$USER"')):
        r = Runner(pretend=True, escalator=esc)
        grp = Group(r)
        rc = _rc('group', 'docker-group', name='docker')
        grp.install(rc)
        grp.uninstall(rc)
        assert f'usermod -aG docker {user}' in r.calls[0]
        assert f'gpasswd -d {user} docker' in r.calls[1]
