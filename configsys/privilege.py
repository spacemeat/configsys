'''privilege.py — how configsys runs a step as root: through sudo, through doas, or directly.

The runner holds ONE escalator, chosen when it is built (`detect()`, first match wins):

  AlreadyRoot  euid 0 — nothing to wrap, nothing to ask.
  Sudo         `sudo` on PATH — authenticate with `sudo -v`, probe with `sudo -n -v`; a keep-alive
               re-runs the probe (which also extends the ticket) every 50s while a batch runs.
  Doas         `doas` on PATH and no sudo (Chimera Linux ships only opendoas) — authenticate with
               `doas true`, probe with `doas -n true`. doas has no refresh: a `persist` rule in
               /etc/doas.conf remembers a password for about 5 minutes from the prompt, not from the
               last use, and only for the process that asked — so no keep-alive, and a run with no
               `persist` rule is told once that each privileged step will ask.
  NoEscalator  neither — a privileged step fails, saying configsys needs sudo or doas.

Everything privileged goes through it: `argv_for(cmd)` (a `runner.run(cmd, sudo=True)` op — one
root shell), `prefix` (that op's readable form in logs and --pretend), `word` (what a command string
writes before ONE step that needs root — `as_root(runner)`, `Driver.as_root`, a source recipe's
`$SUDO`), `preauth()` / `authorized()` (the batch's one up-front prompt — docs/principles.md) and
`keepalive()`. The runner's session (begin_sudo / end_sudo / sudo_session) drives these.
'''

import os
import re
import shutil
import subprocess
import threading

# preauth() outcomes
WARM = 'warm'              # usable without a prompt now
EACH_STEP = 'each-step'    # authenticated, but the tool keeps nothing: every privileged step asks
DENIED = 'denied'          # cancelled, a wrong password, or not permitted


class Keepalive:
    '''Run `refresh` every `every` seconds until stop() — a long batch's spaced-out privileged steps
    never find the credential expired mid-stream. Daemon thread; best-effort (a failing refresh
    ends it).'''
    def __init__(self, refresh, every):
        self._refresh, self._every = refresh, every
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while not self._stop.wait(self._every):
            try:
                self._refresh()
            except Exception:                             # noqa: BLE001
                return

    def stop(self):
        self._stop.set()


class Escalator:
    '''How a privileged op gets root. A subclass names its tool and the two commands it runs: AUTH
    (prompts on the real terminal if a password is needed) and PROBE (non-interactive: may I run as
    root right now without a prompt?).'''
    name = ''                  # the tool, as messages name it
    word = ''                  # what a command string writes before a step that needs root
    needs_auth = True          # False: nothing to authenticate (already root / no tool at all)
    missing = None             # why a privileged op can't run at all (NoEscalator), else None
    user_var = None            # the variable the tool names the invoking user in, inside its shell
    AUTH = PROBE = ()
    upfront_note = ''          # begin_sudo's line when the one up-front prompt is coming
    each_step_note = None      # said once when authentication isn't remembered (EACH_STEP)

    @property
    def prefix(self):
        '''The readable form's prefix: `sudo ` / `doas ` / nothing as root.'''
        return f'{self.word} ' if self.word else ''

    @property
    def may_prompt(self):
        '''`<tool> may prompt` for a message about a step that may ask for a password, else None.'''
        return f'{self.name} may prompt' if self.needs_auth else None

    def available(self):
        return shutil.which(self.name) is not None

    def argv_for(self, cmd):
        '''The WHOLE command under one root shell — prefixing a compound command would elevate only
        its first word and eat a leading `set -e`.'''
        return [self.word, 'bash', '-c', cmd] if self.word else ['bash', '-c', cmd]

    def authenticate(self):
        '''The prompting command, on the inherited (real) terminal. -> whether it succeeded.'''
        return subprocess.run(list(self.AUTH)).returncode == 0

    def authorized(self):
        '''Non-interactive: can a privileged step run right now without a prompt?'''
        return subprocess.run(list(self.PROBE), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0

    def preauth(self):
        '''Authenticate ONCE on the real terminal (one prompt if a password is needed), so the
        batch's later privileged steps run without one. -> WARM, EACH_STEP or DENIED. Best-effort
        (never raises).'''
        try:
            if not self.authenticate():
                return DENIED
            return WARM if self.authorized() else EACH_STEP
        except Exception:                                 # noqa: BLE001
            return DENIED

    def keepalive(self):
        '''A started Keepalive holding the credential for the batch, or None when there is nothing to
        refresh.'''
        return None


class Sudo(Escalator):
    name = word = 'sudo'
    user_var = 'SUDO_USER'
    AUTH = ('sudo', '-v')
    PROBE = ('sudo', '-n', '-v')
    upfront_note = ('This run needs root: authenticating sudo once, up front — it stays cached for '
                    'the whole run.')

    def keepalive(self):
        return Keepalive(self.authorized, 50)        # `sudo -n -v` probes AND extends the ticket;
                                                     # 50s is well under the default 15-min timeout


class Doas(Escalator):
    name = word = 'doas'
    user_var = 'DOAS_USER'
    AUTH = ('doas', 'true')
    PROBE = ('doas', '-n', 'true')
    upfront_note = ('This run needs root: authenticating doas once, up front — a `persist` rule keeps '
                    'it about 5 minutes, so a longer run may ask again.')
    each_step_note = ('doas will ask for your password at each privileged step: /etc/doas.conf has no '
                      '`persist` (or `nopass`) rule for you. To be asked once per batch instead, add '
                      '`permit persist :wheel` to it (configsys never edits doas.conf).')
    # keepalive(): None — doas has no refresh (`persist` counts from the prompt, not from use)


class AlreadyRoot(Escalator):
    name = 'root'
    needs_auth = False

    def available(self):
        return True

    def authorized(self):
        return True


class NoEscalator(Escalator):
    name = 'none'
    word = 'sudo'              # what the command needs: a step written with it fails as
                               # "sudo: command not found", and begin_sudo said why up front
    needs_auth = False
    missing = ('configsys needs sudo or doas to run this as root, and neither is on PATH — install '
               'one, or run configsys as root')
    upfront_note = ('This run needs root, but neither sudo nor doas is on PATH: its root steps will '
                    'fail — install one, or run configsys as root.')

    def available(self):
        return False

    def authorized(self):
        return False


def detect():
    '''This machine's escalator: already root, else sudo on PATH, else doas on PATH, else none.'''
    try:
        if os.geteuid() == 0:
            return AlreadyRoot()
    except AttributeError:                                # non-POSIX: no euid to read
        pass
    for cls in (Sudo, Doas):
        if shutil.which(cls.name):
            return cls()
    return NoEscalator()


_SUDO = Sudo()


def of(runner):
    '''`runner`'s escalator. A stand-in runner without one (a test double) reads as sudo — the form
    such doubles record for a `sudo=True` op.'''
    return getattr(runner, 'escalator', None) or _SUDO


# a command's `$SUDO` (or `${SUDO}`) — never the head of a longer name such as `$SUDO_USER`
_SUDO_VAR = re.compile(r'\$(?:SUDO\b|\{SUDO\})')


def fill_sudo(text, word):
    '''`text` with each `$SUDO` replaced by `word` — the escalator's (`as_root`), or '' where the step
    needs no root — as a source recipe and a script binding write a root step.'''
    return _SUDO_VAR.sub(lambda _m: word, str(text))


def names_sudo(text):
    '''Whether `text` writes a `$SUDO` root step.'''
    return bool(_SUDO_VAR.search(str(text)))


def and_may_prompt(runner, lead, where=''):
    '''`lead; sudo may prompt<where>` (`doas may prompt` under doas), or `lead` alone when nothing
    will ask (already root) — a note before steps that may need a password.'''
    hint = of(runner).may_prompt
    return f'{lead}; {hint}{where}' if hint else lead


def as_root(runner):
    '''The word a command string writes before ONE step that needs root, for `runner`: `sudo`,
    `doas`, or '' when configsys already runs as root — `f'{as_root(runner)} tee {path}'`. A whole
    command runs as root with `runner.run(cmd, sudo=True)` instead (one root shell), and a command
    already run that way never writes it (it is root; doas may not even permit root).'''
    return of(runner).word
