"""Pure script generators + thin tool wrappers.

Each tool follows the V2-spec split:
  - `build(...)` returns a Python script string (pure, no Fusion access, unit-testable).
  - `run(adapter, ...)` calls build, hands the script to the adapter, returns an Envelope.

This split is what makes Tier 1a (CI, no Fusion) testing possible.
"""
