# Tests of biwiki/mediawiki/biki.py and the extension options of biwiki/mediawiki/ext/__init__.py. Written by
# a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The BI wiki's Parser setup: its pages mapping, extensions and SQF Highlighter names (no data clone needed)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biwiki.mediawiki.biki import biki_parser, load_names, load_pages
from biwiki.mediawiki.config import BIKI
from biwiki.mediawiki.ext import register_all
from biwiki.mediawiki.parser import Parser

PAGES = {
    "Template:Greet": "Hello {{{1|world}}}",
    "BIS fnc spawnGroup": "a function",
    "setPos": "a command",
}


class BikiParserTest(unittest.TestCase):
    def _parse(self, text: str, **kwargs) -> str:
        return biki_parser(PAGES, timestamp="20261030000000", **kwargs).parse(text, "Test page")

    def test_config(self):
        parser = biki_parser(PAGES)
        self.assertIs(parser.config, BIKI)
        # the wiki's own namespace (biki_siteinfo.json) is known
        self.assertEqual(parser.site.canonical_namespaces[5050], "Arma_Reforger")

    def test_templates_by_prefixed_title(self):
        self.assertIn("Hello there", self._parse("{{Greet|there}}"))

    def test_existing_pages_are_blue(self):
        html = self._parse("[[setPos]] [[BIS fnc spawnGroup]] [[Missing page]]")
        # titles are case-sensitive on the wiki ($wgCapitalLinks = false)
        self.assertIn('<a href="/wiki/setPos" title="setPos">setPos</a>', html)
        self.assertIn('<a href="/wiki/BIS_fnc_spawnGroup" title="BIS fnc spawnGroup">', html)
        self.assertIn('class="new"', html)

    def test_extensions(self):
        html = self._parse("{{#if: x | yes | no }} {{#expr: 1+2 }}<ref>note</ref><references/>"
                           "<syntaxhighlight lang=\"text\">x</syntaxhighlight><spoiler>s</spoiler>"
                           "<enforce>int a;</enforce>")
        self.assertIn("yes 3", html)
        self.assertIn('class="references"', html)
        self.assertIn('class="mw-highlight', html)
        self.assertIn('class="biki-spoiler"', html)
        self.assertNotIn("&lt;enforce", html)

    def test_sqf_names(self):
        html = self._parse("<sqf inline>hint str player</sqf>", commands=["hint"], functions=["BIS fnc a"])
        self.assertIn('<a href="/wiki/hint">hint</a>', html)
        self.assertNotIn('<a href="/wiki/str">', html)
        self.assertNotIn("<a href", self._parse("<sqf inline>hint</sqf>"))

    def test_options_for_disabled_extension(self):
        with self.assertRaises(ValueError):
            register_all(Parser(), {"Cite"}, {"SQFHighlighter": {"commands": ["hint"]}})


class LoadPagesTest(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "templates.json").write_text(json.dumps(
                {"Template:Greet": {"revid": "1", "timestamp": "2026-01-01T00:00:00Z", "wikitext": "Hi"}}),
                encoding="utf-8")
            raw = tmp / "raw"
            raw.mkdir()
            (raw / "commands.json").write_text(json.dumps(
                {"1": {"title": "setPos", "wikitext": "cmd"}}), encoding="utf-8")
            (raw / "functions.json").write_text(json.dumps(
                {"2": {"title": "BIS fnc a", "wikitext": "fnc"}}), encoding="utf-8")
            (raw / "topics.json").write_text(json.dumps(
                {"3": {"title": "Mission Design", "wikitext": "topic", "redirects": ["Missions"]}}),
                encoding="utf-8")
            pages = load_pages(tmp / "templates.json", raw)
            self.assertEqual(load_names(raw), (["setPos"], ["BIS_fnc_a"]))
        self.assertEqual(pages, {"Template:Greet": "Hi", "setPos": "cmd", "BIS fnc a": "fnc",
                                 "Mission Design": "topic", "Missions": "#REDIRECT [[Mission Design]]"})
        html = biki_parser(pages).parse("{{Greet}} [[Missions]]", "Test page")
        self.assertIn("Hi", html)
        self.assertIn('class="mw-redirect"', html)


if __name__ == "__main__":
    unittest.main()
