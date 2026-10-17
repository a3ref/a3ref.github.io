"""PostToolUse hook: after a Python file in biwiki/ or tests/ changes, run the unit tests (under a second).

Silent when they pass; on failure the output goes to Claude (exit 2) so the break is fixed right away.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

event = json.load(sys.stdin)
path = event.get("tool_input", {}).get("file_path") or ""
root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".").resolve()
try:
    rel = Path(path).resolve().relative_to(root).as_posix()
except ValueError:
    sys.exit(0)
if not (rel.endswith(".py") and rel.startswith(("biwiki/", "tests/"))):
    sys.exit(0)
run = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=root, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=120)
if run.returncode:
    print(f"`python -m unittest` fails after editing {rel}:\n" + (run.stdout + run.stderr)[-3000:], file=sys.stderr)
    sys.exit(2)
