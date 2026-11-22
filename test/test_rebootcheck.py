'''rebootcheck: after-an-op "reboot advised / services need restart" advisory, using each family's
native check (apt file, dnf/zypper exit codes, pacman/apk kernel heuristic). No needrestart dep.'''

import types

from configsys import rebootcheck
from configsys.runner import Result


def _ctx(pm, responses, pretend=False):
    class R:
        def __init__(s):
            s.pretend = pretend

        def run(s, cmd, **kw):
            for pref, (rc, out) in responses.items():
                if cmd.startswith(pref):
                    return Result(cmd, rc, stdout=out)
            return Result(cmd, 127)
    return types.SimpleNamespace(runner=R(),
                                 routes=types.SimpleNamespace(cascade=types.SimpleNamespace(native=lambda b: pm)),
                                 os_info=types.SimpleNamespace(block='x'))


def test_dnf_reboot_and_services():
    c = _ctx('dnf', {'dnf needs-restarting -r': (1, ''),
                     'dnf needs-restarting -s': (0, 'sshd.service\ncrond.service\n')})
    a = rebootcheck.advisory(c)
    assert a.reboot and a.actionable
    assert a.services == ['sshd.service', 'crond.service']


def test_dnf_no_reboot():
    c = _ctx('dnf', {'dnf needs-restarting -r': (0, ''), 'dnf needs-restarting -s': (0, '')})
    assert not rebootcheck.advisory(c).actionable


def test_zypper_exit_102_is_reboot():
    c = _ctx('zypper', {'zypper needs-rebooting': (102, ''), 'zypper ps -sss': (0, 'sshd\npostfix\n')})
    a = rebootcheck.advisory(c)
    assert a.reboot and a.services == ['sshd', 'postfix']


def test_zypper_no_reboot():
    c = _ctx('zypper', {'zypper needs-rebooting': (0, ''), 'zypper ps -sss': (0, '')})
    assert not rebootcheck.advisory(c).reboot


def test_pacman_newer_kernel_advises_reboot():
    c = _ctx('pacman', {'uname -r': (0, '6.8.1-arch1-1\n'), 'pacman -Q linux': (0, 'linux 6.9.0.arch1-1\n')})
    assert rebootcheck.advisory(c).reboot


def test_pacman_same_kernel_different_suffix_no_false_positive():
    # `uname -r` and the pkg version format differ in suffix but are the same kernel -> NO reboot.
    c = _ctx('pacman', {'uname -r': (0, '6.9.0-arch1-1\n'), 'pacman -Q linux': (0, 'linux 6.9.0.arch1-1\n')})
    assert not rebootcheck.advisory(c).reboot


def test_apt_reboot_required_file(tmp_path, monkeypatch):
    flag = tmp_path / 'reboot-required'
    pkgs = tmp_path / 'reboot-required.pkgs'
    flag.write_text('')
    pkgs.write_text('linux-image-6.8\nlibc6\n')
    monkeypatch.setattr(rebootcheck, '_APT_REBOOT_FLAG', flag)
    monkeypatch.setattr(rebootcheck, '_APT_REBOOT_PKGS', pkgs)
    a = rebootcheck.advisory(_ctx('apt', {}))
    assert a.reboot and 'libc6' in a.reason and 'linux-image-6.8' in a.reason


def test_apt_no_flag_no_reboot(tmp_path, monkeypatch):
    monkeypatch.setattr(rebootcheck, '_APT_REBOOT_FLAG', tmp_path / 'absent')
    assert not rebootcheck.advisory(_ctx('apt', {})).reboot


def test_pretend_reports_nothing():
    c = _ctx('dnf', {'dnf needs-restarting -r': (1, '')}, pretend=True)
    assert not rebootcheck.advisory(c).actionable
    assert rebootcheck.reboot_pending(c) == (False, '')


def test_xbps_newer_kernel_series_advises_reboot():
    # Void kernels are series packages (linux6.12, linux6.18); the bare `linux` meta is skipped
    idx = ('ii linux-6.18_1                     The Linux kernel (meta)\n'
           'ii linux6.12-6.12.111_1            The Linux kernel and modules (6.12 series)\n'
           'ii linux6.18-6.18.4_1              The Linux kernel and modules (6.18 series)\n')
    a = rebootcheck.advisory(_ctx('xbps', {'uname -r': (0, '6.12.111_1\n'), 'xbps-query -l': (0, idx)}))
    assert a.reboot and '6.18.4_1' in a.reason
    b = rebootcheck.advisory(_ctx('xbps', {'uname -r': (0, '6.18.4_1\n'), 'xbps-query -l': (0, idx)}))
    assert not b.reboot


# -- the running kernel's own series only (review-2026-11-2 subsystems-06) ---------------------------

def _pacman(uname, q):
    return _ctx('pacman', {'uname -r': (0, uname + '\n'), 'pacman -Q linux-lts': (0, q),
                           'pacman -Q linux': (0, q)})


def test_pacman_lts_booted_beside_a_newer_mainline_is_no_reboot():
    q = 'linux 6.12.1.arch1-1\nlinux-lts 6.6.30-1\n'
    assert rebootcheck.reboot_pending(_pacman('6.6.30-1-lts', q)) == (False, '')


def test_pacman_lts_upgraded_in_its_own_series_is_a_reboot():
    reboot, reason = rebootcheck.reboot_pending(_pacman('6.6.30-1-lts', 'linux-lts 6.6.31-1\n'))
    assert reboot and '6.6.31-1' in reason


def test_pacman_mainline_ignores_an_installed_lts():
    q = 'linux 6.12.1.arch1-1\nlinux-lts 6.13.0-1\n'      # (a lts newer than mainline: still not ours)
    assert rebootcheck.reboot_pending(_pacman('6.12.1-arch1-1', q)) == (False, '')


def test_apk_lts_booted_beside_a_newer_edge_is_no_reboot():
    idx = 'linux-lts-6.6.7-r0 x86_64 {linux-lts}\nlinux-edge-6.12.1-r0 x86_64 {linux-edge}\n'
    c = _ctx('apk', {'uname -r': (0, '6.6.7-0-lts\n'), 'apk list --installed': (0, idx)})
    assert rebootcheck.reboot_pending(c) == (False, '')
    idx2 = 'linux-lts-6.6.9-r0 x86_64 {linux-lts}\nlinux-edge-6.12.1-r0 x86_64 {linux-edge}\n'
    c2 = _ctx('apk', {'uname -r': (0, '6.6.7-0-lts\n'), 'apk list --installed': (0, idx2)})
    assert rebootcheck.reboot_pending(c2)[0] is True


def test_chimera_series_is_the_package_not_the_uname_flavor():
    # every Chimera kernel's release ends `-generic` (linux-lts 6.18.62 -> 6.18.62-0-generic), so the
    # series is the PACKAGE (linux-lts / linux-stable) of the running MAJOR.MINOR
    idx = ('linux-lts-6.18.62-r0 x86_64 {linux-lts}\nlinux-stable-7.3.3-r0 x86_64 {linux-stable}\n'
           'linux-headers-7.0.12-r0 x86_64 {linux-headers}\nlinux-pam-1.7.2-r0 x86_64 {linux-pam}\n')
    booted_lts = _ctx('chimera-apk', {'uname -r': (0, '6.18.60-0-generic\n'), 'apk list --installed': (0, idx)})
    assert rebootcheck.reboot_pending(booted_lts)[0] is True          # lts 6.18.62 > running 6.18.60
    current = _ctx('chimera-apk', {'uname -r': (0, '6.18.62-0-generic\n'), 'apk list --installed': (0, idx)})
    assert rebootcheck.reboot_pending(current) == (False, '')         # a newer linux-stable isn't ours
    only = 'linux-stable-7.4.1-r0 x86_64 {linux-stable}\n'               # the only kernel moved series
    moved = _ctx('chimera-apk', {'uname -r': (0, '7.3.3-0-generic\n'), 'apk list --installed': (0, only)})
    assert rebootcheck.reboot_pending(moved)[0] is True


def test_xbps_another_series_without_the_meta_is_no_reboot():
    idx = ('ii linux6.6-6.6.30_1              The Linux kernel and modules (6.6 series)\n'
           'ii linux6.12-6.12.111_1           The Linux kernel and modules (6.12 series)\n')
    c = _ctx('xbps', {'uname -r': (0, '6.6.30_1\n'), 'xbps-query -l': (0, idx)})
    assert rebootcheck.reboot_pending(c) == (False, '')
    idx2 = idx.replace('6.6.30_1 ', '6.6.31_1 ')
    c2 = _ctx('xbps', {'uname -r': (0, '6.6.30_1\n'), 'xbps-query -l': (0, idx2)})
    assert rebootcheck.reboot_pending(c2)[0] is True
