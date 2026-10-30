# Written by a3ref contributors on 2026-10-30 after the HTML of the BI wiki's BIKI Spoiler extension.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Bohemia Interactive's BIKI Spoiler extension: the <spoiler> tag, a button that shows or hides its content.

The extension is not public; this module reproduces the HTML the BI wiki produces:

``<spoiler text="Title">content</spoiler>`` gives
``<button class="biki-spoiler" data-spoiler-id="ID">Title</button><div id="ID" class="biki-spoiler"><div>HTML</div></div>``

- the content is parsed fully as wikitext (Parser::recursiveTagParseFully: block-level pass and tidy included);
- an empty or missing content gives nothing at all, whatever the text;
- a long content (more than 31 newlines in the wikitext) is followed, inside the inner <div>, by
  ``<a href="#ID" class="bikispoiler-top">↑ Back to spoiler&#39;s top</a>``;
- ``text`` is put into the button as it is, without escaping; without ``text`` the button says "Show text";
- the hook's output is a "nowiki" strip marker, unstripped after the page's block-level pass, which therefore sees
  only the marker and wraps it in a paragraph; tidy then closes the paragraph at the <div> and turns the closing
  ``</p>`` after it into an empty paragraph (``<p><button ...>...</button></p><div ...>...</div>\n<p
  class="mw-empty-elt"></p>``). A general marker, unstripped before the block-level pass, gives no paragraph.

The ID: on the wiki it is PHP's ``uniqid("bikisp")`` ("bikisp" and 13 hex digits of the current time), random on
each parse. Here it is deterministic: "bikisp" and the 13 hex digits of a counter of the spoilers of the parse,
starting at 1. The counter belongs to the parse's ParserOutput, which the parser replaces at the start of each parse
(as Cite emulates ParserClearState), so each parse starts again at ``bikisp0000000000001``.

Parser interface: set_hook, recursive_tag_parse_fully, get_output.
"""
from __future__ import annotations

from typing import Optional

ID_PREFIX = "bikisp"
DEFAULT_TEXT = "Show text"
TOP_LINK_TEXT = "↑ Back to spoiler&#39;s top"
# A long spoiler ends with a link back to its button. On the BI wiki's createVehicle/vehicles page every spoiler
# whose wikitext has 32 or more newlines has the link and none with 31 or fewer has it.
MAX_NEWLINES_WITHOUT_TOP_LINK = 31


def next_id(parser) -> str:
    """The next spoiler ID of this parse (in place of uniqid("bikisp"))."""
    state = getattr(parser, "_ext_spoiler", None)
    output = parser.get_output()
    if state is None or state[0] is not output:
        state = [output, 0]
        parser._ext_spoiler = state
    state[1] += 1
    return f"{ID_PREFIX}{state[1]:013x}"


def spoiler_hook(text: Optional[str], argv: dict, parser, frame) -> str:
    """Parser hook for the <spoiler> tag."""
    if not text:
        return ""
    title = argv.get("text", DEFAULT_TEXT)
    spoiler_id = next_id(parser)
    content = parser.recursive_tag_parse_fully(text, frame)
    if text.count("\n") > MAX_NEWLINES_WITHOUT_TOP_LINK:
        content += f'<a href="#{spoiler_id}" class="bikispoiler-top">{TOP_LINK_TEXT}</a>'
    html = (f'<button class="biki-spoiler" data-spoiler-id="{spoiler_id}">{title}</button>'
            f'<div id="{spoiler_id}" class="biki-spoiler"><div>{content}</div></div>')
    return {0: html, "markerType": "nowiki"}


def register(parser) -> None:
    """ParserFirstCallInit: the <spoiler> tag."""
    parser.set_hook("spoiler", spoiler_hook)
