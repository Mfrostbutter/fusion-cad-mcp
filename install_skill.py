"""Install the Fusion CAD skill into a Claude skills directory.

Assembles SKILL.md plus the knowledge markdown that ships inside the package
into one skill folder. An optional overlay directory is copied on top, so a
private variant can add or replace files without forking the skill.

  python install_skill.py
  python install_skill.py --overlay path/to/overlay --name fusion-cad-agenius
"""

from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent
KNOWLEDGE = REPO / "src" / "fusion_cad_mcp" / "knowledge"
BASE_FILES = [
    REPO / "SKILL.md",
    *(KNOWLEDGE / n for n in ("tools.md", "patterns.md", "gotchas.md")),
]


def write_lf(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 without a BOM. A BOM before the opening --- hides the frontmatter."""
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="")


def install(dest: pathlib.Path, overlay: pathlib.Path | None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for src in BASE_FILES:
        if not src.exists():
            sys.exit(f"missing source file: {src}")
        write_lf(dest / src.name, src.read_text(encoding="utf-8"))
        written.append(src.name)

    if overlay:
        if not overlay.is_dir():
            sys.exit(f"overlay is not a directory: {overlay}")
        for src in sorted(overlay.glob("*.md")):
            if src.name == "README.md":  # documents the overlay, not part of the skill
                continue
            write_lf(dest / src.name, src.read_text(encoding="utf-8"))
            written.append(f"{src.name} (overlay)")

    print(f"installed {len(written)} files to {dest}")
    for name in written:
        print(f"  {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="fusion-cad", help="installed skill folder name")
    ap.add_argument(
        "--skills-dir", type=pathlib.Path, default=pathlib.Path.home() / ".claude" / "skills"
    )
    ap.add_argument(
        "--overlay", type=pathlib.Path, help="directory of .md files copied over the base"
    )
    args = ap.parse_args()
    install(args.skills_dir / args.name, args.overlay)


if __name__ == "__main__":
    main()
