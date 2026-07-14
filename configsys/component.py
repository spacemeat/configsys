'''component.py — the base Family interface.

A Family knows how to operate on the components routed to it (apt, flatpak, ...).
Every family implements the same op set so the app can drive any component
uniformly. Ops take a ResolvedComponent and go through the injected Runner (so
--pretend and tests work everywhere). Read ops return data; mutating ops return a
runner.Result.
'''


class Family:
    name = None          # subclasses set, e.g. 'apt'
    privileged = False   # True if mutating ops need sudo

    def __init__(self, runner):
        self.runner = runner

    # -- read (inspection) ------------------------------------------------

    def get_version(self, rc):
        '''Installed version string, or None if not installed.'''
        raise NotImplementedError('get_version')

    def get_latest(self, rc):
        '''Latest/candidate available version string, or None if unknown.'''
        raise NotImplementedError('get_latest')

    def is_locked(self, rc):
        '''True if the component is version-locked by the native mechanism.'''
        raise NotImplementedError('is_locked')

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        raise NotImplementedError('install')

    def uninstall(self, rc):
        raise NotImplementedError('uninstall')

    def upgrade(self, rc):
        raise NotImplementedError('upgrade')

    def set_version(self, rc, version):
        raise NotImplementedError('set_version')

    def lock(self, rc):
        raise NotImplementedError('lock')

    def unlock(self, rc):
        raise NotImplementedError('unlock')
