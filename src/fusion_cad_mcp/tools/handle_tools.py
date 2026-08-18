"""Tools that consume entity handles (V2 spec Section 5a).

measure(entity_a, entity_b, kind)            — distance / min_distance / angle
find_mesh_using_ray(component, origin, dir)  — NEW May 2026: Component.findMeshUsingRay
ray_collision_with_mesh(mesh_body, ...)      — NEW May 2026: MeshBody.calculateCollisionsWithRay
fillet_edges(edges[], radius)                — UI-selection-style; takes edge handles
chamfer_edges(edges[], distance, ...)        — UI-selection-style; takes edge handles
project_to_sketch(sketch, entities[])        — project handles onto a named sketch

These tools all use the handle resolver from handles.py. Component / sketch /
mesh_body args still take by-name strings (we already address those); only the
new entity references that didn't have name addressing use handles.
"""

from __future__ import annotations

import json
import textwrap

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json
from ..handles import emit_resolve, emit_resolve_many, parse_handle


def _indent4(s: str) -> str:
    """Indent each line by 4 spaces so multi-line emit_resolve* output slots cleanly
    inside a `def run(_ctx):` body without IndentationError on subsequent lines.
    """
    return textwrap.indent(
        s, "    "
    ).lstrip()  # lstrip the FIRST line; the f-string already supplies indent for it


MEASURE_KINDS = {"distance", "min_distance", "angle"}


def _header() -> str:
    return "import adsk.core, adsk.fusion\nimport json\n"


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


# ---------- measure ----------


def build_measure(entity_a: str, entity_b: str, kind: str = "distance") -> str:
    if kind not in MEASURE_KINDS:
        raise ValueError(f"kind must be one of {sorted(MEASURE_KINDS)}, got {kind!r}")
    resolve_a = _indent4(emit_resolve(entity_a, var="_a"))
    resolve_b = _indent4(emit_resolve(entity_b, var="_b"))

    if kind == "distance":
        measure_call = "result = app.measureManager.measureMinimumDistance(_a, _b)"
        report = (
            "{\n"
            "        'ok': True, 'kind': 'distance',\n"
            "        'value_cm': result.value, 'value_mm': result.value * 10.0,\n"
            "        'point_a_cm': [result.positionOne.x, result.positionOne.y, result.positionOne.z],\n"
            "        'point_b_cm': [result.positionTwo.x, result.positionTwo.y, result.positionTwo.z],\n"
            "    }"
        )
    elif kind == "min_distance":
        measure_call = "result = app.measureManager.measureMinimumDistance(_a, _b)"
        report = (
            "{\n"
            "        'ok': True, 'kind': 'min_distance',\n"
            "        'value_cm': result.value, 'value_mm': result.value * 10.0,\n"
            "    }"
        )
    else:  # angle
        measure_call = "result = app.measureManager.measureAngle(_a, _b)"
        report = (
            "{\n"
            "        'ok': True, 'kind': 'angle',\n"
            "        'value_radians': result.value, 'value_degrees': result.value * 180.0 / 3.141592653589793,\n"
            "    }"
        )

    return f"""\
{_header()}
def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return

    {resolve_a}
    {resolve_b}
    # Unwrap proxies: MeasureManager rejects BRepFaceProxy and friends.
    _a_native = _a.nativeObject if hasattr(_a, 'nativeObject') and _a.nativeObject else _a
    _b_native = _b.nativeObject if hasattr(_b, 'nativeObject') and _b.nativeObject else _b
    _a = _a_native
    _b = _b_native
    {measure_call}
    print(json.dumps({report}))
"""


def measure(
    adapter: FusionAdapter, entity_a: str, entity_b: str, kind: str = "distance"
) -> Envelope:
    try:
        parse_handle(entity_a)
        parse_handle(entity_b)
        script = build_measure(entity_a, entity_b, kind)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "measure")


# ---------- find_mesh_using_ray (NEW May 2026) ----------


def build_find_mesh_using_ray(
    component_name: str | None,
    origin_mm: list[float],
    direction: list[float],
) -> str:
    if len(origin_mm) != 3:
        raise ValueError("origin_mm must be [x, y, z] in mm")
    if len(direction) != 3:
        raise ValueError("direction must be [dx, dy, dz]")
    ox, oy, oz = (v / 10.0 for v in origin_mm)
    dx, dy, dz = direction

    if component_name:
        # Walk occurrences recursively to find a sub-component by name
        comp_resolver = (
            f"    def _find_comp(comp, name):\n"
            f"        if comp.name == name: return comp\n"
            f"        for i in range(comp.occurrences.count):\n"
            f"            occ = comp.occurrences.item(i)\n"
            f"            if occ.component is None: continue\n"
            f"            r = _find_comp(occ.component, name)\n"
            f"            if r: return r\n"
            f"        return None\n"
            f"    target = _find_comp(root, {json.dumps(component_name)})\n"
            f"    if target is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'component_not_found',"
            f" 'name': {json.dumps(component_name)}}})); return\n"
        )
    else:
        comp_resolver = "    target = root\n"

    return f"""\
{_header()}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent
{comp_resolver}
    origin = adsk.core.Point3D.create(float({ox}), float({oy}), float({oz}))
    direction_vec = adsk.core.Vector3D.create(float({dx}), float({dy}), float({dz}))

    meshes = target.findMeshUsingRay(origin, direction_vec)
    if meshes is None:
        print(json.dumps({{"ok": True, "meshes_found": 0, "names": []}}))
        return

    # Return may be ObjectCollection, list, or MeshBodyVector (SWIG sequence). All support len() + [i].
    try:
        n = len(meshes)
    except TypeError:
        n = meshes.count if not callable(getattr(meshes, 'count', None)) else 0
    names = []
    for i in range(n):
        item = meshes[i] if hasattr(meshes, '__getitem__') else meshes.item(i)
        names.append(item.name)
    print(json.dumps({{
        "ok": True,
        "meshes_found": n,
        "names": names,
    }}))
"""


def find_mesh_using_ray(
    adapter: FusionAdapter,
    origin_mm: list[float],
    direction: list[float],
    component_name: str | None = None,
) -> Envelope:
    try:
        script = build_find_mesh_using_ray(component_name, origin_mm, direction)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "find_mesh_using_ray")


# ---------- ray_collision_with_mesh (NEW May 2026) ----------


def build_ray_collision_with_mesh(
    mesh_handle: str,
    origin_mm: list[float],
    direction: list[float],
) -> str:
    if len(origin_mm) != 3:
        raise ValueError("origin_mm must be [x, y, z] in mm")
    if len(direction) != 3:
        raise ValueError("direction must be [dx, dy, dz]")
    ox, oy, oz = (v / 10.0 for v in origin_mm)
    dx, dy, dz = direction
    resolve = _indent4(emit_resolve(mesh_handle, var="_mesh"))

    return f"""\
{_header()}
def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return

    {resolve}
    origin = adsk.core.Point3D.create({ox}, {oy}, {oz})
    direction_vec = adsk.core.Vector3D.create({dx}, {dy}, {dz})

    points = _mesh.calculateCollisionsWithRay(origin, direction_vec)
    if points is None:
        print(json.dumps({{"ok": True, "collisions": 0, "points_mm": []}}))
        return

    pts_mm = []
    for i in range(points.count):
        p = points.item(i)
        pts_mm.append([p.x * 10.0, p.y * 10.0, p.z * 10.0])
    print(json.dumps({{
        "ok": True,
        "collisions": len(pts_mm),
        "points_mm": pts_mm,
    }}))
"""


def ray_collision_with_mesh(
    adapter: FusionAdapter,
    mesh_handle: str,
    origin_mm: list[float],
    direction: list[float],
) -> Envelope:
    try:
        parse_handle(mesh_handle)
        script = build_ray_collision_with_mesh(mesh_handle, origin_mm, direction)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "ray_collision_with_mesh")


# ---------- fillet_edges (UI selection style) ----------


def build_fillet_edges(
    edge_handles: list[str], radius: str, is_tangent_chain: bool = True, name: str | None = None
) -> str:
    if not edge_handles:
        raise ValueError("edge_handles must be non-empty")
    if not radius:
        raise ValueError("radius expression required")
    resolve = _indent4(emit_resolve_many(edge_handles, collection_var="_resolved_edges"))
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""
    is_tan = "True" if is_tangent_chain else "False"

    return f"""\
{_header()}
def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    {resolve}
    edges = adsk.core.ObjectCollection.create()
    for e in _resolved_edges:
        edges.add(e)

    fil_in = root.features.filletFeatures.createInput()
    fil_in.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByString({json.dumps(radius)}), {is_tan})
    feat = root.features.filletFeatures.add(fil_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "edges_filleted": edges.count,
        "radius": {json.dumps(radius)},
    }}))
"""


def fillet_edges(
    adapter: FusionAdapter,
    edge_handles: list[str],
    radius: str,
    is_tangent_chain: bool = True,
    name: str | None = None,
) -> Envelope:
    try:
        for h in edge_handles:
            parse_handle(h)
        script = build_fillet_edges(edge_handles, radius, is_tangent_chain, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "fillet_edges")


# ---------- chamfer_edges (UI selection style) ----------

CHAMFER_KINDS = {"equal", "two_dist", "dist_angle"}


def build_chamfer_edges(
    edge_handles: list[str],
    distance: str,
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    name: str | None = None,
) -> str:
    if not edge_handles:
        raise ValueError("edge_handles must be non-empty")
    if kind not in CHAMFER_KINDS:
        raise ValueError(f"kind must be one of {sorted(CHAMFER_KINDS)}, got {kind!r}")
    if kind == "two_dist" and not distance2:
        raise ValueError("kind=two_dist requires distance2")
    if kind == "dist_angle" and not angle:
        raise ValueError("kind=dist_angle requires angle")

    resolve = _indent4(emit_resolve_many(edge_handles, collection_var="_resolved_edges"))
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    # createInput2() takes no args. Edge sets are added via
    # chamferEdgeSets.add*ChamferEdgeSet; add*ChamferEdges no longer exists.
    if kind == "equal":
        chm_call = (
            f"chm_in.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, "
            f"adsk.core.ValueInput.createByString({json.dumps(distance)}), False)"
        )
    elif kind == "two_dist":
        chm_call = (
            f"chm_in.chamferEdgeSets.addTwoDistancesChamferEdgeSet(edges, "
            f"adsk.core.ValueInput.createByString({json.dumps(distance)}), "
            f"adsk.core.ValueInput.createByString({json.dumps(distance2)}), False, False)"
        )
    else:  # dist_angle
        chm_call = (
            f"chm_in.chamferEdgeSets.addDistanceAndAngleChamferEdgeSet(edges, "
            f"adsk.core.ValueInput.createByString({json.dumps(distance)}), "
            f"adsk.core.ValueInput.createByString({json.dumps(angle)}), False, False)"
        )

    return f"""\
{_header()}
def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    {resolve}
    edges = adsk.core.ObjectCollection.create()
    for e in _resolved_edges:
        edges.add(e)

    chm_in = root.features.chamferFeatures.createInput2()
    {chm_call}
    feat = root.features.chamferFeatures.add(chm_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "edges_chamfered": edges.count,
        "kind": {json.dumps(kind)},
    }}))
"""


def chamfer_edges(
    adapter: FusionAdapter,
    edge_handles: list[str],
    distance: str,
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        for h in edge_handles:
            parse_handle(h)
        script = build_chamfer_edges(edge_handles, distance, kind, distance2, angle, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "chamfer_edges")


# ---------- project_to_sketch ----------


def build_project_to_sketch(sketch_name: str, entity_handles: list[str]) -> str:
    if not entity_handles:
        raise ValueError("entity_handles must be non-empty")
    resolve = _indent4(emit_resolve_many(entity_handles, collection_var="_to_project"))
    return f"""\
{_header()}
def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    sk = None
    for i in range(root.sketches.count):
        s = root.sketches.item(i)
        if s.name == {json.dumps(sketch_name)}:
            sk = s; break
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": {json.dumps(sketch_name)}}})); return

    {resolve}
    projected_total = 0
    for ent in _to_project:
        result = sk.project(ent)
        if result is not None:
            projected_total += result.count

    print(json.dumps({{
        "ok": True,
        "sketch": {json.dumps(sketch_name)},
        "entities_projected": len(_to_project),
        "curves_added": projected_total,
    }}))
"""


def project_to_sketch(adapter: FusionAdapter, sketch: str, entity_handles: list[str]) -> Envelope:
    try:
        for h in entity_handles:
            parse_handle(h)
        script = build_project_to_sketch(sketch, entity_handles)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "project_to_sketch")


# ---------- list_body_entities (bridge from name-addressing to handle-addressing) ----------

ENTITY_KINDS = {"face", "edge", "vertex"}


def build_list_body_entities(
    body_name: str,
    kinds: list[str] | None = None,
    face_normal_filter: list[float] | None = None,
    edge_parallel_to: str | None = None,
    min_edge_length_mm: float | None = None,
) -> str:
    if kinds is None:
        kinds = ["face", "edge", "vertex"]
    for k in kinds:
        if k not in ENTITY_KINDS:
            raise ValueError(f"unknown entity kind {k!r}; must be one of {sorted(ENTITY_KINDS)}")
    do_faces = "face" in kinds
    do_edges = "edge" in kinds
    do_verts = "vertex" in kinds

    # Filters sit in a `for` inside an `if`, so statements indent 12 and their
    # `continue` indents 16.
    face_filter_block = ""
    if face_normal_filter is not None:
        if len(face_normal_filter) != 3:
            raise ValueError("face_normal_filter must be [nx, ny, nz]")
        nx, ny, nz = face_normal_filter
        face_filter_block = (
            f"            ok_n, n = f.evaluator.getNormalAtPoint(f.pointOnFace)\n"
            f"            if not ok_n or not (abs(n.x - {nx}) < 1e-3 and abs(n.y - {ny}) < 1e-3 and abs(n.z - {nz}) < 1e-3):\n"
            f"                continue\n"
        )

    edge_filter_block = ""
    if edge_parallel_to is not None:
        ep = edge_parallel_to.lower()
        if ep not in {"x", "y", "z"}:
            raise ValueError("edge_parallel_to must be x, y, or z")
        if ep == "x":
            cond = (
                "abs(sp.y - ep_.y) < 1e-6 and abs(sp.z - ep_.z) < 1e-6 and abs(sp.x - ep_.x) > 1e-6"
            )
        elif ep == "y":
            cond = (
                "abs(sp.x - ep_.x) < 1e-6 and abs(sp.z - ep_.z) < 1e-6 and abs(sp.y - ep_.y) > 1e-6"
            )
        else:
            cond = (
                "abs(sp.x - ep_.x) < 1e-6 and abs(sp.y - ep_.y) < 1e-6 and abs(sp.z - ep_.z) > 1e-6"
            )
        edge_filter_block = f"            if not ({cond}):\n                continue\n"

    if min_edge_length_mm is not None:
        if min_edge_length_mm < 0:
            raise ValueError("min_edge_length_mm must be >= 0")
        edge_filter_block += (
            f"            if (((sp.x - ep_.x)**2 + (sp.y - ep_.y)**2 + (sp.z - ep_.z)**2) ** 0.5) < {min_edge_length_mm / 10.0}:\n"
            f"                continue\n"
        )

    return f"""\
{_header()}

def _find_body(root, name):
    def walk(comp):
        for i in range(comp.bRepBodies.count):
            b = comp.bRepBodies.item(i)
            if b.name == name: return b
        for j in range(comp.occurrences.count):
            occ = comp.occurrences.item(j)
            if occ.component is not None:
                r = walk(occ.component)
                if r: return r
        return None
    return walk(root)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body_name)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body_name)}}})); return

    faces = []
    edges = []
    vertices = []

    if {do_faces}:
        for i in range(body.faces.count):
            f = body.faces.item(i)
{face_filter_block}            faces.append({{
                'index': i,
                'handle': 'face:' + {json.dumps(body_name)} + '/face[' + str(i) + ']:' + f.entityToken,
                'pointOnFace_mm': [f.pointOnFace.x * 10.0, f.pointOnFace.y * 10.0, f.pointOnFace.z * 10.0],
            }})

    if {do_edges}:
        for i in range(body.edges.count):
            e = body.edges.item(i)
            sp = e.startVertex.geometry
            ep_ = e.endVertex.geometry
{edge_filter_block}            edges.append({{
                'index': i,
                'handle': 'edge:' + {json.dumps(body_name)} + '/edge[' + str(i) + ']:' + e.entityToken,
                'length_mm': (((sp.x - ep_.x)**2 + (sp.y - ep_.y)**2 + (sp.z - ep_.z)**2) ** 0.5) * 10.0,
            }})

    if {do_verts}:
        for i in range(body.vertices.count):
            v = body.vertices.item(i)
            vertices.append({{
                'index': i,
                'handle': 'vertex:' + {json.dumps(body_name)} + '/vertex[' + str(i) + ']:' + v.entityToken,
                'position_mm': [v.geometry.x * 10.0, v.geometry.y * 10.0, v.geometry.z * 10.0],
            }})

    print(json.dumps({{
        "ok": True,
        "body": {json.dumps(body_name)},
        "face_count": len(faces),
        "edge_count": len(edges),
        "vertex_count": len(vertices),
        "faces": faces,
        "edges": edges,
        "vertices": vertices,
    }}))
"""


def list_body_entities(
    adapter: FusionAdapter,
    body_name: str,
    kinds: list[str] | None = None,
    face_normal_filter: list[float] | None = None,
    edge_parallel_to: str | None = None,
    min_edge_length_mm: float | None = None,
) -> Envelope:
    try:
        script = build_list_body_entities(
            body_name, kinds, face_normal_filter, edge_parallel_to, min_edge_length_mm
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "list_body_entities")


__all__ = [
    "build_chamfer_edges",
    "build_find_mesh_using_ray",
    "build_fillet_edges",
    "build_list_body_entities",
    "build_measure",
    "build_project_to_sketch",
    "build_ray_collision_with_mesh",
    "chamfer_edges",
    "fillet_edges",
    "find_mesh_using_ray",
    "list_body_entities",
    "measure",
    "project_to_sketch",
    "ray_collision_with_mesh",
]
