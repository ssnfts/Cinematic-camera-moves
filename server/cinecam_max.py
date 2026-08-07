"""
The 3ds Max side: put the rollout on a camera, and make its buttons do work.

This is the only file in the project that imports a host, and it is deliberately
the thinnest one. It does four things and delegates everything else:

* builds the custom attribute from :mod:`maxui` and attaches it to a camera, so
  the controls appear at the end of that camera's Modify panel;
* reads the rollout back into plain numbers, in metres;
* calls :mod:`cinecam`, which has never heard of 3ds Max;
* writes the returned keys onto the camera.

No move maths happens here, on purpose. Everything that could be wrong about a
shot is decided in :mod:`cinecam` where a test can reach it; everything that is
decided here is a unit conversion, a property name, or a key write — the kinds
of thing that fail loudly on the first press rather than quietly in a render.

Units are the one real trap. The spec is in metres and a 3ds Max scene is in
whatever its system unit happens to be, so :func:`_unit_scale` is queried once
and applied at exactly two boundaries: the defaults baked into the generated
rollout, and the values read back out of it. A conversion anywhere else is a
bug.

Time is the other. Frames arrive from MAXScript as tick counts wearing a
different type, so anything time-shaped is fetched through ``mxs.execute`` with
an explicit ``as float``, which yields frames and cannot be misread.
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cinecam                      # noqa: E402
import maxui                        # noqa: E402
import movespec as spec             # noqa: E402

try:
    import pymxs                    # noqa: E402
    from pymxs import runtime as mxs
except ImportError as exc:          # pragma: no cover - only true outside Max
    raise ImportError(
        "cinecam_max runs inside 3ds Max; pymxs is not importable here. The "
        "move maths lives in cinecam.py, which imports no host at all and can "
        "be tested on its own."
    ) from exc

__all__ = [
    "install", "install_by_handle", "install_on_all_cameras", "remove",
    "enable_auto_attach", "disable_auto_attach",
    "build_keys", "apply_to", "preview", "clear_range",
    "ui_dispatch",
]

_TITLE = "Cinematic move"

_definition_cache = None
_helpers_loaded = False


# ── the host, asked exactly once per question ─────────────────────────────────

def _unit_scale() -> float:
    """System units in one metre. Every distance crosses this and no other."""
    try:
        return float(mxs.units.decodeValue("1m"))
    except Exception:
        return 1.0


def _frame(expr: str) -> float:
    """
    A time-valued MAXScript expression, in frames.

    ``as float`` on a MAXScript time gives frames; ``as integer`` gives ticks.
    Going through a string keeps that choice explicit instead of trusting
    whichever one the bridge happens to marshal.
    """
    return float(mxs.execute(f"(({expr}) as float)"))


def _fps() -> int:
    try:
        return int(mxs.framerate)
    except Exception:
        return 24


def _is_camera(node) -> bool:
    try:
        return bool(mxs.isKindOf(node, mxs.camera))
    except Exception:
        return bool(mxs.superClassOf(node) == mxs.camera)


def _all_cameras() -> list:
    try:
        return [c for c in mxs.cameras if _is_camera(c)]
    except TypeError:               # pragma: no cover - older bridges
        out, coll = [], mxs.cameras
        for i in range(int(coll.count)):
            c = mxs.execute(f"cameras[{i + 1}]")
            if _is_camera(c):
                out.append(c)
        return out


def _get(node, name):
    """A custom-attribute value, whether it answers on the node or the object."""
    if mxs.isProperty(node, name):
        return mxs.getProperty(node, name)
    return mxs.getProperty(node.baseObject, name)


def _set(node, name, value):
    if mxs.isProperty(node, name):
        mxs.setProperty(node, name, value)
    else:
        mxs.setProperty(node.baseObject, name, value)


# ── the definition, and getting it onto a camera ──────────────────────────────

def _definition(rebuild: bool = False):
    """
    The custom attribute definition, built once per session.

    Assigned to a MAXScript global and read back rather than taken as the return
    value of ``execute``. ``attributes name (...)`` is documented as the
    right-hand side of an assignment, and evaluating it bare relies on it also
    being an expression — true as far as anyone knows, and not worth a rollout
    that silently fails to attach if it stops being true.
    """
    global _definition_cache
    if _definition_cache is None or rebuild:
        src = maxui.attribute_definition(scale=_unit_scale())
        mxs.execute("global gCineCamDef\ngCineCamDef = " + src)
        _definition_cache = mxs.gCineCamDef
    return _definition_cache


_HELPERS = r'''
-- Deleting keys inside a frame range, written in MAXScript because key times
-- are times: `as float` is frames and `as integer` is ticks, and the conversion
-- is unambiguous on this side of the bridge and guesswork on the other.
fn cineCamClearAnim a f0 f1 depth = (
	local n = 0
	if a == undefined or depth > 6 do return 0
	try (
		local kc = numKeys a
		if kc != undefined and kc > 0 do
			for i = kc to 1 by -1 do (
				local t = (getKeyTime a i) as float
				if t >= f0 - 0.5 and t <= f1 + 0.5 do ( deleteKey a i; n += 1 )
			)
	) catch ()
	try (
		for i = 1 to (numSubs a) do
			n += cineCamClearAnim (getSubAnim a i) f0 f1 (depth + 1)
	) catch ()
	n
)

fn cineCamClearRange node f0 f1 = (
	local n = 0
	n += cineCamClearAnim (try(node.pos.controller)catch(undefined)) f0 f1 0
	n += cineCamClearAnim (try(node.rotation.controller)catch(undefined)) f0 f1 0
	n += cineCamClearAnim (try(node.fov.controller)catch(undefined)) f0 f1 0
	if (isProperty node #target) and node.target != undefined do
		n += cineCamClearAnim (try(node.target.pos.controller)catch(undefined)) f0 f1 0
	n
)
'''


def _ensure_helpers():
    global _helpers_loaded
    if not _helpers_loaded:
        mxs.execute(_HELPERS)
        _helpers_loaded = True


def has_rollout(node) -> bool:
    return bool(mxs.isProperty(node, "cc_move")) or \
        bool(mxs.isProperty(node.baseObject, "cc_move"))


def install(node, force: bool = False) -> bool:
    """
    Put the rollout on one camera. Returns whether anything changed.

    Attached to the *base object*, which is what makes it land at the end of the
    Modify panel under the camera's own rollouts rather than in the modifier
    stack. A camera with no modifiers still gets it, which is the point.
    """
    if not _is_camera(node):
        return False
    if has_rollout(node) and not force:
        return False
    mxs.custAttributes.add(node.baseObject, _definition())
    return True


def install_by_handle(handle) -> bool:
    node = mxs.maxOps.getNodeByHandle(int(handle))
    return bool(node) and install(node)


def install_on_all_cameras(force: bool = False) -> int:
    """Every camera in the open scene. Returns how many gained the rollout."""
    return sum(1 for c in _all_cameras() if install(c, force=force))


def remove(node) -> bool:
    obj = node.baseObject
    for i in range(int(mxs.custAttributes.count(obj)), 0, -1):
        ca = mxs.custAttributes.get(obj, i)
        if ca is not None and mxs.isProperty(ca, "cc_move"):
            mxs.custAttributes.delete(obj, i)
            return True
    return False


def enable_auto_attach() -> None:
    """
    Give every camera created from now on the rollout, without being asked.

    Registered from MAXScript rather than by handing a Python callable across
    the bridge: a ``NodeEventCallback`` has to stay alive in a global or it is
    collected, and a MAXScript global is the thing that reliably outlives this
    module being reloaded.
    """
    mxs.execute(r'''
global gCineCamNodeCB
fn cineCamOnNodesAdded ev nodes = (
	for h in nodes do (
		local n = maxOps.getNodeByHandle h
		if isValidNode n and (superClassOf n == camera) do
			try(python.Execute ("import cinecam_max\ncinecam_max.install_by_handle(" + (h as string) + ")"))catch()
	)
)
gCineCamNodeCB = NodeEventCallback added:cineCamOnNodesAdded
callbacks.removeScripts id:#cineCamAttach
callbacks.addScript #filePostOpen "try(python.Execute \"import cinecam_max\\ncinecam_max.install_on_all_cameras()\")catch()" id:#cineCamAttach
callbacks.addScript #systemPostNew "try(python.Execute \"import cinecam_max\\ncinecam_max.install_on_all_cameras()\")catch()" id:#cineCamAttach
''')


def disable_auto_attach() -> None:
    mxs.execute("global gCineCamNodeCB\n"
                "gCineCamNodeCB = undefined\n"
                "callbacks.removeScripts id:#cineCamAttach")


# ── reading the rollout ───────────────────────────────────────────────────────

def _value(p, node, scale):
    if p.kind == spec.VEC:
        return tuple(float(_get(node, f"{p.name}_{a}")) / scale
                     for a in ("x", "y", "z"))
    raw = _get(node, p.name)
    if p.kind == spec.DIST:
        return float(raw) / scale
    if p.kind in (spec.ANGLE, spec.FLOAT):
        return float(raw)
    if p.kind == spec.INT:
        return int(raw)
    if p.kind == spec.BOOL:
        return bool(raw)
    if p.kind == spec.ENUM:
        return spec.ENUM_VALUES[p.name][int(raw) - 1]
    if p.kind == spec.TEXT:
        return "" if raw is None else str(raw)
    return raw                       # a node, or undefined, which is None


def read(node) -> dict:
    """Every control on the camera, as plain Python, with distances in metres."""
    scale = _unit_scale()
    return {name: _value(p, node, scale) for name, p in spec.PARAMS.items()}


# ── the three callables cinecam asks for ──────────────────────────────────────

def _world(node, frame, scale):
    with pymxs.attime(frame):
        p = node.pos
    return (float(p.x) / scale, float(p.y) / scale, float(p.z) / scale)


def _subject_fn(v, scale):
    if v["cc_subject_mode"] == "node":
        node = v["cc_subject_node"]
        if node is None:
            raise cinecam.MoveError(
                "no subject node is picked. Pick one, or set the subject to a "
                "fixed point.")
        return lambda f: _world(node, f, scale)
    fixed = v["cc_subject"]
    return lambda _f: fixed


def _heading_fn(v, scale):
    """
    Which way the subject is facing, for a tracking rig.

    Three sources because all three are right somewhere. A rigged car knows its
    own heading and its Y axis is the honest answer. An animated dummy with no
    rotation keys does not, and its direction of travel is. A subject that
    stands still has neither, so a fixed angle is the only thing that does not
    swing the rig around on a divide-by-nothing.
    """
    node = v["cc_subject_node"]
    mode = v["cc_heading_mode"]
    fixed = v["cc_heading_deg"]

    if mode == "fixed" or node is None:
        return lambda _f: fixed

    if mode == "yaxis":
        def heading(f):
            with pymxs.attime(f):
                y = node.transform.row2
            return math.degrees(math.atan2(float(y.x), float(y.y)))
        return heading

    def heading(f):
        ax, ay, _ = _world(node, f, scale)
        bx, by, _ = _world(node, f + 1, scale)
        dx, dy = bx - ax, by - ay
        if math.hypot(dx, dy) < 1e-9:
            return fixed
        return math.degrees(math.atan2(dx, dy))
    return heading


def _ground_fn(node, scale):
    """
    Height of the ground under a point, by ray-cast.

    A miss returns a floor far below anything, so :func:`cinecam.clamp_above`
    leaves that key alone. Returning zero instead would drop a camera to the
    world origin's height the moment it flew past the edge of the terrain — a
    guard that creates the fault it exists to prevent.
    """
    top = float(node.max.z) + 10.0 * scale
    cache = {}

    def ground(x, y):
        key = (round(x, 3), round(y, 3))
        if key not in cache:
            ray = mxs.Ray(mxs.Point3(x * scale, y * scale, top),
                          mxs.Point3(0.0, 0.0, -1.0))
            hit = mxs.intersectRay(node, ray)
            cache[key] = -1.0e9 if hit is None else float(hit.pos.z) / scale
        return cache[key]
    return ground


# ── building ──────────────────────────────────────────────────────────────────

def build_keys(node):
    """
    Read the rollout, build the move, run the guards. Touches nothing.

    Returns ``(values, keys, report)``. Raises :class:`cinecam.MoveError` for
    anything that would render as a fault, which is the same refusal the module
    makes offline — this function adds no judgement of its own.
    """
    scale = _unit_scale()
    v = read(node)
    move = spec.MOVES[v["cc_move"]]

    kwargs = {arg: v[pname] for arg, pname in move.args.items()}

    if move.key == "tracking":
        kwargs["heading"] = _heading_fn(v, scale)

    # A picked station beats the typed one: it is easier to put a point helper
    # where the camera should stand than to type where it is.
    if "station" in kwargs and v["cc_station_node"] is not None:
        kwargs["station"] = _world(v["cc_station_node"], v["cc_start"], scale)

    keys = getattr(cinecam, move.key)(
        v["cc_start"], v["cc_end"], _subject_fn(v, scale), **kwargs)

    # Handheld first, then the clamp. The other order lets the wobble push a
    # cleared camera back into the ground, which is the exact fault the clamp
    # exists for.
    if v["cc_handheld"]:
        keys = cinecam.handheld(keys,
                                amp_m=v["cc_handheld_amp"],
                                period_frames=v["cc_handheld_period"],
                                seed=v["cc_handheld_seed"])

    if v["cc_clamp"]:
        if v["cc_ground"] is None:
            raise cinecam.MoveError(
                "ground clearance is on but no ground object is picked.")
        keys = cinecam.clamp_above(keys, _ground_fn(v["cc_ground"], scale),
                                   clearance=v["cc_clearance"])

    report = cinecam.check_moves(
        keys,
        min_separation=v["cc_min_sep"],
        max_jump_m=v["cc_max_jump"] or None,
        max_rel_speed_ms=v["cc_max_rel"] or None,
        fps=_fps())

    return v, keys, report


# ── writing ───────────────────────────────────────────────────────────────────

def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(sum(c * c for c in a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _lookat(pos, target, roll_deg):
    """
    A transform for a free camera, aimed at a point.

    A 3ds Max camera looks down its own -Z, so +Z is the vector from the target
    back to the camera. World +Z is the up reference except when the camera is
    within a fraction of a degree of looking straight down it, where the cross
    product collapses and the roll becomes whatever the floating point felt
    like; +Y takes over there.

    Roll is applied by spinning the two remaining axes rather than by composing
    a quaternion, because the sign convention of a quaternion product is a
    coin-flip that only shows up as a shot rolled the wrong way.
    """
    z = _unit(tuple(pos[i] - target[i] for i in range(3)))
    up = (0.0, 1.0, 0.0) if abs(z[2]) > 0.9995 else (0.0, 0.0, 1.0)
    x = _unit(_cross(up, z))
    y = _cross(z, x)

    if abs(roll_deg) > 1e-9:
        c = math.cos(math.radians(roll_deg))
        s = math.sin(math.radians(roll_deg))
        x, y = (tuple(x[i] * c + y[i] * s for i in range(3)),
                tuple(-x[i] * s + y[i] * c for i in range(3)))

    return mxs.Matrix3(mxs.Point3(*x), mxs.Point3(*y), mxs.Point3(*z),
                       mxs.Point3(*pos))


def _write(node, v, keys) -> list:
    scale = _unit_scale()
    target = node.target if mxs.isProperty(node, "target") else None
    has_fov = bool(mxs.isProperty(node, "fov"))
    notes = []

    if target is not None and abs(v["cc_roll"]) > 1e-9:
        notes.append("roll ignored: a targeted camera takes its roll from the "
                     "look-at controller")
    if not has_fov:
        notes.append("this camera has no fov property, so the lens was not "
                     "keyed")

    if v["cc_clear_first"]:
        _ensure_helpers()
        mxs.cineCamClearRange(node, float(v["cc_start"]), float(v["cc_end"]))

    with pymxs.animate(True):
        for k in keys:
            with pymxs.attime(k["frame"]):
                pos = [c * scale for c in k["pos"]]
                aim = [c * scale for c in k["target"]]
                if target is not None:
                    node.pos = mxs.Point3(*pos)
                    target.pos = mxs.Point3(*aim)
                else:
                    node.transform = _lookat(pos, aim, v["cc_roll"])
                if has_fov:
                    node.fov = float(k["fov"])

    return notes


# ── what the buttons do ───────────────────────────────────────────────────────

def _summary(v, report, notes=()) -> str:
    """
    One line, because the status box is one line.

    It carries the closing speed even though nothing gates on it. That number is
    measured on every move and thresholded on none, deliberately — a tracking
    rig beside a 313 km/h car genuinely moves at 313 km/h and a drone closing at
    69 m/s is a fault, and no single limit separates them. Putting it where a
    person reads it is the whole point of measuring it.
    """
    lo, hi = report["fov"]
    parts = [
        f"{spec.MOVES[v['cc_move']].label}: {report['keys']} keys",
        f"f{report['frames'][0]}-{report['frames'][1]}",
        f"nearest {report['min_separation_m']:.2f} m",
        f"step {report['max_step_m']:.2f} m",
        f"closing {report['max_rel_speed_ms']:.1f} m/s",
        f"lens {lo:.1f}-{hi:.1f} deg",
    ]
    parts += [f"NOTE {n}" for n in notes]
    return ", ".join(parts)


def preview(node) -> str:
    v, _keys, report = build_keys(node)
    return _summary(v, report)


def apply_to(node) -> str:
    v, keys, report = build_keys(node)
    notes = _write(node, v, keys)
    return _summary(v, report, notes)


def clear_range(node) -> str:
    _ensure_helpers()
    v = read(node)
    n = int(mxs.cineCamClearRange(node, float(v["cc_start"]),
                                  float(v["cc_end"])))
    return f"cleared {n} keys over frames {v['cc_start']}-{v['cc_end']}"


def range_from_scene(node) -> str:
    start = int(round(_frame("animationRange.start")))
    end = int(round(_frame("animationRange.end")))
    _set(node, "cc_start", start)
    _set(node, "cc_end", end)
    return f"frame range set to {start}-{end}"


def place_from_camera(node) -> str:
    """
    Fill the placement spinners in from where the camera is standing now.

    Framing a shot by dragging a camera in a viewport is faster than typing a
    bearing, and this is the button that turns the result into numbers the moves
    can use. It writes every spinner that describes the same standoff — radius,
    distance, standoff — because which one is live depends on the move, and
    filling only the live one means changing the move throws the framing away.
    """
    scale = _unit_scale()
    v = read(node)
    frame = _frame("sliderTime")
    sx, sy, sz = _subject_fn(v, scale)(frame)
    cx, cy, cz = _world(node, frame, scale)

    dx, dy = cx - sx, cy - sy
    planar = math.hypot(dx, dy)
    if planar < 1e-6:
        raise cinecam.MoveError(
            "the camera is directly over its subject, so there is no bearing "
            "to read. Move it off the vertical first.")

    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    height = cz - sz

    _set(node, "cc_bearing_deg", bearing)
    _set(node, "cc_from_deg", bearing)
    for name, value in (("cc_height", height),
                        ("cc_radius", planar),
                        ("cc_standoff", planar),
                        ("cc_from_dist", planar),
                        ("cc_from_radius", planar),
                        ("cc_offset", planar)):
        _set(node, name, value * scale)

    return (f"read from the camera: bearing {bearing:.1f} deg, "
            f"standoff {planar:.2f} m, height {height:.2f} m")


_ACTIONS = {
    "apply": apply_to,
    "preview": preview,
    "clear": clear_range,
    "range_from_scene": range_from_scene,
    "place_from_camera": place_from_camera,
}


def ui_dispatch(action: str, handle) -> None:
    """
    Every rollout button lands here.

    Nothing is allowed to escape as a traceback in the listener. A refused move
    is a sentence about what is wrong with the shot, and it goes both into the
    rollout's status box, where it stays after the dialog is dismissed, and into
    a dialog, so it cannot be missed.
    """
    node = mxs.maxOps.getNodeByHandle(int(handle))
    if node is None:
        mxs.messageBox("That camera no longer exists.", title=_TITLE)
        return

    try:
        text = _ACTIONS[action](node)
    except cinecam.MoveError as exc:
        text = f"refused: {exc}"
        _status(node, text)
        mxs.messageBox(f"{text}\n\nNothing was changed.", title=_TITLE)
        return
    except Exception as exc:                       # noqa: BLE001
        text = f"{type(exc).__name__}: {exc}"
        _status(node, text)
        mxs.messageBox(f"{text}\n\nNothing was changed.", title=_TITLE)
        return

    _status(node, text)
    print(f"[cinecam] {node.name}: {text}")


def _status(node, text) -> None:
    try:
        _set(node, "cc_status", str(text))
    except Exception:               # pragma: no cover - a status box, not work
        pass
