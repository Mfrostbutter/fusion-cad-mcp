"""Local Fusion API corpus: build it, don't ship it.

`find_api` searches a corpus of Autodesk's Fusion API help pages. That content
is Autodesk's, so it is never redistributed with this package. Instead the user
builds their own local cache, once, with:

    fusion-cad-mcp corpus build --i-accept-autodesk-terms

The result lands in ~/.fusion-cad/corpus/ by default, which is the first place
the resolver looks, so no further configuration is needed.

The scraper needs HTML libraries that the server itself does not, so they are an
optional install:

    pip install "fusion-cad-mcp[corpus]"
"""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_OUT_DIR = Path.home() / ".fusion-cad" / "corpus"

_MISSING_DEPS = """\
Corpus building needs a few extra libraries that the MCP server itself does not:

    pip install "fusion-cad-mcp[corpus]"

(missing: {missing})
"""


def build(argv: list[str] | None = None) -> int:
    """Run the scraper, then backfill preview/introduced metadata.

    Returns a process exit code. Kept thin: argument parsing and the terms gate
    live in the scraper module so the two entry points cannot drift.
    """
    try:
        from . import scraper
    except ImportError as e:
        print(_MISSING_DEPS.format(missing=e.name), file=sys.stderr)
        return 2

    argv = list(sys.argv[1:] if argv is None else argv)

    # Let --out choose the target directory, defaulting to the location the
    # resolver checks first.
    out_dir = DEFAULT_OUT_DIR
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            print("ERROR: --out needs a directory", file=sys.stderr)
            return 2
        out_dir = Path(argv[i + 1]).expanduser()
        del argv[i : i + 2]

    scraper.configure(out_dir)
    print(f"Building Fusion API corpus in {scraper.OUT_DIR}", file=sys.stderr)

    rc = scraper.main(argv)
    if rc != 0:
        return rc

    # Preview badges and "Introduced in" versions are derived in a second pass
    # so a partial scrape can be resumed without redoing the crawl.
    from . import backfill_metadata

    backfill_metadata.main(corpus_path=scraper.CORPUS_PATH)
    print(f"Corpus ready: {scraper.CORPUS_PATH}", file=sys.stderr)
    return 0


__all__ = ["DEFAULT_OUT_DIR", "build"]
