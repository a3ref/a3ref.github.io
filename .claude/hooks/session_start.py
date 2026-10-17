"""SessionStart hook: tell Claude about missing local clones (stdout is added to the context; silent when all is set up)."""
import os
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
missing = [
    f"{d}/ is missing: `git clone https://github.com/a3ref/{d} {d}` ({why})."
    for d, why in (("data", "needed by build, feed and the tests of real output"), ("mcp", "only for work on the MCP server"))
    if not (root / d / ".git").exists()
]
if missing:
    print("a3ref setup: " + " ".join(missing))
