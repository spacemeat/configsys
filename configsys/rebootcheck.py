'''rebootcheck.py — after an update, is a reboot advised, and which services want a restart?

Uses each family's NATIVE check (no needrestart dependency):
  * apt     — /run/reboot-required (a file update-notifier-common drops on kernel/libc/systemd/… bumps)
  * dnf     — `dnf needs-restarting -r` (exit 1 = reboot advised) / `-s` (services)
  * zypper  — `zypper needs-rebooting`  (exit 102 = reboot needed) / `zypper ps -sss` (services)
  * pacman/apk — no native flag: a kernel-vs-running heuristic (a newer kernel is installed than the
    running one). Conservative — compares only MAJOR.MINOR.PATCH so a distro suffix can't false-fire.
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


def _reboot(ctx, pm):
    if pm == 'apt':
        if _APT_REBOOT_FLAG.exists():
            pkgs = _read_lines(_APT_REBOOT_PKGS)
            return (True, ('updated ' + ', '.join(sorted(set(pkgs)))) if pkgs
                    else 'a core package was updated')
        return (False, '')
    if pm == 'dnf':
        r = _run(ctx, 'dnf needs-restarting -r')
        return (True, 'kernel or core libraries updated') if (r is not None and r.returncode == 1) \
            else (False, '')
    if pm == 'zypper':
        r = _run(ctx, 'zypper needs-rebooting')
        return (True, 'kernel or core libraries updated') if (r is not None and r.returncode == 102) \
            else (False, '')
    if pm in ('pacman', 'apk'):
        return _kernel_heuristic(ctx, pm)
    return (False, '')                                   # brew/atomic: rpm-ostree messages on its own


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


def _kernel_heuristic(ctx, pm):
    run = _run(ctx, 'uname -r')
    running = _kver(run.stdout.strip()) if (run and run.ok) else None
    if running is None:
        return (False, '')
    vers = []
    if pm == 'pacman':
        q = _run(ctx, 'pacman -Q linux linux-lts linux-zen linux-hardened')
        for ln in (q.stdout.splitlines() if (q and q.stdout) else []):
            parts = ln.split()
            if len(parts) == 2:
                vers.append(parts[1])                    # "linux 6.9.1.arch1-1" -> "6.9.1.arch1-1"
    else:                                                # apk
        q = _run(ctx, 'apk list --installed')
        for ln in (q.stdout.splitlines() if (q and q.stdout) else []):
            tok = ln.split()[0] if ln.split() else ''    # "linux-lts-6.6.7-r0 x86_64 {…}"
            for pre in ('linux-lts-', 'linux-virt-', 'linux-edge-', 'linux-rpi-', 'linux-'):
                if tok.startswith(pre):
                    vers.append(tok[len(pre):])
                    break
    best = None
    for v in vers:
        kv = _kver(v)
        if kv is not None and (best is None or kv > best[0]):
            best = (kv, v)
    if best is not None and best[0] > running:
        return (True, f'a newer kernel is installed ({best[1]}) than the running one '
                      f'({".".join(str(x) for x in running)})')
    return (False, '')


# -- services needing restart (opportunistic) ---------------------------------

def _services(ctx, pm):
    if pm == 'dnf':
        return _service_tokens(_run(ctx, 'dnf needs-restarting -s'))
    if pm == 'zypper':
        r = _run(ctx, 'zypper ps -sss')                  # -sss: bare service names, one per line
        return [ln.strip() for ln in (r.stdout.splitlines() if (r and r.ok) else [])
                if ln.strip()][:20]
    if shutil.which('needrestart'):                      # apt/pacman/apk: use it only if already present
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
