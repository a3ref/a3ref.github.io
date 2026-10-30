# Tests of biwiki/mediawiki/ext/enforcehighlighter.py, written by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the <enforce> tag through the real Parser, against the BI wiki's own action=parse output.

tests/mediawiki/ext/EnforceHighlighter/wikiSamples.json holds {input, html} pairs: the six <enforce> blocks of
the mirrored pages and probes written to pin down the rules, with the HTML the wiki returned for them. Entries
marked "derived" had lines with tag-like text in comments (which the wiki renders oddly, see
``_escape_comment``) removed from both input and output.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.ext import enforcehighlighter
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.parseroutput import get_text
from biwiki.mediawiki.site import test_site

SAMPLES = Path(__file__).parent / "mediawiki" / "ext" / "EnforceHighlighter" / "wikiSamples.json"


def _render(wikitext: str) -> str:
    parser = Parser({}, TEST, test_site(config=TEST))
    enforcehighlighter.register(parser)
    html = parser.parse(wikitext, "setPos")
    return get_text(html, parser.output, parser.site, unwrap=False)


class EnforceHighlighterWikiSamplesTest(unittest.TestCase):
    def test_wiki_samples(self):
        samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
        self.assertGreater(len(samples), 20)
        for i, sample in enumerate(samples):
            with self.subTest(i=i, input=sample["input"][:60]):
                self.assertEqual(_render(sample["input"]).strip(), sample["html"].strip())


class EnforceHighlighterTest(unittest.TestCase):
    def test_render_block(self):
        self.assertEqual(
            enforcehighlighter.render("\n if (m_a) Print(\"x\");\n", {}),
            '<div class="enforcescripthighlighter-block armar"><div class="enforcescripthighlighter-scroller">'
            '<span class="k">if</span> <span class="p">(</span><span class="mv">m_a</span><span class="p">)</span> '
            '<span class="om">Print</span><span class="p">(</span><span class="s">&quot;x&quot;</span>'
            '<span class="p">)</span><span class="p">;</span></div></div>')

    def test_empty_inline(self):
        self.assertEqual(enforcehighlighter.render(None, {"inline": ""}),
                         '<span class="enforcescripthighlighter-block">-no code provided-</span>')

    def test_dayz_has_no_links(self):
        self.assertEqual(enforcehighlighter.render("string s;", {"game": "DayZ"}),
                         '<div class="enforcescripthighlighter-block dayz"><div class="enforcescripthighlighter-scroller">'
                         '<span class="nc">string</span> s<span class="p">;</span></div></div>')

    def test_comment_markup_is_escaped(self):
        self.assertEqual(enforcehighlighter.highlight('// <img src=x onerror="a">'),
                         '<span class="c1">// &lt;img src=x onerror="a"&gt;</span>')

    def test_string_ends_at_quote_not_after_backslash(self):
        self.assertEqual(enforcehighlighter.highlight('"a\\" b" c'),
                         '<span class="s">&quot;a\\&quot; b&quot;</span> c')


if __name__ == "__main__":
    unittest.main()
