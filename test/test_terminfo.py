'''terminfo.py: the pure-Python compiled-terminfo reader/writer that builds a `-direct` entry where
neither a system one nor `tic` exists (minimal containers). Proven against the real thing: every
system entry round-trips byte-for-byte, and the derived -direct entry is byte-identical to tic's.'''

import glob
import os
import shutil
import subprocess

import pytest

from configsys.tui import screen, terminfo

SYSTEM_DIRS = ['/etc/terminfo', '/lib/terminfo', '/usr/share/terminfo', '/usr/lib/terminfo']


def _system_entries():
    return [p for d in SYSTEM_DIRS for p in glob.glob(os.path.join(d, '*', '*')) if os.path.isfile(p)]


def test_system_entries_round_trip_byte_for_byte():
    paths = _system_entries()
    if not paths:
        pytest.skip('no compiled terminfo database here')
    for p in paths:
        with open(p, 'rb') as f:
            data = f.read()
        wide = int.from_bytes(data[:2], 'little') == terminfo.MAGIC_32
        assert terminfo.serialize(terminfo.parse(data), wide=wide) == data, p


def test_make_direct_sets_the_direct_color_caps():
    base = terminfo.Entry(b'fake|fake term', [0] * 30, [-1] * 20, [-1] * 10, {'XT': 1}, {}, {'kUP': b'\x1b[1;2A'})
    d = terminfo.parse(terminfo.serialize(terminfo.make_direct(base, 'fake-direct', 'fake')))
    assert d.names.startswith(b'fake-direct|')
    assert d.nums[terminfo.N_COLORS] == 0x1000000 and d.nums[terminfo.N_PAIRS] == 0x10000
    assert d.strs[terminfo.S_SETAF] == terminfo.DIRECT_SETAF
    assert d.strs[terminfo.S_INITC] == terminfo.CANCELLED and d.bools[terminfo.B_CCC] == 0
    assert d.ext_bools == {'RGB': 1, 'XT': 1} and d.ext_nums == {'CO': 8}
    assert d.ext_strs == {'kUP': b'\x1b[1;2A'}                  # the base's own caps carry over


@pytest.mark.parametrize('term', ['xterm-256color', 'tmux-256color', 'screen-256color', 'linux'])
def test_direct_entry_is_byte_identical_to_tics(term, tmp_path):
    if not shutil.which('tic') or not terminfo.find_compiled(term, SYSTEM_DIRS):
        pytest.skip(f'needs tic + a {term} entry')
    name = term.replace('-256color', '') + '-direct'
    assert terminfo.build_direct(name, term, SYSTEM_DIRS, str(tmp_path / 'py'))
    src = tmp_path / 'overlay.src'
    src.write_text(screen._DIRECT_OVERLAY % {'name': name, 'term': term})
    subprocess.run(['tic', '-x', '-o', str(tmp_path / 'tic'), str(src)], check=True, capture_output=True)
    py = open(terminfo.entry_path(str(tmp_path / 'py'), name), 'rb').read()
    tic = open(terminfo.entry_path(str(tmp_path / 'tic'), name), 'rb').read()
    assert py == tic


def test_build_without_tic(monkeypatch, tmp_path):
    # the container case: no ncurses-term (no system -direct) AND no ncurses-bin (no tic)
    if not terminfo.find_compiled('xterm-256color', SYSTEM_DIRS):
        pytest.skip('needs an xterm-256color entry')
    monkeypatch.setattr('shutil.which', lambda _: None)
    monkeypatch.setattr(screen, '_TERMINFO_DIRS', tuple(SYSTEM_DIRS))
    monkeypatch.setattr(screen.curses, 'has_extended_color_support', lambda: True, raising=False)
    real = screen._terminfo_exists
    monkeypatch.setattr(screen, '_terminfo_exists',       # hide the system's own *-direct entries
                        lambda n, e, system=True: False if n.endswith('-direct') and system else real(n, e, system))
    env = {'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'XDG_CACHE_HOME': str(tmp_path)}
    assert screen.direct_color_setup(env) == ('xterm-direct', str(tmp_path / 'configsys' / 'terminfo'))


def test_unreadable_base_fails_cleanly(tmp_path):
    bad = tmp_path / 'db' / 'b'
    bad.mkdir(parents=True)
    (bad / 'broken').write_bytes(b'\x00\x01garbage')
    assert not terminfo.build_direct('broken-direct', 'broken', [str(tmp_path / 'db')], str(tmp_path / 'out'))
    assert not terminfo.build_direct('nope-direct', 'nope', [str(tmp_path / 'db')], str(tmp_path / 'out'))
