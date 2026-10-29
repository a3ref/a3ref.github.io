# Tests of biwiki/mediawiki/sanitizer.py and stringutils.py. Many cases are taken from MediaWiki 1.39's
# tests/phpunit/includes/parser/SanitizerTest.php, tests/phpunit/unit/includes/parser/SanitizerUnitTest.php,
# tests/phpunit/integration/includes/SanitizerValidateEmailTest.php and
# tests/phpunit/unit/includes/libs/StringUtilsTest.php (https://www.mediawiki.org/), (C) MediaWiki contributors,
# GPL-2.0-or-later; translated to Python by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the Sanitizer and StringUtils ports (cases from MediaWiki's PHPUnit tests, GPL-2.0-or-later)."""
from __future__ import annotations

import unittest

from biwiki.mediawiki import sanitizer as s
from biwiki.mediawiki.config import DEFAULT
from biwiki.mediawiki.stringutils import (delimiter_explode, delimiter_replace, delimiter_replace_callback,
                                          hungry_delimiter_replace, is_utf8, replace_markup)


class HtmlTagsTest(unittest.TestCase):
    HTML5_TAGS = [("data", False), ("mark", False), ("time", False), ("video", True)]  # (tag, escaped)

    REMOVE_HTML_TAGS = [
        ("<div>Hello world</div />", "<div>Hello world</div>", "Self-closing closing div"),
        ("<kbd><kbd>Shift</kbd>+<kbd>F3</kbd></kbd>", "<kbd><kbd>Shift</kbd>+<kbd>F3</kbd></kbd>", "Nested <kbd>."),
        ("<var>x<sub><var>i</var></sub></var>, <var>y<sub><var>i</var></sub></var>",
         "<var>x<sub><var>i</var></sub></var>, <var>y<sub><var>i</var></sub></var>", "Nested <var>."),
        ('<dfn><abbr title="Garage Door Opener">GDO</abbr></dfn>',
         '<dfn><abbr title="Garage Door Opener">GDO</abbr></dfn>', "<abbr> inside <dfn>"),
    ]

    def test_internal_remove_html_tags_on_html5_tags(self):
        for tag, escaped in self.HTML5_TAGS:
            with self.subTest(tag):
                if escaped:
                    self.assertEqual(f"&lt;{tag}&gt;", s.internal_remove_html_tags(f"<{tag}>"))
                else:
                    self.assertEqual(f"<{tag}></{tag}>\n", s.internal_remove_html_tags(f"<{tag}></{tag}>\n"))

    def test_remove_some_tags_on_html5_tags(self):
        for tag, escaped in self.HTML5_TAGS:
            with self.subTest(tag):
                if escaped:
                    self.assertEqual(f"&lt;{tag}&gt;", s.remove_some_tags(f"<{tag}>"))
                else:
                    self.assertEqual(f"<{tag}></{tag}>\n", s.remove_some_tags(f"<{tag}></{tag}>\n"))
                    self.assertEqual(f"<{tag}></{tag}>", s.remove_some_tags(f"<{tag}>"))

    def test_internal_remove_html_tags(self):
        for text, expected, message in self.REMOVE_HTML_TAGS:
            with self.subTest(message):
                self.assertEqual(expected, s.internal_remove_html_tags(text))
                self.assertEqual(expected, s.remove_html_tags(text))

    def test_remove_some_tags(self):
        for text, expected, message in self.REMOVE_HTML_TAGS:
            with self.subTest(message):
                self.assertEqual(expected, s.remove_some_tags(text))

    def test_internal_remove_html_tags_details(self):
        cases = [
            # attributes are fixed, unknown tags and stray > escaped
            ("<b onclick=x class=y>hi</b> a > b", '<b class="y">hi</b> a &gt; b'),
            ("<foo>x</foo>", "&lt;foo&gt;x&lt;/foo&gt;"),
            # self-closing: kept for void elements, an empty element for li etc., dropped for others
            ("<br/><hr />", "<br/><hr/>"),
            ("<li/>", "<li></li>"),
            ("<span/>x", "<span>x"),
            # tag names are case-insensitive (ASCII only), \r ends the name
            ("<B\rclass=x>", '<b class="x">'),
            # <meta>/<link> need their microdata attributes
            ('<meta itemprop="a">', '&lt;meta itemprop="a"&gt;'),
            ('<meta itemprop="a" content="b">', '<meta itemprop="a" content="b">'),
            ("a<!-- c -->b", "ab"),
        ]
        for text, expected in cases:
            with self.subTest(text):
                self.assertEqual(expected, s.internal_remove_html_tags(text))

    def test_internal_remove_html_tags_callback(self):
        seen = []

        def callback(params, args):
            seen.append((params, args))
            return params.replace("X", "y")

        self.assertEqual('<span class="y">', s.internal_remove_html_tags("<span class=X>", callback, False))
        self.assertEqual([(" class=X", False)], seen)

    def test_remove_some_tags_balancing(self):
        cases = [
            ("<b>x", "<b>x</b>"),
            ("x</i>y", "xy"),
            ("<p>a<p>b", "<p>a</p><p>b</p>"),
            ("<ul><li>a<li>b</ul>", "<ul><li>a</li><li>b</li></ul>"),
            ("<table><tr><td>x</td></tr></table>", "<table><tbody><tr><td>x</td></tr></tbody></table>"),
            ("<td>x</td>", "x"),
            ("<p></p>", '<p class="mw-empty-elt"></p>'),
            ("<pre>\nx</pre>", "<pre>x</pre>"),
            ("<pre>\n\nx</pre>", "<pre>\n\nx</pre>"),
            ("<br>", "<br />"),
            ("&eacute; &amp; &lt; &copy", "é &amp; &lt; &amp;copy"),
            ("<script>x</script>", "&lt;script&gt;x&lt;/script&gt;"),
            ('<span title="a&quot;b" onclick="x">y</span>', '<span title="a&quot;b">y</span>'),
            ("a<!-- c -->b", "ab"),
        ]
        for text, expected in cases:
            with self.subTest(text):
                self.assertEqual(expected, s.remove_some_tags(text))

    def test_remove_some_tags_options(self):
        self.assertEqual("&lt;b&gt;x&lt;/b&gt;", s.remove_some_tags("<b>x</b>", remove_tags=["b"]))
        self.assertEqual("<foo>x</foo>", s.remove_some_tags("<foo>x</foo>", extra_tags=["foo"]))

        def callback(attrs, suffix):
            return {k: v + suffix for k, v in attrs.items()}

        self.assertEqual('<span title="a!">x</span>',
                         s.remove_some_tags('<span title="a">x</span>', attr_callback=callback,
                                            attr_callback_args=["!"]))

    def test_remove_html_comments(self):
        cases = [
            ("a<!-- x -->b", "ab"),
            ("a\n<!-- x -->\nb", "a\nb"),
            ("a\n  <!-- x -->  \nb", "a\nb"),
            ("a <!-- x --> b", "a  b"),
            ("a<!-- x", "a<!-- x"),
            ("<!-- x -->\nb", "\nb"),
        ]
        for text, expected in cases:
            with self.subTest(text):
                self.assertEqual(expected, s.remove_html_comments(text))

    def test_get_recognized_tag_data(self):
        data = s.get_recognized_tag_data()
        self.assertIn("table", data["htmlelements"])
        self.assertNotIn("img", data["htmlelements"])
        self.assertIn("img", s.get_recognized_tag_data(config=DEFAULT.with_(allow_image_tag=True))["htmlelements"])
        self.assertNotIn("b", s.get_recognized_tag_data(removetags=["b"])["htmlelements"])


class AttributesTest(unittest.TestCase):
    def test_fix_tag_attributes(self):
        self.assertEqual(' class="a" style="color:red" id="b&#95;c"',
                         s.fix_tag_attributes(' class="a" style="color:red" onclick="x" id="b c"', "td"))
        self.assertEqual(' class="a" id="b&#95;c" style="color:red"',
                         s.fix_tag_attributes(' class="a" style="color:red" onclick="x" id="b c"', "td", sorted=True))
        self.assertEqual("", s.fix_tag_attributes("  ", "td"))
        self.assertEqual(' id="b.21c"', s.fix_tag_attributes(' id="b&#33;c"', "td",
                                                              config=DEFAULT.with_(fragment_mode=("legacy",))))

    def test_deprecated_attributes_unaltered(self):
        cases = [
            ('clear="left"', "br"), ('clear="all"', "br"), ('width="100"', "td"), ('nowrap="true"', "td"),
            ('nowrap=""', "td"), ('align="right"', "td"), ('align="center"', "table"), ('align="left"', "tr"),
            ('align="center"', "div"), ('align="left"', "h1"), ('align="left"', "p"),
        ]
        for attr, element in cases:
            with self.subTest(attr=attr, element=element):
                self.assertEqual(f" {attr}", s.fix_tag_attributes(attr, element))

    def test_safe_encode_attribute(self):
        self.assertEqual("&#123;&#123;x&#125;&#125; &#91;&#91;y&#93;&#93; &#124; &#73;SBN http&#58;//z &#039;&#039;",
                         s.safe_encode_attribute("{{x}} [[y]] | ISBN http://z ''"))
        self.assertEqual("a&#10;b&#9;&lt;&quot;", s.safe_encode_attribute('a\nb\t<"'))
        self.assertEqual("HTTP&#58;//x", s.safe_encode_attribute("HTTP://x"))
        self.assertEqual("&#95;&#xFF3F;", s.safe_encode_attribute("_＿"))

    def test_validate_tag_attributes(self):
        cases = [
            ("math", {"id": "foo bar", "bogus": "stripped", "data-foo": "bar"}, {"id": "foo_bar", "data-foo": "bar"}),
            ("meta", {"id": "foo bar", "itemprop": "foo", "content": "bar"}, {"itemprop": "foo", "content": "bar"}),
            ("div", {"role": "presentation", "aria-hidden": "true"}, {"role": "presentation", "aria-hidden": "true"}),
            ("div", {"role": "menuitem", "aria-hidden": "false"}, {"role": "menuitem", "aria-hidden": "false"}),
            ("div",
             {
                 "data-wikitext": "wikitext",
                 "DATA-WIKITEXT-2": "WIKITEXT-2",
                 "data-wikitext-ĳ": "wikitext-Ĳ",
                 "data-mw": "disallow impersonating parsoid",
                 "DATA-mw": "disallow impersonating PARSOID",
                 "data-mw-extension": "disallow impersonating extension",
                 "data-:namespaced": "disallow namespace",
                 "data- invalid": "disallow XSS",
                 "data-/invalid": "disallow XSS",
                 "data->invalid": "disallow XSS",
                 "data-=invalid": "disallow XSS",
             },
             {"data-wikitext": "wikitext", "DATA-WIKITEXT-2": "WIKITEXT-2", "data-wikitext-ĳ": "wikitext-Ĳ"}),
        ]
        for element, attribs, expected in cases:
            with self.subTest(element=element, attribs=attribs):
                self.assertEqual(expected, s.validate_tag_attributes(attribs, element))

    def test_validate_attributes_details(self):
        allowed = s.attributes_allowed_internal("a")
        self.assertEqual({"href": "http://x"}, s.validate_attributes({"href": "http://x"}, allowed))
        self.assertEqual({}, s.validate_attributes({"href": "/relative"}, allowed))
        self.assertEqual({}, s.validate_attributes({"href": "javascript:x"}, allowed))
        self.assertEqual({}, s.validate_attributes({"rel": "javascript:x"}, allowed))
        self.assertEqual({"tabindex": "0"}, s.validate_attributes({"tabindex": "0"}, allowed))
        self.assertEqual({}, s.validate_attributes({"tabindex": "1"}, allowed))
        self.assertEqual({"style": "/* insecure input */"},
                         s.validate_attributes({"style": "background: url(x)"}, allowed))
        self.assertEqual({"aria-owns": "a_b c"}, s.validate_attributes({"aria-owns": " a_b  c "}, allowed))
        # itemtype, itemid, itemref don't make sense without itemscope
        self.assertEqual({}, s.validate_attributes({"itemtype": "x"}, allowed))
        self.assertEqual({"itemscope": "", "itemtype": "x"},
                         s.validate_attributes({"itemscope": "", "itemtype": "x"}, allowed))
        self.assertEqual({"xmlns:foo": "http://x"}, s.validate_attributes({"xmlns:foo": "http://x"}, {}))
        # a deprecated sequential list of names still works
        self.assertEqual({"title": "t"}, s.validate_attributes({"title": "t", "x": "y"}, ["title"]))

    def test_data_attribute_bytes(self):
        # PHP's byte regex refuses the bytes of U+FF3F (EF BC BF) one by one: "ü" is C3 BC
        self.assertEqual({}, s.validate_attributes({"data-ü": "x"}, {}))
        self.assertEqual({"data-é": "x"}, s.validate_attributes({"data-é": "x"}, {}))
        self.assertEqual({}, s.validate_attributes({"data-a_b": "x"}, {}))

    def test_attributes_allowed_internal(self):
        cases = [
            ("math", ["class", "style", "id", "title"]),
            ("meta", ["itemprop", "content"]),
            ("link", ["itemprop", "href", "title"]),
        ]
        for element, attribs in cases:
            with self.subTest(element):
                self.assertEqual(sorted(attribs), sorted(s.attributes_allowed_internal(element)))
        self.assertEqual({}, dict(s.attributes_allowed_internal("script")))
        self.assertIn("rowspan", s.attributes_allowed_internal("td"))

    def test_decode_tag_attributes(self):
        cases = [
            ({"foo": "bar"}, "foo=bar", "Unquoted attribute"),
            ({"עברית": "bar"}, "עברית=bar", "Non-Latin attribute"),
            ({"६": "bar"}, "६=bar", "Devanagari number"),
            ({"搭𨋢": "bar"}, "搭𨋢=bar", "Non-BMP character"),
            ({}, "ńgh=bar", "Combining accent is not allowed"),
            ({"foo": "bar"}, "    foo   =   bar    ", "Spaced attribute"),
            ({"foo": "bar"}, 'foo="bar"', "Double-quoted attribute"),
            ({"foo": "bar"}, "foo='bar'", "Single-quoted attribute"),
            ({"foo": "bar", "baz": "foo"}, "foo='bar'   baz=\"foo\"", "Several attributes"),
            ({":foo": "bar"}, ":foo='bar'", "Leading :"),
            ({"_foo": "bar"}, "_foo='bar'", "Leading _"),
            ({"foo": "bar"}, "Foo='bar'", "Leading capital"),
            ({"foo": "BAR"}, "FOO=BAR", "Attribute keys are normalized to lowercase"),
            ({}, "-foo=bar", "Leading - is forbidden"),
            ({}, ".foo=bar", "Leading . is forbidden"),
            ({"foo-bar": "bar"}, "foo-bar=bar", "A - is allowed inside the attribute"),
            ({"foo-": "bar"}, "foo-=bar", "A - is allowed inside the attribute"),
            ({"foo.bar": "baz"}, "foo.bar=baz", "A . is allowed inside the attribute"),
            ({"foo.": "baz"}, "foo.=baz", "A . is allowed as last character"),
            ({"foo6": "baz"}, "foo6=baz", "Numbers are allowed"),
            ({"1foo": "baz"}, "1foo=baz", "Leading numbers are allowed"),
            ({}, "foo$=baz", "Symbols are not allowed"),
            ({}, "foo@=baz", "Symbols are not allowed"),
            ({}, "foo~=baz", "Symbols are not allowed"),
            ({"foo": "1[#^`*%w/("}, "foo=1[#^`*%w/(", "All kind of characters are allowed as values"),
            ({"foo": "1[#^`*%'w/("}, "foo=\"1[#^`*%'w/(\"", "Double quotes are allowed if quoted by single quotes"),
            ({"foo": '1[#^`*%"w/('}, "foo='1[#^`*%\"w/('", "Single quotes are allowed if quoted by double quotes"),
            ({"foo": '&"'}, "foo=&amp;&quot;", "Special chars can be provided as entities"),
            ({"foo": "&foobar;"}, "foo=&foobar;", "Entity-like items are accepted"),
            # not from MediaWiki's tests
            ({"a": "", "b": "x y"}, "a b='x\n\ty'", "Valueless attribute, whitespace normalized"),
            ({"a": "x"}, 'a="x', "Unterminated quote"),
            ({"Äb": "x"}, "ÄB=x", "strtolower() folds ASCII only"),
        ]
        for expected, text, message in cases:
            with self.subTest(message, text=text):
                self.assertEqual(expected, s.decode_tag_attributes(text))

    def test_merge_attributes(self):
        self.assertEqual({"class": "a b c", "id": "y"},
                         s.merge_attributes({"class": "a b", "id": "x"}, {"class": "b  c", "id": "y"}))
        self.assertEqual({"class": "a"}, s.merge_attributes({"class": "a"}, {"class": "a"}))


class CssTest(unittest.TestCase):
    def test_css_comments_checking(self):
        cases = [
            # Valid comments spanning entire input
            ("/**/", "/**/"),
            ("/* comment */", "/* comment */"),
            # Weird stuff
            (" ", "/****/"),
            (" ", "/* /* */"),
            ("display: block;", "display:/* foo */block;"),
            ("display: block;", "display:\\2f\\2a foo \\2a\\2f block;"),
            ("", "/* unfinished comment structure"),
            ("", "\\2f\\2a unifinished comment'"),
            ("/* insecure input */",
             "filter: progid:DXImageTransform.Microsoft.AlphaImageLoader(src='asdf.png',sizingMethod='scale');"),
            ("/* insecure input */",
             "-ms-filter: \"progid:DXImageTransform.Microsoft.AlphaImageLoader"
             "(src='asdf.png',sizingMethod='scale')\";"),
            ("/* insecure input */", "width: expression(1+1);"),
            ("/* insecure input */", "background-image: image(asdf.png);"),
            ("/* insecure input */", "background-image: -webkit-image(asdf.png);"),
            ("/* insecure input */", "background-image: -moz-image(asdf.png);"),
            ("/* insecure input */", 'background-image: image-set("asdf.png" 1x, "asdf.png" 2x);'),
            ("/* insecure input */", 'background-image: -webkit-image-set("asdf.png" 1x, "asdf.png" 2x);'),
            ("/* insecure input */", 'background-image: -moz-image-set("asdf.png" 1x, "asdf.png" 2x);'),
            ("/* insecure input */", "foo: attr( title, url );"),
            ("/* insecure input */", "foo: attr( title url );"),
            # not from MediaWiki's tests
            ("/* insecure input */", "background: u\\72l(x)"),
            ("/* insecure input */", "background: &#117;rl(x)"),
            ("/* invalid control char */", "color: \\0 red"),
            ("/* invalid control char */", "color: &#1; red"),
            ("content: \\22 x\\22 ", 'content: \\"x\\"'),
            ("color:red", "color:\\\nred"),
        ]
        for expected, css in cases:
            with self.subTest(css):
                self.assertEqual(expected, s.check_css(css))

    def test_out_of_range_escape_raises(self):
        # MediaWiki 1.39 throws InvalidArgumentException (UtfNormal\Utils::codepointToUtf8) here too
        with self.assertRaises(ValueError):
            s.check_css("color: \\110000")


class IdTest(unittest.TestCase):
    TEXT = "foo тест_#%!'()[]:<>&&amp;&amp;amp;%F0"
    LEGACY_ENCODED = "foo_.D1.82.D0.B5.D1.81.D1.82_.23.25.21.27.28.29.5B.5D:.3C.3E.26.26amp.3B.26amp.3Bamp.3B.25F0"
    HTML5_ENCODED_ID = "foo_тест_#%!'()[]:<>&&amp;&amp;amp;%F0"
    HTML5_ENCODED_HREF = "foo_тест_#%!'()[]:<>&&amp;&amp;amp;%25F0"

    def test_escape_id_for_stuff(self):
        legacy = ["legacy", "legacy"]
        legacy_new = ["legacy", "html5", "legacy"]
        new_legacy = ["html5", "legacy", "legacy"]
        new = ["html5", "legacy"]
        all_new = ["html5", "html5"]
        text, legacy_enc, id_enc, href_enc = (self.TEXT, self.LEGACY_ENCODED, self.HTML5_ENCODED_ID,
                                              self.HTML5_ENCODED_HREF)
        # Settings: last element is $wgExternalInterwikiFragmentMode, the rest is $wgFragmentMode
        cases = [
            # Pure legacy: how MW worked before 2017
            ("Attribute", legacy, text, legacy_enc, s.ID_PRIMARY),
            ("Attribute", legacy, text, False, s.ID_FALLBACK),
            ("Link", legacy, text, legacy_enc, None),
            ("ExternalInterwiki", legacy, text, legacy_enc, None),
            # Transition to a new world: legacy links with HTML5 fallback
            ("Attribute", legacy_new, text, legacy_enc, s.ID_PRIMARY),
            ("Attribute", legacy_new, text, id_enc, s.ID_FALLBACK),
            ("Link", legacy_new, text, legacy_enc, None),
            ("ExternalInterwiki", legacy_new, text, legacy_enc, None),
            # New world: HTML5 links, legacy fallbacks
            ("Attribute", new_legacy, text, id_enc, s.ID_PRIMARY),
            ("Attribute", new_legacy, text, legacy_enc, s.ID_FALLBACK),
            ("Link", new_legacy, text, href_enc, None),
            ("ExternalInterwiki", new_legacy, text, legacy_enc, None),
            # Distant future: no legacy fallbacks, but still linking to leagacy wikis
            ("Attribute", new, text, id_enc, s.ID_PRIMARY),
            ("Attribute", new, text, False, s.ID_FALLBACK),
            ("Link", new, text, href_enc, None),
            ("ExternalInterwiki", new, text, legacy_enc, None),
            # Just before the heat death of universe: external interwikis are also HTML5 \m/
            ("Attribute", all_new, text, id_enc, s.ID_PRIMARY),
            ("Attribute", all_new, text, False, s.ID_FALLBACK),
            ("Link", all_new, text, href_enc, None),
            ("ExternalInterwiki", all_new, text, href_enc, None),
            # Whitespace
            ("Attribute", all_new, "foo bar", "foo_bar", s.ID_PRIMARY),
            ("Attribute", all_new, "foo\fbar", "foo_bar", s.ID_PRIMARY),
            ("Attribute", all_new, "foo\nbar", "foo_bar", s.ID_PRIMARY),
            ("Attribute", all_new, "foo\tbar", "foo_bar", s.ID_PRIMARY),
            ("Attribute", all_new, "foo\rbar", "foo_bar", s.ID_PRIMARY),
        ]
        for stuff, settings, id_, expected, mode in cases:
            with self.subTest(stuff=stuff, settings=settings, id_=id_, mode=mode):
                config = DEFAULT.with_(fragment_mode=tuple(settings[:-1]),
                                       external_interwiki_fragment_mode=settings[-1])
                if stuff == "Attribute":
                    escaped = s.escape_id_for_attribute(id_, mode, config=config)
                elif stuff == "Link":
                    escaped = s.escape_id_for_link(id_, config=config)
                else:
                    escaped = s.escape_id_for_external_interwiki(id_, config=config)
                self.assertEqual(expected, escaped)

    def test_invalid_fragment_throws(self):
        with self.assertRaises(ValueError):
            s.escape_id_for_attribute("This should throw", config=DEFAULT.with_(fragment_mode=("boom!",)))

    def test_no_primary_fragment_mode_throws(self):
        config = DEFAULT.with_(fragment_mode=())
        with self.assertRaises(ValueError):
            s.escape_id_for_attribute("This should throw", config=config)
        with self.assertRaises(ValueError):
            s.escape_id_for_link("This should throw", config=config)

    def test_escape_id_reference_list(self):
        for reference_list, id1, id2 in [("foo bar", "foo", "bar"), ("#1 #2", "#1", "#2"), ("+1 +2", "+1", "+2")]:
            with self.subTest(reference_list):
                self.assertEqual(s.escape_id_for_attribute(id1) + " " + s.escape_id_for_attribute(id2),
                                 s.escape_id_reference_list(reference_list))

    def test_long_id_truncated(self):
        self.assertEqual(1024, len(s.escape_id_for_attribute("é" * 2000)))

    def test_escape_class(self):
        cases = [
            ("foo_bar", "foo bar"),
            ("_foo", "1foo"),
            ("_foo", "-foo"),
            ("a_b", "a!!b"),
            ("a_b", "a b"),
            ("ab", "ab__"),
        ]
        for expected, class_ in cases:
            with self.subTest(class_):
                self.assertEqual(expected, s.escape_class(class_))


class CharReferencesTest(unittest.TestCase):
    def test_decode_char_references(self):
        cases = [
            ("école", "&eacute;cole"),
            ("Ĉio bonas dans l'école!", "&#x108;io bonas dans l'&#233;cole!"),
            ("Ĉio bonas dans l'école!", "&#x108;io bonas dans l'&eacute;cole!"),
            ("Ĉio bonas dans l'école! (mais pas &#x108;io dans l'&eacute;cole)",
             "&#x108;io bonas dans l'&eacute;cole! (mais pas &amp;#x108;io dans l'&#38;eacute;cole)"),
            ("a & b", "a & b"),
            ("&foo;", "&foo;"),
            ("�", "&#88888888888888;"),
            # not from MediaWiki's tests
            ("‏‏", "&רלמ;&رلم;"),
            ("&copy", "&copy"),
            ("�", "&#0;"),
        ]
        for expected, text in cases:
            with self.subTest(text):
                self.assertEqual(expected, s.decode_char_references(text))

    def test_normalize_char_references(self):
        cases = [
            ("&#233;", "&eacute;"),
            ("&lt;&gt;&amp;&quot;", "&lt;&gt;&amp;&quot;"),
            ("&#8807;&#824;", "&ngE;"),  # two code points
            ("&#x108;", "&#X0108;"),
            ("&#65;", "&#0065;"),
            ("&amp;#0;", "&#0;"),
            ("&amp;foo;", "&foo;"),
            ("a &amp; b", "a & b"),
            ("&amp;copy", "&copy"),
            ("&rlm;", "&רלמ;"),
        ]
        for expected, text in cases:
            with self.subTest(text):
                self.assertEqual(expected, s.normalize_char_references(text))

    def test_decode_char_references_and_normalize(self):
        self.assertEqual("é", s.decode_char_references_and_normalize("e&#x301;"))
        self.assertEqual("é", s.decode_char_references_and_normalize("é"))  # no reference: unchanged

    def test_escape_html_allow_entities(self):
        cases = [
            ("foo", "foo"),
            ("a¡b", "a&#161;b"),
            ("foo&#039;bar", "foo'bar"),
            ("&lt;script&gt;foo&lt;/script&gt;", "<script>foo</script>"),
            ("&#x338;", "̸"),
            ("&#x338;", "&#x338;"),
        ]
        for expected, html in cases:
            with self.subTest(html):
                self.assertEqual(expected, s.escape_html_allow_entities(html))

    def test_hack_doc_type(self):
        doctype = s.hack_doc_type()
        self.assertTrue(doctype.startswith("<!DOCTYPE html [\n"))
        self.assertIn('<!ENTITY eacute "&#233;">', doctype)
        self.assertIn('<!ENTITY amp "&amp;">', doctype)


class MiscTest(unittest.TestCase):
    def test_is_reserved_data_attribute(self):
        cases = [
            ("foo", False), ("data", False), ("data-foo", False), ("data-mw", True), ("data-ooui", True),
            ("data-parsoid", True), ("data-mw-foo", True), ("data-ooui-foo", True), ("data-mwfoo", True),
        ]
        for attr, expected in cases:
            with self.subTest(attr):
                self.assertIs(expected, s.is_reserved_data_attribute(attr))

    def test_strip_all_tags(self):
        cases = [
            ("<p>Foo</p>", "Foo"),
            ('<p id="one">Foo</p><p id="two">Bar</p>', "Foo Bar"),
            ("<p>Foo</p>\n<p>Bar</p>", "Foo Bar"),
            ("<p>Hello &lt;strong&gt; wor&#x6c;&#100; caf&eacute;</p>", "Hello <strong> world café"),
            ("<p><small data-foo='bar\"&lt;baz>quux'><a href=\"./Foo\">Bar</a></small> Whee!</p>", "Bar Whee!"),
            ('1<span class="<?php">2</span>3', "123"),
            ('1<span class="<?">2</span>3', "123"),
            ("<th>1</th><td>2</td>", "1 2"),
            ("<style>.hello { display: block; }</style>", ""),
            ("Foo<style>p { color: red; }</style>Bar", "FooBar"),
            ("<script>var test = true;</script>", ""),
            # not from MediaWiki's tests
            ("a<br>b<!-- c -->d", "a bd"),
        ]
        for html, expected in cases:
            with self.subTest(html):
                self.assertEqual(expected, s.strip_all_tags(html))

    def test_clean_url(self):
        cases = [
            ("http://www.example.com/file.txt", "http://www.example.com/file.txt"),
            ("https://www.exa­​⁠﻿͏᠋᠌᠍‌‍︀︈️mple.com",
             "https://www.example.com"),
            # not from MediaWiki's tests
            ("http://x/a b|c&quot;", "http://x/a+b%7Cc%22"),
            ("http://[::1]:80/x", "http://[::1]:80/x"),
            ("http://x/&#x0a;", "http://x/%0A"),
            ("no protocol", "no+protocol"),
        ]
        for url, expected in cases:
            with self.subTest(url):
                self.assertEqual(expected, s.clean_url(url))

    def test_validate_email(self):
        valid = [
            "user@example.com", "user@example.museum", "USER@example.com", "user@EXAMPLE.COM", "user@Example.com",
            "USER@eXAMPLE.com", "user+sub@example.com", "user+@example.com", "user@localhost", "FooBar@localdomain",
            "nobody@mycompany", "user-foo@example.org", "userfoo@ex-ample.org", "user.@localdomain", ".@localdomain",
            "$user!ex{this}@123.com", "user@example.1234", "user@a",
        ]
        invalid = [
            " user@host.com", "\tuser@host.com", "user@host.com ", "user@host.com\t", "User user@host",
            "first last@mycompany", "firstlast@my company", "user,foo@example.org", "userfoo@ex,ample.org",
            "user@.", "user@.localdomain", "user@localdomain.", ".@a............", "useràexample.com",
        ]
        for addr in valid:
            with self.subTest(addr):
                self.assertTrue(s.validate_email(addr))
        for addr in invalid:
            with self.subTest(addr):
                self.assertFalse(s.validate_email(addr))

    def test_armor_french_spaces(self):
        self.assertEqual("a&#160;: b !x «&#160;c&#160;»", s.armor_french_spaces("a : b !x « c »"))
        self.assertEqual("a ?", s.armor_french_spaces("a ?", " "))
        self.assertEqual("a :b", s.armor_french_spaces("a :b"))

    def test_normalize_section_name_whitespace(self):
        self.assertEqual("a b c", s.normalize_section_name_whitespace(" a__b _ c_"))

    def test_url_protocols(self):
        self.assertIn("https://", s.wf_url_protocols().replace("\\", ""))
        self.assertNotIn("|//", s.wf_url_protocols(False).replace("\\", ""))


class StringUtilsTest(unittest.TestCase):
    def test_is_utf8(self):
        passing = [
            b"Some ASCII", "Euro sign €".encode(), b"\x00", b"\xc2\x80", b"\xe0\xa0\x80", b"\xf0\x90\x80\x80",
            b"\x7f", b"\xdf\xbf", b"\xef\xbf\xbf", b"\xed\x9f\xbf", b"\xee\x80\x80", b"\xef\xbf\xbd",
            b"\xf2\x80\x80\x80", b"\xf3\xbf\xbf\xbf", b"\xf4\x80\x80\x80", b"\xf4\x8f\xbf\xbf", b"\xef\xbf\xbe",
        ]
        failing = [
            b"\xf8\x88\x80\x80\x80", b"\xfc\x84\x80\x80\x80\x80", b"\xf7\xbf\xbf\xbf", b"\xf4\x90\x80\x80",
            b"\x80", b"\xbf", b"\x80\xbf", b"\xc0", b"\xe0\x80", b"\xdf", b"\xef\xbf", b"e\xaf", b"\xc3\x89\xaf",
            b"\xfe", b"\xff", b"\xc0\xaf", b"\xe0\x80\xaf", b"\xf0\x80\x80\xaf", b"\xc1\xbf", b"\xe0\x9f\xbf",
            b"\xed\xa0\x80", b"\xed\xbf\xbf", b"\xed\xa0\x80\xed\xb0\x80",
        ]
        for value in passing:
            with self.subTest(value):
                self.assertTrue(is_utf8(value))
        for value in failing:
            with self.subTest(value):
                self.assertFalse(is_utf8(value))
        self.assertTrue(is_utf8("é"))
        self.assertFalse(is_utf8("\ud800"))

    def test_delimiter_replace(self):
        self.assertEqual("a b", delimiter_replace("/*", "*/", " ", "a/* x */b"))
        self.assertEqual("a[x]b", delimiter_replace("<", ">", "[$1]", "a<x>b"))
        self.assertEqual("a{<x>}b", delimiter_replace("<", ">", "{$0}", "a<x>b"))
        # START START END matches outer pair
        self.assertEqual("a.b", delimiter_replace("<", ">", ".", "a<<x>b"))
        # a non-matching end is written out
        self.assertEqual("a>b.c", delimiter_replace("<", ">", ".", "a>b<x>c"))
        # an unterminated start is kept
        self.assertEqual("a<b", delimiter_replace("<", ">", ".", "a<b"))
        # "/*/" is not both the start and the end of a comment
        self.assertEqual("[/xy/]", delimiter_replace("/*", "*/", "[$1]", "/*/xy/*/"))
        self.assertEqual("a.b", delimiter_replace("<X", "Y>", ".", "a<xzzy>b", "i"))

    def test_delimiter_replace_callback(self):
        self.assertEqual("a(<x>|x)b", delimiter_replace_callback("<", ">", lambda m: f"({m[0]}|{m[1]})", "a<x>b"))

    def test_hungry_delimiter_replace(self):
        self.assertEqual("a.b.c<d", hungry_delimiter_replace("<", ">", ".", "a<x>b<y>c<d"))

    def test_delimiter_explode(self):
        self.assertEqual(["a", "[b|c]", "d"], list(delimiter_explode("[", "]", "|", "a|[b|c]|d")))
        self.assertEqual(["a", "[[b|c]|e]"], list(delimiter_explode("[", "]", "|", "a|[[b|c]|e]", nested=True)))

    def test_replace_markup(self):
        self.assertEqual('a<td class="x|y">b</td>!c', replace_markup("|", "!", 'a<td class="x|y">b</td>|c'))
        self.assertEqual("ab||c", replace_markup("\x00", "!", "a\x00b||c"))


if __name__ == "__main__":
    unittest.main()
