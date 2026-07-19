"""Tier 1a snapshot tests + Tier 1c validation tests for parameter tools."""

from __future__ import annotations

import ast
import json
from typing import Any

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import parameters as p


# ---------- generator snapshots (Tier 1a) ----------

def test_build_add_is_valid_python():
    src = p.build_add([{"name": "length", "expression": "100 mm", "units": "mm", "comment": ""}])
    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run"]
    assert len(funcs) == 1
    assert len(funcs[0].args.args) == 1


def test_build_add_embeds_defs_as_json():
    defs = [{"name": "width", "expression": "50 mm", "units": "mm", "comment": "the width"}]
    src = p.build_add(defs)
    # The exact JSON encoding must appear in the script literal
    assert json.dumps(defs) in src


def test_build_add_uses_itemByName_for_idempotency():
    src = p.build_add([{"name": "h", "expression": "20 mm"}])
    assert "itemByName" in src
    assert "params.add(" in src


def test_build_update_is_valid_python():
    src = p.build_update("length", "120 mm")
    ast.parse(src)
    assert '"length"' in src
    assert '"120 mm"' in src


def test_build_update_quotes_safely():
    """Names and expressions containing quotes must round-trip without breaking the script."""
    src = p.build_update("tricky_name", 'thickness * 2.0 + 0 mm')
    # Should parse fine
    ast.parse(src)


def test_build_list_is_valid_python():
    src = p.build_list()
    ast.parse(src)
    assert "userParameters" in src


# ---------- validation gates (Tier 1c) ----------

def test_reserved_math_name_is_rejected():
    """pi/sin/sqrt as param names is a footgun; we block at generation."""
    for bad in ("pi", "e", "sin", "cos", "sqrt", "log"):
        ok, err = p._validate_param_defs([{"name": bad, "expression": "1 mm"}])
        assert ok is False, f"{bad!r} should have been rejected"
        assert err and bad in err


def test_empty_defs_rejected():
    ok, err = p._validate_param_defs([])
    assert ok is False


def test_missing_expression_rejected():
    ok, err = p._validate_param_defs([{"name": "length"}])
    assert ok is False
    assert err and "expression" in err


def test_numeric_leading_name_rejected():
    ok, err = p._validate_param_defs([{"name": "2bad", "expression": "1 mm"}])
    assert ok is False


def test_valid_def_passes():
    ok, _ = p._validate_param_defs([{"name": "length", "expression": "100 mm", "units": "mm", "comment": ""}])
    assert ok is True


# ---------- run wrappers with mock adapter ----------

class FakeAdapter:
    def __init__(self, message: str = '{"ok": true, "added": [], "skipped": []}'):
        self.scripts: list[str] = []
        self.message = message

    def execute_script(self, script: str) -> Envelope:
        self.scripts.append(script)
        return Envelope(ok=True, message=self.message)


def test_add_parameters_short_circuits_on_bad_def():
    a = FakeAdapter()
    env = p.add_parameters(a, [{"name": "pi", "expression": "3.14"}])
    assert env.ok is False
    assert env.error == "invalid_defs"
    assert a.scripts == [], "no Fusion call should happen when validation fails"


def test_add_parameters_passes_through_on_success():
    a = FakeAdapter(message=json.dumps({"ok": True, "added": [{"name": "h"}], "skipped": [], "total_params": 1}))
    env = p.add_parameters(a, [{"name": "h", "expression": "20 mm"}])
    assert env.ok is True
    assert env.result is not None
    assert env.result["added"] == [{"name": "h"}]


def test_update_parameter_rejects_empty_name():
    a = FakeAdapter()
    env = p.update_parameter(a, "", "100 mm")
    assert env.ok is False
    assert env.error == "invalid_name"
    assert a.scripts == []


def test_update_parameter_returns_param_not_found_from_fusion():
    a = FakeAdapter(message=json.dumps({"ok": False, "error": "param_not_found", "name": "missing"}))
    env = p.update_parameter(a, "missing", "100 mm")
    assert env.ok is False
    assert env.error == "param_not_found"


def test_list_parameters_parses_param_list():
    payload = {
        "ok": True,
        "count": 2,
        "parameters": [
            {"name": "length", "expression": "100 mm", "value": 10.0, "units": "mm", "comment": ""},
            {"name": "width", "expression": "50 mm", "value": 5.0, "units": "mm", "comment": ""},
        ],
    }
    a = FakeAdapter(message=json.dumps(payload))
    env = p.list_parameters(a)
    assert env.ok is True
    assert env.result is not None
    assert env.result["count"] == 2
