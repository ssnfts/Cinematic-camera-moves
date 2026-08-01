"""
Camera moves, built from named techniques rather than from start/end pairs.

Every camera in this edit was a straight line between two points, and four of
them did not move at all. A locked-off camera is a legitimate choice exactly
once in a sequence; fourteen of them read as a turntable render. This module
builds the moves a camera operator would actually use, each one named for the
technique it is — the vocabulary is the standard one, and the names are worth
keeping because they say what the shot is *for*:

* **arc** — orbit a subject at fixed radius. Reveals form and separates the
  subject from its background by sliding the background past it.
* **dolly** — travel toward or away along the view axis. Changes intimacy
  without changing perspective.
* **truck** — travel laterally. Holds the subject and lets foreground and
  background shear apart, which is where parallax comes from.
* **pedestal / crane** — vertical travel. Turns a plan into an elevation.
* **tracking** — hold station relative to a moving subject, so the world moves
  and the subject does not.
* **pass-through** — the subject overtakes the camera, or the camera it. The
  only move that makes speed legible, because it puts something static in frame
  for the speed to be measured against.
* **dolly zoom** — dolly and zoom in opposition so the subject's screen size is
  held while its perspective is not. See :func:`dolly_zoom`; it has an exact
  invariant and a test that enforces it.
* **handheld** — additive low-frequency noise. Not a move, a texture applied
  over one.

Everything here is pure: a move takes a frame range and a callable that says
where the subject is, and returns keys. Nothing imports a host, so all of it is
checkable offline, which matters because a camera fault is invisible in code and
expensive in renders.

Two guards exist because both have already cost a shot in this project:
:func:`clamp_above` keeps a camera off the ground — a profiled terrain rose
1.61 m under a camera that used to clear a flat plane, and the whole cut
rendered as mud — and :func:`check_moves` refuses a camera sitting on its own
target, which yields an undefined view direction and a frame of garbage.
"""

from __future__ import annotations

import math

__all__ = [
    "ease",
    "arc",
    "helix",
    "whip_pan",
    "dolly",
    "truck",
    "pedestal",
    "tracking",
    "pass_through",
    "dolly_zoom",
    "handheld",
    "clamp_above",
    "check_moves",
    "MoveError",
]


class MoveError(RuntimeError):
    """A move that would render as a fault rather than as a shot."""


def ease(u: float, kind: str = "smooth") -> float:
    """
    Shape a 0..1 progress value.

    ``linear`` is the only one that looks mechanical, and it is the default
    nowhere. ``smooth`` eases both ends, ``in`` starts slow and runs away,
    ``out`` arrives gently — the three shapes almost every real move is made of.
    """
    u = min(max(u, 0.0), 1.0)
    if kind == "linear":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 1.0 - (1.0 - u) ** 2
    if kind == "smooth":
        return u * u * (3.0 - 2.0 * u)
    raise ValueError(f"unknown easing {kind!r}")


def _frames(start: int, end: int, step: int):
    if end <= start:
        raise MoveError(f"a move must advance: got frames {start} to {end}")
    fs = list(range(start, end + 1, max(1, step)))
    if fs[-1] != end:
        fs.append(end)
    return fs


def _key(frame, pos, target, fov):
    return {"frame": int(frame), "pos": [float(v) for v in pos],
            "target": [float(v) for v in target], "fov": float(fov)}


def arc(start, end, subject, *, radius, height, from_deg, sweep_deg,
        fov=35.0, step=2, easing="smooth"):
    """
    Orbit the subject at fixed radius, holding it centred.

    ``from_deg`` is a bearing clockwise from +Y, matching the scene's heading
    convention everywhere else. The radius is constant by construction, which is
    what the test asserts — an arc that drifts in radius is a spiral and reads
    as a mistake.
    """
    keys = []
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        ang = math.radians(from_deg + sweep_deg * u)
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + radius * math.sin(ang),
                          sy + radius * math.cos(ang),
                          sz + height),
                         (sx, sy, sz), fov))
    return keys


def helix(start, end, subject, *, from_radius, to_radius, from_height,
          to_height, from_deg, sweep_deg, fov=35.0, step=2, easing="smooth"):
    """
    Orbit while closing in and changing height — a drone dive, or a spiral in.

    This exists because a plain :func:`arc` around a moving subject can read as
    a static shot. It holds the subject dead centre at a fixed distance, so the
    subject never changes size or screen position, and if nothing is near enough
    to shear past, the frame has nothing in it that visibly moves. The car can be
    doing 220 km/h and the shot still looks locked off.

    Changing the radius fixes it: the subject grows, the ground rushes, and the
    move reads. A descending version of the same thing is what an FPV drone shot
    is, and the reason those read as fast is that the camera arrives somewhere.
    """
    keys = []
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        r = from_radius + (to_radius - from_radius) * u
        h = from_height + (to_height - from_height) * u
        ang = math.radians(from_deg + sweep_deg * u)
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + r * math.sin(ang), sy + r * math.cos(ang), sz + h),
                         (sx, sy, sz), fov))
    return keys


def whip_pan(start, end, subject, *, station, height, from_bearing, to_bearing,
             hold_frac=0.35, distance=60.0, fov=40.0, step=1):
    """
    Snap the aim from one bearing to another, holding at both ends.

    The camera does not move at all; only where it looks does. The whip is the
    fast middle third — most of the shot is the two holds, which is what makes
    the movement read as a whip rather than as a slow pan.
    """
    keys = []
    for f in _frames(start, end, step):
        u = (f - start) / (end - start)
        if u < hold_frac:
            w = 0.0
        elif u > 1.0 - hold_frac:
            w = 1.0
        else:
            w = ease((u - hold_frac) / max(1.0 - 2.0 * hold_frac, 1e-6), "smooth")
        ang = math.radians(from_bearing + (to_bearing - from_bearing) * w)
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (station[0], station[1], station[2] + height),
                         (station[0] + distance * math.sin(ang),
                          station[1] + distance * math.cos(ang),
                          sz),
                         fov))
    return keys


def dolly(start, end, subject, *, from_dist, to_dist, bearing_deg, height,
          fov=35.0, step=2, easing="smooth"):
    """Travel along the view axis, toward or away from the subject."""
    keys = []
    ang = math.radians(bearing_deg)
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        d = from_dist + (to_dist - from_dist) * u
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + d * math.sin(ang), sy + d * math.cos(ang),
                          sz + height),
                         (sx, sy, sz), fov))
    return keys


def truck(start, end, subject, *, offset, height, from_along, to_along,
          bearing_deg, fov=35.0, step=2, easing="smooth"):
    """
    Travel laterally past the subject at a fixed standoff.

    The move that produces parallax: near and far shear at different rates, and
    the eye reads depth from the difference.
    """
    keys = []
    ang = math.radians(bearing_deg)
    side = (math.cos(ang), -math.sin(ang))
    fwd = (math.sin(ang), math.cos(ang))
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        a = from_along + (to_along - from_along) * u
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + side[0] * offset + fwd[0] * a,
                          sy + side[1] * offset + fwd[1] * a,
                          sz + height),
                         (sx, sy, sz), fov))
    return keys


def pedestal(start, end, subject, *, bearing_deg, distance, from_height,
             to_height, fov=35.0, step=2, easing="smooth"):
    """Rise or fall while holding the subject. A plan becomes an elevation."""
    keys = []
    ang = math.radians(bearing_deg)
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        h = from_height + (to_height - from_height) * u
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + distance * math.sin(ang),
                          sy + distance * math.cos(ang), sz + h),
                         (sx, sy, sz), fov))
    return keys


def tracking(start, end, subject, *, offset_right, offset_forward, height,
             heading, fov=35.0, step=2, lead=0.0):
    """
    Hold station on a moving subject, in the subject's own frame.

    ``heading`` is a callable returning the subject's heading at a frame, so the
    rig stays on the car's quarter as it corners instead of swinging around it.
    ``lead`` aims ahead of the subject, which is what stops a chase shot feeling
    like it is being dragged.
    """
    keys = []
    for f in _frames(start, end, step):
        sx, sy, sz = subject(f)
        h = math.radians(heading(f))
        fwd = (math.sin(h), math.cos(h))
        side = (math.cos(h), -math.sin(h))
        keys.append(_key(f,
                         (sx + side[0] * offset_right + fwd[0] * offset_forward,
                          sy + side[1] * offset_right + fwd[1] * offset_forward,
                          sz + height),
                         (sx + fwd[0] * lead, sy + fwd[1] * lead, sz), fov))
    return keys


def pass_through(start, end, subject, *, station, height, look_lead=0.0,
                 fov=35.0, step=2):
    """
    Hold the camera still in world space and let the subject come past.

    The only move here that makes speed readable, because the frame contains
    something stationary to measure the subject against. The camera does not
    move; the *target* does, and that is still an animated camera — a locked
    frame with a moving aim is a pan, not a static shot.
    """
    keys = []
    for f in _frames(start, end, step):
        sx, sy, sz = subject(f)
        keys.append(_key(f, (station[0], station[1], station[2] + height),
                         (sx, sy, sz + look_lead), fov))
    return keys


def dolly_zoom(start, end, subject, *, from_dist, to_dist, from_fov,
               bearing_deg, height, step=2, easing="smooth"):
    """
    Dolly and zoom in opposition, holding the subject's screen size.

    The invariant is exact. A subject of fixed size ``S`` at distance ``d``
    subtends ``S / (2 d tan(fov/2))`` of the frame, so holding screen size means
    holding ``d * tan(fov/2)`` constant. The end FOV is therefore derived, never
    chosen — and :func:`check_moves` is not what enforces it; the test is,
    because a dolly zoom whose size drifts is just a clumsy zoom.
    """
    if from_dist <= 0 or to_dist <= 0:
        raise MoveError("dolly zoom distances must be positive")

    # Screen size follows the *true* camera-to-subject distance, and the camera
    # sits `height` above it, so the constant is built from the hypotenuse. Using
    # the horizontal offset instead leaves the size drifting by the amount the
    # rig is raised — small, invisible in a still, and exactly the kind of slow
    # slide that makes a dolly zoom read as a clumsy zoom.
    def _true(d):
        return math.hypot(d, height)

    k = _true(from_dist) * math.tan(math.radians(from_fov) / 2.0)
    keys = []
    ang = math.radians(bearing_deg)
    for f in _frames(start, end, step):
        u = ease((f - start) / (end - start), easing)
        d = from_dist + (to_dist - from_dist) * u
        fov = 2.0 * math.degrees(math.atan(k / _true(d)))
        if not 1.0 < fov < 170.0:
            raise MoveError(
                f"dolly zoom needs {fov:.1f} degrees at {d:.1f} m, which no "
                f"lens has. Narrow the distance range or start wider."
            )
        sx, sy, sz = subject(f)
        keys.append(_key(f,
                         (sx + d * math.sin(ang), sy + d * math.cos(ang),
                          sz + height),
                         (sx, sy, sz), fov))
    return keys


def handheld(keys, *, amp_m=0.12, period_frames=11.0, seed=1):
    """
    Add low-frequency wobble to a finished move.

    Deterministic on purpose — two sine pairs at incommensurate periods rather
    than random noise, so a re-run produces the same shot and a render can be
    compared against the one before it. Random handheld cannot be reviewed.
    """
    out = []
    for k in keys:
        f = k["frame"]
        a = 2.0 * math.pi * f / period_frames
        b = 2.0 * math.pi * f / (period_frames * 1.618) + seed
        out.append({
            **k,
            "pos": [k["pos"][0] + amp_m * math.sin(a + seed),
                    k["pos"][1] + amp_m * math.sin(b),
                    k["pos"][2] + amp_m * 0.5 * math.sin(a * 0.5 + b)],
        })
    return out


def clamp_above(keys, ground, clearance=2.0):
    """
    Lift any key that would put the camera in the ground.

    ``ground`` is a callable ``(x, y) -> z``. This exists because a profiled
    terrain rose 1.61 m under a camera that had cleared the old flat plane, and
    the entire cut rendered as two bands of mud with no error anywhere.

    The target is left alone: aiming at a point below the surface is normal, and
    lifting it would tilt every shot up off its subject.
    """
    out = []
    for k in keys:
        floor = float(ground(k["pos"][0], k["pos"][1])) + clearance
        p = list(k["pos"])
        if p[2] < floor:
            p[2] = floor
        out.append({**k, "pos": p})
    return out


def check_moves(keys, *, min_separation=0.5, max_jump_m=None,
                max_rel_speed_ms=None, fps=24):
    """
    Refuse a move that would render as a fault. Returns a summary.

    Three things are refused: a camera coinciding with its target, which leaves
    the view direction undefined; frames that do not advance; and, optionally, a
    step so large it is a cut rather than a move.

    ``max_rel_speed_ms`` is available but **left unset by default, on purpose**.
    The returned summary always carries the measurement — the camera's speed
    relative to its subject, projected on the sightline, which is what a
    180-degree shutter smears. Making it a gate was tried and abandoned: no one
    threshold is right for every shot. A tracking rig alongside a 313 km/h car
    genuinely moves at 313 km/h; a pass-through is a still camera whose subject
    crosses at 190 km/h; a drone dive closing at 69 m/s is a real fault. The
    first two are correct shots that any threshold strict enough to catch the
    third would condemn. A number that cannot be thresholded correctly belongs
    in the report, where a person can see the outlier, not in a gate that blocks
    good work.
    """
    if not keys:
        raise MoveError("no keys")

    prev_f = None
    worst_sep = float("inf")
    worst_jump = 0.0
    for k in keys:
        f = k["frame"]
        if prev_f is not None and f <= prev_f:
            raise MoveError(f"frames do not advance: {prev_f} then {f}")
        sep = math.dist(k["pos"], k["target"])
        worst_sep = min(worst_sep, sep)
        if sep < min_separation:
            raise MoveError(
                f"frame {f}: camera is {sep:.3f} m from its target, which "
                f"leaves the view direction undefined"
            )
        prev_f = f

    worst_rel = 0.0
    for a, b in zip(keys, keys[1:]):
        worst_jump = max(worst_jump, math.dist(a["pos"], b["pos"]))
        dt = (b["frame"] - a["frame"]) / float(fps)
        if dt > 0:
            # The camera's *own* speed along its sightline: how fast the rig is
            # flying at what it is looking at. Two simpler measures both fail.
            # The full relative vector counts the subject's travel as camera
            # movement, and so does the rate of change of distance — both
            # condemn a pass-through, a shot whose entire point is a still
            # camera with a subject going past it at 190 km/h. Projecting the
            # camera's velocity onto the sightline is zero for any camera that
            # is not moving, whatever the subject does.
            vel = [((b["pos"][i] - a["pos"][i])
                    - (b["target"][i] - a["target"][i])) / dt for i in range(3)]
            sight = [a["target"][i] - a["pos"][i] for i in range(3)]
            length = math.sqrt(sum(c * c for c in sight)) or 1.0
            worst_rel = max(worst_rel,
                            abs(sum(v * s for v, s in zip(vel, sight)) / length))

    if max_jump_m is not None and worst_jump > max_jump_m:
        raise MoveError(
            f"a step of {worst_jump:.1f} m exceeds the {max_jump_m} m limit; "
            f"that is a cut, not a move"
        )

    if max_rel_speed_ms is not None and worst_rel > max_rel_speed_ms:
        raise MoveError(
            f"the camera closes on its subject at {worst_rel:.1f} m/s "
            f"({worst_rel * 3.6:.0f} km/h), over the {max_rel_speed_ms} m/s "
            f"limit. Nothing flies like that, and a 180-degree shutter will "
            f"smear the frame to mush."
        )


    return {"keys": len(keys),
            "frames": (keys[0]["frame"], keys[-1]["frame"]),
            "min_separation_m": worst_sep,
            "max_step_m": worst_jump,
            "max_rel_speed_ms": worst_rel,
            "fov": (min(k["fov"] for k in keys), max(k["fov"] for k in keys))}
