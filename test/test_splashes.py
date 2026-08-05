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


def test_builtin_plain_is_registered():
    import configsys.tui.splash as host  # noqa: F401 — importing registers the built-in `plain`
    assert splashes.get_splash('plain') is not None
    assert 'plain' in splashes._BUILTIN_SPLASH_NAMES
    assert host.DEFAULT_SPLASH == 'plain'


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
    import configsys.tui.splash  # noqa: F401 — ensure 'plain' is a known built-in
    shadow = SPLASH_PY.replace("name = 'aquarium'", "name = 'plain'").replace('Aquarium', 'Plain')
    pdir = _plugin(tmp_path / 'plugins' / 'shdw',
                   '{ name: shdw  requires-abi: 1  code: splash.py }',
                   {'splash.py': shadow})
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'shdw', plugins.plugin_identity(pdir))
    conflicts = []
    plugins.load_code(tmp_path / 'plugins', tf, [{'source': 'github:x/shdw'}],
                      lambda cls: None, conflicts=conflicts)
    assert any("splash 'plain'" in c for c in conflicts)


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
    p = host.PlainSplash(_FakeWin(), _StubPal(), (24, 80), seed=0)
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
