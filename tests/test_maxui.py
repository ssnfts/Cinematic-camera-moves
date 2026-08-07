"""
Tests for maxui.py — the MAXScript that 3ds Max is going to evaluate.

There is no MAXScript interpreter here, so this checks the two classes of fault
that do not need one. The first is structural: unbalanced brackets and stray
quotes, which in MAXScript surface as a rollout that simply never appears, with
an error buried in the listener. The second is completeness: a parameter with no
control, a control bound to no parameter, or a move that fails to switch on the
spinners its own function takes — all of which load fine and then do nothing.

What this cannot check is whether 3ds Max likes the property names. Nothing
offline can. That is the same standing caveat the README already carries about
every parameter name in this project, and it is why the generated text is worth
reading before it is trusted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import maxui  # noqa: E402
import movespec as spec  # noqa: E402

SRC = maxui.attribute_definition()

CONTROL_KINDS = ("spinner", "dropdownlist", "checkbox", "pickbutton",
                 "edittext", "label", "button")

_DECL = re.compile(r"^\s*(\w+)\s+type:#", re.M)
_CONTROL = re.compile(r"^\s*(?:%s)\s+(\w+)" % "|".join(CONTROL_KINDS), re.M)


def _strip_strings(text):
    """The source with every string literal blanked, for bracket counting."""
    out, in_str, escaped = [], False, False
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            out.append(" " if ch != '"' else ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


# ── it is a well-formed block ─────────────────────────────────────────────────

def test_it_is_an_attribute_definition():
    assert SRC.startswith(f"attributes {maxui.ATTRIBUTE_NAME}")
    assert f"version:{maxui.VERSION}" in SRC
    assert "attribID:#(" in SRC


def test_brackets_balance():
    """
    An unclosed parenthesis in MAXScript is not a loud failure. The rollout
    quietly never appears and the reason is one line in a listener nobody has
    open.
    """
    bare = _strip_strings(SRC)
    for opener, closer in (("(", ")"), ("[", "]")):
        assert bare.count(opener) == bare.count(closer), opener
    depth = 0
    for ch in bare:
        depth += (ch == "(") - (ch == ")")
        assert depth >= 0, "a closing bracket arrives before its opener"
    assert depth == 0


def test_quotes_balance_on_every_line():
    for i, line in enumerate(SRC.splitlines(), 1):
        unescaped = re.sub(r"\\.", "", line)
        assert unescaped.count('"') % 2 == 0, f"line {i}: {line}"


def test_there_are_no_stray_tabs_in_string_literals():
    """A tab inside a label is a label that renders with a gap in it."""
    for literal in re.findall(r'"(?:[^"\\]|\\.)*"', SRC):
        assert "\t" not in literal


# ── every parameter reaches a control, and back ───────────────────────────────

def _expected_params():
    out = []
    for p in spec.PARAMS.values():
        out += list(maxui.param_names(p))
    return out


def _expected_controls():
    out = []
    for p in spec.PARAMS.values():
        if p.kind == spec.VEC:
            out += [maxui.control_name(p, a) for a in ("x", "y", "z")]
        else:
            out.append(maxui.control_name(p))
    return out


def test_every_parameter_is_declared_exactly_once():
    found = _DECL.findall(SRC)
    assert sorted(found) == sorted(_expected_params())


def test_every_control_is_declared_exactly_once():
    found = [n for n in _CONTROL.findall(SRC) if not n.startswith("lbl_")]
    expected = _expected_controls() + [
        "btn_cc_apply", "btn_cc_preview", "btn_cc_clear",
        "btn_cc_range", "btn_cc_place"]
    assert sorted(found) == sorted(expected)


def test_every_parameter_is_bound_to_its_control():
    bound = set(re.findall(r"ui:(\w+)", SRC))
    assert bound == set(_expected_controls())


def test_every_parameter_block_names_a_rollout_that_exists():
    rollouts = set(re.findall(r"^\trollout (\w+)", SRC, re.M))
    named = set(re.findall(r"parameters \w+ rollout:(\w+)", SRC))
    assert named == rollouts
    assert len(rollouts) == 3


# ── the dropdowns say what the spec says ──────────────────────────────────────

@pytest.mark.parametrize("name", sorted(spec.ENUM_LABELS))
def test_every_dropdown_lists_its_labels_in_order(name):
    line = next(ln for ln in SRC.splitlines()
                if f"dropdownlist {maxui.control_name(spec.PARAMS[name])} "
                in ln)
    shown = re.search(r"items:#\((.*?)\)", line).group(1)
    quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', shown)
    assert tuple(quoted) == tuple(spec.ENUM_LABELS[name])


# ── the move dropdown switches the right controls ─────────────────────────────

def _sync_block():
    start = SRC.index("fn syncUI = (")
    return SRC[start:SRC.index("\n\t\t)", start)]


def test_every_switched_control_is_in_a_sync_block():
    body = SRC
    for name in spec.switched_params():
        p = spec.PARAMS[name]
        if maxui._enable_condition(name) == "true":
            continue
        for axis in (("x", "y", "z") if p.kind == spec.VEC else (None,)):
            assert f"{maxui.control_name(p, axis)}.enabled =" in body, name


def test_a_control_no_move_uses_is_never_switched_off():
    """
    The frame range applies to all nine, so no row of the dropdown may grey it.
    Greying a universal control is how a rollout ends up with a spinner that is
    dead for reasons no one can reconstruct.
    """
    for name in ("cc_start", "cc_end", "cc_move", "cc_min_sep"):
        p = spec.PARAMS[name]
        assert f"{maxui.control_name(p)}.enabled =" not in SRC, name


@pytest.mark.parametrize("key", spec.MOVE_KEYS)
def test_each_move_switches_on_exactly_what_it_takes(key):
    index = spec.MOVE_KEYS.index(key) + 1
    for name in spec.PARAMS:
        cond = maxui._move_condition(name)
        live = cond == "true" or f"m == {index}" in cond
        assert live == (name in spec.params_used_by(key)
                        or cond == "true"), f"{key} / {name}"


def test_the_dolly_zoom_hides_the_field_of_view_it_derives():
    """
    The end lens of a dolly zoom is computed from the invariant, never chosen.
    Leaving a live FOV spinner next to it invites someone to set it.
    """
    zoom = spec.MOVE_KEYS.index("dolly_zoom") + 1
    assert f"m == {zoom}" not in maxui._move_condition("cc_fov")
    assert maxui._move_condition("cc_from_fov") == f"m == {zoom}"


def test_a_two_part_condition_is_bracketed_against_maxscript_precedence():
    """
    MAXScript binds ``=`` tighter than ``and``, so an unbracketed
    ``x.enabled = (a) and (b)`` sets ``x`` from ``a`` and discards ``b``. The
    symptom is one spinner live when it should be dead — nothing that looks
    like a syntax problem, and nothing anyone would think to check.
    """
    assert "spn_cc_heading_deg.enabled = ((m == 7) and (cc_heading_mode == 3))" \
        in SRC
    for line in SRC.splitlines():
        if ".enabled =" in line:
            rhs = line.split(".enabled =", 1)[1].strip()
            assert rhs.startswith("(") and rhs.endswith(")"), line
            assert not rhs[1:-1].count(")") > rhs[1:-1].count("("), line


# ── the buttons are wired ─────────────────────────────────────────────────────

@pytest.mark.parametrize("button,action", [
    ("btn_cc_apply", "apply"),
    ("btn_cc_preview", "preview"),
    ("btn_cc_clear", "clear"),
    ("btn_cc_range", "range_from_scene"),
    ("btn_cc_place", "place_from_camera"),
])
def test_every_button_calls_the_bridge(button, action):
    assert f'on {button} pressed do ccCall "{action}"' in SRC


def test_the_bridge_can_find_its_camera_without_a_global():
    """
    A camera carries this rollout inside the .max file, so it will be opened in
    sessions where the installer never ran. The handlers have to stand alone.
    """
    assert "custAttributes.getOwner this" in SRC
    assert "refs.dependentNodes" in SRC
    assert "cinecam_max.ui_dispatch" in SRC


def test_a_missing_bridge_is_a_sentence_and_not_a_traceback():
    assert "install_cinecam.ms" in SRC
    assert "getCurrentException()" in SRC


# ── units cross the boundary exactly once ─────────────────────────────────────

def test_distances_scale_with_the_scene_unit_and_angles_do_not():
    """
    A ``#worldUnits`` default is in system units. A scene in centimetres has to
    get 3000 for a 30 m radius, or every default in the rollout is out by a
    hundred and reads as a camera parked on its subject.
    """
    metres = maxui.attribute_definition(scale=1.0)
    centis = maxui.attribute_definition(scale=100.0)

    radius = spec.PARAMS["cc_radius"]
    assert f"{maxui.control_name(radius)} \"Radius\" type:#worldunits " \
           "range:[0,100000,30]" in metres
    assert f"{maxui.control_name(radius)} \"Radius\" type:#worldunits " \
           "range:[0,10000000,3000]" in centis

    fov = spec.PARAMS["cc_fov"]
    for src in (metres, centis):
        assert f"{maxui.control_name(fov)} \"Field of view\" type:#float " \
               "range:[1,170,35]" in src


def test_no_number_reaches_maxscript_in_scientific_notation():
    """
    ``1e+07`` may or may not parse, depending on which MAXScript one asks. A
    spinner range does not need the notation enough to find out on someone
    else's machine.
    """
    for src in (maxui.attribute_definition(scale=1.0),
                maxui.attribute_definition(scale=1000.0)):
        # The attribute ID is hex, and hex is allowed to contain an "e".
        bare = re.sub(r"0x[0-9a-fA-F]+", "", _strip_strings(src))
        assert not re.search(r"\d[eE][+-]?\d", bare)


def test_vector_defaults_scale_too():
    scaled = maxui.attribute_definition(scale=100.0)
    assert "cc_station_x type:#worldUnits" in scaled
    assert "cc_station_z type:#worldUnits" in scaled


def test_the_generated_text_is_stable():
    """Two calls with the same scale must be byte-identical, or a re-install
    would look like a definition change to 3ds Max."""
    assert maxui.attribute_definition() == maxui.attribute_definition()
