"""Tier 1a/1c tests for Group 4 construction geometry."""

from __future__ import annotations

import ast

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import construction as c


def test_plane_offset_emits_setByOffset():
    src = c.build_create_construction_plane("offset", name="lift_plane", base_plane="xy", offset="thickness")
    ast.parse(src)
    assert "setByOffset" in src
    assert "root.xYConstructionPlane" in src
    assert "createByString(\"thickness\")" in src


def test_plane_offset_requires_args():
    with pytest.raises(ValueError):
        c.build_create_construction_plane("offset", base_plane="xy")  # no offset


def test_plane_midplane_resolves_named_plane():
    src = c.build_create_construction_plane("midplane", plane_a="xy", plane_b="lift_plane")
    assert "setByTwoPlanes" in src
    assert "root.xYConstructionPlane" in src
    assert "\"lift_plane\"" in src  # named plane lookup


def test_plane_at_angle_uses_axis_and_base():
    src = c.build_create_construction_plane("at_angle", axis="x", base_plane="xy", angle="30 deg")
    assert "setByAngle" in src
    assert "root.xConstructionAxis" in src
    assert "createByString(\"30 deg\")" in src


def test_plane_3_points_creates_helper_sketch():
    src = c.build_create_construction_plane("3_points", p1=[0,0,0], p2=[10,0,0], p3=[0,10,5])
    ast.parse(src)
    assert "_cplane_helper_3pt" in src
    assert "setByThreePoints" in src
    # 10mm -> 1.0cm, 5mm -> 0.5cm
    assert "P(1.0, 0.0, 0.0)" in src
    assert "P(0.0, 1.0, 0.5)" in src


def test_plane_3_points_requires_three_points():
    with pytest.raises(ValueError):
        c.build_create_construction_plane("3_points", p1=[0,0,0], p2=[10,0,0])


def test_plane_unknown_kind_rejected():
    with pytest.raises(ValueError):
        c.build_create_construction_plane("tangent")


def test_axis_2_points_creates_helper_sketch():
    src = c.build_create_construction_axis("2_points", p1=[0,0,0], p2=[0,0,50])
    ast.parse(src)
    assert "_caxis_helper_2pt" in src
    assert "setByTwoPoints" in src
    assert "P(0.0, 0.0, 5.0)" in src  # 50mm -> 5cm


def test_axis_normal_to_face_uses_normal_match():
    src = c.build_create_construction_axis(
        "normal_to_face_by_geometry", body="plate", face_normal=[0.0, 0.0, 1.0])
    ast.parse(src)
    assert "setByNormalToFaceAtPoint" in src
    assert "getNormalAtPoint" in src
    assert "abs(n.z - 1.0)" in src


def test_axis_normal_to_face_requires_body_and_normal():
    with pytest.raises(ValueError):
        c.build_create_construction_axis("normal_to_face_by_geometry", body="plate")
    with pytest.raises(ValueError):
        c.build_create_construction_axis("normal_to_face_by_geometry", face_normal=[0,0,1])


def test_point_coords_creates_helper_sketch():
    src = c.build_create_construction_point([20, 30, 40], name="midpoint")
    ast.parse(src)
    assert "_cpoint_helper" in src
    assert "P(2.0, 3.0, 4.0)" in src


def test_point_rejects_bad_coords():
    with pytest.raises(ValueError):
        c.build_create_construction_point([20, 30])


def test_delete_walks_all_construction_collections():
    src = c.build_delete_construction("lift_plane")
    assert "constructionPlanes" in src
    assert "constructionAxes" in src
    assert "constructionPoints" in src
    assert "\"lift_plane\"" in src


# ---------- run wrappers ----------

class FakeAdapter:
    def __init__(self, message: str = '{"ok": true}'):
        self.scripts: list[str] = []
        self.message = message
    def execute_script(self, s: str) -> Envelope:
        self.scripts.append(s)
        return Envelope(ok=True, message=self.message)


def test_create_construction_plane_short_circuits_on_invalid_input():
    a = FakeAdapter()
    env = c.create_construction_plane(a, "wat")
    assert env.ok is False
    assert env.error == "invalid_input"


def test_delete_construction_requires_name():
    a = FakeAdapter()
    env = c.delete_construction(a, "")
    assert env.ok is False
