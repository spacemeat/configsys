#!/usr/bin/env python3
'''docaudit — the mechanical half of the `/update-docs` audit (see
.claude/skills/update-docs/SKILL.md).

Documentation drifts the same few ways every time: a CLI flag or subcommand the docs never learned
about (or one they still teach after it was removed), a retired config keyword still in an example, a
plan doc that still says "NOT built" after it shipped, a renamed term used three different ways. The
judgment work — is this paragraph still TRUE? — belongs to the audit subagents. This tool gathers the
ground truth they check against, and catches the drift a script can catch, so no agent has to
re-derive the CLI from source.

Subcommands:
  facts      [--json]            ground truth extracted from the code: the CLI tree (every subcommand,
                                 option, help string), CONFIGSYS_* env vars read by the code, config
                                 keys + settings registry, component keys, drivers, OS blocks, TUI
                                 screens / keybindings / `?` help glossaries, component statuses
  inventory  [--json]            every markdown file: title, Status header, class (reference / plan /
                                 done / history), git created + last-changed dates, size
  check      [--json] [paths…]   mechanical drift findings (exit 1 if any error-level finding)
  glossary   --write | --check   render README.md's Glossary section from docs/glossary.hu

The vocabulary — every configsys term and the RETIRED terms with their replacements — lives in
docs/glossary.hu. `check` flags retired terms in live docs (docs/done/ and docs/history/ are
historical records and exempt), and the README glossary is generated from that file (test_docs.py
keeps it current, like test_manpages.py keeps the man pages).
'''

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GLOSSARY = ROOT / 'docs' / 'glossary.hu'
README = ROOT / 'README.md'
GLOSSARY_BEGIN = '<!-- glossary:begin'
GLOSSARY_END = '<!-- glossary:end -->'
# historical records: retired terms are expected there, and they're not maintained for accuracy
HISTORICAL = ('docs/done/', 'docs/history/', 'docs/review-')
SKIP_DIRS = {'.venv', '.git', 'node_modules', '__pycache__', '.pytest_cache'}


# -- markdown discovery -------------------------------------------------------

def markdown_files(root=ROOT):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith('.md'):
                out.append(Path(dirpath, f))
    return sorted(out)


def rel(p):
    return os.path.relpath(p, ROOT)


def is_historical(path):
    r = rel(path).replace(os.sep, '/')
    return any(r.startswith(h) for h in HISTORICAL)


# -- facts ------------------------------------------------------------------------

def cli_tree():
    '''[{command: 'config get', options: [{flags, help, default, choices}], positionals: [...],
    help: str}] for the root parser and every (nested) subcommand.'''
    from configsys.app import build_parser
    out = []

    def walk(parser, path, help_text):
        opts, pos, subs = [], [], []
        for a in parser._actions:
            if isinstance(a, argparse._SubParsersAction):
                helps = {ca.dest: ca.help for ca in a._choices_actions}
                for name, sp in a.choices.items():
                    subs.append((name, sp, helps.get(name, '')))
            elif isinstance(a, argparse._HelpAction):
                continue
            elif a.option_strings:
                opts.append({'flags': a.option_strings, 'help': a.help or '',
                             'default': None if a.default in (None, argparse.SUPPRESS) else str(a.default),
                             'choices': list(a.choices) if a.choices else None})
            else:
                pos.append({'name': a.dest, 'help': a.help or '', 'nargs': str(a.nargs) if a.nargs else None})
        out.append({'command': ' '.join(path), 'help': help_text or parser.description or '',
                    'options': opts, 'positionals': pos})
        seen = set()
        for name, sp, h in subs:
            if id(sp) in seen:                       # aliases share a parser
                continue
            seen.add(id(sp))
            walk(sp, path + [name], h)

    walk(build_parser(), [], '')
    return out


def env_vars():
    '''CONFIGSYS_* names the code reads (configsys/ + tools/).'''
    names = set()
    for base in (ROOT / 'configsys', ROOT / 'tools'):
        for p in base.rglob('*.py'):
            names.update(re.findall(r'CONFIGSYS_[A-Z0-9_]+', p.read_text(encoding='utf-8', errors='replace')))
    return sorted(n for n in names if not n.endswith('_'))


def config_facts():
    from configsys import actions, layers
    from configsys.routes import _COMPONENT_KEYS
    retired = getattr(layers, '_RETIRED_TOP_KEYS', {})
    return {
        'top_keys': sorted(layers._KNOWN_TOP_KEYS),
        'retired_top_keys': {k: str(v) for k, v in (retired.items() if isinstance(retired, dict) else
                                                     ((k, '') for k in retired))},
        'settings': {k: {'type': v[0], 'help': v[1] if len(v) > 1 else '',
                         'nature': actions.SETTING_NATURE.get(k)}
                     for k, v in actions.CONFIG_SETTINGS.items()},
        'component_keys': sorted(_COMPONENT_KEYS),
    }


def driver_facts():
    from configsys.drivers import _REGISTRY
    out = {}
    for name, cls in sorted(_REGISTRY.items()):
        doc = (sys.modules[cls.__module__].__doc__ or '').strip().split('\n')[0]
        out[name] = doc
    return out


def os_blocks():
    from configsys import routes
    cascade = routes.load(str(ROOT / 'routes.hu'))[0]
    return {b: {'parent': (spec or {}).get('using'), 'native': cascade.native(b)}
            for b, spec in sorted(cascade.blocks.items())}


def tui_facts():
    from configsys.tui import keyspec, menu, theme
    from configsys import layers
    keys = {}
    try:
        cfg = layers.materialize_string((ROOT / 'config.hu').read_text(encoding='utf-8'))
        keys = (cfg or {}).get('keys') or {}
    except Exception:                                    # noqa: BLE001
        pass
    helps = {}
    for screen, info in getattr(menu, '_HELP', {}).items():
        helps[screen] = {'desc': info.get('desc', ''),
                         'glossary': [t for t, _m in info.get('glossary', [])]}
    return {
        'screens': [{'key': k, 'id': i, 'title': t} for k, i, t in menu.SCREENS],
        'keys': keys,
        'action_labels': dict(keyspec.ACTION_LABELS),
        'help': helps,
        'statuses': sorted(theme.STATUS_COLOR),
    }


def facts():
    return {'cli': cli_tree(), 'env': env_vars(), 'config': config_facts(), 'drivers': driver_facts(),
            'os_blocks': os_blocks(), 'tui': tui_facts()}


# -- inventory ----------------------------------------------------------------------

_STATUS_RE = re.compile(r'^\s*(?:>\s*)?\**\s*status\s*\**\s*[:—-]\s*(.+)$', re.I)
_STATUS_WORDS = re.compile(r'\b(NOT BUILT|NOT YET BUILT|PLAN(?:NING)?(?: ONLY)?|SHIPPED|DONE|BUILT|'
                           r'SUPERSEDED|DEFERRED|IN PROGRESS|COMPLETE)\b')


def _git_dates(path):
    def run(args):
        r = subprocess.run(['git', '-C', str(ROOT)] + args, capture_output=True, text=True)
        return r.stdout.strip().splitlines()
    created = run(['log', '--follow', '--diff-filter=A', '--format=%as', '--', rel(path)])
    modified = run(['log', '-1', '--format=%as', '--', rel(path)])
    return (created[-1] if created else None), (modified[0] if modified else None)


def doc_class(path, status):
    r = rel(path).replace(os.sep, '/')
    if r.startswith('docs/done/'):
        return 'done'
    if r.startswith('docs/history/') or r.startswith('docs/review-'):
        return 'history'
    if not r.startswith('docs/'):
        return 'public' if r in ('README.md',) else 'meta'
    s = (status or '').upper()
    # a design/plan doc whose own header says it shipped or was superseded: a docs/done/ candidate
    if re.search(r'\b(HISTORICAL|SUPERSEDED)\b', s):
        return 'done?'
    if re.search(r'-plan\.md$', r) or 'PLAN' in s or 'NOT BUILT' in s:
        return 'plan'
    return 'reference'


def inventory():
    out = []
    for p in markdown_files():
        text = p.read_text(encoding='utf-8', errors='replace')
        lines = text.splitlines()
        title = next((l.lstrip('# ').strip() for l in lines if l.startswith('#')), '')
        status = None
        for l in lines[:25]:
            m = _STATUS_RE.match(l)
            if m:
                status = m.group(1).strip()
                break
        if status is None:                                # an all-caps status word near the top
            for l in lines[:12]:
                m = _STATUS_WORDS.search(l)
                if m:
                    status = l.strip()[:160]
                    break
        created, modified = _git_dates(p)
        out.append({'path': rel(p), 'title': title, 'status': status, 'class': doc_class(p, status),
                    'created': created, 'modified': modified, 'lines': len(lines)})
    return out


# -- glossary -----------------------------------------------------------------------

def load_glossary(path=GLOSSARY):
    from configsys import layers
    data = layers.materialize_string(Path(path).read_text(encoding='utf-8')) or {}
    return data.get('terms') or {}, data.get('retired') or {}


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def render_glossary(path=GLOSSARY):
    terms, retired = load_glossary(path)
    out = [f'{GLOSSARY_BEGIN} — generated from docs/glossary.hu by `tools/docaudit.py glossary --write`;',
           'edit that file, not this section -->', '']
    for term in sorted(terms, key=lambda t: t.lower().lstrip('.-`')):
        e = terms[term] or {}
        line = f'- **{term}**'
        if e.get('short'):
            line += f' ({e["short"]})'
        line += f' — {e.get("def", "").strip()}'
        see = _as_list(e.get('see'))
        if see:
            line += ' *See also:* ' + ', '.join(f'**{s}**' for s in see) + '.'
        avoid = _as_list(e.get('avoid'))
        if avoid:
            line += ' *Not:* ' + ', '.join(f'“{a}”' for a in avoid) + '.'
        out.append(line)
    if retired:
        out += ['', '**Retired terms** — you may still meet these in older docs (`docs/done/`) or configs:',
                '', '| retired | use instead | |', '|---|---|---|']
        for term in sorted(retired, key=str.lower):
            e = retired[term] or {}
            out.append(f'| `{term}` | {e.get("use", "")} | {e.get("why", "")} |')
    out += ['', GLOSSARY_END]
    return '\n'.join(out)


def glossary_section_in(readme_text):
    i = readme_text.find(GLOSSARY_BEGIN)
    j = readme_text.find(GLOSSARY_END)
    if i < 0 or j < 0:
        return None, i, j
    return readme_text[i:j + len(GLOSSARY_END)], i, j + len(GLOSSARY_END)


def glossary_cmd(write):
    text = README.read_text(encoding='utf-8')
    rendered = render_glossary()
    current, i, j = glossary_section_in(text)
    if current == rendered:
        print('glossary: README section is current')
        return 0
    if not write:
        print('glossary: README section is STALE (or missing) — run tools/docaudit.py glossary --write')
        return 1
    if current is None:
        text = text.rstrip('\n') + '\n\n## Glossary\n\n' + rendered + '\n'
    else:
        text = text[:i] + rendered + text[j:]
    README.write_text(text, encoding='utf-8')
    print('glossary: README section written')
    return 0


# -- check --------------------------------------------------------------------------

def _fd(level, kind, path, line, msg):
    return {'level': level, 'kind': kind, 'path': path, 'line': line, 'msg': msg}


_LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
_FENCE_RE = re.compile(r'^(```+|~~~+)\s*([\w+-]*)')


def _fenced_blocks(lines):
    '''[(lang, start_line_1based, [lines])]'''
    out, cur, lang, start, fence = [], None, '', 0, ''
    for n, l in enumerate(lines, 1):
        m = _FENCE_RE.match(l.strip())
        if cur is None and m:
            cur, lang, start, fence = [], m.group(2).lower(), n, m.group(1)
        elif cur is not None and l.strip().startswith(fence[:3]):
            out.append((lang, start, cur))
            cur = None
        elif cur is not None:
            cur.append(l)
    return out


def _check_links(path, lines):
    out = []
    for n, l in enumerate(lines, 1):
        for target in _LINK_RE.findall(l):
            if re.match(r'^[a-z]+:', target) or target.startswith('#'):
                continue
            t = target.split('#', 1)[0]
            if t and not (path.parent / t).exists():
                out.append(_fd('error', 'broken-link', rel(path), n, f'link target {target!r} does not exist'))
    return out


def _check_retired(path, lines, retired):
    out = []
    pats = []
    for term, e in retired.items():
        e = e or {}
        pat = e.get('match') or (re.escape(term) if not re.match(r'^\w', term) else r'(?<![\w-])' + re.escape(term) + r'(?![\w-])')
        pats.append((term, re.compile(pat), e.get('use', '')))
    gl_begin = next((i for i, l in enumerate(lines, 1) if l.startswith(GLOSSARY_BEGIN)), None)
    gl_end = next((i for i, l in enumerate(lines, 1) if l.startswith(GLOSSARY_END)), None)
    for n, l in enumerate(lines, 1):
        if gl_begin and gl_end and gl_begin <= n <= gl_end:
            continue                                     # the generated glossary NAMES the retired terms
        # a mention that NARRATES the retirement ("replaced the old `prefer:`", "those names are gone")
        # is correct history, not drift — judged on the line and its neighbours
        window = ' '.join(lines[max(0, n - 2):n + 1]).lower()
        if _RETIREMENT_WORDS.search(window):
            continue
        for term, rx, use in pats:
            if rx.search(l):
                out.append(_fd('warn', 'retired-term', rel(path), n,
                               f'retired term {term!r}' + (f' — use {use}' if use else '')))
    return out


_RETIREMENT_WORDS = re.compile(r'\b(retired|formerly|replaced|replaces|gone|renamed|deleted|removed|'
                               r'superseded|predates|no longer|instead of|used to|was |were |old )')


def _check_examples(path, lines, parser):
    '''`configsys …` lines inside fenced code blocks must parse against the real CLI.'''
    out = []
    for lang, start, block in _fenced_blocks(lines):
        if lang not in ('', 'sh', 'bash', 'shell', 'console', 'text'):
            continue
        for k, l in enumerate(block):
            s = l.strip().lstrip('$').strip()
            if not s.startswith('configsys ') or any(c in s for c in '<>[]…|'):
                continue
            s = s.split(' #', 1)[0]
            try:
                args = shlex.split(s)[1:]
            except ValueError:
                continue
            try:
                parser.parse_args(args)
            except SystemExit:
                out.append(_fd('error', 'bad-example', rel(path), start + k + 1,
                               f'example does not parse against the CLI: {s!r}'))
            except Exception:                            # noqa: BLE001
                pass
    return out


def _check_hu(path, lines):
    from configsys import layers
    out = []
    for lang, start, block in _fenced_blocks(lines):
        if lang not in ('hu', 'humon'):
            continue
        text = '\n'.join(block)
        if '…' in text or '...' in text:
            continue                                     # an elided illustration, not a parseable doc
        ok = False
        for candidate in (text, '{\n' + text + '\n}'):
            try:
                layers.materialize_string(candidate)
                ok = True
                break
            except Exception:                            # noqa: BLE001
                continue
        if not ok:
            out.append(_fd('warn', 'bad-humon', rel(path), start, 'humon snippet does not parse '
                           '(alone or wrapped in { }) — fix it, or mark it elided with …'))
    return out


def check(paths=None):
    from configsys.app import build_parser
    terms, retired = load_glossary()
    findings = []
    files = [Path(p).resolve() for p in paths] if paths else markdown_files()
    parser = build_parser()
    for p in files:
        lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
        findings += _check_links(p, lines)
        if not is_historical(p):
            findings += _check_retired(p, lines, retired)
            findings += _check_examples(p, lines, parser)
            findings += _check_hu(p, lines)
    # whole-project consistency (only for a full run)
    if not paths:
        findings += _check_cli_coverage()
        findings += _check_env_coverage()
        findings += _check_settings_coverage()
        findings += _check_status_headers()
        findings += _check_help_retired(retired)
        findings += _check_manpages()
        current, _i, _j = glossary_section_in(README.read_text(encoding='utf-8'))
        if current != render_glossary():
            findings.append(_fd('error', 'glossary-stale', 'README.md', None,
                                'README glossary section is stale/missing — tools/docaudit.py glossary --write'))
    return findings


def _public_text():
    parts = [README.read_text(encoding='utf-8')]
    for p in (ROOT / 'docs').glob('*.md'):
        parts.append(p.read_text(encoding='utf-8', errors='replace'))
    return '\n'.join(parts)


def _command_mentions(text):
    '''[(line_no, "configsys …")] — command lines from inline code spans and fenced code blocks (prose
    like "configsys works" is not a command).'''
    lines = text.splitlines()
    out = []
    for lang, start, block in _fenced_blocks(lines):
        for k, l in enumerate(block):
            s = l.strip().lstrip('$').strip()
            if s.startswith('configsys '):
                out.append((start + k + 1, s.split(' #', 1)[0]))
    for n, l in enumerate(lines, 1):
        for span in re.findall(r'`([^`]+)`', l):
            if span.strip().startswith('configsys '):
                out.append((n, span.strip()))
    return out


def _check_cli_coverage():
    out = []
    readme = README.read_text(encoding='utf-8')
    tree = cli_tree()
    known = {c['command'].split(' ')[0] for c in tree if c['command']}
    flags = {f for c in tree for o in c['options'] for f in o['flags']}
    mentioned = set()
    for n, cmd in _command_mentions(readme):
        words = [w for w in cmd.split()[1:]]
        sub = next((w for w in words if not w.startswith('-')), None)
        if sub and re.match(r'^[a-z][\w-]*$', sub):
            mentioned.add(sub)
            if sub not in known:
                out.append(_fd('error', 'cli-unknown', 'README.md', n, f'`configsys {sub}` is not a subcommand'))
        for f in re.findall(r'(?<![\w-])(--[a-z][\w-]+)', cmd):
            if f not in flags:
                out.append(_fd('warn', 'cli-unknown-flag', 'README.md', n, f'flag {f} is not a configsys option'))
    for cmd in sorted(known - mentioned):
        if not re.search(r'`' + re.escape(cmd) + r'\b', readme):
            out.append(_fd('warn', 'cli-undocumented', 'README.md', None, f'subcommand `{cmd}` is never mentioned'))
    return out


def _check_env_coverage():
    text = _public_text()
    return [_fd('warn', 'env-undocumented', 'README.md', None, f'{v} is read by the code but never documented')
            for v in env_vars() if v not in text]


def _check_settings_coverage():
    out = []
    cf = config_facts()
    text = (ROOT / 'docs' / 'config-format.md').read_text(encoding='utf-8', errors='replace') \
        if (ROOT / 'docs' / 'config-format.md').exists() else ''
    for k in sorted(set(cf['top_keys'])):
        if not re.search(r'(?<![\w-])' + re.escape(k) + r'(?![\w-])', text):
            out.append(_fd('warn', 'setting-undocumented', 'docs/config-format.md', None,
                           f'config key `{k}:` is never documented (it feeds configsys.hu(5))'))
    return out


def _check_status_headers():
    out = []
    for d in inventory():
        if d['class'] in ('plan', 'reference', 'done?') and d['path'].startswith('docs/') and not d['status']:
            out.append(_fd('warn', 'no-status', d['path'], 1, 'docs/ file has no Status header'))
    return out


def _check_help_retired(retired):
    '''Retired terms inside the CLI help strings (-> configsys(1)) and the TUI `?` help text.'''
    out = []
    blobs = [(f'argparse: configsys {c["command"]}'.strip(), ' '.join([c['help']] + [o['help'] for o in c['options']]))
             for c in cli_tree()]
    from configsys.tui import menu
    for screen, info in getattr(menu, '_HELP', {}).items():
        blobs.append((f'TUI ? help: {screen}', info.get('desc', '') + ' ' +
                      ' '.join(f'{t} {m}' for t, m in info.get('glossary', []))))
    for where, text in blobs:
        for term, e in retired.items():
            e = e or {}
            pat = e.get('match') or (r'(?<![\w-])' + re.escape(term) + r'(?![\w-])')
            if re.search(pat, text or ''):
                out.append(_fd('warn', 'retired-term', where, None,
                               f'retired term {term!r}' + (f' — use {e.get("use")}' if e.get('use') else '')))
    return out


def _check_manpages():
    r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'gen_manpages.py'), '--check'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [_fd('error', 'manpage-stale', 'man/', None, 'man pages are stale — run tools/gen_manpages.py')]
    return []


# -- CLI ----------------------------------------------------------------------------

def _print_findings(findings):
    order = {'error': 0, 'warn': 1, 'info': 2}
    for f in sorted(findings, key=lambda f: (order[f['level']], f['kind'], f['path'], f['line'] or 0)):
        loc = f['path'] + (f':{f["line"]}' if f['line'] else '')
        print(f'{f["level"]:5} {f["kind"]:20} {loc:40} {f["msg"]}')
    by = {}
    for f in findings:
        by[f['level']] = by.get(f['level'], 0) + 1
    print(f'\n{len(findings)} finding(s): ' + ', '.join(f'{v} {k}' for k, v in sorted(by.items())))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('facts')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('inventory')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('check')
    p.add_argument('--json', action='store_true')
    p.add_argument('paths', nargs='*')
    p = sub.add_parser('glossary')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', action='store_true')
    g.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'facts':
        f = facts()
        if a.json:
            print(json.dumps(f, indent=1, default=str))
        else:
            print(f'CLI: {len(f["cli"])} commands/subcommands; env: {len(f["env"])} CONFIGSYS_* vars; '
                  f'config: {len(f["config"]["top_keys"])} top keys, {len(f["config"]["settings"])} settings; '
                  f'drivers: {len(f["drivers"])}; OS blocks: {len(f["os_blocks"])}; '
                  f'TUI: {len(f["tui"]["screens"])} screens, {len(f["tui"]["help"])} `?` pages')
        return 0
    if a.cmd == 'inventory':
        inv = inventory()
        if a.json:
            print(json.dumps(inv, indent=1))
        else:
            for d in inv:
                print(f'{d["class"]:9} {d["created"] or "?":10} {d["modified"] or "?":10} {d["lines"]:5}  '
                      f'{d["path"]:45} {(d["status"] or "")[:70]}')
        return 0
    if a.cmd == 'check':
        findings = check(a.paths or None)
        if a.json:
            print(json.dumps(findings, indent=1))
        else:
            _print_findings(findings)
        return 1 if any(f['level'] == 'error' for f in findings) else 0
    return glossary_cmd(a.write)


if __name__ == '__main__':
    sys.exit(main())
