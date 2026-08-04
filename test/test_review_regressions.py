'''Regression tests for bugs found in the stringent adversarial review of the TUI + action layer.
Each locks a specific fix so it can't silently regress.'''

import types

import pytest

from configsys import actions, layers, plugins
from configsys.config import Config
from configsys.errors import ConfigError


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


# -- A3: remove from a DEFINED-but-broken profile must surface the error, not silently no-op -------

def _cfg(repo_text, user_text=None):
    ls = [layers.Layer('config.hu', 'repo', layers.materialize_string(repo_text))]
    if user_text is not None:
        ls.append(layers.Layer('user.hu', 'user', layers.materialize_string(user_text)))
    return Config(ls)


def test_remove_from_broken_profile_raises():
    c = _cfg('{ profiles: { dev: [ btop ] } }', '{ profiles: { dev: [ +nope  a ] } }')
    with pytest.raises(ConfigError):
        c.plan_membership_edit('dev', 'a', 'remove', 'user.hu')   # +nope undefined -> must raise
    # an UNDEFINED profile is still fine to add to (creates it), not an error
    assert c.plan_membership_edit('brandnew', 'a', 'add', 'user.hu') == ['a']


# -- A1: an edit shadowed by a higher-precedence layer must report no-effect, not success ----------

def test_set_profile_membership_warns_when_shadowed(tmp_path):
    low = tmp_path / 'low.hu'
    low.write_text('{ profiles: {} }\n', encoding='utf-8')          # lower layer, no dev
    top = tmp_path / 'top.hu'
    top.write_text('{ profiles: { dev: [ a  b ] } }\n', encoding='utf-8')   # top defines dev

    def load():
        return Config([layers.Layer(str(low), 'plugin', layers.materialize_string(low.read_text())),
                       layers.Layer(str(top), 'user', layers.materialize_string(top.read_text()))])

    ctx = types.SimpleNamespace()
    ctx.paths = types.SimpleNamespace(user_config_file=str(top), plugins_dir=tmp_path / 'plugins')
    ctx.config = load()
    ctx.invalidate = lambda: setattr(ctx, 'config', load())

    # explicitly edit the LOWER layer -> top's dev shadows it -> the add takes no effect
    changed, msg = actions.set_profile_membership(ctx, 'dev', 'x', 'add', target=str(low))
    assert changed is False and 'overridden' in msg
    assert 'x' not in ctx.config.profile_components('dev')


def test_profile_target_picks_the_defining_layer(tmp_path):
    # a profile defined only in the top config -> _profile_target must return the top config, not a
    # (shadowed) primary — else the edit is a silent no-op
    top = tmp_path / 'top.hu'
    top.write_text('{ profiles: { dev: [ a ] } }\n', encoding='utf-8')
    ctx = types.SimpleNamespace()
    ctx.paths = types.SimpleNamespace(user_config_file=str(top), plugins_dir=tmp_path / 'plugins')
    ctx.config = Config([layers.Layer(str(top), 'user', layers.materialize_string(top.read_text()))])
    tfile, _label = actions._profile_target(ctx, 'dev')
    assert tfile == str(top)


# -- A4: theme save must preserve a disabled per-page gradient (and not drop it) --------------------

def test_theme_overrides_preserves_disabled_gradient(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ theme: { pages: { profiles: { gradient: false } } } }\n', encoding='utf-8')
    ctx = types.SimpleNamespace()
    ctx.config = Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    ov = actions.theme_overrides(ctx)
    assert ov['pages']['profiles']['gradient'] is False   # explicit disable survives the round-trip
