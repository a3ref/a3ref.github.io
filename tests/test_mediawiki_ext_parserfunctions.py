# Tests of biwiki/mediawiki/ext/parserfunctions.py and the extension registration (biwiki/mediawiki/ext/__init__.py),
# written by a3ref contributors on 2026-10-30 with the results PHP 8 and ParserFunctions 1.6.0 give; the extension's
# own parser tests (tests/mediawiki/ext/ParserFunctions/) run with the other parser tests in test_mediawiki.py.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""ParserFunctions: PHP's loose comparison, #explode positions, #time ranges, string functions and registration."""
from __future__ import annotations

import re
import unittest

from biwiki.mediawiki.config import BIKI, DEFAULT, TEST
from biwiki.mediawiki.ext import register_all
from biwiki.mediawiki.ext.parserfunctions import php_loose_equals
from biwiki.mediawiki.parser import Parser, parse


def render(text: str, config=TEST, extensions=("ParserFunctions",)) -> str:
    html = parse(text, title="Parser test", config=config,
                 parser_options={"extensions": extensions, "timestamp": 123})
    html = html.removeprefix('<div class="mw-parser-output">').removesuffix("</div>")
    return re.sub(r"^<p>|\n</p>$", "", html)


class LooseEqualsTest(unittest.TestCase):
    def test_php8_string_comparison(self):
        cases = [
            ("01", "1", True), ("0", "-0", True), ("1e3", "1000", True), (" 1", "1 ", True), ("abc", "ABC", False),
            ('"01"', '"1"', False), ("1abc", "1", False),
            # integers beyond PHP_INT_MAX: compared as strings when the doubles are equal
            ("9223372036854775808", "9223372036854775809", False),
            ("9223372036854775808", "9223372036854775808", True),
            # an int and an overflown integer are never equal
            ("9223372036854775807", "9223372036854775808", False),
            # both infinite: compared as strings
            ("1e400", "2e400", False),
            # an int becomes a double for the comparison
            ("9007199254740993", "9007199254740992.0", True),
        ]
        for a, b, expected in cases:
            with self.subTest(a=a, b=b):
                self.assertIs(php_loose_equals(a, b), expected)


class FunctionsTest(unittest.TestCase):
    def test_explode_positions(self):
        config = TEST.with_(pf_enable_string_functions=True)
        cases = [("1", "b"), ("-1", "c"), ("01", ""), ("1.0", ""), ("-1.5", "b"), ("-3.5", "a"), ("-abc", ""),
                 ("3", ""), ("-4", "")]
        for pos, expected in cases:
            with self.subTest(pos=pos):
                self.assertEqual(render("{{#explode:a b c| |" + pos + "}}", config), expected)

    def test_extra_arguments_are_dropped(self):
        # as PHP drops the arguments a function does not declare (the BI wiki's Template:Link passes one more)
        config = TEST.with_(pf_enable_string_functions=True)
        self.assertEqual(render("{{#explode:a#b#c|#|1|0|2}}", config), render("{{#explode:a#b#c|#|1|0}}", config))
        self.assertEqual(render("{{#explode:a#b#c|#|1|0|2}}", config), "b")

    def test_time_year_range(self):
        too_big = '<strong class="error">Error: #time only supports years up to 9999.</strong>'
        self.assertEqual(render("{{#time:Y|9999-12-31 23:00 -05:00}}"), too_big)
        self.assertEqual(render("{{#time:Y-m-d H:i|9999-12-31 23:00 +05:00}}"), "9999-12-31 18:00")
        self.assertEqual(render("{{#time:Y}}"), "1970")  # the parse's timestamp (123)

    def test_ifexist_records_links(self):
        parser = Parser({"Foo": "x"}, TEST, extensions={"ParserFunctions"})
        parser.parse("{{#ifexist:Foo|y|n}}{{#ifexist:Bar|y|n}}{{#ifexist:Foo|y|n}}")
        self.assertEqual(parser.output.links, {0: {"Foo": 1, "Bar": 0}})
        self.assertEqual(parser.expensive_function_count, 2)  # the second Foo is in the LinkCache

    def test_string_functions_follow_the_setting(self):
        # off by default: not a function, and "#len:abc" is no valid template title either
        self.assertEqual(render("{{#len:abc}}", DEFAULT), "{{#len:abc}}")
        self.assertEqual(render("{{#len:abc}}", BIKI), "3")
        self.assertEqual(render("{{#len:abc}}", TEST.with_(pf_enable_string_functions=True)), "3")
        limit = TEST.with_(pf_enable_string_functions=True, pf_string_length_limit=3)
        self.assertEqual(render("{{#sub:abc|1}}", limit),
                         '<strong class="error">Error: String exceeds 3 character limit.</strong>')

    def test_unknown_extension(self):
        with self.assertRaises(ValueError):
            register_all(Parser(), {"ParserFunction"})


if __name__ == "__main__":
    unittest.main()
