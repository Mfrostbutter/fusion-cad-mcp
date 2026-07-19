"""Entity handle scaffolding per V2 spec Section 5a.

Format: `kind:path:token` where token comes from Fusion's `entityToken` property.
The path component is human-readable for debug; the token is the machine resolver.

Lifecycle:
- Entity-producing tools (create_sketch, extrude, fillet, etc.) include handles
  in their result envelope under `state.handles_added`. The script captures
  entity.entityToken from Fusion at run time and emits the handle string.
- Entity-consuming tools (measure, ray methods, fillet_edges UI sel, etc.)
  accept handle strings as inputs. The generator parses the handle and emits
  a `Design.findEntityByToken(token)` call to resolve the live entity.
- Invalidation: handles for entities deleted by undo or feature edits return
  a structured `handle_invalid` error from any consuming tool.

Kinds (V2 spec Section 5a):
    sketch, profile, body, face, edge, vertex, feature, component, occurrence,
    param, joint, ucs, plane, axis, point
"""

from __future__ import annotations

import json
import re

VALID_KINDS = frozenset({
    "sketch", "profile", "body", "face", "edge", "vertex",
    "feature", "component", "occurrence", "param", "joint",
    "ucs", "plane", "axis", "point",
})

# token: alphanumeric, +, /, =, _, -, . (entityToken is base64-ish + some symbols)
_HANDLE_RE = re.compile(r"^([a-z][a-z_]*):([^:]*):([A-Za-z0-9+/=_\-.]+)$")


def parse_handle(s: str) -> dict[str, str]:
    """Parse 'kind:path:token' into {kind, path, token}. Raises ValueError on malformed."""
    if not isinstance(s, str):
        raise ValueError(f"handle must be a string, got {type(s).__name__}")
    m = _HANDLE_RE.match(s)
    if not m:
        raise ValueError(f"malformed handle: {s!r}")
    kind, path, token = m.group(1), m.group(2), m.group(3)
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown handle kind {kind!r} in {s!r}")
    return {"kind": kind, "path": path, "token": token}


def is_handle(s: str) -> bool:
    """Cheap probe: does this look like a handle? Useful for tools accepting either name or handle."""
    if not isinstance(s, str):
        return False
    return bool(_HANDLE_RE.match(s))


def emit_resolve(handle_str: str, var: str = "_entity", fail_var: str = "_handle_invalid") -> str:
    """Emit Python that resolves a handle to a live Fusion entity, assigning to `var`.

    On resolution failure, the script must `print(json.dumps(...)); return` immediately —
    callers compose this into their generator output.

    The emitted code expects `design` and `json` to be in scope. It assigns the resolved
    entity to `var`. If resolution fails, it emits a structured error block; the caller
    can catch by checking `{var}` for None.
    """
    h = parse_handle(handle_str)
    return (
        f"_h_token = {json.dumps(h['token'])}\n"
        f"_h_str = {json.dumps(handle_str)}\n"
        f"_found = design.findEntityByToken(_h_token)\n"
        f"if not _found:\n"
        f"    print(json.dumps({{'ok': False, 'error': 'handle_invalid',"
        f" 'detail': {{'handle': _h_str, 'reason': 'not_found_in_active_doc'}}}}));\n"
        f"    return\n"
        # Fusion's findEntityByToken returns a BaseVector (SWIG-wrapped
        # std::vector), not a Python list. BaseVector is indexable via [0]
        # and supports len() but has none of .item/.count/.classType. Lists
        # and tuples also satisfy len()+[0]. Bare entities (rare) don't.
        f"{var} = _found[0] if hasattr(_found, '__len__') else _found\n"
    )


def emit_resolve_many(handles: list[str], collection_var: str = "_resolved") -> str:
    """Emit Python that resolves a list of handles into a Python list, with per-handle failure."""
    lines = [f"{collection_var} = []\n"]
    for i, h in enumerate(handles):
        parsed = parse_handle(h)
        var = f"_h{i}"
        lines.append(
            f"_h{i}_token = {json.dumps(parsed['token'])}\n"
            f"_h{i}_found = design.findEntityByToken(_h{i}_token)\n"
            f"if not _h{i}_found:\n"
            f"    print(json.dumps({{'ok': False, 'error': 'handle_invalid',"
            f" 'detail': {{'handle': {json.dumps(h)}, 'reason': 'not_found_in_active_doc'}}}}));\n"
            f"    return\n"
            f"{var} = _h{i}_found[0] if hasattr(_h{i}_found, '__len__') else _h{i}_found\n"
            f"{collection_var}.append({var})\n"
        )
    return "".join(lines)


def emit_make_handle(kind: str, path_expr: str, entity_expr: str) -> str:
    """Emit a Python expression that builds a handle string at script run time.

    path_expr and entity_expr are Python expressions evaluated in the script (e.g.
    `sk.name` for path, `sk` for the entity itself). Returns a string expression
    that can be used inside the script (e.g. `state['handle'] = <this>`).

    Example:
        emit_make_handle('sketch', 'sk.name', 'sk')
        -> f"'sketch:' + sk.name + ':' + sk.entityToken"
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown handle kind {kind!r}")
    return f"({json.dumps(kind)} + ':' + str({path_expr}) + ':' + {entity_expr}.entityToken)"


__all__ = [
    "VALID_KINDS",
    "emit_make_handle",
    "emit_resolve",
    "emit_resolve_many",
    "is_handle",
    "parse_handle",
]
