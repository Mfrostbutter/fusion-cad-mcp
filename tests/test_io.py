"""Tier 1a/1c tests for Group 7 IO tools."""

from __future__ import annotations

import ast

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import io as io_tool

# ---------- path validator ----------


def test_path_rejects_relative():
    ok, err = io_tool._validate_path("plate.stl")
    assert ok is False
    assert "absolute" in err


def test_path_rejects_parent_dir():
    ok, err = io_tool._validate_path("C:/Users/someone/../etc/passwd")
    assert ok is False
    assert ".." in err


def test_path_rejects_windows_reserved():
    ok, err = io_tool._validate_path("C:/temp/con.stl")
    assert ok is False
    assert "reserved" in err


def test_path_accepts_normal_absolute_path():
    ok, err = io_tool._validate_path("C:/Users/someone/plate.stl")
    assert ok is True
    assert err is None


def test_path_rejects_empty():
    ok, err = io_tool._validate_path("")
    assert ok is False


# ---------- export generators ----------


def test_export_stl_emits_mesh_refinement_and_units():
    src = io_tool.build_export("stl", "plate", "C:/tmp/plate.stl", refinement="high", units="mm")
    ast.parse(src)
    assert "createSTLExportOptions" in src
    assert "MeshRefinementHigh" in src
    assert "MillimeterDistanceUnits" in src
    assert "_find_body" in src  # body lookup helper present


def test_export_stl_without_body_targets_root_component():
    src = io_tool.build_export("stl", None, "C:/tmp/all.stl")
    assert "createSTLExportOptions(design.rootComponent" in src
    assert "_find_body" not in src  # no body lookup needed


def test_export_stl_rejects_unknown_refinement():
    with pytest.raises(ValueError):
        io_tool.build_export("stl", None, "C:/tmp/x.stl", refinement="ultra")


def test_export_stl_rejects_unknown_units():
    with pytest.raises(ValueError):
        io_tool.build_export("stl", None, "C:/tmp/x.stl", units="furlongs")


def test_export_3mf_uses_c3mf_options():
    src = io_tool.build_export("3mf", "plate", "C:/tmp/plate.3mf")
    assert "createC3MFExportOptions" in src


def test_export_step_uses_simple_factory():
    src = io_tool.build_export("step", None, "C:/tmp/x.step")
    assert "createSTEPExportOptions" in src


def test_export_iges_factory():
    src = io_tool.build_export("iges", None, "C:/tmp/x.iges")
    assert "createIGESExportOptions" in src


def test_export_f3d_factory():
    src = io_tool.build_export("f3d", None, "C:/tmp/x.f3d")
    assert "createFusionArchiveExportOptions" in src


def test_export_obj_with_body():
    src = io_tool.build_export("obj", "plate", "C:/tmp/plate.obj", refinement="low")
    assert "createOBJExportOptions" in src
    assert "MeshRefinementLow" in src


def test_export_unknown_format_rejected():
    with pytest.raises(ValueError):
        io_tool.build_export("ply", None, "C:/tmp/x.ply")


def test_export_makedirs_present():
    """All export generators auto-create the parent directory."""
    for fmt in ("stl", "step", "iges", "3mf", "obj", "f3d"):
        src = io_tool.build_export(
            fmt, None if fmt != "stl" and fmt != "obj" else "plate", f"C:/tmp/x.{fmt}"
        )
        assert "os.makedirs" in src, f"export {fmt} missing makedirs"


# ---------- import generators ----------


def test_import_step():
    src = io_tool.build_import_geometry("step", "C:/parts/widget.step")
    ast.parse(src)
    assert "createSTEPImportOptions" in src
    assert "importToTarget" in src
    assert "bodies_added" in src


def test_import_iges():
    src = io_tool.build_import_geometry("iges", "C:/parts/widget.iges")
    assert "createIGESImportOptions" in src


def test_import_rejects_stl():
    """STL isn't in IMPORT_FORMATS (it goes through a different MeshBody path)."""
    with pytest.raises(ValueError):
        io_tool.build_import_geometry("stl", "C:/tmp/x.stl")


def test_import_checks_file_exists():
    src = io_tool.build_import_geometry("step", "C:/parts/widget.step")
    assert "os.path.exists" in src
    assert "file_not_found" in src


# ---------- run wrappers ----------


class FakeAdapter:
    def __init__(self, message: str = '{"ok": true}'):
        self.scripts: list[str] = []
        self.message = message

    def execute_script(self, s: str) -> Envelope:
        self.scripts.append(s)
        return Envelope(ok=True, message=self.message)


def test_export_short_circuits_on_relative_path():
    a = FakeAdapter()
    env = io_tool.export(a, "stl", "plate.stl")
    assert env.ok is False
    assert env.error == "invalid_path"
    assert a.scripts == []


def test_export_short_circuits_on_unknown_format():
    a = FakeAdapter()
    env = io_tool.export(a, "ply", "C:/tmp/x.ply")
    assert env.ok is False
    assert env.error == "invalid_input"


def test_import_geometry_short_circuits_on_unknown_format():
    a = FakeAdapter()
    env = io_tool.import_geometry(a, "ply", "C:/parts/x.ply")
    assert env.ok is False
    assert env.error == "invalid_input"
