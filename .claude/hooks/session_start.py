"""SessionStart hook: tell Claude when the a3ref/data clone is missing (stdout is added to the context; silent when it is there)."""
import os
import sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
sys.path.insert(0, str(root))
from biwiki.__main__ import DATA  # noqa: E402

if not (DATA / ".git").exists():
    print("a3ref setup: the a3ref/data clone is missing; `git clone https://github.com/a3ref/data data` "
          "(needed by build and feed), or pass the path of an existing clone with --raw/--dataset/--data.")
