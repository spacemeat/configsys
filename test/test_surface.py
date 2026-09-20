'''Unit tests for the TUI Surface abstraction (configsys/tui/surface.py) — the off-screen
BufferSurface the render harness paints into. CursesSurface is a transparent shim over a real
window, covered by the live pty smoke test; here we pin the buffer's recording semantics.'''

from configsys.tui.surface import BufferSurface, Cell


def test_getmaxyx_and_basic_put():
    s = BufferSurface(10, 20)
    assert s.getmaxyx() == (10, 20)
    s.addstr(2, 3, 'hi', 7)
    assert s.cells[(2, 3)] == Cell('h', 7)
    assert s.cells[(2, 4)] == Cell('i', 7)


def test_addstr_clips_to_bounds():
    s = BufferSurface(3, 5)
    s.addstr(1, 3, 'abcdef')          # runs past the right edge (w=5) -> only 'ab' fit
    assert [x for (y, x) in s.cells] == [3, 4]
    s.addstr(9, 0, 'x')               # off the bottom -> dropped
    s.addstr(-1, 0, 'x')              # off the top -> dropped
    assert all(0 <= y < 3 for (y, _x) in s.cells)


def test_addstr_negative_x_partial():
    s = BufferSurface(3, 5)
    s.addstr(0, -2, 'abcd')           # first two chars are off-screen left; 'cd' land at x=0,1
    assert s.cells[(0, 0)].char == 'c'
    assert s.cells[(0, 1)].char == 'd'


def test_overwrite_last_write_wins():
    s = BufferSurface(3, 5)
    s.addstr(0, 0, 'AA', 1)
    s.addstr(0, 0, 'B', 2)
    assert s.cells[(0, 0)] == Cell('B', 2)
    assert s.cells[(0, 1)] == Cell('A', 1)   # untouched


def test_erase_clears_root():
    s = BufferSurface(3, 5)
    s.addstr(0, 0, 'hi')
    s.erase()
    assert s.cells == {}


def test_derwin_offsets_into_shared_grid():
    s = BufferSurface(10, 20)
    sub = s.derwin(4, 6, 2, 3)        # h,w,y,x
    assert sub.getmaxyx() == (4, 6)
    sub.addstr(0, 0, 'X', 5)
    assert s.cells[(2, 3)] == Cell('X', 5)     # sub (0,0) -> parent (2,3)
    sub.addstr(1, 2, 'Y')
    assert s.cells[(3, 5)].char == 'Y'


def test_derwin_clips_to_subwindow():
    s = BufferSurface(10, 20)
    sub = s.derwin(2, 3, 0, 0)
    sub.addstr(0, 0, 'abcde')        # sub width 3 -> only 'abc'
    assert sorted(x for (y, x) in s.cells) == [0, 1, 2]
    sub.addstr(5, 0, 'z')            # past sub height -> dropped
    assert (5, 0) not in s.cells


def test_derwin_erase_clears_only_its_rect():
    s = BufferSurface(10, 20)
    s.addstr(0, 0, 'keep', 1)        # outside the sub
    sub = s.derwin(2, 3, 5, 5)
    sub.addstr(0, 0, 'gone')
    sub.erase()
    assert (5, 5) not in s.cells
    assert s.cells[(0, 0)] == Cell('k', 1)   # parent content survives


def test_grid_is_sorted_snapshot():
    s = BufferSurface(5, 5)
    s.addstr(1, 1, 'b')
    s.addstr(0, 0, 'a')
    assert s.grid() == [(0, 0, 'a', 0), (1, 1, 'b', 0)]


def test_text_rows_reconstructs_lines():
    s = BufferSurface(5, 10)
    s.addstr(0, 2, 'hi')
    s.addstr(2, 0, 'yo')
    assert s.text_rows() == ['  hi', '', 'yo']
