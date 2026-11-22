'''chimera_apk.py — the Chimera Linux driver.

Chimera Linux installs packages with apk-tools v3 — Alpine's tool — but its OWN packages: other
names (`-devel` not `-dev`, `python-*` not `py3-*`, …) in other repositories. So it is its own `via:`
(`chimera-apk`, the chimera os block's `native:`): the `apk:` keys of a binding's `name:` map are
Alpine's and never reach it, and Chimera's names live in ONE generated `component-names: {
chimera-apk: … }` block in routes.hu (tools/chimeranames.py), a `{}` there taking a component
Chimera doesn't package out of the native candidates.

The driver is Alpine's (drivers/apk.py: `apk list` reads, /etc/apk/world as the explicit set, no
per-package hold — Chimera is rolling too, so lock / set-version decline) except where Chimera
differs:
  * the `user` repository — most CLI tools (bat, fish, eza, …) — is off by default and is enabled
    by installing the `chimera-repo-user` package. ensure_prereqs does that ONCE, before the first
    install / upgrade, refreshing the index, and says so;
  * Chimera's apk config turns on `interactive` (a Y/n question before every change); configsys has
    shown the plan and asked already, so every mutation passes `--no-interactive`;
  * the repo package is plumbing configsys added, not an app you picked: it stays out of the
    explicit set the orphan scan reads.
'''

import shlex

from ..runner import Result
from .apk import Apk


class ChimeraApk(Apk):
    name = 'chimera-apk'
    DISTRO = 'Chimera'
    INSTALL = 'apk add --no-interactive {pkgs}'
    REMOVE = 'apk del --no-interactive {pkgs}'
    UPGRADE = 'apk add --no-interactive --upgrade {pkgs}'
    USER_REPO = 'chimera-repo-user'      # the package whose install enables the `user` repository

    def __init__(self, runner, paths=None):
        super().__init__(runner, paths)
        self._user_repo = False          # enabled (or found enabled) by this driver instance

    def ensure_prereqs(self, rc):
        '''Enable Chimera's `user` repository once, before the first install/upgrade: `apk add
        chimera-repo-user` + `apk update`, with a note. Already enabled -> nothing (no note). Under
        --pretend the probe can't answer, so the dry run shows the step it would take. A failed
        setup stops the op, named.'''
        if self._user_repo:
            return None
        repo = shlex.quote(self.USER_REPO)
        probe = self.runner.run(f'apk info -e {repo}')        # installed? (a read: no root)
        if probe.ok and not probe.pretended:
            self._user_repo = True
            return None
        how = f'apk add {self.USER_REPO}, then apk update'
        self.runner.echo(f"chimera-apk: Chimera's `user` repository (most CLI tools) "
                         + (f"would be enabled first if it isn't yet ({how})" if probe.pretended
                            else f"isn't enabled — enabling it first ({how})"))
        r = self.runner.run(f'apk add --no-interactive {repo} && apk update', sudo=True, capture=False)
        if not r.ok:
            tail = r.output.splitlines()[-1].strip() if r.output else f'exit {r.returncode}'
            return Result.fail(f"{rc.comp}: enabling Chimera's `user` repository ({how}) failed: {tail}")
        self._user_repo = True
        return None

    def upgrade_all(self):
        return self.runner.run('apk upgrade --no-interactive', sudo=True, capture=False)

    def explicit_keys(self):
        '''/etc/apk/world minus the repo package configsys added (plumbing, never an orphan).'''
        keys = super().explicit_keys()
        return None if keys is None else keys - {self.USER_REPO}
