'''cli/common.py — the small helpers several verb families share (the --pretend edit note, the install-
scope label, the reboot advisory, the one y/N prompt).

Split out of app.py (review-2026-11-2 D2).
'''

import sys


def _install_scope_label(cfg):
    '''Display string for the install set: this machine + how many components it tracks (picks).
    Replaces the retired active-profiles label — the matrix installs from picks:, not profiles.'''
    n = len(cfg.included())
    return f'{cfg.current_machine()} ({n} tracked)'


def print_reboot_advisory(ctx):
    '''Print the reboot/restart advisory (blank if nothing's needed). Shared by ops and `refresh`.'''
    from .. import rebootcheck
    adv = rebootcheck.advisory(ctx)
    if not adv.actionable:
        return
    if adv.reboot:
        print(f'\nconfigsys: ⚠ reboot advised — {adv.reason}.')
    if adv.services:
        shown = ', '.join(adv.services[:8]) + ('…' if len(adv.services) > 8 else '')
        head = 'also, ' if adv.reboot else 'configsys: '
        print(f'{head}{len(adv.services)} service(s) still using old libraries: {shown}'
              f'{"" if adv.reboot else " — restart them or reboot"}.')


def _pretend_edit(ctx, what):
    '''--pretend is a TRUE dry run, config edits included: print what the edit WOULD do and return
    True so the caller skips the write (and the user-config generation before it). The same shape
    pin set/unset/promote, plugin set-source and glue add/override already use.'''
    if getattr(ctx.runner, 'pretend', False):
        print(f'configsys: [pretend] would {what}')
        return True
    return False


def _warn_unknown_component(name, universe):
    '''A name the merged catalog doesn't define is still written (another machine may load the plugin
    that defines it) — but never silently (B11).'''
    if name not in universe:
        print(f'configsys: warning — {name!r} is not a known component here; it installs nothing on '
              f'a machine that doesn\'t load a layer defining it', file=sys.stderr)


def ask(prompt, *, yes=False, pretend=False, noninteractive='refuse', refuse_note=None):
    '''The ONE y/N question every CLI verb asks (app-cli-18) — one policy instead of a dozen
    hand-written prompts. True = go (y/yes). `yes` (--yes) answers True without asking. `pretend`
    says what WOULD be asked and answers no (a dry run never waits on a question it can't act on). Not
    a terminal: noninteractive='refuse' prints `refuse_note` (default: re-run with --yes) and returns
    None — falsy, so a caller can tell "refused" from "declined" — while 'no' answers False quietly.
    End of input answers no.'''
    if yes:
        return True
    if pretend:
        print(f'configsys: [pretend] would ask: {prompt.strip()}')
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        if noninteractive == 'no':
            return False
        print(refuse_note or '\nconfigsys: not a terminal — re-run with --yes to go ahead.')
        return None
    try:
        return input(prompt).strip().lower() in ('y', 'yes')
    except EOFError:
        return False
