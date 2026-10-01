'''flatpak.py — the flatpak driver (user scope).

Operates on flatpaks in the unprivileged `--user` installation (no sudo, and
sandbox-friendly: XDG_DATA_HOME redirects it). We only install/list/update/remove
and mask — never launch — so none of the bwrap/FUSE/dbus runtime machinery is
needed. Route fields: `hub` (remote name, e.g. flathub) and `name` (the app id).

Version lock uses `flatpak mask` (prevents updates). Adding the hub remote is a
prerequisite handled before install/upgrade, mirroring apt's repo-component.

Outdated detection is COMMIT-based (`outdated_signal` -> `flatpak remote-ls --updates`),
not a version-string compare: a flatpak update is a new commit and often keeps the same
advertised Version (a rebuild, a runtime bump), which a string compare would miss. This
matches what the software store (GNOME Software / Pop!_Shop) reports. `get_latest` still
returns the remote's advertised version string, for DISPLAY of the "latest" column.
'''

import json
import os
import shlex
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..driver import Driver

# Well-known hub remotes -> their .flatpakrepo URL (routes may override via `hub-url`).
HUB_REPOS = {
    'flathub': 'https://dl.flathub.org/repo/flathub.flatpakrepo',
    'flathub-beta': 'https://dl.flathub.org/beta-repo/flathub-beta.flatpakrepo',
}


class Flatpak(Driver):
    name = 'flatpak'
    privileged = False

    # -- helpers ----------------------------------------------------------

    default_scope = 'user'
    honors_scope = True

    @staticmethod
    def _appid(rc):
        return rc.name  # route `name` field is the flatpak app id

    def _flag(self, rc):
        return '--user' if self.scope(rc) == 'user' else '--system'

    @staticmethod
    def _parse_field(text, field):
        prefix = f'{field}:'
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return None

    def ensure_remote(self, rc):
        hub = rc.fields.get('hub')
        if not hub:
            return
        url = rc.fields.get('hub-url') or HUB_REPOS.get(hub)
        if not url:
            # Unknown hub with no url; assume the remote is already configured.
            return
        self.runner.run(
            f'flatpak remote-add {self._flag(rc)} --if-not-exists {shlex.quote(hub)} '
            f'{shlex.quote(url)}', sudo=self.sudo(rc), capture=False)

    # -- read (scope-agnostic: detect it wherever it's installed; no sudo) -

    def installed_index(self):
        # ONE call lists every installed app (either installation) -> {app-id: version}.
        r = self.runner.run('flatpak list --app --columns=application,version')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            cols = line.split('\t') if '\t' in line else line.split()
            if cols and cols[0].strip():
                idx[cols[0].strip()] = (cols[1].strip() if len(cols) > 1 else '') or 'installed'
        return idx

    def index_key(self, rc):
        return self._appid(rc)

    def batch_index(self, rcs):
        '''Pre-fetch the inspect probes for these units in a FIXED few calls instead of ~4 per app.
        remote-info is ~2s/app; `flatpak remote-ls <hub>` lists a whole remote (all of flathub =
        3453 apps in ~2s), so ONE remote-ls per distinct hub replaces every per-app remote-info for
        that hub. Plus one `flatpak list` (installed app -> version+scope) and one `flatpak mask` per
        installation (mask ignores its arg). None only if nothing probes -> per-unit fallback.'''
        installed = {}                                 # app -> (version, scope)
        r = self.runner.run('flatpak list --app --columns=application,version,installation')
        if r.ok:
            for line in r.stdout.splitlines():
                cols = line.split('\t') if '\t' in line else line.split()
                if cols and cols[0].strip():
                    ver = (cols[1].strip() if len(cols) > 1 else '') or 'installed'
                    inst = cols[2].strip() if len(cols) > 2 else ''
                    installed[cols[0].strip()] = (ver, inst if inst in ('user', 'system') else 'user')
        masked = set()                                 # locked (masked) app ids, either installation
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak mask {flag}')
            if r.ok:
                masked.update(x.strip() for x in r.stdout.split() if x.strip())
        # The two `--updates` queries (the authoritative, commit-based outdated set — what the store
        # shows) run BESIDE the candidate listing below instead of after it.
        with ThreadPoolExecutor(max_workers=2) as ex:
            upd = [ex.submit(self.runner.run, f'flatpak remote-ls {flag} --updates --columns=application')
                   for flag in ('--user', '--system')]
            candidate = {}                             # hub -> {app: version}
            for hub in sorted({rc.fields.get('hub') for rc in rcs if rc.fields.get('hub')}):
                for scope in ('system', 'user'):       # the version is scope-independent; first hit wins
                    m = self._remote_versions(hub, scope)
                    if m is not None:
                        candidate[hub] = m
                        break
            updates = set()                            # app ids with a pending update, EITHER scope
            for f in upd:
                r = f.result()
                if r.ok:
                    updates.update(x.strip() for x in r.stdout.split() if x.strip())
        return {'installed': installed, 'masked': masked, 'candidate': candidate, 'updates': updates}

    def _remote_versions(self, hub, scope):
        '''{app: advertised version} for every app on remote `hub` in installation `scope`, or None if
        flatpak can't list it. `remote-ls --columns=version` re-parses the remote's whole appstream
        (flathub: a 50 MB XML, ~2.3 s of CPU) on EVERY call — the listing itself is 0.1 s. So the result
        is cached, keyed by a FINGERPRINT of exactly the files it's computed from (the appstream
        checkout `active` points at — a commit-named dir — and the remote's cached summary). Any
        refresh flatpak does (`flatpak update`, an appstream pull) changes them and misses the cache;
        an unchanged fingerprint means an unchanged answer. No fingerprint -> no caching.'''
        fp = self._remote_fingerprint(hub, scope)
        cache = self._read_remote_cache() if fp else {}
        slot = f'{scope}:{hub}'
        hit = cache.get(slot)
        if fp and isinstance(hit, dict) and hit.get('fp') == fp and isinstance(hit.get('apps'), dict):
            return hit['apps']
        r = self.runner.run(f'flatpak remote-ls --{scope} {shlex.quote(hub)} --app --columns=application,version')
        if not r.ok:
            return None
        m = {}
        for line in r.stdout.splitlines():
            cols = line.split('\t') if '\t' in line else line.split()
            if cols and cols[0].strip():
                m[cols[0].strip()] = (cols[1].strip() if len(cols) > 1 else '') or None
        if fp and m:
            cache[slot] = {'fp': fp, 'apps': m}
            self._write_remote_cache(cache)
        return m

    def _flatpak_dirs(self, scope):
        '''(installation dir, summary-cache dir) for `scope`, as flatpak itself locates them.'''
        env = getattr(self.paths, 'env', None) or os.environ
        home = Path(env.get('HOME') or Path.home())
        if scope == 'system':
            inst = Path(env.get('FLATPAK_SYSTEM_DIR') or '/var/lib/flatpak')
            cache = Path(env.get('XDG_CACHE_HOME') or home / '.cache') / 'flatpak' / 'system-cache' / 'summaries'
            return inst, [cache, inst / 'repo' / 'tmp' / 'cache' / 'summaries']
        inst = Path(env.get('FLATPAK_USER_DIR')
                    or Path(env.get('XDG_DATA_HOME') or home / '.local' / 'share') / 'flatpak')
        return inst, [inst / 'repo' / 'tmp' / 'cache' / 'summaries']

    def _remote_fingerprint(self, hub, scope):
        '''A string that changes whenever `remote-ls <hub>`'s answer can: the resolved appstream
        checkout(s) + the .gz's stat, and the stat of the remote's cached summary files. None when
        there is no appstream to key on (then the caller simply doesn't cache).'''
        if self.paths is None:
            return None
        try:
            inst, sumdirs = self._flatpak_dirs(scope)
            parts = []
            adir = inst / 'appstream' / hub
            for arch in sorted(os.listdir(adir)):
                active = adir / arch / 'active'
                real = os.path.realpath(active)
                st = os.stat(os.path.join(real, 'appstream.xml.gz'))
                parts.append(f'{arch}={real}:{st.st_mtime_ns}:{st.st_size}')
            if not parts:
                return None
            for d in sumdirs:
                if d.is_dir():
                    for f in sorted(os.listdir(d)):
                        if f.startswith(hub + '.') or f.startswith(hub + '-'):
                            st = os.stat(d / f)
                            parts.append(f'{f}:{st.st_mtime_ns}:{st.st_size}')
            return '|'.join(parts)
        except OSError:
            return None

    def _remote_cache_file(self):
        return self.paths.state_dir / 'flatpak-remote-ls.json'

    def _read_remote_cache(self):
        try:
            data = json.loads(self._remote_cache_file().read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_remote_cache(self, cache):
        f = self._remote_cache_file()
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(f'.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(cache))
            os.replace(tmp, f)
        except OSError:
            pass                                       # a cache, never fatal

    def batch_installed_index(self, batch):
        inst = batch.get('installed') if isinstance(batch, dict) else None
        if not isinstance(inst, dict):
            return None
        return {app: (v[0] if isinstance(v, tuple) else v) for app, v in inst.items()}   # drop the scope

    def get_version(self, rc):
        if self._batch is not None:                    # batched: from the one `flatpak list`
            v = self._batch['installed'].get(self._appid(rc))
            return v[0] if v else None
        # no --user/--system flag: find the app in EITHER installation. (Otherwise a
        # system-installed app looks "missing" under the default user scope.)
        app = shlex.quote(self._appid(rc))
        r = self.runner.run(f'flatpak info {app}')
        if not r.ok:
            return None
        return (self._parse_field(r.stdout, 'Version')
                or self._parse_field(r.stdout, 'Commit')
                or 'installed')

    def get_installed(self, rc):
        if self._batch is not None:                    # batched: version + which installation
            v = self._batch['installed'].get(self._appid(rc))
            return v if v else (None, None)
        # which installation actually has it — so the menu shows the real scope, not the target
        app = shlex.quote(self._appid(rc))
        for scope, flag in (('user', '--user'), ('system', '--system')):
            r = self.runner.run(f'flatpak info {flag} {app}')
            if r.ok:
                return (self._parse_field(r.stdout, 'Version')
                        or self._parse_field(r.stdout, 'Commit') or 'installed', scope)
        return (None, None)

    def get_latest(self, rc):
        hub = rc.fields.get('hub')
        if not hub:
            return None
        if self._batch is not None:                    # batched: from the one remote-ls per hub
            return (self._batch['candidate'].get(hub) or {}).get(self._appid(rc)) or None
        # The remote's available version, from `flatpak remote-info` — read from flatpak's LOCAL
        # appstream metadata (refreshed on `flatpak update`/`flatpak remote-ls`), NOT a live network
        # fetch. The remote can exist in BOTH the user and system installations, which makes a bare
        # `remote-info` ambiguous (it prompts) — so disambiguate with a scope flag; either resolves
        # the same remote metadata. Version only (a bare commit hash isn't version-comparable).
        app, hubq = shlex.quote(self._appid(rc)), shlex.quote(hub)
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak remote-info {flag} {hubq} {app}')
            if r.ok:
                return self._parse_field(r.stdout, 'Version') or None
        return None

    def outdated_signal(self, rc):
        '''Commit-based outdated verdict (NOT a version-string compare). A flatpak update is a new
        COMMIT; many keep the same advertised Version (a rebuild, a runtime bump), so the generic
        string compare calls an updatable app "current" while the software store — which compares
        commits — shows the update. `flatpak remote-ls --updates` is that same pending-update set, so
        membership = outdated. Returns None only when flatpak couldn't be queried (fall back to strings).'''
        appid = self._appid(rc)
        if self._batch is not None:                    # batched: the one --updates set per sweep
            return appid in self._batch.get('updates', ())
        seen_ok = False                                # per-unit: ask flatpak directly, both scopes
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak remote-ls {flag} --updates --columns=application')
            if r.ok:
                seen_ok = True
                if appid in r.stdout.split():
                    return True
        return False if seen_ok else None

    def upgradable_index(self):
        '''{ref: (installed, candidate)} — the commit-based pending-update set (what the software
        store shows), across BOTH installations. `flatpak remote-ls --updates` is authoritative;
        runtimes/extensions show alongside apps here (this is the whole-system lane, not the app
        catalogue), so no `--app` filter. Keyed by full REF (app/arch/branch), NOT app id, so a
        runtime installed at two branches (freedesktop 24.08 + 26.08) stays two rows matched to their
        OWN installed versions instead of collapsing into a bogus cross-branch "downgrade";
        update_dedup_key maps a ref back to the app id for the managed-picks exclusion. Installed
        version comes from `flatpak list`. None only when neither scope could be queried.'''
        installed = {}                                 # normalised ref (id/arch/branch) -> version
        r = self.runner.run('flatpak list --columns=ref,version')
        if r.ok:
            for line in r.stdout.splitlines():
                cols = line.split('\t') if '\t' in line else line.split()
                if cols and cols[0].strip():
                    installed[self._norm_ref(cols[0].strip())] = (
                        cols[1].strip() if len(cols) > 1 else '') or None
        idx, seen_ok = {}, False
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak remote-ls {flag} --updates --columns=ref,version')
            if r.ok:
                seen_ok = True
                for line in r.stdout.splitlines():
                    cols = line.split('\t') if '\t' in line else line.split()
                    if cols and cols[0].strip():
                        ref = self._norm_ref(cols[0].strip())
                        cand = (cols[1].strip() if len(cols) > 1 else '') or None
                        idx.setdefault(ref, (installed.get(ref), cand))
        return idx if seen_ok else None

    @staticmethod
    def _norm_ref(ref):
        '''Normalise a flatpak ref to `id/arch/branch`. `flatpak list` prints that form directly;
        `flatpak remote-ls` prefixes the kind (`app/…`, `runtime/…`), so the two never match without
        this — leaving every remote row with a None installed version.'''
        parts = ref.split('/')
        if len(parts) == 4 and parts[0] in ('app', 'runtime'):
            return '/'.join(parts[1:])
        return ref

    def update_dedup_key(self, key):
        # a normalised ref is `<id>/<arch>/<branch>`; a pick is keyed by the app id (index_key).
        return key.split('/', 1)[0]

    def classify_index(self, keys):
        '''The runtime/app split from the tier table: platforms, SDKs, GL drivers, codecs and VAAPI
        extensions are the shared base layer -> `core`; everything else is an app -> `apps`. flatpak
        has no kernel/standard notion. Classified by app id, so it needs no extra query.'''
        return {k: ('core' if self._is_runtime_id(self.update_dedup_key(k)) else 'apps')
                for k in keys}

    @staticmethod
    def _is_runtime_id(appid):
        # every observed runtime/extension id carries `.Platform` (Platform, Platform.GL.*,
        # Platform.VAAPI.*, Platform.codecs-*) or `.Sdk` (Sdk, Sdk.Extension.*); apps carry neither.
        return '.Platform' in appid or '.Sdk' in appid

    def held_keys(self):
        masked, seen_ok = set(), False
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak mask {flag}')
            if r.ok:
                seen_ok = True
                masked.update(x.strip() for x in r.stdout.split() if x.strip())
        return masked if seen_ok else None

    def upgrade_all(self):
        # No scope flag: updates every installation the invoking user can write (the user install
        # always; the system one if policy allows without auth). Masked apps are skipped by flatpak.
        return self.runner.run('flatpak update -y', capture=False)

    def is_locked(self, rc):
        appid = self._appid(rc)
        if self._batch is not None:                    # batched: membership in the mask set
            return appid in self._batch['masked']
        for flag in ('--user', '--system'):
            r = self.runner.run(f'flatpak mask {flag}')
            if r.ok and any(appid in line for line in r.stdout.splitlines()):
                return True
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        self.ensure_remote(rc)
        # name the remote only when the binding declares one; a bare `hub: ''` would otherwise become
        # a literal '' positional and flatpak errors ("Nothing matches"). Without a hub, flatpak
        # resolves the app-id against the configured remotes.
        hub = rc.fields.get('hub')
        remote = f'{shlex.quote(hub)} ' if hub else ''
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak install {self._flag(rc)} -y {remote}{app}',
                               sudo=self.sudo(rc), capture=False)

    def uninstall(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak uninstall {self._flag(rc)} -y {app}',
                               sudo=self.sudo(rc), capture=False)

    def upgrade(self, rc):
        self.ensure_remote(rc)
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak update {self._flag(rc)} -y {app}',
                               sudo=self.sudo(rc), capture=False)

    def set_version(self, rc, version):
        # flatpak pins by commit; treat `version` as a commit id.
        app = shlex.quote(self._appid(rc))
        commit = shlex.quote(version)
        return self.runner.run(
            f'flatpak update {self._flag(rc)} -y --commit={commit} {app}',
            sudo=self.sudo(rc), capture=False)

    def location(self, rc):
        root = '~/.local/share/flatpak' if self.scope(rc) == 'user' else '/var/lib/flatpak'
        return f'{root}  ({self._appid(rc)})'

    def lock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask {self._flag(rc)} {app}',
                               sudo=self.sudo(rc))

    def unlock(self, rc):
        app = shlex.quote(self._appid(rc))
        return self.runner.run(f'flatpak mask {self._flag(rc)} --remove {app}',
                               sudo=self.sudo(rc))
