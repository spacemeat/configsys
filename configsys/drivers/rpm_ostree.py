'''rpm_ostree.py — the rpm-ostree driver: explicit package layering on atomic distros.

For Fedora Atomic / uBlue (Silverblue, Kinoite, Bazzite, Bluefin, Aurora) and kin, where
the root is a read-only ostree image. This driver is the LAST-RESORT path (see
docs/immutable-distros.md): apps go via flatpak and CLI tools via brew (the atomic OS's
`native:`); rpm-ostree is only for what genuinely must be layered into the image — kernel
modules, hardware enablement, system integration.

Layering is reboot-gated: `rpm-ostree install` stages the change into a NEW deployment that
becomes active on next boot. That is rpm-ostree's own always-correct default, so it is ours
too; a binding may set `apply-live: true` to also apply to the running deployment now (only
safe for userspace packages — rpm-ostree refuses it for kernel-level changes).

Honesty over cleverness:
- get_latest is None — ostree carries no live repo metadata; the "latest" of a layered
  package is whatever the image ships, discovered by upgrading the whole system, not per pkg.
- get_version reads the RUNNING system (`rpm -q`); a freshly-staged-but-not-booted package
  reads as not-yet-installed, matching reality (it isn't active until reboot).
- upgrade / set_version / lock are not per-package operations here and say so rather than
  quietly doing something surprising (e.g. upgrading the whole OS).
'''

import shlex

from ..driver import Driver
from ..runner import Result


def _truthy(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


class RpmOstree(Driver):
    name = 'rpm-ostree'
    privileged = True
    default_scope = 'system'   # layered into the system image (always root)

    @staticmethod
    def _pkg(rc):
        return rc.name   # rpm package name (== dnf's; name-map key: `rpm-ostree`)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # the running system's reality; a staged-not-booted layer reads as absent (correct
        # — it isn't active until reboot). `%{VERSION}` needs doubling inside the f-string.
        r = self.runner.run(f"rpm -q --qf '%{{VERSION}}' {shlex.quote(self._pkg(rc))}")
        if not r.ok:
            return None
        return r.stdout.strip() or None

    def get_latest(self, rc):
        return None   # no per-package "latest" on ostree — it comes with the image

    def is_locked(self, rc):
        return False  # layered packages are image-pinned; no per-package lock

    # -- mutate -----------------------------------------------------------

    def _layer(self, verb, rc):
        pkg = shlex.quote(self._pkg(rc))
        if _truthy(rc.fields.get('apply-live')):
            cmd = (f'rpm-ostree {verb} --apply-live -y {pkg} && '
                   f'echo "configsys: {verb} {pkg} applied live (also staged for next boot)" >&2')
        else:
            cmd = (f'rpm-ostree {verb} -y {pkg} && '
                   f'echo "configsys: {verb} {pkg} staged — reboot (or set apply-live) to activate" >&2')
        return self.runner.run(cmd, sudo=True, capture=False)

    def install(self, rc):
        return self._layer('install', rc)

    def uninstall(self, rc):
        return self._layer('uninstall', rc)

    def upgrade(self, rc):
        return Result("(rpm-ostree: layered packages update with the base image; "
                      "run 'rpm-ostree upgrade' to update the whole system)", 0)

    def set_version(self, rc, version):
        return Result('(rpm-ostree: a layered package takes what the image/repos provide; '
                      'pinning an arbitrary version is not supported)', 0)

    def lock(self, rc):
        return Result('(rpm-ostree: layered packages are image-pinned; no per-package lock)', 0)

    def unlock(self, rc):
        return Result('(rpm-ostree: no per-package lock to release)', 0)

    def location(self, rc):
        return '(rpm-ostree layered)'
