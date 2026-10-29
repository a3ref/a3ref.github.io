# Tests of biwiki/mediawiki/parser_headings.py and parseroutput.py, the port of Parser::finalizeHeadings(),
# ParserOutput::getText() and Linker's TOC functions of MediaWiki 1.39 (https://www.mediawiki.org/),
# (C) MediaWiki contributors. Some cases run MediaWiki's own parser tests (tests/mediawiki/parserTests.txt).
# Written by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Heading anchors, section edit links and the table of contents."""
from __future__ import annotations

import inspect
import re
import unittest

from biwiki.mediawiki import parsertests
from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.linker import make_headline, toc_line, toc_unindent
from biwiki.mediawiki.parser import TOC_PLACEHOLDER, Parser
from biwiki.mediawiki.parser_headings import HeadingsMixin
from biwiki.mediawiki.parseroutput import do_edit_section_link, get_text
from biwiki.mediawiki.site import test_site
from biwiki.mediawiki.title import Title

# Until parser.py calls finalize_headings() itself, wire it in here
if issubclass(Parser, HeadingsMixin) and "finalize_headings" in inspect.getsource(Parser.internal_parse):
    HeadingsParser = Parser
else:
    class HeadingsParser(*((Parser,) if issubclass(Parser, HeadingsMixin) else (HeadingsMixin, Parser))):
        def internal_parse(self, text, is_main=True, frame=None):
            orig_text = text
            text = Parser.internal_parse(self, text, is_main, frame)
            return self.finalize_headings(text, orig_text, is_main)


def tidy_toc(toc: str) -> str:
    """Stand-in for the tidy pass (RemexHtml) over the TOC: void elements serialised as "<x ... />"."""
    return re.sub(r"([^ ])/>", r"\1 />", toc)


def render(wikitext: str, title: str = "Parser test", pages=None, config=TEST, **options):
    parser = HeadingsParser(pages or {}, config, test_site(config=config))
    html = parser.parse(wikitext, title)
    options.setdefault("unwrap", True)
    return get_text(html, parser.output, parser.site, tidy=tidy_toc, **options), parser


def edit_link(section: int, hint: str, page: str = "Parser_test") -> str:
    return ('<span class="mw-editsection"><span class="mw-editsection-bracket">[</span>'
            f'<a href="/index.php?title={page}&amp;action=edit&amp;section={section}" title="Edit section: {hint}">'
            'edit</a><span class="mw-editsection-bracket">]</span></span>')


class MediaWikiParserTests(unittest.TestCase):
    """MediaWiki's parser tests about headings and the TOC that the port passes."""

    NAMES = [
        "Basic section headings",
        "Section headings with TOC",
        "Handling of sections up to level 6 and beyond",
        "Resolving duplicate section names",
        "Resolving duplicate section names with differing case (T12721)",
        "TOC anchors don't collide",
        "TOC with wgMaxTocLevel=3 (T8204)",
        "TOC with wgMaxTocLevel=3 and two level four headings (T8204)",
        "Out-of-order TOC heading levels",
        "TOC regression (T11764)",
        "__NOEDITSECTION__ keyword",
        "Disable TOC",
        "T8563: Edit link generation for section shown by <includeonly>",
        "Tags with parameters in TOC",
        "span tags with directionality in TOC",
        "T198618: script element in ToC",
        "includeonly / noinclude / onlyinclude and headers",
    ]

    def test_parser_tests(self):
        data = parsertests.read()
        tests = {t.name: t for t in data.tests}
        for name in self.NAMES:
            test = tests[name]
            with self.subTest(name):
                config = parsertests.test_config(test)
                parser = HeadingsParser(data.articles, config,
                                        test_site(subpages="subpage" in test.options, config=config))
                title = test.options.get("title", parsertests.DEFAULT_TITLE)
                html = parser.parse(test.wikitext, title if isinstance(title, str) else parsertests.DEFAULT_TITLE)
                actual = get_text(html, parser.output, parser.site, allow_toc="notoc" not in test.options,
                                  unwrap="wrap" not in test.options, tidy=tidy_toc)
                self.assertEqual(test.legacy_html, re.sub(r"\s+$", "", actual))


class FinalizeHeadingsTest(unittest.TestCase):
    def test_anchors_and_edit_links(self):
        html, parser = render("== A ==\n== a ==\n=== A ===")
        self.assertEqual(f'<h2><span class="mw-headline" id="A">A</span>{edit_link(1, "A")}</h2>\n'
                         f'<h2><span class="mw-headline" id="a_2">a</span>{edit_link(2, "a")}</h2>\n'
                         f'<h3><span class="mw-headline" id="A_3">A</span>{edit_link(3, "A")}</h3>', html)
        self.assertEqual([s["anchor"] for s in parser.output.sections], ["A", "a_2", "A_3"])
        self.assertEqual([s["number"] for s in parser.output.sections], ["1", "2", "2.1"])
        self.assertEqual([s["byteoffset"] for s in parser.output.sections], [0, 8, 16])

    def test_php_array_key_quirk(self):
        # PHP stores the missing fallback anchor (false) under the key 0, and "0" under 0 too: a heading "0" after
        # another heading counts as a duplicate
        html, _ = render("== A ==\n== 0 ==", enable_section_edit_links=False)
        self.assertIn('id="0_2"', html)

    def test_legacy_fallback_anchor(self):
        config = TEST.with_(fragment_mode=("html5", "legacy"))
        html, _ = render("== ä b ==", config=config, enable_section_edit_links=False)
        self.assertEqual('<h2><span id=".C3.A4_b"></span><span class="mw-headline" id="ä_b">ä b</span></h2>', html)

    def test_template_section(self):
        html, parser = render("{{T}}", pages={"Template:T": "== From T =="})
        self.assertEqual(f'<h2><span class="mw-headline" id="From_T">From T</span>'
                         f'{edit_link("T-1", "From T", "Template:T")}</h2>', html)
        self.assertEqual("T-1", parser.output.sections[0]["index"])
        self.assertEqual("Template:T", parser.output.sections[0]["fromtitle"])

    def test_toc(self):
        html, parser = render("==a==\n==b==\n==c==\n==d==", enable_section_edit_links=False)
        self.assertTrue(html.startswith('<div id="toc" class="toc" role="navigation"'))
        self.assertIn('<li class="toclevel-1 tocsection-4"><a href="#d"><span class="tocnumber">4</span> '
                      '<span class="toctext">d</span></a></li>\n</ul>\n</div>\n\n<h2>', html)
        self.assertTrue(parser.output.show_toc)
        # fewer than four headings: no TOC unless forced
        html, _ = render("==a==\n==b==")
        self.assertNotIn('id="toc"', html)
        html, _ = render("__FORCETOC__\n==a==")
        self.assertIn('id="toc"', html)
        # __TOC__ places it; __NOTOC__ removes it; allow_toc=False drops it
        html, _ = render("x\n__TOC__\n==a==", enable_section_edit_links=False)
        self.assertLess(html.index("<p>x"), html.index('<div id="toc"'))
        self.assertLess(html.index('<div id="toc"'), html.index("<h2>"))
        html, _ = render("__NOTOC__\n==a==\n==b==\n==c==\n==d==")
        self.assertNotIn('id="toc"', html)
        html, _ = render("==a==\n==b==\n==c==\n==d==", allow_toc=False)
        self.assertNotIn('id="toc"', html)
        self.assertNotIn(TOC_PLACEHOLDER, html)

    def test_section_names(self):
        parser = HeadingsParser({}, TEST, test_site(config=TEST))
        parser.parse("", "Parser test")
        self.assertEqual("#Bar_x_and_y", parser.guess_section_name_from_wiki_text("[[Foo|Bar]] ''x'' and <b>y</b>"))
        self.assertEqual("#a_b", parser.guess_section_name_from_stripped_text("a  _b"))
        self.assertEqual("a b", parser.normalize_section_name("a_b"))
        legacy = HeadingsParser({}, TEST.with_(fragment_mode=("html5", "legacy")), test_site(config=TEST))
        legacy.parse("", "Parser test")
        self.assertEqual("#.C3.A4", legacy.guess_legacy_section_name_from_wiki_text("ä"))


class GetTextTest(unittest.TestCase):
    def test_wrapper_and_edit_links(self):
        site = test_site()
        marker = '<h2><span class="mw-headline" id="A">A</span><mw:editsection page="Main Page" section="1">A &amp; ' \
                 "B</mw:editsection></h2>"
        self.assertEqual(f'<div class="mw-parser-output">{marker}</div>'.replace(
            '<mw:editsection page="Main Page" section="1">A &amp; B</mw:editsection>',
            edit_link(1, "A &amp; B", "Main_Page")), get_text(marker, None, site))
        self.assertEqual('<div class="x"><h2><span class="mw-headline" id="A">A</span></h2></div>',
                         get_text(marker, None, site, wrapper_div_class="x", enable_section_edit_links=False))
        self.assertEqual("", get_text('<mw:editsection page="" section="1">x</mw:editsection>', None, site,
                                      unwrap=True))

    def test_deduplicate_styles(self):
        style = '<style data-mw-deduplicate="TemplateStyles:r1">a{}</style>'
        self.assertEqual(style + '<link rel="mw-deduplicated-inline-style" href="mw-data:TemplateStyles:r1"/>',
                         get_text(style + style, unwrap=True))
        self.assertEqual(style + style, get_text(style + style, unwrap=True, deduplicate_styles=False))

    def test_edit_section_link(self):
        title = Title.new_from_text("Foo bar", site=test_site())
        self.assertEqual(edit_link("T-2", "x &quot;y&quot;", "Foo_bar"), do_edit_section_link(title, "T-2", 'x "y"'))


class LinkerTest(unittest.TestCase):
    def test_toc_helpers(self):
        self.assertEqual("</li>\n</ul>\n</li>\n</ul>\n</li>\n", toc_unindent(2))
        self.assertEqual("</li>\n", toc_unindent(-1))
        self.assertEqual('<li class="toclevel-1"><a href="#a"><span class="tocnumber">1&amp;</span> '
                         '<span class="toctext"><i>a</i></span></a>', toc_line("a", "<i>a</i>", "1&", 1))
        self.assertEqual('<h2 class="x"><span id="b"></span><span class="mw-headline" id="a&quot;">t</span>L</h2>',
                         make_headline(2, ' class="x">', 'a"', "t", "L", "b"))
        self.assertEqual('<h2><span class="mw-headline" id="a">t</span></h2>', make_headline(2, ">", "a", "t", "", "a"))


if __name__ == "__main__":
    unittest.main()
