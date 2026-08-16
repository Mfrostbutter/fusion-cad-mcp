"""Cross-cutting guard against JSON literals leaking into generated Python.

Every tool in this package is a code generator: build_*() emits a Python script
that Fusion executes. Interpolating a value with json.dumps() is correct for
strings, but json.dumps(None) produces the bare token `null`, which is not a
Python name. The generated script then dies with

    NameError: name 'null' is not defined

inside Fusion, at whatever line the token landed on.

ast.parse() does NOT catch this. `null`, `true`, and `false` are all
syntactically valid Python identifiers, so the script parses cleanly and only
fails at run time. That is why this bug class survived the existing
`ast.parse(src)` assertions in test_features.py. The check has to be name
resolution, not syntax.

The rule for generators: embed Python values with repr(), not json.dumps().
repr(None) -> None, repr(True) -> True, both valid Python. Reserve json.dumps()
for values that are always strings.

History: patched once in build_move_component (commit 0d5bc8c), then found
again in build_pattern_rectangular (where the default y_axis=None broke every
single-direction call) and build_fillet_edges_by_geometry. This test exists so
there is no third time.
"""

from __future__ import annotations

import ast

import pytest

from fusion_cad_mcp.tools import assembly as asm
from fusion_cad_mcp.tools import construction as cons
from fusion_cad_mcp.tools import doc_state as ds
from fusion_cad_mcp.tools import features as f
from fusion_cad_mcp.tools import handle_tools as ht
from fusion_cad_mcp.tools import io as io_tools
from fusion_cad_mcp.tools import parameters as params
from fusion_cad_mcp.tools import sketch as sk
from fusion_cad_mcp.tools import verify as vf
from fusion_cad_mcp.tools import visualize as viz

# JavaScript/JSON literals that are valid Python identifiers but never defined
# in a generated script. Any of these appearing as a Name node is a leak.
JS_LITERALS = {"null", "true", "false"}

HANDLE = "face:body_main/face[0]:AbC123+/="
EDGE_HANDLE = "edge:body_main/edge[0]:XyZ789+/="

# Each entry is (id, callable, args, kwargs).
#
# Calls deliberately favour MINIMAL arguments, leaving every optional parameter
# at its default. That is where this bug class lives: an optional param that
# defaults to None and gets interpolated unguarded.
GENERATOR_CALLS = [
    # ---- features ----
    ("extrude.min", f.build_extrude, ("outer",), {"expression": "10 mm"}),
    ("extrude.all_positive", f.build_extrude, ("outer",), {"extent_kind": "all_positive"}),
    (
        "extrude.symmetric",
        f.build_extrude,
        ("outer",),
        {"extent_kind": "symmetric", "expression": "4 mm"},
    ),
    (
        "extrude.participants",
        f.build_extrude,
        ("outer",),
        {"operation": "cut", "expression": "2 mm", "participants": ["body_main"]},
    ),
    ("fillet_by_geom.min", f.build_fillet_edges_by_geometry, ("body_main", "2 mm"), {}),
    (
        "fillet_by_geom.minlen",
        f.build_fillet_edges_by_geometry,
        ("body_main", "2 mm"),
        {"min_length_mm": 5.0},
    ),
    ("chamfer_by_geom.min", f.build_chamfer_edges_by_geometry, ("body_main", "1 mm"), {}),
    (
        "chamfer_by_geom.two_dist",
        f.build_chamfer_edges_by_geometry,
        ("body_main", "1 mm"),
        {"kind": "two_dist", "distance2": "2 mm"},
    ),
    (
        "chamfer_by_geom.dist_angle",
        f.build_chamfer_edges_by_geometry,
        ("body_main", "1 mm"),
        {"kind": "dist_angle", "angle": "45 deg"},
    ),
    ("mirror.min", f.build_mirror_feature, ("feat_a", "xy"), {}),
    # The regression case: default y_axis=None used to emit `null` on the happy path.
    (
        "pattern_rect.x_only",
        f.build_pattern_rectangular,
        ("rib",),
        {"x_axis": "x", "x_count": 3, "x_distance": "30 mm"},
    ),
    (
        "pattern_rect.two_dir",
        f.build_pattern_rectangular,
        ("rib",),
        {
            "x_axis": "x",
            "x_count": 3,
            "x_distance": "30 mm",
            "y_axis": "y",
            "y_count": 2,
            "y_distance": "20 mm",
        },
    ),
    ("pattern_circ.min", f.build_pattern_circular, ("rib",), {}),
    ("combine.min", f.build_combine, ("body_main", ["tool_a"]), {}),
    ("revolve.full", f.build_revolve, ("outer",), {}),
    ("revolve.angle", f.build_revolve, ("outer",), {"extent_kind": "angle", "angle": "90 deg"}),
    ("shell.closed", f.build_shell, ("body_main", "2 mm"), {}),
    ("shell.open", f.build_shell, ("body_main", "2 mm"), {"face_normals_to_remove": [[0, 0, 1]]}),
    ("hole.simple", f.build_add_hole, ("body_main", [10.0, 10.0, 0.0], "5 mm"), {}),
    (
        "hole.counterbore",
        f.build_add_hole,
        ("body_main", [10.0, 10.0, 0.0], "5 mm"),
        {"kind": "counterbore", "cbore_diameter": "9 mm", "cbore_depth": "3 mm"},
    ),
    (
        "hole.countersink",
        f.build_add_hole,
        ("body_main", [10.0, 10.0, 0.0], "5 mm"),
        {"kind": "countersink", "csink_diameter": "9 mm", "csink_angle": "90 deg"},
    ),
    (
        "hole.distance",
        f.build_add_hole,
        ("body_main", [10.0, 10.0, 0.0], "5 mm"),
        {"extent_kind": "distance", "depth_expression": "6 mm"},
    ),
    ("move_body.translate", f.build_move_body, ("body_main",), {"translation_mm": [1.0, 2.0, 3.0]}),
    (
        "move_body.rotate",
        f.build_move_body,
        ("body_main",),
        {"rotation_axis": [0, 0, 1], "rotation_angle_deg": 90.0},
    ),
    ("rib.min", f.build_rib, ("outer", "2 mm"), {}),
    ("rebuild_feature.min", f.build_rebuild_feature, ("feat_a",), {}),
    # ---- assembly ----
    ("bodies_to_components", asm.build_bodies_to_components, ({"body_main": "Comp1"},), {}),
    (
        "move_component.translate",
        asm.build_move_component,
        ("Comp1",),
        {"translation_mm": [1.0, 2.0, 3.0]},
    ),
    (
        "move_component.rotate",
        asm.build_move_component,
        ("Comp1",),
        {"rotation_axis": [0, 0, 1], "rotation_angle_deg": 45.0},
    ),
    ("ground_component", asm.build_ground_component, ("Comp1", True), {}),
    ("rigid_group.min", asm.build_create_rigid_group, (["Comp1", "Comp2"],), {}),
    ("contact_set", asm.build_create_contact_set, (["body_a", "body_b"],), {}),
    ("interference_check", asm.build_interference_check, (["body_a", "body_b"],), {}),
    ("joint_limits.min_only", asm.build_set_joint_limits, ("Rev1",), {"min_value": "0 deg"}),
    ("joint_limits.rest_only", asm.build_set_joint_limits, ("Rev1",), {"rest_value": "15 deg"}),
    ("drive_joint", asm.build_drive_joint, ("Rev1", "45 deg"), {}),
    ("create_joint.min", asm.build_create_joint, (HANDLE, HANDLE), {}),
    (
        "create_joint.revolute",
        asm.build_create_joint,
        (HANDLE, HANDLE),
        {"motion_type": "revolute", "axis": "z", "offset_mm": "9 mm", "angle_deg": "90 deg"},
    ),
    # ---- sketch ----
    ("create_sketch", sk.build_create_sketch, ("xy", "outer"), {}),
    ("add_line", sk.build_add_line, ("outer", [0, 0], [10, 0]), {}),
    ("add_rectangle.center", sk.build_add_rectangle, ("outer", "center", [0, 0], [10, 5]), {}),
    (
        "add_rectangle.3pt",
        sk.build_add_rectangle,
        ("outer", "3pt", [0, 0], [10, 0]),
        {"p3": [10, 5]},
    ),
    (
        "add_circle.cr",
        sk.build_add_circle,
        ("outer", "center_radius"),
        {"center": [0, 0], "radius_mm": 5},
    ),
    ("add_polygon", sk.build_add_polygon, ("outer", 6, [0, 0], [10, 0]), {}),
    ("add_ellipse", sk.build_add_ellipse, ("outer", [0, 0], [10, 0], [0, 5]), {}),
    (
        "add_arc.3pt",
        sk.build_add_arc,
        ("outer", "3pt"),
        {"p1": [0, 0], "p2": [5, 5], "p3": [10, 0]},
    ),
    ("add_spline", sk.build_add_spline, ("outer", [[0, 0], [5, 5], [10, 0]]), {}),
    ("geom_constraint", sk.build_add_geometric_constraint, ("outer", "horizontal", ["line:0"]), {}),
    (
        "dimension.min",
        sk.build_add_dimension,
        ("outer", "distance_h", ["line:0:start", "line:0:end"], "width"),
        {},
    ),
    ("assert_profiles", sk.build_assert_profiles, ("outer", 1), {}),
    ("probe_dims.min", sk.build_probe_sketch_dimensions, ("outer",), {}),
    ("edit_dim.min", sk.build_edit_sketch_dimension, ("outer", "d278", "25 mm"), {}),
    # ---- construction ----
    (
        "cplane.offset",
        cons.build_create_construction_plane,
        ("offset",),
        {"base_plane": "xy", "offset": "10 mm"},
    ),
    (
        "cplane.midplane",
        cons.build_create_construction_plane,
        ("midplane",),
        {"plane_a": "xy", "plane_b": "xz"},
    ),
    (
        "cplane.at_angle",
        cons.build_create_construction_plane,
        ("at_angle",),
        {"axis": "x", "base_plane": "xy", "angle": "30 deg"},
    ),
    (
        "cplane.3_points",
        cons.build_create_construction_plane,
        ("3_points",),
        {"p1": [0, 0, 0], "p2": [10, 0, 0], "p3": [0, 10, 0]},
    ),
    (
        "caxis.2_points",
        cons.build_create_construction_axis,
        ("2_points",),
        {"p1": [0, 0, 0], "p2": [0, 0, 10]},
    ),
    (
        "caxis.normal",
        cons.build_create_construction_axis,
        ("normal_to_face_by_geometry",),
        {"body": "body_main", "face_normal": [0, 0, 1]},
    ),
    ("cpoint", cons.build_create_construction_point, ([1.0, 2.0, 3.0],), {}),
    ("delete_construction", cons.build_delete_construction, ("Plane1",), {}),
    # ---- handle tools ----
    ("list_body_entities.min", ht.build_list_body_entities, ("body_main",), {}),
    (
        "list_body_entities.filtered",
        ht.build_list_body_entities,
        ("body_main",),
        {"kinds": ["edge"], "edge_parallel_to": "z", "min_edge_length_mm": 2.0},
    ),
    ("measure", ht.build_measure, (HANDLE, EDGE_HANDLE), {}),
    ("find_mesh_ray", ht.build_find_mesh_using_ray, (None, [0, 0, 0], [0, 0, 1]), {}),
    ("ray_collision", ht.build_ray_collision_with_mesh, (HANDLE, [0, 0, 0], [0, 0, 1]), {}),
    ("fillet_edges.min", ht.build_fillet_edges, ([EDGE_HANDLE], "2 mm"), {}),
    ("chamfer_edges.min", ht.build_chamfer_edges, ([EDGE_HANDLE], "1 mm"), {}),
    ("project_to_sketch", ht.build_project_to_sketch, ("outer", [HANDLE]), {}),
    # ---- io ----
    # NB: build_export takes (format, body, path) - `body` is the second
    # positional, which is NOT the public export() wrapper's argument order.
    ("export.stl", io_tools.build_export, ("stl", None, "C:/tmp/part.stl"), {}),
    ("export.stl.body", io_tools.build_export, ("stl", "body_main", "C:/tmp/part.stl"), {}),
    ("export.step", io_tools.build_export, ("step", None, "C:/tmp/part.step"), {}),
    ("import_geometry", io_tools.build_import_geometry, ("step", "C:/tmp/in.step"), {}),
    # ---- verify ----
    ("bounding_box.all", vf.build_bounding_box, (), {}),
    ("bounding_box.named", vf.build_bounding_box, ("body_main",), {}),
    ("volume.all", vf.build_volume, (), {}),
    ("mass.all", vf.build_mass, (), {}),
    ("center_of_mass.all", vf.build_center_of_mass, (), {}),
    ("audit_feature_health.min", vf.build_audit_feature_health, (), {}),
    # ---- visualize ----
    ("set_view.min", viz.build_set_view, ("iso-top-right",), {}),
    ("set_view.current", viz.build_set_view, ("current",), {"fit": False}),
    # ---- parameters / doc_state ----
    ("params.add", params.build_add, ([{"name": "width", "expression": "50 mm"}],), {}),
    ("params.update", params.build_update, ("width", "60 mm"), {}),
    ("params.list", params.build_list, (), {}),
    ("doc_state", ds.build, (), {}),
]


def _js_literal_names(src: str) -> list[tuple[str, int]]:
    """Return (name, lineno) for every bare JS literal used as a Python name."""
    tree = ast.parse(src)
    return [
        (node.id, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in JS_LITERALS
    ]


@pytest.mark.parametrize(
    "label,fn,args,kwargs",
    GENERATOR_CALLS,
    ids=[c[0] for c in GENERATOR_CALLS],
)
def test_generated_script_has_no_js_literals(label, fn, args, kwargs):
    """No generator may emit `null`/`true`/`false` as a Python name."""
    src = fn(*args, **kwargs)

    # Syntax first, so a genuine syntax error reports as itself.
    ast.parse(src)

    leaks = _js_literal_names(src)
    if leaks:
        detail = "\n".join(
            f"    line {lineno}: {src.splitlines()[lineno - 1].strip()}" for _, lineno in leaks
        )
        pytest.fail(
            f"{label}: generated script contains JSON literal(s) used as Python "
            f"names: {sorted({n for n, _ in leaks})}\n{detail}\n"
            f"Fix: interpolate this value with repr(), not json.dumps()."
        )


def test_pattern_rectangular_single_direction_is_valid_python():
    """Regression: default y_axis=None emitted `null` on the unconditional path.

    The guard must survive as valid Python and evaluate to False so that a
    single-direction pattern proceeds instead of raising NameError in Fusion.
    """
    src = f.build_pattern_rectangular("rib", x_axis="x", x_count=3, x_distance="30 mm")
    assert "null" not in [n for n, _ in _js_literal_names(src)]
    assert "if None is not None and y_axis is None:" in src


def test_fillet_by_geometry_no_match_branch_is_valid_python():
    """Regression: min_length_mm=None emitted `null` in the no_edges_matched branch."""
    src = f.build_fillet_edges_by_geometry("body_main", "2 mm")
    assert not _js_literal_names(src)
    assert '"min_length_mm": None' in src


# ---------- pattern direction two ----------
#
# Fusion does not treat an unset direction two as "a single row". Leaving it
# undefined makes every instance come back as 3 coincident bodies. Verified
# against a live Fusion build:
#
#   setDirectionTwo omitted -> qty=1 gives 3 bodies, qty=4 gives 12 bodies
#   setDirectionTwo(axis, 1, "0 mm") -> qty=4 gives 4 bodies   <- correct
#
# In both cases the X positions were correct, so the failure is invisible to a
# position check and only shows up in the body count. Assert on the generated
# call, since the count itself can only be observed inside Fusion.


def test_pattern_rectangular_always_sets_direction_two():
    """Single-direction patterns must still pin direction two to one instance."""
    src = f.build_pattern_rectangular("rib", x_axis="x", x_count=4, x_distance="60 mm")
    assert src.count("setDirectionTwo") == 2, (
        "expected both the y_axis branch and the single-direction fallback"
    )
    # The fallback must request exactly one instance at zero offset.
    assert "createByReal(1)" in src
    assert 'createByString("0 mm")' in src


def test_pattern_rectangular_direction_two_fallback_differs_from_primary():
    """The fallback axis must not collide with the primary axis."""
    on_x = f.build_pattern_rectangular("rib", x_axis="x", x_count=2, x_distance="10 mm")
    assert "root.yConstructionAxis," in on_x

    # With Y as the primary axis, the fallback has to move off Y.
    on_y = f.build_pattern_rectangular("rib", x_axis="y", x_count=2, x_distance="10 mm")
    assert "root.zConstructionAxis," in on_y


def test_pattern_rectangular_two_direction_still_uses_caller_values():
    """An explicit y_axis must not be overridden by the fallback."""
    src = f.build_pattern_rectangular(
        "rib",
        x_axis="x",
        x_count=3,
        x_distance="30 mm",
        y_axis="y",
        y_count=2,
        y_distance="20 mm",
    )
    assert "createByReal(2)" in src
    assert 'createByString("20 mm")' in src
