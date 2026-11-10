'''hudiff — what changed in a `.hu` file, in plain words by key path (the Plugins review's
summaries; review.py). One test per kind of change.'''

from configsys import hudiff


def words(old, new):
    got = hudiff.summarize(old, new)
    return None if got is None else [t for _k, t in got]


def kinds(old, new):
    return [k for k, _t in hudiff.summarize(old, new)]


def test_a_scalar_setting_changed_added_removed():
    assert words('{ splash: plain }', '{ splash: braille-bar }') == ['splash: plain → braille-bar']
    assert kinds('{ splash: plain }', '{ splash: braille-bar }') == ['change']
    assert words('{ }', '{ splash: plain }') == ['added splash: plain']
    assert words('{ splash: plain }', '{ }') == ['removed splash (was plain)']
    assert kinds('{ }', '{ splash: plain }') == ['add'] and kinds('{ splash: plain }', '{ }') == ['del']


def test_a_set_like_name_list_says_what_came_and_went():
    old = '{ picks: { laptop: [ btop  fzf ] } }'
    new = '{ picks: { laptop: [ fzf  ripgrep ] } }'
    assert words(old, new) == ['picks: laptop + ripgrep − btop']
    assert kinds(old, new) == ['change']
    assert words(old, '{ picks: { laptop: [ btop  fzf  jq ] } }') == ['picks: laptop + jq']
    assert words(old, '{ picks: { laptop: [ fzf  btop ] } }') == []          # order means nothing there
    assert words(old, '{ picks: { laptop: [ btop  fzf ]  desk: [ jq ] } }') == ['picks: desk + jq']
    assert words('{ disabled-drivers: [ snap ] }', '{ disabled-drivers: [ snap  aur ] }') == \
        ['disabled-drivers: + aur']


def test_an_ordered_list_also_says_when_only_the_order_changed():
    old = '{ profiles: { dev: [ +editors  ~vim ] } }'
    assert words(old, '{ profiles: { dev: [ +editors  ~vim  ripgrep ] } }') == ['profiles: dev + ripgrep']
    assert words(old, '{ profiles: { dev: [ ~vim  +editors ] } }') == ['profiles: dev reordered']


def test_the_plugins_list_by_source():
    old = ('{ plugins: [ { source: "github:me/configsys-source"  ref: v0.1.12 }\n'
           '             { source: "github:me/configsys-bar" } ] }')
    new = ('{ plugins: [ { source: "github:me/configsys-source"  ref: v0.1.13 }\n'
           '             { source: "github:me/configsys-foo"  ref: v1 } ] }')
    assert words(old, new) == ['configsys-source: ref v0.1.12 → v0.1.13', 'added plugin configsys-foo @v1',
                               'removed plugin configsys-bar']
    assert kinds(old, new) == ['change', 'add', 'del']
    moved = '{ plugins: [ { source: "github:me/configsys-bar" } { source: "github:me/configsys-source"  ref: v0.1.12 } ] }'
    assert words(old, moved) == ['plugins: order changed (later = higher precedence)']
    pinned = old.replace('ref: v0.1.12', 'ref: v0.1.12  sha256: "sha256:0123456789abcdef0123"')
    assert words(old, pinned) == ['configsys-source: added sha256: sha256:0123456789ab…']


def test_nested_maps_by_dotted_path():
    old = '{ components: { htop: { description: "An interactive process viewer"  standing: 1 } } }'
    new = '{ components: { htop: { description: "An interactive process viewer for the terminal"  standing: 2 } } }'
    assert words(old, new) == ['components.htop.description changed', 'components.htop.standing: 1 → 2']
    assert words('{ components: { } }', '{ components: { btop: { install: [ { via: native } ] } } }') == \
        ['added components.btop']
    assert words('{ components: { btop: { } } }', '{ components: { } }') == ['removed components.btop']


def test_install_bindings_by_method():
    old = '{ components: { htop: { install: [ { via: native } { via: snap } ] } } }'
    new = '{ components: { htop: { install: [ { via: native  name: htop-ng } { via: flatpak  when: "debian" } ] } } }'
    assert words(old, new) == ['components.htop.install[native]: added name: htop-ng',
                               'components.htop.install: added via flatpak when debian',
                               'components.htop.install: removed via snap']


def test_comments_and_layout_alone_are_no_change():
    assert words('{ splash: plain }', '// a note\n{\n    splash: plain   // why\n}\n') == []


def test_a_file_that_does_not_read_has_no_summary():
    assert hudiff.summarize('{ splash: plain }', '{ splash: [ plain ') is None
    assert hudiff.summarize('[ a b ]', '[ a ]') is None                    # not a map


def test_a_new_or_deleted_file():
    new = ('{ components: { htop: { }  btop: { } }  picks: { this-machine: [ btop ] }  splash: plain\n'
           '  plugins: [ { source: "github:me/configsys-foo" } ] }')
    assert words(None, new) == ['added components: htop, btop', 'picks: this-machine + btop',
                                'added splash: plain', 'added plugin configsys-foo']
    assert words('{ splash: plain }', None) == ['removed splash (was plain)']


def test_a_long_summary_is_capped():
    old = '{ a: { } }'
    new = '{ a: { ' + '  '.join(f'k{i}: {i}' for i in range(60)) + ' } }'
    got = words(old, new)
    assert len(got) == hudiff.MOST + 1 and got[-1] == f'… and {60 - hudiff.MOST} more changes'
