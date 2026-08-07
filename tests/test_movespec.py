"""
Tests for movespec.py — the table the rollout and the bridge are both built on.

The failure this file exists to prevent is silent. A spinner wired to an
argument :mod:`cinecam` no longer takes does not raise; it just stops affecting
the shot, and the first anyone knows is a render that looks slightly wrong for
a reason nobody can name. So the table is checked against the real signatures,
by introspection, rather than by reading both and hoping.

The other half is the defaults. A rollout whose out-of-the-box values produce a
refused move teaches the operator to ignore the refusal, so every move is built
once from its own defaults and put through the same checker the Build button
runs.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import cinecam  # noqa: E402
import movespec as spec  # noqa: E402


# The three arguments that are never spinners: two are positional, and one is a
# callable the bridge builds from a picked node.
NOT_CONTROLS = {"start", "end", "subject", "heading"}


def _kwonly(func):
    return {n for n, p in inspect.signature(func).parameters.items()
            if p.kind is inspect.Parameter.KEYWORD_ONLY}


# ── the table matches cinecam ─────────────────────────────────────────────────

def test_every_move_names_a_real_cinecam_function():
    for key in spec.MOVE_KEYS:
        assert hasattr(cinecam, key), key
        assert callable(getattr(cinecam, key))


def test_move_arguments_match_the_real_signatures():
    """
    The whole point of the file. A spinner bound to an argument that no longer
    exists edits nothing and says nothing.
    """
    for key, move in spec.MOVES.items():
        expected = _kwonly(getattr(cinecam, key)) - NOT_CONTROLS
        assert set(move.args) == expected, key


def test_moves_and_keys_and_labels_line_up():
    """The dropdown stores a 1-based index, so order is load-bearing."""
    assert tuple(spec.MOVES) == spec.MOVE_KEYS
    assert len(spec.MOVE_LABELS) == len(spec.MOVE_KEYS)


def test_every_referenced_parameter_exists():
    for key, move in spec.MOVES.items():
        for name in move.uses():
            assert name in spec.PARAMS, f"{key} -> {name}"


def test_a_shared_argument_name_is_not_a_shared_control():
    """
    ``whip_pan`` and ``pedestal`` both take ``distance`` and mean different
    things by it — one throws the aim out, the other stands the camera back. A
    control that changes meaning with the dropdown is a control nobody trusts.
    """
    whip = spec.MOVES["whip_pan"].args["distance"]
    ped = spec.MOVES["pedestal"].args["distance"]
    assert whip != ped


# ── the table is internally consistent ────────────────────────────────────────

def test_every_parameter_is_laid_out_exactly_once():
    placed = [n for g in spec.ALL_GROUPS for n in g.params]
    assert sorted(placed) == sorted(spec.PARAMS)
    assert len(placed) == len(set(placed))


def test_every_laid_out_parameter_exists():
    for g in spec.ALL_GROUPS:
        for name in g.params:
            assert name in spec.PARAMS, f"{g.title} -> {name}"


def test_every_dropdown_has_matching_labels_and_values():
    assert set(spec.ENUM_LABELS) == set(spec.ENUM_VALUES)
    for name in spec.ENUM_LABELS:
        assert spec.PARAMS[name].kind == spec.ENUM
        assert len(spec.ENUM_LABELS[name]) == len(spec.ENUM_VALUES[name])
    for name, p in spec.PARAMS.items():
        if p.kind == spec.ENUM:
            assert name in spec.ENUM_LABELS, name


def test_every_dropdown_default_is_a_real_row():
    for name, values in spec.ENUM_VALUES.items():
        assert 1 <= spec.PARAMS[name].default <= len(values)


def test_easing_rows_are_all_easings_cinecam_knows():
    for kind in spec.EASING_KEYS:
        cinecam.ease(0.5, kind)


def test_numeric_defaults_sit_inside_their_own_range():
    for name, p in spec.PARAMS.items():
        if p.kind in (spec.DIST, spec.ANGLE, spec.FLOAT, spec.INT):
            assert p.lo <= p.default <= p.hi, name
        if p.kind == spec.VEC:
            assert all(p.lo <= v <= p.hi for v in p.default), name


def test_switched_parameters_are_the_ones_a_move_actually_uses():
    switched = set(spec.switched_params())
    for key in spec.MOVE_KEYS:
        assert spec.params_used_by(key) <= switched


def test_the_frame_range_and_subject_are_never_switched_off():
    """Every one of the nine needs these, so no dropdown row may grey them."""
    switched = set(spec.switched_params())
    for name in ("cc_start", "cc_end", "cc_subject_mode", "cc_subject_node"):
        assert name not in switched, name


# ── the defaults build a shot, not a refusal ──────────────────────────────────

def _defaults():
    out = {}
    for name, p in spec.PARAMS.items():
        if p.kind == spec.ENUM:
            out[name] = spec.ENUM_VALUES[name][p.default - 1]
        else:
            out[name] = p.default
    return out


@pytest.mark.parametrize("key", spec.MOVE_KEYS)
def test_the_shipped_defaults_survive_the_checker(key):
    """
    A rollout that refuses its own defaults teaches the operator to click
    through refusals, which is worse than having no guard at all.
    """
    v = _defaults()
    move = spec.MOVES[key]
    kwargs = {arg: v[pname] for arg, pname in move.args.items()}
    if key == "tracking":
        kwargs["heading"] = lambda _f: v["cc_heading_deg"]

    keys = getattr(cinecam, key)(
        v["cc_start"], v["cc_end"], lambda _f: v["cc_subject"], **kwargs)

    report = cinecam.check_moves(
        keys,
        min_separation=v["cc_min_sep"],
        max_jump_m=v["cc_max_jump"] or None,
        max_rel_speed_ms=v["cc_max_rel"] or None)
    assert report["keys"] >= 2


def test_the_shipped_handheld_and_clamp_defaults_are_usable():
    v = _defaults()
    base = cinecam.dolly(v["cc_start"], v["cc_end"], lambda _f: (0.0, 0.0, 0.0),
                         from_dist=v["cc_from_dist"], to_dist=v["cc_to_dist"],
                         bearing_deg=0.0, height=v["cc_height"])
    shaken = cinecam.handheld(base, amp_m=v["cc_handheld_amp"],
                              period_frames=v["cc_handheld_period"],
                              seed=v["cc_handheld_seed"])
    lifted = cinecam.clamp_above(shaken, lambda _x, _y: 0.0,
                                 clearance=v["cc_clearance"])
    assert cinecam.check_moves(lifted, min_separation=v["cc_min_sep"])
