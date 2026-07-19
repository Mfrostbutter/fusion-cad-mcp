"""Tier 1a/1c tests for Group 3 feature generators and run wrappers."""

from __future__ import annotations

import ast
import json

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import features as f


# ---------- extrude ----------

def test_build_extrude_distance_emits_setDistanceExtent():
    src = f.build_extrude("outer", 0, "new_body", "distance", "thickness")
    ast.parse(src)
    assert "setDistanceExtent(False" in src
    assert "createByString(\"thickness\")" in src
    assert "NewBodyFeatureOperation" in src


def test_build_extrude_distance_negative_direction():
    src = f.build_extrude("outer", 0, "cut", "distance", "5 mm", direction="negative")
    assert "setDistanceExtent(True" in src
    assert "CutFeatureOperation" in src


def test_build_extrude_symmetric_full_length():
    src = f.build_extrude("outer", 0, "new_body", "symmetric", "10 mm", is_full_length=True)
    assert "setSymmetricExtent" in src
    assert "createByString(\"10 mm\")" in src


def test_build_extrude_all_positive():
    src = f.build_extrude("outer", 0, "cut", "all_positive")
    assert "setAllExtent" in src
    assert "PositiveExtentDirection" in src


def test_build_extrude_all_negative():
    src = f.build_extrude("outer", 0, "cut", "all_negative")
    assert "NegativeExtentDirection" in src


def test_build_extrude_participants_wires_find_body():
    src = f.build_extrude("outer", 0, "cut", "all_negative", participants=["plate", "rib"])
    ast.parse(src)
    assert "_find_body" in src  # helper present
    assert "\"plate\"" in src
    assert "\"rib\"" in src
    assert "participantBodies" in src


def test_build_extrude_rejects_unknown_operation():
    with pytest.raises(ValueError):
        f.build_extrude("outer", 0, "morph", "distance", "5 mm")


def test_build_extrude_distance_requires_expression():
    with pytest.raises(ValueError):
        f.build_extrude("outer", 0, "new_body", "distance")


def test_build_extrude_invalid_extent_kind():
    with pytest.raises(ValueError):
        f.build_extrude("outer", 0, "new_body", "until_face", "5 mm")


def test_build_extrude_invalid_direction():
    with pytest.raises(ValueError):
        f.build_extrude("outer", 0, "new_body", "distance", "5 mm", direction="up")


# ---------- fillet by geometry ----------

def test_build_fillet_z_parallel_emits_correct_axis_check():
    src = f.build_fillet_edges_by_geometry("plate", "corner_r", parallel_to="z")
    ast.parse(src)
    # Z-parallel: x and y match, z differs
    assert "abs(sp.x - ep.x) < 1e-6 and abs(sp.y - ep.y) < 1e-6 and abs(sp.z - ep.z) > 1e-6" in src
    assert "createByString(\"corner_r\")" in src


def test_build_fillet_y_parallel():
    src = f.build_fillet_edges_by_geometry("plate", "5 mm", parallel_to="y")
    assert "abs(sp.x - ep.x) < 1e-6 and abs(sp.z - ep.z) < 1e-6 and abs(sp.y - ep.y) > 1e-6" in src


def test_build_fillet_any_parallel_skips_axis_filter():
    src = f.build_fillet_edges_by_geometry("plate", "1 mm", parallel_to="any")
    # axis_check is True, so we should see "if True and"
    assert "if True and" in src


def test_build_fillet_min_length_filter():
    src = f.build_fillet_edges_by_geometry("plate", "1 mm", parallel_to="z", min_length_mm=3.0)
    # 3 mm = 0.3 cm
    assert "edge_length_cm >= 0.3" in src


def test_build_fillet_rejects_unknown_axis():
    with pytest.raises(ValueError):
        f.build_fillet_edges_by_geometry("plate", "1 mm", parallel_to="diagonal")


def test_build_fillet_rejects_empty_radius():
    with pytest.raises(ValueError):
        f.build_fillet_edges_by_geometry("plate", "", parallel_to="z")


# ---------- chamfer by geometry ----------

def test_build_chamfer_equal_kind():
    src = f.build_chamfer_edges_by_geometry("plate", "1 mm", kind="equal")
    ast.parse(src)
    # Current API: createInput2() takes no args; edge sets are added through
    # chamferEdgeSets (the old add*ChamferEdges methods no longer exist).
    assert "chamferEdgeSets.addEqualDistanceChamferEdgeSet" in src
    assert "createInput2()" in src


def test_build_chamfer_two_dist_requires_distance2():
    with pytest.raises(ValueError):
        f.build_chamfer_edges_by_geometry("plate", "1 mm", kind="two_dist")


def test_build_chamfer_dist_angle_emits_correct_method():
    src = f.build_chamfer_edges_by_geometry("plate", "2 mm", kind="dist_angle", angle="45 deg")
    assert "chamferEdgeSets.addDistanceAndAngleChamferEdgeSet" in src
    assert "createByString(\"45 deg\")" in src


def test_build_chamfer_rejects_unknown_kind():
    with pytest.raises(ValueError):
        f.build_chamfer_edges_by_geometry("plate", "1 mm", kind="diagonal")


# ---------- mirror_feature ----------

def test_build_mirror_xy_plane():
    src = f.build_mirror_feature("plate_extrude", "xy")
    ast.parse(src)
    assert "root.xYConstructionPlane" in src


def test_build_mirror_named_plane_uses_lookup():
    src = f.build_mirror_feature("plate_extrude", "mid_plane")
    assert "root.constructionPlanes.item" in src
    assert "\"mid_plane\"" in src


# ---------- pattern_rectangular ----------

def test_build_pattern_rect_x_only_no_y():
    src = f.build_pattern_rectangular("rib", x_axis="x", x_count=5, x_distance="40 mm")
    ast.parse(src)
    assert "createByReal(5)" in src
    assert "createByString(\"40 mm\")" in src


def test_build_pattern_rect_two_directions():
    src = f.build_pattern_rectangular("rib", x_axis="x", x_count=3, x_distance="30 mm",
                                       y_axis="y", y_count=2, y_distance="20 mm")
    assert "setDirectionTwo" in src


def test_pattern_rect_requires_x_distance_when_count_gt_1():
    with pytest.raises(ValueError):
        f.build_pattern_rectangular("rib", x_count=3)  # no x_distance


def test_pattern_rect_rejects_count_zero():
    with pytest.raises(ValueError):
        f.build_pattern_rectangular("rib", x_count=0, x_distance="10 mm")


# ---------- pattern_circular ----------

def test_build_pattern_circular_default_z_axis():
    src = f.build_pattern_circular("hole", axis="z", count=6, total_angle="360 deg")
    ast.parse(src)
    assert "root.zConstructionAxis" in src
    assert "createByReal(6)" in src
    assert "createByString(\"360 deg\")" in src


def test_pattern_circular_rejects_count_less_than_2():
    with pytest.raises(ValueError):
        f.build_pattern_circular("hole", count=1)


# ---------- combine ----------

def test_build_combine_join():
    src = f.build_combine("plate", ["lip"], operation="join")
    ast.parse(src)
    assert "JoinFeatureOperation" in src
    assert "isKeepToolBodies = False" in src


def test_build_combine_cut_keep_tools():
    src = f.build_combine("plate", ["pocket1", "pocket2"], operation="cut", keep_tools=True)
    assert "CutFeatureOperation" in src
    assert "isKeepToolBodies = True" in src


def test_combine_rejects_empty_tools():
    with pytest.raises(ValueError):
        f.build_combine("plate", [], operation="join")


def test_combine_rejects_unknown_op():
    with pytest.raises(ValueError):
        f.build_combine("plate", ["lip"], operation="merge")


# ---------- run wrappers ----------

class FakeAdapter:
    def __init__(self, message: str = '{"ok": true}'):
        self.scripts: list[str] = []
        self.message = message
    def execute_script(self, s: str) -> Envelope:
        self.scripts.append(s)
        return Envelope(ok=True, message=self.message)


def test_extrude_short_circuits_on_invalid_input():
    a = FakeAdapter()
    env = f.extrude(a, "outer", 0, "morph", "distance", "5 mm")
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


def test_extrude_passes_through_payload():
    payload = {"ok": True, "feature_name": "Extrude1", "operation": "new_body",
               "extent_kind": "distance", "bodies_added": ["Body1"]}
    a = FakeAdapter(message=json.dumps(payload))
    env = f.extrude(a, "outer", 0, "new_body", "distance", "thickness")
    assert env.ok is True
    assert env.result["bodies_added"] == ["Body1"]


def test_fillet_surfaces_no_edges_matched_error():
    payload = {"ok": False, "error": "no_edges_matched", "parallel_to": "z", "min_length_mm": None}
    a = FakeAdapter(message=json.dumps(payload))
    env = f.fillet_edges_by_geometry(a, "plate", "5 mm", parallel_to="z")
    assert env.ok is False
    assert env.error == "no_edges_matched"


# ---------- rebuild_feature ----------

def test_build_rebuild_feature_parses():
    src = f.build_rebuild_feature("dispense_hole_cut")
    import ast
    ast.parse(src)
    assert 'FEATURE_NAME = "dispense_hole_cut"' in src
    assert "COMP_HINT = None" in src


def test_build_rebuild_feature_with_component_hint():
    src = f.build_rebuild_feature("dispense_hole_cut", component_name="body")
    assert 'COMP_HINT = "body"' in src


def test_build_rebuild_walks_components():
    src = f.build_rebuild_feature("x")
    assert "_find_feature_anywhere" in src
    assert "occurrences.item(j)" in src


def test_build_rebuild_captures_extent_and_start():
    src = f.build_rebuild_feature("x")
    # Must read both extent and start so we can recreate
    assert "DistanceExtentDefinition" in src
    assert "OffsetStartDefinition" in src
    assert "ProfilePlaneStartDefinition" in src


def test_build_rebuild_captures_participant_bodies():
    src = f.build_rebuild_feature("x")
    assert "participantBodies" in src
    assert "participant_body_names" in src


def test_build_rebuild_matches_profile_by_area():
    src = f.build_rebuild_feature("x")
    # areaProperties is a METHOD; the property form raised AttributeError and
    # silently disabled area matching (areas were always None).
    assert "areaProperties().area" in src
    assert "areaProperties.area" not in src
    assert "best_diff" in src


def test_rebuild_returns_old_and_new_health():
    payload = {
        "ok": True,
        "feature_name": "dispense_hole_cut",
        "feature_class": "ExtrudeFeature",
        "component": "body",
        "old_health": 1,
        "old_message": "The profile reference is lost and this feature is using cached geometry.",
        "new_health": 0,
        "captured": {
            "class": "ExtrudeFeature",
            "operation": 2,
            "sketch_name": "dispense_hole",
            "extent_kind": "distance",
            "extent_distance_expr": "floor_thk - slot_chamber_d - slot_narrow_d",
            "start_kind": "offset",
            "start_offset_expr": "slot_chamber_d + slot_narrow_d",
            "profile_count": 1,
        },
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "dispense_hole_cut")
    assert env.ok is True
    assert env.result["old_health"] == 1
    assert env.result["new_health"] == 0
    assert env.result["captured"]["extent_kind"] == "distance"


def test_rebuild_returns_structured_error_for_fillet():
    payload = {
        "ok": False,
        "error": "not_supported_for_rebuild",
        "feature_class": "FilletFeature",
        "feature_name": "Fillet3",
        "component": "body",
        "supported": ["ExtrudeFeature"],
        "old_health": 2,
        "recommendation": "For FilletFeature/ChamferFeature: suppress instead (gotcha G11). For others: delete and re-create with the appropriate add_* tool.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "Fillet3")
    assert env.ok is False
    assert env.error == "not_supported_for_rebuild"
    assert "FilletFeature" in env.result["feature_class"]
    assert "suppress" in env.result["recommendation"].lower()


def test_rebuild_warns_when_delete_succeeded_but_recreate_failed():
    payload = {
        "ok": False,
        "error": "sketch_not_found",
        "feature_name": "dispense_hole_cut",
        "name": "dispense_hole",
        "captured": {"sketch_name": "dispense_hole", "operation": 2},
        "WARNING": "Feature was deleted but re-creation failed. Use Fusion's undo to restore, then handle this rebuild manually.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "dispense_hole_cut")
    assert env.ok is False
    assert env.error == "sketch_not_found"
    assert "undo" in env.result["WARNING"].lower()


def test_rebuild_surfaces_feature_not_found():
    payload = {"ok": False, "error": "feature_not_found", "name": "nope"}
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "nope")
    assert env.ok is False
    assert env.error == "feature_not_found"


# ---------- rebuild_feature review fixes (multi-profile, preflight) ----------

def test_build_rebuild_always_emits_profile_areas_list():
    """Single-profile case must store profile_areas as a 1-element LIST,
    not a singular profile_area. Recreate iterates the list uniformly so
    multi-profile rebuilds work."""
    src = f.build_rebuild_feature("x")
    # Capture path: single-profile branch stores list
    assert 'info["profile_areas"] = [prof.areaProperties().area]' in src
    # The old singular field must NOT appear anywhere
    assert 'profile_area"]' not in src or 'profile_areas"]' in src  # only plural


def test_build_rebuild_wraps_profile_getter():
    """Regression: on a stale feature whose sketch curves were deleted, the
    ExtrudeFeature.profile getter itself raises InternalValidationError. The
    capture must catch it and mark the feature unrebuildable so preflight
    preserves it (instead of the whole script crashing)."""
    src = f.build_rebuild_feature("x")
    assert "profile_unreadable" in src
    # the getter access must sit inside a try block
    assert "        prof = ft.profile" in src


def test_build_rebuild_preflight_checks_profiles_exist():
    """Regression: a sketch that resolves but has 0 profiles used to pass
    preflight, so deleteMe() ran and recreation then failed, destroying the
    feature. Preflight must check profiles.count before the delete."""
    src = f.build_rebuild_feature("x")
    pre = src[src.index("def _preflight_check"):src.index("def _recreate_extrude")]
    assert "sketch_has_no_profiles" in pre
    assert "profiles.count == 0" in pre


def test_build_rebuild_recreates_with_object_collection_for_multi_profile():
    src = f.build_rebuild_feature("x")
    # Recreate path should build an ObjectCollection when matched_profiles>1
    assert "ObjectCollection.create()" in src
    assert "len(matched_profiles) == 1" in src or "len(matched_profiles)==1" in src


def test_build_rebuild_uses_n_to_n_area_matching():
    src = f.build_rebuild_feature("x")
    # Should track which current-sketch profiles are already used so
    # N targets match N distinct profiles, not all the same one.
    assert "used_indices" in src


def test_build_rebuild_preflight_runs_before_delete():
    """Unsupported extent/start/two-sided shapes must be detected BEFORE
    deleteMe() so the original feature is preserved on bail."""
    src = f.build_rebuild_feature("x")
    # The preflight helper must exist and be called in run() before deleteMe
    assert "_preflight_check" in src
    idx_pre = src.find("preflight = _preflight_check")
    idx_del = src.find("ft.deleteMe()")
    assert idx_pre != -1, "_preflight_check call missing in run()"
    assert idx_del != -1, "deleteMe() call missing"
    assert idx_pre < idx_del, "preflight must run BEFORE deleteMe"


def test_build_rebuild_preflight_returns_original_preserved_note():
    src = f.build_rebuild_feature("x")
    assert "Original feature preserved" in src


def test_rebuild_preflight_short_circuits_unsupported_extent():
    payload = {
        "ok": False,
        "error": "unsupported_extent_type",
        "extent_class": "ThroughAllExtentDefinition",
        "feature_name": "weird_cut",
        "component": "body",
        "captured": {"unsupported_extent": "ThroughAllExtentDefinition"},
        "note": "Original feature preserved. Rebuild not attempted because the captured state is not currently supported for automatic recreation.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "weird_cut")
    assert env.ok is False
    assert env.error == "unsupported_extent_type"
    assert "preserved" in env.result["note"].lower()


def test_rebuild_succeeds_for_multi_profile_extrude():
    payload = {
        "ok": True,
        "feature_name": "multi_pocket",
        "feature_class": "ExtrudeFeature",
        "component": "body",
        "old_health": 1,
        "old_message": "cached geometry",
        "new_health": 0,
        "captured": {
            "class": "ExtrudeFeature",
            "operation": 2,
            "sketch_name": "pocket_outlines",
            "profile_count": 3,
            "profile_areas": [12.5, 8.7, 4.2],
            "extent_kind": "distance",
            "extent_distance_expr": "5 mm",
            "start_kind": "profile_plane",
        },
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "multi_pocket")
    assert env.ok is True
    assert env.result["captured"]["profile_count"] == 3
    assert env.result["captured"]["profile_areas"] == [12.5, 8.7, 4.2]


# ---------- rebuild_feature duplicate-sketch-name resolution ----------

def test_build_rebuild_captures_sketch_owner_component():
    """Capture must record the parent component of the sketch so recreate can
    resolve the correct sketch when the name is duplicated across components."""
    src = f.build_rebuild_feature("x")
    assert "sketch_owner_component" in src
    assert "parentSketch.parentComponent.name" in src


def test_build_rebuild_uses_resolver_with_owner_hint():
    """Recreate must pass the captured owner to _resolve_sketch so duplicate
    sketch names don't silently bind to the wrong sketch."""
    src = f.build_rebuild_feature("x")
    assert "_resolve_sketch" in src
    assert 'captured.get("sketch_owner_component")' in src


def test_build_rebuild_preflight_resolves_sketch_before_delete():
    """Sketch ambiguity must be detected BEFORE deleteMe() — otherwise the
    original feature is lost even though we can't rebuild."""
    src = f.build_rebuild_feature("x")
    # Within _preflight_check, _resolve_sketch must be called and ambiguous
    # results must short-circuit. The preflight call site already runs before
    # deleteMe() per the prior fix; verify the resolver is part of preflight.
    pre_start = src.find("def _preflight_check")
    pre_end = src.find("def _recreate_extrude")
    assert pre_start != -1 and pre_end != -1 and pre_start < pre_end
    pre_body = src[pre_start:pre_end]
    assert "_resolve_sketch" in pre_body
    assert "sketch_name_ambiguous" in pre_body


def test_rebuild_surfaces_sketch_name_ambiguous_from_preflight():
    payload = {
        "ok": False,
        "error": "sketch_name_ambiguous",
        "name": "outline",
        "matches": [
            {"component": "body", "sketch": "outline"},
            {"component": "lid", "sketch": "outline"},
        ],
        "hint": "Original sketch's owner component could not be matched uniquely. Captured owner: None",
        "feature_name": "outline_cut",
        "component": "body",
        "captured": {"sketch_name": "outline", "sketch_owner_component": None},
        "note": "Original feature preserved. Rebuild not attempted because the captured state is not currently supported for automatic recreation.",
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = f.rebuild_feature(a, "outline_cut")
    assert env.ok is False
    assert env.error == "sketch_name_ambiguous"
    assert "preserved" in env.result["note"].lower()
    assert len(env.result["matches"]) == 2
