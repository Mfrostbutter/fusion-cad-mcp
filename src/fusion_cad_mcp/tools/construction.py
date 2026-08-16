"""Group 4 / construction geometry (first slice).

create_construction_plane (offset / midplane / at_angle / 3_points)
create_construction_axis (2_points / normal_to_face_by_geometry)
create_construction_point (3_coords)
delete_construction (by name)

UCS family (create_ucs / list_ucs) deferred: the May 2026 UserCoordinateSystem
API surface has Preview-tagged objects per the corrected discovery doc; opt-in
preview support lands in a future slice.

Plane and axis lookups: when a tool input names an existing entity (plane,
axis, face), we resolve at runtime by walking the root component's collections.
'xy'/'xz'/'yz' and 'x'/'y'/'z' resolve to the principals.
"""

from __future__ import annotations

import json

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

PRINCIPAL_PLANES = {
    "xy": "root.xYConstructionPlane",
    "xz": "root.xZConstructionPlane",
    "yz": "root.yZConstructionPlane",
}

PRINCIPAL_AXES = {
    "x": "root.xConstructionAxis",
    "y": "root.yConstructionAxis",
    "z": "root.zConstructionAxis",
}


def _plane_expr(name: str) -> str:
    name_lc = name.lower()
    if name_lc in PRINCIPAL_PLANES:
        return PRINCIPAL_PLANES[name_lc]
    return (
        f"next((root.constructionPlanes.item(i) for i in range(root.constructionPlanes.count) "
        f"if root.constructionPlanes.item(i).name == {json.dumps(name)}), None)"
    )


def _axis_expr(name: str) -> str:
    name_lc = name.lower()
    if name_lc in PRINCIPAL_AXES:
        return PRINCIPAL_AXES[name_lc]
    return (
        f"next((root.constructionAxes.item(i) for i in range(root.constructionAxes.count) "
        f"if root.constructionAxes.item(i).name == {json.dumps(name)}), None)"
    )


def _ok_runner(adapter: FusionAdapter, script: str, label: str) -> Envelope:
    env = adapter.execute_script(script)
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error=f"{label}_parse_failed", message=env.message)
    if parsed.get("ok") is False:
        return Envelope(
            ok=False,
            error=parsed.get("error", f"{label}_failed"),
            message=env.message,
            result=parsed,
        )
    return Envelope(ok=True, message=env.message, result=parsed)


def _header() -> str:
    return "import adsk.core, adsk.fusion\nimport json\nP = adsk.core.Point3D.create\n"


# ---------- create_construction_plane ----------

PLANE_KINDS = {"offset", "midplane", "at_angle", "3_points"}


def build_create_construction_plane(
    kind: str,
    name: str | None = None,
    base_plane: str | None = None,
    offset: str | None = None,
    plane_a: str | None = None,
    plane_b: str | None = None,
    axis: str | None = None,
    angle: str | None = None,
    p1: list[float] | None = None,
    p2: list[float] | None = None,
    p3: list[float] | None = None,
) -> str:
    if kind not in PLANE_KINDS:
        raise ValueError(f"kind must be one of {sorted(PLANE_KINDS)}, got {kind!r}")

    name_block = f"    plane.name = {json.dumps(name)}\n" if name else ""

    if kind == "offset":
        if not base_plane or not offset:
            raise ValueError("kind=offset requires base_plane + offset")
        setup = (
            f"    base = {_plane_expr(base_plane)}\n"
            f"    if base is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'base_plane_not_found',"
            f" 'name': {json.dumps(base_plane)}}})); return\n"
            f"    inp = root.constructionPlanes.createInput()\n"
            f"    inp.setByOffset(base, adsk.core.ValueInput.createByString({json.dumps(offset)}))\n"
        )
    elif kind == "midplane":
        if not plane_a or not plane_b:
            raise ValueError("kind=midplane requires plane_a + plane_b")
        setup = (
            f"    a = {_plane_expr(plane_a)}\n"
            f"    b = {_plane_expr(plane_b)}\n"
            f"    if a is None:\n        print(json.dumps({{'ok': False, 'error': 'plane_a_not_found'}})); return\n"
            f"    if b is None:\n        print(json.dumps({{'ok': False, 'error': 'plane_b_not_found'}})); return\n"
            f"    inp = root.constructionPlanes.createInput()\n"
            f"    inp.setByTwoPlanes(a, b)\n"
        )
    elif kind == "at_angle":
        if not axis or not base_plane or not angle:
            raise ValueError("kind=at_angle requires axis + base_plane + angle")
        setup = (
            f"    ax = {_axis_expr(axis)}\n"
            f"    base = {_plane_expr(base_plane)}\n"
            f"    if ax is None:\n        print(json.dumps({{'ok': False, 'error': 'axis_not_found'}})); return\n"
            f"    if base is None:\n        print(json.dumps({{'ok': False, 'error': 'base_plane_not_found'}})); return\n"
            f"    inp = root.constructionPlanes.createInput()\n"
            f"    inp.setByAngle(ax, adsk.core.ValueInput.createByString({json.dumps(angle)}), base)\n"
        )
    else:  # 3_points
        if not (p1 and p2 and p3 and len(p1) == 3 and len(p2) == 3 and len(p3) == 3):
            raise ValueError("kind=3_points requires p1, p2, p3 each as [x, y, z] in mm")
        # Use sketch points wrapped in a BaseFeature? Actually setByThreePoints needs Point3D-backed entities.
        # A common approach: create a temporary sketch with 3 sketchPoints, then pass them.
        # Simpler: use occurrences.create...? No — the supported API takes SketchPoint or Vertex objects.
        # Make a hidden helper sketch.
        setup = (
            f"    helper = root.sketches.add(root.xYConstructionPlane)\n"
            f"    helper.name = '_cplane_helper_3pt'\n"
            f"    helper.isComputeDeferred = True\n"
            f"    sp1 = helper.sketchPoints.add(P({p1[0] / 10}, {p1[1] / 10}, {p1[2] / 10}))\n"
            f"    sp2 = helper.sketchPoints.add(P({p2[0] / 10}, {p2[1] / 10}, {p2[2] / 10}))\n"
            f"    sp3 = helper.sketchPoints.add(P({p3[0] / 10}, {p3[1] / 10}, {p3[2] / 10}))\n"
            f"    helper.isComputeDeferred = False\n"
            f"    inp = root.constructionPlanes.createInput()\n"
            f"    inp.setByThreePoints(sp1, sp2, sp3)\n"
        )

    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + setup
        + "    plane = root.constructionPlanes.add(inp)\n"
        + name_block
        + "    print(json.dumps({\n"
        + "        'ok': True,\n"
        + f"        'kind': {json.dumps(kind)},\n"
        + "        'name': plane.name,\n"
        + "    }))\n"
    )


def create_construction_plane(
    adapter: FusionAdapter, kind: str, name: str | None = None, **kw
) -> Envelope:
    try:
        script = build_create_construction_plane(kind, name=name, **kw)
    except (ValueError, TypeError) as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_construction_plane")


# ---------- create_construction_axis ----------

AXIS_KINDS = {"2_points", "normal_to_face_by_geometry"}


def build_create_construction_axis(
    kind: str,
    name: str | None = None,
    p1: list[float] | None = None,
    p2: list[float] | None = None,
    body: str | None = None,
    face_normal: list[float] | None = None,
    face_point: list[float] | None = None,
) -> str:
    if kind not in AXIS_KINDS:
        raise ValueError(f"kind must be one of {sorted(AXIS_KINDS)}, got {kind!r}")
    name_block = f"    ax.name = {json.dumps(name)}\n" if name else ""

    if kind == "2_points":
        if not (p1 and p2 and len(p1) == 3 and len(p2) == 3):
            raise ValueError("kind=2_points requires p1 + p2 each as [x, y, z] in mm")
        setup = (
            f"    helper = root.sketches.add(root.xYConstructionPlane)\n"
            f"    helper.name = '_caxis_helper_2pt'\n"
            f"    helper.isComputeDeferred = True\n"
            f"    sp1 = helper.sketchPoints.add(P({p1[0] / 10}, {p1[1] / 10}, {p1[2] / 10}))\n"
            f"    sp2 = helper.sketchPoints.add(P({p2[0] / 10}, {p2[1] / 10}, {p2[2] / 10}))\n"
            f"    helper.isComputeDeferred = False\n"
            f"    inp = root.constructionAxes.createInput()\n"
            f"    inp.setByTwoPoints(sp1, sp2)\n"
        )
    else:  # normal_to_face_by_geometry
        if not body or not face_normal or len(face_normal) != 3:
            raise ValueError(
                "kind=normal_to_face_by_geometry requires body + face_normal [nx,ny,nz]"
            )
        # Find face by matching normal direction; tolerance ~1e-3 on each component
        nx, ny, nz = face_normal
        face_finder = (
            f"    _find = lambda root, name: next("
            f"(root.bRepBodies.item(i) for i in range(root.bRepBodies.count) "
            f"if root.bRepBodies.item(i).name == name), None)\n"
            f"    body = _find(root, {json.dumps(body)})\n"
            f"    if body is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'body_not_found', 'name': {json.dumps(body)}}})); return\n"
            f"    target_face = None\n"
            f"    for i in range(body.faces.count):\n"
            f"        f = body.faces.item(i)\n"
            f"        ok, n = f.evaluator.getNormalAtPoint(f.pointOnFace)\n"
            f"        if ok and abs(n.x - {nx}) < 1e-3 and abs(n.y - {ny}) < 1e-3 and abs(n.z - {nz}) < 1e-3:\n"
            f"            target_face = f\n"
            f"            break\n"
            f"    if target_face is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'face_not_found_by_normal',"
            f" 'normal': [{nx}, {ny}, {nz}]}})); return\n"
            f"    inp = root.constructionAxes.createInput()\n"
            f"    inp.setByNormalToFaceAtPoint(target_face, target_face.pointOnFace)\n"
        )
        setup = face_finder

    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + setup
        + "    ax = root.constructionAxes.add(inp)\n"
        + name_block
        + "    print(json.dumps({'ok': True, 'kind': "
        + json.dumps(kind)
        + ", 'name': ax.name}))\n"
    )


def create_construction_axis(
    adapter: FusionAdapter, kind: str, name: str | None = None, **kw
) -> Envelope:
    try:
        script = build_create_construction_axis(kind, name=name, **kw)
    except (ValueError, TypeError) as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_construction_axis")


# ---------- create_construction_point ----------


def build_create_construction_point(coords: list[float], name: str | None = None) -> str:
    if not coords or len(coords) != 3:
        raise ValueError("coords must be [x, y, z] in mm")
    name_block = f"    pt.name = {json.dumps(name)}\n" if name else ""
    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + "    helper = root.sketches.add(root.xYConstructionPlane)\n"
        + "    helper.name = '_cpoint_helper'\n"
        + "    helper.isComputeDeferred = True\n"
        + f"    sp = helper.sketchPoints.add(P({coords[0] / 10}, {coords[1] / 10}, {coords[2] / 10}))\n"
        + "    helper.isComputeDeferred = False\n"
        + "    inp = root.constructionPoints.createInput()\n"
        + "    inp.setByPoint(sp)\n"
        + "    pt = root.constructionPoints.add(inp)\n"
        + name_block
        + "    print(json.dumps({'ok': True, 'name': pt.name, 'coords_mm': "
        + json.dumps(coords)
        + "}))\n"
    )


def create_construction_point(
    adapter: FusionAdapter, coords: list[float], name: str | None = None
) -> Envelope:
    try:
        script = build_create_construction_point(coords, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_construction_point")


# ---------- delete_construction ----------


def build_delete_construction(name: str) -> str:
    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + "    deleted = []\n"
        + "    for coll_name in ('constructionPlanes', 'constructionAxes', 'constructionPoints'):\n"
        + "        coll = getattr(root, coll_name)\n"
        + "        for i in range(coll.count - 1, -1, -1):\n"
        + "            item = coll.item(i)\n"
        + f"            if item.name == {json.dumps(name)}:\n"
        + "                deleted.append(coll_name + '/' + item.name)\n"
        + "                item.deleteMe()\n"
        + "    if not deleted:\n"
        + "        print(json.dumps({'ok': False, 'error': 'construction_not_found',"
        + f" 'name': {json.dumps(name)}}})); return\n"
        + "    print(json.dumps({'ok': True, 'deleted': deleted}))\n"
    )


def delete_construction(adapter: FusionAdapter, name: str) -> Envelope:
    if not name or not isinstance(name, str):
        return Envelope(ok=False, error="invalid_input", message="name must be a non-empty string")
    return _ok_runner(adapter, build_delete_construction(name), "delete_construction")


__all__ = [
    "build_create_construction_axis",
    "build_create_construction_plane",
    "build_create_construction_point",
    "build_delete_construction",
    "create_construction_axis",
    "create_construction_plane",
    "create_construction_point",
    "delete_construction",
]
