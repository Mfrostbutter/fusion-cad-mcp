"""Adapter: HTTP MCP client to Autodesk Fusion's listener at 127.0.0.1:27182/mcp.

Speaks MCP Streamable HTTP transport (protocol 2025-06-18). Holds one session for
the lifetime of the adapter and re-handshakes once when Fusion rejects it with a
4xx, which is what a Fusion restart looks like from this side.

Talking to Fusion's own MCP over HTTP was chosen over an in-process add-in so
the server can run in any Python environment and survive Fusion restarts.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx

from . import __version__
from .envelope import Envelope, from_fusion_response

DEFAULT_URL = "http://127.0.0.1:27182/mcp"
DEFAULT_TIMEOUT = 60.0
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "fusion-cad-mcp"


class AdapterError(RuntimeError):
    """Raised when the adapter cannot reach Fusion or the handshake fails."""


class FusionAdapter:
    """Synchronous HTTP MCP client to Fusion."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._session_id: str | None = None
        self._initialized = False
        self._id_counter = itertools.count(1)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FusionAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- low-level transport ----

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _next_id(self) -> int:
        return next(self._id_counter)

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(self.url, json=payload, headers=self._headers())
        except httpx.ConnectError as e:
            raise AdapterError(
                f"Cannot reach Fusion MCP at {self.url}. "
                f"Is Fusion running with Preferences > General > API > Fusion MCP Server enabled?"
            ) from e

    # ---- MCP handshake ----

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": __version__},
            },
        }
        r = self._post(init_payload)
        if r.status_code != 200:
            raise AdapterError(f"initialize failed: {r.status_code} {r.text[:200]}")

        self._session_id = r.headers.get("Mcp-Session-Id")
        if not self._session_id:
            raise AdapterError("initialize succeeded but no Mcp-Session-Id header returned")

        # Send the required notifications/initialized; expect 202 with no body
        notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        r2 = self._post(notify)
        if r2.status_code != 202:
            raise AdapterError(
                f"notifications/initialized failed: {r2.status_code} {r2.text[:200]}"
            )

        self._initialized = True

    # ---- public surface ----

    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        r = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
            }
        )
        r.raise_for_status()
        data = r.json()
        return data.get("result", {}).get("tools", [])

    def _reset_session(self) -> None:
        """Forget the current session so the next call re-handshakes."""
        self._session_id = None
        self._initialized = False

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a Fusion MCP tool by name. Returns the raw JSON-RPC response dict.

        Retries once on a stale session. Restarting Fusion invalidates the
        session id while this process keeps sending the dead one, and Fusion
        answers 4xx forever after. Recovering here means a Fusion restart no
        longer requires restarting the MCP server.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        self._ensure_initialized()
        r = self._post(payload)

        # 4xx here means Fusion rejected the session, not the request: the
        # payload was accepted once already. 5xx is a Fusion-side fault and
        # retrying would just repeat it.
        if 400 <= r.status_code < 500:
            self._reset_session()
            self._ensure_initialized()
            payload["id"] = self._next_id()
            r = self._post(payload)

        r.raise_for_status()
        return r.json()

    def execute_script(self, script: str) -> Envelope:
        """Run a Python script in Fusion. Returns the V2-spec envelope."""
        raw = self.call_tool(
            "fusion_mcp_execute",
            {"featureType": "script", "object": {"script": script}},
        )
        return from_fusion_response(raw)

    def execute_document_op(self, operation: str, **object_args: Any) -> Envelope:
        """Run a document-level op: save, close, open. See Fusion MCP schema."""
        obj = {"operation": operation, **object_args}
        raw = self.call_tool(
            "fusion_mcp_execute",
            {"featureType": "document", "object": obj},
        )
        return from_fusion_response(raw)

    def read_query(self, query_type: str, **kwargs: Any) -> Envelope:
        """Run a fusion_mcp_read query: document, projects, screenshot, apiDocumentation."""
        payload: dict[str, Any] = {"queryType": query_type, **kwargs}
        raw = self.call_tool("fusion_mcp_read", payload)
        return from_fusion_response(raw)

    def update(self, kind: str) -> Envelope:
        """Run undo or redo."""
        if kind not in {"undo", "redo"}:
            raise ValueError(f"update kind must be undo or redo, got {kind!r}")
        raw = self.call_tool("fusion_mcp_update", {"featureType": kind})
        return from_fusion_response(raw)
