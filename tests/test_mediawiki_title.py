"""Tests of the port of MediaWiki's title handling (biwiki/mediawiki/title.py and site.py).

Most cases are ported from MediaWiki 1.39 tests/phpunit/includes/title/MediaWikiTitleCodecTest.php and
tests/phpunit/includes/TitleTest.php, (C) MediaWiki contributors, GPL-2.0-or-later like the port (see
biwiki/mediawiki/README.md and COPYING). Changed by a3ref contributors on 2026-10-30: translated to Python
unittest; cases that need other languages, gender namespaces or a database are left out.
"""
from __future__ import annotations

import unittest

from biwiki.mediawiki.config import DEFAULT
from biwiki.mediawiki.site import (NS_CATEGORY, NS_FILE, NS_FILE_TALK, NS_MAIN, NS_PROJECT, NS_SPECIAL, NS_TALK,
                                   NS_TEMPLATE, NS_USER, NS_USER_TALK, Site, biki_site, test_site)
from biwiki.mediawiki.title import (MalformedTitleException, Title, TitleValue, get_title_codec, sanitize_ip,
                                    decode_char_references_and_normalize)


def codec_test_site() -> Site:
    """MediaWikiTitleCodecTest::setUp(): Project namespace "Project", interwikis 'localtestiw' (local) and
    'remotetestiw', capital links."""
    return Site(DEFAULT.with_(capital_links=True),
                interwikis=[{"iw_prefix": "localtestiw", "iw_url": "localtestiw"},
                            {"iw_prefix": "remotetestiw", "iw_url": "remotetestiw"}],
                local_interwikis=["localtestiw"])


def title_test_site(**config) -> Site:
    """TitleTest::setUp()"""
    config = {"meta_namespace": "Project", "server": "https://example.org", "script_path": "/w",
              "script": "/w/index.php", "article_path": "/wiki/$1", **config}
    return Site(DEFAULT.with_(**config),
                extra_namespaces={12302: "TEST-JS", 12303: "TEST-JS_TALK"},
                interwikis=[
                    {"iw_prefix": "localtestiw", "iw_url": "localtestiw"},
                    {"iw_prefix": "remotetestiw", "iw_url": "remotetestiw"},
                    {"iw_prefix": "wiki", "iw_url": "wiki"},
                    {"iw_prefix": "wikipedia", "iw_url": "wikipedia"},
                    {"iw_prefix": "de", "iw_url": "de", "iw_local": 1},
                    {"iw_prefix": "zz", "iw_url": "zz", "iw_local": 0},
                    {"iw_prefix": "acme", "iw_url": "https://acme.test/$1"},
                    {"iw_prefix": "yy", "iw_url": "https://yy.wiki.test/wiki/$1", "iw_local": 1},
                ],
                local_interwikis=["localtestiw"])


class MediaWikiTitleCodecTest(unittest.TestCase):
    def setUp(self):
        self.site = codec_test_site()
        self.codec = get_title_codec(self.site)

    def test_format(self):
        cases = [
            (NS_MAIN, "Foo_Bar", "", "", "Foo Bar"),
            (NS_USER, "Hansi_Maier", "stuff_and_so_on", "", "User:Hansi Maier#stuff and so on"),
            (False, "Hansi_Maier", "", "", "Hansi Maier"),
            (NS_USER_TALK, "hansi__maier", "", "", "User talk:hansi  maier"),
            (NS_MAIN, "FooBar", "", "remotetestiw", "remotetestiw:FooBar"),
        ]
        for ns, text, fragment, interwiki, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.codec.format_title(ns, text, fragment, interwiki), expected)

    def test_parse_title(self):
        cases = [
            ("  : Hansi_Maier _ ", NS_MAIN, TitleValue(NS_MAIN, "Hansi_Maier")),
            ("User:::1", NS_MAIN, TitleValue(NS_USER, "0:0:0:0:0:0:0:1")),
            (":Category:Quux", NS_MAIN, TitleValue(NS_CATEGORY, "Quux")),
            ("Category:Quux", NS_MAIN, TitleValue(NS_CATEGORY, "Quux")),
            ("Category:Quux", NS_CATEGORY, TitleValue(NS_CATEGORY, "Quux")),
            ("Quux", NS_CATEGORY, TitleValue(NS_CATEGORY, "Quux")),
            (":Quux", NS_CATEGORY, TitleValue(NS_MAIN, "Quux")),
            ("a b c", NS_MAIN, TitleValue(NS_MAIN, "A_b_c")),
            (" a  b  c ", NS_MAIN, TitleValue(NS_MAIN, "A_b_c")),
            (" _ Foo __ Bar_ _", NS_MAIN, TitleValue(NS_MAIN, "Foo_Bar")),
            ("Sandbox", NS_MAIN, TitleValue(NS_MAIN, "Sandbox")),
            ('A "B"', NS_MAIN, TitleValue(NS_MAIN, 'A_"B"')),
            ("A 'B'", NS_MAIN, TitleValue(NS_MAIN, "A_'B'")),
            (".com", NS_MAIN, TitleValue(NS_MAIN, ".com")),
            ("~", NS_MAIN, TitleValue(NS_MAIN, "~")),
            ('"', NS_MAIN, TitleValue(NS_MAIN, '"')),
            ("'", NS_MAIN, TitleValue(NS_MAIN, "'")),
            ("Talk:Sandbox", NS_MAIN, TitleValue(NS_TALK, "Sandbox")),
            ("Talk:Foo:Sandbox", NS_MAIN, TitleValue(NS_TALK, "Foo:Sandbox")),
            ("File:Example.svg", NS_MAIN, TitleValue(NS_FILE, "Example.svg")),
            ("File_talk:Example.svg", NS_MAIN, TitleValue(NS_FILE_TALK, "Example.svg")),
            ("Foo/.../Sandbox", NS_MAIN, TitleValue(NS_MAIN, "Foo/.../Sandbox")),
            ("Sandbox/...", NS_MAIN, TitleValue(NS_MAIN, "Sandbox/...")),
            ("A~~", NS_MAIN, TitleValue(NS_MAIN, "A~~")),
            # Length is 256 total, but only title part matters
            ("Category:" + "x" * 248, NS_MAIN, TitleValue(NS_CATEGORY, "X" + "x" * 247)),
            ("x" * 252, NS_MAIN, TitleValue(NS_MAIN, "X" + "x" * 251)),
            # Test decoding and normalization
            ("&quot;n&#x303;&#34;", NS_MAIN, TitleValue(NS_MAIN, '"ñ"')),
            ("X#n&#x303;", NS_MAIN, TitleValue(NS_MAIN, "X", "ñ")),
            # target section parsing
            ("X#", NS_MAIN, TitleValue(NS_MAIN, "X")),
            ("#", NS_MAIN, TitleValue(NS_MAIN, "")),
            ("X##", NS_MAIN, TitleValue(NS_MAIN, "X", "#")),
            ("X#z#z", NS_MAIN, TitleValue(NS_MAIN, "X", "z#z")),
            ("X#z z", NS_MAIN, TitleValue(NS_MAIN, "X", "z z")),
            ("X#z%z", NS_MAIN, TitleValue(NS_MAIN, "X", "z%z")),
            ("X#z&z", NS_MAIN, TitleValue(NS_MAIN, "X", "z&z")),
        ]
        for text, ns, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.codec.parse_title(text, ns), expected)

    def test_parse_title_invalid(self):
        cases = [
            "User:#", "::", "::xx", "::##", " :: x",
            "Talk:File:Foo.jpg", "Talk:localtestiw:Foo",
            "::1",  # only valid in user namespace
            "User::x",  # leading ":" in a user name is only valid of IPv6 addresses
            "", ":", "__  __", "  __  ",
            # Bad characters forbidden regardless of wgLegalTitleChars
            "A [ B", "A ] B", "A { B", "A } B", "A < B", "A > B", "A | B",
            # URL encoding
            "A%20B", "A%23B", "A%2523B",
            # Subject of NS_TALK does not roundtrip to NS_MAIN
            "Talk:File:Example.svg",
            # Directory navigation
            ".", "..", "./Sandbox", "../Sandbox", "Foo/./Sandbox", "Foo/../Sandbox", "Sandbox/.", "Sandbox/..",
            # Tilde
            "A ~~~ Name", "A ~~~~ Signature", "A ~~~~~ Timestamp",
            "x" * 256,
            # Namespace prefix without actual title
            "Talk:", "Category: ", "Category: #bar",
            # Invalid Unicode (in Python: a lone surrogate, as from bytes decoded with surrogateescape)
            "Apollo\udc96Soyuz",
            # Input resulting from invalid Unicode being sanitized somewhere else
            "Apollo�Soyuz",
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(MalformedTitleException):
                    self.codec.parse_title(text, NS_MAIN)

    def test_make_title_value_safe(self):
        cases = {
            "Nonexistent NS": (None, 942929, "Test"),
            "Linebreak in title": (None, NS_MAIN, "Test\nthis"),
            "Pipe in title": (None, NS_MAIN, "Test|this"),
            "Simple page": (TitleValue(NS_MAIN, "Test"), NS_MAIN, "Test"),
            "Passed fragment": (TitleValue(NS_MAIN, "Test", "Fragment"), NS_MAIN, "Test", "Fragment"),
            "Embedded fragment": (TitleValue(NS_MAIN, "Test", "Fragment"), NS_MAIN, "Test#Fragment"),
            "Passed fragment with spaces": (TitleValue(NS_MAIN, "Test", " Frag ment"), NS_MAIN, " Test ",
                                            " Frag_ment "),
            "Embedded fragment with spaces": (TitleValue(NS_MAIN, "Test", " Frag ment"), NS_MAIN,
                                              " Test # Frag_ment "),
            "Passed fragment with leading tab": (None, NS_MAIN, "\tTest\t", "\tFragment"),
            "Embedded fragment with leading tab": (None, NS_MAIN, "\tTest\t#\tFragment"),
            "Passed fragment with trailing tab": (None, NS_MAIN, "\tTest\t", "Fragment\t"),
            "Embedded fragment with trailing tab": (None, NS_MAIN, "\tTest\t#Fragment\t"),
            "Passed fragment with interior tab": (None, NS_MAIN, "\tTest\t", "Frag\tment"),
            "Embedded fragment with interior tab": (None, NS_MAIN, "\tTest\t#\tFrag\tment"),
            "Passed local interwiki": (TitleValue(NS_MAIN, "Test"), NS_MAIN, "Test", "", "localtestiw"),
            "Embedded local interwiki": (TitleValue(NS_MAIN, "Test"), NS_MAIN, "localtestiw:Test"),
            "Passed remote interwiki": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"), NS_MAIN, "Test", "",
                                        "remotetestiw"),
            "Embedded remote interwiki": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"), NS_MAIN,
                                          "remotetestiw:Test"),
            "Passed local interwiki with different case": (TitleValue(NS_MAIN, "Test"), NS_MAIN, "Test", "",
                                                           "LocalTestIW"),
            "Embedded local interwiki with different case": (TitleValue(NS_MAIN, "Test"), NS_MAIN,
                                                             "LocalTestIW:Test"),
            "Passed remote interwiki with different case": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"),
                                                            NS_MAIN, "Test", "", "RemoteTestIW"),
            "Embedded remote interwiki with different case": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"),
                                                              NS_MAIN, "RemoteTestIW:Test"),
            "Passed local interwiki with lowercase page name": (TitleValue(NS_MAIN, "Test"), NS_MAIN, "test", "",
                                                                "localtestiw"),
            "Embedded local interwiki with lowercase page name": (TitleValue(NS_MAIN, "Test"), NS_MAIN,
                                                                  "localtestiw:test"),
            # For remote we don't auto-capitalize
            "Passed remote interwiki with lowercase page name": (TitleValue(NS_MAIN, "test", "", "remotetestiw"),
                                                                 NS_MAIN, "test", "", "remotetestiw"),
            "Embedded remote interwiki with lowercase page name": (TitleValue(NS_MAIN, "test", "", "remotetestiw"),
                                                                   NS_MAIN, "remotetestiw:test"),
            "Fragment and local interwiki": (TitleValue(NS_MAIN, "Test", "Fragment"), NS_MAIN, "Test", "Fragment",
                                             "localtestiw"),
            "Fragment and remote interwiki": (TitleValue(NS_MAIN, "Test", "Fragment", "remotetestiw"), NS_MAIN,
                                              "Test", "Fragment", "remotetestiw"),
            "Fragment and local interwiki and non-main namespace": (TitleValue(NS_TALK, "Test", "Fragment"),
                                                                    NS_TALK, "Test", "Fragment", "localtestiw"),
            # We don't know the foreign wiki's namespaces, so it will always be NS_MAIN
            "Fragment and remote interwiki and non-main namespace": (
                TitleValue(NS_MAIN, "Talk:Test", "Fragment", "remotetestiw"), NS_TALK, "Test", "Fragment",
                "remotetestiw"),
            # Whitespace normalization and Unicode stripping
            "Name with space": (TitleValue(NS_MAIN, "Test_test"), NS_MAIN, "Test test"),
            "Unicode bidi override characters": (TitleValue(NS_MAIN, "Test"), NS_MAIN,
                                                 "‎T‏e‪s‫t‬‭‮"),
            "Invalid UTF-8 sequence": (None, NS_MAIN, "Te\udc80\udcf0st"),
            "Whitespace collapsing": (TitleValue(NS_MAIN, "Test_test"), NS_MAIN,
                                      "Test _  ᠎        "
                                      "       　test"),
            "UTF8_REPLACEMENT": (None, NS_MAIN, "�"),
            # Namespace prefixes
            "Talk:Test": (TitleValue(NS_TALK, "Test"), NS_MAIN, "Talk:Test"),
            "Test in talk NS": (TitleValue(NS_TALK, "Test"), NS_TALK, "Test"),
            "Talkk:Test": (TitleValue(NS_MAIN, "Talkk:Test"), NS_MAIN, "Talkk:Test"),
            "Talk:Talk:Test": (None, NS_MAIN, "Talk:Talk:Test"),
            "Talk:User:Test": (None, NS_MAIN, "Talk:User:Test"),
            "User:Talk:Test": (TitleValue(NS_USER, "Talk:Test"), NS_MAIN, "User:Talk:Test"),
            "User:Test in talk NS": (None, NS_TALK, "User:Test"),
            "Talk:Test in talk NS": (None, NS_TALK, "Talk:Test"),
            "User:Test in user NS": (TitleValue(NS_USER, "User:Test"), NS_USER, "User:Test"),
            "Talk:Test in user NS": (TitleValue(NS_USER, "Talk:Test"), NS_USER, "Talk:Test"),
            # Initial colon
            ":Test": (TitleValue(NS_MAIN, "Test"), NS_MAIN, ":Test"),
            ":Talk:Test": (TitleValue(NS_TALK, "Test"), NS_MAIN, ":Talk:Test"),
            ":localtestiw:Test": (TitleValue(NS_MAIN, "Test"), NS_MAIN, ":localtestiw:Test"),
            ":remotetestiw:Test": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"), NS_MAIN, ":remotetestiw:Test"),
            "localtestiw::Test": (None, NS_MAIN, "localtestiw::Test"),
            "remotetestiw::Test": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"), NS_MAIN, "remotetestiw::Test"),
            "localtestiw:: Test": (None, NS_MAIN, "localtestiw:: Test"),
            "remotetestiw:: Test": (TitleValue(NS_MAIN, "Test", "", "remotetestiw"), NS_MAIN,
                                    "remotetestiw:: Test"),
            # Empty titles
            "Empty title": (None, NS_MAIN, ""),
            "Empty title with namespace": (None, NS_USER, ""),
            "Local interwiki with empty page name": (TitleValue(NS_MAIN, "Main_Page"), NS_MAIN, "localtestiw:"),
            "Remote interwiki with empty page name": (TitleValue(NS_MAIN, "", "", "remotetestiw"), NS_MAIN,
                                                      "remotetestiw:"),
            # Whitespace-only titles
            "Whitespace-only title": (None, NS_MAIN, "\t\n"),
            "Whitespace-only title with namespace": (None, NS_USER, " _ "),
            "Local interwiki with whitespace-only page name": (None, NS_MAIN, "localtestiw:_\t"),
            "Remote interwiki with whitespace-only page name": (None, NS_MAIN, "remotetestiw:\t_\n\r"),
            # Namespace and interwiki
            "Talk:localtestiw:Test": (None, NS_MAIN, "Talk:localtestiw:Test"),
            "Talk:remotetestiw:Test": (None, NS_MAIN, "Talk:remotetestiw:Test"),
            "User:localtestiw:Test": (TitleValue(NS_USER, "Localtestiw:Test"), NS_MAIN, "User:localtestiw:Test"),
            "User:remotetestiw:Test": (TitleValue(NS_USER, "Remotetestiw:Test"), NS_MAIN, "User:remotetestiw:Test"),
            "localtestiw:Test in user namespace": (TitleValue(NS_USER, "Localtestiw:Test"), NS_USER,
                                                   "localtestiw:Test"),
            "remotetestiw:Test in user namespace": (TitleValue(NS_USER, "Remotetestiw:Test"), NS_USER,
                                                    "remotetestiw:Test"),
            "localtestiw:talk:test": (TitleValue(NS_TALK, "Test"), NS_MAIN, "localtestiw:talk:test"),
            "remotetestiw:talk:test": (TitleValue(NS_MAIN, "talk:test", "", "remotetestiw"), NS_MAIN,
                                       "remotetestiw:talk:test"),
            # Invalid chars
            "Test[test": (None, NS_MAIN, "Test[test"),
            # Long titles
            "255 chars long": (TitleValue(NS_MAIN, "A" * 255), NS_MAIN, "A" * 255),
            "255 chars long in user NS": (TitleValue(NS_USER, "A" * 255), NS_USER, "A" * 255),
            "User:255 chars long": (TitleValue(NS_USER, "A" * 255), NS_MAIN, "User:" + "A" * 255),
            "256 chars long": (None, NS_MAIN, "A" * 256),
            "256 chars long in user NS": (None, NS_USER, "A" * 256),
            "User:256 chars long": (None, NS_MAIN, "User:" + "A" * 256),
            "512 chars long in special NS": (TitleValue(NS_SPECIAL, "A" * 512), NS_SPECIAL, "A" * 512),
            "Special:512 chars long": (TitleValue(NS_SPECIAL, "A" * 512), NS_MAIN, "Special:" + "A" * 512),
            "513 chars long in special NS": (None, NS_SPECIAL, "A" * 513),
            "Special:513 chars long": (None, NS_MAIN, "Special:" + "A" * 513),
            # IP addresses
            "User:000.000.000": (TitleValue(NS_USER, "000.000.000"), NS_MAIN, "User:000.000.000"),
            "User:000.000.000.000": (TitleValue(NS_USER, "0.0.0.0"), NS_MAIN, "User:000.000.000.000"),
            "000.000.000.000": (TitleValue(NS_MAIN, "000.000.000.000"), NS_MAIN, "000.000.000.000"),
            "User:1.1.256.000": (TitleValue(NS_USER, "1.1.256.000"), NS_MAIN, "User:1.1.256.000"),
            "User:1.1.255.000": (TitleValue(NS_USER, "1.1.255.0"), NS_MAIN, "User:1.1.255.000"),
        }
        # Invalid and valid dots
        for dots in (".", "..", "..."):
            for pattern in ("?", "?/", "?/Test", "Test/?/Test", "/?", "Test/?", "?Test", "Test?Test", "Test?"):
                test = pattern.replace("?", dots)
                if dots == "..." or pattern in ("?Test", "Test?Test", "Test?"):
                    expected_main, expected_user = TitleValue(NS_MAIN, test), TitleValue(NS_USER, test)
                else:
                    expected_main = expected_user = None
                cases[test] = (expected_main, NS_MAIN, test)
                cases[f"{test} in user NS"] = (expected_user, NS_USER, test)
                cases[f"User:{test}"] = (expected_user, NS_MAIN, f"User:{test}")
        # Invalid and valid tildes
        for tildes in ("~~", "~~~"):
            for pattern in ("?", "Test?", "?Test", "Test?Test"):
                test = pattern.replace("?", tildes)
                if tildes == "~~":
                    expected_main, expected_user = TitleValue(NS_MAIN, test), TitleValue(NS_USER, test)
                else:
                    expected_main = expected_user = None
                cases[test] = (expected_main, NS_MAIN, test)
                cases[f"{test} in user NS"] = (expected_user, NS_USER, test)
                cases[f"User:{test}"] = (expected_user, NS_MAIN, f"User:{test}")

        for name, (expected, ns, text, *rest) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.codec.make_title_value_safe(ns, text, *rest), expected)
                # testMakeTitleSafe: Title::makeTitleSafe() gives the same title
                actual = Title.make_title_safe(ns, text, *rest, site=self.site)
                if expected is None:
                    self.assertIsNone(actual)
                else:
                    self.assertIsNotNone(actual)
                    expected_title = Title.make_title(expected.namespace, expected.db_key, expected.fragment,
                                                      expected.interwiki, site=self.site)
                    self.assertEqual(actual.prefixed_db_key, expected_title.prefixed_db_key)

    def test_get_namespace_name(self):
        self.assertEqual(self.codec.get_namespace_name(NS_USER_TALK, "Foo"), "User_talk")
        with self.assertRaises(ValueError):
            self.codec.get_namespace_name(942929, "Foo")


class TitleTest(unittest.TestCase):
    def setUp(self):
        self.site = title_test_site()

    def new(self, text, ns=NS_MAIN):
        return Title.new_from_text(text, ns, site=self.site)

    def test_secure_and_split_valid(self):
        cases = [
            "Sandbox", 'A "B"', "A 'B'", ".com", "~", "#", '"', "'", "Talk:Sandbox", "Talk:Foo:Sandbox",
            "File:Example.svg", "File_talk:Example.svg", "Foo/.../Sandbox", "Sandbox/...", "A~~", ":A",
            # Length is 256 total, but only title part matters
            "Category:" + "x" * 248, "x" * 252,
            # interwiki prefix
            "localtestiw: #anchor", "localtestiw:", "localtestiw:foo", "localtestiw: foo # anchor",
            "localtestiw: Talk: Sandbox # anchor", "remotetestiw:", "remotetestiw: Talk: # anchor",
            "remotetestiw: #bar", "remotetestiw: Talk:", "remotetestiw: Talk: Foo", "localtestiw:remotetestiw:",
            "localtestiw:remotetestiw:foo",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsInstance(self.new(text), Title)

    def test_secure_and_split_invalid(self):
        cases = [
            ("", "title-invalid-empty"),
            (":", "title-invalid-empty"),
            ("__  __", "title-invalid-empty"),
            ("  __  ", "title-invalid-empty"),
            # Bad characters forbidden regardless of wgLegalTitleChars
            ("A [ B", "title-invalid-characters"),
            ("A ] B", "title-invalid-characters"),
            ("A { B", "title-invalid-characters"),
            ("A } B", "title-invalid-characters"),
            ("A < B", "title-invalid-characters"),
            ("A > B", "title-invalid-characters"),
            ("A | B", "title-invalid-characters"),
            ("A \t B", "title-invalid-characters"),
            ("A \n B", "title-invalid-characters"),
            # URL encoding
            ("A%20B", "title-invalid-characters"),
            ("A%23B", "title-invalid-characters"),
            ("A%2523B", "title-invalid-characters"),
            # Subject of NS_TALK does not roundtrip to NS_MAIN
            ("Talk:File:Example.svg", "title-invalid-talk-namespace"),
            # Directory navigation
            (".", "title-invalid-relative"),
            ("..", "title-invalid-relative"),
            ("./Sandbox", "title-invalid-relative"),
            ("../Sandbox", "title-invalid-relative"),
            ("Foo/./Sandbox", "title-invalid-relative"),
            ("Foo/../Sandbox", "title-invalid-relative"),
            ("Sandbox/.", "title-invalid-relative"),
            ("Sandbox/..", "title-invalid-relative"),
            # Tilde
            ("A ~~~ Name", "title-invalid-magic-tilde"),
            ("A ~~~~ Signature", "title-invalid-magic-tilde"),
            ("A ~~~~~ Timestamp", "title-invalid-magic-tilde"),
            # Length
            ("x" * 256, "title-invalid-too-long"),
            # Namespace prefix without actual title
            ("Talk:", "title-invalid-empty"),
            ("Talk:#", "title-invalid-empty"),
            ("Category: ", "title-invalid-empty"),
            ("Category: #bar", "title-invalid-empty"),
            # interwiki prefix
            ("localtestiw: Talk: # anchor", "title-invalid-empty"),
            ("localtestiw: Talk:", "title-invalid-empty"),
        ]
        for text, message in cases:
            with self.subTest(text=text):
                with self.assertRaises(MalformedTitleException) as cm:
                    Title.new_from_text_throw(text, site=self.site)
                self.assertEqual(cm.exception.get_error_message(), message)
                self.assertIsNone(self.new(text))

    def test_new_from_text_null(self):
        self.assertIsNone(self.new(None))
        self.assertIsNone(self.new(""))
        self.assertEqual(self.new(42).prefixed_text, "42")

    def test_new_from_text_cache(self):
        # Ensure that the instance we get back from newFromText is the original one
        title = self.new("Foo")
        self.assertIs(self.new("Foo"), title)

    def test_make_title(self):
        cases = [
            ("Foo", NS_MAIN, "Foo"),
            ("User:Foo", NS_USER, "Foo"),
            ("Foo#Section", NS_MAIN, "Foo", "Section"),
            ("#Section", NS_MAIN, "", "Section"),
            ("acme:Foo", NS_MAIN, "Foo", "", "acme"),
            ("Foo Bar", NS_MAIN, "Foo_Bar"),
        ]
        for expected, ns, text, *rest in cases:
            with self.subTest(expected):
                title = Title.make_title(ns, text, *rest, site=self.site)
                self.assertTrue(title.is_valid())
                self.assertEqual(title.full_text, expected)

    def test_make_title_invalid(self):
        cases = [
            ("Special:Badtitle/NS-1234:Foo", -1234, "Foo"),
            ("User:foo", NS_USER, "foo"),
            ("", NS_MAIN, ""),
            ("Foo|Bar", NS_MAIN, "Foo|Bar"),
            ("qwerty:Foo", NS_MAIN, "Foo", "", "qwerty"),
        ]
        for expected, ns, text, *rest in cases:
            with self.subTest(expected):
                title = Title.make_title(ns, text, *rest, site=self.site)
                self.assertFalse(title.is_valid())
                self.assertEqual(title.full_text, expected)

    def test_make_title_safe(self):
        cases = [
            ("Foo", NS_MAIN, "Foo"),
            ("User:Foo", NS_USER, "Foo"),
            ("Foo#Section", NS_MAIN, "Foo", "Section"),
            ("#Section", NS_MAIN, "", "Section"),
            ("acme:Foo", NS_MAIN, "Foo", "", "acme"),
            ("Foo Bar", NS_MAIN, "Foo_Bar"),
            ("User:Foo", NS_USER, "foo"),
            # Bad interwiki becomes part of the title text. Is this intentional?
            ("Qwerty:Foo", NS_MAIN, "Foo", "", "qwerty"),
        ]
        for expected, ns, text, *rest in cases:
            with self.subTest(expected):
                title = Title.make_title_safe(ns, text, *rest, site=self.site)
                self.assertTrue(title.is_valid())
                self.assertEqual(title.full_text, expected)
        self.assertIsNone(Title.make_title_safe(-1234, "Foo", site=self.site))
        self.assertIsNone(Title.make_title_safe(NS_MAIN, "", site=self.site))
        self.assertIsNone(Title.make_title_safe(NS_MAIN, "Foo|Bar", site=self.site))

    def test_get_link_url(self):
        site = title_test_site(server="https://xx.wiki.test", external_interwiki_fragment_mode="legacy",
                               fragment_mode=("html5", "legacy"))
        cases = [
            ("/wiki/Goats", NS_MAIN, "Goats"),
            ("/wiki/Goats#Goatificatiön", NS_MAIN, "Goats", "Goatificatiön"),
            # Fragment only (query is ignored)
            ("#Goatificatiön", NS_MAIN, "", "Goatificatiön", "", {"a": 1}),
            ("https://xx.wiki.test/wiki/xyzzy:Goats#Goatificatiön", NS_MAIN, "Goats", "Goatificatiön", "xyzzy"),
            ("https://acme.test/Goats#Goatificati.C3.B6n", NS_MAIN, "Goats", "Goatificatiön", "acme"),
            ("https://acme.test/Goats?a=1&b=blank+blank#Goatificati.C3.B6n", NS_MAIN, "Goats", "Goatificatiön",
             "acme", {"a": 1, "b": "blank blank"}),
            ("https://yy.wiki.test/wiki/Goats#Goatificatiön", NS_MAIN, "Goats", "Goatificatiön", "yy"),
        ]
        for expected, ns, text, fragment, interwiki, query in [c + ("",) * (6 - len(c)) for c in cases]:
            with self.subTest(expected):
                title = Title.make_title(ns, text, fragment, interwiki, site=site)
                self.assertEqual(title.get_link_url(query), expected)

    def test_local_and_full_url(self):
        title = self.new("Talk:Foo bar")
        self.assertEqual(title.get_local_url(), "/wiki/Talk:Foo_bar")
        self.assertEqual(title.get_local_url("action=raw"), "/w/index.php?title=Talk:Foo_bar&action=raw")
        self.assertEqual(title.get_edit_url(), "/w/index.php?title=Talk:Foo_bar&action=edit")
        self.assertEqual(title.get_full_url(), "https://example.org/wiki/Talk:Foo_bar")
        self.assertEqual(self.new("A&B?C").get_local_url(), "/wiki/A%26B%3FC")
        self.assertEqual(self.new("acme:Foo").get_edit_url(), "")

    def test_subpage(self):
        site = title_test_site()
        cases = [
            ("Foo", "x", "Foo/x", NS_MAIN, ""),
            ("Foo#bar", "x", "Foo/x", NS_MAIN, ""),
            ("User:Foo", "x", "User:Foo/x", NS_USER, ""),
            ("wiki:User:Foo", "x", "wiki:User:Foo/x", NS_MAIN, "wiki"),
        ]
        for text, sub, expected, ns, interwiki in cases:
            with self.subTest(text):
                actual = Title.new_from_text(text, site=site).get_subpage(sub)
                self.assertEqual(actual.prefixed_text, expected)
                self.assertEqual((actual.namespace, actual.interwiki), (ns, interwiki))

    def test_base_root_subpage_text(self):
        base_cases = [
            (NS_USER, "John_Doe", "John Doe"),
            (NS_USER, "John_Doe/subOne/subTwo", "John Doe/subOne"),
            (NS_USER, "Foo / Bar / Baz", "Foo / Bar "),
            (NS_USER, "Foo/", "Foo"),
            (NS_USER, "Foo/Bar/", "Foo/Bar"),
            (NS_USER, "/", "/"),
            (NS_USER, "//", "/"),
            (NS_USER, "/oops/", "/oops"),
            (NS_USER, "/indeed", "/indeed"),
            (NS_USER, "//indeed", "/"),
            (NS_USER, "/Ramba/Zamba/Mamba/", "/Ramba/Zamba/Mamba"),
            (NS_USER, "//x//y//z//", "//x//y//z/"),
        ]
        root_cases = [
            (NS_USER, "John_Doe", "John Doe"),
            (NS_USER, "John_Doe/subOne/subTwo", "John Doe"),
            (NS_USER, "Foo / Bar / Baz", "Foo "),
            (NS_USER, "Foo/", "Foo"),
            (NS_USER, "Foo/Bar/", "Foo"),
            (NS_USER, "/", "/"),
            (NS_USER, "//", "/"),
            (NS_USER, "/oops/", "/oops"),
            (NS_USER, "/Ramba/Zamba/Mamba/", "/Ramba"),
            (NS_USER, "//x//y//z//", "//x"),
            (NS_TALK, "////", "///"),
            (NS_TEMPLATE, "////", "///"),
            (NS_TEMPLATE, "Foo////", "Foo"),
            (NS_TEMPLATE, "Foo////Bar", "Foo"),
        ]
        subpage_cases = [
            (NS_USER, "John_Doe", "John Doe"),
            (NS_USER, "John_Doe/subOne/subTwo", "subTwo"),
            (NS_USER, "John_Doe/subOne", "subOne"),
            (NS_USER, "/", "/"),
            (NS_USER, "//", ""),
            (NS_USER, "/oops/", ""),
            (NS_USER, "/indeed", "/indeed"),
            (NS_USER, "//indeed", "indeed"),
            (NS_USER, "/Ramba/Zamba/Mamba/", ""),
            (NS_USER, "//x//y//z//", ""),
            (NS_TEMPLATE, "Foo", "Foo"),
            (NS_CATEGORY, "Foo", "Foo"),
            (NS_MAIN, "Bar", "Bar"),
        ]
        for ns, text, expected in base_cases:
            with self.subTest(base=text):
                title = Title.make_title(ns, text, site=self.site)
                self.assertEqual(title.base_text, expected)
                base = title.get_base_title()
                self.assertTrue(base.is_valid())
                self.assertTrue(base.equals(Title.make_title_safe(ns, expected, site=self.site)))
        for ns, text, expected in root_cases:
            with self.subTest(root=text):
                title = Title.make_title(ns, text, site=self.site)
                self.assertEqual(title.root_text, expected)
                root = title.get_root_title()
                self.assertTrue(root.is_valid())
                self.assertTrue(root.equals(Title.make_title_safe(ns, expected, site=self.site)))
        for ns, text, expected in subpage_cases:
            with self.subTest(subpage=text):
                self.assertEqual(Title.make_title(ns, text, site=self.site).subpage_text, expected)

    def test_get_fragment(self):
        cases = [
            ("Foo", ""),
            ("Foo#bar", "bar"),
            ("Foo#bär", "bär"),
            # Inner whitespace is normalized
            ("Foo#bar_bar", "bar bar"),
            ("Foo#bar bar", "bar bar"),
            ("Foo#bar   bar", "bar bar"),
            # Leading whitespace is kept, trailing whitespace is trimmed.
            ("Foo#_bar_bar_", " bar bar"),
            ("Foo# bar bar ", " bar bar"),
        ]
        for full, fragment in cases:
            with self.subTest(full):
                self.assertEqual(self.new(full).fragment, fragment)

    def test_in_namespace(self):
        self.assertTrue(self.new("Main Page").in_namespace(NS_MAIN))
        self.assertFalse(self.new("Main Page").in_namespace(NS_TALK))
        self.assertTrue(self.new("User:Foo").in_namespace(NS_USER))
        self.assertTrue(self.new("User:Foo").in_namespaces(NS_USER, NS_TALK))
        self.assertTrue(self.new("User talk:Foo").has_subject_namespace(NS_USER))
        self.assertFalse(self.new("User talk:Foo").has_subject_namespace(NS_MAIN))

    def test_get_other_page(self):
        cases = [
            ("Main Page", "Talk:Main Page"),
            ("Talk:Main Page", "Main Page"),
            ("Help:Main Page", "Help talk:Main Page"),
            ("Help talk:Main Page", "Help:Main Page"),
            ("Special:FooBar", None),
            ("Media:File.jpg", None),
        ]
        for text, expected in cases:
            with self.subTest(text):
                title = self.new(text)
                if expected is None:
                    with self.assertRaises(ValueError):
                        title.get_other_page()
                else:
                    self.assertEqual(title.get_other_page().prefixed_text, expected)

    def test_can_exist(self):
        self.assertTrue(self.new("Foo").can_exist())
        self.assertTrue(self.new("User:Foo").can_exist())
        self.assertFalse(self.new("Special:Version").can_exist())
        self.assertFalse(self.new("acme:Foo").can_exist())
        self.assertFalse(self.new("#Foo").can_exist())

    def test_equals_and_set_fragment(self):
        a, b = self.new("Foo#x"), self.new("foo#y")
        self.assertTrue(a.equals(b))
        self.assertFalse(a.is_same_link_as(b))
        self.assertEqual(a, b)
        title = self.new("Foo")
        title.set_fragment("#Some_section")
        self.assertEqual(title.fragment, "Some section")
        self.assertIsNot(self.new("Foo"), title)  # set_fragment() took the title out of the cache


class SiteTest(unittest.TestCase):
    def test_test_site(self):
        site = test_site()
        self.assertEqual(site.get_ns_text(NS_PROJECT), "TestWiki")
        self.assertEqual(site.get_ns_text(NS_PROJECT + 1), "TestWiki_talk")
        self.assertEqual(site.get_ns_index("project"), NS_PROJECT)
        self.assertEqual(site.get_ns_index("TESTWIKI"), NS_PROJECT)
        self.assertEqual(site.get_ns_index("image"), NS_FILE)
        self.assertEqual(site.get_ns_index("memoryalpha"), 100)
        self.assertIsNone(site.get_ns_index("nope"))
        self.assertFalse(site.has_subpages(NS_USER))
        self.assertTrue(test_site(subpages=True).has_subpages(NS_MAIN))
        self.assertEqual(site.fetch_interwiki("Meatball").get_url("A_b/c:d"),
                         "http://www.usemod.com/cgi-bin/mb.pl?A_b/c:d")
        self.assertTrue(site.fetch_interwiki("zh").is_local())
        self.assertIsNone(site.fetch_interwiki("nope"))

    def test_test_site_titles(self):
        site = test_site()

        def t(text):
            return Title.new_from_text(text, site=site)

        self.assertEqual(t("project:foo").prefixed_text, "TestWiki:Foo")
        self.assertEqual(t("Image:Foo.jpg").prefixed_text, "File:Foo.jpg")
        # A namespace shadowing a interwiki link (T53680): the namespace wins
        self.assertEqual(t("MemoryAlpha:Foo").namespace, 100)
        self.assertEqual(t("meatball:Foo").interwiki, "meatball")
        self.assertEqual(t("meatball:Foo").get_link_url(), "http://www.usemod.com/cgi-bin/mb.pl?Foo")
        self.assertEqual(t("Meatball:Foo bar#a b").get_link_url(),
                         "http://www.usemod.com/cgi-bin/mb.pl?Foo_bar#a_b")
        # Local interwikis behave like initial-colon links
        title = t("local:Talk:Foo")
        self.assertEqual((title.interwiki, title.namespace, title.db_key), ("", NS_TALK, "Foo"))
        self.assertTrue(title.was_local_interwiki())
        self.assertEqual(t("mi:").prefixed_text, "Main Page")
        # Local interwiki that matches a namespace name (T228616): the namespace wins
        self.assertEqual(t("project:Foo").namespace, NS_PROJECT)
        self.assertEqual(t("Foo#a b").fragment_for_url, "#a_b")
        self.assertEqual(t("Foo#ä").fragment_for_url, "#.C3.A4")  # legacy fragment mode in the parser tests
        self.assertEqual(t("en:Foo").get_full_url(), "//en.wikipedia.org/wiki/Foo")
        # An empty title leaves an empty query, which wfExpandUrl() drops (parser test "Inline interwiki link with
        # empty title (T4372)")
        self.assertEqual(t("MeatBall:").get_link_url(), "http://www.usemod.com/cgi-bin/mb.pl")
        self.assertEqual(t("meatball:#x").get_link_url(), "http://www.usemod.com/cgi-bin/mb.pl#x")

    def test_biki_site(self):
        site = biki_site()
        self.assertEqual(site.get_ns_text(NS_PROJECT), "Bohemia_Interactive_Community")

        def t(text, ns=NS_MAIN):
            return Title.new_from_text(text, ns, site=site)

        # Titles are case-sensitive on the BI wiki, except in the always-capitalized namespaces
        self.assertEqual(t("setPos").prefixed_text, "setPos")
        self.assertEqual(t("category:arma 3: scripting commands").prefixed_text,
                         "Category:arma 3: scripting commands")
        self.assertEqual(t("user:foo").prefixed_text, "User:Foo")
        self.assertEqual(t("Bohemia Interactive Community:Foo").namespace, NS_PROJECT)
        self.assertEqual(t("Project:foo").prefixed_text, "Bohemia Interactive Community:foo")
        self.assertEqual(t("doTarget", NS_TEMPLATE).prefixed_db_key, "Template:doTarget")
        self.assertEqual(t("setPos").get_full_url(), "https://community.bistudio.com/wiki/setPos")
        # the wiki's own interwiki map (biki_siteinfo.json) has wikibooks:, but no wikipedia:
        self.assertEqual(t("wikibooks:Arma 3").get_link_url(), "http://en.wikibooks.org/wiki/Arma_3")
        self.assertEqual(t("wikipedia:Arma 3").interwiki, "")
        self.assertEqual(t("Arma Reforger:Foo").namespace, 5050)  # an extra namespace of the wiki
        self.assertTrue(t("Arma 3: Actions/Foo").is_subpage() is False)
        self.assertTrue(t("Template:A/B").is_subpage())
        self.assertEqual(t("Template:A/B").base_text, "A")


class HelpersTest(unittest.TestCase):
    def test_sanitize_ip(self):
        cases = [
            ("::1", "0:0:0:0:0:0:0:1"),
            ("cebc:2004:f::", "CEBC:2004:F:0:0:0:0:0"),
            ("3f:535::e:fbb", "3F:535:0:0:0:0:E:FBB"),
            ("::", "0:0:0:0:0:0:0:0"),
            ("0.0.0.0", "0.0.0.0"),
            ("010.000.001.255", "10.0.1.255"),
            ("Not an IP", "Not an IP"),
            ("1::2::3", "1::2::3"),
            ("", None),
        ]
        for ip, expected in cases:
            with self.subTest(ip):
                self.assertEqual(sanitize_ip(ip), expected)

    def test_decode_char_references(self):
        self.assertEqual(decode_char_references_and_normalize("&eacute;&#257;&#x3017;"), "éā〗")
        self.assertEqual(decode_char_references_and_normalize("&foo; &#0;"), "&foo; �")
        self.assertEqual(decode_char_references_and_normalize("&רלמ;"), "‏")
        self.assertEqual(decode_char_references_and_normalize("é"), "é")  # no reference: no NFC
        self.assertEqual(decode_char_references_and_normalize("é&amp;"), "é&")


if __name__ == "__main__":
    unittest.main()
