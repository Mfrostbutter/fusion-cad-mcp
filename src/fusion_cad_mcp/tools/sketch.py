"""Group 2 / sketch geometry tools (first slice).

create_sketch, add_line, add_rectangle, add_circle, add_polygon,
add_geometric_constraint, add_dimension, assert_profiles.

Entity references inside a sketch use compact strings so the agent can
construct them by hand or from a tool result:

    "origin"                 -> sketch origin point
    "line:0"                 -> sketchLines.item(0)
    "line:0:start"           -> sketchLines.item(0).startSketchPoint
    "line:0:end"             -> sketchLines.item(0).endSketchPoint
    "circle:0"               -> sketchCircles.item(0)
    "circle:0:center"        -> sketchCircles.item(0).centerSketchPoint
    "arc:0" / ":start"/":end"/":center"
    "point:N"                -> sketchPoints.item(N) (free-floating points)
    "dim:N"                  -> sketchDimensions.item(N)

The tool sketch_name arg gives the parent. Each tool generates a Python script
that opens the sketch, resolves the entity refs against the live model, and
performs the op. Coordinates and lengths are accepted in mm; the generators
convert to cm (Fusion internal) at emit time.

Per gotchas.md G9 (corrected 2026-05-31): parameter-name expressions in sketch
dims work fine — add_dimension passes them through verbatim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

# ---------- entity-ref resolver (generator-time) ----------

_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)*$")


def _resolve_ref(ref: str, sk_var: str = "sk") -> str:
    """Emit a Python expression for the entity reference, evaluated against `sk_var`."""
    if not _REF_RE.match(ref):
        raise ValueError(f"malformed entity ref: {ref!r}")
    if ref == "origin":
        return f"{sk_var}.originPoint"

    parts = ref.split(":")
    kind = parts[0]

    if kind in {"line", "circle", "arc", "point", "dim"}:
        if len(parts) < 2:
            raise ValueError(f"{ref!r}: {kind} ref needs an index")
        try:
            idx = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"{ref!r}: index must be an int") from exc
        sub = parts[2] if len(parts) >= 3 else None

        if kind == "line":
            base = f"{sk_var}.sketchCurves.sketchLines.item({idx})"
            if sub is None:
                return base
            if sub == "start":
                return f"{base}.startSketchPoint"
            if sub == "end":
                return f"{base}.endSketchPoint"
        elif kind == "circle":
            base = f"{sk_var}.sketchCurves.sketchCircles.item({idx})"
            if sub is None:
                return base
            if sub == "center":
                return f"{base}.centerSketchPoint"
        elif kind == "arc":
            base = f"{sk_var}.sketchCurves.sketchArcs.item({idx})"
            if sub is None:
                return base
            if sub == "start":
                return f"{base}.startSketchPoint"
            if sub == "end":
                return f"{base}.endSketchPoint"
            if sub == "center":
                return f"{base}.centerSketchPoint"
        elif kind == "point":
            if sub is not None:
                raise ValueError(f"{ref!r}: point refs cannot have a sub-entity")
            return f"{sk_var}.sketchPoints.item({idx})"
        elif kind == "dim":
            if sub is not None:
                raise ValueError(f"{ref!r}: dim refs cannot have a sub-entity")
            return f"{sk_var}.sketchDimensions.item({idx})"

        raise ValueError(f"{ref!r}: unknown sub-entity {sub!r} for {kind}")

    raise ValueError(f"{ref!r}: unknown entity kind {kind!r}")


# ---------- script header shared by all sketch tools ----------

def _sketch_header(sketch_name: str) -> str:
    """Emit Python that locates the sketch by name in the root component."""
    return f"""\
import adsk.core
import adsk.fusion
import json

P = adsk.core.Point3D.create

def _find_sketch(root, name):
    for i in range(root.sketches.count):
        sk = root.sketches.item(i)
        if sk.name == name:
            return sk
    return None

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    root = design.rootComponent
    SKETCH_NAME = {json.dumps(sketch_name)}
"""


def _ensure_sketch_in_script() -> str:
    return """\
    sk = _find_sketch(root, SKETCH_NAME)
    if sk is None:
        print(json.dumps({"ok": False, "error": "sketch_not_found", "name": SKETCH_NAME}))
        return
"""


# ---------- create_sketch ----------

PLANE_MAP = {
    "xy": "root.xYConstructionPlane",
    "xz": "root.xZConstructionPlane",
    "yz": "root.yZConstructionPlane",
}


def build_create_sketch(plane: str, name: str) -> str:
    plane_lc = plane.lower()
    if plane_lc not in PLANE_MAP:
        raise ValueError(f"plane must be one of xy / xz / yz, got {plane!r}")
    plane_expr = PLANE_MAP[plane_lc]
    return f"""\
import adsk.core
import adsk.fusion
import json

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    root = design.rootComponent
    for i in range(root.sketches.count):
        if root.sketches.item(i).name == {json.dumps(name)}:
            print(json.dumps({{"ok": False, "error": "sketch_name_taken", "name": {json.dumps(name)}}}))
            return
    sk = root.sketches.add({plane_expr})
    sk.name = {json.dumps(name)}
    handle = 'sketch:' + sk.name + ':' + sk.entityToken
    print(json.dumps({{"ok": True, "sketch_name": sk.name, "plane": {json.dumps(plane_lc)}, "handle": handle}}))
"""


def create_sketch(adapter: FusionAdapter, plane: str, name: str) -> Envelope:
    try:
        script = build_create_sketch(plane, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "create_sketch")


# ---------- add_line ----------

def build_add_line(sketch_name: str, p1: list[float], p2: list[float]) -> str:
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    return f"""{header}{ensure}    sk.isComputeDeferred = True
    ln = sk.sketchCurves.sketchLines.addByTwoPoints(
        P({p1[0]/10}, {p1[1]/10}, 0),
        P({p2[0]/10}, {p2[1]/10}, 0))
    sk.isComputeDeferred = False
    print(json.dumps({{"ok": True, "line_index": sk.sketchCurves.sketchLines.count - 1}}))
"""


def add_line(adapter: FusionAdapter, sketch: str, p1: list[float], p2: list[float]) -> Envelope:
    if len(p1) != 2 or len(p2) != 2:
        return Envelope(ok=False, error="invalid_input", message="p1 and p2 must be [x, y] in mm")
    return _run(adapter, build_add_line(sketch, p1, p2), "add_line")


# ---------- add_rectangle ----------

VALID_RECT_KINDS = {"center", "corner", "3pt"}


def build_add_rectangle(sketch_name: str, kind: str, p1: list[float], p2: list[float], p3: list[float] | None = None) -> str:
    if kind not in VALID_RECT_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_RECT_KINDS)}, got {kind!r}")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()

    if kind == "center":
        add = f"sk.sketchCurves.sketchLines.addCenterPointRectangle(P({p1[0]/10}, {p1[1]/10}, 0), P({p2[0]/10}, {p2[1]/10}, 0))"
    elif kind == "corner":
        add = f"sk.sketchCurves.sketchLines.addTwoPointRectangle(P({p1[0]/10}, {p1[1]/10}, 0), P({p2[0]/10}, {p2[1]/10}, 0))"
    else:  # 3pt
        if p3 is None or len(p3) != 2:
            raise ValueError("kind=3pt requires p3 as [x, y] in mm")
        add = (f"sk.sketchCurves.sketchLines.addThreePointRectangle("
               f"P({p1[0]/10}, {p1[1]/10}, 0), P({p2[0]/10}, {p2[1]/10}, 0), P({p3[0]/10}, {p3[1]/10}, 0))")

    return f"""{header}{ensure}    sk.isComputeDeferred = True
    pre_count = sk.sketchCurves.sketchLines.count
    rect = {add}
    sk.isComputeDeferred = False
    new_indices = list(range(pre_count, sk.sketchCurves.sketchLines.count))
    line_handles = []
    for idx in new_indices:
        ln = sk.sketchCurves.sketchLines.item(idx)
        # SketchLine itself doesn't have entityToken; the underlying body curves do (after compute)
        # but the points (startSketchPoint/endSketchPoint) DO have entityToken.
        # For now, emit 'point' handles for the endpoints so other tools (constraints, dims) can target them.
        try:
            start_tok = ln.startSketchPoint.entityToken
            end_tok = ln.endSketchPoint.entityToken
            line_handles.append({{
                'index': idx,
                'start_point_handle': 'point:' + sk.name + '/line[' + str(idx) + ']/start:' + start_tok,
                'end_point_handle':   'point:' + sk.name + '/line[' + str(idx) + ']/end:' + end_tok,
            }})
        except Exception:
            line_handles.append({{'index': idx}})
    print(json.dumps({{"ok": True, "kind": {json.dumps(kind)}, "line_indices": new_indices, "line_handles": line_handles}}))
"""


def add_rectangle(adapter: FusionAdapter, sketch: str, kind: str, p1: list[float], p2: list[float], p3: list[float] | None = None) -> Envelope:
    if len(p1) != 2 or len(p2) != 2:
        return Envelope(ok=False, error="invalid_input", message="p1 and p2 must be [x, y] in mm")
    try:
        script = build_add_rectangle(sketch, kind, p1, p2, p3)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_rectangle")


# ---------- add_circle ----------

VALID_CIRCLE_KINDS = {"center_radius", "3pt"}


def build_add_circle(sketch_name: str, kind: str, **kw: Any) -> str:
    if kind not in VALID_CIRCLE_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_CIRCLE_KINDS)}, got {kind!r}")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    if kind == "center_radius":
        center = kw.get("center")
        radius_mm = kw.get("radius_mm")
        if center is None or len(center) != 2 or radius_mm is None:
            raise ValueError("kind=center_radius requires center=[x,y] and radius_mm")
        add = f"sk.sketchCurves.sketchCircles.addByCenterRadius(P({center[0]/10}, {center[1]/10}, 0), {radius_mm/10})"
    else:  # 3pt
        p1, p2, p3 = kw.get("p1"), kw.get("p2"), kw.get("p3")
        if not (p1 and p2 and p3 and len(p1) == 2 and len(p2) == 2 and len(p3) == 2):
            raise ValueError("kind=3pt requires p1, p2, p3 each as [x, y] in mm")
        add = (f"sk.sketchCurves.sketchCircles.addByThreePoints("
               f"P({p1[0]/10}, {p1[1]/10}, 0), P({p2[0]/10}, {p2[1]/10}, 0), P({p3[0]/10}, {p3[1]/10}, 0))")

    return f"""{header}{ensure}    sk.isComputeDeferred = True
    pre = sk.sketchCurves.sketchCircles.count
    c = {add}
    sk.isComputeDeferred = False
    print(json.dumps({{"ok": True, "circle_index": pre, "kind": {json.dumps(kind)}}}))
"""


def add_circle(adapter: FusionAdapter, sketch: str, kind: str, **kw: Any) -> Envelope:
    try:
        script = build_add_circle(sketch, kind, **kw)
    except (ValueError, TypeError) as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_circle")


# ---------- add_ellipse ----------

def build_add_ellipse(sketch_name: str, center: list[float], major_axis_end: list[float], minor_axis_end: list[float]) -> str:
    if len(center) != 2 or len(major_axis_end) != 2 or len(minor_axis_end) != 2:
        raise ValueError("center / major_axis_end / minor_axis_end must each be [x, y] in mm")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    return f"""{header}{ensure}    sk.isComputeDeferred = True
    pre = sk.sketchCurves.sketchEllipses.count
    el = sk.sketchCurves.sketchEllipses.add(
        P({center[0]/10}, {center[1]/10}, 0),
        P({major_axis_end[0]/10}, {major_axis_end[1]/10}, 0),
        P({minor_axis_end[0]/10}, {minor_axis_end[1]/10}, 0))
    sk.isComputeDeferred = False
    print(json.dumps({{"ok": True, "ellipse_index": pre}}))
"""


def add_ellipse(adapter: FusionAdapter, sketch: str, center: list[float], major_axis_end: list[float], minor_axis_end: list[float]) -> Envelope:
    try:
        script = build_add_ellipse(sketch, center, major_axis_end, minor_axis_end)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_ellipse")


# ---------- add_arc ----------

VALID_ARC_KINDS = {"3pt", "center_start_end", "center_start_sweep"}


def build_add_arc(sketch_name: str, kind: str, **kw: Any) -> str:
    if kind not in VALID_ARC_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_ARC_KINDS)}, got {kind!r}")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()

    if kind == "3pt":
        p1, p2, p3 = kw.get("p1"), kw.get("p2"), kw.get("p3")
        if not (p1 and p2 and p3 and len(p1) == 2 and len(p2) == 2 and len(p3) == 2):
            raise ValueError("kind=3pt requires p1, p2, p3 each as [x, y] in mm")
        add = (f"sk.sketchCurves.sketchArcs.addByThreePoints("
               f"P({p1[0]/10}, {p1[1]/10}, 0), P({p2[0]/10}, {p2[1]/10}, 0), P({p3[0]/10}, {p3[1]/10}, 0))")
    elif kind == "center_start_end":
        center, start, end = kw.get("center"), kw.get("start"), kw.get("end")
        if not (center and start and end and len(center) == 2 and len(start) == 2 and len(end) == 2):
            raise ValueError("kind=center_start_end requires center, start, end each as [x, y] in mm")
        add = (f"sk.sketchCurves.sketchArcs.addByCenterStartEnd("
               f"P({center[0]/10}, {center[1]/10}, 0), P({start[0]/10}, {start[1]/10}, 0), P({end[0]/10}, {end[1]/10}, 0))")
    else:  # center_start_sweep
        center, start, sweep_rad = kw.get("center"), kw.get("start"), kw.get("sweep_radians")
        if not (center and start and sweep_rad is not None and len(center) == 2 and len(start) == 2):
            raise ValueError("kind=center_start_sweep requires center, start, sweep_radians (float)")
        add = (f"sk.sketchCurves.sketchArcs.addByCenterStartSweep("
               f"P({center[0]/10}, {center[1]/10}, 0), P({start[0]/10}, {start[1]/10}, 0), {sweep_rad})")

    return f"""{header}{ensure}    sk.isComputeDeferred = True
    pre = sk.sketchCurves.sketchArcs.count
    arc = {add}
    sk.isComputeDeferred = False
    print(json.dumps({{"ok": True, "arc_index": pre, "kind": {json.dumps(kind)}}}))
"""


def add_arc(adapter: FusionAdapter, sketch: str, kind: str, **kw: Any) -> Envelope:
    try:
        script = build_add_arc(sketch, kind, **kw)
    except (ValueError, TypeError) as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_arc")


# ---------- add_spline ----------

def build_add_spline(sketch_name: str, points: list[list[float]], closed: bool = False) -> str:
    if not points or len(points) < 2:
        raise ValueError("points must be a list of at least 2 [x, y] points in mm")
    for i, p in enumerate(points):
        if len(p) != 2:
            raise ValueError(f"points[{i}] must be [x, y]")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    points_block = ",\n        ".join(f"P({p[0]/10}, {p[1]/10}, 0)" for p in points)
    is_closed = "True" if closed else "False"
    return f"""{header}{ensure}    sk.isComputeDeferred = True
    pre = sk.sketchCurves.sketchFittedSplines.count
    coll = adsk.core.ObjectCollection.create()
    for pt in [
        {points_block}
    ]:
        coll.add(pt)
    sp = sk.sketchCurves.sketchFittedSplines.add(coll)
    sp.isClosed = {is_closed}
    sk.isComputeDeferred = False
    print(json.dumps({{"ok": True, "spline_index": pre, "point_count": {len(points)}, "closed": {is_closed}}}))
"""


def add_spline(adapter: FusionAdapter, sketch: str, points: list[list[float]], closed: bool = False) -> Envelope:
    try:
        script = build_add_spline(sketch, points, closed)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_spline")


# ---------- add_polygon ----------

def build_add_polygon(sketch_name: str, sides: int, center: list[float], vertex: list[float], inscribed: bool = True) -> str:
    if sides < 3:
        raise ValueError("sides must be >= 3")
    if len(center) != 2 or len(vertex) != 2:
        raise ValueError("center and vertex must be [x, y] in mm")
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    method = "addScribedPolygon" if inscribed else "addCircumscribedPolygon"
    # Fusion's addScribedPolygon(centerPoint, edgeCount, angle, radius, isFlipped)
    # We'll compute radius + angle from center+vertex.
    return f"""{header}{ensure}    import math
    cx, cy = {center[0]/10}, {center[1]/10}
    vx, vy = {vertex[0]/10}, {vertex[1]/10}
    radius = math.hypot(vx - cx, vy - cy)
    angle = math.atan2(vy - cy, vx - cx)
    sk.isComputeDeferred = True
    pre = sk.sketchCurves.sketchLines.count
    poly = sk.sketchCurves.sketchLines.{method}(P(cx, cy, 0), {sides}, angle, radius, False)
    sk.isComputeDeferred = False
    new_indices = list(range(pre, sk.sketchCurves.sketchLines.count))
    print(json.dumps({{"ok": True, "sides": {sides}, "line_indices": new_indices}}))
"""


def add_polygon(adapter: FusionAdapter, sketch: str, sides: int, center: list[float], vertex: list[float], inscribed: bool = True) -> Envelope:
    try:
        script = build_add_polygon(sketch, sides, center, vertex, inscribed)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_polygon")


# ---------- add_geometric_constraint ----------

# Maps tool-facing kind -> (gc-method-name, expected_entity_count, accepts_lines_or_points)
GC_KINDS: dict[str, tuple[str, int, str]] = {
    "horizontal":    ("addHorizontal",    1, "line_or_two_points"),
    "vertical":      ("addVertical",      1, "line_or_two_points"),
    "parallel":      ("addParallel",      2, "lines"),
    "perpendicular": ("addPerpendicular", 2, "lines"),
    "coincident":    ("addCoincident",    2, "any"),
    "tangent":       ("addTangent",       2, "any"),
    "equal":         ("addEqual",         2, "any"),
    "concentric":    ("addConcentric",    2, "circle_or_arc"),
    "fix":           ("addFix",           1, "any"),
    "midpoint":      ("addMidPoint",      2, "point_and_line"),
    "symmetric":     ("addSymmetry",      3, "two_entities_about_line"),
}


def build_add_geometric_constraint(sketch_name: str, kind: str, entities: list[str]) -> str:
    if kind not in GC_KINDS:
        raise ValueError(f"kind must be one of {sorted(GC_KINDS)}, got {kind!r}")
    method, expected, _shape = GC_KINDS[kind]
    if len(entities) != expected:
        raise ValueError(f"kind={kind} requires {expected} entity refs, got {len(entities)}")

    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    resolved = ", ".join(_resolve_ref(r) for r in entities)
    return f"""{header}{ensure}    gc = sk.geometricConstraints
    gc.{method}({resolved})
    print(json.dumps({{"ok": True, "kind": {json.dumps(kind)}, "applied_to": {json.dumps(entities)}}}))
"""


def add_geometric_constraint(adapter: FusionAdapter, sketch: str, kind: str, entities: list[str]) -> Envelope:
    try:
        script = build_add_geometric_constraint(sketch, kind, entities)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_geometric_constraint")


# ---------- add_dimension ----------

VALID_DIM_KINDS = {"distance_h", "distance_v", "distance", "angle", "radial", "diameter"}

_DIM_ORIENT = {
    "distance_h": "HorizontalDimensionOrientation",
    "distance_v": "VerticalDimensionOrientation",
    "distance":   "AlignedDimensionOrientation",
}


def build_add_dimension(
    sketch_name: str,
    kind: str,
    entities: list[str],
    expression: str,
    text_pos: list[float] | None = None,
) -> str:
    if kind not in VALID_DIM_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_DIM_KINDS)}, got {kind!r}")
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression must be a non-empty string")

    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    tp = text_pos if text_pos and len(text_pos) == 2 else [0.0, 0.0]
    tp_cm = (tp[0] / 10.0, tp[1] / 10.0)

    if kind in {"distance_h", "distance_v", "distance"}:
        if len(entities) != 2:
            raise ValueError(f"kind={kind} requires 2 point refs")
        p1 = _resolve_ref(entities[0])
        p2 = _resolve_ref(entities[1])
        orient = f"adsk.fusion.DimensionOrientations.{_DIM_ORIENT[kind]}"
        call = f"sk.sketchDimensions.addDistanceDimension({p1}, {p2}, {orient}, P({tp_cm[0]}, {tp_cm[1]}, 0))"
    elif kind == "angle":
        if len(entities) != 2:
            raise ValueError("kind=angle requires 2 line refs")
        l1 = _resolve_ref(entities[0])
        l2 = _resolve_ref(entities[1])
        call = f"sk.sketchDimensions.addAngularDimension({l1}, {l2}, P({tp_cm[0]}, {tp_cm[1]}, 0))"
    elif kind == "radial":
        if len(entities) != 1:
            raise ValueError("kind=radial requires 1 circle/arc ref")
        c = _resolve_ref(entities[0])
        call = f"sk.sketchDimensions.addRadialDimension({c}, P({tp_cm[0]}, {tp_cm[1]}, 0))"
    elif kind == "diameter":
        if len(entities) != 1:
            raise ValueError("kind=diameter requires 1 circle/arc ref")
        c = _resolve_ref(entities[0])
        call = f"sk.sketchDimensions.addDiameterDimension({c}, P({tp_cm[0]}, {tp_cm[1]}, 0))"
    else:
        raise AssertionError("unreachable")

    return f"""{header}{ensure}    pre = sk.sketchDimensions.count
    d = {call}
    d.parameter.expression = {json.dumps(expression)}
    print(json.dumps({{
        "ok": True,
        "kind": {json.dumps(kind)},
        "dim_index": pre,
        "expression": d.parameter.expression,
        "value_cm": d.parameter.value,
        "value_mm": d.parameter.value * 10.0,
    }}))
"""


def add_dimension(
    adapter: FusionAdapter,
    sketch: str,
    kind: str,
    entities: list[str],
    expression: str,
    text_pos: list[float] | None = None,
) -> Envelope:
    try:
        script = build_add_dimension(sketch, kind, entities, expression, text_pos)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _run(adapter, script, "add_dimension")


# ---------- assert_profiles ----------

def build_assert_profiles(sketch_name: str, expected: int) -> str:
    header = _sketch_header(sketch_name)
    ensure = _ensure_sketch_in_script()
    return f"""{header}{ensure}    actual = sk.profiles.count
    ok = actual == {expected}
    print(json.dumps({{
        "ok": ok,
        "actual": actual,
        "expected": {expected},
        "isFullyConstrained": sk.isFullyConstrained,
    }}))
"""


def assert_profiles(adapter: FusionAdapter, sketch: str, expected: int) -> Envelope:
    if not isinstance(expected, int) or expected < 0:
        return Envelope(ok=False, error="invalid_input", message="expected must be a non-negative int")
    # Bypass the generic _run helper so we can distinguish "assertion failed"
    # (parsed.ok = False but the script ran fine) from real script-level errors.
    env = adapter.execute_script(build_assert_profiles(sketch, expected))
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="assert_profiles_parse_failed", message=env.message)
    if "error" in parsed:
        return Envelope(
            ok=False, error=parsed.get("error", "assert_profiles_error"),
            message=env.message, result=parsed,
        )
    if parsed.get("ok") is False:
        return Envelope(
            ok=False, error="profile_count_mismatch",
            message=env.message, result=parsed,
        )
    return Envelope(ok=True, message=env.message, result=parsed)


# ---------- probe_sketch_dimensions ----------

# Shared script fragment: ambiguity-aware sketch lookup across root + every
# sub-component. Returns (sketch, owner_component_name, ambiguity_matches).
# - ambiguity_matches is None when resolved cleanly.
# - When the name matches >1 sketch in the search scope, ambiguity_matches is
#   a list of {"component", "sketch"} entries so the caller can disambiguate
#   in one follow-up call with component_name set.
# - comp_hint resolution: if hint matches exactly 1 sketch -> resolve. If hint
#   matches 0 -> fall through to global search. If hint matches >1 -> still
#   ambiguous (within the hinted component).
_SKETCH_RESOLVER = r"""
def _find_all_sketches(comp, name):
    out = []
    for i in range(comp.sketches.count):
        sk = comp.sketches.item(i)
        if sk.name == name:
            out.append((sk, comp.name))
    for j in range(comp.occurrences.count):
        occ = comp.occurrences.item(j)
        if occ.component is not None:
            out.extend(_find_all_sketches(occ.component, name))
    return out

def _resolve_sketch(root, name, comp_hint):
    # Returns (sketch, owner_component_name, ambiguity_matches_or_None).
    if comp_hint is not None:
        hinted = [(s, c) for s, c in _find_all_sketches(root, name) if c == comp_hint]
        if len(hinted) == 1:
            return hinted[0][0], hinted[0][1], None
        if len(hinted) > 1:
            return None, None, [{"component": c, "sketch": s.name} for s, c in hinted]
        # zero hits in hinted component; fall through to global search
    all_m = _find_all_sketches(root, name)
    if len(all_m) == 0:
        return None, None, None  # not found
    if len(all_m) == 1:
        return all_m[0][0], all_m[0][1], None
    return None, None, [{"component": c, "sketch": s.name} for s, c in all_m]

# Back-compat shim for any inline code still calling _find_sketch_anywhere.
def _find_sketch_anywhere(comp, name):
    matches = _find_all_sketches(comp, name)
    if not matches:
        return None, None
    return matches[0]
"""

# Alias preserved so any existing imports keep working.
_SKETCH_WALKER = _SKETCH_RESOLVER


def build_probe_sketch_dimensions(sketch_name: str, component_name: str | None = None) -> str:
    """Dump every dimension in a sketch: parameter name, expression, value, and
    the geometry coords of the entities it constrains.

    Use this to identify which literal-named dim (`d278`, etc.) controls which
    geometric feature, when sketches use baked-in numbers instead of user-param
    expressions.

    component_name is an optional hint for disambiguation when the same sketch
    name exists in multiple components (uses the first match in tree order
    when not specified).
    """
    sk_n = json.dumps(sketch_name)
    cn = "None" if component_name is None else json.dumps(component_name)
    return f"""\
import adsk.core
import adsk.fusion
import json
{_SKETCH_WALKER}

SKETCH_NAME = {sk_n}
COMP_HINT = {cn}


def _entity_descriptor(e):
    if e is None:
        return None
    try:
        cls = e.classType().split("::")[-1]
    except Exception:
        cls = "?"
    out = {{"type": cls}}
    try:
        if hasattr(e, "geometry"):
            g = e.geometry
            if hasattr(g, "x"):
                out["point_mm"] = [round(g.x*10, 4), round(g.y*10, 4)]
        if hasattr(e, "startSketchPoint") and hasattr(e, "endSketchPoint"):
            sp = e.startSketchPoint.geometry
            ep = e.endSketchPoint.geometry
            out["start_mm"] = [round(sp.x*10, 4), round(sp.y*10, 4)]
            out["end_mm"] = [round(ep.x*10, 4), round(ep.y*10, 4)]
        if hasattr(e, "centerSketchPoint") and not out.get("start_mm"):
            cp = e.centerSketchPoint.geometry
            out["center_mm"] = [round(cp.x*10, 4), round(cp.y*10, 4)]
            if hasattr(e, "radius"):
                out["radius_mm"] = round(e.radius*10, 4)
            if hasattr(e, "majorAxisRadius"):
                out["major_radius_mm"] = round(e.majorAxisRadius*10, 4)
                out["minor_radius_mm"] = round(e.minorAxisRadius*10, 4)
    except Exception as ex:
        out["probe_error"] = str(ex)
    return out


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    sk, owner, ambig = _resolve_sketch(design.rootComponent, SKETCH_NAME, COMP_HINT)
    if ambig is not None:
        print(json.dumps({{
            "ok": False, "error": "sketch_name_ambiguous", "name": SKETCH_NAME,
            "matches": ambig,
            "hint": "Pass component_name to disambiguate.",
        }}))
        return
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": SKETCH_NAME}}))
        return
    dims = []
    for d in sk.sketchDimensions:
        try:
            cls = d.classType().split("::")[-1]
        except Exception:
            cls = "?"
        try:
            p = d.parameter
            name = p.name
            expr = p.expression
            val_cm = p.value
            unit = p.unit or ""
            # Most sketch dims are length (cm internal); a few are angles (rad).
            if unit in ("", "cm", "mm", "m", "in", "ft"):
                val_mm = round(val_cm * 10, 4)
                value_field = {{"value_mm": val_mm}}
            else:
                value_field = {{"value": round(val_cm, 6), "unit": unit}}
        except Exception as ex:
            name = "?"; expr = "?"; value_field = {{"value_error": str(ex)}}; unit = "?"
        try:
            e1 = _entity_descriptor(d.entityOne)
        except Exception:
            e1 = None
        try:
            e2 = _entity_descriptor(d.entityTwo) if hasattr(d, "entityTwo") else None
        except Exception:
            e2 = None
        entry = {{
            "dim_class": cls,
            "param_name": name,
            "expression": expr,
            "unit": unit,
            "entity_one": e1,
            "entity_two": e2,
        }}
        entry.update(value_field)
        dims.append(entry)
    print(json.dumps({{
        "ok": True,
        "sketch_name": sk.name,
        "component": owner,
        "plane": sk.referencePlane.name if sk.referencePlane else None,
        "isFullyConstrained": sk.isFullyConstrained,
        "profile_count": sk.profiles.count,
        "dimension_count": len(dims),
        "dimensions": dims,
    }}))
"""


def probe_sketch_dimensions(
    adapter: FusionAdapter,
    sketch: str,
    component_name: str | None = None,
) -> Envelope:
    return _run(
        adapter,
        build_probe_sketch_dimensions(sketch, component_name),
        "probe_sketch_dimensions",
    )


# ---------- edit_sketch_dimension ----------

def build_edit_sketch_dimension(
    sketch_name: str,
    dim_name: str,
    new_expression: str,
    component_name: str | None = None,
) -> str:
    """Edit a sketch dimension's expression by parameter name (e.g., 'd278').

    Returns old expression, new expression, and post-edit value. Triggers
    design.computeAll() before returning so the caller can chain into an
    audit_feature_health call.
    """
    sk_n = json.dumps(sketch_name)
    dim_n = json.dumps(dim_name)
    expr_n = json.dumps(new_expression)
    cn = "None" if component_name is None else json.dumps(component_name)
    return f"""\
import adsk.core
import adsk.fusion
import json
{_SKETCH_WALKER}

SKETCH_NAME = {sk_n}
DIM_NAME = {dim_n}
NEW_EXPR = {expr_n}
COMP_HINT = {cn}


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    sk, owner, ambig = _resolve_sketch(design.rootComponent, SKETCH_NAME, COMP_HINT)
    if ambig is not None:
        print(json.dumps({{
            "ok": False, "error": "sketch_name_ambiguous", "name": SKETCH_NAME,
            "matches": ambig,
            "hint": "Pass component_name to disambiguate.",
        }}))
        return
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": SKETCH_NAME}}))
        return
    target = None
    for d in sk.sketchDimensions:
        try:
            if d.parameter.name == DIM_NAME:
                target = d
                break
        except Exception:
            continue
    if target is None:
        # Surface what IS available so the agent can recover without another tool call
        available = []
        for d in sk.sketchDimensions:
            try:
                available.append({{"param_name": d.parameter.name, "expression": d.parameter.expression}})
            except Exception:
                pass
        print(json.dumps({{
            "ok": False,
            "error": "dim_not_found",
            "name": DIM_NAME,
            "sketch": sk.name,
            "component": owner,
            "available_dims": available,
        }}))
        return
    try:
        old_expr = target.parameter.expression
    except Exception:
        old_expr = "?"
    try:
        target.parameter.expression = NEW_EXPR
    except Exception as ex:
        print(json.dumps({{
            "ok": False,
            "error": "expression_rejected",
            "name": DIM_NAME,
            "tried": NEW_EXPR,
            "old_expression": old_expr,
            "detail": str(ex),
        }}))
        return
    design.computeAll()
    new_expr = target.parameter.expression
    new_val = target.parameter.value
    new_unit = target.parameter.unit or ""
    # Angle dims store value in radians internally; length dims in cm.
    # Emit the right-labeled field so the agent sees correct units.
    result = {{
        "ok": True,
        "sketch": sk.name,
        "component": owner,
        "param_name": DIM_NAME,
        "old_expression": old_expr,
        "new_expression": new_expr,
        "unit": new_unit,
        "isFullyConstrained_after": sk.isFullyConstrained,
    }}
    if new_unit in ("rad", "deg"):
        # internal value is radians; convert to degrees for display
        import math as _math
        result["new_value_deg"] = round(_math.degrees(new_val), 4)
    elif new_unit in ("", "cm", "mm", "m", "in", "ft"):
        # internal value is cm
        result["new_value_mm"] = round(new_val * 10, 4)
    else:
        # unknown unit class - emit raw value and unit so caller can interpret
        result["new_value_raw"] = round(new_val, 6)
    print(json.dumps(result))
"""


def edit_sketch_dimension(
    adapter: FusionAdapter,
    sketch: str,
    dim_name: str,
    new_expression: str,
    component_name: str | None = None,
) -> Envelope:
    if not isinstance(new_expression, str) or not new_expression.strip():
        return Envelope(ok=False, error="invalid_input", message="new_expression must be a non-empty string")
    return _run(
        adapter,
        build_edit_sketch_dimension(sketch, dim_name, new_expression, component_name),
        "edit_sketch_dimension",
    )


# ---------- shared runner ----------

def _run(adapter: FusionAdapter, script: str, label: str) -> Envelope:
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


__all__ = [
    "add_arc",
    "add_circle",
    "add_dimension",
    "add_ellipse",
    "add_geometric_constraint",
    "add_line",
    "add_polygon",
    "add_rectangle",
    "add_spline",
    "assert_profiles",
    "build_add_arc",
    "build_add_circle",
    "build_add_dimension",
    "build_add_ellipse",
    "build_add_geometric_constraint",
    "build_add_line",
    "build_add_polygon",
    "build_add_rectangle",
    "build_add_spline",
    "build_assert_profiles",
    "build_create_sketch",
    "build_edit_sketch_dimension",
    "build_probe_sketch_dimensions",
    "create_sketch",
    "edit_sketch_dimension",
    "probe_sketch_dimensions",
]
