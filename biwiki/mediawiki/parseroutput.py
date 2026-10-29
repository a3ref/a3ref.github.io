# Ported from MediaWiki 1.39 includes/parser/ParserOutput.php (ParserOutput::getText() and EDITSECTION_REGEX),
# Parser::replaceTableOfContentsMarker() and the TOC_START/TOC_END markers (includes/parser/Parser.php), and
# Skin::doEditSectionLink() (includes/skins/Skin.php) (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python as functions over the HTML of a parse and the
# ParserOutput dataclass of parser.py; no hooks, no language variants, no debug info or absolute URLs; the skin is
# MediaWiki's default (the edit link of Skin::doEditSectionLink()), in English.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The HTML of a page as it is shown: the parser's HTML with the wrapper div, the section edit links and the table
of contents put in (ParserOutput::getText())."""
from __future__ import annotations

import re
from typing import Callable, Optional

from .html import element, htmlspecialchars, open_element, raw_element, close_element
from .messages import msg

EDITSECTION_REGEX = re.compile(r'<(?:mw:)?editsection page="(.*?)" section="(.*?)">(.*?)</(?:mw:)?editsection>', re.S)

# Parser::TOC_START / TOC_END (deprecated, in old cached content only)
TOC_START = "<mw:toc>"
TOC_END = "</mw:toc>"
_TOC_START_END = re.compile(re.escape(TOC_START) + ".*?" + re.escape(TOC_END), re.S)
_DEDUPLICATE = re.compile(r"<style[\t\n\x0b\f\r ]+([^>]*data-mw-deduplicate[\t\n\x0b\f\r ]*=[^>]*)>.*?</style>", re.S)
_SLOTHEADER = re.compile(r"<mw:slotheader>(.*?)</mw:slotheader>")
_SPECIALCHARS = {"&amp;": "&", "&quot;": '"', "&#039;": "'", "&#39;": "'", "&lt;": "<", "&gt;": ">"}
_SPECIALCHARS_REGEX = re.compile("|".join(re.escape(k) for k in _SPECIALCHARS))


def _htmlspecialchars_decode(text: str) -> str:
    """PHP htmlspecialchars_decode() with ENT_QUOTES, in one pass"""
    return _SPECIALCHARS_REGEX.sub(lambda m: _SPECIALCHARS[m.group(0)], text)


def replace_table_of_contents_marker(text: str, toc: str) -> str:
    """Parser::replaceTableOfContentsMarker(): replace the table-of-contents marker in parsed HTML. ``toc``: HTML
    table of contents string, or else an empty string to remove the marker."""
    from .parser import TOC_PLACEHOLDER

    # For forwards compatibility during transition period, also replace "new" TOC_PLACEHOLDER value (to be used in
    # the future, but might show up in the cache during a rollback to this version).
    return text.replace('<meta property="mw:PageProp/toc" />', toc).replace(TOC_PLACEHOLDER, toc)


def do_edit_section_link(title, section: str, section_title: str, link_renderer=None) -> str:
    """Skin::doEditSectionLink(): create a section edit link. ``title``: the Title being linked to (may not be
    the same as the current page, if the section is included from a template); ``section``: the designation of
    the section being pointed to, to be included in the link, like "&section=$section"; ``section_title``: section
    title. ``link_renderer``: a linkrenderer.LinkRenderer (link colours); without one the link is made as a known
    link without classes."""
    # HTML generated here should probably have userlangattributes added to it for LTR text on RTL pages
    attribs = {"title": msg("editsectionhint", section_title)}  # rawParams
    links = {
        "editsection": {
            "text": msg("editsection"),
            "targetTitle": title,
            "attribs": attribs,
            "query": {"action": "edit", "section": section},
        },
    }

    result = open_element("span", {"class": "mw-editsection"})
    result += raw_element("span", {"class": "mw-editsection-bracket"}, "[")

    links_html = []
    for details in links.values():
        if link_renderer is not None:
            links_html.append(link_renderer.make_known_link(details["targetTitle"], details["text"],
                                                            details["attribs"], details["query"]))
        else:
            # LinkRenderer::makeKnownLink()
            href = details["targetTitle"].get_link_url(details["query"])
            links_html.append(raw_element("a", {"href": href, **details["attribs"]},
                                          htmlspecialchars(details["text"])))

    result += raw_element("span", {"class": "mw-editsection-divider"}, msg("pipe-separator")).join(links_html)

    result += raw_element("span", {"class": "mw-editsection-bracket"}, "]")
    result += close_element("span")
    return result


def get_text(text: str, output=None, site=None, *, allow_toc: bool = True, inject_toc: bool = True,
             enable_section_edit_links: bool = True, skin=None, unwrap: bool = False,
             deduplicate_styles: bool = True, wrapper_div_class: Optional[str] = None,
             include_debug_info: bool = False, absolute_urls: bool = False,
             tidy: Optional[Callable[[str], str]] = None) -> str:
    """ParserOutput::getText(): the HTML of a parse (``text``, the parser's result) as shown on the page.

    ``output``: the ParserOutput of the parse (its ``toc_html`` and ``wrapper_div_classes``); ``site``: the
    site.Site, to read the titles of the section edit links. Options (PHP's names in brackets):
      - allow_toc (allowTOC): show the TOC, assuming there is one
      - inject_toc (injectTOC): replace the TOC marker with the TOC
      - enable_section_edit_links (enableSectionEditLinks): include section edit links, assuming section edit
        link tokens are present
      - skin: an object with do_edit_section_link(title, section, section_title), or a dict
        {"link_renderer": LinkRenderer}; default: Skin::doEditSectionLink() without link colours
      - unwrap: return text without a wrapper div
      - deduplicate_styles (deduplicateStyles): remove duplicate <style> tags marked data-mw-deduplicate
      - wrapper_div_class (wrapperDivClass): the class of the wrapper div; default: the output's
        wrapper_div_classes, else "mw-parser-output" (as Parser::parse() sets it)
      - tidy: the tidy pass (RemexDriver::tidy() with Sanitizer::armorFrenchSpaces) MediaWiki runs over the TOC;
        not ported yet, so by default the TOC is used as it is
    include_debug_info and absolute_urls are not ported and must be false."""
    if include_debug_info:
        raise NotImplementedError("includeDebugInfo (the limit report) is not ported")
    if absolute_urls:
        raise NotImplementedError("absoluteURLs (Linker::expandLocalLinks()) is not ported")
    if wrapper_div_class is None:
        classes = getattr(output, "wrapper_div_classes", None)
        wrapper_div_class = " ".join(classes) if classes is not None else "mw-parser-output"

    # (The ParserOutputPostCacheTransform hook would run here.)

    if wrapper_div_class != "" and not unwrap:
        text = raw_element("div", {"class": wrapper_div_class}, text)

    if enable_section_edit_links:
        from .sanitizer import decode_char_references
        from .site import Site
        from .title import Title

        if site is None:
            from .config import DEFAULT

            site = Site(DEFAULT)

        def edit_section(m: re.Match) -> str:
            editsection_page = Title.new_from_text(_htmlspecialchars_decode(m.group(1)), site=site)
            editsection_section = _htmlspecialchars_decode(m.group(2))
            editsection_content = decode_char_references(m.group(3))
            if editsection_page is None:
                # bad title in editsection placeholder (T261347)
                return ""
            if skin is not None and hasattr(skin, "do_edit_section_link"):
                return skin.do_edit_section_link(editsection_page, editsection_section, editsection_content)
            link_renderer = skin.get("link_renderer") if isinstance(skin, dict) else None
            return do_edit_section_link(editsection_page, editsection_section, editsection_content, link_renderer)

        text = EDITSECTION_REGEX.sub(edit_section, text)
    else:
        text = EDITSECTION_REGEX.sub("", text)

    if allow_toc:
        if inject_toc:
            toc = getattr(output, "toc_html", "") or ""
            # (language conversion of the TOC: none for English)
            if tidy is not None:
                toc = tidy(toc)
            text = replace_table_of_contents_marker(text, toc)
            # The line below can be removed once old content has expired from the parser cache
            text = text.replace(TOC_START, "").replace(TOC_END, "")
        else:
            from .parser import TOC_PLACEHOLDER

            # The line below can be removed once old content has expired from the parser cache (and
            # Parser::TOC_PLACEHOLDER should then be made private)
            text = _TOC_START_END.sub(lambda m: TOC_PLACEHOLDER, text)
    else:
        text = replace_table_of_contents_marker(text, "")
        # The line below can be removed once old content has expired from the parser cache
        text = _TOC_START_END.sub("", text)

    if deduplicate_styles:
        from .sanitizer import decode_tag_attributes
        from .site import wf_urlencode

        seen: set[str] = set()

        def deduplicate(m: re.Match) -> str:
            attr = decode_tag_attributes(m.group(1))
            if attr.get("data-mw-deduplicate") is None:
                return m.group(0)
            key = attr["data-mw-deduplicate"]
            if key not in seen:
                seen.add(key)
                return m.group(0)
            # We were going to use an empty <style> here, but there was concern that would be too much overhead
            # for browsers. So let's hope a <link> with a non-standard rel and href isn't going to be
            # misinterpreted or mangled by any subsequent processing.
            return element("link", {"rel": "mw-deduplicated-inline-style", "href": "mw-data:" + wf_urlencode(key)})

        text = _DEDUPLICATE.sub(deduplicate, text)

    # Hydrate slot section header placeholders generated by RevisionRenderer.
    text = _SLOTHEADER.sub(lambda m: _htmlspecialchars_decode(m.group(1)), text)

    # Hardens the output against NFC normalization (T387130).
    from .sanitizer import escape_combining_char

    return escape_combining_char(text)
