"""doc_state: read-only summary of the active Fusion document.

Group 1 / Document & State (V2 spec Section 4).
"""

from __future__ import annotations

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json


def build() -> str:
    """Return the Python script that introspects the active document."""
    return """
import adsk.core
import adsk.fusion
import json


def run(_ctx):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)

    if design is None:
        print(json.dumps({"active_design": False}))
        return

    root = design.rootComponent
    ui = app.userInterface
    state = {
        "active_design": True,
        "doc_name": doc.name if doc else None,
        "is_dirty": doc.isModified if doc else None,
        "workspace": ui.activeWorkspace.name if ui and ui.activeWorkspace else None,
        "units": design.unitsManager.defaultLengthUnits,
        "bodies_count": root.bRepBodies.count,
        "sketches_count": root.sketches.count,
        "features_count": root.features.count,
        "components_count": root.allOccurrences.count,
        "parameters_count": design.userParameters.count,
    }
    print(json.dumps(state))
""".strip()


def run(adapter: FusionAdapter) -> Envelope:
    """Execute doc_state against Fusion. Returns Envelope with the parsed state in result."""
    env = adapter.execute_script(build())
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="doc_state_parse_failed", message=env.message)
    return Envelope(ok=True, message=env.message, result=parsed)
