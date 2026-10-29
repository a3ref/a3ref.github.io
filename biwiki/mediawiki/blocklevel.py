# Ported from MediaWiki 1.39 includes/parser/BlockLevelPass.php (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Paragraphs, indent-pre and lists from lines starting with *, #, : or ;."""
from __future__ import annotations

import re
from typing import Optional

# State constants for the definition list colon extraction
COLON_STATE_TEXT = 0
COLON_STATE_TAG = 1
COLON_STATE_TAGSTART = 2
COLON_STATE_CLOSETAG = 3
COLON_STATE_TAGSLASH = 4
COLON_STATE_COMMENT = 5
COLON_STATE_COMMENTDASH = 6
COLON_STATE_COMMENTDASHDASH = 7
COLON_STATE_LC = 8

# P-wrapping and indent-pre are suppressed inside, not outside
_BLOCK_ELEMS = "table|h1|h2|h3|h4|h5|h6|pre|p|ul|ol|dl"
# P-wrapping and indent-pre are suppressed outside, not inside
_ANTI_BLOCK_ELEMS = "td|th"
_OPEN_MATCH = re.compile(rf"<(({_BLOCK_ELEMS})|\/({_ANTI_BLOCK_ELEMS})|"
                         r"\/?(tr|caption|dt|dd|li))\b", re.I)  # the last group always suppresses
_CLOSE_MATCH = re.compile(rf"<(\/({_BLOCK_ELEMS})|({_ANTI_BLOCK_ELEMS})|"
                          r"\/?(center|blockquote|div|hr|mw:|aside|figure))\b", re.I)  # the last group never does
_STYLE_OR_LINK_LINE = re.compile(r"^(?:<style\b[^>]*>.*?<\/style>\s*|<link\b[^>]*>\s*)+$", re.I)


def do_block_levels(text: str, line_start: bool) -> str:
    """Make lists from lines starting with ':', '*', '#', etc. ``line_start``: whether this is at the start of a
    line. Returns the lists rendered as HTML."""
    return BlockLevelPass(text, line_start).execute()


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


class BlockLevelPass:
    def __init__(self, text: str, line_start: bool):
        self.text = text
        self.line_start = line_start
        self.dt_open = False
        self.in_pre = False
        self.last_paragraph = ""

    def has_open_paragraph(self) -> bool:
        return self.last_paragraph != ""

    def close_paragraph(self, at_the_end: bool = False) -> str:
        """If a pre or p is open, return the corresponding close tag and update the state. If no tag is open,
        return an empty string. ``at_the_end``: omit trailing newline if we've reached the end."""
        result = ""
        if self.has_open_paragraph():
            result = "</" + self.last_paragraph + ">"
            if not at_the_end:
                result += "\n"
        self.in_pre = False
        self.last_paragraph = ""
        return result

    @staticmethod
    def get_common(st1: str, st2: str) -> int:
        """The length of the longest common substring of both arguments, starting at the beginning of both."""
        shorter = min(len(st1), len(st2))
        i = 0
        while i < shorter and st1[i] == st2[i]:
            i += 1
        return i

    def open_list(self, char: str) -> str:
        """Open the list item element identified by the prefix character."""
        result = self.close_paragraph()
        if char == "*":
            result += "<ul><li>"
        elif char == "#":
            result += "<ol><li>"
        elif char == ":":
            result += "<dl><dd>"
        elif char == ";":
            result += "<dl><dt>"
            self.dt_open = True
        else:
            result = "<!-- ERR 1 -->"
        return result

    def next_item(self, char: str) -> str:
        """Close the current list item and open the next one."""
        if char in ("*", "#"):
            return "</li>\n<li>"
        if char in (":", ";"):
            close = "</dt>\n" if self.dt_open else "</dd>\n"
            if char == ";":
                self.dt_open = True
                return close + "<dt>"
            self.dt_open = False
            return close + "<dd>"
        return "<!-- ERR 2 -->"

    def close_list(self, char: str) -> str:
        """Close the current list item identified by the prefix character."""
        if char == "*":
            return "</li></ul>"
        if char == "#":
            return "</li></ol>"
        if char == ":":
            if self.dt_open:
                self.dt_open = False
                return "</dt></dl>"
            return "</dd></dl>"
        return "<!-- ERR 3 -->"

    def execute(self) -> str:
        # Parsing through the text line by line. The main thing happening here is handling of block-level elements
        # p, pre, and making lists from lines starting with * # : etc.
        text_lines = self.text.split("\n")

        last_prefix = ""
        output: list[str] = []
        self.dt_open = in_block_elem = False
        prefix_length = 0
        prefix = prefix2 = ""
        pending_p_tag: str | bool = False
        in_blockquote = False

        for index, input_line in enumerate(text_lines):
            not_last_line = index + 1 < len(text_lines)

            # Fix up line_start
            if not self.line_start:
                output.append(input_line)
                self.line_start = True
                continue
            # * = ul, # = ol, ; = dt, : = dd

            last_prefix_length = len(last_prefix)
            pre_close_match = re.search(r"<\/pre", input_line, re.I) is not None
            pre_open_match = re.search(r"<pre", input_line, re.I) is not None
            # If not in a <pre> element, scan for and figure out what prefixes are there.
            if not self.in_pre:
                # Multiple prefixes may abut each other for nested lists.
                prefix_length = len(input_line) - len(input_line.lstrip("*#:;"))
                prefix = input_line[:prefix_length]
                # ; and : are both from definition-lists, so they're equivalent for the purposes of determining
                # whether or not we need to open/close elements.
                prefix2 = prefix.replace(";", ":")
                t = input_line[prefix_length:]
                self.in_pre = pre_open_match
            else:
                # Don't interpret any other prefixes in preformatted text
                prefix_length = 0
                prefix = prefix2 = ""
                t = input_line

            # List generation
            if prefix_length and last_prefix == prefix2:
                # Same as the last item, so no need to deal with nesting or opening stuff
                output.append(self.next_item(prefix[-1]))
                pending_p_tag = False

                if prefix[-1] == ";":
                    # The one nasty exception: definition lists work like this:
                    # ; title : definition text
                    # So we check for : in the remainder text to split up the title and definition, without
                    # b0rking links.
                    split = self.find_colon_no_links(t)
                    if split is not None:
                        term, t = split
                        # Trim whitespace in list items
                        output.append(_php_trim(term) + self.next_item(":"))
            elif prefix_length or last_prefix_length:
                # We need to open or close prefixes, or both.

                # Either open or close a level...
                common_prefix_length = self.get_common(prefix, last_prefix)
                pending_p_tag = False

                # Close all the prefixes which aren't shared.
                while common_prefix_length < last_prefix_length:
                    output.append(self.close_list(last_prefix[last_prefix_length - 1]))
                    last_prefix_length -= 1

                # Continue the current prefix if appropriate.
                if prefix_length <= common_prefix_length and common_prefix_length > 0:
                    output.append(self.next_item(prefix[common_prefix_length - 1]))

                # Close an open <dt> if we have a <dd> (":") starting on this line
                if self.dt_open and common_prefix_length > 0 and prefix[common_prefix_length - 1] == ":":
                    output.append(self.next_item(":"))

                # Open prefixes where appropriate.
                if last_prefix and prefix_length > common_prefix_length:
                    output.append("\n")
                while prefix_length > common_prefix_length:
                    char = prefix[common_prefix_length]
                    output.append(self.open_list(char))

                    if char == ";":
                        # @todo FIXME: This is dupe of code above
                        split = self.find_colon_no_links(t)
                        if split is not None:
                            term, t = split
                            # Trim whitespace in list items
                            output.append(_php_trim(term) + self.next_item(":"))
                    common_prefix_length += 1
                if not prefix_length and last_prefix:
                    output.append("\n")
                last_prefix = prefix2

            # If we have no prefixes, go to paragraph mode.
            if prefix_length == 0:
                # No prefix (not in list)--go to paragraph mode
                open_match = _OPEN_MATCH.search(t) is not None
                close_match = _CLOSE_MATCH.search(t) is not None

                # Any match closes the paragraph, but only when not close_match do we enter block mode. The
                # oddities with table rows and cells are to avoid paragraph wrapping in interstitial spaces
                # leading to fostered content.
                if open_match or close_match:
                    pending_p_tag = False
                    # Only close the paragraph if we're not inside a <pre> tag, or if that <pre> tag has just been
                    # opened
                    if not self.in_pre or pre_open_match:
                        output.append(self.close_paragraph())
                    if pre_open_match and not pre_close_match:
                        self.in_pre = True
                    for bq in re.finditer(r"<(\/?)blockquote[\s>]", t, re.I):
                        in_blockquote = not bq.group(1)  # is this a close tag?
                    in_block_elem = not close_match
                elif not in_block_elem and not self.in_pre:
                    if t[:1] == " " and (self.last_paragraph == "pre" or _php_trim(t) != "") and not in_blockquote:
                        # pre
                        if self.last_paragraph != "pre":
                            pending_p_tag = False
                            output.append(self.close_paragraph() + "<pre>")
                            self.last_paragraph = "pre"
                        t = t[1:]
                    elif _STYLE_OR_LINK_LINE.search(t):
                        # T186965: <style> or <link> by itself on a line shouldn't open or close paragraphs.
                        # But it should clear pending_p_tag.
                        if pending_p_tag:
                            output.append(self.close_paragraph())
                            pending_p_tag = False
                    else:
                        # paragraph
                        if _php_trim(t) == "":
                            if pending_p_tag:
                                output.append(pending_p_tag + "<br />")
                                pending_p_tag = False
                                self.last_paragraph = "p"
                            elif self.last_paragraph != "p":
                                output.append(self.close_paragraph())
                                pending_p_tag = "<p>"
                            else:
                                pending_p_tag = "</p><p>"
                        elif pending_p_tag:
                            output.append(pending_p_tag)
                            pending_p_tag = False
                            self.last_paragraph = "p"
                        elif self.last_paragraph != "p":
                            output.append(self.close_paragraph() + "<p>")
                            self.last_paragraph = "p"
            # somewhere above we forget to get out of pre block (T2785)
            if pre_close_match and self.in_pre:
                self.in_pre = False
            if pending_p_tag is False:
                if prefix_length == 0:
                    output.append(t)
                    # Add a newline if there's an open paragraph or we've yet to reach the last line.
                    if not_last_line or self.has_open_paragraph():
                        output.append("\n")
                else:
                    # Trim whitespace in list items
                    output.append(_php_trim(t))
        while prefix_length:
            output.append(self.close_list(prefix2[prefix_length - 1]))
            prefix_length -= 1
            # Note that a paragraph is only ever opened when prefix_length is zero, but we'll choose to be overly
            # cautious.
            if not prefix_length and self.has_open_paragraph():
                output.append("\n")
        output.append(self.close_paragraph(True))
        return "".join(output)

    @staticmethod
    def find_colon_no_links(s: str) -> Optional[tuple[str, str]]:
        """Split up a string on ':', ignoring any occurrences inside tags to prevent illegal overlapping. Returns
        (before, after), or None if no ':' is found."""
        m = re.compile(r":|<|-\{").search(s)
        if not m:
            return None  # Nothing to find!
        if m.group(0) == ":":
            # Easy; no tag nesting to worry about
            return s[: m.start()], s[m.start() + 1:]

        # Ugly state machine to walk through avoiding tags.
        state = COLON_STATE_TEXT
        lt_level = lc_level = 0
        i = m.start()
        while i < len(s):
            c = s[i]
            if state == COLON_STATE_TEXT:
                if c == "<":
                    # Could be either a <start> tag or an </end> tag
                    state = COLON_STATE_TAGSTART
                elif c == ":":
                    if lt_level == 0:
                        return s[:i], s[i + 1:]  # We found it!
                    # Embedded in a tag; don't break it.
                else:
                    # Skip ahead looking for something interesting
                    m = re.compile(r":|<|-\{").search(s, i)
                    if not m:
                        return None  # Nothing else interesting
                    if m.group(0) == "-{":
                        state = COLON_STATE_LC
                        lc_level += 1
                        i = m.start() + 1
                    else:
                        i = m.start() - 1  # Skip ahead to next interesting character.
            elif state == COLON_STATE_LC:
                # In language converter markup -{ ... }-
                m = re.compile(r"-\{|\}-").search(s, i)
                if not m:
                    # We're nested in language converter markup, but there are no close tags left. Abort!
                    break
                if m.group(0) == "-{":
                    i = m.start() + 1
                    lc_level += 1
                else:
                    i = m.start() + 1
                    lc_level -= 1
                    if lc_level == 0:
                        state = COLON_STATE_TEXT
            elif state == COLON_STATE_TAG:
                # In a <tag>
                if c == ">":
                    lt_level += 1
                    state = COLON_STATE_TEXT
                elif c == "/":
                    state = COLON_STATE_TAGSLASH  # Slash may be followed by >?
            elif state == COLON_STATE_TAGSTART:
                if c == "/":
                    state = COLON_STATE_CLOSETAG
                elif c == "!":
                    state = COLON_STATE_COMMENT
                elif c == ">":
                    state = COLON_STATE_TEXT  # Illegal early close? This shouldn't happen D:
                else:
                    state = COLON_STATE_TAG
            elif state == COLON_STATE_CLOSETAG:
                # In a </tag>
                if c == ">":
                    if lt_level > 0:
                        lt_level -= 1
                    # else: ignore the excess close tag, but keep looking for colons. (This matches Parsoid.)
                    state = COLON_STATE_TEXT
            elif state == COLON_STATE_TAGSLASH:
                # Yes, a self-closed tag <blah/>; else probably we're jumping the gun, and this is an attribute
                state = COLON_STATE_TEXT if c == ">" else COLON_STATE_TAG
            elif state == COLON_STATE_COMMENT:
                if c == "-":
                    state = COLON_STATE_COMMENTDASH
            elif state == COLON_STATE_COMMENTDASH:
                state = COLON_STATE_COMMENTDASHDASH if c == "-" else COLON_STATE_COMMENT
            elif state == COLON_STATE_COMMENTDASHDASH:
                state = COLON_STATE_TEXT if c == ">" else COLON_STATE_COMMENT
            i += 1
        # Invalid input; not enough close tags
        return None
