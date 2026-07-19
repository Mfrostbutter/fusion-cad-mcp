"""Revolve / shell / add_hole_simple tests."""
import ast
import pytest

from fusion_cad_mcp.tools import features as f


# ---------- revolve ----------

def test_build_revolve_full_360():
    src = f.build_revolve("profile_sk", 0, axis="z", operation="new_body", extent_kind="full")
    ast.parse(src)
    assert "setAngleExtent(False" in src
    assert "createByString('360 deg')" in src
    assert "root.zConstructionAxis" in src


def test_build_revolve_angle_with_expression():
    src = f.build_revolve("profile_sk", 0, axis="x", extent_kind="angle", angle="90 deg")
    assert "createByString(\"90 deg\")" in src


def test_build_revolve_rejects_angle_without_expression():
    with pytest.raises(ValueError):
        f.build_revolve("sk", 0, extent_kind="angle")


def test_build_revolve_with_participants():
    src = f.build_revolve("sk", 0, axis="z", operation="cut", extent_kind="full", participants=["plate"])
    assert "participantBodies" in src
    assert "_find_body" in src


# ---------- shell ----------

def test_build_shell_with_face_normal():
    src = f.build_shell("plate", "wall_thk", face_normals_to_remove=[[0, 0, 1]], direction="inside")
    ast.parse(src)
    # adsk.fusion.ThicknessDirections does not exist; direction is expressed by
    # which of insideThickness / outsideThickness gets set.
    assert "ThicknessDirections" not in src
    assert "shell_in.insideThickness" in src
    assert "shell_in.outsideThickness" not in src
    assert "target_normals = [(0, 0, 1)]" in src
    assert "abs(n.x - tn[0])" in src
    assert "createByString(\"wall_thk\")" in src


def test_build_shell_outside_direction_sets_outside_thickness():
    src = f.build_shell("plate", "2 mm", direction="outside")
    ast.parse(src)
    assert "shell_in.outsideThickness" in src
    assert "shell_in.insideThickness" not in src


def test_build_shell_closed_adds_body_to_input_entities():
    # An empty ObjectCollection is rejected by ShellFeatures.add; the closed
    # (hollow) shell must pass the body itself.
    src = f.build_shell("plate", "2 mm")
    assert "target_faces.add(body)" in src


def test_build_shell_no_faces_emits_closed_shell_comment():
    src = f.build_shell("plate", "2 mm")
    assert "no faces removed" in src


def test_build_shell_rejects_unknown_direction():
    with pytest.raises(ValueError):
        f.build_shell("plate", "2 mm", direction="diagonal")


# ---------- add_hole_simple ----------

def test_build_add_hole_simple_all_extent():
    src = f.build_add_hole_simple("plate", [10, 5, 0], "5 mm", extent_kind="all")
    ast.parse(src)
    assert "createSimpleInput" in src
    assert "setAllExtent" in src
    assert "NegativeExtentDirection" in src
    # 10mm -> 1.0cm target coords feed both face selection and the point
    assert "_tx = 1.0" in src
    assert "_ty = 0.5" in src
    assert "P(_tx, _ty, top_z)" in src
    # Face selection must prefer the +Z face containing the target x/y, not
    # blindly the tallest one (a hole aimed at a lower step used to start in
    # mid-air above it).
    assert "containing_face" in src
    assert "position_on_face" in src


def test_build_add_hole_simple_distance_extent():
    src = f.build_add_hole_simple("plate", [0, 0, 0], "M5", extent_kind="distance", depth_expression="thickness / 2")
    assert "setDistanceExtent" in src
    assert "createByString(\"thickness / 2\")" in src


def test_build_add_hole_simple_requires_depth_for_distance():
    with pytest.raises(ValueError):
        f.build_add_hole_simple("plate", [0, 0, 0], "5 mm", extent_kind="distance")


def test_build_add_hole_simple_rejects_bad_position():
    with pytest.raises(ValueError):
        f.build_add_hole_simple("plate", [10, 5], "5 mm")  # missing z
