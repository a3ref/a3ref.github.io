# Tests of biwiki/mediawiki/ext/sqfhighlighter.py, the <sqf> and <sqs> tags of the MediaWiki parser port
# (https://www.mediawiki.org/), (C) MediaWiki contributors. The samples in tests/mediawiki/ext/SqfHighlighter/ are
# the BI wiki's action=parse output (https://community.bistudio.com/) for them.
# Written by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the SQF Highlighter (<sqf>, <sqs>) through the real Parser, against the wiki's own HTML."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.ext import sqfhighlighter
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.parseroutput import get_text
from biwiki.mediawiki.site import test_site

SAMPLES = Path(__file__).parent / "mediawiki" / "ext" / "SqfHighlighter" / "samples.json"

# The commands and functions the samples use; the wiki knows all of them, the result is the same.
COMMANDS = (
    "addMissionEventHandler alive allUnits apply benchmark call comment configFile configProperties copyToClipboard "
    "count displayCtrl estimatedTimeLeft exec findDisplay floor format getPos goto hint in lockTurret menuEnable mod "
    "name not params player position private random round select set setDamage setFaceAnimation setPos "
    "setViewDistance showCommandingMenu side spawn str systemChat text time toString vehicle west").split()
FUNCTIONS = ["BIS fnc spawnGroup"]
# A comment is wikitext: one sample has {{arma3}} in a comment, of which the wiki's HTML keeps only "Arma 3"
PAGES = {"Template:Arma3": "Arma 3"}


def _render(wikitext: str, title: str = "Parser test", commands=COMMANDS, functions=FUNCTIONS) -> str:
    parser = Parser(PAGES, TEST, test_site(config=TEST))
    sqfhighlighter.register(parser, commands=commands, functions=functions)
    html = parser.parse(wikitext, title)
    return get_text(html, parser.output, parser.site, unwrap=True).strip()


def _unwrap(html: str) -> str:
    m = re.fullmatch(r'<div class="mw-parser-output">(.*)</div>', html, re.S)
    return (m.group(1) if m else html).strip()


class SamplesTest(unittest.TestCase):
    def test_samples_match_the_wiki(self):
        samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
        for language in ("sqf", "sqs"):
            for k, sample in enumerate(samples[language]):
                with self.subTest(language=language, sample=k, input=sample["input"][:60]):
                    self.assertEqual(_render(sample["input"], sample["title"]), _unwrap(sample["html"]))


class SqfHighlighterTest(unittest.TestCase):
    def test_hook_returns_a_nowiki_strip_item(self):
        parser = Parser({}, TEST, test_site(config=TEST))
        highlighter = sqfhighlighter.register(parser)
        result = highlighter.sqf_hook("hint 1", {}, parser)
        self.assertEqual(result["markerType"], "nowiki")
        self.assertEqual(result[0], '<div class="sqfhighlighter-block"><div class="sqfhighlighter-scroller">'
                                    '<span class="gv">hint</span> <span class="n">1</span></div></div>')

    def test_block_is_wrapped_in_empty_paragraphs(self):
        self.assertEqual(
            _render("<sqf>a</sqf>"),
            '<p class="mw-empty-elt"></p><div class="sqfhighlighter-block"><div class="sqfhighlighter-scroller">'
            '<span class="gv">a</span></div></div>\n<p class="mw-empty-elt"></p>')

    def test_commands_and_functions_are_injected(self):
        code = "<sqf inline>hint BIS_fnc_a; BIS_fnc_b</sqf>"
        self.assertEqual(
            _render(code, commands=(), functions=()),
            '<p><span class="sqfhighlighter-block"><span class="gv">hint</span> <span class="fe">BIS_fnc_a</span>; '
            '<span class="fe">BIS_fnc_b</span></span>\n</p>')
        self.assertEqual(
            _render(code, commands=["hint"], functions=["BIS fnc a"]),
            '<p><span class="sqfhighlighter-block"><a href="/wiki/hint">hint</a> <a href="/wiki/BIS_fnc_a">'
            'BIS_fnc_a</a>; <span class="fe">BIS_fnc_b</span></span>\n</p>')

    def test_keywords_link_without_registration(self):
        self.assertIn('<span class="k"><a href="/wiki/if">if</a></span>',
                      _render("<sqf inline>if</sqf>", commands=()))

    def test_current_page_is_not_linked(self):
        self.assertIn('<span class="sl">hint</span>', _render("<sqf inline>hint</sqf>", title="hint"))
        self.assertIn('<span class="sl">BIS_fnc_a</span>',
                      _render("<sqf inline>BIS_fnc_a</sqf>", title="BIS fnc a", functions=()))

    def test_names_from_raw(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "functions.json"
            path.write_text(json.dumps({"2": {"title": "BIS fnc b"}, "1": {"title": "BIS fnc a"}}), encoding="utf-8")
            self.assertEqual(sqfhighlighter.names_from_raw(path), ["BIS_fnc_a", "BIS_fnc_b"])


if __name__ == "__main__":
    unittest.main()
