"""V2-spec result envelope for tool returns.

Every tool returns the same envelope shape so agents have one parsing contract.
Every tool returns this shape so clients have one parsing contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Envelope:
    """The single result envelope all tools return."""

    ok: bool
    message: str = ""
    result: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    image: dict[str, Any] | None = None  # {data: <base64>, mime_type: "image/png"}
    error: str | None = None
    traceback: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None or k == "ok"}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def from_fusion_response(raw: dict[str, Any]) -> Envelope:
    """Translate the raw Fusion MCP tools/call response into our envelope.

    Fusion's response shape (observed in the 2026-05-31 spike):
        {
          "id": <int>,
          "jsonrpc": "2.0",
          "result": {
            "content": [{"type": "text", "text": "<json-encoded inner>"}]
          }
        }

    The inner text payload is JSON with at minimum:
        { "message": "<stdout>", "success": true | false, "error"?: "...", "traceback"?: "..." }
    """
    # Transport-level JSON-RPC error (the request itself failed)
    if "error" in raw:
        rpc_err = raw["error"]
        return Envelope(
            ok=False,
            error=rpc_err.get("message", "jsonrpc_error"),
            result={"code": rpc_err.get("code")},
        )

    result = raw.get("result")
    if not isinstance(result, dict):
        return Envelope(ok=False, error="missing_result", message=json.dumps(raw)[:500])

    content = result.get("content")
    if not isinstance(content, list) or not content:
        return Envelope(ok=False, error="empty_content")

    first = content[0]
    if not isinstance(first, dict):
        return Envelope(ok=False, error="unexpected_content_type", result={"content": content})

    ctype = first.get("type")

    # Image responses (e.g. fusion_mcp_read screenshot) come through here
    if ctype == "image":
        return Envelope(
            ok=True,
            image={"data": first.get("data", ""), "mime_type": first.get("mimeType", "")},
        )

    if ctype != "text":
        return Envelope(ok=False, error="unexpected_content_type", result={"content": content})

    text = first.get("text", "")

    # Try to parse the inner JSON payload
    try:
        inner = json.loads(text)
    except json.JSONDecodeError:
        return Envelope(ok=False, error="inner_not_json", message=text)

    if not isinstance(inner, dict):
        return Envelope(ok=True, message=text, result={"raw": inner})

    success = inner.get("success", True)
    message = inner.get("message", "")

    if success is False:
        return Envelope(
            ok=False,
            error=inner.get("error") or "fusion_error",
            message=message,
            traceback=inner.get("traceback"),
        )

    return Envelope(ok=True, message=message, result=inner)


def parse_stdout_json(envelope: Envelope) -> dict[str, Any] | None:
    """Many tools print their result as a single JSON line on stdout.

    Returns the parsed dict, or None if the message is not JSON.
    """
    if not envelope.ok or not envelope.message:
        return None
    msg = envelope.message.strip()
    if not msg.startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(msg)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


# Re-export for convenience
__all__ = ["Envelope", "from_fusion_response", "parse_stdout_json"]
