#!/usr/bin/env python3
'''Generate configsys' man pages, single-sourced — no external dependencies:

  man/configsys.1      from the argparse parser (configsys.app.build_parser)
  man/configsys.hu.5   from docs/config-format.md (a controlled Markdown subset)

Usage:
  python3 tools/gen_manpages.py           # (re)write both pages
  python3 tools/gen_manpages.py --check   # exit 1 if either is stale (for CI/tests)

The checked-in pages are what `configsys manpages install` ships; test/test_manpages.py
runs --check so they can't drift from the parser or the Markdown source.
'''

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

MAN1 = os.path.join(ROOT, 'man', 'configsys.1')
MAN5 = os.path.join(ROOT, 'man', 'configsys.hu.5')
CONFIG_MD = os.path.join(ROOT, 'docs', 'config-format.md')


# -- troff helpers --------------------------------------------------------

def _inline(s):
    '''Inline Markdown -> troff. Escape literal backslashes first, then wrap markup.'''
    s = s.replace('\\', '\\e')
    s = re.sub(r'\*\*(.+?)\*\*', r'\\fB\1\\fR', s)          # **bold**
    s = re.sub(r'`([^`]+)`', r'\\fB\1\\fR', s)              # `code`
    s = re.sub(r'(?<!\*)\*([^*\s][^*]*?)\*(?!\*)', r'\\fI\1\\fR', s)   # *italic*
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)          # [text](link) -> text
    if s[:1] in ('.', "'"):                                 # a line can't start with a control char
        s = '\\&' + s
    return s


def _code(line):
    '''Escape a verbatim code line for a .nf block.'''
    line = line.replace('\\', '\\e')
    return ('\\&' + line) if line[:1] in ('.', "'") else line


def _th(name, section, desc):
    return f'.TH {name.upper()} {section} "" "configsys" "{desc}"'


# -- section 1: from the argparse parser ----------------------------------

def _subparsers(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a
    return None


def gen_man1():
    from configsys.app import build_parser
    p = build_parser()
    out = [_th('configsys', '1', 'User Commands')]
    out += ['.SH NAME', 'configsys \\- ' + _inline(p.description.split('.')[0])]
    out += ['.SH SYNOPSIS',
            '.B configsys', '[\\fIoptions\\fR] [\\fIcommand\\fR] [\\fIargs\\fR ...]']
    out += ['.SH DESCRIPTION', _inline(p.description)]

    out.append('.SH OPTIONS')
    for act in p._actions:
        if not act.option_strings or act.help == argparse.SUPPRESS:
            continue
        names = ', '.join('\\fB' + o + '\\fR' for o in act.option_strings)
        meta = (' \\fI' + act.metavar + '\\fR') if act.metavar else ''
        out += ['.TP', names + meta, _inline(act.help or '')]

    sub = _subparsers(p)
    help_of = {a.dest: a.help for a in sub._choices_actions}
    out.append('.SH COMMANDS')
    for name, sp in sub.choices.items():
        out += ['.TP', '\\fB' + name + '\\fR', _inline(sp.description or help_of.get(name) or '')]
        nsub = _subparsers(sp)                          # one level of subcommands (plugin, dotfiles)
        if nsub is not None and nsub.choices:
            names = ', '.join('\\fB' + n + '\\fR' for n in nsub.choices)
            out += ['.RS', '.PP', 'Subcommands: ' + names + '.', '.RE']

    # epilog carries the examples + environment blocks — split on the two labels
    epi = p.epilog or ''
    for label, heading in (('examples:', 'EXAMPLES'), ('environment:', 'ENVIRONMENT')):
        m = re.search(rf'(?ms)^{label}\n(.*?)(?=\n\w+:\n|\Z)', epi)
        if m:
            out += [f'.SH {heading}', '.nf'] + [_code(l) for l in m.group(1).rstrip().splitlines()] + ['.fi']

    out += ['.SH FILES',
            '.TP', '\\fB~/.config/configsys/configsys.hu\\fR', 'per-machine config (profiles, pins, plugins).',
            '.TP', '\\fB~/.config/configsys/dotfiles/\\fR', 'machine-local dotfiles content store (see dotfiles capture).',
            '.TP', '\\fB~/.config/configsys/plugins/\\fR', 'synced plugin repos (one dir per plugin).',
            '.TP', '\\fB~/.config/configsys/plugin-trust.hu\\fR', 'approved content hashes for code plugins.',
            '.TP', '\\fB~/.config/configsys/state.hu\\fR', 'ledger: version-lock intent + bookkeeping.',
            '.TP', '\\fB~/.config/configsys/versions.hu\\fR', 'discovered-version cache (24h TTL).']
    out += ['.SH SEE ALSO', '.BR configsys.hu (5)']
    return '\n'.join(out) + '\n'


# -- section 5: from docs/config-format.md --------------------------------

def gen_man5():
    with open(CONFIG_MD, encoding='utf-8') as f:
        md = f.read()
    out = [_th('configsys.hu', '5', 'File Formats')]
    para, in_code, seen_h1, bullet = [], False, False, [False]

    def flush():
        if para:
            out.append('.IP \\(bu 2' if bullet[0] else '.PP')
            out.append(_inline(' '.join(para)))
            para.clear()

    def head(*emit):                               # flush, end any bullet, emit heading
        flush()
        bullet[0] = False
        out.extend(emit)

    for line in md.splitlines():
        if line.startswith('```'):
            head(*(['.fi', '.RE'] if in_code else ['.PP', '.RS 4', '.nf']))
            in_code = not in_code
            continue
        if in_code:
            out.append(_code(line))
            continue
        if line.startswith('# '):
            if not seen_h1:                        # the H1 title becomes NAME
                seen_h1 = True
                head('.SH NAME', 'configsys.hu \\- ' + _inline(line[2:]))
            else:
                head('.SH ' + _inline(line[2:]).upper())
            continue
        if line.startswith('## '):
            head('.SH ' + _inline(line[3:]).upper())
            continue
        if line.startswith('### '):
            head('.SS ' + _inline(line[4:]))
            continue
        m = re.match(r'\s*[-*]\s+(.*)', line)
        if m:                                      # new bullet: flush the previous, start fresh
            flush()
            bullet[0] = True
            para.append(m.group(1))
            continue
        if not line.strip():                       # blank line ends the current block
            flush()
            bullet[0] = False
            continue
        para.append(line.strip())                  # a continuation line joins the current block
    flush()
    return '\n'.join(out) + '\n'


# -- driver ---------------------------------------------------------------

def _write_or_check(path, content, check):
    existing = None
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            existing = f.read()
    if check:
        return existing == content
    if existing != content:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    return True


def main():
    ap = argparse.ArgumentParser(description='generate the configsys man pages')
    ap.add_argument('--check', action='store_true', help='exit 1 if a page is stale (no writes)')
    args = ap.parse_args()
    ok1 = _write_or_check(MAN1, gen_man1(), args.check)
    ok5 = _write_or_check(MAN5, gen_man5(), args.check)
    if args.check and not (ok1 and ok5):
        stale = [p for p, ok in ((MAN1, ok1), (MAN5, ok5)) if not ok]
        print('stale man pages (run tools/gen_manpages.py): ' + ', '.join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
