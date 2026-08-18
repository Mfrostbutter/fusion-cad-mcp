"""FastMCP server entry point. Exposes wrapped tools over stdio.

Tool registration is split per group for readability. Each tool is a thin
shim: it calls the group module's run() function with the shared adapter,
then returns the envelope as a plain dict for FastMCP serialization.
"""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP

from .adapter import DEFAULT_URL, FusionAdapter
from .tools import assembly as asm
from .tools import construction as cons
from .tools import doc_state as doc_state_tool
from .tools import document as docs
from .tools import execute as execute_tool
from .tools import features as feat
from .tools import handle_tools as ht
from .tools import io as io_tools
from .tools import knowledge as kn
from .tools import parameters as params
from .tools import sketch as sk
from .tools import verify as verify_tools
from .tools import visualize as viz_tools

mcp = FastMCP("fusion-cad-mcp")

_adapter: FusionAdapter | None = None


def _get_adapter() -> FusionAdapter:
    global _adapter
    if _adapter is None:
        url = os.environ.get("FUSION_MCP_URL", DEFAULT_URL)
        _adapter = FusionAdapter(url=url)
    return _adapter


# ---------- Group 1: Document & State ----------


@mcp.tool()
def doc_state() -> dict:
    """Summary of the active Fusion document: design_type (parametric/direct), bodies/sketches/features count, units, dirty flag, components, parameters, timeline. On a direct design parameters_count and timeline_count come back None and are listed in result.unavailable; every other field, features_count included, is still reported."""
    return doc_state_tool.run(_get_adapter()).to_dict()


@mcp.tool()
def list_open_docs() -> dict:
    """List recently-open documents in Fusion."""
    return docs.list_open_docs(_get_adapter()).to_dict()


@mcp.tool()
def list_projects() -> dict:
    """List all projects (hubs / folders) the user can see."""
    return docs.list_projects(_get_adapter()).to_dict()


@mcp.tool()
def search_docs(query: str, project: str | None = None) -> dict:
    """Fuzzy-search documents by name. Optional project scope."""
    return docs.search_docs(_get_adapter(), query, project).to_dict()


@mcp.tool()
def open_doc(name: str, project: str | None = None) -> dict:
    """Open a document by name (fuzzy). Optional project scope."""
    return docs.open_doc(_get_adapter(), name, project).to_dict()


@mcp.tool()
def save() -> dict:
    """Save the active document. Untitled docs are refused by Fusion; use save_as instead."""
    return docs.save(_get_adapter()).to_dict()


@mcp.tool()
def save_as(path: str) -> dict:
    """Save the active document to a new path. Fusion's MCP may still require initial save via UI."""
    return docs.save_as(_get_adapter(), path).to_dict()


@mcp.tool()
def close(confirm: str = "prompt") -> dict:
    """Close the active document. confirm must be 'save', 'discard', or 'prompt'.
    Never auto-pick save vs discard for dirty docs; surface the choice to the user.
    """
    return docs.close(_get_adapter(), confirm).to_dict()


@mcp.tool()
def undo(count: int = 1) -> dict:
    """Undo the last `count` actions. WARNING: undo is atomic on the prior execute call.
    Mixed-content scripts get fully wiped. Prefer delete-loop cleanup when possible.
    """
    return docs.undo(_get_adapter(), count).to_dict()


@mcp.tool()
def redo(count: int = 1) -> dict:
    """Redo the last `count` undone actions."""
    return docs.redo(_get_adapter(), count).to_dict()


# ---------- Group 2: Sketch (parameters subset) ----------


@mcp.tool()
def add_parameters(defs: list[dict]) -> dict:
    """Add user parameters idempotently. Existing names are skipped, not overwritten.

    Each def: {name, expression, units?, comment?}.
    Reserved math names (sin/cos/pi/e/sqrt/etc) are rejected at validation time
    because Fusion will silently bind expressions to the math function.
    """
    return params.add_parameters(_get_adapter(), defs).to_dict()


@mcp.tool()
def update_parameter(name: str, expression: str) -> dict:
    """Update one user parameter's expression. Returns before/after values."""
    return params.update_parameter(_get_adapter(), name, expression).to_dict()


@mcp.tool()
def list_parameters() -> dict:
    """List all user parameters with resolved values, expressions, units, comments."""
    return params.list_parameters(_get_adapter()).to_dict()


# ---------- Group 2: Sketch geometry ----------


@mcp.tool()
def create_sketch(plane: str, name: str) -> dict:
    """Create a new sketch on a principal plane. plane in {xy, xz, yz}. name must be unique."""
    return sk.create_sketch(_get_adapter(), plane, name).to_dict()


@mcp.tool()
def add_line(sketch: str, p1: list, p2: list) -> dict:
    """Add a single line to a sketch. p1, p2 are [x, y] in mm."""
    return sk.add_line(_get_adapter(), sketch, p1, p2).to_dict()


@mcp.tool()
def add_rectangle(sketch: str, kind: str, p1: list, p2: list, p3: list | None = None) -> dict:
    """Add a rectangle to a sketch. kind in {center, corner, 3pt}. Returns line_indices for the 4 edges.
    center: p1=center point, p2=corner. corner: p1, p2 are opposite corners. 3pt: p1, p2 define one edge, p3 sets the other edge direction.
    """
    return sk.add_rectangle(_get_adapter(), sketch, kind, p1, p2, p3).to_dict()


@mcp.tool()
def add_circle(
    sketch: str,
    kind: str,
    center: list | None = None,
    radius_mm: float | None = None,
    p1: list | None = None,
    p2: list | None = None,
    p3: list | None = None,
) -> dict:
    """Add a circle. kind=center_radius needs center+radius_mm. kind=3pt needs p1+p2+p3.
    Returns circle_index for later reference."""
    kw = {
        k: v
        for k, v in {"center": center, "radius_mm": radius_mm, "p1": p1, "p2": p2, "p3": p3}.items()
        if v is not None
    }
    return sk.add_circle(_get_adapter(), sketch, kind, **kw).to_dict()


@mcp.tool()
def add_polygon(
    sketch: str, sides: int, center: list, vertex: list, inscribed: bool = True
) -> dict:
    """Add a regular polygon. sides >= 3. Inscribed (default) means vertices lie on the radius."""
    return sk.add_polygon(_get_adapter(), sketch, sides, center, vertex, inscribed).to_dict()


@mcp.tool()
def add_geometric_constraint(sketch: str, kind: str, entities: list) -> dict:
    """Apply a geometric constraint. kind in {horizontal, vertical, parallel, perpendicular, coincident,
    tangent, equal, concentric, fix, midpoint, symmetric}. entities is a list of entity refs like
    'line:0', 'line:0:start', 'circle:1:center', or 'origin'."""
    return sk.add_geometric_constraint(_get_adapter(), sketch, kind, entities).to_dict()


@mcp.tool()
def add_dimension(
    sketch: str, kind: str, entities: list, expression: str, text_pos: list | None = None
) -> dict:
    """Add a dimension with an expression. kind in {distance_h, distance_v, distance, angle, radial, diameter}.
    Parameter-name expressions ('body_width', 'length / 2') work AND propagate when the param changes
    (gotchas.md G9, verified 2026-05-31). Use literal mm only when you want a baked value.

    entities depends on kind:
      distance_h / distance_v / distance: 2 point refs (e.g. ['line:0:start', 'line:0:end'])
      angle: 2 line refs
      radial / diameter: 1 circle or arc ref
    """
    return sk.add_dimension(_get_adapter(), sketch, kind, entities, expression, text_pos).to_dict()


@mcp.tool()
def assert_profiles(sketch: str, expected: int) -> dict:
    """Check that the sketch has the expected number of closed profiles. Returns ok=False if not.
    Use after building a sketch to catch self-intersecting polygons (which return profiles=2 silently)."""
    return sk.assert_profiles(_get_adapter(), sketch, expected).to_dict()


@mcp.tool()
def probe_sketch_dimensions(sketch: str, component_name: str | None = None) -> dict:
    """Dump every dimension in a sketch with parameter name, expression, value, and
    entity-attachment coordinates.

    Use this to identify which literal-named dim (e.g. `d278`) controls which
    geometric feature when sketches use baked-in numbers. Walks root + every
    sub-component to find the sketch; pass component_name for disambiguation
    when the same sketch name exists in multiple components.

    Per-dim payload: dim_class, param_name, expression, value_mm, unit,
    entity_one, entity_two. Entity descriptors include point/start/end/center
    coords in mm so you can match dims to specific lines/circles/ellipses.
    """
    return sk.probe_sketch_dimensions(_get_adapter(), sketch, component_name).to_dict()


@mcp.tool()
def edit_sketch_dimension(
    sketch: str,
    dim_name: str,
    new_expression: str,
    component_name: str | None = None,
) -> dict:
    """Change a sketch dimension's expression by parameter name (e.g. `d278`).

    Triggers design.computeAll() before returning. After calling this, run
    `audit_feature_health` to check whether the edit broke any downstream
    features (very common for fillets when their target edges move; see G11).

    On dim_not_found, the response includes the available dimensions in the
    sketch so the agent can correct course without another tool call.

    Args:
        sketch: Sketch name (will search root + every sub-component).
        dim_name: Parameter name of the dimension (use `probe_sketch_dimensions`
            to find these).
        new_expression: New expression as a string. Can be a numeric literal
            ("20 mm"), a user param reference ("oval_x"), or an expression
            ("oval_x / 2 + 1 mm"). Units required if not a bare expression.
        component_name: Optional disambiguation when the sketch name exists in
            multiple components.
    """
    return sk.edit_sketch_dimension(
        _get_adapter(), sketch, dim_name, new_expression, component_name
    ).to_dict()


@mcp.tool()
def add_ellipse(sketch: str, center: list, major_axis_end: list, minor_axis_end: list) -> dict:
    """Add an ellipse defined by center + major-axis endpoint + minor-axis endpoint. All in mm."""
    return sk.add_ellipse(_get_adapter(), sketch, center, major_axis_end, minor_axis_end).to_dict()


@mcp.tool()
def add_arc(
    sketch: str,
    kind: str,
    p1: list | None = None,
    p2: list | None = None,
    p3: list | None = None,
    center: list | None = None,
    start: list | None = None,
    end: list | None = None,
    sweep_radians: float | None = None,
) -> dict:
    """Add an arc. kind in {3pt, center_start_end, center_start_sweep}.
    3pt: p1, p2, p3.
    center_start_end: center, start, end.
    center_start_sweep: center, start, sweep_radians (positive = CCW).
    """
    kw = {
        k: v
        for k, v in {
            "p1": p1,
            "p2": p2,
            "p3": p3,
            "center": center,
            "start": start,
            "end": end,
            "sweep_radians": sweep_radians,
        }.items()
        if v is not None
    }
    return sk.add_arc(_get_adapter(), sketch, kind, **kw).to_dict()


@mcp.tool()
def add_spline(sketch: str, points: list, closed: bool = False) -> dict:
    """Add a fitted spline through a list of [x, y] points (mm). Optionally closed."""
    return sk.add_spline(_get_adapter(), sketch, points, closed).to_dict()


# ---------- Group 3: Features ----------


@mcp.tool()
def extrude(
    sketch: str,
    profile_index: int = 0,
    operation: str = "new_body",
    extent_kind: str = "distance",
    expression: str | None = None,
    direction: str = "positive",
    is_full_length: bool = True,
    participants: list[str] | None = None,
    name: str | None = None,
) -> dict:
    """Extrude a sketch profile into a feature.
    operation: new_body | join | cut | intersect | new_component
    extent_kind: distance (needs expression) | symmetric (needs expression) | all_positive | all_negative
    direction: positive | negative (for distance kind)
    participants: body names to operate on (for cut/join/intersect)
    Returns feature_name + bodies_added.
    """
    return feat.extrude(
        _get_adapter(),
        sketch,
        profile_index,
        operation,
        extent_kind,
        expression,
        direction,
        is_full_length,
        participants,
        name,
    ).to_dict()


@mcp.tool()
def fillet_edges_by_geometry(
    body: str,
    radius: str,
    parallel_to: str = "z",
    min_length_mm: float | None = None,
    is_tangent_chain: bool = True,
    name: str | None = None,
) -> dict:
    """Fillet edges of a body by geometric filter (no UI selection needed).
    parallel_to: x | y | z | any — only edges parallel to that axis (or all).
    radius: expression like 'corner_r' or '8 mm'.
    min_length_mm: optional minimum edge length filter (skips tiny rounding edges).
    """
    return feat.fillet_edges_by_geometry(
        _get_adapter(),
        body,
        radius,
        parallel_to,
        min_length_mm,
        is_tangent_chain,
        name,
    ).to_dict()


@mcp.tool()
def chamfer_edges_by_geometry(
    body: str,
    distance: str,
    parallel_to: str = "z",
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    min_length_mm: float | None = None,
    name: str | None = None,
) -> dict:
    """Chamfer edges of a body by geometric filter.
    kind: equal (one distance) | two_dist (needs distance2) | dist_angle (needs angle).
    """
    return feat.chamfer_edges_by_geometry(
        _get_adapter(),
        body,
        distance,
        parallel_to,
        kind,
        distance2,
        angle,
        min_length_mm,
        name,
    ).to_dict()


@mcp.tool()
def mirror_feature(feature_or_body: str, plane: str, name: str | None = None) -> dict:
    """Mirror a feature or body across a plane. plane: xy | xz | yz | <construction_plane_name>."""
    return feat.mirror_feature(_get_adapter(), feature_or_body, plane, name).to_dict()


@mcp.tool()
def pattern_rectangular(
    feature_or_body: str,
    x_axis: str = "x",
    x_count: int = 2,
    x_distance: str | None = None,
    y_axis: str | None = None,
    y_count: int = 1,
    y_distance: str | None = None,
    name: str | None = None,
) -> dict:
    """Rectangular pattern. x_axis / y_axis: x | y | z | <construction_axis_name>.
    x_distance / y_distance: total-extent expressions like '40 mm' or '4 * pitch'.
    """
    return feat.pattern_rectangular(
        _get_adapter(),
        feature_or_body,
        x_axis,
        x_count,
        x_distance,
        y_axis,
        y_count,
        y_distance,
        name,
    ).to_dict()


@mcp.tool()
def pattern_circular(
    feature_or_body: str,
    axis: str = "z",
    count: int = 6,
    total_angle: str = "360 deg",
    name: str | None = None,
) -> dict:
    """Circular pattern around an axis. axis: x | y | z | <construction_axis_name>."""
    return feat.pattern_circular(
        _get_adapter(),
        feature_or_body,
        axis,
        count,
        total_angle,
        name,
    ).to_dict()


@mcp.tool()
def combine(
    target_body: str,
    tool_bodies: list[str],
    operation: str = "join",
    keep_tools: bool = False,
    name: str | None = None,
) -> dict:
    """Boolean combine. operation: join | cut | intersect. keep_tools: preserve tool bodies after op."""
    return feat.combine(
        _get_adapter(),
        target_body,
        tool_bodies,
        operation,
        keep_tools,
        name,
    ).to_dict()


@mcp.tool()
def revolve(
    sketch: str,
    profile_index: int = 0,
    axis: str = "z",
    operation: str = "new_body",
    extent_kind: str = "full",
    angle: str | None = None,
    is_symmetric: bool = False,
    participants: list[str] | None = None,
    name: str | None = None,
) -> dict:
    """Revolve a sketch profile around an axis.
    axis: x | y | z | <construction_axis_name>
    extent_kind: full (360deg) | angle (needs angle expr)
    operation: new_body | join | cut | intersect | new_component
    """
    return feat.revolve(
        _get_adapter(),
        sketch,
        profile_index,
        axis,
        operation,
        extent_kind,
        angle,
        is_symmetric,
        participants,
        name,
    ).to_dict()


@mcp.tool()
def shell(
    body: str,
    thickness: str,
    face_normals_to_remove: list | None = None,
    direction: str = "inside",
    name: str | None = None,
) -> dict:
    """Hollow out a body. face_normals_to_remove is a list of [nx, ny, nz] for faces to remove
    (e.g. [[0, 0, 1]] removes the top face). Empty / omitted = closed shell.
    direction: inside | outside | both.
    """
    return feat.shell(
        _get_adapter(),
        body,
        thickness,
        face_normals_to_remove,
        direction,
        name,
    ).to_dict()


@mcp.tool()
def add_hole(
    body: str,
    position_mm: list,
    diameter: str,
    kind: str = "simple",
    cbore_diameter: str | None = None,
    cbore_depth: str | None = None,
    csink_diameter: str | None = None,
    csink_angle: str | None = None,
    extent_kind: str = "all",
    depth_expression: str | None = None,
    name: str | None = None,
) -> dict:
    """Add a hole on the body's top face (max-Z, +Z normal).
    kind: simple | counterbore (needs cbore_diameter + cbore_depth) | countersink (needs csink_diameter + csink_angle).
    position_mm: [x, y, z] — x/y locate on the top face; z is informational.
    extent_kind: all | distance (needs depth_expression).
    """
    return feat.add_hole(
        _get_adapter(),
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
    ).to_dict()


@mcp.tool()
def rebuild_feature(feature_name: str, component_name: str | None = None) -> dict:
    """Rebuild a feature whose downstream references are stale (G10) by
    capturing its inputs, deleting it, and re-creating from the current sketch.

    Supported feature classes: ExtrudeFeature (DistanceExtent, ProfilePlaneStart
    or OffsetStart, 1 or N profiles in the same sketch). This is the most
    common G10 case — a feature that got `healthState=1 (warning, using cached
    geometry)` after a sketch geometry rewrite.

    Returns structured `not_supported_for_rebuild` error for other feature
    classes (fillet, chamfer, hole, revolve, etc.) with a recommendation:
    - FilletFeature/ChamferFeature broken by upstream edits: SUPPRESS instead
      (gotcha G11; edge re-binding is design-specific geometric matching).
    - Others: delete + re-create via the appropriate add_* tool.

    Profile matching: when the original sketch has more than one profile, picks
    the new profile whose area is closest to the captured original area. Falls
    back to profile[0] if no area was captured.

    Failure mode warning: if delete succeeds but recreate fails (e.g., sketch
    name changed, multiple profiles spread across sketches), the response sets
    ok=false and includes a WARNING field instructing the agent to undo via
    Fusion's undo and try again manually.

    Args:
        feature_name: Name of the feature to rebuild. Walks root + every
            sub-component.
        component_name: Optional hint for disambiguation.

    Chain pattern: edit_sketch_dimension -> audit_feature_health -> for each
    broken extrude in features list, rebuild_feature -> audit_feature_health.
    """
    return feat.rebuild_feature(_get_adapter(), feature_name, component_name).to_dict()


@mcp.tool()
def move_body(
    body: str,
    translation_mm: list | None = None,
    rotation_axis: list | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list | None = None,
    name: str | None = None,
) -> dict:
    """Move a body via a Move feature (parametric in the timeline).
    Provide translation_mm (mm) and/or rotation (axis + angle_deg).
    """
    return feat.move_body(
        _get_adapter(),
        body,
        translation_mm,
        rotation_axis,
        rotation_angle_deg,
        rotation_origin_mm,
        name,
    ).to_dict()


@mcp.tool()
def rib(
    sketch: str,
    thickness: str,
    side: str = "symmetric",
    extend_profile: bool = True,
    name: str | None = None,
) -> dict:
    """NOT SCRIPTABLE in the current Fusion API: RibFeatures is a read-only
    collection (no createInput/add), so this always returns the structured
    error `rib_not_scriptable`. Model ribs as thin join-extrudes instead.
    """
    return feat.rib(_get_adapter(), sketch, thickness, side, extend_profile, name).to_dict()


# ---------- Group 5: Assembly & Motion (first slice, no joints) ----------


@mcp.tool()
def bodies_to_components(mapping: dict) -> dict:
    """Convert root-level bodies into named components, preserving world position.
    mapping is {body_name: new_component_name}. Multi-body designs need this before
    joint/motion work — Fusion's joints operate on components, not bodies.
    """
    return asm.bodies_to_components(_get_adapter(), mapping).to_dict()


@mcp.tool()
def move_component(
    name: str,
    translation_mm: list | None = None,
    rotation_axis: list | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list | None = None,
) -> dict:
    """Move an occurrence by translation (mm) and/or rotation (axis + angle deg).
    rotation_origin_mm defaults to [0, 0, 0] (world origin) if omitted.
    Breaks the occurrence's ground-to-parent flag if set (otherwise the move
    silently reverts). Check `moved` and `after_translation_mm` in the
    response; a joint solver can override the requested move.
    """
    return asm.move_component(
        _get_adapter(),
        name,
        translation_mm,
        rotation_axis,
        rotation_angle_deg,
        rotation_origin_mm,
    ).to_dict()


@mcp.tool()
def ground_component(name: str) -> dict:
    """Set the ground flag on an occurrence (lock its world position)."""
    return asm.ground_component(_get_adapter(), name).to_dict()


@mcp.tool()
def unground_component(name: str) -> dict:
    """Clear the ground flag on an occurrence."""
    return asm.unground_component(_get_adapter(), name).to_dict()


@mcp.tool()
def create_rigid_group(component_names: list, name: str | None = None) -> dict:
    """Lock 2+ components together as a rigid group (they move as one)."""
    return asm.create_rigid_group(_get_adapter(), component_names, name).to_dict()


@mcp.tool()
def create_contact_set(body_names: list) -> dict:
    """Create a contact set for physics / motion analysis between 2+ bodies."""
    return asm.create_contact_set(_get_adapter(), body_names).to_dict()


@mcp.tool()
def interference_check(entity_names: list) -> dict:
    """Run an interference analysis on 2+ bodies or occurrences.
    Returns per-pair interference volume in mm^3. Empty pair list = no interference.
    """
    return asm.interference_check(_get_adapter(), entity_names).to_dict()


@mcp.tool()
def set_joint_limits(
    joint_name: str,
    min_value: str | None = None,
    max_value: str | None = None,
    rest_value: str | None = None,
) -> dict:
    """Set min/max/rest values on an existing joint by name.
    Values are expressions: angles for revolute (e.g. '45 deg'), distances for slider.
    rest_value is the NEW May 2026 snap-back position. Pass None to leave any field unset.
    Limits bind to rotationLimits when the motion has one, else slideLimits
    (cylindrical joints get rotation limits). The response echoes back what
    Fusion actually stored under `applied` (internal units: radians / cm).
    """
    return asm.set_joint_limits(
        _get_adapter(), joint_name, min_value, max_value, rest_value
    ).to_dict()


@mcp.tool()
def drive_joint(joint_name: str, value: str) -> dict:
    """Drive an existing joint to a target value.
    value is an expression: angle for revolute, distance for slider, etc.
    Tries jointMotion attributes in order: rotation, slide, roll, pitch, yaw.
    Fusion silently ignores drives beyond the joint's limits; check `applied`
    in the response (false = the joint stayed where it was).
    """
    return asm.drive_joint(_get_adapter(), joint_name, value).to_dict()


@mcp.tool()
def create_joint(
    geometry_one: str,
    geometry_two: str,
    motion_type: str = "rigid",
    axis: str = "z",
    offset_mm: str | None = None,
    angle_deg: str | None = None,
    name: str | None = None,
) -> dict:
    """Create a Joint between two entity-handle origins.

    Joint origins are specified as entity handles (kind:path:token). Supported
    kinds: face (planar OR cylindrical/conical), edge (uses MiddleKeyPoint),
    vertex (uses Point), point (sketch point). Get handles from
    list_body_entities for face/edge/vertex, or use the sketch tools' returned
    handles for sketch points.

    motion_type: one of rigid, revolute, slider, cylindrical, ball.
    - rigid: locks the two origins; no DOF
    - revolute: 1 DOF rotation about `axis` (use for hinges)
    - slider: 1 DOF translation along `axis`
    - cylindrical: rotation + translation along `axis`
    - ball: 3 DOF rotation (axis arg ignored; Fusion only accepts pitch=Z,
      yaw=X, which is what gets used)

    axis: x | y | z, relative to the first joint geometry's local frame.
    For typical face-normal rotation (hinge pin coming out of the face) use z.

    offset_mm: optional ValueInput expression for lateral offset between the
    two geometries. A snap hinge typically needs a few mm here to hold the gap
    between mating flanges.
    Preserved across user-param changes (unlike Move-based positioning).

    angle_deg: optional initial angle (revolute / cylindrical).

    name: optional joint name in the timeline.

    Returns {ok, joint_name, joint_token, motion_type, axis, offset_mm, angle_deg}.
    Use joint_name for downstream drive_joint / set_joint_limits calls.

    Errors:
    - handle_invalid: one of the geometry handles could not be resolved.
    - joint_geometry_failed: face/edge/vertex/point handle resolved but Fusion
      could not build a JointGeometry from it (e.g. degenerate face).
    - joints_add_failed: joint inputs were valid but Fusion refused the joint
      (usually means the two geometries are mateable only with a different
      motion type, or one geometry is in a frozen component).
    """
    return asm.create_joint(
        _get_adapter(),
        geometry_one,
        geometry_two,
        motion_type,
        axis,
        offset_mm,
        angle_deg,
        name,
    ).to_dict()


# ---------- Group 4: Construction Geometry ----------


@mcp.tool()
def create_construction_plane(
    kind: str,
    name: str | None = None,
    base_plane: str | None = None,
    offset: str | None = None,
    plane_a: str | None = None,
    plane_b: str | None = None,
    axis: str | None = None,
    angle: str | None = None,
    p1: list | None = None,
    p2: list | None = None,
    p3: list | None = None,
) -> dict:
    """Create a construction plane. kind in {offset, midplane, at_angle, 3_points}.
    offset: base_plane + offset expr (e.g. 'thickness')
    midplane: plane_a + plane_b (between two existing planes)
    at_angle: axis + base_plane + angle expr (e.g. '30 deg')
    3_points: p1, p2, p3 each as [x, y, z] in mm
    Plane / axis names default to principals: 'xy', 'xz', 'yz' / 'x', 'y', 'z'.
    """
    kw = {
        k: v
        for k, v in {
            "base_plane": base_plane,
            "offset": offset,
            "plane_a": plane_a,
            "plane_b": plane_b,
            "axis": axis,
            "angle": angle,
            "p1": p1,
            "p2": p2,
            "p3": p3,
        }.items()
        if v is not None
    }
    return cons.create_construction_plane(_get_adapter(), kind, name, **kw).to_dict()


@mcp.tool()
def create_construction_axis(
    kind: str,
    name: str | None = None,
    p1: list | None = None,
    p2: list | None = None,
    body: str | None = None,
    face_normal: list | None = None,
) -> dict:
    """Create a construction axis. kind in {2_points, normal_to_face_by_geometry}.
    2_points: p1, p2 each as [x, y, z] in mm
    normal_to_face_by_geometry: body name + face_normal [nx, ny, nz] (finds the face whose normal matches)
    """
    kw = {
        k: v
        for k, v in {
            "p1": p1,
            "p2": p2,
            "body": body,
            "face_normal": face_normal,
        }.items()
        if v is not None
    }
    return cons.create_construction_axis(_get_adapter(), kind, name, **kw).to_dict()


@mcp.tool()
def create_construction_point(coords: list, name: str | None = None) -> dict:
    """Create a construction point at explicit [x, y, z] coordinates (mm)."""
    return cons.create_construction_point(_get_adapter(), coords, name).to_dict()


@mcp.tool()
def delete_construction(name: str) -> dict:
    """Delete a construction plane / axis / point by name."""
    return cons.delete_construction(_get_adapter(), name).to_dict()


# ---------- Group 5 / 6 / 2 / 3: Handle-consuming tools ----------


@mcp.tool()
def list_body_entities(
    body: str,
    kinds: list | None = None,
    face_normal_filter: list | None = None,
    edge_parallel_to: str | None = None,
    min_edge_length_mm: float | None = None,
) -> dict:
    """Enumerate faces / edges / vertices of a body and return their handles.
    This is the bridge between name-addressing (bodies) and handle-addressing (sub-entities).

    kinds: subset of [face, edge, vertex]. Defaults to all three.
    face_normal_filter: [nx, ny, nz] — only faces matching that normal (e.g. [0, 0, 1] for top).
    edge_parallel_to: x | y | z — only axis-parallel edges.
    min_edge_length_mm: filter out short edges (typical use: skip fillet runouts).

    Returns face/edge/vertex lists, each with handle, index, and geometric info.
    Use the returned handles in measure, fillet_edges, chamfer_edges, project_to_sketch, etc.
    """
    return ht.list_body_entities(
        _get_adapter(),
        body,
        kinds,
        face_normal_filter,
        edge_parallel_to,
        min_edge_length_mm,
    ).to_dict()


@mcp.tool()
def measure(entity_a: str, entity_b: str, kind: str = "distance") -> dict:
    """Measure between two entities using their handles (from list_body_entities or tool returns).
    kind: distance (min distance + nearest points) | min_distance (value only) | angle.
    """
    return ht.measure(_get_adapter(), entity_a, entity_b, kind).to_dict()


@mcp.tool()
def find_mesh_using_ray(
    origin_mm: list,
    direction: list,
    component_name: str | None = None,
) -> dict:
    """NEW May 2026: cast a ray and return MeshBody objects intersected.
    origin_mm: ray origin [x, y, z] in mm.
    direction: ray direction [dx, dy, dz] (any magnitude; will be normalized by Fusion).
    component_name: optional component to scope the search; omit for whole root.
    """
    return ht.find_mesh_using_ray(_get_adapter(), origin_mm, direction, component_name).to_dict()


@mcp.tool()
def ray_collision_with_mesh(
    mesh_handle: str,
    origin_mm: list,
    direction: list,
) -> dict:
    """NEW May 2026: cast a ray against ONE MeshBody, return all intersection points.
    mesh_handle: handle of a mesh body (e.g. from find_mesh_using_ray or list_body_entities).
    """
    return ht.ray_collision_with_mesh(_get_adapter(), mesh_handle, origin_mm, direction).to_dict()


@mcp.tool()
def fillet_edges(
    edge_handles: list, radius: str, is_tangent_chain: bool = True, name: str | None = None
) -> dict:
    """Fillet specific edges by handle (UI-selection style).
    edge_handles: list from list_body_entities (kinds=['edge']).
    radius: expression like 'corner_r' or '8 mm'.
    """
    return ht.fillet_edges(_get_adapter(), edge_handles, radius, is_tangent_chain, name).to_dict()


@mcp.tool()
def chamfer_edges(
    edge_handles: list,
    distance: str,
    kind: str = "equal",
    distance2: str | None = None,
    angle: str | None = None,
    name: str | None = None,
) -> dict:
    """Chamfer specific edges by handle.
    kind: equal | two_dist (needs distance2) | dist_angle (needs angle).
    """
    return ht.chamfer_edges(
        _get_adapter(), edge_handles, distance, kind, distance2, angle, name
    ).to_dict()


@mcp.tool()
def project_to_sketch(sketch: str, entity_handles: list) -> dict:
    """Project entities (by handle) onto a named sketch. Useful for cut-extrudes that reference body geometry."""
    return ht.project_to_sketch(_get_adapter(), sketch, entity_handles).to_dict()


# ---------- Group 6: Verify & Visualize ----------


@mcp.tool()
def bounding_box(body_name: str | None = None) -> dict:
    """Return mm bbox + extents for a body (by name) or all bodies if name omitted.
    Walks root + every occurrence.
    """
    return verify_tools.bounding_box(_get_adapter(), body_name).to_dict()


@mcp.tool()
def volume(body_name: str | None = None) -> dict:
    """Return volume in cm^3 and mm^3 for a body (by name) or all bodies if name omitted."""
    return verify_tools.volume(_get_adapter(), body_name).to_dict()


@mcp.tool()
def mass(body_name: str | None = None) -> dict:
    """Return mass (kg), material name, density, and volume for a body or all bodies.
    Material is whatever the body has been assigned; uses Fusion's physical-properties calc.
    """
    return verify_tools.mass(_get_adapter(), body_name).to_dict()


@mcp.tool()
def center_of_mass(body_name: str | None = None) -> dict:
    """Return center of mass in mm world coordinates for a body or all bodies."""
    return verify_tools.center_of_mass(_get_adapter(), body_name).to_dict()


@mcp.tool()
def audit_feature_health(
    component_name: str | None = None,
    include_healthy: bool = False,
) -> dict:
    """Sweep the feature tree (root + every sub-component) and report features
    whose healthState != 0.

    Call this after ANY tool that edits sketch geometry, user parameters, or
    features. If summary.failed > 0 (state 2 or 3) or summary.warning > 0
    (state 1), the BREP may look healthy via the API while Fusion's UI shows
    a stale cached display. See gotchas G10/G11.

    Args:
        component_name: Restrict the audit to features in this component
            (still recurses into its sub-components). Default: root + all.
        include_healthy: Include healthy features (state 0) in the features
            list. Default False — only broken features are returned.

    Returns envelope.result = {
        ok, summary: {total, healthy, warning, failed},
        features: [{path, component, name, classType, healthState, healthLabel,
                    isSuppressed, errorOrWarningMessage}, ...]
    }
    """
    return verify_tools.audit_feature_health(
        _get_adapter(), component_name, include_healthy
    ).to_dict()


@mcp.tool()
def screenshot(
    direction: str = "iso-top-right",
    width: int | None = None,
    height: int | None = None,
    transparent: bool = True,
    anti_aliasing: bool = True,
) -> dict:
    """Capture a PNG screenshot of the active viewport. Returns base64 image in envelope.image.
    direction: one of current, front, back, bottom, top, left, right, iso-* (4 variants).
    Fusion handles fit-view internally for named directions.
    """
    return viz_tools.screenshot(
        _get_adapter(), direction, width, height, transparent, anti_aliasing
    ).to_dict()


@mcp.tool()
def set_view(direction: str = "iso-top-right", fit: bool = True) -> dict:
    """Orient the viewport to a named direction. Optionally fit to view.
    Use when you want to change camera without capturing a screenshot.
    """
    return viz_tools.set_view(_get_adapter(), direction, fit).to_dict()


@mcp.tool()
def screenshot_compare_with_marker(
    before_marker_position: int,
    direction: str = "iso-top-right",
    width: int | None = None,
    height: int | None = None,
    transparent: bool = True,
    anti_aliasing: bool = True,
) -> dict:
    """Capture before/after screenshots from the same camera by rolling the
    timeline marker to `before_marker_position`, screenshotting, restoring
    the original marker position, and screenshotting again.

    Use this to give yourself or the user a clean visual diff of a change you
    just made — much more convincing than describing the change in words when
    the geometric delta is subtle. Same camera both shots so the comparison
    is honest.

    Restore semantics: if anything fails after the marker is moved, this tool
    attempts to roll back to the original position before returning. The
    `restore_marker_failed` error indicates the rollback itself failed — in
    that case the design may be left at an intermediate marker position and
    the user should manually drag the marker back.

    Args:
        before_marker_position: Timeline marker position to capture as the
            "before" state. Must be in [0, timeline.count]. Use 0 for the
            initial empty state, or the index just before a specific feature.
        direction: One of: current, front, back, bottom, top, left, right,
            iso-bottom-left/right, iso-top-left/right. Defaults to iso-top-right.
        width, height: Optional image dimensions in pixels.
        transparent: PNG transparency. Default True.
        anti_aliasing: Smooth edges. Default True.

    Returns envelope.result = {
        before_image: {data: <base64 PNG>, mime_type: "image/png"},
        after_image:  {data: <base64 PNG>, mime_type: "image/png"},
        before_marker, after_marker, direction
    }
    """
    return viz_tools.screenshot_compare_with_marker(
        _get_adapter(),
        before_marker_position,
        direction,
        width,
        height,
        transparent,
        anti_aliasing,
    ).to_dict()


# ---------- Group 7: IO & Knowledge ----------


@mcp.tool()
def find_api(
    query: str,
    kind: str | None = None,
    namespace: str | None = None,
    limit: int = 5,
) -> dict:
    """Search the local Fusion API help corpus.

    Returns top-N matches as {slug, title, namespace, kind, url, is_preview, introduced, snippet}.
    Use this BEFORE writing a script that touches an unfamiliar method or class.

    Filters:
      kind: 'object' | 'member' | 'manual' | etc — restrict to one page type
      namespace: substring match on namespace (e.g. 'Fusion', 'CAM', 'core')
    """
    return kn.find_api(query, kind=kind, namespace=namespace, limit=limit).to_dict()


@mcp.tool()
def find_pattern(query: str, limit: int = 5) -> dict:
    """Search patterns.md (verified Fusion MCP patterns and helpers) by intent.

    Use when looking for the canonical idiom for a common operation (constrained
    rectangle, fillet by geometry, screenshot fit-view, etc).
    """
    return kn.find_pattern(query, limit).to_dict()


@mcp.tool()
def find_tool(query: str, limit: int = 5) -> dict:
    """Search this server's own tool reference (tools.md) by intent or symptom.

    Returns the matching sections: signatures, exact enum values, return keys,
    and error codes. Use this to look up how to call a tool instead of guessing
    at arguments, and to check what an error code means.

    Works with Fusion closed.
    """
    return kn.find_tool(query, limit).to_dict()


@mcp.tool()
def find_gotcha(query: str, limit: int = 5) -> dict:
    """Search gotchas.md (known failure modes) by symptom or keyword.

    Use when something behaves unexpectedly: check here for the documented cause
    + fix before debugging from scratch.
    """
    return kn.find_gotcha(query, limit).to_dict()


@mcp.tool()
def export(
    format: str,
    path: str,
    body: str | None = None,
    refinement: str = "medium",
    units: str = "mm",
) -> dict:
    """Export geometry to a file. format in {stl, 3mf, step, iges, obj, f3d, sat, smt}.
    path: absolute path (relative + '..' + Windows reserved names rejected).
    body: optional body name. If omitted, exports the whole root component.
          STEP/IGES/SAT/SMT/F3D always export the whole design (ignore body).
    refinement: low | medium | high — applies to STL and OBJ mesh quality.
    units: mm | cm | m | inch — STL/OBJ only.
    """
    return io_tools.export(_get_adapter(), format, path, body, refinement, units).to_dict()


@mcp.tool()
def import_geometry(format: str, path: str) -> dict:
    """Import geometry from a file into the active design.
    format in {step, iges, sat, smt, f3d}.
    path: absolute path to an existing file.
    Returns counts of bodies and occurrences added to the root component.
    """
    return io_tools.import_geometry(_get_adapter(), format, path).to_dict()


# ---------- Escape hatch ----------


@mcp.tool()
def execute(script: str) -> dict:
    """Raw Python passthrough. The script must define `def run(_ctx):` as entry point.
    Use print() for any data to return; stdout becomes the response message.
    """
    return execute_tool.run(_get_adapter(), script).to_dict()


_USAGE = """\
fusion-cad-mcp - MCP server for driving Autodesk Fusion

Usage:
  fusion-cad-mcp                    Run the MCP server on stdio (default)
  fusion-cad-mcp corpus build       Build the local Fusion API help corpus
                                    that find_api searches. Needs
                                    --i-accept-autodesk-terms; see
                                    `corpus build --help` for options.

The corpus is Autodesk content and is never redistributed, so each user builds
their own local cache. Everything else works without it.
"""


def main() -> None:
    """Entry point installed by pyproject as `fusion-cad-mcp`.

    Bare invocation runs the MCP server, which is what an MCP client expects.
    Subcommands are handled before that, since an MCP client never passes any.
    """
    argv = sys.argv[1:]

    if argv and argv[0] == "corpus":
        from .corpus import build

        if len(argv) < 2 or argv[1] != "build":
            print("Usage: fusion-cad-mcp corpus build [options]", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(build(argv[2:]))

    if argv and argv[0] in {"-h", "--help", "help"}:
        print(_USAGE)
        raise SystemExit(0)

    if argv:
        print(f"Unknown argument: {argv[0]}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)

    mcp.run()


if __name__ == "__main__":
    main()
