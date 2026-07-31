'''Unit tests for the startup liquid-fill simulation (tui/splash.py).

Only the curses-free core (LiquidSim + palette maths) is tested here; LiquidSplash.play drives
curses and is exercised by hand / the run skill. The sim is deterministic given its rng, so these
assertions are stable.'''

import random

from configsys.tui import splash


def _sim(w=80, h=24, seed=0):
    return splash.LiquidSim(w, h, random.Random(seed))


def test_progress_maps_fraction_to_rows():
    sim = _sim(h=24)
    sim.set_progress(0.5)
    assert sim.target == 12.0            # 0.5 * 24
    sim.set_progress(1.0)
    assert sim.target == 24.0


def test_progress_is_clamped():
    sim = _sim(h=10)
    sim.set_progress(-3)
    assert sim.target == 0.0
    sim.set_progress(5)                  # >1 clamps to full, not 50 rows
    assert sim.target == 10.0


def test_progress_is_monotonic():
    '''A later, smaller fraction must not drop the water (no receding mid-flight).'''
    sim = _sim(h=20)
    sim.set_progress(0.8)
    assert sim.target == 16.0
    sim.set_progress(0.2)
    assert sim.target == 16.0            # unchanged


def test_level_eases_toward_target_over_time():
    sim = _sim(h=30)
    sim.set_progress(1.0)
    assert sim.level == 0.0
    sim.step(0.033)
    first = sim.level
    assert 0 < first < 30               # moved, but not instantly full
    for _ in range(300):
        sim.step(0.033)
    assert sim.filled and abs(sim.level - 30) < 0.1


def test_step_ignores_nonpositive_dt():
    sim = _sim()
    sim.set_progress(1.0)
    sim.step(0)
    sim.step(-1)
    assert sim.level == 0.0


def test_surface_is_flat_when_dry_and_wavy_when_filled():
    sim = _sim(w=80, h=24)
    assert sim.surface_height(10) <= 0.01        # dry -> no wave
    sim.set_progress(1.0)
    for _ in range(120):
        sim.step(0.033)
    heights = [sim.surface_height(x) for x in range(0, 80, 4)]
    assert max(heights) - min(heights) > 0.2     # the surface wave varies across columns


def test_fish_need_water_and_are_capped():
    sim = _sim(w=80, h=24, seed=3)
    # dry: many steps, no fish can spawn
    for _ in range(200):
        sim._step_fish(0.033)
    assert sim.fish == []
    # fill up, then run long enough to hit the population cap
    sim.set_progress(1.0)
    for _ in range(800):
        sim.step(0.02)
    cap = max(1, sim.w // 26)
    assert 0 < len(sim.fish) <= cap


def test_fish_leave_the_screen():
    sim = _sim(w=40, h=20, seed=5)
    sim.set_progress(1.0)
    for _ in range(200):
        sim.step(0.02)
    for f in sim.fish:                            # every live fish is within/near the bounds
        assert -f.width - 1 <= f.x <= sim.w + 1


def test_boats_need_a_sea_and_are_capped_and_leave():
    sim = _sim(w=80, h=24, seed=9)
    # shallow water: no boat ever spawns
    sim.set_progress(0.1)
    for _ in range(60):
        sim.step(0.033)
    assert sim.boats == []
    # a proper sea, run long: at most one boat, and it stays within bounds
    sim.set_progress(1.0)
    saw = 0
    for _ in range(1500):
        sim.step(0.02)
        saw = max(saw, len(sim.boats))
        assert len(sim.boats) <= 1
        for b in sim.boats:
            assert -3 <= b.x <= sim.w + 3
    assert saw == 1                                  # a boat did appear over that long a sea


def test_starfield_scatters_in_the_upper_sky():
    sim = _sim(w=80, h=24, seed=7)
    assert len(sim.stars) >= 4
    sky_rows = int(sim.h * 0.72)
    for row, col, glyph, phase, ci in sim.stars:
        assert 0 <= row < sky_rows                 # upper sky only, not down at the seabed
        assert 0 <= col < sim.w
        assert glyph in splash.STAR_GLYPHS
        assert 0 <= ci <= 2                         # a valid colour index
    # stars are fixed for the run — advancing the sim doesn't move them
    before = list(sim.stars)
    for _ in range(50):
        sim.step(0.03)
    assert sim.stars == before


def test_moon_is_at_most_one_and_stable():
    seen = set()
    for seed in range(40):
        m = _sim(seed=seed).moon
        assert m in (None, '☽', '☾')          # never both, never anything else
        seen.add(m)
    assert seen == {None, '☽', '☾'}            # all three outcomes occur across seeds
    # the moon is fixed for a run — it doesn't change as the sim advances
    sim = _sim(seed=1)
    m0 = sim.moon
    sim.set_progress(1.0)
    for _ in range(200):
        sim.step(0.03)
    assert sim.moon == m0


def test_comet_needs_no_water_and_vanishes_at_the_waterline():
    sim = _sim(w=80, h=24, seed=2)
    sim.set_progress(1.0)                       # a full sea -> waterline near the top
    for _ in range(200):
        sim.step(0.033)
        for c in sim.comets:                    # any live comet is above the water at its column
            assert c.y < sim.h - sim.surface_height(c.x) + 1
            assert -2 <= c.x <= sim.w + 2


def test_skeleton_needs_a_deep_sea_and_is_capped():
    sim = _sim(w=80, h=24, seed=4)
    sim.set_progress(0.2)                       # shallow -> no skeleton ever
    for _ in range(200):
        sim.step(0.033)
    assert sim.skeletons == []
    sim.set_progress(1.0)
    for _ in range(3000):
        sim.step(0.02)
        assert len(sim.skeletons) <= 1
        for sk in sim.skeletons:
            assert 0 <= sk.x < sim.w


def test_fish_sprites_are_directional_and_sized():
    # right-swimmers end in a right head, left-swimmers start with a left head
    assert all(f[-1] in '▶►' for f in splash.FISH_RIGHT)
    assert all(f[0] in '◀◄' for f in splash.FISH_LEFT)
    assert any('■' in f for f in splash.FISH_RIGHT) and any('▪' in f for f in splash.FISH_RIGHT)


def test_fish_use_all_tail_brackets_for_variety():
    openings = {p[0] for p in splash._TAILS}
    closings = {p[1] for p in splash._TAILS}
    assert len(openings) == 7 and len(closings) == 7
    # every closing bracket tails some right-swimmer; every opening some left-swimmer
    assert all(any(f.startswith(c) for f in splash.FISH_RIGHT) for c in closings)
    assert all(any(f.endswith(o) for f in splash.FISH_LEFT) for o in openings)


def test_label_shows_counts_and_percent():
    # exact format the label renders (built without curses via __new__)
    s = splash.LiquidSplash.__new__(splash.LiquidSplash)
    s.label = 'checking install state'
    assert s._label_text((14, 70)) == 'checking install state:   14/70 (20%)'
    assert s._label_text((70, 70)) == 'checking install state:   70/70 (100%)'
    assert s._label_text((0, 0)) == 'checking install state…'      # total unknown yet


def test_random_palette_shape_and_range():
    deep, surface, foam, fish, bubble = splash.random_palette(random.Random(11))
    for rgb in (deep, surface, foam, fish, bubble):
        assert len(rgb) == 3
        assert all(0 <= c <= 255 for c in rgb)
    # deep is darker than the surface (that's the whole point of the depth ramp)
    assert sum(deep) < sum(surface)


def test_random_palette_varies_by_seed():
    a = splash.random_palette(random.Random(1))
    b = splash.random_palette(random.Random(2))
    assert a != b


def test_lerp_endpoints_and_midpoint():
    assert splash._lerp((0, 0, 0), (100, 200, 50), 0) == (0, 0, 0)
    assert splash._lerp((0, 0, 0), (100, 200, 50), 1) == (100, 200, 50)
    assert splash._lerp((0, 0, 0), (100, 200, 50), 0.5) == (50, 100, 25)
