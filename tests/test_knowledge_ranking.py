"""Ranking behavior for the find_* knowledge tools.

The original scoring was raw bag-of-words: +30 for a query term in the heading,
+1 per occurrence in the body, every term weighted the same. Three failure modes
fell out of that, and this module pins the fixes.

The motivating case: searching "pattern_rectangular direction two" returned the
`shell` section first, because `shell` discusses "direction" repeatedly, while
the section literally named `pattern_rectangular` ranked below it.
"""

from __future__ import annotations

import math

import pytest

from fusion_cad_mcp.tools.knowledge import (
    _COVERAGE_FLOOR,
    _score_section,
    _tokenize,
    find_gotcha,
    find_tool,
)


def _sec(heading: str, body: str) -> dict:
    return {"heading": heading, "level": 2, "body": body}


# ---------- unit level ----------

def test_rare_term_outweighs_common_term():
    """A distinctive term must beat a common one, given idf."""
    idf = {"widget": 4.0, "the": 1.0}
    rare = _score_section(["widget"], _sec("x", "widget"), idf)
    common = _score_section(["the"], _sec("x", "the"), idf)
    assert rare > common


def test_repeat_mentions_have_diminishing_returns():
    """Twelve mentions must not be worth twelve times one mention.

    Linear scoring is what let a section win on volume alone. Damping must be
    clearly sublinear, not merely monotonic.
    """
    reps = 12
    idf = {"direction": 1.0}
    one = _score_section(["direction"], _sec("x", "direction"), idf)
    many = _score_section(["direction"], _sec("x", "direction " * reps), idf)

    assert many > one, "more mentions should still score higher"
    assert many < one * reps / 2, (
        f"damping is not clearly sublinear: {one} -> {many} "
        f"(linear would be {one * reps})"
    )


def test_covering_more_query_terms_beats_hammering_one():
    """The core regression, in miniature."""
    idf = {"alpha": 2.0, "beta": 2.0, "gamma": 2.0}
    terms = ["alpha", "beta", "gamma"]

    covers_all = _score_section(terms, _sec("x", "alpha beta gamma"), idf)
    hammers_one = _score_section(terms, _sec("x", "alpha " * 20), idf)

    assert covers_all > hammers_one, (
        f"matching every term ({covers_all}) should beat repeating one "
        f"({hammers_one})"
    )


def test_heading_match_still_dominates_body_match():
    idf = {"extrude": 2.0}
    in_heading = _score_section(["extrude"], _sec("extrude", ""), idf)
    in_body = _score_section(["extrude"], _sec("x", "extrude " * 5), idf)
    assert in_heading > in_body


def test_unknown_term_is_treated_as_rare_not_weightless():
    """A term absent from the idf map must not score as zero-weight."""
    scored = _score_section(["neverseen"], _sec("x", "neverseen"), idf={})
    assert scored > 0


def test_no_match_scores_zero():
    assert _score_section(["absent"], _sec("x", "y"), {"absent": 3.0}) == 0.0


def test_coverage_floor_is_a_sane_fraction():
    assert 0.0 < _COVERAGE_FLOOR < 1.0


# ---------- end to end, against the real documents ----------

@pytest.mark.parametrize(
    "query,expected_substring",
    [
        # The regression that motivated the fix.
        ("pattern_rectangular direction two", "pattern_rectangular"),
        ("add_hole face selection", "add_hole"),
        ("set_joint_limits units", "set_joint_limits"),
        ("shell direction", "shell"),
        ("export bytes_written", "export"),
    ],
)
def test_find_tool_ranks_the_named_tool_first(query, expected_substring):
    env = find_tool(query, 1)
    assert env.ok, f"find_tool failed: {env.error}"
    hits = env.result["hits"]
    assert hits, f"no hits for {query!r}"
    assert expected_substring in hits[0]["heading"], (
        f"{query!r} ranked {hits[0]['heading']!r} first; "
        f"expected a heading containing {expected_substring!r}"
    )


@pytest.mark.parametrize(
    "query,expected_substring",
    [
        ("ball joint pitch yaw", "Ball joint"),
        ("pattern coincident bodies", "coincident"),
        ("areaProperties", "areaProperties"),
    ],
)
def test_find_gotcha_ranks_the_right_entry_first(query, expected_substring):
    env = find_gotcha(query, 1)
    assert env.ok, f"find_gotcha failed: {env.error}"
    hits = env.result["hits"]
    assert hits, f"no hits for {query!r}"
    assert expected_substring in hits[0]["heading"], (
        f"{query!r} ranked {hits[0]['heading']!r} first"
    )


def test_scores_are_rounded_for_readability():
    env = find_tool("extrude", 1)
    score = env.result["hits"][0]["score"]
    assert isinstance(score, float)
    assert math.isclose(score, round(score, 2))


def test_tokenizer_keeps_underscored_identifiers_whole():
    """Tool names are the most distinctive terms available; do not split them."""
    assert "pattern_rectangular" in _tokenize("call pattern_rectangular now")
