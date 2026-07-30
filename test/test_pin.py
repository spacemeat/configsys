'''The `pin` CLI (Phase 3a): view / set / unset install-method (and provider) pins, and promote
a local pin into the primary plugin so it travels to other machines. Writes go through the
surgical set_section primitive; set/unset touch the top config, promote the primary plugin.'''

from configsys import plugins
from configsys.app import main


def _run(home, *args):                       # real writes (NOT --pretend)
    return main(['--home', str(home), '--os', 'pop', *args])


def _cfgdir(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_pin_set_list_unset_roundtrip(tmp_path, capsys):
    assert _run(tmp_path, 'pin', 'set', 'steam', 'flatpak') == 0
    capsys.readouterr()
    assert _run(tmp_path, 'pin', 'list') == 0
    out = capsys.readouterr().out
    assert 'steam' in out and 'flatpak' in out and 'local' in out
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    assert plugins.read_pins(str(cfg)) == {'steam': 'flatpak'}
    assert _run(tmp_path, 'pin', 'unset', 'steam') == 0
    assert plugins.read_pins(str(cfg)) == {}


def test_pin_set_rejects_unknown_value(tmp_path, capsys):
    assert _run(tmp_path, 'pin', 'set', 'steam', 'bogus') == 1
    err = capsys.readouterr().err
    assert 'neither a known via' in err


def test_pin_set_rejects_via_not_a_binding(tmp_path, capsys):
    # btop has only a native binding -> pinning it to flatpak is a clear error
    assert _run(tmp_path, 'pin', 'set', 'btop', 'flatpak') == 1
    assert 'no via:flatpak binding' in capsys.readouterr().err


def test_pin_set_reroutes_resolution(tmp_path, capsys):
    # a written binding-pin is picked up on the next load and changes what resolves
    assert _run(tmp_path, 'pin', 'set', 'steam', 'flatpak') == 0
    capsys.readouterr()
    assert _run(tmp_path, 'where', 'steam') == 0
    assert 'flatpak\\steam' in capsys.readouterr().out


def test_pin_list_empty(tmp_path, capsys):
    assert _run(tmp_path, 'pin', 'list') == 0
    assert 'no pins' in capsys.readouterr().out


def test_pin_promote_moves_pin_into_primary(tmp_path, capsys):
    cfgdir = _cfgdir(tmp_path)
    pdir = cfgdir / 'plugins' / 'me'
    plugins.scaffold_primary(pdir, 'me', sections={'profiles': 'profiles: { p: [ btop ] }'})
    (cfgdir / 'configsys.hu').write_text(
        '{ plugins: [ { source: ' + str(pdir) + '  primary: true } ]  pins: { steam: flatpak } }')

    assert _run(tmp_path, 'pin', 'promote', 'steam') == 0
    out = capsys.readouterr().out
    assert 'into primary plugin me' in out and 'commit & push' in out
    # moved: gone from the top config, now in the primary's data file
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {}
    assert plugins.read_pins(str(pdir / 'me.hu')) == {'steam': 'flatpak'}


def test_pin_promote_without_primary_errors(tmp_path, capsys):
    cfgdir = _cfgdir(tmp_path)
    (cfgdir / 'configsys.hu').write_text('{ pins: { steam: flatpak } }')
    assert _run(tmp_path, 'pin', 'promote', 'steam') == 1
    assert 'no primary plugin' in capsys.readouterr().err


def test_pin_promote_absent_pin_errors(tmp_path, capsys):
    _cfgdir(tmp_path)
    assert _run(tmp_path, 'pin', 'promote', 'steam') == 1
    assert 'nothing to promote' in capsys.readouterr().err
