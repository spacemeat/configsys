'''Docs integrity: README's Glossary is generated from docs/glossary.hu (like the man pages from their
sources), the glossary is internally consistent, and tools/docaudit.py's mechanical checks behave.
The full drift audit (`docaudit.py check`) is the /update-docs skill's job, not CI's.'''

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('docaudit', HERE.parent / 'tools' / 'docaudit.py')
da = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(da)


def test_readme_glossary_is_generated_current():
    current, _i, _j = da.glossary_section_in(da.README.read_text(encoding='utf-8'))
    assert current == da.render_glossary(), 'run: tools/docaudit.py glossary --write'


def test_glossary_entries_are_complete_and_cross_references_resolve():
    terms, retired = da.load_glossary()
    assert len(terms) >= 40
    for term, e in terms.items():
        assert (e or {}).get('def'), f'{term}: no def'
        for s in da._as_list((e or {}).get('see')):
            assert s in terms, f'{term}: see-also {s!r} is not an entry'
    for term, e in retired.items():
        assert (e or {}).get('use'), f'retired {term}: no replacement'


def test_retired_term_check_skips_narration(tmp_path):
    p = tmp_path / 'x.md'
    p.write_text('Write `prefer: 5` to rank a method.\n\n\n\nIt replaced the old `prefer:` knob.\n')
    lines = p.read_text().splitlines()
    retired = {'prefer:': {'use': '`standing:`'}}
    hits = da._check_retired(p, lines, retired)
    assert [h['line'] for h in hits] == [1]            # line 5 narrates the retirement


def test_command_mentions_ignore_prose_and_check_flags():
    text = ('configsys works on many distros.\n'
            'Run `configsys pin set yazi tarball` then:\n'
            '```\n$ configsys --pretend install ripgrep\n```\n')
    cmds = [c for _n, c in da._command_mentions(text)]
    assert cmds == ['configsys --pretend install ripgrep', 'configsys pin set yazi tarball']


def test_broken_links_and_humon_snippets(tmp_path):
    (tmp_path / 'real.md').write_text('# real\n')
    p = tmp_path / 'doc.md'
    p.write_text('[ok](real.md) [web](https://x.org) [anchor](#a) [gone](missing.md)\n'
                 '```hu\nfoo: { install: [ { via: native } ] }\n```\n'
                 '```hu\nfoo: { install: [ via: native  bad: ] } }\n```\n'
                 '```hu\nfoo: { … }\n```\n')
    lines = p.read_text().splitlines()
    assert [f['msg'] for f in da._check_links(p, lines)] == ["link target 'missing.md' does not exist"]
    bad = da._check_hu(p, lines)
    assert [f['line'] for f in bad] == [5]             # the 2nd block; the elided 3rd is skipped


def test_examples_must_parse_against_the_cli(tmp_path):
    from configsys.app import build_parser
    p = tmp_path / 'doc.md'
    p.write_text('```sh\nconfigsys inspect\nconfigsys no-such-command\nconfigsys pin set <comp> <via>\n```\n')
    found = da._check_examples(p, p.read_text().splitlines(), build_parser())
    assert [f['line'] for f in found] == [3]           # placeholders (<…>) are skipped


def test_inventory_classifies_docs():
    by = {d['path']: d for d in da.inventory()}
    assert by['README.md']['class'] == 'public'
    assert by['docs/principles.md']['class'] == 'reference'
    assert by['docs/principles.md']['created']          # git history recovers the creation date


def test_inventory_dates_come_from_one_git_walk(monkeypatch):
    # tests-tools-13: one `git log` for every doc, not two per file
    real, calls = da.subprocess.run, []
    monkeypatch.setattr(da.subprocess, 'run', lambda *a, **k: calls.append(a) or real(*a, **k))
    da.inventory()
    assert len(calls) == 1


def test_git_dates_follow_a_rename_back_to_the_first_add():
    log = ('@2026-11-02\nM\tdocs/done/x-plan.md\n'
           '@2026-10-01\nR100\tdocs/todo/x-plan.md\tdocs/done/x-plan.md\n'
           '@2026-09-15\nM\tdocs/todo/x-plan.md\nA\tdocs/y.md\n'
           '@2026-09-01\nA\tdocs/todo/x-plan.md\n')
    dates = da._parse_git_dates(log)
    assert dates['docs/done/x-plan.md'] == ('2026-09-01', '2026-11-02')
    assert dates['docs/y.md'] == ('2026-09-15', '2026-09-15')


def test_a_global_value_option_is_not_the_subcommand():
    # tests-tools-12: `configsys --os fedora where steam` documents `where`, not a `fedora` command
    assert da._subcommand(['--os', 'fedora', 'where', 'steam']) == 'where'
    assert da._subcommand(['--home=/tmp/h', '--pretend', 'install', 'x']) == 'install'
    assert da._subcommand(['--machine', 'laptop']) is None


def test_cli_coverage_accepts_global_options_in_examples(tmp_path, monkeypatch):
    readme = tmp_path / 'README.md'
    readme.write_text('Run `configsys --os fedora where steam`.\n')
    monkeypatch.setattr(da, 'README', readme)
    assert not [f for f in da._check_cli_coverage() if f['kind'] == 'cli-unknown']


def test_a_help_example_parses_and_prints_nothing(tmp_path, capsys):
    from configsys.app import build_parser
    p = tmp_path / 'doc.md'
    p.write_text('```sh\nconfigsys plugin --help\n```\n')
    assert da._check_examples(p, p.read_text().splitlines(), build_parser()) == []
    out = capsys.readouterr()
    assert out.out == '' and out.err == ''              # `check --json` stays valid JSON


def test_a_generic_was_beside_a_retired_term_does_not_hide_it(tmp_path):
    p = tmp_path / 'x.md'
    p.write_text('Add your install list to `configs:`.\nThat was the easy part.\n')
    _terms, retired = da.load_glossary()
    hits = da._check_retired(p, p.read_text().splitlines(), retired)
    assert [h['line'] for h in hits] == [1]
