'''component.py — the base Family interface.

A Family knows how to operate on the components routed to it (apt, flatpak, ...).
Every family implements the same op set so the app can drive any component
uniformly. Ops take a ResolvedComponent and go through the injected Runner (so
--pretend and tests work everywhere). Read ops return data; mutating ops return a
runner.Result.
'''


from pathlib import Path

# Base directory for bare-relative install paths under system scope.
SYSTEM_PREFIX = Path('/opt')


class Family:
    name = None            # subclasses set, e.g. 'apt'
    privileged = False     # True if mutating ops need sudo
    default_scope = 'user'  # families that honor scope may override

    def __init__(self, runner, paths=None):
        self.runner = runner
        self.paths = paths   # for families that touch the filesystem (tarball, ...)

    # -- scope helpers (shared by scope-aware families) -------------------

    def _scope(self, rc):
        '''Effective install scope for a component (field wins; else family default).'''
        return rc.fields.get('scope') or self.default_scope

    def _sudo(self, rc):
        '''System scope needs root for its mutations; user scope never does.'''
        return self._scope(rc) == 'system'

    def _scoped_dir(self, raw, rc):
        '''Resolve an install path. Absolute and ~ paths pass through; a bare
        relative path (e.g. `vulkan`) resolves under HOME for user scope and under
        /opt for system scope.'''
        s = str(raw)
        if s.startswith(('/', '~')):
            return self.paths.expand(s) if self.paths is not None else Path(s).expanduser()
        base = SYSTEM_PREFIX if self._scope(rc) == 'system' else (
            self.paths.home if self.paths is not None else Path.home())
        return base / s

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
