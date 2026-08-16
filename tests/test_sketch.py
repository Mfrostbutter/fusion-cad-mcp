"""Tier 1a generator snapshots + Tier 1c validation for Group 2 sketch tools."""

from __future__ import annotations

import ast
import json

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import sketch as sk

# ---------- entity ref resolver (pure unit) ----------


def test_resolve_origin():
    assert sk._resolve_ref("origin") == "sk.originPoint"


def test_resolve_line_index():
    assert sk._resolve_ref("line:3") == "sk.sketchCurves.sketchLines.item(3)"


def test_resolve_line_start_end():
    assert sk._resolve_ref("line:0:start") == "sk.sketchCurves.sketchLines.item(0).startSketchPoint"
    assert sk._resolve_ref("line:0:end") == "sk.sketchCurves.sketchLines.item(0).endSketchPoint"


def test_resolve_circle_center():
    assert (
        sk._resolve_ref("circle:2:center")
        == "sk.sketchCurves.sketchCircles.item(2).centerSketchPoint"
    )


def test_resolve_arc_subentities():
    base = "sk.sketchCurves.sketchArcs.item(1)"
    assert sk._resolve_ref("arc:1") == base
    assert sk._resolve_ref("arc:1:start") == base + ".startSketchPoint"
    assert sk._resolve_ref("arc:1:end") == base + ".endSketchPoint"
    assert sk._resolve_ref("arc:1:center") == base + ".centerSketchPoint"


def test_resolve_point_and_dim():
    assert sk._resolve_ref("point:5") == "sk.sketchPoints.item(5)"
    assert sk._resolve_ref("dim:0") == "sk.sketchDimensions.item(0)"


def test_resolve_rejects_bad_kind():
    with pytest.raises(ValueError):
        sk._resolve_ref("widget:0")


def test_resolve_rejects_missing_index():
    with pytest.raises(ValueError):
        sk._resolve_ref("line")


def test_resolve_rejects_bad_subentity():
    with pytest.raises(ValueError):
        sk._resolve_ref("line:0:middle")
    with pytest.raises(ValueError):
        sk._resolve_ref("point:0:start")  # no subentities allowed


def test_resolve_rejects_malformed_ref():
    with pytest.raises(ValueError):
        sk._resolve_ref("line:abc")  # non-int index
    with pytest.raises(ValueError):
        sk._resolve_ref("line@0")  # bad chars


# ---------- create_sketch generator ----------


def test_build_create_sketch_xy():
    src = sk.build_create_sketch("xy", "outer")
    ast.parse(src)
    assert "root.xYConstructionPlane" in src
    assert '"outer"' in src


def test_build_create_sketch_rejects_bad_plane():
    with pytest.raises(ValueError):
        sk.build_create_sketch("diagonal", "outer")


def test_build_create_sketch_checks_name_collision():
    src = sk.build_create_sketch("xy", "outer")
    assert "sketch_name_taken" in src


# ---------- add_line / add_rectangle / add_circle / add_polygon generators ----------


def test_build_add_line_converts_mm_to_cm():
    src = sk.build_add_line("outer", [80, 50], [120, 50])
    ast.parse(src)
    # 80 mm -> 8.0 cm
    assert "P(8.0, 5.0, 0)" in src
    assert "P(12.0, 5.0, 0)" in src


def test_build_add_rectangle_center_kind():
    src = sk.build_add_rectangle("outer", "center", [0, 0], [40, 25])
    ast.parse(src)
    assert "addCenterPointRectangle" in src


def test_build_add_rectangle_corner_kind():
    src = sk.build_add_rectangle("outer", "corner", [-40, -25], [40, 25])
    ast.parse(src)
    assert "addTwoPointRectangle" in src


def test_build_add_rectangle_3pt_requires_p3():
    with pytest.raises(ValueError):
        sk.build_add_rectangle("outer", "3pt", [0, 0], [40, 0])


def test_build_add_circle_center_radius():
    src = sk.build_add_circle("hole", "center_radius", center=[0, 0], radius_mm=6.0)
    ast.parse(src)
    assert "addByCenterRadius" in src
    assert "0.6" in src  # 6mm -> 0.6cm


def test_build_add_circle_3pt():
    src = sk.build_add_circle("hole", "3pt", p1=[0, 0], p2=[10, 0], p3=[5, 5])
    ast.parse(src)
    assert "addByThreePoints" in src


def test_build_add_circle_rejects_missing_args():
    with pytest.raises(ValueError):
        sk.build_add_circle("hole", "center_radius", center=[0, 0])  # no radius
    with pytest.raises(ValueError):
        sk.build_add_circle("hole", "3pt", p1=[0, 0], p2=[10, 0])  # no p3


def test_build_add_polygon_geometry():
    src = sk.build_add_polygon("hex", 6, [0, 0], [10, 0])
    ast.parse(src)
    assert "addScribedPolygon" in src
    assert "math.hypot" in src
    assert "math.atan2" in src


def test_build_add_polygon_rejects_few_sides():
    with pytest.raises(ValueError):
        sk.build_add_polygon("tri", 2, [0, 0], [10, 0])


# ---------- geometric constraint generator ----------


def test_build_horizontal_constraint():
    src = sk.build_add_geometric_constraint("outer", "horizontal", ["line:0"])
    ast.parse(src)
    assert "gc.addHorizontal(sk.sketchCurves.sketchLines.item(0))" in src


def test_build_parallel_resolves_both_lines():
    src = sk.build_add_geometric_constraint("outer", "parallel", ["line:0", "line:2"])
    ast.parse(src)
    assert "gc.addParallel(" in src
    assert "item(0)" in src
    assert "item(2)" in src


def test_build_coincident_with_origin():
    src = sk.build_add_geometric_constraint("outer", "coincident", ["line:0:start", "origin"])
    ast.parse(src)
    assert "startSketchPoint" in src
    assert "originPoint" in src


def test_constraint_rejects_wrong_arity():
    with pytest.raises(ValueError):
        sk.build_add_geometric_constraint("outer", "parallel", ["line:0"])  # needs 2


def test_constraint_rejects_unknown_kind():
    with pytest.raises(ValueError):
        sk.build_add_geometric_constraint("outer", "almostHorizontal", ["line:0"])


# ---------- dimension generator ----------


def test_build_distance_h_dim_with_param_expression():
    """Verifies G9-corrected behavior: parameter-name expression is passed verbatim."""
    src = sk.build_add_dimension("outer", "distance_h", ["line:0:start", "line:0:end"], "length")
    ast.parse(src)
    assert "addDistanceDimension(" in src
    assert "HorizontalDimensionOrientation" in src
    assert '"length"' in src


def test_build_diameter_dim():
    src = sk.build_add_dimension("hole", "diameter", ["circle:0"], "hole_d")
    ast.parse(src)
    assert "addDiameterDimension(" in src
    assert '"hole_d"' in src


def test_build_angle_dim_requires_two_lines():
    with pytest.raises(ValueError):
        sk.build_add_dimension("outer", "angle", ["line:0"], "30 deg")


def test_build_distance_rejects_empty_expression():
    with pytest.raises(ValueError):
        sk.build_add_dimension("outer", "distance_h", ["line:0:start", "line:0:end"], "")


def test_dim_text_pos_converts_mm_to_cm():
    src = sk.build_add_dimension(
        "outer", "distance_h", ["line:0:start", "line:0:end"], "100 mm", text_pos=[20, 30]
    )
    # 20mm -> 2.0cm, 30mm -> 3.0cm
    assert "P(2.0, 3.0, 0)" in src


# ---------- assert_profiles ----------


def test_build_assert_profiles_emits_actual_vs_expected():
    src = sk.build_assert_profiles("outer", 1)
    ast.parse(src)
    assert "actual = sk.profiles.count" in src
    assert "actual == 1" in src


# ---------- run wrappers with mock adapter ----------


class FakeAdapter:
    def __init__(self, message: str = '{"ok": true}'):
        self.scripts: list[str] = []
        self.message = message

    def execute_script(self, s: str) -> Envelope:
        self.scripts.append(s)
        return Envelope(ok=True, message=self.message)


def test_create_sketch_short_circuits_on_bad_plane():
    a = FakeAdapter()
    env = sk.create_sketch(a, "diagonal", "outer")
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


def test_add_rectangle_passes_payload_through_on_success():
    payload = {"ok": True, "kind": "center", "line_indices": [0, 1, 2, 3]}
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.add_rectangle(a, "outer", "center", [0, 0], [40, 25])
    assert env.ok is True
    assert env.result["line_indices"] == [0, 1, 2, 3]


def test_add_dimension_surfaces_invalid_input_without_calling_fusion():
    a = FakeAdapter()
    env = sk.add_dimension(a, "outer", "distance_h", ["line:0:start"], "100 mm")  # only 1 entity
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


def test_assert_profiles_flips_envelope_ok_false_on_mismatch():
    payload = {"ok": False, "actual": 2, "expected": 1, "isFullyConstrained": True}
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.assert_profiles(a, "outer", 1)
    assert env.ok is False
    assert env.error == "profile_count_mismatch"
    assert env.result["actual"] == 2


def test_assert_profiles_ok_when_match():
    payload = {"ok": True, "actual": 1, "expected": 1, "isFullyConstrained": True}
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.assert_profiles(a, "outer", 1)
    assert env.ok is True


# ---------- probe_sketch_dimensions ----------


def test_build_probe_sketch_dimensions_parses():
    src = sk.build_probe_sketch_dimensions("clip_profile")
    ast.parse(src)
    assert 'SKETCH_NAME = "clip_profile"' in src
    assert "COMP_HINT = None" in src


def test_build_probe_with_component_hint():
    src = sk.build_probe_sketch_dimensions("clip_profile", component_name="body")
    ast.parse(src)
    assert 'COMP_HINT = "body"' in src


def test_build_probe_walks_sub_components():
    src = sk.build_probe_sketch_dimensions("clip_profile")
    assert "_find_sketch_anywhere" in src
    assert "occurrences.item(j)" in src


def test_build_probe_emits_entity_descriptors():
    src = sk.build_probe_sketch_dimensions("x")
    # Should describe the entities each dim attaches to
    assert "startSketchPoint" in src
    assert "centerSketchPoint" in src
    assert "majorAxisRadius" in src


def test_probe_returns_dim_list():
    payload = {
        "ok": True,
        "sketch_name": "clip_profile",
        "component": "body",
        "plane": "YZ",
        "isFullyConstrained": True,
        "profile_count": 1,
        "dimension_count": 2,
        "dimensions": [
            {
                "dim_class": "SketchLinearDimension",
                "param_name": "d278",
                "expression": "80 mm",
                "value_mm": 80.0,
                "unit": "cm",
                "entity_one": {"type": "SketchPoint", "point_mm": [0.0, 0.0]},
                "entity_two": {"type": "SketchPoint", "point_mm": [-80.0, 17.0]},
            },
            {
                "dim_class": "SketchLinearDimension",
                "param_name": "d285",
                "expression": "52 mm",
                "value_mm": 52.0,
                "unit": "cm",
                "entity_one": {"type": "SketchPoint", "point_mm": [-80.0, 30.5]},
                "entity_two": {"type": "SketchPoint", "point_mm": [-28.0, 30.5]},
            },
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.probe_sketch_dimensions(a, "clip_profile")
    assert env.ok is True
    assert env.result["dimension_count"] == 2
    assert env.result["dimensions"][0]["param_name"] == "d278"


def test_probe_surfaces_sketch_not_found():
    payload = {"ok": False, "error": "sketch_not_found", "name": "nope"}
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.probe_sketch_dimensions(a, "nope")
    assert env.ok is False
    assert env.error == "sketch_not_found"


# ---------- edit_sketch_dimension ----------


def test_build_edit_sketch_dimension_parses():
    src = sk.build_edit_sketch_dimension("clip_profile", "d278", "80 mm")
    ast.parse(src)
    assert 'SKETCH_NAME = "clip_profile"' in src
    assert 'DIM_NAME = "d278"' in src
    assert 'NEW_EXPR = "80 mm"' in src
    assert "design.computeAll()" in src


def test_build_edit_walks_sub_components():
    src = sk.build_edit_sketch_dimension("clip_profile", "d278", "80 mm")
    assert "_find_sketch_anywhere" in src


def test_build_edit_with_component_hint():
    src = sk.build_edit_sketch_dimension("clip_profile", "d278", "80 mm", component_name="body")
    assert 'COMP_HINT = "body"' in src


def test_build_edit_accepts_param_expressions():
    # Test the actual generator output for an expression with param reference
    src = sk.build_edit_sketch_dimension("dispense_hole", "d193", "oval_x / 2")
    assert 'NEW_EXPR = "oval_x / 2"' in src


def test_edit_short_circuits_on_empty_expression():
    a = FakeAdapter()
    env = sk.edit_sketch_dimension(a, "outer", "d1", "")
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


def test_edit_returns_old_and_new_expression():
    payload = {
        "ok": True,
        "sketch": "clip_profile",
        "component": "body",
        "param_name": "d278",
        "old_expression": "65 mm",
        "new_expression": "80 mm",
        "new_value_mm": 80.0,
        "isFullyConstrained_after": True,
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.edit_sketch_dimension(a, "clip_profile", "d278", "80 mm")
    assert env.ok is True
    assert env.result["old_expression"] == "65 mm"
    assert env.result["new_expression"] == "80 mm"
    assert env.result["new_value_mm"] == 80.0


def test_edit_dim_not_found_returns_available_dims():
    payload = {
        "ok": False,
        "error": "dim_not_found",
        "name": "d999",
        "sketch": "clip_profile",
        "component": "body",
        "available_dims": [
            {"param_name": "d278", "expression": "80 mm"},
            {"param_name": "d285", "expression": "52 mm"},
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.edit_sketch_dimension(a, "clip_profile", "d999", "10 mm")
    assert env.ok is False
    assert env.error == "dim_not_found"
    assert len(env.result["available_dims"]) == 2


def test_edit_expression_rejected_surfaces_detail():
    payload = {
        "ok": False,
        "error": "expression_rejected",
        "name": "d278",
        "tried": "not a valid expression!!",
        "old_expression": "65 mm",
        "detail": "Parsing error in expression",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.edit_sketch_dimension(a, "clip_profile", "d278", "not a valid expression!!")
    assert env.ok is False
    assert env.error == "expression_rejected"
    assert "Parsing error" in env.result["detail"]


def test_edit_emits_value_deg_for_angle_dims_not_mm():
    """Review fix: angle dimensions (unit='rad' or 'deg') must NOT be
    labeled new_value_mm. Generator branches on the param's unit."""
    src = sk.build_edit_sketch_dimension("x", "d1", "45 deg")
    # Generator must branch on unit and emit new_value_deg for rad/deg
    assert '"rad"' in src
    assert '"deg"' in src
    assert "new_value_deg" in src
    # Length branch must still emit new_value_mm (regression guard)
    assert "new_value_mm" in src


def test_edit_emits_value_mm_for_angle_payload_returns_deg():
    """Wrapper passes through whatever the script emits; verify the
    angle payload shape round-trips cleanly."""
    payload = {
        "ok": True,
        "sketch": "tilted_arm",
        "component": "body",
        "param_name": "d7",
        "old_expression": "30 deg",
        "new_expression": "45 deg",
        "unit": "deg",
        "new_value_deg": 45.0,
        "isFullyConstrained_after": True,
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.edit_sketch_dimension(a, "tilted_arm", "d7", "45 deg")
    assert env.ok is True
    assert env.result["new_value_deg"] == 45.0
    assert "new_value_mm" not in env.result


# ---------- duplicate sketch-name resolution ----------


def test_build_probe_emits_ambiguity_resolver():
    """Generator must embed _resolve_sketch (replaces the old _find_sketch_anywhere
    single-result lookup) and surface sketch_name_ambiguous in the run flow."""
    src = sk.build_probe_sketch_dimensions("outline")
    assert "_resolve_sketch" in src
    assert "sketch_name_ambiguous" in src
    # Old single-find pattern must NOT be the resolution path anymore
    assert "_hinted_find" not in src


def test_build_edit_emits_ambiguity_resolver():
    src = sk.build_edit_sketch_dimension("outline", "d1", "10 mm")
    assert "_resolve_sketch" in src
    assert "sketch_name_ambiguous" in src
    assert "_hinted_find" not in src


def test_build_resolver_returns_matches_with_component_and_sketch():
    """Ambiguity matches must include component + sketch for one-call recovery."""
    src = sk.build_probe_sketch_dimensions("outline")
    assert '"component": c' in src
    assert '"sketch": s.name' in src


def test_probe_surfaces_sketch_name_ambiguous():
    payload = {
        "ok": False,
        "error": "sketch_name_ambiguous",
        "name": "outline",
        "matches": [
            {"component": "body", "sketch": "outline"},
            {"component": "lid", "sketch": "outline"},
        ],
        "hint": "Pass component_name to disambiguate.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.probe_sketch_dimensions(a, "outline")
    assert env.ok is False
    assert env.error == "sketch_name_ambiguous"
    assert len(env.result["matches"]) == 2
    assert {m["component"] for m in env.result["matches"]} == {"body", "lid"}


def test_edit_surfaces_sketch_name_ambiguous():
    payload = {
        "ok": False,
        "error": "sketch_name_ambiguous",
        "name": "outline",
        "matches": [
            {"component": "body", "sketch": "outline"},
            {"component": "lid", "sketch": "outline"},
        ],
        "hint": "Pass component_name to disambiguate.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = sk.edit_sketch_dimension(a, "outline", "d1", "10 mm")
    assert env.ok is False
    assert env.error == "sketch_name_ambiguous"
    assert "component_name" in env.result["hint"]
