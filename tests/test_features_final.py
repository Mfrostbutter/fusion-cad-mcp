"""Final feature additions: move_body, rib, add_hole kinds."""
import ast
import pytest

from fusion_cad_mcp.tools import features as f


def test_build_move_body_translation():
    src = f.build_move_body("plate", translation_mm=[20, 0, 0])
    ast.parse(src)
    assert "moveFeatures.createInput" in src
    assert "Vector3D.create(2.0, 0.0, 0.0)" in src  # 20mm -> 2cm


def test_build_move_body_rotation():
    src = f.build_move_body("plate", rotation_axis=[0, 0, 1], rotation_angle_deg=45)
    ast.parse(src)
    assert "setToRotation" in src
    # 45 deg = pi/4 ~ 0.7853
    assert "0.7853" in src


def test_build_move_body_requires_something():
    with pytest.raises(ValueError):
        f.build_move_body("plate")


def test_build_rib_parses():
    src = f.build_rib("rib_sk", "2 mm", side="symmetric")
    ast.parse(src)
    assert "Symmetric" in src
    assert "createByString(\"2 mm\")" in src


def test_build_rib_rejects_unknown_side():
    with pytest.raises(ValueError):
        f.build_rib("rib_sk", "2 mm", side="middle")


def test_rib_returns_not_scriptable_without_calling_fusion():
    # RibFeatures is a read-only collection in the current Fusion API (no
    # createInput/add), so the tool must short-circuit with a structured error
    # and never send a script to the adapter.
    class _BoomAdapter:
        def execute_script(self, script):
            raise AssertionError("rib must not call Fusion")

    env = f.rib(_BoomAdapter(), "rib_sk", "2 mm")
    assert env.ok is False
    assert env.error == "rib_not_scriptable"
    assert "thin" in env.message.lower() or "extrude" in env.message.lower()


def test_add_hole_simple_alias_still_works():
    src = f.build_add_hole_simple("plate", [0, 0, 5], "5 mm")
    ast.parse(src)
    assert "createSimpleInput" in src


def test_add_hole_counterbore():
    src = f.build_add_hole(
        "plate", [0, 0, 5], "5 mm", kind="counterbore",
        cbore_diameter="10 mm", cbore_depth="3 mm",
    )
    ast.parse(src)
    assert "createCounterboreInput" in src
    assert "createByString(\"10 mm\")" in src
    assert "createByString(\"3 mm\")" in src


def test_add_hole_countersink():
    src = f.build_add_hole(
        "plate", [0, 0, 5], "5 mm", kind="countersink",
        csink_diameter="10 mm", csink_angle="90 deg",
    )
    ast.parse(src)
    assert "createCountersinkInput" in src
    assert "createByString(\"90 deg\")" in src


def test_add_hole_counterbore_requires_args():
    with pytest.raises(ValueError):
        f.build_add_hole("plate", [0, 0, 5], "5 mm", kind="counterbore")


def test_add_hole_unknown_kind():
    with pytest.raises(ValueError):
        f.build_add_hole("plate", [0, 0, 5], "5 mm", kind="oversized")
