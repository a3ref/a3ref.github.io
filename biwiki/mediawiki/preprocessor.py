# Ported from MediaWiki 1.39 includes/parser/Preprocessor.php, Preprocessor_Hash.php, PPDStack_Hash.php,
# PPDStackElement_Hash.php and PPDPart_Hash.php (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; Preprocessor_Hash is Preprocessor (the PHP name
# is an alias); no DOM cache (WANObjectCache), so DOM_UNCACHED has no effect; positions count characters instead
# of bytes, which changes nothing as every character the preprocessor looks for is ASCII.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The preprocessor: wikitext -> a tree of templates, arguments, comments, extension tags and headings.

Differences from DOM schema:
  * attribute nodes are children
  * "<h>" nodes that aren't at the top are replaced with <possible-h>

Nodes are stored in a recursive list data structure. A node store is a list where each element may be either a
string (representing a text node) or a "descriptor", which is a two-element list where the first element is the
node name and the second element is the node store for the children.

Attributes are represented as children that have a node name starting with "@", and a single text node child.

The node classes are in ppnode.py, the expansion frames in ppframe.py; both are re-exported here.
"""
from __future__ import annotations

import re
from typing import Optional

from .ppframe import (NO_ARGS, NO_IGNORE, NO_TAGS, NO_TEMPLATES, PROCESS_NOWIKI, RECOVER_COMMENTS,  # noqa: F401
                      RECOVER_ORIG, STRIP_COMMENTS, CustomFrame, Frame, PPCustomFrame_Hash, PPFrame_Hash,
                      PPTemplateFrame_Hash, TemplateFrame)
from .ppnode import (MWException, PPNode_Hash_Array, PPNode_Hash_Attr, PPNode_Hash_Text,  # noqa: F401
                     PPNode_Hash_Tree)

# Transclusion mode flag for Preprocessor::preprocessToObj()
DOM_FOR_INCLUSION = 1
# Language conversion construct omission flag for Preprocessor::preprocessToObj()
DOM_LANG_CONVERSION_DISABLED = 2
# Preprocessor cache bypass flag for Preprocessor::preprocessToObj
DOM_UNCACHED = 4

# PCRE's \s without the u modifier: ASCII whitespace only (Python's \s also matches Unicode spaces)
_WS = "[\t\n\x0b\f\r ]"
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_cspn_cache: dict[str, re.Pattern] = {}


def _strcspn(text: str, chars: str, start: int) -> int:
    """PHP strcspn( $text, $chars, $start ): the length of the run from ``start`` without any of ``chars``."""
    regex = _cspn_cache.get(chars)
    if regex is None:
        regex = _cspn_cache[chars] = re.compile("[^" + re.escape(chars) + "]*")
    return regex.match(text, start).end() - start


def _strspn(text: str, chars: str, start: int, length: Optional[int] = None) -> int:
    """PHP strspn( $text, $chars, $start, $length ): the length of the run from ``start`` made of ``chars`` only;
    a negative ``start`` counts from the end."""
    if start < 0:
        start = max(len(text) + start, 0)
    end = len(text) if length is None else min(len(text), start + length)
    i = start
    while i < end and text[i] in chars:
        i += 1
    return max(i - start, 0)


def _strspn_rev(text: str, chars: str, end: int) -> int:
    """strspn( $revText, $chars, strlen( $text ) - $end ) on $revText = strrev( $text ): the length of the run of
    ``chars`` that ends just before ``end``."""
    i = end
    while i > 0 and text[i - 1] in chars:
        i -= 1
    return end - i


class PPDPart_Hash:  # noqa: N801 - MediaWiki's class name
    def __init__(self, out: str = ""):
        # Output accumulator
        self.out: list = []
        # Index of equals sign, if found
        self.eqpos: Optional[int] = None
        self.comment_end: Optional[int] = None
        self.visual_end: Optional[int] = None

        if out != "":
            self.out.append(out)


class PPDStackElement_Hash:  # noqa: N801 - MediaWiki's class name
    def __init__(self, open: str = "", close: str = "", saved_prefix: str = "",  # noqa: A002 - MediaWiki's name
                 start_pos: Optional[int] = None, count: int = 0, parts: Optional[list] = None,
                 line_start: bool = False):
        # Opening character (\n for heading)
        self.open = open
        # Matching closing character
        self.close = close
        # Saved prefix that may affect later processing, e.g. to differentiate `-{{{{` and `{{{{` after later
        # seeing `}}}`.
        self.saved_prefix = saved_prefix
        # Start offset of this element in the source wikitext
        self.start_pos = start_pos
        # Number of opening characters found (number of "=" for heading)
        self.count = count
        # PPDPart_Hash objects describing pipe-separated parts.
        self.parts: list[PPDPart_Hash] = parts if parts is not None else [PPDPart_Hash()]
        # True if the open char appeared at the start of the input line. Not set for headings.
        self.line_start = line_start

    def get_accum(self) -> list:
        return self.parts[-1].out

    def add_part(self, s: str = "") -> None:
        self.parts.append(PPDPart_Hash(s))

    def get_current_part(self) -> PPDPart_Hash:
        return self.parts[-1]

    def get_flags(self) -> dict:
        part_count = len(self.parts)
        find_pipe = self.open != "\n" and self.open != "["
        return {
            "findPipe": find_pipe,
            "findEquals": find_pipe and part_count > 1 and self.parts[part_count - 1].eqpos is None,
            "inHeading": self.open == "\n",
        }

    def break_syntax(self, opening_count: Optional[int] = None) -> list:
        """Get the accumulator that would result if the close is not found."""
        if self.open == "\n":
            accum = [self.saved_prefix] + self.parts[0].out
        else:
            if opening_count is None:
                opening_count = self.count
            s = self.open[:-1]
            s += self.open[-1:] * (opening_count - len(s))
            accum = [self.saved_prefix + s]
            last_index = 0
            first = True
            for part in self.parts:
                if first:
                    first = False
                elif isinstance(accum[last_index], str):
                    accum[last_index] += "|"
                else:
                    last_index += 1
                    accum.append("|")

                for node in part.out:
                    if isinstance(node, str) and isinstance(accum[last_index], str):
                        accum[last_index] += node
                    else:
                        last_index += 1
                        accum.append(node)
        return accum


class PPDStack_Hash:  # noqa: N801 - MediaWiki's class name
    """Stack class to help Preprocessor::preprocessToObj()"""

    def __init__(self):
        self.stack: list[PPDStackElement_Hash] = []
        self.top: Optional[PPDStackElement_Hash] = None
        self.root_accum: list = []
        self.accum: list = self.root_accum

    def count(self) -> int:
        return len(self.stack)

    def get_accum(self) -> list:
        return self.accum

    def get_current_part(self) -> Optional[PPDPart_Hash]:
        if self.top is None:
            return None
        return self.top.get_current_part()

    def push(self, data) -> None:
        """``data``: a PPDStackElement_Hash, or a dict of the keyword arguments to make one"""
        if isinstance(data, PPDStackElement_Hash):
            self.stack.append(data)
        else:
            self.stack.append(PPDStackElement_Hash(**data))
        self.top = self.stack[-1]
        self.accum = self.top.get_accum()

    def pop(self) -> PPDStackElement_Hash:
        if not self.stack:
            raise MWException("PPDStack_Hash::pop: no elements remaining")
        temp = self.stack.pop()

        if self.stack:
            self.top = self.stack[-1]
            self.accum = self.top.get_accum()
        else:
            self.top = None
            self.accum = self.root_accum
        return temp

    def add_part(self, s: str = "") -> None:
        self.top.add_part(s)
        self.accum = self.top.get_accum()

    def get_flags(self) -> dict:
        if not self.stack:
            return {"findEquals": False, "findPipe": False, "inHeading": False}
        return self.top.get_flags()


class Preprocessor:
    """Preprocessor using lists (Preprocessor_Hash)"""

    DOM_FOR_INCLUSION = DOM_FOR_INCLUSION
    DOM_LANG_CONVERSION_DISABLED = DOM_LANG_CONVERSION_DISABLED
    DOM_UNCACHED = DOM_UNCACHED

    # Brace matching rules
    rules = {
        "{": {"end": "}", "names": {2: "template", 3: "tplarg"}, "min": 2, "max": 3},
        "[": {"end": "]", "names": {2: None}, "min": 2, "max": 2},
        "-{": {"end": "}-", "names": {2: None}, "min": 2, "max": 2},
    }

    def __init__(self, parser, disable_lang_conversion: bool = False):
        """``disable_lang_conversion``: disable language variant conversion (the disableLangConversion option)"""
        self.parser = parser
        # Whether language variant conversion is disabled
        self.disable_lang_conversion = disable_lang_conversion

    def reset_parser(self, parser) -> None:
        """Allows resetting the internal Parser reference after Preprocessor is cloned."""
        self.parser = parser

    def new_frame(self) -> Frame:
        """Create a new top-level frame for expansion of a page"""
        return Frame(self)

    def new_custom_frame(self, args: dict) -> CustomFrame:
        """Create a new custom frame for programmatic use of parameter replacement"""
        return CustomFrame(self, args)

    def new_part_node_array(self, values) -> PPNode_Hash_Array:
        """Create a new custom node for programmatic use of parameter replacement. ``values``: a dict, or a list
        (whose keys are its indexes, as for a PHP list)."""
        from .ppframe import _php_key

        items = values.items() if isinstance(values, dict) else enumerate(values)
        node_list = []
        for k, val in items:
            k = _php_key(k)
            if isinstance(k, int):
                store = [["part", [
                    ["name", [["@index", [k]]]],
                    ["value", [str(val)]],
                ]]]
            else:
                store = [["part", [
                    ["name", [str(k)]],
                    "=",
                    ["value", [str(val)]],
                ]]]
            node_list.append(PPNode_Hash_Tree(store, 0))
        return PPNode_Hash_Array(node_list)

    def preprocess_to_obj(self, text: str, flags: int = 0) -> PPNode_Hash_Tree:
        """Get the document object model for the given wikitext.

        ``flags``: bit field of the DOM_* flags:
          - DOM_FOR_INCLUSION: treat the wikitext as transcluded content from a page rather than direct content of a
            page or message. By default, the text is assumed to be undergoing processing for use by direct page
            views. The use of this flag causes text within <noinclude> tags to be ignored, text within <includeonly>
            to be included, and text outside of <onlyinclude> to be ignored.
          - DOM_LANG_CONVERSION_DISABLED: do not parse "-{ ... }-" constructs, which are involved in language
            variant conversion.
          - DOM_UNCACHED: disable use of the preprocessor cache (there is none here).
        """
        if self.disable_lang_conversion:
            # Language conversions are globally disabled; implicitly set flag
            flags |= DOM_LANG_CONVERSION_DISABLED
        return PPNode_Hash_Tree(self.build_dom_tree_array_from_text(text, flags), 0)

    def build_dom_tree_array_from_text(self, text: str, flags: int) -> list:
        """The document object model array of the wikitext ``text`` (``flags``: DOM_* flags)"""
        for_inclusion = flags & DOM_FOR_INCLUSION
        lang_conversion_disabled = flags & DOM_LANG_CONVERSION_DISABLED

        xmlish_elements = list(self.parser.get_strip_list())
        xmlish_allow_missing_end_tag = ["includeonly", "noinclude", "onlyinclude"]
        enable_onlyinclude = False
        if for_inclusion:
            ignored_tags = ["includeonly", "/includeonly"]
            ignored_elements = ["noinclude"]
            xmlish_elements.append("noinclude")
            if "<onlyinclude>" in text and "</onlyinclude>" in text:
                enable_onlyinclude = True
        else:
            ignored_tags = ["noinclude", "/noinclude", "onlyinclude", "/onlyinclude"]
            ignored_elements = ["includeonly"]
            xmlish_elements.append("includeonly")
        # The names are not escaped, as in MediaWiki
        xmlish_regex = "|".join(xmlish_elements + ignored_tags)

        # Matched at an offset with re.match(), which anchors it there (PHP's "A" modifier)
        elements_regex = re.compile(f"({xmlish_regex})(?:{_WS}|/>|>)|(!--)", re.I | re.A)

        stack = PPDStack_Hash()

        search_base = "[{<\n"
        if not lang_conversion_disabled:
            search_base += "-"

        length_text = len(text)

        # Input pointer, starts out pointing to a pseudo-newline before the start
        i = 0
        # Current accumulator. See the module docstring for the format.
        accum = stack.get_accum()
        # True to find equals signs in arguments
        find_equals = False
        # True to take notice of pipe characters
        find_pipe = False
        heading_index = 1
        # True if i is inside a possible heading
        in_heading = False
        # True if there are no more greater-than (>) signs right of i
        no_more_gt = False
        # Map of tag name => true if there are no more closing tags of given type right of i
        no_more_closing_tag: dict[str, bool] = {}
        # True to ignore all input up to the next <onlyinclude>
        find_onlyinclude = enable_onlyinclude
        # Do a line-start run without outputting an LF character
        fake_line_start = True

        while True:
            if find_onlyinclude:
                # Ignore all input up to the next <onlyinclude>
                start_pos = text.find("<onlyinclude>", i)
                if start_pos == -1:
                    # Ignored section runs to the end
                    accum.append(["ignore", [text[i:]]])
                    break
                tag_end_pos = start_pos + len("<onlyinclude>")  # past-the-end
                accum.append(["ignore", [text[i:tag_end_pos]]])
                i = tag_end_pos
                find_onlyinclude = False

            rule = None
            if fake_line_start:
                found = "line-start"
                cur_char = ""
            else:
                # Find next opening brace, closing brace or pipe
                search = search_base
                if stack.top is None:
                    current_closing = ""
                else:
                    current_closing = stack.top.close
                    search += current_closing
                if find_pipe:
                    search += "|"
                if find_equals:
                    # First equals will be for the template
                    search += "="
                # Output literal section, advance input counter
                literal_length = _strcspn(text, search, i)
                if literal_length > 0:
                    self.add_literal(accum, text[i:i + literal_length])
                    i += literal_length
                if i >= length_text:
                    if current_closing == "\n":
                        # Do a past-the-end run to finish off the heading
                        cur_char = ""
                        found = "line-end"
                    else:
                        # All done
                        break
                else:
                    cur_char = cur_two_char = text[i]
                    if i + 1 < length_text:
                        cur_two_char += text[i + 1]
                    if cur_char == "|":
                        found = "pipe"
                    elif cur_char == "=":
                        found = "equals"
                    elif cur_char == "<":
                        found = "angle"
                    elif cur_char == "\n":
                        if in_heading:
                            found = "line-end"
                        else:
                            found = "line-start"
                    elif cur_two_char == current_closing:
                        found = "close"
                        cur_char = cur_two_char
                    elif cur_char == current_closing:
                        found = "close"
                    elif cur_two_char in self.rules:
                        cur_char = cur_two_char
                        found = "open"
                        rule = self.rules[cur_char]
                    elif cur_char in self.rules:
                        found = "open"
                        rule = self.rules[cur_char]
                    else:
                        # Some versions of PHP have a strcspn which stops on null characters; ignore these and
                        # continue. We also may get '-' and '}' characters here which don't match -{ or
                        # current_closing. Add these to output and continue.
                        if cur_char == "-" or cur_char == "}":
                            self.add_literal(accum, cur_char)
                        i += 1
                        continue

            if found == "angle":
                # Handle </onlyinclude>
                if enable_onlyinclude and text.startswith("</onlyinclude>", i):
                    find_onlyinclude = True
                    continue

                # Determine element name
                matches = elements_regex.match(text, i + 1)
                if not matches:
                    # Element name missing or not listed
                    self.add_literal(accum, "<")
                    i += 1
                    continue
                # Handle comments
                if matches.group(2) == "!--":
                    # To avoid leaving blank lines, when a sequence of space-separated comments is both preceded and
                    # followed by a newline (ignoring spaces), then trim leading and trailing spaces and the trailing
                    # newline.

                    # Find the end
                    end_pos = text.find("-->", i + 4)
                    if end_pos == -1:
                        # Unclosed comment in input, runs to end
                        inner = text[i:]
                        accum.append(["comment", [inner]])
                        i = length_text
                    else:
                        # Search backwards for leading whitespace
                        ws_start = (i - _strspn_rev(text, " \t", i)) if i else 0

                        # Search forwards for trailing whitespace
                        # ws_end will be the position of the last space (or the '>' if there's none)
                        ws_end = end_pos + 2 + _strspn(text, " \t", end_pos + 3)

                        # Keep looking forward as long as we're finding more comments.
                        comments = [(ws_start, ws_end)]
                        while text[ws_end + 1:ws_end + 5] == "<!--":
                            c = text.find("-->", ws_end + 4)
                            if c == -1:
                                break
                            c = c + 2 + _strspn(text, " \t", c + 3)
                            comments.append((ws_end + 1, c))
                            ws_end = c

                        # Eat the line if possible
                        # TODO: This could theoretically be done if ws_start == 0, i.e. for comments at the overall
                        # start. That's not how Sanitizer::removeHTMLcomments() did it, but it's a possible beneficial
                        # b/c break.
                        if ws_start > 0 and text[ws_start - 1:ws_start] == "\n" and text[ws_end + 1:ws_end + 2] == "\n":
                            # Remove leading whitespace from the end of the accumulator
                            ws_length = i - ws_start
                            end_index = len(accum) - 1

                            if (ws_length > 0 and end_index >= 0 and isinstance(accum[end_index], str)
                                    and _strspn(accum[end_index], " \t", -ws_length) == ws_length):
                                accum[end_index] = accum[end_index][:-ws_length]

                            # Dump all but the last comment to the accumulator
                            for j, com in enumerate(comments):
                                start_pos = com[0]
                                end_pos = com[1] + 1
                                if j == len(comments) - 1:
                                    break
                                inner = text[start_pos:end_pos]
                                accum.append(["comment", [inner]])

                            # Do a line-start run next time to look for headings after the comment
                            fake_line_start = True
                        else:
                            # No line to eat, just take the comment itself
                            start_pos = i
                            end_pos += 2

                        if stack.top is not None:
                            part = stack.top.get_current_part()
                            if not (part.comment_end is not None and part.comment_end == ws_start - 1):
                                part.visual_end = ws_start
                            # Else comments abutting, no change in visual end
                            part.comment_end = end_pos
                        i = end_pos + 1
                        inner = text[start_pos:end_pos + 1]
                        accum.append(["comment", [inner]])
                    continue
                name = matches.group(1)
                lower_name = name.translate(_ASCII_LOWER)
                attr_start = i + len(name) + 1

                # Find end of tag
                tag_end_pos = -1 if no_more_gt else text.find(">", attr_start)
                if tag_end_pos == -1:
                    # Infinite backtrack
                    # Disable tag search to prevent worst-case O(N^2) performance
                    no_more_gt = True
                    self.add_literal(accum, "<")
                    i += 1
                    continue

                # Handle ignored tags
                if lower_name in ignored_tags:
                    accum.append(["ignore", [text[i:tag_end_pos + 1]]])
                    i = tag_end_pos + 1
                    continue

                tag_start_pos = i
                if text[tag_end_pos - 1] == "/":
                    # Short end tag
                    attr_end = tag_end_pos - 1
                    inner = None
                    i = tag_end_pos + 1
                    close = None
                else:
                    attr_end = tag_end_pos
                    # Find closing tag
                    close_match = None
                    if name not in no_more_closing_tag:
                        close_match = re.compile("</" + re.escape(name) + _WS + "*>", re.I | re.A).search(
                            text, tag_end_pos + 1)
                    if close_match:
                        inner = text[tag_end_pos + 1:close_match.start()]
                        i = close_match.end()
                        close = close_match.group(0)
                    else:
                        # No end tag
                        if name in xmlish_allow_missing_end_tag:
                            # Let it run out to the end of the text.
                            inner = text[tag_end_pos + 1:]
                            i = length_text
                            close = None
                        else:
                            # Don't match the tag, treat opening tag as literal and resume parsing.
                            i = tag_end_pos + 1
                            self.add_literal(accum, text[tag_start_pos:tag_end_pos + 1])
                            # Cache results, otherwise we have O(N^2) performance for input like <foo><foo><foo>...
                            no_more_closing_tag[name] = True
                            continue
                # <includeonly> and <noinclude> just become <ignore> tags
                if lower_name in ignored_elements:
                    accum.append(["ignore", [text[tag_start_pos:i]]])
                    continue

                if attr_end <= attr_start:
                    attr = ""
                else:
                    # Note that the attr element contains the whitespace between name and attribute, this is
                    # necessary for precise reconstruction during pre-save transform.
                    attr = text[attr_start:attr_end]

                children = [
                    ["name", [name]],
                    ["attr", [attr]]]
                if inner is not None:
                    children.append(["inner", [inner]])
                if close is not None:
                    children.append(["close", [close]])
                accum.append(["ext", children])
            elif found == "line-start":
                # Is this the start of a heading?
                # Line break belongs before the heading element in any case
                if fake_line_start:
                    fake_line_start = False
                else:
                    self.add_literal(accum, cur_char)
                    i += 1

                # Examine upto 6 characters
                count = _strspn(text, "=", i, min(length_text, 6))
                if count == 1 and find_equals:
                    # DWIM: This looks kind of like a name/value separator. Let's let the equals handler have it and
                    # break the potential heading. This is heuristic, but AFAICT the methods for completely correct
                    # disambiguation are very complex.
                    pass
                elif count > 0:
                    stack.push(PPDStackElement_Hash(open="\n", close="\n", parts=[PPDPart_Hash("=" * count)],
                                                    start_pos=i, count=count))
                    accum = stack.get_accum()
                    stack_flags = stack.get_flags()
                    find_equals = stack_flags["findEquals"]
                    find_pipe = stack_flags["findPipe"]
                    in_heading = stack_flags["inHeading"]
                    i += count
            elif found == "line-end":
                piece = stack.top
                # A heading must be open, otherwise \n wouldn't have been in the search list
                assert piece.open == "\n"
                part = piece.get_current_part()
                # Search back through the input to see if it has a proper close.
                # Do this using the reversed string since the other solutions (end anchor, etc.) are inefficient.
                ws_length = _strspn_rev(text, " \t", i)
                search_start = i - ws_length
                if part.comment_end is not None and search_start - 1 == part.comment_end:
                    # Comment found at line end
                    # Search for equals signs before the comment
                    search_start = part.visual_end
                    search_start -= _strspn_rev(text, " \t", search_start)
                count = piece.count
                equals_length = _strspn_rev(text, "=", search_start)
                if equals_length > 0:
                    if search_start - equals_length == piece.start_pos:
                        # This is just a single string of equals signs on its own line
                        # Replicate the doHeadings behavior /={count}(.+)={count}/
                        # First find out how many equals signs there really are (don't stop at 6)
                        count = equals_length
                        if count < 3:
                            count = 0
                        else:
                            count = min(6, (count - 1) // 2)
                    else:
                        count = min(equals_length, count)
                    if count > 0:
                        # Normal match, output <h>
                        element = [["possible-h", [["@level", [count]], ["@i", [heading_index]]] + accum]]
                        heading_index += 1
                    else:
                        # Single equals sign on its own line, count=0
                        element = accum
                else:
                    # No match, no <h>, just pass down the inner text
                    element = accum
                # Unwind the stack
                stack.pop()
                accum = stack.get_accum()
                stack_flags = stack.get_flags()
                find_equals = stack_flags["findEquals"]
                find_pipe = stack_flags["findPipe"]
                in_heading = stack_flags["inHeading"]

                # Append the result to the enclosing accumulator
                accum.extend(element)

                # Note that we do NOT increment the input pointer.
                # This is because the closing linebreak could be the opening linebreak of another heading. Infinite
                # loops are avoided because the next iteration MUST hit the heading open case above, which
                # unconditionally increments the input pointer.
            elif found == "open":
                # count opening brace characters
                cur_len = len(cur_char)
                if cur_len > 1:
                    # allow the final character to repeat
                    count = _strspn(text, cur_char[cur_len - 1], i + 1) + 1
                else:
                    count = _strspn(text, cur_char, i)

                saved_prefix = ""
                line_start = i > 0 and text[i - 1] == "\n"

                if cur_char == "-{" and count > cur_len:
                    # -{ => {{ transition because rightmost wins
                    saved_prefix = "-"
                    i += 1
                    cur_char = "{"
                    count -= 1
                    rule = self.rules[cur_char]

                # we need to add to stack only if opening brace count is enough for one of the rules
                if count >= rule["min"]:
                    # Add it to the stack
                    stack.push(PPDStackElement_Hash(open=cur_char, close=rule["end"], saved_prefix=saved_prefix,
                                                    count=count, line_start=line_start))
                    accum = stack.get_accum()
                    stack_flags = stack.get_flags()
                    find_equals = stack_flags["findEquals"]
                    find_pipe = stack_flags["findPipe"]
                    in_heading = stack_flags["inHeading"]
                else:
                    # Add literal brace(s)
                    self.add_literal(accum, saved_prefix + cur_char * count)
                i += count
            elif found == "close":
                piece = stack.top
                # lets check if there are enough characters for closing brace
                max_count = piece.count
                if piece.close == "}-" and cur_char == "}":
                    max_count -= 1  # don't try to match closing '-' as a '}'
                cur_len = len(cur_char)
                count = cur_len if cur_len > 1 else _strspn(text, cur_char, i, max_count)

                # check for maximum matching characters (if there are 5 closing characters, we will probably need
                # only 3 - depending on the rules)
                rule = self.rules[piece.open]
                if count > rule["max"]:
                    # The specified maximum exists in the callback array, unless the caller has made an error
                    matching_count = rule["max"]
                else:
                    # Count is less than the maximum
                    # Skip any gaps in the callback array to find the true largest match
                    matching_count = count
                    while matching_count > 0 and matching_count not in rule["names"]:
                        matching_count -= 1

                if matching_count <= 0:
                    # No matching element found in callback array
                    # Output a literal closing brace and continue
                    end_text = text[i:i + count]
                    self.add_literal(accum, end_text)
                    i += count
                    continue
                name = rule["names"][matching_count]
                if name is None:
                    # No element, just literal text
                    end_text = text[i:i + matching_count]
                    element = piece.break_syntax(matching_count)
                    self.add_literal(element, end_text)
                else:
                    # Create XML element
                    parts = piece.parts[1:]
                    title_accum = piece.parts[0].out

                    children = []

                    # The invocation is at the start of the line if lineStart is set in the stack, and all opening
                    # brackets are used up.
                    if max_count == matching_count and piece.line_start and len(piece.saved_prefix) == 0:
                        children.append(["@lineStart", [1]])
                    title_node = ["title", title_accum]
                    children.append(title_node)
                    arg_index = 1
                    for part in parts:
                        if part.eqpos is not None:
                            equals_node = part.out[part.eqpos]
                            name_node = ["name", part.out[:part.eqpos]]
                            value_node = ["value", part.out[part.eqpos + 1:]]
                            part_node = ["part", [name_node, equals_node, value_node]]
                            children.append(part_node)
                        else:
                            name_node = ["name", [["@index", [arg_index]]]]
                            arg_index += 1
                            value_node = ["value", part.out]
                            part_node = ["part", [name_node, value_node]]
                            children.append(part_node)
                    element = [[name, children]]

                # Advance input pointer
                i += matching_count

                # Unwind the stack
                stack.pop()
                accum = stack.get_accum()

                # Re-add the old stack element if it still has unmatched opening characters remaining
                if matching_count < piece.count:
                    piece.parts = [PPDPart_Hash()]
                    piece.count -= matching_count
                    # do we still qualify for any callback with remaining count?
                    min_ = self.rules[piece.open]["min"]
                    if piece.count >= min_:
                        stack.push(piece)
                        accum = stack.get_accum()
                    elif piece.count == 1 and piece.open == "{" and piece.saved_prefix == "-":
                        piece.saved_prefix = ""
                        piece.open = "-{"
                        piece.count = 2
                        piece.close = self.rules[piece.open]["end"]
                        stack.push(piece)
                        accum = stack.get_accum()
                    else:
                        s = piece.open[:-1]
                        s += piece.open[-1:] * (piece.count - len(s))
                        self.add_literal(accum, piece.saved_prefix + s)
                elif piece.saved_prefix != "":
                    self.add_literal(accum, piece.saved_prefix)

                stack_flags = stack.get_flags()
                find_equals = stack_flags["findEquals"]
                find_pipe = stack_flags["findPipe"]
                in_heading = stack_flags["inHeading"]

                # Add XML element to the enclosing accumulator
                accum.extend(element)
            elif found == "pipe":
                find_equals = True  # shortcut for getFlags()
                stack.add_part()
                accum = stack.get_accum()
                i += 1
            elif found == "equals":
                find_equals = False  # shortcut for getFlags()
                accum.append(["equals", ["="]])
                stack.get_current_part().eqpos = len(accum) - 1
                i += 1

        # Output any remaining unclosed brackets
        for piece in stack.stack:
            stack.root_accum.extend(piece.break_syntax())

        # Enable top-level headings
        for node in stack.root_accum:
            if isinstance(node, list) and node[PPNode_Hash_Tree.NAME] == "possible-h":
                node[PPNode_Hash_Tree.NAME] = "h"

        return [["root", stack.root_accum]]

    @staticmethod
    def add_literal(accum: list, text: str) -> None:
        n = len(accum)
        if n and isinstance(accum[n - 1], str):
            accum[n - 1] += text
        else:
            accum.append(text)


# MediaWiki's class name
Preprocessor_Hash = Preprocessor
