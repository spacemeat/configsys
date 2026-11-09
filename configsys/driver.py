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
ABI-stable surface (stable within a given plugins.ABI_VERSION; docs/plugins.md §7, §7a) is:

  Class attributes to set : name, privileged, default_scope, honors_scope, targets_version
                            (False = set_version can't reach a requested version; the op
                            loop refuses set-version instead of calling it), holds_version
                            (False = a rolling manager that can't hold/downgrade), native_backed
                            (True = installs register in the OS package database),
                            trusted_registry + command_fields (True = a package BY NAME from a
                            registry the system already trusts, which an UNTRUSTED plugin layer may
                            route to unless it sets one of command_fields — trustgate.py; default
                            False: the driver runs, builds or downloads code, and an untrusted
                            plugin's bindings of it wait for `plugin trust`)
  Ops to implement        : get_version, get_latest, is_locked, install, uninstall,
                            upgrade, set_version, lock, unlock
  Overridable (optional)  : location(rc), scope(rc), get_installed(rc),
                            reconcile_scope(rc, detected, target)
  Optional hooks (each has a working default; override what your manager can answer):
    batched installed state : installed_index(), index_key(rc), batch_index(rcs),
                              batch_installed_index(batch), latest_index(names) (every candidate in
                              one query — the default batch_index carries it, with held_keys()) —
                              plus the `batch` attribute the core sets to batch_index's result
                              before the per-unit reads, and the batched_version(rc) /
                              batched_latest(rc) / batched_held(rc) helpers that read it
    orphan scan             : explicit_keys(), origin_index()
    System Updates          : upgradable_index(), update_dedup_key(key), held_keys(),
                              classify_index(keys) (tiers from UPDATE_TIERS), upgrade_all(), and
                              an optional upgradable_advisory() the core looks up with getattr
    version signals         : outdated_signal(rc), upstream_version(rc), and an optional
                              version_advisory(rc) the core looks up with getattr
  Helpers a subclass MAY call, in clusters:
    resolve + fetch an artifact : resolve_version(rc, *, refresh=False), version_spec(rc),
                                  download_url(rc, version), download_target(rc, version=None),
                                  upstream_version(rc), arch(), arch_token(rc),
                                  expected_sha256(rc, *keys), verify_download(rc, file_q, *keys),
                                  download_failure(rc, version) (the reason when there's no URL)
    install location/privilege  : scoped_dir(raw, rc), sudo(rc), scope(rc),
                                  location_override(rc), display_path(p), home(),
                                  toolchain_bindirs() (managed rust/go bin dirs, for a build PATH)
    install markers             : MARKER_PREFIX, marker_path(dir, rc, kind='version'),
                                  read_marker(path) (empty marker = 'installed', absent = None)
    command trust               : command_trusted(rc), untrusted_command_result(rc)
    files + names               : will_write(path) (call BEFORE writing into a content root — your
                                  primary plugin's tree; the write journal commits exactly that),
                                  installed_name(rc, driver=None) (a binding's `installed-name:`,
                                  scalar or driver-keyed map, for one manager)
  Injection : __init__(runner, paths) — runner.run(cmd, *, sudo=False, capture=True)
              -> Result(.ok/.returncode/.stdout) (also importable from configsys.plugins);
              paths.home/.env/.expand(p)/...

Underscore members (_scope, _apply_placeholders, _disco_spec, …) are internal and may
change without an ABI bump — subclasses must not rely on them.
'''


import os
import platform
import re
import shlex
from pathlib import Path

from .runner import Result

# Base directory for bare-relative install paths under system scope.
SYSTEM_PREFIX = Path('/opt')

# A resolved version must look like a version: start alphanumeric, then version punctuation only.
# Anything else (spaces, shell metacharacters) is refused before it can reach a shell — a tag name
# is network input, not author text. Covers v-prefixed, dotted, epoch (1:2.3), +build, ~pre forms.
# Public: the op loop checks an explicit `set-version` request against it too (actions.run_plan).
SAFE_VERSION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+~:-]*$')
_SAFE_VERSION_RE = SAFE_VERSION_RE

# Coarse, universal update tiers for the System Updates lane (docs/system-updates.md).
# A FIXED set so grouping stays consistent across managers; each driver maps its native notion (apt
# Priority, flatpak runtime/app split) into these via classify_index, degrading to a name heuristic
# where it has none. Ordered most-fundamental first — how the grouped CLI list reads top to bottom.
UPDATE_TIERS = ('kernel', 'core', 'standard', 'apps')

# The universal fallback: what a manager with no tier notion can still tell from a package name.
_KERNEL_NAME_RE = re.compile(r'^(linux-(image|headers|modules|generic|lowlatency|oem)|kernel|vmlinuz)')
_CORE_NAME_RE = re.compile(r'^(libc[0-9]?($|[.-])|glibc($|[.-])|musl($|[.-]))')


def tier_by_name(key):
    '''The update tier inferable from a package name alone — kernel (linux-image/kernel/…), core
    (libc/glibc/musl), else apps. The `fallback (any)` column of the tier table: what every manager
    can classify without a native priority notion.'''
    base = str(key).split('/', 1)[0]                 # tolerate a flatpak ref (id/arch/branch)
    if _KERNEL_NAME_RE.match(base):
        return 'kernel'
    if _CORE_NAME_RE.match(base):
        return 'core'
    return 'apps'


# How every release-asset download fetches (tarball, appImage, font, native-pkg-file, the shared
# _fetch_and_extract): curl's --retry retries only its transient answers — a timeout, HTTP 408/429/
# 5xx (GitHub's release redirect 504s in bursts) — never a 404, so a moved asset still fails at once.
_CURL_DOWNLOAD = 'curl -fSL --retry 3 --retry-delay 2'


# What configsys never `rm -rf`s (or moves over) as "a component's own directory", whatever a route,
# a plugin or `locations:` says (review-2026-11-2 A6, Driver.unsafe_dir_reason).
_SYSTEM_TREES = ('/usr', '/etc', '/var', '/boot', '/lib', '/lib32', '/lib64', '/bin', '/sbin',
                 '/dev', '/proc', '/sys', '/run', '/home', '/root', '/mnt', '/media', '/snap', '/nix')
_SHARED_NAMES = frozenset({'bin', 'sbin', 'lib', 'lib32', 'lib64', 'libexec', 'share', 'include',
                           'etc', 'man', 'src', 'games', 'var', 'local', 'state', 'cache', 'fonts',
                           'applications', 'icons'})
_HOME_SHARED = ('.local', '.local/bin', '.local/share', '.local/lib', '.local/state',
                '.local/share/fonts', '.local/share/applications', '.local/share/icons', '.config',
                '.cache', 'bin', 'Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Public',
                'Templates', 'Videos')



def strip_count(v):
    """A binding's `strip:` as a non-negative int, or None when it isn't one (`strip: one`)."""
    if isinstance(v, bool):
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        return None
    return n if n >= 0 else None

class Driver:
    name = None             # subclasses set, e.g. 'apt'
    # TRUST (docs/plugins.md §6, trustgate.py): `trusted_registry = True` marks a driver that installs a
    # package BY NAME from a registry the system already trusts (distro repos, Flathub, the Snap Store,
    # Homebrew core); an UNTRUSTED plugin layer may contribute its bindings unless one sets a field in
    # `command_fields` (adds a repo / key / remote, or widens privilege). Every other driver runs,
    # builds or downloads code, so its bindings from an untrusted layer wait for `plugin trust`.
    trusted_registry = False
    command_fields = frozenset()
    privileged = False      # True if mutating ops need sudo
    default_scope = 'user'  # this driver's scope when not overridden
    honors_scope = False    # True if user/system is selectable (flatpak, tarball, ...)
    # Optional per-inspect BATCH context: InstallState.inspect pre-computes a driver's enumerable
    # probe data ONCE (via the driver's `batch_index(names)`) and sets it here on each per-unit
    # instance, so read ops (get_version/get_latest/is_locked) can answer from it instead of a
    # subprocess per unit. None = no batch available -> the per-unit fallback path runs. Opaque:
    # only the driver that produced it reads it. Part of the frozen surface (a batching plugin
    # driver reads it, or calls batched_version).
    batch = None

    # Whether a specific version can be HELD or PINNED for this driver's packages — a native hold
    # (apt-mark/dnf versionlock/zypper addlock/brew pin), or a version configsys itself installs and
    # then declines to auto-upgrade (tarball/cargo/npm/…, where configsys IS the updater). FALSE for a
    # rolling manager whose repos carry only the current version AND whose OS updater runs out of band
    # (pacman -Syu / apk upgrade): there a "lock" can't be honored and set-version can't reach an old
    # version, so lock/set-version are DECLINED and the UI doesn't offer them — no surprises.
    holds_version = True

    # Whether set_version(rc, version) can install the REQUESTED version. False for a driver whose
    # artifact is fixed by its route (a version-templated tarball/AppImage/font/.deb url, a
    # package-fixed toolchain, the current AUR PKGBUILD) or that has no version at all (glue,
    # service, group): there set_version could only reinstall the routed version, so the op loop
    # REFUSES a set-version with a clear message instead of reporting a retarget that didn't happen.
    targets_version = True

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
        '''Effective install scope for a component — `scope(rc)`, the one truth: a `scope` field
        counts only on an honors_scope driver (drivers-os-14: a stray `scope: system` on a fixed-
        scope binding no longer flips sudo()/scoped_dir() while scope() ignores it).'''
        return self.scope(rc)

    def sudo(self, rc):
        '''System scope needs root for its mutations; user scope never does.'''
        return self._scope(rc) == 'system'

    # -- version resolution (download-based drivers) ---------------------

    def arch(self):
        '''System CPU arch for $ARCH substitution (e.g. x86_64, aarch64). Naming
        conventions differ per project, so some URLs still need hand-tuning.'''
        env = self.paths.env if self.paths is not None else {}
        return env.get('CONFIGSYS_ARCH') or platform.machine()

    def arch_token(self, rc=None):
        '''What `$ARCH` expands to for this unit: its binding's `cpu-names:` spelling of this cpu
        (amd64/arm64/x64…), else the raw cpu (x86_64/aarch64).'''
        from .resolve import arch_token
        return arch_token(rc.fields if rc is not None else None, self.arch())

    def _apply_placeholders(self, text, version, rc=None):
        if not text:
            return text
        if version:
            text = text.replace('$VERSION', version)
        return text.replace('$ARCH', self.arch_token(rc))

    def _disco_spec(self, rc):
        '''The version spec with $ARCH substituted into an `asset` glob (so the
        cache key and asset match are arch-correct).'''
        spec = rc.fields.get('version')
        if isinstance(spec, dict) and 'asset' in spec:
            spec = dict(spec)
            spec['asset'] = spec['asset'].replace('$ARCH', self.arch_token(rc))
        return spec

    def _offline(self):
        '''--pretend must be side-effect-free, network reads included: version discovery goes
        cache-only (never touches the network) when the runner is pretending.'''
        return bool(getattr(self.runner, 'pretend', False))

    def command_trusted(self, rc):
        '''Whether this binding's defining layer may run declared shell (via: script/source, a glue
        #!cs-eval). Core/user always; a plugin only if content-trusted. The command-carrying drivers
        gate their ops on this so untrusted plugin DATA can't achieve code execution — see
        plugins.command_source_trusted. No `paths` context (unit tests) = trusted.'''
        if self.paths is None:
            return True
        from . import plugins
        return plugins.command_source_trusted(self.paths, getattr(rc, 'source', '') or '')

    def untrusted_command_result(self, rc):
        '''The `Result.fail` a command-carrying driver returns when the binding is from an untrusted
        plugin — names the plugin and the `plugin trust` remedy.'''
        from . import plugins
        name = plugins.plugin_of_source(self.paths, getattr(rc, 'source', '') or '') if self.paths else None
        remedy = f'configsys plugin trust {name}' if name else 'configsys plugin trust <plugin>'
        return Result.fail(
            f'{rc.comp}: refusing to run {self.name} commands from the untrusted plugin '
            f'{name or "?"!r} — review it, then `{remedy}`', category='untrusted-plugin')

    def resolve_version(self, rc, *, refresh=False):
        '''The version to install / treat as latest. A `version:` dict is a discovery
        spec (github / url / static); a string is a literal; otherwise None (undiscoverable).

        SECURITY: a discovered version is often a git TAG NAME scraped from the network, and drivers
        splice it into shell commands (`$VERSION` in a source `build:`, download URLs). Tag/branch
        names may legally contain shell metacharacters, so a hostile/compromised upstream could turn
        a tag into a command. Reject any version outside a strict version charset here, at the one
        chokepoint every driver uses — an unsafe version reads as undiscoverable (a clean failure),
        never as injectable text.'''
        spec = self._disco_spec(rc)
        version = None
        if isinstance(spec, dict):
            from . import versions
            version = versions.discover(spec, self.paths, refresh=refresh, offline=self._offline())
        elif isinstance(spec, str) and spec:
            version = spec
        if version is not None and not _SAFE_VERSION_RE.match(version):
            return None
        return version

    def download_target(self, rc, version=None):
        '''(version, url) to install: download_url's URL plus the version it ACTUALLY fetches — record
        this one (e.g. in a version marker), not resolve_version's. A github `asset` glob is found in
        the latest release that carries it (api.github.com), which can differ from the tag-feed
        version resolve_version reports; recording the feed's then misreports the install (kotlin:
        a CI tag `build-2.4.21-RC-421` recorded over a downloaded 2.4.20). An explicit `version`
        (set_version) is kept as given.'''
        explicit = version is not None
        version = version if explicit else (self.resolve_version(rc) or '')
        if getattr(self.download_url, '__func__', None) is not Driver.download_url:
            return version, self.download_url(rc, version)   # a subclass's own URL logic wins
        spec = self._disco_spec(rc)
        if isinstance(spec, dict) and spec.get('github') and spec.get('asset'):
            from . import versions
            av, url = versions.discover_asset(spec, self.paths, refresh=not self._offline(),
                                              offline=self._offline())
            if url:
                if av and not explicit and _SAFE_VERSION_RE.match(av):
                    version = av
                return version, url
        return version, self._fallback_url(rc, spec, version)

    def download_url(self, rc, version):
        '''Preferred download URL: a matched github release asset (authoritative,
        rename-robust) if the version spec has an `asset` glob, else the route `url`
        template with $VERSION/$ARCH filled in.

        Resolves the asset FRESH (refresh, unless --pretend), NOT from the version cache. This is the
        install/upgrade download path (one component, a deliberate action), and the asset URL is
        cached with a lifetime INDEPENDENT of the version string — which comes from the anonymous atom
        feed and refreshes far more often. A stale cached asset URL would otherwise let get_latest
        report a new version (fresh, via the feed) while the download fetched the OLD release's file
        (e.g. insomnia: get_latest 13.3.0 but the cached .deb still 13.2.0 -> dpkg "already newest").
        Forcing a live asset lookup here keeps the downloaded file in lockstep with the claimed
        version, for every asset-download driver (native-pkg-file/tarball/appImage/font/source).'''
        spec = self._disco_spec(rc)
        if isinstance(spec, dict):
            from . import versions
            asset = versions.discover_asset_url(spec, self.paths, refresh=not self._offline(),
                                                offline=self._offline())
            if asset:
                return asset
        return self._fallback_url(rc, spec, version)

    def _fallback_url(self, rc, spec, version):
        '''The download URL when no asset was matched via the API.'''
        if isinstance(spec, dict):
            # API-free fallback for a LITERAL github asset name (no glob): the releases/latest/
            # download URL. Robust when api.github.com is unreachable, and lets --pretend show a
            # real URL without a network call.
            gh, name = spec.get('github'), spec.get('asset')
            if gh and isinstance(name, str) and '*' not in name:
                return f'https://github.com/{gh}/releases/latest/download/{name}'
        url = self._apply_placeholders(rc.fields.get('url'), version, rc)
        if url and '$VERSION' in url:
            # the version couldn't be discovered (network/throttling, nothing cached): no URL, so the
            # driver fails saying so — not a download of a literal `$VERSION` path that 404s
            return None
        return url

    # -- archive acquisition (shared by tarball [binary] and source [build]) ---

    def _extract_cmd(self, url, tmp_q, dest_q, archive_fmt=None, strip=None):
        '''Shell fragment to unpack a downloaded archive (already-quoted `tmp_q`) into `dest_q`:
        `.zip` -> `unzip`, else `tar -xf` (auto-detects gz/xz/bz2). `archive_fmt` can force it
        ('zip'); `strip` (tar only) drops N leading path components — a source tarball's
        `foo-1.2.3/` wrapper dir.'''
        fmt = str(archive_fmt or '').lower()
        if fmt == 'zip' or (not fmt and url.lower().split('?', 1)[0].endswith('.zip')):
            return f'unzip -o -q {tmp_q} -d {dest_q}'
        if strip:
            n = strip_count(strip)
            if n is None:          # a bad `strip:` fails THIS step with a reason, never a traceback (B14)
                return (f'{{ echo {shlex.quote(f"configsys: `strip: {strip}` is not a whole number")} >&2; '
                        'false; }')
            s = f'--strip-components={n} '
        else:
            s = ''
        return f'tar -xf {tmp_q} {s}-C {dest_q}'

    def _fetch_and_extract(self, url, dest, archive_fmt=None, strip=None, rc=None):
        '''Shell fragment shared by the tarball (binary) and source (build) drivers: create
        `dest`, curl the archive into a temp file there, verify it against the binding's `sha256:`
        (when `rc` declares one), unpack it, remove the temp. Needs curl (the binding/driver
        `requires: curl`).'''
        dq = shlex.quote(str(dest))
        tmp = shlex.quote(str(Path(dest) / '.configsys-download.archive'))
        return (f'mkdir -p {dq} && {_CURL_DOWNLOAD} {shlex.quote(url)} -o {tmp}'
                f'{self.verify_download(rc, tmp)} && '
                f'{self._extract_cmd(url, tmp, dq, archive_fmt, strip)} && rm -f {tmp}')

    _SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')

    def expected_sha256(self, rc, *keys):
        '''The binding's `sha256:` for what this machine downloads, or None: a scalar, or a map keyed
        by cpu (`x86_64` / its `cpu-names:` token) — and, for native-pkg-file, by package format
        first (`keys`, e.g. 'deb'). A value that isn't 64 hex digits reads as None (routecheck flags
        it). Meaningful with a pinned `version:` (a fixed digest can't follow `latest`).'''
        v = (getattr(rc, 'fields', None) or {}).get('sha256') if rc is not None else None
        if isinstance(v, dict):                       # only then is this machine's cpu needed
            for k in (*keys, self.arch(), self.arch_token(rc)):
                if isinstance(v, dict) and k in v:
                    v = v[k]
        return v if isinstance(v, str) and self._SHA256.match(v) else None

    def verify_download(self, rc, file_q, *keys):
        '''`' && <check>'` — a shell fragment that fails the command unless the downloaded file at
        the (already shell-quoted) `file_q` matches the binding's `sha256:` (looked up by `keys`
        first, see expected_sha256) — or '' when the binding declares none. Spliced right after the
        download, before anything unpacks or installs it (2026-09 A7 / review-2026-11-2 A1).'''
        want = self.expected_sha256(rc, *keys)
        if want is None:
            return ''
        return (f" && {{ printf '%s  %s\\n' {want.lower()} {file_q} | sha256sum -c --quiet - "
                f"|| {{ echo 'configsys: download does not match its sha256 — not installed' >&2; "
                f"rm -f {file_q}; false; }}; }}")

    def download_failure(self, rc, version):
        '''Why a download driver has no URL to fetch for `rc` — the reason its `Result.fail` carries
        (drivers-lang-20: shared by tarball/appImage/font/native-pkg-file/source, so the TUI summary
        and `report` say why, not just "exit 1"). `version` is what resolution produced (may be '').'''
        spec = self._disco_spec(rc)
        asset = spec.get('asset') if isinstance(spec, dict) else None
        if asset:
            return (f'no release asset matched `{asset}` for {rc.comp} '
                    f'{version or "(version unresolved)"} — check the asset name/arch/case '
                    f'for this platform, or run `configsys refresh`')
        if not rc.fields.get('url'):
            return (f'{rc.comp}: binding has neither a `url:` template nor a matching '
                    f'`version:` asset to download')
        return f'{rc.comp}: could not build a download URL (version unresolved?)'

    # -- path-driver kit (tarball/appImage/font/source; plugin build drivers may use it too) ----

    MARKER_PREFIX = '.configsys-'   # every configsys marker / stage name in an install dir

    def home(self):
        '''configsys's home (`--home` / CONFIGSYS_HOME aware), never a bare $HOME.'''
        return Path(self.paths.home) if self.paths is not None else Path.home()

    def marker_path(self, d, rc, kind='version'):
        '''`<d>/.configsys-<comp>.<kind>` — the marker a path driver keeps in its install dir: the
        recorded `version`, or an ownership marker (`cloned`, `adopted`).'''
        return Path(d) / f'{self.MARKER_PREFIX}{rc.comp}.{kind}'

    @staticmethod
    def read_marker(path):
        '''The version a marker records: its text, `'installed'` when it is empty (present, version
        unrecorded — an unresolved discovery wrote it), None when it is absent or unreadable.'''
        try:
            v = Path(path).read_text(encoding='utf-8').strip()
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return v or 'installed'

    def toolchain_bindirs(self):
        '''The bin dirs of the toolchains configsys manages, for a non-interactive build/install
        shell's PATH (it hasn't sourced the glue): rustup's ~/.cargo/bin, the `go` tarball's
        `$CONFIGSYS_SDK_DIR/go/bin` as Paths lays it out (env > `dirs: { sdk: }` > default) at user
        then system scope, and where `go install` puts tools (GOBIN, else GOPATH/bin, else ~/go/bin).
        One answer instead of three diverging constants (drivers-lang-22). With no `paths` (unit
        tests) the defaults, `$HOME` left for the shell to expand.'''
        gobin = self._gobin()
        cargo = str(self.home() / '.cargo' / 'bin') if self.paths is not None else '$HOME/.cargo/bin'
        return list(dict.fromkeys([cargo, *self._go_sdk_bindirs(),
                                   str(gobin) if gobin is not None else '$HOME/go/bin']))

    def _go_sdk_bindirs(self):
        '''The managed Go toolchain's bin dir at user then system scope (the `go` tarball's
        `installDir: $CONFIGSYS_SDK_DIR/go`).'''
        if self.paths is None:
            return ['$HOME/sdks/go/bin', str(SYSTEM_PREFIX / 'sdks' / 'go' / 'bin')]
        return list(dict.fromkeys(str(Path(str(self.paths.install_dir('$CONFIGSYS_SDK_DIR/go', s))) / 'bin')
                                  for s in ('user', 'system')))

    def _gobin(self):
        '''Where `go install` puts binaries — what `go env GOBIN GOPATH` reports, read in-process (no
        spawn): GOBIN, else the first GOPATH entry's bin, else <home>/go/bin; the environment first,
        then `go env -w`'s file ($GOENV, else <config>/go/env). None with no `paths` (the ~/go/bin
        default, left for the shell).'''
        if self.paths is None:
            return None
        env, home = self.paths.env, self.home()
        saved = {}
        gofile = env.get('GOENV') or str(Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'go' / 'env')
        if gofile != 'off':
            try:
                for line in Path(gofile).read_text(encoding='utf-8').splitlines():
                    k, eq, v = line.partition('=')
                    if eq:
                        saved[k.strip()] = v.strip()
            except OSError:
                pass
        gobin = env.get('GOBIN') or saved.get('GOBIN')
        if gobin:
            return Path(gobin)
        gopath = (env.get('GOPATH') or saved.get('GOPATH') or '').split(os.pathsep)[0]
        return Path(gopath) / 'bin' if gopath else home / 'go' / 'bin'

    def unsafe_dir_reason(self, path):
        '''Why `path` must never be deleted or replaced wholesale as a component's own install dir —
        or None when it may. Normalized first (a `..` can't sneak past), then refused: a relative
        path; `/` and every top-level dir; anything inside a distro-owned tree (`/usr/*`, `/etc/*`,
        `/var/*`, …) and a shared dir like `/usr/local/bin` or `/opt/share`; your home, the scope
        bases, the app/sdk/src category dirs and configsys's state dir — and every ANCESTOR of them;
        a shared dir directly in your home (`~/.config`, `~/.local/bin`, `~/Documents`, any `~/.dir`).
        The guard every path driver (tarball, font, source, appImage) asks before an rm -rf / mv, and
        plugin drivers may too (review-2026-11-2 A6).'''
        s = str(path)
        if not s or not os.path.isabs(s):
            return f'{s or "(empty)"} is not an absolute path'
        p = Path(os.path.normpath(s))
        if p == p.parent or p.parent == Path('/'):
            return f'{p} is a top-level directory'
        home = Path(os.path.normpath(str(self.paths.home if self.paths is not None else Path.home())))
        local = str(p).startswith('/usr/local/')        # yours: /usr/local/go, …/share/fonts/configsys-x
        mine = p.is_relative_to(home)                   # inside your home (itself often under /home)
        for tree in _SYSTEM_TREES:
            if str(p).startswith(tree + '/') and not (local or mine):
                return f'{p} is inside {tree}, which the system owns'
        if p.name in _SHARED_NAMES and (local or len(p.parts) <= 4):
            return f'{p} is a shared directory'
        protected = []
        if self.paths is not None:
            pp = self.paths
            protected = [Path(str(pp.home)), Path(str(pp.state_dir))]
            for scope in ('user', 'system'):
                try:
                    protected.append(Path(str(pp.scope_base(scope))))
                except Exception:                      # noqa: BLE001
                    pass
            for var in ('CONFIGSYS_APP_DIR', 'CONFIGSYS_SDK_DIR', 'CONFIGSYS_SRC_DIR'):
                for scope in ('user', 'system'):      # a category dir as each scope lays it out
                    try:
                        protected.append(Path(str(pp.install_dir(pp.dir_var(var), scope))))
                    except Exception:                  # noqa: BLE001
                        pass
        protected.append(home)
        for q in protected:
            q = Path(os.path.normpath(str(q)))
            if p == q or q.is_relative_to(p):
                return f'{p} is (or contains) {q}'
        try:
            rel = p.relative_to(home)
        except ValueError:
            rel = None
        if rel is not None and (str(rel) in _HOME_SHARED
                                or (len(rel.parts) == 1 and rel.parts[0].startswith('.'))):
            return f'{p} is a shared directory in your home'
        return None

    def replace_dir_refusal(self, d, marker):
        '''Why an install may not `rm -rf` and replace `d` — `unsafe_dir_reason`, or `d` already holds
        files and no `marker` of this component (configsys didn't put it there: a hand install, your
        own checkout) — or None. `install --force` (paths.install_force) takes over such a dir.'''
        why = self.unsafe_dir_reason(d)
        if why:
            return why
        if getattr(self.paths, 'install_force', False):
            return None
        try:
            dp = Path(str(d))
            if dp.is_dir() and any(dp.iterdir()) and not Path(str(marker)).exists():
                return (f'{dp} already exists and configsys didn\'t install it — move it aside, or '
                        '`install --force` to replace it')
        except OSError:
            pass
        return None

    def version_spec(self, rc):
        '''The version-discovery spec for `rc` as this driver looks it up (arch and asset applied) —
        the key `configsys refresh` re-queries the cache under (F4: was the private _disco_spec).'''
        return self._disco_spec(rc)

    def will_write(self, path):
        '''Announce a write into `path` BEFORE making it — the primary plugin's write journal
        (primarygit) commits exactly the announced paths that changed, so a driver writing into a
        content root (your primary's dotfiles/glue) must say so, or its write reads as your hand edit
        (review-2026-11-2 F3: frozen here so a rename of primarygit can't silently break a plugin).'''
        from . import primarygit
        primarygit.will_write(path)

    @staticmethod
    def installed_name(rc, driver=None):
        '''A binding's `installed-name:` for one package manager (`driver`, default the unit's own),
        or None — scalar for every manager, or a driver-keyed map with an optional `default:`. The one
        helper a plugin driver should use (hand-reading the field crashes on the map form — F3).'''
        inm = rc.fields.get('installed-name')
        if isinstance(inm, dict):
            inm = inm.get(driver or rc.driver) or inm.get('default')
        return str(inm) if inm else None

    def location_override(self, rc):
        '''The per-component install-location override for this unit, or None. Set from the config
        `locations:` map (component -> path) and injected onto the unit as the reserved
        `location-override` field (a distinct key — `location` is already an authored DISPLAY field
        on the source/script drivers). An ABSOLUTE, scope-bypassing path: "find/manage this
        component's install HERE", regardless of the binding's `dir`/`installDir` and the scope
        layout. Path-based drivers prefer it over their computed target; package drivers ignore it.'''
        loc = rc.fields.get('location-override')
        if not loc:
            return None
        paths = getattr(self, 'paths', None)
        if paths is not None:                          # `~` is configsys's HOME (--home), never $HOME
            return Path(os.path.normpath(str(paths.expand(str(loc)))))
        return Path(os.path.normpath(str(Path(str(loc)).expanduser())))

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

    def batch_index(self, rcs):
        '''Default pre-fetch for a package-manager driver: ONE `installed_index()` enumeration that the
        read ops answer from, instead of a `get_version` subprocess PER unit — the C1 startup-perf win
        for every native manager, not just apt/flatpak. Returns `{'installed': {key: version}}`, or
        None when the driver isn't enumerable (path/build drivers) or the enumeration failed (fall
        back to per-unit probes). Drivers needing MORE in the batch (apt's held+candidate sets,
        flatpak's remotes) override with a richer context.'''
        idx = self.installed_index()
        if idx is None:
            return None
        ctx = {'installed': idx}
        names = sorted({self.index_key(rc) for rc in rcs if self.index_key(rc)})
        if names:
            # the CANDIDATE side too (C1): one `latest_index` query for every unit, instead of a
            # repo-metadata-loading probe per unit — 100 Fedora picks: 201 spawns / ~30 s -> 3 / ~3 s
            try:
                cand = self.latest_index(names)
            except Exception:                          # noqa: BLE001 — per-unit probes still work
                cand = None
            if cand is not None:
                ctx['candidate'] = cand
            try:
                held = self.held_keys()                # the manager's own holds, for is_locked
            except Exception:                          # noqa: BLE001
                held = None
            if held is not None:
                ctx['held'] = set(held)
        return ctx

    def latest_index(self, names):
        '''{name: candidate version} for the given index keys in ONE query, or None when this driver
        can't batch it (then `get_latest` probes per unit). A name the query didn't answer is simply
        absent (its unit falls back to its own probe). Native managers override (dnf repoquery,
        zypper info, pacman -Si, apk list, brew info --json). Frozen hook.'''
        return None

    def batched_latest(self, rc):
        '''(candidate, hit) from the batch context — hit False when this inspect isn't batched or
        the batch didn't answer this unit (the caller probes per unit then).'''
        cand = self.batch.get('candidate') if isinstance(self.batch, dict) else None
        if isinstance(cand, dict) and self.index_key(rc) in cand:
            return cand[self.index_key(rc)], True
        return None, False

    def batched_held(self, rc):
        '''(locked, hit) from the batch context's held set (hit False when not batched).'''
        held = self.batch.get('held') if isinstance(self.batch, dict) else None
        if isinstance(held, set):
            return self.index_key(rc) in held, True
        return False, False

    def batch_installed_index(self, batch):
        '''Extract a plain `{index_key: version}` installed map from THIS driver's batch context (the
        opaque value its `batch_index` returned) — so the startup inspection's already-paid enumeration
        can seed the TUI install overlay instead of it re-spawning every lister. Reads the default
        `{'installed': …}` shape; drivers whose context isn't that override.'''
        return batch.get('installed') if isinstance(batch, dict) else None

    def batched_version(self, rc):
        '''(version_or_None, hit): the installed version from the batch context when this inspect is
        batched, so a native driver's `get_version` answers from the one enumeration. `hit` is False
        when there is no batch (the driver then runs its own per-unit probe).'''
        if isinstance(self.batch, dict) and 'installed' in self.batch:
            return self.batch['installed'].get(self.index_key(rc)), True
        return None, False

    def explicit_keys(self):
        '''The set of installed_index keys the user EXPLICITLY installed (manual / on-request), as
        opposed to those pulled in automatically as dependencies — or None when this driver draws no
        such distinction (then callers treat every installed key as explicit). Native managers
        override (apt-mark showmanual, pacman -Qe, dnf --userinstalled, zypper's AutoInstalled, brew
        leaves). Lets the orphan scan ignore the thousands of dependency packages nobody chose. None
        on command failure too.'''
        return None

    # True for a driver that installs into the OS package database (so its packages appear in the
    # NATIVE manager's installed_index, not under this driver's own name): clang/gcc (apt.llvm.org /
    # a PPA + the native tool), native-pkg-file (a .deb/.rpm via dpkg/rpm), aur (pacman). The orphan
    # scan cross-indexes their package keys under the native manager so enumeration matches.
    native_backed = False

    def origin_index(self):
        '''{package_key: origin_tier} classifying how fundamental each installed package is to the OS
        — apt Priority (`required`/`important`/`standard`/`optional`/`extra`), or a comparable
        per-manager notion. None when the driver has no such concept. The orphan scan carries the tier
        on every foreign orphan (so the data is never lost) and, for now, hides the base tiers
        (required/important/standard) unless asked — a user CAN still choose to manage even systemd.'''
        return None

    def upgradable_index(self):
        '''{package_key: (installed_version, candidate_version)} for everything this manager reports
        UPGRADABLE right now — the SAME key space as installed_index()/index_key(). Reads the native
        index (kept fresh by `configsys refresh`); never refreshes on its own. None when the driver
        has no bulk-manager notion (path/build/language drivers) OR the enumeration failed (fall back
        to claiming nothing, never a wrong list). This feeds the System Updates lane
        (upgradable − managed picks), NOT the picks pipeline — see docs/system-updates.md.'''
        return None

    def update_dedup_key(self, key):
        '''Map an upgradable_index() key to the identity the managed-picks exclusion compares against
        (what index_key() produces for a pick). Default: the key itself — apt/snap use the same
        package/snap name for both. flatpak overrides: its upgradable key is a full ref
        (app/arch/branch, so multi-branch runtimes stay distinct rows) while a pick is keyed by app id.'''
        return key

    def held_keys(self):
        '''The keys this manager has HELD/locked at the manager level (apt-mark hold, flatpak mask,
        snap --hold), so the System Updates lane can MARK them and never bulk-upgrade them. None when
        the driver has no such notion or the query failed. Same key space as upgradable_index().'''
        return None

    def classify_index(self, keys):
        '''{key: tier} classifying each upgradable `key` into one of UPDATE_TIERS, so the System
        Updates lane groups the list by how fundamental each package is (kernel/core/standard/apps)
        instead of showing a wall. Default: the name heuristic (kernel/libc by name, else apps) — a
        manager with a real priority notion (apt) or a runtime/app split (flatpak) overrides. `keys`
        is the upgradable set, so a driver whose priority query enumerates only installed packages can
        still answer for exactly the keys asked.'''
        return {k: tier_by_name(k) for k in keys}

    def get_latest(self, rc):
        '''Latest/candidate available version string, or None if unknown. Default: the discovered
        version (`version:` github/url/static spec) — what most download/build/language-module drivers
        report as "latest". Package-manager drivers override with a repo-candidate query; a driver with
        no version notion (dotfiles/glue/service/group/…) overrides to return None or its state.'''
        return self.resolve_version(rc)

    def is_locked(self, rc):
        '''True if the component is version-locked. Default: False — most drivers have no NATIVE hold
        (the ledger carries the intent, honored by the op loop). apt/dnf/zypper/brew/snap override
        with a real check; a rolling manager that can't hold (pacman/apk) also returns False.'''
        return False

    def upstream_version(self, rc):
        '''The newest UPSTREAM release, for a method that builds a FIXED version its route pins (a
        recipe's `ref:` — e.g. configsys-blender's v4.3.2) — declared on the binding as
        `upstream: { <version spec> }`. Advisory only: it is never "latest" (get_latest stays the
        pinned version the method would actually build, so the unit doesn't read outdated forever
        while an upgrade just rebuilds the pin). None when undeclared or undiscoverable.'''
        spec = rc.fields.get('upstream')
        if not isinstance(spec, dict):
            return None
        from . import versions
        try:
            v = versions.discover(spec, self.paths, offline=self._offline())
        except Exception:                            # noqa: BLE001 — advisory: never break inspect
            return None
        return v if v and _SAFE_VERSION_RE.match(v) else None

    def outdated_signal(self, rc):
        '''Optional override of the generic installed-vs-latest version-STRING comparison, for a
        manager whose real update signal isn't the version string. Return True/False to decide, or
        None (default) to fall back to comparing the strings. flatpak overrides it: an update there is
        a new COMMIT, and many carry the SAME advertised version (a rebuild, a runtime bump), so the
        string compare would wrongly call an updatable app "current".'''
        return None

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

    def upgrade_all(self):
        '''Upgrade EVERYTHING this manager reports upgradable, via its own bulk command (apt upgrade,
        flatpak update, snap refresh) — the System Updates lane's apply step, NOT tied to any
        ResolvedComponent. A held/masked package is left held by the manager itself. Returns a runner
        Result, or None when the driver has no bulk-upgrade concept.'''
        return None

    def set_version(self, rc, version):
        raise NotImplementedError('set_version')

    def lock(self, rc):
        '''Record a version hold. Default: a no-op Result — the ACTUAL hold is the ledger entry the op
        loop (actions.run_plan) writes when this returns ok. A driver with a NATIVE hold
        (apt-mark/versionlock/addlock/brew pin/snap --hold) overrides to do it for real; a rolling
        manager that can't hold (pacman/apk, holds_version=False) overrides to decline.'''
        return Result(f'({self.name} lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result(f'({self.name} unlock recorded in ledger)', 0)

    # -- presentation -----------------------------------------------------

    def location(self, rc):
        '''Human-readable install location (where files go / would go), or None for
        package-managed drivers with no single path (apt). Shown in the TUI infoblock.'''
        return None

    def display_path(self, p):
        '''Collapse HOME to ~ for readable display (on a path boundary — paths.tilde).'''
        from .paths import tilde
        return tilde(p, self.home())
