'''apt.py — the Debian/apt driver.

Version state via dpkg-query + apt-cache policy; mutation via apt-get; version
lock via apt-mark hold/unhold. Mutating ops run under sudo and stream their output
(capture=False) so the user sees apt's progress and sudo can prompt.
'''

import shlex

from ..driver import Driver
from ..failures import SIGNATURE, classify, retry_transient
from ..runner import Result

# apt-get update transient-retry (see failures.retry_transient): a momentary stumble — a network
# blip, or "E: The list of sources could not be read" from a concurrent apt run (unattended-upgrades,
# packagekit) touching sources.list.d mid-read — clears on a retry, while a definitive failure is
# returned at once. `_UPDATE_TRIES` total attempts, `_UPDATE_BACKOFF` seconds between (0 in tests).
_UPDATE_TRIES = 3
_UPDATE_BACKOFF = 1.5

# Keep automated installs from popping interactive TUI dialogs mid-batch — the whiptail/newt screens
# that paint the whole terminal a solid colour and then linger. DEBIAN_FRONTEND=noninteractive makes
# debconf answer from preseeds/defaults instead of prompting (e.g. wireshark's non-root-capture
# question); NEEDRESTART_MODE=a stops Ubuntu's post-apt `needrestart` hook from prompting about which
# services to restart / a newer kernel. Prepended to every mutating apt-get invocation.
_APT_ENV = 'DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a'


def _parse_policy(text, want):
    '''{name: candidate-version} from `apt-cache policy pkg1 pkg2 ...` output, restricted to `want`.
    Each package block starts with `<name>:` at column 0; its indented `Candidate:` line gives the
    version ((none)/empty -> None). Packages apt can't find are simply omitted (no block).'''
    out = {}
    cur = None
    for line in text.splitlines():
        if line[:1] and not line[:1].isspace() and line.rstrip().endswith(':'):
            hdr = line.rstrip()[:-1]              # a column-0 `name:` header starts a package block
            cur = hdr if hdr in want else None
        elif cur is not None:
            s = line.strip()
            if s.startswith('Candidate:'):
                cand = s.split(':', 1)[1].strip()
                out[cur] = None if cand in ('(none)', '') else cand
                cur = None
    return out


class Apt(Driver):
    name = 'apt'
    privileged = True
    default_scope = 'system'   # apt packages are system-wide (fixed)

    # -- prerequisites ----------------------------------------------------

    @staticmethod
    def _as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def _apt_update(self):
        '''`apt-get update`, retrying a TRANSIENT stumble a few times with a short backoff — so a
        momentary hiccup never gets misread as a broken repo (see failures.retry_transient).'''
        return retry_transient(lambda: self.runner.run('sudo apt-get update', capture=True),
                               tries=_UPDATE_TRIES, backoff=_UPDATE_BACKOFF)

    def _commit_source(self, write_cmd, src_path, key_url=None, key_path=None):
        '''Write a vendor apt source (write_cmd writes it only if absent AND runs apt-get update),
        then VALIDATE. On a signature failure with a key configured, re-fetch the key overwriting the
        stale one and retry once (rotation self-heal). If it STILL fails and we created the source
        THIS run, roll it back (rm) so a failed setup never leaves a poison pill that breaks every
        later apt op — BUT only after confirming OUR source is the culprit (apt-get update can fail on
        a PRE-EXISTING, unrelated broken source, whose "E: The list of sources could not be read"
        names nothing): re-check with our source disabled, and if it still fails, restore our valid
        source and report the real, pre-existing breakage instead. Returns None on success, or a
        classified failing Result. See docs/driver-resilience-plan.md (P2 validate-then-commit).'''
        sp = shlex.quote(src_path)
        existed = self.runner.run(f'test -f {sp}', capture=True).ok
        res = self.runner.run(write_cmd, capture=True)
        if res.ok:
            return None
        # the write_cmd's embedded `apt-get update` failed but the source is now written — retry a
        # standalone update (transient-resilient) before treating this as a real failure. A momentary
        # blip clears here and the source commits cleanly, no rollback, no misleading verdict.
        res = self._apt_update()
        if res.ok:
            return None
        cat, rem = classify(res.output)
        if cat == SIGNATURE and key_url and key_path:
            kp, ku = shlex.quote(key_path), shlex.quote(key_url)
            self.runner.run(f'sudo curl -fsSL {ku} -o {kp}', capture=True)   # overwrite (rotation)
            res = self._apt_update()
            if res.ok:
                return None
            cat, rem = classify(res.output)
        if not existed:
            # Disable OUR just-created source and re-run update: does apt recover without it?
            self.runner.run(f'sudo rm -f {sp}', capture=True)
            recheck = self._apt_update()
            if not recheck.ok:
                # STILL failing without our source -> the breakage is pre-existing and unrelated.
                # Restore our valid source (don't strand a working repo) and report the real problem.
                self.runner.run(write_cmd, capture=True)     # file is now absent -> re-creates it
                tail = (recheck.output.splitlines()[-1].strip()
                        if recheck.output else 'apt-get update failed')
                cat, rem = classify(recheck.output)
                return Result.fail(
                    f'apt-get update is failing on a pre-existing apt source, not on {src_path} '
                    f'(removing it did not help): {tail}. Fix the broken source under '
                    f'/etc/apt/sources.list.d/, then retry.', category=cat, remediation=rem)
            # apt recovered without our source -> ours WAS the culprit; keep it rolled back and report.
        tail = (res.output.splitlines()[-1].strip() if res.output else 'apt-get update failed')
        return Result.fail(f'vendor repo setup for {src_path} failed: {tail}'
                           + ('' if existed else ' (source rolled back)'),
                           category=cat, remediation=rem)

    def ensure_prereqs(self, rc):
        '''System setup a component needs before it can install, declared on its
        route: extra CPU architectures to enable (`foreign-arch`, e.g. i386 for
        Steam), archive components (`repo-component`), and third-party signing key +
        source list (`pubkey-*`/`source-*`). Idempotent — each step is skipped when
        already satisfied. Returns None normally, or a classified failing Result if a
        vendor repo could not be verified (so install/upgrade abort cleanly).'''
        f = rc.fields

        for arch in self._as_list(f.get('foreign-arch')):
            a = shlex.quote(arch)
            # enable the multiarch once (idempotent), then refresh lists so its
            # packages become visible. `steam:i386` needs i386 on an amd64 host.
            self.runner.run(
                f'if ! dpkg --print-foreign-architectures | grep -qx {a}; then '
                f'dpkg --add-architecture {a} && apt-get update; fi',
                sudo=True, capture=False)

        for comp in self._as_list(f.get('repo-component')):
            c = shlex.quote(comp)
            # add-apt-repository is idempotent and refreshes apt lists itself.
            self.runner.run(f'add-apt-repository -y {c}', sudo=True, capture=False)

        # `ppa`: a Launchpad PPA (e.g. deadsnakes/ppa for python3.12/3.13) — `add-apt-repository -y
        # ppa:<name>` adds it + refreshes. Needs software-properties-common (declare it in requires:).
        for ppa in self._as_list(f.get('ppa')):
            p = shlex.quote(ppa if ppa.startswith('ppa:') else f'ppa:{ppa}')
            self.runner.run(f'add-apt-repository -y {p}', sudo=True, capture=False)

        key_url, key_path = f.get('pubkey-url'), f.get('pubkey-path')
        if key_url and key_path:
            kp, ku = shlex.quote(key_path), shlex.quote(key_url)
            self.runner.run(f'[ -f {kp} ] || sudo curl -fsSL {ku} -o {kp}',
                            capture=False)

        src_url, src_path = f.get('source-url'), f.get('source-path')
        if src_url and src_path:
            sp, su = shlex.quote(src_path), shlex.quote(src_url)
            fail = self._commit_source(
                f'if [ ! -f {sp} ]; then sudo curl -fsSL {su} -o {sp} '
                f'&& sudo apt-get update; fi', src_path, key_url, key_path)
            if fail is not None:
                return fail

        # `source-line`: an inline `deb ...` line written to source-path (for vendor repos
        # like Microsoft's that ship no downloadable .list — you echo the line yourself).
        # `$CODENAME` in the line is resolved on the target from /etc/os-release (UBUNTU_CODENAME
        # first — set on Ubuntu + derivatives like Pop!_OS/Mint — else VERSION_CODENAME), so a
        # codename-specific vendor repo (e.g. MongoDB's ubuntu/<codename>) works on any release
        # rather than a single hardcoded suite. Same mechanism the clang/gcc AltDriver uses.
        src_line = f.get('source-line')
        if src_line and src_path:
            sp = shlex.quote(src_path)
            if '$CODENAME' in src_line:
                write = (
                    f'if [ ! -f {sp} ]; then '
                    f'CODENAME="$(. /etc/os-release; echo "${{UBUNTU_CODENAME:-$VERSION_CODENAME}}")"; '
                    f'echo "{src_line}" | sudo tee {sp} >/dev/null && sudo apt-get update; fi')
            else:
                sl = shlex.quote(src_line)
                write = (f'if [ ! -f {sp} ]; then echo {sl} | sudo tee {sp} >/dev/null '
                         f'&& sudo apt-get update; fi')
            fail = self._commit_source(write, src_path, key_url, key_path)
            if fail is not None:
                return fail

        # `debconf`: preseed install-time debconf answers so a NON-interactive install makes
        # the choice we want instead of the silent default (e.g. wireshark's non-root-capture
        # setuid, which apt otherwise declines). Each entry is a raw debconf-set-selections
        # line "<owner> <question> <type> <value>". Preseed always; and if the owning package
        # is ALREADY installed, dpkg-reconfigure it so the answer takes effect on this run too
        # — not only on a fresh install. (dnf/pacman don't read this field.)
        for line in self._as_list(f.get('debconf')):
            owner = (line.split(None, 1) or [''])[0]
            if not owner:
                continue
            lq, oq = shlex.quote(line), shlex.quote(owner)
            self.runner.run(
                f'echo {lq} | debconf-set-selections && '
                f'if dpkg-query -W -f=\'${{Status}}\' {oq} 2>/dev/null '
                f'| grep -q "install ok installed"; then '
                f'DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive {oq}; fi',
                sudo=True, capture=False)

    # -- read -------------------------------------------------------------

    def installed_index(self):
        # ONE call lists every installed package -> {name: version}; the coexistence detector does
        # membership lookups instead of a dpkg-query per component. \n-terminated (multiarch rows).
        # Key BOTH the bare name and the arch-qualified `name:arch`: a route may name a foreign-arch
        # package (e.g. Steam's `steam:i386`), but dpkg reports ${Package} BARE, so without the
        # qualified key the batched lookup would miss an installed multiarch package (reporting it
        # "missing" though it's installed).
        # Prefix each row with the install status: `apt-get remove` (configsys's uninstall) leaves a
        # package in the `config-files` state (its conffiles under /etc survive), and dpkg-query -W
        # STILL lists it with a version — so without this filter a removed component keeps reporting as
        # installed (stale "installed" underline / version). Keep only genuinely-installed packages.
        r = self.runner.run(
            "dpkg-query -W -f='${db:Status-Status} ${Package} ${Architecture} ${Version}\\n'")
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            parts = line.split(' ', 3)
            if len(parts) < 3 or parts[0] != 'installed' or not parts[1]:
                continue                          # skip config-files (rc), not-installed, half-* states
            name, arch = parts[1], parts[2]
            ver = (parts[3].strip() if len(parts) > 3 else '') or 'installed'
            idx.setdefault(name, ver)             # bare name — first row wins (matches get_version)
            idx.setdefault(f'{name}:{arch}', ver) # arch-qualified — for routes like `steam:i386`
        return idx

    def explicit_keys(self):
        '''`apt-mark showmanual` — packages the user explicitly installed, as opposed to the ones
        apt auto-pulled as dependencies. Bare names (no arch); the orphan scan matches on those.'''
        r = self.runner.run('apt-mark showmanual')
        if not r.ok:
            return None
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

    def origin_index(self):
        '''{package: Priority} — Debian priority (required/important/standard/optional/extra), the
        "how fundamental is this to the OS" tier. Bare names; a blank priority reads as '' (unknown).'''
        r = self.runner.run("dpkg-query -W -f='${Package} ${Priority}\\n'")
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            name, _, prio = line.partition(' ')
            if name:
                idx.setdefault(name, prio.strip())     # first row wins (matches installed_index)
        return idx

    @staticmethod
    def _probe_name(rc):
        '''The package to READ install-state / version from — the binding's `installed-name:` when
        set, else the install `name`. For a metapackage that a system commonly has WITHOUT (Debian
        ships LibreOffice as `libreoffice-core` + `-calc`/… without the `libreoffice` meta), so
        `name` installs the suite but `installed-name` (a component present whenever any of it is)
        is what tells us it's installed. Mutation ops (install/remove/upgrade/lock) still use
        `name`.'''
        return rc.fields.get('installed-name') or rc.name

    def batch_index(self, rcs):
        '''Pre-fetch the three inspect probes for these units in THREE calls (not three per package):
        the installed-version index (dpkg-query -W, all packages), the held set (apt-mark showhold,
        which ignores its arg and lists them all anyway), and candidate versions (one `apt-cache
        policy pkg...`). Returned as a dict the read ops below consult via self._batch. None on the
        rare total failure -> the caller falls back to per-unit probes.'''
        names = sorted({self._probe_name(rc) for rc in rcs})
        installed = self.installed_index()
        if installed is None:
            return None
        r = self.runner.run('apt-mark showhold')
        held = set(r.stdout.split()) if r.ok else set()
        candidate = {}
        if names:
            r = self.runner.run('apt-cache policy ' + ' '.join(shlex.quote(n) for n in names))
            if r.ok:
                candidate = _parse_policy(r.stdout, set(names))
        return {'installed': installed, 'held': held, 'candidate': candidate}

    def batch_installed_index(self, batch):
        return batch.get('installed') if isinstance(batch, dict) else None

    def get_version(self, rc):
        if self._batch is not None:               # batched: answer from the one dpkg-query index
            return self._batch['installed'].get(self._probe_name(rc))
        pkg = shlex.quote(self._probe_name(rc))
        # `\n`-terminate the format: a multiarch package (e.g. libvulkan1:amd64 + :i386,
        # once i386 is enabled for Steam) prints one row per installed instance. Without a
        # separator the two versions concatenate into a doubled string that never matches
        # the apt candidate -> perpetually "outdated". Take the first row (arches match).
        # status-guarded (see installed_index): a `config-files` (removed-but-conffiles) package still
        # answers dpkg-query with a version — take the first genuinely-INSTALLED row, else not installed.
        r = self.runner.run(f"dpkg-query -W -f='${{db:Status-Status}} ${{Version}}\\n' {pkg}")
        if r.ok and r.stdout.strip():
            for ln in r.stdout.splitlines():
                st, _, ver = ln.strip().partition(' ')
                if st == 'installed' and ver.strip():
                    return ver.strip()
        return None

    # -- read: available version ------------------------------------------
    # (A tool that ships an upstream .deb rather than living in the apt repos is its own via:
    # native-pkg-file — see drivers/native_pkg_file.py. apt is just the distro repos.)

    def get_latest(self, rc):
        if self._batch is not None:               # batched: answer from the one apt-cache policy call
            return self._batch['candidate'].get(self._probe_name(rc))
        pkg = shlex.quote(self._probe_name(rc))
        r = self.runner.run(f'apt-cache policy {pkg}')
        if not r.ok:
            return None
        for line in r.stdout.splitlines():        # single block -> first Candidate: is ours
            line = line.strip()
            if line.startswith('Candidate:'):
                cand = line.split(':', 1)[1].strip()
                return None if cand in ('(none)', '') else cand
        return None

    def is_locked(self, rc):
        if self._batch is not None:               # batched: membership in the one showhold list
            return rc.name in self._batch['held']
        r = self.runner.run('apt-mark showhold')
        return bool(r.ok and rc.name in r.stdout.split())

    # -- mutate -----------------------------------------------------------

    @staticmethod
    def _pkgs(rc):
        '''The package argument(s) for apt. A `packages: [a, b, ...]` binding installs the whole set
        (the house convention for a native component that needs several apt packages — e.g. a
        python3.12 interpreter + -venv + -dev, or GL + GLU dev); otherwise `rc.name` (which may itself
        be a whitespace-separated set). Each token is quoted. `installed-name:` still governs
        detection, so state-probing has a single package to look at.'''
        pkgs = rc.fields.get('packages')
        names = ([str(p) for p in pkgs] if isinstance(pkgs, list) else
                 [str(pkgs)] if pkgs else rc.name.split())
        return ' '.join(shlex.quote(p) for p in names)

    def install(self, rc):
        pre = self.ensure_prereqs(rc)
        if pre is not None:                      # a vendor repo failed to verify -> abort cleanly
            return pre
        return self.runner.run(f'{_APT_ENV} apt-get install -y {self._pkgs(rc)}',
                               sudo=True, capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'{_APT_ENV} apt-get remove -y {self._pkgs(rc)}',
                               sudo=True, capture=False)

    def upgrade(self, rc):
        pre = self.ensure_prereqs(rc)
        if pre is not None:
            return pre
        return self.runner.run(f'{_APT_ENV} apt-get install --only-upgrade -y {self._pkgs(rc)}',
                               sudo=True, capture=False)

    def set_version(self, rc, version):
        pre = self.ensure_prereqs(rc)
        if pre is not None:
            return pre
        pkg = shlex.quote(rc.name)
        ver = shlex.quote(version)
        return self.runner.run(
            f'{_APT_ENV} apt-get install -y --allow-downgrades {pkg}={ver}',
            sudo=True, capture=False)

    def lock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-mark hold {pkg}', sudo=True)

    def unlock(self, rc):
        pkg = shlex.quote(rc.name)
        return self.runner.run(f'apt-mark unhold {pkg}', sudo=True)
