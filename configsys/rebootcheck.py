'''rebootcheck.py — after an update, is a reboot advised, and which services want a restart?

Uses each family's NATIVE check (no needrestart dependency):
  * apt     — /run/reboot-required (a file update-notifier-common drops on kernel/libc/systemd/… bumps)
  * dnf     — `dnf needs-restarting -r` (exit 1 = reboot advised) / `-s` (services)
  * zypper  — `zypper needs-rebooting`  (exit 102 = reboot needed) / `zypper ps -sss` (services)
  * pacman/apk/xbps — no native flag: a kernel-vs-running heuristic (a newer kernel of the running one's
    series is installed). Conservative — compares only MAJOR.MINOR.PATCH so a distro suffix can't
    false-fire, and never against another flavor/series you may boot on purpose.
  * brew    — none, declared in _NO_REBOOT_CHECK (user-space; rpm-ostree reports its own reboots).
Service lists use the native tool where cheap, else `needrestart` IF it happens to be installed
(opportunistic — never required). Everything is best-effort + non-fatal; pretend runs report nothing.'''

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Advisory:
    reboot: bool = False
    reason: str = ''
    services: list = field(default_factory=list)

    @property
    def actionable(self):
        return self.reboot or bool(self.services)


def _run(ctx, cmd):
    try:
        return ctx.runner.run(cmd, capture=True)
    except Exception:                                    # noqa: BLE001 — a probe must never break an op
        return None


def _pm(ctx):
    try:
        return ctx.routes.cascade.native(ctx.os_info.block)
    except Exception:                                    # noqa: BLE001
        return None


def reboot_pending(ctx):
    '''(reboot: bool, reason: str) — the reboot-only check (cheap enough for the TUI chip). Empty in
    pretend / when it can't be determined.'''
    if getattr(ctx.runner, 'pretend', False):
        return (False, '')
    return _reboot(ctx, _pm(ctx))


def advisory(ctx):
    '''Full Advisory (reboot + reason + services) — for the after-an-op report. Empty in pretend.'''
    if getattr(ctx.runner, 'pretend', False):
        return Advisory()
    pm = _pm(ctx)
    reboot, reason = _reboot(ctx, pm)
    return Advisory(reboot=reboot, reason=reason, services=_services(ctx, pm))


# -- reboot-required, per family -----------------------------------------------

_APT_REBOOT_FLAG = Path('/run/reboot-required')          # update-notifier-common drops this (/var/run -> /run)
_APT_REBOOT_PKGS = Path('/run/reboot-required.pkgs')


def _apt_reboot(ctx, pm):
    if _APT_REBOOT_FLAG.exists():
        pkgs = _read_lines(_APT_REBOOT_PKGS)
        return (True, ('updated ' + ', '.join(sorted(set(pkgs)))) if pkgs
                else 'a core package was updated')
    return (False, '')


def _dnf_reboot(ctx, pm):
    r = _run(ctx, 'dnf needs-restarting -r')
    return (True, 'kernel or core libraries updated') if (r is not None and r.returncode == 1) \
        else (False, '')


def _zypper_reboot(ctx, pm):
    r = _run(ctx, 'zypper needs-rebooting')
    return (True, 'kernel or core libraries updated') if (r is not None and r.returncode == 102) \
        else (False, '')


def _reboot(ctx, pm):
    check = _REBOOT_CHECKS.get(pm)
    return check(ctx, pm) if check else (False, '')


def _read_lines(p):
    try:
        return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]
    except OSError:
        return []


def _kver(s):
    '''The leading MAJOR.MINOR.PATCH of a kernel string as an int tuple, or None. Ignores any distro
    suffix (-arch1-1, -1-oem, .fcNN) so a format mismatch between `uname -r` and the pkg version can't
    produce a false "newer kernel".'''
    m = re.match(r'(\d+)\.(\d+)\.(\d+)', s or '')
    return tuple(int(x) for x in m.groups()) if m else None


def _flavor(raw):
    '''The kernel FLAVOR a `uname -r` names by its trailing token — `6.6.30-1-lts` -> `lts`,
    `6.6.7-0-virt` -> `virt`, `6.12.1-zen1-1-zen` -> `zen` — or '' for a plain one (`6.12.1-arch1-1`,
    Void's `6.12.111_1`), whose last token isn't a word.'''
    tail = raw.rsplit('-', 1)[-1] if '-' in raw else ''
    return tail if tail.isalpha() else ''


def _kernel_heuristic(ctx, pm):
    '''A newer kernel than the running one, of the SERIES it was booted from: a box that boots
    linux-lts on purpose with a newer `linux` also installed (or Alpine's linux-lts beside
    linux-edge) must not read "reboot advised" forever — a reboot wouldn't clear it. pacman: the
    `linux-<flavor>` package `uname -r` names (bare `linux` when it names none); apk: the
    `linux-<flavor>-` package; xbps: the `linuxM.N` series package of the running MAJOR.MINOR, plus
    the series the `linux` meta package now points at (an update that moved your default series is
    one a reboot picks up).'''
    run = _run(ctx, 'uname -r')
    raw = run.stdout.strip() if (run and run.ok) else ''
    running = _kver(raw)
    if running is None:
        return (False, '')
    flavor = _flavor(raw)
    vers = []
    if pm == 'pacman':
        pkg = f'linux-{flavor}' if flavor else 'linux'
        q = _run(ctx, f'pacman -Q {pkg}')
        for ln in (q.stdout.splitlines() if (q and q.stdout) else []):
            parts = ln.split()
            if len(parts) == 2 and parts[0] == pkg:
                vers.append(parts[1])                    # "linux 6.9.1.arch1-1" -> "6.9.1.arch1-1"
    elif pm == 'xbps':
        q = _run(ctx, 'xbps-query -l')                   # "ii linux6.12-6.12.111_1  The Linux kernel…"
        series, meta = {}, None
        for ln in (q.stdout.splitlines() if (q and q.stdout) else []):
            parts = ln.split()
            name = parts[1] if len(parts) >= 2 else ''
            m = re.match(r'linux(\d+\.\d+)-(\d.*)$', name)
            mm = re.match(r'linux-(\d+\.\d+)', name)    # "linux-6.18_1": the meta's default series
            if m:
                series[m.group(1)] = m.group(2)
            elif mm:
                meta = mm.group(1)
        wanted = {f'{running[0]}.{running[1]}'} | ({meta} if meta else set())
        vers = [v for mm, v in series.items() if mm in wanted]
    else:                                                # apk
        if not flavor:
            return (False, '')                           # every Alpine kernel names its flavor
        pre = f'linux-{flavor}-'
        q = _run(ctx, 'apk list --installed')
        for ln in (q.stdout.splitlines() if (q and q.stdout) else []):
            tok = ln.split()[0] if ln.split() else ''    # "linux-lts-6.6.7-r0 x86_64 {…}"
            if tok.startswith(pre):
                vers.append(tok[len(pre):])
    best = None
    for v in vers:
        kv = _kver(v)
        if kv is not None and (best is None or kv > best[0]):
            best = (kv, v)
    if best is not None and best[0] > running:
        return (True, f'a newer kernel is installed ({best[1]}) than the running one '
                      f'({".".join(str(x) for x in running)})')
    return (False, '')


# Every native manager declares exactly one of these (test_driver_inventory): its reboot-required
# check, or why it has none.
_REBOOT_CHECKS = {'apt': _apt_reboot, 'dnf': _dnf_reboot, 'zypper': _zypper_reboot,
                  'pacman': _kernel_heuristic, 'apk': _kernel_heuristic, 'xbps': _kernel_heuristic}
_NO_REBOOT_CHECK = {
    'brew': 'user-space formulae never need a reboot; on fedora_atomic (brew-native) the system '
            'image is rpm-ostree\'s, and its driver prints its own reboot notice',
}


# -- services needing restart (opportunistic) ---------------------------------

def _services(ctx, pm):
    if pm == 'dnf':
        return _service_tokens(_run(ctx, 'dnf needs-restarting -s'))
    if pm == 'zypper':
        r = _run(ctx, 'zypper ps -sss')                  # -sss: bare service names, one per line
        return [ln.strip() for ln in (r.stdout.splitlines() if (r and r.ok) else [])
                if ln.strip()][:20]
    if shutil.which('needrestart'):                      # apt/pacman/apk/xbps: use it only if already present
        r = _run(ctx, 'needrestart -b')                  # batch: `NEEDRESTART-SVC: <unit>` lines
        return [ln.split(':', 1)[1].strip()
                for ln in (r.stdout.splitlines() if (r and r.stdout) else [])
                if ln.startswith('NEEDRESTART-SVC:')][:20]
    return []


def _service_tokens(r):
    if not (r and r.ok):
        return []
    out = []
    for ln in r.stdout.splitlines():
        for tok in ln.split():
            if tok.endswith('.service'):
                out.append(tok)
    return out[:20]
