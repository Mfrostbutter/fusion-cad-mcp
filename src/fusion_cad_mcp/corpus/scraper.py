"""Fusion 360 API docs scraper.

Crawls help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/*.htm starting from
a seed list (Index.htm + What's New + known UM pages), follows every internal
.htm link, converts each page to markdown, writes one .md per page plus a JSONL
corpus and a manifest.

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
from urllib.parse import urljoin, urlparse

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
LOG_PATH = OUT_DIR / "scraper.log"


def configure(out_dir: Path) -> None:
    """Point the scraper at a different output directory.

    The paths are module-level constants used throughout, so rebind them all
    together rather than threading a directory through every function.
    """
    global OUT_DIR, PAGES_DIR, CORPUS_PATH, MANIFEST_PATH, LOG_PATH
    OUT_DIR = Path(out_dir).expanduser().resolve()
    PAGES_DIR = OUT_DIR / "pages"
    CORPUS_PATH = OUT_DIR / "corpus.jsonl"
    MANIFEST_PATH = OUT_DIR / "manifest.json"
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
SESSION.headers.update({
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
})


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
        kind = "member" if member and (member[0].islower() or member in {"classType", "objectType"}) else "object"
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


def run(limit: int | None, rate: float, resume: bool) -> None:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Reset corpus on fresh run
    if not resume and CORPUS_PATH.exists():
        CORPUS_PATH.unlink()

    seen: set[str] = set()
    queue: deque[str] = deque()
    for s in SEEDS:
        queue.append(BASE + s)

    if resume:
        already = already_scraped()
        log(f"Resume: {len(already)} pages already scraped, skipping")
    else:
        already = set()

    scraped = 0
    failed = 0
    while queue:
        if limit and scraped >= limit:
            log(f"Limit {limit} reached, stopping")
            break
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        slug = url.rsplit("/", 1)[-1]
        if slug in already:
            # On disk from a prior run. Raw HTML is not kept, so its outbound
            # links cannot be re-discovered: resume is best-effort, and a full
            # crawl is the way to guarantee complete coverage.
            continue

        log(f"[{scraped + 1}] GET {slug}")
        html = fetch(url)
        if html is None:
            log(f"  SKIP {slug}: 404 or permanent failure")
            failed += 1
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

        time.sleep(rate)

    manifest = {
        "scraped": scraped,
        "failed": failed,
        "seen": len(seen),
        "queue_remaining": len(queue),
        "completed": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"DONE scraped={scraped} failed={failed} seen={len(seen)} queue_remaining={len(queue)}")


def main(argv: list[str] | None = None) -> int:
    """Parse args, gate on terms acceptance, crawl. Returns an exit code.

    Callable as a library so `fusion-cad-mcp corpus build` and direct execution
    share one implementation, including the terms gate.
    """
    ap = argparse.ArgumentParser(prog="fusion-cad-mcp corpus build")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N pages (smoke test)")
    ap.add_argument("--rate", type=float, default=1.0, help="Seconds between requests")
    ap.add_argument("--resume", action="store_true", help="Skip pages already on disk")
    ap.add_argument("--contact", default="", help="Optional contact string for the User-Agent")
    ap.add_argument("--user-agent", default="", help="Override the default User-Agent")
    ap.add_argument("--i-accept-autodesk-terms", action="store_true", help="Confirm this user-initiated local cache build complies with Autodesk terms")
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
        SESSION.headers["User-Agent"] = f"fusion-cad-mcp-corpus-builder/0.1 (local cache; contact {args.contact})"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        run(args.limit, args.rate, args.resume)
    except KeyboardInterrupt:
        log("Interrupted by user")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
