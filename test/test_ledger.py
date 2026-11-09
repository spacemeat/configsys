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


def test_empty_ledger_roundtrips(tmp_path):
    # Regression: an empty ledger saves as `{}`, which humon.from_file rejected as
    # BADENCODING (too short to sniff). Save + reload must succeed.
    p = paths_in(tmp_path)
    Ledger().save(p)
    assert p.ledger_file.exists()
    reloaded = Ledger.load(p)
    assert reloaded.records == {}


def test_blank_ledger_file_treated_as_empty(tmp_path):
    p = paths_in(tmp_path)
    p.state_dir.mkdir(parents=True, exist_ok=True)
    p.ledger_file.write_text('   \n', encoding='utf-8')
    assert Ledger.load(p).records == {}


def test_single_record_roundtrips(tmp_path):
    # a small (but non-empty) ledger also round-trips
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('apt\\btop', True)
    led.save(p)
    assert Ledger.load(p).is_locked('apt\\btop') is True


def test_backslash_keys_survive_roundtrip(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('font\\mononoki-nerd', True)
    led.save(p)
    assert Ledger.load(p).is_locked('font\\mononoki-nerd') is True


def test_save_merges_only_this_process_changes(tmp_path):
    # B10: a TUI that loaded the ledger long ago must not overwrite what a CLI run saved meanwhile
    p = paths_in(tmp_path)
    tui = Ledger.load(p)                       # loaded first (empty)
    cli = Ledger.load(p)
    cli.set_lock('apt\\btop', True)
    cli.save(p)                                # the CLI locks btop
    tui.set_lock('apt\\htop', True)
    tui.save(p)                                # the TUI later saves its own change
    back = Ledger.load(p)
    assert back.is_locked('apt\\btop') and back.is_locked('apt\\htop')


def test_save_writes_back_a_cleared_receipt(tmp_path):
    from configsys.componentObj import ResolvedComponent
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_receipt(ResolvedComponent(key='apt\\btop', driver='apt', comp='btop', fields={'name': 'btop'}))
    led.save(p)
    later = Ledger.load(p)
    later.clear_receipt('apt\\btop')
    later.save(p)
    assert Ledger.load(p).records['apt\\btop'].get('receipt') is None


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('apt\\btop', True)
    led.save(p)
    assert not p.ledger_file.with_name(p.ledger_file.name + '.tmp').exists()


def test_corrupt_ledger_loads_empty_and_is_moved_aside_on_save(tmp_path):
    # B10: a torn/garbled state.hu is never a brick — run on empty, keep the bad file for inspection
    p = paths_in(tmp_path)
    p.state_dir.mkdir(parents=True, exist_ok=True)
    p.ledger_file.write_text('{ apt\\btop: { locked: tr', encoding='utf-8')
    led = Ledger.load(p)
    assert led.records == {} and led.corrupt == p.ledger_file
    led.set_lock('apt\\htop', True)
    led.save(p)
    aside = list(p.state_dir.glob('state.hu.corrupt-*'))
    assert len(aside) == 1 and 'locked: tr' in aside[0].read_text()
    back = Ledger.load(p)
    assert back.corrupt is None and back.is_locked('apt\\htop')
