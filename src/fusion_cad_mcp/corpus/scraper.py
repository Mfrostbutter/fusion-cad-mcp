"""Fusion 360 API docs scraper.

Crawls help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/*.htm starting from
a seed list (Index.htm + What's New + known UM pages), follows every internal
.htm link, converts each page to markdown, writes one .md per page plus a JSONL
corpus, a manifest, and the crawl frontier that --resume picks back up.

Usage:
    py -3 scraper.py --i-accept-autodesk-terms
    py -3 scraper.py --limit 20 --i-accept-autodesk-terms
    py -3 scraper.py --resume --i-accept-autodesk-terms

Politeness:
    1 req/sec by default; --rate to override (seconds between requests).
    Retries 3x with backoff on 5xx; logs and skips on 404.
    Requires explicit local-cache consent before fetching Autodesk Help pages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert

BASE = "https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/"

# lxml is faster and more forgiving on Autodesk's markup, but bs4 only fails on
# it at first parse, long after the crawl has started. Resolve it up front and
# fall back to the stdlib parser.
try:
    import lxml  # noqa: F401

    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

# Output location. Defaults to the same directory the resolver looks in first
# (~/.fusion-cad/corpus), so a plain `fusion-cad-mcp corpus build` produces a
# corpus the server finds with no further configuration. Overridable, because
# the repo keeps its own dev corpus under src/api-reference/.
DEFAULT_OUT_DIR = Path.home() / ".fusion-cad" / "corpus"

OUT_DIR = DEFAULT_OUT_DIR
PAGES_DIR = OUT_DIR / "pages"
CORPUS_PATH = OUT_DIR / "corpus.jsonl"
MANIFEST_PATH = OUT_DIR / "manifest.json"
FRONTIER_PATH = OUT_DIR / "frontier.json"
LOG_PATH = OUT_DIR / "scraper.log"

# Save the frontier every N pages so a crash or kill loses at most this much
# crawl progress.
FRONTIER_SAVE_EVERY = 250


def configure(out_dir: Path) -> None:
    """Point the scraper at a different output directory.

    The paths are module-level constants used throughout, so rebind them all
    together rather than threading a directory through every function.
    """
    global OUT_DIR, PAGES_DIR, CORPUS_PATH, MANIFEST_PATH, FRONTIER_PATH, LOG_PATH
    OUT_DIR = Path(out_dir).expanduser().resolve()
    PAGES_DIR = OUT_DIR / "pages"
    CORPUS_PATH = OUT_DIR / "corpus.jsonl"
    MANIFEST_PATH = OUT_DIR / "manifest.json"
    FRONTIER_PATH = OUT_DIR / "frontier.json"
    LOG_PATH = OUT_DIR / "scraper.log"
    OUT_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_USER_AGENT = "fusion-cad-mcp-corpus-builder/0.1 (local cache; contact configurable)"
PREVIEW_MARKER = "This functionality is provided as a preview"
INTRODUCED_RE = re.compile(r"Introduced in version\s+([^\n\r]+)", re.IGNORECASE)

TERMS_NOTICE = """\
This command fetches Autodesk Help pages and builds a local corpus cache on this machine.
It does not grant redistribution rights and does not publish Autodesk documentation.
Continue only if you have reviewed Autodesk Terms of Use / Acceptable Use and accept
responsibility for this user-initiated local cache build.
"""

# Seed pages: starting points for the crawl.
SEEDS = [
    "Index.htm",
    "WhatsNew.htm",
    # User Manual entry points (probed and confirmed):
    "BasicConcepts_UM.htm",
    "CustomFeatures_UM.htm",
]

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    }
)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch(url: str, *, retries: int = 3, backoff: float = 2.0) -> str | None:
    """GET with retries. Returns body text or None on permanent failure."""
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code >= 500:
                time.sleep(backoff * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            log(f"  WARN {url}: {e} (attempt {attempt + 1})")
            time.sleep(backoff * (attempt + 1))
    return None


HTM_LINK_RE = re.compile(r"""href\s*=\s*['\"]([^'\"]+\.htm)(?:#[^'\"]*)?['\"]""", re.IGNORECASE)


def extract_links(html: str) -> list[str]:
    """Pull all internal .htm links from a page (relative or absolute under our base)."""
    out = []
    for m in HTM_LINK_RE.finditer(html):
        href = m.group(1)
        # Absolutize
        absurl = urljoin(BASE, href)
        # Same-folder scope only
        if absurl.startswith(BASE):
            # Drop fragment, normalize
            absurl = absurl.split("#", 1)[0]
            out.append(absurl)
    return out


def title_from_html(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    return t.get_text(strip=True) if t else ""


def main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Return the meaningful content tag. Autodesk help pages put content in <body>."""
    body = soup.find("body") or soup
    # Strip scripts, styles, navigation cruft
    for tag in body.find_all(["script", "style"]):
        tag.decompose()
    return body


def classify(slug: str) -> tuple[str, str]:
    """Return (namespace, kind) for a page slug like 'MeshBody_calculateCollisionsWithRay.htm'."""
    name = slug[:-4] if slug.endswith(".htm") else slug
    if name.endswith("_UM"):
        return ("user-manual", "manual")
    if "_" in name:
        parent, member = name.split("_", 1)
        # Heuristic: if member looks like a method/property (camelCase), it's a member page
        kind = (
            "member"
            if member and (member[0].islower() or member in {"classType", "objectType"})
            else "object"
        )
        return (parent, kind)
    return (name, "object")


def page_to_record(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, HTML_PARSER)
    title = title_from_html(soup)
    body = main_content(soup)
    body_html = str(body)
    body_md = md_convert(body_html, heading_style="ATX", bullets="-").strip()
    slug = url.rsplit("/", 1)[-1]
    namespace, kind = classify(slug)
    introduced_match = INTRODUCED_RE.search(body_md)
    return {
        "url": url,
        "slug": slug,
        "title": title,
        "namespace": namespace,
        "kind": kind,
        "is_preview": PREVIEW_MARKER in body_md or " Object Preview" in title,
        "introduced": introduced_match.group(1).strip() if introduced_match else None,
        "body_md": body_md,
    }


def write_page(record: dict) -> Path:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    fname = record["slug"].replace(".htm", ".md")
    path = PAGES_DIR / fname
    front = (
        "---\n"
        f"url: {record['url']}\n"
        f"slug: {record['slug']}\n"
        f"title: {record['title']!r}\n"
        f"namespace: {record['namespace']}\n"
        f"kind: {record['kind']}\n"
        "---\n\n"
    )
    path.write_text(front + record["body_md"], encoding="utf-8")
    return path


def append_corpus(record: dict) -> None:
    with CORPUS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def already_scraped() -> set[str]:
    """For --resume: collect slugs we've already written."""
    if not PAGES_DIR.exists():
        return set()
    return {p.stem + ".htm" for p in PAGES_DIR.glob("*.md")}


def save_frontier(queue: deque[str] | list[str], seen: set[str]) -> None:
    """Persist the pending queue and visited set so --resume can continue.

    Written atomically: a truncated frontier would silently shrink the crawl.
    """
    payload = {"pending": list(queue), "seen": sorted(seen)}
    tmp = FRONTIER_PATH.with_name(FRONTIER_PATH.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(FRONTIER_PATH)


def load_frontier() -> tuple[list[str], set[str]] | None:
    """Read a saved frontier. None when absent or unreadable."""
    if not FRONTIER_PATH.exists():
        return None
    try:
        data = json.loads(FRONTIER_PATH.read_text(encoding="utf-8"))
        return list(data.get("pending", [])), set(data.get("seen", []))
    except (OSError, ValueError) as e:
        log(f"WARN unreadable frontier {FRONTIER_PATH.name}: {e}")
        return None


# Link targets in converted pages: [text](Foo.htm), [text](Foo.htm "title"),
# and <Foo.htm> autolinks.
MD_LINK_RE = re.compile(
    r"""\(\s*([^()\s]+\.htm)(?:\#[^()\s]*)?(?:\s+"[^"]*")?\s*\)"""
    r"""|<\s*([^<>\s]+\.htm)(?:\#[^<>\s]*)?\s*>""",
    re.IGNORECASE,
)


def extract_links_from_markdown(text: str) -> list[str]:
    """Pull internal .htm links out of an already-converted page."""
    out = []
    for m in MD_LINK_RE.finditer(text):
        href = m.group(1) or m.group(2)
        absurl = urljoin(BASE, href).split("#", 1)[0]
        if absurl.startswith(BASE):
            out.append(absurl)
    return out


def rebuild_frontier_from_pages() -> list[str]:
    """Re-derive the crawl frontier from the pages already on disk.

    Raw HTML is not kept, so the converted markdown is the only surviving record
    of each page's outbound links. Used when resuming a corpus built before the
    frontier was persisted.
    """
    links: list[str] = []
    known: set[str] = set()
    if not PAGES_DIR.exists():
        return links
    for path in sorted(PAGES_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            log(f"  WARN unreadable page {path.name}: {e}")
            continue
        for link in extract_links_from_markdown(text):
            if link not in known:
                known.add(link)
                links.append(link)
    return links


def run(limit: int | None, rate: float, resume: bool) -> dict:
    """Crawl until the queue drains. Returns the manifest."""
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Reset corpus on fresh run
    if not resume:
        if CORPUS_PATH.exists():
            CORPUS_PATH.unlink()
        FRONTIER_PATH.unlink(missing_ok=True)

    seen: set[str] = set()
    queue: deque[str] = deque()
    already: set[str] = set()
    frontier_source = "seeds"
    restored = 0

    if resume:
        already = already_scraped()
        log(f"Resume: {len(already)} pages already scraped, skipping")
        saved = load_frontier()
        if saved is not None:
            pending, seen = saved
            queue.extend(pending)
            frontier_source = "saved"
            restored = len(queue)
            log(f"Resume: restored frontier, {restored} URLs pending")
        elif already:
            # Corpus predates frontier persistence. Raw HTML is not kept, so
            # re-derive the links from the converted pages rather than re-fetch.
            queue.extend(rebuild_frontier_from_pages())
            frontier_source = "pages"
            restored = len(queue)
            log(f"Resume: no saved frontier, rebuilt {restored} URLs from pages on disk")

    for s in SEEDS:
        url = BASE + s
        if url not in seen:
            queue.append(url)

    scraped = 0
    failed = 0
    # Popped but not yet accounted for. Requeued if the crawl dies mid-page,
    # otherwise the URL sits in `seen` with nothing on disk and resume skips it.
    inflight: str | None = None
    try:
        while queue:
            if limit and scraped >= limit:
                log(f"Limit {limit} reached, stopping")
                break
            url = queue.popleft()
            if url in seen:
                continue
            slug = url.rsplit("/", 1)[-1]
            if slug in already:
                seen.add(url)
                continue

            inflight = url
            seen.add(url)
            log(f"[{scraped + 1}] GET {slug}")
            html = fetch(url)
            if html is None:
                log(f"  SKIP {slug}: 404 or permanent failure")
                failed += 1
                inflight = None
                time.sleep(rate)
                continue

            try:
                record = page_to_record(url, html)
                write_page(record)
                append_corpus(record)
                scraped += 1
            except Exception as e:
                log(f"  ERROR parsing {slug}: {e}")
                failed += 1

            # Enqueue newly discovered links
            for link in extract_links(html):
                if link not in seen:
                    queue.append(link)
            inflight = None

            if scraped and scraped % FRONTIER_SAVE_EVERY == 0:
                save_frontier(queue, seen)

            time.sleep(rate)
    finally:
        # Also runs on Ctrl-C, so an interrupted crawl stays resumable.
        if inflight is not None:
            queue.appendleft(inflight)
            seen.discard(inflight)
        save_frontier(queue, seen)

    manifest = {
        "scraped": scraped,
        "failed": failed,
        "seen": len(seen),
        "queue_remaining": len(queue),
        "pages_on_disk": len(already),
        "frontier_source": frontier_source,
        "frontier_restored": restored,
        "completed": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"DONE scraped={scraped} failed={failed} seen={len(seen)} queue_remaining={len(queue)}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Parse args, gate on terms acceptance, crawl. Returns an exit code.

    Callable as a library so `fusion-cad-mcp corpus build` and direct execution
    share one implementation, including the terms gate.
    """
    ap = argparse.ArgumentParser(prog="fusion-cad-mcp corpus build")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N pages (smoke test)")
    ap.add_argument("--rate", type=float, default=1.0, help="Seconds between requests")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Continue a prior crawl: skip pages already on disk and restore the pending queue",
    )
    ap.add_argument("--contact", default="", help="Optional contact string for the User-Agent")
    ap.add_argument("--user-agent", default="", help="Override the default User-Agent")
    ap.add_argument(
        "--i-accept-autodesk-terms",
        action="store_true",
        help="Confirm this user-initiated local cache build complies with Autodesk terms",
    )
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.i_accept_autodesk_terms:
        print(TERMS_NOTICE, file=sys.stderr)
        # isatty() is not reliable: it reports True in some non-interactive
        # contexts (subprocess pipes, certain terminals, CI), where input()
        # then raises EOFError and the user gets a traceback instead of
        # guidance. Catch it and give the same clean instruction.
        if not sys.stdin.isatty():
            print("ERROR: pass --i-accept-autodesk-terms in non-interactive runs.", file=sys.stderr)
            return 2
        try:
            answer = input("Type YES to build the local corpus cache: ")
        except (EOFError, KeyboardInterrupt):
            print(
                "\nERROR: no interactive input available. "
                "Pass --i-accept-autodesk-terms to confirm.",
                file=sys.stderr,
            )
            return 2
        if answer.strip() != "YES":
            print("Cancelled.", file=sys.stderr)
            return 130

    if args.user_agent:
        SESSION.headers["User-Agent"] = args.user_agent
    elif args.contact:
        SESSION.headers["User-Agent"] = (
            f"fusion-cad-mcp-corpus-builder/0.1 (local cache; contact {args.contact})"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        manifest = run(args.limit, args.rate, args.resume)
    except KeyboardInterrupt:
        log("Interrupted by user")
        return 130

    # Safety net: a resume that scrapes nothing and recovered no frontier has
    # not finished the crawl, it has lost it. Fail loudly rather than let the
    # caller print "Corpus ready" over a near-empty corpus.
    if (
        args.resume
        and manifest["scraped"] == 0
        and manifest["pages_on_disk"]
        and manifest["frontier_source"] != "saved"
        and manifest["frontier_restored"] == 0
    ):
        print(
            "WARNING: resume found no pending work and scraped nothing; the crawl "
            "frontier could not be restored.\nThe corpus contains only the "
            f"{manifest['pages_on_disk']} pages already on disk and is very likely "
            "incomplete.\nRe-run without --resume to rebuild it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
