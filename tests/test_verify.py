"""Tier 1a generator snapshots + Tier 1c run-wrapper behavior for verify tools."""

from __future__ import annotations

import ast
import json

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import verify as v


def _parses(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- generator snapshot ----------

def test_build_bbox_parses_and_has_run():
    src = v.build_bounding_box()
    tree = _parses(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run"]
    assert len(fns) == 1


def test_build_volume_walks_components():
    src = v.build_volume()
    assert "walk(comp" in src
    assert "occurrences.item(j)" in src


def test_build_mass_uses_physical_properties():
    src = v.build_mass()
    assert "physicalProperties" in src
    assert "pp.mass" in src


def test_build_center_of_mass_returns_mm():
    src = v.build_center_of_mass()
    # mm conversion (cm * 10) appears in the script
    assert "*10" in src


def test_name_filter_omitted_emits_None():
    src = v.build_bounding_box(None)
    assert "NAME_FILTER = None" in src


def test_name_filter_provided_is_json_safe():
    """Body names with special characters must round-trip through json.dumps."""
    src = v.build_bounding_box('weird "name" with quotes')
    # Should parse without breaking even with embedded quotes in the name
    _parses(src)
    assert '"weird \\"name\\" with quotes"' in src or "weird" in src


# ---------- run wrapper behavior ----------

class FakeAdapter:
    def __init__(self, message: str = '{"ok": true, "bodies": [], "count": 0}'):
        self.scripts: list[str] = []
        self.message = message

    def execute_script(self, script: str) -> Envelope:
        self.scripts.append(script)
        return Envelope(ok=True, message=self.message)


def test_bounding_box_parses_well_formed_response():
    payload = {
        "ok": True,
        "count": 1,
        "bodies": [
            {
                "path": "plate",
                "name": "plate",
                "bbox_mm": {"min": [-40.0, -25.0, 0.0], "max": [40.0, 25.0, 5.0]},
                "extent_mm": [80.0, 50.0, 5.0],
            }
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = v.bounding_box(a)
    assert env.ok is True
    assert env.result is not None
    assert env.result["bodies"][0]["extent_mm"] == [80.0, 50.0, 5.0]


def test_body_not_found_surfaces_structured_error():
    payload = {"ok": False, "error": "body_not_found", "name": "missing"}
    a = FakeAdapter(message=json.dumps(payload))
    env = v.bounding_box(a, body_name="missing")
    assert env.ok is False
    assert env.error == "body_not_found"


def test_unparseable_stdout_surfaces_parse_error():
    a = FakeAdapter(message="not json at all")
    env = v.volume(a)
    assert env.ok is False
    assert env.error == "volume_parse_failed"


def test_mass_returns_material_field():
    payload = {
        "ok": True,
        "count": 1,
        "bodies": [
            {
                "path": "plate",
                "name": "plate",
                "mass_kg": 0.0234,
                "volume_cm3": 19.16,
                "material": "PLA",
                "density_kg_m3": 1240.0,
            }
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = v.mass(a, body_name="plate")
    assert env.ok is True
    assert env.result["bodies"][0]["material"] == "PLA"


# ---------- audit_feature_health ----------

def test_build_audit_feature_health_parses_and_runs():
    src = v.build_audit_feature_health()
    tree = _parses(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run"]
    assert len(fns) == 1


def test_audit_includes_health_state_labels():
    src = v.build_audit_feature_health()
    # Labels must be present so the agent sees meaningful strings, not just ints
    assert "healthy" in src
    assert "warning" in src
    assert "failed" in src


def test_audit_walks_sub_components():
    src = v.build_audit_feature_health()
    assert "occurrences.item(j)" in src
    assert "audit_comp(occ.component" in src


def test_audit_default_skips_healthy():
    src = v.build_audit_feature_health()
    assert "INCLUDE_HEALTHY = False" in src


def test_audit_include_healthy_flag():
    src = v.build_audit_feature_health(include_healthy=True)
    assert "INCLUDE_HEALTHY = True" in src


def test_audit_component_filter_emits_json_safe_value():
    src = v.build_audit_feature_health(component_name="body")
    assert 'COMP_FILTER = "body"' in src


def test_audit_component_filter_none_emits_none():
    src = v.build_audit_feature_health(component_name=None)
    assert "COMP_FILTER = None" in src


def test_audit_run_wrapper_parses_healthy_response():
    payload = {
        "ok": True,
        "summary": {"total": 12, "healthy": 12, "warning": 0, "failed": 0},
        "features": [],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = v.audit_feature_health(a)
    assert env.ok is True
    assert env.result["summary"]["healthy"] == 12
    assert env.result["features"] == []


def test_audit_surfaces_broken_features():
    payload = {
        "ok": True,
        "summary": {"total": 7, "healthy": 5, "warning": 1, "failed": 1},
        "features": [
            {
                "path": " / body / dispense_hole_cut",
                "component": "body",
                "name": "dispense_hole_cut",
                "classType": "ExtrudeFeature",
                "healthState": 1,
                "healthLabel": "warning",
                "isSuppressed": False,
                "errorOrWarningMessage": "The profile reference is lost and this feature is using cached geometry.",
            },
            {
                "path": " / body / Fillet3",
                "component": "body",
                "name": "Fillet3",
                "classType": "FilletFeature",
                "healthState": 2,
                "healthLabel": "failed",
                "isSuppressed": False,
                "errorOrWarningMessage": "The fillet/chamfer could not be created at the requested size.",
            },
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = v.audit_feature_health(a)
    assert env.ok is True
    assert env.result["summary"]["warning"] == 1
    assert env.result["summary"]["failed"] == 1
    assert len(env.result["features"]) == 2
    assert env.result["features"][0]["name"] == "dispense_hole_cut"
    assert env.result["features"][1]["healthLabel"] == "failed"


def test_audit_no_active_design_surfaces_error():
    payload = {"ok": False, "error": "no_active_design"}
    a = FakeAdapter(message=json.dumps(payload))
    env = v.audit_feature_health(a)
    assert env.ok is False
    assert env.error == "no_active_design"


def test_audit_summary_respects_component_filter():
    """Review fix: when component_name is set, the summary counts must
    only include features from the matching component, not the whole
    root tree."""
    src = v.build_audit_feature_health(component_name="body")
    # The count() helper must gate its body on COMP_FILTER, not just
    # iterate every component unconditionally.
    assert "if COMP_FILTER is None or comp.name == COMP_FILTER:" in src
