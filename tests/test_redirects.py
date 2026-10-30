"""Pages that only point elsewhere: wiki redirects mirrored as topics, and the lower-case alias pages."""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from biwiki.render import Pages, Writer, _redirect_stub, _sitemap, redirect_target

BASE = "https://a3ref.github.io/"


class RedirectTargetTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(redirect_target("#REDIRECT [[Description.ext]]\n[[Category: File extensions]]"),
                         ("Description.ext", ""))
        self.assertEqual(redirect_target("#REDIRECt [[Config.cpp/bin File Format]]"), ("Config.cpp/bin File Format", ""))
        self.assertEqual(redirect_target("#REDIRECT [[RVMAT_basics]]"), ("RVMAT basics", ""))
        self.assertEqual(redirect_target("#REDIRECT [[BIS File Formats#PEW_File_Formats | PEW File Formats]]"),
                         ("BIS File Formats", "PEW File Formats"))
        self.assertIsNone(redirect_target("A page with content. #REDIRECT [[X]]"))


class RedirectStubTest(unittest.TestCase):
    pages = Pages({"topics": {1: {"title": "Description.ext", "wikitext": "Mission attributes."},
                              2: {"title": "EXT", "wikitext": "#REDIRECT [[Description.ext]]"},
                              3: {"title": "CFG", "wikitext": "#REDIRECT [[Model Config]]"}}})

    def test_mirrored_target(self):
        page = _redirect_stub({"name": "EXT"}, ("Description.ext", ""), self.pages, BASE)
        self.assertIn(f'<link rel="canonical" href="{BASE}topics/Description.ext.html">', page)
        self.assertIn('<meta http-equiv="refresh" content="0; url=../topics/Description.ext.html">', page)
        self.assertIn('<a href="../topics/Description.ext.html">Description.ext</a>', page)
        self.assertNotIn("noindex", page)
        self.assertRegex(page, r'<main id="content"[^>]*>\s*<h1')

    def test_target_not_mirrored(self):
        page = _redirect_stub({"name": "CFG"}, ("Model Config", ""), self.pages, BASE)
        self.assertIn('<meta name="robots" content="noindex">', page)
        self.assertIn('href="https://community.bistudio.com/wiki/Model_Config"', page)
        self.assertNotIn("canonical", page)
        self.assertNotIn("refresh", page)

    def test_left_out_of_the_sitemap(self):
        records = {"topics": [{"title": t, "updated": None} for t in ("CFG", "Description.ext", "EXT")]}
        slugs = {"CFG": "CFG", "Description.ext": "Description.ext", "EXT": "EXT"}
        sitemap = _sitemap(BASE, records, slugs, {}, {"CFG", "EXT"})
        self.assertIn(f"{BASE}topics/Description.ext.html", sitemap)
        self.assertNotIn("CFG.html", sitemap)
        self.assertNotIn("EXT.html", sitemap)


class AliasPageTest(unittest.TestCase):
    """Linux builds write commands/setpos.html next to setPos.html; forced on here, as on a case-sensitive disk."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "commands").mkdir()
        self.writer = Writer(self.tmp, BASE)
        self.writer.aliases = True

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_alias_is_indexable_with_absolute_canonical(self):
        self.writer.write(self.tmp / "commands", "setPos", "html", "<!DOCTYPE html>page", "setPos")
        alias = (self.tmp / "commands" / "setpos.html").read_text(encoding="utf-8")
        self.assertIn(f'<link rel="canonical" href="{BASE}commands/setPos.html">', alias)
        self.assertIn('<meta http-equiv="refresh" content="0; url=setPos.html">', alias)
        self.assertNotIn("noindex", alias)
        self.assertEqual(len(re.findall(r"<title>setPos</title>", alias)), 1)

    def test_given_alias(self):
        self.writer.write(self.tmp / "commands", "setPos", "html", "page", "setPos", alias="stub")
        self.assertEqual((self.tmp / "commands" / "setpos.html").read_text(encoding="utf-8"), "stub")


if __name__ == "__main__":
    unittest.main()
