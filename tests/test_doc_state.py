"""Tier 1a: script generator snapshot test for doc_state. No Fusion required."""

from __future__ import annotations

import json

import pytest

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import doc_state


def test_build_returns_valid_python():
    """Generator must produce parseable Python that defines run()."""
    import ast

    src = doc_state.build()
    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run"]
    assert len(funcs) == 1, "doc_state script must define exactly one run() function"
    # run must take one positional arg per Fusion MCP contract
    assert len(funcs[0].args.args) == 1


def test_build_imports_required_modules():
    src = doc_state.build()
    assert "import adsk.core" in src
    assert "import adsk.fusion" in src
    assert "import json" in src


def test_build_handles_no_active_design():
    src = doc_state.build()
    assert '"active_design": False' in src or "'active_design': False" in src


# ---------- generated-script behaviour, executed against a stub adsk ----------
#
# doc_state's whole failure mode lives inside the script Fusion runs, not in
# the wrapper: a direct design raises RuntimeError("3 : this is not a
# parametric design") the moment userParameters/timeline is touched. A static
# assertion on the source cannot tell whether the guard actually catches it,
# so the script is exec'd against a minimal stub of the adsk modules.
#
# The stub deliberately keeps root.features.count readable on a direct design:
# that matches live Fusion, where the original script evaluated features.count
# successfully and only failed at design.userParameters.

PARAMETRIC = 1
DIRECT = 0


class _Coll:
    def __init__(self, count):
        self._count = count

    @property
    def count(self):
        if isinstance(self._count, Exception):
            raise self._count
        return self._count


class _StubDesign:
    def __init__(self, design_type, *, params_error=None, units="mm"):
        self.designType = design_type
        parametric = design_type == PARAMETRIC
        err = RuntimeError("3 : this is not a parametric design")
        self.userParameters = _Coll(params_error or (4 if parametric else err))
        self.timeline = _Coll(7 if parametric else err)
        self.unitsManager = type("U", (), {"defaultLengthUnits": units})()
        self.rootComponent = type(
            "Root",
            (),
            {
                "bRepBodies": _Coll(3),
                "sketches": _Coll(1),
                "allOccurrences": _Coll(2),
                # Readable in both modes — features.count is not parametric-only.
                "features": _Coll(5),
            },
        )()


def _exec_script(design):
    """Run the generated script against a stub adsk and return the printed JSON."""
    import contextlib
    import io as _io
    import sys
    import types

    adsk = types.ModuleType("adsk")
    core = types.ModuleType("adsk.core")
    fusion = types.ModuleType("adsk.fusion")
    adsk.core = core
    adsk.fusion = fusion

    doc = type("Doc", (), {"name": "Part1", "isModified": True})()
    ui = type("UI", (), {"activeWorkspace": type("W", (), {"name": "FusionSolid"})()})()
    app = type("App", (), {"activeDocument": doc, "userInterface": ui, "activeProduct": design})()
    core.Application = type("Application", (), {"get": staticmethod(lambda: app)})
    fusion.Design = type("Design", (), {"cast": staticmethod(lambda product: product)})
    fusion.DesignTypes = type(
        "DesignTypes", (), {"ParametricDesignType": PARAMETRIC, "DirectDesignType": DIRECT}
    )

    ns: dict = {}
    buf = _io.StringIO()
    saved = {k: sys.modules.get(k) for k in ("adsk", "adsk.core", "adsk.fusion")}
    sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
    try:
        exec(compile(doc_state.build(), "<doc_state>", "exec"), ns)
        with contextlib.redirect_stdout(buf):
            ns["run"](None)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return json.loads(buf.getvalue())


def test_script_reports_parametric_design_fully():
    state = _exec_script(_StubDesign(PARAMETRIC))
    assert state["active_design"] is True
    assert state["design_type"] == "parametric"
    assert state["is_parametric"] is True
    assert state["parameters_count"] == 4
    assert state["timeline_count"] == 7
    assert state["features_count"] == 5
    assert state["unavailable"] == {}
    assert state["bodies_count"] == 3


def test_script_returns_partial_state_on_direct_design():
    """The bug: userParameters/timeline raise, and used to kill the whole call."""
    state = _exec_script(_StubDesign(DIRECT))
    assert state["design_type"] == "direct"
    assert state["is_parametric"] is False

    # Everything non-parametric is still reported.
    assert state["bodies_count"] == 3
    assert state["sketches_count"] == 1
    assert state["components_count"] == 2
    assert state["units"] == "mm"
    assert state["doc_name"] == "Part1"
    assert state["workspace"] == "FusionSolid"

    # features.count works on a direct design (observed live), so it stays
    # populated and must not be listed as unavailable.
    assert state["features_count"] == 5
    assert "features_count" not in state["unavailable"]

    # Parametric-only fields are present-but-null and explained.
    for key in ("parameters_count", "timeline_count"):
        assert state[key] is None
        assert key in state["unavailable"]


def test_script_does_not_swallow_unrelated_errors():
    """A non-parametric guard must not double as a blanket except."""
    design = _StubDesign(PARAMETRIC, params_error=RuntimeError("5 : object is invalid"))
    with pytest.raises(RuntimeError, match="object is invalid"):
        _exec_script(design)


def test_script_reports_no_active_design():
    state = _exec_script(None)
    assert state == {"active_design": False}


def test_run_parses_well_formed_response(monkeypatch):
    """run() should extract the doc state from the adapter's envelope into result."""

    class FakeAdapter:
        def execute_script(self, script: str) -> Envelope:
            return Envelope(
                ok=True,
                message=json.dumps(
                    {
                        "active_design": True,
                        "doc_name": "Untitled",
                        "is_dirty": False,
                        "workspace": "FusionSolidEnvironment",
                        "units": "mm",
                        "bodies_count": 3,
                        "sketches_count": 1,
                        "features_count": 5,
                        "components_count": 0,
                        "parameters_count": 4,
                    }
                ),
            )

    env = doc_state.run(FakeAdapter())
    assert env.ok is True
    assert env.result is not None
    assert env.result["bodies_count"] == 3
    assert env.result["units"] == "mm"


def test_run_passes_direct_design_state_through():
    """A direct-design payload is a success, not an error, and keeps `unavailable`."""

    class FakeAdapter:
        def execute_script(self, script: str) -> Envelope:
            return Envelope(
                ok=True,
                message=json.dumps(
                    {
                        "active_design": True,
                        "design_type": "direct",
                        "is_parametric": False,
                        "bodies_count": 2,
                        "parameters_count": None,
                        "timeline_count": None,
                        "features_count": None,
                        "unavailable": {"parameters_count": "requires a parametric design"},
                    }
                ),
            )

    env = doc_state.run(FakeAdapter())
    assert env.ok is True
    assert env.result["design_type"] == "direct"
    assert env.result["bodies_count"] == 2
    assert env.result["parameters_count"] is None
    assert "parameters_count" in env.result["unavailable"]


def test_run_surfaces_adapter_error_unchanged():
    class FakeAdapter:
        def execute_script(self, script: str) -> Envelope:
            return Envelope(ok=False, error="fusion_error", traceback="...")

    env = doc_state.run(FakeAdapter())
    assert env.ok is False
    assert env.error == "fusion_error"


def test_run_handles_unparseable_stdout():
    class FakeAdapter:
        def execute_script(self, script: str) -> Envelope:
            return Envelope(ok=True, message="not json at all")

    env = doc_state.run(FakeAdapter())
    assert env.ok is False
    assert env.error == "doc_state_parse_failed"
