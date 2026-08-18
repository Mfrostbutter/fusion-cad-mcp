"""doc_state: read-only summary of the active Fusion document.

Group 1 / Document & State (V2 spec Section 4).

Direct (non-parametric) designs do not expose the parametric-only halves of
the Design API. Touching `design.userParameters` or `design.timeline` on one
raises

    RuntimeError: 3 : this is not a parametric design

which used to take the whole tool down, even though every other field was
perfectly readable. On a live direct design the original script got as far as
`root.features.count` — that one succeeded — and only died at
`design.userParameters`, so `features_count` is reported normally here and is
NOT treated as parametric-only. The generated script reports `design_type` up
front and fills only the two observed parametric-only fields through a guard
that absorbs ONLY that specific RuntimeError, recording them under
`unavailable`. Any other error still propagates, so a genuine failure is never
disguised as "direct design".
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

# Fusion's wording for the parametric-only guard. Matched on text because the
# API raises a plain RuntimeError ("3 : this is not a parametric design") with
# no distinguishable type or code attribute.
NOT_PARAMETRIC = "not a parametric design"


def fill(state, unavailable, key, getter):
    """Set state[key], or note it as unavailable on a direct design.

    Only the "not a parametric design" RuntimeError is absorbed. Anything
    else re-raises so unrelated failures surface instead of being reported
    as a missing field.
    """
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

    # Parametric-only from here down: userParameters and timeline are the two
    # APIs observed to raise on a direct design (features.count does not). A
    # direct design leaves these None and explains itself in "unavailable"
    # rather than failing the whole call.
    unavailable = {}
    fill(state, unavailable, "parameters_count", lambda: design.userParameters.count)
    fill(state, unavailable, "timeline_count", lambda: design.timeline.count)
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
