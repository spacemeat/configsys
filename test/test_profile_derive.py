'''The `^derive` profile primitive (step 1: semantics + lints). `^q` offers q's members as an opt-in
MENU contributing NO members; bare names are PICKS, `~name` a DECLINE, a menu item that is neither is
NEW. menu(^p) = members(p); multi-parent unions; derivation-of-derivation narrows; `^self` derives the
next-lower layer. See docs/profiles-derive-plan.md.'''

import pytest

from configsys import layers
from configsys.config import Config
from configsys.errors import ConfigError


def _cfg(text):
    return Config([layers.Layer('config.hu', 'repo', layers.materialize_string(text))])


def _layered(*specs):   # (role, text) low->high
    return Config([layers.Layer(f'{r}.hu', r, layers.materialize_string(t)) for r, t in specs])


BASE = '''{
  profiles: {
    ai-tools:    [ claude-code  ollama  aider  codex ]
    python-lang: [ python3  pip ]
    ocaml-lang:  [ ocaml  dune ]
    langs:       [ +python-lang  +ocaml-lang ]
  }
}'''


def test_derive_picks_declines_and_new():
    c = _cfg(BASE.replace('}\n}', '  ts-ai: [ "^ai-tools"  claude-code  ollama  ~aider ]\n  }\n}'))
    assert sorted(c.profile_components('ts-ai')) == ['claude-code', 'ollama']    # picks only
    assert sorted(c.profile_menu('ts-ai')) == ['aider', 'claude-code', 'codex', 'ollama']
    assert c.profile_new('ts-ai') == {'codex'}                                   # not picked, not declined
    assert 'aider' not in c.profile_new('ts-ai')                                 # declined -> quiet
    assert c.is_derived('ts-ai') and not c.is_derived('ai-tools')


def test_derive_contributes_no_members():
    # a `^q` with NO bare picks yields an all-menu, zero-member profile (a starting point)
    c = _cfg(BASE.replace('}\n}', '  empty: [ "^ai-tools" ]\n  }\n}'))
    assert c.profile_components('empty') == []
    assert len(c.profile_menu('empty')) == 4


def test_multi_parent_menu_is_a_union():
    c = _cfg(BASE.replace('}\n}', '  laptop: [ "^python-lang"  "^ocaml-lang"  python3  dune ]\n  }\n}'))
    assert sorted(c.profile_menu('laptop')) == ['dune', 'ocaml', 'pip', 'python3']
    assert sorted(c.profile_components('laptop')) == ['dune', 'python3']
    assert c.profile_new('laptop') == {'ocaml', 'pip'}


def test_derive_from_an_aggregate_offers_its_sub_profiles_as_units():
    # A-hierarchical: `^langs` where langs = [+python-lang +ocaml-lang] offers those SUB-PROFILES as
    # UNITS (structural), not the flattened components. Deriving a sub-unit recurses into it.
    c = _cfg(BASE.replace('}\n}', '  ts-langs: [ "^langs"  python3 ]\n  }\n}'))
    assert sorted(c.profile_menu('ts-langs')) == ['ocaml-lang', 'python-lang']   # sub-units, not comps
    assert c.profile_menu_items('ts-langs') == {'subprofiles': {'python-lang', 'ocaml-lang'},
                                                'components': set()}
    assert c.profile_new('ts-langs') == {'python-lang', 'ocaml-lang'}            # both offered as units


NESTED = '''{
  profiles: {
    java-lang:   [ jdk ]
    kotlin-lang: [ kotlin ]
    jvm-lang:    [ +java-lang  +kotlin-lang ]
    py-lang:     [ python3  pip ]
    langs:       [ +jvm-lang  +py-lang  perl ]
  }
}'''


def test_structural_menu_mixes_sub_units_and_components():
    c = _cfg(NESTED.replace('}\n}', '  ts: [ "^langs" ]\n  }\n}'))
    items = c.profile_menu_items('ts')
    assert items == {'subprofiles': {'jvm-lang', 'py-lang'}, 'components': {'perl'}}
    assert c.profile_new('ts') == {'jvm-lang', 'py-lang', 'perl'}     # all offered, nothing engaged
    assert c.profile_components('ts') == []                            # ^ contributes no members


def test_deriving_a_sub_unit_recurses_and_resolves_it():
    # `^jvm-lang` drops jvm-lang out of NEW and offers ITS children (java-lang, kotlin-lang) as NEW.
    c = _cfg(NESTED.replace('}\n}', '  ts: [ "^langs"  "^jvm-lang" ]\n  }\n}'))
    items = c.profile_menu_items('ts')
    assert items['subprofiles'] == {'jvm-lang', 'py-lang', 'java-lang', 'kotlin-lang'}
    assert c.profile_new('ts') == {'py-lang', 'perl', 'java-lang', 'kotlin-lang'}   # jvm-lang engaged
    assert 'jvm-lang' not in c.profile_new('ts')


def test_new_sub_profile_upstream_shows_as_a_unit():
    # ts derives langs and has engaged every current child; when langs gains a NEW sub-profile
    # upstream, it surfaces as a NEW unit (not auto-installed) — the headline A-hierarchical win.
    settled = NESTED.replace('}\n}',
                             '  ts: [ "^langs"  ~jvm-lang  ~py-lang  ~perl ]\n  }\n}')
    assert _cfg(settled).profile_new('ts') == set()                   # all current children engaged
    grown = (NESTED.replace('py-lang:     [ python3  pip ]',
                            'py-lang:     [ python3  pip ]\n    go-lang:     [ go ]')
                   .replace('+jvm-lang  +py-lang  perl', '+jvm-lang  +py-lang  +go-lang  perl')
                   .replace('}\n}', '  ts: [ "^langs"  ~jvm-lang  ~py-lang  ~perl ]\n  }\n}'))
    assert _cfg(grown).profile_new('ts') == {'go-lang'}               # the new sub-profile, offered


def test_mention_removes_a_sub_from_new():
    base = NESTED.replace('}\n}', '  ts: [ "^langs"  {X} ]\n  }\n}')
    assert 'jvm-lang' not in _cfg(base.replace('{X}', '~jvm-lang')).profile_new('ts')   # excluded
    assert 'jvm-lang' not in _cfg(base.replace('{X}', '+jvm-lang')).profile_new('ts')   # included whole
    assert 'jvm-lang' not in _cfg(base.replace('{X}', '"^jvm-lang"')).profile_new('ts')  # derived


def test_derivation_of_a_derivation_narrows():
    # menu(^p) = members(p), NOT menu(p): deriving from a derived profile offers only its PICKS.
    text = BASE.replace('}\n}',
                        '  ts-langs: [ "^langs"  python3 ]\n'
                        '  desk-langs: [ "^ts-langs" ]\n  }\n}')
    c = _cfg(text)
    assert c.profile_menu('desk-langs') == {'python3'}          # ts-langs' pick, not all of langs
    assert c.profile_components('desk-langs') == []
    assert c.profile_new('desk-langs') == {'python3'}


def test_self_derive_over_layers_and_open_discovery():
    # a user layer pins the repo profile with ^self: repo growth is OFFERED (NEW), never applied.
    user = ('user', '{ profiles: { dev: [ "^dev"  gh  lazygit  ~git ] } }')
    c1 = _layered(('repo', '{ profiles: { dev: [ gh  git  lazygit ] } }'), user)
    assert sorted(c1.profile_components('dev')) == ['gh', 'lazygit']    # picks
    assert sorted(c1.profile_menu('dev')) == ['gh', 'git', 'lazygit']  # ^self -> repo's members
    assert c1.profile_new('dev') == set()                              # git declined
    c2 = _layered(('repo', '{ profiles: { dev: [ gh  git  lazygit  jq ] } }'), user)   # repo grows
    assert c2.profile_new('dev') == {'jq'}                             # offered, not a member
    assert 'jq' not in c2.profile_components('dev')


def test_open_decline_of_a_subprofile_stays_declined_when_it_grows():
    def build(extra):
        return _cfg('{ profiles: { '
                    f'jvm-lang: [ java  scala{extra} ]  '
                    'langs: [ +jvm-lang  python3 ]  '
                    'mine: [ "^langs"  python3  ~jvm-lang ] } }')
    assert build('').profile_new('mine') == set()          # java/scala declined via ~jvm-lang
    grown = build('  kotlin')                               # jvm-lang gains kotlin
    assert grown.profile_new('mine') == set()              # still declined (open decline), not NEW
    assert 'kotlin' not in grown.profile_components('mine')


def test_derive_terms_and_layout_entry():
    c = _cfg(BASE.replace('}\n}', '  m: [ "^ai-tools"  claude-code  ~aider ]\n  }\n}'))
    assert c.profile_derive_terms('m') == ['ai-tools']
    layout = c.profile_layout('m')
    assert ('derive', 'ai-tools') in layout                 # not mistaken for a component
    assert ('component', 'claude-code') in layout
    assert not any(kind == 'component' and ref.startswith('^') for kind, ref in layout)


def test_check_derives_raises_on_undefined():
    c = _cfg('{ profiles: { x: [ "^nope" ] } }')
    with pytest.raises(ConfigError):
        c.check_derives('x')
    assert c.profile_menu('x') == set()                     # the swallowing wrapper is quiet


def test_self_derive_with_no_lower_layer_raises():
    c = _cfg('{ profiles: { x: [ "^x"  a ] } }')            # ^self but nothing below
    with pytest.raises(ConfigError):
        c.check_derives('x')


def test_plain_profile_has_empty_menu_and_new():
    c = _cfg(BASE)
    assert c.profile_menu('ai-tools') == set()
    assert c.profile_new('ai-tools') == set()


# -- check lints (via cmd_check) -----------------------------------------------------------------

def _check_out(tmp_path, capsys, body):
    from configsys.app import Context, build_parser, cmd_check
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(body)
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    rc = cmd_check(ctx, None)
    return rc, capsys.readouterr().out


def test_check_errors_on_undefined_derive(tmp_path, capsys):
    rc, out = _check_out(tmp_path, capsys, '{ configs: [ g ]  profiles: { g: [ "^nope" ] } }')
    assert rc == 1 and 'undefined profile "nope"' in out


def test_check_warns_derive_alongside_include(tmp_path, capsys):
    _, out = _check_out(tmp_path, capsys,
                        '{ configs: [ d ]  profiles: { base: [ htop bat ]  d: [ "^base"  +base ] } }')
    assert '`^base` alongside `+base`' in out


def test_check_warns_subsumed_derive(tmp_path, capsys):
    _, out = _check_out(tmp_path, capsys,
                        '{ configs: [ e ]  profiles: { base: [ htop bat ]  sub: [ htop ]  '
                        'e: [ "^base"  "^sub" ] } }')
    assert 'subsumed by another derive' in out


def test_check_exempts_menu_decline_from_removes_nothing(tmp_path, capsys):
    # `~sub` where sub's members are in the derive menu is a valid DECLINE, not a no-op removal.
    _, out = _check_out(tmp_path, capsys,
                        '{ configs: [ f ]  profiles: { base: [ htop bat ]  sub: [ htop ]  '
                        'f: [ "^base"  htop  ~sub ] } }')
    assert 'removes nothing' not in out
