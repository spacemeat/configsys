'''The SPLASH provider ABI (configsys/splashes.py): the registry + register_splash/get_splash, the
Splash base contract, and load_code registering a plugin's `SPLASHES = [...]` export under the same
checksum/ABI/trust gates as DRIVERS. Curses-free — the host frame loop (tui/splash.run_splash) is
exercised by hand.'''

import pytest

from configsys import plugins, splashes

# A synthetic splash plugin — a name base never ships, so `splash: aquarium` is genuinely unknown
# until this plugin's code is trusted (the point of the gate).
SPLASH_PY = '''from configsys.plugins import Splash, register_splash

class Aquarium(Splash):
    name = 'aquarium'
    def render(self, frame):
        return frame.progress >= 1.0

SPLASHES = [Aquarium]
'''


@pytest.fixture(autouse=True)
def _restore_splashes():
    '''register_splash mutates a process-global; snapshot + restore so nothing leaks between tests.'''
    snap = dict(splashes._SPLASHES)
    yield
    splashes._SPLASHES.clear()
    splashes._SPLASHES.update(snap)


def _plugin(pdir, manifest, files):
    pdir.mkdir(parents=True)
    (pdir / 'plugin.hu').write_text(manifest)
    for name, text in files.items():
        (pdir / name).write_text(text)
    return pdir


# -- registry + base contract -------------------------------------------------

def test_register_get_and_names():
    class Demo(splashes.Splash):
        name = 'demo-splash'
        def render(self, frame):
            return True

    assert splashes.register_splash(Demo) is Demo          # decorator-friendly (returns the class)
    assert splashes.get_splash('demo-splash') is Demo
    assert 'demo-splash' in splashes.splash_names()
    assert splashes.get_splash('nope') is None


def test_register_requires_a_name():
    class Nameless(splashes.Splash):
        def render(self, frame):
            return True

    with pytest.raises(ValueError):
        splashes.register_splash(Nameless)


def test_base_render_is_abstract():
    s = splashes.Splash.__new__(splashes.Splash)
    with pytest.raises(NotImplementedError):
        s.render(None)


def test_builtin_braille_bar_is_registered():
    import configsys.tui.splash as host  # noqa: F401 — importing registers the built-in `braille-bar`
    assert splashes.get_splash('braille-bar') is not None
    assert 'braille-bar' in splashes._BUILTIN_SPLASH_NAMES
    assert host.DEFAULT_SPLASH == 'braille-bar'


# -- load_code registers SPLASHES under the trust gate ------------------------

def test_load_code_registers_trusted_splashes(tmp_path):
    pdir = _plugin(tmp_path / 'plugins' / 'aqua',
                   '{ name: aqua  requires-abi: 1  code: splash.py }',
                   {'splash.py': SPLASH_PY})
    tf = tmp_path / 'trust.hu'
    decls = [{'source': 'github:x/aqua'}]

    # untrusted -> the splash is NOT registered
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, decls, lambda cls: None)
    assert loaded == [] and 'untrusted' in dict(skipped)['aqua']
    assert splashes.get_splash('aquarium') is None

    # trust the content -> the SPLASHES export is imported + registered (no DRIVERS needed)
    plugins.set_trust(tf, 'aqua', plugins.plugin_identity(pdir))
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, decls, lambda cls: None)
    assert skipped == []
    assert loaded == [('aqua', ['aquarium'])]
    assert splashes.get_splash('aquarium') is not None


def test_load_code_flags_splash_shadowing_a_builtin(tmp_path):
    import configsys.tui.splash  # noqa: F401 — ensure 'braille-bar' is a known built-in
    shadow = SPLASH_PY.replace("name = 'aquarium'", "name = 'braille-bar'").replace('Aquarium', 'Plain')
    pdir = _plugin(tmp_path / 'plugins' / 'shdw',
                   '{ name: shdw  requires-abi: 1  code: splash.py }',
                   {'splash.py': shadow})
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'shdw', plugins.plugin_identity(pdir))
    conflicts = []
    plugins.load_code(tmp_path / 'plugins', tf, [{'source': 'github:x/shdw'}],
                      lambda cls: None, conflicts=conflicts)
    assert any("splash 'braille-bar'" in c for c in conflicts)


class _FakeWin:
    '''The handful of curses-window methods run_splash touches.'''
    def __init__(self, h=24, w=80):
        self._hw = (h, w)
        self.frames = 0
    def getmaxyx(self):
        return self._hw
    def nodelay(self, flag):
        pass
    def getch(self):
        return -1
    def noutrefresh(self):
        self.frames += 1
    def erase(self):
        pass
    def addstr(self, y, x, s, attr=0):
        pass


def test_run_splash_drives_a_provider_and_stops(monkeypatch):
    import curses

    from configsys.tui import splash as hostmod
    monkeypatch.setattr(curses, 'doupdate', lambda: None)
    monkeypatch.setattr(hostmod.time, 'sleep', lambda s: None)

    seen = []

    class Once(splashes.Splash):
        name = 'once'
        min_duration = 0.0
        def render(self, frame):
            seen.append(frame)
            return frame.progress >= 1.0        # at rest once full

    win = _FakeWin()
    hostmod.run_splash(win, pal=None, provider_cls=Once, is_done=lambda: True,
                       frac=lambda: 1.0, counts=lambda: (5, 5), label='x')
    assert len(seen) == 1                        # done immediately -> one frame then stop
    assert seen[0].progress == 1.0 and seen[0].done is True


def test_run_splash_survives_a_broken_provider(monkeypatch):
    import curses

    from configsys.tui import splash as hostmod
    monkeypatch.setattr(curses, 'doupdate', lambda: None)
    monkeypatch.setattr(hostmod.time, 'sleep', lambda s: None)

    class Broken(splashes.Splash):
        name = 'broken'
        min_duration = 0.0
        def render(self, frame):
            raise RuntimeError('boom')

    win = _FakeWin()
    # a raising render must fall back to the text line and still finish (never brick startup)
    hostmod.run_splash(win, pal=_StubPal(), provider_cls=Broken, is_done=lambda: True,
                       frac=lambda: 0.5, counts=lambda: (1, 2), label='x')


class _StubPal:
    def get(self, role):
        return 0


def test_plain_splash_renders_and_signals_done():
    import configsys.tui.splash as host
    from configsys.splashes import SplashFrame
    p = host.BrailleBarSplash(_FakeWin(), _StubPal(), (24, 80), seed=0)
    mid = SplashFrame(progress=0.5, counts=(5, 10), label='checking', dt=0.03, elapsed=1.0, done=False)
    assert p.render(mid) is False            # still inspecting -> keep going
    end = SplashFrame(progress=1.0, counts=(10, 10), label='checking', dt=0.03, elapsed=2.0, done=True)
    assert p.render(end) is True             # done -> at rest, host may stop


def test_module_with_no_exports_is_skipped(tmp_path):
    pdir = _plugin(tmp_path / 'plugins' / 'empty',
                   '{ name: empty  requires-abi: 1  code: mod.py }',
                   {'mod.py': 'X = 1\n'})
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'empty', plugins.plugin_identity(pdir))
    loaded, skipped = plugins.load_code(tmp_path / 'plugins', tf, [{'source': 'github:x/empty'}],
                                        lambda cls: None)
    assert loaded == [] and 'no DRIVERS or SPLASHES' in dict(skipped)['empty']


# -- plugin name as an alias for its splash (config UX) -----------------------

def test_splash_plugins_and_plugin_name_alias(tmp_path):
    '''A user names the PLUGIN they installed (configsys-splash-blocks), not the provider it calls
    itself internally (blocks). resolve_splash_value maps the sole-splash plugin name -> provider;
    splash_plugins surfaces which plugin provides each splash (for the picker label).'''
    pdir = tmp_path / 'plugins' / 'configsys-splash-blocks'
    _plugin(pdir, '{ name: configsys-splash-blocks  requires-abi: 1'
                  '  provides: { splashes: [ blocks ] }  code: blocks.py }',
            {'blocks.py': 'X = 1\n'})
    decls = [{'source': 'file:/somewhere/configsys-splash-blocks'}]
    pd = tmp_path / 'plugins'

    assert plugins.splash_plugins(pd, decls) == {'blocks': 'configsys-splash-blocks'}
    # the plugin name resolves to its sole provider...
    assert plugins.resolve_splash_value('configsys-splash-blocks', pd, decls) == 'blocks'
    # ...a real provider name passes through (get_splash sees it once registered; here it's unknown
    # so it falls to the plugin map, which has no plugin named 'blocks' -> unchanged)
    assert plugins.resolve_splash_value('blocks', pd, decls) == 'blocks'
    # an unknown value is left alone (existing unknown->default degrade still applies)
    assert plugins.resolve_splash_value('nope', pd, decls) == 'nope'


def test_multi_splash_plugin_name_is_not_aliased(tmp_path):
    '''A plugin providing MORE than one splash can't be aliased by plugin name alone (ambiguous) —
    the value passes through so the user must name the provider.'''
    pdir = tmp_path / 'plugins' / 'combo'
    _plugin(pdir, '{ name: combo  requires-abi: 1  provides: { splashes: [ a  b ] }  code: c.py }',
            {'c.py': 'X = 1\n'})
    decls = [{'source': 'file:/x/combo'}]
    pd = tmp_path / 'plugins'
    assert plugins.splash_plugins(pd, decls) == {'a': 'combo', 'b': 'combo'}
    assert plugins.resolve_splash_value('combo', pd, decls) == 'combo'   # ambiguous -> unchanged


def test_splash_value_hint_flags_multi_splash_plugin(tmp_path):
    '''Setting a plugin that provides 2+ splashes is ambiguous (can't alias by plugin name) — the
    hint names the choices instead of the misleading "unavailable" fallback. A sole-splash plugin,
    a bare provider name, and off/unknown give no hint.'''
    _plugin(tmp_path / 'plugins' / 'combo',
            '{ name: combo  requires-abi: 1  provides: { splashes: [ a  b ] }  code: c.py }',
            {'c.py': 'X=1\n'})
    _plugin(tmp_path / 'plugins' / 'configsys-splash-blocks',
            '{ name: configsys-splash-blocks  requires-abi: 1'
            '  provides: { splashes: [ blocks ] }  code: b.py }', {'b.py': 'X=1\n'})
    pd = tmp_path / 'plugins'
    decls = [{'source': 'file:/x/combo'}, {'source': 'file:/x/configsys-splash-blocks'}]

    hint = plugins.splash_value_hint('combo', pd, decls)
    assert hint and 'multiple splashes' in hint and 'a, b' in hint
    assert plugins.splash_value_hint('configsys-splash-blocks', pd, decls) is None   # sole splash: fine
    assert plugins.splash_value_hint('blocks', pd, decls) is None                    # a provider name
    assert plugins.splash_value_hint('off', pd, decls) is None


# -- `splash: random` provider selection --------------------------------------

def test_random_splash_excludes_the_default_and_is_deterministic_with_rng():
    import random
    from configsys.tui import splash as _hostsplash          # registers the built-in default
    default = _hostsplash.DEFAULT_SPLASH

    class A(splashes.Splash):
        name = 'aq-a'
        def render(self, frame):
            return True

    class B(splashes.Splash):
        name = 'aq-b'
        def render(self, frame):
            return True
    splashes.register_splash(A)
    splashes.register_splash(B)

    picks = {splashes.random_splash(exclude=default, rng=random.Random(s)) for s in range(30)}
    assert picks == {'aq-a', 'aq-b'}                          # only the two plugin splashes, never default
    assert default not in picks


def test_random_splash_is_none_when_only_the_default_is_registered():
    from configsys.tui import splash as _hostsplash
    # snapshot fixture leaves only the built-ins; drop all but the default so there's nothing to pick
    for n in list(splashes._SPLASHES):
        if n != _hostsplash.DEFAULT_SPLASH:
            del splashes._SPLASHES[n]
    assert splashes.random_splash(exclude=_hostsplash.DEFAULT_SPLASH) is None


def test_config_set_splash_does_not_crash(tmp_path):
    '''`config set splash <value>` must not blow up on the splash-resolve warn path (it referenced
    an un-imported `plugins`). Covers 'random' and a plain provider name.'''
    from configsys.app import main
    home = ['--home', str(tmp_path), '--os', 'pop']
    assert main(home + ['config', 'set', 'splash', 'random']) == 0
    assert main(home + ['config', 'set', 'splash', 'blocks']) == 0
