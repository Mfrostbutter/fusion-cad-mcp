"""Group 5 / assembly tools (first slice, no joints).

bodies_to_components(map)  — turn root-level bodies into named components, preserving world position.
move_component(name, translation_mm[, rotation_axis, rotation_angle_deg])  — reposition an occurrence.
ground_component(name) / unground_component(name)  — toggle the ground flag.
create_rigid_group(component_names)  — lock components together as a rigid group.
create_contact_set(body_names)  — define a contact set for physics / motion.
interference_check(occurrence_names | body_names)  — find overlaps; returns count + per-pair volumes.

Joint creation tools (create_joint, create_as_built_joint, set_joint_limits, drive_joint)
deferred until entity handle resolution lands; they need face/edge refs that the
current name-based addressing can't express.
"""

from __future__ import annotations

import json
from typing import Any

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

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

_FIND_OCC_HELPER = """
def _find_occurrence(root, name):
    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        if occ.name == name or occ.component.name == name:
            return occ
    # search nested
    def walk(comp):
        for i in range(comp.occurrences.count):
            occ = comp.occurrences.item(i)
            if occ.name == name or occ.component.name == name:
                return occ
            r = walk(occ.component)
            if r: return r
        return None
    return walk(root)
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


def _header() -> str:
    return "import adsk.core, adsk.fusion\nimport json\n"


# ---------- bodies_to_components ----------

def build_bodies_to_components(mapping: dict[str, str]) -> str:
    """Convert root-level bodies to named components (one per entry).

    Preserves world position via createComponentFromBody.
    """
    if not mapping or not isinstance(mapping, dict):
        raise ValueError("mapping must be a non-empty dict of body_name -> component_name")
    return f"""\
{_header()}{_FIND_BODY_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    converted = []
    for body_name, comp_name in {json.dumps(mapping)}.items():
        b = _find_body(root, body_name)
        if b is None:
            print(json.dumps({{"ok": False, "error": "body_not_found", "name": body_name}})); return
        # BRepBody.createComponent() is the API for "Create Components from
        # Bodies" (world position preserved). Features.createComponentFromBodyFeatures
        # does not exist (verified absent in Fusion 2704.1.23).
        new_body = b.createComponent()
        if new_body is None:
            print(json.dumps({{"ok": False, "error": "create_component_failed", "name": body_name}})); return
        new_body.parentComponent.name = comp_name
        # createComponent() renames the moved body to the component default
        # ("Body1"); restore the original name so name-based addressing of the
        # body keeps working after conversion.
        new_body.name = body_name
        converted.append({{"from_body": body_name, "to_component": comp_name}})

    print(json.dumps({{"ok": True, "converted": converted, "total_components": root.occurrences.count}}))
"""


def bodies_to_components(adapter: FusionAdapter, mapping: dict[str, str]) -> Envelope:
    try:
        script = build_bodies_to_components(mapping)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "bodies_to_components")


# ---------- move_component ----------

def build_move_component(
    name: str,
    translation_mm: list[float] | None = None,
    rotation_axis: list[float] | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list[float] | None = None,
) -> str:
    if translation_mm is None and rotation_axis is None:
        raise ValueError("must provide at least translation_mm or (rotation_axis + rotation_angle_deg)")
    if rotation_axis is not None and rotation_angle_deg is None:
        raise ValueError("rotation_axis requires rotation_angle_deg")
    if translation_mm is not None and len(translation_mm) != 3:
        raise ValueError("translation_mm must be [tx, ty, tz] in mm")
    if rotation_axis is not None and len(rotation_axis) != 3:
        raise ValueError("rotation_axis must be [x, y, z]")

    tx, ty, tz = (0.0, 0.0, 0.0)
    if translation_mm:
        tx, ty, tz = (v / 10.0 for v in translation_mm)

    rotation_block = ""
    if rotation_axis is not None:
        rx, ry, rz = rotation_axis
        origin = rotation_origin_mm or [0, 0, 0]
        ox, oy, oz = (v / 10.0 for v in origin)
        import math
        angle_rad = (rotation_angle_deg or 0) * 3.141592653589793 / 180.0
        rotation_block = f"""
    rot = adsk.core.Matrix3D.create()
    rot.setToRotation({angle_rad}, adsk.core.Vector3D.create({rx}, {ry}, {rz}), adsk.core.Point3D.create({ox}, {oy}, {oz}))
    matrix.transformBy(rot)
"""

    return f"""\
{_header()}{_FIND_OCC_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    occ = _find_occurrence(root, {json.dumps(name)})
    if occ is None:
        print(json.dumps({{"ok": False, "error": "occurrence_not_found", "name": {json.dumps(name)}}})); return

    matrix = adsk.core.Matrix3D.create()
    matrix.translation = adsk.core.Vector3D.create({tx}, {ty}, {tz})
{rotation_block}
    # Compose with current transform. Do NOT roll the timeline first: rolling
    # to the occurrence's timelineObject reverts the pending transform, which
    # made this tool a silent no-op (ok=true, nothing moved) and crashed
    # snapshots.add() with "Has no pending snapshot" on jointed components
    # (verified live 2026-07-18).
    #
    # Occurrences made by createComponent() default to isGroundToParent=True,
    # and snapshots.add() snaps a ground-to-parent occurrence back to its
    # grounded position, silently reverting the move. Break the ground first.
    if getattr(occ, 'isGroundToParent', False):
        occ.isGroundToParent = False
    before = occ.transform2.translation
    before_mm = [before.x * 10, before.y * 10, before.z * 10]
    current = occ.transform2
    current.transformBy(matrix)
    occ.transform2 = current
    if design.snapshots.hasPendingSnapshot:
        design.snapshots.add()  # commit the move

    # Read back the position so joint-solver overrides are visible to callers.
    after = occ.transform2.translation
    after_mm = [after.x * 10, after.y * 10, after.z * 10]
    moved = any(abs(a - b) > 1e-6 for a, b in zip(after_mm, before_mm))

    # Embed Python values via repr() so None becomes Python None (not JSON null
    # which would be a NameError when this script runs).
    print(json.dumps({{
        "ok": True,
        "component": {repr(name)},
        "translation_mm": {repr(translation_mm) if translation_mm else repr([0,0,0])},
        "rotation_axis": {repr(rotation_axis)},
        "rotation_angle_deg": {repr(rotation_angle_deg)},
        "before_translation_mm": [round(v, 4) for v in before_mm],
        "after_translation_mm": [round(v, 4) for v in after_mm],
        "moved": moved,
    }}))
"""


def move_component(
    adapter: FusionAdapter,
    name: str,
    translation_mm: list[float] | None = None,
    rotation_axis: list[float] | None = None,
    rotation_angle_deg: float | None = None,
    rotation_origin_mm: list[float] | None = None,
) -> Envelope:
    try:
        script = build_move_component(name, translation_mm, rotation_axis, rotation_angle_deg, rotation_origin_mm)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "move_component")


# ---------- ground / unground ----------

def build_ground_component(name: str, grounded: bool) -> str:
    flag = "True" if grounded else "False"
    return f"""\
{_header()}{_FIND_OCC_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    occ = _find_occurrence(root, {json.dumps(name)})
    if occ is None:
        print(json.dumps({{"ok": False, "error": "occurrence_not_found", "name": {json.dumps(name)}}})); return

    occ.isGrounded = {flag}
    print(json.dumps({{"ok": True, "component": {json.dumps(name)}, "isGrounded": occ.isGrounded}}))
"""


def ground_component(adapter: FusionAdapter, name: str) -> Envelope:
    if not name:
        return Envelope(ok=False, error="invalid_input", message="name required")
    return _ok_runner(adapter, build_ground_component(name, True), "ground_component")


def unground_component(adapter: FusionAdapter, name: str) -> Envelope:
    if not name:
        return Envelope(ok=False, error="invalid_input", message="name required")
    return _ok_runner(adapter, build_ground_component(name, False), "unground_component")


# ---------- create_rigid_group ----------

def build_create_rigid_group(component_names: list[str], name: str | None = None) -> str:
    if not component_names or len(component_names) < 2:
        raise ValueError("rigid group requires at least 2 component names")
    name_block = f"    rg.name = {json.dumps(name)}\n" if name else ""
    return f"""\
{_header()}{_FIND_OCC_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    occs = adsk.core.ObjectCollection.create()
    found = []
    for nm in {json.dumps(component_names)}:
        occ = _find_occurrence(root, nm)
        if occ is None:
            print(json.dumps({{"ok": False, "error": "occurrence_not_found", "name": nm}})); return
        occs.add(occ)
        found.append(nm)

    # RigidGroups has no createInput; the API is add(occurrences, includeChildren)
    # directly on the collection (verified live in Fusion 2704.1.23). Fusion
    # raises when an existing joint would make the group over-constrained.
    try:
        rg = root.rigidGroups.add(occs, True)
    except Exception as e:
        print(json.dumps({{"ok": False, "error": "rigid_group_add_failed",
                           "detail": str(e), "components": found}})); return
    if rg is None:
        print(json.dumps({{"ok": False, "error": "rigid_group_add_failed", "components": found}})); return
{name_block}    print(json.dumps({{
        "ok": True,
        "rigid_group_name": rg.name,
        "components": found,
    }}))
"""


def create_rigid_group(adapter: FusionAdapter, component_names: list[str], name: str | None = None) -> Envelope:
    try:
        script = build_create_rigid_group(component_names, name)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_rigid_group")


# ---------- create_contact_set ----------

def build_create_contact_set(body_names: list[str]) -> str:
    if not body_names or len(body_names) < 2:
        raise ValueError("contact set requires at least 2 body names")
    return f"""\
{_header()}
# ContactSets requires bodies "in the context of the root component", so bodies
# inside components must be the assembly-context proxies from occ.bRepBodies,
# not the native bodies a plain component walk returns.
def _find_body_proxy(root, name):
    for i in range(root.bRepBodies.count):
        b = root.bRepBodies.item(i)
        if b.name == name: return b
    for i in range(root.allOccurrences.count):
        occ = root.allOccurrences.item(i)
        for j in range(occ.bRepBodies.count):
            b = occ.bRepBodies.item(j)
            if b.name == name: return b
    return None


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    bodies = []
    found = []
    for nm in {json.dumps(body_names)}:
        b = _find_body_proxy(root, nm)
        if b is None:
            print(json.dumps({{"ok": False, "error": "body_not_found", "name": nm}})); return
        bodies.append(b)
        found.append(nm)

    # ContactSets lives on the Design (not Component) and add() takes the array
    # directly; there is no createInput (verified live in Fusion 2704.1.23).
    cs = design.contactSets.add(bodies)
    if cs is None:
        print(json.dumps({{"ok": False, "error": "contact_set_add_failed", "bodies": found}})); return
    print(json.dumps({{"ok": True, "contact_set_name": cs.name, "bodies": found}}))
"""


def create_contact_set(adapter: FusionAdapter, body_names: list[str]) -> Envelope:
    try:
        script = build_create_contact_set(body_names)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_contact_set")


# ---------- interference_check ----------

def build_interference_check(entity_names: list[str]) -> str:
    if not entity_names or len(entity_names) < 2:
        raise ValueError("interference check requires at least 2 entity names (bodies or components)")
    return f"""\
{_header()}{_FIND_BODY_HELPER}{_FIND_OCC_HELPER}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    entities = adsk.core.ObjectCollection.create()
    found = []
    for nm in {json.dumps(entity_names)}:
        # try body first, then occurrence
        item = _find_body(root, nm)
        kind = 'body'
        if item is None:
            item = _find_occurrence(root, nm)
            kind = 'occurrence'
        if item is None:
            print(json.dumps({{"ok": False, "error": "entity_not_found", "name": nm}})); return
        entities.add(item)
        found.append({{"name": nm, "kind": kind}})

    inp = design.createInterferenceInput(entities)
    inp.areCoincidentFacesIncluded = False
    results = design.analyzeInterference(inp)

    pairs = []
    for i in range(results.count):
        r = results.item(i)
        pairs.append({{
            "entity_one": r.entityOne.name if hasattr(r.entityOne, 'name') else None,
            "entity_two": r.entityTwo.name if hasattr(r.entityTwo, 'name') else None,
            "interference_volume_cm3": round(r.interferenceBody.volume, 6) if r.interferenceBody else 0.0,
            "interference_volume_mm3": round(r.interferenceBody.volume * 1000, 3) if r.interferenceBody else 0.0,
        }})

    print(json.dumps({{
        "ok": True,
        "checked": found,
        "interference_pairs": pairs,
        "pair_count": len(pairs),
    }}))
"""


def interference_check(adapter: FusionAdapter, entity_names: list[str]) -> Envelope:
    try:
        script = build_interference_check(entity_names)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "interference_check")


# ---------- set_joint_limits ----------

def build_set_joint_limits(
    joint_name: str,
    min_value: str | None = None,
    max_value: str | None = None,
    rest_value: str | None = None,
) -> str:
    """Set limits / rest position on an existing joint.

    Per May 2026 release: limits and rest position are first-class joint motion controls.
    For revolute joints values are angles ('45 deg'); for slider joints they are distances.
    Pass None to leave a limit unset. rest_value (NEW May 2026) is where the joint
    snaps back when dragged.
    """
    if min_value is None and max_value is None and rest_value is None:
        raise ValueError("must provide at least one of min_value, max_value, rest_value")

    # Limits do NOT live on the JointMotion itself. RevoluteJointMotion exposes
    # rotationLimits, SliderJointMotion exposes slideLimits (Cylindrical has
    # both; we prefer rotation), each a JointLimits with isMinimumValueEnabled /
    # minimumValue / isMaximumValueEnabled / maximumValue / isRestValueEnabled /
    # restValue. Values are internal units (radians / cm), so expressions are
    # evaluated via unitsManager.evaluateExpression with deg/mm as the expected
    # measure; NOT ValueInput.createByString(...).realValue, which raises
    # "Value does not contain a real" for string inputs (verified live 2026-07-18).
    min_block = ""
    if min_value is not None:
        min_block = (
            f"    _v = _eval({json.dumps(min_value)})\n"
            f"    if _v is None: return\n"
            f"    lim.isMinimumValueEnabled = True\n"
            f"    lim.minimumValue = _v\n"
        )
    max_block = ""
    if max_value is not None:
        max_block = (
            f"    _v = _eval({json.dumps(max_value)})\n"
            f"    if _v is None: return\n"
            f"    lim.isMaximumValueEnabled = True\n"
            f"    lim.maximumValue = _v\n"
        )
    rest_block = ""
    if rest_value is not None:
        rest_block = (
            f"    _v = _eval({json.dumps(rest_value)})\n"
            f"    if _v is None: return\n"
            f"    lim.isRestValueEnabled = True\n"
            f"    lim.restValue = _v\n"
        )

    return f"""\
{_header()}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    joint = None
    for i in range(root.joints.count):
        j = root.joints.item(i)
        if j.name == {json.dumps(joint_name)}:
            joint = j; break
    if joint is None:
        print(json.dumps({{"ok": False, "error": "joint_not_found", "name": {json.dumps(joint_name)}}})); return

    jm = joint.jointMotion
    if jm is None:
        print(json.dumps({{"ok": False, "error": "joint_has_no_motion", "name": {json.dumps(joint_name)}}})); return

    lim = getattr(jm, 'rotationLimits', None)
    limits_kind = 'rotation'
    if lim is None:
        lim = getattr(jm, 'slideLimits', None)
        limits_kind = 'slide'
    if lim is None:
        print(json.dumps({{"ok": False, "error": "joint_has_no_limits",
                           "name": {json.dumps(joint_name)},
                           "motion_class": jm.classType()}})); return
    units = 'deg' if limits_kind == 'rotation' else 'mm'

    def _eval(expr):
        try:
            return design.unitsManager.evaluateExpression(expr, units)
        except Exception as e:
            print(json.dumps({{"ok": False, "error": "expression_invalid",
                               "expression": expr, "expected_units": units,
                               "detail": str(e)}}))
            return None

{min_block}{max_block}{rest_block}
    # Read back what Fusion actually stored (internal units: radians or cm)
    # so callers can verify the limits took effect.
    print(json.dumps({{
        "ok": True,
        "joint_name": {json.dumps(joint_name)},
        "limits_kind": limits_kind,
        "applied": {{
            "min_enabled": lim.isMinimumValueEnabled,
            "min_value_internal": lim.minimumValue if lim.isMinimumValueEnabled else None,
            "max_enabled": lim.isMaximumValueEnabled,
            "max_value_internal": lim.maximumValue if lim.isMaximumValueEnabled else None,
            "rest_enabled": lim.isRestValueEnabled,
            "rest_value_internal": lim.restValue if lim.isRestValueEnabled else None,
        }},
    }}))
"""


def set_joint_limits(
    adapter: FusionAdapter,
    joint_name: str,
    min_value: str | None = None,
    max_value: str | None = None,
    rest_value: str | None = None,
) -> Envelope:
    try:
        script = build_set_joint_limits(joint_name, min_value, max_value, rest_value)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "set_joint_limits")


# ---------- drive_joint ----------

def build_drive_joint(joint_name: str, value: str) -> str:
    if not value:
        raise ValueError("value expression required")
    return f"""\
{_header()}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    joint = None
    for i in range(root.joints.count):
        j = root.joints.item(i)
        if j.name == {json.dumps(joint_name)}:
            joint = j; break
    if joint is None:
        print(json.dumps({{"ok": False, "error": "joint_not_found", "name": {json.dumps(joint_name)}}})); return

    jm = joint.jointMotion
    if jm is None:
        print(json.dumps({{"ok": False, "error": "joint_has_no_motion", "name": {json.dumps(joint_name)}}})); return

    # Drive via the first available property: rotationValue (revolute), slideValue (slider), etc.
    # The expression is evaluated per-attribute with the matching measure (deg for
    # rotary, mm for slide); ValueInput.createByString(...).realValue raises
    # "Value does not contain a real" for string inputs (verified live 2026-07-18).
    _units_by_attr = {{'rotationValue': 'deg', 'slideValue': 'mm',
                       'rollValue': 'deg', 'pitchValue': 'deg', 'yawValue': 'deg'}}
    set_attrs = []
    last_err = None
    for attr in ('rotationValue', 'slideValue', 'rollValue', 'pitchValue', 'yawValue'):
        if hasattr(jm, attr):
            try:
                target_val = design.unitsManager.evaluateExpression(
                    {json.dumps(value)}, _units_by_attr[attr])
                setattr(jm, attr, target_val)
                set_attrs.append(attr)
                break
            except Exception as e:
                last_err = str(e)

    if not set_attrs:
        print(json.dumps({{"ok": False, "error": "no_drivable_motion_attribute",
                           "motion_class": jm.classType(), "detail": last_err}})); return

    # Fusion silently ignores a drive beyond the joint's limits (no exception,
    # value stays put; verified live 2026-07-18), so read back the actual value
    # and surface whether the requested target was applied.
    actual = getattr(jm, set_attrs[0])
    print(json.dumps({{
        "ok": True,
        "joint_name": {json.dumps(joint_name)},
        "drove": set_attrs[0],
        "value": {json.dumps(value)},
        "value_internal": actual,
        "requested_internal": target_val,
        "applied": abs(actual - target_val) < 1e-9,
    }}))
"""


def drive_joint(adapter: FusionAdapter, joint_name: str, value: str) -> Envelope:
    try:
        script = build_drive_joint(joint_name, value)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "drive_joint")


# ---------- create_joint ----------

VALID_MOTION_TYPES = {"rigid", "revolute", "slider", "cylindrical", "ball"}
VALID_AXES = {"x", "y", "z"}


def _joint_geometry_for_handle(handle_var: str, kind: str) -> str:
    """Emit Python that turns a resolved Fusion entity (in `handle_var`) into a
    JointGeometry, assigning the result to `<handle_var>_geom`. Returns the
    code block as a string. Generator-time kind dispatch keeps the runtime
    branch tight."""
    geom_var = f"{handle_var}_geom"
    if kind == "face":
        # Try planar first; fall back to non-planar (cylindrical, conical).
        return (
            f"    try:\n"
            f"        {geom_var} = adsk.fusion.JointGeometry.createByPlanarFace(\n"
            f"            {handle_var}, None, adsk.fusion.JointKeyPointTypes.CenterKeyPoint)\n"
            f"    except Exception:\n"
            f"        {geom_var} = adsk.fusion.JointGeometry.createByNonPlanarFace(\n"
            f"            {handle_var}, adsk.fusion.JointKeyPointTypes.CenterKeyPoint)\n"
            f"    if {geom_var} is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'joint_geometry_failed',\n"
            f"            'kind': 'face', 'detail': 'createByPlanarFace and createByNonPlanarFace both returned None'}})); return\n"
        )
    if kind == "edge":
        return (
            f"    {geom_var} = adsk.fusion.JointGeometry.createByCurve(\n"
            f"        {handle_var}, adsk.fusion.JointKeyPointTypes.MiddleKeyPoint)\n"
            f"    if {geom_var} is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'joint_geometry_failed',\n"
            f"            'kind': 'edge', 'detail': 'createByCurve returned None'}})); return\n"
        )
    if kind == "vertex":
        return (
            f"    {geom_var} = adsk.fusion.JointGeometry.createByPoint({handle_var})\n"
            f"    if {geom_var} is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'joint_geometry_failed',\n"
            f"            'kind': 'vertex', 'detail': 'createByPoint returned None'}})); return\n"
        )
    if kind == "point":  # sketch point
        return (
            f"    {geom_var} = adsk.fusion.JointGeometry.createBySketchPoint({handle_var})\n"
            f"    if {geom_var} is None:\n"
            f"        print(json.dumps({{'ok': False, 'error': 'joint_geometry_failed',\n"
            f"            'kind': 'point', 'detail': 'createBySketchPoint returned None'}})); return\n"
        )
    raise ValueError(
        f"handle kind {kind!r} cannot be used as a joint origin; "
        f"supported kinds: face, edge, vertex, point"
    )


def build_create_joint(
    geometry_one: str,
    geometry_two: str,
    motion_type: str = "rigid",
    axis: str = "z",
    offset_mm: str | None = None,
    angle_deg: str | None = None,
    name: str | None = None,
) -> str:
    """Generate a script that creates a Joint between two entity-handle origins.

    Supported motion types: rigid, revolute, slider, cylindrical, ball.
    The `axis` argument is the joint motion axis relative to the first joint
    geometry's local frame. Use 'z' for the typical 'pin coming out of the
    face' configuration; revolutes about the face normal need 'z'.

    Use entity handles (kind:path:token) from probe_sketch_dimensions or
    list_body_entities. Acceptable kinds: face, edge, vertex, point.

    For a snap-hinge between two mating flanges, a typical setup is
      geometry_one = face center of one hinge knuckle's mating face
      geometry_two = face center of the other hinge knuckle's mating face
      motion_type = "revolute"
      axis = "z"  (face normal)
      offset_mm = "9 mm"  (the joint offset that preserves the gap)
    """
    if motion_type not in VALID_MOTION_TYPES:
        raise ValueError(
            f"motion_type must be one of {sorted(VALID_MOTION_TYPES)}, got {motion_type!r}"
        )
    if axis not in VALID_AXES:
        raise ValueError(f"axis must be one of {sorted(VALID_AXES)}, got {axis!r}")

    from ..handles import emit_resolve, parse_handle  # local import keeps module load light
    import textwrap

    h1 = parse_handle(geometry_one)
    h2 = parse_handle(geometry_two)
    if h1["kind"] not in ("face", "edge", "vertex", "point"):
        raise ValueError(
            f"geometry_one kind {h1['kind']!r} unsupported; need face/edge/vertex/point"
        )
    if h2["kind"] not in ("face", "edge", "vertex", "point"):
        raise ValueError(
            f"geometry_two kind {h2['kind']!r} unsupported; need face/edge/vertex/point"
        )

    # emit_resolve produces top-level Python; indent each block to 4 spaces
    # so it sits cleanly inside run().
    resolve_one = textwrap.indent(emit_resolve(geometry_one, var="_ent1"), "    ")
    resolve_two = textwrap.indent(emit_resolve(geometry_two, var="_ent2"), "    ")
    geom_one_block = _joint_geometry_for_handle("_ent1", h1["kind"])
    geom_two_block = _joint_geometry_for_handle("_ent2", h2["kind"])

    axis_enum = {
        "x": "XAxisJointDirection",
        "y": "YAxisJointDirection",
        "z": "ZAxisJointDirection",
    }[axis]

    if motion_type == "rigid":
        motion_block = "    joint_input.setAsRigidJointMotion()\n"
    elif motion_type == "revolute":
        motion_block = (
            f"    joint_input.setAsRevoluteJointMotion(\n"
            f"        adsk.fusion.JointDirections.{axis_enum})\n"
        )
    elif motion_type == "slider":
        motion_block = (
            f"    joint_input.setAsSliderJointMotion(\n"
            f"        adsk.fusion.JointDirections.{axis_enum})\n"
        )
    elif motion_type == "cylindrical":
        motion_block = (
            f"    joint_input.setAsCylindricalJointMotion(\n"
            f"        adsk.fusion.JointDirections.{axis_enum})\n"
        )
    elif motion_type == "ball":
        # setAsBallJointMotion(pitchDirection, yawDirection): Fusion only
        # accepts pitch=Z, yaw=X. All 8 other principal-axis combinations raise
        # "Invalid parameter pitchDirection/yawDirection" (exhaustively verified
        # live 2026-07-18 on Fusion 2704.1.23).
        motion_block = (
            "    joint_input.setAsBallJointMotion(\n"
            "        adsk.fusion.JointDirections.ZAxisJointDirection,\n"
            "        adsk.fusion.JointDirections.XAxisJointDirection)\n"
        )
    else:
        raise ValueError(f"motion_type {motion_type!r} not handled")  # defensive

    offset_block = ""
    if offset_mm is not None:
        offset_block = (
            f"    joint_input.offset = adsk.core.ValueInput.createByString({json.dumps(offset_mm)})\n"
        )
    angle_block = ""
    if angle_deg is not None:
        angle_block = (
            f"    joint_input.angle = adsk.core.ValueInput.createByString({json.dumps(angle_deg)})\n"
        )

    rename_block = ""
    if name is not None:
        rename_block = f"    joint.name = {json.dumps(name)}\n"

    return f"""\
{_header()}

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}})); return
    root = design.rootComponent

    # Resolve geometry handles
{resolve_one}
{resolve_two}

    # Build JointGeometry for each
{geom_one_block}{geom_two_block}

    joints = root.joints
    joint_input = joints.createInput(_ent1_geom, _ent2_geom)

    # Motion type
{motion_block}

    # Optional inputs
{offset_block}{angle_block}
    try:
        joint = joints.add(joint_input)
    except Exception as e:
        print(json.dumps({{
            "ok": False, "error": "joints_add_failed",
            "detail": str(e),
            "motion_type": {repr(motion_type)},
            "axis": {repr(axis)},
        }})); return
{rename_block}
    # Embed Python values via repr() so None becomes Python None (not JSON null
    # which would be a NameError when this script runs).
    print(json.dumps({{
        "ok": True,
        "joint_name": joint.name,
        "joint_token": joint.entityToken,
        "motion_type": {repr(motion_type)},
        "axis": {repr(axis)},
        "offset_mm": {repr(offset_mm)},
        "angle_deg": {repr(angle_deg)},
    }}))
"""


def create_joint(
    adapter: FusionAdapter,
    geometry_one: str,
    geometry_two: str,
    motion_type: str = "rigid",
    axis: str = "z",
    offset_mm: str | None = None,
    angle_deg: str | None = None,
    name: str | None = None,
) -> Envelope:
    try:
        script = build_create_joint(
            geometry_one, geometry_two, motion_type, axis, offset_mm, angle_deg, name,
        )
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "create_joint")


__all__ = [
    "bodies_to_components",
    "build_bodies_to_components",
    "build_create_contact_set",
    "build_create_joint",
    "build_create_rigid_group",
    "build_drive_joint",
    "build_ground_component",
    "build_interference_check",
    "build_move_component",
    "build_set_joint_limits",
    "create_contact_set",
    "create_joint",
    "create_rigid_group",
    "drive_joint",
    "ground_component",
    "interference_check",
    "move_component",
    "set_joint_limits",
    "unground_component",
]
