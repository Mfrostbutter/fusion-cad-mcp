"""handles.py module: parse + emit helpers."""

import pytest

from fusion_cad_mcp import handles as h


def test_parse_handle_basic():
    parsed = h.parse_handle("body:plate_v3:abc123")
    assert parsed == {"kind": "body", "path": "plate_v3", "token": "abc123"}


def test_parse_handle_path_can_have_slashes_and_indices():
    parsed = h.parse_handle("edge:plate_v3/edge[7]:xyz==")
    assert parsed["kind"] == "edge"
    assert parsed["path"] == "plate_v3/edge[7]"
    assert parsed["token"] == "xyz=="


def test_parse_handle_empty_path_ok():
    parsed = h.parse_handle("face::tokenonly")
    assert parsed["path"] == ""
    assert parsed["token"] == "tokenonly"


def test_parse_handle_rejects_unknown_kind():
    with pytest.raises(ValueError):
        h.parse_handle("widget:foo:bar")


def test_parse_handle_rejects_malformed():
    with pytest.raises(ValueError):
        h.parse_handle("not_a_handle")
    with pytest.raises(ValueError):
        h.parse_handle("body:no_token")
    with pytest.raises(ValueError):
        h.parse_handle("")


def test_is_handle_true_for_well_formed():
    assert h.is_handle("body:plate:tok")
    assert h.is_handle("edge:body/edge[0]:tok==")


def test_is_handle_false_for_garbage():
    assert not h.is_handle("plate_v3")
    assert not h.is_handle("")
    assert not h.is_handle(None)


def test_emit_resolve_includes_token_and_error_block():
    src = h.emit_resolve("body:plate:abc")
    assert '"abc"' in src
    assert "findEntityByToken" in src
    assert "handle_invalid" in src
    # The unwrap must handle Fusion's BaseVector (SWIG std::vector wrapper)
    # which returns from findEntityByToken for face/edge/vertex handles.
    # BaseVector is indexable via [0] and has len(); we test len-presence as
    # the unwrap signal. Bare entities (rare) lack __len__ and pass through.
    assert "hasattr(_found, '__len__')" in src
    assert "_found[0]" in src


def test_emit_resolve_unwraps_basevector():
    """Regression: findEntityByToken returns a BaseVector for face/edge handles.
    The previous resolver used `isinstance(_found, list)` which is False for
    BaseVector, so the whole vector got passed to JointGeometry and Fusion
    rejected it with a confusing typing error. Verify the new len-based unwrap
    works for any indexable container."""
    src = h.emit_resolve("face:plate:tok")
    # The unwrap must use hasattr(_found, '__len__') so BaseVector + list + tuple
    # all flow through the same indexed path. isinstance(list) alone would miss
    # BaseVector.
    assert "isinstance(_found, list)" not in src
    assert "hasattr(_found, '__len__')" in src


def test_emit_resolve_many_indexes_helpers():
    src = h.emit_resolve_many(["edge:body/edge[0]:t1", "edge:body/edge[1]:t2"])
    assert '"t1"' in src
    assert '"t2"' in src
    assert "_h0" in src and "_h1" in src
    assert "_resolved.append" in src


def test_emit_make_handle_builds_runtime_expression():
    expr = h.emit_make_handle("body", "b.name", "b")
    # Should produce code that concatenates kind + path + token at run time
    assert ("'body'" in expr) or ('"body"' in expr)
    assert "b.name" in expr
    assert "b.entityToken" in expr


def test_emit_make_handle_rejects_unknown_kind():
    with pytest.raises(ValueError):
        h.emit_make_handle("widget", "x.name", "x")
