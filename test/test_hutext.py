'''hutext — the one humon TEXT scanner and quoting rule every writer shares (plugins' section edits,
troveio's emit, humerge's merges): three quote styles, no escapes, comments that hide braces.'''

from configsys import hutext, layers


def test_scalar_picks_a_quote_style_the_value_does_not_contain():
    for v in ('plain', 'two words', 'say "hi"', "it's", 'both \' and "', 'C:\\dir\\'):
        assert layers.materialize_string('{ a: ' + hutext.scalar(v) + ' }') == {'a': v}
    assert hutext.scalar(True) == 'true' and hutext.scalar(None) == '""'


def test_the_scanner_steps_over_strings_and_comments_without_escapes():
    text = ('{\n  cmd: `echo \'{\'`  // a { brace\n  path: "C:\\\\"\n  /* } */ next: [ 1 2 ]\n'
            '  last: x\n}\n')
    start, end = hutext.section_span(text, 'next')
    assert text[start:end] == 'next: [ 1 2 ]'
    start, end = hutext.section_span(text, 'last')
    assert text[start:end].startswith('last: x')
    assert hutext.section_span(text, 'brace') is None                # inside a comment


def test_emit_writes_name_lists_on_one_line():
    assert hutext.emit({'desk': ['zsh', 'fish'], 'x': {}}, 0) == '{\n    desk: [ zsh  fish ]\n    x: {}\n}'
