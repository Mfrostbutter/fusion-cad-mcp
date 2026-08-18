"""doc_state: read-only summary of the active Fusion document.

Group 1 / Document & State (V2 spec Section 4).

A direct (non-parametric) design raises on `design.userParameters` and
`design.timeline`. Those two are read behind a guard and come back None under
`unavailable`; every other field, `features_count` included, reads normally.
"""

from __future__ import annotations

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json


def build() -> str:
    """Return the Python script that introspects the active document."""
    return '''
import adsk.core
import adsk.fusion
import json

# Matched on text: Fusion raises a plain RuntimeError with no code attribute.
NOT_PARAMETRIC = "not a parametric design"


def _fill(state, unavailable, key, getter):
    """Set state[key], or mark it unavailable on a direct design."""
    try:
        state[key] = getter()
    except RuntimeError as exc:
        if NOT_PARAMETRIC not in str(exc):
            raise
        state[key] = None
        unavailable[key] = "requires a parametric design"


def run(_ctx):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)

    if design is None:
        print(json.dumps({"active_design": False}))
        return

    root = design.rootComponent
    ui = app.userInterface
    is_parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
    state = {
        "active_design": True,
        "design_type": "parametric" if is_parametric else "direct",
        "is_parametric": is_parametric,
        "doc_name": doc.name if doc else None,
        "is_dirty": doc.isModified if doc else None,
        "workspace": ui.activeWorkspace.name if ui and ui.activeWorkspace else None,
        "units": design.unitsManager.defaultLengthUnits,
        "bodies_count": root.bRepBodies.count,
        "sketches_count": root.sketches.count,
        "features_count": root.features.count,
        "components_count": root.allOccurrences.count,
    }

    # Parametric-only: these two raise on a direct design, features.count does not.
    unavailable = {}
    _fill(state, unavailable, "parameters_count", lambda: design.userParameters.count)
    _fill(state, unavailable, "timeline_count", lambda: design.timeline.count)
    state["unavailable"] = unavailable

    print(json.dumps(state))
'''.strip()


def run(adapter: FusionAdapter) -> Envelope:
    """Execute doc_state against Fusion. Returns Envelope with the parsed state in result."""
    env = adapter.execute_script(build())
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="doc_state_parse_failed", message=env.message)
    return Envelope(ok=True, message=env.message, result=parsed)
