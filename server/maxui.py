"""
The Modify-panel rollout, written out as MAXScript from the spec.

3ds Max will only put controls on a camera if it is handed a *custom attribute
definition* — a block of MAXScript declaring parameters and the rollouts that
edit them. Hand-writing that block would mean maintaining, by hand, a second
copy of every parameter :mod:`movespec` already declares, in a language with no
test runner attached. The two copies would drift, and the way that failure
presents is a spinner that silently edits nothing.

So the block is generated. This module is pure string assembly with no host
import, which means the exact text that 3ds Max is going to evaluate can be
checked offline, and ``test_maxui`` does check it: every parameter gets a
control, every control gets a parameter, and every move switches on the controls
its own function actually takes.

The one thing that cannot be generated blind is distance. A ``#worldUnits``
parameter's default and range are in *system units*, and the spec is in metres,
so :func:`attribute_definition` takes the scene's scale and applies it in the
one place it belongs. A scene set to centimetres gets a 3000-unit default radius
and a spinner that reads 30 m, rather than a 30-unit radius that reads 0.3 m.
"""

from __future__ import annotations

import movespec as spec

__all__ = [
    "ATTRIBUTE_NAME",
    "VERSION",
    "control_name",
    "param_names",
    "attribute_definition",
]

ATTRIBUTE_NAME = "CineCamMove"

# Bumped whenever the parameter block changes shape. 3ds Max uses this together
# with the attribute ID to decide whether an existing camera's stored values can
# be carried across, so it is not decoration.
VERSION = 1

# Arbitrary but fixed. Two definitions sharing an ID are treated as the same
# attribute, which is what lets a scene saved yesterday open against today's
# rollout instead of arriving with a dead one.
ATTRIBUTE_ID = ("0x5c1e6a37", "0x2f9b4ae1")

_ROLLOUTS = (
    ("rlo_cc_shot", "Cinematic move", spec.SHOT_GROUPS),
    ("rlo_cc_guard", "Cinematic move: texture and guards", spec.GUARD_GROUPS),
    ("rlo_cc_apply", "Cinematic move: apply", spec.APPLY_GROUPS),
)

# Controls that are never switched off by the move dropdown, because every move
# needs them.
_ALWAYS_ON = ("cc_move", "cc_start", "cc_end", "cc_subject_mode", "cc_status",
              "cc_clear_first", "cc_roll", "cc_min_sep", "cc_max_jump",
              "cc_max_rel", "cc_handheld", "cc_clamp")

# Controls with a second condition on top of the move: the subject pickers
# follow the subject-mode dropdown, and a fixed heading is only meaningful when
# the heading source is set to fixed.
_ALSO_NEEDS = {
    "cc_subject_node": "sm == 1",
    "cc_subject": "sm == 2",
    "cc_heading_deg": "cc_heading_mode == 3",
    "cc_handheld_amp": "cc_handheld",
    "cc_handheld_period": "cc_handheld",
    "cc_handheld_seed": "cc_handheld",
    "cc_ground": "cc_clamp",
    "cc_clearance": "cc_clamp",
}

_PREFIX = {
    spec.ENUM: "ddl", spec.BOOL: "chk", spec.NODE: "pck", spec.TEXT: "txt",
}

_MXS_TYPE = {
    spec.DIST: "#worldUnits", spec.VEC: "#worldUnits", spec.ANGLE: "#float",
    spec.FLOAT: "#float", spec.INT: "#integer", spec.BOOL: "#boolean",
    spec.ENUM: "#integer", spec.NODE: "#node", spec.TEXT: "#string",
}

_SPINNER_TYPE = {
    spec.DIST: "#worldunits", spec.VEC: "#worldunits", spec.ANGLE: "#float",
    spec.FLOAT: "#float", spec.INT: "#integer",
}

_AXES = ("x", "y", "z")


# ── names ─────────────────────────────────────────────────────────────────────

def control_name(p, axis: str | None = None) -> str:
    """The MAXScript control id for a parameter, or for one axis of a vector."""
    if p.kind == spec.VEC:
        return f"spn_{p.name}_{axis}"
    return f"{_PREFIX.get(p.kind, 'spn')}_{p.name}"


def param_names(p) -> tuple:
    """
    The MAXScript parameter names a spec parameter becomes.

    One for everything except a vector, which becomes three, because a
    ``#point3`` bound to three spinners has to name each spinner anyway and
    three plain values are easier to read back than a packed one.
    """
    if p.kind == spec.VEC:
        return tuple(f"{p.name}_{a}" for a in _AXES)
    return (p.name,)


# ── literals ──────────────────────────────────────────────────────────────────

def _num(v) -> str:
    """
    A number MAXScript will certainly parse.

    Plain decimal, never scientific: whether MAXScript accepts an explicit
    exponent sign in ``1e+07`` is the kind of question that gets answered by a
    rollout failing to load on someone else's machine, and a spinner range does
    not need the notation badly enough to find out.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    f = float(v)
    if f == int(f) and abs(f) < 1.0e15:
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def _str(s) -> str:
    """A MAXScript double-quoted literal, with the two things that break one."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tip(p) -> str:
    return f" tooltip:{_str(p.help)}" if p.help else ""


def _scaled(p, v, scale):
    return v * scale if p.kind in (spec.DIST, spec.VEC) else v


# ── the parameters block ──────────────────────────────────────────────────────

def _param_lines(p, scale) -> list:
    ty = _MXS_TYPE[p.kind]

    if p.kind == spec.NODE:
        return [f"{p.name} type:{ty} ui:{control_name(p)}"]

    if p.kind == spec.TEXT:
        return [f"{p.name} type:{ty} ui:{control_name(p)} "
                f"default:{_str(p.default)}"]

    if p.kind == spec.VEC:
        out = []
        for axis, v in zip(_AXES, p.default):
            out.append(f"{p.name}_{axis} type:{ty} "
                       f"ui:{control_name(p, axis)} "
                       f"default:{_num(v * scale)} animatable:false")
        return out

    return [f"{p.name} type:{ty} ui:{control_name(p)} "
            f"default:{_num(_scaled(p, p.default, scale))} animatable:false"]


# ── the controls ──────────────────────────────────────────────────────────────

def _control_lines(p, scale) -> list:
    lo = _num(_scaled(p, p.lo, scale))
    hi = _num(_scaled(p, p.hi, scale))

    if p.kind == spec.ENUM:
        items = ", ".join(_str(s) for s in spec.ENUM_LABELS[p.name])
        return [f"dropdownlist {control_name(p)} {_str(p.label)} "
                f"items:#({items}) width:146 align:#left{_tip(p)}"]

    if p.kind == spec.BOOL:
        return [f"checkbox {control_name(p)} {_str(p.label)} "
                f"align:#left{_tip(p)}"]

    if p.kind == spec.NODE:
        return [f"pickbutton {control_name(p)} {_str(p.label)} width:146 "
                f"autoDisplay:true align:#left "
                f"message:{_str('Pick the ' + p.label.lower())}{_tip(p)}"]

    if p.kind == spec.TEXT:
        return [f"edittext {control_name(p)} \"\" width:146 "
                f"readOnly:true align:#left{_tip(p)}"]

    if p.kind == spec.VEC:
        out = [f"label lbl_{p.name} {_str(p.label + ':')} align:#left"]
        for axis in _AXES:
            out.append(f"spinner {control_name(p, axis)} "
                       f"{_str('  ' + axis.upper())} type:#worldunits "
                       f"range:[{lo},{hi},"
                       f"{_num(p.default[_AXES.index(axis)] * scale)}] "
                       f"fieldwidth:56 align:#right{_tip(p)}")
        return out

    return [f"spinner {control_name(p)} {_str(p.label)} "
            f"type:{_SPINNER_TYPE[p.kind]} "
            f"range:[{lo},{hi},{_num(_scaled(p, p.default, scale))}] "
            f"fieldwidth:56 align:#right{_tip(p)}"]


# ── which controls are live for which move ────────────────────────────────────

def _move_condition(name: str) -> str:
    """``true``, or the disjunction of the move indices that use this one."""
    if name in _ALWAYS_ON:
        return "true"
    live = [i + 1 for i, key in enumerate(spec.MOVE_KEYS)
            if name in spec.params_used_by(key)]
    if not live or len(live) == len(spec.MOVE_KEYS):
        return "true"
    return " or ".join(f"m == {i}" for i in live)


def _enable_condition(name: str) -> str:
    """
    Bare, with no outer bracket — :func:`_sync_lines` puts that on.

    It has to go on there and not here, because MAXScript binds an assignment
    tighter than ``and``: ``x.enabled = (a) and (b)`` sets ``x`` from ``a``
    alone and quietly throws ``b`` away, which shows up as a spinner that is
    live when it should be dead and nowhere else.
    """
    parts = [c for c in (_move_condition(name), _ALSO_NEEDS.get(name))
             if c and c != "true"]
    if not parts:
        return "true"
    if len(parts) == 1:
        return parts[0]
    return " and ".join(f"({c})" for c in parts)


def _sync_lines(groups) -> list:
    """
    The body of the rollout's ``syncUI``.

    Disabled rather than hidden, deliberately. Hiding a control leaves a hole in
    the layout unless every control below it is repositioned by hand, and the
    reposition is the part that breaks quietly when a parameter is added. A
    greyed spinner still says what the move does not use, which is information a
    missing spinner does not carry.
    """
    out = []
    for g in groups:
        for name in g.params:
            p = spec.PARAMS[name]
            cond = _enable_condition(name)
            if cond == "true":
                continue
            for axis in (_AXES if p.kind == spec.VEC else (None,)):
                out.append(f"{control_name(p, axis)}.enabled = ({cond})")
    return out


# ── the button handlers ───────────────────────────────────────────────────────

def _bridge_lines() -> list:
    """
    How a button reaches Python.

    Everything here is deliberately self-contained: no helper struct, no global
    function, nothing that has to have been defined earlier in the session. A
    camera carries this rollout inside the .max file, so it will be opened on
    machines and in sessions where the installer never ran, and the failure has
    to be a sentence telling the user what to run rather than a MAXScript
    exception in the listener.

    The node is passed by handle rather than marshalled, because a handle is an
    integer and integers survive every version of the Python bridge.
    """
    return _BRIDGE.strip("\n").split("\n")


_BRIDGE = r'''
fn ccOwnerNode = (
	local n = undefined
	local o = try(custAttributes.getOwner this)catch(undefined)
	if o != undefined do (
		local ns = try(refs.dependentNodes o)catch(#())
		if ns.count > 0 do n = ns[1]
	)
	if n == undefined and selection.count == 1 do (
		if (isProperty selection[1] #cc_move) do n = selection[1]
	)
	n
)

fn ccBootstrap = (
	if (globalVars.isGlobal #gCineCamHome) do (
		local home = gCineCamHome
		if home != undefined do (
			local slashed = substituteString (home as string) "\\" "/"
			try(python.Execute ("import sys\np = \"" + slashed +
				"\"\nif p not in sys.path: sys.path.insert(0, p)"))catch()
		)
	)
)

fn ccCall action = (
	local n = ccOwnerNode()
	if n == undefined then (
		messageBox "Cannot tell which camera this rollout belongs to. Select the camera and press again." title:"Cinematic move"
	) else (
		ccBootstrap()
		try (
			python.Execute ("import cinecam_max\ncinecam_max.ui_dispatch(\"" +
				action + "\", " + (n.handle as string) + ")")
		) catch (
			messageBox ("The cinecam bridge is not loaded in this session.\n\nRun install_cinecam.ms from the cinematic_cameras folder, then press again.\n\n" + (getCurrentException())) title:"Cinematic move"
		)
	)
)

on btn_cc_apply pressed do ccCall "apply"
on btn_cc_preview pressed do ccCall "preview"
on btn_cc_clear pressed do ccCall "clear"
on btn_cc_range pressed do ccCall "range_from_scene"
on btn_cc_place pressed do ccCall "place_from_camera"
'''


def _button_lines() -> list:
    return _BUTTONS.strip("\n").split("\n")


_BUTTONS = r'''
button btn_cc_apply "Build the move" width:146 height:26 align:#center tooltip:"Run the guards, then key the camera."
button btn_cc_preview "Check without keying" width:146 height:22 align:#center tooltip:"Run the guards and report. Touches nothing."
button btn_cc_clear "Clear keys in range" width:146 height:22 align:#center
button btn_cc_range "Frames = animation range" width:146 height:22 align:#center
button btn_cc_place "Read placement from viewport" width:146 height:22 align:#center tooltip:"Drag the camera where you want it, then press this to fill in bearing, standoff and height."
'''


# ── assembly ──────────────────────────────────────────────────────────────────

def _indent(lines, depth) -> list:
    pad = "\t" * depth
    return [(pad + ln if ln else "") for ln in lines]


def attribute_definition(scale: float = 1.0,
                         name: str = ATTRIBUTE_NAME) -> str:
    """
    The whole custom attribute, ready to hand to ``mxs.execute``.

    ``scale`` is how many system units make one metre. Get it from
    ``units.decodeValue "1m"`` and nowhere else.
    """
    out = [f"attributes {name}",
           f"version:{VERSION}",
           f"attribID:#({ATTRIBUTE_ID[0]}, {ATTRIBUTE_ID[1]})",
           "("]

    # Parameters first. One block per rollout, because `ui:` can only bind to
    # controls in the rollout the block names.
    for rollout_id, _, groups in _ROLLOUTS:
        block = [f"parameters params_{rollout_id} rollout:{rollout_id}", "("]
        body = []
        for g in groups:
            for pname in g.params:
                body += _param_lines(spec.PARAMS[pname], scale)
        block += _indent(body, 1)
        block += [")", ""]
        out += _indent(block, 1)

    # Then the rollouts themselves.
    for rollout_id, title, groups in _ROLLOUTS:
        block = [f"rollout {rollout_id} {_str(title)} width:162", "("]
        body = []
        for g in groups:
            controls = []
            for pname in g.params:
                controls += _control_lines(spec.PARAMS[pname], scale)
            body += [f"group {_str(g.title)}", "("]
            body += _indent(controls, 1)
            body += [")", ""]

        if rollout_id == "rlo_cc_apply":
            body += _button_lines() + [""] + _bridge_lines()
        else:
            sync = _sync_lines(groups)
            body += ["fn syncUI = (", "\tlocal m = cc_move",
                     "\tlocal sm = cc_subject_mode"]
            body += _indent(sync, 1)
            body += [")", ""]
            handlers = [f"on {rollout_id} open do syncUI()"]
            for trigger in ("cc_move", "cc_subject_mode", "cc_heading_mode"):
                if any(trigger in g.params for g in groups):
                    handlers.append(
                        f"on {control_name(spec.PARAMS[trigger])} selected i "
                        f"do syncUI()")
            for trigger in ("cc_handheld", "cc_clamp"):
                if any(trigger in g.params for g in groups):
                    handlers.append(
                        f"on {control_name(spec.PARAMS[trigger])} changed v "
                        f"do syncUI()")
            body += handlers

        block += _indent(body, 1)
        block += [")", ""]
        out += _indent(block, 1)

    out.append(")")
    return "\n".join(out) + "\n"
