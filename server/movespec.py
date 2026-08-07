"""
What the camera rollout is allowed to ask for, declared once.

:mod:`cinecam` takes keyword arguments; a Modify-panel rollout takes spinners.
Something has to say which spinner is which argument, and the tempting place to
put that is inside the host bridge, next to the ``pymxs`` calls. That is the
wrong place, because it is the one place that cannot be tested without opening
3ds Max — and a rollout that quietly stops matching a function signature is
exactly the sort of fault this project already pays for in renders.

So the mapping lives here, as data, with no host import and no ``cinecam``
import either. Two things then consume it: :mod:`maxui`, which turns it into a
MAXScript custom attribute, and :mod:`cinecam_max`, which reads the rollout back
and calls the move. Both are generated from the same table, so they cannot
disagree with each other, and ``test_movespec`` checks the table against
:mod:`cinecam`'s real signatures, so the table cannot disagree with the moves.

Distances are metres here, always. The host works in whatever the scene's system
unit is; converting is :mod:`cinecam_max`'s job and it happens in exactly one
place.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Param",
    "Move",
    "Group",
    "DIST", "ANGLE", "FLOAT", "INT", "BOOL", "ENUM", "NODE", "VEC", "TEXT",
    "PARAMS",
    "MOVES",
    "MOVE_KEYS",
    "MOVE_LABELS",
    "EASING_KEYS",
    "EASING_LABELS",
    "SUBJECT_KEYS",
    "SUBJECT_LABELS",
    "HEADING_KEYS",
    "HEADING_LABELS",
    "ENUM_LABELS",
    "ENUM_VALUES",
    "SHOT_GROUPS",
    "GUARD_GROUPS",
    "APPLY_GROUPS",
    "ALL_GROUPS",
    "param",
    "params_used_by",
    "switched_params",
]


# Parameter kinds. DIST and VEC are the only ones that carry a unit, which is
# why they are distinguished from plain floats at all: everything else survives
# a unit change untouched, and these two do not.
DIST = "dist"
ANGLE = "angle"
FLOAT = "float"
INT = "int"
BOOL = "bool"
ENUM = "enum"
NODE = "node"
VEC = "vec"
TEXT = "text"


@dataclass(frozen=True)
class Param:
    """One control in the rollout, and one value on the camera."""

    name: str
    label: str
    kind: str
    default: object = 0.0
    lo: float = -1.0e7
    hi: float = 1.0e7
    items: tuple = ()
    help: str = ""


@dataclass(frozen=True)
class Group:
    """A titled box of controls. Purely how the rollout reads."""

    title: str
    params: tuple


@dataclass(frozen=True)
class Move:
    """
    One :mod:`cinecam` function, and where its arguments come from.

    ``args`` maps a *cinecam keyword* to a *parameter name*, and it is not
    always the identity: ``whip_pan`` and ``pedestal`` both take ``distance``,
    but one means how far the aim is thrown and the other means how far back the
    camera stands. Sharing a spinner between those two would be a control that
    means different things on different days.

    ``extra`` lists parameters the move needs that are not passed straight
    through — a picked station node, a heading source — so the rollout knows to
    enable them even though they never appear in a call.
    """

    key: str
    label: str
    args: dict
    extra: tuple = ()
    doc: str = ""

    def uses(self) -> frozenset:
        return frozenset(self.args.values()) | frozenset(self.extra)


# ── the parameters ────────────────────────────────────────────────────────────

_P = [
    # The shot itself.
    Param("cc_move", "Move", ENUM, 1,
          help="Which technique to build."),
    Param("cc_start", "First frame", INT, 0, -100000, 100000),
    Param("cc_end", "Last frame", INT, 100, -100000, 100000),
    Param("cc_step", "Key every", INT, 2, 1, 100,
          help="Frames between keys. 1 for a whip, 2 for most things."),
    Param("cc_easing", "Easing", ENUM, 1,
          help="Linear is the only one that looks mechanical."),

    # Where the subject is.
    Param("cc_subject_mode", "Subject from", ENUM, 1),
    Param("cc_subject_node", "Subject node", NODE, None,
          help="Sampled per frame, so a moving subject is tracked properly."),
    Param("cc_subject", "Subject", VEC, (0.0, 0.0, 0.0),
          -100000.0, 100000.0,
          help="Used when the subject is a fixed point rather than a node."),
    Param("cc_heading_mode", "Heading from", ENUM, 1,
          help="Tracking only: which way the subject is facing."),
    Param("cc_heading_deg", "Heading", ANGLE, 0.0, -3600.0, 3600.0),

    # Placement, shared by most moves.
    Param("cc_height", "Height over subject", DIST, 6.0, -100000.0, 100000.0),
    Param("cc_bearing_deg", "Bearing", ANGLE, 0.0, -3600.0, 3600.0,
          help="Clockwise from +Y, matching the scene's heading convention."),
    Param("cc_standoff", "Standoff", DIST, 25.0, 0.0, 100000.0,
          help="Pedestal: how far back the camera stands."),
    Param("cc_offset", "Lateral offset", DIST, 18.0, -100000.0, 100000.0,
          help="Truck: the standoff the camera holds as it slides past."),

    # Orbits.
    Param("cc_radius", "Radius", DIST, 30.0, 0.0, 100000.0),
    Param("cc_from_deg", "Start bearing", ANGLE, 0.0, -3600.0, 3600.0),
    Param("cc_sweep_deg", "Sweep", ANGLE, 120.0, -3600.0, 3600.0),
    Param("cc_from_radius", "Radius from", DIST, 80.0, 0.0, 100000.0),
    Param("cc_to_radius", "Radius to", DIST, 20.0, 0.0, 100000.0),

    # Vertical travel.
    Param("cc_from_height", "Height from", DIST, 40.0, -100000.0, 100000.0),
    Param("cc_to_height", "Height to", DIST, 6.0, -100000.0, 100000.0),

    # Travel along an axis.
    Param("cc_from_dist", "Distance from", DIST, 60.0, 0.001, 100000.0),
    Param("cc_to_dist", "Distance to", DIST, 18.0, 0.001, 100000.0),
    Param("cc_from_along", "Along from", DIST, -50.0, -100000.0, 100000.0),
    Param("cc_to_along", "Along to", DIST, 50.0, -100000.0, 100000.0),

    # A camera that stands still and aims.
    Param("cc_station_node", "Station node", NODE, None,
          help="Overrides the station point below when set."),
    Param("cc_station", "Station", VEC, (0.0, 0.0, 0.0),
          -100000.0, 100000.0),
    Param("cc_throw", "Aim throw", DIST, 60.0, 0.001, 100000.0,
          help="Whip pan: how far out the aim point is thrown."),
    Param("cc_from_bearing", "Aim from", ANGLE, 0.0, -3600.0, 3600.0),
    Param("cc_to_bearing", "Aim to", ANGLE, 90.0, -3600.0, 3600.0),
    Param("cc_hold_frac", "Hold at each end", FLOAT, 0.35, 0.0, 0.49,
          help="Most of a whip is the two holds; that is what makes it read."),

    # Riding with the subject.
    Param("cc_offset_right", "Offset right", DIST, 4.0, -100000.0, 100000.0),
    Param("cc_offset_forward", "Offset forward", DIST, -9.0,
          -100000.0, 100000.0),
    Param("cc_lead", "Aim lead", DIST, 0.0, -100000.0, 100000.0,
          help="Aim ahead of the subject so a chase is not being dragged."),
    Param("cc_look_lead", "Aim height lead", DIST, 0.0,
          -100000.0, 100000.0),

    # Lens.
    Param("cc_fov", "Field of view", FLOAT, 35.0, 1.0, 170.0),
    Param("cc_from_fov", "Start field of view", FLOAT, 28.0, 1.0, 170.0,
          help="Dolly zoom: the end of the range is derived, never chosen."),

    # Texture.
    Param("cc_handheld", "Add handheld", BOOL, False),
    Param("cc_handheld_amp", "Amplitude", DIST, 0.12, 0.0, 100.0),
    Param("cc_handheld_period", "Period", FLOAT, 11.0, 0.5, 1000.0,
          help="In frames. Deterministic, so two runs match."),
    Param("cc_handheld_seed", "Seed", INT, 1, 0, 100000),

    # Guards.
    Param("cc_clamp", "Keep off the ground", BOOL, False),
    Param("cc_ground", "Ground object", NODE, None,
          help="Ray-cast down onto this to find the surface under the rig."),
    Param("cc_clearance", "Clearance", DIST, 2.0, 0.0, 10000.0),
    Param("cc_min_sep", "Min camera-to-target", DIST, 0.5, 0.0, 10000.0,
          help="Below this the view direction is undefined and the move is "
               "refused."),
    Param("cc_max_jump", "Max step per key", DIST, 0.0, 0.0, 100000.0,
          help="Zero is off. Above this, the move is a cut and is refused."),
    Param("cc_max_rel", "Max closing speed", FLOAT, 0.0, 0.0, 100000.0,
          help="Metres per second, zero is off. Left off by default: no one "
               "threshold is right for every shot, so it is reported instead."),

    # Output.
    Param("cc_clear_first", "Clear keys in range first", BOOL, True),
    Param("cc_roll", "Roll", ANGLE, 0.0, -360.0, 360.0,
          help="Free cameras only; a targeted camera gets its roll from the "
               "look-at controller."),
    Param("cc_status", "", TEXT, "",
          help="Last result. Written by the bridge, not by hand."),
]

PARAMS = {p.name: p for p in _P}

if len(PARAMS) != len(_P):  # pragma: no cover - a typo guard, not a branch
    raise RuntimeError("duplicate parameter name in the spec")


def param(name: str) -> Param:
    return PARAMS[name]


# ── the enumerations, shared by the rollout and the bridge ────────────────────

MOVE_KEYS = ("arc", "helix", "whip_pan", "dolly", "truck", "pedestal",
             "tracking", "pass_through", "dolly_zoom")

MOVE_LABELS = ("Arc", "Helix", "Whip pan", "Dolly", "Truck",
               "Pedestal / crane", "Tracking", "Pass-through", "Dolly zoom")

EASING_KEYS = ("smooth", "in", "out", "linear")
EASING_LABELS = ("Smooth both ends", "Ease in", "Ease out", "Linear")

SUBJECT_KEYS = ("node", "point")
SUBJECT_LABELS = ("Scene node", "Fixed point")

HEADING_KEYS = ("yaxis", "motion", "fixed")
HEADING_LABELS = ("Subject's Y axis", "Direction of travel", "Fixed angle")

# Every dropdown, in one place: what it shows and what each row means. The
# rollout stores a 1-based index, so the labels and the keys have to stay in the
# same order — keeping the two halves side by side is what makes that checkable.
ENUM_LABELS = {
    "cc_move": MOVE_LABELS,
    "cc_easing": EASING_LABELS,
    "cc_subject_mode": SUBJECT_LABELS,
    "cc_heading_mode": HEADING_LABELS,
}

ENUM_VALUES = {
    "cc_move": MOVE_KEYS,
    "cc_easing": EASING_KEYS,
    "cc_subject_mode": SUBJECT_KEYS,
    "cc_heading_mode": HEADING_KEYS,
}


# ── the moves ─────────────────────────────────────────────────────────────────

_M = [
    Move("arc", "Arc",
         {"radius": "cc_radius", "height": "cc_height",
          "from_deg": "cc_from_deg", "sweep_deg": "cc_sweep_deg",
          "fov": "cc_fov", "step": "cc_step", "easing": "cc_easing"},
         doc="Orbit at fixed radius. Reveals form; slides the background past "
             "the subject."),

    Move("helix", "Helix",
         {"from_radius": "cc_from_radius", "to_radius": "cc_to_radius",
          "from_height": "cc_from_height", "to_height": "cc_to_height",
          "from_deg": "cc_from_deg", "sweep_deg": "cc_sweep_deg",
          "fov": "cc_fov", "step": "cc_step", "easing": "cc_easing"},
         doc="Orbit while closing in and changing height. Use this when an arc "
             "reads as a locked-off shot."),

    Move("whip_pan", "Whip pan",
         {"station": "cc_station", "height": "cc_height",
          "from_bearing": "cc_from_bearing", "to_bearing": "cc_to_bearing",
          "hold_frac": "cc_hold_frac", "distance": "cc_throw",
          "fov": "cc_fov", "step": "cc_step"},
         extra=("cc_station_node",),
         doc="The camera does not move; only where it looks does."),

    Move("dolly", "Dolly",
         {"from_dist": "cc_from_dist", "to_dist": "cc_to_dist",
          "bearing_deg": "cc_bearing_deg", "height": "cc_height",
          "fov": "cc_fov", "step": "cc_step", "easing": "cc_easing"},
         doc="Travel along the view axis. Changes intimacy, not perspective."),

    Move("truck", "Truck",
         {"offset": "cc_offset", "height": "cc_height",
          "from_along": "cc_from_along", "to_along": "cc_to_along",
          "bearing_deg": "cc_bearing_deg", "fov": "cc_fov",
          "step": "cc_step", "easing": "cc_easing"},
         doc="Travel laterally. This is where parallax comes from."),

    Move("pedestal", "Pedestal / crane",
         {"bearing_deg": "cc_bearing_deg", "distance": "cc_standoff",
          "from_height": "cc_from_height", "to_height": "cc_to_height",
          "fov": "cc_fov", "step": "cc_step", "easing": "cc_easing"},
         doc="Vertical travel. Turns a plan into an elevation."),

    Move("tracking", "Tracking",
         {"offset_right": "cc_offset_right",
          "offset_forward": "cc_offset_forward", "height": "cc_height",
          "fov": "cc_fov", "step": "cc_step", "lead": "cc_lead"},
         extra=("cc_heading_mode", "cc_heading_deg"),
         doc="Hold station in the subject's own frame, so the world moves and "
             "the subject does not."),

    Move("pass_through", "Pass-through",
         {"station": "cc_station", "height": "cc_height",
          "look_lead": "cc_look_lead", "fov": "cc_fov", "step": "cc_step"},
         extra=("cc_station_node",),
         doc="The subject comes past a still camera. The only move that makes "
             "speed legible."),

    Move("dolly_zoom", "Dolly zoom",
         {"from_dist": "cc_from_dist", "to_dist": "cc_to_dist",
          "from_fov": "cc_from_fov", "bearing_deg": "cc_bearing_deg",
          "height": "cc_height", "step": "cc_step", "easing": "cc_easing"},
         doc="Dolly and zoom in opposition, holding the subject's screen size "
             "exactly. The end lens is derived, not chosen."),
]

MOVES = {m.key: m for m in _M}


# ── how the rollout is laid out ───────────────────────────────────────────────

SHOT_GROUPS = (
    Group("Shot", ("cc_move", "cc_start", "cc_end", "cc_step", "cc_easing")),
    Group("Subject", ("cc_subject_mode", "cc_subject_node", "cc_subject",
                      "cc_heading_mode", "cc_heading_deg")),
    Group("Placement", ("cc_height", "cc_bearing_deg", "cc_standoff",
                        "cc_offset")),
    Group("Orbit", ("cc_radius", "cc_from_deg", "cc_sweep_deg",
                    "cc_from_radius", "cc_to_radius")),
    Group("Rise", ("cc_from_height", "cc_to_height")),
    Group("Travel", ("cc_from_dist", "cc_to_dist", "cc_from_along",
                     "cc_to_along")),
    Group("Station and aim", ("cc_station_node", "cc_station", "cc_throw",
                              "cc_from_bearing", "cc_to_bearing",
                              "cc_hold_frac")),
    Group("Riding with the subject", ("cc_offset_right", "cc_offset_forward",
                                      "cc_lead", "cc_look_lead")),
    Group("Lens", ("cc_fov", "cc_from_fov")),
)

GUARD_GROUPS = (
    Group("Handheld", ("cc_handheld", "cc_handheld_amp", "cc_handheld_period",
                       "cc_handheld_seed")),
    Group("Ground clearance", ("cc_clamp", "cc_ground", "cc_clearance")),
    Group("Refusals", ("cc_min_sep", "cc_max_jump", "cc_max_rel")),
)

APPLY_GROUPS = (
    Group("Output", ("cc_clear_first", "cc_roll")),
    Group("Last result", ("cc_status",)),
)

ALL_GROUPS = SHOT_GROUPS + GUARD_GROUPS + APPLY_GROUPS


def params_used_by(move_key: str) -> frozenset:
    """Every parameter the named move reads, passed through or not."""
    return MOVES[move_key].uses()


def switched_params() -> tuple:
    """
    Parameters whose relevance depends on which move is selected.

    Everything else — the frame range, the subject, the guards — applies to all
    nine, and the rollout leaves those enabled at all times. A control that is
    always on and a control that is sometimes on look different on purpose.
    """
    used = set()
    for m in MOVES.values():
        used |= m.uses()
    return tuple(n for n in PARAMS if n in used)
