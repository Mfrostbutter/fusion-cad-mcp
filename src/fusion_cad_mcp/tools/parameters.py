"""Group 2 / parameter tools.

Three tools that bracket every Sketch and Feature workflow:
- add_parameters: idempotent bulk add (won't replace existing)
- update_parameter: change the expression on an existing param
- list_parameters: enumerate with resolved values

All three are pure scripts wrapped by the adapter. Math-name guard per
patterns.md: reserved names like sin/cos/pi/e/sqrt MUST NOT be used as param
names; the script rejects those at generation time.

Parameters added by these tools bind correctly to both feature inputs
(via ValueInput.createByString) and sketch dimensions (via
dim.parameter.expression). Parametric sketches work; the lock-badge display
lag documented in gotchas.md G9 is cosmetic only.
"""

from __future__ import annotations

import json
from typing import Any

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

# Names Fusion treats as math identifiers in expressions. Using these as user-param
# names creates expressions that look correct but evaluate to the math function
# instead of the parameter value. The skill caught this the hard way; we block at
# generation time so it never reaches Fusion.
RESERVED_MATH_NAMES = frozenset(
    [
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh",
        "abs", "sqrt", "exp", "log", "ln", "log10",
        "min", "max", "round", "floor", "ceil",
        "pi", "e",
    ]
)


def _validate_param_defs(defs: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Validate the shape of the defs list. Returns (ok, error_message)."""
    if not isinstance(defs, list):
        return False, "defs must be a list"
    if not defs:
        return False, "defs must be non-empty"
    for i, d in enumerate(defs):
        if not isinstance(d, dict):
            return False, f"defs[{i}] must be an object"
        name = d.get("name")
        expr = d.get("expression")
        if not isinstance(name, str) or not name:
            return False, f"defs[{i}].name must be a non-empty string"
        if not isinstance(expr, str) or not expr:
            return False, f"defs[{i}].expression must be a non-empty string"
        if name in RESERVED_MATH_NAMES:
            return False, (
                f"defs[{i}].name {name!r} is a reserved math identifier; "
                "Fusion will interpret expressions referencing it as the math function"
            )
        if not (name[0].isalpha() or name[0] == "_"):
            return False, f"defs[{i}].name {name!r} must start with a letter or underscore"
    return True, None


def build_add(defs: list[dict[str, Any]]) -> str:
    """Generate the Python script for an idempotent add_parameters operation.

    Each def is {name, expression, units?, comment?}. Existing params are skipped
    (not overwritten); use update_parameter for in-place edits.
    """
    # The defs are JSON-encoded into the script so the script is self-contained
    # and depends on no out-of-band state.
    encoded = json.dumps(defs)
    return f"""
import adsk.core
import adsk.fusion
import json


PARAM_DEFS = {encoded}


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    params = design.userParameters

    added = []
    skipped = []
    for d in PARAM_DEFS:
        name = d["name"]
        expression = d["expression"]
        units = d.get("units", "")
        comment = d.get("comment", "")
        existing = params.itemByName(name)
        if existing is not None:
            skipped.append({{"name": name, "current_expression": existing.expression}})
            continue
        params.add(name, adsk.core.ValueInput.createByString(expression), units, comment)
        added.append({{"name": name, "expression": expression}})

    print(json.dumps({{"ok": True, "added": added, "skipped": skipped, "total_params": params.count}}))
""".strip()


def build_update(name: str, expression: str) -> str:
    """Generate the script for updating one parameter's expression."""
    return f"""
import adsk.core
import adsk.fusion
import json

NAME = {json.dumps(name)}
EXPRESSION = {json.dumps(expression)}


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    param = design.userParameters.itemByName(NAME)
    if param is None:
        print(json.dumps({{"ok": False, "error": "param_not_found", "name": NAME}}))
        return
    before = param.expression
    param.expression = EXPRESSION
    print(json.dumps({{
        "ok": True,
        "name": NAME,
        "before": before,
        "after": param.expression,
        "value": param.value,
    }}))
""".strip()


def build_list() -> str:
    """Generate the script for listing all user parameters with resolved values."""
    return """
import adsk.core
import adsk.fusion
import json


def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({"ok": False, "error": "no_active_design"}))
        return
    out = []
    for i in range(design.userParameters.count):
        p = design.userParameters.item(i)
        out.append({
            "name": p.name,
            "expression": p.expression,
            "value": p.value,
            "units": p.unit,
            "comment": p.comment,
        })
    print(json.dumps({"ok": True, "parameters": out, "count": len(out)}))
""".strip()


# ---------- run wrappers ----------

def add_parameters(adapter: FusionAdapter, defs: list[dict[str, Any]]) -> Envelope:
    ok, err = _validate_param_defs(defs)
    if not ok:
        return Envelope(ok=False, error="invalid_defs", message=err or "")
    env = adapter.execute_script(build_add(defs))
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="parse_failed", message=env.message)
    if parsed.get("ok") is False:
        return Envelope(ok=False, error=parsed.get("error", "fusion_error"), message=env.message)
    return Envelope(ok=True, message=env.message, result=parsed)


def update_parameter(adapter: FusionAdapter, name: str, expression: str) -> Envelope:
    if not name or not isinstance(name, str):
        return Envelope(ok=False, error="invalid_name", message="name must be a non-empty string")
    if not expression or not isinstance(expression, str):
        return Envelope(ok=False, error="invalid_expression", message="expression must be a non-empty string")
    env = adapter.execute_script(build_update(name, expression))
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="parse_failed", message=env.message)
    if parsed.get("ok") is False:
        return Envelope(ok=False, error=parsed.get("error", "fusion_error"), message=env.message, result=parsed)
    return Envelope(ok=True, message=env.message, result=parsed)


def list_parameters(adapter: FusionAdapter) -> Envelope:
    env = adapter.execute_script(build_list())
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="parse_failed", message=env.message)
    if parsed.get("ok") is False:
        return Envelope(ok=False, error=parsed.get("error", "fusion_error"), message=env.message)
    return Envelope(ok=True, message=env.message, result=parsed)


__all__ = [
    "RESERVED_MATH_NAMES",
    "add_parameters",
    "build_add",
    "build_list",
    "build_update",
    "list_parameters",
    "update_parameter",
]
