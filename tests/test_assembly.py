"""Assembly tool generator + run-wrapper tests."""

import ast

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import assembly as asm

# ---------- bodies_to_components ----------


def test_bodies_to_components_parses_and_iterates_mapping():
    src = asm.build_bodies_to_components({"plate": "plate_comp", "bracket": "bracket_comp"})
    ast.parse(src)
    # Features.createComponentFromBodyFeatures does not exist in the live API;
    # the correct call is BRepBody.createComponent(). (Filter comment lines:
    # the generated code documents the dead API in a comment.)
    code_lines = [line for line in src.splitlines() if not line.strip().startswith("#")]
    assert all("createComponentFromBodyFeatures" not in line for line in code_lines)
    assert "b.createComponent()" in src
    # createComponent() renames the moved body to the component default; the
    # original name must be restored so name-based addressing keeps working.
    assert "new_body.name = body_name" in src
    assert '"plate": "plate_comp"' in src or "plate" in src
    assert '"bracket"' in src or "bracket" in src


def test_bodies_to_components_rejects_empty():
    with pytest.raises(ValueError):
        asm.build_bodies_to_components({})


# ---------- move_component ----------


def test_move_translation_only_converts_mm_to_cm():
    src = asm.build_move_component("plate_comp", translation_mm=[20, -10, 5])
    ast.parse(src)
    # 20mm -> 2.0, -10mm -> -1.0, 5mm -> 0.5
    assert "Vector3D.create(2.0, -1.0, 0.5)" in src


def test_move_rotation_only_uses_radians():
    src = asm.build_move_component("plate_comp", rotation_axis=[0, 0, 1], rotation_angle_deg=90)
    ast.parse(src)
    # 90 deg = pi/2 = 1.5707...
    assert "Vector3D.create(0, 0, 1)" in src
    assert "1.5707" in src


def test_move_component_breaks_ground_and_verifies_motion():
    """Regression for the silent no-op: rolling the timeline reverted the
    pending transform, and snapshots.add() snapped ground-to-parent
    occurrences back to their grounded position (ok=true, nothing moved)."""
    src = asm.build_move_component("plate_comp", translation_mm=[10, 0, 0])
    ast.parse(src)
    # No timeline roll before the move.
    assert "rollTo" not in src
    # Ground-to-parent must be broken or the snapshot reverts the move.
    assert "isGroundToParent" in src
    # snapshots.add() raises when nothing is pending (jointed components);
    # it must be guarded.
    assert "hasPendingSnapshot" in src
    # The response must read back the actual position so callers can detect
    # a joint-solver override.
    assert '"moved"' in src
    assert "after_translation_mm" in src


def test_move_rejects_axis_without_angle():
    with pytest.raises(ValueError):
        asm.build_move_component("p", rotation_axis=[0, 0, 1])


def test_move_rejects_nothing():
    with pytest.raises(ValueError):
        asm.build_move_component("p")


def test_move_rejects_bad_translation_length():
    with pytest.raises(ValueError):
        asm.build_move_component("p", translation_mm=[10, 5])


def test_move_translation_only_emits_python_none_not_json_null():
    """Regression: a prior version used json.dumps() to embed optional values
    into the generated Python source. json.dumps(None) is the string "null"
    which is a NameError when the script runs. Fix uses repr() which emits
    the Python literal "None". Validate by AST-parsing the script (any bare
    "null" identifier would raise NameError at run time; parse succeeds
    syntactically, so we also assert the print payload uses None, not null."""
    src = asm.build_move_component("comp_A", translation_mm=[10, 0, 0])
    # The script must parse cleanly
    ast.parse(src)
    # The print payload must spell rotation fields as Python None, not JSON null.
    # Look for the print-of-result dict that summarizes the move.
    assert '"rotation_axis": None' in src
    assert '"rotation_angle_deg": None' in src
    # Bare "null" must never appear unquoted in the generator output (it would
    # be a NameError when the script runs).
    for line in src.splitlines():
        # Skip comments and strings: a quick conservative check is that
        # the token "null" should not appear as a bare identifier on its own.
        # Specifically guard against the historical "rotation_axis": null shape.
        assert ": null," not in line, f"bare JSON null in generated script: {line!r}"
        assert ": null}}" not in line, f"bare JSON null in generated script: {line!r}"


def test_move_rotation_emits_concrete_list_not_repr_with_None():
    """When rotation_axis IS provided, repr() emits a Python list literal like
    [0, 0, 1] which is valid Python. Confirm the round-trip."""
    src = asm.build_move_component("comp_A", rotation_axis=[0, 0, 1], rotation_angle_deg=90)
    ast.parse(src)
    assert '"rotation_axis": [0, 0, 1]' in src
    assert '"rotation_angle_deg": 90' in src


# ---------- ground / unground ----------


def test_ground_emits_true_flag():
    src = asm.build_ground_component("plate_comp", True)
    ast.parse(src)
    assert "occ.isGrounded = True" in src


def test_unground_emits_false_flag():
    src = asm.build_ground_component("plate_comp", False)
    assert "occ.isGrounded = False" in src


# ---------- rigid group ----------


def test_rigid_group_requires_at_least_2_components():
    with pytest.raises(ValueError):
        asm.build_create_rigid_group(["only_one"])


def test_rigid_group_parses():
    src = asm.build_create_rigid_group(["comp_a", "comp_b", "comp_c"], name="locked_trio")
    ast.parse(src)
    # RigidGroups has no createInput; the live API is add(occurrences, includeChildren)
    assert "rigidGroups.createInput" not in src
    assert "rigidGroups.add(occs, True)" in src
    assert "rigid_group_add_failed" in src  # over-constrained input raises; must be caught
    assert '"locked_trio"' in src


# ---------- contact set ----------


def test_contact_set_requires_at_least_2_bodies():
    with pytest.raises(ValueError):
        asm.build_create_contact_set(["solo"])


def test_contact_set_parses():
    src = asm.build_create_contact_set(["plate", "bracket"])
    ast.parse(src)
    # ContactSets lives on the Design, add() takes the array directly (no createInput),
    # and bodies inside components must be assembly-context proxies.
    assert "contactSets.createInput" not in src
    assert "design.contactSets.add(bodies)" in src
    assert "_find_body_proxy" in src
    assert "allOccurrences" in src


# ---------- interference check ----------


def test_interference_requires_at_least_2():
    with pytest.raises(ValueError):
        asm.build_interference_check(["one_body"])


def test_interference_parses_and_reports_per_pair_volume():
    src = asm.build_interference_check(["plate", "bracket"])
    ast.parse(src)
    assert "analyzeInterference" in src
    assert "interferenceBody" in src
    assert "interference_volume_mm3" in src


# ---------- run wrappers ----------


class FakeAdapter:
    def __init__(self, message: str = '{"ok": true}'):
        self.scripts: list[str] = []
        self.message = message

    def execute_script(self, s: str) -> Envelope:
        self.scripts.append(s)
        return Envelope(ok=True, message=self.message)


def test_bodies_to_components_short_circuits_on_empty():
    a = FakeAdapter()
    env = asm.bodies_to_components(a, {})
    assert env.ok is False
    assert env.error == "invalid_input"
    assert a.scripts == []


def test_ground_requires_name():
    a = FakeAdapter()
    env = asm.ground_component(a, "")
    assert env.ok is False
