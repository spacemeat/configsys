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
