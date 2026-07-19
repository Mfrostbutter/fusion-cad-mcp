"""Group 6 / verify tools.

bounding_box, volume, mass, center_of_mass.

Each tool accepts an optional body_name. If omitted, returns measurements for
ALL bodies in the design (root + every occurrence). If given, returns just the
matching body or a structured 'body_not_found' error.

All distances reported in mm. Internal Fusion units are cm; conversion happens
in the generator so the agent sees mm everywhere.
"""

from __future__ import annotations

import json

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json


def _body_walker_script(measurement_block: str, body_name: str | None) -> str:
    """Build a script that walks every body in root + all occurrences and yields
    measurements. measurement_block is Python that operates on a name `b` (the
    BRepBody) and emits per-body dict entries into a list named `entries`.
    """
    name_filter = "None" if body_name is None else json.dumps(body_name)
    return f"""
import adsk.core
import adsk.fusion
import json

NAME_FILTER = {name_filter}

def walk(comp, prefix, entries):
    for i in range(comp.bRepBodies.count):
        b = comp.bRepBodies.item(i)
        if NAME_FILTER is not None and b.name != NAME_FILTER:
            continue
        path = prefix + b.name
        try:
{measurement_block}
        except Exception as e:
            entries.append({{"path": path, "error": str(e)}})
    for j in range(comp.occurrences.count):
        occ = comp.occurrences.item(j)
        if occ.component is not None:
            walk(occ.component, prefix + comp.name + " / ", entries)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    entries = []
    walk(design.rootComponent, "", entries)
    if NAME_FILTER is not None and not entries:
        print(json.dumps({{"ok": False, "error": "body_not_found", "name": NAME_FILTER}}))
        return
    print(json.dumps({{"ok": True, "bodies": entries, "count": len(entries)}}))
""".strip()


def build_bounding_box(body_name: str | None = None) -> str:
    return _body_walker_script(
        """\
            bb = b.boundingBox
            entries.append({
                "path": path,
                "name": b.name,
                "bbox_mm": {
                    "min": [round(bb.minPoint.x*10, 4), round(bb.minPoint.y*10, 4), round(bb.minPoint.z*10, 4)],
                    "max": [round(bb.maxPoint.x*10, 4), round(bb.maxPoint.y*10, 4), round(bb.maxPoint.z*10, 4)],
                },
                "extent_mm": [
                    round((bb.maxPoint.x - bb.minPoint.x)*10, 4),
                    round((bb.maxPoint.y - bb.minPoint.y)*10, 4),
                    round((bb.maxPoint.z - bb.minPoint.z)*10, 4),
                ],
            })""",
        body_name,
    )


def build_volume(body_name: str | None = None) -> str:
    return _body_walker_script(
        """\
            v_cm3 = b.volume
            entries.append({
                "path": path,
                "name": b.name,
                "volume_cm3": round(v_cm3, 6),
                "volume_mm3": round(v_cm3 * 1000.0, 3),
            })""",
        body_name,
    )


def build_mass(body_name: str | None = None) -> str:
    return _body_walker_script(
        """\
            pp = b.physicalProperties
            # Fusion's density is kg per internal cm^3; convert to kg/m^3 by *1e6 for readability
            density_kg_m3 = (pp.density * 1_000_000) if hasattr(pp, "density") else None
            entries.append({
                "path": path,
                "name": b.name,
                "mass_kg": round(pp.mass, 6),
                "volume_cm3": round(pp.volume, 6),
                "material": b.material.name if b.material else None,
                "density_kg_m3": round(density_kg_m3, 3) if density_kg_m3 is not None else None,
            })""",
        body_name,
    )


def build_center_of_mass(body_name: str | None = None) -> str:
    return _body_walker_script(
        """\
            pp = b.physicalProperties
            c = pp.centerOfMass
            entries.append({
                "path": path,
                "name": b.name,
                "center_of_mass_mm": [round(c.x*10, 4), round(c.y*10, 4), round(c.z*10, 4)],
            })""",
        body_name,
    )


def build_audit_feature_health(
    component_name: str | None = None,
    include_healthy: bool = False,
) -> str:
    """Walk the feature tree (root + every sub-component) and report features
    whose healthState != 0. Set include_healthy=True to dump every feature.

    Returns a JSON envelope:
      {ok, summary: {total, healthy, warning, failed}, features: [
        {path, name, classType, healthState, healthLabel, isSuppressed,
         errorOrWarningMessage}, ...
      ]}

    healthState values observed (Fusion May 2026 build):
      0 = healthy
      1 = warning (typical: stale profile reference, using cached geometry)
      2 = failed (typical: fillet could not be created at requested size)
      3 = failed (variant; also seen for fillets after major upstream changes)
    """
    comp_filter = "None" if component_name is None else json.dumps(component_name)
    include = "True" if include_healthy else "False"
    return f"""
import adsk.core
import adsk.fusion
import json

COMP_FILTER = {comp_filter}
INCLUDE_HEALTHY = {include}

HEALTH_LABELS = {{0: "healthy", 1: "warning", 2: "failed", 3: "failed"}}


def audit_comp(comp, prefix, out):
    if COMP_FILTER is not None and comp.name != COMP_FILTER:
        # Still recurse so a deep sub-component matching the filter is reachable.
        pass
    else:
        for i in range(comp.features.count):
            ft = comp.features.item(i)
            try:
                state = int(ft.healthState)
            except Exception:
                state = -1
            if state == 0 and not INCLUDE_HEALTHY:
                continue
            try:
                cls = ft.classType().split("::")[-1]
            except Exception:
                cls = "?"
            try:
                msg = ft.errorOrWarningMessage or ""
            except Exception:
                msg = ""
            try:
                supp = bool(ft.isSuppressed)
            except Exception:
                supp = False
            out.append({{
                "path": prefix + comp.name + " / " + ft.name,
                "component": comp.name,
                "name": ft.name,
                "classType": cls,
                "healthState": state,
                "healthLabel": HEALTH_LABELS.get(state, "unknown"),
                "isSuppressed": supp,
                "errorOrWarningMessage": msg[:500],
            }})
    for j in range(comp.occurrences.count):
        occ = comp.occurrences.item(j)
        if occ.component is not None:
            audit_comp(occ.component, prefix + comp.name + " / ", out)


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    out = []
    audit_comp(design.rootComponent, "", out)
    # Summary needs a separate sweep so it's always accurate even when INCLUDE_HEALTHY is False.
    # COMP_FILTER must apply to both the features list AND the summary (review fix);
    # always recurse into sub-components, but only count features in matching component(s).
    summary = {{"total": 0, "healthy": 0, "warning": 0, "failed": 0}}

    def count(comp):
        if COMP_FILTER is None or comp.name == COMP_FILTER:
            for i in range(comp.features.count):
                ft = comp.features.item(i)
                summary["total"] += 1
                try:
                    st = int(ft.healthState)
                except Exception:
                    st = -1
                if st == 0:
                    summary["healthy"] += 1
                elif st == 1:
                    summary["warning"] += 1
                elif st in (2, 3):
                    summary["failed"] += 1
        for j in range(comp.occurrences.count):
            occ = comp.occurrences.item(j)
            if occ.component is not None:
                count(occ.component)

    count(design.rootComponent)
    print(json.dumps({{
        "ok": True,
        "summary": summary,
        "features": out,
    }}))
""".strip()


# ---------- run wrappers ----------

def _run_walker(adapter: FusionAdapter, script: str, label: str) -> Envelope:
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


def bounding_box(adapter: FusionAdapter, body_name: str | None = None) -> Envelope:
    return _run_walker(adapter, build_bounding_box(body_name), "bounding_box")


def volume(adapter: FusionAdapter, body_name: str | None = None) -> Envelope:
    return _run_walker(adapter, build_volume(body_name), "volume")


def mass(adapter: FusionAdapter, body_name: str | None = None) -> Envelope:
    return _run_walker(adapter, build_mass(body_name), "mass")


def center_of_mass(adapter: FusionAdapter, body_name: str | None = None) -> Envelope:
    return _run_walker(adapter, build_center_of_mass(body_name), "center_of_mass")


def audit_feature_health(
    adapter: FusionAdapter,
    component_name: str | None = None,
    include_healthy: bool = False,
) -> Envelope:
    """Sweep the feature tree and report broken features.

    Call this as a postcondition after any tool that mutates sketch geometry,
    user parameters, or features. If summary.failed or summary.warning > 0,
    surface to the user before claiming success.
    """
    return _run_walker(
        adapter,
        build_audit_feature_health(component_name, include_healthy),
        "audit_feature_health",
    )


__all__ = [
    "audit_feature_health",
    "bounding_box",
    "build_audit_feature_health",
    "build_bounding_box",
    "build_center_of_mass",
    "build_mass",
    "build_volume",
    "center_of_mass",
    "mass",
    "volume",
]
