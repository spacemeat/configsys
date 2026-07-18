'''The service (systemd) and group (usermod) drivers — post-install primitives — and the
docker composition that uses them (docker = parts[engine, service]; docker-group opt-in).'''

import os

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.group import Group
from configsys.drivers.service import Service
from configsys.routes import Resolver
from configsys.runner import Result, Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


class Fake:
    '''A runner stub that returns a fixed exit code (for read-op parsing).'''
    def __init__(self, code):
        self.code = code

    def run(self, cmd, **kw):
        return Result(cmd, self.code)


def _rc(driver, comp, **fields):
    return ResolvedComponent(key=f'{driver}\\{comp}', driver=driver, comp=comp, fields=fields)


def test_both_registered_and_system_scope():
    assert isinstance(get_driver('service', Runner(pretend=True)), Service)
    assert isinstance(get_driver('group', Runner(pretend=True)), Group)
    assert Service(Runner(pretend=True)).scope(_rc('service', 'x')) == 'system'
    assert Group(Runner(pretend=True)).scope(_rc('group', 'x')) == 'system'
    assert not Service(Runner(pretend=True)).honors_scope


# -- service -------------------------------------------------------------

def test_service_enable_and_disable_commands():
    r = Runner(pretend=True)
    svc = Service(r)
    rc = _rc('service', 'docker-service', unit='docker')
    svc.install(rc)
    svc.uninstall(rc)
    assert r.calls[0].startswith('sudo ')
    assert 'systemctl enable --now docker' in r.calls[0]
    assert 'no systemd here' in r.calls[0]                       # graceful degrade branch
    assert 'systemctl disable --now docker' in r.calls[1]


def test_service_start_false_enables_only():
    r = Runner(pretend=True)
    Service(r).install(_rc('service', 'x', unit='foo', start=False))
    assert 'systemctl enable foo' in r.calls[0] and '--now' not in r.calls[0]


def test_service_get_version_reflects_is_enabled():
    rc = _rc('service', 'docker-service', unit='docker')
    assert Service(Fake(0)).get_version(rc) == 'enabled'
    assert Service(Fake(1)).get_version(rc) is None
    assert Service(Runner(pretend=True)).location(rc) == 'systemd unit: docker'


# -- group ---------------------------------------------------------------

def test_group_add_and_remove_commands():
    r = Runner(pretend=True)
    grp = Group(r)
    rc = _rc('group', 'docker-group', name='docker')
    grp.install(rc)
    grp.uninstall(rc)
    assert 'usermod -aG docker "${SUDO_USER:-$USER}"' in r.calls[0]
    assert 'log out/in' in r.calls[0]                            # relogin note
    assert 'gpasswd -d "${SUDO_USER:-$USER}" docker' in r.calls[1]


def test_group_get_version_reflects_membership():
    rc = _rc('group', 'docker-group', name='docker')
    assert Group(Fake(0)).get_version(rc) == 'member'
    assert Group(Fake(1)).get_version(rc) is None


# -- docker composition --------------------------------------------------

def test_docker_resolves_to_engine_plus_service():
    units = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['docker'])
    assert set(units) == {'apt\\docker-engine', 'service\\docker-service'}
    assert units['apt\\docker-engine'].name == 'docker.io'          # name-mapped from docker
    assert units['service\\docker-service'].fields['unit'] == 'docker'


def test_docker_engine_name_maps_per_manager():
    assert Resolver(ROUTES, 'fedora', '41').resolve_names(['docker'])['dnf\\docker-engine'].name == 'moby-engine'
    assert Resolver(ROUTES, 'arch', '20260101').resolve_names(['docker'])['pacman\\docker-engine'].name == 'docker'


def test_docker_group_is_opt_in_and_pulls_the_engine():
    # naming docker-group brings the engine (so the group exists) + the membership
    units = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['docker-group'])
    assert set(units) == {'apt\\docker-engine', 'group\\docker-group'}
    assert units['group\\docker-group'].name == 'docker'
