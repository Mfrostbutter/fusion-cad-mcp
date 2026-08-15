"""Handle-consuming tool generators + run wrappers."""
import ast

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import handle_tools as ht

# ---------- list_body_entities ----------

def test_list_body_entities_all_kinds():
    src = ht.build_list_body_entities("plate")
    ast.parse(src)
    assert "body.faces" in src
    assert "body.edges" in src
    assert "body.vertices" in src
    assert "entityToken" in src


def test_list_body_entities_face_normal_filter():
    src = ht.build_list_body_entities("plate", kinds=["face"], face_normal_filter=[0, 0, 1])
    ast.parse(src)
    assert "abs(n.z - 1)" in src


def test_list_body_entities_edge_parallel_z_filter():
    src = ht.build_list_body_entities("plate", kinds=["edge"], edge_parallel_to="z")
    assert "abs(sp.x - ep_.x) < 1e-6 and abs(sp.y - ep_.y) < 1e-6 and abs(sp.z - ep_.z) > 1e-6" in src


def test_list_body_entities_min_edge_length_converts_mm_to_cm():
    src = ht.build_list_body_entities("plate", kinds=["edge"], min_edge_length_mm=3.0)
    # 3mm -> 0.3cm
    assert "< 0.3" in src


def test_list_body_entities_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ht.build_list_body_entities("plate", kinds=["surface"])


# ---------- measure ----------

def test_build_measure_distance():
    src = ht.build_measure("face:body/face[0]:tA", "face:body/face[1]:tB", kind="distance")
    ast.parse(src)
    assert "measureMinimumDistance" in src
    assert '"tA"' in src
    assert '"tB"' in src


def test_build_measure_angle():
    src = ht.build_measure("face:b/face[0]:t1", "face:b/face[1]:t2", kind="angle")
    assert "measureAngle" in src
    assert "value_degrees" in src


def test_build_measure_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ht.build_measure("face:b:t1", "face:b:t2", kind="bogus")


def test_measure_short_circuits_on_bad_handle():
    class A:
        scripts: list = []
        def execute_script(self, s):
            self.scripts.append(s)
            return Envelope(ok=True)
    a = A()
    env = ht.measure(a, "garbage", "face:b:t2")
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


# ---------- find_mesh_using_ray ----------

def test_build_find_mesh_using_ray_default_root():
    src = ht.build_find_mesh_using_ray(None, [0, 0, 50], [0, 0, -1])
    ast.parse(src)
    assert "findMeshUsingRay" in src
    assert "target = root" in src
    # mm -> cm: 50 -> 5.0; floats explicit
    assert "Point3D.create(float(0.0), float(0.0), float(5.0))" in src


def test_build_find_mesh_using_ray_with_component():
    src = ht.build_find_mesh_using_ray("subassy", [0, 0, 0], [1, 0, 0])
    assert '"subassy"' in src
    assert "component_not_found" in src


def test_find_mesh_using_ray_rejects_bad_origin():
    class A:
        scripts: list = []
        def execute_script(self, s):
            self.scripts.append(s)
            return Envelope(ok=True)
    a = A()
    env = ht.find_mesh_using_ray(a, [0, 0], [0, 0, -1])
    assert env.ok is False
    assert env.error == "invalid_input"


# ---------- ray_collision_with_mesh ----------

def test_build_ray_collision_with_mesh_uses_calculateCollisionsWithRay():
    src = ht.build_ray_collision_with_mesh("body:mesh:tok", [0, 0, 50], [0, 0, -1])
    ast.parse(src)
    assert "calculateCollisionsWithRay" in src


def test_ray_collision_rejects_bad_handle():
    class A:
        scripts: list = []
        def execute_script(self, s):
            self.scripts.append(s)
            return Envelope(ok=True)
    a = A()
    env = ht.ray_collision_with_mesh(a, "not-a-handle", [0,0,0], [0,0,-1])
    assert env.ok is False


# ---------- fillet_edges (UI sel) ----------

def test_build_fillet_edges_resolves_each_handle():
    src = ht.build_fillet_edges(
        ["edge:b/edge[0]:t0", "edge:b/edge[1]:t1", "edge:b/edge[2]:t2"],
        "5 mm",
    )
    ast.parse(src)
    assert '"t0"' in src and '"t1"' in src and '"t2"' in src
    assert "addConstantRadiusEdgeSet" in src


def test_fillet_edges_rejects_empty_list():
    class A:
        scripts: list = []
        def execute_script(self, s):
            self.scripts.append(s)
            return Envelope(ok=True)
    a = A()
    env = ht.fillet_edges(a, [], "5 mm")
    assert env.ok is False


# ---------- chamfer_edges ----------

def test_build_chamfer_edges_equal():
    src = ht.build_chamfer_edges(["edge:b/edge[0]:t"], "1 mm", kind="equal")
    ast.parse(src)
    # Current API: createInput2() takes no args; edge sets via chamferEdgeSets.
    assert "chamferEdgeSets.addEqualDistanceChamferEdgeSet" in src
    assert "createInput2()" in src


def test_chamfer_two_dist_requires_distance2():
    with pytest.raises(ValueError):
        ht.build_chamfer_edges(["edge:b/edge[0]:t"], "1 mm", kind="two_dist")


# ---------- project_to_sketch ----------

def test_build_project_to_sketch_resolves_entities():
    src = ht.build_project_to_sketch("outline", ["edge:b/edge[0]:t1", "edge:b/edge[1]:t2"])
    ast.parse(src)
    assert "sk.project(ent)" in src
    assert '"t1"' in src
