"""MediaWiki's own parser tests: those the port passed once (tests/mediawiki/passing.txt) must keep passing.

The port and the test cases are GPL-licensed (see biwiki/mediawiki/README.md); this runner only calls them.
Run: python -m unittest; for the full report: python -m biwiki.mediawiki.parsertests --show 5
"""
from __future__ import annotations

import unittest

from biwiki.mediawiki import parsertests
from biwiki.mediawiki.blocklevel import do_block_levels
from biwiki.mediawiki.quotes import do_quotes


class MediaWikiParserTests(unittest.TestCase):
    def test_passing_tests_still_pass(self):
        known = parsertests.load_passing()
        self.assertTrue(known, "tests/mediawiki/passing.txt is missing or empty")
        data = parsertests.read()
        failed = []
        for test in data.tests:
            if test.name in known:
                result = parsertests.run_test(test, data.articles)
                if not result.passed:
                    failed.append(test.name)
        self.assertEqual(failed, [], f"{len(failed)} MediaWiki parser tests regressed")

    def test_reader(self):
        data = parsertests.read()
        self.assertGreater(len(data.tests), 1500)
        self.assertIn("Template:Foo", data.articles)
        self.assertEqual(parsertests.parse_options('cat title=[[Foo bar]] wgX="a b" parsoid=wt2html,html2wt'),
                         {"cat": True, "title": "Foo bar", "wgx": "a b", "parsoid": ["wt2html", "html2wt"]})


class PortedPassesTest(unittest.TestCase):
    def test_quotes(self):
        self.assertEqual(do_quotes("'''DO NOT'' use"), "'<i>DO NOT</i> use")

    def test_block_levels(self):
        self.assertEqual(do_block_levels("a\n\nb\n* x\n* y", True), "<p>a\n</p><p>b\n</p>\n<ul><li>x</li>\n<li>y</li></ul>")


if __name__ == "__main__":
    unittest.main()
