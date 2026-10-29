# Tests of biwiki/mediawiki/coreparserfunctions.py and core_magic_variables.py. Many cases are taken from MediaWiki
# 1.39's tests/parser/parserTests.txt (https://www.mediawiki.org/), (C) MediaWiki contributors, GPL-2.0-or-later;
# translated to Python by a3ref contributors on 2026-10-30.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the CoreParserFunctions and CoreMagicVariables ports (cases from MediaWiki's parser tests, GPL)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from biwiki.mediawiki import core_magic_variables as cmv
from biwiki.mediawiki import coreparserfunctions as cpf
from biwiki.mediawiki.config import BIKI, TEST
from biwiki.mediawiki.parser import Parser
from biwiki.mediawiki.site import biki_site, test_site
from biwiki.mediawiki.title import Title


class _Parser(Parser):
    """The parser with the magic variables connected, set up as MediaWiki's parser tests: the fake time 123
    (1970-01-01T00:02:03Z), revision id 1337, seven uploaded files."""

    def __init__(self, pages=None, config=TEST, site=None):
        super().__init__(pages=pages or {}, config=config, site=site or test_site(config=config))
        self.timestamp = 123
        self.revision_id = 1337
        self.site_stats = cpf.TEST_SITE_STATS

    def get_variable_value(self, index, frame=None):
        return cmv.get_variable_value(self, index, frame)


def _render(wikitext: str, parser=None, title: str = "Parser test") -> str:
    parser = parser or _Parser()
    html = parser.parse(wikitext, title)
    if html.startswith("<p>") and html.endswith("\n</p>"):
        html = html[3:-5]
    return html


class LanguageTest(unittest.TestCase):
    def test_format_num(self):
        lang = cpf.ENGLISH
        cases = [
            ("1234567.891", "1,234,567.891"), ("-1234", "−1,234"), ("100", "100"), ("0012", "0,012"),
            (".5", ".5"), ("1.", "1."), ("1.50", "1.50"), ("1e5", "100,000"), ("1234.56789e0", "1,234.568"),
            ("12abc3456", "12abc3,456"), ("", ""), ("NAN", "Not a Number"), ("INF", "∞"), ("-INF", "−∞"),
            (1234, "1,234"), ("-0", "−0"),
        ]
        for number, expected in cases:
            with self.subTest(number):
                self.assertEqual(expected, lang.format_num(number))
        self.assertEqual("−1234.5", lang.format_num_no_separators("-1234.5"))

    def test_parse_formatted_number(self):
        lang = cpf.ENGLISH
        self.assertEqual("-1234.5", lang.parse_formatted_number("−1,234.5"))
        self.assertEqual("NAN", lang.parse_formatted_number("Not a Number"))
        self.assertEqual("-INF", lang.parse_formatted_number("−∞"))

    def test_plural_and_gender(self):
        lang = cpf.ENGLISH
        self.assertEqual("one", lang.convert_plural(1, ["one", "many"]))
        self.assertEqual("many", lang.convert_plural(2, ["one", "many"]))
        self.assertEqual("many", lang.convert_plural(1.5, ["one", "many"]))
        self.assertEqual("one", lang.convert_plural(5, ["one"]))
        self.assertEqual("five", lang.convert_plural(5, ["one", "5=five", "many"]))
        self.assertEqual("many", lang.convert_plural(6, ["one", "5=five", "many"]))
        self.assertEqual("", lang.convert_plural(1, []))
        self.assertEqual("they", lang.gender("unknown", ["he", "she", "they"]))
        self.assertEqual("he", lang.gender("unknown", ["he", "she"]))
        self.assertEqual("she", lang.gender("female", ["he", "she"]))

    def test_case(self):
        lang = cpf.ENGLISH
        self.assertEqual("Aoeu", lang.ucfirst("aoeu"))
        self.assertEqual("aOEU", lang.lcfirst("AOEU"))
        self.assertEqual("Éa", lang.ucfirst("éa"))
        self.assertEqual("", lang.ucfirst(""))
        self.assertEqual("SS", lang.uc("ß"))

    def test_bidi_and_dir_mark(self):
        lang = cpf.ENGLISH
        self.assertEqual("‪abc‬", lang.embed_bidi("abc"))
        self.assertEqual("‫שלום‬", lang.embed_bidi("שלום"))
        self.assertEqual("123", lang.embed_bidi("123"))
        self.assertEqual("‎", lang.get_dir_mark())

    def test_language_codes(self):
        self.assertEqual("en-GB", cpf.bcp47("en-gb"))
        self.assertEqual("zh-Hant-TW", cpf.bcp47("zh-tw"))
        self.assertEqual("be-tarask", cpf.bcp47("be-x-old"))
        self.assertEqual("sr-Latn", cpf.bcp47("sr-el"))
        self.assertEqual("العربية", cpf.get_language_name("ar"))
        self.assertEqual("", cpf.get_language_name("xx"))

    def test_user_adjust(self):
        self.assertEqual("123", cpf.ENGLISH.user_adjust(123, "", 0))
        self.assertEqual("20010115133500", cpf.ENGLISH.user_adjust("20010115123500", "", 60))
        self.assertEqual("20001231233500", cpf.ENGLISH.user_adjust("20010101003500", "", -60))

    def test_php_helpers(self):
        self.assertEqual(1000, cpf._php_intval("1e3"))
        self.assertEqual(5, cpf._php_intval(" 5abc"))
        self.assertEqual(0, cpf._php_intval("junk"))
        self.assertEqual("1.0E+20", cpf._php_float_to_string(1e20))
        self.assertEqual("1.5", cpf._php_float_to_string(1.5))
        self.assertEqual("1", cpf._php_float_to_string(1.0))
        self.assertTrue(cpf._php_is_numeric(" 1.5e3 "))
        self.assertFalse(cpf._php_is_numeric("1,5"))
        self.assertEqual("a%20b~", cpf.rawurlencode("a b~"))
        self.assertEqual("a b/é", cpf.urldecode("a+b%2F%C3%A9"))


class MagicVariablesTest(unittest.TestCase):
    def test_current_time_words(self):
        # Note that the current date is hard-coded as 1970-01-01T00:02:03Z (a Thursday) when running parser tests.
        cases = [
            ("{{CURRENTDAY}}", "1"), ("{{CURRENTDAY2}}", "01"), ("{{CURRENTDAYNAME}}", "Thursday"),
            ("{{CURRENTDOW}}", "4"), ("{{CURRENTMONTH}}", "01"), ("{{CURRENTMONTH1}}", "1"),
            ("{{CURRENTMONTHABBREV}}", "Jan"), ("{{CURRENTMONTHNAME}}", "January"),
            ("{{CURRENTMONTHNAMEGEN}}", "January"), ("{{CURRENTTIME}}", "00:02"), ("{{CURRENTHOUR}}", "00"),
            ("{{CURRENTWEEK}}", "1"), ("{{CURRENTYEAR}}", "1970"), ("{{CURRENTTIMESTAMP}}", "19700101000203"),
        ]
        for wikitext, expected in cases:
            with self.subTest(wikitext):
                self.assertEqual(expected, _render(wikitext))

    def test_local_time_words_utc(self):
        wikitext = ("{{LOCALMONTH}} {{LOCALMONTH1}} {{LOCALMONTHNAME}} {{LOCALMONTHNAMEGEN}} {{LOCALMONTHABBREV}} "
                    "{{LOCALDAY}} {{LOCALDAY2}} {{LOCALDAYNAME}} {{LOCALYEAR}} {{LOCALTIME}} {{LOCALHOUR}} "
                    "{{LOCALWEEK}} {{LOCALDOW}} {{LOCALTIMESTAMP}}")
        self.assertEqual("01 1 January January Jan 1 01 Thursday 1970 00:02 00 1 4 19700101000203",
                         _render(wikitext))

    def test_local_time_zone(self):
        parser = _Parser(config=BIKI, site=biki_site())
        parser.timestamp = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
        self.assertEqual("23 01 02 Wednesday", _render("{{CURRENTHOUR}} {{LOCALHOUR}} {{LOCALDAY2}} "
                                                       "{{CURRENTDAYNAME}}", parser, "Foo"))
        self.assertEqual(120, cpf.local_tz_offset(parser))

    def test_page_names(self):
        self.assertEqual("Ævar Arnfjörð Bjarmason", _render("{{PAGENAME}}", title="User:Ævar Arnfjörð Bjarmason"))
        self.assertEqual("%C3%86var_Arnfj%C3%B6r%C3%B0_Bjarmason",
                         _render("{{PAGENAMEE}}", title="User:Ævar Arnfjörð Bjarmason"))
        self.assertEqual("&#42;RFC_1234_http&#58;//example.com/",
                         _render("{{PAGENAMEE}}", title="*RFC 1234 http://example.com/"))
        self.assertEqual("Talk:Parser test Parser_test 0 Talk", _render(
            "{{TALKPAGENAME}} {{SUBJECTPAGENAMEE}} {{NAMESPACENUMBER}} {{TALKSPACE}}"))

    def test_site_words(self):
        self.assertEqual("MediaWiki example.org /skins en en /wiki/$1", _render(
            "{{SITENAME}} {{SERVERNAME}} {{STYLEPATH}} {{CONTENTLANGUAGE}} {{PAGELANGUAGE}} {{ARTICLEPATH}}"))
        self.assertEqual("7", _render("{{NUMBEROFFILES}}"))
        self.assertEqual("‎", _render("{{DIRECTIONMARK}}"))
        self.assertEqual(cmv.MW_VERSION, _render("{{CURRENTVERSION}}"))
        self.assertEqual("|", _render("{{!}}"))
        self.assertIsNone(cmv.get_variable_value(_Parser(), "nosuchvariable"))

    def test_revision_words_non_latest_revision(self):
        parser = _Parser()
        self.assertEqual("1337", _render("{{REVISIONID}}", parser))
        self.assertEqual({"vary-revision-id"}, parser.output.output_flags)
        # no saved revision: the parser options' raw timestamp (123), as MediaWiki's parser tests show
        parser = _Parser()
        self.assertEqual("123", _render("{{REVISIONTIMESTAMP}}", parser, "This page does not exist"))
        self.assertEqual({"vary-revision-timestamp"}, parser.output.output_flags)
        parser = _Parser()
        self.assertEqual("", _render("{{REVISIONUSER}}", parser))
        self.assertEqual({"vary-user"}, parser.output.output_flags)

    def _latest_revision_parser(self, wikitext: str) -> _Parser:
        """The parser tests' "lastsavedrevision" option: the page has a saved revision 1337."""
        parser = _Parser()
        title = Title.new_from_text("Parser test", site=parser.site)
        rev = cpf.RevisionRecord(id=1337, page_id=187, timestamp="19700101000203", user="127.0.0.1",
                                 size=len(wikitext.encode()), content=wikitext)
        parser.current_revision_record_callback = lambda t, p: rev if t.equals(title) else None
        return parser

    def test_revision_words_latest_revision(self):
        cases = [
            ("{{REVISIONID}}", "1337", {"vary-revision-id"}),
            ("{{REVISIONTIMESTAMP}}", "19700101000203", None),
            ("{{REVISIONUSER}}", "127.0.0.1", {"vary-user"}),
            ("{{REVISIONID:{{PAGENAME}}}}", "1337", {"vary-revision-id"}),
            ("{{REVISIONTIMESTAMP:{{PAGENAME}}}}", "19700101000203", {"vary-revision-timestamp"}),
            ("{{REVISIONDAY:{{PAGENAME}}}}", "1", {"vary-revision-timestamp"}),
            ("{{REVISIONMONTH:{{PAGENAME}}}}", "01", {"vary-revision-timestamp"}),
            ("{{REVISIONYEAR:{{PAGENAME}}}}", "1970", {"vary-revision-timestamp"}),
            ("{{PAGESIZE:{{PAGENAME}}}}", "25", {"vary-revision-sha1"}),
        ]
        for wikitext, expected, flags in cases:
            with self.subTest(wikitext):
                parser = self._latest_revision_parser(wikitext)
                self.assertEqual(expected, _render(wikitext, parser))
                self.assertEqual(flags, getattr(parser.output, "output_flags", None))

    def test_revision_functions_without_revision(self):
        parser = _Parser()
        self.assertEqual("", _render("{{REVISIONID:{{PAGENAME}}}}", parser))
        self.assertEqual({"vary-revision-id"}, parser.output.output_flags)
        parser = _Parser()
        self.assertEqual("", _render("{{REVISIONTIMESTAMP:This page does not exist}}", parser))
        self.assertIsNone(getattr(parser.output, "output_flags", None))


class ParserFunctionsTest(unittest.TestCase):
    def test_case_and_namespace_functions(self):
        cases = [
            ("{{LCFirst:AOEU}} {{ucFIRST:aoeu}} {{lc:ABC}} {{uc:abc}}", "aOEU Aoeu abc ABC"),
            ("{{ns:4}} {{ns:Project_talk}} {{ns:0}} {{nse:project talk}} {{ns:99}}", "TestWiki TestWiki talk  "
                                                                                       "TestWiki_talk "),
            ("{{NAMESPACE:Talk:x}} {{NAMESPACEE:User talk:x}} {{TALKSPACE:User:x}} {{SUBJECTSPACE:User talk:x}}",
             "Talk User_talk User talk User"),
            ("{{FULLPAGENAME:project:x}} {{BASEPAGENAME:Foo/bar}} {{TALKPAGENAMEE:Foo bar}}",
             "TestWiki:X Foo/bar Talk:Foo_bar"),
        ]
        for wikitext, expected in cases:
            with self.subTest(wikitext):
                self.assertEqual(expected, _render(wikitext))

    def test_surplus_arguments_are_ignored(self):
        # T7678: Double-parsed template argument
        self.assertEqual("{{{1}}}", _render("{{lc:{{{1}}}|hello}}"))

    def test_url_functions(self):
        self.assertEqual("a+b%26c a%20b a_b", _render("{{urlencode:a b&c}} {{urlencode:a b|PATH}} "
                                                      "{{urlencode:a b|WIKI}}"))
        self.assertEqual("/index.php?title=Some_page&amp=&", _render("{{localurl:Some page|amp=&}}"))
        self.assertEqual("/wiki/File:Foo.png", _render("{{localurl:Media:Foo.png}}"))
        self.assertEqual("/wiki/Foo_bar", _render("{{localurl:Foo%20bar}}"))
        self.assertEqual("http://example.org/wiki/Foo", cpf.canonicalurl(_Parser(), "Foo"))
        self.assertEqual("http://example.org/index.php?title=Foo&amp;action=edit",
                         cpf.fullurle(_Parser(), "Foo", "action=edit"))
        self.assertEqual({"found": False}, cpf.localurl(_Parser(), "[[x]]"))

    def test_formatnum(self):
        parser = _Parser()
        self.assertEqual("1,234,567.891 −1,234 1234 123456.78", _render(
            "{{formatnum:1234567.891}} {{formatnum:-1234}} {{formatnum:1,234|R}} {{formatnum:123456.78|NOSEP}}",
            parser))
        self.assertEqual([], parser.output.tracking_categories)
        parser = _Parser()
        self.assertEqual("12abc3,456", _render("{{formatnum:12abc3456}}", parser))
        self.assertEqual(["nonnumeric-formatnum"], parser.output.tracking_categories)

    def test_plural_gender_grammar_bidi(self):
        self.assertEqual("one one many one they foo ‪abc‬", _render(
            "{{PLURAL:1|one|many}} {{PLURAL:1.0|one|many}} {{plural:1,000|one|many}} {{PLURAL:5|one}} "
            "{{gender:x|he|she|they}} {{grammar:elative|foo}} {{bidi:abc}}"))

    def test_int(self):
        self.assertEqual("You have lots of money (not!).", _render("{{int:youhavenewmessages|lots of money|not!}}"))
        self.assertEqual("⧼var⧽", _render("{{int:var}}"))
        parser = _Parser(pages={"MediaWiki:Fake": "Fake '''$1'''"})
        self.assertEqual("Fake <b>x</b>", _render("{{int:fake|x}}", parser))

    def test_special(self):
        self.assertEqual("Special:Random Special:Badtitle Special:Foobar", _render(
            "{{#special:RandomPage}} {{#special:BaDtItLe}} {{#special:Foobar}}"))
        self.assertEqual("Special:RecentChanges/param Special:Foobar nonexistent Special:Foobar_nonexistent", _render(
            "{{#special:Recentchanges/param}} {{#special:foobar nonexistent}} {{#speciale:foobar nonexistent}}"))
        self.assertEqual("Special:Badtitle", _render("{{#special:}}"))

    def test_language_pad_anchor(self):
        # an unknown code gives its BCP 47 form
        self.assertEqual("العربية British English xx-GB", _render(
            "{{#language:ar}} {{#language:EN-GB}} {{#language:xx-gb}}"))
        self.assertEqual("00xyz xyz00 Æ-Hello Hello-Æ abcdef", _render(
            "{{padleft:xyz|5}} {{padright:xyz|5}} {{padleft:-Hello|7|Æ}} {{padright:Hello-|7|Æ}} "
            "{{padleft:abcdef|junk}}"))
        self.assertEqual("a_b_c_y", _render("{{anchorencode:a b_c [[x|y]]}}"))

    def test_formatdate(self):
        cases = [
            ("{{#formatdate:2009-03-24}}", '<span class="mw-formatted-date" title="2009-03-24">2009-03-24</span>'),
            ("{{#formatdate:2009-03-24|mdy}}",
             '<span class="mw-formatted-date" title="2009-03-24">March 24, 2009</span>'),
            ("{{#formatdate:January 15}}", '<span class="mw-formatted-date" title="01-15">January 15</span>'),
            ("{{#formatdate:2009-03-24|dmy}}",
             '<span class="mw-formatted-date" title="2009-03-24">24 March 2009</span>'),
            ("{{#formatdate:2019-22-22|dmy}}", "2019-22-22"),
            ("{{#formatdate:june 3|dmy}}", '<span class="mw-formatted-date" title="06-03">3 June</span>'),
            ("{{#formatdate:200 BC|dmy}}", "200 BC"),
            ("{{#formatdate:1 June 200 BC|mdy}}",
             '<span class="mw-formatted-date" title="-0199-06-01">June 1, 200 BC</span>'),
        ]
        for wikitext, expected in cases:
            with self.subTest(wikitext):
                self.assertEqual(expected, _render(wikitext))

    def test_tag(self):
        self.assertEqual("<b>known</b> <span>-<span>-x</span></span>", _render(
            "{{#tag:b|known}} {{#tag:span|-{{#tag:span|-{{1x|x}}}}}}", _Parser(pages={"Template:1x": "{{{1}}}"})))
        self.assertEqual('<span title="a">x</span>', _render("{{#tag:span|x|title=\"a\"}}"))

    def test_database_functions_with_empty_database(self):
        self.assertEqual("0 0 0 0", _render("{{PAGESINCATEGORY:<bogus>}} {{PAGESINCATEGORY:Foo|files}} "
                                            "{{PAGESIZE:No such page}} {{PAGEID:No such page}}"))
        self.assertEqual("3", _render("{{PAGESIZE:Template:Foo}}", _Parser(pages={"Template:Foo": "FOO"})))
        self.assertEqual("[] infinity infinity", _render(
            "[{{PROTECTIONLEVEL:edit}}] {{PROTECTIONEXPIRY:create}} {{PROTECTIONEXPIRY:edit|Template:Foo}}",
            _Parser(pages={"Template:Foo": "FOO"})))
        self.assertEqual("", _render("{{filepath:Foo.jpg}}{{CASCADINGSOURCES}}"))

    def test_defaultsort(self):
        parser = _Parser()
        self.assertEqual('<span class="error"><strong>Warning:</strong> Default sort key "y" overrides earlier '
                         'default sort key "x".</span>', _render("{{DEFAULTSORT:x}}{{DEFAULTSORT:y}}", parser))
        self.assertEqual("y", parser.output.page_properties["defaultsort"])
        parser = _Parser()
        self.assertEqual("", _render("{{DEFAULTSORT:x}}{{DEFAULTSORT:y|noreplace}}", parser))
        self.assertEqual("x", parser.output.page_properties["defaultsort"])

    def test_displaytitle(self):
        parser = _Parser()
        self.assertEqual("", _render("{{DISPLAYTITLE:<i>parser</i> test}}", parser))
        self.assertEqual("<i>parser</i> test", parser.output.display_title)
        parser = _Parser()
        self.assertEqual("", _render("{{DISPLAYTITLE:whatever}}", parser))
        self.assertEqual("", parser.output.display_title)
        self.assertEqual([("restricted-displaytitle", "whatever")], parser.output.warnings)
        self.assertEqual(["restricted-displaytitle-ignored"], parser.output.tracking_categories)
        parser = _Parser()
        _render('{{DISPLAYTITLE:<span style="display: none;">P</span>arser test}}', parser)
        self.assertEqual('<span style="/* attempt to bypass $wgRestrictDisplayTitle */">P</span>arser test',
                         parser.output.display_title)


class HelpersTest(unittest.TestCase):
    def test_parse_width_param(self):
        self.assertEqual({"width": 200, "height": 300}, cpf.parse_width_param("200x300px"))
        self.assertEqual({"width": 300}, cpf.parse_width_param("300"))
        self.assertEqual({}, cpf.parse_width_param("big"))

    def test_special_page_names(self):
        self.assertEqual(("Recentchanges", "a b"), cpf.resolve_alias("recent_changes/a b".replace("_", "")))
        self.assertEqual((None, None), cpf.resolve_alias("recent changes"))
        self.assertEqual((None, None), cpf.resolve_alias("Nonexistent"))
        self.assertEqual("RecentChanges/a_b", cpf.get_local_name_for("Recentchanges", "a b"))

    def test_register(self):
        hooks = {}

        class Fake:
            config = TEST

            def set_function_hook(self, id_, callback, flags=0):
                hooks[id_] = flags

        cpf.register(Fake())
        self.assertEqual(1, hooks["ns"])
        self.assertEqual(2, hooks["tag"])
        self.assertEqual(0, hooks["special"])
        self.assertIn("displaytitle", hooks)
        self.assertNotIn("pagesinnamespace", hooks)


if __name__ == "__main__":
    unittest.main()
