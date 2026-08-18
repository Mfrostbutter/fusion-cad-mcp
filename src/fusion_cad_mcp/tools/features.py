"""Group 3 / feature tools (first slice).

extrude, fillet_edges_by_geometry, chamfer_edges_by_geometry, mirror_feature,
pattern_rectangular, pattern_circular, combine.

Addressing model (until V2 Section 5a handles land):
- sketches addressed by name
- profiles addressed by (sketch_name, profile_index)
- bodies addressed by name (set when extrude creates them; we also surface body_index)
- features addressed by name
- construction planes / axes addressed by 'xy'|'xz'|'yz'|'x'|'y'|'z' (principal) or name
- edges/faces are NOT addressable here — the `_by_geometry` variants of fillet/chamfer
  iterate edges programmatically and filter by axis direction + optional length
"""

from __future__ import annotations

import json

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

# ---------- shared helpers ----------

OPERATION_ENUM = {
    "new_body": "NewBodyFeatureOperation",
    "join": "JoinFeatureOperation",
    "cut": "CutFeatureOperation",
    "intersect": "IntersectFeatureOperation",
    "new_component": "NewComponentFeatureOperation",
}

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


_FIND_BODY_HELPER = """
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
"""

_FIND_FEATURE_OR_BODY_HELPER = """
def _find_feature_or_body(root, name):
    for i in range(root.features.count):
        f = root.features.item(i)
        if f.name == name: return ('feature', f)
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
    b = walk(root)
    if b is not None: return ('body', b)
    return (None, None)
"""


def _resolve_plane_expr(plane: str) -> str:
    """Return Python expression evaluating to the named plane.
    'xy'/'xz'/'yz' -> principal; else assumed to be a construction plane name and looked up."""
    plane_lc = plane.lower()
    if plane_lc in PRINCIPAL_PLANES:
        return PRINCIPAL_PLANES[plane_lc]
    # Otherwise: resolve at runtime via name lookup in constructionPlanes
    return f"""(
        next((root.constructionPlanes.item(i) for i in range(root.constructionPlanes.count)
              if root.constructionPlanes.item(i).name == {json.dumps(plane)}), None)
    )"""


def _resolve_axis_expr(axis: str) -> str:
    axis_lc = axis.lower()
    if axis_lc in PRINCIPAL_AXES:
        return PRINCIPAL_AXES[axis_lc]
    return f"""(
        next((root.constructionAxes.item(i) for i in range(root.constructionAxes.count)
              if root.constructionAxes.item(i).name == {json.dumps(axis)}), None)
    )"""


def _emit_header() -> str:
    return """\
import adsk.core, adsk.fusion
import json
"""


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


# ---------- extrude ----------

VALID_EXTENTS = {"distance", "symmetric", "all_positive", "all_negative"}


def build_extrude(
    sketch: str,
    profile_index: int = 0,
    operation: str = "new_body",
    extent_kind: str = "distance",
    expression: str | None = None,
    direction: str = "positive",
    is_full_length: bool = True,
    participants: list[str] | None = None,
    name: str | None = None,
) -> str:
    if operation not in OPERATION_ENUM:
        raise ValueError(f"operation must be one of {sorted(OPERATION_ENUM)}, got {operation!r}")
    if extent_kind not in VALID_EXTENTS:
        raise ValueError(f"extent_kind must be one of {sorted(VALID_EXTENTS)}, got {extent_kind!r}")
    if extent_kind in {"distance", "symmetric"} and not expression:
        raise ValueError(f"extent_kind={extent_kind} requires an expression")
    if direction not in {"positive", "negative"}:
        raise ValueError(f"direction must be positive or negative, got {direction!r}")

    op_expr = f"adsk.fusion.FeatureOperations.{OPERATION_ENUM[operation]}"

    # extent setter
    if extent_kind == "distance":
        is_negative = "True" if direction == "negative" else "False"
        extent_setter = (
            f"ext_in.setDistanceExtent({is_negative}, "
            f"adsk.core.ValueInput.createByString({json.dumps(expression)}))"
        )
    elif extent_kind == "symmetric":
        is_full = "True" if is_full_length else "False"
        extent_setter = (
            f"ext_in.setSymmetricExtent("
            f"adsk.core.ValueInput.createByString({json.dumps(expression)}), {is_full})"
        )
    elif extent_kind == "all_positive":
        extent_setter = "ext_in.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)"
    else:  # all_negative
        extent_setter = "ext_in.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)"

    # participants
    parts_block = ""
    parts_helper = ""
    if participants:
        parts_helper = _FIND_BODY_HELPER
        parts_block = "\n".join(
            [
                "    _parts = []",
                *[
                    f"    _b = _find_body(root, {json.dumps(p)})"
                    + f"\n    if _b is None: print(json.dumps({{'ok': False, 'error': 'participant_not_found', 'name': {json.dumps(p)}}})); return"
                    + "\n    _parts.append(_b)"
                    for p in participants
                ],
                "    ext_in.participantBodies = _parts",
            ]
        )

    name_block = ""
    if name:
        name_block = f"    feat.name = {json.dumps(name)}\n"

    return f"""\
{_emit_header()}{parts_helper}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    sk = None
    for i in range(root.sketches.count):
        s = root.sketches.item(i)
        if s.name == {json.dumps(sketch)}:
            sk = s
            break
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": {json.dumps(sketch)}}})); return
    if {profile_index} < 0 or {profile_index} >= sk.profiles.count:
        print(json.dumps({{"ok": False, "error": "profile_index_out_of_range",
                           "got": {profile_index}, "count": sk.profiles.count}})); return

    ext_in = root.features.extrudeFeatures.createInput(sk.profiles.item({profile_index}), {op_expr})
    {extent_setter}
{parts_block}
    feat = root.features.extrudeFeatures.add(ext_in)
{name_block}    body_names = [feat.bodies.item(i).name for i in range(feat.bodies.count)] if feat.bodies.count > 0 else []
    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "operation": {json.dumps(operation)},
        "extent_kind": {json.dumps(extent_kind)},
        "bodies_added": body_names,
    }}))
"""


def extrude(
    adapter: FusionAdapter,
    sketch: str,
    profile_index: int = 0,
    operation: str = "new_body",
    extent_kind: str = "distance",
    expression: str | None = None,
    direction: str = "positive",
    is_full_length: bool = True,
    participants: list[str] | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_extrude(
            sketch,
            profile_index,
            operation,
            extent_kind,
            expression,
            direction,
            is_full_length,
            participants,
            name,
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "extrude")


# ---------- fillet_edges_by_geometry ----------

EDGE_PARALLEL = {"x", "y", "z", "any"}


def build_fillet_edges_by_geometry(
    body: str,
    radius: str,
    parallel_to: str = "z",
    min_length_mm: float | None = None,
    is_tangent_chain: bool = True,
    name: str | None = None,
) -> str:
    if parallel_to not in EDGE_PARALLEL:
        raise ValueError(f"parallel_to must be one of {sorted(EDGE_PARALLEL)}, got {parallel_to!r}")
    if not radius or not isinstance(radius, str):
        raise ValueError("radius must be a non-empty expression string")

    min_len_check = "True"
    if min_length_mm is not None:
        if min_length_mm < 0:
            raise ValueError("min_length_mm must be >= 0")
        min_len_check = f"(edge_length_cm >= {min_length_mm / 10.0})"

    if parallel_to == "any":
        axis_check = "True"
    else:
        # parallel to axis A means the other two coords match between endpoints
        if parallel_to == "x":
            axis_check = (
                "abs(sp.y - ep.y) < 1e-6 and abs(sp.z - ep.z) < 1e-6 and abs(sp.x - ep.x) > 1e-6"
            )
        elif parallel_to == "y":
            axis_check = (
                "abs(sp.x - ep.x) < 1e-6 and abs(sp.z - ep.z) < 1e-6 and abs(sp.y - ep.y) > 1e-6"
            )
        else:  # z
            axis_check = (
                "abs(sp.x - ep.x) < 1e-6 and abs(sp.y - ep.y) < 1e-6 and abs(sp.z - ep.z) > 1e-6"
            )

    is_tan = "True" if is_tangent_chain else "False"
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}{_FIND_BODY_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body)}}})); return

    edges = adsk.core.ObjectCollection.create()
    matched = 0
    for i in range(body.edges.count):
        e = body.edges.item(i)
        sp = e.startVertex.geometry
        ep = e.endVertex.geometry
        edge_length_cm = ((sp.x - ep.x)**2 + (sp.y - ep.y)**2 + (sp.z - ep.z)**2) ** 0.5
        if {axis_check} and {min_len_check}:
            edges.add(e)
            matched += 1

    if matched == 0:
        print(json.dumps({{"ok": False, "error": "no_edges_matched",
                           "parallel_to": {json.dumps(parallel_to)},
                           "min_length_mm": {repr(min_length_mm)}}})); return

    fil_in = root.features.filletFeatures.createInput()
    fil_in.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByString({json.dumps(radius)}), {is_tan})
    feat = root.features.filletFeatures.add(fil_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "edges_filleted": matched,
        "radius": {json.dumps(radius)},
    }}))
"""


def fillet_edges_by_geometry(
    adapter: FusionAdapter,
    body: str,
    radius: str,
    parallel_to: str = "z",
    min_length_mm: float | None = None,
    is_tangent_chain: bool = True,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_fillet_edges_by_geometry(
            body, radius, parallel_to, min_length_mm, is_tangent_chain, name
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "fillet_edges_by_geometry")


# ---------- chamfer_edges_by_geometry ----------

CHAMFER_KINDS = {"equal", "two_dist", "dist_angle"}


def build_chamfer_edges_by_geometry(
    body: str,
    distance: str,
    parallel_to: str = "z",
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    min_length_mm: float | None = None,
    name: str | None = None,
) -> str:
    if parallel_to not in EDGE_PARALLEL:
        raise ValueError(f"parallel_to must be one of {sorted(EDGE_PARALLEL)}, got {parallel_to!r}")
    if kind not in CHAMFER_KINDS:
        raise ValueError(f"kind must be one of {sorted(CHAMFER_KINDS)}, got {kind!r}")
    if not distance:
        raise ValueError("distance is required")
    if kind == "two_dist" and not distance2:
        raise ValueError("kind=two_dist requires distance2")
    if kind == "dist_angle" and not angle:
        raise ValueError("kind=dist_angle requires angle")

    min_len_check = "True"
    if min_length_mm is not None:
        if min_length_mm < 0:
            raise ValueError("min_length_mm must be >= 0")
        min_len_check = f"(edge_length_cm >= {min_length_mm / 10.0})"

    if parallel_to == "any":
        axis_check = "True"
    elif parallel_to == "x":
        axis_check = (
            "abs(sp.y - ep.y) < 1e-6 and abs(sp.z - ep.z) < 1e-6 and abs(sp.x - ep.x) > 1e-6"
        )
    elif parallel_to == "y":
        axis_check = (
            "abs(sp.x - ep.x) < 1e-6 and abs(sp.z - ep.z) < 1e-6 and abs(sp.y - ep.y) > 1e-6"
        )
    else:
        axis_check = (
            "abs(sp.x - ep.x) < 1e-6 and abs(sp.y - ep.y) < 1e-6 and abs(sp.z - ep.z) > 1e-6"
        )

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

    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}{_FIND_BODY_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body)}}})); return

    edges = adsk.core.ObjectCollection.create()
    matched = 0
    for i in range(body.edges.count):
        e = body.edges.item(i)
        sp = e.startVertex.geometry
        ep = e.endVertex.geometry
        edge_length_cm = ((sp.x - ep.x)**2 + (sp.y - ep.y)**2 + (sp.z - ep.z)**2) ** 0.5
        if {axis_check} and {min_len_check}:
            edges.add(e)
            matched += 1

    if matched == 0:
        print(json.dumps({{"ok": False, "error": "no_edges_matched"}})); return

    chm_in = root.features.chamferFeatures.createInput2()
    {chm_call}
    feat = root.features.chamferFeatures.add(chm_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "edges_chamfered": matched,
        "kind": {json.dumps(kind)},
    }}))
"""


def chamfer_edges_by_geometry(
    adapter: FusionAdapter,
    body: str,
    distance: str,
    parallel_to: str = "z",
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    min_length_mm: float | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_chamfer_edges_by_geometry(
            body, distance, parallel_to, kind, distance2, angle, min_length_mm, name
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "chamfer_edges_by_geometry")


# ---------- mirror_feature ----------


def build_mirror_feature(
    feature_or_body: str,
    plane: str,
    name: str | None = None,
) -> str:
    plane_expr = _resolve_plane_expr(plane)
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""
    return f"""\
{_emit_header()}
def _find_feature_or_body(root, name):
    for i in range(root.features.count):
        f = root.features.item(i)
        if f.name == name: return ('feature', f)
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
    b = walk(root)
    if b is not None: return ('body', b)
    return (None, None)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    kind, target = _find_feature_or_body(root, {json.dumps(feature_or_body)})
    if target is None:
        print(json.dumps({{"ok": False, "error": "target_not_found", "name": {json.dumps(feature_or_body)}}})); return

    plane = {plane_expr}
    if plane is None:
        print(json.dumps({{"ok": False, "error": "plane_not_found", "plane": {json.dumps(plane)}}})); return

    items = adsk.core.ObjectCollection.create()
    items.add(target)

    mir_in = root.features.mirrorFeatures.createInput(items, plane)
    feat = root.features.mirrorFeatures.add(mir_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "mirrored_kind": kind,
        "source": {json.dumps(feature_or_body)},
        "plane": {json.dumps(plane)},
    }}))
"""


def mirror_feature(
    adapter: FusionAdapter,
    feature_or_body: str,
    plane: str,
    name: str | None = None,
) -> Envelope:
    return _ok_runner(adapter, build_mirror_feature(feature_or_body, plane, name), "mirror_feature")


# ---------- pattern_rectangular ----------


def build_pattern_rectangular(
    feature_or_body: str,
    x_axis: str = "x",
    x_count: int = 2,
    x_distance: str | None = None,
    y_axis: str | None = None,
    y_count: int = 1,
    y_distance: str | None = None,
    name: str | None = None,
) -> str:
    if x_count < 1:
        raise ValueError("x_count must be >= 1")
    if y_count < 1:
        raise ValueError("y_count must be >= 1")
    if x_count > 1 and not x_distance:
        raise ValueError("x_distance required when x_count > 1")
    if y_axis and y_count > 1 and not y_distance:
        raise ValueError("y_distance required when y_axis given and y_count > 1")

    x_axis_expr = _resolve_axis_expr(x_axis)
    y_axis_expr = _resolve_axis_expr(y_axis) if y_axis else "None"

    # setDirectionTwo must always be called: an unset direction two yields
    # coincident duplicate bodies, not one row. Single-direction patterns pin it
    # to quantity 1 / 0 mm. The fallback axis must differ from the primary axis
    # or Fusion rejects the input; a named axis falls back to Y.
    _fallback = "z" if str(x_axis).lower() == "y" else "y"
    dir_two_fallback_expr = PRINCIPAL_AXES[_fallback]

    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}
def _find_feature_or_body(root, name):
    for i in range(root.features.count):
        f = root.features.item(i)
        if f.name == name: return ('feature', f)
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
    b = walk(root)
    if b is not None: return ('body', b)
    return (None, None)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    _kind, target = _find_feature_or_body(root, {json.dumps(feature_or_body)})
    if target is None:
        print(json.dumps({{"ok": False, "error": "target_not_found", "name": {json.dumps(feature_or_body)}}})); return

    # repr(), not json: None must render as Python None, not null.
    x_axis = {x_axis_expr}
    y_axis = {y_axis_expr}
    if x_axis is None:
        print(json.dumps({{"ok": False, "error": "x_axis_not_found", "axis": {json.dumps(x_axis)}}})); return
    if {repr(y_axis)} is not None and y_axis is None:
        print(json.dumps({{"ok": False, "error": "y_axis_not_found", "axis": {repr(y_axis)}}})); return

    items = adsk.core.ObjectCollection.create()
    items.add(target)

    pat_in = root.features.rectangularPatternFeatures.createInput(
        items,
        x_axis,
        adsk.core.ValueInput.createByReal({x_count}),
        adsk.core.ValueInput.createByString({json.dumps(x_distance or "0 mm")}),
        adsk.fusion.PatternDistanceType.ExtentPatternDistanceType,
    )
    # Direction two is always set; see build_pattern_rectangular for why.
    if y_axis is not None:
        pat_in.setDirectionTwo(
            y_axis,
            adsk.core.ValueInput.createByReal({y_count}),
            adsk.core.ValueInput.createByString({json.dumps(y_distance or "0 mm")}),
        )
    else:
        pat_in.setDirectionTwo(
            {dir_two_fallback_expr},
            adsk.core.ValueInput.createByReal(1),
            adsk.core.ValueInput.createByString("0 mm"),
        )

    feat = root.features.rectangularPatternFeatures.add(pat_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "x_count": {x_count},
        "y_count": {y_count} if {repr(y_axis)} is not None else 1,
    }}))
"""


def pattern_rectangular(
    adapter: FusionAdapter,
    feature_or_body: str,
    x_axis: str = "x",
    x_count: int = 2,
    x_distance: str | None = None,
    y_axis: str | None = None,
    y_count: int = 1,
    y_distance: str | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_pattern_rectangular(
            feature_or_body,
            x_axis,
            x_count,
            x_distance,
            y_axis,
            y_count,
            y_distance,
            name,
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "pattern_rectangular")


# ---------- pattern_circular ----------


def build_pattern_circular(
    feature_or_body: str,
    axis: str = "z",
    count: int = 6,
    total_angle: str = "360 deg",
    name: str | None = None,
) -> str:
    if count < 2:
        raise ValueError("count must be >= 2")
    if not total_angle:
        raise ValueError("total_angle required")

    axis_expr = _resolve_axis_expr(axis)
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}
def _find_feature_or_body(root, name):
    for i in range(root.features.count):
        f = root.features.item(i)
        if f.name == name: return ('feature', f)
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
    b = walk(root)
    if b is not None: return ('body', b)
    return (None, None)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    _kind, target = _find_feature_or_body(root, {json.dumps(feature_or_body)})
    if target is None:
        print(json.dumps({{"ok": False, "error": "target_not_found", "name": {json.dumps(feature_or_body)}}})); return

    axis = {axis_expr}
    if axis is None:
        print(json.dumps({{"ok": False, "error": "axis_not_found", "axis": {json.dumps(axis)}}})); return

    items = adsk.core.ObjectCollection.create()
    items.add(target)

    pat_in = root.features.circularPatternFeatures.createInput(items, axis)
    pat_in.quantity = adsk.core.ValueInput.createByReal({count})
    pat_in.totalAngle = adsk.core.ValueInput.createByString({json.dumps(total_angle)})
    feat = root.features.circularPatternFeatures.add(pat_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "count": {count},
        "total_angle": {json.dumps(total_angle)},
    }}))
"""


def pattern_circular(
    adapter: FusionAdapter,
    feature_or_body: str,
    axis: str = "z",
    count: int = 6,
    total_angle: str = "360 deg",
    name: str | None = None,
) -> Envelope:
    try:
        script = build_pattern_circular(feature_or_body, axis, count, total_angle, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "pattern_circular")


# ---------- combine ----------

COMBINE_OPS = {
    "join": "JoinFeatureOperation",
    "cut": "CutFeatureOperation",
    "intersect": "IntersectFeatureOperation",
}


def build_combine(
    target_body: str,
    tool_bodies: list[str],
    operation: str = "join",
    keep_tools: bool = False,
    name: str | None = None,
) -> str:
    if operation not in COMBINE_OPS:
        raise ValueError(f"operation must be one of {sorted(COMBINE_OPS)}, got {operation!r}")
    if not tool_bodies:
        raise ValueError("tool_bodies must be non-empty")

    op_expr = f"adsk.fusion.FeatureOperations.{COMBINE_OPS[operation]}"
    keep = "True" if keep_tools else "False"
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}
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

    target = _find_body(root, {json.dumps(target_body)})
    if target is None:
        print(json.dumps({{"ok": False, "error": "target_body_not_found", "name": {json.dumps(target_body)}}})); return

    tools = adsk.core.ObjectCollection.create()
    for nm in {json.dumps(tool_bodies)}:
        b = _find_body(root, nm)
        if b is None:
            print(json.dumps({{"ok": False, "error": "tool_body_not_found", "name": nm}})); return
        tools.add(b)

    combo_in = root.features.combineFeatures.createInput(target, tools)
    combo_in.operation = {op_expr}
    combo_in.isKeepToolBodies = {keep}
    feat = root.features.combineFeatures.add(combo_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "operation": {json.dumps(operation)},
        "keep_tools": {keep},
    }}))
"""


def combine(
    adapter: FusionAdapter,
    target_body: str,
    tool_bodies: list[str],
    operation: str = "join",
    keep_tools: bool = False,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_combine(target_body, tool_bodies, operation, keep_tools, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "combine")


# ---------- revolve ----------

REVOLVE_EXTENTS = {"angle", "full"}


def build_revolve(
    sketch: str,
    profile_index: int = 0,
    axis: str = "z",
    operation: str = "new_body",
    extent_kind: str = "full",
    angle: str | None = None,
    is_symmetric: bool = False,
    participants: list[str] | None = None,
    name: str | None = None,
) -> str:
    if operation not in OPERATION_ENUM:
        raise ValueError(f"operation must be one of {sorted(OPERATION_ENUM)}, got {operation!r}")
    if extent_kind not in REVOLVE_EXTENTS:
        raise ValueError(
            f"extent_kind must be one of {sorted(REVOLVE_EXTENTS)}, got {extent_kind!r}"
        )
    if extent_kind == "angle" and not angle:
        raise ValueError("extent_kind=angle requires angle expression")

    axis_expr = _resolve_axis_expr(axis)
    op_expr = f"adsk.fusion.FeatureOperations.{OPERATION_ENUM[operation]}"

    if extent_kind == "full":
        extent_setter = (
            "rev_in.setAngleExtent(False, adsk.core.ValueInput.createByString('360 deg'))"
        )
    else:
        sym = "True" if is_symmetric else "False"
        extent_setter = f"rev_in.setAngleExtent({sym}, adsk.core.ValueInput.createByString({json.dumps(angle)}))"

    parts_block = ""
    parts_helper = ""
    if participants:
        parts_helper = _FIND_BODY_HELPER
        parts_block = "\n".join(
            [
                "    _parts = []",
                *[
                    f"    _b = _find_body(root, {json.dumps(p)})"
                    + f"\n    if _b is None: print(json.dumps({{'ok': False, 'error': 'participant_not_found', 'name': {json.dumps(p)}}})); return"
                    + "\n    _parts.append(_b)"
                    for p in participants
                ],
                "    rev_in.participantBodies = _parts",
            ]
        )

    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}{parts_helper}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    sk = None
    for i in range(root.sketches.count):
        s = root.sketches.item(i)
        if s.name == {json.dumps(sketch)}:
            sk = s; break
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": {json.dumps(sketch)}}})); return
    if {profile_index} < 0 or {profile_index} >= sk.profiles.count:
        print(json.dumps({{"ok": False, "error": "profile_index_out_of_range",
                           "got": {profile_index}, "count": sk.profiles.count}})); return

    axis = {axis_expr}
    if axis is None:
        print(json.dumps({{"ok": False, "error": "axis_not_found", "axis": {json.dumps(axis)}}})); return

    rev_in = root.features.revolveFeatures.createInput(sk.profiles.item({profile_index}), axis, {op_expr})
    {extent_setter}
{parts_block}
    feat = root.features.revolveFeatures.add(rev_in)
{name_block}    body_names = [feat.bodies.item(i).name for i in range(feat.bodies.count)] if feat.bodies.count > 0 else []
    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "operation": {json.dumps(operation)},
        "extent_kind": {json.dumps(extent_kind)},
        "bodies_added": body_names,
    }}))
"""


def revolve(
    adapter: FusionAdapter,
    sketch: str,
    profile_index: int = 0,
    axis: str = "z",
    operation: str = "new_body",
    extent_kind: str = "full",
    angle: str | None = None,
    is_symmetric: bool = False,
    participants: list[str] | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_revolve(
            sketch,
            profile_index,
            axis,
            operation,
            extent_kind,
            angle,
            is_symmetric,
            participants,
            name,
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "revolve")


# ---------- shell ----------


def build_shell(
    body: str,
    thickness: str,
    face_normals_to_remove: list[list[float]] | None = None,
    direction: str = "inside",
    name: str | None = None,
) -> str:
    if not thickness:
        raise ValueError("thickness expression required")
    if direction not in {"inside", "outside", "both"}:
        raise ValueError(f"direction must be inside/outside/both, got {direction!r}")

    # ShellFeatureInput has no direction enum (ThicknessDirections does not
    # exist). Direction comes from which thickness property is set.
    if direction == "inside":
        thickness_setters = f"shell_in.insideThickness = adsk.core.ValueInput.createByString({json.dumps(thickness)})"
    elif direction == "outside":
        thickness_setters = f"shell_in.outsideThickness = adsk.core.ValueInput.createByString({json.dumps(thickness)})"
    else:  # both: same expression applied to each side
        thickness_setters = (
            f"shell_in.insideThickness = adsk.core.ValueInput.createByString({json.dumps(thickness)})\n"
            f"    shell_in.outsideThickness = adsk.core.ValueInput.createByString({json.dumps(thickness)})"
        )

    if face_normals_to_remove is None:
        face_normals_to_remove = []

    face_finder = ""
    if face_normals_to_remove:
        normals_str = ", ".join(f"({n[0]}, {n[1]}, {n[2]})" for n in face_normals_to_remove)
        face_finder = f"""    target_faces = adsk.core.ObjectCollection.create()
    target_normals = [{normals_str}]
    for i in range(body.faces.count):
        f = body.faces.item(i)
        ok, n = f.evaluator.getNormalAtPoint(f.pointOnFace)
        if not ok: continue
        for tn in target_normals:
            if abs(n.x - tn[0]) < 1e-3 and abs(n.y - tn[1]) < 1e-3 and abs(n.z - tn[2]) < 1e-3:
                target_faces.add(f); break
    if target_faces.count == 0:
        print(json.dumps({{'ok': False, 'error': 'no_faces_matched_normals',
                           'normals': {json.dumps(face_normals_to_remove)}}})); return
    removed_count = target_faces.count
"""
    else:
        # Closed shell: input entities must hold the body itself; ShellFeatures.add
        # rejects an empty collection.
        face_finder = (
            "    target_faces = adsk.core.ObjectCollection.create()\n"
            "    target_faces.add(body)  # no faces removed = closed (hollow) shell\n"
            "    removed_count = 0\n"
        )

    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}{_FIND_BODY_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body)}}})); return

{face_finder}
    shell_in = root.features.shellFeatures.createInput(target_faces, False)
    {thickness_setters}
    feat = root.features.shellFeatures.add(shell_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "faces_removed": removed_count,
        "thickness": {json.dumps(thickness)},
        "direction": {json.dumps(direction)},
    }}))
"""


def shell(
    adapter: FusionAdapter,
    body: str,
    thickness: str,
    face_normals_to_remove: list[list[float]] | None = None,
    direction: str = "inside",
    name: str | None = None,
) -> Envelope:
    try:
        script = build_shell(body, thickness, face_normals_to_remove, direction, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "shell")


# ---------- move_body ----------


def build_move_body(
    body: str,
    translation_mm: list[float] | None = None,
    rotation_axis: list[float] | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list[float] | None = None,
    name: str | None = None,
) -> str:
    if translation_mm is None and rotation_axis is None:
        raise ValueError(
            "must provide at least translation_mm or rotation_axis + rotation_angle_deg"
        )
    if rotation_axis is not None and rotation_angle_deg is None:
        raise ValueError("rotation_axis requires rotation_angle_deg")
    if translation_mm is not None and len(translation_mm) != 3:
        raise ValueError("translation_mm must be [tx, ty, tz] in mm")

    tx, ty, tz = (0.0, 0.0, 0.0)
    if translation_mm:
        tx, ty, tz = (v / 10.0 for v in translation_mm)

    rotation_block = ""
    if rotation_axis is not None:
        rx, ry, rz = rotation_axis
        origin = rotation_origin_mm or [0, 0, 0]
        ox, oy, oz = (v / 10.0 for v in origin)
        import math

        angle_rad = (rotation_angle_deg or 0) * math.pi / 180.0
        rotation_block = f"""
    rot = adsk.core.Matrix3D.create()
    rot.setToRotation({angle_rad}, adsk.core.Vector3D.create({rx}, {ry}, {rz}), adsk.core.Point3D.create({ox}, {oy}, {oz}))
    matrix.transformBy(rot)
"""

    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}{_FIND_BODY_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body)}}})); return

    matrix = adsk.core.Matrix3D.create()
    matrix.translation = adsk.core.Vector3D.create({tx}, {ty}, {tz})
{rotation_block}
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)

    mv_in = root.features.moveFeatures.createInput(bodies, matrix)
    feat = root.features.moveFeatures.add(mv_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "body": {json.dumps(body)},
    }}))
"""


def move_body(
    adapter: FusionAdapter,
    body: str,
    translation_mm: list[float] | None = None,
    rotation_axis: list[float] | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list[float] | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_move_body(
            body, translation_mm, rotation_axis, rotation_angle_deg, rotation_origin_mm, name
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "move_body")


# ---------- rib ----------

RIB_SIDES = {"left", "right", "symmetric"}


def build_rib(
    sketch: str,
    thickness: str,
    side: str = "symmetric",
    extend_profile: bool = True,
    name: str | None = None,
) -> str:
    if not thickness:
        raise ValueError("thickness expression required")
    if side not in RIB_SIDES:
        raise ValueError(f"side must be one of {sorted(RIB_SIDES)}, got {side!r}")
    side_enum = {
        "left": "Left",
        "right": "Right",
        "symmetric": "Symmetric",
    }[side]
    extend = "True" if extend_profile else "False"
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    return f"""\
{_emit_header()}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    sk = None
    for i in range(root.sketches.count):
        s = root.sketches.item(i)
        if s.name == {json.dumps(sketch)}:
            sk = s; break
    if sk is None:
        print(json.dumps({{"ok": False, "error": "sketch_not_found", "name": {json.dumps(sketch)}}})); return

    curves = adsk.core.ObjectCollection.create()
    for i in range(sk.sketchCurves.count):
        curves.add(sk.sketchCurves.item(i))

    rib_in = root.features.ribFeatures.createInput(
        curves,
        adsk.core.ValueInput.createByString({json.dumps(thickness)}),
        {extend},
    )
    rib_in.wallLocation = adsk.fusion.ThinExtrudeWallLocation.{side_enum}
    feat = root.features.ribFeatures.add(rib_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "thickness": {json.dumps(thickness)},
        "side": {json.dumps(side)},
    }}))
"""


def rib(
    adapter: FusionAdapter,
    sketch: str,
    thickness: str,
    side: str = "symmetric",
    extend_profile: bool = True,
    name: str | None = None,
) -> Envelope:
    # RibFeatures is read-only (item/itemByName/count, no createInput or add), so
    # ribs cannot be scripted. Return a structured error instead of crashing.
    return Envelope(
        ok=False,
        error="rib_not_scriptable",
        message=(
            "Fusion's API exposes RibFeatures as a read-only collection (no "
            "createInput/add), so rib creation is not scriptable in this Fusion "
            "version. Model the rib as a thin extrude instead: sketch a closed "
            "profile for the rib cross-section and use extrude with "
            "operation='join'."
        ),
    )


# ---------- add_hole (simple, counterbore, countersink) ----------

HOLE_KINDS = {"simple", "counterbore", "countersink"}


def build_add_hole(
    body: str,
    position_mm: list[float],
    diameter: str,
    kind: str = "simple",
    cbore_diameter: str | None = None,
    cbore_depth: str | None = None,
    csink_diameter: str | None = None,
    csink_angle: str | None = None,
    extent_kind: str = "all",
    depth_expression: str | None = None,
    name: str | None = None,
) -> str:
    if len(position_mm) != 3:
        raise ValueError("position_mm must be [x, y, z] in mm")
    if not diameter:
        raise ValueError("diameter expression required")
    if kind not in HOLE_KINDS:
        raise ValueError(f"kind must be one of {sorted(HOLE_KINDS)}, got {kind!r}")
    if extent_kind not in {"all", "distance"}:
        raise ValueError(f"extent_kind must be all or distance, got {extent_kind!r}")
    if extent_kind == "distance" and not depth_expression:
        raise ValueError("extent_kind=distance requires depth_expression")
    if kind == "counterbore" and not (cbore_diameter and cbore_depth):
        raise ValueError("kind=counterbore requires cbore_diameter + cbore_depth")
    if kind == "countersink" and not (csink_diameter and csink_angle):
        raise ValueError("kind=countersink requires csink_diameter + csink_angle")

    target_x, target_y, _target_z = position_mm
    name_block = f"    feat.name = {json.dumps(name)}\n" if name else ""

    if extent_kind == "all":
        extent_setter = "hole_in.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)"
    else:
        extent_setter = f"hole_in.setDistanceExtent(adsk.core.ValueInput.createByString({json.dumps(depth_expression)}))"

    if kind == "simple":
        input_create = (
            f"hole_in = root.features.holeFeatures.createSimpleInput("
            f"adsk.core.ValueInput.createByString({json.dumps(diameter)}))"
        )
    elif kind == "counterbore":
        input_create = (
            f"hole_in = root.features.holeFeatures.createCounterboreInput(\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(diameter)}),\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(cbore_diameter)}),\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(cbore_depth)}))"
        )
    else:  # countersink
        input_create = (
            f"hole_in = root.features.holeFeatures.createCountersinkInput(\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(diameter)}),\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(csink_diameter)}),\n"
            f"        adsk.core.ValueInput.createByString({json.dumps(csink_angle)}))"
        )

    return f"""\
{_emit_header()}{_FIND_BODY_HELPER}
P = adsk.core.Point3D.create

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    body = _find_body(root, {json.dumps(body)})
    if body is None:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": {json.dumps(body)}}})); return

    # Highest +Z face whose XY extent contains the position, falling back to the
    # tallest +Z face. Tallest-always starts holes aimed at a lower step in
    # mid-air above it.
    _tx = {target_x / 10}
    _ty = {target_y / 10}
    top_face = None
    top_z = -1e18
    containing_face = None
    containing_z = -1e18
    for i in range(body.faces.count):
        f = body.faces.item(i)
        ok, n = f.evaluator.getNormalAtPoint(f.pointOnFace)
        if not (ok and abs(n.z - 1.0) < 1e-3):
            continue
        if f.pointOnFace.z > top_z:
            top_face = f
            top_z = f.pointOnFace.z
        fb = f.boundingBox
        if (fb.minPoint.x - 1e-6 <= _tx <= fb.maxPoint.x + 1e-6
                and fb.minPoint.y - 1e-6 <= _ty <= fb.maxPoint.y + 1e-6
                and f.pointOnFace.z > containing_z):
            containing_face = f
            containing_z = f.pointOnFace.z
    position_on_face = containing_face is not None
    if containing_face is not None:
        top_face = containing_face
        top_z = containing_z
    if top_face is None:
        print(json.dumps({{"ok": False, "error": "no_top_face_found"}})); return

    helper = root.sketches.add(top_face)
    helper.name = '_hole_position_helper'
    helper.isComputeDeferred = True
    world_pt = P(_tx, _ty, top_z)
    sk_pt = helper.sketchPoints.add(helper.modelToSketchSpace(world_pt))
    helper.isComputeDeferred = False

    {input_create}
    hole_in.setPositionBySketchPoint(sk_pt)
    {extent_setter}
    feat = root.features.holeFeatures.add(hole_in)
{name_block}    print(json.dumps({{
        "ok": True,
        "feature_name": feat.name,
        "kind": {json.dumps(kind)},
        "diameter": {json.dumps(diameter)},
        "position_mm": {json.dumps(position_mm)},
        "face_plane_z_mm": round(top_z * 10, 4),
        "position_on_face": position_on_face,
    }}))
"""


def add_hole(
    adapter: FusionAdapter,
    body: str,
    position_mm: list[float],
    diameter: str,
    kind: str = "simple",
    cbore_diameter: str | None = None,
    cbore_depth: str | None = None,
    csink_diameter: str | None = None,
    csink_angle: str | None = None,
    extent_kind: str = "all",
    depth_expression: str | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_add_hole(
            body,
            position_mm,
            diameter,
            kind,
            cbore_diameter,
            cbore_depth,
            csink_diameter,
            csink_angle,
            extent_kind,
            depth_expression,
            name,
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "add_hole")


# Back-compat alias
build_add_hole_simple = build_add_hole
add_hole_simple = add_hole


# ---------- rebuild_feature ----------


def build_rebuild_feature(feature_name: str, component_name: str | None = None) -> str:
    """Rebuild a feature whose downstream references are stale (G10) by
    capturing its inputs, deleting it, and re-creating from the current sketch.

    Supported feature types: ExtrudeFeature (with Distance extent, +
    ProfilePlaneStart or OffsetStart). Most common G10 case.

    For other feature types (fillet, chamfer, hole, revolve, etc.) returns a
    structured `not_supported_for_rebuild` error with the feature class so the
    caller can fall back to: (a) suppress and let the user repair interactively
    (G11), or (b) delete + manually re-create with the appropriate tool.

    Walks root + every sub-component to find the feature. Pass component_name
    to disambiguate when the same feature name exists in multiple components.
    """
    feat_n = json.dumps(feature_name)
    cn = "None" if component_name is None else json.dumps(component_name)
    return f"""\
import adsk.core
import adsk.fusion
import json

FEATURE_NAME = {feat_n}
COMP_HINT = {cn}


def _find_feature_anywhere(comp, name):
    for i in range(comp.features.count):
        ft = comp.features.item(i)
        if ft.name == name:
            return ft, comp
    for j in range(comp.occurrences.count):
        occ = comp.occurrences.item(j)
        if occ.component is not None:
            f, c = _find_feature_anywhere(occ.component, name)
            if f is not None:
                return f, c
    return None, None


def _find_hinted(root, hint):
    if hint is None:
        return _find_feature_anywhere(root, FEATURE_NAME)
    def search(comp):
        if comp.name == hint:
            for i in range(comp.features.count):
                ft = comp.features.item(i)
                if ft.name == FEATURE_NAME:
                    return ft, comp
        for j in range(comp.occurrences.count):
            occ = comp.occurrences.item(j)
            if occ.component is not None:
                f, c = search(occ.component)
                if f is not None:
                    return f, c
        return None, None
    f, c = search(root)
    return (f, c) if f is not None else _find_feature_anywhere(root, FEATURE_NAME)


# Resolve a sketch by name. Returns (sketch, owner_component_name, ambiguity),
# where ambiguity is a list of {{"component", "sketch"}} when the name matches
# more than one sketch in scope. comp_hint None searches the whole tree; a hint
# matching 0 falls through to global.
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
    if comp_hint is not None:
        hinted = [(s, c) for s, c in _find_all_sketches(root, name) if c == comp_hint]
        if len(hinted) == 1:
            return hinted[0][0], hinted[0][1], None
        if len(hinted) > 1:
            return None, None, [{{"component": c, "sketch": s.name}} for s, c in hinted]
    all_m = _find_all_sketches(root, name)
    if len(all_m) == 0:
        return None, None, None
    if len(all_m) == 1:
        return all_m[0][0], all_m[0][1], None
    return None, None, [{{"component": c, "sketch": s.name}} for s, c in all_m]


def _capture_extrude(ft):
    # Capture ExtrudeFeature inputs for re-creation. Unhandled extents/starts set
    # unsupported_extent / unsupported_start. profile_areas is always a list so
    # recreate rebuilds N profiles uniformly; the sketch's parent component is
    # captured to disambiguate names shared across components.
    info = {{"class": "ExtrudeFeature"}}
    info["operation"] = ft.operation  # int enum
    # .profile raises InternalValidationError once the sketch curves are deleted.
    # Treat as unrebuildable so preflight preserves the original feature.
    try:
        prof = ft.profile
    except Exception as e:
        info["unsupported"] = "profile_unreadable: " + str(e)
        return info
    if hasattr(prof, "parentSketch"):
        info["sketch_name"] = prof.parentSketch.name
        try:
            info["sketch_owner_component"] = prof.parentSketch.parentComponent.name
        except Exception:
            info["sketch_owner_component"] = None
        info["profile_count"] = 1
        try:
            # areaProperties is a method; the property form returns None areas and
            # matching always falls back.
            info["profile_areas"] = [prof.areaProperties().area]
        except Exception:
            info["profile_areas"] = [None]
    else:
        # ObjectCollection of profiles
        try:
            n = prof.count
            info["profile_count"] = n
            sketches = set()
            owners = set()
            areas = []
            for k in range(n):
                p = prof.item(k)
                if hasattr(p, "parentSketch"):
                    sketches.add(p.parentSketch.name)
                    try:
                        owners.add(p.parentSketch.parentComponent.name)
                    except Exception:
                        pass
                try:
                    areas.append(p.areaProperties().area)
                except Exception:
                    areas.append(None)
            info["sketch_name"] = list(sketches)[0] if len(sketches) == 1 else None
            info["sketch_owner_component"] = list(owners)[0] if len(owners) == 1 else None
            info["profile_areas"] = areas
            if info["sketch_name"] is None:
                info["unsupported"] = "multi_sketch_profiles"
        except Exception as e:
            info["unsupported"] = f"profile_read_failed: {{e}}"
    # Extent
    try:
        ext = ft.extentOne
        ext_cls = ext.classType().split("::")[-1]
        info["extent_class"] = ext_cls
        if ext_cls == "DistanceExtentDefinition":
            info["extent_kind"] = "distance"
            info["extent_distance_expr"] = ext.distance.expression
            try:
                info["extent_is_flipped"] = bool(ext.isFlipped)
            except Exception:
                info["extent_is_flipped"] = False
        else:
            info["unsupported_extent"] = ext_cls
    except Exception as e:
        info["extent_read_error"] = str(e)
    # Start
    try:
        st = ft.startExtent
        st_cls = st.classType().split("::")[-1]
        info["start_class"] = st_cls
        if st_cls == "ProfilePlaneStartDefinition":
            info["start_kind"] = "profile_plane"
        elif st_cls == "OffsetStartDefinition":
            info["start_kind"] = "offset"
            info["start_offset_expr"] = st.offset.expression
        else:
            info["unsupported_start"] = st_cls
    except Exception as e:
        info["start_read_error"] = str(e)
    # Participant bodies (relevant for Cut/Join/Intersect)
    body_names = []
    try:
        pb = ft.participantBodies
        if pb is not None:
            for b in pb:
                body_names.append(b.name)
    except Exception:
        pass
    info["participant_body_names"] = body_names
    # Two-sided?
    try:
        info["has_extent_two"] = ft.extentTwo is not None
    except Exception:
        info["has_extent_two"] = False
    return info


def _preflight_check(captured):
    # Non-None error dict when the captured state is unrebuildable. Must run
    # before deleteMe() or a known-bad shape is deleted and never recreated.
    if "unsupported" in captured:
        return {{"error": "unsupported_profile_shape", "detail": captured["unsupported"]}}
    if "unsupported_extent" in captured:
        return {{"error": "unsupported_extent_type",
                 "extent_class": captured["unsupported_extent"]}}
    if "unsupported_start" in captured:
        return {{"error": "unsupported_start_type",
                 "start_class": captured["unsupported_start"]}}
    if captured.get("has_extent_two"):
        return {{"error": "two_sided_extrude_not_supported"}}
    if not captured.get("sketch_name"):
        return {{"error": "sketch_name_unknown"}}
    # Resolve before delete so duplicate-name ambiguity bails before the
    # original feature is destroyed.
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    sk_name = captured["sketch_name"]
    owner_hint = captured.get("sketch_owner_component")
    sk, _owner, ambig = _resolve_sketch(design.rootComponent, sk_name, owner_hint)
    if ambig is not None:
        return {{
            "error": "sketch_name_ambiguous", "name": sk_name,
            "matches": ambig,
            "hint": ("Original sketch's owner component could not be matched uniquely. "
                     "Captured owner: " + str(owner_hint)),
        }}
    if sk is None:
        return {{"error": "sketch_not_found", "name": sk_name}}
    # A resolved sketch with no closed profiles passes preflight, then fails
    # recreation after deleteMe() has destroyed the feature. Check here.
    if sk.profiles.count == 0:
        return {{"error": "sketch_has_no_profiles", "name": sk_name}}
    return None


def _recreate_extrude(comp, captured, old_name):
    # Re-create an extrude feature in `comp` from the captured input dict.
    # Returns (new_feature, error_dict). Assumes _preflight_check already ran.
    sk_name = captured["sketch_name"]
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    # Captured owner component as the hint so duplicate sketch names across
    # components still bind to the right one.
    owner_hint = captured.get("sketch_owner_component")
    sk, owner, ambig = _resolve_sketch(design.rootComponent, sk_name, owner_hint)
    if ambig is not None:
        return None, {{
            "error": "sketch_name_ambiguous", "name": sk_name,
            "matches": ambig,
            "hint": ("Original sketch's owner component could not be matched uniquely. "
                     "Captured owner: " + str(owner_hint)),
        }}
    if sk is None:
        return None, {{"error": "sketch_not_found", "name": sk_name}}
    if sk.profiles.count == 0:
        return None, {{"error": "sketch_has_no_profiles", "sketch": sk_name}}

    # Match N original profiles to N current profiles by area-closest.
    # For single-profile feature, profile_areas has 1 entry.
    target_areas = captured.get("profile_areas") or []
    matched_profiles = []
    used_indices = set()
    if target_areas:
        for ta in target_areas:
            best_idx = None
            best_diff = 1e18
            for k in range(sk.profiles.count):
                if k in used_indices:
                    continue
                try:
                    a = sk.profiles.item(k).areaProperties().area
                except Exception:
                    continue
                if ta is None:
                    diff = 0  # any profile acceptable
                else:
                    diff = abs(a - ta)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = k
            if best_idx is not None:
                matched_profiles.append(sk.profiles.item(best_idx))
                used_indices.add(best_idx)
    if not matched_profiles:
        # Fallback: pick profile 0 (single-profile case where capture failed)
        matched_profiles = [sk.profiles.item(0)]

    # Build input. createInput accepts either a single Profile or an
    # ObjectCollection of Profiles.
    ext = comp.features.extrudeFeatures
    if len(matched_profiles) == 1:
        einput = ext.createInput(matched_profiles[0], captured["operation"])
    else:
        oc = adsk.core.ObjectCollection.create()
        for p in matched_profiles:
            oc.add(p)
        einput = ext.createInput(oc, captured["operation"])

    if captured.get("start_kind") == "offset":
        offset_def = adsk.fusion.OffsetStartDefinition.create(
            adsk.core.ValueInput.createByString(captured["start_offset_expr"]))
        einput.startExtent = offset_def
    einput.setDistanceExtent(
        captured.get("extent_is_flipped", False),
        adsk.core.ValueInput.createByString(captured["extent_distance_expr"]),
    )
    pb_names = captured.get("participant_body_names") or []
    if pb_names:
        bodies = []
        for nm in pb_names:
            b = comp.bRepBodies.itemByName(nm)
            if b is not None:
                bodies.append(b)
        if bodies:
            einput.participantBodies = bodies
    new_feat = ext.add(einput)
    if old_name:
        new_feat.name = old_name
    return new_feat, None


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    ft, comp = _find_hinted(design.rootComponent, COMP_HINT)
    if ft is None:
        print(json.dumps({{"ok": False, "error": "feature_not_found", "name": FEATURE_NAME}}))
        return
    try:
        cls = ft.classType().split("::")[-1]
    except Exception:
        cls = "?"
    old_name = ft.name
    try:
        old_health = int(ft.healthState)
    except Exception:
        old_health = -1
    try:
        old_msg = ft.errorOrWarningMessage or ""
    except Exception:
        old_msg = ""

    if cls != "ExtrudeFeature":
        print(json.dumps({{
            "ok": False,
            "error": "not_supported_for_rebuild",
            "feature_class": cls,
            "feature_name": old_name,
            "component": comp.name,
            "supported": ["ExtrudeFeature"],
            "old_health": old_health,
            "recommendation": (
                "For FilletFeature/ChamferFeature: suppress instead (gotcha G11). "
                "For others: delete and re-create with the appropriate add_* tool."
            ),
        }}))
        return

    captured = _capture_extrude(ft)
    # PRE-FLIGHT: bail BEFORE destructive delete for known-unrebuildable shapes.
    preflight = _preflight_check(captured)
    if preflight is not None:
        preflight["ok"] = False
        preflight["feature_name"] = old_name
        preflight["component"] = comp.name
        preflight["captured"] = captured
        preflight["note"] = (
            "Original feature preserved. Rebuild not attempted because the captured "
            "state is not currently supported for automatic recreation."
        )
        print(json.dumps(preflight))
        return

    # Try to delete + recreate
    try:
        ft.deleteMe()
    except Exception as e:
        print(json.dumps({{
            "ok": False, "error": "delete_failed", "detail": str(e), "captured": captured,
        }}))
        return
    new_feat, err = _recreate_extrude(comp, captured, old_name)
    if err is not None:
        # Deleted but not re-created: surface clearly.
        err["ok"] = False
        err["feature_name"] = old_name
        err["captured"] = captured
        err["WARNING"] = (
            "Feature was deleted but re-creation failed. Use Fusion's undo to restore, "
            "then handle this rebuild manually."
        )
        print(json.dumps(err))
        return
    design.computeAll()
    try:
        new_health = int(new_feat.healthState)
    except Exception:
        new_health = -1
    print(json.dumps({{
        "ok": True,
        "feature_name": new_feat.name,
        "feature_class": cls,
        "component": comp.name,
        "old_health": old_health,
        "old_message": old_msg[:300],
        "new_health": new_health,
        "captured": captured,
    }}))
"""


def rebuild_feature(
    adapter: FusionAdapter,
    feature_name: str,
    component_name: str | None = None,
) -> Envelope:
    """Run rebuild_feature; returns envelope with old/new health states + the captured inputs."""
    return _ok_runner(
        adapter,
        build_rebuild_feature(feature_name, component_name),
        "rebuild_feature",
    )


__all__ = [
    "add_hole_simple",
    "build_add_hole_simple",
    "build_chamfer_edges_by_geometry",
    "build_combine",
    "build_extrude",
    "build_fillet_edges_by_geometry",
    "build_mirror_feature",
    "build_pattern_circular",
    "build_pattern_rectangular",
    "build_rebuild_feature",
    "build_revolve",
    "build_shell",
    "chamfer_edges_by_geometry",
    "combine",
    "extrude",
    "fillet_edges_by_geometry",
    "mirror_feature",
    "pattern_circular",
    "pattern_rectangular",
    "rebuild_feature",
    "revolve",
    "shell",
]
