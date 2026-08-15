"""Make the test suite import this checkout, not an installed copy.

Without this, `import fusion_cad_mcp` resolves through site-packages to
whatever copy is installed on the machine, so the suite can pass while the
code under it is untouched. That holds inside git worktrees too, which is
exactly where automated runs execute.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
