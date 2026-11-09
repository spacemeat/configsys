from configsys.ledger import Ledger
from configsys.paths import Paths


def paths_in(tmp_path):
    return Paths(env={'HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 'state')})


def test_missing_ledger_loads_empty(tmp_path):
    led = Ledger.load(paths_in(tmp_path))
    assert led.records == {}
    assert led.is_locked('apt\\btop') is False


def test_roundtrip_persists_locks(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('apt\\btop', True)
    led.save(p)

    assert p.ledger_file.exists()
    reloaded = Ledger.load(p)
    assert reloaded.is_locked('apt\\btop') is True
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
    assert 'apt\\btop' not in Ledger.load(p).records           # nothing left to say: pruned


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


# -- review-2026-11-2 actions-25 / actions-31 ------------------------------------------------------

def _unit(i):
    from configsys.componentObj import ResolvedComponent
    return ResolvedComponent(key=f'apt\\c{i}', driver='apt', comp=f'c{i}',
                             fields={'name': f'c{i}', 'scope': 'system', 'packages': [f'c{i}', f'c{i}-data']})


def test_a_big_ledger_round_trips_in_one_parse(tmp_path, monkeypatch):
    import configsys.troveio as troveio
    p = paths_in(tmp_path)
    led = Ledger()
    for i in range(200):
        led.set_receipt(_unit(i))
        if i % 3 == 0:
            led.set_lock(f'apt\\c{i}', True)
    led.save(p)
    calls = []
    real = troveio.load
    monkeypatch.setattr(troveio, 'load', lambda *a, **k: calls.append(a) or real(*a, **k))
    back = Ledger.load(p)
    assert calls == []                                     # one materialize pass, no trove load
    assert back.records == led.records
    assert back.is_locked('apt\\c3') and not back.is_locked('apt\\c4')
    assert back.receipt('apt\\c7') == {'via': 'apt', 'name': 'c7',
                                        'fields': {'scope': 'system', 'packages': ['c7', 'c7-data']}}


def test_legacy_fields_load_and_are_not_written_back(tmp_path):
    p = paths_in(tmp_path)
    p.state_dir.mkdir(parents=True, exist_ok=True)
    p.ledger_file.write_text('{ apt\\btop: { locked: true  managed: false  pinned_version: "" }\n'
                             '  appImage\\nvim: { locked: false  managed: true  pinned_version: "0.10" } }\n',
                             encoding='utf-8')
    led = Ledger.load(p)
    assert led.corrupt is None and led.is_locked('apt\\btop')
    led.set_lock('apt\\htop', True)
    led.save(p)
    text = p.ledger_file.read_text()
    assert 'managed' not in text and 'pinned_version' not in text
    assert 'nvim' not in text                              # no lock, no receipt: dropped on save
    assert Ledger.load(p).is_locked('apt\\btop') and Ledger.load(p).is_locked('apt\\htop')


def test_an_unlocked_receiptless_record_is_dropped(tmp_path):
    p = paths_in(tmp_path)
    led = Ledger()
    led.set_lock('apt\\btop', True)
    led.save(p)
    led.set_lock('apt\\btop', False)
    led.save(p)
    assert Ledger.load(p).records == {}
