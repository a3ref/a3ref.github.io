# Ported from MediaWiki 1.39 includes/parser/Parser.php, Parser::handleTables() (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the strip state is a parameter.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Wiki tables ({| ... |}) -> HTML tables."""
from __future__ import annotations

import re

from .sanitizer import fix_tag_attributes
from .stringutils import replace_markup
from .stripstate import StripState


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


def handle_tables(text: str, strip_state: StripState) -> str:
    """Parse the wiki syntax used to render tables."""
    lines = text.split("\n")
    out: list[str] = []
    td_history: list[bool] = []  # Is currently a td tag open?
    last_tag_history: list[str] = []  # Save history of last lag activated (td, th or caption)
    tr_history: list[bool] = []  # Is currently a tr tag open?
    tr_attributes: list[str] = []  # history of tr attributes
    has_opened_tr: list[bool] = []  # Did this table open a <tr> element?
    indent_level = 0  # indent level of the table

    for out_line in lines:
        line = _php_trim(out_line)

        if line == "":  # empty line, go to next line
            out.append(out_line + "\n")
            continue

        first_character = line[0]
        first_two = line[:2]

        m = re.match(r"^(:*)\s*\{\|(.*)$", line, re.S)
        if m:
            # First check if we are starting a new table
            indent_level = len(m.group(1))
            attributes = strip_state.unstrip_both(m.group(2))
            attributes = fix_tag_attributes(attributes, "table")
            out_line = "<dl><dd>" * indent_level + f"<table{attributes}>"
            td_history.append(False)
            last_tag_history.append("")
            tr_history.append(False)
            tr_attributes.append("")
            has_opened_tr.append(False)
        elif not td_history:
            # Don't do any of the following
            out.append(out_line + "\n")
            continue
        elif first_two == "|}":
            # We are ending a table
            line = "</table>" + line[2:]
            last_tag = last_tag_history.pop()

            if not has_opened_tr.pop():
                line = f"<tr><td></td></tr>{line}"
            if tr_history.pop():
                line = f"</tr>{line}"
            if td_history.pop():
                line = f"</{last_tag}>{line}"
            tr_attributes.pop()
            if indent_level > 0:
                out_line = line.rstrip(" \t\n\r\0\x0b") + "</dd></dl>" * indent_level
            else:
                out_line = line
        elif first_two == "|-":
            # Now we have a table row
            line = re.sub(r"^\|-+", "", line)

            # Whats after the tag is now only attributes
            attributes = strip_state.unstrip_both(line)
            attributes = fix_tag_attributes(attributes, "tr")
            tr_attributes.pop()
            tr_attributes.append(attributes)

            line = ""
            last_tag = last_tag_history.pop()
            has_opened_tr.pop()
            has_opened_tr.append(True)

            if tr_history.pop():
                line = "</tr>"
            if td_history.pop():
                line = f"</{last_tag}>{line}"

            out_line = line
            tr_history.append(False)
            td_history.append(False)
            last_tag_history.append("")
        elif first_character in ("|", "!") or first_two == "|+":
            # This might be cell elements, td, th or captions
            if first_two == "|+":
                first_character = "+"
                line = line[2:]
            else:
                line = line[1:]

            # Implies both are valid for table headings.
            if first_character == "!":
                line = replace_markup("!!", "||", line)

            # Split up multiple cells on the same line.
            # FIXME : This can result in improper nesting of tags processed by earlier parser steps.
            cells = line.split("||")

            out_line = ""

            # Loop through each table cell
            for cell in cells:
                previous = ""
                if first_character != "+":
                    tr_after = tr_attributes.pop()
                    if not tr_history.pop():
                        previous = f"<tr{tr_after}>\n"
                    tr_history.append(True)
                    tr_attributes.append("")
                    has_opened_tr.pop()
                    has_opened_tr.append(True)

                last_tag = last_tag_history.pop()

                if td_history.pop():
                    previous = f"</{last_tag}>\n{previous}"

                if first_character == "|":
                    last_tag = "td"
                elif first_character == "!":
                    last_tag = "th"
                elif first_character == "+":
                    last_tag = "caption"
                else:
                    last_tag = ""

                last_tag_history.append(last_tag)

                # A cell could contain both parameters and data
                cell_data = cell.split("|", 1)

                # T2553: Note that a '|' inside an invalid link should not be mistaken as delimiting cell
                # parameters. Bug T153140: Neither should language converter markup.
                if re.search(r"\[\[|-\{", cell_data[0]):
                    cell = f"{previous}<{last_tag}>" + _php_trim(cell)
                elif len(cell_data) == 1:
                    # Whitespace in cells is trimmed
                    cell = f"{previous}<{last_tag}>" + _php_trim(cell_data[0])
                else:
                    attributes = strip_state.unstrip_both(cell_data[0])
                    attributes = fix_tag_attributes(attributes, last_tag)
                    # Whitespace in cells is trimmed
                    cell = f"{previous}<{last_tag}{attributes}>" + _php_trim(cell_data[1])

                out_line += cell
                td_history.append(True)
        out.append(out_line + "\n")

    # Closing open td, tr && table
    while td_history:
        if td_history.pop():
            out.append("</td>\n")
        if tr_history.pop():
            out.append("</tr>\n")
        if not has_opened_tr.pop():
            out.append("<tr><td></td></tr>\n")
        out.append("</table>\n")

    result = "".join(out)
    # Remove trailing line-ending (b/c)
    if result.endswith("\n"):
        result = result[:-1]

    # special case: don't return empty table
    if result == "<table>\n<tr><td></td></tr>\n</table>":
        result = ""

    return result
