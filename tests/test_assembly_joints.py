"""Joint by-name tools: set_joint_limits + drive_joint."""
import ast
import json

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import assembly as asm


def test_set_joint_limits_requires_at_least_one_value():
    with pytest.raises(ValueError):
        asm.build_set_joint_limits("hinge")


def test_set_joint_limits_min_only():
    src = asm.build_set_joint_limits("hinge", min_value="-45 deg")
    ast.parse(src)
    # Limits live on jm.rotationLimits / jm.slideLimits (JointLimits objects),
    # not on the JointMotion directly, and use isMinimumValueEnabled naming.
    assert "lim.isMinimumValueEnabled = True" in src
    assert "isMaximumValueEnabled = True" not in src
    assert "isRestValueEnabled = True" not in src
    assert "rotationLimits" in src
    assert "slideLimits" in src
    # Expressions must be evaluated via unitsManager; .realValue on a string
    # ValueInput raises "Value does not contain a real" inside Fusion.
    assert "evaluateExpression" in src
    assert ".realValue" not in src
    assert '"-45 deg"' in src


def test_set_joint_limits_min_max_rest():
    src = asm.build_set_joint_limits("hinge", min_value="-45 deg", max_value="45 deg", rest_value="0 deg")
    ast.parse(src)
    assert "lim.isMinimumValueEnabled = True" in src
    assert "lim.isMaximumValueEnabled = True" in src
    assert "lim.isRestValueEnabled = True" in src
    # Response reads back what Fusion actually stored.
    assert "min_value_internal" in src


def test_drive_joint_requires_value():
    with pytest.raises(ValueError):
        asm.build_drive_joint("hinge", "")


def test_drive_joint_tries_multiple_motion_attrs():
    src = asm.build_drive_joint("hinge", "30 deg")
    ast.parse(src)
    assert "rotationValue" in src
    assert "slideValue" in src
    # Evaluated per attribute with matching measure (deg / mm), never realValue
    # (filter comment lines: the generated code documents the dead API).
    assert "evaluateExpression" in src
    code_lines = [line for line in src.splitlines() if not line.strip().startswith("#")]
    assert all(".realValue" not in line for line in code_lines)
    assert '"30 deg"' in src
    # Fusion silently clamps beyond-limit drives; response must expose it.
    assert '"applied"' in src


# ---------- create_joint ----------


def _h(kind, path="b", token="tok"):
    return f"{kind}:{path}:{token}"


def test_build_create_joint_rigid_face_face_parses():
    src = asm.build_create_joint(_h("face", token="t1"), _h("face", token="t2"))
    ast.parse(src)
    assert "setAsRigidJointMotion" in src
    assert "createByPlanarFace" in src
    # Both resolve blocks present
    assert '"t1"' in src
    assert '"t2"' in src


def test_build_create_joint_revolute_uses_axis_enum():
    src = asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                                 motion_type="revolute", axis="z")
    assert "setAsRevoluteJointMotion" in src
    assert "ZAxisJointDirection" in src


def test_build_create_joint_slider_x_axis():
    src = asm.build_create_joint(_h("edge", token="a"), _h("edge", token="b"),
                                 motion_type="slider", axis="x")
    assert "setAsSliderJointMotion" in src
    assert "XAxisJointDirection" in src
    # Edges use createByCurve with MiddleKeyPoint
    assert "createByCurve" in src
    assert "MiddleKeyPoint" in src


def test_build_create_joint_cylindrical_y_axis():
    src = asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                                 motion_type="cylindrical", axis="y")
    assert "setAsCylindricalJointMotion" in src
    assert "YAxisJointDirection" in src


def test_build_create_joint_ball_uses_z_pitch_x_yaw():
    src = asm.build_create_joint(_h("vertex", token="a"), _h("vertex", token="b"),
                                 motion_type="ball", axis="z")
    assert "setAsBallJointMotion" in src
    # Fusion only accepts pitch=Z, yaw=X; every other principal-axis combo
    # raises "Invalid parameter pitchDirection/yawDirection" (verified live).
    assert "ZAxisJointDirection" in src
    assert "XAxisJointDirection" in src
    assert "YAxisJointDirection" not in src
    # Vertices use createByPoint
    assert "createByPoint" in src


def test_build_create_joint_point_kind_uses_sketch_point():
    src = asm.build_create_joint(_h("point", token="a"), _h("point", token="b"),
                                 motion_type="rigid")
    assert "createBySketchPoint" in src


def test_build_create_joint_offset_and_angle():
    src = asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                                 motion_type="revolute", axis="z",
                                 offset_mm="9 mm", angle_deg="0 deg")
    assert "joint_input.offset = adsk.core.ValueInput.createByString(\"9 mm\")" in src
    assert "joint_input.angle = adsk.core.ValueInput.createByString(\"0 deg\")" in src


def test_build_create_joint_renames_when_name_given():
    src = asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                                 name="hinge_main")
    assert "joint.name = \"hinge_main\"" in src


def test_build_create_joint_rejects_bad_motion_type():
    with pytest.raises(ValueError):
        asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                               motion_type="spring")


def test_build_create_joint_rejects_bad_axis():
    with pytest.raises(ValueError):
        asm.build_create_joint(_h("face", token="a"), _h("face", token="b"),
                               axis="w")


def test_build_create_joint_rejects_non_origin_handle_kind():
    with pytest.raises(ValueError):
        asm.build_create_joint(_h("body", token="a"), _h("face", token="b"))


def test_create_joint_passes_through_payload():
    class A:
        def execute_script(self, s):
            self.s = s
            return Envelope(ok=True, message=json.dumps({
                "ok": True, "joint_name": "Joint1", "joint_token": "abc",
                "motion_type": "revolute", "axis": "z",
                "offset_mm": "9 mm", "angle_deg": None,
            }))

    a = A()
    env = asm.create_joint(a, _h("face", token="t1"), _h("face", token="t2"),
                           motion_type="revolute", axis="z", offset_mm="9 mm")
    assert env.ok is True
    assert env.result["joint_name"] == "Joint1"
    assert env.result["offset_mm"] == "9 mm"


def test_create_joint_short_circuits_on_invalid_input():
    class A:
        def execute_script(self, s):
            raise AssertionError("must not reach Fusion on validation failure")

    env = asm.create_joint(A(), _h("face", token="a"), _h("face", token="b"),
                           motion_type="spring")
    assert env.ok is False
    assert env.error == "invalid_input"


def test_create_joint_surfaces_joints_add_failed():
    payload = {
        "ok": False, "error": "joints_add_failed",
        "detail": "JointInput rejected by Fusion",
        "motion_type": "revolute", "axis": "z",
    }

    class A:
        def execute_script(self, s):
            return Envelope(ok=True, message=json.dumps(payload))

    env = asm.create_joint(A(), _h("face", token="a"), _h("face", token="b"),
                           motion_type="revolute")
    assert env.ok is False
    assert env.error == "joints_add_failed"
    assert "rejected" in env.result["detail"]
