'''cli/issues.py — `report`, `request`, `request-os` — assembling and filing issues (the body is shown first).

Split out of app.py (review-2026-11-2 D2).
'''

from .common import ask


# Practical ceiling for a prefilled issues/new URL. GitHub's own docs cap the server at ~8k, and
# some browsers are tighter; 6k leaves headroom for encoding overhead and stays safely under both.
_URL_PREFILL_LIMIT = 6000


def _file_issue(ctx, title, body, label='install-report', save_as='last-report.md'):
    '''File the (already-approved) report/request and RETURN (rc, display_lines) — the outcome as a
    list of ready-to-show lines (an issue URL, a prefilled link, or a saved-body path). No printing and
    no prompting, so both the CLI (_send_report prints these) and the TUI review overlay (shows them)
    reuse the exact same send logic + consent contract. Prefers `gh issue create`; else saves the body
    and offers a prefilled new-issue link.'''
    import shutil
    import subprocess
    import urllib.parse
    from ..reportgen import REPORTS_REPO

    if getattr(ctx.runner, 'pretend', False):          # a dry run files nothing and saves nothing
        how = '`gh issue create`' if shutil.which('gh') else 'a prefilled new-issue link'
        return 0, [f'configsys: [pretend] would file "{title}" at {REPORTS_REPO} via {how} — not sent']
    lines = []
    if shutil.which('gh'):
        import tempfile
        import contextlib
        import os
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(body)
            bodyfile = f.name
        try:
            proc = subprocess.run(['gh', 'issue', 'create', '--repo', REPORTS_REPO,
                                   '--title', title, '--body-file', bodyfile,
                                   '--label', label],
                                  capture_output=True, text=True)
        finally:                                       # the body can hold scrubbed-but-personal output
            with contextlib.suppress(OSError):
                os.unlink(bodyfile)
        if proc.returncode == 0:
            return 0, [f'configsys: filed — {proc.stdout.strip()}']
        lines.append(f'configsys: gh could not file it ({proc.stderr.strip() or "error"}).')
        # fall through to the link path so the work isn't lost

    # no gh (or gh failed): save the body and offer a prefilled new-issue link. When the body is short
    # enough to survive a URL, prefill it too so the browser opens fully populated; longer ones fall
    # back to open-the-link-and-paste (browsers/servers choke past ~8k of URL).
    out = ctx.paths.state_dir / save_as
    try:
        ctx.paths.state_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding='utf-8')
        saved = f'The full report is saved at {out}.'
    except OSError:
        saved = ''

    base = f'https://github.com/{REPORTS_REPO}/issues/new'
    fields = {'title': title, 'labels': label}
    with_body = f'{base}?' + urllib.parse.urlencode({**fields, 'body': body})
    if len(with_body) <= _URL_PREFILL_LIMIT:
        lines += ['configsys: no `gh` — open this and the issue is prefilled, ready to submit:',
                  f'  {with_body}']
        if saved:
            lines.append(f'({saved})')
    else:
        link = f'{base}?' + urllib.parse.urlencode(fields)
        lines += ['configsys: install `gh` to file automatically, or open this and paste the body:',
                  f'  {link}']
        if saved:
            lines.append(saved)
    return 0, lines


def _review_and_file(ctx, title, body, args, *, what='this report', label='install-report',
                     save_as='last-report.md', note=None):
    '''The one review-then-file step `report`, `request` and `request-os` share: print the scrubbed
    body, then (unless --print) ask before sending — a non-terminal without --yes refuses (rc 1), a
    no is "not sent" (rc 0). `note` = an extra line under the body.'''
    from .. import reportgen
    print('\n' + '=' * 72)
    print(f'{title}\n')
    print(body)
    print('=' * 72)
    if note:
        print(note)
    if getattr(args, 'print_only', False):
        return 0
    go = ask(f'\nSend {what} to {reportgen.REPORTS_REPO}? [y/N] ', yes=getattr(args, 'yes', False),
             refuse_note='\nconfigsys: not a terminal; re-run with --yes to file, or --print to just view.')
    if go is None:
        return 1
    if not go:
        print('configsys: not sent.')
        return 0
    return _send_report(ctx, title, body, label=label, save_as=save_as)


def _send_report(ctx, title, body, label='install-report', save_as='last-report.md'):
    '''CLI path: file the report/request and print the outcome. Returns 0 on success/handed-off.'''
    rc, lines = _file_issue(ctx, title, body, label, save_as)
    for ln in lines:
        print(ln)
    return rc


def cmd_report(ctx, args):
    from .. import reportgen
    saved = reportgen.load_failures(ctx.paths)             # list of failure records (this run)
    name = getattr(args, 'name', None)

    multi = None
    if name:
        # only attach a saved failure that's about the component we're reporting
        failure = next((f for f in saved if f.get('component') == name), None)
    elif len(saved) > 1:
        multi = saved                                      # no name + many failures -> report ALL
        failure = None
    elif len(saved) == 1:
        name, failure = saved[0].get('component'), saved[0]
    else:
        print('configsys: nothing to report — name a component (`configsys report <name>`) '
              'or run it after a failed install so the failure is captured.')
        return 1

    payload = (reportgen.collect(ctx, failures=multi) if multi
               else reportgen.collect(ctx, component=name, failure=failure))
    secrets = reportgen.secret_values(ctx.env)
    body = reportgen.render(payload, home=ctx.paths.home, secrets=secrets)
    title = reportgen.title(payload)

    return _review_and_file(ctx, title, body, args, note=None if failure or multi else (
        'note: no captured driver output (report either after a failed op, or paste it in).'))


def cmd_request(ctx, args):
    '''Ask upstream for a full cross-platform story for a component. Builds a coverage matrix
    (where it resolves today vs. where it's missing), shows the scrubbed body, and files it
    only on approval — same no-hidden-telemetry contract as `report`.'''
    from .. import reportgen
    name = getattr(args, 'name', None)
    if not name:
        print('configsys: name a component — `configsys request <name>`.')
        return 1

    payload = reportgen.request_payload(ctx, name)
    secrets = reportgen.secret_values(ctx.env)
    body = reportgen.render_request(payload, home=ctx.paths.home, secrets=secrets)
    title = reportgen.request_title(payload)

    return _review_and_file(ctx, title, body, args, what='this request', label=reportgen.REQUEST_LABEL,
                            save_as='last-request.md')


def cmd_request_os(ctx, args):
    '''Suggest THIS OS for inclusion, or report that a system update changed/broke it. Captures the
    detected os-release + how configsys currently maps it (block + native manager), shows the scrubbed
    body, and files it only on approval — same no-hidden-telemetry contract as report/request.'''
    from .. import reportgen
    payload = reportgen.os_request_payload(ctx)
    secrets = reportgen.secret_values(ctx.env)
    body = reportgen.render_os_request(payload, home=ctx.paths.home, secrets=secrets)
    title = reportgen.os_request_title(payload)

    return _review_and_file(ctx, title, body, args, what='this', label=reportgen.OS_REQUEST_LABEL,
                            save_as='last-os-request.md')
