"""Small Markdown writers of the HTML -> Markdown converter (``htmlmd``); ``site`` reads its CODE_LINK marks.

Original a3ref code (MIT).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# Returns a URL for a wiki page title (+ optional anchor), or None to render the link as plain text.
LinkResolver = Callable[[str, str], Optional[str]]

# A link inside a code block, for the site only: CODE_LINK[0] text CODE_LINK[1] url CODE_LINK[2]
CODE_LINK = ("\ue030", "\ue031", "\ue032")

# a backslash that Markdown would not show as is: before ASCII punctuation or at the end of a line
MD_BACKSLASH = re.compile(r"\\(?=[!-/:-@\[-`{-~]|\n|$)")
# a line Markdown reads as a block of its own
MD_BLOCK = re.compile(r"[ \t]*(?:[*+-][ \t]|\d+[.)][ \t]|#{1,6}[ \t]|>|\||`{3,}|~{3,})")


def quote(body: str, alert: Optional[str] = None, label: Optional[str] = None) -> str:
    """``body`` as a Markdown block quote; ``alert`` makes it a GitHub alert ("[!NOTE]"), ``label`` a bold lead-in."""
    lines = []
    if alert:
        lines.append(f"[!{alert}]")
    if label:
        if MD_BLOCK.match(body):  # a code block, table or list cannot continue the label's line
            body = f"**{label}:**\n\n{body}"
        else:
            body = f"**{label}:** {body}" if body else f"**{label}**"
    lines += body.split("\n")
    return "\n".join(("> " + l) if l.strip() else ">" for l in lines)


def inline_code(code: str) -> str:
    """``code`` as a Markdown code span on one line, with enough backticks around it."""
    if code and not code.strip():  # {{hl|&nbsp;}}: a space shown as code
        return "` `"
    code = re.sub(r"\s*\n\s*", " ", code).strip()
    if not code:
        return ""
    ticks = "``" if "`" in code else "`"
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{ticks}{pad}{code}{pad}{ticks}"


def unspan(rows: list[list[tuple[str, bool, int, int]]]) -> list[list[tuple[str, bool]]]:
    """Markdown tables have no row/column spans. A row-spanning cell is repeated in every row it covers, so
    each row reads on its own ("Arma 3 v2.00 | Location", not "Location" under the version column); a
    column-spanning cell keeps its first column and leaves the others empty (titles across the whole table).
    ``rows``: (text, is header cell, rowspan, colspan) per cell; returns (text, is header cell)."""
    out: list[list[tuple[str, bool]]] = []
    pending: dict[int, tuple[tuple[str, bool], int]] = {}  # column -> (cell, rows still covered)
    for row in rows:
        line: list[tuple[str, bool]] = []
        cells = iter(row)
        while True:
            col = len(line)
            if col in pending:
                c, left = pending.pop(col)
                line.append(c)
                if left > 1:
                    pending[col] = (c, left - 1)
                continue
            nxt = next(cells, None)
            if nxt is None:
                if pending and max(pending) > col:
                    line.append(("", False))
                    continue
                break
            text, is_th, rowspan, colspan = nxt
            for k in range(colspan):
                c = (text if k == 0 else "", is_th)
                if rowspan > 1:
                    pending[len(line)] = (c, rowspan - 1)
                line.append(c)
        out.append(line)
    return out


def split_ws(s: str) -> tuple[str, str, str]:
    """(leading whitespace, the rest stripped, trailing whitespace): emphasis marks go around the core only."""
    core = s.strip()
    if not core:
        return s, "", ""
    start = s.index(core[0])
    return s[:start], core, s[start + len(core):]
