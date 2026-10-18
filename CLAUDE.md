@AGENTS.md

## Claude Code

Hooks in `.claude/settings.json` (scripts in `.claude/hooks/`):

- edits to generated files (`out/`, the data clone, test fixtures) are blocked with a note on what to change instead;
- after an edit to a Python file in `biwiki/` or `tests/`, `python -m unittest` runs; failures come back to you;
- at startup, a missing data clone is reported.
