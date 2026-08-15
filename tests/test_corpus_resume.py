"""Resume-path regression tests for the corpus scraper.

Covers the silent-failure mode where `--resume` drained the queue to nothing,
scraped zero pages, and still reported success (issue #3). No network: fetch()
is stubbed with a tiny fake site.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

scraper = pytest.importorskip("fusion_cad_mcp.corpus.scraper")

BASE = scraper.BASE

# Fake site: Index links to A and B, A links to C, C links to D.
FAKE_SITE = {
    "Index.htm": '<html><title>Index</title><body><a href="A.htm">A</a><a href="B.htm">B</a></body></html>',
    "A.htm": '<html><title>A</title><body><a href="C.htm">C</a></body></html>',
    "B.htm": "<html><title>B</title><body>b</body></html>",
    "C.htm": '<html><title>C</title><body><a href="D.htm">D</a></body></html>',
    "D.htm": "<html><title>D</title><body>d</body></html>",
}


@pytest.fixture
def site(tmp_path: Path, monkeypatch):
    """Point the scraper at tmp_path and serve FAKE_SITE instead of the network."""
    scraper.configure(tmp_path)
    monkeypatch.setattr(scraper, "SEEDS", ["Index.htm"])
    monkeypatch.setattr(scraper, "fetch", lambda url, **kw: FAKE_SITE.get(url.rsplit("/", 1)[-1]))
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    return tmp_path


def _slugs(out: Path) -> set[str]:
    return {p.name for p in (out / "pages").glob("*.md")}


def test_full_crawl_reaches_every_page(site):
    m = scraper.run(limit=None, rate=0, resume=False)
    assert m["scraped"] == 5
    assert _slugs(site) == {"Index.md", "A.md", "B.md", "C.md", "D.md"}


def test_resume_after_limit_finishes_the_crawl(site):
    """Issue #3: a --limit smoke test then --resume used to scrape nothing."""
    first = scraper.run(limit=2, rate=0, resume=False)
    assert first["scraped"] == 2
    assert first["queue_remaining"] > 0

    second = scraper.run(limit=None, rate=0, resume=True)
    assert second["scraped"] == 3
    assert second["frontier_source"] == "saved"
    assert _slugs(site) == {"Index.md", "A.md", "B.md", "C.md", "D.md"}


def test_frontier_survives_an_interrupt(site):
    """Ctrl-C mid-crawl still leaves a resumable frontier."""
    real_fetch = scraper.fetch

    def boom(url, **kw):
        if url.endswith("A.htm"):
            raise KeyboardInterrupt
        return real_fetch(url)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scraper, "fetch", boom)
        with pytest.raises(KeyboardInterrupt):
            scraper.run(limit=None, rate=0, resume=False)

    frontier = json.loads((site / "frontier.json").read_text(encoding="utf-8"))
    assert frontier["pending"]

    m = scraper.run(limit=None, rate=0, resume=True)
    assert m["frontier_source"] == "saved"
    assert _slugs(site) == {"Index.md", "A.md", "B.md", "C.md", "D.md"}


def test_resume_rebuilds_frontier_from_pages_when_none_saved(site):
    """Corpora built before frontier persistence still resume, off the markdown."""
    scraper.run(limit=2, rate=0, resume=False)
    (site / "frontier.json").unlink()

    m = scraper.run(limit=None, rate=0, resume=True)
    assert m["frontier_source"] == "pages"
    assert m["frontier_restored"] > 0
    assert _slugs(site) == {"Index.md", "A.md", "B.md", "C.md", "D.md"}


def test_resume_on_a_complete_corpus_is_a_clean_no_op(site):
    scraper.run(limit=None, rate=0, resume=False)
    assert scraper.main(["--resume", "--rate", "0", "--i-accept-autodesk-terms"]) == 0


def test_resume_that_recovers_nothing_exits_nonzero(site, monkeypatch, capsys):
    """The silent-failure shape from issue #3 is now a loud, non-zero finish."""
    scraper.run(limit=2, rate=0, resume=False)
    (site / "frontier.json").unlink()
    # Simulate the old behaviour: no frontier restored from anywhere.
    monkeypatch.setattr(scraper, "rebuild_frontier_from_pages", lambda: [])

    rc = scraper.main(["--resume", "--rate", "0", "--i-accept-autodesk-terms"])
    assert rc == 1
    assert "very likely" in capsys.readouterr().err


def test_extract_links_from_markdown_handles_link_forms():
    md = (
        "See [A](A.htm), [B](B.htm#anchor), [C](C.htm \"C title\"), <D.htm>, "
        "[off-site](https://example.com/E.htm)."
    )
    assert scraper.extract_links_from_markdown(md) == [
        BASE + "A.htm",
        BASE + "B.htm",
        BASE + "C.htm",
        BASE + "D.htm",
    ]
