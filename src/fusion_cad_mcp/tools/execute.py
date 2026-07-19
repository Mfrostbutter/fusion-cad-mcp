"""execute: raw script passthrough (escape hatch per V2 spec Section 4 Group 7)."""

from __future__ import annotations

from ..adapter import FusionAdapter
from ..envelope import Envelope


def run(adapter: FusionAdapter, script: str) -> Envelope:
    """Pass the script straight through to Fusion. No validation, no wrapping."""
    return adapter.execute_script(script)
