"""Group 7 / corpus-backed knowledge tools.

find_api    -> top-N matches over the scraped Fusion API help corpus
find_pattern -> top-N matches over patterns.md sections
find_gotcha  -> top-N matches over gotchas.md sections

The corpus is built once by the user (see fusion-cad-mcp corpus build) and lives
locally. We do NOT redistribute Autodesk content. Resolution order:

  1. FUSION_CAD_CORPUS_DIR environment variable
  2. ~/.fusion-cad/corpus/
  3. src/api-reference/ in this repo (dev fallback)

If no corpus is found, find_api returns a structured 'corpus_not_built' error
directing the user to run the build subcommand. find_pattern and find_gotcha
look for patterns.md / gotchas.md next to the corpus dir, then fall back to a
known location inside the repo for dev.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from ..envelope import Envelope

# ---------- corpus resolution ----------

REPO_ROOT_HINTS = [
    Path(__file__).resolve().parents[4],  # .../fusion360-mcp/
]


def _resolve_corpus_dir() -> Path | None:
    env = os.environ.get("FUSION_CAD_CORPUS_DIR")
    if env:
        p = Path(env).expanduser()
        if (p / "corpus.jsonl").exists():
            return p
    home = Path.home() / ".fusion-cad" / "corpus"
    if (home / "corpus.jsonl").exists():
        return home
    for root in REPO_ROOT_HINTS:
        candidate = root / "src" / "api-reference"
        if (candidate / "corpus.jsonl").exists():
            return candidate
    return None


# Our own docs, so unlike the Autodesk API corpus they ship inside the wheel
# and find_pattern / find_gotcha / find_tool work on a plain `pip install`.
PACKAGED_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def _resolve_skill_doc(name: str) -> Path | None:
    """Locate a knowledge markdown file.

    Order matters. A user-supplied copy beside the corpus wins so it can be
    overridden; the repo checkout comes next so development always reads the
    live file rather than a stale bundle; the packaged copy is the fallback
    that makes an installed wheel work standalone.
    """
    corpus = _resolve_corpus_dir()
    if corpus is not None:
        sibling = corpus.parent / name
        if sibling.exists():
            return sibling
    for root in REPO_ROOT_HINTS:
        candidate = root / "src" / name
        if candidate.exists():
            return candidate
    packaged = PACKAGED_KNOWLEDGE_DIR / name
    if packaged.exists():
        return packaged
    return None


# ---------- API corpus search ----------


@dataclass
class CorpusIndex:
    """In-memory index of the scraped API corpus.

    For each record we keep the lightweight fields needed for scoring + the
    body_md for snippet generation. ~80 MB markdown total; load once, query
    many times.
    """

    records: list[dict[str, Any]]
    by_slug_lower: dict[str, int]

    @classmethod
    def load(cls, corpus_dir: Path) -> CorpusIndex:
        records: list[dict[str, Any]] = []
        with (corpus_dir / "corpus.jsonl").open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        by_slug = {r["slug"].lower(): i for i, r in enumerate(records)}
        return cls(records=records, by_slug_lower=by_slug)


@cache
def _api_index() -> CorpusIndex | None:
    d = _resolve_corpus_dir()
    if d is None:
        return None
    return CorpusIndex.load(d)


_TERM_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TERM_RE.findall(s)]


def _score_record(query_terms: list[str], rec: dict[str, Any]) -> float:
    """Cheap relevance scoring. Slug and title dominate; body is a tiebreaker."""
    if not query_terms:
        return 0
    slug_lc = rec["slug"].lower()
    title_lc = (rec.get("title") or "").lower()

    score = 0

    # Strong: full multi-term concat appears in slug
    if len(query_terms) > 1:
        for sep in ("_", ".", ""):
            if sep.join(query_terms) in slug_lc:
                score += 200
                break

    # Each term: slug match dominates, then title, then body
    body_lc = rec.get("body_md", "")[:8000].lower()  # cap body scan for speed
    unique_terms = set(query_terms)
    matched = 0
    for t in unique_terms:
        hit = False
        if t in slug_lc:
            score += 50
            hit = True
        if t in title_lc:
            score += 25
            hit = True
        count = body_lc.count(t)
        if count:
            # Log damping, so a page cannot win purely by repeating one common
            # word. Same reason as _score_section.
            score += 1.0 + math.log(count)
            hit = True
        if hit:
            matched += 1

    # Reward covering more of the query over hammering one term.
    if matched and len(unique_terms) > 1:
        coverage = matched / len(unique_terms)
        score *= _COVERAGE_FLOOR + (1.0 - _COVERAGE_FLOOR) * coverage

    # Penalty for preview pages (still surface them, but rank below stable)
    if rec.get("is_preview"):
        score = max(0.0, score - 30)

    return score


def find_api(
    query: str,
    kind: str | None = None,
    namespace: str | None = None,
    limit: int = 5,
) -> Envelope:
    """Search the scraped API corpus.

    kind: optional filter on kind field (object / member / manual / etc).
    namespace: optional substring filter on namespace field.
    """
    idx = _api_index()
    if idx is None:
        return Envelope(
            ok=False,
            error="corpus_not_built",
            message=(
                "No local Fusion API corpus found. Run `fusion-cad-mcp corpus build` "
                "once to scrape the help pages to ~/.fusion-cad/corpus/. "
                "Set FUSION_CAD_CORPUS_DIR to point elsewhere if needed."
            ),
        )

    q_terms = _tokenize(query)
    if not q_terms:
        return Envelope(ok=False, error="empty_query", message="query had no searchable tokens")

    candidates: list[tuple[float, dict[str, Any]]] = []
    for rec in idx.records:
        if kind and rec.get("kind") != kind:
            continue
        if namespace and namespace.lower() not in (rec.get("namespace") or "").lower():
            continue
        s = _score_record(q_terms, rec)
        if s > 0:
            candidates.append((s, rec))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[: max(1, limit)]

    hits = [
        {
            "score": round(score, 2),
            "slug": rec["slug"],
            "title": rec.get("title", ""),
            "namespace": rec.get("namespace"),
            "kind": rec.get("kind"),
            "url": rec.get("url"),
            "is_preview": rec.get("is_preview", False),
            "introduced": rec.get("introduced"),
            "snippet": _snippet(rec.get("body_md", ""), q_terms),
        }
        for score, rec in top
    ]
    return Envelope(
        ok=True,
        message=f"{len(hits)} hits (of {len(candidates)} matching) for {query!r}",
        result={"hits": hits, "matched": len(candidates)},
    )


def _snippet(body_md: str, query_terms: list[str], window: int = 240) -> str:
    """Return ~240 chars from body around the first matching term, or the head."""
    if not body_md:
        return ""
    lc = body_md.lower()
    for t in query_terms:
        i = lc.find(t)
        if i >= 0:
            start = max(0, i - window // 3)
            end = min(len(body_md), i + (2 * window) // 3)
            return body_md[start:end].strip()
    return body_md[:window].strip()


# ---------- patterns.md / gotchas.md section search ----------

_SECTION_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _parse_sections(md_text: str) -> list[dict[str, Any]]:
    """Split a markdown file into sections keyed by ## (and #) headings."""
    matches = list(_SECTION_HEADING_RE.finditer(md_text))
    sections: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = md_text[start:end].strip()
        sections.append({"level": level, "heading": heading, "body": body})
    return sections


@cache
def _sections_for(path_str: str) -> tuple[dict[str, Any], ...]:
    """Cached parse of a markdown doc into sections."""
    p = Path(path_str)
    if not p.exists():
        return tuple()
    return tuple(_parse_sections(p.read_text(encoding="utf-8")))


@cache
def _section_idf(path_str: str) -> dict[str, float]:
    """Inverse document frequency per term, over the sections of one document.

    Without this, every query term weighs the same, so a common word beats a
    distinctive one. Searching "pattern_rectangular direction two" used to
    return the `shell` section first, purely because that section says
    "direction" many times, while the section actually named
    `pattern_rectangular` ranked below it.
    """
    sections = _sections_for(path_str)
    n = len(sections) or 1
    df: dict[str, int] = {}
    for s in sections:
        for t in set(_tokenize(s["heading"] + " " + s["body"])):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


# A term absent from the document is maximally rare; treat it as such rather
# than as weightless, so a typo does not silently become a free match.
_UNSEEN_IDF = 3.0

# Full coverage is worth up to 2.5x a single-term match. Tuned so that matching
# every query term once beats matching one term a dozen times.
_COVERAGE_FLOOR = 0.4


def _score_section(
    query_terms: list[str],
    section: dict[str, Any],
    idf: dict[str, float] | None = None,
) -> float:
    """Score one section against the query.

    Three properties that the naive version lacked:
      - rare terms weigh more than common ones (idf)
      - repeated mentions have diminishing returns, so a section cannot win on
        volume alone
      - covering more of the query beats hammering one term
    """
    if not query_terms:
        return 0.0
    idf = idf or {}
    heading_lc = section["heading"].lower()
    body_lc = section["body"].lower()

    unique_terms = set(query_terms)
    score = 0.0
    matched = 0

    for t in unique_terms:
        w = idf.get(t, _UNSEEN_IDF)
        hit = False
        if t in heading_lc:
            score += 30.0 * w
            hit = True
        count = body_lc.count(t)
        if count:
            # log damping: the 1st mention is worth far more than the 12th.
            score += (1.0 + math.log(count)) * w
            hit = True
        if hit:
            matched += 1

    if not matched:
        return 0.0

    coverage = matched / len(unique_terms)
    return score * (_COVERAGE_FLOOR + (1.0 - _COVERAGE_FLOOR) * coverage)


def _search_md(path: Path | None, query: str, limit: int, doc_label: str) -> Envelope:
    if path is None or not path.exists():
        return Envelope(
            ok=False,
            error=f"{doc_label}_not_found",
            message=f"{doc_label} markdown file not located. Set its path next to the corpus dir.",
        )
    q_terms = _tokenize(query)
    if not q_terms:
        return Envelope(ok=False, error="empty_query", message="query had no searchable tokens")

    sections = _sections_for(str(path))
    idf = _section_idf(str(path))
    scored = [(_score_section(q_terms, s, idf), s) for s in sections]
    scored = [(sc, s) for sc, s in scored if sc > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, limit)]

    hits = [
        {
            "score": round(sc, 2),
            "heading": s["heading"],
            "level": s["level"],
            "snippet": s["body"][:400].strip(),
            "source": path.name,
        }
        for sc, s in top
    ]
    return Envelope(
        ok=True,
        message=f"{len(hits)} hits (of {len(scored)} matching) in {path.name} for {query!r}",
        result={"hits": hits, "matched": len(scored)},
    )


def find_pattern(query: str, limit: int = 5) -> Envelope:
    return _search_md(_resolve_skill_doc("patterns.md"), query, limit, "patterns")


def find_gotcha(query: str, limit: int = 5) -> Envelope:
    return _search_md(_resolve_skill_doc("gotchas.md"), query, limit, "gotchas")


def find_tool(query: str, limit: int = 5) -> Envelope:
    """Search this server's own tool reference.

    Lets a client look up a signature, enum, or error code on demand instead of
    carrying the whole reference in context, which is the point of the typed
    tool surface in the first place.
    """
    return _search_md(_resolve_skill_doc("tools.md"), query, limit, "tools")


__all__ = [
    "CorpusIndex",
    "find_api",
    "find_gotcha",
    "find_pattern",
    "find_tool",
]
