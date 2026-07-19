"""The knowledge markdown bundled in the package must match src/.

find_tool, find_pattern and find_gotcha answer from markdown shipped inside the
Python package, so a `pip install` works with no repo checkout. The canonical
copies live in ../src/ and build.ps1 syncs them across.

Two copies means they can drift, and a drifted copy is worse than a missing one:
the tool answers confidently from stale docs. These tests make drift a test
failure instead. If one fails, run build.ps1 (or copy the three files across).

Skipped rather than failed when src/ is absent, since a wheel installed without
the repo legitimately has only the packaged copies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fusion_cad_mcp.tools.knowledge import PACKAGED_KNOWLEDGE_DIR

KNOWLEDGE_FILES = ["tools.md", "patterns.md", "gotchas.md"]

# server/tests/ -> server/ -> fusion360-mcp/ -> src/
SRC_DIR = Path(__file__).resolve().parents[2] / "src"


@pytest.mark.parametrize("name", KNOWLEDGE_FILES)
def test_packaged_copy_exists(name):
    packaged = PACKAGED_KNOWLEDGE_DIR / name
    assert packaged.exists(), (
        f"{name} is missing from the package at {PACKAGED_KNOWLEDGE_DIR}. "
        f"find_* would fall back to the repo copy in development and fail "
        f"outright for an installed user. Run build.ps1."
    )


@pytest.mark.parametrize("name", KNOWLEDGE_FILES)
def test_packaged_copy_matches_source(name):
    source = SRC_DIR / name
    if not source.exists():
        pytest.skip(f"{name} not present in src/; running outside a repo checkout")

    packaged = PACKAGED_KNOWLEDGE_DIR / name
    assert packaged.exists(), f"{name} missing from package; run build.ps1"

    # Compare normalized text, since the repo checks out CRLF on Windows while
    # the packaged copy may carry LF. Content is what matters here.
    src_text = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    pkg_text = packaged.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert pkg_text == src_text, (
        f"Packaged {name} has drifted from src/{name} "
        f"({len(pkg_text)} vs {len(src_text)} chars). Run build.ps1 to resync, "
        f"or the server will answer find_* from stale documentation."
    )


def test_knowledge_tools_resolve_to_a_real_file():
    """Every find_* tool must have a document to search."""
    from fusion_cad_mcp.tools.knowledge import _resolve_skill_doc

    for name in KNOWLEDGE_FILES:
        assert _resolve_skill_doc(name) is not None, (
            f"_resolve_skill_doc({name!r}) found nothing. The matching find_* "
            f"tool would return a *_not_found error."
        )
