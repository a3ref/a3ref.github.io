# Ported from MediaWiki 1.39 includes/parser/Parser.php, Parser::parse(), internalParse() and
# internalParseHalfParsed() (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python, the stages ported so far; pages and templates
# come from the ``pages`` mapping instead of a database.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Wikitext -> HTML, as MediaWiki's legacy parser does.

Ported so far: handleAllQuotes, doBlockLevels. Still to come, in Parser.php's order: the preprocessor (templates,
arguments, parser functions, extension tags, comments), Sanitizer, tables, magic words (__NOTOC__ ...), headings,
internal and external links, magic links, the table of contents, the strip state and tidy (RemexHtml).
"""
from __future__ import annotations

from typing import Mapping, Optional

from .blocklevel import do_block_levels
from .quotes import handle_all_quotes


def parse(text: str, title: str = "Main Page", pages: Optional[Mapping[str, str]] = None) -> str:
    """The HTML MediaWiki renders for ``text`` on the page ``title``; ``pages`` holds the wikitext of the other
    pages (templates, pages that links may point to), by title."""
    text = internal_parse(text)
    return internal_parse_half_parsed(text, line_start=True)


def internal_parse(text: str) -> str:
    return handle_all_quotes(text)


def internal_parse_half_parsed(text: str, line_start: bool) -> str:
    return do_block_levels(text, line_start)
