# Ported from MediaWiki 1.39 includes/parser/Parser.php, Parser::handleAllQuotes() and Parser::doQuotes()
# (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the tags written are a parameter (a3ref's
# former direct Markdown renderer used its own marks).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""''italic'', '''bold''' and '''''both''''', line by line."""
from __future__ import annotations

import re

HTML = ("<i>", "</i>", "<b>", "</b>")


def handle_all_quotes(text: str, tags: tuple[str, str, str, str] = HTML) -> str:
    return "\n".join(do_quotes(line, tags) for line in text.split("\n"))


def do_quotes(text: str, tags: tuple[str, str, str, str] = HTML) -> str:
    """One line. ``tags``: opening and closing italics, opening and closing bold."""
    i_open, i_close, b_open, b_close = tags
    arr = re.split(r"(''+)", text)
    if len(arr) == 1:
        return text

    # First, do some preliminary work. This may shift some apostrophes from being mark-up to being text. It also
    # counts the number of occurrences of bold and italics mark-ups.
    numbold = numitalics = 0
    for i in range(1, len(arr), 2):
        thislen = len(arr[i])
        # If there are ever four apostrophes, assume the first is supposed to be text, and the remaining three
        # constitute mark-up for bold text. (T15227: ''''foo'''' turns into ' ''' foo ' ''')
        if thislen == 4:
            arr[i - 1] += "'"
            arr[i] = "'''"
            thislen = 3
        elif thislen > 5:
            # If there are more than 5 apostrophes in a row, assume they're all text except for the last 5.
            # (T15227: ''''''foo'''''' turns into ' ''''' foo ' ''''')
            arr[i - 1] += "'" * (thislen - 5)
            arr[i] = "'''''"
            thislen = 5
        # Count the number of occurrences of bold and italics mark-ups.
        if thislen == 2:
            numitalics += 1
        elif thislen == 3:
            numbold += 1
        elif thislen == 5:
            numitalics += 1
            numbold += 1

    # If there is an odd number of both bold and italics, it is likely that one of the bold ones was meant to be an
    # apostrophe followed by italics. Which one we cannot know for certain, but it is more likely to be one that has
    # a single-letter word before it.
    if numbold % 2 == 1 and numitalics % 2 == 1:
        firstsingleletterword = firstmultiletterword = firstspace = -1
        for i in range(1, len(arr), 2):
            if len(arr[i]) == 3:
                before = arr[i - 1]
                x1 = before[-1:]
                # PHP substr( $s, -2, 1 ) on a one-character string gives that character
                x2 = before[-2] if len(before) > 1 else before[:1]
                if x1 == " ":
                    if firstspace == -1:
                        firstspace = i
                elif x2 == " ":
                    firstsingleletterword = i
                    # if firstsingleletterword is set, we don't look at the other options, so we can bail early.
                    break
                elif firstmultiletterword == -1:
                    firstmultiletterword = i
        # If there is a single-letter word, use it! If not, but there's a multi-letter word, use that one. ...
        # otherwise use the first one that has neither. (notice that it is possible for all three to be -1 if,
        # for example, there is only one pentuple-apostrophe in the line)
        for pick in (firstsingleletterword, firstmultiletterword, firstspace):
            if pick > -1:
                arr[pick] = "''"
                arr[pick - 1] += "'"
                break

    # Now let's actually convert our apostrophic mush to HTML!
    output: list[str] = []
    buffer = ""
    state = ""
    for i, r in enumerate(arr):
        if i % 2 == 0:
            if state == "both":
                buffer += r
            else:
                output.append(r)
            continue
        thislen = len(r)
        if thislen == 2:  # two quotes - open or close italics
            if state == "i":
                output.append(i_close)
                state = ""
            elif state == "bi":
                output.append(i_close)
                state = "b"
            elif state == "ib":
                output.append(b_close + i_close + b_open)
                state = "b"
            elif state == "both":
                output.append(b_open + i_open + buffer + i_close)
                state = "b"
            else:  # state can be 'b' or ''
                output.append(i_open)
                state += "i"
        elif thislen == 3:  # three quotes - open or close bold
            if state == "b":
                output.append(b_close)
                state = ""
            elif state == "bi":
                output.append(i_close + b_close + i_open)
                state = "i"
            elif state == "ib":
                output.append(b_close)
                state = "i"
            elif state == "both":
                output.append(i_open + b_open + buffer + b_close)
                state = "i"
            else:  # state can be 'i' or ''
                output.append(b_open)
                state += "b"
        elif thislen == 5:  # five quotes - open or close both separately
            if state == "b":
                output.append(b_close + i_open)
                state = "i"
            elif state == "i":
                output.append(i_close + b_open)
                state = "b"
            elif state == "bi":
                output.append(i_close + b_close)
                state = ""
            elif state == "ib":
                output.append(b_close + i_close)
                state = ""
            elif state == "both":
                output.append(i_open + b_open + buffer + b_close + i_close)
                state = ""
            else:  # state == ''
                buffer = ""
                state = "both"
    # Now close all remaining tags. Notice that the order is important.
    if state in ("b", "ib"):
        output.append(b_close)
    if state in ("i", "bi", "ib"):
        output.append(i_close)
    if state == "bi":
        output.append(b_close)
    # There might be lonely ''''', so make sure we have a buffer
    if state == "both" and buffer:
        output.append(b_open + i_open + buffer + i_close + b_close)
    return "".join(output)
