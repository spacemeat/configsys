'''driver.py — the base Driver interface (the core of the plugin ABI).

A Driver knows how to operate on the components routed to it (apt, flatpak, ...).
Every driver implements the same op set so the app can drive any component
uniformly. Ops take a ResolvedComponent and go through the injected Runner (so
--pretend and tests work everywhere). Read ops return data; mutating ops return a
runner.Result.

This class IS the contract a code plugin subclasses. A plugin's code module imports
`from configsys.plugins import Driver` and lists its subclasses in a module-level
`DRIVERS = [SubclassOfDriver, ...]` export; the trusted loader registers each (a
plugin may also call `register_driver` directly for dynamic cases). The frozen,
ABI-stable surface (stable within a given plugins.ABI_VERSION) is:

  Class attributes to set : name, privileged, default_scope, honors_scope
  Ops to implement        : get_version, get_latest, is_locked, install, uninstall,
                            upgrade, set_version, lock, unlock
  Overridable (optional)  : location(rc), scope(rc)
  Helpers a subclass MAY call, in two clusters:
    resolve + fetch an artifact : resolve_version(rc, *, refresh=False),
                                  download_url(rc, version), arch()
    install location/privilege  : scoped_dir(raw, rc), sudo(rc), scope(rc),
                                  display_path(p)
  Injection : __init__(runner, paths) — runner.run(cmd, *, sudo=False, capture=True)
              -> Result(.ok/.returncode/.stdout) (also importable from configsys.plugins);
              paths.home/.env/.expand(p)/...

Underscore members (_scope, _apply_placeholders, _disco_spec) are internal and may
change without an ABI bump — subclasses must not rely on them.
'''


import platform
from pathlib import Path

# Base directory for bare-relative install paths under system scope.
SYSTEM_PREFIX = Path('/opt')


class Driver:
    name = None             # subclasses set, e.g. 'apt'
    privileged = False      # True if mutating ops need sudo
    default_scope = 'user'  # this driver's scope when not overridden
    honors_scope = False    # True if user/system is selectable (flatpak, tarball, ...)

    def __init__(self, runner, paths=None):
        self.runner = runner
        self.paths = paths   # for drivers that touch the filesystem (tarball, ...)

    # -- scope helpers (shared by scope-aware drivers) -------------------

    def scope(self, rc):
        '''The scope this component installs to, for display. Scope-honoring
        drivers take a route/config override; the rest have a fixed scope (apt is
        always system; cargo/dotfiles are per-user).'''
        if self.honors_scope:
            return rc.fields.get('scope') or self.default_scope
        return self.default_scope

    def _scope(self, rc):
        '''Effective install scope for a component (field wins; else driver default).'''
        return rc.fields.get('scope') or self.default_scope

    def sudo(self, rc):
        '''System scope needs root for its mutations; user scope never does.'''
        return self._scope(rc) == 'system'

    # -- version resolution (download-based drivers) ---------------------

    def arch(self):
        '''System CPU arch for $ARCH substitution (e.g. x86_64, aarch64). Naming
        conventions differ per project, so some URLs still need hand-tuning.'''
        env = self.paths.env if self.paths is not None else {}
        return env.get('CONFIGSYS_ARCH') or platform.machine()

    def _apply_placeholders(self, text, version):
        if not text:
            return text
        if version:
            text = text.replace('$VERSION', version)
        return text.replace('$ARCH', self.arch())

    def _disco_spec(self, rc):
        '''The version spec with $ARCH substituted into an `asset` glob (so the
        cache key and asset match are arch-correct).'''
        spec = rc.fields.get('version')
        if isinstance(spec, dict) and 'asset' in spec:
            spec = dict(spec)
            spec['asset'] = spec['asset'].replace('$ARCH', self.arch())
        return spec

    def resolve_version(self, rc, *, refresh=False):
        '''The version to install / treat as latest. A `version:` dict is a discovery
        spec (github / url / static); a string is a literal; otherwise fall back to a
        legacy $VERSION route var. Returns None if undiscoverable.'''
        spec = self._disco_spec(rc)
        if isinstance(spec, dict):
            from . import versions
            return versions.discover(spec, self.paths, refresh=refresh)
        if isinstance(spec, str) and spec:
            return spec
        return rc.vars.get('$VERSION') or rc.vars.get('$SDKVERSION')

    def download_url(self, rc, version):
        '''Preferred download URL: a matched github release asset (authoritative,
        rename-robust) if the version spec has an `asset` glob, else the route `url`
        template with $VERSION/$ARCH filled in.'''
        spec = self._disco_spec(rc)
        if isinstance(spec, dict):
            from . import versions
            asset = versions.discover_asset_url(spec, self.paths)
            if asset:
                return asset
        return self._apply_placeholders(rc.fields.get('url'), version)

    def scoped_dir(self, raw, rc):
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

    # -- presentation -----------------------------------------------------

    def location(self, rc):
        '''Human-readable install location (where files go / would go), or None for
        package-managed drivers with no single path (apt). Shown in the TUI infoblock.'''
        return None

    def display_path(self, p):
        '''Collapse HOME to ~ for readable display.'''
        s = str(p)
        home = str(self.paths.home) if self.paths is not None else str(Path.home())
        return '~' + s[len(home):] if home and s.startswith(home) else s
