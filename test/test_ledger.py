from configsys.ledger import Ledger
from configsys.paths import Paths


def paths_in(tmp_path):
    return Paths(env={'HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 'state')})


def test_missing_ledger_loads_empty(tmp_path):
    led = Ledger.load(paths_in(tmp_path))
    assert led.records == {}
    assert led.is_locked('apt\\btop') is False
    assert led.pinned_version('apt\\btop') == ''


def test_roundtrip_persists_lock_managed_pinned(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('apt\\btop', True)
    led.set_managed('appImage\\neovim', True)
    led.set_pinned('apt\\ripgrep', '13.0.0-2')
    led.save(p)

    assert p.ledger_file.exists()
    reloaded = Ledger.load(p)
    assert reloaded.is_locked('apt\\btop') is True
    assert reloaded.is_managed('appImage\\neovim') is True
    assert reloaded.pinned_version('apt\\ripgrep') == '13.0.0-2'
    # untouched keys stay default
    assert reloaded.is_locked('apt\\ripgrep') is False


def test_backslash_keys_survive_roundtrip(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('debian-font\\mononoki-nerd', True)
    led.save(p)
    assert Ledger.load(p).is_locked('debian-font\\mononoki-nerd') is True
