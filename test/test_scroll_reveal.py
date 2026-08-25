'''_scroll_reveal — on expanding a tree branch, scroll so the parent anchors near the top and as
many children as fit show beneath it, instead of the parent sitting at the bottom with the newly
opened subtree below the fold. (Used by TUI Components + Profiles.)'''

from configsys.tui.menu import _scroll_reveal

H, N = 10, 50


def test_overflow_anchors_parent_at_top():
    # parent at row 20, view was [15..24]; the opened subtree runs to row 40 -> lift parent to the top
    assert _scroll_reveal(20, 40, 15, H, N) == 20


def test_subtree_already_fits_is_a_noop():
    # parent 16, subtree ends at 19, view [15..24] already contains it -> no jarring scroll
    assert _scroll_reveal(16, 19, 15, H, N) == 15


def test_parent_above_view_comes_into_view():
    assert _scroll_reveal(3, 8, 10, H, N) == 3


def test_parent_near_end_clamps_to_last_page():
    # can't put the parent at the very top without empty space -> clamp so the last page shows fully
    assert _scroll_reveal(48, 49, 20, H, N) == N - H


def test_list_shorter_than_window_stays_at_zero():
    assert _scroll_reveal(2, 5, 0, H, 6) == 0


def test_no_children_expanded_row_still_kept_visible():
    # subtree_end == parent (nothing opened / all collapsed) behaves like keeping the row in view
    assert _scroll_reveal(30, 30, 10, H, N) == 30      # below the [10..19] window -> anchor at top
    assert _scroll_reveal(12, 12, 10, H, N) == 10      # already visible -> unchanged
