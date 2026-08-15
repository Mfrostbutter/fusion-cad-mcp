"""Group 7 / IO tools.

export(format, body, path, ...)  — STL, 3MF, STEP, IGES, OBJ, F3D, SAT, SMT.
import_geometry(format, path)    — STEP, IGES, SAT, SMT, F3D into the active doc.

Path safety: tools reject relative paths, parent-dir tricks (".."), and
Windows reserved names (CON, NUL, etc). Absolute paths only. Directories are
auto-created (os.makedirs exist_ok=True) per the skill's gotcha catalog.
"""

from __future__ import annotations

import json
import os
import re

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

EXPORT_FORMATS = {"stl", "3mf", "step", "iges", "obj", "f3d", "sat", "smt"}
IMPORT_FORMATS = {"step", "iges", "sat", "smt", "f3d"}

# STL refinement levels map to Fusion's MeshRefinementSettings enum
STL_REFINEMENT = {
    "low":    "MeshRefinementLow",
    "medium": "MeshRefinementMedium",
    "high":   "MeshRefinementHigh",
}

_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _validate_path(path: str) -> tuple[bool, str | None]:
    """Reject obviously dangerous or invalid paths. Returns (ok, error_message)."""
    if not path or not isinstance(path, str):
        return False, "path must be a non-empty string"
    if ".." in re.split(r"[\\/]", path):
        return False, "path contains '..' parent-dir reference"
    if not os.path.isabs(path):
        return False, f"path must be absolute, got {path!r}"
    base = os.path.basename(path).lower()
    base_no_ext = base.split(".")[0]
    if base_no_ext in _WIN_RESERVED:
        return False, f"path uses Windows reserved name {base_no_ext!r}"
    return True, None


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
    return "import adsk.core, adsk.fusion\nimport json, os\n"


# ---------- export ----------

def build_export(
    format: str,
    body: str | None,
    path: str,
    refinement: str = "medium",
    units: str = "mm",
) -> str:
    fmt = format.lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"format must be one of {sorted(EXPORT_FORMATS)}, got {format!r}")
    # path validated by caller; we still escape it into the script

    # Fusion ExportManager API names per format
    if fmt == "stl":
        if refinement not in STL_REFINEMENT:
            raise ValueError(f"refinement must be one of {sorted(STL_REFINEMENT)} for STL, got {refinement!r}")
        return _build_export_stl(body, path, refinement, units)
    elif fmt == "3mf":
        return _build_export_3mf(body, path)
    elif fmt == "step":
        return _build_export_simple("createSTEPExportOptions", path)
    elif fmt == "iges":
        return _build_export_simple("createIGESExportOptions", path)
    elif fmt == "f3d":
        return _build_export_simple("createFusionArchiveExportOptions", path)
    elif fmt == "obj":
        return _build_export_obj(body, path, refinement)
    elif fmt == "sat":
        return _build_export_simple("createSATExportOptions", path)
    elif fmt == "smt":
        return _build_export_simple("createSMTExportOptions", path)
    raise AssertionError("unreachable")


def _emit_find_body() -> str:
    return """
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


def _build_export_stl(body: str | None, path: str, refinement: str, units: str) -> str:
    units_enum_map = {
        "mm":     "MillimeterDistanceUnits",
        "cm":     "CentimeterDistanceUnits",
        "m":      "MeterDistanceUnits",
        "inch":   "InchDistanceUnits",
        "in":     "InchDistanceUnits",
    }
    if units not in units_enum_map:
        raise ValueError(f"units must be one of {sorted(units_enum_map)} for STL, got {units!r}")
    units_enum = units_enum_map[units]
    refinement_enum = STL_REFINEMENT[refinement]

    body_block = ""
    target_expr = "design.rootComponent"
    if body:
        body_block = _emit_find_body()
        target_expr = "b"

    return (
        _header()
        + body_block
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + (f"    b = _find_body(root, {json.dumps(body)})\n"
           f"    if b is None:\n"
           f"        print(json.dumps({{'ok': False, 'error': 'body_not_found', 'name': {json.dumps(body)}}})); return\n"
           if body else "")
        + f"    os.makedirs(os.path.dirname({json.dumps(path)}), exist_ok=True)\n"
        + "    em = design.exportManager\n"
        + f"    opts = em.createSTLExportOptions({target_expr}, {json.dumps(path)})\n"
        + f"    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.{refinement_enum}\n"
        + "    opts.sendToPrintUtility = False\n"
        + f"    opts.units = adsk.fusion.DistanceUnits.{units_enum}\n"
        + "    em.execute(opts)\n"
        + f"    size = os.path.getsize({json.dumps(path)}) if os.path.exists({json.dumps(path)}) else 0\n"
        + f"    print(json.dumps({{'ok': True, 'format': 'stl', 'path': {json.dumps(path)},"
        + f" 'bytes_written': size, 'refinement': {json.dumps(refinement)}, 'units': {json.dumps(units)}}}))\n"
    )


def _build_export_3mf(body: str | None, path: str) -> str:
    body_block = ""
    target_expr = "design.rootComponent"
    if body:
        body_block = _emit_find_body()
        target_expr = "b"

    return (
        _header()
        + body_block
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + (f"    b = _find_body(root, {json.dumps(body)})\n"
           f"    if b is None:\n"
           f"        print(json.dumps({{'ok': False, 'error': 'body_not_found', 'name': {json.dumps(body)}}})); return\n"
           if body else "")
        + f"    os.makedirs(os.path.dirname({json.dumps(path)}), exist_ok=True)\n"
        + "    em = design.exportManager\n"
        + f"    opts = em.createC3MFExportOptions({target_expr}, {json.dumps(path)})\n"
        + "    em.execute(opts)\n"
        + f"    size = os.path.getsize({json.dumps(path)}) if os.path.exists({json.dumps(path)}) else 0\n"
        + f"    print(json.dumps({{'ok': True, 'format': '3mf', 'path': {json.dumps(path)}, 'bytes_written': size}}))\n"
    )


def _build_export_obj(body: str | None, path: str, refinement: str) -> str:
    if refinement not in STL_REFINEMENT:
        raise ValueError(f"refinement must be one of {sorted(STL_REFINEMENT)} for OBJ, got {refinement!r}")
    refinement_enum = STL_REFINEMENT[refinement]
    body_block = ""
    target_expr = "design.rootComponent"
    if body:
        body_block = _emit_find_body()
        target_expr = "b"
    return (
        _header()
        + body_block
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + "    root = design.rootComponent\n"
        + (f"    b = _find_body(root, {json.dumps(body)})\n"
           f"    if b is None:\n"
           f"        print(json.dumps({{'ok': False, 'error': 'body_not_found', 'name': {json.dumps(body)}}})); return\n"
           if body else "")
        + f"    os.makedirs(os.path.dirname({json.dumps(path)}), exist_ok=True)\n"
        + "    em = design.exportManager\n"
        + f"    opts = em.createOBJExportOptions({target_expr}, {json.dumps(path)})\n"
        + f"    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.{refinement_enum}\n"
        + "    em.execute(opts)\n"
        + f"    size = os.path.getsize({json.dumps(path)}) if os.path.exists({json.dumps(path)}) else 0\n"
        + f"    print(json.dumps({{'ok': True, 'format': 'obj', 'path': {json.dumps(path)}, 'bytes_written': size}}))\n"
    )


def _build_export_simple(opts_factory: str, path: str) -> str:
    """For STEP/IGES/SAT/SMT/F3D — export the whole design (no body arg supported by these)."""
    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + f"    os.makedirs(os.path.dirname({json.dumps(path)}), exist_ok=True)\n"
        + "    em = design.exportManager\n"
        + f"    opts = em.{opts_factory}({json.dumps(path)})\n"
        + "    em.execute(opts)\n"
        + f"    size = os.path.getsize({json.dumps(path)}) if os.path.exists({json.dumps(path)}) else 0\n"
        + f"    print(json.dumps({{'ok': True, 'path': {json.dumps(path)}, 'bytes_written': size}}))\n"
    )


def export(
    adapter: FusionAdapter,
    format: str,
    path: str,
    body: str | None = None,
    refinement: str = "medium",
    units: str = "mm",
) -> Envelope:
    ok, err = _validate_path(path)
    if not ok:
        return Envelope(ok=False, error="invalid_path", message=err or "")
    try:
        script = build_export(format, body, path, refinement, units)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "export")


# ---------- import_geometry ----------

def build_import_geometry(format: str, path: str) -> str:
    fmt = format.lower()
    if fmt not in IMPORT_FORMATS:
        raise ValueError(f"format must be one of {sorted(IMPORT_FORMATS)}, got {format!r}")

    factory = {
        "step": "createSTEPImportOptions",
        "iges": "createIGESImportOptions",
        "sat":  "createSATImportOptions",
        "smt":  "createSMTImportOptions",
        "f3d":  "createFusionArchiveImportOptions",
    }[fmt]

    return (
        _header()
        + "\ndef run(_ctx):\n"
        + "    app = adsk.core.Application.get()\n"
        + "    design = adsk.fusion.Design.cast(app.activeProduct)\n"
        + "    if design is None:\n"
        + "        print(json.dumps({'ok': False, 'error': 'no_active_design'})); return\n"
        + f"    if not os.path.exists({json.dumps(path)}):\n"
        + f"        print(json.dumps({{'ok': False, 'error': 'file_not_found', 'path': {json.dumps(path)}}})); return\n"
        + "    im = app.importManager\n"
        + f"    opts = im.{factory}({json.dumps(path)})\n"
        + "    pre_bodies = design.rootComponent.bRepBodies.count\n"
        + "    pre_occs = design.rootComponent.occurrences.count\n"
        + "    im.importToTarget(opts, design.rootComponent)\n"
        + "    print(json.dumps({\n"
        + f"        'ok': True, 'format': {json.dumps(fmt)}, 'path': {json.dumps(path)},\n"
        + "        'bodies_added': design.rootComponent.bRepBodies.count - pre_bodies,\n"
        + "        'occurrences_added': design.rootComponent.occurrences.count - pre_occs,\n"
        + "    }))\n"
    )


def import_geometry(adapter: FusionAdapter, format: str, path: str) -> Envelope:
    ok, err = _validate_path(path)
    if not ok:
        return Envelope(ok=False, error="invalid_path", message=err or "")
    try:
        script = build_import_geometry(format, path)
    except ValueError as e:
        return Envelope(ok=False, error="invalid_input", message=str(e))
    return _ok_runner(adapter, script, "import_geometry")


__all__ = [
    "EXPORT_FORMATS",
    "IMPORT_FORMATS",
    "build_export",
    "build_import_geometry",
    "export",
    "import_geometry",
]
