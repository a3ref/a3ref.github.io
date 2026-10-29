# Ported from MediaWiki 1.39 includes/parser/Parser.php (https://www.mediawiki.org/), (C) MediaWiki contributors:
# Parser::finalizeHeadings(), getSectionNameFromStrippedText(), makeAnchor(), makeLegacyAnchor(),
# guessSectionNameFromWikiText(), guessLegacySectionNameFromWikiText(), guessSectionNameFromStrippedText(),
# normalizeSectionName(), stripSectionName().
# Changed by a3ref contributors on 2026-10-30: translated to Python as a mixin of the Parser class; no hooks
# (ParserSectionCreate), no language variants; the numbers are formatted as in English.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Headings: anchors, numbering, the table of contents and the section edit markers (finalizeHeadings).

HeadingsMixin is mixed into Parser (parser.py), with PreprocessingMixin; it uses ``config``, ``site``,
``double_underscores``, ``show_toc``, ``force_toc_position``, ``output``, ``strip_state``, ``headings`` and the
preprocessor, and ``replace_link_holders_text()`` when the links port provides it.
"""
from __future__ import annotations

import re
from typing import Union

from .html import htmlspecialchars
from .linker import make_headline, toc_indent, toc_line, toc_line_end, toc_list, toc_unindent
from .ppframe import RECOVER_ORIG, _php_key
from .sanitizer import (ID_FALLBACK, ID_PRIMARY, decode_char_references, escape_id_for_attribute, escape_id_for_link,
                        normalize_section_name_whitespace)
from .stripstate import MARKER_PREFIX, MARKER_SUFFIX

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_HEADING_REGEX = re.compile(r"<H(?P<level>[1-6])(?P<attrib>.*?>)(?P<header>[\s\S]*?)</H[1-6] *>", re.I)
_HEADING_SPLIT = re.compile(r"<H[1-6].*?>[\s\S]*?</H[1-6]>", re.I)
_MARKER_REGEX = re.escape(MARKER_PREFIX) + r"-h-(\d+)-" + re.escape(MARKER_SUFFIX)
_MARKER_START = re.compile("^" + _MARKER_REGEX)
_MARKER_START_WS = re.compile("^" + _MARKER_REGEX + "[\t\n\x0b\f\r ]*")
_STYLE_OR_SCRIPT = re.compile(r"<(style|script)(?: [^>]*[^>/])?>.*?</\1>", re.I | re.S)
_TOCLINE_STRIP = re.compile(r"<(?!/?(span|sup|sub|bdi|i|b|s|strike|q)(?: [^>]*)?>).*?>")
_TOCLINE_KEEP = re.compile(r'<(/?(?:span(?: dir="(?:rtl|ltr)")?|sup|sub|bdi|i|b|s|strike))(?: .*?)?>')
_ANY_TAG = re.compile(r"<.*?>")


def _php_trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


def _format_num(n: int) -> str:
    """Language::formatNum() for English"""
    return f"{n:,}"


class HeadingsMixin:
    """finalizeHeadings() and the section name helpers of MediaWiki's Parser."""

    def finalize_headings(self, text: str, orig_text: str, is_main: bool = True) -> str:
        """This function accomplishes several tasks:
        1) Auto-number headings if that option is enabled
        2) Add an [edit] link to sections for users who have enabled the option and can edit the page
        3) Add a Table of contents on the top for users who have enabled the option
        4) Auto-anchor headings

        It loops through all headlines, collects the necessary data, then splits up the string and re-inserts the
        newly formatted headlines. ``orig_text``: original, untouched wikitext."""
        from .parser_preprocess import OT_WIKI

        config = self.config
        output = self.output
        # Inhibit editsection links if requested in the page
        maybe_show_edit_link = "noeditsection" not in self.double_underscores
        # (Actual presence will depend on post-cache transforms)

        # Get all headlines for numbering them and adding funky stuff like [edit] links - this is for later, but we
        # need the number of headlines right now
        # NOTE: white space in headings have been trimmed in handleHeadings. They shouldn't be trimmed here since
        # whitespace in HTML headings is significant.
        matches = list(_HEADING_REGEX.finditer(text))
        num_matches = len(matches)

        # if there are fewer than 4 headlines in the article, do not show TOC unless it's been explicitly enabled.
        enough_toc = self.show_toc and (num_matches >= 4 or self.force_toc_position)

        # Allow user to stipulate that a page should have a "new section" link added via __NEWSECTIONLINK__
        if "newsectionlink" in self.double_underscores:
            output.new_section = True

        # Allow user to remove the "new section" link via __NONEWSECTIONLINK__
        if "nonewsectionlink" in self.double_underscores:
            output.hide_new_section = True

        # if the string __FORCETOC__ (not case-sensitive) occurs in the HTML, override above conditions and always
        # show TOC above first header
        if "forcetoc" in self.double_underscores:
            self.show_toc = True
            enough_toc = True

        # headline counter
        headline_count = 0
        num_visible = 0

        # Ugh .. the TOC should have neat indentation levels which can be passed to the skin functions. These are
        # determined here
        toc = ""
        head: dict[int, str] = {}
        sublevel_count: dict[int, int] = {}
        level_count: dict[int, int] = {}
        level = 0
        prevlevel = 0
        toclevel = 0
        prevtoclevel = 0
        base_title_text = self.get_title().prefixed_db_key
        old_type = self.output_type
        self.set_output_type(OT_WIKI)
        frame = self.get_preprocessor().new_frame()
        root = self.preprocess_to_dom(orig_text)
        node = root.get_first_child()
        byte_offset = 0
        tocraw = []
        refers: dict = {}

        max_toc_level = config.max_toc_level
        for m in matches:
            headline = m.group("header")
            is_template = False
            title_text: Union[str, bool] = False
            section_index: Union[int, bool] = False
            numbering = ""
            marker_match = _MARKER_START.match(headline)
            if marker_match:
                serial = int(marker_match.group(1))
                title_text, section_index = self.headings[serial]
                is_template = title_text != base_title_text
                headline = _MARKER_START_WS.sub("", headline, count=1)

            if toclevel:
                prevlevel = level
            level = int(m.group("level"))

            if level > prevlevel:
                # Increase TOC level
                toclevel += 1
                sublevel_count[toclevel] = 0
                if toclevel < max_toc_level:
                    prevtoclevel = toclevel
                    toc += toc_indent()
                    num_visible += 1
            elif level < prevlevel and toclevel > 1:
                # Decrease TOC level, find level to jump to
                i = toclevel
                while i > 0:
                    if level_count.get(i) == level:
                        # Found last matching level
                        toclevel = i
                        break
                    elif level_count.get(i, 0) < level:
                        # Found first matching level below current level
                        toclevel = i + 1
                        break
                    i -= 1
                if i == 0:
                    toclevel = 1
                if toclevel < max_toc_level:
                    if prevtoclevel < max_toc_level:
                        # Unindent only if the previous toc level was shown :p
                        toc += toc_unindent(prevtoclevel - toclevel)
                        prevtoclevel = toclevel
                    else:
                        toc += toc_line_end()
            else:
                # No change in level, end TOC line
                if toclevel < max_toc_level:
                    toc += toc_line_end()

            level_count[toclevel] = level

            # count number of headlines for each level
            sublevel_count[toclevel] = sublevel_count.get(toclevel, 0) + 1
            dot = False
            for i in range(1, toclevel + 1):
                if sublevel_count.get(i):
                    if dot:
                        numbering += "."
                    numbering += _format_num(sublevel_count[i])
                    dot = True

            # The safe header is a version of the header text safe to use for links

            # Remove link placeholders by the link text.
            #     <!--LINK number-->
            # turns into
            #     link text with suffix
            # Do this before unstrip since link text can contain strip markers
            safe_headline = self._replace_link_holders_text(headline)

            # Avoid insertion of weird stuff like <math> by expanding the relevant sections
            safe_headline = self.strip_state.unstrip_both(safe_headline)

            # Remove any <style> or <script> tags (T198618)
            safe_headline = _STYLE_OR_SCRIPT.sub("", safe_headline)

            # Strip out HTML (first regex removes any tag not allowed)
            # Allowed tags are:
            # * <sup> and <sub> (T10393)
            # * <i> (T28375)
            # * <b> (r105284)
            # * <bdi> (T74884)
            # * <span dir="rtl"> and <span dir="ltr"> (T37167)
            # * <s> and <strike> (T35715)
            # * <q> (T251672)
            # We strip any parameter from accepted tags (second regex), except dir="rtl|ltr" from <span>, to allow
            # setting directionality in toc items.
            tocline = _TOCLINE_STRIP.sub("", safe_headline)
            tocline = _TOCLINE_KEEP.sub(r"<\1>", tocline)

            # Strip '<span></span>', which is the result from the above if <span id="foo"></span> is used to produce
            # an additional anchor for a section.
            tocline = tocline.replace("<span></span>", "")

            tocline = _php_trim(tocline)

            # For the anchor, strip out HTML-y stuff period
            safe_headline = _ANY_TAG.sub("", safe_headline)
            safe_headline = normalize_section_name_whitespace(safe_headline)

            # Save headline for section edit hint before it's escaped
            headline_hint = safe_headline

            # Decode HTML entities
            safe_headline = decode_char_references(safe_headline)

            safe_headline = self.normalize_section_name(safe_headline)

            fallback_headline = escape_id_for_attribute(safe_headline, ID_FALLBACK, config=config)
            link_anchor = escape_id_for_link(safe_headline, config=config)
            safe_headline = escape_id_for_attribute(safe_headline, ID_PRIMARY, config=config)
            if fallback_headline is None or fallback_headline == safe_headline:
                # No reason to have both (in fact, we can't)
                fallback_headline = False

            # HTML IDs must be case-insensitively unique for IE compatibility (T12721).
            array_key = safe_headline.translate(_ASCII_LOWER)
            fallback_array_key = False if fallback_headline is False else fallback_headline.translate(_ASCII_LOWER)

            # Create the anchor for linking from the TOC to the section (keys as PHP stores them: "1" is 1, false is 0)
            anchor = safe_headline
            fallback_anchor = fallback_headline
            if _php_key(array_key) in refers:
                i = 2
                while _php_key(f"{array_key}_{i}") in refers:
                    i += 1
                anchor += f"_{i}"
                link_anchor += f"_{i}"
                refers[_php_key(f"{array_key}_{i}")] = True
            else:
                refers[_php_key(array_key)] = True
            if fallback_headline is not False and _php_key(fallback_array_key) in refers:
                i = 2
                while _php_key(f"{fallback_array_key}_{i}") in refers:
                    i += 1
                fallback_anchor += f"_{i}"
                refers[_php_key(f"{fallback_array_key}_{i}")] = True
            else:
                refers[_php_key(fallback_array_key)] = True

            if enough_toc and toclevel < max_toc_level:
                toc += toc_line(link_anchor, tocline, numbering, toclevel,
                                False if is_template else section_index)

            # Add the section to the section tree
            # Find the DOM node for this header
            no_offset = is_template or section_index is False
            while node and not no_offset:
                if node.get_name() == "h":
                    bits = node.split_heading()
                    if bits["i"] == section_index:
                        break
                byte_offset += len(self.strip_state.unstrip_both(frame.expand(node, RECOVER_ORIG)))
                node = node.get_next_sibling()
            tocraw.append({
                "toclevel": toclevel,
                # cast level to string in order to keep b/c for the parse api
                "level": str(level),
                "line": tocline,
                "number": numbering,
                "index": ("T-" if is_template else "") + ("" if section_index is False else str(section_index)),
                "fromtitle": title_text,
                "byteoffset": None if no_offset else byte_offset,
                "anchor": anchor,
            })

            # give headline the correct <h#> tag
            if maybe_show_edit_link and section_index is not False:
                # Output edit section links as markers with styles that can be customized by skins
                if is_template:
                    # Put a T flag in the section identifier, to indicate to extractSections() that sections inside
                    # <includeonly> should be counted.
                    editsection_page = title_text
                    editsection_section = f"T-{section_index}"
                else:
                    editsection_page = self.get_title().prefixed_text
                    editsection_section = str(section_index)
                editsection_content = headline_hint
                # We use a bit of pesudo-xml for editsection markers. The language converter is run later on. Using
                # a UNIQ style marker leads to the converter screwing up the tokens when it converts stuff. And
                # trying to insert strip tags fails too. At this point all real inputted tags have already been
                # escaped, so we don't have to worry about a user trying to input one of these markers directly. We
                # use a page and section attribute to stop the language converter from converting these important
                # bits of data, but put the headline hint inside a content block because the language converter is
                # supposed to be able to convert that piece of data.
                # Gets replaced with html in ParserOutput::getText
                editlink = '<mw:editsection page="' + htmlspecialchars(str(editsection_page), False)
                editlink += '" section="' + htmlspecialchars(editsection_section, False) + '"'
                editlink += ">" + editsection_content + "</mw:editsection>"
            else:
                editlink = ""
            head[headline_count] = make_headline(level, m.group("attrib"), anchor, headline, editlink,
                                                 fallback_anchor)

            headline_count += 1

        self.set_output_type(old_type)

        # Never ever show TOC if no headers (or suppressed)
        suppress_toc = False  # ParserOptions::getSuppressTOC()
        if num_visible < 1 or suppress_toc:
            enough_toc = False

        if enough_toc:
            if 0 < prevtoclevel < max_toc_level:
                toc += toc_unindent(prevtoclevel - 1)
            toc = toc_list(toc)
            output.toc_html = toc
            # Record the fact that the TOC should be shown. T294950
            output.show_toc = True

        if is_main and not suppress_toc:
            # We generally output the section information via the API even if there isn't "enough" of a ToC to merit
            # showing it -- but the "suppress TOC" parser option is set when any sections that might be found aren't
            # "really there" (ie, JavaScript content that might have spurious === or <h2>: T307691) so we will
            # *not* set section information in that case.
            output.sections = tocraw

        # split up and insert constructed headlines
        blocks = _HEADING_SPLIT.split(text)

        # build an array of document sections
        sections = []
        for i, block in enumerate(blocks):
            # head is zero-based, sections aren't.
            if not head.get(i - 1):
                sections.append(block)
            else:
                sections.append(head[i - 1] + block)
            # (The ParserSectionCreate hook would be run here, one per section.)

        if enough_toc and is_main and not self.force_toc_position:
            from .parser import TOC_PLACEHOLDER

            # append the TOC at the beginning
            # Top anchor now in skin
            sections[0] += TOC_PLACEHOLDER + "\n"

        return "".join(sections)

    def _replace_link_holders_text(self, text: str) -> str:
        """Parser::replaceLinkHoldersText(): the links port's replace_link_holders_text() if there is one, else the
        text unchanged."""
        replace = getattr(self, "replace_link_holders_text", None)
        return replace(text) if replace is not None else text

    # ---- section names ----------------------------------------------------------------------------------------

    def get_section_name_from_stripped_text(self, text: str) -> str:
        text = normalize_section_name_whitespace(text)
        text = decode_char_references(text)
        return self.normalize_section_name(text)

    def make_anchor(self, section_name: str) -> str:
        return "#" + escape_id_for_link(section_name, config=self.config)

    def make_legacy_anchor(self, section_name: str) -> str:
        fragment_mode = self.config.fragment_mode
        if len(fragment_mode) > 1 and fragment_mode[1] == "legacy":
            # ForAttribute() and ForLink() are the same for legacy encoding
            id_ = escape_id_for_attribute(section_name, ID_FALLBACK, config=self.config)
        else:
            id_ = escape_id_for_link(section_name, config=self.config)
        return f"#{id_}"

    def guess_section_name_from_wiki_text(self, text: str) -> str:
        """Try to guess the section anchor name based on a wikitext fragment presumably extracted from a heading,
        for example "Header" from "== Header ==". Returns the anchor (starting with '#')."""
        # Strip out wikitext links(they break the anchor)
        text = self.strip_section_name(text)
        section_name = self.get_section_name_from_stripped_text(text)
        return self.make_anchor(section_name)

    def guess_legacy_section_name_from_wiki_text(self, text: str) -> str:
        """Same as guess_section_name_from_wiki_text(), but produces legacy anchors instead, if possible. For use
        in redirects, since various versions of Microsoft browsers interpret Location: headers as something other
        than UTF-8, resulting in breakage."""
        # Strip out wikitext links(they break the anchor)
        text = self.strip_section_name(text)
        section_name = self.get_section_name_from_stripped_text(text)
        return self.make_legacy_anchor(section_name)

    def guess_section_name_from_stripped_text(self, text: str) -> str:
        """Like guess_section_name_from_wiki_text(), but takes already-stripped text as input."""
        section_name = self.get_section_name_from_stripped_text(text)
        return self.make_anchor(section_name)

    def normalize_section_name(self, text: str) -> str:
        """Apply the same normalization as code making links to this section would"""
        from .title import MalformedTitleException, get_title_codec

        # T90902: ensure the same normalization is applied for IDs as to links
        try:
            parts = get_title_codec(self._preprocessing_site()).split_title_string(f"#{text}")
        except MalformedTitleException:
            return text
        return parts["fragment"]

    def strip_section_name(self, text: str) -> str:
        """Strips a text string of wikitext for use in a section anchor.

        Accepts a text string and then removes all wikitext from the string and leaves only the resultant text
        (i.e. the result of [[User:WikiSysop|Sysop]] would be "Sysop" and the result of [[User:WikiSysop]] would be
        "User:WikiSysop") - this is intended to create valid section anchors by mimicking the output of the parser
        when headings are parsed."""
        from .linker import valid_protocols
        from .quotes import do_quotes
        from .stringutils import delimiter_replace

        # Strip internal link markup
        text = re.sub(r"\[\[:?([^[|]+)\|([^[]+)\]\]", r"\2", text)
        text = re.sub(r"\[\[:?([^[]+)\|?\]\]", r"\1", text)

        # Strip external link markup
        # @todo FIXME: Not tolerant to blank link text
        # I.E. [https://www.mediawiki.org] will render as [1] or something depending on how many empty links there
        # are on the page - need to figure that out.
        text = re.sub(r"\[(?i:" + valid_protocols(self.config) + r")([^ ]+?) ([^[]+)\]", r"\2", text)

        # Parse wikitext quotes (italics & bold)
        text = do_quotes(text)

        # Strip HTML tags
        return delimiter_replace("<", ">", "", text)
