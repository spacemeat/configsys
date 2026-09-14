'''Regression tests for bugs found in the stringent adversarial review of the TUI + action layer.
Each locks a specific fix so it can't silently regress.'''

import types

from configsys import actions, layers, plugins
from configsys.config import Config


# -- TUI #1: `g` on Components crashed (ms.top attr shadowed the top() method) --------------------

def test_menustate_go_top_is_callable_not_shadowed():
    from configsys.tui.menu import MenuState
    ms = MenuState({}, {}, {})
    ms.go_top()                      # was `ms.top()` -> TypeError (int not callable)
    ms.go_bottom()
    assert ms.cursor == 0 and isinstance(ms.top, int)   # ms.top stays the scroll offset


# -- A2: set_section must preserve a comment humon binds to the edited node ------------------------

def test_set_section_preserves_leading_comment(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{\n    // keep this comment about scope\n    scope: system\n}\n', encoding='utf-8')
    plugins.set_scalar_section(str(f), 'scope', 'user')
    txt = f.read_text()
    assert 'keep this comment about scope' in txt      # the bound comment survives the edit
    assert 'scope: user' in txt


def test_set_section_not_fooled_by_key_in_a_comment(tmp_path):
    # a comment above the node that itself contains `scope:` must not be mistaken for the key line
    f = tmp_path / 'u.hu'
    f.write_text('{\n    // example: scope: user is the default\n    scope: system\n}\n', encoding='utf-8')
    plugins.set_scalar_section(str(f), 'scope', 'user')
    txt = f.read_text()
    assert 'example: scope: user is the default' in txt
    assert 'scope: user\n' in txt or 'scope: user}' in txt


# -- A4: theme save must preserve a disabled per-page gradient (and not drop it) --------------------

def test_theme_overrides_preserves_disabled_gradient(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ theme: { pages: { profiles: { gradient: false } } } }\n', encoding='utf-8')
    ctx = types.SimpleNamespace()
    ctx.config = Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    ov = actions.theme_overrides(ctx)
    assert ov['pages']['profiles']['gradient'] is False   # explicit disable survives the round-trip


def test_theme_role_fg_references_color_map(tmp_path):
    # a per-page role fg that names a color in the shared map resolves to that color, and retinting
    # the map re-tints the role (the two-list model's whole point)
    user = tmp_path / 'user.hu'
    user.write_text('{ theme: { colors: { brand: "#0a0b0c" }'
                    '          pages: { components: { component: { fg: brand } } } } }\n',
                    encoding='utf-8')
    ctx = types.SimpleNamespace()
    ctx.config = Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    from configsys.tui.theme import resolve_theme
    _colors, pages = resolve_theme(ctx.config.theme())
    assert pages['components']['roles']['component']['fg'] == (10, 11, 12)
