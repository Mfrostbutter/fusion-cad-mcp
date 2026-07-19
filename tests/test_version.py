"""The declared version must agree with the packaged one.

`__version__` is sent to Fusion in the MCP handshake as clientInfo, and
pyproject's version is what ends up on the wheel. They are edited in different
files, so they drift, and a drifted version makes a bug report point at the
wrong build.
"""

from __future__ import annotations

import re
from pathlib import Path

import fusion_cad_mcp

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str | None:
    if not PYPROJECT.exists():
        return None
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def test_package_version_matches_pyproject():
    declared = _declared_version()
    if declared is None:
        import pytest

        pytest.skip("pyproject.toml not available; running outside a checkout")

    assert fusion_cad_mcp.__version__ == declared, (
        f"__init__.py says {fusion_cad_mcp.__version__!r} but pyproject.toml "
        f"says {declared!r}. Update both."
    )


def test_version_is_parseable():
    assert re.fullmatch(r"\d+\.\d+\.\d+", fusion_cad_mcp.__version__), (
        f"{fusion_cad_mcp.__version__!r} is not a plain semantic version"
    )
