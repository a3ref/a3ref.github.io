# Tests of biwiki/mediawiki/ext/spoiler.py. Written by a3ref contributors on 2026-10-30; the expected HTML is the BI
# wiki's (https://community.bistudio.com/), with the random spoiler IDs normalised.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the BIKI Spoiler port (<spoiler>) through the real Parser."""
from __future__ import annotations

import re
import unittest

from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.ext import spoiler
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.parseroutput import get_text
from biwiki.mediawiki.site import test_site

ID = re.compile(r"bikisp[0-9a-f]{13}")

BUTTON = '<p><button class="biki-spoiler" data-spoiler-id="ID">{}</button></p><div id="ID" class="biki-spoiler"><div>'
END = '</div></div>\n<p class="mw-empty-elt"></p>'

# (wikitext, title, the wiki's HTML without the mw-parser-output wrapper)
SAMPLES = [
    ('<spoiler text= "Show AnimationSources">\n# Terc\n</spoiler>', "Arma 3: createVehicle/vehicles",
     BUTTON.format("Show AnimationSources") + "<ol><li>Terc</li></ol>\n" + END),
    ('<spoiler text= "Show AnimationSources">\n# Lid => user\n</spoiler>', "Arma 3: createVehicle/vehicles",
     BUTTON.format("Show AnimationSources") + "<ol><li>Lid =&gt; user</li></ol>\n" + END),
    ('<spoiler text= "Show AnimationSources">\n# Drawer_1_move_source => user\n# Drawer_1_hide_source => user\n'
     '</spoiler>', "Arma 3: createVehicle/vehicles",
     BUTTON.format("Show AnimationSources") + "<ol><li>Drawer_1_move_source =&gt; user</li>\n"
     "<li>Drawer_1_hide_source =&gt; user</li></ol>\n" + END),
    ("<spoiler></spoiler>", "setPos", ""),
    ('<spoiler text="Show"></spoiler>', "setPos", ""),
    ("<spoiler>plain '''bold''' text</spoiler>", "setPos",
     BUTTON.format("Show text") + "<p>plain <b>bold</b> text\n</p>" + END),
    ('<spoiler text="Only title">x</spoiler>', "setPos", BUTTON.format("Only title") + "<p>x\n</p>" + END),
    ('<spoiler text="a &amp; <b>b</b>">body < & ></spoiler>', "setPos",
     '<p><button class="biki-spoiler" data-spoiler-id="ID">a &amp; <b< button=""><div id="ID" '
     'class="biki-spoiler"><div><p>b"&gt;body &lt; &amp; &gt;\n</p></div></div>\n<p class="mw-empty-elt"></p>'
     "</b<></button></p>"),
    ("<spoiler text='single'>x</spoiler>", "setPos", BUTTON.format("single") + "<p>x\n</p>" + END),
    ('<spoiler text="outer"><spoiler text="inner">deep</spoiler></spoiler>', "setPos",
     BUTTON.format("outer") + '<p>&lt;spoiler text="inner"&gt;deep\n</p></div></div><p>&lt;/spoiler&gt;\n</p>'
     '<p class="mw-empty-elt"></p>'),
    ('<spoiler>* a\n* b\n\n== H ==\n{| class="wikitable"\n|a||b\n|}</spoiler>', "setPos",
     BUTTON.format("Show text") + '<ul><li>a</li>\n<li>b</li></ul>\n<h2><span class="mw-headline" id="H">H</span>'
     '</h2>\n<table class="wikitable">\n<tbody><tr>\n<td>a</td>\n<td>b\n</td></tr></tbody></table>' + END),
]


def _parser() -> Parser:
    parser = Parser({}, TEST, test_site(config=TEST))
    spoiler.register(parser)
    return parser


def _render(wikitext: str, title: str = "setPos", parser: Parser = None) -> str:
    parser = parser or _parser()
    html = parser.parse(wikitext, title)
    return get_text(html, parser.output, parser.site, enable_section_edit_links=False)


def _normalised(html: str) -> str:
    return ID.sub("ID", html)


class SpoilerTest(unittest.TestCase):
    def test_wiki_samples(self):
        for wikitext, title, expected in SAMPLES:
            with self.subTest(wikitext=wikitext):
                self.assertEqual(_normalised(_render(wikitext, title)),
                                 f'<div class="mw-parser-output">{expected}</div>')

    def test_ids_count_up_per_parse_and_start_again_on_the_next(self):
        parser = _parser()
        wikitext = "<spoiler>a</spoiler>\n<spoiler>b</spoiler>"
        for _ in range(2):
            ids = ID.findall(_render(wikitext, parser=parser))
            self.assertEqual(ids, ["bikisp0000000000001"] * 2 + ["bikisp0000000000002"] * 2)

    def test_long_spoiler_ends_with_a_link_to_its_top(self):
        def items(n):
            return "\n" + "".join(f"# i{k}\n" for k in range(n))

        top = '<a href="#ID" class="bikispoiler-top">↑ Back to spoiler&#39;s top</a>'
        long_html = _normalised(_render(f"<spoiler>{items(31)}</spoiler>"))  # 32 newlines
        self.assertIn("<li>i30</li></ol>\n" + top + "</div></div>", long_html)
        self.assertNotIn("bikispoiler-top", _render(f"<spoiler>{items(30)}</spoiler>"))  # 31 newlines

    def test_spoiler_in_a_list_item_has_no_paragraph(self):
        # as on the wiki's createVehicle/vehicles page
        html = _normalised(_render('* AirportBase\n* Alien_Extractor_01_F <spoiler text= "Show AnimationSources">\n'
                                   '# move_y => user\n</spoiler>\n* Alien_Extractor_01_generic_F',
                                   "Arma 3: createVehicle/vehicles"))
        self.assertEqual(
            html, '<div class="mw-parser-output"><ul><li>AirportBase</li>\n<li>Alien_Extractor_01_F <button '
            'class="biki-spoiler" data-spoiler-id="ID">Show AnimationSources</button><div id="ID" '
            'class="biki-spoiler"><div><ol><li>move_y =&gt; user</li></ol>\n</div></div></li>\n'
            "<li>Alien_Extractor_01_generic_F</li></ul></div>")

    def test_content_of_other_tags_is_parsed(self):
        # The wiki's <sqf> (not ported) gives a block <div> in a "nowiki" strip marker, as its output shows; a
        # stand-in shows how the spoiler wraps it.
        parser = _parser()
        parser.set_hook("sqf", lambda text, argv, parser_, frame: {
            0: f'<div class="sqfhighlighter-block">{text}</div>', "markerType": "nowiki"})
        self.assertEqual(
            _normalised(_render('<spoiler>\n<sqf>hint "in";</sqf>\n</spoiler>', parser=parser)),
            '<div class="mw-parser-output">' + BUTTON.format("Show text")
            + '<p class="mw-empty-elt"></p><div class="sqfhighlighter-block">hint "in";</div>\n'
            '<p class="mw-empty-elt"></p>' + END + "</div>")


if __name__ == "__main__":
    unittest.main()
