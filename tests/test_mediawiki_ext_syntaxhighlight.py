# Tests of biwiki/mediawiki/ext/syntaxhighlight.py, written by a3ref contributors on 2026-10-30 with the HTML
# SyntaxHighlight 1.39.0 and Pygments 2.11.2's HtmlFormatter give for a text-only token stream; the extension's own
# parser tests (tests/mediawiki/ext/SyntaxHighlight/) run with the other parser tests in test_mediawiki.py.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""SyntaxHighlight: line numbers, highlighted lines, line ranges, languages and tracking categories."""
from __future__ import annotations

import unittest

from biwiki.mediawiki.config import TEST
from biwiki.mediawiki.ext import syntaxhighlight as sh
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.parseroutput import get_text
from biwiki.mediawiki.site import test_site


def _render(wikitext: str) -> tuple[str, list[str]]:
    """The HTML (without the mw-parser-output wrapper) and the tracking categories (message keys)."""
    parser = Parser({}, TEST, test_site(config=TEST), extensions=("SyntaxHighlight",))
    html = parser.parse(wikitext, "Parser test")
    return get_text(html, parser.output, parser.site, unwrap=True).rstrip(), parser.output.tracking_categories


class SyntaxHighlightTest(unittest.TestCase):
    def test_line_numbers_start_and_highlight(self):
        html, cats = _render('<syntaxhighlight lang="CPP" line start="9" highlight="2">a\nb</syntaxhighlight>')
        self.assertEqual(
            html,
            '<div class="mw-highlight mw-highlight-lang-cpp mw-content-ltr mw-highlight-lines" dir="ltr"><pre>'
            '<span></span><span class="linenos" data-line="9"></span>a\n'
            '<span class="hll"><span class="linenos" data-line="10"></span>b\n</span></pre></div>')
        self.assertEqual(cats, [])

    def test_linelinks(self):
        html, _ = _render('<syntaxhighlight lang="text" line linelinks="L">x</syntaxhighlight>')
        self.assertIn('<pre><span></span><span id="L-1"><a href="#L-1"><span class="linenos" data-line="1"></span>'
                      '</a>x\n</span></pre>', html)

    def test_unknown_language_is_plain_and_tracked(self):
        html, cats = _render('<syntaxhighlight lang="sqf" line highlight="1">a < b</syntaxhighlight>')
        self.assertEqual(html, '<div class="mw-highlight mw-content-ltr mw-highlight-lines" dir="ltr">'
                               '<pre>a &lt; b</pre></div>')
        self.assertEqual(cats, ["syntaxhighlight-error-category"])

    def test_source_tag_and_no_language(self):
        # lang defaults to '' (not null) in processContent(), which highlightInner() reports as an unknown language
        _, cats = _render("<source>x</source>")
        self.assertEqual(cats, ["syntaxhighlight-source-category", "syntaxhighlight-error-category"])

    def test_geshi_name_and_inline_highlight(self):
        html, _ = _render('x <syntaxhighlight lang="html4strict" inline highlight="1">"a"</syntaxhighlight> y')
        self.assertEqual(html, '<p>x <code class="mw-highlight mw-highlight-lang-html mw-content-ltr" dir="ltr">'
                               '<span class="hll">&quot;a&quot; </span></code> y\n</p>')

    def test_size_limit(self):
        code = "x" * (sh.HIGHLIGHT_MAX_BYTES + 1)
        status = sh.highlight(code, "text")
        self.assertEqual(status.warnings, [("syntaxhighlight-error-exceeds-size-limit", len(code),
                                            sh.HIGHLIGHT_MAX_BYTES)])
        self.assertEqual(status.value, '<div class="mw-highlight mw-highlight-lang-text mw-content-ltr" dir="ltr">'
                                       f"<pre>{code}</pre></div>")

    def test_parse_highlight_lines(self):
        self.assertEqual(sh.parse_highlight_lines(" 1, 3-5 ,x,7-6, 0-2, 9"), [1, 3, 4, 5, 9])
        self.assertEqual(len(sh.parse_highlight_lines("1-999,1-999")), sh.HIGHLIGHT_MAX_LINES)
        self.assertEqual(sh.parse_highlight_lines("1-1001"), [])  # a range over 1000 lines is ignored


if __name__ == "__main__":
    unittest.main()
