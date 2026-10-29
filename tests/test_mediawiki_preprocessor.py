# Ported from MediaWiki 1.39 tests/phpunit/includes/parser/PreprocessorTest.php (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the test cases are copied unchanged; added
# tests of the expansion frames with a small fake parser.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the preprocessor port (biwiki/mediawiki/preprocessor.py, ppnode.py, ppframe.py).

CASES and HEADINGS are MediaWiki's PreprocessorTest::provideCases() and provideHeadings() (wikitext -> the tree as
XML), and the files in tests/mediawiki/preprocess/ are those of its testPreprocessorOutputFiles(); like the port they
are GPL-2.0-or-later (see biwiki/mediawiki/README.md). The frame tests use a fake parser that implements just the
part of the parser interface the frames call.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from biwiki.mediawiki.config import Config
from biwiki.mediawiki.ppframe import CustomFrame, Frame, TemplateFrame
from biwiki.mediawiki.ppnode import MWException, PPNode_Hash_Array, PPNode_Hash_Attr, PPNode_Hash_Text
from biwiki.mediawiki.preprocessor import (DOM_FOR_INCLUSION, DOM_LANG_CONVERSION_DISABLED, NO_TAGS, NO_TEMPLATES,
                                           RECOVER_ORIG, Preprocessor, PPNode_Hash_Tree)
from biwiki.mediawiki.stripstate import MARKER_PREFIX, MARKER_SUFFIX, StripState

PREPROCESS_DIR = Path(__file__).parent / "mediawiki" / "preprocess"

# PreprocessorTest::provideCases()
CASES = [
    ('Foo',
     '<root>Foo</root>'),
    ('<!-- Foo -->',
     '<root><comment>&lt;!-- Foo --&gt;</comment></root>'),
    ('<!-- Foo --><!-- Bar -->',
     '<root><comment>&lt;!-- Foo --&gt;</comment><comment>&lt;!-- Bar --&gt;</comment></root>'),
    ('<!-- Foo -->  <!-- Bar -->',
     '<root><comment>&lt;!-- Foo --&gt;</comment>  <comment>&lt;!-- Bar --&gt;</comment></root>'),
    ('<!-- Foo --> \n <!-- Bar -->',
     '<root><comment>&lt;!-- Foo --&gt;</comment> \n <comment>&lt;!-- Bar --&gt;</comment></root>'),
    ('<!-- Foo --> \n <!-- Bar -->\n',
     '<root><comment>&lt;!-- Foo --&gt;</comment> \n<comment> &lt;!-- Bar --&gt;\n</comment></root'
     '>'),
    ('<!-- Foo -->  <!-- Bar -->\n',
     '<root><comment>&lt;!-- Foo --&gt;</comment>  <comment>&lt;!-- Bar --&gt;</comment>\n</root>'),
    ('<!-->Bar',
     '<root><comment>&lt;!--&gt;Bar</comment></root>'),
    ('<!-- Comment -- comment',
     '<root><comment>&lt;!-- Comment -- comment</comment></root>'),
    ('== Foo ==\n  <!-- Bar -->\n== Baz ==\n',
     '<root><h level="2" i="1">== Foo ==</h>\n<comment>  &lt;!-- Bar --&gt;\n</comment><h level="2'
     '" i="2">== Baz ==</h>\n</root>'),
    ('<gallery/>',
     '<root><ext><name>gallery</name><attr></attr></ext></root>'),
    ('Foo <gallery/> Bar',
     '<root>Foo <ext><name>gallery</name><attr></attr></ext> Bar</root>'),
    ('<gallery></gallery>',
     '<root><ext><name>gallery</name><attr></attr><inner></inner><close>&lt;/gallery&gt;</close>'
     '</ext></root>'),
    ('<foo> <gallery></gallery>',
     '<root>&lt;foo&gt; <ext><name>gallery</name><attr></attr><inner></inner><close>&lt;/gallery'
     '&gt;</close></ext></root>'),
    ('<foo> <gallery><gallery></gallery>',
     '<root>&lt;foo&gt; <ext><name>gallery</name><attr></attr><inner>&lt;gallery&gt;</inner><clo'
     'se>&lt;/gallery&gt;</close></ext></root>'),
    ('<noinclude> Foo bar </noinclude>',
     '<root><ignore>&lt;noinclude&gt;</ignore> Foo bar <ignore>&lt;/noinclude&gt;</ignore></root'
     '>'),
    ('<noinclude>\n{{Foo}}\n</noinclude>',
     '<root><ignore>&lt;noinclude&gt;</ignore>\n<template lineStart="1"><title>Foo</title></templ'
     'ate>\n<ignore>&lt;/noinclude&gt;</ignore></root>'),
    ('<noinclude>\n{{Foo}}\n</noinclude>\n',
     '<root><ignore>&lt;noinclude&gt;</ignore>\n<template lineStart="1"><title>Foo</title></templ'
     'ate>\n<ignore>&lt;/noinclude&gt;</ignore>\n</root>'),
    ('<gallery>foo bar',
     '<root>&lt;gallery&gt;foo bar</root>'),
    ('<{{foo}}>',
     '<root>&lt;<template><title>foo</title></template>&gt;</root>'),
    ('<{{{foo}}}>',
     '<root>&lt;<tplarg><title>foo</title></tplarg>&gt;</root>'),
    ('<gallery></gallery</gallery>',
     '<root><ext><name>gallery</name><attr></attr><inner>&lt;/gallery</inner><close>&lt;/gallery'
     '&gt;</close></ext></root>'),
    ('=== Foo === ',
     '<root><h level="3" i="1">=== Foo === </h></root>'),
    ('==<!-- -->= Foo === ',
     '<root><h level="2" i="1">==<comment>&lt;!-- --&gt;</comment>= Foo === </h></root>'),
    ('=== Foo ==<!-- -->= ',
     '<root><h level="1" i="1">=== Foo ==<comment>&lt;!-- --&gt;</comment>= </h></root>'),
    ('=== Foo ===<!-- -->\n',
     '<root><h level="3" i="1">=== Foo ===<comment>&lt;!-- --&gt;</comment></h>\n</root>'),
    ('=== Foo ===<!-- --> <!-- -->\n',
     '<root><h level="3" i="1">=== Foo ===<comment>&lt;!-- --&gt;</comment> <comment>&lt;!-- --&'
     'gt;</comment></h>\n</root>'),
    ('== Foo ==\n== Bar == \n',
     '<root><h level="2" i="1">== Foo ==</h>\n<h level="2" i="2">== Bar == </h>\n</root>'),
    ('===========',
     '<root><h level="5" i="1">===========</h></root>'),
    ('Foo\n=\n==\n=\n',
     '<root>Foo\n=\n==\n=\n</root>'),
    ('{{Foo}}',
     '<root><template><title>Foo</title></template></root>'),
    ('\n{{Foo}}',
     '<root>\n<template lineStart="1"><title>Foo</title></template></root>'),
    ('{{Foo|bar}}',
     '<root><template><title>Foo</title><part><name index="1" /><value>bar</value></part></templ'
     'ate></root>'),
    ('{{Foo|bar}}a',
     '<root><template><title>Foo</title><part><name index="1" /><value>bar</value></part></templ'
     'ate>a</root>'),
    ('{{Foo|bar|baz}}',
     '<root><template><title>Foo</title><part><name index="1" /><value>bar</value></part><part><'
     'name index="2" /><value>baz</value></part></template></root>'),
    ('{{Foo|1=bar}}',
     '<root><template><title>Foo</title><part><name>1</name>=<value>bar</value></part></template'
     '></root>'),
    ('{{Foo|=bar}}',
     '<root><template><title>Foo</title><part><name></name>=<value>bar</value></part></template>'
     '</root>'),
    ('{{Foo|bar=baz}}',
     '<root><template><title>Foo</title><part><name>bar</name>=<value>baz</value></part></templa'
     'te></root>'),
    ('{{Foo|{{bar}}=baz}}',
     '<root><template><title>Foo</title><part><name><template><title>bar</title></template></nam'
     'e>=<value>baz</value></part></template></root>'),
    ('{{Foo|1=bar|baz}}',
     '<root><template><title>Foo</title><part><name>1</name>=<value>bar</value></part><part><nam'
     'e index="1" /><value>baz</value></part></template></root>'),
    ('{{Foo|1=bar|2=baz}}',
     '<root><template><title>Foo</title><part><name>1</name>=<value>bar</value></part><part><nam'
     'e>2</name>=<value>baz</value></part></template></root>'),
    ('{{Foo|bar|foo=baz}}',
     '<root><template><title>Foo</title><part><name index="1" /><value>bar</value></part><part><'
     'name>foo</name>=<value>baz</value></part></template></root>'),
    ('{{{1}}}',
     '<root><tplarg><title>1</title></tplarg></root>'),
    ('{{{1|}}}',
     '<root><tplarg><title>1</title><part><name index="1" /><value></value></part></tplarg></roo'
     't>'),
    ('{{{Foo}}}',
     '<root><tplarg><title>Foo</title></tplarg></root>'),
    ('{{{Foo|}}}',
     '<root><tplarg><title>Foo</title><part><name index="1" /><value></value></part></tplarg></r'
     'oot>'),
    ('{{{Foo|bar|baz}}}',
     '<root><tplarg><title>Foo</title><part><name index="1" /><value>bar</value></part><part><na'
     'me index="2" /><value>baz</value></part></tplarg></root>'),
    ('{<!-- -->{Foo}}',
     '<root>{<comment>&lt;!-- --&gt;</comment>{Foo}}</root>'),
    ('{{{{Foobar}}}}',
     '<root>{<tplarg><title>Foobar</title></tplarg>}</root>'),
    ('{{{ {{Foo}} }}}',
     '<root><tplarg><title> <template><title>Foo</title></template> </title></tplarg></root>'),
    ('{{ {{{Foo}}} }}',
     '<root><template><title> <tplarg><title>Foo</title></tplarg> </title></template></root>'),
    ('{{{{{Foo}}}}}',
     '<root><template><title><tplarg><title>Foo</title></tplarg></title></template></root>'),
    ('{{{{{Foo}} }}}',
     '<root><tplarg><title><template><title>Foo</title></template> </title></tplarg></root>'),
    ('{{{{{{Foo}}}}}}',
     '<root><tplarg><title><tplarg><title>Foo</title></tplarg></title></tplarg></root>'),
    ('{{{{{{Foo}}}}}',
     '<root>{<template><title><tplarg><title>Foo</title></tplarg></title></template></root>'),
    ('[[[Foo]]',
     '<root>[[[Foo]]</root>'),
    ('{{Foo|[[[[bar]]|baz]]}}',
     '<root><template><title>Foo</title><part><name index="1" /><value>[[[[bar]]|baz]]</value></'
     'part></template></root>'),
    ('{{Foo|[[[[bar]|baz]]}}',
     '<root>{{Foo|[[[[bar]|baz]]}}</root>'),
    ('{{Foo|Foo [[[[bar]|baz]]}}',
     '<root>{{Foo|Foo [[[[bar]|baz]]}}</root>'),
    ('Foo <display map>Bar</display map             >Baz',
     '<root>Foo <ext><name>display map</name><attr></attr><inner>Bar</inner><close>&lt;/display '
     'map             &gt;</close></ext>Baz</root>'),
    ('Foo <display map foo>Bar</display map             >Baz',
     '<root>Foo <ext><name>display map</name><attr> foo</attr><inner>Bar</inner><close>&lt;/disp'
     'lay map             &gt;</close></ext>Baz</root>'),
    ('Foo <gallery bar="baz" />',
     '<root>Foo <ext><name>gallery</name><attr> bar=&quot;baz&quot; </attr></ext></root>'),
    ('Foo <gallery bar="1" baz=2 />',
     '<root>Foo <ext><name>gallery</name><attr> bar=&quot;1&quot; baz=2 </attr></ext></root>'),
    ('</foo>Foo<//foo>',
     '<root><ext><name>/foo</name><attr></attr><inner>Foo</inner><close>&lt;//foo&gt;</close></e'
     'xt></root>'),
    ('{{#ifexpr: ({{{1|1}}} = 2) | Foo | Bar }}',
     '<root><template><title>#ifexpr: (<tplarg><title>1</title><part><name index="1" /><value>1<'
     '/value></part></tplarg> = 2) </title><part><name index="1" /><value> Foo </value></part><p'
     'art><name index="2" /><value> Bar </value></part></template></root>'),
    ('{{#if: {{{1|}}} | Foo | {{Bar}} }}',
     '<root><template><title>#if: <tplarg><title>1</title><part><name index="1" /><value></value'
     '></part></tplarg> </title><part><name index="1" /><value> Foo </value></part><part><name i'
     'ndex="2" /><value> <template><title>Bar</title></template> </value></part></template></roo'
     't>'),
    ('{{#if: {{{1|}}} | Foo | [[Bar]] }}',
     '<root><template><title>#if: <tplarg><title>1</title><part><name index="1" /><value></value'
     '></part></tplarg> </title><part><name index="1" /><value> Foo </value></part><part><name i'
     'ndex="2" /><value> [[Bar]] </value></part></template></root>'),
    ('{{#if: {{{1|}}} | [[Foo]] | Bar }}',
     '<root><template><title>#if: <tplarg><title>1</title><part><name index="1" /><value></value'
     '></part></tplarg> </title><part><name index="1" /><value> [[Foo]] </value></part><part><na'
     'me index="2" /><value> Bar </value></part></template></root>'),
    ('{{#if: {{{1|}}} | 1 | {{#if: {{{1|}}} | 2 | 3 }} }}',
     '<root><template><title>#if: <tplarg><title>1</title><part><name index="1" /><value></value'
     '></part></tplarg> </title><part><name index="1" /><value> 1 </value></part><part><name ind'
     'ex="2" /><value> <template><title>#if: <tplarg><title>1</title><part><name index="1" /><va'
     'lue></value></part></tplarg> </title><part><name index="1" /><value> 2 </value></part><par'
     't><name index="2" /><value> 3 </value></part></template> </value></part></template></root>'),
    ('{{ {{Foo}}',
     '<root>{{ <template><title>Foo</title></template></root>'),
    ('{{Foobar {{Foo}} {{Bar}} {{Baz}} ',
     '<root>{{Foobar <template><title>Foo</title></template> <template><title>Bar</title></templ'
     'ate> <template><title>Baz</title></template> </root>'),
    ('[[Foo]] |',
     '<root>[[Foo]] |</root>'),
    ('{{Foo|Bar|',
     '<root>{{Foo|Bar|</root>'),
    ('[[Foo]',
     '<root>[[Foo]</root>'),
    ('[[Foo|Bar]',
     '<root>[[Foo|Bar]</root>'),
    ('{{Foo| [[Bar] }}',
     '<root>{{Foo| [[Bar] }}</root>'),
    ('{{Foo| [[Bar|Baz] }}',
     '<root>{{Foo| [[Bar|Baz] }}</root>'),
    ('{{Foo|bar=[[baz]}}',
     '<root>{{Foo|bar=[[baz]}}</root>'),
    ('{{foo|',
     '<root>{{foo|</root>'),
    ('{{foo|}',
     '<root>{{foo|}</root>'),
    ('{{foo|} }}',
     '<root><template><title>foo</title><part><name index="1" /><value>} </value></part></templa'
     'te></root>'),
    ('{{foo|bar=|}',
     '<root>{{foo|bar=|}</root>'),
    ('{{Foo|} Bar=',
     '<root>{{Foo|} Bar=</root>'),
    ('{{Foo|} Bar=}}',
     '<root><template><title>Foo</title><part><name>} Bar</name>=<value></value></part></templat'
     'e></root>'),
]

# PreprocessorTest::provideHeadings(): tests from T30642 (https://phabricator.wikimedia.org/T30642)
HEADINGS = [
    # These should become headings:
    ('== h ==<!--c1-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment></h></root>'),
    ('== h == \t<!--c1-->',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment></h></root>'),
    ('== h ==<!--c1--> \t',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment> \t</h></root>'),
    ('== h == \t<!--c1--> \t',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment> \t</h></root>'),
    ('== h ==<!--c1--><!--c2-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment></h></root>'),
    ('== h == \t<!--c1--><!--c2-->',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment></h></root>'),
    ('== h ==<!--c1--><!--c2--> \t',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment> \t</h></root>'),
    ('== h == \t<!--c1--><!--c2--> \t',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment> \t</h></root>'),
    ('== h == \t<!--c1-->  <!--c2-->',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment></h></root>'),
    ('== h ==<!--c1-->  <!--c2--> \t',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--&g'
     't;</comment> \t</h></root>'),
    ('== h == \t<!--c1-->  <!--c2--> \t',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment> \t</h></root>'),
    ('== h ==<!--c1--><!--c2--><!--c3-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment><comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==<!--c1-->  <!--c2--><!--c3-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--&g'
     't;</comment><comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==<!--c1--><!--c2-->  <!--c3-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment>  <comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==<!--c1-->  <!--c2-->  <!--c3-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--&g'
     't;</comment>  <comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==  <!--c1--><!--c2--><!--c3-->',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment><comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==  <!--c1-->  <!--c2--><!--c3-->',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment><comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==  <!--c1--><!--c2-->  <!--c3-->',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment>  <comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==  <!--c1-->  <!--c2-->  <!--c3-->',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment>  <comment>&lt;!--c3--&gt;</comment></h></root>'),
    ('== h ==<!--c1--><!--c2--><!--c3-->  ',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment><comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==<!--c1-->  <!--c2--><!--c3-->  ',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--&g'
     't;</comment><comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==<!--c1--><!--c2-->  <!--c3-->  ',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;'
     '</comment>  <comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==<!--c1-->  <!--c2-->  <!--c3-->  ',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--&g'
     't;</comment>  <comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==  <!--c1--><!--c2--><!--c3-->  ',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment><comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==  <!--c1-->  <!--c2--><!--c3-->  ',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment><comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==  <!--c1--><!--c2-->  <!--c3-->  ',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&g'
     't;</comment>  <comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==  <!--c1-->  <!--c2-->  <!--c3-->  ',
     '<root><h level="2" i="1">== h ==  <comment>&lt;!--c1--&gt;</comment>  <comment>&lt;!--c2--'
     '&gt;</comment>  <comment>&lt;!--c3--&gt;</comment>  </h></root>'),
    ('== h ==<!--c1--> \t<!--c2-->',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment> \t<comment>&lt;!--c2--&g'
     't;</comment></h></root>'),
    ('== h == \t<!--c1--> \t<!--c2-->',
     '<root><h level="2" i="1">== h == \t<comment>&lt;!--c1--&gt;</comment> \t<comment>&lt;!--c2--'
     '&gt;</comment></h></root>'),
    ('== h ==<!--c1--> \t<!--c2--> \t',
     '<root><h level="2" i="1">== h ==<comment>&lt;!--c1--&gt;</comment> \t<comment>&lt;!--c2--&g'
     't;</comment> \t</h></root>'),
    # These are not working:
    ('== h == x <!--c1--><!--c2--><!--c3-->  ',
     '<root>== h == x <comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;</comment><comme'
     'nt>&lt;!--c3--&gt;</comment>  </root>'),
    ('== h ==<!--c1--> x <!--c2--><!--c3-->  ',
     '<root>== h ==<comment>&lt;!--c1--&gt;</comment> x <comment>&lt;!--c2--&gt;</comment><comme'
     'nt>&lt;!--c3--&gt;</comment>  </root>'),
    ('== h ==<!--c1--><!--c2--><!--c3--> x ',
     '<root>== h ==<comment>&lt;!--c1--&gt;</comment><comment>&lt;!--c2--&gt;</comment><comment>'
     '&lt;!--c3--&gt;</comment> x </root>'),
]


def normalize_xml(xml: str) -> str:
    """Normalize XML string to the form that a DOMDocument saves out (PreprocessorTest::normalizeXml)."""
    # Normalize self-closing tags
    xml = re.sub(r"<([a-z]+)/>", r"<\1></\1>", xml.replace(" />", "/>"))
    # Remove <equals> tags, which only occur in Preprocessor_Hash and have no semantic value
    return re.sub(r"</?equals>", "", xml)


def _trim(s: str) -> str:
    return s.strip(" \t\n\r\0\x0b")


class FakeOutput:
    def __init__(self):
        self.warnings: list[tuple] = []

    def add_warning_msg(self, key: str, *params) -> None:
        self.warnings.append((key, *params))


class FakeParser:
    """The part of the parser the preprocessor and the frames call. Templates come from ``templates`` (name ->
    wikitext); any other template renders as a link "[[name]]"."""

    def __init__(self, ot: str = "html", templates: dict | None = None, config: Config = Config(),
                 title: str = "Page title"):
        self.config = config
        self.ot = {key: key == ot for key in ("html", "wiki", "pre", "plain")}
        self.templates = templates or {}
        self.title = title
        self.strip_state = StripState(self)
        self.pp_node_count = 0
        self.highest_expansion_depth = 0
        self.headings: list = []
        self.output = FakeOutput()
        self.tracking_categories: list[str] = []
        self.limitations: list[tuple] = []
        self.marker_index = 0
        self.preprocessor = Preprocessor(self)

    def get_strip_list(self) -> list[str]:
        return ["gallery", "display map", "/foo"]  # as in PreprocessorTest

    def get_preprocessor(self) -> Preprocessor:
        return self.preprocessor

    def get_title(self) -> str:
        return self.title

    def get_output(self) -> FakeOutput:
        return self.output

    def add_tracking_category(self, msg: str) -> None:
        self.tracking_categories.append(msg)

    def limitation_warn(self, type_: str, current="", max_="") -> None:
        self.limitations.append((type_, current, max_))

    def insert_strip_item(self, text: str) -> str:
        marker = f"{MARKER_PREFIX}-item-{self.marker_index}-{MARKER_SUFFIX}"
        self.marker_index += 1
        self.strip_state.add_general(marker, text)
        return marker

    def expand(self, text: str) -> str:
        """Parser::replaceVariables() without the size check"""
        frame = self.preprocessor.new_frame()
        return frame.expand(self.preprocessor.preprocess_to_obj(text))

    def brace_substitution(self, piece: dict, frame: Frame) -> dict:
        name = _trim(frame.expand(piece["title"]))
        if name not in self.templates:
            return {"text": "[[" + name + "]]"}
        title = "Template:" + name
        if not frame.loop_check(title):
            return {"text": f'<span class="error">Template loop detected: [[{title}]]</span>'}
        dom = self.preprocessor.preprocess_to_obj(self.templates[name], DOM_FOR_INCLUSION)
        return {"text": frame.new_child(piece["parts"], title).expand(dom)}

    def arg_substitution(self, piece: dict, frame: Frame) -> dict:
        """Parser::argSubstitution() without the include size check"""
        parts = piece["parts"]
        name_with_spaces = frame.expand(piece["title"])
        arg_name = _trim(name_with_spaces)
        obj = None
        text = frame.get_argument(arg_name)
        if text is False and parts.get_length() > 0 and (
                self.ot["html"] or self.ot["pre"] or (self.ot["wiki"] and frame.is_template())):
            # No match in frame, use the supplied default
            obj = parts.item(0).get_children()
        if text is False and obj is None:
            # No match anywhere
            obj = frame.virtual_bracketed_implode("{{{", "|", "}}}", name_with_spaces, parts)
        return {"object": obj} if obj is not None else {"text": text}

    def extension_substitution(self, params: dict, frame: Frame, process_nowiki: bool = False) -> str:
        name = frame.expand(params["name"])
        attr = "" if params["attr"] is None else frame.expand(params["attr"])
        inner = "-" if params["inner"] is None else frame.expand(params["inner"])
        return f"[ext {name}|{attr}|{inner}]"


class PreprocessorTreeTest(unittest.TestCase):
    """PreprocessorTest: wikitext -> tree, compared as XML"""

    def setUp(self):
        self.preprocessor = FakeParser().preprocessor

    def preprocess_to_xml(self, wikitext: str) -> str:
        return normalize_xml(str(self.preprocessor.preprocess_to_obj(wikitext)))

    def test_preprocessor_output(self):
        for wikitext, expected in CASES:
            with self.subTest(wikitext=wikitext):
                self.assertEqual(normalize_xml(expected), self.preprocess_to_xml(wikitext))

    def test_headings(self):
        for wikitext, expected in HEADINGS:
            with self.subTest(wikitext=wikitext):
                self.assertEqual(normalize_xml(expected), self.preprocess_to_xml(wikitext))

    def test_preprocessor_output_files(self):
        files = sorted(PREPROCESS_DIR.glob("*.txt"))
        self.assertTrue(files, f"no test files in {PREPROCESS_DIR}")
        for path in files:
            with self.subTest(file=path.name):
                wikitext = path.read_text(encoding="utf-8")
                expected = path.with_suffix(".expected").read_text(encoding="utf-8")
                self.assertEqual(normalize_xml(expected), self.preprocess_to_xml(wikitext))

    def test_recover_orig_gives_back_the_text(self):
        """Expanding with RECOVER_ORIG reproduces the source, as extractSections() relies on."""
        extra = ["-{a|{{b}}}-", "-{{{x}}}-", "-{{T}}-", "-{{{{T}}}}-", "{{a|b=c|d}}", "[[a|{{b}}]]",
                 "<includeonly>x</includeonly>y", "<noinclude>x", "a<onlyinclude>b</onlyinclude>c",
                 "== a ==\n<gallery>\n</gallery>\n<!-- c -->\n== b ==", "{{a\n== h ==\n}}", "==a{{b"]
        texts = [text for text, _ in CASES + HEADINGS] + extra
        texts += [path.read_text(encoding="utf-8") for path in sorted(PREPROCESS_DIR.glob("*.txt"))]
        for flags in (0, DOM_FOR_INCLUSION, DOM_LANG_CONVERSION_DISABLED):
            parser = FakeParser(ot="pre")
            frame = parser.preprocessor.new_frame()
            for text in texts:
                with self.subTest(text=text[:60], flags=flags):
                    dom = parser.preprocessor.preprocess_to_obj(text, flags)
                    self.assertEqual(text, frame.expand(dom, RECOVER_ORIG))

    def test_inclusion(self):
        xml = self.preprocess_to_xml("a<noinclude>b</noinclude><includeonly>c</includeonly>")
        self.assertEqual("<root>a<ignore>&lt;noinclude&gt;</ignore>b<ignore>&lt;/noinclude&gt;</ignore>"
                         "<ignore>&lt;includeonly&gt;c&lt;/includeonly&gt;</ignore></root>", xml)
        dom = self.preprocessor.preprocess_to_obj("a<noinclude>b</noinclude><includeonly>c</includeonly>",
                                                  DOM_FOR_INCLUSION)
        self.assertEqual("<root>a<ignore>&lt;noinclude&gt;b&lt;/noinclude&gt;</ignore>"
                         "<ignore>&lt;includeonly&gt;</ignore>c<ignore>&lt;/includeonly&gt;</ignore></root>",
                         str(dom))
        dom = self.preprocessor.preprocess_to_obj("a<onlyinclude>b</onlyinclude>c", DOM_FOR_INCLUSION)
        self.assertEqual("<root><ignore>a&lt;onlyinclude&gt;</ignore>b<ignore>&lt;/onlyinclude&gt;c</ignore></root>",
                         str(dom))

    def test_language_conversion(self):
        self.assertEqual("<root>-{a}-</root>", self.preprocess_to_xml("-{a}-"))
        # -{ => {{ transition because rightmost wins
        self.assertEqual("<root>-<template><title>a</title></template>-</root>", self.preprocess_to_xml("-{{a}}-"))
        self.assertEqual("<root>-<tplarg><title>a</title></tplarg>-</root>", self.preprocess_to_xml("-{{{a}}}-"))
        self.assertEqual("<root>-{ <template><title>a</title></template> }-</root>",
                         self.preprocess_to_xml("-{ {{a}} }-"))
        # Inside -{ }- an equals sign does not name a template argument, unless -{ }- is disabled
        self.assertEqual('<root><template><title>T</title><part><name index="1"/><value>-{a=b}-</value></part>'
                         "</template></root>", self.preprocess_to_xml("{{T|-{a=b}-}}"))
        disabled = str(self.preprocessor.preprocess_to_obj("{{T|-{a=b}-}}", DOM_LANG_CONVERSION_DISABLED))
        self.assertEqual("<root><template><title>T</title><part><name>-{a</name><equals>=</equals><value>b}-</value>"
                         "</part></template></root>", disabled)


class NodeTest(unittest.TestCase):
    def setUp(self):
        self.preprocessor = FakeParser().preprocessor

    def test_navigation(self):
        root = self.preprocessor.preprocess_to_obj("a{{T|x|k=v}}b")
        self.assertEqual("root", root.get_name())
        first = root.get_first_child()
        self.assertIsInstance(first, PPNode_Hash_Text)
        self.assertEqual("a", first.value)
        template = first.get_next_sibling()
        self.assertEqual("template", template.get_name())
        self.assertEqual("b", template.get_next_sibling().value)
        self.assertIsNone(template.get_next_sibling().get_next_sibling())
        self.assertEqual(3, root.get_children().get_length())
        self.assertEqual(2, template.get_children_of_type("part").get_length())

        bits = template.split_template()
        self.assertEqual("", bits["lineStart"])
        self.assertEqual("<title>T</title>", str(bits["title"]))
        parts = bits["parts"]
        self.assertIsInstance(parts, PPNode_Hash_Array)
        arg = parts.item(0).split_arg()
        self.assertEqual(1, arg["index"])
        self.assertEqual("<value>x</value>", str(arg["value"]))
        arg = parts.item(1).split_arg()
        self.assertEqual("", arg["index"])
        self.assertEqual("<name>k</name>", str(arg["name"]))

    def test_heading_and_ext(self):
        root = self.preprocessor.preprocess_to_obj("== a ==\n<gallery x>y</gallery>")
        heading = root.get_first_child()
        self.assertEqual({"i": 1, "level": 2}, heading.split_heading())
        level = heading.get_first_child()
        self.assertIsInstance(level, PPNode_Hash_Attr)
        self.assertEqual(("level", 2), (level.name, level.value))
        ext = heading.get_next_sibling().get_next_sibling()
        bits = ext.split_ext()
        self.assertEqual(["name", "attr", "inner", "close"], list(bits))
        self.assertEqual(" x", bits["attr"].get_first_child().value)
        with self.assertRaises(MWException):
            ext.split_heading()
        with self.assertRaises(MWException):
            heading.get_next_sibling().split_arg()

    def test_new_part_node_array(self):
        nodes = self.preprocessor.new_part_node_array({1: "a", "2": "b", "k": "v"})
        self.assertEqual(['<part><name index="1"/><value>a</value></part>',
                          '<part><name index="2"/><value>b</value></part>',
                          "<part><name>k</name>=<value>v</value></part>"], [str(node) for node in nodes.value])


class FrameTest(unittest.TestCase):
    def test_templates_and_arguments(self):
        parser = FakeParser(templates={"T": "{{{1}}}-{{{x}}}-{{{y|def}}}-{{{2|}}}-{{{3}}}"})
        self.assertEqual("a-b-def--{{{3}}}", parser.expand("{{T|a|x= b }}"))
        self.assertEqual(" a -b-def--{{{3}}}", parser.expand("{{T| a |x=b<!-- c -->}}"))
        self.assertEqual("[[Foo]] [[Bar]]", parser.expand("{{Foo}} {{ {{{1| Bar }}} }}"))
        self.assertEqual("{{{1}}} d", parser.expand("{{{1}}} {{{1|d}}}"))

    def test_duplicate_arguments(self):
        parser = FakeParser(templates={"T": "{{{1}}}"})
        self.assertEqual("b", parser.expand("{{T|a|1=b}}"))
        self.assertEqual([("duplicate-args-warning", "Page title", "Template:T", 1)], parser.output.warnings)
        self.assertEqual(["duplicate-args-category"], parser.tracking_categories)

    def test_inclusion(self):
        parser = FakeParser(templates={"U": "a<noinclude>b</noinclude><includeonly>c</includeonly>",
                                       "V": "x<onlyinclude>y</onlyinclude>z<onlyinclude>w</onlyinclude>"})
        self.assertEqual("ac|yw", parser.expand("{{U}}|{{V}}"))
        self.assertEqual("ab", parser.expand("a<noinclude>b</noinclude><includeonly>c</includeonly>"))

    def test_loop_check(self):
        parser = FakeParser(templates={"L": "x{{M}}", "M": "{{L}}"})
        self.assertEqual('x<span class="error">Template loop detected: [[Template:L]]</span>', parser.expand("{{L}}"))

    def test_comments(self):
        self.assertEqual("ab", FakeParser().expand("a<!-- c -->b"))
        parser = FakeParser(ot="wiki")
        out = parser.expand("a<!-- c -->b")
        self.assertEqual(f"a{MARKER_PREFIX}-item-0-{MARKER_SUFFIX}b", out)
        self.assertEqual("a<!-- c -->b", parser.strip_state.unstrip_general(out))

    def test_extension_tags(self):
        parser = FakeParser()
        self.assertEqual("[ext gallery| x=1|y][ext gallery||-]", parser.expand("<gallery x=1>y</gallery><gallery/>"))
        frame = parser.preprocessor.new_frame()
        text = "<gallery x=1>y</gallery ><gallery/>"
        self.assertEqual(text, frame.expand(parser.preprocessor.preprocess_to_obj(text), NO_TAGS))

    def test_no_templates(self):
        parser = FakeParser()
        frame = parser.preprocessor.new_frame()
        dom = parser.preprocessor.preprocess_to_obj("{{Foo|bar|x=y}} {{{1}}}")
        self.assertEqual("{{Foo|bar|x=y}} {{{1}}}", frame.expand(dom, NO_TEMPLATES))

    def test_headings(self):
        parser = FakeParser()
        out = parser.expand("== A ==\ntext\n=== B ===")
        marker0 = f"{MARKER_PREFIX}-h-0-{MARKER_SUFFIX}"
        marker1 = f"{MARKER_PREFIX}-h-1-{MARKER_SUFFIX}"
        self.assertEqual(f"=={marker0} A ==\ntext\n==={marker1} B ===", out)
        self.assertEqual([["Page_title", 1], ["Page_title", 2]], parser.headings)
        self.assertEqual("== A ==\ntext\n=== B ===", parser.strip_state.unstrip_general(out))
        # Not in HTML mode: just the text
        self.assertEqual("== A ==", FakeParser(ot="pre").expand("== A =="))

    def test_node_count_limit(self):
        parser = FakeParser(config=Config(max_pp_node_count=3))
        out = parser.expand("{{a}}{{b}}{{c}}{{d}}")
        self.assertIn('<span class="error">Node-count limit exceeded</span>', out)
        self.assertEqual("node-count-exceeded", parser.limitations[0][0])

    def test_expansion_depth_limit(self):
        parser = FakeParser(templates={"N": "<{{{1}}}>"}, config=Config(max_pp_expand_depth=5))
        out = parser.expand("{{N|{{N|{{N|{{N|{{N|{{N|x}}}}}}}}}}}}")
        self.assertIn('<span class="error">Expansion depth limit exceeded</span>', out)
        self.assertEqual("expansion-depth-exceeded", parser.limitations[0][0])
        self.assertEqual(0, Frame._expansion_depth)

    def test_template_frame(self):
        parser = FakeParser()
        pp = parser.preprocessor
        frame = pp.new_frame()
        self.assertFalse(frame.is_template())
        self.assertTrue(frame.is_empty())
        self.assertEqual("frame{}", str(frame))
        child = frame.new_child(pp.new_part_node_array({1: " a ", "k": " v "}), "Template:X")
        self.assertIsInstance(child, TemplateFrame)
        self.assertTrue(child.is_template())
        self.assertFalse(child.is_empty())
        self.assertEqual(" a ", child.get_argument("1"))
        self.assertEqual("v", child.get_argument("k"))
        self.assertIs(False, child.get_argument("missing"))
        self.assertEqual({1: " a ", "k": "v"}, child.get_arguments())
        self.assertEqual({1: " a "}, child.get_numbered_arguments())
        self.assertEqual({"k": "v"}, child.get_named_arguments())
        self.assertFalse(child.loop_check("Template:X"))
        self.assertTrue(frame.loop_check("Template:X"))
        self.assertEqual(["Page_title", "Template:X"], child.title_cache)
        self.assertEqual("Template:X", child.get_pdbk())
        self.assertEqual("Page_title", child.get_pdbk(0))
        self.assertEqual(1, child.depth)
        child.set_volatile()
        self.assertTrue(frame.is_volatile())
        child.set_ttl(10)
        self.assertEqual(10, frame.get_ttl())

    def test_custom_frame(self):
        parser = FakeParser()
        frame = parser.preprocessor.new_custom_frame({"1": "a", "k": "v"})
        self.assertIsInstance(frame, CustomFrame)
        self.assertEqual("a", frame.get_argument(1))
        self.assertEqual("v", frame.get_argument("k"))
        self.assertIs(False, frame.get_argument("x"))
        self.assertFalse(frame.is_empty())
        self.assertEqual('cstmframe{"1":"a", "k":"v"}', str(frame))

    def test_implode(self):
        parser = FakeParser()
        frame = parser.preprocessor.new_frame()
        root = parser.preprocessor.preprocess_to_obj("{{T|a|b}}")
        parts = root.get_first_child().split_template()["parts"]
        values = [part.split_arg()["value"] for part in parts.value]
        self.assertEqual("a, b", frame.implode(", ", *values))
        self.assertEqual("x|a|b", frame.implode("|", "x", PPNode_Hash_Array(values)))
        self.assertEqual("(a;b)", frame.expand(frame.virtual_bracketed_implode("(", ";", ")", values)))
        self.assertEqual("a;b", frame.expand(frame.virtual_implode(";", values)))

    def test_tree_from_list_of_children(self):
        tree = PPNode_Hash_Tree([["root", ["a", ["b", ["c"]]]]], 0)
        self.assertEqual("<root>a<b>c</b></root>", str(tree))
        self.assertEqual("ac", FakeParser().preprocessor.new_frame().expand(tree))


if __name__ == "__main__":
    unittest.main()
