# Tests of biwiki/mediawiki/ext/cite.py. Some cases follow the Cite extension's tests/parser/citeParserTests.txt and
# bookReferencing.txt (https://www.mediawiki.org/wiki/Extension:Cite), (C) the Cite contributors,
# GPL-2.0-or-later; translated to Python by a3ref contributors on 2026-10-30, who added the hook-point cases.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the Cite port (<ref>, <references>) through the real Parser."""
from __future__ import annotations

import unittest
from dataclasses import replace

from biwiki.mediawiki.config import TEST, Config
from biwiki.mediawiki.ext import cite
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.parseroutput import get_text
from biwiki.mediawiki.site import test_site


def _parser(config: Config = TEST) -> Parser:
    parser = Parser({}, config, test_site(config=config))
    cite.register(parser)
    return parser


def _render(wikitext: str, parser: Parser = None) -> str:
    parser = parser or _parser()
    html = parser.parse(wikitext, "Parser test")
    # (MediaWiki 1.39.0's Sanitizer, which Cite's tests expect, left "_" in ids as it is)
    return get_text(html, parser.output, parser.site, unwrap=True).rstrip().replace("&#95;", "_")


class CiteTest(unittest.TestCase):
    def test_references_added_after_parse_without_references_tag(self):
        self.assertEqual(
            _render("Wikipedia rocks!<ref>Proceeds of Rockology, vol. XXI</ref>"),
            '<p>Wikipedia rocks!<sup id="cite_ref-1" class="reference"><a href="#cite_note-1">&#91;1&#93;</a>'
            "</sup>\n</p>\n"
            '<div class="mw-references-wrap"><ol class="references">\n'
            '<li id="cite_note-1"><span class="mw-cite-backlink"><a href="#cite_ref-1">↑</a></span> '
            '<span class="reference-text">Proceeds of Rockology, vol. XXI</span>\n</li>\n</ol></div>')

    def test_reused_named_ref_backlinks_are_separated_by_spaces(self):
        # cite_references_link_many_sep is "&#32;", which MessageCache::get() turns into a space
        html = _render('<ref name="a">text</ref><ref name="a" />\n<references />')
        self.assertIn('<span class="mw-cite-backlink">↑ <sup><a href="#cite_ref-a_1-0">1.0</a></sup> '
                      '<sup><a href="#cite_ref-a_1-1">1.1</a></sup></span>', html)

    def test_group_without_references_is_an_error(self):
        parser = _parser()
        html = _render('<ref group="note">x</ref>', parser)
        self.assertIn('<a href="#cite_note-1">&#91;note 1&#93;</a>', html)
        self.assertIn('<span class="error mw-ext-cite-error" lang="en" dir="ltr">Cite error: '
                      '<code>&lt;ref&gt;</code> tags exist for a group named "note", but no corresponding '
                      '<code>&lt;references group="note"/&gt;</code> tag was found</span>', html)
        self.assertIn("cite-tracking-category-cite-error", parser.output.tracking_categories)

    def test_register_is_idempotent(self):
        parser = _parser()
        cite.register(parser)
        html = _render("a<ref>b</ref>", parser)
        self.assertEqual(html.count('<ol class="references">'), 1)

    def test_state_is_cleared_between_parses(self):
        # ParserClearState: the second parse starts numbering anew and does not list the first page's refs
        parser = _parser()
        _render("<ref>first</ref>", parser)
        html = _render("<ref>second</ref>", parser)
        self.assertIn('<sup id="cite_ref-1" class="reference">', html)
        self.assertNotIn("first", html)

    def test_references_inside_ref_definitions(self):
        html = _render('<ref name="x" />\n<references>\n<ref name="x">defined</ref>\n</references>')
        self.assertIn('<span class="reference-text">defined</span>', html)

    def test_responsive_off(self):
        html = _render('<ref>x</ref>\n<references responsive="0" />')
        self.assertNotIn("mw-references-wrap", html)
        html = _render("<ref>x</ref>", _parser(replace(TEST, cite_responsive_references=False)))
        self.assertNotIn("mw-references-wrap", html)

    def test_book_referencing(self):
        wikitext = '<ref name="a">book</ref>\n<ref extends="a">page 2</ref>'
        html = _render(wikitext)
        self.assertIn("invalid names, e.g. too many", html)
        parser = _parser(replace(TEST, cite_book_referencing=True))
        html = _render(wikitext, parser)
        self.assertIn('<a href="#cite_note-2">&#91;1.1&#93;</a>', html)
        self.assertIn('<ol class="mw-extended-references">', html)
        self.assertEqual(parser.output.page_properties.get("ref-extends"), "")


if __name__ == "__main__":
    unittest.main()
