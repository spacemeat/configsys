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
import shlex
from pathlib import Path

# Base directory for bare-relative install paths under system scope.
SYSTEM_PREFIX = Path('/opt')


class Driver:
    name = None             # subclasses set, e.g. 'apt'
    privileged = False      # True if mutating ops need sudo
    default_scope = 'user'  # this driver's scope when not overridden
    honors_scope = False    # True if user/system is selectable (flatpak, tarball, ...)
    # Optional per-inspect BATCH context: InstallState.inspect pre-computes a driver's enumerable
    # probe data ONCE (via the driver's `batch_index(names)`) and sets it here on each per-unit
    # instance, so read ops (get_version/get_latest/is_locked) can answer from it instead of a
    # subprocess per unit. None = no batch available -> the per-unit fallback path runs. Opaque:
    # only the driver that produced it reads it.
    _batch = None

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

    def _offline(self):
        '''--pretend must be side-effect-free, network reads included: version discovery goes
        cache-only (never touches the network) when the runner is pretending.'''
        return bool(getattr(self.runner, 'pretend', False))

    def resolve_version(self, rc, *, refresh=False):
        '''The version to install / treat as latest. A `version:` dict is a discovery
        spec (github / url / static); a string is a literal; otherwise None (undiscoverable).'''
        spec = self._disco_spec(rc)
        if isinstance(spec, dict):
            from . import versions
            return versions.discover(spec, self.paths, refresh=refresh, offline=self._offline())
        if isinstance(spec, str) and spec:
            return spec
        return None

    def download_url(self, rc, version):
        '''Preferred download URL: a matched github release asset (authoritative,
        rename-robust) if the version spec has an `asset` glob, else the route `url`
        template with $VERSION/$ARCH filled in.'''
        spec = self._disco_spec(rc)
        if isinstance(spec, dict):
            from . import versions
            asset = versions.discover_asset_url(spec, self.paths, offline=self._offline())
            if asset:
                return asset
            # API-free fallback for a LITERAL github asset name (no glob): the releases/latest/
            # download URL. Robust when api.github.com is unreachable, and lets --pretend show a
            # real URL without a network call.
            gh, name = spec.get('github'), spec.get('asset')
            if gh and isinstance(name, str) and '*' not in name:
                return f'https://github.com/{gh}/releases/latest/download/{name}'
        return self._apply_placeholders(rc.fields.get('url'), version)

    # -- archive acquisition (shared by tarball [binary] and source [build]) ---

    def _extract_cmd(self, url, tmp_q, dest_q, archive_fmt=None, strip=None):
        '''Shell fragment to unpack a downloaded archive (already-quoted `tmp_q`) into `dest_q`:
        `.zip` -> `unzip`, else `tar -xf` (auto-detects gz/xz/bz2). `archive_fmt` can force it
        ('zip'); `strip` (tar only) drops N leading path components — a source tarball's
        `foo-1.2.3/` wrapper dir.'''
        fmt = str(archive_fmt or '').lower()
        if fmt == 'zip' or (not fmt and url.lower().split('?', 1)[0].endswith('.zip')):
            return f'unzip -o -q {tmp_q} -d {dest_q}'
        s = f'--strip-components={int(strip)} ' if strip else ''
        return f'tar -xf {tmp_q} {s}-C {dest_q}'

    def _fetch_and_extract(self, url, dest, archive_fmt=None, strip=None):
        '''Shell fragment shared by the tarball (binary) and source (build) drivers: create
        `dest`, curl the archive into a temp file there, unpack it, remove the temp. Needs curl
        (the binding/driver `requires: curl`).'''
        dq = shlex.quote(str(dest))
        tmp = shlex.quote(str(Path(dest) / '.configsys-download.archive'))
        return (f'mkdir -p {dq} && curl -fSL {shlex.quote(url)} -o {tmp} && '
                f'{self._extract_cmd(url, tmp, dq, archive_fmt, strip)} && rm -f {tmp}')

    def location_override(self, rc):
        '''The per-component install-location override for this unit, or None. Set from the config
        `locations:` map (component -> path) and injected onto the unit as the reserved
        `location-override` field (a distinct key — `location` is already an authored DISPLAY field
        on the source/script drivers). An ABSOLUTE, scope-bypassing path: "find/manage this
        component's install HERE", regardless of the binding's `dir`/`installDir` and the scope
        layout. Path-based drivers prefer it over their computed target; package drivers ignore it.'''
        loc = rc.fields.get('location-override')
        return Path(str(loc)).expanduser() if loc else None

    def scoped_dir(self, raw, rc):
        '''Resolve an install path via the Paths layout (single source of truth): the
        $CONFIGSYS_*_DIR category vars are substituted, then absolute/`~` passes through and a
        bare-relative path resolves under the scope base (CONFIGSYS_USERSCOPE_DIR / SYSTEMSCOPE_DIR,
        defaults ~ and /opt). The paths=None branch is the old inline behavior for unit tests that
        pass explicit absolute dirs (no env/vars).'''
        if self.paths is not None:
            return self.paths.install_dir(raw, self._scope(rc))
        s = str(raw)
        if s.startswith(('/', '~')):
            return Path(s).expanduser()
        base = SYSTEM_PREFIX if self._scope(rc) == 'system' else Path.home()
        return base / s

    # -- read (inspection) ------------------------------------------------

    def get_version(self, rc):
        '''Installed version string, or None if not installed.'''
        raise NotImplementedError('get_version')

    def get_installed(self, rc):
        '''(version, scope) where this unit is ACTUALLY installed, or (None, None) if it isn't.
        The reality-based counterpart to scope(rc) (which is the TARGET the config asks for). The
        default assumes a single fixed scope (default_scope): installed there iff get_version
        finds it. Scope-honoring drivers override — path-based ones via _installed_across_scopes
        (so a scope mismatch never reads as "missing"), flatpak via its own per-installation
        probe. inspect() shows the detected scope when installed, the target scope otherwise.'''
        v = self.get_version(rc)
        return (v, self.default_scope) if v is not None else (None, None)

    def _installed_across_scopes(self, rc):
        '''Probe user then system by re-deriving this driver's scoped paths; return (version,
        scope) from wherever the unit is found, else (None, None). For path-based honors_scope
        drivers (tarball / appImage / font). Restores rc's `scope` field afterward.'''
        had, saved = 'scope' in rc.fields, rc.fields.get('scope')
        try:
            for s in ('user', 'system'):
                rc.fields['scope'] = s
                v = self.get_version(rc)
                if v is not None:
                    return (v, s)
            return (None, None)
        finally:
            if had:
                rc.fields['scope'] = saved
            else:
                rc.fields.pop('scope', None)

    def installed_index(self):
        '''For a package-manager driver: {package_key: version} of EVERYTHING it currently has
        installed, from ONE enumeration call — so the coexistence detector can check many components
        with a single subprocess instead of one probe per component. None = not enumerable
        (path/build drivers): the detector falls back to their fast per-method get_version. Returns
        None on command failure too (fall back rather than claim nothing is installed).'''
        return None

    def index_key(self, rc):
        '''The key under which this unit would appear in installed_index() — the same handle
        get_version looks up. Default: the resolved package name (rc.name). Drivers whose install
        identity isn't rc.name (flatpak app id, snap name) override.'''
        return rc.name

    def explicit_keys(self):
        '''The set of installed_index keys the user EXPLICITLY installed (manual / on-request), as
        opposed to those pulled in automatically as dependencies — or None when this driver draws no
        such distinction (then callers treat every installed key as explicit). Native managers
        override (apt-mark showmanual, pacman -Qe, dnf --userinstalled, brew leaves). Lets the orphan
        scan ignore the thousands of dependency packages nobody chose. None on command failure too.'''
        return None

    def origin_index(self):
        '''{package_key: origin_tier} classifying how fundamental each installed package is to the OS
        — apt Priority (`required`/`important`/`standard`/`optional`/`extra`), or a comparable
        per-manager notion. None when the driver has no such concept. The orphan scan carries the tier
        on every foreign orphan (so the data is never lost) and, for now, hides the base tiers
        (required/important/standard) unless asked — a user CAN still choose to manage even systemd.'''
        return None

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

    def reconcile_scope(self, rc, detected, target):
        '''Make the install match the DECLARED scope: it's at `detected`, config says `target`.
        Default = correctness-first REINSTALL: bring it up at `target`, then remove the old copy
        at `detected` — install-new BEFORE uninstall-old, so a failed step never leaves nothing
        installed, and each driver's own install/uninstall keeps desktop entries / markers / sudo
        / symlinks correct. This is safe wherever uninstall touches only the component's own files
        (or refcounts, like flatpak). A driver with a cheap in-place MOVE (a large build tree, a
        font dir) overrides this to avoid a needless reinstall. Returns a runner Result.'''
        had, saved = 'scope' in rc.fields, rc.fields.get('scope')
        try:
            rc.fields['scope'] = target
            r_new = self.install(rc)
            if not r_new.ok:
                return r_new                          # abort; the old copy is untouched
            rc.fields['scope'] = detected
            r_old = self.uninstall(rc)
            return r_new if r_old.ok else r_old
        finally:
            if had:
                rc.fields['scope'] = saved
            else:
                rc.fields.pop('scope', None)

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
