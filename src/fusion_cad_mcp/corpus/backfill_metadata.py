"""Backfill derived metadata into the local Fusion API corpus.

This is intentionally local-only: it reads the already-scraped corpus.jsonl,
derives fields from each record's title/body_md, and rewrites the JSONL
atomically. It does not fetch Autodesk pages.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

DEFAULT_CORPUS_PATH = Path.home() / ".fusion-cad" / "corpus" / "corpus.jsonl"

PREVIEW_MARKER = "This functionality is provided as a preview"
INTRODUCED_RE = re.compile(r"Introduced in version\s+([^\n\r]+)", re.IGNORECASE)


def derive_metadata(record: dict) -> tuple[bool, str | None]:
    title = record.get("title") or ""
    body_md = record.get("body_md") or ""
    introduced_match = INTRODUCED_RE.search(body_md)
    is_preview = PREVIEW_MARKER in body_md or " Object Preview" in title
    introduced = introduced_match.group(1).strip() if introduced_match else None
    return is_preview, introduced


def main(corpus_path: Path | None = None) -> None:
    """Rewrite corpus.jsonl in place with derived fields, and update its manifest.

    The corpus lives wherever the scraper wrote it, so the path is passed in
    rather than assumed to sit beside this module.
    """
    corpus_path = Path(corpus_path or DEFAULT_CORPUS_PATH).expanduser()
    manifest_path = corpus_path.parent / "manifest.json"
    tmp_path = corpus_path.parent / (corpus_path.name + ".tmp")

    if not corpus_path.exists():
        raise SystemExit(f"Missing corpus: {corpus_path}")

    count = 0
    preview_count = 0
    introduced_count = 0

    with corpus_path.open("r", encoding="utf-8") as src, tmp_path.open("w", encoding="utf-8") as dst:
        for line in src:
            if not line.strip():
                continue
            record = json.loads(line)
            is_preview, introduced = derive_metadata(record)
            record["is_preview"] = is_preview
            record["introduced"] = introduced
            preview_count += int(is_preview)
            introduced_count += int(bool(introduced))
            count += 1
            dst.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    tmp_path.replace(corpus_path)

    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata_backfilled"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["metadata_fields"] = ["is_preview", "introduced"]
    manifest["preview_records"] = preview_count
    manifest["introduced_records"] = introduced_count
    manifest["records"] = count
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(
        f"Backfilled {count} records "
        f"({preview_count} preview, {introduced_count} with introduced metadata)."
    )


if __name__ == "__main__":
    main()
