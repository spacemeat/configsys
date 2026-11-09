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
    assert text[start:end] == 'last: x'
    assert hutext.section_span(text, 'brace') is None                # inside a comment


def test_emit_writes_name_lists_on_one_line():
    assert hutext.emit({'desk': ['zsh', 'fish'], 'x': {}}, 0) == '{\n    desk: [ zsh  fish ]\n    x: {}\n}'


# -- review-2026-11-2 A2: a scalar edit ends at its value, never at the end of the line ---------------

def test_a_quoted_scalar_span_is_the_value_not_the_next_line():
    text = '{\n    machine: "laptop"\n    picks: { laptop: [ btop  ripgrep ] }\n}\n'
    start, end = hutext.section_span(text, 'machine')
    assert text[start:end] == 'machine: "laptop"'


def test_a_bare_scalar_mid_line_keeps_its_neighbours_and_comment():
    text = '{ scope: user  machine: laptop  picks: { laptop: [ btop ] } }'
    start, end = hutext.section_span(text, 'scope')
    assert text[start:end] == 'scope: user'
    text = '{\n    scope: user  // keep me\n}\n'
    start, end = hutext.section_span(text, 'scope')
    assert text[start:end] == 'scope: user'


def test_comment_openers_inside_a_value_force_quotes():
    for v in ('/home/u/apps//ripgrep', '/opt/x/*', 'a//b'):
        assert layers.materialize_string('{ a: ' + hutext.scalar(v) + ' }') == {'a': v}
    assert hutext.scalar('/opt/x') == '/opt/x'                         # plain paths stay bare


def test_root_close_skips_a_brace_inside_a_trailing_comment():
    text = '{\n    scope: user\n}\n// trailing } comment\n'
    assert text[hutext.root_close(text)] == '}' and hutext.root_close(text) == text.index('}')
    assert hutext.root_close('') is None and hutext.root_close('// only a comment\n') is None


def test_remove_span_finds_the_key_not_an_earlier_copy_in_a_comment():
    text = '{\n    // pins: { steam: flatpak }\n    scope: user\n    pins: { steam: flatpak }\n}\n'
    start, end = hutext.remove_span(text, 'pins')
    assert text[:start] + text[end:] == '{\n    // pins: { steam: flatpak }\n    scope: user\n}\n'
