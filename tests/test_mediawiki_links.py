"""Tests of the port of MediaWiki's internal links (biwiki/mediawiki/parser_links.py, linkholders.py,
linkrenderer.py and the internal-link functions of linker.py).

The expected HTML follows MediaWiki 1.39's parser tests (tests/parser/parserTests.txt); the normalizeLinkUrl cases
are ported from tests/phpunit/includes/parser/ParserMethodsTest.php, (C) MediaWiki contributors, GPL-2.0-or-later
like the port (see biwiki/mediawiki/README.md and COPYING).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from biwiki.mediawiki.linker import make_self_link_obj, normalize_subpage_link
from biwiki.mediawiki.linkrenderer import HtmlArmor, LinkCache, LinkRenderer, SpecialPageFactory
from biwiki.mediawiki.magicword import FACTORY
from biwiki.mediawiki.parser_links import LinksMixin, normalize_link_url
from biwiki.mediawiki.site import biki_site, test_site
from biwiki.mediawiki.stripstate import MARKER_PREFIX, StripState
from biwiki.mediawiki.title import Title


class LinkParser(LinksMixin):
    """The parts of Parser that the link code uses, enough to run handle_internal_links and the link holders."""

    def __init__(self, site=None, pages=None, title="Parser test"):
        self.site = site or test_site()
        self.config = self.site.config
        self.pages = pages or {}
        self.title = title
        self.magic_words = FACTORY
        self.output = SimpleNamespace(categories={}, page_properties={})
        self.strip_state = StripState(self)

    def handle_external_links(self, text: str) -> str:
        return text

    def render(self, text: str) -> str:
        self.output = SimpleNamespace(categories={}, page_properties={})
        self.clear_link_state()
        text = self.handle_internal_links(text)
        text = text.replace(MARKER_PREFIX + "NOPARSE", "")
        return self.replace_link_holders_private(text)


def red(title: str, text: str = None, href_title: str = None) -> str:
    href = href_title or title.replace(" ", "_")
    return (f'<a href="/index.php?title={href}&amp;action=edit&amp;redlink=1" class="new" '
            f'title="{title} (page does not exist)">{text if text is not None else title}</a>')


class InternalLinksTest(unittest.TestCase):
    def setUp(self):
        self.p = LinkParser(pages={"Main Page": "Hello", "Redirect": "#REDIRECT [[Main Page]]",
                                   "Category:Exists": "x", "Template:Foo": "y"})

    def test_red_and_blue_links(self):
        self.assertEqual(self.p.render("[[Foo]]"), red("Foo"))
        self.assertEqual(self.p.render("[[Main Page]]"), '<a href="/wiki/Main_Page" title="Main Page">Main Page</a>')
        self.assertEqual(self.p.render("[[main Page|the main page]]"),
                         '<a href="/wiki/Main_Page" title="Main Page">the main page</a>')
        self.assertEqual(self.p.render("[[Redirect]]"),
                         '<a href="/wiki/Redirect" class="mw-redirect" title="Redirect">Redirect</a>')
        self.assertEqual(self.p.render("[[template:foo]]"),
                         '<a href="/wiki/Template:Foo" title="Template:Foo">template:foo</a>')
        self.p.render("[[Main Page]] [[Redirect]] [[Foo]] [[Special:Version]] [[Template:Foo]]")
        self.assertEqual(self.p.output.links, {0: {"Main_Page": 1, "Redirect": 1, "Foo": 0}, 10: {"Foo": 1}})
        self.assertEqual(self.p.output.links_special, {"Version": 1})

    def test_link_trail_and_quotes(self):
        self.assertEqual(self.p.render("[[Main Page]]s and [[Foo]]bar."),
                         '<a href="/wiki/Main_Page" title="Main Page">Main Pages</a> and ' + red("Foo", "Foobar") + ".")
        self.assertEqual(self.p.render("[[Foo|''Foo'']]"), red("Foo", "<i>Foo</i>"))
        # T6598: quotes in the target part are not interpreted
        self.assertEqual(self.p.render("[[Foo''bar'']]"),
                         red("Foo&#039;&#039;bar&#039;&#039;", "Foo''bar''", "Foo%27%27bar%27%27"))

    def test_fragments(self):
        self.assertEqual(self.p.render("[[#anchor]]"), '<a href="#anchor">#anchor</a>')
        self.assertEqual(self.p.render("[[Main Page#a b|x]]"), '<a href="/wiki/Main_Page#a_b" title="Main Page">x</a>')
        # broken links drop the fragment
        self.assertEqual(self.p.render("[[Foo#bar]]"), red("Foo", "Foo#bar"))

    def test_self_link(self):
        self.assertEqual(self.p.render("[[Parser test]]s"), '<a class="mw-selflink selflink">Parser tests</a>')
        self.assertEqual(self.p.render("[[Parser test#x]]"), red("Parser test", "Parser test#x"))

    def test_invalid_links_stay_text(self):
        for text in ("[[Foo|bar", "[[<>]]", "[[http://example.com]]", "[[Foo%5B]]", "[[Talk:File:X]]", "[[]]"):
            with self.subTest(text):
                self.assertNotIn("<a", self.p.render(text))
        self.assertEqual(self.p.render("[[Foo&amp;amp; bar]]"), "[[Foo&amp;amp; bar]]")
        # url-encoded titles are decoded
        self.assertEqual(self.p.render("[[%46oo]]"), red("Foo", "Foo"))

    def test_categories(self):
        self.assertEqual(self.p.render("a\n[[Category:Foo bar]]\n[[Category:Baz|key&amp;]]\nb"), "a\nb")
        self.assertEqual(self.p.output.categories, {"Foo_bar": "", "Baz": "key&"})
        self.p.output = SimpleNamespace(categories={}, page_properties={"defaultsort": "Sort"})
        self.p.clear_link_state()
        self.p.handle_internal_links("[[Category:Foo]]")
        self.assertEqual(self.p.output.categories, {"Foo": "Sort"})
        # escaped with a colon: a link
        self.assertEqual(self.p.render("[[:Category:Exists]]"),
                         '<a href="/wiki/Category:Exists" title="Category:Exists">Category:Exists</a>')

    def test_interwiki_and_language_links(self):
        self.assertEqual(self.p.render("[[meatball:Foo bar|x]]"),
                         '<a href="http://www.usemod.com/cgi-bin/mb.pl?Foo_bar" class="extiw" '
                         'title="meatball:Foo bar">x</a>')
        self.assertEqual(self.p.output.interwiki_links, {"meatball": {"Foo_bar": 1}})
        self.assertEqual(self.p.render("x\n[[es:Alimento]]\n[[fr:Nourriture]]\n[[es:Otro]]"), "x")
        self.assertEqual(self.p.output.language_links, ["es:Alimento", "fr:Nourriture"])
        self.assertEqual(self.p.render("[[:es:Spanish]]"),
                         '<a href="http://es.wikipedia.org/wiki/Spanish" class="extiw" title="es:Spanish">'
                         "es:Spanish</a>")
        # local interwikis behave like initial-colon links
        self.assertEqual(self.p.render("[[local:Main Page]]"),
                         '<a href="/wiki/Main_Page" title="Main Page">local:Main Page</a>')
        # interlanguage links on talk pages stay links
        talk = LinkParser(title="Talk:Foo")
        self.assertIn('class="extiw"', talk.render("[[es:Foo]]"))

    def test_special_pages(self):
        self.assertEqual(self.p.render("[[Special:Version]]"),
                         '<a href="/wiki/Special:Version" title="Special:Version">Special:Version</a>')
        self.assertEqual(self.p.render("[[special:recentchanges|rc]]"),
                         '<a href="/wiki/Special:RecentChanges" title="Special:RecentChanges">rc</a>')
        self.assertEqual(self.p.render("[[Special:BookSources/0978739256|foo]]"),
                         '<a href="/wiki/Special:BookSources/0978739256" '
                         'title="Special:BookSources/0978739256">foo</a>')
        self.assertEqual(
            self.p.render("[[Special:ThisNameWillHopefullyNeverBeUsed#anchor]]"),
            '<a href="/wiki/Special:ThisNameWillHopefullyNeverBeUsed" class="new" '
            'title="Special:ThisNameWillHopefullyNeverBeUsed (page does not exist)">'
            "Special:ThisNameWillHopefullyNeverBeUsed#anchor</a>")
        self.assertEqual(self.p.render("[[MediaWiki:Common.css]]"),
                         '<a href="/wiki/MediaWiki:Common.css" title="MediaWiki:Common.css">MediaWiki:Common.css</a>')

    def test_media_and_file_links(self):
        self.assertEqual(self.p.render("[[Media:Foobar.jpg|A file]]"),
                         '<a href="/index.php?title=Special:Upload&amp;wpDestFile=Foobar.jpg" class="new" '
                         'title="Foobar.jpg">A file</a>')
        self.assertEqual(self.p.output.images, {"Foobar.jpg": 1})
        # images: make_image() is a stub until the image code is ported; captions with links are consumed
        self.assertEqual(self.p.render("[[File:X.jpg|thumb|a [[Foo]] caption]] after"), "File:X.jpg after")
        self.assertEqual(self.p.render("[[:File:X.jpg]]"), red("File:X.jpg"))

    def test_subpages(self):
        p = LinkParser(site=test_site(subpages=True), title="Help:Foo/Bar", pages={"Help:Foo/Baz": ""})
        self.assertEqual(p.render("[[/Sub]]"), red("Help:Foo/Bar/Sub", "/Sub"))
        self.assertEqual(p.render("[[/Sub/]]"), red("Help:Foo/Bar/Sub", "Sub"))
        self.assertEqual(p.render("[[../Baz]]"), '<a href="/wiki/Help:Foo/Baz" title="Help:Foo/Baz">Help:Foo/Baz</a>')
        self.assertEqual(p.render("[[../Baz/]]"), '<a href="/wiki/Help:Foo/Baz" title="Help:Foo/Baz">Baz</a>')
        self.assertEqual(p.render("[[../]]"), red("Help:Foo"))
        # without subpages the slash is part of the title
        self.assertEqual(LinkParser(title="Help:Foo").render("[[/Sub]]"), red("/Sub"))

    def test_link_holders_text_and_batches(self):
        p = self.p
        p.clear_link_state()
        text = p.handle_internal_links("[[Foo|a]] [[meatball:B|b]]")
        self.assertEqual(p.replace_link_holders_text(text), "a b")
        # is_big(): replace and clear in the middle of a page
        p.config = p.config.with_(link_holder_batch_size=1)
        self.assertEqual(p.render("[[Foo]] [[Bar]] [[Baz]]"), " ".join(red(t) for t in ("Foo", "Bar", "Baz")))

    def test_biki_site(self):
        p = LinkParser(site=biki_site(), title="setPos", pages={"getPos": "x"})
        self.assertEqual(p.render("[[getPos]]"), '<a href="/wiki/getPos" title="getPos">getPos</a>')
        self.assertEqual(p.render("[[setPos]]"), '<a class="mw-selflink selflink">setPos</a>')
        self.assertEqual(p.render("[[GetPos]]"),
                         '<a href="/wiki?title=GetPos&amp;action=edit&amp;redlink=1" class="new" '
                         'title="GetPos (page does not exist)">GetPos</a>')


class LinkRendererTest(unittest.TestCase):
    def setUp(self):
        self.site = test_site()
        self.renderer = LinkRenderer(LinkCache({"Exists": "x"}, self.site))

    def title(self, text):
        return Title.new_from_text(text, site=self.site)

    def test_make_link(self):
        self.assertEqual(self.renderer.make_link(self.title("Exists"), HtmlArmor("<b>x</b>")),
                         '<a href="/wiki/Exists" title="Exists"><b>x</b></a>')
        self.assertEqual(self.renderer.make_link(self.title("Exists"), "<b>x</b>"),
                         '<a href="/wiki/Exists" title="Exists">&lt;b&gt;x&lt;/b&gt;</a>')
        self.assertEqual(self.renderer.make_link(self.title("Nope")), red("Nope"))
        self.assertEqual(self.renderer.make_known_link(self.title("Exists"), None, {"class": "foo", "title": False}),
                         '<a href="/wiki/Exists" class="foo">Exists</a>')

    def test_special_page_factory(self):
        spf = SpecialPageFactory()
        self.assertEqual(spf.resolve_alias("recentChanges/50"), ("Recentchanges", "50"))
        self.assertEqual(spf.resolve_alias("Nope"), (None, None))
        self.assertTrue(spf.exists("Random"))
        self.assertFalse(spf.exists("JavaScriptTest"))
        self.assertEqual(spf.get_local_name_for("Randompage", "a b"), "Random/a_b")

    def test_self_link_and_subpage_helpers(self):
        t = self.title("Foo")
        self.assertEqual(make_self_link_obj(t, "", "", "s!"), '<a class="mw-selflink selflink">Foos</a>!')
        # the parser-test site has no subpages: no change
        self.assertEqual(normalize_subpage_link(self.title("Help:A/B/C"), "../../X/", ""), ("../../X/", ""))
        site = test_site(subpages=True)
        ctx = Title.new_from_text("Help:A/B/C", site=site)
        self.assertEqual(normalize_subpage_link(ctx, "../../X/", ""), ("Help:A/X", "X"))
        self.assertEqual(normalize_subpage_link(ctx, "/D#e", ""), ("Help:A/B/C/D#e", "/D#e"))
        self.assertEqual(normalize_subpage_link(ctx, "../../../../X", ""), ("../../../../X", ""))


class NormalizeLinkUrlTest(unittest.TestCase):
    def test_normalize_link_url(self):
        cases = [
            ("Escaping of unsafe characters",
             'http://example.org/foo bar?param[]="value"&param[]=valüe',
             "http://example.org/foo%20bar?param%5B%5D=%22value%22&param%5B%5D=val%C3%BCe"),
            ("Case normalization of percent-encoded characters",
             "http://example.org/%ab%cD%Ef%FF",
             "http://example.org/%AB%CD%EF%FF"),
            ("Unescaping of safe characters",
             "http://example.org/%3C%66%6f%6F%3E?%3C%66%6f%6F%3E#%3C%66%6f%6F%3E",
             "http://example.org/%3Cfoo%3E?%3Cfoo%3E#%3Cfoo%3E"),
            ("Context-sensitive replacement of sometimes-safe characters",
             "http://example.org/%23%2F%3F%26%3D%2B%3B?%23%2F%3F%26%3D%2B%3B#%23%2F%3F%26%3D%2B%3B",
             "http://example.org/%23%2F%3F&=+;?%23/?%26%3D%2B%3B#%23/?&=+;"),
            ("IPv6 links aren't escaped", "http://[::1]/foobar", "http://[::1]/foobar"),
            ("non-IPv6 links aren't unescaped", "http://%5B::1%5D/foobar", "http://%5B::1%5D/foobar"),
        ]
        for name, url, expected in cases:
            with self.subTest(name):
                self.assertEqual(normalize_link_url(url), expected)
                self.assertEqual(LinksMixin.normalize_link_url(url), expected)


if __name__ == "__main__":
    unittest.main()
