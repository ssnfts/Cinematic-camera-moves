"""
Tests for cinecam.py — offline, no host.

A camera fault is invisible in code and expensive in renders, so the moves are
checked against the invariant each one is defined by: an arc holds its radius, a
dolly zoom holds its subject's screen size, a tracking rig holds station. Those
cannot be satisfied by a move that is subtly wrong.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import cinecam  # noqa: E402


def moving(f):
    """A subject travelling north-east and climbing gently."""
    return (100.0 + 0.9 * f, 200.0 + 0.4 * f, 5.0 + 0.01 * f)


def still(_f):
    return (100.0, 200.0, 5.0)


def heading(_f):
    return 45.0


# ── easing ────────────────────────────────────────────────────────────────────

def test_easing_is_bounded_and_hits_both_ends():
    for kind in ("linear", "in", "out", "smooth"):
        assert cinecam.ease(0.0, kind) == pytest.approx(0.0)
        assert cinecam.ease(1.0, kind) == pytest.approx(1.0)
        for i in range(21):
            assert 0.0 <= cinecam.ease(i / 20, kind) <= 1.0


def test_easing_is_monotone():
    for kind in ("linear", "in", "out", "smooth"):
        prev = -1.0
        for i in range(51):
            v = cinecam.ease(i / 50, kind)
            assert v >= prev - 1e-12, kind
            prev = v


def test_easing_clamps_outside_the_range():
    assert cinecam.ease(-5.0) == pytest.approx(0.0)
    assert cinecam.ease(9.0) == pytest.approx(1.0)


def test_unknown_easing_is_refused():
    with pytest.raises(ValueError, match="unknown easing"):
        cinecam.ease(0.5, "bouncy")


# ── each move's defining invariant ────────────────────────────────────────────

def test_arc_holds_its_radius():
    """An arc that drifts in radius is a spiral, and reads as a mistake."""
    keys = cinecam.arc(100, 200, moving, radius=30.0, height=8.0,
                       from_deg=0.0, sweep_deg=120.0)
    for k in keys:
        planar = math.dist(k["pos"][:2], k["target"][:2])
        assert planar == pytest.approx(30.0, abs=1e-9)


def test_arc_actually_sweeps():
    keys = cinecam.arc(100, 200, still, radius=30.0, height=8.0,
                       from_deg=0.0, sweep_deg=120.0)
    def bearing(k):
        dx = k["pos"][0] - k["target"][0]
        dy = k["pos"][1] - k["target"][1]
        return math.degrees(math.atan2(dx, dy)) % 360.0
    assert abs((bearing(keys[-1]) - bearing(keys[0])) % 360.0 - 120.0) < 1e-6


def test_dolly_zoom_holds_the_subject_size():
    """
    The exact invariant: screen size goes as 1 / (d * tan(fov/2)), so that
    product must be constant. A dolly zoom whose size drifts is a clumsy zoom.
    """
    keys = cinecam.dolly_zoom(100, 200, still, from_dist=40.0, to_dist=12.0,
                              from_fov=28.0, bearing_deg=200.0, height=2.0)
    ref = None
    for k in keys:
        d = math.dist(k["pos"], k["target"])
        product = d * math.tan(math.radians(k["fov"]) / 2.0)
        if ref is None:
            ref = product
        assert product == pytest.approx(ref, rel=1e-9)


def test_dolly_zoom_actually_changes_the_lens():
    keys = cinecam.dolly_zoom(100, 200, still, from_dist=40.0, to_dist=12.0,
                              from_fov=28.0, bearing_deg=200.0, height=2.0)
    assert keys[-1]["fov"] > keys[0]["fov"] * 2.0


def test_dolly_zoom_refuses_an_impossible_lens():
    with pytest.raises(cinecam.MoveError, match="no lens has"):
        cinecam.dolly_zoom(100, 200, still, from_dist=200.0, to_dist=0.4,
                           from_fov=40.0, bearing_deg=0.0, height=2.0)


def test_dolly_changes_distance_monotonically():
    keys = cinecam.dolly(100, 200, still, from_dist=80.0, to_dist=15.0,
                         bearing_deg=30.0, height=3.0)
    ds = [math.dist(k["pos"], k["target"]) for k in keys]
    assert ds[0] == pytest.approx(math.hypot(80.0, 3.0), rel=1e-9)
    assert all(b <= a + 1e-9 for a, b in zip(ds, ds[1:]))


def test_tracking_holds_station_on_the_subject():
    """The world moves and the subject does not — that is the whole point."""
    keys = cinecam.tracking(100, 200, moving, offset_right=4.0,
                            offset_forward=-9.0, height=1.5, heading=heading)
    ref = None
    for k in keys:
        sx, sy, sz = moving(k["frame"])
        d = math.dist(k["pos"], (sx, sy, sz))
        if ref is None:
            ref = d
        assert d == pytest.approx(ref, rel=1e-9)


def test_tracking_can_lead_the_subject():
    plain = cinecam.tracking(100, 120, moving, offset_right=0.0,
                             offset_forward=-9.0, height=1.5, heading=heading)
    led = cinecam.tracking(100, 120, moving, offset_right=0.0,
                           offset_forward=-9.0, height=1.5, heading=heading,
                           lead=12.0)
    assert math.dist(led[0]["target"], plain[0]["target"]) == pytest.approx(12.0)


def test_pass_through_holds_the_camera_and_moves_the_aim():
    """A locked frame with a moving aim is a pan, not a static shot."""
    keys = cinecam.pass_through(100, 200, moving, station=(150.0, 260.0, 5.0),
                                height=1.2)
    assert all(k["pos"] == keys[0]["pos"] for k in keys)
    assert math.dist(keys[0]["target"], keys[-1]["target"]) > 50.0


def test_pedestal_changes_only_height():
    keys = cinecam.pedestal(100, 200, still, bearing_deg=90.0, distance=25.0,
                            from_height=1.5, to_height=40.0)
    xs = {round(k["pos"][0], 9) for k in keys}
    ys = {round(k["pos"][1], 9) for k in keys}
    assert len(xs) == 1 and len(ys) == 1
    assert keys[-1]["pos"][2] - keys[0]["pos"][2] == pytest.approx(38.5)


def test_truck_travels_laterally_at_fixed_standoff():
    keys = cinecam.truck(100, 200, still, offset=18.0, height=3.0,
                         from_along=-60.0, to_along=60.0, bearing_deg=0.0)
    assert math.dist(keys[0]["pos"][:2], keys[-1]["pos"][:2]) == \
        pytest.approx(120.0, rel=1e-9)


def test_helix_closes_in_and_changes_height():
    """
    The move that fixes a shot reading as static.

    An arc holds the subject at a fixed distance, so it never changes size and
    the frame has nothing in it that visibly moves. A helix arrives somewhere.
    """
    keys = cinecam.helix(100, 200, moving, from_radius=90.0, to_radius=18.0,
                         from_height=60.0, to_height=6.0, from_deg=0.0,
                         sweep_deg=120.0)
    first = math.dist(keys[0]["pos"][:2], keys[0]["target"][:2])
    last = math.dist(keys[-1]["pos"][:2], keys[-1]["target"][:2])
    assert first == pytest.approx(90.0, abs=1e-9)
    assert last == pytest.approx(18.0, abs=1e-9)
    assert keys[-1]["pos"][2] < keys[0]["pos"][2] - 40.0


def test_helix_radius_is_monotone():
    keys = cinecam.helix(100, 200, still, from_radius=90.0, to_radius=18.0,
                         from_height=60.0, to_height=6.0, from_deg=0.0,
                         sweep_deg=120.0)
    ds = [math.dist(k["pos"][:2], k["target"][:2]) for k in keys]
    assert all(b <= a + 1e-9 for a, b in zip(ds, ds[1:]))


def test_helix_changes_the_subject_size_unlike_an_arc():
    """The whole point: an arc cannot do this, which is why shot 6 read static."""
    a = cinecam.arc(100, 200, moving, radius=30.0, height=8.0,
                    from_deg=0.0, sweep_deg=120.0)
    h = cinecam.helix(100, 200, moving, from_radius=80.0, to_radius=15.0,
                      from_height=30.0, to_height=5.0, from_deg=0.0,
                      sweep_deg=120.0)
    arc_spread = {round(math.dist(k["pos"], k["target"]), 3) for k in a}
    helix_first = math.dist(h[0]["pos"], h[0]["target"])
    helix_last = math.dist(h[-1]["pos"], h[-1]["target"])
    assert len(arc_spread) == 1
    assert helix_first / helix_last > 3.0


def test_whip_pan_holds_the_camera_and_holds_both_ends():
    keys = cinecam.whip_pan(100, 200, still, station=(50.0, 60.0, 5.0),
                            height=2.0, from_bearing=0.0, to_bearing=90.0)
    assert all(k["pos"] == keys[0]["pos"] for k in keys)

    def bearing(k):
        dx = k["target"][0] - k["pos"][0]
        dy = k["target"][1] - k["pos"][1]
        return math.degrees(math.atan2(dx, dy)) % 360.0

    early = [bearing(k) for k in keys if k["frame"] < 125]
    late = [bearing(k) for k in keys if k["frame"] > 175]
    assert max(early) - min(early) < 1e-6
    assert max(late) - min(late) < 1e-6
    assert abs(late[0] - early[0] - 90.0) < 1e-6


def test_whip_pan_is_fastest_in_the_middle():
    keys = cinecam.whip_pan(100, 200, still, station=(50.0, 60.0, 5.0),
                            height=2.0, from_bearing=0.0, to_bearing=90.0)

    def bearing(k):
        dx = k["target"][0] - k["pos"][0]
        dy = k["target"][1] - k["pos"][1]
        return math.degrees(math.atan2(dx, dy)) % 360.0

    rates = [abs(bearing(b) - bearing(a)) for a, b in zip(keys, keys[1:])]
    mid = rates[len(rates) // 2]
    assert mid > 0.0
    assert mid > max(rates[:5] + rates[-5:]) + 1.0


# ── the guards, both of which have already cost a shot ────────────────────────

def test_clamp_lifts_a_camera_the_terrain_grew_under():
    """
    Shot 12, exactly. The camera cleared a flat plane at 5.27; the profiled
    surface came up to 8.48 and the whole cut rendered as mud.
    """
    keys = cinecam.dolly(100, 120, still, from_dist=30.0, to_dist=10.0,
                         bearing_deg=0.0, height=1.6)
    lifted = cinecam.clamp_above(keys, lambda x, y: 8.477, clearance=2.0)
    assert all(k["pos"][2] >= 10.477 - 1e-9 for k in lifted)


def test_clamp_leaves_a_clear_camera_alone():
    keys = cinecam.pedestal(100, 120, still, bearing_deg=0.0, distance=20.0,
                            from_height=40.0, to_height=60.0)
    same = cinecam.clamp_above(keys, lambda x, y: 5.0, clearance=2.0)
    assert [k["pos"] for k in same] == [k["pos"] for k in keys]


def test_clamp_does_not_move_the_target():
    keys = cinecam.dolly(100, 120, still, from_dist=30.0, to_dist=10.0,
                         bearing_deg=0.0, height=0.2)
    lifted = cinecam.clamp_above(keys, lambda x, y: 50.0, clearance=2.0)
    assert [k["target"] for k in lifted] == [k["target"] for k in keys]


def test_a_camera_on_its_target_is_refused():
    keys = cinecam.dolly(100, 120, still, from_dist=8.0, to_dist=0.05,
                         bearing_deg=0.0, height=0.0)
    with pytest.raises(cinecam.MoveError, match="view direction undefined"):
        cinecam.check_moves(keys)


def test_a_teleport_is_refused():
    keys = cinecam.arc(100, 140, still, radius=30.0, height=5.0,
                       from_deg=0.0, sweep_deg=350.0, step=20)
    with pytest.raises(cinecam.MoveError, match="that is a cut, not a move"):
        cinecam.check_moves(keys, max_jump_m=5.0)


def test_a_backwards_range_is_refused():
    with pytest.raises(cinecam.MoveError, match="must advance"):
        cinecam.arc(200, 100, still, radius=10.0, height=2.0,
                    from_deg=0.0, sweep_deg=90.0)


def test_check_reports_a_summary():
    keys = cinecam.arc(100, 200, moving, radius=25.0, height=6.0,
                       from_deg=10.0, sweep_deg=90.0)
    got = cinecam.check_moves(keys)
    assert got["frames"] == (100, 200)
    assert got["min_separation_m"] > 20.0


# ── handheld ──────────────────────────────────────────────────────────────────

def test_handheld_is_deterministic():
    """Random handheld cannot be reviewed against the render before it."""
    base = cinecam.dolly(100, 200, still, from_dist=40.0, to_dist=20.0,
                         bearing_deg=0.0, height=2.0)
    a = cinecam.handheld(base, seed=3)
    b = cinecam.handheld(base, seed=3)
    assert [k["pos"] for k in a] == [k["pos"] for k in b]


def test_handheld_is_bounded_and_actually_moves():
    base = cinecam.dolly(100, 200, still, from_dist=40.0, to_dist=20.0,
                         bearing_deg=0.0, height=2.0)
    shaken = cinecam.handheld(base, amp_m=0.2)
    offsets = [math.dist(a["pos"], b["pos"]) for a, b in zip(base, shaken)]
    assert max(offsets) > 0.02
    assert max(offsets) <= 0.2 * math.sqrt(2.25) + 1e-9


def test_handheld_leaves_the_aim_alone():
    base = cinecam.dolly(100, 200, still, from_dist=40.0, to_dist=20.0,
                         bearing_deg=0.0, height=2.0)
    assert [k["target"] for k in cinecam.handheld(base)] == \
        [k["target"] for k in base]


# ── every move must survive the checker ───────────────────────────────────────

def test_all_moves_pass_their_own_checker():
    made = [
        cinecam.arc(100, 200, moving, radius=30.0, height=9.0,
                    from_deg=0.0, sweep_deg=140.0),
        cinecam.dolly(100, 200, moving, from_dist=70.0, to_dist=18.0,
                      bearing_deg=210.0, height=4.0),
        cinecam.truck(100, 200, moving, offset=20.0, height=3.0,
                      from_along=-50.0, to_along=50.0, bearing_deg=15.0),
        cinecam.pedestal(100, 200, moving, bearing_deg=120.0, distance=30.0,
                         from_height=2.0, to_height=45.0),
        cinecam.tracking(100, 200, moving, offset_right=5.0,
                         offset_forward=-11.0, height=1.6, heading=heading),
        cinecam.pass_through(100, 200, moving, station=(400.0, 400.0, 5.0),
                             height=1.0),
        cinecam.dolly_zoom(100, 200, moving, from_dist=45.0, to_dist=16.0,
                           from_fov=24.0, bearing_deg=300.0, height=3.0),
    ]
    for keys in made:
        assert cinecam.check_moves(keys)["keys"] >= 2
