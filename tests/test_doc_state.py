"""Tier 1a: script generator snapshot test for doc_state. No Fusion required."""

from __future__ import annotations

import json

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
